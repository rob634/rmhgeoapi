# Production Architecture: Multi-Function App Architecture

**Date**: 07 DEC 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: IMPLEMENTED - Phase 1 Complete

---

## Executive Summary

The codebase now supports **environment-variable-driven multi-Function App deployment**. A single codebase can be deployed in different modes:
- **Standalone** (default): Single app handles everything
- **Platform + Workers**: Centralized orchestration with distributed execution

This enables workload separation where raster (GDAL, 2-8+ GB) and vector (geopandas, 20-200 MB) operations can run with different `host.json` concurrency settings.

---

## What Was Implemented (07 DEC 2025)

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PLATFORM APP (Orchestration Hub)                         │
│                                                                             │
│  Responsibilities:                                                          │
│  ✅ HTTP endpoints (job submission, status, admin)                          │
│  ✅ Job queue processing (geospatial-jobs) - BOTH message types             │
│  ✅ Stage creation and task routing                                         │
│  ✅ Job finalization and STAC updates                                       │
│                                                                             │
│  Resource Profile: LOW - orchestration is just DB reads/writes + queueing   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
           ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
           │ raster-tasks │ │ vector-tasks │ │ (future)     │
           │    queue     │ │    queue     │ │ longrun-tasks│
           └──────┬───────┘ └──────┬───────┘ └──────────────┘
                  │                │
                  ▼                ▼
┌─────────────────────────┐ ┌─────────────────────────┐
│     RASTER WORKER       │ │     VECTOR WORKER       │
│                         │ │                         │
│  On task completion:    │ │  On task completion:    │
│  1. Update task in DB   │ │  1. Update task in DB   │
│  2. Check if last task  │ │  2. Check if last task  │
│  3. If last: send       │ │  3. If last: send       │
│     stage_complete to   │ │     stage_complete to   │
│     geospatial-jobs ────┼─┼──► Platform processes   │
│                         │ │                         │
│  host.json:             │ │  host.json:             │
│  maxConcurrentCalls: 2  │ │  maxConcurrentCalls: 32 │
└─────────────────────────┘ └─────────────────────────┘
```

### App Mode Configuration

The `APP_MODE` environment variable controls which queues an app listens to:

| Mode | HTTP | Jobs Queue | Raster Tasks | Vector Tasks | Legacy Tasks |
|------|------|------------|--------------|--------------|--------------|
| `standalone` (default) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `platform_raster` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `platform_vector` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `platform_only` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `worker_raster` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `worker_vector` | ✅ | ❌ | ❌ | ✅ | ❌ |

### Message-Based Stage Advancement

The jobs queue now handles TWO message types:

| Message Type | Sender | Content | Platform Action |
|--------------|--------|---------|-----------------|
| `job_submit` | HTTP endpoint | job_id, job_type, parameters | Create Stage 1 tasks, route to queues |
| `stage_complete` | Any worker | job_id, completed_stage | Create next stage OR finalize job |

Workers send `stage_complete` messages back to the centralized jobs queue. Platform handles ALL orchestration.

---

## Files Modified

### Configuration Layer

| File | Changes |
|------|---------|
| `config/defaults.py` | Added `AppModeDefaults`, `TaskRoutingDefaults`, extended `QueueDefaults` with `RASTER_TASKS_QUEUE`, `VECTOR_TASKS_QUEUE` |
| `config/queue_config.py` | Added `raster_tasks_queue`, `vector_tasks_queue` fields |
| `config/app_mode_config.py` | **NEW FILE** - `AppMode` enum, `AppModeConfig` class with queue listening properties |
| `config/__init__.py` | Exported new config classes |

### Task Data Model

| File | Changes |
|------|---------|
| `core/models/task.py` | Added `target_queue`, `executed_by_app`, `execution_started_at` fields for multi-app tracking |
| `core/schema/sql_generator.py` | Added new columns to tasks table DDL + indexes |

### CoreMachine Routing

| File | Changes |
|------|---------|
| `core/machine.py` | Added `_get_queue_for_task()` method for task-type routing |
| `core/machine.py` | Updated `_batch_queue_tasks()` to group tasks by target queue |
| `core/machine.py` | Updated `_individual_queue_tasks()` for per-task routing |
| `core/machine.py` | Updated `_task_definition_to_record()` to set `target_queue` |
| `core/machine.py` | Added `_send_stage_complete_signal()` for worker mode signaling |
| `core/machine.py` | Added `_should_signal_stage_complete()` to check app mode |
| `core/machine.py` | Added `process_stage_complete_message()` for handling stage_complete |

### Function App Triggers

| File | Changes |
|------|---------|
| `function_app.py` | Modified `process_service_bus_job` to detect `message_type` (job_submit vs stage_complete) |
| `function_app.py` | Added `process_raster_task` trigger for `raster-tasks` queue |
| `function_app.py` | Added `process_vector_task` trigger for `vector-tasks` queue |

### Health Monitoring

| File | Changes |
|------|---------|
| `triggers/health.py` | Added `_check_app_mode()` component showing mode, queues, routing |

---

## Task Routing Configuration

Task types are mapped to queues in `config/defaults.py`:

```python
class TaskRoutingDefaults:
    # Raster tasks → raster-tasks queue (memory-intensive, low concurrency)
    RASTER_TASKS = [
        "handler_raster_validate",
        "handler_raster_create_cog",
        "handler_stac_raster_item",
        "handler_raster_create_tiles",
        "handler_raster_create_mosaic",
        "validate_raster",
        "create_cog",
        "extract_stac_metadata",
        "create_tiling_scheme",
        "extract_tile",
        "create_mosaic_json",
    ]

    # Vector tasks → vector-tasks queue (high concurrency, DB-bound)
    VECTOR_TASKS = [
        "handler_vector_prepare",
        "handler_vector_upload",
        "handler_stac_vector_item",
        "process_vector_prepare",
        "process_vector_upload",
        "create_vector_stac",
    ]
