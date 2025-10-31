# Platform Schema Definition - Infrastructure Comparison

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion

---

## 🎯 TL;DR - The Key Difference

**Jobs & Tasks:**
- ✅ **Pydantic models ARE the schema** (Infrastructure-as-Code)
- ✅ Schema auto-generated from Pydantic field types
- ✅ Single source of truth: `core/models/job.py` and `core/models/task.py`

**Platform:**
- ❌ **Hardcoded DDL in schema deployer** (NOT Infrastructure-as-Code)
- ❌ Schema manually written in `triggers/schema_pydantic_deploy.py`
- ⚠️ Potential drift between `PlatformRecord` Pydantic model and actual database schema

---

## 📊 Side-by-Side Comparison

### Jobs & Tasks (✅ Infrastructure-as-Code Pattern)

**Step 1: Define Pydantic Model**
```python
# core/models/job.py
class JobRecord(JobData):
    """Database representation of a job."""
    job_id: str = Field(..., max_length=64)
    job_type: str = Field(..., max_length=100)
    status: JobStatus = Field(default=JobStatus.PENDING)
    stage: int = Field(default=1)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 2: Schema Auto-Generated**
```python
# core/schema/sql_generator.py
class PydanticToSQL:
    """Convert Pydantic models to PostgreSQL DDL."""

    TYPE_MAP = {
        str: "VARCHAR",
        int: "INTEGER",
        datetime: "TIMESTAMP",
        dict: "JSONB",
        Dict: "JSONB",
    }

    def generate_create_table(self, model: Type[BaseModel]) -> sql.Composed:
        """Generate CREATE TABLE from Pydantic model fields."""
        # Introspects JobRecord, generates DDL automatically
        # - Reads field types → PostgreSQL types
        # - Reads Field(..., max_length=64) → VARCHAR(64)
        # - Reads Enum → CREATE TYPE enum
        # - Reads Optional → NULL/NOT NULL
```

**Step 3: Deployment**
```python
# triggers/schema_pydantic_deploy.py
from core.models import JobRecord, TaskRecord
from core.schema.sql_generator import PydanticToSQL

generator = PydanticToSQL(schema_name="app")
generator.generate_schema([JobRecord, TaskRecord])
# ✅ Tables created automatically from Pydantic definitions
```

**Result:**
```sql
CREATE TABLE app.jobs (
    job_id VARCHAR(64) PRIMARY KEY,      -- From Field(..., max_length=64)
    job_type VARCHAR(100) NOT NULL,      -- From Field(..., max_length=100)
    status app.job_status_enum NOT NULL, -- From JobStatus Enum
    stage INTEGER DEFAULT 1,             -- From Field(default=1)
    parameters JSONB DEFAULT '{}'::jsonb,-- From Dict[str, Any]
    metadata JSONB DEFAULT '{}'::jsonb,  -- From Dict[str, Any]
    result_data JSONB,                   -- From Optional[Dict]
    error_details TEXT,                  -- From Optional[str]
    created_at TIMESTAMPTZ DEFAULT NOW(),-- From datetime
    updated_at TIMESTAMPTZ DEFAULT NOW() -- From datetime
);
```

**✅ Benefits:**
- Schema **always** matches Pydantic model
- Change field type in Python → Schema updates automatically
- Add new field in Python → Schema updates automatically
- Single source of truth (Pydantic model)
- Zero drift between code and database

---

### Platform (❌ Manual DDL Pattern)

**Step 1: Define Pydantic Model**
```python
# triggers/trigger_platform.py
class PlatformRecord(BaseModel):
    """Platform request database record."""
    request_id: str = Field(..., description="SHA256 hash (32 chars)")
    dataset_id: str
    resource_id: str
    version_id: str
    data_type: str
    status: PlatformRequestStatus = Field(default=PlatformRequestStatus.PENDING)
    job_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result_data: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 2: Schema Manually Written**
```python
# triggers/schema_pydantic_deploy.py (lines 362-415)
# ⚠️ HARDCODED DDL - NOT GENERATED FROM PYDANTIC

platform_schema_statements = [
    sql.SQL("""
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            request_id VARCHAR(32) PRIMARY KEY,  -- ⚠️ Hardcoded
            dataset_id VARCHAR(255) NOT NULL,     -- ⚠️ Hardcoded
            resource_id VARCHAR(255) NOT NULL,    -- ⚠️ Hardcoded
            version_id VARCHAR(50) NOT NULL,      -- ⚠️ Hardcoded
            data_type VARCHAR(50) NOT NULL,       -- ⚠️ Hardcoded
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            parameters JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            result_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """).format(
        schema=sql.Identifier("app"),
        table=sql.Identifier("platform_requests")
    ),
]
```

