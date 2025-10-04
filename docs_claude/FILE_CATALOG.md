# File Catalog

**Date**: 4 OCT 2025 (Updated with container operations & task lineage)
**Total Python Files**: 55+ (excluding test files)
**Purpose**: Quick file lookup with one-line descriptions
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ Updated - Container operations, deterministic task lineage added

## 🎯 Core Entry Points (2 files)

| File | Purpose |
|------|---------|
| `function_app.py` | Azure Functions entry point - HTTP, Queue, Service Bus, Timer triggers |
| `config.py` | Strongly typed configuration with Pydantic v2 |

## 🏗️ Core Architecture (core/ folder, 17 files) ⭐ UPDATED 4 OCT

### Core Controllers & Managers (4 files)
| File | Purpose |
|------|---------|
| `core/machine.py` | CoreMachine orchestration - job/task processing with fan-out support |
| `core/task_id.py` | ⭐ NEW - Deterministic task ID generation for lineage tracking |
| `core/state_manager.py` | Database operations with advisory locks - composition over inheritance (540 lines) |
| `core/orchestration_manager.py` | Simplified dynamic task creation for Service Bus batch optimization (400 lines) |

### Core Models (core/models/ - 6 files)
| File | Purpose |
|------|---------|
| `core/models/enums.py` | JobStatus, TaskStatus enums - single source of truth |
| `core/models/job.py` | JobRecord, JobExecutionContext - pure Pydantic models |
| `core/models/task.py` | TaskRecord, TaskDefinition - task data structures |
| `core/models/results.py` | TaskResult, StageResultContract - execution results |
| `core/models/context.py` | StageExecutionContext, StageAdvancementResult - execution context |
| `core/models/__init__.py` | Exports all models for `from core.models import *` |

### Core Logic (core/logic/ - 3 files)
| File | Purpose |
|------|---------|
| `core/logic/calculations.py` | Stage advancement and task count calculations |
| `core/logic/transitions.py` | State transition validation logic |
| `core/logic/__init__.py` | Logic utilities exports |

### Core Schema Management (core/schema/ - 7 files) ⭐ UPDATED 30 SEP
| File | Purpose |
|------|---------|
| `core/schema/deployer.py` | Database schema deployment and validation |
| `core/schema/sql_generator.py` | SQL DDL generation for PostgreSQL |
| `core/schema/workflow.py` | ⭐ NEW - Workflow definitions (copied from root schema_workflow.py) |
| `core/schema/orchestration.py` | ⭐ NEW - Orchestration patterns (copied from root schema_orchestration.py) |
| `core/schema/queue.py` | ⭐ NEW - Queue message schemas (copied from root schema_queue.py) |
| `core/schema/updates.py` | ⭐ NEW - Update models (copied from root schema_updates.py) |
| `core/schema/__init__.py` | Schema utilities exports (18 new exports added) |

## 🎛️ Controllers (8 files)

### Legacy Controllers (Storage Queue - 4 files)
| File | Purpose | Status |
|------|---------|--------|
| `controller_base.py` | God Class controller (2,290 lines - uses schema_base imports) | ⚠️ Legacy |
| `controller_container.py` | Container workflow for blob container file listing | ✅ Working |
| `controller_hello_world.py` | Example 2-stage workflow implementation | ✅ Working |
| `controller_stac_setup.py` | STAC setup controller for PostGIS/pgstac | ⚠️ Needs testing |

### New Controllers (Service Bus - 1 file)
| File | Purpose | Status |
|------|---------|--------|
| `controller_service_bus_hello.py` | Service Bus HelloWorld using core/ architecture | ✅ Active development |

### Factory & Registration (3 files)
| File | Purpose |
|------|---------|
| `controller_factories.py` | JobFactory for controller instantiation (no auto-prefixing) |
| `registration.py` | JobCatalog and TaskCatalog for explicit registration |
| `controller_service_bus_container.py` | Service Bus container controller (stub) |

## 📜 Interfaces (1 file in interfaces/ folder)

| File | Purpose |
|------|---------|
| `interfaces/repository.py` | IQueueRepository and other repository interfaces |