```

Tasks not in either list route to the legacy `geospatial-tasks` queue.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `standalone` | App deployment mode |
| `APP_NAME` | `rmhazuregeoapi` | Unique identifier for task tracking |
| `RASTER_APP_URL` | None | External raster app URL (future use) |
| `VECTOR_APP_URL` | None | External vector app URL (future use) |
| `SERVICE_BUS_RASTER_TASKS_QUEUE` | `raster-tasks` | Raster tasks queue name |
| `SERVICE_BUS_VECTOR_TASKS_QUEUE` | `vector-tasks` | Vector tasks queue name |

---

## Deployment Configurations

### Current: Standalone Mode (Default)

```bash
# No environment variables needed - defaults to standalone
func azure functionapp publish rmhazuregeoapi --python --build remote
```

The health endpoint shows:
```json
{
  "mode": "standalone",
  "queues_listening": {
    "jobs": true,
    "raster_tasks": true,
    "vector_tasks": true,
    "legacy_tasks": true
  }
}
```

### Future: Platform + Raster + Vector Worker

**Main Platform App (rmhazuregeoapi)**:
```
APP_MODE=platform_raster
APP_NAME=rmhazuregeoapi
```

**Vector Worker App (rmhgeo-vector)**:
```
APP_MODE=worker_vector
APP_NAME=rmhgeo-vector
```

### Future: Pure Router + Two Workers

**Platform Only (rmhazuregeoapi)**:
```
APP_MODE=platform_only
APP_NAME=rmhazuregeoapi
```

**Raster Worker (rmhgeo-raster)**:
```
APP_MODE=worker_raster
APP_NAME=rmhgeo-raster
```

**Vector Worker (rmhgeo-vector)**:
```
APP_MODE=worker_vector
APP_NAME=rmhgeo-vector
```

---

## Service Bus Queues

| Queue | Purpose | Created | Listener |
|-------|---------|---------|----------|
| `geospatial-jobs` | Job orchestration + stage_complete signals | Existing | Platform apps |
| `raster-tasks` | Raster task processing | **NEW (needs creation)** | Raster apps |
| `vector-tasks` | Vector task processing | **NEW (needs creation)** | Vector apps |
| `geospatial-tasks` | Legacy/fallback | Existing | Standalone only |

### Create New Queues

```bash
# Create raster-tasks queue
az servicebus queue create \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name raster-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P7D

# Create vector-tasks queue
az servicebus queue create \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name vector-tasks \
  --lock-duration PT2M \
  --max-delivery-count 1 \
  --default-message-time-to-live P7D
