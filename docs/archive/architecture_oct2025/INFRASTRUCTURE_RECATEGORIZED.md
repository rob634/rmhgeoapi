# Infrastructure Recategorization - Descriptive Categories

**Date**: 30 SEP 2025
**Purpose**: Replace vague "INFRASTRUCTURE" with clear, descriptive categories

---

## The Problem with "INFRASTRUCTURE"

**Too vague!** 38 files lumped together with no clarity on their actual purpose.

---

## NEW CATEGORIES (Descriptive & Clear)

### 1️⃣ **DATA MODELS - DATABASE ENTITIES** (7 files)
**What**: Pydantic models that map to PostgreSQL tables
**Why separate**: These are your **database schema** - they define table structure

```
core/models/__init__.py
core/models/context.py       - JobExecutionContext (runtime context, not stored)
core/models/enums.py         - JobStatus, TaskStatus (database enums)
core/models/job.py           - JobRecord (maps to `jobs` table)
core/models/task.py          - TaskRecord (maps to `tasks` table)
core/models/results.py       - TaskResult, StageAdvancementResult (database outputs)
```

**Used for**: Creating/reading database records
**Example**:
```python
job_record = JobRecord(
    job_id="abc123",
    job_type="hello_world",
    status=JobStatus.PENDING,  # ← Uses enum
    parameters={"n": 3}
)
db.insert(job_record)  # ← Inserts into PostgreSQL
```

---

### 2️⃣ **SCHEMAS - DATA VALIDATION & TRANSFORMATION** (6 files)
**What**: Pydantic models for **validation, serialization, and business logic**
**Why separate**: These are NOT stored in database - they're for data flow

```
core/schema/__init__.py
core/schema/deployer.py      - Schema deployment configurations
core/schema/orchestration.py - OrchestrationInstruction, FileOrchestrationItem
core/schema/queue.py         - JobQueueMessage, TaskQueueMessage (queue payloads)
core/schema/sql_generator.py - SQL DDL generation models
core/schema/updates.py       - TaskUpdateModel, JobUpdateModel (update operations)
core/schema/workflow.py      - WorkflowDefinition, StageDefinition
```

**Used for**:
- Validating queue messages
- Defining workflows
- Generating SQL
- Update operations

**Example**:
```python
# Schema for queue message (NOT stored in DB)
job_message = JobQueueMessage(
    job_id="abc123",
    job_type="hello_world",
    parameters={"n": 3},
    stage=1,
    correlation_id="xyz"
)
queue.send(job_message.model_dump_json())  # ← Serialized to queue

# Schema for updates (NOT a full record)
update = TaskUpdateModel(
    status=TaskStatus.COMPLETED,
    result_data={"output": "done"}
)
db.update_task(task_id, update)  # ← Partial update
```

---

### 3️⃣ **AZURE RESOURCE REPOSITORIES** (9 files)
**What**: Classes that talk to Azure services (Blob, Queue, Service Bus, etc.)

```
infrastructure/__init__.py
infrastructure/base.py       - BaseRepository ABC
infrastructure/blob.py       - BlobRepository - Azure Blob Storage operations
infrastructure/factory.py    - RepositoryFactory - Creates repository instances
infrastructure/interface_repository.py - Repository interface definitions
infrastructure/jobs_tasks.py - JobsTasksRepository - PostgreSQL jobs/tasks table access
infrastructure/postgresql.py - PostgreSQLRepository - Direct PostgreSQL operations
infrastructure/queue.py      - QueueRepository - Azure Queue Storage operations
infrastructure/service_bus.py - ServiceBusRepository - Azure Service Bus operations
infrastructure/vault.py      - VaultRepository - Azure Key Vault operations
```

**Purpose**: Abstract Azure SDK details from business logic

---

### 4️⃣ **STATE MANAGEMENT & ORCHESTRATION** (4 files)
**What**: Core architectural components that manage job/task lifecycle

```
core/state_manager.py        - StateManager - Database state transitions & advisory locks
core/orchestration_manager.py - OrchestrationManager - Dynamic task creation (fan-out pattern)
core/core_controller.py      - CoreController ABC - Minimal base for controllers
core/__init__.py            - Package exports
```

**Purpose**: Shared architectural components used by both epochs
**Note**: These may evolve as architecture changes (not pure infrastructure)

---

### 5️⃣ **BUSINESS LOGIC HELPERS** (3 files)
**What**: Utility functions for calculations and state transitions

