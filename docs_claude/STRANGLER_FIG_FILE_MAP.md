# Strangler Fig File Classification Map

**Created**: 30 MAR 2026
**Source**: Two-wave cold-read audit (8 Wave 1 + 3 Wave 2 agents, full codebase coverage)
**Purpose**: Authoritative file-level roadmap for Epoch 4 removal at v0.11.0

---

## Classification Key

| Category | Meaning | Action |
|----------|---------|--------|
| **E4** | Epoch 4 only (CoreMachine, Service Bus, Job/Stage/Task) | DELETE at v0.11.0 |
| **E5** | Epoch 5 only (DAG Brain, YAML workflows, atomic handlers) | KEEP |
| **OVERLAP** | Used by both epochs | SIMPLIFY at v0.11.0 (remove E4 imports/branches) |
| **MYSTERY** | Abandoned spikes, one-time scripts | Moved to `docs/archive/mystery_code_mar2026/` on 30 MAR 2026 |

---

## Summary

| Category | File Count | Action |
|----------|-----------|--------|
| E4 — Delete | ~100 | Remove at v0.11.0 (Story 6.1, 6.2) |
| E5 — Keep | ~75 | Production Epoch 5 code |
| OVERLAP — Simplify | ~100 | Remove E4 branches at v0.11.0 |
| MYSTERY — Archived | 7 | Already moved to `docs/archive/` |
| Archive (pre-existing) | ~80+ | `docs/archive/` — bulk delete at 1.0.0 |

**Net reduction at v0.11.0**: ~100 files deleted, ~100 files simplified. ~34% code elimination.

---

## E4 — Delete at v0.11.0

### core/ (13 files)

| File | Purpose | Lines |
|------|---------|-------|
| `core/machine.py` | CoreMachine orchestrator — stage-based job lifecycle | ~2400 |
| `core/machine_factory.py` | Factory for CoreMachine instances | ~100 |
| `core/state_manager.py` | Atomic state management with advisory locks | ~500 |
| `core/orchestration_manager.py` | Dynamic task creation from Stage 1 analysis | ~300 |
| `core/core_controller.py` | Abstract base for Epoch 4 job controllers | ~200 |
| `core/error_handler.py` | CoreMachine-specific error handling | ~150 |
| `core/docker_context.py` | Docker task context for checkpoint resume | ~200 |
| `core/fan_in.py` | Load previous stage results for fan-in handlers | ~100 |
| `core/models/job.py` | JobRecord (QUEUED/PROCESSING/COMPLETED lifecycle) | ~150 |
| `core/models/task.py` | TaskRecord (PENDING/READY/PROCESSING lifecycle) | ~150 |
| `core/models/stage.py` | StageStatus enum and stage advancement | ~80 |
| `core/schema/queue.py` | Service Bus message schemas (JobQueueMessage, TaskQueueMessage) | ~100 |
| `core/schema/orchestration.py` | Dynamic task orchestration instructions | ~150 |
| `core/schema/workflow.py` | Stage-based workflow schema (pre-YAML) | ~100 |

### infrastructure/ (16 files)

| File | Purpose |
|------|---------|
| `infrastructure/service_bus.py` | Azure Service Bus messaging (800+ lines) |
| `infrastructure/checkpoint_manager.py` | Docker task checkpoint/resume |
| `infrastructure/jobs_tasks.py` | JobRepository + TaskRepository for `app.jobs`/`app.tasks` |
| `infrastructure/guardian_repository.py` | SystemGuardian recovery queries (imports ServiceBusRepository) |
| `infrastructure/circuit_breaker.py` | Service Bus circuit breaker |
| `infrastructure/connection_pool.py` | Legacy connection pool management |
| `infrastructure/db_connections.py` | Legacy connection setup |
| `infrastructure/db_auth.py` | Legacy database authentication |
| `infrastructure/db_utils.py` | Legacy database utilities |
| `infrastructure/factory.py` | Creates JobRepository/TaskRepository (E4 only) |
| `infrastructure/diagnostics.py` | QA diagnostics for Epoch 4 |
| `infrastructure/service_layer_client.py` | Service Layer API client (E4 webhook integration) |
| `infrastructure/release_table_repository.py` | Release→table junction CRUD |
| `infrastructure/platform_registry_repository.py` | B2B platform config registry |
| `infrastructure/map_state_repository.py` | Web map configuration CRUD |
| `infrastructure/raster_render_repository.py` | TiTiler render config CRUD |

