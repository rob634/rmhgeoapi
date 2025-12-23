# DATA_MODEL.md - Infrastructure as Code Reference

**Created**: 23 DEC 2025
**Last Updated**: 23 DEC 2025
**Principle**: All data contracts enforced by Pydantic. All dynamic SQL uses psycopg.SQL composition.

---

## Core Principle: Infrastructure as Code

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SINGLE SOURCE OF TRUTH                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  Pydantic Models  ──────►  SQL DDL Generation  ──────►  Database Schema     │
│  (Python)                  (psycopg.SQL)                (PostgreSQL)         │
├─────────────────────────────────────────────────────────────────────────────┤
│  Pydantic Models  ──────►  JSON Serialization  ──────►  Queue Messages      │
│  (Python)                  (model_dump_json)            (Service Bus)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Rules:**
1. Pydantic models are the source of truth for data structure
2. Dynamic SQL MUST use `psycopg.sql.SQL()` + `sql.Identifier()` for identifiers
3. No f-string interpolation of table/column names in executed SQL
4. Static DDL is acceptable in schema files (controlled code)

---

## Part 1: Pydantic Model Architecture

### 1.1 Core Contract Hierarchy

```
core/contracts/__init__.py
├── TaskData (Base)           ─────► task_id, parent_job_id, job_type, task_type, stage, parameters
└── JobData (Base)            ─────► job_id (SHA256), job_type, parameters

core/models/
├── TaskRecord(TaskData)      ─────► + status, result_data, timestamps, target_queue, executed_by
├── JobRecord(JobData)        ─────► + status, stage, total_stages, timestamps, result_data
└── TaskDefinition            ─────► Lightweight task creation model

core/schema/queue.py
├── TaskQueueMessage(TaskData) ────► + retry_count, timestamp, parent_task_id
├── JobQueueMessage(JobData)   ────► + stage, stage_results, retry_count, correlation_id
└── StageCompleteMessage       ────► Multi-app stage completion signal
```

### 1.2 Boundary Specializations

| Boundary | Base | Specialized Model | Added Fields |
|----------|------|-------------------|--------------|
| **Database** | TaskData | TaskRecord | status, result_data, timestamps, target_queue |
| **Database** | JobData | JobRecord | status, stage, total_stages, result_data |
| **Queue** | TaskData | TaskQueueMessage | retry_count, timestamp, parent_task_id |
| **Queue** | JobData | JobQueueMessage | stage, stage_results, correlation_id |

### 1.3 STAC Namespace Models

```
core/models/stac.py
├── PlatformProperties         ────► platform:dataset_id, platform:resource_id, etc.
├── AppProperties              ────► app:job_id, app:job_type, app:created_by
├── GeoProperties              ────► geo:iso3, geo:primary_iso3, geo:countries
├── AzureProperties            ────► azure:container, azure:blob_path, azure:tier
├── PostGISProperties          ────► postgis:schema, postgis:table, postgis:row_count
└── STACItemProperties         ────► Composite with to_flat_dict() serialization
```

### 1.4 Domain-Specific Result Models

```
core/models/results.py
├── TaskResult                 ────► Task execution result
├── TaskCompletionResult       ────► SQL function return contract
├── StageResultContract        ────► Stage result structure
├── JobCompletionResult        ────► Job completion tracking
├── ProcessVectorStage1Data    ────► GAP-006 fix: Stage 1→2 contract
└── ProcessVectorStage2Result  ────► Stage 2 upload result
```

### 1.5 Validation Patterns

**Strong Field Constraints:**
```python
# SHA256 job_id validation
job_id: str = Field(..., min_length=64, max_length=64)

@field_validator('job_id')
def validate_job_id_format(cls, v: str) -> str:
    if not all(c in '0123456789abcdef' for c in v.lower()):
        raise ValueError("job_id must be hexadecimal")
    return v.lower()
```

**Normalization Validators:**
```python
@field_validator('task_type')
def normalize_task_type(cls, v: str) -> str:
    return v.lower().replace('-', '_')  # Consistent naming
```

**State Transition Validation:**
```python
def can_transition_to(self, new_status: TaskStatus) -> bool:
    # Validates state machine transitions
    if current == TaskStatus.QUEUED and new_status == TaskStatus.PROCESSING:
        return True
    ...
```

---

## Part 2: SQL DDL Patterns

### 2.1 Static DDL (Acceptable)

Static schema definitions in controlled code are acceptable:

```python
# core/schema/sql_generator.py - Generated from Pydantic models
CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS {schema}.jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    job_type VARCHAR(100) NOT NULL,
    status job_status NOT NULL DEFAULT 'queued',
    ...
)
"""
```

### 2.2 Dynamic SQL (MUST use sql.SQL composition)

