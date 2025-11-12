# EPOCH 4: Azure Geospatial ETL Pipeline - Complete Restart

**Date**: 30 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Master document for Epoch 4 rebuild - Starting fresh with lessons learned

---

## 🎯 Executive Summary

You are building **Epoch 4** of an Azure serverless geospatial ETL pipeline. This is a **complete restart** - take the lessons learned from Epochs 1-3 and build it right from the ground up.

### What We Built (Epochs 1-3)
- ✅ Working multi-stage job orchestration (Job → Stage → Task pattern)
- ✅ PostgreSQL-backed state management with advisory locks
- ✅ Both Queue Storage and Service Bus pipelines
- ✅ Clean architecture with composition over inheritance
- ⚠️ **2,290-line God Class** that needs elimination
- ⚠️ Mixed legacy/new code creating complexity

### What We're Building (Epoch 4)
- 🎯 **Declarative job definitions** (~50 lines per job, not 1,000)
- 🎯 **CoreMachine architecture** - all machinery abstracted
- 🎯 **Zero God Classes** - composition all the way down
- 🎯 **Clean separation** - instructions vs machinery
- 🎯 **Production-ready** from day one

---

## 🏗️ Core Architecture Vision

### The Fundamental Principle

**Job-specific code should be declarative instructions, not imperative machinery.**

Current problem: Controllers contain ~1,000 lines of orchestration code that's identical across all jobs. This violates DRY.

Solution: Abstract ALL machinery into core classes, leaving job-specific code as simple declarations.

### Example: What a Job Should Look Like

```python
# hello_world_job.py - THE ENTIRE JOB DEFINITION (~50 lines)

from core.machine import JobDeclaration, register_job

@register_job
class HelloWorldJob(JobDeclaration):
    """Pure declaration - WHAT this job does, not HOW"""

    JOB_TYPE = "hello_world"
    BATCH_THRESHOLD = 50

    STAGES = [
        {
            "number": 1,
            "name": "greeting",
            "task_type": "hello_world_greeting",
            "parallelism": "dynamic",
            "count_param": "n"
        },
        {
            "number": 2,
            "name": "reply",
            "task_type": "hello_world_reply",
            "parallelism": "match_previous",
            "uses_lineage": True
        }
    ]

    PARAMETERS = {
        "n": {"type": "int", "min": 1, "max": 1000, "default": 3},
        "message": {"type": "str", "default": "Hello World"}
    }

    def create_tasks_for_stage(self, stage: int, params: dict):
        """ONLY custom logic needed"""
        n = params['n']
        if stage == 1:
            return [{"index": i, "message": params['message']} for i in range(n)]
        elif stage == 2:
            return [{"index": i} for i in range(n)]

# Business logic handlers (separate file)
@register_handler("hello_world_greeting")
def handle_greeting(params: dict) -> dict:
    return {"greeting": f"Hello from task {params['index']}"}

@register_handler("hello_world_reply")
def handle_reply(params: dict, context: TaskContext) -> dict:
    predecessor = context.get_predecessor_result()
    return {"reply": f"Replying to: {predecessor['greeting']}"}
```

That's it! ~50 lines for a complete working job. All orchestration handled by CoreMachine.

---

## 📊 Job → Stage → Task Pattern

### Orchestration Flow

```
JOB (Orchestration Layer)
 ├── STAGE 1 (Sequential)
 │   ├── Task A (Parallel) ┐
 │   ├── Task B (Parallel) ├─ All tasks run concurrently
 │   └── Task C (Parallel) ┘  Last task triggers stage completion
 │
 ├── STAGE 2 (Sequential - waits for Stage 1)
 │   ├── Task D (Parallel) ┐
 │   └── Task E (Parallel) ┘  Last task triggers stage completion
 │
 └── COMPLETION (Job aggregation & final status)
```

### Queue-Driven Processing

