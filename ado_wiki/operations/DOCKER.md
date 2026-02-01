# Docker Worker Architecture

**Last Updated**: 22 DEC 2025
**Status**: Foundation Complete - Ready for Docker App Implementation
**Purpose**: Enable long-running tasks without Azure Functions timeout constraints

---

## Executive Summary

The Geospatial Platform supports a **Docker Worker** deployment mode (`WORKER_DOCKER`) that allows the same codebase to run in a Docker container, processing tasks from a dedicated `long-running-tasks` queue. This enables processing that exceeds Azure Functions' 10-minute timeout limit.

**Key Insight**: The codebase is already modular. CoreMachine, handlers, and infrastructure layers have **zero** `azure.functions` imports. Only the trigger layer (`function_app.py`, `triggers/*`) is Azure Functions-specific.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AZURE FUNCTION APP                                 │
│                         (APP_MODE=standalone)                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │ HTTP        │  │ Jobs Queue  │  │ Raster      │  │ Vector           │   │
│  │ Triggers    │  │ Trigger     │  │ Tasks       │  │ Tasks            │   │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘   │
│         │               │                │                   │              │
│         └───────────────┴────────────────┴───────────────────┘              │
│                                   │                                          │
│                         ┌─────────▼─────────┐                               │
│                         │   CoreMachine     │                               │
│                         │  (Orchestrator)   │                               │
│                         └───────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    Routes large tasks to long-running queue
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │   long-running-tasks queue    │
                    │      (Service Bus)            │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DOCKER CONTAINER                                   │
│                        (APP_MODE=worker_docker)                              │
│                                                                              │
│  ┌─────────────────┐      ┌─────────────────┐      ┌──────────────────┐    │
│  │  docker_main.py │ ───▶ │   CoreMachine   │ ───▶ │  Same Handlers   │    │
│  │  (Queue Poller) │      │  (Orchestrator) │      │  (create_cog,    │    │
│  └─────────────────┘      └─────────────────┘      │   fathom_*, etc) │    │
│                                    │                └──────────────────┘    │
│                                    │                                         │
│                          Signals stage_complete                              │
│                                    │                                         │
│                                    ▼                                         │
│                    ┌───────────────────────────────┐                        │
│                    │   geospatial-jobs queue       │                        │
│                    │   (back to Function App)      │                        │
│                    └───────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## What Has Been Implemented (22 DEC 2025)

### 1. App Mode Configuration

**File**: `config/app_mode_config.py`

```python
class AppMode(str, Enum):
    STANDALONE = "standalone"           # All queues, all endpoints
    PLATFORM_RASTER = "platform_raster" # HTTP + jobs + raster-tasks
    PLATFORM_VECTOR = "platform_vector" # HTTP + jobs + vector-tasks
    PLATFORM_ONLY = "platform_only"     # HTTP + jobs only
    WORKER_RASTER = "worker_raster"     # raster-tasks only
    WORKER_VECTOR = "worker_vector"     # vector-tasks only
    WORKER_DOCKER = "worker_docker"     # long-running-tasks only (NEW)
```

**Properties for WORKER_DOCKER**:

| Property | Value | Purpose |
|----------|-------|---------|
| `has_http_endpoints` | `False` | No HTTP - polling only |
| `listens_to_jobs_queue` | `False` | Platform handles orchestration |
| `listens_to_raster_tasks` | `False` | Uses different queue |
| `listens_to_vector_tasks` | `False` | Uses different queue |
| `listens_to_long_running_tasks` | `True` | **Primary queue** |
| `is_worker_mode` | `True` | Signals stage_complete to jobs queue |
| `is_docker_mode` | `True` | Identifies Docker deployment |

### 2. Runtime Validation

**File**: `config/app_mode_config.py` → `from_environment()`

If `APP_MODE=worker_docker` is set but `FUNCTIONS_WORKER_RUNTIME` environment variable exists (indicating Azure Functions), the app fails loudly:

```python
if mode == AppMode.WORKER_DOCKER and is_azure_functions:
    raise ValueError(
        "INVALID CONFIGURATION: APP_MODE='worker_docker' cannot be used in Azure Functions. "
        "WORKER_DOCKER mode is only valid in Docker containers."
    )
```

### 3. Queue Configuration

**File**: `config/defaults.py` → `QueueDefaults`

```python
LONG_RUNNING_TASKS_QUEUE = "long-running-tasks"
```

**File**: `config/queue_config.py` → `QueueConfig`

```python
long_running_tasks_queue: str = Field(
    default=QueueDefaults.LONG_RUNNING_TASKS_QUEUE,
    description="Service Bus queue for long-running tasks (Docker worker)"
)
```

**Environment Variable**: `SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE`

