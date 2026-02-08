# Project History

**Last Updated**: 21 JAN 2026
**Active Log**: Dec 2025 - Present
**Rolling Archive**: When this file exceeds ~600 lines, older content is archived with a UUID filename.

**Archives** (chronological):
- [HISTORY_26e76e95.md](./HISTORY_26e76e95.md) - Sep-Nov 2025 (4,500+ lines)
- [HISTORY_ARCHIVE_DEC2025.md](./HISTORY_ARCHIVE_DEC2025.md) - TODO.md cleanup archive

This document tracks completed architectural changes and improvements to the Azure Geospatial ETL Pipeline.

---

## 07 FEB 2026: STAC Architecture - Optional Cataloging for Vectors ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure
**Impact**: STAC is now purely for discovery, not application logic

### Architecture Decision

**Before**: All vectors were automatically added to a `system-vectors` STAC collection, duplicating metadata from `geo.table_catalog`.

**After**: STAC cataloging is optional. Users must explicitly provide `collection_id` to create STAC items. This enables:
- Mixed raster/vector collections (future)
- User-defined collection organization
- STAC as pure discovery layer (not application logic)

### Key Principle

> **STAC is for discovery, not application logic.**
> `geo.table_catalog` is the source of truth for vector metadata.
> OGC Features API reads from `table_catalog`, not STAC.

### Changes Made

| File | Change |
|------|--------|
| `config/defaults.py` | Removed `VECTOR_COLLECTION`, `SYSTEM_COLLECTIONS = []`, removed `system-vectors` from `COLLECTION_METADATA` |
| `infrastructure/pgstac_bootstrap.py` | `get_system_stac_collections()` now returns `[]` |
| `services/stac_vector_catalog.py` | `collection_id` is now required (validation error if missing) |
| `jobs/process_vector.py` | Stage 3 is conditional on `collection_id`, added `stac_item_id` parameter |

### process_vector Job Changes

**New Parameters**:
- `collection_id` (optional) - STAC collection to add item to
- `stac_item_id` (optional) - Custom STAC item ID

**Stage 3 Behavior**:
- If `collection_id` provided: Creates STAC item in specified collection
- If `collection_id` omitted: Stage 3 skipped, no STAC item created

**Job Result** (when STAC skipped):
```json
{
  "stac": {
    "stac_skipped": true,
    "stac_item_created": false,
    "reason": "No collection_id provided - STAC cataloging skipped (data accessible via OGC Features API)"
  }
}
```

### Data Access Without STAC

Vector data remains fully accessible:
- **OGC Features API**: `/api/features/collections/{schema}-{table}/items`
- **Vector Tiles**: TiPG MVT endpoints
- **Metadata**: `geo.table_catalog` (source of truth)

---

## 21 JAN 2026: Docker Worker Application Insights AAD Auth Fix ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure
**Feature**: F7.12.E Docker Worker OpenTelemetry

### Problem

Docker worker logs were not appearing in Application Insights. Investigation revealed three issues:
1. Wrong App Insights connection string (different instrumentation key)
2. App Insights has `DisableLocalAuth=true` requiring Entra ID authentication
3. Missing RBAC role for managed identity

### Solution

1. **Updated connection string** - Pointed Docker worker to same App Insights as Function App (`rmhazuregeoapi`)
2. **Added AAD authentication support** - Updated `configure_azure_monitor_telemetry()` to detect `APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD` and pass `DefaultAzureCredential`
3. **Assigned RBAC role** - "Monitoring Metrics Publisher" to Docker worker's managed identity

### Files Modified

| File | Change |
|------|--------|
| `docker_service.py` | Added AAD auth support to `configure_azure_monitor_telemetry()` |
| `docker_service.py` | Added `/test/logging` and `/test/logging/verify` health check endpoints |
| `docs_claude/DEPLOYMENT_GUIDE.md` | Added Docker Worker Application Insights Setup section |
| `docs_claude/ERRORS_AND_FIXES.md` | Added OBSERVABILITY category with OBS-001, OBS-002, OBS-003 |

### Environment Variables Required

