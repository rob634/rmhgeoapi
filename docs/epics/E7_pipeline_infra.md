# Epic E7: Pipeline Infrastructure

**Type**: Foundational Enabler
**Status**: Complete
**Last Updated**: 30 JAN 2026
**ADO Feature**: "ETL Pipeline Infrastructure"

---

## Value Statement

E7 provides the execution engine that powers all data processing. Without E7, there are no ETL pipelines. It enables E1 (Vector), E2 (Raster), E8 (Analytics), and E9 (Large Data) to function.

---

## Architecture

```
Platform Gateway ──▶ geospatial-jobs ──▶ Orchestrator (CoreMachine)
                         (queue)                │
                                ┌───────────────┴───────────────┐
                                ▼                               ▼
                       container-tasks                 functionapp-tasks
                           (queue)                         (queue)
                                │                               │
                                ▼                               ▼
                        Docker Worker                  FunctionApp Worker
                      (ALL heavy ETL)                (lightweight ops)
```

**Key Principle**: Docker Worker is the PRIMARY execution environment for all geospatial operations (GDAL, geopandas, bulk SQL). FunctionApp Worker handles lightweight database queries and inventory operations.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F7.1 CoreMachine | ✅ | Job→Stage→Task state machine with retry logic |
| F7.2 Docker Worker | ✅ | GDAL/geopandas execution environment |
| F7.3 Queue Architecture | ✅ | container-tasks + functionapp-tasks routing |
| F7.4 Metadata Architecture | ✅ | VectorMetadata, RasterMetadata, unified registry |
| F7.5 Job Lifecycle | ✅ | Status tracking, approval workflow integration |

---

## Feature Summaries

### F7.1: CoreMachine
Job orchestration engine implementing Job→Stage→Task pattern. Stages execute sequentially, tasks execute in parallel within a stage. "Last task turns out the lights" pattern for stage completion detection.

**Implementation**: `docs_claude/ARCHITECTURE_REFERENCE.md`

### F7.2: Docker Worker
Primary execution environment for all heavy operations. Runs GDAL, geopandas, rasterstats, and bulk SQL operations. OSGeo GDAL base image with full driver support.

**Implementation**: `docs_claude/DOCKER_INTEGRATION.md`

### F7.3: Queue Architecture
Three-queue system:
- `geospatial-jobs`: Job coordination (Orchestrator listens)
- `container-tasks`: Heavy operations (Docker Worker listens)
- `functionapp-tasks`: Lightweight operations (FunctionApp Worker listens)

**Implementation**: `docs_claude/V0.8_PLAN.md` (to be created)

### F7.4: Metadata Architecture
Unified metadata registry for tracking processed data:
- `geo.table_catalog`: Vector table metadata
- `app.cog_metadata`: Raster COG metadata
- `app.vector_etl_tracking`: ETL provenance

**Implementation**: `docs_claude/RASTER_METADATA.md`

### F7.5: Job Lifecycle
Complete job tracking from submission to approval:
- Job/task status tracking in `app.jobs`, `app.tasks`
- Automatic approval record creation on completion
- STAC items created with `app:published=false` until approved

**Implementation**: `docs_claude/APPROVAL_WORKFLOW.md`

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| Azure Service Bus | E1, E2, E8, E9 |
| PostgreSQL | All epics |
| Azure Blob Storage | All epics |

---

## Implementation Details

All implementation specifications are in `docs_claude/`:
- `ARCHITECTURE_REFERENCE.md` - CoreMachine details
- `DOCKER_INTEGRATION.md` - Docker Worker setup
- `COREMACHINE_GAPS.md` - Gap analysis and job_events table
- `APPROVAL_WORKFLOW.md` - Approval system
- `RASTER_METADATA.md` - Metadata architecture
