# ============================================================================
# CLAUDE CONTEXT - DAG ORCHESTRATOR
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Poll-loop lifecycle controller for workflow DAG runs
# PURPOSE: Acquire advisory lock, drive the per-tick dispatch cycle
#          (transitions → conditionals → fan-outs → fan-ins), detect
#          terminal state, and write the final run status to the database.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: OrchestratorResult, DAGOrchestrator
# DEPENDENCIES: hashlib, logging, threading, time, psycopg,
#               core.dag_graph_utils, core.dag_transition_engine,
#               core.dag_fan_engine, core.models.workflow_definition,
#               core.models.workflow_enums,
#               infrastructure.workflow_run_repository, exceptions
# ============================================================================
"""
DAG Orchestrator — lifecycle controller for a single workflow run.

Each call to DAGOrchestrator.run() acquires a PostgreSQL transaction-level
advisory lock on the run_id so that concurrent callers (e.g. multiple Function
App instances or Docker worker threads) do not step on each other. The lock
auto-releases when the transaction commits — no dedicated connection needed.

The dispatch order within each tick is fixed (ARB decision):
    1. evaluate_transitions   — promote PENDING → READY, evaluate when-clauses
    2. evaluate_conditionals  — route conditional branches
    3. expand_fan_outs        — expand fan-out templates into child instances
    4. aggregate_fan_ins      — collapse completed children into fan-in results

Spec: D.5 DAGOrchestrator component.
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from core.dag_graph_utils import is_run_terminal
from core.dag_transition_engine import evaluate_transitions
from core.dag_fan_engine import evaluate_conditionals, expand_fan_outs, aggregate_fan_ins
from core.models.workflow_definition import WorkflowDefinition
from core.models.workflow_enums import WorkflowRunStatus, WorkflowTaskStatus
from infrastructure.workflow_run_repository import WorkflowRunRepository
from exceptions import ContractViolationError, DatabaseError

logger = logging.getLogger(__name__)


# ============================================================================
# RELEASE LIFECYCLE (Option B — orchestrator-managed, not handler-managed)
# ============================================================================


def _handle_release_lifecycle(
    run,
    status: WorkflowRunStatus,
    repo,
    error_message: Optional[str] = None,
):
    """
    Update the linked Release record based on workflow run status transitions.

    Called at three points in the orchestrator:
    1. PENDING → RUNNING: Release → PROCESSING
    2. Terminal COMPLETED: Release → COMPLETED + cache blob_path
    3. Terminal FAILED: Release → FAILED

    Non-fatal — Release update failure does not affect workflow execution.
    Handlers have zero Release awareness; this is purely orchestration.
    """
    release_id = getattr(run, 'release_id', None)
    if not release_id:
        return

    try:
        from infrastructure import ReleaseRepository
        from core.models.asset import ProcessingStatus
        release_repo = ReleaseRepository()

        if status == WorkflowRunStatus.RUNNING:
            release_repo.update_processing_status(
                release_id, ProcessingStatus.PROCESSING
            )
            logger.info(
                "Release lifecycle: %s → PROCESSING (run_id=%s)",
                release_id[:16], run.run_id[:16],
            )

        elif status == WorkflowRunStatus.COMPLETED:
            release_repo.update_processing_status(
                release_id, ProcessingStatus.COMPLETED
            )
            # Cache blob_path from the persist handler's result for approval UI
            _cache_outputs_on_release(run, release_repo, repo)
            logger.info(
                "Release lifecycle: %s → COMPLETED (run_id=%s)",
                release_id[:16], run.run_id[:16],
            )

        elif status == WorkflowRunStatus.FAILED:
            # Truncate error to 500 chars (matching monolith behavior)
            error_truncated = (error_message or "Unknown error")[:500]
            release_repo.update_processing_status(
                release_id, ProcessingStatus.FAILED, error=error_truncated
            )
            logger.info(
                "Release lifecycle: %s → FAILED (run_id=%s)",
                release_id[:16], run.run_id[:16],
            )

    except Exception as exc:
        logger.warning(
            "Release lifecycle update failed (non-fatal): release_id=%s status=%s error=%s",
            release_id[:16] if release_id else "?", status.value, exc,
        )


def _cache_outputs_on_release(run, release_repo, workflow_repo):
    """
    After COMPLETED, find output blob paths from task results and cache
    on the Release record for the approval UI.
    """
    try:
        tasks = workflow_repo.get_tasks_for_run(run.run_id)
        for task in tasks:
            result = task.result_data or {}
            inner = result.get('result', {})

            # Raster: persist handler has silver_blob_path
            blob_path = inner.get('silver_blob_path')
            # Vector: register_catalog has table info
            if not blob_path and inner.get('tables_registered'):
                entries = inner.get('catalog_entries', [])
                if entries:
                    blob_path = entries[0].get('table_name')

            if blob_path:
                release_repo.update_physical_outputs(
                    run.release_id, blob_path=blob_path
                )
                break
    except Exception as exc:
        logger.warning(
            "Release output caching failed (non-fatal): run_id=%s error=%s",
            run.run_id[:16], exc,
        )


# ============================================================================
# RESULT DTO
# ============================================================================


@dataclass
class OrchestratorResult:
    """
    Summary of a completed DAGOrchestrator.run() call.

    Spec: D.5 — OrchestratorResult DTO.  All counter fields accumulate across
    every cycle; final_status reflects the last known run status at exit.
    """
    run_id: str
    final_status: WorkflowRunStatus
    tasks_promoted: int = 0     # total PENDING→READY + conditional + fan-in completions
    tasks_skipped: int = 0      # total tasks transitioned to SKIPPED
    tasks_failed: int = 0       # total tasks transitioned to FAILED
    cycles_run: int = 0         # number of dispatch cycles completed
    elapsed_seconds: float = 0.0
    error: Optional[str] = None  # set on non-terminal exits (lock held, shutdown, max cycles)


# ============================================================================
# PRIVATE HELPERS
# ============================================================================


def _advisory_lock_id(run_id: str) -> int:
    """
    Derive a stable 63-bit PostgreSQL advisory lock key from a run_id string.

    Spec: D.5 — advisory_lock_id.  SHA-256 first 16 hex chars → int, masked
    to 63 bits so it fits PostgreSQL's bigint advisory lock space without sign
    issues (pg_try_advisory_lock takes bigint, which is signed 64-bit; masking
    to 0x7FFFFFFFFFFFFFFF keeps the value non-negative).

    Parameters
    ----------
    run_id:
        The workflow run primary key (UUID string or similar).

    Returns
    -------
    int
        Stable, deterministic 63-bit integer lock key.
    """
    return int(hashlib.sha256(run_id.encode()).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF


# ============================================================================
# ORCHESTRATOR
# ============================================================================


class DAGOrchestrator:
    """
    Poll-loop controller for a single DAG workflow run.

    Holds one WorkflowRunRepository for all application DB operations.
    Acquires a transaction-level advisory lock via the pooled connection
    so concurrent orchestrator instances do not interfere.

    Spec: D.5 — DAGOrchestrator.

    Parameters
    ----------
    repo:
        WorkflowRunRepository used for all task + run DB mutations.
    """

    def __init__(self, repo: WorkflowRunRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # ADVISORY LOCK (transaction-level)
    # ------------------------------------------------------------------

    def _try_acquire_xact_lock(self, lock_id: int) -> bool:
        """
        Acquire a transaction-level advisory lock using a pooled connection.

        Uses pg_try_advisory_xact_lock which auto-releases when the
        transaction ends (commit or rollback). No dedicated connection needed.
        Returns False (no-op) if another session holds the lock.
        """
        try:
            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_id,))
                    row = cur.fetchone()
                    acquired = row[0]
                conn.commit()

            if acquired:
                logger.info("DAGOrchestrator: advisory xact lock acquired (lock_id=%d)", lock_id)
            else:
                logger.info("DAGOrchestrator: advisory xact lock NOT acquired (lock_id=%d)", lock_id)

            return acquired
        except Exception as exc:
            logger.error("DAGOrchestrator: failed to acquire xact lock: %s", exc)
            return False

    # ------------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ------------------------------------------------------------------

    def run(
        self,
        run_id: str,
        max_cycles: int = 1000,
        cycle_interval: float = 5.0,
        shutdown_event: Optional[threading.Event] = None,
    ) -> OrchestratorResult:
        """
        Drive a single workflow run to completion.

        Acquires a PostgreSQL advisory lock on `run_id`, then polls the database
        in a tight cycle until the run reaches a terminal state, max_cycles is
        exhausted, or a shutdown signal is received.

        Advisory lock semantics: if another orchestrator instance already holds
        the lock (e.g. a concurrent Function App invocation), this call returns
        immediately with ``result.error = "lock_held"`` and
        ``result.final_status = WorkflowRunStatus.RUNNING``.  The caller should
        treat this as a benign no-op.

        Parameters
        ----------
        run_id:
            The workflow run primary key.
        max_cycles:
            Hard ceiling on dispatch cycles (prevents infinite loops on stuck runs).
        cycle_interval:
            Seconds to sleep between cycles when the run is still in-flight.
            Set to 0.0 in unit tests for fast execution.
        shutdown_event:
            Optional threading.Event; when set, the loop exits cleanly after
            completing the current cycle.

        Returns
        -------
        OrchestratorResult
            Always returned — never raises (ContractViolationError excepted, which
            propagates to indicate a programming bug).

        Raises
        ------
        ContractViolationError
            If a DB/definition mismatch is detected inside a cycle (programming bug).
        """
        t_start = time.monotonic()
        result = OrchestratorResult(
            run_id=run_id,
            final_status=WorkflowRunStatus.RUNNING,
        )

        try:
            # ----------------------------------------------------------
            # Step 1: Acquire transaction-level advisory lock
            # ----------------------------------------------------------
            lock_id = _advisory_lock_id(run_id)
            acquired = self._try_acquire_xact_lock(lock_id)

            if not acquired:
                result.error = "lock_held"
                logger.info(
                    "DAGOrchestrator.run: run_id=%s — lock held by another instance, exiting",
                    run_id,
                )
                return result

            # ----------------------------------------------------------
            # Step 2: Load run
            # ----------------------------------------------------------
            run = self._repo.get_by_run_id(run_id)
            if run is None:
                raise ContractViolationError(
                    f"DAGOrchestrator.run: run_id={run_id!r} not found in workflow_runs. "
                    "Caller must only invoke run() with a valid, pre-inserted run_id."
                )

            # ----------------------------------------------------------
            # Step 3: Check current status — already terminal?
            # ----------------------------------------------------------
            if run.status in (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED):
                result.final_status = run.status
                logger.info(
                    "DAGOrchestrator.run: run_id=%s already terminal (status=%s) — exiting",
                    run_id, run.status.value,
                )
                return result

            # ----------------------------------------------------------
            # Step 4: Mark RUNNING if PENDING
            # ----------------------------------------------------------
            if run.status == WorkflowRunStatus.PENDING:
                updated = self._repo.update_run_status(run_id, WorkflowRunStatus.RUNNING)
                if updated:
                    logger.info(
                        "DAGOrchestrator.run: run_id=%s PENDING→RUNNING", run_id
                    )
                    _handle_release_lifecycle(run, WorkflowRunStatus.RUNNING, self._repo)
                else:
                    logger.debug(
                        "DAGOrchestrator.run: run_id=%s update_run_status guard rejected "
                        "(may already be RUNNING from a previous tick)", run_id
                    )

            # ----------------------------------------------------------
            # Step 5: Parse workflow definition from JSONB snapshot
            # ----------------------------------------------------------
            workflow_def = WorkflowDefinition.model_validate(run.definition)
            job_params: dict = run.parameters or {}

            logger.info(
                "DAGOrchestrator.run: run_id=%s workflow=%r starting poll loop "
                "(max_cycles=%d, cycle_interval=%.1fs)",
                run_id, run.workflow_name, max_cycles, cycle_interval,
            )

            # ----------------------------------------------------------
            # Step 6: Poll loop
            # ----------------------------------------------------------
            consecutive_errors = 0
            MAX_CONSECUTIVE_ERRORS = 3

            for cycle in range(max_cycles):

                # Shutdown check at top of each cycle
                if shutdown_event is not None and shutdown_event.is_set():
                    result.error = "shutdown_requested"
                    logger.info(
                        "DAGOrchestrator.run: run_id=%s shutdown requested at cycle %d",
                        run_id, cycle,
                    )
                    break

                try:
                    # 6a: Fresh state load
                    tasks = self._repo.get_tasks_for_run(run_id)
                    deps = self._repo.get_deps_for_run(run_id)

                    # Build predecessor_outputs from completed/expanded tasks.
                    # Skip fan-out children (fan_out_source is not None) — they share
                    # task_name with their template, causing dict collision. Fan-in
                    # aggregation reads children directly via fan_out_source, not here.
                    predecessor_outputs: dict[str, dict] = {
                        t.task_name: t.result_data or {}
                        for t in tasks
                        if t.status in (
                            WorkflowTaskStatus.COMPLETED,
                            WorkflowTaskStatus.EXPANDED,
                        )
                        and t.fan_out_source is None
                    }

                    # 6b: Fixed dispatch order (ARB decision)
                    tr = evaluate_transitions(
                        run_id, workflow_def, tasks, deps,
                        predecessor_outputs, job_params, self._repo,
                    )
                    cr = evaluate_conditionals(
                        run_id, workflow_def, tasks, deps,
                        predecessor_outputs, job_params, self._repo,
                    )
                    fr = expand_fan_outs(
                        run_id, workflow_def, tasks, deps,
                        predecessor_outputs, job_params, self._repo,
                    )
                    ar = aggregate_fan_ins(
                        run_id, workflow_def, tasks, deps, self._repo,
                    )

                    # 6c: Accumulate counts
                    # tr: promoted (PENDING→READY), skipped, failed
                    # cr: taken (conditional completions), skipped (branch targets), failed
                    # fr: expanded (template ids), children_created — FanOutResult has no .failed
                    # ar: aggregated (fan-in completions), failed
                    result.tasks_promoted += (
                        len(tr.promoted)
                        + len(cr.taken)
                        + fr.children_created
                        + len(ar.aggregated)
                    )
                    result.tasks_skipped += len(tr.skipped) + len(cr.skipped)
                    result.tasks_failed += (
                        len(tr.failed) + len(cr.failed) + len(ar.failed)
                    )

                    # 6d: Reset error counter on clean cycle
                    consecutive_errors = 0

                    logger.debug(
                        "DAGOrchestrator cycle %d: run_id=%s "
                        "promoted=%d skipped=%d failed=%d fan_out_children=%d",
                        cycle, run_id,
                        len(tr.promoted) + len(cr.taken) + len(ar.aggregated),
                        len(tr.skipped) + len(cr.skipped),
                        len(tr.failed) + len(cr.failed) + len(ar.failed),
                        fr.children_created,
                    )

                    # 6e: Refresh tasks for terminal check
                    tasks = self._repo.get_tasks_for_run(run_id)
                    is_terminal, terminal_status = is_run_terminal(tasks)

                    if is_terminal:
                        self._repo.update_run_status(run_id, terminal_status)
                        result.final_status = terminal_status
                        result.cycles_run = cycle + 1
                        logger.info(
                            "DAGOrchestrator.run: run_id=%s terminal detected at cycle %d "
                            "— final_status=%s",
                            run_id, cycle, terminal_status.value,
                        )
                        _handle_release_lifecycle(
                            run, terminal_status, self._repo,
                            error_message=result.error,
                        )
                        break

                    result.cycles_run = cycle + 1

                except ContractViolationError:
                    # Programming bug — propagate immediately; advisory lock
                    # is still released in the finally block below.
                    logger.error(
                        "DAGOrchestrator.run: run_id=%s ContractViolationError at cycle %d "
                        "— propagating (programming bug)",
                        run_id, cycle,
                    )
                    raise

                except Exception as exc:
                    consecutive_errors += 1
                    logger.error(
                        "DAGOrchestrator cycle %d error (%d/%d): run_id=%s — %s",
                        cycle, consecutive_errors, MAX_CONSECUTIVE_ERRORS,
                        run_id, exc,
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self._repo.update_run_status(run_id, WorkflowRunStatus.FAILED)
                        result.final_status = WorkflowRunStatus.FAILED
                        result.error = f"max_consecutive_errors: {exc}"
                        result.cycles_run = cycle + 1
                        logger.error(
                            "DAGOrchestrator.run: run_id=%s reached max consecutive errors "
                            "(%d) — marking FAILED and exiting",
                            run_id, MAX_CONSECUTIVE_ERRORS,
                        )
                        _handle_release_lifecycle(
                            run, WorkflowRunStatus.FAILED, self._repo,
                            error_message=str(exc),
                        )
                        break

                # Sleep between cycles only when still in-flight
                if cycle_interval > 0.0:
                    time.sleep(cycle_interval)

            else:
                # for-loop completed all max_cycles without a terminal break
                result.error = "max_cycles_exhausted"
                logger.warning(
                    "DAGOrchestrator.run: run_id=%s exhausted max_cycles=%d without reaching "
                    "terminal state — possible stuck run",
                    run_id, max_cycles,
                )

        finally:
            result.elapsed_seconds = time.monotonic() - t_start
            # Transaction-level lock auto-released on commit/rollback.
            # No dedicated connection to close.

        logger.info(
            "DAGOrchestrator.run: run_id=%s complete — final_status=%s cycles=%d "
            "promoted=%d skipped=%d failed=%d elapsed=%.2fs error=%s",
            run_id,
            result.final_status.value,
            result.cycles_run,
            result.tasks_promoted,
            result.tasks_skipped,
            result.tasks_failed,
            result.elapsed_seconds,
            result.error,
        )
        return result
