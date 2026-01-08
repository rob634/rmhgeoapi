# ============================================================================
# SERVICE BUS QUEUE CONFIGURATION
# ============================================================================
# STATUS: Configuration - Azure Service Bus queues for job/task messaging
# PURPOSE: Configure Service Bus namespace, queues, and authentication
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Check 8 Applied - Full operational deployment guide
# ============================================================================

"""
Azure Service Bus Queue Configuration.

================================================================================
CORPORATE QA/PROD DEPLOYMENT GUIDE
================================================================================

This module configures Azure Service Bus for job and task messaging.
Before deploying, file service requests to create the Service Bus resources.

--------------------------------------------------------------------------------
REQUIRED AZURE RESOURCES
--------------------------------------------------------------------------------

1. SERVICE BUS NAMESPACE
   ----------------------
   Service Request Template:
       "Create Azure Service Bus Namespace:
        - Name: {app-name}-servicebus
        - SKU: Standard (or Premium for production with VNet)
        - Location: Same region as Function App

        For Premium SKU (production):
        - Messaging Units: 1 (scale as needed)
        - Zone Redundancy: Enabled
        - VNet Integration: Enabled (if required)"

   Environment Variables (choose ONE authentication method):

   Option A - Connection String:
       ServiceBusConnection = Endpoint=sb://{namespace}.servicebus.windows.net/;SharedAccessKeyName=...

   Option B - Managed Identity (Recommended):
       SERVICE_BUS_FQDN = {namespace}.servicebus.windows.net

2. SERVICE BUS QUEUES
   -------------------
   Service Request Template:
       "Create Service Bus queues in namespace {namespace}:

        geospatial-jobs:
        - Max Size: 1 GB
        - Message TTL: 14 days
        - Lock Duration: 5 minutes
        - Max Delivery Count: 10
        - Purpose: Job orchestration and stage_complete signals

        raster-tasks:
        - Max Size: 5 GB
        - Message TTL: 7 days
        - Lock Duration: 10 minutes (GDAL operations are slow)
        - Max Delivery Count: 3
        - Purpose: Memory-intensive GDAL COG creation

        vector-tasks:
        - Max Size: 1 GB
        - Message TTL: 7 days
        - Lock Duration: 5 minutes
        - Max Delivery Count: 5
        - Purpose: PostGIS operations, lightweight processing

        long-running-tasks (Optional - Docker worker):
        - Max Size: 1 GB
        - Message TTL: 30 days
        - Lock Duration: 30 minutes
        - Max Delivery Count: 3
        - Purpose: Tasks exceeding Function App timeout"

   Environment Variables (optional overrides):
       SERVICE_BUS_JOBS_QUEUE         = geospatial-jobs
       SERVICE_BUS_RASTER_TASKS_QUEUE = raster-tasks
       SERVICE_BUS_VECTOR_TASKS_QUEUE = vector-tasks
       SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE = long-running-tasks

3. MANAGED IDENTITY ACCESS
   ------------------------
   Service Request Template:
       "Grant managed identity access to Service Bus:
        - Identity: {app-name}-db-admin
        - Role: 'Azure Service Bus Data Sender' (for sending)
        - Role: 'Azure Service Bus Data Receiver' (for receiving)
        - Scope: Service Bus namespace resource"

--------------------------------------------------------------------------------
AUTHENTICATION MODES
--------------------------------------------------------------------------------

1. MANAGED IDENTITY (Production - Recommended)
   - No connection strings stored
   - Set SERVICE_BUS_FQDN only (full URL: {namespace}.servicebus.windows.net)

2. CONNECTION STRING (Development)
   - Quick setup for local development
   - Set ServiceBusConnection (Azure Functions binding name)

--------------------------------------------------------------------------------
DEPLOYMENT VERIFICATION
--------------------------------------------------------------------------------

After configuration, verify with:

    curl https://{app-url}/api/health

Expected response includes:
    "service_bus": {
        "status": "healthy",
        "namespace": "{namespace}.servicebus.windows.net"
    }

Test job submission:
    curl -X POST https://{app-url}/api/jobs/submit/hello_world \\
         -H "Content-Type: application/json" \\
         -d '{"message": "test"}'

Common Failure Messages:
    ServiceBusConnectionError: Cannot connect to namespace
        → Check SERVICE_BUS_FQDN or ServiceBusConnection

    UnauthorizedAccess: Identity lacks queue access
        → Grant 'Azure Service Bus Data Sender/Receiver' roles

    QueueNotFound: Queue does not exist
        → Create queues in Service Bus namespace

--------------------------------------------------------------------------------
ARCHITECTURE
--------------------------------------------------------------------------------

Queue Architecture (No Legacy Fallbacks):
    - geospatial-jobs: Job orchestration and stage_complete signals
    - raster-tasks: Memory-intensive GDAL operations (low concurrency)
    - vector-tasks: DB-bound and lightweight operations (high concurrency)
    - long-running-tasks: Docker worker (exceeds Function timeout)

All task types MUST be explicitly mapped in TaskRoutingDefaults.
There is NO fallback queue - unmapped task types raise ContractViolationError.

Exports:
    QueueConfig: Pydantic queue configuration model
    QueueNames: Queue name constants
"""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import QueueDefaults


