# Claude Context - Azure Geospatial ETL Pipeline

**Author**: Robert and Geospatial Claude Legion
**Date**: 16 OCT 2025
**Primary Documentation**: Start here for all Claude instances

## 🚨 CRITICAL: NEW CORE ARCHITECTURE (29 SEP 2025)

### Two Parallel Implementations
The system now has **TWO separate controller architectures** running in parallel:

#### 1. **Legacy: BaseController (God Class)**
- **File**: `controller_base.py` (2,290 lines)
- **Used by**: Storage Queue jobs (`hello_world`, `summarize_container`)
- **Status**: ⚠️ Legacy - being replaced, still operational
- **Pattern**: Inheritance-based with 2,290 lines of God Class
- **Imports**: Uses `schema_base.py` for models (being migrated to `core.models`)

#### 2. **NEW: Core Architecture (Clean)** ✨
- **Location**: `core/` folder
- **Used by**: Service Bus jobs (`sb_hello_world`)
- **Status**: ✅ Active development - the future
- **Pattern**: Composition over inheritance
- **Imports**: Uses `core.models` exclusively

### Core Architecture Structure
```
core/
├── __init__.py              # Lazy loading to prevent circular imports
├── core_controller.py       # Minimal base (400 lines vs 2,290)
├── state_manager.py         # Database operations (composition)
├── orchestration_manager.py # Dynamic task creation (composition)
├── models/                  # Pure Pydantic data models
│   ├── __init__.py
│   ├── enums.py            # JobStatus, TaskStatus
│   ├── job.py              # JobRecord
│   ├── task.py             # TaskRecord, TaskDefinition
│   ├── results.py          # TaskResult, StageResultContract
│   └── context.py          # JobExecutionContext, StageExecutionContext
├── logic/                   # Business logic utilities
│   ├── __init__.py
│   ├── calculations.py     # Stage advancement calculations
│   └── transitions.py      # State transition validation
└── schema/                  # Database schema management
    ├── __init__.py
    ├── deployer.py         # Schema deployment logic
    └── sql_generator.py    # SQL generation utilities
```

