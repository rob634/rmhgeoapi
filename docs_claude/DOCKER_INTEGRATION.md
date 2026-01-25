# DOCKER_INTEGRATION.md - Mock CoreMachine for Unit Testing

**Purpose**: Enable instant unit testing in Azure Functions with mock infrastructure
**Author**: Robert and Geospatial Claude Legion
**Created**: 23 DEC 2025
**Status**: Ready for implementation

---

## Overview

The `rmhgeoapi-docker` repository contains a `testing/` module that enables full CoreMachine lifecycle testing **without external dependencies** (no PostgreSQL, no Service Bus). This document describes how to integrate that module into `rmhgeoapi` (Azure Functions) for instant unit testing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Azure Functions (rmhgeoapi)                   │
│                                                                  │
│   /api/test/execute/{task_type}  ◄──── NEW HTTP Trigger         │
│         │                                                        │
│         ▼                                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ from testing import setup_single_task_test              │   │
│   │                                                         │   │
│   │ machine, state_mgr, sb_repo, msg = setup_single_task_test│   │
│   │ result = machine.process_task_message(msg)              │   │
│   │                                                         │   │
│   │ return {result, state_snapshot, captured_messages}      │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   Uses:                                                          │
│   ├── MockStateManager (in-memory, no PostgreSQL)               │
│   ├── MockServiceBusRepository (captures, no real queue)        │
│   └── Real handlers (full code execution)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Benefits

| Benefit | Description |
|---------|-------------|
| **Instant Results** | No queue polling - immediate HTTP response |
| **No Database Required** | MockStateManager stores state in memory |
| **No Service Bus Required** | MockServiceBusRepository captures messages |
| **Full Handler Execution** | Real handler code runs (not mocked) |
| **State Inspection** | View job/task state after execution |
| **Message Inspection** | See what messages WOULD have been sent |

---

## Implementation Steps

### Step 1: Copy testing/ Module

```bash
# From rmhgeoapi directory
cp -r ../rmhgeoapi-docker/testing .
```

The `testing/` module contains:

```
testing/
├── __init__.py              # Exports all components
├── mock_state_manager.py    # MockStateManager - in-memory state
├── mock_service_bus.py      # MockServiceBusRepository - message capture
└── test_core_machine.py     # Factory functions
```

### Step 2: Add HTTP Trigger to function_app.py

Add this endpoint to `function_app.py`:

```python
@app.route(route="test/execute/{task_type}", methods=["POST"])
async def test_execute_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Execute handler with mock infrastructure for unit testing.

    Returns immediate results without touching database or queues.

    Request body:
    {
        "params": {...},           # Handler parameters
        "job_type": "optional"     # Optional job type context
    }

    Response:
    {
        "success": true/false,
        "task_type": "handler_name",
        "handler_result": {...},   # What the handler returned
        "lifecycle": {...},        # Task/job state transitions
        "captured_messages": [...], # What would be sent to queues
        "state_snapshot": {...}    # Final state of jobs/tasks
    }
    """
    import json
    import time
    from testing import setup_single_task_test

    task_type = req.route_params.get('task_type')

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    params = body.get('params', {})
    job_type = body.get('job_type', 'test_job')

    # Setup test infrastructure
    machine, state_mgr, sb_repo, task_message = setup_single_task_test(
        task_type=task_type,
        parameters=params,
        job_type=job_type
    )

    # Execute with full lifecycle
    start_time = time.time()
    try:
        result = machine.process_task_message(task_message)
        success = result.get('success', False) if isinstance(result, dict) else True
        handler_result = result
    except Exception as e:
        success = False
        handler_result = {"error": str(e), "error_type": type(e).__name__}

    elapsed = time.time() - start_time

    # Get final state
    state_snapshot = state_mgr.get_state_snapshot()
    captured_messages = sb_repo.get_message_summary()

    # Build response
    response = {
        "success": success,
        "task_type": task_type,
        "elapsed_seconds": round(elapsed, 3),
        "handler_result": handler_result,
        "lifecycle": {
            "task_id": task_message.task_id,
            "job_id": task_message.parent_job_id,
            "job_type": job_type,
            "stage": task_message.stage,
        },
        "captured_messages": captured_messages,
        "state_snapshot": state_snapshot
    }

    return func.HttpResponse(
        json.dumps(response, default=str),
        mimetype="application/json",
        status_code=200 if success else 500
    )
```