```
HTTP Request → Jobs Queue → Job Handler → Tasks Queue → Task Handlers
                   ↓              ↓            ↓             ↓
               Job Record    Stage Create   Task Records   Execute
               (PostgreSQL)  (Orchestrate)  (PostgreSQL)   (Business Logic)
```

### Key Patterns

1. **"Last Task Turns Out the Lights"**
   - Advisory locks prevent race conditions
   - Exactly one task detects completion and advances stage
   - Scales to unlimited parallelism without deadlocks

2. **Idempotent Job Submission**
   - Job ID = SHA256(job_type + parameters)
   - Duplicate submissions return existing job
   - Natural deduplication at submission

3. **Inter-Stage Data Flow**
   - Stage results passed to next stage
   - Tasks can access predecessor results via lineage
   - Large results stored in blob storage (>1MB threshold)

---

## 🗄️ Database Architecture

### Critical Concept: Database-as-Code

**PostgreSQL functions ARE infrastructure code, not just data storage.**

The database layer contains:
- **Tables** - State storage (jobs, tasks)
- **Functions** - Business logic executed in the database
- **Triggers** - Automatic state transitions
- **Enums** - Type safety at database level
- **Indexes** - Performance optimization

All deployed via Python code (`core/schema/deployer.py` and `sql_generator.py`). Schema changes are version-controlled and deployed like application code.

**Why Functions in Database?**
1. **Atomicity** - ACID guarantees for complex state transitions
2. **Performance** - No network round-trips for multi-step operations
3. **Advisory Locks** - Database-level concurrency control
4. **Single Source of Truth** - Business rules enforced at data layer
5. **Language Agnostic** - Any client can call these functions

### Three-Schema Design

```
PostgreSQL Database
├── app schema (STABLE - Core Orchestration)
│   ├── jobs table - Job state management
│   ├── tasks table - Task execution tracking
│   ├── PostgreSQL FUNCTIONS - Atomic operations with advisory locks ⭐
│   ├── ENUMS - JobStatus, TaskStatus (database-enforced)
│   └── INDEXES - Optimized queries
│
├── pgstac schema (STABLE - STAC Catalog)
│   ├── collections - STAC collections (datasets)
│   ├── items - STAC items (individual assets)
│   ├── search() FUNCTION - CQL2 spatial/temporal queries
│   └── Partitioned tables - Scale to millions of items
│
└── geo schema (FLEXIBLE - Spatial Data Library)
    ├── Vector layers (PostGIS geometries)
    ├── Raster catalogs (PostGIS raster)
    ├── Custom spatial FUNCTIONS - Project-specific analysis
    └── Project-specific spatial tables (grows over time)
```

### Jobs Table (app.jobs)