**CORRECT Pattern:**
```python
from psycopg import sql

# Safe - uses sql.Identifier for all dynamic identifiers
query = sql.SQL("""
    SELECT {columns}
    FROM {schema}.{table}
    WHERE {pk_col} = %s
""").format(
    columns=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
    schema=sql.Identifier(schema_name),
    table=sql.Identifier(table_name),
    pk_col=sql.Identifier(pk_column)
)
cur.execute(query, (pk_value,))
```

**INCORRECT Pattern:**
```python
# DANGEROUS - SQL injection vulnerability
query = f"SELECT * FROM {schema}.{table} WHERE id = %s"
cur.execute(query, (id_value,))
```

### 2.3 Key Files Using Proper sql.SQL Composition

| File | Description | Status |
|------|-------------|--------|
| `infrastructure/h3_repository.py` | H3 grid operations | COMPLIANT |
| `ogc_features/repository.py` | OGC Features API | COMPLIANT |
| `core/schema/geo_table_builder.py` | Dynamic table creation | COMPLIANT |
| `core/schema/sql_generator.py` | Schema DDL generation | COMPLIANT |
| `infrastructure/postgresql.py` | Base repository | COMPLIANT |
| `services/vector/postgis_handler.py` | Vector upload | COMPLIANT |

---

## Part 3: Queue Message Serialization

### 3.1 Serialization Flow

```python
# SENDING (Python → Queue)
task_message = TaskQueueMessage(
    task_id="abc-s1-0",
    parent_job_id="def456...",
    ...
)
message_json = task_message.model_dump_json()  # Pydantic v2 native
queue_repo.send_message("tasks", task_message)

# RECEIVING (Queue → Python)
message_body = msg.get_body().decode('utf-8')
task_message = TaskQueueMessage.model_validate_json(message_body)  # Validates!
```

### 3.2 Key Points

1. **model_dump_json()** - Native Pydantic serialization with proper datetime handling
2. **model_validate_json()** - Validates incoming messages against schema
3. **ConfigDict(validate_assignment=True)** - Validates on attribute assignment
4. **Extra fields** - Some models use `extra="forbid"` to catch schema drift

---

## Part 4: Issues Found

### 4.1 CRITICAL: datetime.utcnow() Deprecation

| File | Line | Current | Fix |
|------|------|---------|-----|
| `core/schema/queue.py` | 49 | `datetime.utcnow` | `datetime.now(timezone.utc)` |
| `core/schema/queue.py` | 189 | `datetime.utcnow` | `datetime.now(timezone.utc)` |
| `core/models/results.py` | 92 | `datetime.utcnow` | `datetime.now(timezone.utc)` |

### 4.2 MEDIUM: Inconsistent ConfigDict Settings

| Model | Setting | Recommendation |
|-------|---------|----------------|
| `TaskQueueMessage` | `validate_assignment=True` | Add `extra="forbid"` |
| `JobQueueMessage` | `validate_assignment=True` | Add `extra="forbid"` |
| `ProcessVectorStage1Data` | `extra="allow"` | Consider `extra="forbid"` |

### 4.3 LOW: f-string SQL in Admin/Debug Code

These are in admin-only endpoints with hardcoded table names (not user input), but should be converted for consistency:

| File | Line | Issue |
|------|------|-------|
| `triggers/admin/h3_debug.py` | 821 | `f"SELECT COUNT(*) FROM h3.{table}"` |
| `triggers/admin/h3_debug.py` | 849 | `f"TRUNCATE TABLE h3.{table}"` |
| `triggers/admin/db_diagnostics.py` | 397 | `f"SELECT ... {schema} ..."` |

**Note**: These use controlled hardcoded values, not user input. They're safe but should use sql.SQL for consistency.

### 4.4 Documentation vs Reality

`core/contracts/__init__.py` docstring mentions:
> TaskQueueMessage(TaskData): Adds transport fields

But `TaskQueueMessage` is in `core/schema/queue.py`, not contracts. Update docstring.

---

## Part 5: Model-to-SQL Mapping

### 5.1 Jobs Table (from JobRecord)

```python
# Pydantic Model (core/models/job.py)
class JobRecord(JobData):
    job_id: str          # → VARCHAR(64) PRIMARY KEY
    job_type: str        # → VARCHAR(100) NOT NULL
    status: JobStatus    # → job_status ENUM
    stage: int           # → INTEGER DEFAULT 1
    parameters: Dict     # → JSONB
    created_at: datetime # → TIMESTAMPTZ
```

```sql
-- Generated DDL (core/schema/sql_generator.py)
CREATE TABLE IF NOT EXISTS app.jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    job_type VARCHAR(100) NOT NULL,
    status job_status NOT NULL DEFAULT 'queued',
    stage INTEGER NOT NULL DEFAULT 1,
    parameters JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.2 Tasks Table (from TaskRecord)

```python
# Pydantic Model (core/models/task.py)
class TaskRecord(TaskData):
    task_id: str           # → VARCHAR(100) PRIMARY KEY
    parent_job_id: str     # → VARCHAR(64) FK
    task_type: str         # → VARCHAR(100)
    status: TaskStatus     # → task_status ENUM
    parameters: Dict       # → JSONB
    result_data: Dict|None # → JSONB
    target_queue: str|None # → VARCHAR(100)