### Step 3: Add State Inspection Endpoints (Optional)

For more detailed debugging:

```python
# Shared test state (reset between test sessions)
_test_state = {"machine": None, "state_mgr": None, "sb_repo": None}


@app.route(route="test/state", methods=["GET"])
async def test_get_state(req: func.HttpRequest) -> func.HttpResponse:
    """Get current test state snapshot."""
    import json
    if _test_state["state_mgr"]:
        return func.HttpResponse(
            json.dumps(_test_state["state_mgr"].get_state_snapshot(), default=str),
            mimetype="application/json"
        )
    return func.HttpResponse('{"message": "No test state available"}', mimetype="application/json")


@app.route(route="test/messages", methods=["GET"])
async def test_get_messages(req: func.HttpRequest) -> func.HttpResponse:
    """Get captured queue messages."""
    import json
    if _test_state["sb_repo"]:
        return func.HttpResponse(
            json.dumps(_test_state["sb_repo"].get_message_summary(), default=str),
            mimetype="application/json"
        )
    return func.HttpResponse('{"message": "No messages captured"}', mimetype="application/json")


@app.route(route="test/reset", methods=["POST"])
async def test_reset_state(req: func.HttpRequest) -> func.HttpResponse:
    """Reset test state."""
    _test_state["machine"] = None
    _test_state["state_mgr"] = None
    _test_state["sb_repo"] = None
    return func.HttpResponse('{"message": "Test state reset"}', mimetype="application/json")
```

---

## Usage Examples

### Test a Handler

```bash
# Test validate_raster
curl -X POST https://rmhheavyapi.azurewebsites.net/api/test/execute/validate_raster \
    -H "Content-Type: application/json" \
    -d '{
        "params": {
            "source_url": "https://rmhazuregeo.blob.core.windows.net/bronze/test.tif?sv=..."
        }
    }'
```

### Response Format

```json
{
  "success": true,
  "task_type": "validate_raster",
  "elapsed_seconds": 0.234,
  "handler_result": {
    "valid": true,
    "source_crs": "EPSG:4326",
    "raster_type": {"detected_type": "rgb", "confidence": "VERY_HIGH"},
    "shape": [7777, 5030],
    "band_count": 3,
    "dtype": "uint8"
  },
  "lifecycle": {
    "task_id": "test-task-abc123",
    "job_id": "test-job-xyz789",
    "job_type": "test_job",
    "stage": 1
  },
  "captured_messages": [
    {
      "queue_name": "geospatial-jobs",
      "message_type": "stage_complete",
      "timestamp": "2025-12-23T10:00:00Z"
    }
  ],
  "state_snapshot": {
    "jobs": {
      "test-job-xyz789": {"status": "PROCESSING", "current_stage": 1}
    },
    "tasks": {
      "test-task-abc123": {"status": "COMPLETED", "stage": 1}
    }
  }
}
```

### Test with Job Context

```bash
# Test with specific job type for proper context injection
curl -X POST https://rmhheavyapi.azurewebsites.net/api/test/execute/create_cog \
    -H "Content-Type: application/json" \
    -d '{
        "params": {
            "source_url": "https://...",
            "target_crs": "EPSG:4326"
        },
        "job_type": "process_raster_v2"
    }'
```

---

## Testing Module Components

### MockStateManager

In-memory implementation of StateManager:

```python
from testing import MockStateManager

state_mgr = MockStateManager()

# Create test records
state_mgr.create_test_job("job-1", "process_raster", {"file": "test.tif"})
state_mgr.create_test_task("task-1", "job-1", "validate_raster", stage=1, parameters={})

# Inspect state
print(state_mgr.get_state_snapshot())
# {
#   "jobs": {"job-1": {...}},
#   "tasks": {"task-1": {...}},
#   "stage_stats": {"job-1": {"1": {"total": 1, "completed": 0, "failed": 0}}}
# }

# View operation log
print(state_mgr.get_operation_log())
# [
#   {"operation": "create_job", "job_id": "job-1", ...},
#   {"operation": "create_task", "task_id": "task-1", ...}
# ]
```

