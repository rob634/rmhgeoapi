# GDAL Docker Worker - Implementation Guide

**Date**: 12 DEC 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Phase 1 - rmhgeoapi Modifications

---

## Overview

A **separate Docker-based worker** to handle long-running GDAL operations that exceed the Azure Functions 30-minute timeout. This document serves as:

1. **Implementation tracker** for rmhgeoapi modifications (Phase 1)
2. **Foundation document** for the new `rmh-gdal-worker` repository (Phase 2+)

### Key Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Platform | Azure Web App (Docker) | Dedicated App Service Plan, no EA approval needed |
| Codebase | Separate Git repo | Clean separation, copy only needed components |
| Queue | NEW `docker-tasks` queue | Explicit routing, no race conditions with Function App |
| Timeout | 1 hour default (configurable) | Covers largest raster operations |
| Priority | Raster operations only | Vector timeout issues are rare |

### Critical Finding: Architecture Already Supports Multi-Queue Jobs!

The rmhgeoapi codebase **already supports** routing different tasks within the same job to different queues:

```python
# core/logic/calculations.py - Stage completion is QUEUE-AGNOSTIC
def is_stage_complete(context: StageExecutionContext) -> bool:
    return (context.completed_tasks + context.failed_tasks) >= context.total_tasks
    # ^^^ Counts tasks in DATABASE - doesn't care which queue processed them!
```

This means a single job can have tasks processed by both Function App AND Docker worker:

```
Job: process_large_raster_v2 (5 stages)
├── Stage 1: generate_tiling_scheme → raster-tasks → Function App (fast)
├── Stage 2: extract_tiles → docker-tasks → Docker Worker (slow, 45 min)
├── Stage 3: create_cogs → raster-tasks → Function App (fast)
├── Stage 4: create_mosaicjson → raster-tasks → Function App (fast)
└── Stage 5: create_stac → raster-tasks → Function App (fast)
```

---

## Phase 1 TODO: rmhgeoapi Modifications

### 1.1 Add Docker Queue Configuration

**File**: `config/defaults.py`

- [ ] Add `DOCKER_TASKS_QUEUE = "docker-tasks"` to `QueueDefaults` class
- [ ] Add `DockerRoutingDefaults` class:
  ```python
  class DockerRoutingDefaults:
      """Docker worker routing configuration."""

      # Task types that ALWAYS route to Docker (regardless of file size)
      DOCKER_TASK_TYPES = [
          "handler_tile_extraction",      # Stage 2 of process_large_raster_v2
          "handler_large_cog_creation",   # Future: Very large COG creation
      ]

      # Dynamic routing thresholds
      SIZE_THRESHOLD_MB = 1000           # Files >1GB route to Docker
      DURATION_THRESHOLD_MINUTES = 20    # Estimated >20 min route to Docker
  ```

**File**: `config/queues_config.py`

- [ ] Add `docker_tasks_queue` field to `QueuesConfig` model:
  ```python
  docker_tasks_queue: str = Field(
      default=QueueDefaults.DOCKER_TASKS_QUEUE,
      description="Queue for long-running Docker worker tasks"
  )
  ```

### 1.2 Update CoreMachine Task Routing

**File**: `core/machine.py`

- [ ] Add `_should_route_to_docker()` method:
  ```python
  def _should_route_to_docker(self, task_type: str, parameters: dict = None) -> bool:
      """
      Determine if task should route to Docker worker queue.

      Criteria (checked in order):
      1. Task type is in DOCKER_TASK_TYPES list → Always Docker
      2. File size > SIZE_THRESHOLD_MB → Docker
      3. Estimated duration > DURATION_THRESHOLD_MINUTES → Docker

      Returns:
          True if task should go to docker-tasks queue
      """
      from config.defaults import DockerRoutingDefaults

      # Explicit task type routing
      if task_type in DockerRoutingDefaults.DOCKER_TASK_TYPES:
          self.logger.debug(f"📦 Task '{task_type}' → docker-tasks (explicit type)")
          return True

      # Dynamic routing based on parameters
      if parameters:
          file_size_mb = parameters.get('file_size_mb', 0)
          if file_size_mb > DockerRoutingDefaults.SIZE_THRESHOLD_MB:
              self.logger.debug(f"📦 Task '{task_type}' → docker-tasks (size: {file_size_mb}MB)")
              return True

          estimated_minutes = parameters.get('estimated_duration_minutes', 0)
          if estimated_minutes > DockerRoutingDefaults.DURATION_THRESHOLD_MINUTES:
              self.logger.debug(f"📦 Task '{task_type}' → docker-tasks (duration: {estimated_minutes}min)")
              return True

      return False
  ```

