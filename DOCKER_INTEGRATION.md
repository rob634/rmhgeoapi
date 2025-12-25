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

*Created: 23 DEC 2025*
