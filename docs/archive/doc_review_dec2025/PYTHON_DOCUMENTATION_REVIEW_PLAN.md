# Python Documentation Review Plan

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 14 DEC 2025
**Purpose**: Systematic review of Python file documentation across three tiers
**Scope**: ~170 active Python files (~88,700 lines of code)

---

## Executive Summary

| Tier | Focus | Files | Lines | Current Status |
|------|-------|-------|-------|----------------|
| **Tier 1** | Core Orchestration | ~40 | ~12,200 | Excellent (95%+) |
| **Tier 2** | Services & Business Logic | ~80 | ~39,500 | Very Good (90%+) |
| **Tier 3** | Supporting Infrastructure | ~50 | ~37,000 | Good (85%+) |

**Overall Documentation Coverage**: ~95% of files have module docstrings

---

## Tier 1: Core Orchestration (Critical Foundation)

### Purpose
Files that manage job orchestration, state transitions, base abstractions, factories, registries, and database schema operations. These are the backbone of the system.

### Review Priority: HIGHEST

### Files to Review

#### 1.1 Core Machine & Orchestration (core/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **core/machine.py** | 2,163 | P1 | Universal orchestrator - verify architecture docs |
| **core/state_manager.py** | 924 | P1 | "Last task turns out lights" pattern |
| **core/orchestration_manager.py** | 409 | P1 | Dynamic task creation |
| **core/core_controller.py** | 367 | P2 | Controller coordination |
| **core/schema/sql_generator.py** | 1,275 | P2 | SQL generation |
| **core/schema/geo_table_builder.py** | 601 | P2 | GeoPandas table building |
| **core/schema/orchestration.py** | 527 | P2 | Orchestration instructions |
| **core/schema/workflow.py** | 486 | P2 | Workflow definitions |
| **core/schema/deployer.py** | 485 | P2 | Schema deployment |
| **core/schema/queue.py** | 198 | P3 | Queue schema |
| **core/schema/updates.py** | 109 | P3 | Schema updates |

#### 1.2 Core Models (core/models/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **core/models/platform.py** | 344 | P2 | DDH integration models |
| **core/models/etl.py** | 193 | P2 | ETL operation models |
| **core/models/unpublish.py** | 166 | P2 | Unpublish models |
| **core/models/task.py** | 139 | P2 | Task data model |
| **core/models/results.py** | 123 | P2 | Result models |
| **core/models/job.py** | 125 | P2 | Job record models |
| **core/models/stage.py** | 107 | P3 | Stage definitions |
| **core/models/janitor.py** | 118 | P3 | Cleanup models |
| **core/models/enums.py** | 91 | P3 | Enum definitions |
| **core/models/context.py** | 82 | P3 | Execution context |

#### 1.3 Error Handling & Contracts

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **core/errors.py** | 284 | P1 | Error code definitions |
| **core/error_handler.py** | 202 | P1 | Error handling logic |
| **core/contracts/__init__.py** | 219 | P1 | Contract definitions |
| **exceptions.py** | 134 | P1 | Exception hierarchy |

#### 1.4 Core Utilities

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **core/logic/calculations.py** | 179 | P3 | Business calculations |
| **core/logic/transitions.py** | 163 | P2 | State transitions |
| **core/task_id.py** | 122 | P2 | Task ID generation |
| **core/utils.py** | 50 | P3 | Core utilities |

### Tier 1 Review Checklist
- [ ] Verify CLAUDE CONTEXT headers present and accurate
- [ ] Check docstrings describe "why" not just "what"
- [ ] Validate interface contracts documented
- [ ] Confirm error handling patterns documented
- [ ] Review cross-references to related files

---

## Tier 2: Services & Business Logic

### Purpose
Files that implement job-specific logic, task handlers, data transformations, API endpoints, and business rule enforcement.

### Review Priority: HIGH

### Files to Review