### MockServiceBusRepository

Captures queue messages instead of sending:

```python
from testing import MockServiceBusRepository

sb_repo = MockServiceBusRepository()

# After handler execution, inspect captured messages
print(sb_repo.get_sent_messages())
# [
#   {"queue": "geospatial-jobs", "message": {...}, "timestamp": "..."}
# ]

# Filter by queue
jobs_messages = sb_repo.get_messages_for_queue("geospatial-jobs")

# Get stage_complete signals
signals = sb_repo.get_stage_complete_signals()
```

### Factory Functions

```python
from testing import create_test_core_machine, setup_single_task_test

# Full control setup
machine, state_mgr, sb_repo = create_test_core_machine()
# ... create jobs/tasks manually ...
result = machine.process_task_message(task_message)

# Quick single-task test
machine, state_mgr, sb_repo, msg = setup_single_task_test(
    task_type="hello_world_greeting",
    parameters={"message": "Hello!"},
    job_type="hello_world"
)
result = machine.process_task_message(msg)
```

---

## Comparison: Test Endpoint vs Production

| Aspect | `/api/test/execute/*` | Queue Processing |
|--------|----------------------|------------------|
| State Storage | In-memory (MockStateManager) | PostgreSQL |
| Queue Messages | Captured (MockServiceBusRepository) | Sent to Service Bus |
| Response Time | Immediate | Async (poll queue) |
| Database Required | No | Yes |
| Service Bus Required | No | Yes |
| Handler Code | Same (real execution) | Same (real execution) |
| Use Case | Development, debugging | Production |

---

## Sync Strategy

The `testing/` module originated in `rmhgeoapi-docker`. After copying to `rmhgeoapi`:

**Option A (Recommended)**: Bidirectional sync
- Changes to `testing/` can be made in either repo
- Sync manually when needed: `cp -r testing/ ../rmhgeoapi-docker/testing/`

**Option B**: Docker-only development
- Make changes in `rmhgeoapi-docker/testing/`
- Always copy TO rmhgeoapi, never edit here

**Option C**: Future - shared package
- Extract `testing/` to separate pip package
- Install in both projects

---

## Security Considerations

The `/api/test/*` endpoints should be:

1. **Disabled in production** - Use environment variable check:
   ```python
   ENABLE_TEST_ENDPOINTS = os.getenv("ENABLE_TEST_ENDPOINTS", "false").lower() == "true"

   if not ENABLE_TEST_ENDPOINTS:
       return func.HttpResponse("Test endpoints disabled", status_code=404)
   ```

2. **Protected by authentication** - Add function-level auth or API key

3. **Rate limited** - Prevent abuse

---

## Related Documentation

| Document | Location | Purpose |
|----------|----------|---------|
| TESTING_MEMORY.md | rmhgeoapi-docker | Development chronicle |
| CLAUDE.md | rmhgeoapi-docker | Docker worker context |
| WIKI_DOCKER.md | rmhgeoapi | Full architecture guide |

---

## Docker Worker Parallelism Model

**Added**: 23 JAN 2026

This section documents the parallelism architecture of the Docker worker and Azure deployment model.

### Architecture Overview

```
Azure App Service Plan (ASP-rmhazure)
│
├── capacity = 1 (IMPORTANT: Keep at 1 for queue workers)
│
└── Docker Container Instance (rmhheavyapi)
        │
        ├── Main Process (Python/uvicorn/FastAPI)
        │       │
        │       ├── FastAPI endpoints (/health, /handlers, etc.)
        │       │
        │       └── BackgroundQueueWorker thread
        │               │
        │               └── Polls long-running-tasks queue
        │                   └── Processes 1 message at a time (max_message_count=1)
        │
        └── Handler Execution (during task processing)
                │
                └── Can use internal parallelism:
                    ├── Python multiprocessing
                    ├── GDAL internal threads
                    ├── numpy/BLAS parallelism
                    └── ThreadPoolExecutor for I/O
```

