# Claude Context - Azure Geospatial ETL Platform

**Date**: 04 APR 2026
**Version**: v0.10.10.1
**Primary Documentation**: Start here for all Claude instances
**Architecture Source of Truth**: `V10_MIGRATION.md` (root) | **Product Docs**: `docs/product/`

---

## What This System Does

A **geospatial ETL platform** that processes raster, vector, and multidimensional data into standards-compliant APIs:

```
Bronze Storage (raw files) --> DAG Brain (YAML workflow orchestration) --> Silver Storage (COGs/Zarr) + PostGIS + STAC
                                    |                                          |
                           Docker Workers (SKIP LOCKED polling)     Standards-Compliant APIs:
                                                                     - OGC API - Features (vector queries via TiPG)
                                                                     - STAC API (metadata search)
                                                                     - TiTiler (dynamic tile serving for raster + Zarr)
```

**DAG is default (v0.10.10)**: DAG Brain (13 YAML workflows + PostgreSQL polling) is the primary orchestrator. Legacy CoreMachine (Python jobs + Service Bus) remains in maintenance mode only. v0.11.0 (strangler fig complete) has started — discovery automation merged.

**Core Capabilities**:
- **Raster Processing**: GeoTIFF --> Cloud-Optimized GeoTIFF (COG) with STAC metadata
- **Vector Processing**: GeoJSON/Shapefile/GPKG/CSV --> PostGIS with OGC Features API
- **Zarr/NetCDF Processing**: NetCDF --> Zarr conversion with rechunking, native Zarr ingest
- **Multi-Table Vector**: Single file + split_column --> 1 table + N views; multi-file --> N tables; GPKG multi-layer --> N tables
- **Job Orchestration**: Multi-stage workflows with parallel task execution
- **Unpublish Pipelines**: Symmetric teardown for raster, vector, Zarr, and multi-source vector

---

## Quick Start

### Active Environment (4-App Architecture)

| Role | App Name | APP_MODE | Image | URL |
|------|----------|----------|-------|-----|
| **Function App** | `rmhazuregeoapi` | `standalone` | Function App (zip deploy) | https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net |
| **DAG Brain** | `rmhdagmaster` | `orchestrator` | Docker (ACR: `geospatial-worker`) | (internal) |
| **Docker Worker** | `rmhheavyapi` | `worker_docker` | Docker (ACR: `geospatial-worker`) | https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net |
| **TiTiler** | `rmhtitiler` | — | Docker (`titiler-pgstac:2.1.0`) | rmhtitiler-ghcyd7g0bxdvc2hc |

**DAG Brain and Docker Worker share the same ACR image** (`rmhazureacr.azurecr.io/geospatial-worker:{version}`). `APP_MODE` selects behavior.

**Deprecated apps** (never use): `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn`, `rmhgeoapibeta`, `rmhgeogateway`

| Resource | Value |
|----------|-------|
| **Database** | `geopgflex` on rmhpostgres.postgres.database.azure.com (PostgreSQL 17) |
| **TiTiler** | `titiler-pgstac:2.1.0` on rmhtitiler-ghcyd7g0bxdvc2hc |
| **Silver Storage** | `rmhstorage123` |
| **Resource Group** | `rmhazure_rg` |
| **ACR** | `rmhazureacr.azurecr.io` |

### Essential Commands
```bash
# Deploy (recommended -- handles versioning, health checks, verification)
./deploy.sh orchestrator   # Deploy Function App (rmhazuregeoapi)
./deploy.sh docker         # Deploy Docker Worker (rmhheavyapi)
./deploy.sh dagbrain       # Deploy DAG Brain (rmhdagmaster) — same ACR image as docker
./deploy.sh all            # Deploy all apps

# Health Check
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Schema Sync (safe -- creates missing tables/indexes, preserves data)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=ensure&confirm=yes"

# Schema Rebuild (destructive -- drops and recreates, dev/test only)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&confirm=yes"

# Submit Test Job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'

# Check Job Status
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## Architecture Overview

### Architecture (Strangler Fig Migration — v0.10.x)

```
+------------------------------------------------------------+
|                    PLATFORM LAYER                          |
|  Client-agnostic REST API (Function App)                   |
|  "Give me data, I'll give you API endpoints"               |
|                                                            |
|  Input: ProcessingRequest (data_type, source_location)     |
|  Output: API endpoints (OGC Features, STAC, tiles)         |
+----------------------------+-------------------------------+
                             |
              +--------------+--------------+
              |                             |
              v                             v