```sql
CREATE TABLE app.jobs (
    job_id TEXT PRIMARY KEY,              -- SHA256 hash for idempotency
    job_type TEXT NOT NULL,               -- Maps to controller
    status TEXT NOT NULL,                 -- QUEUED → PROCESSING → COMPLETED/FAILED
    stage INT NOT NULL,                   -- Current stage (1 to N)
    total_stages INT NOT NULL,            -- Defined by workflow
    parameters JSONB NOT NULL,            -- Original input parameters
    stage_results JSONB DEFAULT '{}'::jsonb,  -- Aggregated results per stage
    result_data JSONB DEFAULT '{}'::jsonb,    -- Final aggregated results
    error_details TEXT,                   -- Failure information
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Tasks Table (app.tasks)

```sql
CREATE TABLE app.tasks (
    task_id TEXT PRIMARY KEY,             -- Format: {job_id[:8]}-{stage}-{index}
    parent_job_id TEXT NOT NULL REFERENCES app.jobs(job_id),
    task_type TEXT NOT NULL,              -- Maps to service handler
    status TEXT NOT NULL,                 -- QUEUED → PROCESSING → COMPLETED/FAILED
    stage INT NOT NULL,                   -- Stage number
    task_index TEXT NOT NULL,             -- Can be semantic (e.g., "tile-x5-y10")
    parameters JSONB NOT NULL,            -- Task-specific params
    result_data JSONB DEFAULT '{}'::jsonb,    -- Task output
    next_stage_params JSONB,              -- Explicit handoff to next stage
    error_details TEXT,
    heartbeat TIMESTAMPTZ,                -- For long-running tasks
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Critical PostgreSQL Functions (Database-as-Code)

**IMPORTANT**: These functions are NOT just helpers - they ARE the orchestration engine.

#### Function 1: complete_task_and_check_stage()

**Purpose**: Atomically complete a task and detect if it's the last in the stage

```sql
-- Complete task and check if stage is done (atomic with advisory lock)
CREATE FUNCTION complete_task_and_check_stage(
    p_task_id TEXT,
    p_job_id TEXT,
    p_stage INT
) RETURNS BOOLEAN AS $$
BEGIN
    -- CRITICAL: Advisory lock prevents race conditions
    -- Only ONE task can execute this code at a time per job-stage
    PERFORM pg_advisory_xact_lock(
        hashtext(p_job_id || ':stage:' || p_stage::text)
    );

    -- Update task status
    UPDATE app.tasks
    SET status = 'COMPLETED', updated_at = NOW()
    WHERE task_id = p_task_id;

    -- Check if all tasks in stage complete (no row locks needed!)
    -- This query is safe because of advisory lock above
    RETURN NOT EXISTS (
        SELECT 1 FROM app.tasks
        WHERE parent_job_id = p_job_id
        AND stage = p_stage
        AND status != 'COMPLETED'
    );
END;
$$ LANGUAGE plpgsql;
```

**Key Insight**: Advisory locks provide O(1) serialization instead of O(n²) row locks. This enables unlimited parallelism without deadlocks.

#### Function 2: advance_job_stage()

**Purpose**: Move job to next stage with stage results

```sql
CREATE FUNCTION advance_job_stage(
    p_job_id TEXT,
    p_next_stage INT,
    p_stage_results JSONB
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE app.jobs
    SET
        stage = p_next_stage,
        stage_results = stage_results || p_stage_results,  -- Merge results
        status = 'PROCESSING',
        updated_at = NOW()
    WHERE job_id = p_job_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;
```

#### Function 3: complete_job()

**Purpose**: Mark job as complete with final results

```sql
CREATE FUNCTION complete_job(
    p_job_id TEXT,
    p_result_data JSONB
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE app.jobs
    SET
        status = 'COMPLETED',
        result_data = p_result_data,
        updated_at = NOW()
    WHERE job_id = p_job_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;
```

### Database Schema Deployment (Infrastructure-as-Code)

**All schema changes deployed via Python:**

```python
# core/schema/deployer.py
class SchemaDeployer:
    """Deploys database schema like application code"""

    def deploy_full_schema(self):
        """Deploy complete schema - tables, enums, functions, indexes"""
        self.create_enums()      # JobStatus, TaskStatus types
        self.create_tables()     # jobs, tasks with constraints
        self.create_functions()  # Business logic in database
        self.create_indexes()    # Performance optimization

# core/schema/sql_generator.py
class SQLGenerator:
    """Generate SQL DDL from Python models"""

    def generate_function_ddl(self, function_name: str) -> str:
        """Generate CREATE FUNCTION statements"""
        # Functions version-controlled in Python code!
```

**Critical Pattern**:
- Schema changes committed to git
- Deployed via `/api/db/schema/redeploy` endpoint
- Functions updated atomically with code
- No manual SQL scripts

---

## 📦 Code Organization (Epoch 4 Target)

### Core Architecture (core/ folder)

```
core/
├── __init__.py                    # Lazy loading, clean exports
├── machine.py                     # ⭐ NEW - CoreMachine (universal orchestrator)
├── controller.py                  # Minimal abstract base (~100 lines)
├── state_manager.py               # Database operations with advisory locks
├── orchestration_manager.py      # Dynamic task creation and batching
│
├── models/                        # Pure Pydantic data models
│   ├── enums.py                  # JobStatus, TaskStatus
│   ├── job.py                    # JobRecord, JobExecutionContext
│   ├── task.py                   # TaskRecord, TaskDefinition
│   ├── results.py                # TaskResult, StageResultContract
│   └── context.py                # ExecutionContext, task lineage
│
├── schema/                        # Schema management
│   ├── deployer.py               # Schema deployment logic
│   ├── sql_generator.py          # SQL DDL generation
│   ├── workflow.py               # Workflow definitions
│   ├── orchestration.py          # Orchestration patterns
│   ├── queue.py                  # Queue message schemas
│   └── updates.py                # Update models
│
└── logic/                         # Business logic utilities
    ├── calculations.py           # Stage advancement calculations
    └── transitions.py            # State transition validation
```

### Job Definitions (jobs/ folder) - NEW!

```
jobs/
├── __init__.py                    # Auto-registration
├── hello_world.py                # HelloWorld job declaration (~50 lines)
├── process_raster.py             # Raster processing workflow
├── container_list.py             # Container listing workflow
└── stac_ingest.py                # STAC ingestion workflow
```

### Services (services/ folder)

```
services/
├── __init__.py                    # Handler registry
├── hello_world.py                # Hello World business logic
├── raster.py                     # Raster processing handlers
├── blob.py                       # Blob storage operations
└── stac.py                       # STAC catalog operations
```

### Infrastructure (infra/ folder) - Renamed from repositories/

```
infra/
├── __init__.py
├── interfaces.py                 # Repository interfaces
├── factory.py                    # Repository factory
├── postgresql.py                 # PostgreSQL implementation
├── blob.py                       # Azure Blob Storage
├── queue.py                      # Azure Queue Storage
├── service_bus.py                # Azure Service Bus
└── vault.py                      # Azure Key Vault
```

### Azure Functions Entry Point

```
function_app.py                   # HTTP, Queue, Service Bus, Timer triggers
config.py                         # Pydantic configuration
```

---

## 🎯 CoreMachine Architecture (New for Epoch 4)

### The Universal Orchestration Engine

```python
class CoreMachine:
    """
    Universal orchestration engine that works identically for ALL jobs.
    Contains ZERO job-specific code - all machinery is generic.
    """

    def __init__(self, job_declaration: JobDeclaration):
        self.job = job_declaration
        self.state_manager = StateManager()
        self.orchestrator = OrchestrationManager()

    def process_job_message(self, message: JobQueueMessage):
        """Generic job processing - same for ALL jobs"""
        # 1. Validate message
        # 2. Create tasks from declaration
        # 3. Queue tasks (batch or individual based on count)
        # 4. Update job status
        # All generic - no job-specific code!

    def process_task_message(self, message: TaskQueueMessage):
        """Generic task processing - same for ALL jobs"""
        # 1. Get handler from registry
        # 2. Execute with context (provides lineage if needed)
        # 3. Check stage completion (advisory lock)
        # 4. Advance stage or complete job
        # All generic - no job-specific code!

    def handle_stage_completion(self, stage: int, job_id: str):
        """Generic stage advancement - same for ALL jobs"""
        if self.should_advance_stage(stage):
            self.queue_next_stage(stage + 1)
        elif self.is_final_stage(stage):
            self.complete_job(job_id)

    def queue_tasks(self, tasks: List[TaskDefinition]):
        """Generic task distribution - same for ALL jobs"""
        if len(tasks) >= self.job.BATCH_THRESHOLD:
            return self.batch_queue_tasks(tasks)  # Service Bus batches
        else:
            return self.individual_queue_tasks(tasks)  # Queue Storage
```

### What Makes CoreMachine Work

1. **Job Declaration Interface**: Jobs provide metadata and task creation
2. **Handler Registry**: Task handlers registered by task_type
3. **Context Injection**: Tasks receive context with lineage access
4. **Generic State Management**: All database operations in StateManager
5. **Smart Batching**: Automatic batch vs individual queuing

---

## 🚀 Azure Resources & Deployment

### Active Resources

**Function App:**
- Name: `rmhgeoapibeta` (**ONLY** active app)
- URL: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net
- Runtime: Python 3.12
- Plan: Premium (Elastic)
- Region: East US

**Database:**
- Server: `rmhpgflex.postgres.database.azure.com`
- Database: `postgres`
- Schemas: `app`, `pgstac`, `geo`
- Version: PostgreSQL 14
- Extensions: PostGIS 3.4

**Storage:**
- Account: `rmhazuregeo`
- Containers: `rmhazuregeobronze`, `rmhazuregeosilver`, `rmhazuregeogold`
- Queues: `geospatial-jobs`, `geospatial-tasks`

**Resource Group:**
- Name: `rmhazure_rg` (NOT rmhresourcegroup)
- Location: East US

### Deployment Command

```bash
func azure functionapp publish rmhgeoapibeta --python --build remote
```

### Post-Deployment Checklist

```bash
# 1. Health Check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# 2. Redeploy Database Schema (REQUIRED after code changes!)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes

# 3. Submit Test Job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 3}'

# 4. Check Job Status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# 5. Verify Tasks
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

---

## 📚 Lessons Learned from Epochs 1-3

### ✅ What Worked Well

1. **Advisory Locks for "Last Task Turns Out Lights"**
   - Eliminated all race conditions
   - Scales to unlimited parallelism
   - O(1) complexity vs O(n²) row locks

2. **SHA256 Job IDs for Idempotency**
   - Natural deduplication
   - Deterministic job tracking
   - Client retry safety

3. **Three-Schema Database Design**
   - Clear separation of concerns
   - Stable orchestration (app schema)
   - Flexible data library (geo schema)

4. **Pydantic Everywhere**
   - Type safety throughout
   - Automatic validation
   - Self-documenting models

5. **Multi-Stage Job Pattern**
   - Handles complex workflows naturally
   - Inter-stage data flow
   - Dynamic task creation

### ⚠️ What Didn't Work (Don't Repeat!)

1. **God Class (2,290 lines)**
   - BaseController became unmaintainable
   - Copy-paste orchestration in every controller
   - Mixed job-specific and generic code

2. **Imperative Job Definitions**
   - Controllers with ~1,000 lines of boilerplate
   - Should be ~50 lines of declarations
   - Machinery should be abstracted

3. **Mixed Legacy/New Code**
   - Parallel implementations confusing
   - Import path ambiguity
   - Technical debt accumulation

4. **Insufficient Abstraction**
   - Orchestration logic repeated per job
   - Should be in CoreMachine
   - DRY principle violated

### 🎯 Core Principles for Epoch 4

1. **Declarative Over Imperative**
   - Jobs declare what, not how
   - Machinery abstracted to CoreMachine
   - ~50 lines per job maximum

2. **Composition Over Inheritance**
   - No God Classes
   - Inject dependencies
   - Single responsibility components

3. **No Backward Compatibility**
   - Development mode - fail fast
   - Clean breaks over compatibility shims
   - Clear error messages for migration

4. **Production-Ready from Day One**
   - Proper error handling
   - Comprehensive logging
   - Monitoring and observability

5. **Self-Documenting Code**
   - Pydantic models
   - Type hints everywhere
   - Clear naming conventions

---

## 🛠️ Implementation Roadmap for Epoch 4

### Phase 1: Core Foundation (Week 1)

**Objective**: Build CoreMachine and minimal infrastructure

1. **Database Schema Deployment (FIRST!)**
   - Deploy PostgreSQL functions with advisory locks
   - Create enums (JobStatus, TaskStatus) at database level
   - Verify functions via `/api/db/functions/test` endpoint
   - **This is infrastructure code** - version controlled, deployed atomically

2. **Create core/machine.py**
   - Universal job orchestration engine
   - Calls PostgreSQL functions for state transitions
   - Generic stage advancement
   - Generic task distribution
   - Zero job-specific code

3. **Refactor core/controller.py**
   - Minimal abstract base (~100 lines)
   - Only abstract methods for job declarations
   - No orchestration logic

4. **Update core/state_manager.py**
   - Thin wrapper over PostgreSQL functions
   - All business logic in database functions
   - Connection management only

5. **Update core/orchestration_manager.py**
   - Smart batching decisions
   - Task creation helpers
   - Retry logic

**Success Criteria:**
- PostgreSQL functions deployed and tested
- CoreMachine can process a simple job end-to-end
- Zero orchestration code in job definitions
- All tests passing

### Phase 2: Job Declaration System (Week 1-2)

**Objective**: Create declarative job definition framework

1. **Create jobs/ folder structure**
   - Auto-registration system
   - Job declaration base class
   - Parameter validation schemas

2. **Implement HelloWorld as declaration**
   - Convert from 1,000 lines to ~50 lines
   - Test with CoreMachine
   - Validate equivalence to old version

3. **Create handler registry**
   - Auto-discovery of handlers
   - Task type → handler mapping
   - Context injection for lineage

**Success Criteria:**
- HelloWorld job is ~50 lines
- Handlers auto-registered
- Context provides predecessor access

### Phase 3: Production Workflows (Week 2-3)

**Objective**: Implement real-world geospatial workflows

1. **Process Raster Workflow**
   ```
   Stage 1: Validate raster format, extract metadata
   Stage 2: Calculate tile boundaries (if large)
   Stage 3: Process tiles in parallel (reproject, COG conversion)
   Stage 4: Create STAC catalog entry
   ```

2. **Container List Workflow**
   ```
   Stage 1: List container, filter by extension
   Stage 2: Process files in batches
   ```

3. **STAC Ingest Workflow**
   ```
   Stage 1: Read STAC collection
   Stage 2: Validate and import items in parallel
   ```

**Success Criteria:**
- Each workflow ~50-100 lines
- Handlers tested independently
- End-to-end workflows complete

### Phase 4: Service Bus Integration (Week 3)

**Objective**: Optimize for high-volume batch processing

1. **Service Bus Repository**
   - Batch message sending (100/batch)
   - Aligned with PostgreSQL batches
   - Performance metrics

2. **Batch Coordination**
   - PostgreSQL batch_create_tasks()
   - Service Bus batch send
   - Two-phase commit pattern

3. **Smart Queue Selection**
   - <50 tasks → Queue Storage
   - ≥50 tasks → Service Bus batches
   - Configurable threshold

**Success Criteria:**
- 1,000 tasks complete in ~2-3 seconds
- No deadlocks at any scale
- Proper error handling

### Phase 5: Monitoring & Operations (Week 4)

**Objective**: Production observability and debugging

1. **Enhanced Logging**
   - Correlation IDs throughout
   - Structured logging (JSON)
   - Performance metrics

2. **Database Endpoints**
   - Job/task querying
   - Statistics and health
   - Debug dump endpoints

3. **Health Checks**
   - Component status
   - Database connectivity
   - Queue depths

**Success Criteria:**
- Full observability
- Easy debugging
- Clear error messages

---

## 🔍 Critical Technical Details

### Advisory Lock Pattern

```sql
-- Single serialization point per job-stage
PERFORM pg_advisory_xact_lock(
    hashtext(v_job_id || ':stage:' || v_stage::text)
);

-- Now safely count remaining tasks (no row locks needed!)
SELECT COUNT(*) INTO v_remaining
FROM app.tasks
WHERE parent_job_id = v_job_id
AND stage = v_stage
AND status != 'COMPLETED';

-- Lock released automatically at transaction end
```

**Why This Works:**
- O(1) lock complexity (one lock per job-stage)
- No row-level deadlocks
- Scales to unlimited tasks
- Lock automatically released

### Task Lineage Access

```python
# In task handler
@register_handler("process_tile")
def handle_tile(params: dict, context: TaskContext) -> dict:
    # Automatic access to predecessor (same index, previous stage)
    if context.has_predecessor():
        metadata = context.get_predecessor_result()
        tile_bounds = metadata['tile_bounds']

    # Process tile with bounds from previous stage
    result = process_tile(tile_bounds)
    return result
```

### Batch vs Individual Queuing

```python
class CoreMachine:
    def queue_tasks(self, tasks: List[TaskDefinition]):
        """Smart queuing based on task count"""
        if len(tasks) >= self.job.BATCH_THRESHOLD:
            # Service Bus: 100 tasks/batch, ~2.5 seconds for 1,000 tasks
            return self.service_bus_repo.batch_send(tasks)
        else:
            # Queue Storage: Individual messages, simpler for small jobs
            return self.queue_repo.send_messages(tasks)
```

---

## 📋 File Naming Conventions

**Strict naming for auto-discovery:**

```
jobs/job_*.py         → Job declarations (auto-registered)
services/service_*.py → Business logic handlers (auto-registered)
core/core_*.py        → Core machinery components
infra/repo_*.py       → Infrastructure repositories
triggers/trigger_*.py → Azure Functions triggers
```

---

## 🚨 Critical Warnings & Reminders

### DO's

✅ **Use CoreMachine for all orchestration**
✅ **Keep job definitions declarative (~50 lines)**
✅ **Use Pydantic everywhere for type safety**
✅ **Advisory locks for all completion checks**
✅ **Structured logging with correlation IDs**
✅ **Fail fast in development mode**

### DON'Ts

❌ **NEVER create God Classes**
❌ **NEVER copy-paste orchestration logic**
❌ **NEVER mix instructions with machinery**
❌ **NEVER deploy to deprecated apps** (rmhazurefn, rmhgeoapi, rmhgeoapifn)
❌ **NEVER implement backward compatibility** (development mode)
❌ **NEVER skip schema redeploy after code changes**

---

## 📊 Success Metrics

### Code Quality
- Job definitions: ≤100 lines each
- CoreMachine: All orchestration abstracted
- Test coverage: ≥80%
- Zero God Classes

### Performance
- 1,000 tasks: Complete in <5 seconds
- No deadlocks at any scale
- Linear scaling with batch size

### Developer Experience
- New job: <1 hour to implement
- Clear error messages
- Self-documenting code
- Easy debugging

---

## 🎓 Key Architectural Decisions

### Decision 1: CoreMachine vs Controllers
**Choice**: Abstract all orchestration into CoreMachine
**Rationale**: Jobs should declare what, not how. DRY principle.
**Impact**: Jobs go from 1,000 lines → 50 lines

### Decision 2: Database Functions as Infrastructure
**Choice**: Critical business logic in PostgreSQL functions, not Python
**Rationale**: ACID guarantees, advisory locks, atomicity, performance
**Impact**: "Last task turns out lights" race-free at any scale
**Key Point**: Functions are infrastructure-as-code, deployed like app code

### Decision 3: Advisory Locks vs Row Locks
**Choice**: PostgreSQL advisory locks for completion checks
**Rationale**: O(1) complexity, no deadlocks, unlimited parallelism
**Impact**: Scale from n=4 (deadlocks) → n=1000+ (no deadlocks)

### Decision 4: Three-Schema Database
**Choice**: Separate app, pgstac, geo schemas
**Rationale**: Stable orchestration, standards-compliant catalog, flexible data
**Impact**: Clean boundaries, safe migrations, each schema has own functions

### Decision 5: SHA256 Job IDs
**Choice**: Hash(job_type + params) for job ID
**Rationale**: Natural idempotency, client retry safety
**Impact**: Automatic deduplication, enforced at database level

### Decision 6: Composition Over Inheritance
**Choice**: Inject StateManager, OrchestrationManager
**Rationale**: Single responsibility, testability, no God Classes
**Impact**: Clean separation, easy testing

---

## 🔗 Additional Resources

### From Epoch 3 (Reference Only)

**Documentation Structure:**
```
docs_claude/
├── CLAUDE_CONTEXT.md         # Epoch 3 primary context
├── TODO_ACTIVE.md            # Epoch 3 tasks (28 SEP 2025)
├── HISTORY.md                # What was built in Epoch 3
├── ARCHITECTURE_REFERENCE.md # Deep technical specs
├── FILE_CATALOG.md           # File organization
└── DEPLOYMENT_GUIDE.md       # Deployment procedures
```

**Archived Implementation Docs:**
```
docs/archive/
├── service_bus/              # Service Bus iterations (25-26 SEP)
├── basecontroller/           # God Class refactoring attempts
├── analysis/                 # Debugging investigations
└── obsolete/                 # Superseded documentation
```

### Critical Files to Study (Epoch 3)

1. **core/core_controller.py** - Clean controller base (400 lines vs 2,290)
2. **core/state_manager.py** - Database operations with advisory locks
3. **core/orchestration_manager.py** - Dynamic task creation
4. **controller_service_bus_hello.py** - Example of what NOT to do (1,000 lines)
5. **schema_sql_generator.py** - Advisory lock implementation

---

## 🚀 Getting Started - Day 1 Tasks

### 1. Review Epoch 3 Architecture
- Read core/core_controller.py
- Understand StateManager patterns
- **Study PostgreSQL functions** in schema_sql_generator.py
- Review advisory lock implementation (database-as-code!)
- Review job→stage→task flow

### 2. Design CoreMachine
- Sketch out class structure
- Identify all generic operations
- Plan job declaration interface
- Define handler registry pattern

### 3. Create Foundation
- Set up core/machine.py
- Implement basic job processing
- Add task distribution logic
- Create handler registry

### 4. Test with HelloWorld
- Convert to declarative style
- Verify end-to-end flow
- Validate equivalence
- Measure line count reduction

### 5. Document Architecture
- CoreMachine design doc
- Job declaration guide
- **Database-as-Code pattern** (functions, enums, deployment)
- Migration from Epoch 3
- Developer getting started

---

## 💡 The Vision

**Before (Epoch 3):**
```python
# controller_service_bus_hello.py - 1,019 lines
class ServiceBusHelloWorldController:
    # 200+ lines of stage advancement
    # 100+ lines of job completion
    # 250+ lines of task queuing
    # 150+ lines of batch processing
    # Only ~50 lines of actual job logic!
```

**After (Epoch 4):**
```python
# jobs/hello_world.py - 50 lines total!
@register_job
class HelloWorldJob(JobDeclaration):
    JOB_TYPE = "hello_world"
    STAGES = [...]  # Declarative stage definitions

    def create_tasks_for_stage(self, stage, params):
        # ONLY this custom logic needed
        return [...]

# All orchestration in CoreMachine (shared by ALL jobs)
```

---

## 🎯 Final Thoughts

Epoch 4 is about **doing it right from the start**:

1. **Separate instructions from machinery** - Jobs declare, CoreMachine executes
2. **Eliminate duplication** - Write orchestration once, use everywhere
3. **Composition over inheritance** - No God Classes allowed
4. **Production quality** - Error handling, logging, monitoring from day one
5. **Developer joy** - New jobs in minutes, not days

The goal: **Adding a new job should require writing ONLY what makes that job unique, nothing more.**

Start with CoreMachine. Get it right. Everything else falls into place.

---

**Good luck, Epoch 4 Claude! Build something beautiful. 🚀**

*"The best code is no code. The second best is declarative code. The worst is imperative orchestration code copy-pasted into every controller."*