### 4. Task Routing Configuration

**File**: `config/defaults.py` → `TaskRoutingDefaults`

```python
LONG_RUNNING_TASKS = [
    # Currently empty - no tasks route here yet
    # Future: "create_cog_large", "fathom_merge_large", etc.
]
```

---

## Code Modularity Assessment

### What Docker CAN Import (No azure.functions dependency)

| Module | Import Safe | Notes |
|--------|-------------|-------|
| `core/machine.py` | ✅ | CoreMachine orchestrator |
| `core/state_manager.py` | ✅ | Job/task state management |
| `core/models/*` | ✅ | Pydantic models |
| `services/*` | ✅ | All 56+ handlers |
| `jobs/*` | ✅ | All 27 job definitions |
| `infrastructure/*` | ✅ | Repositories (blob, postgres, service bus) |
| `config/*` | ✅ | All configuration |
| `util_logger.py` | ✅ | Logging utilities |

### What Docker CANNOT Import

| Module | Why |
|--------|-----|
| `function_app.py` | Azure Functions entry point |
| `triggers/*` | HTTP/ServiceBus trigger decorators |
| `web_interfaces/*` | HTTP response handling |

---

## Environment Variables for Docker

Docker container requires these environment variables:

### Required

```bash
# App Mode (MUST be worker_docker)
APP_MODE=worker_docker
APP_NAME=docker-worker-01  # Unique identifier for task tracking

# Service Bus
ServiceBusConnection=Endpoint=sb://your-namespace.servicebus.windows.net/;SharedAccessKeyName=...
# OR for Managed Identity:
SERVICE_BUS_NAMESPACE=your-namespace.servicebus.windows.net

# PostgreSQL
POSTGRES_HOST=your-server.postgres.database.azure.com
POSTGRES_USER=your-admin-user
POSTGRES_PASSWORD=your-password  # Or use managed identity
POSTGRES_DATABASE=your-database

# Storage (for blob operations)
BRONZE_STORAGE_ACCOUNT=<bronze-storage>
SILVER_STORAGE_ACCOUNT=<silver-storage>
```

### Optional

```bash
# Queue name override (default: long-running-tasks)
SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE=long-running-tasks

# Logging
LOG_LEVEL=INFO
```

---

## Next Steps for Docker App Implementation

### Step 1: Create `docker_main.py` (Entry Point)

Create a new file in the Docker project that polls the queue:

```python
#!/usr/bin/env python3
"""
Docker Worker Entry Point.

Polls the long-running-tasks queue and processes tasks via CoreMachine.
This replaces function_app.py for Docker deployments.

Usage:
    APP_MODE=worker_docker python docker_main.py
"""

import os
import sys
import time
import json
import signal
import logging
from datetime import datetime, timezone

# Ensure APP_MODE is set before importing config
os.environ.setdefault("APP_MODE", "worker_docker")

from config import get_config
from config.app_mode_config import AppModeConfig
from core.machine import CoreMachine
from core.models.task import TaskQueueMessage
from infrastructure.service_bus import ServiceBusRepository
from util_logger import LoggerFactory

# Graceful shutdown flag
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logging.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True

def main():
    """Main polling loop for Docker worker."""
    global _shutdown_requested

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Initialize
    logger = LoggerFactory.create_logger("docker_worker")
    config = get_config()
    app_mode_config = AppModeConfig.from_environment()

    # Validate we're in Docker mode
    if not app_mode_config.is_docker_mode:
        logger.error(f"Invalid APP_MODE: {app_mode_config.mode.value}. Must be 'worker_docker'")
        sys.exit(1)

    logger.info(f"Starting Docker Worker: {app_mode_config.app_name}")
    logger.info(f"Listening to queue: {config.queues.long_running_tasks_queue}")

    # Initialize CoreMachine and ServiceBus
    core_machine = CoreMachine()
    sb_repo = ServiceBusRepository()

    queue_name = config.queues.long_running_tasks_queue
    poll_interval_seconds = 5  # Time to wait when queue is empty
    max_messages_per_poll = 1  # Process one at a time for long-running tasks

    logger.info("Entering main polling loop...")

    while not _shutdown_requested:
        try:
            # Poll for messages
            messages = sb_repo.receive_messages(
                queue_name=queue_name,
                max_messages=max_messages_per_poll,
                max_wait_time=30  # Long poll - wait up to 30s for messages
            )

            if not messages:
                # No messages, continue polling
                continue

            for msg in messages:
                if _shutdown_requested:
                    logger.info("Shutdown requested, abandoning current message")
                    sb_repo.abandon_message(queue_name, msg)
                    break

                try:
                    # Parse task message
                    task_data = msg.get('content', {})
                    task_message = TaskQueueMessage(**task_data)

                    logger.info(
                        f"Processing task: {task_message.task_id[:16]}... "
                        f"(type: {task_message.task_type}, job: {task_message.parent_job_id[:16]}...)"
                    )

                    start_time = time.time()

                    # Process via CoreMachine (same as Function App)
                    result = core_machine.process_task_message(task_message)

                    elapsed = time.time() - start_time

                    if result.get('success'):
                        logger.info(f"Task completed in {elapsed:.2f}s: {task_message.task_id[:16]}...")
                        sb_repo.complete_message(queue_name, msg)

                        if result.get('stage_complete'):
                            logger.info(f"Stage {task_message.stage} complete, signaled to jobs queue")
                    else:
                        error = result.get('error', 'Unknown error')
                        logger.error(f"Task failed after {elapsed:.2f}s: {error}")
                        # Dead-letter failed messages
                        sb_repo.dead_letter_message(queue_name, msg, reason=error)

                except Exception as e:
                    logger.exception(f"Exception processing message: {e}")
                    sb_repo.dead_letter_message(queue_name, msg, reason=str(e))

        except Exception as e:
            logger.exception(f"Exception in polling loop: {e}")
            time.sleep(poll_interval_seconds)

    logger.info("Docker Worker shutdown complete")

if __name__ == "__main__":
    main()
```