### Key Concepts

| Aspect | Configuration | Rationale |
|--------|--------------|-----------|
| **Azure instances** | 1 (capacity=1) | Prevents competing consumers |
| **Queue messages** | 1 at a time | Full resources per task |
| **Internal parallelism** | Allowed | Handlers can spawn threads/processes |
| **Task isolation** | Complete | No concurrent task interference |

### Why Single Instance?

Docker tasks are designed for **large, memory-intensive operations**:
- Multi-GB rasters requiring windowed processing
- H3 pyramid generation with cascade handlers
- Long-running ETL that exceeds Function App timeouts

Processing one task at a time:
- **Prevents OOM**: No concurrent large operations fighting for memory
- **Simplifies checkpointing**: One task's state to track
- **Predictable resources**: All 7.7GB RAM available for current task
- **Easier debugging**: Single task execution path

### Resource Allocation

```
Container Resources (P1v3 tier):
├── CPU: 2 cores
├── RAM: 7.7 GB total
│   ├── System/Python overhead: ~250 MB
│   ├── Available for task: ~7.4 GB
│   └── Tiling threshold: 2 GB (RASTER_TILING_THRESHOLD_MB) - produces tiled output above this
└── Storage: Azure Files mount at /mounts/etl-temp (V0.8 - unlimited capacity)
```

### Horizontal Scaling (If Needed)

To process N tasks in parallel, scale the App Service Plan:

```bash
# Scale to 3 parallel Docker workers
az appservice plan update --name ASP-rmhazure \
  --resource-group rmhazure_rg \
  --number-of-workers 3
```

**Considerations for multi-instance**:
- All instances MUST run same Docker image version
- Each instance processes 1 task → 3 instances = 3 concurrent tasks
- Requires healthy container startup on all instances
- Consider session-enabled queues for workload affinity
- Monitor for competing consumer issues (see PIP-006 in ERRORS_AND_FIXES.md)

### Queue Polling Configuration

From `docker_service.py`:

```python
class BackgroundQueueWorker:
    def __init__(self, ...):
        self.max_wait_time_seconds = 30  # Long poll timeout
        # ...

    def _process_loop(self):
        messages = receiver.receive_messages(
            max_message_count=1,        # One message at a time
            max_wait_time=30            # Wait up to 30s for message
        )
```

### Internal Parallelism Examples

Handlers CAN use internal parallelism for compute-intensive operations:

```python
# Example: GDAL windowed processing with thread pool
def process_large_raster(params):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(process_window, window)
            for window in windows
        ]
        results = [f.result() for f in futures]

# Example: numpy operations (automatically use BLAS threads)
import numpy as np
# numpy will use multiple threads for large array operations

# Example: GDAL internal threading
# Set GDAL_NUM_THREADS environment variable
os.environ['GDAL_NUM_THREADS'] = 'ALL_CPUS'
```

### Monitoring Commands

```bash
# Check current instance count
az webapp list-instances --name rmhheavyapi --resource-group rmhazure_rg \
  --query "[].{name:name, zone:physicalZone}" -o table

# Check App Service Plan capacity
az appservice plan show --name ASP-rmhazure --resource-group rmhazure_rg \
  --query "sku.capacity"

# Check Docker worker health
curl -s https://rmhheavyapi.../health | jq '.background_workers.queue_worker'

# Check queue status
az servicebus queue show --resource-group rmhazure_rg --namespace-name rmhazure \
  --name long-running-tasks --query "countDetails"
```

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Messages dead-lettered immediately | Multiple instances competing | Scale to 1 instance |
| `messages_processed: 0` but queue has messages | Wrong queue name or auth | Check SERVICE_BUS_FQDN |
| High memory during task | Expected for large rasters | Monitor, don't panic |
| Task hangs | Handler bug or infinite loop | Check logs, add timeouts |

---

## Docker Orchestration Framework (F7.18)

