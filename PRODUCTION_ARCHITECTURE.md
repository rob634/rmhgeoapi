# Production Architecture: Function App Separation Strategy

**Date**: 06 DEC 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: PROPOSAL - Under Review

---

## Executive Summary

The current monolithic Function App should be split based on **workload characteristics**. Raster (GDAL) and Vector (geopandas/PostGIS) operations have fundamentally opposite resource and concurrency requirements that cannot be optimized in a single `host.json`.

**Selected Architecture: Option A** - Main ETL App as Entry Point with Vector Worker extraction.

---

## Current Environment

### Existing Function Apps

| App | Purpose | Identity | Storage Access |
|-----|---------|----------|----------------|
| **rmhazuregeoapi** | Main ETL + Platform + Orchestration | `rmhpgflexadmin` | Bronze R, Silver W |
| **OGC/STAC App** | Read-only APIs (OGC Features, STAC) | `rmhpgflexreader` | None |
| **TiTiler** | Dynamic tile serving (Docker) | Service account | Silver R |
| **2 spare slots** | Available for new deployment | TBD | TBD |

### Workload Characteristics

| Workload | Memory per Op | CPU Profile | Ideal Concurrency | Current Setting |
|----------|---------------|-------------|-------------------|-----------------|
| **Raster (GDAL)** | 2-8+ GB | Heavy (reprojection, COG) | LOW (1-2 concurrent) | `maxConcurrentCalls: 2` |
| **Vector (geopandas)** | 20-200 MB | Light (chunk uploads) | HIGH (20-100+ concurrent) | Same as raster 😬 |

### The Problem

You cannot optimize a single `host.json` for both workloads:
- Setting `maxConcurrentCalls: 2` for raster safety kills vector parallelism
- Setting it to 20+ for vector throughput risks OOM on raster jobs

---

## Selected Architecture: Option A

**Main ETL App as Entry Point + Vector Worker Extraction**

### Why Option A?

1. **Uses only 1 spare Function App** - Keep the other for future needs
2. **Platform layer already handles routing** - No CoreMachine changes needed
3. **Minimal code changes** - Main app keeps HTTP triggers, orchestration
4. **Clear separation** - Vector parallelism unlocked without raster OOM risk
5. **Vector writes to PostgreSQL, not Silver** - No storage write permissions needed

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          EXISTING APPS                                    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────┐     ┌─────────────────────┐                    │
│  │   OGC/STAC App      │     │     TiTiler         │                    │
│  │   (Read-Only APIs)  │     │     (Docker)        │                    │
│  │                     │     │                     │                    │
│  │ • OGC Features API  │     │ • Dynamic tiles     │                    │
│  │ • STAC API          │     │ • COG serving       │                    │
│  │ • rmhpgflexreader   │     │ • Silver read       │                    │
│  └─────────────────────┘     └─────────────────────┘                    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                           ETL LAYER                                       │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │              MAIN ETL APP (rmhazuregeoapi) - ENTRY POINT            │  │
│  │              Identity: rmhpgflexadmin                               │  │
│  │              Storage: Bronze R, Silver W                            │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │  HTTP Layer (Platform):                                            │  │
│  │  • POST /api/platform/submit  ─────────────────────────────────┐   │  │
│  │  • POST /api/platform/raster                                   │   │  │
│  │  • POST /api/platform/raster-collection                        │   │  │
│  │  • POST /api/jobs/submit/{job_type}                            │   │  │
│  │  • GET /api/jobs/status/{job_id}                               │   │  │
│  │  • GET /api/platform/status/{request_id}                       │   │  │
│  │  • Admin, health, web interfaces                               │   │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │  Orchestration Layer (CoreMachine):                                │  │
│  │  • Job queue processing (geospatial-jobs)              │           │  │
│  │  • Task routing by type ──────────────────────────────►│           │  │
│  │  • Stage advancement                                   │           │  │
│  │  • "Last task turns out lights" pattern                │           │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │  Raster Task Processing (raster-tasks queue):          │           │  │
│  │  • validate_raster                                     │           │  │
│  │  • create_cog                                          │           │  │
│  │  • extract_stac_metadata                               │           │  │
│  │  • maxConcurrentCalls: 2                               │           │  │
│  │                                                        │           │  │
│  │  host.json: functionTimeout=30min, prefetch=0          │           │  │
│  └────────────────────────────────────────────┬───────────┘           │  │
│                                               │                        │  │
│                              vector-tasks     │                        │  │
│                                               ▼                        │  │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │              VECTOR ETL APP (NEW) - WORKER ONLY                     │  │
│  │              Identity: rmhpgflexadmin (reuse)                       │  │
│  │              Storage: Bronze R only                                 │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │  Service Bus Trigger ONLY (no HTTP):                               │  │
│  │  • vector-tasks queue                                              │  │
│  │                                                                    │  │
│  │  Vector Task Processing:                                           │  │
│  │  • process_vector_prepare                                          │  │
│  │  • process_vector_upload                                           │  │
│  │  • create_vector_stac                                              │  │
│  │                                                                    │  │
│  │  host.json: maxConcurrentCalls=32, prefetch=5, timeout=10min       │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │     Azure Service Bus      │
                    │  • geospatial-jobs         │ ← Job orchestration
                    │  • raster-tasks            │ ← Main app processes
                    │  • vector-tasks            │ ← Vector app processes
                    └───────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────┐
                    │    Azure PostgreSQL        │
                    │    rmhpgflex               │
                    │  • app schema (jobs/tasks) │
                    │  • pgstac schema (STAC)    │
                    │  • geo schema (vectors)    │
                    └───────────────────────────┘
