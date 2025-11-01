# File Catalog

**Date**: 31 OCT 2025 (Process Large Raster Execution Trace Added)
**Total Python Files**: 140 (actual count)
**Purpose**: Quick file lookup with one-line descriptions
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ Updated - Added PROCESS_LARGE_RASTER_EXECUTION_TRACE.md documentation

## 📊 Quick Stats (Updated 29 OCT 2025)
- **Root Python files**: 6
- **Root documentation**: 26 markdown files (25 + CODE_QUALITY_REVIEW)
- **Platform documentation**: 4 new files (hello_world, enum patterns, fixes, boundary analysis)
- **Core directories**: 12 folders
- **Infrastructure**: 13 files (added decorators_blob.py)
- **Services**: 30+ files (added vector/postgis_handler_enhanced.py, vector/tasks_enhanced.py)
- **Triggers**: 11 files (added Platform layer: trigger_platform.py, trigger_platform_status.py)
- **Jobs**: 12 files (all using JobBase ABC)

## 🎯 Root Level Files (32 files)

### Core Entry Points (6 Python files)
| File | Purpose | Lines |
|------|---------|-------|
| `function_app.py` | Azure Functions entry point - HTTP, Queue, Service Bus, Timer triggers | 62,167 |
| `config.py` | Strongly typed configuration with Pydantic v2 - includes COG tier profiles | 40,758 |
| `exceptions.py` | Custom exception hierarchy for business logic vs contract violations | 4,092 |
| `util_logger.py` | Centralized logging factory with component types for structured logs | 21,109 |
| `service_stac.py` | STAC metadata extraction and catalog operations | 10,288 |
| `service_statistics.py` | Statistical analysis services for data processing | 10,150 |

### Configuration Files (6 files)
| File | Purpose |
|------|---------|
| `host.json` | Azure Functions runtime configuration (retry, logging, extensions) |
| `requirements.txt` | Python dependencies - Azure SDKs, GDAL, psycopg, etc. |
| `local.settings.json` | Local development environment variables (not in git) |
| `local.settings.example.json` | Template for local settings configuration |
| `docker-compose.yml` | Local PostgreSQL + pgAdmin for development |
| `import_validation_registry.json` | Auto-discovered module import health tracking |

### Documentation Files (25 markdown files) ⭐ UPDATED 29 OCT

#### Platform Layer Documentation ⭐ NEW 25-29 OCT (4 files)
| File | Purpose | Status |
|------|---------|--------|
| `PLATFORM_HELLO_WORLD.md` | ⭐ Platform layer hello_world reference implementation (fractal pattern demo) | ✅ NEW 29 OCT |
| `PLATFORM_PYDANTIC_ENUM_PATTERNS.md` | ⭐ Platform/CoreMachine enum consistency patterns (JobStatus, DataType) | ✅ NEW 29 OCT |
| `PLATFORM_LAYER_FIXES_TODO.md` | Platform layer known issues and fixes (26 OCT 2025) | Reference |
| `PLATFORM_BOUNDARY_ANALYSIS.md` | Platform vs CoreMachine boundary analysis | Architecture |

