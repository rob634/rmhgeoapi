# ============================================================================
# DOCKER HEALTH - Subsystem-Based Health Check Architecture
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Framework - Docker Worker subsystem health monitoring
# PURPOSE: Modular health checks for Docker Worker subsystems
# CREATED: 29 JAN 2026
# VERSION: V0.8.1.1
# EXPORTS: get_all_subsystems, HealthAggregator
# DEPENDENCIES: base, shared, runtime, classic_worker
# ============================================================================
"""
Docker Health Subsystem Architecture.

This module provides a structured approach to health monitoring for the Docker
Worker.

Subsystems:
- SharedInfrastructureSubsystem: Database, storage, service bus (common)
- RuntimeSubsystem: Hardware, GDAL, imports, deployment config
- ClassicWorkerSubsystem: Existing queue-based job processing

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
    dag_janitor=None,
    dag_scheduler=None,
) -> List["WorkerSubsystem"]:
    """
    Get all health subsystems with their dependencies injected.

    APP_MODE aware: orchestrator mode uses DAGBrainSubsystem instead of
    ClassicWorkerSubsystem. SharedInfrastructure and Runtime are common.

    Args:
        queue_worker: BackgroundQueueWorker instance
        worker_lifecycle: DockerWorkerLifecycle instance
        token_refresh_worker: TokenRefreshWorker instance
        etl_mount_status: ETL mount status dict (optional)
        dag_janitor: DAGJanitor instance (orchestrator mode only)
        dag_scheduler: DAGScheduler instance (orchestrator mode only)

    Returns:
        List of WorkerSubsystem instances in priority order
    """
    import os
    from .shared import SharedInfrastructureSubsystem
    from .runtime import RuntimeSubsystem

    app_mode = os.environ.get("APP_MODE", "worker_docker")

    subsystems = [
        # Priority 10: Shared infrastructure (database, storage)
        SharedInfrastructureSubsystem(
            queue_worker=queue_worker,
        ),

        # Priority 20: Runtime environment (hardware, GDAL, imports)
        RuntimeSubsystem(
            etl_mount_status=etl_mount_status,
        ),
    ]

    # Priority 30: Mode-specific subsystem
    if app_mode == "orchestrator":
        from .dag_brain import DAGBrainSubsystem
        subsystems.append(
            DAGBrainSubsystem(
                dag_janitor=dag_janitor,
                dag_scheduler=dag_scheduler,
                worker_lifecycle=worker_lifecycle,
                token_refresh_worker=token_refresh_worker,
            )
        )
    else:
        from .classic_worker import ClassicWorkerSubsystem
        subsystems.append(
            ClassicWorkerSubsystem(
                queue_worker=queue_worker,
                worker_lifecycle=worker_lifecycle,
                token_refresh_worker=token_refresh_worker,
            )
        )

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