```bash
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=6aa0e75f-...;IngestionEndpoint=...
APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD
APP_NAME=rmhheavyapi
ENVIRONMENT=dev
```

### RBAC Role Assignment

```bash
az role assignment create \
  --assignee cea30c4b-8d75-4a39-8b53-adab9a904345 \
  --role "Monitoring Metrics Publisher" \
  --scope "/subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/microsoft.insights/components/rmhazuregeoapi"
```

---

## 21 JAN 2026: Platform Routing Improvements ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure

### Changes

1. **Platform Default to Docker** - When `docker_worker_enabled=true` in config, platform raster jobs automatically route to Docker worker without requiring `processing_mode=docker` parameter
2. **Endpoint Consolidation** - Removed redundant `/api/platform/raster` and `/api/platform/raster-collection` endpoints. All platform submissions now go through unified `/api/platform/submit`
3. **Expected Data Type Validation** - Added validation for `expected_data_type` parameter

### Files Modified

| File | Change |
|------|--------|
| `web_interfaces/stac/interface.py` | Default `processing_mode` based on config |
| `web_interfaces/vector/interface.py` | Removed redundant endpoints |

---

## 15 JAN 2026: Platform API Diagnostics (F7.12) ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure
**Goal**: Expose diagnostic endpoints via Platform API for external service layer apps

### Endpoints Created

| Endpoint | Purpose |
|----------|---------|
| `GET /api/platform/health` | Simplified system readiness check (ready_for_jobs boolean, queue backlog, avg job time) |
| `GET /api/platform/failures` | Recent failures with sanitized errors, grouped by pattern |
| `GET /api/platform/lineage/{request_id}` | Data lineage by request ID (source → processing → output) |
| `POST /api/platform/validate` | Pre-flight validation (file exists, readable, size, recommended job type) |

### Files Created/Modified

| File | Change |
|------|--------|
| `triggers/platform/diagnostics.py` | New file with all diagnostic endpoints |
| `triggers/platform/__init__.py` | Register diagnostic blueprint |

---

## 10-11 JAN 2026: F7.12 Logging Architecture Consolidation ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure
**Goal**: Eliminate duplicate debug flags, unify diagnostics, add global log context for multi-app filtering

### Subsections Completed

| Section | Description | Status |
|---------|-------------|--------|
| F7.12.A | Global Log Context - Every log includes app_name, instance_id, environment | ✅ |
| F7.12.B | Unify Diagnostics Module | ⏭️ SKIPPED (existing structure adequate) |
| F7.12.C | Consolidate Debug Flags - Reduced 4 flags to 2 (`OBSERVABILITY_MODE`, `METRICS_ENABLED`) | ✅ |
| F7.12.D | Python App Insights Log Export - `/api/logs/export` endpoint | ✅ |
| F7.12.E | Docker Worker OpenTelemetry - Docker logs to same App Insights | ✅ |
| F7.12.F | JSONL Log Dump System - Level-based filtering with retention | ✅ |

### Key Files Created/Modified

| File | Purpose |
|------|---------|
| `config/observability_config.py` | Unified observability configuration |
| `infrastructure/appinsights_exporter.py` | App Insights REST API client |
| `infrastructure/jsonl_log_handler.py` | JSONL blob handler for log export |
| `triggers/admin/log_cleanup_timer.py` | Log retention cleanup timer |
| `util_logger.py` | Global log context injection |

### Environment Variables

```bash
OBSERVABILITY_MODE=true           # Master switch for debug diagnostics
METRICS_ENABLED=true              # ETL job progress to PostgreSQL
VERBOSE_LOG_DUMP=true             # Combined with OBSERVABILITY_MODE, dumps ALL logs
JSONL_DEBUG_RETENTION_DAYS=7      # Days to keep verbose logs
JSONL_WARNING_RETENTION_DAYS=30   # Days to keep warning+ logs
```

### KQL Query for Multi-App Filtering

```kql
traces
| where cloud_RoleName in ("rmhazuregeoapi", "rmhheavyapi")
| project timestamp, cloud_RoleName, message
| order by timestamp desc
```

---