# ============================================================================
# QUEUE NAMES
# ============================================================================

class QueueNames:
    """Queue name constants for easy access."""
    JOBS = QueueDefaults.JOBS_QUEUE
    RASTER_TASKS = QueueDefaults.RASTER_TASKS_QUEUE
    VECTOR_TASKS = QueueDefaults.VECTOR_TASKS_QUEUE
    # Long-running tasks (13 DEC 2025, renamed 22 DEC 2025 - Docker worker)
    LONG_RUNNING_TASKS = QueueDefaults.LONG_RUNNING_TASKS_QUEUE


# ============================================================================
# QUEUE CONFIGURATION
# ============================================================================

class QueueConfig(BaseModel):
    """
    Azure Service Bus queue configuration.

    Controls Service Bus connection and message processing settings.

    Queue Architecture (11 DEC 2025 - No Legacy Fallbacks):
    - jobs_queue: Job orchestration and stage_complete signals
    - raster_tasks_queue: Memory-intensive GDAL operations (low concurrency)
    - vector_tasks_queue: DB-bound and lightweight operations (high concurrency)

    All task types MUST be explicitly mapped in TaskRoutingDefaults.
    Unmapped task types raise ContractViolationError (no fallback queue).
    """

    # Service Bus connection
    connection_string: Optional[str] = Field(
        default=None,
        repr=False,
        description="Service Bus connection string (from ServiceBusConnection env var or Azure Functions binding)"
    )

    namespace: Optional[str] = Field(
        default=None,
        description="Service Bus namespace for managed identity auth (alternative to connection string)"
    )

    # Queue names
    jobs_queue: str = Field(
        default=QueueDefaults.JOBS_QUEUE,
        description="Service Bus queue name for job messages and stage_complete signals"
    )

    raster_tasks_queue: str = Field(
        default=QueueDefaults.RASTER_TASKS_QUEUE,
        description="Service Bus queue for raster tasks (GDAL operations, low concurrency)"
    )

    vector_tasks_queue: str = Field(
        default=QueueDefaults.VECTOR_TASKS_QUEUE,
        description="Service Bus queue for vector tasks (DB operations, high concurrency)"
    )

    # Long-running tasks queue (13 DEC 2025, renamed 22 DEC 2025 - Docker worker)
    long_running_tasks_queue: str = Field(
        default=QueueDefaults.LONG_RUNNING_TASKS_QUEUE,
        description="Service Bus queue for long-running tasks (Docker worker). "
                    "No Azure Functions timeout constraints - can run hours/days. "
                    "Used for large files or complex processing exceeding Function App limits."
    )

    # Batch processing
    max_batch_size: int = Field(
        default=QueueDefaults.MAX_BATCH_SIZE,
        ge=1,
        le=1000,
        description="Maximum batch size for Service Bus messages"
    )

    batch_threshold: int = Field(
        default=QueueDefaults.BATCH_THRESHOLD,
        ge=1,
        le=500,
        description="Threshold for triggering batch send (messages)"
    )

    # Retry configuration
    retry_count: int = Field(
        default=QueueDefaults.RETRY_COUNT,
        ge=0,
        le=10,
        description="Number of retry attempts for Service Bus operations"
    )

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(
            connection_string=os.environ.get("ServiceBusConnection"),
            # Check SERVICE_BUS_FQDN (full URL), legacy SERVICE_BUS_NAMESPACE, and Azure Functions binding variable
            namespace=os.environ.get("SERVICE_BUS_FQDN") or os.environ.get("SERVICE_BUS_NAMESPACE") or os.environ.get("ServiceBusConnection__fullyQualifiedNamespace"),
            jobs_queue=os.environ.get("SERVICE_BUS_JOBS_QUEUE", QueueDefaults.JOBS_QUEUE),
            raster_tasks_queue=os.environ.get("SERVICE_BUS_RASTER_TASKS_QUEUE", QueueDefaults.RASTER_TASKS_QUEUE),
            vector_tasks_queue=os.environ.get("SERVICE_BUS_VECTOR_TASKS_QUEUE", QueueDefaults.VECTOR_TASKS_QUEUE),
            # Long-running queue (13 DEC 2025, renamed 22 DEC 2025 - Docker worker)
            long_running_tasks_queue=os.environ.get(
                "SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE",
                QueueDefaults.LONG_RUNNING_TASKS_QUEUE
            ),
            max_batch_size=int(os.environ.get("SERVICE_BUS_MAX_BATCH_SIZE", str(QueueDefaults.MAX_BATCH_SIZE))),
            batch_threshold=int(os.environ.get("SERVICE_BUS_BATCH_THRESHOLD", str(QueueDefaults.BATCH_THRESHOLD))),
            retry_count=int(os.environ.get("SERVICE_BUS_RETRY_COUNT", str(QueueDefaults.RETRY_COUNT))),
        )
