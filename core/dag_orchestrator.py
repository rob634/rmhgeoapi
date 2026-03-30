# ============================================================================
# CLAUDE CONTEXT - DAG ORCHESTRATOR
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Poll-loop lifecycle controller for workflow DAG runs
# PURPOSE: Drive the per-tick dispatch cycle (transitions → conditionals →
#          fan-outs → fan-ins), detect terminal state, and write the final
#          run status to the database. Lease safety is managed externally
#          by the DAG Brain primary loop via the lease_check callback.
# LAST_REVIEWED: 26 MAR 2026
# EXPORTS: OrchestratorResult, DAGOrchestrator
# DEPENDENCIES: logging, threading, time, psycopg,
#               core.dag_graph_utils, core.dag_transition_engine,
#               core.dag_fan_engine, core.dag_repository_protocol,
#               core.models.workflow_definition, core.models.workflow_enums,
#               exceptions
# ============================================================================
"""
DAG Orchestrator — lifecycle controller for a single workflow run.

Each call to DAGOrchestrator.run() drives a single workflow run to completion.
Concurrency safety is managed externally by the DAG Brain primary loop via a
database lease (LeaseRepository). The orchestrator itself is lease-agnostic —
it accepts an optional ``lease_check`` callable that it invokes at the top of
each cycle. If the callable returns False the loop exits cleanly with
``result.error = "lease_lost"``.

The dispatch order within each tick is fixed (ARB decision):
    1. evaluate_transitions   — promote PENDING → READY, evaluate when-clauses
    2. evaluate_conditionals  — route conditional branches
    3. expand_fan_outs        — expand fan-out templates into child instances
    4. aggregate_fan_ins      — collapse completed children into fan-in results

Spec: D.5 DAGOrchestrator component.
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional

from util_logger import LoggerFactory, ComponentType

from core.dag_graph_utils import is_run_terminal
from core.dag_transition_engine import evaluate_transitions
from core.dag_fan_engine import evaluate_conditionals, expand_fan_outs, aggregate_fan_ins
from core.models.workflow_definition import WorkflowDefinition
from core.models.workflow_enums import WorkflowRunStatus, WorkflowTaskStatus
from core.dag_repository_protocol import DAGRepositoryProtocol
from exceptions import ContractViolationError, DatabaseError

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, __name__)


# ============================================================================
# RELEASE LIFECYCLE (Option B — orchestrator-managed, not handler-managed)
# ============================================================================


def _handle_release_lifecycle(
    run,
    status: WorkflowRunStatus,
    repo,
    error_message: Optional[str] = None,
    release_repo=None,
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
        from core.models.asset import ProcessingStatus
        if release_repo is None:
            from infrastructure import ReleaseRepository
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

    except ContractViolationError:
        raise  # Programming bug — must not be swallowed (Constitution §1.3)
    except Exception as exc:
        logger.warning(
            "Release lifecycle update failed (non-fatal): release_id=%s status=%s error=%s",
            release_id[:16] if release_id else "?", status.value, exc,
        )


def _cache_outputs_on_release(run, release_repo, workflow_repo):
    """
    After COMPLETED, find output blob paths from task results and cache
    on the Release record for the approval UI.

    Expected handler output fields (in result_data.result):
    - Raster persist handler: silver_blob_path (str)
    - Vector register_catalog: tables_registered (bool), catalog_entries (list of dicts with table_name)
    """
    try:
        tasks = workflow_repo.get_tasks_for_run(run.run_id)
        for task in tasks:
            if task.status != WorkflowTaskStatus.COMPLETED:
                continue
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
    except ContractViolationError:
        raise  # Programming bug — must not be swallowed (Constitution §1.3)
    except Exception as exc:
        logger.warning(
            "Release output caching failed (non-fatal): run_id=%s error=%s",
            run.run_id[:16], exc,
        )


# ============================================================================
# FINALIZE DISPATCH
# ============================================================================


def _dispatch_finalize(
    workflow_def: WorkflowDefinition,
    run_id: str,
):
    """
    Invoke the workflow's finalize handler after terminal state is reached.

    Called on both COMPLETED and FAILED terminal paths so that mount cleanup
    happens regardless of outcome. Non-fatal — finalize failure does not
    affect the run's terminal status or Release lifecycle.

    If the workflow has no ``finalize`` block, this is a no-op.
    """
    if not workflow_def.finalize:
        return

    handler_name = workflow_def.finalize.handler
    try:
        from services import ALL_HANDLERS
        handler_fn = ALL_HANDLERS.get(handler_name)
        if handler_fn is None:
            logger.warning(
                "Finalize dispatch: handler '%s' not in ALL_HANDLERS — skipping",
                handler_name,
            )
            return

        logger.info(
            "Finalize dispatch: run_id=%s handler=%s",
            run_id[:16], handler_name,
        )
        result = handler_fn({"_run_id": run_id})
        logger.info(
            "Finalize dispatch: run_id=%s handler=%s success=%s",
            run_id[:16], handler_name, result.get("success"),
        )
    except ContractViolationError:
        raise  # Programming bug — must not be swallowed (Constitution §1.3)
    except Exception as exc:
        logger.warning(
            "Finalize dispatch failed (non-fatal): run_id=%s handler=%s error=%s",
            run_id[:16], handler_name, exc,
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
    tasks_promoted: int = 0         # PENDING→READY transitions
    conditionals_taken: int = 0     # conditional branches resolved
    fan_out_children: int = 0       # fan-out child instances created
    fan_ins_aggregated: int = 0     # fan-in aggregations completed
    tasks_skipped: int = 0      # total tasks transitioned to SKIPPED
    tasks_failed: int = 0       # total tasks transitioned to FAILED
    cycles_run: int = 0         # number of dispatch cycles completed
    elapsed_seconds: float = 0.0
    error: Optional[str] = None  # set on non-terminal exits (lease_lost, shutdown, max cycles)


# ============================================================================
# ORCHESTRATOR
# ============================================================================


class DAGOrchestrator:
    """
    Poll-loop controller for a single DAG workflow run.

    Holds one DAGRepositoryProtocol implementation for all application DB operations.
    Concurrency safety is managed externally via a database lease; this
    class is lease-agnostic and accepts a ``lease_check`` callback in
    ``run()`` to verify the lease is still held at the top of each cycle.

    Spec: D.5 — DAGOrchestrator.

    Parameters
    ----------
    repo:
        DAGRepositoryProtocol implementation used for all task + run DB mutations.
    """

    def __init__(self, repo: DAGRepositoryProtocol) -> None:
        self._repo = repo
        self._release_repo = None

    def _get_release_repo(self):
        """Lazy-init ReleaseRepository to avoid per-call connection churn."""
        if self._release_repo is None:
            from infrastructure import ReleaseRepository
            self._release_repo = ReleaseRepository()
        return self._release_repo

    # ------------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ------------------------------------------------------------------

    def run(
        self,
        run_id: str,
        max_cycles: int = 1000,
        cycle_interval: float = 5.0,
        shutdown_event: Optional[threading.Event] = None,
        lease_check: Optional[callable] = None,
    ) -> OrchestratorResult:
        """
        Drive a single workflow run to completion.

        Polls the database in a tight cycle until the run reaches a terminal
        state, max_cycles is exhausted, a shutdown signal is received, or the
        lease_check callback returns False.

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
        lease_check:
            Optional callable that returns True if the caller still holds the
            database lease, False if the lease has been lost or expired. Called
            at the start of each cycle. If it returns False the loop exits with
            ``result.error = "lease_lost"``. Pass None to skip lease validation
            (e.g. in unit tests or when the caller manages safety externally).

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
            # Step 1: Load run
            # ----------------------------------------------------------
            run = self._repo.get_by_run_id(run_id)
            if run is None:
                raise ContractViolationError(
                    f"DAGOrchestrator.run: run_id={run_id!r} not found in workflow_runs. "
                    "Caller must only invoke run() with a valid, pre-inserted run_id."
                )

            # ----------------------------------------------------------
            # Step 2: Check current status — already terminal or suspended?
            # ----------------------------------------------------------
            if run.status in (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED):
                result.final_status = run.status
                logger.info(
                    "DAGOrchestrator.run: run_id=%s already terminal (status=%s) — exiting",
                    run_id, run.status.value,
                )
                return result

            if run.status == WorkflowRunStatus.AWAITING_APPROVAL:
                # Gate reconciliation: check linked release's approval_state
                release = self._repo.get_release_for_waiting_run(run_id)

                if release is None:
                    logger.warning(
                        "DAGOrchestrator.run: run_id=%s AWAITING_APPROVAL but no linked release",
                        run_id,
                    )
                    result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                    return result

                approval_state = release.get("approval_state")

                # Discover gate node name from WAITING tasks (not hardcoded)
                waiting_tasks = [
                    t for t in self._repo.get_tasks_for_run(run_id)
                    if t.status == WorkflowTaskStatus.WAITING
                ]
                gate_node_name = waiting_tasks[0].task_name if waiting_tasks else "approval_gate"

                if approval_state == "approved":
                    gate_completed = self._repo.complete_gate_node(
                        run_id=run_id,
                        gate_node_name=gate_node_name,
                        result_data={
                            "decision": "approved",
                            "clearance_state": release.get("clearance_state"),
                            "reviewer": release.get("reviewer"),
                            "version_id": release.get("version_id"),
                        },
                    )
                    if gate_completed:
                        logger.info(
                            "Gate reconciliation: run_id=%s approved — resuming workflow",
                            run_id,
                        )
                        # Reload run status — complete_gate_node changed it to RUNNING
                        run = self._repo.get_by_run_id(run_id)
                        # Fall through to normal processing below
                    else:
                        logger.warning(
                            "Gate reconciliation: run_id=%s gate completion failed "
                            "(may already be completed)", run_id,
                        )
                        result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                        return result

                elif approval_state == "rejected":
                    self._repo.skip_gate_node(
                        run_id=run_id,
                        gate_node_name=gate_node_name,
                        result_data={
                            "decision": "rejected",
                            "reviewer": release.get("reviewer"),
                        },
                    )
                    logger.info(
                        "Gate reconciliation: run_id=%s rejected — skipping downstream",
                        run_id,
                    )
                    # Reload run — skip_gate_node changed it to RUNNING
                    run = self._repo.get_by_run_id(run_id)
                    # Fall through — transition engine will propagate skips

                elif approval_state == "revoked":
                    self._repo.update_run_status(run_id, WorkflowRunStatus.FAILED)
                    logger.warning(
                        "Gate reconciliation: run_id=%s revoked — failing workflow",
                        run_id,
                    )
                    result.final_status = WorkflowRunStatus.FAILED
                    return result

                else:
                    # Still pending_review — nothing to do
                    logger.debug(
                        "Gate reconciliation: run_id=%s still pending_review",
                        run_id,
                    )
                    result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                    return result

            # ----------------------------------------------------------
            # Step 3: Mark RUNNING if PENDING
            # ----------------------------------------------------------
            if run.status == WorkflowRunStatus.PENDING:
                updated = self._repo.update_run_status(run_id, WorkflowRunStatus.RUNNING)
                if updated:
                    logger.info(
                        "DAGOrchestrator.run: run_id=%s PENDING→RUNNING", run_id
                    )
                    _handle_release_lifecycle(run, WorkflowRunStatus.RUNNING, self._repo, release_repo=self._get_release_repo())
                else:
                    logger.debug(
                        "DAGOrchestrator.run: run_id=%s update_run_status guard rejected "
                        "(may already be RUNNING from a previous tick)", run_id
                    )

            # ----------------------------------------------------------
            # Step 4: Parse workflow definition from JSONB snapshot
            # ----------------------------------------------------------
            workflow_def = WorkflowDefinition.model_validate(run.definition)
            job_params: dict = run.parameters or {}

            logger.info(
                "DAGOrchestrator.run: run_id=%s workflow=%r starting poll loop "
                "(max_cycles=%d, cycle_interval=%.1fs)",
                run_id, run.workflow_name, max_cycles, cycle_interval,
            )

            # ----------------------------------------------------------
            # Step 5: Poll loop
            # ----------------------------------------------------------
            consecutive_errors = 0
            MAX_CONSECUTIVE_ERRORS = 3

            for cycle in range(max_cycles):

                # Lease check at top of each cycle
                if lease_check is not None and not lease_check():
                    result.error = "lease_lost"
                    logger.warning(
                        "DAGOrchestrator.run: lease lost for run_id=%s — stopping",
                        run_id,
                    )
                    break

                # Shutdown check at top of each cycle
                if shutdown_event is not None and shutdown_event.is_set():
                    result.error = "shutdown_requested"
                    logger.info(
                        "DAGOrchestrator.run: run_id=%s shutdown requested at cycle %d",
                        run_id, cycle,
                    )
                    break

                try:
                    # 5a: Fresh state load
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

                    # 5b: Fixed dispatch order (ARB decision)
                    tr = evaluate_transitions(
                        run_id, workflow_def, tasks, deps,
                        predecessor_outputs, job_params, self._repo,
                    )

                    # Re-fetch state after transitions to avoid stale-snapshot
                    # latency (F4 fix: ensures conditionals/fans see promoted tasks)
                    if tr.promoted or tr.skipped or tr.failed:
                        tasks = self._repo.get_tasks_for_run(run_id)
                        predecessor_outputs = {
                            t.task_name: t.result_data or {}
                            for t in tasks
                            if t.status in (
                                WorkflowTaskStatus.COMPLETED,
                                WorkflowTaskStatus.EXPANDED,
                            )
                            and t.fan_out_source is None
                        }

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

                    # 5c: Accumulate counts
                    # tr: promoted (PENDING→READY), skipped, failed
                    # cr: taken (conditional completions), skipped (branch targets), failed
                    # fr: expanded (template ids), children_created — FanOutResult has no .failed
                    # ar: aggregated (fan-in completions), failed
                    result.tasks_promoted += len(tr.promoted)
                    result.conditionals_taken += len(cr.taken)
                    result.fan_out_children += fr.children_created
                    result.fan_ins_aggregated += len(ar.aggregated)
                    result.tasks_skipped += len(tr.skipped) + len(cr.skipped)
                    result.tasks_failed += (
                        len(tr.failed) + len(cr.failed) + len(ar.failed)
                    )

                    # 5d: Reset error counter on clean cycle
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

                    # 5e: Refresh tasks for terminal check
                    tasks = self._repo.get_tasks_for_run(run_id)
                    is_terminal, terminal_status = is_run_terminal(tasks)

                    if not is_terminal and terminal_status == WorkflowRunStatus.AWAITING_APPROVAL:
                        # Run has hit a gate node — suspend it
                        self._repo.update_run_status(run_id, WorkflowRunStatus.AWAITING_APPROVAL)
                        logger.info(
                            "DAGOrchestrator.run: run_id=%s suspended at gate node "
                            "(AWAITING_APPROVAL) at cycle %d",
                            run_id, cycle,
                        )
                        result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                        result.cycles_run = cycle + 1
                        break

                    if is_terminal:
                        self._repo.update_run_status(run_id, terminal_status)
                        result.final_status = terminal_status
                        result.cycles_run = cycle + 1
                        logger.info(
                            "DAGOrchestrator.run: run_id=%s terminal detected at cycle %d "
                            "— final_status=%s",
                            run_id, cycle, terminal_status.value,
                        )
                        # Build error message from failed tasks (not result.error,
                        # which is only set for non-terminal exits like lease_lost)
                        release_error = result.error
                        if not release_error and terminal_status == WorkflowRunStatus.FAILED:
                            failed_tasks = [
                                t for t in tasks
                                if t.status == WorkflowTaskStatus.FAILED
                            ]
                            if failed_tasks:
                                first_err = (
                                    (failed_tasks[0].result_data or {})
                                    .get('error')
                                    or 'Task failed'
                                )
                                release_error = (
                                    f"{len(failed_tasks)} task(s) failed. "
                                    f"First: {first_err}"
                                )
                        _handle_release_lifecycle(
                            run, terminal_status, self._repo,
                            error_message=release_error,
                            release_repo=self._get_release_repo(),
                        )
                        _dispatch_finalize(workflow_def, run_id)
                        break

                    result.cycles_run = cycle + 1

                except ContractViolationError:
                    # Programming bug — propagate immediately.
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
                            release_repo=self._get_release_repo(),
                        )
                        _dispatch_finalize(workflow_def, run_id)
                        break

                # Sleep between cycles only when still in-flight
                if cycle_interval > 0.0:
                    time.sleep(cycle_interval)

            else:
                # for-loop completed all max_cycles without a terminal break.
                # Only mark FAILED when max_cycles is large (real stuck run).
                # When max_cycles=1 (single-tick mode used by DAG Brain),
                # the Brain's outer loop will re-dispatch — this is normal.
                if max_cycles > 1:
                    self._repo.update_run_status(run_id, WorkflowRunStatus.FAILED)
                    result.final_status = WorkflowRunStatus.FAILED
                    result.error = "max_cycles_exhausted"
                    result.cycles_run = max_cycles
                    logger.warning(
                        "DAGOrchestrator.run: run_id=%s exhausted max_cycles=%d without reaching "
                        "terminal state — marking FAILED",
                        run_id, max_cycles,
                    )
                    _handle_release_lifecycle(
                        run, WorkflowRunStatus.FAILED, self._repo,
                        error_message="max_cycles_exhausted",
                        release_repo=self._get_release_repo(),
                    )
                    _dispatch_finalize(workflow_def, run_id)
                else:
                    result.cycles_run = max_cycles

        finally:
            result.elapsed_seconds = time.monotonic() - t_start

        logger.info(
            "DAGOrchestrator.run: run_id=%s complete — final_status=%s cycles=%d "
            "promoted=%d conditionals=%d fan_children=%d fan_ins=%d "
            "skipped=%d failed=%d elapsed=%.2fs error=%s",
            run_id,
            result.final_status.value,
            result.cycles_run,
            result.tasks_promoted,
            result.conditionals_taken,
            result.fan_out_children,
            result.fan_ins_aggregated,
            result.tasks_skipped,
            result.tasks_failed,
            result.elapsed_seconds,
            result.error,
        )
        return result