### Core Architecture Dependencies (Root Modules Still Used)
The `core/` architecture uses these root modules:
- **config.py** - Configuration management
- **repositories/** - Database access layer (shared by both architectures)
- **task_factory.py** - Task handler factory
- **utils/contract_validator.py** - Contract enforcement
- **util_logger.py** - Logging infrastructure
- **schema_workflow.py** - Workflow definitions
- **schema_queue.py** - Queue message schemas
- **schema_orchestration.py** - Orchestration schemas
- **schema_updates.py** - Update models for partial updates
- **exceptions.py** - Custom exception classes

### Migration Path
```
OLD (BaseController):                  NEW (Core):
controller_base.py (2,290 lines) →    core/core_controller.py (400 lines)
                                      + core/state_manager.py (composition)
                                      + core/orchestration_manager.py (composition)

schema_base.py →                      core/models/ (pure Pydantic models)

Inheritance hell →                    Composition over inheritance
```

### How to Identify Which Architecture
```python
# Legacy (BaseController)
from controller_base import BaseController
from schema_base import JobStatus, TaskStatus  # OLD imports

class HelloWorldController(BaseController):  # 2,290 lines inherited!
    pass

# New (Core Architecture)
from core import CoreController, StateManager, OrchestrationManager
from core.models import JobStatus, TaskStatus  # NEW imports

class ServiceBusHelloWorldController(CoreController):  # Only 400 lines inherited
    def __init__(self):
        self.state_manager = StateManager()  # Composition!
```

## ✅ CURRENT STATUS: MULTI-STAGE ORCHESTRATION FULLY OPERATIONAL

### Working Features
- ✅ **Multi-stage job orchestration** working end-to-end (tested with n=100)
- ✅ **Container controller** with dynamic orchestration (Stage 1 analyzes, Stage 2 processes)
- ✅ **Contract enforcement** throughout system with @enforce_contract decorators
- ✅ **Contract compliance** fixed in all controllers with StageResultContract
- ✅ **JSON serialization** fixed with Pydantic `model_dump(mode='json')`
- ✅ **Error handling** with granular try-catch blocks and proper job failure marking
- ✅ **Advisory locks** preventing race conditions at any scale
- ✅ **PostgreSQL atomic operations** via StageCompletionRepository
- ✅ **Idempotency** - SHA256 hash ensures duplicate submissions return same job_id
- ✅ **Folder structure** - utils/ folder tested and working in Azure Functions

## 🚀 Quick Start

### Active Environment
- **Function App**: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net (**ONLY** active app)
- **Database**: rmhpgflex.postgres.database.azure.com (geo schema)
- **Resource Group**: rmhazure_rg (NOT rmhresourcegroup)
- **Storage**: rmhazuregeo* containers (Bronze/Silver/Gold tiers)

### Deployment Command
```bash
func azure functionapp publish rmhgeoapibeta --python --build remote
```

### Testing Commands (Ready to Copy)
```bash
# 1. Health Check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# 2. Redeploy Database Schema (Required after deployment!)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes

# 3. Submit Test Job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 3}'

# 4. Check Job Status (use job_id from step 3)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# 5. Check Tasks for Job
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

## 🏗️ Architecture Overview

### Job Declaration Pattern (Pattern B)

**Updated**: 15 OCT 2025

Jobs are **declarative blueprints** processed by CoreMachine:

```
Job Class (Blueprint)
  ↓
CoreMachine (Orchestrator)
  ↓
Handlers (Business Logic)
```

**Job Responsibilities:**
- Define stages (plain dicts)
- Create task parameters (`create_tasks_for_stage()`)
- Validate parameters (optional)

**CoreMachine Responsibilities:**
- Read job blueprints
- Convert dicts → Pydantic objects
- Queue tasks (batch or individual)
- Execute handlers
- Manage state transitions
- Handle stage completion

**Pattern B: Simple Job Classes (Official Standard)**

```python
class HelloWorldJob:
    job_type: str = "hello_world"
    stages: List[Dict[str, Any]] = [...]  # Plain dicts

    @staticmethod
    def create_tasks_for_stage(...) -> List[dict]:
        return [{"task_id": ..., "task_type": ...}]
```

**Registration (Explicit):**
```python
# jobs/__init__.py
ALL_JOBS = {"hello_world": HelloWorldJob}

# function_app.py
core_machine = CoreMachine(all_jobs=ALL_JOBS, all_handlers=ALL_HANDLERS)
```

**Why Pattern B:**
- Jobs are simple blueprints
- CoreMachine handles complexity
- Pydantic at boundaries (type safety)
- All 10 production jobs use this

**Removed Files (Phase 2 - 15 OCT 2025):**
- `jobs/workflow.py` - Removed (unused Workflow ABC with wrong contract)
- `jobs/registry.py` - Removed (unused decorator pattern)

**Unused Reference Files:**
- `core/models/stage.py` - Stage model (not used by jobs - jobs use plain dicts)

**For complete details:** See `docs_claude/ARCHITECTURE_REFERENCE.md` section "Job Declaration Pattern"

### Job→Stage→Task Pattern
```
JOB (Blueprint - Declares stages)
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

### Pyramid Architecture (Serverless State Management)
```
┌─────────────┐
│   Schemas   │  Foundation: Core data models (Pydantic)
├─────────────┤
│ Controllers │  Orchestration: Job workflows (stateless)
├─────────────┤
│Repositories │  State Management: PostgreSQL ACID ops (ALL STATE HERE)
├─────────────┤
│  Services   │  Business Logic: Task execution (stateless)
├─────────────┤
│  Triggers   │  Entry Points: HTTP/Queue/Timer handlers
├─────────────┤
│  Utilities  │  Cross-Cutting: Logging, validation
└─────────────┘
```

### Key Design Principles
1. **Idempotency**: SHA256(job_type + params) = deterministic job ID
2. **"Last Task Turns Out Lights"**: Advisory locks enable unlimited parallelism without deadlocks
3. **No Backward Compatibility**: Fail fast with clear errors (development mode)
4. **Queue-Driven**: Async processing via Azure Storage Queues
5. **Factory Pattern**: All object creation through factories (JobFactory, TaskFactory, RepositoryFactory)

## 📁 File Structure & Conventions

### File Naming Convention (Strict)
```
controller_*.py  → Job orchestration logic
interface_*.py   → Abstract behavior contracts (pure ABCs)
repository_*.py  → Data access implementations
service_*.py     → Business logic & task execution
schema_*.py      → Pydantic data models
trigger_*.py     → HTTP/Queue/Timer entry points
util_*.py        → Utilities and helpers
```

### File Count Summary (Updated with folder structure)
- **Controllers**: 5 files (base, container, hello_world, stac_setup, factories)
- **Interfaces**: 1 file
- **Repositories**: 6 files (base, blob, factory, jobs_tasks, postgresql, vault)
- **Services**: 4 files (factories, hello_world, stac_setup, schema_manager)
- **Schemas**: 6 files (base, core, orchestration, queue, sql_generator, workflow)
- **Triggers**: 7 files
- **Utilities**: 3 files (1 in utils/ folder: contract_validator; 2 in root: import_validator, logger)
- **Core**: 2 files (function_app, config)
- **Total Python Files**: 34+

### Import Rules
```python
# ✅ CORRECT: Import from interfaces
from interface_repository import IJobRepository

# ❌ WRONG: Import concrete implementations directly
from repository_postgresql import PostgreSQLRepository  # Never!

# ✅ CORRECT: Use factories
from repository_factory import RepositoryFactory
repo = RepositoryFactory.create_repository("postgresql")
```

## 🎯 Current State (16 OCT 2025)

### ✅ What's Working - FULL END-TO-END WORKFLOW
- ✅ HTTP job submission → Queue → Database flow
- ✅ Stage 1 task execution and completion
- ✅ Stage advancement from stage 1 to stage 2
- ✅ Stage 2 task execution and completion
- ✅ Job completion with result aggregation
- ✅ **Container workflows** - summarize_container and list_container operational
- ✅ **Dynamic orchestration** - Stage 1 analyzes content, creates Stage 2 tasks
- ✅ PostgreSQL advisory locks (scales to n=30+ concurrent tasks without deadlocks)
- ✅ Database monitoring endpoints (/api/db/*)
- ✅ Schema deployment and validation
- ✅ **NO POISON QUEUE MESSAGES** - All issues resolved
- ✅ **Idempotency working** - Duplicate submissions return same job_id
- ✅ **Folder migration** - utils/ folder structure working in Azure Functions

### 🎉 Major Issues Resolved (See HISTORY.md for details)
1. **Deadlock Elimination**: Advisory locks enable n=30+ concurrent tasks (previously deadlocked at n>4)
2. **Poison Queue Issue**: Fixed invalid status transition PROCESSING→PROCESSING
3. **N=2 Race Condition**: Fixed task completion counting issue
4. **Complete End-to-End**: All job sizes (n=1 to n=30+) work perfectly
5. **Contract Compliance**: Fixed StageResultContract compliance in all controllers
6. **Dynamic Orchestration**: Container controller Stage 1→Stage 2 task creation working

### ⚠️ Known Issues
1. **complete_job action**: When Stage 1 returns action="complete_job", system still tries to advance to Stage 2

### 🔒 Critical Pattern: Advisory Locks for "Last Task Turns Out Lights"
**The Challenge**: When multiple tasks complete simultaneously, exactly one must detect it's the last and advance the stage.

**The Solution Evolution**:
- ❌ Row-level locks (`FOR UPDATE`): Caused deadlocks at n=30
- ❌ Ordered locks (`ORDER BY task_id`): Still deadlocked at scale
- ✅ **Advisory locks**: Zero deadlocks at any scale

**Implementation** (in `schema_sql_generator.py`):
```sql
-- Single serialization point per job-stage
PERFORM pg_advisory_xact_lock(
    hashtext(v_job_id || ':stage:' || v_stage::text)
);
-- Now count remaining tasks without row locks
```

**Performance Impact**:
- Lock complexity: FROM O(n²) → O(1)
- Deadlocks at n=30: FROM 18 failures → 0 failures
- Completion time: FROM timeout → 15 seconds

### Recent Fixes (13 SEP 2025)
- ✅ Poison queue root cause identified and fixed
- ✅ Controller validation logic updated for stage 2+ messages
- ✅ Comprehensive testing completed (n=1,2,3,4,20)
- ✅ Idempotency verified with duplicate submissions

## 🔧 Development Configuration

### Claude Context Headers (Required for all Python files)
```python
# ============================================================================
# CLAUDE CONTEXT - [DESCRIPTIVE_TITLE]
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: [Component type] - [Brief description]
# PURPOSE: [One sentence description]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: [Classes/functions exposed]
# INTERFACES: [ABCs implemented]
# PYDANTIC_MODELS: [Models used]
# DEPENDENCIES: [External libraries]
# SOURCE: [Data sources]
# SCOPE: [Operational scope]
# VALIDATION: [Validation approach]
# PATTERNS: [Design patterns]
# ENTRY_POINTS: [How to use]
# INDEX: [Line numbers for navigation]
# ============================================================================
```

### Development Settings
- **Retry Logic**: DISABLED (`maxDequeueCount: 1` in host.json)
- **Error Handling**: Fail-fast mode for development
- **Key Vault**: Disabled - using environment variables

## 📚 Reference Documents

| Document | Purpose |
|----------|---------|
| `TODO.md` | ⚡ PRIMARY AND ONLY active task list |
| `ARCHITECTURE_REFERENCE.md` | Deep technical specifications |
| `FILE_CATALOG.md` | Quick file lookup with descriptions |
| `DEPLOYMENT_GUIDE.md` | Deployment procedures and monitoring |
| `HISTORY.md` | Completed work log |

## 🔍 Database Debugging Endpoints

```bash
# Get all jobs and tasks
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/debug/all?limit=100

# Query jobs with filters
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?status=failed&limit=10

# Database statistics
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Test PostgreSQL functions
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/functions/test
```

## 🚨 Critical Reminders

1. **NEVER** update .md files with "PRODUCTION READY" unless explicitly instructed
2. **NEVER** use deprecated function apps (rmhazurefn, rmhgeoapi, rmhgeoapifn)
3. **ALWAYS** prefer editing existing files over creating new ones
4. **ALWAYS** update ARCHITECTURE_FILE_INDEX.md after file changes
5. **NEVER** implement backward compatibility - fail fast with clear errors

## Storage Access
```
Account: rmhazuregeo
Key: [REDACTED - See Azure Portal or Key Vault for actual key]
```

---

*This is the primary context document for Claude. For detailed information, see referenced documents in this folder.*