```

---

## Platform Layer: The Routing Engine

The Platform layer (`triggers/trigger_platform.py`) is the **Anti-Corruption Layer** that:

1. **Accepts DDH requests** (dataset_id, resource_id, version_id)
2. **Translates to CoreMachine jobs** (`_translate_to_coremachine()`)
3. **Routes by data type** (VECTOR → `process_vector`, RASTER → `process_raster_v2`)
4. **Handles size-based fallback** (large rasters → `process_large_raster_v2`)

### Current Flow (Before Queue Separation)

```
DDH Request → Platform Trigger → CoreMachine Job → geospatial-tasks queue → Same App
```

### New Flow (With Queue Separation)

```
DDH Request → Platform Trigger → CoreMachine Job
                                       │
                      ┌────────────────┼────────────────┐
                      ▼                ▼                ▼
              raster-tasks      vector-tasks     geospatial-tasks
                      │                │                │
                      ▼                ▼                ▼
               Main ETL App     Vector ETL App    Main ETL App
```

### Where Routing Happens

The routing logic belongs in **CoreMachine** (`core/machine.py`), specifically in the task queueing methods:

- `_batch_queue_tasks()` (line 1229)
- `_individual_queue_tasks()` (line 1296)

Currently both use `self.config.queues.tasks_queue` (single queue). We add routing logic to select queue by task type.

---

## Implementation Plan

### Phase 1: Queue Separation (Main App Only)

**Goal:** Add routing logic, create queues, test with monolith

**No new Function App yet** - Main app listens to ALL queues during this phase.

#### 1.1 Create Service Bus Queues

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

#### 1.2 Add Queue Config

```python
# config/queue_config.py - Add new queue names
class QueueConfig(BaseModel):
    jobs_queue: str = "geospatial-jobs"
    tasks_queue: str = "geospatial-tasks"  # Legacy fallback
    raster_tasks_queue: str = "raster-tasks"  # NEW
    vector_tasks_queue: str = "vector-tasks"  # NEW
```

#### 1.3 Add Task Routing to CoreMachine

```python
# core/machine.py - Add routing method

# Task type → Queue mapping
TASK_QUEUE_ROUTING = {
    # Raster tasks → raster-tasks queue
    "validate_raster": "raster",
    "create_cog": "raster",
    "extract_stac_metadata": "raster",
    "create_tiling_scheme": "raster",
    "extract_tile": "raster",
    "create_mosaic_json": "raster",

    # Vector tasks → vector-tasks queue
    "process_vector_prepare": "vector",
    "process_vector_upload": "vector",
    "create_vector_stac": "vector",
}

def _get_queue_for_task(self, task_type: str) -> str:
    """Route task to appropriate queue based on task type."""
    routing = TASK_QUEUE_ROUTING.get(task_type, "default")

    if routing == "raster":
        return self.config.queues.raster_tasks_queue
    elif routing == "vector":
        return self.config.queues.vector_tasks_queue
    else:
        return self.config.queues.tasks_queue  # Fallback
```

#### 1.4 Update Task Queueing Methods

```python
# core/machine.py - Update _batch_queue_tasks() and _individual_queue_tasks()

def _batch_queue_tasks(self, task_defs, job_id, stage_number):
    # Group tasks by target queue
    tasks_by_queue = {}
    for task_def in task_defs:
        queue_name = self._get_queue_for_task(task_def.task_type)
        if queue_name not in tasks_by_queue:
            tasks_by_queue[queue_name] = []
        tasks_by_queue[queue_name].append(task_def)

    # Send to each queue
    for queue_name, tasks in tasks_by_queue.items():
        # ... existing batch logic, but per queue ...