### services/ — Monolithic Handlers (8 files)

| File | Purpose | Replaced By |
|------|---------|-------------|
| `services/handler_process_raster_complete.py` | Full raster pipeline in one function | `services/raster/handler_*.py` (8 atomics) |
| `services/handler_vector_docker_complete.py` | Full vector pipeline in one function | `services/vector/handler_*.py` (7 atomics) |
| `services/handler_raster_collection_complete.py` | Full tiled raster pipeline | `services/raster/handler_*.py` + fan-out |
| `services/handler_netcdf_to_zarr.py` | Full NetCDF→Zarr pipeline | `services/zarr/handler_*.py` (5 atomics) |
| `services/handler_ingest_zarr.py` | Full Zarr ingest pipeline | `services/zarr/handler_*.py` (5 atomics) |
| `services/handler_vector_multi_source.py` | Full multi-source vector pipeline | vector_multi_source_docker.py + YAML |
| `services/service_hello_world.py` | Epoch 4 test handlers | `workflows/hello_world.yaml` |
| `services/hello_world.py` | Epoch 4 test handler functions | `workflows/hello_world.yaml` |

### jobs/ — Entire Directory (16 files)

| File | Purpose |
|------|---------|
| `jobs/base.py` | JobBase ABC — 6-method contract |
| `jobs/mixins.py` | JobBaseMixin — boilerplate elimination |
| `jobs/raster_mixin.py` | Raster-specific parameter schemas |
| `jobs/raster_workflows_base.py` | DRY finalization for raster collection jobs |
| `jobs/__init__.py` | ALL_JOBS registry and validation |
| `jobs/hello_world.py` | Test job |
| `jobs/validate_raster_job.py` | Standalone raster validation |
| `jobs/stac_catalog_container.py` | Bulk STAC cataloging |
| `jobs/process_raster_docker.py` | Single raster processing |
| `jobs/process_raster_collection_docker.py` | Tiled raster collection |
| `jobs/vector_docker_etl.py` | Vector ETL |
| `jobs/ingest_zarr.py` | Native Zarr ingest |
| `jobs/netcdf_to_zarr.py` | NetCDF→Zarr conversion |
| `jobs/unpublish_raster.py` | Raster unpublish |
| `jobs/unpublish_vector.py` | Vector unpublish |
| `jobs/unpublish_zarr.py` | Zarr unpublish |

**Note**: `jobs/vector_multi_source_docker.py` and `jobs/unpublish_vector_multi_source.py` are marked EPOCH 5 — KEEP.

### triggers/ (26 files)