## 21 JAN 2026: Artifact Registry - Blob Version Tracking ✅

**Status**: ✅ **COMPLETE**
**Epic**: E4 Security Zones / Externalization
**Version**: 0.7.16.x (pending deployment)

### Achievement

Added `blob_version_id` field to artifact tracking system. When Azure Blob Storage versioning is enabled, the artifact registry now captures the Azure blob version ID for each artifact. This enables linking internal revision tracking to actual blob storage versions for recovery and audit scenarios.

### Use Case

When a dataset is updated (metadata + file change) without a semantic version change:
- New artifact created with revision N+1, new `content_hash`, new `blob_version_id`
- Old artifact marked `SUPERSEDED`, retains its original `blob_version_id`
- Full lineage preserved: `supersedes`/`superseded_by` links + Azure version IDs

### Files Modified

| File | Change |
|------|--------|
| `core/models/artifact.py` | Added `blob_version_id` field |
| `infrastructure/artifact_repository.py` | Added field to INSERT/SELECT |
| `services/artifact_service.py` | Added `blob_version_id` parameter |
| `infrastructure/blob.py` | Capture `version_id` from Azure upload response |
| `services/raster_cog.py` | Return `blob_version_id` in COG result |
| `services/raster_mosaicjson.py` | Return `blob_version_id` in MosaicJSON result |
| `services/handler_process_raster_complete.py` | Pass to artifact creation |
| `services/handler_process_large_raster_complete.py` | Pass to artifact creation |

### Schema Change

**New Column**: `app.artifacts.blob_version_id VARCHAR(64)`

**Deployment** (breaking - requires rebuild):
```bash
# Deploy code
func azure functionapp publish rmhazuregeoapi --python --build remote

# Rebuild app schema (creates new column)
curl -X POST ".../api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes"
```

### Enable Azure Blob Versioning

```bash
az storage account blob-service-properties update \
  --account-name <silver_account> \
  --resource-group <rg> \
  --enable-versioning true
```

---

## 20-21 JAN 2026: Artifact Registry (Core) ✅

**Status**: ✅ **COMPLETE**
**Epic**: E4 Security Zones / Externalization

### Achievement

Created internal artifact registry for tracking pipeline outputs with supersession/lineage support. Tracks artifacts independently of STAC with client-agnostic UUIDs and flexible `client_refs` JSONB for any client schema (DDH, Data360, manual, etc.).

### Key Features

- Internal `artifact_id` (UUID) - never exposed to clients
- `content_hash` (SHA256 multihash) for duplicate detection
- `supersedes`/`superseded_by` links for overwrite lineage
- `revision` - global monotonic counter per `client_refs`
- `status` - active, superseded, archived, deleted lifecycle
- `client_refs` JSONB - flexible client parameter storage

### Files Created

| File | Purpose |
|------|---------|
| `core/models/artifact.py` | Artifact model + ArtifactStatus enum |
| `infrastructure/artifact_repository.py` | CRUD operations |
| `services/artifact_service.py` | Business logic |

---

## 12 JAN 2026: F7.12 Docker Worker Infrastructure ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure
**Deployed**: 11 JAN 2026 to `rmhheavyapi` Web App
**Image**: `rmhazureacr.azurecr.io/rmh-gdal-worker:latest`
**Version**: 0.7.8

### Achievement

Deployed Docker worker for long-running tasks that exceed Azure Functions 30-minute timeout. Uses same CoreMachine as Function App - only the trigger mechanism differs.

### Stories Completed

| Story | Description |
|-------|-------------|
| S7.12.1 | Create `docker_main.py` (queue polling entry point) |
| S7.12.2 | Create `workers_entrance.py` (FastAPI + health endpoints) |
| S7.12.3 | Create `Dockerfile`, `requirements-docker.txt`, `docker.env.example` |
| S7.12.5 | Create `.funcignore` to exclude Docker files from Functions deploy |
| S7.12.6 | Create `infrastructure/auth/` module for Managed Identity OAuth |
| S7.12.7 | Verify ACR build succeeds |
| S7.12.8 | Deploy to rmhheavyapi Web App |
| S7.12.9 | Configure identities (PostgreSQL: user-assigned, Storage: system-assigned) |
| S7.12.10 | Verify all health endpoints (`/livez`, `/readyz`, `/health`) |

