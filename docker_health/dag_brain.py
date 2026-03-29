# ============================================================================
# DOCKER HEALTH - DAG Brain Subsystem
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Health Subsystem - DAG orchestrator health monitoring
# PURPOSE: Health checks for DAG Brain mode (orchestrator + janitor + scheduler)
# CREATED: 18 MAR 2026
# EXPORTS: DAGBrainSubsystem
# DEPENDENCIES: base.WorkerSubsystem
# ============================================================================
"""
DAG Brain Health Subsystem.

Replaces ClassicWorkerSubsystem when APP_MODE=orchestrator.
Monitors the DAG-specific services instead of the queue worker:
- janitor: Stale task recovery thread
- scheduler: Cron-based workflow submission thread
- auth_tokens: OAuth tokens (same as ClassicWorker)
- connection_pool: PostgreSQL connection pool (same as ClassicWorker)
- lifecycle: Graceful shutdown coordination (same as ClassicWorker)
"""

from typing import Dict, Any, Optional

from .base import WorkerSubsystem


class DAGBrainSubsystem(WorkerSubsystem):
    """
    Health checks for DAG Brain orchestrator mode.

    Components:
    - janitor: DAGJanitor background thread status
    - scheduler: DAGScheduler cron-based workflow submission thread
    - auth_tokens: OAuth token status and refresh worker
    - connection_pool: PostgreSQL connection pool stats
    - lifecycle: Graceful shutdown coordination
    """

    name = "dag_brain"
    description = "DAG workflow orchestration (Epoch 5)"
    priority = 30  # Same slot as ClassicWorker

    def __init__(
        self,
        dag_primary_loop=None,
        dag_janitor=None,
        dag_scheduler=None,
        worker_lifecycle=None,
        token_refresh_worker=None,
    ):
        self._primary_loop = dag_primary_loop
        self._janitor = dag_janitor
        self._scheduler = dag_scheduler
        self.worker_lifecycle = worker_lifecycle
        self.token_refresh_worker = token_refresh_worker

    def is_enabled(self) -> bool:
        """DAG Brain subsystem is always enabled in orchestrator mode."""
        return True

    def get_health(self) -> Dict[str, Any]:
        """Return health status for DAG Brain system."""
        components = {}
        metrics = {}

        # Check primary loop (most important — this IS the DAG Brain)
        components["primary_loop"] = self._check_primary_loop()

        # Check janitor
        components["janitor"] = self._check_janitor()

        # Check scheduler
        components["scheduler"] = self._check_scheduler()

        # Check auth tokens (same logic as ClassicWorker)
        components["auth_tokens"] = self._check_auth_tokens()

        # Check connection pool (same logic as ClassicWorker)
        components["connection_pool"] = self._check_connection_pool()

        # Check lifecycle
        components["lifecycle"] = self._check_lifecycle()

        # Check workflow registry
        components["workflow_registry"] = self._check_workflow_registry()

        # Check orchestrator lease
        components["lease"] = self._check_lease()

        # Metrics
        if self._primary_loop:
            loop_status = self._primary_loop.get_status()
            metrics["primary_loop_scans"] = loop_status["total_scans"]
            metrics["primary_loop_cycles"] = loop_status["total_cycles"]
            metrics["primary_loop_last_scan_at"] = loop_status["last_scan_at"]

        if self._janitor:
            metrics["janitor_sweeps"] = self._janitor._total_sweeps
            metrics["last_sweep_at"] = (
                self._janitor._last_sweep_at.isoformat()
                if self._janitor._last_sweep_at else None
            )
        if self._scheduler:
            metrics["scheduler_polls"] = self._scheduler._total_polls
            metrics["scheduler_fired"] = self._scheduler._total_fired
            metrics["scheduler_last_poll_at"] = (
                self._scheduler._last_poll_at.isoformat()
                if self._scheduler._last_poll_at else None
            )

        result = {
            "status": self.compute_status(components),
            "components": components,
            "metrics": metrics,
        }
        return result

    def _check_primary_loop(self) -> Dict[str, Any]:
        """Check DAG Brain primary orchestration loop status."""
        if not self._primary_loop:
            return self.build_component(
                status="unhealthy",
                description="DAG Brain primary orchestration loop",
                source="dag_brain",
                details={"note": "Primary loop not initialized"},
            )

        loop_status = self._primary_loop.get_status()
        thread_alive = loop_status["running"]

        # Check for stuck thread — alive but not scanning
        status = "unhealthy"
        if thread_alive:
            last_scan = loop_status.get("last_scan_at")
            if last_scan:
                from datetime import datetime, timezone
                if isinstance(last_scan, str):
                    last_scan = datetime.fromisoformat(last_scan)
                age = (datetime.now(timezone.utc) - last_scan).total_seconds()
                status = "healthy" if age < 300 else "unhealthy"
                loop_status["scan_age_seconds"] = round(age)
            else:
                status = "healthy"  # No scan yet — thread just started

        return self.build_component(
            status=status,
            description="DAG Brain primary orchestration loop",
            source="dag_brain",
            details=loop_status,
        )

    def _check_janitor(self) -> Dict[str, Any]:
        """Check DAGJanitor background thread status."""
        if not self._janitor:
            return self.build_component(
                status="warning",
                description="DAG Janitor (stale task recovery)",
                source="dag_brain",
                details={"note": "Janitor not initialized"},
            )

        thread = self._janitor._thread
        thread_alive = thread is not None and thread.is_alive()

        return self.build_component(
            status="healthy" if thread_alive else "unhealthy",
            description="DAG Janitor (stale task recovery)",
            source="dag_brain",
            details={
                "thread_alive": thread_alive,
                "total_sweeps": self._janitor._total_sweeps,
                "last_sweep_at": (
                    self._janitor._last_sweep_at.isoformat()
                    if self._janitor._last_sweep_at else None
                ),
                "config": {
                    "scan_interval": self._janitor._config.scan_interval,
                    "stale_threshold": self._janitor._config.stale_threshold,
                    "max_retries": self._janitor._config.max_retries,
                },
            },
        )

    def _check_scheduler(self) -> Dict[str, Any]:
        """Check DAGScheduler background thread status."""
        if not self._scheduler:
            return self.build_component(
                status="warning",
                description="DAG Scheduler (cron-based workflow submission)",
                source="dag_brain",
                details={"note": "Scheduler not initialized"},
            )

        thread = self._scheduler._thread
        thread_alive = thread is not None and thread.is_alive()

        details = {
            "thread_alive": thread_alive,
            "total_polls": self._scheduler._total_polls,
            "total_fired": self._scheduler._total_fired,
            "last_poll_at": (
                self._scheduler._last_poll_at.isoformat()
                if self._scheduler._last_poll_at else None
            ),
            "config": {
                "poll_interval": self._scheduler._config.poll_interval,
            },
        }

        # Query active schedules for visibility
        try:
            from infrastructure.schedule_repository import ScheduleRepository
            repo = ScheduleRepository()
            active_schedules = repo.list_all(status="active")
            details["active_schedules"] = [
                {
                    "schedule_id": s["schedule_id"],
                    "workflow_name": s["workflow_name"],
                    "cron_expression": s["cron_expression"],
                    "last_run_at": (
                        s["last_run_at"].isoformat()
                        if s.get("last_run_at") else None
                    ),
                    "description": s.get("description"),
                }
                for s in active_schedules
            ]
            details["active_schedule_count"] = len(active_schedules)
        except Exception as e:
            details["active_schedules_error"] = str(e)
            details["active_schedule_count"] = None

        return self.build_component(
            status="healthy" if thread_alive else "unhealthy",
            description="DAG Scheduler (cron-based workflow submission)",
            source="dag_brain",
            details=details,
        )

    def _check_workflow_registry(self) -> Dict[str, Any]:
        """Check DAG workflow registry — loaded workflows, handler coverage, and load errors."""
        try:
            from core.workflow_registry import get_workflow_registry
            from services import ALL_HANDLERS

            registry = get_workflow_registry()
            workflow_names = registry.list_workflows()
            loaded_count = len(workflow_names)
            load_errors = getattr(registry, 'load_errors', [])

            referenced_handlers = set()
            for wf_name in workflow_names:
                defn = registry.get(wf_name)
                if defn and defn.nodes:
                    for node in defn.nodes.values():
                        if hasattr(node, "handler") and node.handler:
                            referenced_handlers.add(node.handler)

            registered_handlers = set(ALL_HANDLERS.keys())
            missing_handlers = sorted(referenced_handlers - registered_handlers)

            if missing_handlers:
                status = "unhealthy"
            elif load_errors and loaded_count == 0:
                status = "unhealthy"
            elif load_errors:
                status = "degraded"
            elif loaded_count == 0:
                status = "warning"
            else:
                status = "healthy"

            details = {
                "workflows_loaded": loaded_count,
                "workflow_names": workflow_names,
                "handlers_registered": len(registered_handlers),
                "handlers_referenced_by_workflows": len(referenced_handlers),
                "missing_handlers": missing_handlers,
                "workflows_dir": str(registry._dir),
            }
            if load_errors:
                details["invalid_workflows"] = load_errors
                details["invalid_count"] = len(load_errors)

            return self.build_component(
                status=status,
                description="DAG workflow registry",
                source="dag_brain",
                details=details,
            )
        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="DAG workflow registry",
                source="dag_brain",
                details={"error": str(e)},
            )

    def _check_auth_tokens(self) -> Dict[str, Any]:
        """Check OAuth token status."""
        try:
            from infrastructure.auth import get_token_status

            token_status = get_token_status()
            pg_token = token_status.get("postgres", {})
            storage_token = token_status.get("storage", {})
            tokens_healthy = pg_token.get("has_token", False)

            refresh_status = {}
            if self.token_refresh_worker:
                refresh_status = self.token_refresh_worker.get_status()

            return self.build_component(
                status="healthy" if tokens_healthy else "unhealthy",
                description="OAuth tokens for PostgreSQL and Storage",
                source="dag_brain",
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
                },
            )
        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="OAuth tokens for PostgreSQL and Storage",
                source="dag_brain",
                details={"error": str(e)},
            )

    def _check_connection_pool(self) -> Dict[str, Any]:
        """Check PostgreSQL connection pool status."""
        try:
            from infrastructure.connection_pool import ConnectionPoolManager
            from infrastructure.circuit_breaker import CircuitBreaker

            pool_stats = ConnectionPoolManager.get_pool_stats()
            cb_stats = CircuitBreaker.get_instance().get_stats()
            pool_stats["circuit_breaker"] = cb_stats
            pool_has_error = "error" in pool_stats or cb_stats.get("state") != "closed"

            return self.build_component(
                status="healthy" if not pool_has_error else "warning",
                description="PostgreSQL connection pool (psycopg)",
                source="dag_brain",
                details=pool_stats,
            )
        except Exception as e:
            return self.build_component(
                status="warning",
                description="PostgreSQL connection pool (psycopg)",
                source="dag_brain",
                details={"error": str(e)},
            )

    def _check_lease(self) -> Dict[str, Any]:
        """Check orchestrator lease status."""
        try:
            from infrastructure.lease_repository import LeaseRepository
            repo = LeaseRepository()
            lease = repo.get_current()

            if not lease:
                return self.build_component(
                    status="unhealthy",
                    description="Orchestrator lease",
                    source="dag_brain",
                    details={"note": "No lease row — table may not be initialized"},
                )

            return self.build_component(
                status="healthy" if not lease["is_expired"] else "unhealthy",
                description="Orchestrator lease",
                source="dag_brain",
                details={
                    "holder_id": lease["holder_id"],
                    "expires_at": str(lease["expires_at"]),
                    "renewed_at": str(lease["renewed_at"]),
                    "is_expired": lease["is_expired"],
                },
            )
        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="Orchestrator lease",
                source="dag_brain",
                details={"error": str(e)},
            )

    def _check_lifecycle(self) -> Dict[str, Any]:
        """Check graceful shutdown and lifecycle status."""
        if not self.worker_lifecycle:
            return self.build_component(
                status="disabled",
                description="Graceful shutdown and signal handling",
                source="dag_brain",
                details={"note": "Lifecycle manager not initialized"},
            )

        lifecycle_status = self.worker_lifecycle.get_status()
        is_shutting_down = lifecycle_status.get("shutdown_initiated", False)

        return self.build_component(
            status="warning" if is_shutting_down else "healthy",
            description="Graceful shutdown and signal handling",
            source="dag_brain",
            details=lifecycle_status,
        )


__all__ = ["DAGBrainSubsystem"]