| File | Purpose |
|------|---------|
| `triggers/submit_job.py` | POST /api/jobs/{job_type} — CoreMachine submission |
| `triggers/get_job_status.py` | GET /api/jobs/status/{job_id} |
| `triggers/get_job_events.py` | GET /api/jobs/{job_id}/events |
| `triggers/get_job_logs.py` | GET /api/jobs/{job_id}/logs |
| `triggers/service_bus/__init__.py` | Service Bus trigger package |
| `triggers/service_bus/job_handler.py` | geospatial-jobs queue handler |
| `triggers/service_bus/task_handler.py` | container-tasks queue handler (already dead code) |
| `triggers/service_bus/error_handler.py` | Dead-letter queue handler |
| `triggers/jobs/delete.py` | DELETE /api/jobs/{job_id} |
| `triggers/jobs/resubmit.py` | POST /api/jobs/{job_id}/resubmit |
| `triggers/promote.py` | Promotion CRUD endpoints |
| `triggers/trigger_map_states.py` | Map state CRUD |
| `triggers/trigger_raster_renders.py` | Render config CRUD |
| `triggers/stac_extract.py` | STAC extraction trigger |
| `triggers/trigger_platform.py` | Legacy platform submit facade |
| `triggers/trigger_platform_status.py` | Legacy platform status |
| `triggers/trigger_platform_catalog.py` | Legacy platform catalog |
| `triggers/janitor/__init__.py` | Janitor package |
| `triggers/janitor/system_guardian.py` | 5-minute SystemGuardian timer |
| `triggers/janitor/http_triggers.py` | Janitor HTTP endpoints |
| `triggers/admin/admin_servicebus.py` | Service Bus admin |
| `triggers/admin/admin_janitor.py` | Janitor admin |
| `triggers/admin/servicebus.py` | Service Bus queue admin |
| `triggers/admin/geo_integrity_timer.py` | Geo integrity timer |
| `triggers/admin/geo_orphan_timer.py` | Geo orphan timer |
| `triggers/admin/geo_table_operations.py` | Geo table operations |

### web_interfaces/ (34 files — 17 modules x 2 files each)

| Module | Purpose |
|--------|---------|
| `web_interfaces/execution/` | CoreMachine job execution viewer |
| `web_interfaces/jobs/` | Job list/detail interface |
| `web_interfaces/tasks/` | Task detail viewer |
| `web_interfaces/pipeline/` | Stage/task graph visualization |
| `web_interfaces/metrics/` | Job performance metrics |
| `web_interfaces/submit/` | Generic job submission form |
| `web_interfaces/submit_raster/` | Raster job form |
| `web_interfaces/submit_vector/` | Vector job form |
| `web_interfaces/submit_raster_collection/` | Raster collection job form |
| `web_interfaces/platform/` | Platform request visualization |
| `web_interfaces/queues/` | Service Bus queue viewer |
| `web_interfaces/database/` | Schema/table explorer |
| `web_interfaces/gallery/` | Promoted datasets gallery |
| `web_interfaces/promote_vector/` | Promote vector form |
| `web_interfaces/promoted_viewer/` | View promoted datasets |
| `web_interfaces/asset_versions/` | Asset version browser |
| `web_interfaces/stac_map/` | STAC map viewer |

### web_dashboard/ (8 files)

| File | Purpose |
|------|---------|
| `web_dashboard/__init__.py` | Dashboard package |
| `web_dashboard/shell.py` | Full page wrapper with tab bar |
| `web_dashboard/base_panel.py` | Abstract panel base |
| `web_dashboard/registry.py` | Panel registry |
| `web_dashboard/panels/__init__.py` | Panels package |
| `web_dashboard/panels/platform.py` | Platform operations tab |
| `web_dashboard/panels/jobs.py` | Job monitoring tab |
| `web_dashboard/panels/data.py` | Data browsing tab |
| `web_dashboard/panels/system.py` | System operations tab |

### config/startup/docker_health (3 files)

| File | Purpose |
|------|---------|
| `config/queue_config.py` | Service Bus queue configuration |
| `startup/service_bus_validator.py` | Service Bus DNS/queue validation |
| `docker_health/classic_worker.py` | Health checks for DB-polling queue worker |

---

## E5 — Keep

### core/ — DAG Engine (18 files)