#### Core Documentation (21 files)
| File | Purpose | Status |
|------|---------|--------|
| `CLAUDE.md` | Primary entry point redirecting to docs_claude/ | ⭐ START HERE |
| `CODE_QUALITY_REVIEW_29OCT2025.md` | ⭐ Code quality review - Platform + vector services documentation audit | ✅ NEW 29 OCT |
| `RASTER_PIPELINE.md` | Comprehensive raster ETL workflow documentation | Production guide |
| `COG_MOSAIC.md` | MosaicJSON generation from COG tiles | Technical spec |
| `STAC_IMPLEMENTATION_PLAN.md` | STAC catalog implementation roadmap | Planning doc |
| `VECTOR_ETL_IMPLEMENTATION_PLAN.md` | Vector ingestion pipeline design | Implementation guide |
| `H3.md` | H3 hexagon grid system documentation | Reference |
| `ARCHITECTURE_REVIEW.md` | System architecture analysis and patterns | Technical review |
| `JOB_CREATION_QUICKSTART.md` | Guide for creating new job types | Developer guide |
| `COREMACHINE_STATUS_TRANSITION_FIX.md` | Bug fix documentation for status transitions | Fixed 21 OCT |
| `DIAMOND_PATTERN_TEST.md` | Fan-out/fan-in workflow testing | Test results |
| `FINAL_STATUS_24OCT2025.md` | System status checkpoint | Status report |
| `PHASE_2_DEPLOYMENT_GUIDE.md` | Phase 2 deployment procedures | Deployment guide |
| `POSTGRES_REQUIREMENTS.md` | PostgreSQL setup and requirements | Infrastructure |
| `PYTHON_HEADER_REVIEW_TRACKING.md` | Code header standardization tracking | Maintenance |
| `QUICK_FIX_GUIDE.md` | Common fixes and troubleshooting | Operations |
| `ROOT_CLEANUP_ANALYSIS.md` | Analysis of root folder organization | Cleanup plan |
| `ABC_ENFORCEMENT_OPPORTUNITIES.md` | Abstract base class implementation opportunities | Architecture |
| `duckdb_parameter.md` | DuckDB configuration parameters | Reference |
| `vector_api.md` | Vector API endpoint documentation | API reference |
| `robertnotes.md` | Robert's personal development notes | Notes |

## 📁 Directory Structure (12 folders)

| Directory | Purpose | Key Contents |
|-----------|---------|--------------|
| `core/` | Clean architecture implementation (CoreMachine) | 17 files - orchestration, models, state management |
| `docs/` | Archived documentation | Legacy docs moved from root |
| `docs_claude/` | ⭐ PRIMARY documentation for Claude | TODO.md, HISTORY.md, context docs |
| `infrastructure/` | Repository pattern implementations | 12 files - blob, postgresql, service bus, duckdb |
| `jobs/` | Job workflow definitions | 12 files - all inherit from JobBase ABC |
| `models/` | Additional Pydantic models | Supporting data models |
| `services/` | Business logic and handlers | 30+ files - raster, vector, STAC, container ops |
| `sql/` | SQL scripts and migrations | Database schema definitions |
| `test/` | Test files and fixtures | Unit and integration tests |
| `triggers/` | Azure Function HTTP triggers | 7+ files - API endpoints |
| `utils/` | Utility modules | Contract validator (moved from root) |
| `vector/` | Vector processing utilities | Vector-specific operations |

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

## 💾 Infrastructure Layer (13 files in infrastructure/ folder) ⭐ UPDATED 29 OCT

| File | Purpose | Status |
|------|---------|--------|
| `infrastructure/base.py` | Common repository patterns and validation | ✅ Working |
| `infrastructure/factory.py` | Central factory for all repository instances (includes DuckDB) | ✅ Updated 10 OCT |
| `infrastructure/jobs_tasks.py` | Business logic for job and task management + batch operations | ✅ Working |
| `infrastructure/postgresql.py` | PostgreSQL-specific implementation with psycopg | ✅ Working |
| `infrastructure/blob.py` | Azure Blob Storage operations with managed identity + decorator validation | ✅ Updated 29 OCT |
| `infrastructure/decorators_blob.py` | ⭐ NEW - Fail-fast validation decorators for blob operations (@validate_container, @validate_blob) | ✅ NEW 28 OCT |
| `infrastructure/queue.py` | Queue Storage operations with singleton pattern | ✅ Working |
| `infrastructure/service_bus.py` | Service Bus implementation with batch support | ✅ Working |
| `infrastructure/vault.py` | Azure Key Vault integration (currently disabled) | ⚠️ Disabled |
| `infrastructure/stac.py` | pgSTAC operations for STAC catalog | ✅ Working |
| `infrastructure/duckdb.py` | DuckDB analytical query engine with spatial+azure extensions | ✅ Working 10 OCT |
| `infrastructure/interface_repository.py` | Repository interfaces (IJobRepository, ITaskRepository, IDuckDBRepository) | ✅ Updated 10 OCT |
| `infrastructure/__init__.py` | Infrastructure module exports | ✅ Working |

## ⚙️ Services (services/ folder) ⭐ UPDATED 29 OCT