### Key Files Created

- `docker_main.py` - Queue polling entry point
- `workers_entrance.py` → `docker_service.py` - FastAPI app with health endpoints
- `Dockerfile` - OSGeo GDAL ubuntu-full-3.10.1 base
- `requirements-docker.txt` - Dependencies (minus azure-functions)
- `infrastructure/auth/` - Token cache, PostgreSQL OAuth, Storage OAuth

### Identity Configuration (All Identity-Based - No Secrets)

| Resource | Identity | Type | RBAC Role |
|----------|----------|------|-----------|
| PostgreSQL | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | User-assigned MI | PostgreSQL AAD Auth |
| Storage | `cea30c4b-8d75-4a39-8b53-adab9a904345` | System-assigned MI | Storage Blob Data Contributor |
| Service Bus | `cea30c4b-8d75-4a39-8b53-adab9a904345` | System-assigned MI | Data Sender + Data Receiver |

---

## 12 JAN 2026: F7.13 Docker Job Definitions (Phase 1) ✅

**Status**: ✅ **PHASE 1 COMPLETE** (checkpoint infrastructure + BackgroundQueueWorker)
**Epic**: E7 Pipeline Infrastructure

### Achievement

Created checkpoint/resume infrastructure for Docker tasks and integrated BackgroundQueueWorker into FastAPI service.

### Stories Completed

| Story | Description |
|-------|-------------|
| S7.13.1 | Create `jobs/process_raster_docker.py` - single-stage job |
| S7.13.2 | Create `services/handler_process_raster_complete.py` - consolidated handler |
| S7.13.3 | Register job and handler in `__init__.py` files |
| S7.13.4 | Rename `heartbeat` → `last_pulse` throughout codebase |
| S7.13.5 | Add checkpoint fields to `TaskRecord` model and schema |
| S7.13.6 | Create `CheckpointManager` class for resume support |
| S7.13.7 | Update handler to use `CheckpointManager` |
| S7.13.8 | Add BackgroundQueueWorker to workers_entrance.py |
| S7.13.9 | Rename `workers_entrance.py` → `docker_service.py` |

### Checkpoint Architecture

Docker tasks are "atomic" from orchestrator's perspective but internally resumable:
- `checkpoint_phase` - Current phase number (1, 2, 3...)
- `checkpoint_data` - Phase-specific state (JSONB)
- `checkpoint_updated_at` - Last checkpoint timestamp

### Remaining (F7.13 Phase 2)

- S7.13.11-14: Deploy, end-to-end test, checkpoint resume test, vector job

---

## 12 JAN 2026: F7.12 Logging Architecture Consolidation ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure

### Achievement

Unified observability infrastructure with global log context and consolidated debug flags.

### Sub-Features Completed

| Feature | Description | Status |
|---------|-------------|--------|
| F7.12.A | Global Log Context (app_name, instance_id, environment in every log) | ✅ |
| F7.12.B | Unify Diagnostics Module | ⏭️ Skipped (existing structure adequate) |
| F7.12.C | Consolidate Debug Flags (4 → 2: OBSERVABILITY_MODE, METRICS_ENABLED) | ✅ |
| F7.12.D | Python App Insights Log Export (`/api/logs/export`) | ✅ |
| F7.12.E | Docker Worker OpenTelemetry (logs to same App Insights) | ✅ |
| F7.12.F | JSONL Log Dump System (level-based blob export) | ✅ |

### Key Files

- `config/observability_config.py` - Unified observability configuration
- `infrastructure/jsonl_log_handler.py` - JSONL blob handler
- `infrastructure/appinsights_exporter.py` - App Insights REST API client
- `util_logger.py` - Global log context integration

---

## 12 JAN 2026: F7.16 Code Maintenance (Phase 1) ✅

**Status**: ✅ **PHASE 1 COMPLETE**
**Goal**: Split 2,673-line monolithic db_maintenance.py into focused modules

### Results