#### 2.1 Job Definitions (jobs/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **jobs/base.py** | 534 | P1 | Abstract JobBase interface |
| **jobs/mixins.py** | 708 | P1 | JobBaseMixin boilerplate |
| **jobs/raster_mixin.py** | 394 | P2 | Raster-specific mixin |
| **jobs/raster_workflows_base.py** | 229 | P2 | Raster workflow base |
| **jobs/process_vector.py** | 447 | P2 | Vector processing |
| **jobs/process_raster_v2.py** | 409 | P2 | Raster v2 pipeline |
| **jobs/process_large_raster_v2.py** | 303 | P2 | Large raster tiling |
| **jobs/process_raster_collection_v2.py** | 193 | P2 | Collection processing |
| **jobs/unpublish_vector.py** | 263 | P2 | Vector unpublish |
| **jobs/unpublish_raster.py** | 256 | P2 | Raster unpublish |
| **jobs/create_h3_base.py** | 417 | P3 | H3 base creation |
| **jobs/bootstrap_h3_land_grid_pyramid.py** | 383 | P3 | H3 pyramid |
| **jobs/generate_h3_level4.py** | 378 | P3 | H3 level 4 |
| **jobs/stac_catalog_container.py** | 380 | P3 | STAC catalog |
| **jobs/stac_catalog_vectors.py** | 297 | P3 | Vector STAC |
| **jobs/process_fathom_stack.py** | 347 | P3 | Fathom stack |
| **jobs/process_fathom_merge.py** | 332 | P3 | Fathom merge |
| **jobs/inventory_fathom_container.py** | 292 | P3 | Fathom inventory |
| **jobs/inventory_container_contents.py** | 258 | P3 | Container inventory |
| **jobs/container_summary.py** | 346 | P3 | Container summary |
| **jobs/validate_raster_job.py** | 333 | P3 | Raster validation |
| **jobs/hello_world.py** | 203 | P3 | Example job |

#### 2.2 Major Services (services/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **services/registry.py** | ~50 | P1 | Task handler registration |
| **services/task.py** | ~70 | P1 | TaskExecutor ABC |
| **services/vector/postgis_handler.py** | 1,445 | P1 | PostGIS vector loading |
| **services/fathom_etl.py** | 1,303 | P2 | Fathom ETL pipeline |
| **services/h3_grid.py** | 1,262 | P2 | H3 grid generation |
| **services/janitor_service.py** | 1,218 | P2 | Cleanup service |
| **services/raster_validation.py** | 1,160 | P2 | Raster validation |
| **services/unpublish_handlers.py** | 708 | P2 | Unpublish handlers |
| **services/container_analysis.py** | 709 | P2 | Container analysis |
| **services/geospatial_inventory.py** | 704 | P2 | Geospatial inventory |
| **services/stac_collection.py** | 689 | P2 | STAC collection |
| **services/tiling_scheme.py** | 672 | P2 | Tiling scheme |
| **services/raster_cog.py** | 632 | P2 | COG creation |
| **services/service_stac_metadata.py** | 621 | P2 | STAC metadata |
| **services/stac_metadata_helper.py** | 586 | P3 | STAC helpers |
| **services/service_blob.py** | 556 | P2 | Blob operations |
| **services/tiling_extraction.py** | 547 | P3 | Tile extraction |
| **services/stac_catalog.py** | 516 | P3 | STAC catalog |
| **services/raster_mosaicjson.py** | 504 | P3 | MosaicJSON |
| **services/vector/tasks.py** | 497 | P2 | Vector tasks |
| **services/vector/process_vector_tasks.py** | 477 | P2 | Vector batch |
| **services/service_stac_setup.py** | 484 | P3 | STAC setup |
| **services/service_stac_vector.py** | 466 | P3 | STAC vector |

#### 2.3 Web Interfaces (web_interfaces/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **web_interfaces/base.py** | 320 | P1 | Base interface class |
| **web_interfaces/__init__.py** | 312 | P1 | Interface registry |
| **web_interfaces/health/interface.py** | 1,273 | P2 | Health dashboard |
| **web_interfaces/docs/interface.py** | 902 | P2 | API docs interface |
| **web_interfaces/stac/interface.py** | 825 | P2 | STAC interface |
| **web_interfaces/pipeline/interface.py** | 821 | P2 | Pipeline interface |
| **web_interfaces/tasks/interface.py** | 641 | P3 | Task interface |
| **web_interfaces/map/interface.py** | 633 | P3 | Map interface |
| **web_interfaces/jobs/interface.py** | 490 | P3 | Jobs interface |
| **web_interfaces/platform/interface.py** | 457 | P3 | Platform interface |
| **web_interfaces/vector/interface.py** | 454 | P3 | Vector interface |
| **web_interfaces/home/interface.py** | 242 | P3 | Home page |