### Core Services (5 files - Root Level)
| File | Purpose |
|------|---------|
| `services/service_hello_world.py` | Hello World task processing logic |
| `services/service_blob.py` | Blob storage service handlers |
| `services/service_stac_setup.py` | STAC setup service |
| `services/container_summary.py` | Container aggregate statistics handler |
| `services/container_list.py` | Container blob listing and analysis handlers |

### Raster Services (services/ - Root Level)
| File | Purpose |
|------|---------|
| `services/raster_validation.py` | Raster validation and metadata extraction |
| `services/raster_cog.py` | COG (Cloud Optimized GeoTIFF) generation |
| `services/tiling_scheme.py` | Tiling scheme generation for large rasters |
| `services/tiling_extraction.py` | Tile extraction from large rasters |

### Vector Services (services/vector/ subfolder) ⭐ NEW 26 OCT
| File | Purpose | Status |
|------|---------|--------|
| `services/vector/postgis_handler_enhanced.py` | ⭐ NEW - Enhanced PostGIS ingestion with comprehensive error handling | ✅ NEW 26 OCT |
| `services/vector/tasks_enhanced.py` | ⭐ NEW - Enhanced vector ETL task handlers with granular error tracking | ✅ NEW 26 OCT |
| `services/vector/converters.py` | Format-specific converters (CSV, GeoJSON, Shapefile, KML, etc.) | ✅ Working |

## 📋 Job Workflows (12 files in jobs/ folder) ⭐ UPDATED 15 OCT 2025

### Core Infrastructure (2 files)
| File | Purpose | Status |
|------|---------|--------|
| `jobs/base.py` | ⭐ NEW - JobBase ABC enforcing 5 required methods (Phase 2) | ✅ Active 15 OCT |
| `jobs/__init__.py` | Job registry (ALL_JOBS dict) + validation | ✅ Updated 15 OCT |

### Job Implementations (10 files) - All inherit from JobBase
| File | Purpose | Stages | Status |
|------|---------|--------|--------|
| `jobs/hello_world.py` | Hello World testing workflow | 2-stage | ✅ Updated 15 OCT |
| `jobs/create_h3_base.py` | ⭐ H3 base grid generation (resolutions 0-4) | 1-stage | ✅ Updated 15 OCT |
| `jobs/generate_h3_level4.py` | ⭐ H3 level 4 hierarchical expansion | 1-stage | ✅ Updated 15 OCT |
| `jobs/ingest_vector.py` | Vector file ingestion to PostGIS | Multi-stage | ✅ Updated 15 OCT |
| `jobs/validate_raster_job.py` | Raster validation workflow | Multi-stage | ✅ Updated 15 OCT |
| `jobs/container_summary.py` | Container summary analysis | 1-stage | ✅ Updated 15 OCT |
| `jobs/container_list.py` | Container listing with fan-out | 2-stage | ✅ Updated 15 OCT |
| `jobs/stac_catalog_container.py` | STAC catalog from container contents | Multi-stage | ✅ Updated 15 OCT |
| `jobs/stac_catalog_vectors.py` | STAC catalog from vector tables | Multi-stage | ✅ Updated 15 OCT |
| `jobs/process_raster.py` | Raster processing workflow | Multi-stage | ✅ Updated 15 OCT |

**⭐ Phase 2 Migration Complete (15 OCT 2025)**:
- All 10 jobs now inherit from `JobBase` ABC
- ABC enforces 5 required methods at class definition time
- Removed deprecated files: `jobs/workflow.py`, `jobs/registry.py`
- Zero behavior changes - only interface enforcement added

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

## ⚙️ Trigger Handlers (triggers/ folder) ⭐ UPDATED 29 OCT

### HTTP Triggers - CoreMachine (7 files)
| File | Purpose | Status |
|------|---------|--------|
| `triggers/health.py` | Health check endpoint with import validation | ✅ Active |
| `triggers/submit_job.py` | CoreMachine job submission HTTP trigger | ✅ Active |
| `triggers/list_jobs.py` | Job listing endpoint | ✅ Active |
| `triggers/job_status.py` | Job status query endpoint | ✅ Active |
| `triggers/db_admin.py` | Database administration endpoints (schema deployment, nuke) | ✅ Active |
| `triggers/db_query.py` | ⭐ Database query endpoints - CoreMachine (jobs, tasks) + Platform (api_requests, orchestration_jobs) | ✅ Updated 29 OCT |
| `triggers/container.py` | Container operation triggers | ✅ Active |