```
core/logic/__init__.py
core/logic/calculations.py   - Helper calculations (job completion %, etc.)
core/logic/transitions.py    - State transition validation logic
```

**Purpose**: Shared business logic used by multiple components

---

### 6️⃣ **HTTP TRIGGER ENDPOINTS** (7 files)
**What**: Azure Functions HTTP triggers - API endpoints
**TODO**: Review each to identify if framework logic needs extraction

```
triggers/__init__.py
triggers/db_query.py         - Database query endpoints (GET /api/db/jobs, /api/db/tasks)
triggers/get_job_status.py   - Job status endpoint (GET /api/jobs/status/{job_id})
triggers/health.py           - Health check (GET /api/health)
triggers/http_base.py        - HTTPTriggerBase ABC - Base class for HTTP triggers
triggers/poison_monitor.py   - Poison queue monitor (GET/POST /api/monitor/poison)
triggers/schema_pydantic_deploy.py - Schema deployment (POST /api/db/schema/redeploy)
triggers/submit_job.py       - Job submission (POST /api/jobs/submit/{job_type})
```

**Action Required**: Audit for framework logic that belongs in CoreMachine

---

### 7️⃣ **CROSS-CUTTING UTILITIES** (3 files)
**What**: Validation and debugging utilities used everywhere

```
utils/__init__.py
utils/contract_validator.py  - Type contract enforcement (@enforce_contract)
utils/import_validator.py    - Startup import validation (fail-fast)
```

**Purpose**: Cross-cutting concerns (validation, diagnostics)

---

## DATA MODELS vs SCHEMAS - The Key Difference

### DATA MODELS (Database Entities)
**Purpose**: Map to PostgreSQL tables 1:1
**Location**: `core/models/`
**Lifecycle**: Created once, read many times, updated occasionally

**Example - JobRecord**:
```python
# core/models/job.py
class JobRecord(BaseModel):
    job_id: str = Field(..., min_length=64)
    job_type: str
    status: JobStatus           # ← Database column
    stage: int
    total_stages: int
    parameters: Dict[str, Any]  # ← JSONB column
    result_data: Dict[str, Any] # ← JSONB column
    created_at: datetime
    updated_at: datetime

# Usage:
job = JobRecord(...)
db.insert_into_jobs_table(job)  # ← Becomes a database row
```

**Characteristics**:
- ✅ Has ALL fields from database table
- ✅ Maps 1:1 to table structure
- ✅ Used for full CRUD operations
- ❌ NOT used for partial updates
- ❌ NOT used for queue messages

---

### SCHEMAS (Validation & Transformation)
**Purpose**: Validate data in flight (queue messages, API requests, updates)
**Location**: `core/schema/`
**Lifecycle**: Created, validated, discarded (ephemeral)

**Example 1 - Queue Message**:
```python
# core/schema/queue.py
class JobQueueMessage(BaseModel):
    job_id: str = Field(..., min_length=64)
    job_type: str
    parameters: Dict[str, Any]
    stage: int
    correlation_id: str

# Usage:
message = JobQueueMessage(...)
queue.send(message.model_dump_json())  # ← Serialized, NOT stored in DB
```