- [ ] Update `_get_queue_for_task()` to check Docker routing first:
  ```python
  def _get_queue_for_task(self, task_type: str, parameters: dict = None) -> str:
      """Route task to appropriate queue based on task type and parameters."""
      from utils.errors import ContractViolationError

      # Check Docker routing FIRST (takes precedence)
      if self._should_route_to_docker(task_type, parameters):
          return self.config.queues.docker_tasks_queue

      # Standard raster/vector routing
      if task_type in TaskRoutingDefaults.RASTER_TASKS:
          return self.config.queues.raster_tasks_queue
      elif task_type in TaskRoutingDefaults.VECTOR_TASKS:
          return self.config.queues.vector_tasks_queue
      else:
          raise ContractViolationError(
              f"Task type '{task_type}' is not mapped to a queue. "
              f"Add to TaskRoutingDefaults or DockerRoutingDefaults."
          )
  ```

- [ ] Update `_batch_queue_tasks()` to pass parameters to routing
- [ ] Update `_individual_queue_tasks()` to pass parameters to routing

### 1.3 Add App Mode for Docker Worker

**File**: `config/app_mode_config.py`

- [ ] Add `WORKER_DOCKER` to `AppMode` enum:
  ```python
  WORKER_DOCKER = "worker_docker"     # docker-tasks only (Docker Web App)
  ```

- [ ] Add `listens_to_docker_tasks` property:
  ```python
  @property
  def listens_to_docker_tasks(self) -> bool:
      """Whether this mode processes docker-tasks queue."""
      return self.mode in [
          AppMode.STANDALONE,      # Dev/test - listen to all
          AppMode.WORKER_DOCKER,   # Docker worker - primary listener
      ]
  ```

### 1.4 Create Service Bus Queue

**Azure Portal / CLI**:

- [ ] Create `docker-tasks` queue in Service Bus namespace `rmhazuregeosb`
- [ ] Configure queue settings:
  - Max delivery count: 3 (same as other queues)
  - Lock duration: 5 minutes (longer for long-running tasks)
  - Default TTL: 7 days
  - Dead-lettering enabled

**CLI Command**:
```bash
az servicebus queue create \
  --resource-group rmhazure_rg \
  --namespace-name rmhazuregeosb \
  --name docker-tasks \
  --lock-duration PT5M \
  --max-delivery-count 3 \
  --default-message-time-to-live P7D \
  --enable-dead-lettering-on-message-expiration true
```

### 1.5 Testing

- [ ] Deploy updated rmhgeoapi to Azure
- [ ] Submit test job with task in `DOCKER_TASK_TYPES`
- [ ] Verify task routes to `docker-tasks` queue (check Service Bus Explorer)
- [ ] Verify task does NOT get processed (no Docker worker yet)
- [ ] Verify job status shows task as "queued" on `docker-tasks`

---

## Phase 2: New Repository Setup (rmh-gdal-worker)

### Repository Structure

