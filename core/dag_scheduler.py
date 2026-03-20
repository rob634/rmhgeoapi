# ============================================================================
# CLAUDE CONTEXT - DAG SCHEDULER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Cron-based workflow submission thread
# PURPOSE: Poll app.schedules for due items and submit workflow runs
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: SchedulerConfig, SchedulerResult, DAGScheduler
# DEPENDENCIES: threading, logging, time, croniter,
#               infrastructure.schedule_repository,
#               infrastructure.workflow_run_repository,
#               core.workflow_registry
# ============================================================================
"""
DAG Scheduler — cron-based workflow submission.

Runs as a background thread in the DAG Brain (Docker, APP_MODE=orchestrator).
Fires every SCHEDULER_POLL_INTERVAL seconds. For each active schedule:
  - Computes next_due via croniter from last_run_at (or created_at)
  - If next_due <= now and concurrency permits: submits a new workflow run
  - Records the run via ScheduleRepository.record_run

Design: fail-open per schedule. One bad cron expression or missing workflow
never blocks other schedules. The scheduler thread itself never crashes.
"""

import hashlib
import logging
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class SchedulerConfig:
    """
    Timing configuration for the cron scheduler.

    Override via SCHEDULER_* environment variables.
    """
    poll_interval: int = 30  # seconds between polls

    @classmethod
    def from_environment(cls) -> 'SchedulerConfig':
        import os
        return cls(
            poll_interval=int(os.environ.get('SCHEDULER_POLL_INTERVAL', '30')),
        )


# ============================================================================
# RESULT
# ============================================================================

@dataclass
class SchedulerResult:
    """Result of a single scheduler poll."""
    schedules_checked: int = 0
    schedules_fired: int = 0
    schedules_skipped: int = 0   # skipped due to concurrency limit
    schedules_errored: int = 0   # invalid cron, missing workflow, DB error, etc.
    elapsed_ms: float = 0.0


# ============================================================================
# SCHEDULER
# ============================================================================