- `db_maintenance.py`: 2,673 → 1,922 lines (28% reduction)
- Extracted `data_cleanup.py`: 195 lines (cleanup + prerequisites)
- Extracted `geo_table_operations.py`: 578 lines (geo table management)
- Schema operations remain in db_maintenance.py (future extraction)

---

## 09 JAN 2026: F7.8 Unified Metadata Architecture 📋

**Status**: ✅ **COMPLETE** - Phase 1 & 2
**Epic**: E7 Pipeline Infrastructure
**Impact**: Pydantic-based metadata models as single source of truth across all data types
**Author**: Robert and Claude

### Achievement

Created unified metadata architecture with Pydantic models providing consistent metadata patterns:

```
BaseMetadata (abstract)
    ├── VectorMetadata      → geo.table_metadata
    ├── RasterMetadata      → app.cog_metadata (F7.9)
    └── Future formats      → extensible via inheritance
```

### Stories Completed

| Story | Description |
|-------|-------------|
| S7.8.1 | Created `core/models/unified_metadata.py` with BaseMetadata + VectorMetadata |
| S7.8.2 | Created `core/models/external_refs.py` with DDHRefs + ExternalRefs models |
| S7.8.3 | Created `app.dataset_refs` table DDL (cross-type external linkage) |
| S7.8.4 | Added `providers JSONB` and `custom_properties JSONB` to geo.table_metadata |
| S7.8.5 | Refactored `ogc_features/repository.py` to return VectorMetadata model |
| S7.8.6 | Refactored `ogc_features/service.py` to use VectorMetadata.to_ogc_collection() |
| S7.8.7 | Refactored `services/service_stac_vector.py` to use VectorMetadata |
| S7.8.8 | Wired Platform layer to populate app.dataset_refs on ingest |
| S7.8.9 | Documented pattern for future RasterMetadata, ZarrMetadata |
| S7.8.10 | Archived METADATA.md design doc to docs/archive |

### Key Files

- `core/models/unified_metadata.py` - Main metadata models (Provider, Extent, BaseMetadata, VectorMetadata)
- `core/models/external_refs.py` - DDH linkage models (DatasetRef, DatasetRefRecord)
- `core/schema/sql_generator.py` - DDL for app.dataset_refs table
- `ogc_features/repository.py` - `get_vector_metadata()` method

### Principles Established

1. Pydantic models as single source of truth
2. Typed columns over JSONB (minimize JSONB usage)
3. pgstac as catalog index (populated FROM metadata tables)
4. Open/Closed Principle — extend via inheritance
5. External refs in app schema — cross-cutting DDH linkage spans all data types

---

## 09 JAN 2026: F12.5 Web Interface DRY Consolidation 🎨

**Status**: ✅ **COMPLETE**
**Epic**: E12 Interface Modernization
**Impact**: Eliminated copy-pasted CSS/JS across web interfaces, clean template for frontend teams
**Author**: Robert and Claude

### Achievement

Consolidated duplicate CSS and JavaScript across web interfaces:

| Before | After |
|--------|-------|
| `.header-with-count` copied 4x | Moved to COMMON_CSS |
| `.action-bar` + `.filter-group` copied 3x | Moved to COMMON_CSS |
| `filterCollections()` JS copied 3x | Moved to COMMON_JS |

### Stories Completed

| Story | Description | Files |
|-------|-------------|-------|
| S12.5.1 | Move `.header-with-count` CSS to COMMON_CSS | `base.py` |
| S12.5.2 | Move `.action-bar` + `.filter-group` CSS to COMMON_CSS | `base.py` |
| S12.5.3 | Remove duplicated CSS from interfaces | `stac/`, `vector/` |
| S12.5.4 | Add `filterCollections()` JS to COMMON_JS | `base.py` |
| S12.5.5 | Remove duplicated JS from interfaces | `stac/`, `vector/` |
| S12.5.6 | Fix naming: `_generate_css` → `_generate_custom_css` | `pipeline/interface.py` |
| S12.5.7 | Verify all affected interfaces render correctly | Browser testing |

### Verification