#### 2.4 OGC Features API (ogc_features/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **ogc_features/repository.py** | 1,102 | P1 | PostGIS queries |
| **ogc_features/service.py** | 635 | P1 | Business logic |
| **ogc_features/triggers.py** | 584 | P2 | HTTP endpoints |
| **ogc_features/models.py** | 333 | P2 | Pydantic models |
| **ogc_features/config.py** | 304 | P2 | Configuration |

#### 2.5 STAC API (stac_api/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **stac_api/triggers.py** | 516 | P2 | HTTP endpoints |
| **stac_api/service.py** | 335 | P2 | Business logic |
| **stac_api/config.py** | 44 | P3 | Configuration |

#### 2.6 Vector Converters (vector/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **vector/converter_base.py** | 76 | P2 | Abstract base |
| **vector/converter_registry.py** | 146 | P2 | Registry |
| **vector/converter_helpers.py** | 303 | P3 | Helpers |
| **vector/load_vector_task.py** | 187 | P2 | Load task |
| **vector/csv_converter.py** | 121 | P3 | CSV converter |
| **vector/shapefile_converter.py** | 111 | P3 | Shapefile |
| **vector/kmz_converter.py** | 102 | P3 | KMZ |
| **vector/geopackage_converter.py** | 85 | P3 | GeoPackage |
| **vector/kml_converter.py** | 67 | P3 | KML |
| **vector/geojson_converter.py** | 67 | P3 | GeoJSON |

### Tier 2 Review Checklist
- [ ] Verify job parameters documented
- [ ] Check stage definitions clear
- [ ] Validate task handler contracts
- [ ] Confirm input/output formats documented
- [ ] Review error handling documented

---

## Tier 3: Supporting Infrastructure

### Purpose
Files that provide foundational services, database adapters, configuration management, logging, validation, and utilities.

### Review Priority: MEDIUM

### Files to Review

#### 3.1 Infrastructure (infrastructure/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **infrastructure/postgresql.py** | 1,768 | P1 | Repository pattern |
| **infrastructure/service_bus.py** | 1,689 | P1 | Service Bus abstraction |
| **infrastructure/blob.py** | 1,033 | P1 | Blob storage |
| **infrastructure/base.py** | 555 | P1 | Base repository |
| **infrastructure/factory.py** | 414 | P2 | Repository factory |
| **infrastructure/pgstac_bootstrap.py** | 2,594 | P2 | pgstac bootstrap |
| **infrastructure/validators.py** | 1,359 | P2 | Validation system |
| **infrastructure/jobs_tasks.py** | 1,092 | P2 | Job/Task repository |
| **infrastructure/h3_repository.py** | 689 | P3 | H3 repository |
| **infrastructure/duckdb.py** | 683 | P3 | DuckDB queries |
| **infrastructure/janitor_repository.py** | 682 | P3 | Cleanup repository |
| **infrastructure/interface_repository.py** | 674 | P3 | Interface repository |
| **infrastructure/data_factory.py** | 638 | P3 | Data factory |
| **infrastructure/h3_batch_tracking.py** | 479 | P3 | H3 batch tracking |
| **infrastructure/queue.py** | 390 | P2 | Queue abstraction |
| **infrastructure/pgstac_repository.py** | 376 | P3 | pgstac repository |
| **infrastructure/platform.py** | 269 | P2 | Platform layer |
| **infrastructure/vault.py** | 264 | P3 | Key Vault |
| **infrastructure/database_utils.py** | 226 | P3 | DB utilities |

#### 3.2 Configuration (config/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **config/app_config.py** | 787 | P1 | Main configuration |
| **config/defaults.py** | 678 | P2 | Default values |
| **config/storage_config.py** | 540 | P2 | Storage config |
| **config/database_config.py** | 520 | P2 | Database config |
| **config/platform_config.py** | 444 | P2 | Platform config |
| **config/app_mode_config.py** | 276 | P3 | App mode config |
| **config/h3_config.py** | 231 | P3 | H3 config |
| **config/raster_config.py** | 216 | P3 | Raster config |
| **config/analytics_config.py** | 200 | P3 | Analytics config |
| **config/queue_config.py** | 141 | P3 | Queue config |
| **config/vector_config.py** | 78 | P3 | Vector config |