```
rmh-gdal-worker/                   # NEW GIT REPO
├── Dockerfile                     # GDAL + Python base image
├── requirements.txt               # azure-servicebus, rasterio, psycopg, etc.
├── .dockerignore                  # Exclude docs, tests, __pycache__
├── README.md                      # Deployment instructions
├── GDAL_WORKER.md                 # THIS FILE (copied from rmhgeoapi)
│
├── worker/
│   ├── __init__.py
│   ├── main.py                    # Entry point: Service Bus listener loop
│   ├── task_processor.py          # Task execution wrapper
│   └── health.py                  # Health check endpoint (optional)
│
├── core/                          # COPIED from rmhgeoapi (subset)
│   ├── __init__.py
│   ├── machine.py                 # CoreMachine (task processing only)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── task.py                # TaskRecord model
│   │   └── job.py                 # JobRecord model (read-only)
│   └── logic/
│       ├── __init__.py
│       └── calculations.py        # is_stage_complete()
│
├── services/                      # COPIED from rmhgeoapi (raster only)
│   ├── __init__.py
│   ├── tile_extraction.py         # handler_tile_extraction
│   ├── cog_creation.py            # handler_large_cog_creation
│   └── registry.py                # Handler registry
│
├── config/
│   ├── __init__.py
│   ├── settings.py                # Environment-based configuration
│   └── defaults.py                # Worker-specific defaults
│
└── infrastructure/                # COPIED from rmhgeoapi (subset)
    ├── __init__.py
    ├── database.py                # PostgreSQL connection
    ├── storage.py                 # Azure Blob Storage
    └── service_bus.py             # Service Bus send/receive
```

### Dockerfile

```dockerfile
# rmh-gdal-worker/Dockerfile
FROM python:3.11-slim

# Install GDAL system dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV GDAL_CONFIG=/usr/bin/gdal-config

# Create non-root user
RUN useradd -m -s /bin/bash worker
USER worker
WORKDIR /home/worker/app

# Install Python dependencies
COPY --chown=worker:worker requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy application code
COPY --chown=worker:worker . .

# Health check endpoint (optional)
EXPOSE 8080

# Entry point
ENV PYTHONPATH=/home/worker/app
CMD ["python", "-m", "worker.main"]
```

### requirements.txt

```
# Azure SDKs
azure-servicebus>=7.11.0
azure-storage-blob>=12.19.0
azure-identity>=1.15.0

# Database
psycopg[binary]>=3.1.0

# Geospatial
rasterio>=1.3.9
rio-cogeo>=5.0.0
GDAL>=3.6.0

# Core
pydantic>=2.5.0
python-dotenv>=1.0.0

# Monitoring (optional)
applicationinsights>=0.11.10
opencensus-ext-azure>=1.1.0
```

### Worker Entry Point (worker/main.py)

```python
"""
Docker Worker Entry Point.

Listens to docker-tasks queue and processes long-running GDAL operations.
Same task processing logic as Azure Functions, different runtime.

Environment Variables:
    SERVICE_BUS_CONNECTION_STRING: Service Bus connection (or use Managed Identity)
    POSTGIS_HOST: PostgreSQL host
    POSTGIS_DATABASE: Database name
    APP_NAME: Worker identifier (default: gdal-docker-worker)
    WORKER_TIMEOUT_MINUTES: Max task duration (default: 60)
    WORKER_CONCURRENCY: Max concurrent tasks (default: 2)
"""

import asyncio
import signal
import logging
import os
from datetime import datetime, timezone

from azure.servicebus.aio import ServiceBusClient
from azure.identity.aio import DefaultAzureCredential

from config.settings import WorkerSettings
from worker.task_processor import TaskProcessor

logger = logging.getLogger(__name__)


class DockerWorker:
    """Service Bus listener for docker-tasks queue."""

    def __init__(self):
        self.settings = WorkerSettings.from_environment()
        self.processor = TaskProcessor(self.settings)
        self.running = True
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Handle graceful shutdown on SIGTERM/SIGINT."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._shutdown_handler)

    def _shutdown_handler(self, signum, frame):
        """Graceful shutdown handler."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False

    async def run(self):
        """Main worker loop."""
        logger.info(f"Starting Docker worker: {self.settings.app_name}")
        logger.info(f"Listening to queue: {self.settings.docker_tasks_queue}")
        logger.info(f"Timeout: {self.settings.timeout_minutes} minutes")

        # Use Managed Identity or connection string
        if self.settings.service_bus_connection_string:
            client = ServiceBusClient.from_connection_string(
                self.settings.service_bus_connection_string
            )
        else:
            credential = DefaultAzureCredential()
            client = ServiceBusClient(
                fully_qualified_namespace=self.settings.service_bus_namespace,
                credential=credential
            )

        async with client:
            receiver = client.get_queue_receiver(
                queue_name=self.settings.docker_tasks_queue,
                max_wait_time=30  # Poll every 30 seconds
            )

            async with receiver:
                while self.running:
                    messages = await receiver.receive_messages(
                        max_message_count=self.settings.concurrency,
                        max_wait_time=30
                    )

                    for message in messages:
                        try:
                            await self.processor.process_message(message)
                            await receiver.complete_message(message)
                        except Exception as e:
                            logger.error(f"Task failed: {e}")
                            # Let Service Bus handle retry via dead-lettering
                            await receiver.abandon_message(message)

        logger.info("Docker worker shutdown complete")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    worker = DockerWorker()
    asyncio.run(worker.run())
```