```

---

## Health Endpoint Output

The `/api/health` endpoint now includes an `app_mode` component:

```json
{
  "component": "app_mode",
  "status": "healthy",
  "details": {
    "mode": "standalone",
    "app_name": "rmhazuregeoapi",
    "queues_listening": {
      "jobs": true,
      "raster_tasks": true,
      "vector_tasks": true,
      "legacy_tasks": true
    },
    "queue_names": {
      "jobs": "geospatial-jobs",
      "raster_tasks": "raster-tasks",
      "vector_tasks": "vector-tasks",
      "legacy_tasks": "geospatial-tasks"
    },
    "routing": {
      "routes_raster_externally": false,
      "routes_vector_externally": false
    },
    "role": {
      "is_platform": true,
      "is_worker": false,
      "has_http": true
    }
  }
}
```

---

## Task Tracking Fields

Each task now records multi-app tracking data:

| Field | Purpose | Set When |
|-------|---------|----------|
| `target_queue` | Which queue task was routed to | Task creation |
| `executed_by_app` | APP_NAME of processing app | Task processing starts |
| `execution_started_at` | When processing began | Task processing starts |

This enables:
- **Debugging**: Know exactly which app processed each task
- **Monitoring**: Track task distribution across workers
- **Performance**: Calculate queue wait time vs execution time

---

## Implementation Status

### Phase 1: Foundation (COMPLETE)

- [x] Add AppModeDefaults, TaskRoutingDefaults to config/defaults.py
- [x] Extend QueueDefaults with raster/vector queue names
- [x] Add raster_tasks_queue, vector_tasks_queue to config/queue_config.py
- [x] Create config/app_mode_config.py with AppModeConfig class
- [x] Export new config classes in config/__init__.py
- [x] Add target_queue, executed_by_app, execution_started_at to task model
- [x] Update sql_generator.py with new task columns + indexes
- [x] Add _get_queue_for_task() to CoreMachine
- [x] Update _batch_queue_tasks() for task-type routing
- [x] Update _individual_queue_tasks() for task-type routing
- [x] Update _task_definition_to_record() to set target_queue
- [x] Add stage_complete signaling to _handle_task_completion()
- [x] Add process_stage_complete_message() to CoreMachine
- [x] Add Service Bus triggers for new queues in function_app.py
- [x] Update health endpoint with app_mode info
- [x] Deploy and test in standalone mode

### Phase 2: Worker Extraction (FUTURE)

- [ ] Create Service Bus queues (raster-tasks, vector-tasks)
- [ ] Create Vector Function App (rmhgeo-vector)
- [ ] Set APP_MODE=worker_vector, APP_NAME=rmhgeo-vector
- [ ] Deploy same codebase
- [ ] Verify vector tasks processed by worker
- [ ] Verify stage_complete signals Platform for stage advancement
- [ ] Update main app host.json for raster optimization (maxConcurrentCalls: 2)

### Phase 3: Raster Worker (FUTURE)

- [ ] Create Raster Function App (rmhgeo-raster) if needed
- [ ] Set APP_MODE=worker_raster
- [ ] Dedicated host.json for memory-intensive GDAL operations

---

## Rollback Plan

If issues arise with multi-app deployment:

1. Set `APP_MODE=standalone` on all apps
2. All apps will process all queues
3. No code changes needed - just environment variable

---

## Cost Impact

| Configuration | Monthly Cost |
|--------------|--------------|
| Standalone (current) | ~$70 |
| Platform + Vector Worker | ~$140 |
| Platform + Raster + Vector | ~$210 |

**ROI**: Workload isolation, independent scaling, optimized concurrency per workload type.

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 07 DEC 2025 | Environment-variable-driven modes | Same codebase, flexible deployment |
| 07 DEC 2025 | All modes keep HTTP endpoints | User feedback - easier debugging |
| 07 DEC 2025 | Task-type-based routing in CoreMachine | Platform layer agnostic |
| 07 DEC 2025 | Message-based stage advancement | Workers signal Platform via jobs queue |
| 07 DEC 2025 | Standalone as default mode | Backward compatible, no breaking changes |

---

**Document Status**: IMPLEMENTED - Phase 1 Complete
**Last Updated**: 07 DEC 2025