```

#### 1.5 Add Service Bus Triggers for New Queues

```python
# function_app.py - Add triggers for new queues

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="raster-tasks",
    connection="ServiceBusConnection"
)
def process_raster_task(msg: func.ServiceBusMessage):
    """Process raster task from dedicated queue."""
    core_machine.process_task_message(msg)

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="vector-tasks",
    connection="ServiceBusConnection"
)
def process_vector_task(msg: func.ServiceBusMessage):
    """Process vector task from dedicated queue."""
    core_machine.process_task_message(msg)
```

#### 1.6 Test Phase 1

```bash
# Deploy to main app
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test vector job (should route to vector-tasks queue)
curl -X POST https://rmhazuregeoapi.../api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-vectors",
    "resource_id": "parcels",
    "version_id": "v1",
    "container_name": "rmhazuregeobronze",
    "file_name": "test.geojson",
    "service_name": "Test Parcels"
  }'

# Test raster job (should route to raster-tasks queue)
curl -X POST https://rmhazuregeoapi.../api/platform/raster \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-imagery",
    "resource_id": "site-alpha",
    "version_id": "v1",
    "container_name": "rmhazuregeobronze",
    "file_name": "test.tif",
    "service_name": "Test Imagery"
  }'

# Check queue metrics in Azure Portal
# Verify messages go to correct queues
```

---

### Phase 2: Vector Worker Extraction

**Goal:** Create dedicated Vector ETL Function App with optimized concurrency

#### 2.1 Create Vector Function App

```bash
# Create Function App (using spare slot)
az functionapp create \
  --resource-group rmhazure_rg \
  --name rmhgeo-vector \
  --storage-account rmhazuregeo \
  --plan <existing-app-service-plan> \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4

# Assign managed identity
az functionapp identity assign \
  --resource-group rmhazure_rg \
  --name rmhgeo-vector \
  --identities /subscriptions/.../rmhpgflexadmin
```

#### 2.2 Vector App File Structure

```
rmhgeo-vector/
├── function_app.py          # Service Bus trigger ONLY (no HTTP)
├── host.json                # Vector-optimized settings
├── requirements.txt         # Subset of dependencies (no GDAL!)
│
├── core/                    # CoreMachine (task processing only)
│   ├── machine.py           # Task handler routing
│   ├── state_manager.py     # Database operations
│   └── models/              # Pydantic models
│
├── jobs/
│   └── process_vector.py    # Vector job definition
│
├── services/
│   └── vector/              # Vector handlers only
│       ├── prepare.py
│       ├── upload.py
│       └── stac.py
│
├── config/                  # Shared config (subset)
└── infrastructure/          # PostgreSQL, Service Bus repos
```

#### 2.3 Vector App host.json

```json
{
  "version": "2.0",
  "functionTimeout": "00:10:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 5,
      "messageHandlerOptions": {
        "autoComplete": true,
        "maxConcurrentCalls": 32,
        "maxAutoLockRenewalDuration": "00:10:00"
      }
    }
  },
  "logging": {
    "logLevel": {
      "default": "Information"
    }
  }
}
```

#### 2.4 Vector App function_app.py

```python
"""
Vector ETL Worker - Service Bus Trigger Only

Processes vector tasks from vector-tasks queue.
No HTTP endpoints - all orchestration in main ETL app.
"""
import azure.functions as func
from core.machine import CoreMachine
from jobs import ALL_JOBS
from services import ALL_HANDLERS

app = func.FunctionApp()

# Initialize CoreMachine for task processing
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS
)

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="vector-tasks",
    connection="ServiceBusConnection"
)
def process_vector_task(msg: func.ServiceBusMessage):
    """
    Process vector task from dedicated queue.

    Tasks routed here by main ETL app's CoreMachine.
    Handlers: process_vector_prepare, process_vector_upload, create_vector_stac
    """
    core_machine.process_task_message(msg)
