# File Catalog

**Date**: 20 NOV 2025 (Professional Documentation Cleanup)
**Total Python Files**: 203 (actual count)
**Total Code Lines**: 79,713
**Purpose**: Quick file lookup with one-line descriptions
**Status**: Updated with complete file inventory

## 📊 Quick Stats
- **Root Python files**: 6
- **Config module**: 7 files (modular configuration)
- **Core module**: 17 files (orchestration, models, state management)
- **Infrastructure**: 16 files (repositories, blob, database, service bus)
- **Jobs**: 18 files (workflow definitions using JobBase ABC)
- **Services**: 43 files (business logic and handlers)
- **Triggers**: 21 files (HTTP/Service Bus endpoints)
- **Vector module**: 12 files (format converters and handlers)
- **Web interfaces**: 12 files (HTML UI for jobs, STAC, vectors)
- **OGC Features**: 6 files (OGC API - Features implementation)
- **STAC API**: 4 files (STAC specification endpoints)
- **Models**: 2 files (Pydantic model definitions)
- **Utils**: 4 files (utilities and validators)
- **Tests**: 13 files (unit and integration tests)

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

## 📁 Directory Structure (18 folders)

| Directory | Purpose | Key Contents |
|-----------|---------|--------------|
| `config/` | Modular configuration system | 7 files - app, database, queue, raster, storage, vector config |
| `core/` | Clean architecture implementation (CoreMachine) | 17 files - orchestration, models, state management |
| `docs/` | Archived documentation | Legacy docs moved from root |
| `docs_claude/` | PRIMARY documentation for Claude | TODO.md, HISTORY.md, context docs |
| `infrastructure/` | Repository pattern implementations | 16 files - blob, postgresql, service bus, duckdb |
| `jobs/` | Job workflow definitions | 18 files - all inherit from JobBase ABC |
| `models/` | Additional Pydantic models | 2 files - band_mapping, h3_base |
| `ogc_features/` | OGC API - Features Core 1.0 | 6 files - standalone vector features API |
| `services/` | Business logic and handlers | 43 files - raster, vector, STAC, container ops |
| `sql/` | SQL scripts and migrations | Database schema definitions |
| `stac_api/` | STAC API specification | 4 files - STAC catalog endpoints |
| `test/` | Test files and fixtures | 13 files - unit and integration tests |
| `tests/` | Additional test files | 1 file - managed identity tests |
| `triggers/` | Azure Function HTTP/Service Bus triggers | 21 files - API endpoints and processors |
| `utils/` | Utility modules | 4 files - contract validator, import validator |
| `vector/` | Vector processing utilities | 12 files - format converters |
| `vector_viewer/` | Vector visualization interface | 3 files - web UI for vector data |
| `web_interfaces/` | HTML interfaces for system components | 12 files - jobs, STAC, tasks, vectors UIs |

## ⚙️ Configuration System (config/ folder, 7 files)

| File | Purpose |
|------|---------|
| `config/__init__.py` | Configuration module exports and initialization |
| `config/app_config.py` | Application-wide configuration settings |
| `config/database_config.py` | PostgreSQL, PostGIS, pgSTAC database settings |
| `config/queue_config.py` | Azure Service Bus and Queue Storage configuration |
| `config/raster_config.py` | Raster processing, COG generation, tiling parameters |
| `config/storage_config.py` | Azure Blob Storage container and tier configuration |
| `config/vector_config.py` | Vector ingestion and PostGIS table settings |

## 🏗️ Core Architecture (core/ folder, 17 files)

### Core Controllers & Managers (4 files)
| File | Purpose |
|------|---------|
| `core/machine.py` | CoreMachine orchestration for job and task processing with fan-out support |
| `core/task_id.py` | Deterministic task ID generation for lineage tracking |
| `core/state_manager.py` | Database operations with advisory locks using composition pattern |
| `core/orchestration_manager.py` | Dynamic task creation for Service Bus batch optimization |

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

## 💾 Infrastructure Layer (16 files in infrastructure/ folder)