---

## Phase 3: Worker Implementation

### Task Processor (worker/task_processor.py)

```python
"""
Task processor for Docker worker.

Executes GDAL handlers and signals stage completion.
"""

import json
import logging
from datetime import datetime, timezone

from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusSender

from core.models.task import TaskRecord, TaskStatus
from services.registry import HANDLER_REGISTRY
from infrastructure.database import DatabaseClient
from infrastructure.service_bus import ServiceBusClient

logger = logging.getLogger(__name__)


class TaskProcessor:
    """Process tasks from docker-tasks queue."""

    def __init__(self, settings):
        self.settings = settings
        self.db = DatabaseClient(settings)
        self.service_bus = ServiceBusClient(settings)

    async def process_message(self, message):
        """Process a single task message."""
        # Parse message
        task_data = json.loads(str(message))
        task_id = task_data['task_id']
        task_type = task_data['task_type']
        parameters = task_data.get('parameters', {})

        logger.info(f"Processing task: {task_id} ({task_type})")

        # Update task status to PROCESSING
        await self.db.update_task_status(task_id, TaskStatus.PROCESSING)

        try:
            # Get handler from registry
            handler = HANDLER_REGISTRY.get(task_type)
            if not handler:
                raise ValueError(f"Unknown task type: {task_type}")

            # Execute handler (this is where GDAL work happens)
            result = await handler(parameters)

            # Update task as COMPLETED
            await self.db.update_task_result(task_id, TaskStatus.COMPLETED, result)

            logger.info(f"Task completed: {task_id}")

            # Check if stage is complete and signal if needed
            await self._check_stage_completion(task_data)

        except Exception as e:
            logger.error(f"Task failed: {task_id} - {e}")
            await self.db.update_task_result(
                task_id,
                TaskStatus.FAILED,
                {'error': str(e)}
            )
            raise

    async def _check_stage_completion(self, task_data):
        """Check if stage is complete and send signal to jobs queue."""
        job_id = task_data['job_id']
        stage = task_data['stage']

        # Query database for stage task counts
        stats = await self.db.get_stage_task_stats(job_id, stage)

        if stats['completed'] + stats['failed'] >= stats['total']:
            # Stage complete - send signal to jobs queue
            await self._send_stage_complete_signal(
                job_id=job_id,
                job_type=task_data.get('job_type'),
                completed_stage=stage
            )

    async def _send_stage_complete_signal(self, job_id: str, job_type: str, completed_stage: int):
        """Send stage_complete message to geospatial-jobs queue."""
        message = {
            'message_type': 'stage_complete',
            'job_id': job_id,
            'job_type': job_type,
            'completed_stage': completed_stage,
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'completed_by_app': self.settings.app_name,
            'correlation_id': f"docker-{job_id[:8]}"
        }

        await self.service_bus.send_to_jobs_queue(message)

        logger.info(
            f"Stage complete signal sent: job={job_id}, stage={completed_stage}"
        )
```

---

## Phase 4: Azure Deployment

### Azure Resources Required

1. **Azure Container Registry (ACR)**
   - Name: `rmhgdalacr` (or existing ACR)
   - SKU: Basic (~$5/month)

2. **Azure Web App (Docker)**
   - Name: `rmh-gdal-worker`
   - App Service Plan: Dedicated B3 or higher
   - Container source: ACR

3. **Managed Identity**
   - Use existing User-Assigned Managed Identity from Function App
   - Grant RBAC: Storage Blob Data Contributor, Service Bus Data Receiver

### Deployment Commands