**Characteristics**:
- ✅ Subset of fields (only what's needed)
- ✅ Used for messages, requests, responses
- ❌ Does NOT map to database table
- ❌ Does NOT persist

**Example 2 - Update Model**:
```python
# core/schema/updates.py
class TaskUpdateModel(BaseModel):
    status: Optional[TaskStatus] = None
    result_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None

# Usage:
update = TaskUpdateModel(status=TaskStatus.COMPLETED)
db.update_task(task_id, update)  # ← Partial update, NOT a full record
```

**Characteristics**:
- ✅ All fields optional (partial updates)
- ✅ Used for UPDATE operations
- ❌ NOT a complete database record

---

## Visual Comparison

### DATA MODEL (Database Entity)
```
JobRecord (core/models/job.py)
  ↓
PostgreSQL `jobs` table
  ↓
Row in database
```

### SCHEMA (Validation/Transform)
```
JobQueueMessage (core/schema/queue.py)
  ↓
Azure Queue Storage
  ↓
Ephemeral message (not persisted)

TaskUpdateModel (core/schema/updates.py)
  ↓
UPDATE statement
  ↓
Modifies existing row (partial)
```

---

## Updated File Count by Category

| Category | Files | Description |
|----------|-------|-------------|
| **Data Models - Database Entities** | 7 | Map to PostgreSQL tables |
| **Schemas - Validation & Transform** | 6 | Queue messages, updates, workflows |
| **Azure Resource Repositories** | 9 | Access Azure services |
| **State Management & Orchestration** | 4 | Core architectural components |
| **Business Logic Helpers** | 3 | Shared calculations & transitions |
| **HTTP Trigger Endpoints** | 7 | API endpoints (needs review) |
| **Cross-Cutting Utilities** | 3 | Validation, diagnostics |
| **TOTAL** | 39 | (was "38 infrastructure") |

---

## Header Markers - NEW Format

### Data Models
```python
# ============================================================================
# CLAUDE CONTEXT
# ============================================================================
# CATEGORY: DATA MODELS - DATABASE ENTITIES
# PURPOSE: Pydantic model mapping to PostgreSQL table
# EPOCH: Shared by all epochs (database schema)
```

### Schemas
```python
# ============================================================================
# CLAUDE CONTEXT
# ============================================================================
# CATEGORY: SCHEMAS - DATA VALIDATION & TRANSFORMATION
# PURPOSE: Pydantic model for queue messages / updates / workflows
# EPOCH: Shared by all epochs (data flow)
```

### Repositories
```python
# ============================================================================
# CLAUDE CONTEXT
# ============================================================================
# CATEGORY: AZURE RESOURCE REPOSITORIES
# PURPOSE: Azure SDK wrapper for [Blob/Queue/Service Bus/etc]
# EPOCH: Shared by all epochs (infrastructure)
```

### State Management
```python
# ============================================================================
# CLAUDE CONTEXT
# ============================================================================
# CATEGORY: STATE MANAGEMENT & ORCHESTRATION
# PURPOSE: Core architectural component for [state/orchestration]
# EPOCH: Shared by all epochs (may evolve with architecture)
```

### HTTP Triggers
```python
# ============================================================================
# CLAUDE CONTEXT
# ============================================================================
# CATEGORY: HTTP TRIGGER ENDPOINTS
# PURPOSE: API endpoint for [health/jobs/status/etc]
# EPOCH: Shared by all epochs (API layer)
# TODO: Audit for framework logic that belongs in CoreMachine
```

### Utilities
```python
# ============================================================================
# CLAUDE CONTEXT
# ============================================================================
# CATEGORY: CROSS-CUTTING UTILITIES
# PURPOSE: [Validation/Import checking/etc]
# EPOCH: Shared by all epochs (utilities)
```

---

## Example: Why This Matters

### Confusing (OLD):
```
core/models/job.py         - INFRASTRUCTURE
core/schema/queue.py       - INFRASTRUCTURE
```
**Problem**: Both sound the same but serve completely different purposes!

### Clear (NEW):
```
core/models/job.py         - DATA MODELS - DATABASE ENTITIES
core/schema/queue.py       - SCHEMAS - DATA VALIDATION & TRANSFORMATION
```
**Benefit**: Immediately clear what each file does!

---

## HTTP Triggers - TODO List

**Action Required**: Review each trigger file and check:

1. **triggers/submit_job.py**
   - ❓ Does it contain workflow orchestration logic?
   - ❓ Should job creation be in CoreMachine?

2. **triggers/get_job_status.py**
   - ✅ Likely just a query wrapper (OK)

3. **triggers/health.py**
   - ✅ Health check only (OK)

4. **triggers/db_query.py**
   - ✅ Database queries only (OK)

5. **triggers/poison_monitor.py**
   - ❓ Does it contain business logic for handling poison messages?

6. **triggers/schema_pydantic_deploy.py**
   - ✅ Schema deployment only (OK)

7. **triggers/http_base.py**
   - ✅ Base class only (OK)

**Next Step**: Audit each trigger for framework logic extraction

---

## Summary

### NEW Categories (Descriptive):
1. **Data Models - Database Entities** (7) - PostgreSQL tables
2. **Schemas - Validation & Transform** (6) - Queue messages, updates
3. **Azure Resource Repositories** (9) - Azure SDK wrappers
4. **State Management & Orchestration** (4) - Core architecture
5. **Business Logic Helpers** (3) - Shared calculations
6. **HTTP Trigger Endpoints** (7) - API layer (needs review)
7. **Cross-Cutting Utilities** (3) - Validation, diagnostics

### Key Distinction:
- **Data Models** = Database rows (persistent)
- **Schemas** = Messages/updates (ephemeral)

### Action Items:
1. Update headers with new category names
2. Audit HTTP triggers for framework logic
3. Consider extracting trigger logic to CoreMachine

**Want me to proceed with updating the headers to use these new categories?**