| File | Purpose |
|------|---------|
| `infrastructure/__init__.py` | Infrastructure module exports |
| `infrastructure/base.py` | Common repository patterns and validation |
| `infrastructure/blob.py` | Azure Blob Storage operations with managed identity |
| `infrastructure/database_utils.py` | Database utility functions and helpers |
| `infrastructure/decorators_blob.py` | Fail-fast validation decorators for blob operations |
| `infrastructure/duckdb.py` | DuckDB analytical query engine with spatial extensions |
| `infrastructure/duckdb_query.py` | DuckDB query execution and result handling |
| `infrastructure/factory.py` | Central factory for all repository instances |
| `infrastructure/h3_repository.py` | H3 grid system database operations |
| `infrastructure/interface_repository.py` | Repository interface definitions |
| `infrastructure/jobs_tasks.py` | Job and task management with batch operations |
| `infrastructure/pgstac_bootstrap.py` | pgSTAC schema bootstrap and installation |
| `infrastructure/pgstac_repository.py` | pgSTAC catalog operations and queries |
| `infrastructure/platform.py` | Platform layer database operations |
| `infrastructure/postgis.py` | PostGIS vector data operations |
| `infrastructure/postgresql.py` | PostgreSQL connection and query execution |
| `infrastructure/queue.py` | Queue Storage operations with singleton pattern |
| `infrastructure/service_bus.py` | Service Bus implementation with batch support |
| `infrastructure/vault.py` | Azure Key Vault integration |

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

## 📋 Job Workflows (18 files in jobs/ folder)

### Core Infrastructure (2 files)
| File | Purpose |
|------|---------|
| `jobs/base.py` | JobBase ABC enforcing 5 required methods |
| `jobs/__init__.py` | Job registry (ALL_JOBS dict) and validation |
| `jobs/mixins.py` | JobBaseMixin for declarative job creation (77% code reduction) |

### Job Implementations (All inherit from JobBase)
| File | Purpose | Stages |
|------|---------|--------|
| `jobs/bootstrap_h3_land_grid_pyramid.py` | H3 land grid pyramid generation | Multi-stage |
| `jobs/container_list.py` | Container blob listing with fan-out | 2-stage |
| `jobs/container_list_diamond.py` | Container list with diamond pattern | Multi-stage |
| `jobs/container_summary.py` | Container summary analysis | 1-stage |
| `jobs/create_h3_base.py` | H3 base grid generation (resolutions 0-4) | 1-stage |
| `jobs/generate_h3_level4.py` | H3 level 4 hierarchical expansion | 1-stage |
| `jobs/hello_world.py` | Hello World testing workflow | 2-stage |
| `jobs/hello_world_mixin.py` | Hello World using JobBaseMixin (test implementation) | 2-stage |
| `jobs/hello_world_original_backup.py` | Original hello_world backup | 2-stage |
| `jobs/ingest_vector.py` | Vector file ingestion to PostGIS | Multi-stage |
| `jobs/process_large_raster.py` | Large raster tiling and COG generation | Multi-stage |
| `jobs/process_raster.py` | Standard raster processing workflow | Multi-stage |
| `jobs/process_raster_collection.py` | Batch raster collection processing | Multi-stage |
| `jobs/stac_catalog_container.py` | STAC catalog from container contents | Multi-stage |
| `jobs/stac_catalog_vectors.py` | STAC catalog from vector tables | Multi-stage |
| `jobs/validate_raster_job.py` | Raster validation workflow | Multi-stage |

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

## 🔧 Utilities (4 files in utils/ folder)

| File | Purpose |
|------|---------|
| `utils/__init__.py` | Utilities module exports |
| `utils/contract_validator.py` | Runtime type enforcement decorator |
| `utils/import_validator.py` | Module import validation and health checks |
| `utils/test_raster_generator.py` | Test raster file generation utilities |

## 🗺️ OGC Features API (6 files in ogc_features/ folder)

| File | Purpose |
|------|---------|
| `ogc_features/__init__.py` | OGC Features module exports |
| `ogc_features/config.py` | OGC API configuration and settings |
| `ogc_features/models.py` | Pydantic models for OGC Features responses |
| `ogc_features/repository.py` | PostGIS queries for vector features |
| `ogc_features/service.py` | Business logic for OGC Features operations |
| `ogc_features/triggers.py` | HTTP triggers for OGC Features endpoints |

## 📦 STAC API (4 files in stac_api/ folder)

| File | Purpose |
|------|---------|
| `stac_api/__init__.py` | STAC API module exports |
| `stac_api/config.py` | STAC API configuration settings |
| `stac_api/service.py` | pgSTAC query execution and response formatting |
| `stac_api/triggers.py` | HTTP triggers for STAC specification endpoints |

## 🌐 Web Interfaces (12 files in web_interfaces/ folder)