## 💾 Repositories (8 files in repositories/ folder)

| File | Purpose |
|------|---------|
| `repositories/base.py` | Common repository patterns and validation |
| `repositories/factory.py` | Central factory for all repository instances |
| `repositories/jobs_tasks.py` | Business logic for job and task management + batch operations |
| `repositories/postgresql.py` | PostgreSQL-specific implementation with psycopg |
| `repositories/blob.py` | Azure Blob Storage operations |
| `repositories/queue.py` | Queue Storage operations with singleton pattern |
| `repositories/service_bus.py` | Service Bus implementation with batch support |
| `repositories/vault.py` | Azure Key Vault integration (currently disabled) |

## ⚙️ Services (5 files in services/ folder) ⭐ UPDATED 4 OCT

| File | Purpose |
|------|---------|
| `services/service_hello_world.py` | Hello World task processing logic |
| `services/service_blob.py` | Blob storage service handlers |
| `services/service_stac_setup.py` | STAC setup service |
| `services/container_summary.py` | ⭐ NEW - Container aggregate statistics handler |
| `services/container_list.py` | ⭐ NEW - Container blob listing and analysis handlers |

## 📋 Job Workflows (3 files in jobs/ folder) ⭐ NEW 4 OCT

| File | Purpose |
|------|---------|
| `jobs/hello_world.py` | Hello World two-stage workflow definition |
| `jobs/container_summary.py` | ⭐ NEW - Container summary single-stage job |
| `jobs/container_list.py` | ⭐ NEW - Container list two-stage fan-out job |

## 📊 Schemas (10 files - Root Level) ⚠️ LEGACY

| File | Purpose | Status |
|------|---------|--------|
| `schema_base.py` | Core Pydantic models (JobRecord, TaskRecord, etc.) | ⚠️ LEGACY - Replaced by core/models (30 SEP) |
| `schema_workflow.py` | Workflow definition schemas | ⚠️ LEGACY - Replaced by core/schema/workflow.py (30 SEP) |
| `schema_orchestration.py` | Dynamic orchestration models | ⚠️ LEGACY - Replaced by core/schema/orchestration.py (30 SEP) |
| `schema_queue.py` | Queue message schemas | ⚠️ LEGACY - Replaced by core/schema/queue.py (30 SEP) |
| `schema_updates.py` | Update models for partial database updates | ⚠️ LEGACY - Replaced by core/schema/updates.py (30 SEP) |
| `schema_file_item.py` | File processing schemas | ✅ Working |
| `schema_geospatial.py` | Geospatial data models | ✅ Working |
| `schema_postgis.py` | PostGIS specific schemas | ✅ Working |
| `schema_stac.py` | STAC metadata schemas | ✅ Working |
| `model_core.py` | Core Pydantic v2 models | ⚠️ Unclear purpose |

**⚠️ IMPORTANT**:
- **NEW CODE**: Use `from core.models import ...` and `from core.schema import ...`
- **LEGACY CODE**: Root schema files marked with warnings, still work for old controllers
- **MIGRATION**: See CORE_SCHEMA_MIGRATION.md for details (30 SEP 2025)

## 🔧 Utilities (3 files in utils/ folder)

| File | Purpose |
|------|---------|
| `utils/contract_validator.py` | Runtime type enforcement decorator |
| `util_logger.py` | Centralized logging with component types |
| `util_azure_sql.py` | Azure SQL utilities |

## 🚀 Task Processing (2 files)

| File | Purpose |
|------|---------|
| `task_factory.py` | TaskHandlerFactory for task routing |
| `task_handlers.py` | Task processor implementations |

## ⚙️ Trigger Handlers (7 files in triggers/ folder)

| File | Purpose |
|------|---------|
| `triggers/health.py` | Health check endpoint |
| `triggers/submit_job.py` | Job submission HTTP trigger |
| `triggers/list_jobs.py` | Job listing endpoint |
| `triggers/job_status.py` | Job status query endpoint |
| `triggers/db_admin.py` | Database administration endpoints |
| `triggers/db_query.py` | Database query endpoints |
| `triggers/container.py` | Container operation triggers |

