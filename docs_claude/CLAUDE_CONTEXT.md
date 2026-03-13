# Claude Context - Azure Geospatial ETL Platform

**Date**: 13 MAR 2026
**Version**: v0.10.1.1
**Primary Documentation**: Start here for all Claude instances

---

## What This System Does

A **geospatial ETL platform** that processes raster, vector, and multidimensional data into standards-compliant APIs:

```
Bronze Storage (raw files) --> CoreMachine (orchestration) --> Silver Storage (COGs/Zarr) + PostGIS + STAC
                                    |
                           Standards-Compliant APIs:
                            - OGC API - Features (vector queries via TiPG)
                            - STAC API (metadata search)
                            - TiTiler (dynamic tile serving for raster + Zarr)
```

**Core Capabilities**:
- **Raster Processing**: GeoTIFF --> Cloud-Optimized GeoTIFF (COG) with STAC metadata
- **Vector Processing**: GeoJSON/Shapefile/GPKG/CSV --> PostGIS with OGC Features API
- **Zarr/NetCDF Processing**: NetCDF --> Zarr conversion, native Zarr ingest with rechunking, VirtualiZarr references
- **Multi-Table Vector**: Single file + split_column --> 1 table + N views; multi-file --> N tables; GPKG multi-layer --> N tables
- **Job Orchestration**: Multi-stage workflows with parallel task execution
- **Unpublish Pipelines**: Symmetric teardown for raster, vector, Zarr, and multi-source vector

---

## Quick Start

### Active Environment (3-App Architecture)

| Role | App Name | APP_MODE | URL |
|------|----------|----------|-----|
| **Orchestrator** | `rmhazuregeoapi` | `standalone` | https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net |
| **Gateway** | `rmhgeogateway` | `platform` | https://rmhgeogateway-gdc4hrafawfrcqak.eastus-01.azurewebsites.net |
| **Docker Worker** | `rmhheavyapi` | `worker_docker` | https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net |

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
./deploy.sh orchestrator   # Deploy Orchestrator
./deploy.sh gateway        # Deploy Gateway
./deploy.sh docker         # Deploy Docker Worker

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

### Two-Layer Design

```
+------------------------------------------------------------+
|                    PLATFORM LAYER                          |
|  Client-agnostic REST API                                  |
|  "Give me data, I'll give you API endpoints"               |
|                                                            |
|  Input: ProcessingRequest (data_type, source_location)     |
|  Output: API endpoints (OGC Features, STAC, tiles)         |
+----------------------------+-------------------------------+
                             |
                             v
+------------------------------------------------------------+
|                    COREMACHINE                              |
|  Universal Job Orchestration Engine                        |
|                                                            |
|  Pattern: Composition over Inheritance                     |
|  - StateManager (database ops)                             |
|  - OrchestrationManager (task creation)                    |
|  - All work delegated to specialized components            |
+------------------------------------------------------------+
```

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
+-- CLAUDE.md                # --> Points here
+-- deploy.sh                # Deployment script (orchestrator/gateway/docker)
|
+-- config/                  # Modular configuration
|   +-- *.py                 # app, database, queue, raster, storage, vector, platform, metrics
|
+-- core/                    # CoreMachine orchestration engine
|   +-- machine.py           # Main orchestrator
|   +-- state_manager.py     # Database operations
|   +-- models/              # Pydantic models (JobRecord, TaskRecord, etc.)
|   +-- schema/              # DDL generation from Pydantic
|
+-- infrastructure/          # Repository pattern implementations
|   +-- postgresql.py        # Database access (psycopg3, type adapters)
|   +-- service_bus.py       # Message queues
|   +-- blob.py              # Azure Blob Storage (auth owner)
|
+-- jobs/                    # Job definitions (JobBase + JobBaseMixin)
|   +-- base.py              # JobBase ABC
|   +-- mixins.py            # JobBaseMixin (77% less boilerplate)
|   +-- process_raster_docker.py        # Raster ETL
|   +-- vector_docker_etl.py            # Vector ETL (incl. split views)
|   +-- vector_multi_source_docker.py   # Multi-file/multi-layer vector
|   +-- ingest_zarr.py                  # Native Zarr ingest + rechunk
|   +-- netcdf_to_zarr.py              # NetCDF --> Zarr conversion
|   +-- virtualzarr.py                 # VirtualiZarr references
|   +-- unpublish_*.py                 # Symmetric teardown jobs
|
+-- services/                # Business logic & task handlers
|   +-- raster/              # COG creation, tiling
|   +-- vector/              # PostGIS operations
|   |   +-- postgis_handler.py   # Core vector processing
|   |   +-- view_splitter.py     # Split views (P2)
|   +-- handler_*.py         # Handler implementations (7 handlers)
|
+-- triggers/                # HTTP/Service Bus endpoints
|   +-- jobs.py              # Job submission/status
|   +-- platform.py          # Platform layer API
|   +-- *.py                 # Other endpoints
|
+-- ogc_features/            # OGC API - Features (standalone)
+-- stac_api/                # STAC API endpoints
+-- web_dashboard/           # HTMX-powered admin dashboard
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

### Web Dashboard
HTMX-powered admin UI in `web_dashboard/` -- 4 tabs: Platform, Jobs, Data, System.
Includes storage browser, queue monitoring, and job management.

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

### History
| Document | Purpose |
|----------|---------|
| **HISTORY.md** | Completed work log |

---

## Critical Reminders

1. **3-App Architecture**: Orchestrator (`rmhazuregeoapi`), Gateway (`rmhgeogateway`), Docker Worker (`rmhheavyapi`). Deprecated apps: `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn`, `rmhgeoapibeta`.
2. **Schema sync after deploy**: Use `?action=ensure&confirm=yes` (safe). Only use `action=rebuild` for fresh dev/test environments.
3. **No Backward Compatibility**: Fail fast with clear errors (development mode). Never create fallbacks that mask breaking changes.
4. **Auth owned by BlobRepository**: All blob access (including fsspec/adlfs for h5py/VirtualiZarr) must derive credentials from `BlobRepository.for_zone()` singleton. Never create independent `DefaultAzureCredential()`.
5. **Schema changes use rebuild, not ALTER**: Enum values and DDL changes go into model code, deploy via `action=rebuild`. No standalone ALTER statements.
6. **Prefer Editing**: Always edit existing files over creating new ones.
7. **Date Format**: Use military format (13 MAR 2026).
8. **Deploy script**: Use `./deploy.sh orchestrator|gateway|docker|all` for deployments.

---

**Last Updated**: 13 MAR 2026
