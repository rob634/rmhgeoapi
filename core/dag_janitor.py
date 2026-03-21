# ============================================================================
# CLAUDE CONTEXT - DAG JANITOR
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Stale task recovery for workflow_tasks and legacy tasks
# PURPOSE: Background sweep that reclaims stuck RUNNING tasks with stale
#          heartbeats. Retries if eligible, fails permanently if exhausted.
#          Covers both app.workflow_tasks (DAG) and app.tasks (legacy).
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: JanitorConfig, JanitorResult, DAGJanitor
# DEPENDENCIES: logging, threading, time, dataclasses,
#               infrastructure.workflow_run_repository, exceptions
# ============================================================================
"""
DAG Janitor — stale task recovery.

Runs as a background thread in the Docker worker (or DAG Brain).
Fires every SCAN_INTERVAL seconds. For each RUNNING task whose
last_pulse (or updated_at) is older than STALE_THRESHOLD:
  - If retry_count < max_retries: reset to READY with execute_after backoff
  - If retry_count >= max_retries: mark FAILED permanently

Replaces the Function App's system_guardian_sweep timer trigger for
task recovery. Data quality timers (geo_orphan, metadata_consistency,
etc.) remain in the Function App.

Design: fail-open. Each scan phase catches exceptions independently.
A failed scan logs ERROR and retries on the next interval.
"""

import logging
import math
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from core.dag_graph_utils import TaskSummary
from core.models.workflow_enums import WorkflowTaskStatus, WorkflowRunStatus
from exceptions import DatabaseError

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class JanitorConfig:
    """
    Timing thresholds for stale task detection.

    All values in seconds. Override via environment variables prefixed JANITOR_.
    """
    scan_interval: int = 60          # How often the janitor runs (seconds)
    stale_threshold: int = 120       # RUNNING task with no pulse for this long → stale
    max_retries: int = 3             # Max retry attempts before permanent FAILED
    backoff_base: int = 30           # Base delay for exponential backoff (seconds)
    backoff_cap: int = 600           # Maximum backoff delay (seconds)
    batch_limit: int = 50            # Max tasks to process per scan

    @classmethod
    def from_environment(cls) -> 'JanitorConfig':
        """Load config with JANITOR_* env var overrides."""
        import os
        return cls(
            scan_interval=int(os.environ.get('JANITOR_SCAN_INTERVAL', '60')),
            stale_threshold=int(os.environ.get('JANITOR_STALE_THRESHOLD', '120')),
            max_retries=int(os.environ.get('JANITOR_MAX_RETRIES', '3')),
            backoff_base=int(os.environ.get('JANITOR_BACKOFF_BASE', '30')),
            backoff_cap=int(os.environ.get('JANITOR_BACKOFF_CAP', '600')),
            batch_limit=int(os.environ.get('JANITOR_BATCH_LIMIT', '50')),
        )


# ============================================================================
# RESULT
# ============================================================================

@dataclass
class JanitorResult:
    """Result of a single janitor sweep."""
    workflow_tasks_scanned: int = 0
    workflow_tasks_retried: int = 0
    workflow_tasks_failed: int = 0
    legacy_tasks_scanned: int = 0
    legacy_tasks_retried: int = 0
    legacy_tasks_failed: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


# ============================================================================
# JANITOR
# ============================================================================