+---------------------------+  +----------------------------+
| DAG Brain (Epoch 5)       |  | CoreMachine (Epoch 4)      |
| YAML workflow definitions |  | Python job classes          |
| PostgreSQL SKIP LOCKED    |  | Service Bus queues          |
| 13 workflows (default)    |  | Maintenance mode only       |
+---------------------------+  +----------------------------+
              |                             |
              +---------- Workers ----------+
                   (SKIP LOCKED polling)
```

**~66 handlers** registered in `ALL_HANDLERS` (58 base + 8 discovery automation). **13 YAML workflows** on disk.
**v0.11.0 started**: Discovery automation merged. CoreMachine + Service Bus deletion in progress. DAG Brain is sole orchestrator.

### Asset/Release Domain Model (v0.9+)

```
Asset (stable identity, SHA256 of platform_id|dataset_id|resource_id)
  +-- Release 1 (version_ordinal=1, approval lifecycle)
  +-- Release 2 (version_ordinal=2, can coexist with v1)
```

Key decisions:
- **version_id assigned at approval**, not submission
- **STAC materialization at approval only** -- cached dict on Release, written to pgSTAC when approved
- **"is_latest" is computed**, never stored -- `MAX(version_ordinal)` via `ORDER BY version_ordinal DESC LIMIT 1`
- **Vector excluded from STAC** -- vector discovery via PostGIS/OGC Features API only; STAC is for raster and Zarr
- **Ordinal naming**: tables use `ord1`, `ord2` (not "draft")

### Job --> Stage --> Task Pattern

```
JOB (Blueprint)
 +-- STAGE 1 (Sequential)
 |   +-- Task A (Parallel) \
 |   +-- Task B (Parallel)  > All tasks run concurrently
 |   +-- Task C (Parallel) /  Last task triggers stage completion
 |
 +-- STAGE 2 (waits for Stage 1)
 |   +-- Tasks...
 |
 +-- COMPLETION (aggregation & final status)