**Added**: 24 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Goal**: Reusable infrastructure for Docker-based long-running jobs with connection pooling, checkpointing, and graceful shutdown
**Status**: Phases 1-4 COMPLETE, Phase 5 pending

### Existing Infrastructure

| Component | Status | Location |
|-----------|--------|----------|
| **CheckpointManager** | EXISTS | `infrastructure/checkpoint_manager.py` |
| **Task checkpoint fields** | EXISTS | `checkpoint_phase`, `checkpoint_data`, `checkpoint_updated_at` |
| **Handler pattern** | EXISTS | `services/handler_process_raster_complete.py` |
| **Connection pooling** | COMPLETE | `infrastructure/connection_pool.py` |
| **DockerTaskContext** | COMPLETE | `core/docker_context.py` |
| **Graceful shutdown** | COMPLETE | `docker_service.py` |

### CheckpointManager API

```python
# infrastructure/checkpoint_manager.py
checkpoint = CheckpointManager(task_id, task_repo)
checkpoint.should_skip(phase)      # Check if phase completed
checkpoint.save(phase, data, validate_artifact)  # Save with artifact validation
checkpoint.get_data(key, default)  # Retrieve checkpoint data
checkpoint.is_shutdown_requested() # Check if shutdown signal received
checkpoint.save_and_stop_if_requested(phase, data)  # Save + check in one call
```

### Implementation Phases

#### Phase 1: Connection Pool Manager - COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.1 | Create `ConnectionPoolManager` class | Done |
| S7.18.2 | Integrate with `PostgreSQLRepository._get_connection()` | Done |
| S7.18.3 | Wire token refresh to call `recreate_pool()` | Done |
| S7.18.4 | Add pool config env vars | Done |

**Environment Variables** (Docker mode only):
- `DOCKER_DB_POOL_MIN` - Minimum pool connections (default: 2)
- `DOCKER_DB_POOL_MAX` - Maximum pool connections (default: 10)

#### Phase 2: Checkpoint Integration - COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.5 | Task checkpoint schema | Done |
| S7.18.6 | CheckpointManager class | Done |
| S7.18.7 | Add `is_shutdown_requested()` method | Done |

**New Methods**:
- `set_shutdown_event(event)` - Register shutdown event post-init
- `is_shutdown_requested()` - Check if shutdown signal received
- `should_stop()` - Alias for is_shutdown_requested()
- `save_and_stop_if_requested(phase, data)` - Convenience method

#### Phase 3: Docker Task Context - COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.8 | Create `DockerTaskContext` dataclass | Done |
| S7.18.9 | Modify `BackgroundQueueWorker` to create context | Done |
| S7.18.10 | Pass context to handlers via CoreMachine | Done |
| S7.18.11 | Add progress reporting to task metadata | Done |

**How Handlers Access Context**:
```python
def my_handler(params: Dict) -> Dict:
    context = params.get('_docker_context')  # DockerTaskContext or None
    if context:
        if context.should_stop():
            context.checkpoint.save(phase, data)
            return {'success': True, 'interrupted': True}
        context.report_progress(50, "Halfway done")
```

#### Phase 4: Graceful Shutdown - COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.12 | Create `DockerWorkerLifecycle` class | Done |
| S7.18.13 | Integrate shutdown event with `BackgroundQueueWorker` | Done |
| S7.18.14 | Add shutdown status to `/health` endpoint | Done |
| S7.18.15 | Test graceful shutdown (SIGTERM → checkpoint saved) | Done |

**Graceful Shutdown Flow**:
1. SIGTERM received → `worker_lifecycle.initiate_shutdown()` called
2. Shutdown event set → all workers see `should_stop() = True`
3. In-flight tasks save checkpoint via `DockerTaskContext`
4. BackgroundQueueWorker abandons queued messages (retry later)
5. ConnectionPoolManager drains and closes
6. `/health` returns 503 with `status: "shutting_down"`

#### Phase 5: H3 Bootstrap Docker - PENDING

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.16 | Create `bootstrap_h3_docker` job definition | Pending |
| S7.18.17 | Create `h3_bootstrap_complete` handler | Pending |
| S7.18.18 | Register job and handler in `__init__.py` | Pending |
| S7.18.19 | Test: Rwanda bootstrap with checkpoint/resume | Pending |
| S7.18.20 | Test: Graceful shutdown mid-cascade | Pending |