**Step 3: Deployment**
```python
# triggers/schema_pydantic_deploy.py
# ⚠️ Manual execution of hardcoded DDL
for platform_stmt in platform_schema_statements:
    cur.execute(platform_stmt)
```

**❌ Problems:**

1. **Drift Risk**: If someone updates `PlatformRecord` but forgets to update DDL
2. **Manual Maintenance**: Every schema change requires updating DDL by hand
3. **No Validation**: No automatic check that DDL matches Pydantic model
4. **Inconsistency**: Different pattern from Jobs/Tasks
5. **Error-Prone**: Easy to miss field length changes or type updates

**Example Drift Scenario:**
```python
# Developer updates Pydantic model
class PlatformRecord(BaseModel):
    request_id: str = Field(..., max_length=64)  # Changed 32→64
    dataset_id: str = Field(..., max_length=500) # Changed 255→500
    new_field: Optional[str] = None              # Added new field

# ❌ Database schema NOT automatically updated!
# Developer must remember to:
# 1. Update schema_pydantic_deploy.py DDL
# 2. Update any indexes
# 3. Run migration
# 4. Test everything

# With Infrastructure-as-Code pattern:
# ✅ Just redeploy schema - it auto-updates from Pydantic!
```

---

## 🔍 Why the Difference?

### Historical Context

**Jobs & Tasks:**
- Core workflow system designed from start with Infrastructure-as-Code
- Built `PydanticToSQL` generator specifically for this
- Went through multiple iterations to perfect the pattern

**Platform:**
- Added later (26 OCT 2025) as orchestration layer
- Quick implementation to get Platform working
- Used manual DDL as "temporary" approach
- Never migrated to Infrastructure-as-Code pattern

### Current State

| Aspect | Jobs/Tasks | Platform |
|--------|-----------|----------|
| **Schema Definition** | Pydantic model | Manual DDL |
| **Schema Generation** | Automatic | Manual |
| **Drift Prevention** | Built-in | Manual vigilance |
| **Maintenance** | Update model only | Update model + DDL |
| **Pattern Consistency** | CoreMachine standard | Different approach |
| **Lines of Code** | ~50 (model only) | ~50 model + ~60 DDL |

---

## 🚨 Risks of Current Platform Approach

### Risk 1: Schema Drift

**Scenario:**
```python
# Someone updates PlatformRecord
class PlatformRecord(BaseModel):
    request_id: str = Field(..., max_length=64)  # Increased from 32

# But forgets to update DDL in schema_pydantic_deploy.py
CREATE TABLE app.platform_requests (
    request_id VARCHAR(32) PRIMARY KEY  -- ❌ Still 32!
)

# Result: Runtime errors on long request IDs
```

### Risk 2: Missing Fields

**Scenario:**
```python
# Add new field to PlatformRecord
class PlatformRecord(BaseModel):
    priority: int = Field(default=5)

# Forget to add to DDL
# Result: Field exists in code but not in database
# Repository saves → PostgreSQL ignores unknown field
# Data loss without errors!
```

### Risk 3: Type Mismatches

**Scenario:**
```python
# Change type in Pydantic
class PlatformRecord(BaseModel):
    metadata: List[Dict[str, Any]]  # Changed from Dict

# DDL not updated
CREATE TABLE ... (
    metadata JSONB  -- Works for both, but semantic difference
)

# Result: Code expects list, database allows object
# No error, but data structure inconsistency
```

### Risk 4: Index Maintenance

**Scenario:**
```python
# Remove field from Pydantic
class PlatformRecord(BaseModel):
    # Removed: old_field: str

# DDL still has column + index
CREATE INDEX idx_platform_old_field ON ...

# Result: Unused column and index waste space
# Performance impact on inserts
```

---

## ✅ Recommended Solution: Migrate Platform to Infrastructure-as-Code

### Phase 1: Create PlatformRecord in core/models/platform.py

```python
# core/models/platform.py (NEW FILE)
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

class PlatformRequestStatus(str, Enum):
    """Platform request status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class PlatformRecord(BaseModel):
    """
    Platform request database record.

    This is the SINGLE SOURCE OF TRUTH for the platform_requests table schema.
    The database schema is auto-generated from these field definitions.
    """
    request_id: str = Field(..., max_length=32, description="SHA256 hash of identifiers")
    dataset_id: str = Field(..., max_length=255)
    resource_id: str = Field(..., max_length=255)
    version_id: str = Field(..., max_length=50)
    data_type: str = Field(..., max_length=50)
    status: PlatformRequestStatus = Field(default=PlatformRequestStatus.PENDING)
    job_ids: List[str] = Field(default_factory=list, description="CoreMachine job IDs")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result_data: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class PlatformRequestJobMapping(BaseModel):
    """
    Mapping table between Platform requests and CoreMachine jobs.

    Auto-generated table schema from these field definitions.
    """
    request_id: str = Field(..., max_length=32)
    job_id: str = Field(..., max_length=64)
    job_type: str = Field(..., max_length=100)
    sequence: int = Field(default=1)
    status: str = Field(default="pending", max_length=20)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Phase 2: Update Schema Generator

```python
# triggers/schema_pydantic_deploy.py
from core.models import JobRecord, TaskRecord
from core.models.platform import PlatformRecord, PlatformRequestJobMapping  # NEW
from core.schema.sql_generator import PydanticToSQL