```

**Key Pattern: "Last Task Turns Out the Lights"**
- Advisory locks enable unlimited parallelism without deadlocks
- Exactly one task detects completion and advances stage
- Zero-task stage guard: when `create_tasks_for_stage` returns `[]`, stage auto-advances

### Database Schemas

| Schema | Purpose | Management |
|--------|---------|------------|
| `app` | Jobs, tasks, core orchestration | Pydantic --> SQL generator |
| `platform` | API request tracking, assets, releases, routes | Own schema (Pydantic --> SQL generator) |
| `pgstac` | STAC metadata catalog | pypgstac migrate |
| `geo` | User vector/raster data | Dynamic at runtime |
| `h3` | H3 hexagonal grids | Static SQL |

---

## Project Structure

```
rmhgeoapi/
+-- function_app.py          # Azure Functions entry point
+-- docker_service.py        # Docker worker/orchestrator FastAPI app
+-- CLAUDE.md                # --> Points here
+-- V10_MIGRATION.md         # ARCHITECTURE SOURCE OF TRUTH
+-- deploy.sh                # Deployment script (orchestrator/dagbrain/docker/all)
|
+-- config/                  # Modular configuration
|   +-- *.py                 # app, database, queue, raster, storage, vector, platform, metrics
|
+-- core/                    # Orchestration engines (Epoch 4 + Epoch 5)
|   +-- machine.py           # CoreMachine (Epoch 4 — maintenance mode)
|   +-- dag_orchestrator.py  # DAGOrchestrator (Epoch 5 — active development)
|   +-- dag_initializer.py   # Workflow run → task graph instantiation
|   +-- dag_graph_utils.py   # DAG traversal utilities
|   +-- dag_transition_engine.py  # Task state transitions
|   +-- dag_fan_engine.py    # Fan-out expansion + fan-in aggregation
|   +-- param_resolver.py    # Parameter resolution (receives: + dotted paths)
|   +-- workflow_loader.py   # YAML parser + validator
|   +-- workflow_registry.py # Loaded workflow cache
|   +-- models/              # Pydantic models (JobRecord, WorkflowRun, WorkflowTask, etc.)
|   +-- schema/              # DDL generation from Pydantic
|
+-- workflows/               # YAML workflow definitions (Epoch 5) — 13 workflows
|   +-- hello_world.yaml, echo_test.yaml, test_fan_out.yaml
|   +-- vector_docker_etl.yaml    # 6 nodes, linear + conditional
|   +-- process_raster.yaml       # 12 nodes, conditional + fan-out + fan-in + STAC
|   +-- process_raster_collection.yaml  # Multi-file raster collection
|   +-- acled_sync.yaml           # 3 nodes, API-driven scheduled
|   +-- ingest_zarr.yaml          # Zarr ingest with rechunking
|   +-- unpublish_raster.yaml, unpublish_vector.yaml, unpublish_zarr.yaml
|   +-- discover_maxar_delivery.yaml, discover_wbg_legacy.yaml  # v0.11.0 discovery automation
|
+-- infrastructure/          # Repository pattern implementations
|   +-- postgresql.py        # Database access (psycopg3, type adapters)
|   +-- db_auth.py           # ManagedIdentityAuth (extracted from postgresql.py)
|   +-- db_connections.py    # ConnectionManager (extracted from postgresql.py)
|   +-- db_utils.py          # Shared type adapters, JSONB parsing
|   +-- service_bus.py       # Message queues (deprecated — removed in v0.11.0)
|   +-- blob.py              # Azure Blob Storage (auth owner)
|
+-- jobs/                    # Python job definitions (Epoch 4 — maintenance mode)
|
+-- services/                # Business logic & task handlers (~66 total in ALL_HANDLERS)
|   +-- raster/              # Atomic raster handlers (9)
|   +-- vector/              # Atomic vector handlers (7)
|   +-- shared/              # Composable STAC handlers (2) + catalog
|   +-- handler_*.py         # Legacy monolithic handlers (Epoch 4)
|
+-- triggers/                # HTTP/Service Bus endpoints
|   +-- platform/            # Platform layer API (B2B surface)
|   +-- admin/               # Admin endpoints (dbadmin, stac, system)
|   +-- *.py                 # Other endpoints
|
+-- ui/                      # DAG Brain admin UI (APP_MODE=orchestrator only)
|   +-- dto.py, terminology.py, features.py, navigation.py
|   +-- adapters/            # Epoch4/DAG adapter layer
|
+-- templates/               # Jinja2 templates for DAG Brain UI
+-- static/                  # CSS/JS for DAG Brain UI
|
+-- ogc_features/            # OGC API - Features (standalone)
+-- stac_api/                # STAC API endpoints
|
+-- docs_claude/             # Claude documentation (YOU ARE HERE)
    +-- CLAUDE_CONTEXT.md    # THIS FILE - Start here
    +-- TODO.md              # Active tasks
    +-- *.md                 # Reference docs (see Documentation Map)
```

---

## Creating New Jobs

**Use JobBaseMixin** -- 77% less code, 30 minutes instead of 2 hours.

```python
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin

class MyJob(JobBaseMixin, JobBase):  # Mixin FIRST!
    job_type = "my_job"
    description = "What this job does"

    stages = [
        {"number": 1, "name": "process", "task_type": "my_handler", "parallelism": "single"}
    ]

    parameters_schema = {
        'param': {'type': 'str', 'required': True}
    }

    @staticmethod
    def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
        return [{"task_id": f"{job_id[:8]}-s1", "task_type": "my_handler", "parameters": {}}]

    @staticmethod
    def finalize_job(context=None):
        return {"status": "completed", "job_type": "my_job"}
```

**Full guide**: `docs_claude/JOB_CREATION_QUICKSTART.md`

---

## Debugging and Monitoring

### Database Endpoints
```bash
# Job details
curl .../api/dbadmin/jobs/{JOB_ID}