```

#### 2.5 Remove Vector Trigger from Main App

Once Vector app is deployed and tested:

```python
# function_app.py (main app) - Remove vector-tasks trigger
# Keep only raster-tasks and geospatial-tasks triggers
```

---

### Phase 3: Update Main App host.json

After Vector extraction, optimize main app for raster:

```json
{
  "version": "2.0",
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 0,
      "messageHandlerOptions": {
        "autoComplete": true,
        "maxConcurrentCalls": 2,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

---

### Phase 4: Long-Running Container (FUTURE)

**Status:** Deferred until TiTiler Docker app is stable

When needed for 50GB+ files:
1. Create Container App with `longrun-tasks` queue trigger
2. Add size-based routing in Platform layer
3. Use existing RASTER_JOB_FALLBACKS pattern for automatic routing

---

## Identity Strategy

### Option 1: Reuse rmhpgflexadmin (Selected - Simplest)

Both ETL apps use the same managed identity:
- **Pros:** Works immediately, no new identity setup
- **Cons:** Vector app has more permissions than strictly needed

### Option 2: Create rmhpgflexvector (Future - Better Security)

Dedicated identity with minimal permissions:
- `SELECT` on Bronze storage references
- `INSERT/UPDATE/DELETE` on `geo` schema
- `INSERT` on `app.tasks` (status updates)
- `SELECT` on `app.jobs` (read job params)
- `INSERT` on `pgstac` schema (STAC records)
- **No Silver storage access**

**Recommendation:** Start with Option 1, create dedicated identity when security audit requires it.

---

## Service Bus Queue Summary

| Queue | Purpose | Listener | Lock Duration | Max Delivery |
|-------|---------|----------|---------------|--------------|
| `geospatial-jobs` | Job orchestration | Main ETL | PT5M | 1 |
| `raster-tasks` | Raster task processing | Main ETL | PT5M | 1 |
| `vector-tasks` | Vector task processing | Vector ETL | PT2M | 1 |
| `geospatial-tasks` | Legacy/fallback | Main ETL | PT5M | 1 |

---

## Testing Checklist

### Phase 1 Tests
- [ ] Create Service Bus queues
- [ ] Deploy routing logic to main app
- [ ] Submit vector job → verify routes to `vector-tasks`
- [ ] Submit raster job → verify routes to `raster-tasks`
- [ ] Verify jobs complete successfully (same app processes both queues)

### Phase 2 Tests
- [ ] Deploy Vector ETL app
- [ ] Verify Service Bus trigger fires
- [ ] Submit vector job → verify Vector app processes
- [ ] Submit raster job → verify Main app processes
- [ ] Test 10-chunk vector upload → verify parallelism
- [ ] Remove vector trigger from main app
- [ ] Re-test both job types

### Performance Validation
- [ ] Vector job with 100 chunks: Should complete ~10x faster
- [ ] Raster job during vector job: No OOM errors
- [ ] Queue depth monitoring: No message buildup

---

## Cost Analysis

### Current State
| Resource | Monthly Cost |
|----------|--------------|
| rmhazuregeoapi (B3 Basic) | ~$70 |
| OGC/STAC App | ~$70 |
| TiTiler (Docker) | ~$30 |
| **Total** | **~$170** |

### After Phase 2
| Resource | Monthly Cost |
|----------|--------------|
| rmhazuregeoapi (B3 Basic) | ~$70 |
| rmhgeo-vector (B3 Basic) | ~$70 |
| OGC/STAC App | ~$70 |
| TiTiler (Docker) | ~$30 |
| Additional Service Bus queues | ~$5 |
| **Total** | **~$245** |

**ROI:** ~$75/month increase for:
- 10-30x vector throughput improvement
- Workload isolation (no OOM during mixed loads)
- Independent scaling and deployment
- Clear separation of concerns

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 06 DEC 2025 | Select Option A (Main as Entry Point) | Uses only 1 spare slot, Platform layer handles routing |
| 06 DEC 2025 | Reuse rmhpgflexadmin identity | Simplest path, security review later |
| 06 DEC 2025 | Defer Container App (Phase 4) | Wait for TiTiler Docker stability |
| 06 DEC 2025 | CoreMachine handles queue routing | Platform agnostic, task-type based routing |

---

## Open Questions

1. **Vector app name:** `rmhgeo-vector` or different naming convention?
2. **App Service Plan:** Share with main app or separate plan?
3. **Monitoring:** Same Application Insights instance or separate?
4. **QA deployment:** Same architecture or simplified?

---

## Next Steps

1. [x] Review and approve architecture proposal
2. [ ] Create Service Bus queues (`raster-tasks`, `vector-tasks`)
3. [ ] Implement task routing in CoreMachine
4. [ ] Test Phase 1 with monolith
5. [ ] Create Vector Function App
6. [ ] Deploy and test Phase 2
7. [ ] Update main app host.json for raster optimization

---

**Document Status**: PROPOSAL - Under Review
**Last Updated**: 06 DEC 2025
**Next Review**: After Robert's approval
