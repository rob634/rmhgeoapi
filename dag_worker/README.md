# DAG Worker Module

**EPOCH:** 5 - DAG ORCHESTRATION
**STATUS:** Core
**CREATED:** 29 JAN 2026

## Overview

This module provides DAG task execution capabilities for the Docker worker.
It runs **alongside** the existing Epoch 4 worker, listening to a separate queue.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DOCKER WORKER                                 │
│                                                                  │
│   ┌─────────────────────┐    ┌─────────────────────┐            │
│   │  Epoch 4 Listener   │    │   DAG Listener      │            │
│   │  (epoch4-tasks)     │    │   (dag-worker-tasks)│            │
│   └──────────┬──────────┘    └──────────┬──────────┘            │
│              │                          │                        │
│              └────────────┬─────────────┘                        │
│                           ▼                                      │
│              ┌───────────────────────┐                           │
│              │   SHARED HANDLERS     │                           │
│              │   (raster, vector,    │                           │
│              │    stac, etc.)        │                           │
│              └───────────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

## Components

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports |
| `contracts.py` | TaskMessage, TaskResult schemas |
| `config.py` | Environment-based configuration |
| `handler_registry.py` | Handler name → function mapping |
| `executor.py` | Handler execution with timeout/error handling |
| `reporter.py` | HTTP callback to orchestrator |
| `listener.py` | Service Bus queue consumer |

## Configuration

Set these environment variables to enable the DAG listener:

```bash
# Required
DAG_QUEUE_ENABLED=true
DAG_QUEUE_CONNECTION=<service bus connection string>
DAG_ORCHESTRATOR_CALLBACK_URL=http://orchestrator:8000/api/v1/callbacks/task-result

# Optional
DAG_QUEUE_NAME=dag-worker-tasks          # Default queue name
DAG_WORKER_ID=worker-1                   # Worker identifier (default: hostname)
DAG_MAX_CONCURRENT_TASKS=1               # Parallel task limit
DAG_SHUTDOWN_TIMEOUT=30                  # Graceful shutdown timeout
```

## Usage

### Running Alongside Epoch 4

```python
import asyncio
from dag_worker import DagListener
from dag_worker.config import DagWorkerConfig

async def main():
    # Load config from environment
    dag_config = DagWorkerConfig.from_env()

    # Create listeners
    epoch4_listener = ...  # Existing Epoch 4 listener
    dag_listener = DagListener(dag_config)

    # Run both concurrently
    await asyncio.gather(
        epoch4_listener.run(),
        dag_listener.run(),
    )

asyncio.run(main())
```

### Registering Handlers

```python
from dag_worker.handler_registry import register_handler

@register_handler("my_custom_handler")
async def my_custom_handler(params: dict) -> dict:
    """
    Custom handler function.

    Args:
        params: Parameters from workflow YAML

    Returns:
        Result dictionary (becomes node output)
    """
    result = do_work(params["input_path"])
    return {"output_path": result}
```

### Using Existing Handlers

Import and register existing handlers from rmhgeoapi:

```python
# In handler_registry.py

from services.handler_raster_validate import raster_validate
from services.handler_vector_docker_complete import vector_docker_complete

_REGISTRY["raster_validate"] = raster_validate
_REGISTRY["vector_docker_complete"] = vector_docker_complete
```

## Message Flow

```
1. Orchestrator dispatches task to dag-worker-tasks queue
   {
     "task_id": "job123_validate_0",
     "job_id": "job123",
     "node_id": "validate",
     "handler": "raster_validate",
     "params": {"source_path": "..."},
     "timeout_seconds": 300
   }

2. DagListener receives message from queue

3. TaskExecutor looks up handler, executes with timeout

4. ResultReporter POSTs result to orchestrator callback
   {
     "task_id": "job123_validate_0",
     "job_id": "job123",
     "node_id": "validate",
     "status": "completed",
     "output": {"validated": true, "crs": "EPSG:4326"},
     "execution_duration_ms": 1234
   }

5. DagListener completes (removes) message from queue
```

## Built-in Test Handlers

| Handler | Purpose |
|---------|---------|
| `echo` | Returns input params as output |
| `sleep` | Sleeps for N seconds (for timeout testing) |
| `fail` | Always raises exception (for error testing) |

## Error Handling

| Error Type | Behavior |
|------------|----------|
| Handler exception | Report FAILED to orchestrator, abandon message |
| Timeout | Report FAILED with timeout message |
| Callback failure | Abandon message (retry later) |
| Invalid JSON | Dead-letter message |

## Graceful Shutdown

The executor handles SIGTERM/SIGINT:

1. Stop accepting new tasks
2. Wait for current task to complete (up to `DAG_SHUTDOWN_TIMEOUT`)
3. Report any in-progress results
4. Close connections

## Isolation

This module is **completely self-contained**. It can be copied to
`rmhdagmaster/worker/` once tested, with only import path changes needed.

Files to copy:
- `dag_worker/__init__.py`
- `dag_worker/contracts.py`
- `dag_worker/config.py`
- `dag_worker/handler_registry.py`
- `dag_worker/executor.py`
- `dag_worker/reporter.py`
- `dag_worker/listener.py`

## Testing

```python
import asyncio
from dag_worker import DagListener
from dag_worker.config import DagWorkerConfig

# Use test configuration
config = DagWorkerConfig(
    enabled=True,
    queue_connection="<test connection string>",
    queue_name="dag-worker-tasks-test",
    callback_url="http://localhost:8000/api/v1/callbacks/task-result",
)

# Run listener
listener = DagListener(config)
asyncio.run(listener.run())
```

## Dependencies

- `azure-servicebus>=7.11.0` - Queue consumer
- `httpx>=0.27.0` - HTTP client for callbacks
- `pydantic>=2.0.0` - Message validation

All dependencies are already in `requirements-docker.txt`.