All interfaces verified post-deployment:
- `/api/interface/stac` - Header badge, search, type filter working
- `/api/interface/vector` - Header badge, search input present
- `/api/interface/stac-map` - Uses own DOM-based filter (as designed)
- `/api/interface/pipeline` - Renders correctly, pipeline cards visible

---

## 07 JAN 2026: F9.1 FATHOM Rwanda Pipeline 🌊

**Status**: ✅ **COMPLETE**
**Epic**: E9 Large Data Hosting
**Impact**: End-to-end FATHOM flood data processing on Rwanda (1,872 TIF files, 1.85 GB)
**Author**: Robert and Claude
**Docs**: [FATHOM_ETL.md](./FATHOM_ETL.md), [WIKI_JOB_FATHOM_ETL.md](/docs/wiki/WIKI_JOB_FATHOM_ETL.md)

### Achievement

Built and executed two-phase ETL pipeline for FATHOM global flood data on Rwanda test region:

```
Phase 1: Band Stacking (8 return periods → 1 multi-band COG per scenario)
Phase 2: Spatial Merge (6 tiles → merged COGs per scenario)
```

### Rwanda Data Dimensions

| Dimension | Values |
|-----------|--------|
| Flood Types | FLUVIAL_DEFENDED, FLUVIAL_UNDEFENDED, PLUVIAL_DEFENDED |
| Years | 2020, 2030, 2050, 2080 |
| SSP Scenarios | SSP1_2.6, SSP2_4.5, SSP3_7.0, SSP5_8.5 (future only) |
| Return Periods | 1in5, 1in10, 1in20, 1in50, 1in100, 1in200, 1in500, 1in1000 |
| Tiles | 6 tiles covering Rwanda |

### Performance Results

| Metric | Value |
|--------|-------|
| Inventory | 6 tiles, 234 Phase 1 groups, 39 Phase 2 groups |
| Phase 1 | 234/234 tasks completed, 0 failures (~7 min) |
| Phase 2 | 39/39 tasks completed, 0 failures (~8 min) |
| Total pipeline | ~17 minutes |
| Throughput | 33 tasks/min (Phase 1), 5 tasks/min (Phase 2) |

### Stories Completed

| Story | Description |
|-------|-------------|
| S9.1.R1 | Add `base_prefix` parameter to `inventory_fathom_container` job |
| S9.1.R2 | Deploy and run inventory for Rwanda (`base_prefix: "rwa"`) |
| S9.1.R3 | Run Phase 1 band stacking |
| S9.1.R4 | Run Phase 2 spatial merge |
| S9.1.R5 | Verify outputs in silver-fathom storage |
| S9.1.R7 | Change FATHOM grid from 5×5 to 4×4 degrees |
| S9.1.R8 | Fix region filtering bug (`source_metadata->>'region'` WHERE clauses) |

### Key Files

- `jobs/inventory_fathom_container.py` - Inventory job with region filtering
- `services/fathom_container_inventory.py` - Bronze scanner with region extraction
- `services/fathom_etl.py` - Core handlers with region filtering
- `jobs/process_fathom_stack.py` - Phase 1 job
- `jobs/process_fathom_merge.py` - Phase 2 job

---

## 06 JAN 2026: System Diagnostics & Configuration Drift Detection 🔍

**Status**: ✅ **COMPLETE**
**Impact**: Azure platform configuration snapshots for drift detection and audit trails
**Author**: Robert and Claude

### Achievement

Built system snapshot infrastructure to capture and compare Azure platform configurations:

| Component | Description |
|-----------|-------------|
| `app.system_snapshots` table | Stores configuration snapshots with Pydantic model |
| Health: network_environment | Captures 90+ WEBSITE_*/AZURE_* environment vars |
| Health: instance_info | Instance ID, worker config, cold start detection |
| Snapshot service | Capture + drift detection via config hash comparison |

### Snapshot Trigger Types

| Trigger | When | Purpose |
|---------|------|---------|
| `startup` | App cold start | Baseline for each instance |
| `scheduled` | Timer (hourly) | Detect drift over time |
| `manual` | Admin endpoint | On-demand debugging |
| `drift_detected` | Hash changed | Record moment of change |