| File | Purpose |
|------|---------|
| `core/dag_orchestrator.py` | Poll-loop lifecycle controller |
| `core/dag_initializer.py` | WorkflowDefinition → live WorkflowRun |
| `core/dag_transition_engine.py` | PENDING→READY promotions, when-clause evaluation |
| `core/dag_fan_engine.py` | Conditional branching, fan-out, fan-in |
| `core/dag_graph_utils.py` | Pure graph functions (adjacency, reachability) |
| `core/dag_scheduler.py` | Cron-based background workflow submission |
| `core/dag_janitor.py` | Stale task recovery with heartbeat monitoring |
| `core/dag_repository_protocol.py` | Protocol contract for DAG repository |
| `core/workflow_loader.py` | YAML workflow parser with Pydantic validation |
| `core/workflow_registry.py` | In-memory cached registry of YAML workflows |
| `core/param_resolver.py` | Pure parameter resolution from job params + predecessor outputs |
| `core/models/workflow_run.py` | WorkflowRun entity |
| `core/models/workflow_task.py` | WorkflowTask entity |
| `core/models/workflow_task_dep.py` | Task dependency edges |
| `core/models/workflow_definition.py` | YAML workflow schema (Pydantic) |
| `core/models/workflow_enums.py` | WorkflowRunStatus, WorkflowTaskStatus, NodeType |
| `core/models/orchestrator_lease.py` | Distributed mutex for DAG Brain |
| `core/models/schedule.py` | Schedule entity for cron workflows |

### infrastructure/ (12 files)

| File | Purpose |
|------|---------|
| `infrastructure/workflow_run_repository.py` | Atomic DB operations for DAG tables |
| `infrastructure/lease_repository.py` | Distributed mutex via `app.orchestrator_lease` |
| `infrastructure/etl_mount.py` | Mount path management for DAG handlers |
| `infrastructure/release_repository.py` | Versioned release lifecycle CRUD |
| `infrastructure/asset_repository.py` | V0.9 Asset entity CRUD |
| `infrastructure/route_repository.py` | B2C/B2B route records |
| `infrastructure/vault.py` | Key Vault credential broker |
| `infrastructure/api_repository.py` | External API access base class |
| `infrastructure/acled_repository.py` | ACLED conflict data API client |
| `infrastructure/schedule_repository.py` | Schedule CRUD |
| `infrastructure/scheduled_dataset_repository.py` | Scheduled dataset CRUD |
| `infrastructure/zarr_metadata_repository.py` | Zarr metadata CRUD |

### services/ — Atomic DAG Handlers (25 files)

| Module | Files | Purpose |
|--------|-------|---------|
| `services/raster/handler_*.py` | 8 | download, validate, create_cog, upload, persist_app_tables, generate_tiling, process_single_tile, persist_tiled, finalize |
| `services/raster/identifiers.py` | 1 | Deterministic STAC item ID derivation |
| `services/vector/handler_*.py` | 7 | load_source, validate_and_clean, create_and_load_tables, register_catalog, create_split_views, refresh_tipg, finalize |
| `services/stac/handler_*.py` | 2 | materialize_item, materialize_collection |
| `services/zarr/handler_*.py` | 5 | validate_source, download_to_mount, batch_blobs, generate_pyramid, register |
| `services/handler_acled_*.py` | 3 | fetch_and_diff, save_to_bronze, append_to_silver |

### services/ — E5 Business Logic (4 files)

| File | Purpose |
|------|---------|
| `services/asset_service.py` | Asset/Release lifecycle orchestration |
| `services/asset_approval_service.py` | Approval workflow logic |
| `services/promote_service.py` | Dataset promotion system |
| `jobs/vector_multi_source_docker.py` | Multi-source vector ETL (E5 despite JobBase inheritance) |
| `jobs/unpublish_vector_multi_source.py` | Multi-source vector unpublish (E5) |

### workflows/ — YAML Definitions (10 files)

| File | Purpose |
|------|---------|
| `workflows/process_raster.yaml` | Unified raster ETL with approval gate |
| `workflows/vector_docker_etl.yaml` | Vector ETL with approval gate |
| `workflows/ingest_zarr.yaml` | Unified Zarr ingest (NetCDF + native Zarr) |
| `workflows/acled_sync.yaml` | ACLED conflict data sync |
| `workflows/unpublish_raster.yaml` | Raster unpublish DAG |
| `workflows/unpublish_vector.yaml` | Vector unpublish DAG |
| `workflows/unpublish_zarr.yaml` | Zarr unpublish DAG |
| `workflows/hello_world.yaml` | Test workflow |
| `workflows/echo_test.yaml` | Conditional routing test |
| `workflows/test_fan_out.yaml` | Fan-out/fan-in test |