| File | Purpose |
|------|---------|
| `web_interfaces/__init__.py` | Web interfaces module exports |
| `web_interfaces/base.py` | Base HTML interface generation |
| `web_interfaces/docs/__init__.py` | Documentation UI module |
| `web_interfaces/jobs/__init__.py` | Jobs UI module |
| `web_interfaces/jobs/interface.py` | HTML interface for job management |
| `web_interfaces/stac/__init__.py` | STAC UI module |
| `web_interfaces/stac/interface.py` | HTML interface for STAC browsing |
| `web_interfaces/tasks/__init__.py` | Tasks UI module |
| `web_interfaces/tasks/interface.py` | HTML interface for task monitoring |
| `web_interfaces/vector/__init__.py` | Vector UI module |
| `web_interfaces/vector/interface.py` | HTML interface for vector data browsing |

## 📐 Vector Processing (12 files in vector/ folder)

| File | Purpose |
|------|---------|
| `vector/converter_base.py` | Abstract base class for format converters |
| `vector/converter_helpers.py` | Helper functions for vector conversion |
| `vector/converter_registry.py` | Registry for vector format converters |
| `vector/converters_init.py` | Converter initialization and registration |
| `vector/csv_converter.py` | CSV to PostGIS converter |
| `vector/geojson_converter.py` | GeoJSON to PostGIS converter |
| `vector/geopackage_converter.py` | GeoPackage to PostGIS converter |
| `vector/kml_converter.py` | KML to PostGIS converter |
| `vector/kmz_converter.py` | KMZ to PostGIS converter |
| `vector/load_vector_task.py` | Vector loading task orchestration |
| `vector/shapefile_converter.py` | Shapefile to PostGIS converter |

## 🎨 Vector Viewer (3 files in vector_viewer/ folder)

| File | Purpose |
|------|---------|
| `vector_viewer/__init__.py` | Vector viewer module exports |
| `vector_viewer/service.py` | Vector data retrieval and formatting |
| `vector_viewer/triggers.py` | HTTP triggers for vector visualization |

## 🚀 Trigger Handlers (21 files in triggers/ folder)

### Core Triggers (11 files)
| File | Purpose |
|------|---------|
| `triggers/__init__.py` | Triggers module exports |
| `triggers/analyze_container.py` | Container analysis HTTP trigger |
| `triggers/get_job_status.py` | Job status query endpoint |
| `triggers/health.py` | System health check endpoint |
| `triggers/http_base.py` | Base class for HTTP triggers |
| `triggers/ingest_vector.py` | Vector ingestion HTTP trigger |
| `triggers/poison_monitor.py` | Poison queue monitoring timer trigger |
| `triggers/schema_pydantic_deploy.py` | Pydantic-driven schema deployment |
| `triggers/submit_job.py` | CoreMachine job submission endpoint |
| `triggers/trigger_platform.py` | Platform layer request submission |
| `triggers/trigger_platform_status.py` | Platform request status monitoring |

### Admin Triggers (9 files in triggers/admin/)
| File | Purpose |
|------|---------|
| `triggers/admin/__init__.py` | Admin triggers module exports |
| `triggers/admin/db_data.py` | Database data inspection endpoints |
| `triggers/admin/db_diagnostics.py` | Database diagnostics and health checks |
| `triggers/admin/db_health.py` | Database connection health monitoring |
| `triggers/admin/db_maintenance.py` | Database maintenance operations (nuke, redeploy) |
| `triggers/admin/db_queries.py` | Database query endpoints for jobs and tasks |
| `triggers/admin/db_schemas.py` | Database schema inspection |
| `triggers/admin/db_tables.py` | Database table management |
| `triggers/admin/h3_debug.py` | H3 grid debugging endpoints |
| `triggers/admin/servicebus.py` | Service Bus administration |

### STAC Triggers (7 files)
| File | Purpose |
|------|---------|
| `triggers/stac_collections.py` | STAC collections listing endpoint |
| `triggers/stac_extract.py` | STAC metadata extraction trigger |
| `triggers/stac_init.py` | pgSTAC initialization endpoint |
| `triggers/stac_inspect.py` | STAC catalog inspection tools |
| `triggers/stac_nuke.py` | STAC catalog cleanup endpoint |
| `triggers/stac_setup.py` | STAC setup and configuration |
| `triggers/stac_vector.py` | STAC vector catalog operations |

### Test Triggers (1 file)
| File | Purpose |
|------|---------|
| `triggers/test_raster_create.py` | Test raster generation endpoint |

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