class DAGScheduler:
    """
    Background cron-based workflow submission thread.

    Each poll cycle loads all active schedules, evaluates whether each is due,
    and submits workflow runs for those that are. Runs are tracked via
    ScheduleRepository so last_run_at advances correctly.

    Usage:
        scheduler = DAGScheduler(schedule_repo, workflow_repo, config)
        scheduler.start(stop_event)  # background thread
        # ... later ...
        stop_event.set()  # exits on next poll boundary
    """

    def __init__(
        self,
        schedule_repo,    # ScheduleRepository — list_active, get_active_run_count, record_run
        workflow_repo,    # WorkflowRunRepository — passed to DAGInitializer
        config: Optional[SchedulerConfig] = None,
    ) -> None:
        self._schedule_repo = schedule_repo
        self._workflow_repo = workflow_repo
        self._config = config or SchedulerConfig.from_environment()
        self._thread: Optional[threading.Thread] = None
        self._last_poll_at: Optional[datetime] = None
        self._total_polls: int = 0
        self._total_fired: int = 0

    def start(self, stop_event: threading.Event) -> None:
        """Start the scheduler background thread."""
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(stop_event,),
            name="dag-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "DAGScheduler started: poll_interval=%ds",
            self._config.poll_interval,
        )

    def _run_loop(self, stop_event: threading.Event) -> None:
        """Main scheduler loop — runs until stop_event is set."""
        while not stop_event.is_set():
            try:
                result = self.poll()
                self._total_polls += 1
                self._last_poll_at = datetime.now(timezone.utc)
                self._total_fired += result.schedules_fired

                if result.schedules_fired > 0 or result.schedules_errored > 0:
                    logger.info(
                        "DAGScheduler poll #%d: checked=%d fired=%d skipped=%d "
                        "errored=%d elapsed_ms=%.1f",
                        self._total_polls,
                        result.schedules_checked,
                        result.schedules_fired,
                        result.schedules_skipped,
                        result.schedules_errored,
                        result.elapsed_ms,
                    )
                else:
                    logger.debug(
                        "DAGScheduler poll #%d: checked=%d nothing due (elapsed_ms=%.1f)",
                        self._total_polls,
                        result.schedules_checked,
                        result.elapsed_ms,
                    )

            except Exception as exc:
                logger.error("DAGScheduler poll error (non-fatal): %s", exc)

            stop_event.wait(self._config.poll_interval)

        logger.info(
            "DAGScheduler stopped after %d polls, %d total runs fired",
            self._total_polls,
            self._total_fired,
        )

    def poll(self) -> SchedulerResult:
        """
        Execute one scheduler poll cycle.

        Callable directly from tests. Each schedule is processed in its own
        try/except — one failure never prevents others from being evaluated.
        """
        from croniter import croniter

        result = SchedulerResult()
        t0 = time.monotonic()
        now = datetime.now(timezone.utc)

        schedules = self._schedule_repo.list_active()
        result.schedules_checked = len(schedules)

        for schedule in schedules:
            try:
                schedule_id = schedule['schedule_id']
                workflow_name = schedule['workflow_name']
                cron_expr = schedule['cron_expression']
                max_concurrent = schedule.get('max_concurrent', 1)
                parameters = schedule.get('parameters') or {}

                # Compute next due time from the last run (or creation time)
                base_time = schedule.get('last_run_at') or schedule.get('created_at')
                if base_time is None:
                    logger.error(
                        "DAGScheduler: schedule=%s has no last_run_at or created_at — skipping",
                        schedule_id,
                    )
                    result.schedules_errored += 1
                    continue

                # croniter requires timezone-naive or timezone-aware consistently
                # Normalise base_time to UTC-aware then strip tz for croniter
                if hasattr(base_time, 'tzinfo') and base_time.tzinfo is not None:
                    base_naive = base_time.replace(tzinfo=None)
                else:
                    base_naive = base_time

                try:
                    next_due_naive = croniter(cron_expr, base_naive).get_next(datetime)
                except Exception as cron_err:
                    logger.error(
                        "DAGScheduler: invalid cron_expression '%s' for schedule=%s: %s",
                        cron_expr, schedule_id, cron_err,
                    )
                    result.schedules_errored += 1
                    continue

                # Re-attach UTC for comparison
                next_due = next_due_naive.replace(tzinfo=timezone.utc)

                if next_due > now:
                    # Not yet due — nothing to do
                    continue

                # Concurrency check
                active_count = self._schedule_repo.get_active_run_count(schedule_id)
                if active_count >= max_concurrent:
                    logger.info(
                        "DAGScheduler: schedule=%s workflow=%s skipped — "
                        "active_runs=%d >= max_concurrent=%d",
                        schedule_id, workflow_name, active_count, max_concurrent,
                    )
                    result.schedules_skipped += 1
                    continue

                # Fire
                run_id = self._fire_schedule(schedule)
                if run_id is not None:
                    self._schedule_repo.record_run(schedule_id, run_id)
                    result.schedules_fired += 1
                    logger.info(
                        "DAGScheduler: fired schedule=%s workflow=%s run_id=%s",
                        schedule_id, workflow_name, run_id[:16],
                    )
                else:
                    result.schedules_errored += 1

            except Exception as exc:
                logger.error(
                    "DAGScheduler: unexpected error processing schedule=%s: %s",
                    schedule.get('schedule_id', '?'), exc,
                )
                result.schedules_errored += 1

        result.elapsed_ms = (time.monotonic() - t0) * 1000
        return result

    def _fire_schedule(self, schedule: dict) -> Optional[str]:
        """
        Submit a workflow run for the given schedule.

        Returns the run_id on success, or None on failure (caller increments
        schedules_errored). All errors are logged here.
        """
        from core.workflow_registry import WorkflowRegistry, WorkflowNotFoundError
        from core.dag_initializer import DAGInitializer
        from config import __version__

        workflow_name = schedule['workflow_name']
        schedule_id = schedule['schedule_id']
        parameters = schedule.get('parameters') or {}

        # Load the workflow definition from the YAML registry
        workflows_dir = Path(__file__).resolve().parents[1] / "workflows"
        registry = WorkflowRegistry(workflows_dir)
        registry.load_all()

        workflow_def = registry.get(workflow_name)
        if workflow_def is None:
            logger.error(
                "DAGScheduler: workflow '%s' not found in registry for schedule=%s",
                workflow_name, schedule_id,
            )
            return None

        # Generate a deterministic request_id so duplicate fires are traceable
        canonical = f"schedule:{schedule_id}:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M')}"
        request_id = f"sched-{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"

        try:
            initializer = DAGInitializer(self._workflow_repo)
            run = initializer.create_run(
                workflow_def=workflow_def,
                parameters=parameters,
                platform_version=__version__,
                request_id=request_id,
            )
        except Exception as exc:
            logger.error(
                "DAGScheduler: failed to create run for schedule=%s workflow=%s: %s",
                schedule_id, workflow_name, exc,
            )
            return None

        # Launch the orchestrator in a background thread (same pattern as submit endpoint)
        from core.dag_orchestrator import DAGOrchestrator

        orchestrator = DAGOrchestrator(self._workflow_repo)

        def _drive_run():
            try:
                result = orchestrator.run(run.run_id, cycle_interval=3.0)
                logger.info(
                    "DAGScheduler orchestrator finished: schedule=%s run_id=%s status=%s",
                    schedule_id, run.run_id[:16], result.final_status.value,
                )
            except Exception as exc:
                logger.error(
                    "DAGScheduler orchestrator error: schedule=%s run_id=%s: %s",
                    schedule_id, run.run_id[:16], exc,
                )

        t = threading.Thread(
            target=_drive_run,
            name=f"dag-orch-{run.run_id[:8]}",
            daemon=True,
        )
        t.start()

        return run.run_id