#### 3.3 HTTP Triggers (triggers/)

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **triggers/http_base.py** | 473 | P1 | Base trigger classes |
| **triggers/submit_job.py** | 303 | P1 | Job submission |
| **triggers/get_job_status.py** | 254 | P2 | Job status |
| **triggers/health.py** | 1,972 | P2 | Health checks |
| **triggers/trigger_platform.py** | 963 | P2 | Platform handling |
| **triggers/trigger_platform_status.py** | 823 | P2 | Platform status |
| **triggers/admin/db_maintenance.py** | 2,312 | P2 | DB maintenance |
| **triggers/admin/db_diagnostics.py** | 1,056 | P3 | DB diagnostics |
| **triggers/admin/db_data.py** | 883 | P3 | DB data |
| **triggers/admin/servicebus.py** | 872 | P3 | Service Bus admin |

#### 3.4 Utilities & Entry Point

| File | Lines | Priority | Review Focus |
|------|-------|----------|--------------|
| **function_app.py** | 2,821 | P1 | Entry point |
| **util_logger.py** | 678 | P1 | Logging system |
| **utils/contract_validator.py** | ~150 | P1 | Type enforcement |
| **utils/import_validator.py** | ~100 | P2 | Import validation |

#### 3.5 Files Needing Documentation (Gaps)

| File | Lines | Issue |
|------|-------|-------|
| **service_stac.py** | 283 | No module docstring |
| **service_statistics.py** | 245 | No module docstring |

### Tier 3 Review Checklist
- [ ] Verify configuration options documented
- [ ] Check connection patterns documented
- [ ] Validate error handling documented
- [ ] Confirm environment variables listed
- [ ] Review security considerations noted

---

## Review Process

### Phase 1: Critical Files (Tier 1 P1)
**Timeline**: First pass
**Files**: ~15 files, ~8,000 lines
**Focus**: Core orchestration, error handling, contracts

### Phase 2: Core Business Logic (Tier 2 P1)
**Timeline**: Second pass
**Files**: ~20 files, ~12,000 lines
**Focus**: Job base, services registry, API handlers

### Phase 3: Infrastructure Foundation (Tier 3 P1)
**Timeline**: Third pass
**Files**: ~10 files, ~10,000 lines
**Focus**: Configuration, repositories, entry point

### Phase 4: Remaining P2 Files
**Timeline**: Fourth pass
**Files**: ~40 files
**Focus**: Secondary services, triggers, interfaces

### Phase 5: P3 Files (Optional)
**Timeline**: As needed
**Files**: ~80 files
**Focus**: Utilities, helpers, minor components

---

## Documentation Standards

### Required Elements (Per File)
1. **Module docstring** - Purpose, exports, dependencies
2. **Class docstrings** - Responsibility, usage pattern
3. **Method docstrings** - Args, returns, raises (for public methods)
4. **Inline comments** - Complex logic explanation

### CLAUDE CONTEXT Header (Optional Enhancement)
```python
# ============================================================================
# CLAUDE CONTEXT - [DESCRIPTIVE_TITLE]
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: [Component type] - [Brief description]
# PURPOSE: [One sentence description]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: [Main classes, functions]
# INTERFACES: [ABC or protocols implemented]
# DEPENDENCIES: [Key external libraries]
# ============================================================================
```

### Exemplary Files (Use as Templates)
- `core/machine.py` - Universal orchestrator documentation
- `core/errors.py` - Error classification documentation
- `jobs/base.py` - Abstract interface documentation
- `jobs/mixins.py` - Mixin with quick-start guide
- `infrastructure/postgresql.py` - Repository pattern documentation
- `util_logger.py` - Utility documentation
- `triggers/http_base.py` - Trigger documentation
- `ogc_features/service.py` - Service layer documentation

---

## Metrics

### Current State
- **Files with docstrings**: ~95% (160+ files)
- **Files with CLAUDE headers**: ~15 files (exemplary)
- **Files missing docstrings**: 2 files (service_stac.py, service_statistics.py)

### Target State
- **Files with docstrings**: 100%
- **Files with CLAUDE headers**: All Tier 1 P1 files
- **Documentation quality**: Consistent across tiers

---

**Last Updated**: 14 DEC 2025