# Tasks for job
curl .../api/dbadmin/tasks/{JOB_ID}

# Failed jobs
curl ".../api/dbadmin/jobs?status=failed&limit=10"

# Database stats
curl ".../api/dbadmin/diagnostics?type=stats"
```

### Application Insights
```bash
# App ID: d3af3d37-cfe3-411f-adef-bc540181cbca (all 3 apps share this)
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 20" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

### DAG Brain Admin UI
Jinja2 + HTMX admin UI (APP_MODE=orchestrator only). Pages: Dashboard, Jobs, Submit (with file browser + validate), Assets (approve/reject/revoke), Handlers, Health. Proxies API calls to Function App via `ORCHESTRATOR_URL`.

---

## Documentation Map

### Primary
| Document | Purpose |
|----------|---------|
| **CLAUDE_CONTEXT.md** | START HERE -- system overview |
| **TODO.md** | Active tasks only |
| **DEV_BEST_PRACTICES.md** | Patterns, common mistakes, gotchas |
| **ERRORS_AND_FIXES.md** | Error catalog -- search here first when debugging |

### Architecture
| Document | Purpose |
|----------|---------|
| **ARCHITECTURE_REFERENCE.md** | Deep technical specs, job patterns, error handling |
| **ARCHITECTURE_DIAGRAMS.md** | Visual C4/Mermaid diagrams |
| **SCHEMA_ARCHITECTURE.md** | PostgreSQL 5-schema design |
| **SCHEMA_EVOLUTION.md** | Safe vs breaking changes, migration patterns |

### Operations
| Document | Purpose |
|----------|---------|
| **DEPLOYMENT_GUIDE.md** | Deployment procedures for all 3 apps |
| **APPLICATION_INSIGHTS.md** | Log queries and diagnostics |
| **DOCKER_INTEGRATION.md** | Docker worker parallelism model |
| **PIPELINE_OPERATIONS.md** | Failure modes and resilience |

### Development
| Document | Purpose |
|----------|---------|
| **JOB_CREATION_QUICKSTART.md** | 5-step guide for new jobs |
| **FATHOM_ETL.md** | FATHOM flood data pipeline (Phase 1 and 2) |
| **AGENT_PLAYBOOKS.md** | Multi-agent review pipelines |

### Product
| Document | Purpose |
|----------|---------|
| **docs/product/EPICS.md** | SAFe Epic definitions and WSJF calculations |
| **docs/product/PRODUCT_OVERVIEW.md** | Product vision and capability summary |
| **docs/product/STORIES_F1-F5/** | Feature and Story registry by data domain + lifecycle + platform |

### History
| Document | Purpose |
|----------|---------|
| **HISTORY.md** | Completed work log |

---

## Critical Reminders

1. **4-App Architecture**: Function App (`rmhazuregeoapi`), DAG Brain (`rmhdagmaster`), Docker Worker (`rmhheavyapi`), TiTiler (`rmhtitiler`). DAG Brain + Worker share same ACR image.
2. **Epoch 5 Active (13 workflows, ~66 handlers)**: DAG Brain is default orchestrator. CoreMachine/Service Bus in maintenance mode. New features as YAML workflows + atomic handlers only.
3. **Schema sync after deploy**: Use `?action=ensure&confirm=yes` (safe). Only use `action=rebuild` for fresh dev/test environments.
4. **No Backward Compatibility**: Fail fast with clear errors (development mode). Never create fallbacks that mask breaking changes.
5. **Auth owned by BlobRepository**: All blob access must derive credentials from `BlobRepository.for_zone()` singleton. Never create independent `DefaultAzureCredential()`.
6. **Schema changes use rebuild, not ALTER**: Enum values and DDL changes go into model code, deploy via `action=rebuild`. No standalone ALTER statements.
7. **Prefer Editing**: Always edit existing files over creating new ones.
8. **Date Format**: Use military format (04 APR 2026).
9. **Deploy script**: Use `./deploy.sh orchestrator|dagbrain|docker|all` for deployments. DAG Brain + Docker Worker deploy together (same image).

---

**Last Updated**: 04 APR 2026