def _deploy_schema_handler(self, req: func.HttpRequest) -> func.HttpResponse:
    """Deploy schema from Pydantic models."""

    # Generate schema from ALL models
    generator = PydanticToSQL(schema_name="app")
    generator.generate_schema([
        JobRecord,
        TaskRecord,
        PlatformRecord,                # ✅ Auto-generate Platform tables
        PlatformRequestJobMapping      # ✅ Auto-generate mapping table
    ])

    # No more manual DDL for Platform!
```

### Phase 3: Remove Manual DDL

```python
# triggers/schema_pydantic_deploy.py (lines 356-427)
# ❌ DELETE this entire section - no longer needed!
# Platform tables now auto-generated from Pydantic models

# Before: 60+ lines of manual DDL
# After: 0 lines - all automatic!
```

### Phase 4: Update Imports

```python
# triggers/trigger_platform.py
# BEFORE
class PlatformRecord(BaseModel):
    """Defined inline in trigger file"""
    ...

# AFTER
from core.models.platform import PlatformRecord, PlatformRequestStatus

# Repository and triggers now import from core/models
# Single source of truth
```

---

## 📊 Benefits of Migration

| Benefit | Impact |
|---------|--------|
| **Zero Drift** | Schema always matches Pydantic model |
| **Consistency** | Same pattern as Jobs/Tasks |
| **Maintainability** | Update model once, schema updates automatically |
| **Type Safety** | Field constraints enforced in DDL |
| **Reduced LOC** | Remove 60+ lines of manual DDL |
| **Better Validation** | Pydantic validation + PostgreSQL constraints |
| **Documentation** | Field descriptions become COMMENT ON COLUMN |

---

## 🎯 Current Status Summary

### What We Have Now (29 OCT 2025)

**✅ Working:**
- Platform tables correctly defined in `app` schema
- SQL composition for injection safety
- Repository inheritance from PostgreSQLRepository
- All CRUD operations working

**⚠️ Technical Debt:**
- Platform schema is **NOT Infrastructure-as-Code**
- Manual DDL maintenance required
- Risk of drift between Pydantic model and database
- Inconsistent with Jobs/Tasks pattern

**🔧 Recommendation:**
Migrate Platform to Infrastructure-as-Code pattern when time permits. This is **P2 priority** - system works, but migration improves maintainability.

---

## 📝 Migration Effort Estimate

**Phase 1-4 Total:** ~3-4 hours

- **Phase 1**: Create `core/models/platform.py` (1 hour)
  - Move `PlatformRecord` and related models
  - Add proper Field constraints (max_length, etc.)
  - Add comprehensive docstrings

- **Phase 2**: Update schema generator (30 minutes)
  - Add Platform models to generation list
  - Test schema generation locally

- **Phase 3**: Remove manual DDL (30 minutes)
  - Delete hardcoded DDL from schema_pydantic_deploy.py
  - Update comments and documentation

- **Phase 4**: Update imports (1 hour)
  - Fix imports in trigger_platform.py
  - Fix imports in infrastructure/platform.py
  - Test all endpoints

- **Testing & Validation**: (1 hour)
  - Deploy to Azure
  - Run schema redeploy
  - Verify tables created correctly
  - Test Platform endpoints

---

## 🚀 Immediate Action Items

**For Current Deployment:**
- ✅ Platform tables work with current manual DDL
- ✅ No blocking issues for deployment
- ✅ Can proceed with testing

**For Future Improvement (P2 Priority):**
- [ ] Create `core/models/platform.py`
- [ ] Add Platform models to schema generator
- [ ] Remove manual DDL from schema deployer
- [ ] Update imports throughout codebase
- [ ] Document migration in HISTORY.md

---

## 🎓 Key Takeaway

**Jobs & Tasks use Infrastructure-as-Code:**
```
Pydantic Model → PydanticToSQL → PostgreSQL DDL
(Single Source of Truth)
```

**Platform currently uses manual DDL:**
```
Pydantic Model (code validation)
     +
Manual DDL (database schema)
(Two sources of truth - drift risk!)
```

**Recommended:**
```
Migrate Platform to Infrastructure-as-Code pattern
for consistency and zero-drift guarantee.
```

---

**Document Version:** 1.0
**Last Updated:** 29 OCT 2025
**Next Review:** After Platform deployment testing