### Step 2: Verify ServiceBusRepository Methods

Check that `infrastructure/service_bus.py` has these methods (they should exist):

```python
# Required methods for Docker worker:
receive_messages(queue_name, max_messages, max_wait_time) -> List[dict]
complete_message(queue_name, message) -> None
abandon_message(queue_name, message) -> None
dead_letter_message(queue_name, message, reason) -> None
```

If `dead_letter_message` doesn't exist, add it or use `abandon_message` with a retry counter.

### Step 3: Create `Dockerfile`

```dockerfile
FROM python:3.11-slim

# Install GDAL and system dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libpq-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment
ENV GDAL_VERSION=3.6.2
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# Copy application code
COPY . .

# Set environment
ENV APP_MODE=worker_docker
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from config import get_config; print('OK')" || exit 1

# Run the worker
CMD ["python", "docker_main.py"]
```

### Step 4: Create `requirements-docker.txt`

Copy from `requirements.txt` but **exclude**:
- `azure-functions`
- Any Azure Functions-specific packages

```bash
# Generate from main requirements, excluding azure-functions
grep -v "azure-functions" requirements.txt > requirements-docker.txt
```

### Step 5: Implement Task Routing in Function App

The Function App needs logic to route large tasks to the Docker queue. This happens in CoreMachine or OrchestrationManager.

**File to modify**: `core/machine.py` or `core/orchestration_manager.py`

```python
def _route_task_to_queue(self, task: TaskDefinition) -> str:
    """Determine which queue a task should be routed to."""

    # Check if task should go to long-running queue
    if self._should_route_to_docker(task):
        return self.config.queues.long_running_tasks_queue

    # Existing routing logic
    if task.task_type in TaskRoutingDefaults.RASTER_TASKS:
        return self.config.queues.raster_tasks_queue
    elif task.task_type in TaskRoutingDefaults.VECTOR_TASKS:
        return self.config.queues.vector_tasks_queue
    else:
        raise ContractViolationError(f"Unknown task type: {task.task_type}")

def _should_route_to_docker(self, task: TaskDefinition) -> bool:
    """Determine if task should be routed to Docker worker."""

    # Option 1: Explicit task types
    if task.task_type in TaskRoutingDefaults.LONG_RUNNING_TASKS:
        return True

    # Option 2: File size threshold (check task parameters)
    file_size_mb = task.parameters.get('file_size_mb', 0)
    if file_size_mb > RasterDefaults.RASTER_SIZE_THRESHOLD_MB:
        return True

    # Option 3: Job-level flag
    if task.parameters.get('_route_to_docker', False):
        return True

    return False
```

### Step 6: Create the Azure Service Bus Queue

```bash
# Create the long-running-tasks queue in Azure
az servicebus queue create \
    --resource-group <resource-group> \
    --namespace-name your-servicebus-namespace \
    --name long-running-tasks \
    --max-size 5120 \
    --default-message-time-to-live P14D \
    --lock-duration PT5M
```

Note the longer `lock-duration` (5 minutes vs default 30 seconds) for long-running tasks.

---

## Testing the Docker Worker

### Local Testing (without Docker)

```bash
# Set environment variables
export APP_MODE=worker_docker
export APP_NAME=docker-worker-local
export ServiceBusConnection="your-connection-string"
export POSTGRES_HOST=localhost
# ... other env vars ...

# Run directly
python docker_main.py
```