```bash
# Build and push Docker image
docker build -t rmhgdalacr.azurecr.io/rmh-gdal-worker:latest .
az acr login --name rmhgdalacr
docker push rmhgdalacr.azurecr.io/rmh-gdal-worker:latest

# Create Web App (if not exists)
az webapp create \
  --resource-group rmhazure_rg \
  --plan rmh-app-service-plan \
  --name rmh-gdal-worker \
  --deployment-container-image-name rmhgdalacr.azurecr.io/rmh-gdal-worker:latest

# Configure environment variables
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmh-gdal-worker \
  --settings \
    APP_NAME=gdal-docker-worker \
    WORKER_TIMEOUT_MINUTES=60 \
    POSTGIS_HOST=rmhpgflex.postgres.database.azure.com \
    POSTGIS_DATABASE=geo
```

---

## Message Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          JOB SUBMISSION                                  │
│   POST /api/jobs/submit/process_large_raster_v2                         │
│   {"blob_path": "bronze-rasters/huge_file.tif"}                         │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FUNCTION APP (Platform)                               │
│                                                                          │
│   1. Create job record in database                                       │
│   2. Stage 1 tasks → raster-tasks queue (fast validation)               │
│   3. Wait for stage_complete signal                                      │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                           │
        ▼                                           ▼
┌───────────────────┐                   ┌───────────────────────────────┐
│   raster-tasks    │                   │      docker-tasks (NEW)       │
│   (Stage 1, 3-5)  │                   │      (Stage 2 only)           │
└────────┬──────────┘                   └───────────────┬───────────────┘
         │                                              │
         ▼                                              ▼
┌───────────────────┐                   ┌───────────────────────────────┐
│  Function App     │                   │   Docker Web App              │
│  (30 min max)     │                   │   (60 min timeout)            │
│                   │                   │                               │
│  • validation     │                   │   • tile extraction           │
│  • small COGs     │                   │   • large file processing     │
│  • STAC metadata  │                   │   • memory-intensive GDAL     │
└────────┬──────────┘                   └───────────────┬───────────────┘
         │                                              │
         │      Both update app.tasks table            │
         │      in PostgreSQL database                 │
         │                                              │
         └──────────────────┬───────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │   stage_complete signal     │
              │   → geospatial-jobs queue   │
              │                             │
              │   {                         │
              │     "message_type":         │
              │       "stage_complete",     │
              │     "job_id": "abc123",     │
              │     "completed_stage": 2,   │
              │     "completed_by_app":     │
              │       "gdal-docker-worker"  │
              │   }                         │
              └──────────────┬──────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │   Function App (Platform)   │
              │                             │
              │   Receives stage_complete   │
              │   → Advances to Stage 3     │
              │   → Creates Stage 3 tasks   │
              │   → Routes to raster-tasks  │
              └─────────────────────────────┘
```

---

## Success Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `docker-tasks` queue exists in Service Bus | [ ] |
| 2 | CoreMachine routes long-running tasks to `docker-tasks` | [ ] |
| 3 | Docker worker processes tasks from `docker-tasks` queue | [ ] |
| 4 | Tasks complete within 60 minutes | [ ] |
| 5 | Docker worker sends `stage_complete` to `geospatial-jobs` | [ ] |
| 6 | Function App advances jobs after Docker stage completes | [ ] |
| 7 | End-to-end job with mixed queues completes successfully | [ ] |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Docker cold start | Enable "Always On" in App Service |
| Large image size | Multi-stage Docker build |
| Lost heartbeats | 5-minute lock duration on queue |
| Duplicate processing | Idempotent handlers (already implemented) |
| Memory exhaustion | Configure App Service Plan with adequate RAM |

---

## Cost Estimate

| Resource | Configuration | Est. Cost/Month |
|----------|---------------|-----------------|
| Web App (Docker) | B3 Basic (4 vCPU, 7GB) | ~$55 |
| Container Registry | Basic tier | ~$5 |
| **Total Additional** | | **~$60** |

*Note: If using shared App Service Plan, marginal cost is just ACR (~$5/month)*

---

## Progress Log

### 12 DEC 2025
- Created GDAL_WORKER.md implementation guide
- Defined Phase 1 TODO for rmhgeoapi modifications
- Documented complete architecture and message flow

---

**Next Step**: Execute Phase 1.1 - Add Docker queue configuration to `config/defaults.py`