```

```sql
-- Generated DDL
CREATE TABLE IF NOT EXISTS app.tasks (
    task_id VARCHAR(100) PRIMARY KEY,
    parent_job_id VARCHAR(64) NOT NULL REFERENCES app.jobs(job_id),
    task_type VARCHAR(100) NOT NULL,
    status task_status NOT NULL DEFAULT 'pending',
    parameters JSONB NOT NULL DEFAULT '{}',
    result_data JSONB,
    target_queue VARCHAR(100)
);
```

---

## Part 6: Enforcement Checklist

### For New Code

- [ ] Define Pydantic model FIRST
- [ ] Use `sql.SQL()` + `sql.Identifier()` for dynamic table/column names
- [ ] Use parameterized queries (`%s`) for values
- [ ] Add field constraints (min_length, max_length, ge, le)
- [ ] Add validators for format enforcement
- [ ] Use `extra="forbid"` for boundary contracts
- [ ] Use timezone-aware datetimes

### Code Review Checklist

```bash
# Find f-string SQL (potential violations)
grep -rn 'execute(f"' --include="*.py"
grep -rn 'f".*SELECT.*FROM' --include="*.py"
grep -rn 'f".*INSERT INTO' --include="*.py"

# Verify sql.SQL usage
grep -rn 'sql\.SQL\|sql\.Identifier' --include="*.py" | wc -l
# Should be high (currently 200+ usages)

# Find deprecated datetime.utcnow
grep -rn 'datetime.utcnow' --include="*.py"
```

---

## Part 7: Schema Consistency Audit

### 7.1 Database Schemas Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATABASE SCHEMA ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  app        │ Core orchestration (jobs, tasks, platform tracking)           │
│  h3         │ H3 hexagonal grid OLTP system                                 │
│  geo        │ Dynamic geographic/vector tables                              │
│  pgstac     │ STAC catalog (managed by pypgstac library)                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Schema Deployment Patterns

| Schema | Deployer | Pattern | Source of Truth |
|--------|----------|---------|-----------------|
| **app** | `core/schema/sql_generator.py` | Pydantic → DDL | Pydantic models |
| **h3** | `infrastructure/h3_schema.py` | Dedicated class with sql.SQL | Inline DDL |
| **geo** | `core/schema/geo_table_builder.py` | Dynamic builder | Runtime parameters |
| **pgstac** | pypgstac library | External | External library |

### 7.3 App Schema Tables (Pydantic-Driven)

| Table | Pydantic Model | In sql_generator.py? | Status |
|-------|----------------|----------------------|--------|
| `app.jobs` | `JobRecord` | YES | COMPLIANT |
| `app.tasks` | `TaskRecord` | YES | COMPLIANT |
| `app.api_requests` | `ApiRequest` | YES | COMPLIANT |
| `app.janitor_runs` | `JanitorRun` | YES | COMPLIANT |
| `app.etl_source_files` | `EtlSourceFile` | YES | COMPLIANT |
| `app.unpublish_jobs` | `UnpublishJobRecord` | YES | COMPLIANT |
| `app.curated_datasets` | `CuratedDataset` | YES | COMPLIANT |
| `app.curated_update_log` | `CuratedUpdateLog` | YES | COMPLIANT |
| `app.promoted_datasets` | `PromotedDataset` | YES | COMPLIANT (Fixed 23 DEC 2025) |

### 7.4 H3 Schema Tables (Dedicated Deployer)

| Table | Purpose | Pydantic Model? | sql.SQL? |
|-------|---------|-----------------|----------|
| `h3.cells` | Core H3 geometry (unique per h3_index) | NO | YES |
| `h3.cell_admin0` | Country overlap mapping | NO | YES |
| `h3.cell_admin1` | State/province overlap mapping | NO | YES |
| `h3.dataset_registry` | Raster dataset metadata catalog | NO | YES |
| `h3.zonal_stats` | Raster aggregation (PARTITIONED) | NO | YES |
| `h3.point_stats` | Point-in-polygon counts | NO | YES |
| `h3.batch_progress` | Resumable job tracking | NO | YES |

**Note**: H3 schema uses dedicated `H3SchemaDeployer` class with proper sql.SQL composition. This is acceptable divergence - the deployer is well-structured and self-documenting.

### 7.5 Geo Schema Tables (Dynamic)

| Table | Created By | Pattern |
|-------|------------|---------|
| `geo.*` (dynamic) | `process_vector` job | `GeoTableBuilder` with sql.SQL |
| `geo.table_metadata` | `db_maintenance` | Inline DDL |
| `geo.feature_collection_styles` | `db_maintenance` | Inline DDL |

---

## Part 8: Consolidated Issues List

### 8.1 CRITICAL - ~~Must Fix~~ FIXED

| ID | Category | Issue | File(s) | Status |
|----|----------|-------|---------|--------|
| **C1** | Schema Gap | `app.promoted_datasets` has Pydantic model but NO DDL in sql_generator.py | `core/schema/sql_generator.py` | **FIXED 23 DEC 2025** |
| **C2** | Schema Gap | `SystemRole` enum not in sql_generator.py | `core/schema/sql_generator.py` | **FIXED 23 DEC 2025** |

**Fix Applied (23 DEC 2025):**
```python
# Added to core/schema/sql_generator.py imports:
from ..models.promoted import PromotedDataset, SystemRole  # Promoted datasets (23 DEC 2025)