## 📝 Documentation (Root Level) ✅ CLEANED UP 30 SEP

**Current Documentation (6 files):**

| File | Purpose |
|------|---------|
| `CLAUDE.md` | ⭐ PRIMARY - Entry point redirecting to docs_claude/ |
| `CORE_SCHEMA_MIGRATION.md` | Schema migration to core/schema/ (30 SEP 2025) |
| `CORE_IMPORT_TEST_REPORT.md` | Import validation - 19/19 tests passed (30 SEP 2025) |
| `LOCAL_TESTING_README.md` | Local development setup guide |
| `core_machine.md` | Architectural vision for declarative controllers |
| `ROOT_MD_FILES_ANALYSIS.md` | Analysis of root markdown cleanup (30 SEP 2025) |

**Archived Documentation (16 files moved to docs/archive/):**
- `docs/archive/service_bus/` - 8 implementation iteration docs (25-26 SEP)
- `docs/archive/basecontroller/` - 2 refactoring strategy docs (26 SEP)
- `docs/archive/analysis/` - 4 debugging/investigation docs (26-28 SEP)
- `docs/archive/obsolete/` - 2 superseded docs (26 SEP)
- See `docs/archive/README.md` for complete archive catalog

## 📁 Documentation (docs_claude/ folder)

| File | Purpose |
|------|---------|
| `CLAUDE_CONTEXT.md` | Primary context for Claude |
| `TODO_ACTIVE.md` | Current active tasks |
| `HISTORY.md` | Project history since Sep 11, 2025 |
| `OLDER_HISTORY.md` | Project history before Sep 11, 2025 |
| `FILE_CATALOG.md` | This file - quick file lookup |
| `ARCHITECTURE_REFERENCE.md` | Deep technical specifications |
| `DEPLOYMENT_GUIDE.md` | Azure deployment procedures |

## 🔄 Architecture Evolution

### Current State (30 SEP 2025):
- **BaseController**: 2,290-line God Class marked as LEGACY (30 SEP)
- **Core Architecture**: ~1,870 lines across focused components in `core/`
- **Parallel Pipelines**: Queue Storage (legacy) and Service Bus (core) both operational
- **Schema Migration**: 4 core schemas moved to `core/schema/` (30 SEP)
- **Root Dependencies**: Reduced from 13 → 9 files (31% reduction)

### Recent Milestones (30 SEP 2025):
1. ✅ **Schema Migration Complete**
   - Migrated 4 schemas (1,453 lines) to `core/schema/`
   - Updated 3 core files to use new imports
   - All 19 import tests passing
   - 6 legacy files marked with warnings

2. ✅ **Documentation Cleanup**
   - Root markdown files: 21 → 6 (71% reduction)
   - 16 files archived to `docs/archive/`
   - Created archive README for easy reference

### Migration Strategy:
1. ✅ Service Bus uses clean architecture (`core/` components)
2. ⚠️ Queue Storage still uses BaseController (legacy - no breaking changes)
3. 🔄 Gradual migration path: Legacy code still works, new code uses `core/`
4. 🎯 Goal: Eventually deprecate BaseController entirely

### Import Patterns:
```python
# ✅ NEW CODE (Use these)
from core.models import JobRecord, TaskStatus
from core.schema import WorkflowDefinition, OrchestrationInstruction
from core import CoreController, StateManager, OrchestrationManager

# ⚠️ LEGACY CODE (Still works, but marked)
from schema_base import JobRecord, TaskStatus
from schema_workflow import WorkflowDefinition
from controller_base import BaseController
```

### Key Patterns:
- **Composition Over Inheritance**: Components injected, not inherited
- **Single Responsibility**: Each component has one clear purpose
- **Template Method**: ServiceBusListProcessor for list-then-process
- **Strategy Pattern**: Swappable queue processors
- **Clean Imports**: All core imports from `core.*`

---

**Last Updated**: 30 SEP 2025 - Schema migration complete, docs organized, legacy files marked