### Handler Pattern Evolution

```python
# OLD PATTERN (handler creates checkpoint)
def process_raster_complete(params: Dict, context: Optional[Dict] = None):
    task_id = params.get('_task_id')
    if task_id:
        checkpoint = CheckpointManager(task_id, task_repo)  # Handler creates

# NEW PATTERN (context provides checkpoint + shutdown awareness)
def process_raster_complete(params: Dict, context: DockerTaskContext):
    if context.should_stop():  # Shutdown awareness!
        return {'interrupted': True, 'resumable': True}
    if not context.checkpoint.should_skip(1):  # Checkpoint provided
        result = do_work()
        context.checkpoint.save(1, data={'result': result})
```

---

## HTTP-Triggered Docker Worker (F7.15)

**Status**: PLANNED - Alternative to Service Bus polling
**Prerequisite**: Complete F7.13 Option A first, then implement as configuration option

### Concept

Eliminate Docker→Service Bus connection entirely.
Function App task worker HTTP-triggers Docker, then exits. Docker tracks its own state.

```
┌─────────────────┐    ┌──────────────────────┐
│  Function App   │───▶│  Service Bus Queue   │
│  (SB Trigger)   │◀───│  long-running-tasks  │
└────────┬────────┘    └──────────────────────┘
         │
         │ 1. HTTP POST /task/start
         │    {task_id, params, callback_url}
         │
         │ 2. Docker returns 202 Accepted immediately
         ▼
┌─────────────────┐
│  Docker Worker  │──── 3. Process task in background
│  (HTTP only)    │     4. Update task status in PostgreSQL
└────────┬────────┘     5. Optionally call callback_url when done
         │
         │ (Function App is already gone - no timeout issues)
         ▼
   Task completion detected by:
   - Polling task status table
   - Or callback to Function App HTTP endpoint
```

### Why This Might Be Better

1. **Simpler Docker auth** - Only needs HTTP endpoint, no Service Bus SDK
2. **No queue credentials in Docker** - Function App owns all queue logic
3. **Function App exits immediately** - No timeout concerns
4. **State in PostgreSQL** - Already have task status table

### Implementation Stories

| Story | Description | Status |
|-------|-------------|--------|
| S7.15.1 | Create 2-stage job: `process_raster_docker_http` | Pending |
| S7.15.2 | Stage 1 handler: `validate_and_trigger_docker` | Pending |
| S7.15.3 | Docker endpoint: `POST /task/start` | Pending |
| S7.15.4 | Docker background processing with CoreMachine | Pending |
| S7.15.5 | Configuration switch: `DOCKER_ORCHESTRATION_MODE` | Pending |
| S7.15.6 | Test both modes work | Pending |

### Configuration

```bash
# Option A: Docker polls Service Bus (default)
DOCKER_ORCHESTRATION_MODE=service_bus

# Option B: Function App HTTP-triggers Docker
DOCKER_ORCHESTRATION_MODE=http_trigger
DOCKER_WORKER_URL=https://rmhheavyapi-xxx.azurewebsites.net
```

### Docker Execution Model Terminology

| Model | Name | Trigger | Job Suffix | Use Case |
|-------|------|---------|------------|----------|
| **A** | **Queue-Polled** | Docker polls Service Bus | `*_docker` | Heavy ETL, hours-long |
| **B** | **Function-Triggered** | FA HTTP → Docker | `*_triggered` | FA as gatekeeper |

**When to Use Which**:

| Scenario | Model |
|----------|-------|
| Tasks running hours (large rasters) | Queue-Polled |
| FA validation before Docker starts | Function-Triggered |
| Simpler Docker (no Service Bus) | Function-Triggered |
| High-volume parallel tasks | Queue-Polled |

---

*Created: 23 DEC 2025*
*Updated: 24 JAN 2026 - Added Docker Orchestration Framework (F7.18) and HTTP-Triggered Docker (F7.15)*