# Added to generate_composed_statements():
composed.extend(self.generate_enum("system_role", SystemRole))  # Line 1086
composed.append(self.generate_table_composed(PromotedDataset, "promoted_datasets"))  # Line 1102
composed.extend(self.generate_indexes_composed("promoted_datasets", PromotedDataset))  # Line 1113
```

### 8.2 HIGH - Should Fix

| ID | Category | Issue | File(s) | Impact |
|----|----------|-------|---------|--------|
| **H1** | Deprecated API | `datetime.utcnow()` (3 occurrences) | `core/schema/queue.py:49,189`, `core/models/results.py:92` | Python 3.12 deprecation warning |
| **H2** | Deprecated API | `datetime.utcnow()` in H3 deployer | `infrastructure/h3_schema.py:101` | Python 3.12 deprecation warning |

**Fix Pattern:**
```python
# Replace
timestamp: datetime = Field(default_factory=datetime.utcnow)
# With
timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### 8.3 MEDIUM - Recommended

| ID | Category | Issue | File(s) | Impact |
|----|----------|-------|---------|--------|
| **M1** | Pydantic Config | Queue messages lack `extra="forbid"` | `core/schema/queue.py` | Schema drift not caught |
| **M2** | Pydantic Config | `ProcessVectorStage1Data` uses `extra="allow"` | `core/models/results.py` | Accepts unknown fields |
| **M3** | Documentation | Docstring says TaskQueueMessage is in contracts | `core/contracts/__init__.py` | Misleading |

### 8.4 LOW - Nice to Have

| ID | Category | Issue | File(s) | Impact |
|----|----------|-------|---------|--------|
| **L1** | Consistency | f-string SQL in admin endpoints | `triggers/admin/h3_debug.py:821,849` | Safe but inconsistent |
| **L2** | Consistency | f-string SQL in diagnostics | `triggers/admin/db_diagnostics.py:397` | Safe but inconsistent |

**Note**: L1/L2 use hardcoded table names from controlled code, not user input. Safe but should use sql.SQL for consistency.

---

## Part 9: Related Documentation

| Document | Purpose |
|----------|---------|
| `SILENT_ERRORS.md` | Exception handling violations (14 total, 6 remaining) |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | Full architecture details |
| `core/schema/sql_generator.py` | DDL generation from Pydantic models |
| `core/schema/deployer.py` | App schema deployment |
| `infrastructure/h3_schema.py` | H3 schema deployment |

---

## Part 10: Summary

### Issue Counts

| Priority | Count | Fixed | Remaining |
|----------|-------|-------|-----------|
| CRITICAL | 2 | 2 | 0 |
| HIGH | 4 | 0 | 4 |
| MEDIUM | 3 | 0 | 3 |
| LOW | 2 | 0 | 2 |
| **TOTAL** | **11** | **2** | **9** |

### Schema Compliance

| Schema | Pydantic-Driven? | sql.SQL Compliant? | Status |
|--------|------------------|-------------------|--------|
| **app** | YES | YES | **100% COMPLIANT** |
| **h3** | NO (dedicated deployer) | YES | ACCEPTABLE DIVERGENCE |
| **geo** | NO (dynamic) | YES | COMPLIANT |
| **pgstac** | N/A (external) | N/A | N/A |

### Overall Assessment

The infrastructure-as-code principle is **well-implemented**:
- All app schema tables now have Pydantic models driving DDL generation (FIXED 23 DEC 2025)
- H3 schema divergence is acceptable - it's a well-structured dedicated deployer
- All dynamic SQL properly uses psycopg.sql composition (200+ usages)
- Remaining issues are deprecation warnings and code quality improvements

### Change Log

| Date | Change | Files |
|------|--------|-------|
| 23 DEC 2025 | Added `PromotedDataset` + `SystemRole` to sql_generator.py | `core/schema/sql_generator.py` |