class DAGJanitor:
    """
    Background stale task recovery.

    Spec: D.7 — Janitor. Scans both workflow_tasks (DAG) and tasks (legacy)
    for RUNNING tasks with stale heartbeats. Retries or fails them.

    Usage:
        janitor = DAGJanitor(workflow_repo, config)
        janitor.start(stop_event)  # background thread
        # ... later ...
        stop_event.set()  # janitor exits on next scan boundary
    """

    def __init__(
        self,
        workflow_repo,  # WorkflowRunRepository — for workflow_tasks
        config: Optional[JanitorConfig] = None,
    ) -> None:
        self._workflow_repo = workflow_repo
        self._config = config or JanitorConfig.from_environment()
        self._thread: Optional[threading.Thread] = None
        self._last_sweep_at: Optional[datetime] = None
        self._total_sweeps: int = 0

    def start(self, stop_event: threading.Event) -> None:
        """Start the janitor background thread."""
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(stop_event,),
            name="dag-janitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "DAGJanitor started: scan_interval=%ds stale_threshold=%ds max_retries=%d",
            self._config.scan_interval,
            self._config.stale_threshold,
            self._config.max_retries,
        )

    def _run_loop(self, stop_event: threading.Event) -> None:
        """Main janitor loop — runs until stop_event is set."""
        while not stop_event.is_set():
            try:
                result = self.sweep()
                self._total_sweeps += 1
                self._last_sweep_at = datetime.now(timezone.utc)

                total_actions = (
                    result.workflow_tasks_retried + result.workflow_tasks_failed
                    + result.legacy_tasks_retried + result.legacy_tasks_failed
                )
                if total_actions > 0:
                    logger.info(
                        "DAGJanitor sweep #%d: wf_retried=%d wf_failed=%d "
                        "legacy_retried=%d legacy_failed=%d elapsed_ms=%.1f",
                        self._total_sweeps,
                        result.workflow_tasks_retried, result.workflow_tasks_failed,
                        result.legacy_tasks_retried, result.legacy_tasks_failed,
                        result.elapsed_ms,
                    )
                else:
                    logger.debug(
                        "DAGJanitor sweep #%d: no stale tasks found (elapsed_ms=%.1f)",
                        self._total_sweeps, result.elapsed_ms,
                    )

            except Exception as exc:
                logger.error("DAGJanitor sweep error (non-fatal): %s", exc)

            stop_event.wait(self._config.scan_interval)

        logger.info("DAGJanitor stopped after %d sweeps", self._total_sweeps)

    def sweep(self) -> JanitorResult:
        """
        Execute one janitor sweep. Called by the background loop or directly in tests.

        Fail-open: each phase catches exceptions independently.
        """
        result = JanitorResult()
        t0 = time.monotonic()

        # Phase 1: Workflow tasks (app.workflow_tasks)
        try:
            self._sweep_workflow_tasks(result)
        except Exception as exc:
            logger.error("DAGJanitor phase 1 (workflow_tasks) error: %s", exc)
            result.errors.append(f"workflow_tasks: {exc}")

        # Phase 2: Legacy tasks (app.tasks)
        try:
            self._sweep_legacy_tasks(result)
        except Exception as exc:
            logger.error("DAGJanitor phase 2 (legacy_tasks) error: %s", exc)
            result.errors.append(f"legacy_tasks: {exc}")

        result.elapsed_ms = (time.monotonic() - t0) * 1000
        return result

    def _sweep_workflow_tasks(self, result: JanitorResult) -> None:
        """
        Find and recover stale RUNNING workflow tasks.

        Spec: D.7 — scan workflow_tasks WHERE status='running'
        AND last_pulse < NOW() - stale_threshold (or last_pulse IS NULL
        AND started_at < NOW() - stale_threshold).
        """
        stale_tasks = self._workflow_repo.get_stale_workflow_tasks(
            stale_threshold_seconds=self._config.stale_threshold,
            limit=self._config.batch_limit,
        )
        result.workflow_tasks_scanned = len(stale_tasks)

        for task in stale_tasks:
            retry_count = task.get('retry_count', 0)
            max_retries = task.get('max_retries', self._config.max_retries)
            task_id = task['task_instance_id']
            task_name = task.get('task_name', 'unknown')

            if retry_count < max_retries:
                # Retry with exponential backoff
                backoff = min(
                    self._config.backoff_base * (2 ** retry_count),
                    self._config.backoff_cap,
                )
                self._workflow_repo.retry_workflow_task(
                    task_instance_id=task_id,
                    backoff_seconds=backoff,
                )
                result.workflow_tasks_retried += 1
                logger.info(
                    "DAGJanitor: retrying workflow task=%s (%s) "
                    "attempt=%d/%d backoff=%ds",
                    task_id[:20], task_name, retry_count + 1, max_retries, backoff,
                )
            else:
                # Exhausted retries → permanent FAILED
                self._workflow_repo.fail_task(
                    task_id,
                    f"Janitor: task unresponsive after {retry_count} retries "
                    f"(stale_threshold={self._config.stale_threshold}s)",
                )
                result.workflow_tasks_failed += 1
                logger.warning(
                    "DAGJanitor: FAILED workflow task=%s (%s) — "
                    "max retries exhausted (%d/%d)",
                    task_id[:20], task_name, retry_count, max_retries,
                )

    def _sweep_legacy_tasks(self, result: JanitorResult) -> None:
        """
        Find and recover stale PROCESSING legacy tasks (app.tasks).

        Uses the existing increment_task_retry_count SQL function for
        atomic retry with exponential backoff.
        """
        try:
            from infrastructure.jobs_tasks import TaskRepository
            task_repo = TaskRepository()
        except Exception as exc:
            logger.debug("DAGJanitor: legacy task repo not available: %s", exc)
            return

        stale_tasks = self._workflow_repo.get_stale_legacy_tasks(
            stale_threshold_seconds=self._config.stale_threshold,
            limit=self._config.batch_limit,
        )
        result.legacy_tasks_scanned = len(stale_tasks)

        for task in stale_tasks:
            retry_count = task.get('retry_count', 0)
            task_id = task['task_id']

            if retry_count < self._config.max_retries:
                retry_result = task_repo.increment_task_retry_count(
                    task_id,
                    error_details=f"Janitor: stale PROCESSING (threshold={self._config.stale_threshold}s)",
                )
                if retry_result:
                    result.legacy_tasks_retried += 1
                else:
                    result.legacy_tasks_failed += 1
            else:
                task_repo.fail_task(
                    task_id,
                    f"Janitor: max retries exhausted ({retry_count}/{self._config.max_retries})",
                )
                result.legacy_tasks_failed += 1

                # Propagate to parent job if all tasks are now terminal
                self._maybe_fail_parent_job(task, task_repo)

    def _maybe_fail_parent_job(self, task: dict, task_repo) -> None:
        """
        After permanently failing a task, check if the parent job should
        also be marked failed (all sibling tasks terminal, at least one failed).

        Fail-open: catches all exceptions so a propagation error never
        blocks the janitor sweep.
        """
        job_id = task.get('parent_job_id')
        if not job_id:
            return

        try:
            from infrastructure.jobs_tasks import JobRepository

            siblings = task_repo.get_tasks_for_job(job_id)
            if not siblings:
                return

            terminal = {'completed', 'failed', 'skipped', 'cancelled'}
            statuses = [
                s.status.value if hasattr(s.status, 'value') else str(s.status)
                for s in siblings
            ]

            if not all(s in terminal for s in statuses):
                return  # Some tasks still running — don't touch the job

            failed_count = sum(1 for s in statuses if s == 'failed')
            if failed_count == 0:
                return  # All terminal but none failed — shouldn't happen here, but guard

            job_repo = JobRepository()
            job_repo.fail_job(
                job_id,
                f"Janitor: all {len(siblings)} tasks terminal, {failed_count} failed",
            )
            logger.info(
                "Janitor propagated failure to job %s (%d tasks, %d failed)",
                job_id[:20], len(siblings), failed_count,
            )
        except Exception as exc:
            logger.warning(
                "Janitor job propagation failed for %s: %s", job_id[:20], exc,
            )