### Key Files

| File | Purpose |
|------|---------|
| `core/models/system_snapshot.py` | Pydantic model + SnapshotTriggerType enum |
| `core/schema/sql_generator.py` | DDL generation for system_snapshots table |
| `services/snapshot_service.py` | SnapshotService + SnapshotRepository |
| `triggers/admin/snapshot.py` | Blueprint with HTTP endpoints |
| `function_app.py` | Timer trigger + startup capture |

### Azure Configuration

- Scale controller logging enabled: `SCALE_CONTROLLER_LOGGING_ENABLED=AppInsights:Verbose`
- Drift detection via SHA256 hash of stable config fields

---

## 05 JAN 2026: Thread Safety Fix for BlobRepository 🔒

**Status**: ✅ **COMPLETE**
**Trigger**: KeyError race condition with 8 instances × 4 concurrent calls = 32 parallel executions
**Impact**: Fixed container client caching race condition
**Author**: Robert and Claude

### Problem

With `maxConcurrentCalls: 4` and 8 instances, hit race conditions in BlobRepository's container client caching due to check-then-act pattern without locking:

```python
# UNSAFE: Three separate bytecode ops, GIL releases between them
if key not in dict:      # ① CHECK
    dict[key] = value    # ② STORE (may trigger dict resize!)
return dict[key]         # ③ RETURN (KeyError during resize!)
```

### Solution

Implemented double-checked locking pattern:

```python
# SAFE: Lock protects entire sequence
if key in dict:                    # Fast path (no lock)
    return dict[key]
with lock:                         # Slow path (locked)
    if key not in dict:            # Double-check
        dict[key] = create_value()
    return dict[key]
```

### Key Concepts Documented

| Coordination Type | Scope | Lock Mechanism | Example |
|-------------------|-------|----------------|---------|
| **Distributed** | Across instances/processes | PostgreSQL `pg_advisory_xact_lock` | "Last task turns out lights" |
| **Local** | Within single process | Python `threading.Lock` | Dict caching in singletons |

### Files Changed

- `infrastructure/blob.py` - Added `_instances_lock`, `_container_clients_lock`, double-checked locking

---

## 02 JAN 2026: Root Folder Cleanup & Consolidation 🧹

**Status**: ✅ **COMPLETE**
**Impact**: Reduced root folders from 26 to 22, improved discoverability
**Author**: Robert and Claude
**Archive**: [docs/archive/FOLDER_CLEANUP.md](../docs/archive/FOLDER_CLEANUP.md)

### Achievement

Comprehensive folder structure cleanup consolidating orphaned files and reorganizing misplaced content:

| Phase | Action | Result |
|-------|--------|--------|
| Phase 1 | Docs consolidation | `titiler/` (18 files) → `docs/titiler/`, `fathom/` → `docs_claude/` |
| Phase 2 | Models consolidation | `band_mapping.py` → `core/models/`, `h3_base.py` archived |
| Phase 3 | Routes consolidation | Blueprints → `triggers/admin/`, imports updated |
| Phase 4 | Utils review | KEPT - Valid utility package (16+ active usages) |
| Phase 5 | SQL review | SKIPPED - H3 refactor will handle |
| Phase 6 | Optional moves | SKIPPED - `openapi/`, `scripts/` valid as-is |

### Root File Cleanup

Also cleaned 52 root files (~1.8MB):
- 10 files → `docs_claude/` (planning docs)
- 20 files → `docs/wiki/` (markdown documentation)
- 8 files → `docs/archive/` (deprecated/historical)
- 6 files deleted (test HTML artifacts)
- 2 files deleted (`service_stac.py`, `service_statistics.py` - dead code)

### Key Changes

1. **Deleted dead code**: `service_stac.py`, `service_statistics.py`, `models/h3_base.py`
2. **Updated imports**: `services/tiling_scheme.py`, `services/tiling_extraction.py` now use `core.models.band_mapping`
3. **Moved blueprints**: `routes/admin_*.py` → `triggers/admin/`, updated `function_app.py`

---

## 01 JAN 2026: DDL Utilities Consolidation 🔧

