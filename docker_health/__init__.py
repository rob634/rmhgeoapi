# ============================================================================
# DOCKER HEALTH - Subsystem-Based Health Check Architecture
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Framework - Docker Worker subsystem health monitoring
# PURPOSE: Modular health checks anticipating dual queue systems (Classic + DAG)
# CREATED: 29 JAN 2026
# VERSION: V0.8.1.1
# EXPORTS: get_all_subsystems, HealthAggregator
# DEPENDENCIES: base, shared, runtime, classic_worker, dag_worker
# ============================================================================
"""
Docker Health Subsystem Architecture.

This module provides a structured approach to health monitoring for the Docker
Worker, anticipating the addition of a DAG-driven workflow system alongside
the existing queue-based job processing.

Subsystems:
- SharedInfrastructureSubsystem: Database, storage, service bus (common)
- RuntimeSubsystem: Hardware, GDAL, imports, deployment config
- ClassicWorkerSubsystem: Existing queue-based job processing
- DAGWorkerSubsystem: Future DAG-driven workflow processing (stub)

Usage:
    from docker_health import get_all_subsystems, HealthAggregator

    subsystems = get_all_subsystems(
        queue_worker=queue_worker,
        worker_lifecycle=worker_lifecycle,
        token_refresh_worker=token_refresh_worker,
        etl_mount_status=_etl_mount_status,
    )

    aggregator = HealthAggregator(subsystems)
    health_response = aggregator.get_health()
"""

from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import WorkerSubsystem


def get_all_subsystems(
    queue_worker,
    worker_lifecycle,
    token_refresh_worker,
    etl_mount_status: Optional[dict] = None,
    dag_processor=None,  # Future: DAG processor reference
) -> List["WorkerSubsystem"]:
    """
    Get all health subsystems with their dependencies injected.

    Args:
        queue_worker: BackgroundQueueWorker instance
        worker_lifecycle: DockerWorkerLifecycle instance
        token_refresh_worker: TokenRefreshWorker instance
        etl_mount_status: ETL mount status dict (optional)
        dag_processor: Future DAG processor reference (optional)

    Returns:
        List of WorkerSubsystem instances in priority order
    """
    from .shared import SharedInfrastructureSubsystem
    from .runtime import RuntimeSubsystem
    from .classic_worker import ClassicWorkerSubsystem
    from .dag_worker import DAGWorkerSubsystem

    subsystems = [
        # Priority 10: Shared infrastructure (database, storage, service bus)
        SharedInfrastructureSubsystem(
            queue_worker=queue_worker,
        ),

        # Priority 20: Runtime environment (hardware, GDAL, imports)
        RuntimeSubsystem(
            etl_mount_status=etl_mount_status,
        ),

        # Priority 30: Classic queue worker (existing system)
        ClassicWorkerSubsystem(
            queue_worker=queue_worker,
            worker_lifecycle=worker_lifecycle,
            token_refresh_worker=token_refresh_worker,
        ),

        # Priority 40: DAG worker (future system - currently disabled)
        DAGWorkerSubsystem(
            dag_processor=dag_processor,
        ),
    ]

    # Sort by priority (lower = runs first)
    return sorted(subsystems, key=lambda s: s.priority)


# Re-export key classes
from .base import WorkerSubsystem
from .aggregator import HealthAggregator

__all__ = [
    'WorkerSubsystem',
    'HealthAggregator',
    'get_all_subsystems',
]