### triggers/ — E5 Endpoints (12 files)

| File | Purpose |
|------|---------|
| `triggers/dag/dag_bp.py` | /api/dag/* diagnostic endpoints |
| `triggers/platform/platform_bp.py` | Platform API blueprint |
| `triggers/platform/submit.py` | POST /api/platform/submit |
| `triggers/platform/unpublish.py` | POST /api/platform/unpublish |
| `triggers/platform/resubmit.py` | POST /api/platform/resubmit |
| `triggers/assets/asset_approvals_bp.py` | Asset approval endpoints |
| `triggers/trigger_approvals.py` | Approve/reject/revoke endpoints |
| `triggers/preflight_checks/dag.py` | DAG infrastructure preflight |
| `docker_health/dag_brain.py` | DAG Brain health checks |
| `ui_routes.py` | DAG Brain admin UI routes |
| `ui_assets_api.py` | Assets API for DAG approval |
| `ui_submit_api.py` | Submit API for DAG workflows |
| `ui/adapters/dag.py` | DAG model→DTO adapter |

---

## OVERLAP — Simplify at v0.11.0

### High-Priority Simplifications

These files have explicit E4 imports or branches that should be removed:

| File | What to Remove |
|------|---------------|
| `core/models/enums.py` | Remove `JobStatus`, `TaskStatus`, `StageStatus` enums |
| `core/logic/transitions.py` | Remove E4 state machine rules |
| `core/__init__.py` | Remove CoreMachine, StateManager exports |
| `services/platform_job_submit.py` | Remove `ServiceBusRepository` + `JobQueueMessage` imports |
| `services/platform_translation.py` | Remove CoreMachine enum imports |
| `services/__init__.py` | Remove E4 monolithic handler registrations |
| `infrastructure/base.py` | Remove `JobStatus`/`TaskStatus` imports |
| `infrastructure/interface_repository.py` | Remove `IJobRepository`/`ITaskRepository` |
| `function_app.py` | Remove Service Bus trigger wiring, keep DAG + shared blueprints |
| `docker_service.py` | Remove classic worker mode, keep Brain + Worker |
| `startup/orchestrator.py` | Remove Service Bus validation steps |
| `ui/adapters/epoch4.py` | DELETE entirely (E4 adapter) |

### Shared Business Logic (keep, remove E4 code paths)

| File | E4 Consumer | E5 Consumer |
|------|-------------|-------------|
| `services/vector/core.py` | handler_vector_docker_complete | vector/handler_*.py |
| `services/vector/postgis_handler.py` | handler_vector_docker_complete | vector/handler_create_and_load_tables |
| `services/vector/helpers.py` | handler_vector_docker_complete | vector/handler_load_source |
| `services/vector/converters.py` | handler_vector_docker_complete | vector/handler_load_source |
| `services/vector/column_sanitizer.py` | handler_vector_docker_complete | vector/handler_validate_and_clean |
| `services/vector/view_splitter.py` | handler_vector_docker_complete | vector/handler_create_split_views |
| `services/raster_cog.py` | handler_process_raster_complete | raster/handler_create_cog |
| `services/raster_validation.py` | handler_process_raster_complete | raster/handler_validate |
| `services/tiling_scheme.py` | handler_raster_collection_complete | raster/handler_generate_tiling_scheme |
| `services/tiling_extraction.py` | handler_raster_collection_complete | raster/handler_process_single_tile |
| `services/unpublish_handlers.py` | unpublish jobs (E4) | unpublish workflows (E5) |
| `services/stac/stac_collection_builder.py` | E4 STAC path | stac/handler_materialize_collection |
| `services/stac/stac_item_builder.py` | E4 STAC path | stac/handler_materialize_item |
| `services/stac_collection.py` | E4 job handler | E5 workflow handler (has TODO: remove pystac) |

### Epoch-Agnostic Data Access (no changes needed)

These serve published data regardless of ingest epoch:

- `ogc_features/` (5 files) — OGC API Features from PostGIS
- `ogc_styles/` (6 files) — CartoSym-JSON styles
- `raster_api/` (4 files) — TiTiler convenience wrapper
- `xarray_api/` (5 files) — Direct Zarr access
- `vector_viewer/` (3 files) — QA viewer for vector collections
- `raster_collection_viewer/` (2 files, service + triggers) — Leaflet raster viewer

### Shared Infrastructure (no E4 coupling, keep as-is)

- `infrastructure/blob.py`, `postgresql.py`, `postgis.py`
- `infrastructure/pgstac_bootstrap.py`, `pgstac_repository.py`
- `infrastructure/h3_repository.py`, `h3_schema.py`, `h3_source_repository.py`, `h3_source_seeds.py`, `h3_batch_tracking.py`
- `infrastructure/auth/` (all 5 files)
- `infrastructure/artifact_repository.py`, `release_audit_repository.py`, `snapshot_repository.py`
- `infrastructure/external_service_repository.py`, `dataset_refs_repository.py`, `promoted_repository.py`
- `infrastructure/database_utils.py`, `data_factory.py`, `duckdb.py`, `duckdb_query.py`
- `infrastructure/metrics_repository.py`, `metrics_blob_logger.py`
- `infrastructure/decorators_blob.py`, `validators.py`, `schema_analyzer.py`
- `infrastructure/platform.py`, `job_event_repository.py`
- `infrastructure/job_progress.py`, `job_progress_contexts.py`
- `infrastructure/appinsights_exporter.py`, `jsonl_log_handler.py`, `service_latency.py`
- `infrastructure/raster_metadata_repository.py`

### Shared Config/Startup/Health (no E4 coupling except where noted)

- All `config/` except `queue_config.py` (E4)
- `startup/state.py`, `startup/__init__.py`, `startup/import_validator.py`
- `docker_health/base.py`, `shared.py`, `runtime.py`, `aggregator.py`, `__init__.py`
- `exceptions.py`, `util_logger.py`, `utils/` (all 4 files)

### Shared Triggers/Admin/Health

- `triggers/__init__.py`, `http_base.py`, `timer_base.py`
- `triggers/health.py`, `livez.py`, `system_health.py`, `probes.py`
- `triggers/preflight.py`, `preflight_checks/` (base, database, environment, runtime, storage)
- `triggers/stac/` (all 4 files), `stac_collections.py`, `stac_nuke.py`, `stac_inspect.py`, `stac_setup.py`
- `triggers/storage_upload.py`, `list_container_blobs.py`, `list_storage_containers.py`, `get_blob_metadata.py`, `analyze_container.py`
- `triggers/schema_pydantic_deploy.py`
- `triggers/timers/` (2 files)
- `triggers/admin/` — most admin endpoints are shared (db_*, snapshot, metadata_consistency_timer, external_service_timer, admin_artifacts, admin_external_services, admin_external_db, admin_approvals, admin_data_migration, admin_system, h3_*, data_cleanup, log_cleanup_timer, system_snapshot_timer)
- `triggers/health_checks/` (all 6 files)

### Shared Web Interfaces

- `web_interfaces/__init__.py`, `base.py`
- `web_interfaces/home/`, `health/`, `docs/`, `redoc/`, `swagger/`
- `web_interfaces/map/`, `storage/`, `upload/`, `integration/`
- `web_interfaces/stac/`, `stac_collection/`, `raster_viewer/`
- `web_interfaces/vector/`, `vector_tiles/`, `vector_viewer/`, `zarr/`
- `web_interfaces/external_services/`, `service_preview/`

### Shared UI Infrastructure

- `ui/__init__.py`, `ui/dto.py`, `ui/features.py`, `ui/navigation.py`, `ui/terminology.py`, `ui/templates_helper.py`
- `ui/adapters/__init__.py`

---

## Deletion Order for v0.11.0

**Phase 1 — Cut the roots** (Story 6.1):
1. Delete `core/machine.py`, `machine_factory.py`, `state_manager.py`, `orchestration_manager.py`, `core_controller.py`, `error_handler.py`, `docker_context.py`, `fan_in.py`
2. Delete `core/models/job.py`, `task.py`, `stage.py`
3. Delete `core/schema/queue.py`, `orchestration.py`, `workflow.py`
4. Delete entire `jobs/` directory (except `vector_multi_source_docker.py`, `unpublish_vector_multi_source.py`)
5. Delete 8 monolithic handlers from `services/`
6. Clean `core/__init__.py`, `core/models/enums.py`, `core/logic/transitions.py`

**Phase 2 — Cut the plumbing** (Story 6.2):
1. Delete `infrastructure/service_bus.py`, `circuit_breaker.py`
2. Delete `triggers/service_bus/` directory
3. Delete `config/queue_config.py`, `startup/service_bus_validator.py`
4. Clean `function_app.py` — remove SB trigger registration
5. Clean `requirements.txt` — remove `azure-servicebus`

**Phase 3 — Cut the vines** (Story 6.1 continued):
1. Delete `infrastructure/jobs_tasks.py`, `guardian_repository.py`, `checkpoint_manager.py`, `factory.py`
2. Delete `infrastructure/connection_pool.py`, `db_connections.py`, `db_auth.py`, `db_utils.py`, `diagnostics.py`
3. Delete `infrastructure/service_layer_client.py`, `release_table_repository.py`, `platform_registry_repository.py`, `map_state_repository.py`, `raster_render_repository.py`
4. Delete E4 triggers (submit_job, get_job_*, jobs/delete, jobs/resubmit, promote, map_states, raster_renders, stac_extract, trigger_platform*, janitor/*)
5. Delete E4 admin triggers (admin_servicebus, admin_janitor, servicebus, geo_*)
6. Delete `docker_health/classic_worker.py`

**Phase 4 — Cut the leaves** (Story 6.1 continued):
1. Delete entire `web_dashboard/` directory
2. Delete 17 E4 `web_interfaces/` modules
3. Delete `ui/adapters/epoch4.py`
4. Clean `docker_service.py` — remove classic worker mode
5. Clean `services/__init__.py` — remove E4 handler registrations
6. Clean `services/platform_job_submit.py` — remove ServiceBus path
7. Clean `services/platform_translation.py` — remove CoreMachine imports

**Phase 5 — Verify** (Story 6.4):
```bash
grep -r "CoreMachine\|JobBase\|JobBaseMixin\|ServiceBus\|service_bus\|processing_queue" --include="*.py" | grep -v docs/ | grep -v archive/
# Should return zero hits
```

---

## Verification Queries

After v0.11.0 cleanup, these greps should return zero hits (excluding docs/archive):

```bash
# Epoch 4 orchestration
grep -r "CoreMachine\|core\.machine\|machine_factory" --include="*.py" | grep -v "docs/"
grep -r "JobBase\|JobBaseMixin\|create_tasks_for_stage" --include="*.py" | grep -v "docs/"
grep -r "StateManager\|state_manager\|orchestration_manager" --include="*.py" | grep -v "docs/"

# Service Bus
grep -r "ServiceBus\|service_bus\|servicebus\|azure-servicebus" --include="*.py" --include="*.txt" | grep -v "docs/"
grep -r "geospatial-jobs\|container-tasks\|stage-complete" --include="*.py" | grep -v "docs/"

# Epoch 4 tables (app.jobs and app.tasks should be empty/dropped)
grep -r "app\.jobs\b\|app\.tasks\b\|JobRepository\|TaskRepository" --include="*.py" | grep -v "docs/" | grep -v "workflow"

# Epoch 4 status enums
grep -r "JobStatus\.\|TaskStatus\.\|StageStatus\." --include="*.py" | grep -v "docs/" | grep -v "Workflow"
```
