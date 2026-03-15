# ============================================================================
# DOCKER HEALTH - Classic Worker Subsystem
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Subsystem - DB-polling job processing
# PURPOSE: Health checks for the DB-polling queue worker
# CREATED: 29 JAN 2026
# LAST_REVIEWED: 15 MAR 2026
# EXPORTS: ClassicWorkerSubsystem
# DEPENDENCIES: base.WorkerSubsystem
# ============================================================================
"""
Classic Worker Health Subsystem.

Monitors the DB-polling job processing system:
- queue_worker: PostgreSQL SKIP LOCKED task consumer
- auth_tokens: OAuth tokens for PostgreSQL and Storage
- connection_pool: PostgreSQL connection pool
- lifecycle: Graceful shutdown and signal handling

15 MAR 2026: Updated from Service Bus to DB-polling model.
"""

from typing import Dict, Any

from .base import WorkerSubsystem


class ClassicWorkerSubsystem(WorkerSubsystem):
    """
    Health checks for DB-polling job processing.

    This subsystem monitors the queue worker that claims tasks from
    PostgreSQL via SKIP LOCKED.

    Components:
    - queue_worker: DB-polling consumer thread status
    - auth_tokens: OAuth token status and refresh worker
    - connection_pool: PostgreSQL connection pool stats
    - lifecycle: Graceful shutdown coordination
    """

    name = "classic_worker"
    description = "Queue-based job processing (existing system)"
    priority = 30  # Run after runtime checks

    def __init__(
        self,
        queue_worker=None,
        worker_lifecycle=None,
        token_refresh_worker=None,
    ):
        """
        Initialize with worker references.

        Args:
            queue_worker: BackgroundQueueWorker instance
            worker_lifecycle: DockerWorkerLifecycle instance
            token_refresh_worker: TokenRefreshWorker instance
        """
        self.queue_worker = queue_worker
        self.worker_lifecycle = worker_lifecycle
        self.token_refresh_worker = token_refresh_worker

    def is_enabled(self) -> bool:
        """Classic worker is enabled if queue_worker exists."""
        return self.queue_worker is not None

    def get_health(self) -> Dict[str, Any]:
        """Return health status for classic worker system."""
        components = {}
        metrics = {}
        errors = []

        # Check queue worker
        queue_result = self._check_queue_worker()
        components["queue_worker"] = queue_result
        if queue_result["status"] == "unhealthy":
            errors.append(queue_result.get("details", {}).get("init_error", "Queue worker unhealthy"))

        # Check auth tokens
        components["auth_tokens"] = self._check_auth_tokens()

        # Check connection pool
        components["connection_pool"] = self._check_connection_pool()

        # Check lifecycle
        lifecycle_result = self._check_lifecycle()
        components["lifecycle"] = lifecycle_result
        if lifecycle_result["status"] == "warning":
            errors.append("Worker is shutting down")

        # Extract metrics
        if self.queue_worker:
            queue_status = self.queue_worker.get_status()
            metrics["messages_processed"] = queue_status.get("messages_processed", 0)
            metrics["last_poll_time"] = queue_status.get("last_poll_time")

        result = {
            "status": self.compute_status(components),
            "components": components,
            "metrics": metrics,
        }

        if errors:
            result["errors"] = errors

        return result

    def _check_queue_worker(self) -> Dict[str, Any]:
        """Check DB-polling queue worker status."""
        if not self.queue_worker:
            return self.build_component(
                status="disabled",
                description="DB-polling task consumer",
                details={"note": "Queue worker not initialized"}
            )

        queue_status = self.queue_worker.get_status()
        queue_running = queue_status.get("running", False)
        queue_init_failed = queue_status.get("init_failed", False)

        # Determine status
        # Init failure = UNHEALTHY (broken app), not running = WARNING
        if queue_init_failed:
            status = "unhealthy"  # Broken - can't process tasks
        elif queue_running:
            status = "healthy"
        else:
            status = "warning"  # Not running yet but may start

        return self.build_component(
            status=status,
            description="DB-polling task consumer (SKIP LOCKED)",
            details={
                "running": queue_running,
                "healthy": self.queue_worker.is_healthy(),
                "init_failed": queue_init_failed,
                "init_error": queue_status.get("init_error"),
                "messages_processed": queue_status.get("messages_processed", 0),
                "started_at": queue_status.get("started_at"),
                "last_poll_time": queue_status.get("last_poll_time"),
                "last_error": queue_status.get("last_error"),
                "shutdown_signaled": queue_status.get("shutdown_signaled", False),
                "uses_shared_shutdown": queue_status.get("uses_shared_shutdown", True),
            }
        )

    def _check_auth_tokens(self) -> Dict[str, Any]:
        """Check OAuth token status."""
        try:
            from infrastructure.auth import get_token_status

            token_status = get_token_status()
            pg_token = token_status.get("postgres", {})
            storage_token = token_status.get("storage", {})
            tokens_healthy = pg_token.get("has_token", False)

            # Get token refresh worker status
            refresh_status = {}
            if self.token_refresh_worker:
                refresh_status = self.token_refresh_worker.get_status()

            return self.build_component(
                status="healthy" if tokens_healthy else "unhealthy",
                description="OAuth tokens for PostgreSQL and Storage",
                details={
                    "postgres": {
                        "has_token": pg_token.get("has_token", False),
                        "ttl_minutes": pg_token.get("ttl_minutes"),
                    },
                    "storage": {
                        "has_token": storage_token.get("has_token", False),
                    },
                    "token_refresh_worker": {
                        "running": refresh_status.get("running", False),
                        "refresh_count": refresh_status.get("refresh_count", 0),
                        "last_refresh": refresh_status.get("last_refresh"),
                    },
                }
            )

        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="OAuth tokens for PostgreSQL and Storage",
                details={"error": str(e)}
            )

    def _check_connection_pool(self) -> Dict[str, Any]:
        """Check PostgreSQL connection pool status."""
        try:
            from infrastructure.connection_pool import ConnectionPoolManager

            pool_stats = ConnectionPoolManager.get_pool_stats()

            # Include circuit breaker state (13 MAR 2026)
            from infrastructure.circuit_breaker import CircuitBreaker
            cb_stats = CircuitBreaker.get_instance().get_stats()
            pool_stats['circuit_breaker'] = cb_stats
            pool_has_error = "error" in pool_stats or cb_stats.get('state') != 'closed'

            return self.build_component(
                status="healthy" if not pool_has_error else "warning",
                description="PostgreSQL connection pool (psycopg)",
                details=pool_stats
            )

        except Exception as e:
            return self.build_component(
                status="warning",
                description="PostgreSQL connection pool (psycopg)",
                details={"error": str(e)}
            )

    def _check_lifecycle(self) -> Dict[str, Any]:
        """Check graceful shutdown and lifecycle status."""
        if not self.worker_lifecycle:
            return self.build_component(
                status="disabled",
                description="Graceful shutdown and signal handling",
                details={"note": "Lifecycle manager not initialized"}
            )

        lifecycle_status = self.worker_lifecycle.get_status()
        is_shutting_down = lifecycle_status.get("shutdown_initiated", False)

        return self.build_component(
            status="warning" if is_shutting_down else "healthy",
            description="Graceful shutdown and signal handling",
            details=lifecycle_status
        )


__all__ = ['ClassicWorkerSubsystem']