### Docker Testing

```bash
# Build
docker build -t geospatial-worker:latest .

# Run with environment file
docker run --env-file docker.env geospatial-worker:latest

# Or with individual env vars
docker run \
    -e APP_MODE=worker_docker \
    -e APP_NAME=docker-worker-01 \
    -e ServiceBusConnection="..." \
    geospatial-worker:latest
```

### Integration Test

1. Submit a job that routes to `long-running-tasks` queue
2. Verify Docker worker picks up the task
3. Verify task completes and stage_complete signal is sent
4. Verify Function App advances to next stage

---

## Monitoring and Observability

### Logging

The Docker worker uses the same `util_logger.py` as the Function App, producing structured JSON logs:

```json
{
    "timestamp": "2025-12-22T10:30:00Z",
    "level": "INFO",
    "message": "Task completed in 45.23s: abc12345...",
    "task_id": "abc12345-...",
    "job_id": "def67890-...",
    "task_type": "create_cog",
    "app_name": "docker-worker-01"
}
```

### Health Endpoint (Optional)

For Kubernetes/container orchestration, add a simple health HTTP endpoint:

```python
# In docker_main.py, add a background thread for health checks
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server(port=8080):
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
```

---

## Error Handling

### Task Failures

When a task fails:
1. Log the error with full context
2. Dead-letter the message (prevents infinite retry)
3. CoreMachine marks task as FAILED in PostgreSQL
4. Job may continue (COMPLETED_WITH_ERRORS) or fail depending on configuration

### Graceful Shutdown

The worker handles SIGTERM/SIGINT:
1. Sets `_shutdown_requested` flag
2. Completes current task (doesn't abandon mid-processing)
3. Stops polling for new messages
4. Exits cleanly

This is critical for container orchestration (Kubernetes, ECS, etc.).

---

## Deployment Options

### Azure Container Instances (ACI)

Simplest option for single-container deployment:

```bash
az container create \
    --resource-group <resource-group> \
    --name geospatial-worker \
    --image your-registry.azurecr.io/geospatial-worker:latest \
    --cpu 4 \
    --memory 16 \
    --environment-variables \
        APP_MODE=worker_docker \
        APP_NAME=docker-worker-aci \
    --secure-environment-variables \
        ServiceBusConnection="..." \
        POSTGRES_PASSWORD="..."
```

### Azure Container Apps

For auto-scaling based on queue depth:

```yaml
# container-app.yaml
properties:
  configuration:
    secrets:
      - name: servicebus-connection
        value: "..."
    scale:
      minReplicas: 0
      maxReplicas: 10
      rules:
        - name: queue-scaling
          azureQueue:
            queueName: long-running-tasks
            queueLength: 5
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: geospatial-worker
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: worker
          image: geospatial-worker:latest
          env:
            - name: APP_MODE
              value: "worker_docker"
          resources:
            requests:
              memory: "8Gi"
              cpu: "2"
            limits:
              memory: "16Gi"
              cpu: "4"
```

---

## Summary Checklist

### Done in This Codebase ✅

- [x] `WORKER_DOCKER` app mode enum
- [x] `is_docker_mode` property
- [x] `listens_to_long_running_tasks` property
- [x] `is_worker_mode` includes WORKER_DOCKER
- [x] Runtime validation (fails in Azure Functions)
- [x] Queue config: `long-running-tasks`
- [x] Environment variable: `SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE`
- [x] `LONG_RUNNING_TASKS` routing list (empty, ready for task types)

### To Do in Docker App 📋

- [ ] Create `docker_main.py` entry point
- [ ] Verify/add ServiceBusRepository message handling methods
- [ ] Create `Dockerfile`
- [ ] Create `requirements-docker.txt`
- [ ] Test locally with `APP_MODE=worker_docker`
- [ ] Build and test Docker image
- [ ] Add task routing logic in CoreMachine (or manual queue submission for testing)
- [ ] Create Azure Service Bus queue
- [ ] Deploy to Azure (ACI, Container Apps, or AKS)
- [ ] Integration test: job → docker → stage_complete → function app

---

## Contact / Handoff Notes

This document was prepared for handoff to "Docker Claude" - the Claude instance working on the Docker container application.

**Key Files to Reference**:
- `config/app_mode_config.py` - AppMode enum and properties
- `config/queue_config.py` - Queue configuration
- `config/defaults.py` - TaskRoutingDefaults.LONG_RUNNING_TASKS
- `core/machine.py` - CoreMachine.process_task_message()
- `infrastructure/service_bus.py` - ServiceBusRepository

**The architecture is ready**. The Docker app just needs an entry point that polls and calls `CoreMachine.process_task_message()`.