**Status**: ✅ **COMPLETE** - DRY refactoring of SQL DDL generation
**Impact**: Code reduction, consistency, maintainability
**Author**: Robert and Claude

### Achievement

Created centralized `ddl_utils.py` module consolidating SQL DDL patterns across all schema generators:

```
core/schema/ddl_utils.py (NEW - 646 lines)
├── IndexBuilder     (btree, gist, gin, unique with partial/descending)
├── TriggerBuilder   (updated_at triggers)
├── CommentBuilder   (schema/table/column/index comments)
└── SchemaUtils      (create_schema, set_search_path, grant_all)
```

### Files Migrated

| File | Before | After | Reduction |
|------|--------|-------|-----------|
| `infrastructure/h3_schema.py` | 1419 | 1161 | -258 (-18%) |
| `core/schema/geo_table_builder.py` | 602 | 520 | -82 (-14%) |
| `core/schema/sql_generator.py` | — | 1073 | Updated |

### Changes Made

1. **Fixed f-string SQL injection** in `triggers/admin/h3_debug.py` - converted to `sql.Identifier()`
2. **Created IndexBuilder** with support for:
   - Composite indexes (multiple columns)
   - Partial indexes (`partial_where` clause)
   - Descending indexes for temporal queries
3. **Updated sql_generator.py**:
   - Fixed `etl_fathom` → `etl_source_files` table name
   - Added missing primary keys for curated_datasets, curated_update_log, promoted_datasets
   - Added 15+ new indexes for newer tables
4. **Fixed config attribute** `admin_identity_name` → `managed_identity_admin_name`

### Testing Verified

| Schema | Test Method | Result |
|--------|-------------|--------|
| App | `full-rebuild` endpoint | ✅ 9 tables, 39 indexes, 5 functions |
| H3 | Drop + rebuild | ✅ 16 tables created |
| Geo | Vector ETL job | ✅ Table created with indexes/triggers |

### Key Pattern

```python
from core.schema.ddl_utils import IndexBuilder, TriggerBuilder, CommentBuilder

# Create indexes
IndexBuilder.btree('app', 'jobs', 'status', name='idx_jobs_status')
IndexBuilder.gist('geo', 'countries', 'geom')
IndexBuilder.btree('app', 'tasks', 'heartbeat', partial_where='heartbeat IS NOT NULL')

# Create triggers
TriggerBuilder.updated_at_trigger('geo', 'countries')

# Add comments
CommentBuilder.table('geo', 'countries', 'Country boundaries')
```

---

## 21 DEC 2025: FATHOM Flood Data ETL Pipeline 🌊

**Status**: ⚠️ **Phase 1 Complete, Phase 2 In Progress**
**Impact**: Global flood hazard data processing at scale
**Author**: Robert and Claude
**Docs**: [FATHOM_ETL.md](./FATHOM_ETL.md)

### Achievement

Built two-phase ETL pipeline for FATHOM global flood data:

```
Phase 1: Band Stacking (8 return periods → 1 multi-band COG per tile)
Phase 2: Spatial Merge (N×N tiles → 1 larger merged COG)
```

### Test Region: Côte d'Ivoire

| Phase | Status | Output |
|-------|--------|--------|
| Phase 1 | ✅ Complete | 32 stacked COGs in `silver-fathom/fathom-stacked/ci/` |
| Phase 2 | ⚠️ 46/47 | Merged COGs in `silver-fathom/fathom/ci/` |

### Bugs Fixed

1. **dict_row access pattern**: psycopg3 returns dicts, code used tuple unpacking
2. **source_container filter**: Phase 2 inventory filtered wrong container

### Performance Metrics

- Phase 2 avg task: 96.8 seconds
- Peak memory: ~5 GB RSS (grid_size=3)
- Safe grid_size limit: 3 (larger causes OOM)

### Key Files

| File | Purpose |
|------|---------|
| `jobs/process_fathom_stack.py` | Phase 1 job |
| `jobs/process_fathom_merge.py` | Phase 2 job |
| `services/fathom_etl.py` | All handlers |
| `services/fathom_container_inventory.py` | Bronze scanner |

---
