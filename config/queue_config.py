"""
Azure Service Bus Queue Configuration.

Provides configuration for:
    - Service Bus connection settings
    - Queue names (jobs, tasks)
    - Batch processing settings
    - Retry configuration

Note: This is a SERVICE BUS ONLY application - Storage Queues are NOT supported.

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
    TASKS = QueueDefaults.TASKS_QUEUE


# ============================================================================
# QUEUE CONFIGURATION
# ============================================================================

class QueueConfig(BaseModel):
    """
    Azure Service Bus queue configuration.

    Controls Service Bus connection and message processing settings.

    Queue Architecture (07 DEC 2025):
    - jobs_queue: Job orchestration and stage_complete signals
    - tasks_queue: Legacy/fallback for unrouted tasks
    - raster_tasks_queue: Memory-intensive GDAL operations (low concurrency)
    - vector_tasks_queue: DB-bound operations (high concurrency)
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

    # Queue names - Core
    jobs_queue: str = Field(
        default=QueueDefaults.JOBS_QUEUE,
        description="Service Bus queue name for job messages and stage_complete signals"
    )

    tasks_queue: str = Field(
        default=QueueDefaults.TASKS_QUEUE,
        description="Service Bus queue name for legacy/fallback task messages"
    )

    # Queue names - Specialized (07 DEC 2025)
    raster_tasks_queue: str = Field(
        default=QueueDefaults.RASTER_TASKS_QUEUE,
        description="Service Bus queue for raster tasks (GDAL operations, low concurrency)"
    )

    vector_tasks_queue: str = Field(
        default=QueueDefaults.VECTOR_TASKS_QUEUE,
        description="Service Bus queue for vector tasks (DB operations, high concurrency)"
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

    # NOTE: Legacy Storage Queue fields REMOVED (30 NOV 2025)
    # Storage Queues are NOT supported - Service Bus only.
    # Use jobs_queue and tasks_queue properties instead.

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(
            connection_string=os.environ.get("ServiceBusConnection"),
            # Check both SERVICE_BUS_NAMESPACE and Azure Functions binding variable
            namespace=os.environ.get("SERVICE_BUS_NAMESPACE") or os.environ.get("ServiceBusConnection__fullyQualifiedNamespace"),
            jobs_queue=os.environ.get("SERVICE_BUS_JOBS_QUEUE", QueueDefaults.JOBS_QUEUE),
            tasks_queue=os.environ.get("SERVICE_BUS_TASKS_QUEUE", QueueDefaults.TASKS_QUEUE),
            raster_tasks_queue=os.environ.get("SERVICE_BUS_RASTER_TASKS_QUEUE", QueueDefaults.RASTER_TASKS_QUEUE),
            vector_tasks_queue=os.environ.get("SERVICE_BUS_VECTOR_TASKS_QUEUE", QueueDefaults.VECTOR_TASKS_QUEUE),
            max_batch_size=int(os.environ.get("SERVICE_BUS_MAX_BATCH_SIZE", str(QueueDefaults.MAX_BATCH_SIZE))),
            batch_threshold=int(os.environ.get("SERVICE_BUS_BATCH_THRESHOLD", str(QueueDefaults.BATCH_THRESHOLD))),
            retry_count=int(os.environ.get("SERVICE_BUS_RETRY_COUNT", str(QueueDefaults.RETRY_COUNT))),
        )