### HTTP Triggers - Platform Layer ⭐ NEW 25-29 OCT
| File | Purpose | Status |
|------|---------|--------|
| `triggers/trigger_platform.py` | ⭐ NEW - Platform request submission (DDH orchestration above CoreMachine) | ✅ NEW 25 OCT |
| `triggers/trigger_platform_status.py` | ⭐ NEW - Platform request status monitoring with job aggregation | ✅ NEW 25 OCT |

**Platform Layer Pattern**:
- External applications (DDH) submit requests to Platform layer
- Platform orchestrator determines which CoreMachine jobs to create
- "Turtle above CoreMachine" - business logic orchestration
- Single Platform request → Multiple CoreMachine jobs
- Status endpoint aggregates all job results

### Service Bus Triggers (1 file)
| File | Purpose |
|------|---------|
| `triggers/trigger_job_processor.py` | Service Bus job queue processor - CoreMachine orchestration |

### Schema Deployment (1 file)
| File | Purpose |
|------|---------|
| `triggers/schema_pydantic_deploy.py` | Pydantic-driven schema deployment with Platform schema support |

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
| `PROCESS_LARGE_RASTER_EXECUTION_TRACE.md` | ⭐ NEW 31 OCT - Complete execution trace from HTTP → Job Complete |
| `COREMACHINE_PLATFORM_ARCHITECTURE.md` | Two-layer architecture (Platform + CoreMachine) |
| `SERVICE_BUS_HARMONIZATION.md` | Three-layer config architecture for Service Bus + Functions |

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

## 🦆 DuckDB Analytical Infrastructure (NEW 10 OCT 2025)

### Overview
DuckDB provides serverless analytical queries over Azure Blob Storage with spatial analytics capabilities.

### Key Capabilities
- **Serverless Parquet Queries**: Query Parquet files in blob storage WITHOUT downloading (10-100x faster)
- **Spatial Extension**: PostGIS-like ST_* functions for geometry operations
- **Azure Extension**: Direct az:// protocol access to Azure Blob Storage
- **GeoParquet Export**: Write spatial data to GeoParquet format for Gold tier
- **In-Memory Analytics**: Fast columnar queries with vectorized execution

### Architecture Integration
```python
from infrastructure.factory import RepositoryFactory

# Get DuckDB repository
duckdb_repo = RepositoryFactory.create_duckdb_repository()

# Query Parquet in blob storage (NO DOWNLOAD!)
result = duckdb_repo.read_parquet_from_blob('rmhazuregeosilver', 'exports/*.parquet')
df = result.df()

# Export to GeoParquet
metadata = duckdb_repo.export_geoparquet(df, '/tmp/output.parquet')
```

### Configuration (config.py)
- `duckdb_connection_type`: "memory" (default) or "persistent"
- `duckdb_enable_spatial`: PostGIS-like functions (default: True)
- `duckdb_enable_azure`: Blob storage queries (default: True)
- `duckdb_memory_limit`: Optional memory limit (e.g., "1GB")
- `duckdb_threads`: Optional thread count (default: auto-detect)

### Health Monitoring
DuckDB is an **optional component** in `/api/health`:
- Status: "healthy", "not_installed", or "error"
- Extensions: spatial, azure, httpfs availability
- Connection: memory/persistent mode status
- Impact: GeoParquet exports and serverless queries

### Use Cases
1. **Gold Tier Exports**: Generate GeoParquet files for data products
2. **Analytical Queries**: Fast aggregations over historical data
3. **Serverless Processing**: Query blob Parquet without data movement
4. **Spatial Analytics**: Complex geometry operations without PostGIS

---

**Last Updated**: 29 OCT 2025 - Added Platform database query endpoints (api_requests, orchestration_jobs)