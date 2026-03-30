# ============================================================================
# CLAUDE CONTEXT - DAG GRAPH UTILITIES
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Pure graph functions for DAG orchestration
# PURPOSE: Zero-DB pure functions for DAG adjacency, reachability, predecessor
#          gating, and terminal-state detection used by DAGOrchestrator
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: TaskSummary, build_adjacency, get_descendants,
#          all_predecessors_terminal, is_run_terminal
# DEPENDENCIES: collections, dataclasses, typing, core.models.workflow_enums,
#               exceptions
# ============================================================================
"""
DAG graph utilities — pure functions, zero database access.

All functions are stateless and operate only on in-memory data structures.
They are designed to be called by DAGOrchestrator after it has fetched
the relevant rows from the database via WorkflowRunRepository.

Spec: D.5 DAG Graph Utilities + Orchestrator Loop — graph functions component.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from util_logger import LoggerFactory, ComponentType

from core.models.workflow_enums import WorkflowTaskStatus, WorkflowRunStatus
from exceptions import ContractViolationError

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, __name__)

# ---------------------------------------------------------------------------
# TERMINAL STATUS SET
# Tasks in these statuses are considered "done" — no further transitions
# are expected from the orchestrator's perspective.
# ---------------------------------------------------------------------------
_TERMINAL_TASK_STATUSES = frozenset({
    WorkflowTaskStatus.COMPLETED,
    WorkflowTaskStatus.FAILED,
    WorkflowTaskStatus.SKIPPED,
    WorkflowTaskStatus.CANCELLED,
    WorkflowTaskStatus.EXPANDED,
    # WAITING intentionally excluded — gate nodes block downstream promotion
})


# ============================================================================
# DATA TRANSFER OBJECT
# ============================================================================

@dataclass(frozen=True)
class TaskSummary:
    """
    Lightweight read-only view of a workflow task used by graph functions.

    Spec: D.5 — TaskSummary DTO. Frozen so it can be safely shared across
    call frames without mutation risk. Maps directly to the columns returned
    by WorkflowRunRepository.get_tasks_for_run().
    """
    task_instance_id: str
    task_name: str
    handler: str                    # Needed by evaluate_conditionals filter
    status: WorkflowTaskStatus
    result_data: Optional[dict]    # None for DB NULL
    fan_out_source: Optional[str]
    fan_out_index: Optional[int]


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

def build_adjacency(
    tasks: list[TaskSummary],
    deps: list[tuple[str, str]],
) -> dict[str, set[str]]:
    """
    Build a task-name-level upstream adjacency map from raw task + dep data.

    Spec: D.5 — build_adjacency. Operates on task_instance_ids (DB PKs) but
    returns a map keyed by task_name for use in orchestrator logic, which
    reasons about node identities rather than instance UUIDs.

    Parameters
    ----------
    tasks:
        List of TaskSummary objects for the run.
    deps:
        List of (task_instance_id, depends_on_instance_id) tuples — the raw
        edge list from WorkflowRunRepository.get_deps_for_run() with the
        optional flag stripped (caller may include it separately).

    Returns
    -------
    dict[str, set[str]]
        Maps each task_name to the set of upstream task_names it depends on.
        All task_names from `tasks` are guaranteed to appear as keys even if
        they have no dependencies (empty set value).

    Raises
    ------
    ContractViolationError
        If a dep edge references a task_instance_id not present in `tasks`.
        This is a programming bug — the caller must not pass partial data.
    """
    # Filter out fan-out children — they share task_name with their template
    # and corrupt name-based lookups. Fan-in handles children directly via
    # fan_out_source, not through the adjacency graph.
    template_tasks = [t for t in tasks if t.fan_out_source is None]

    # Build lookup: instance_id -> task_name (need ALL tasks for dep resolution)
    instance_id_to_name: dict[str, str] = {
        t.task_instance_id: t.task_name for t in tasks
    }

    # Seed adjacency with template tasks only
    adjacency: dict[str, set[str]] = {t.task_name: set() for t in template_tasks}

    for (task_iid, dep_iid) in deps:
        if task_iid not in instance_id_to_name:
            raise ContractViolationError(
                f"build_adjacency: dep references unknown task_instance_id={task_iid!r}. "
                "Caller must pass the complete task list for this run."
            )
        if dep_iid not in instance_id_to_name:
            raise ContractViolationError(
                f"build_adjacency: dep references unknown depends_on_instance_id={dep_iid!r}. "
                "Caller must pass the complete task list for this run."
            )

        task_name = instance_id_to_name[task_iid]
        upstream_name = instance_id_to_name[dep_iid]
        # Skip deps involving fan-out children — their deps are internal
        if task_name in adjacency:
            adjacency[task_name].add(upstream_name)

    return adjacency


# ============================================================================
# REACHABILITY
# ============================================================================

def get_descendants(
    start_name: str,
    adjacency: dict[str, set[str]],
) -> set[str]:
    """
    Return all downstream task names reachable from start_name (exclusive).

    Spec: D.5 — get_descendants. Used by the orchestrator to propagate SKIPPED
    status through conditional branches: when a conditional node is skipped,
    all its descendants are also skipped.

    The `adjacency` map is upstream-oriented (child → set of parents). This
    function inverts it internally to traverse downstream.

    Parameters
    ----------
    start_name:
        The task name to start BFS from (not included in result).
    adjacency:
        Upstream adjacency as returned by build_adjacency.

    Returns
    -------
    set[str]
        All task names reachable downstream from start_name. Empty set if
        start_name has no downstream nodes or is not present in adjacency.
    """
    # Build reverse adjacency: upstream_name -> set of downstream names
    reverse: dict[str, set[str]] = defaultdict(set)
    for task_name, upstreams in adjacency.items():
        for upstream in upstreams:
            reverse[upstream].add(task_name)

    # BFS from start_name
    visited: set[str] = set()
    queue: deque[str] = deque()

    for downstream in reverse.get(start_name, set()):
        if downstream not in visited:
            visited.add(downstream)
            queue.append(downstream)

    while queue:
        current = queue.popleft()
        for downstream in reverse.get(current, set()):
            if downstream not in visited:
                visited.add(downstream)
                queue.append(downstream)

    return visited


# ============================================================================
# PREDECESSOR GATING
# ============================================================================

def all_predecessors_terminal(
    task_name: str,
    adjacency: dict[str, set[str]],
    task_by_name: dict[str, TaskSummary],
    optional_deps: set[str],
) -> bool:
    """
    Return True if every upstream predecessor is in an acceptable terminal state.

    Spec: D.5 — all_predecessors_terminal. Determines whether a PENDING task
    can be promoted to READY. The optional_deps set controls which predecessor
    task_names are allowed to be SKIPPED without blocking the dependent task.

    Acceptance rules per upstream status
    -------------------------------------
    - COMPLETED, EXPANDED, CANCELLED → always OK
    - SKIPPED, FAILED                → terminal; accepted for gating purposes
    - PENDING, READY, RUNNING        → always blocking (return False immediately)

    Note: FAILED is accepted as terminal so that failure propagation can
    cascade through dead branches (e.g., untaken conditional → failed fan-out
    → dependent fan-in should be skipped, not stuck forever). The caller
    (evaluate_transitions) is responsible for deciding whether to skip or
    fail the dependent task based on whether any required predecessor failed.

    Parameters
    ----------
    task_name:
        The task whose readiness we are evaluating.
    adjacency:
        Upstream adjacency map (task_name → set of upstream task_names).
    task_by_name:
        Map of task_name → TaskSummary for status lookup.
    optional_deps:
        Set of upstream task_names that are declared optional for this task.

    Returns
    -------
    bool
        True if all predecessors are in acceptable terminal states.
        False if any predecessor is blocking or in a non-terminal state.
    """
    for upstream_name in adjacency.get(task_name, set()):
        upstream = task_by_name.get(upstream_name)
        if upstream is None:
            # Unknown predecessor — treat as blocking (defensive)
            logger.warning(
                "all_predecessors_terminal: upstream task_name=%r not found in task_by_name "
                "(task=%r) — treating as blocking",
                upstream_name,
                task_name,
            )
            return False

        status = upstream.status

        if status in _TERMINAL_TASK_STATUSES:
            # All terminal states (COMPLETED, FAILED, SKIPPED, CANCELLED,
            # EXPANDED) are accepted for gating. FAILED/SKIPPED don't block
            # — the caller decides how to handle them (skip propagation).
            continue

        # PENDING, READY, RUNNING — still in-flight, block
        logger.debug(
            "all_predecessors_terminal: blocking on upstream=%r status=%r for task=%r",
            upstream_name,
            status.value,
            task_name,
        )
        return False

    return True


# ============================================================================
# RUN TERMINAL DETECTION
# ============================================================================

def is_run_terminal(
    tasks: list[TaskSummary],
) -> tuple[bool, WorkflowRunStatus]:
    """
    Determine whether a workflow run has reached a terminal state.

    Spec: D.5 — is_run_terminal. Called by DAGOrchestrator after every tick
    to decide whether to update the run status and stop polling.

    Terminal outcome rules (evaluated in order)
    -------------------------------------------
    1. If `tasks` is empty → ContractViolationError (programming bug).
    2. If any task is NOT in _TERMINAL_TASK_STATUSES → (False, RUNNING).
    3. If any task is FAILED or CANCELLED → (True, FAILED).
    4. Otherwise all tasks are in acceptable terminal states → (True, COMPLETED).

    Note: CANCELLED causes a FAILED run status. A workflow where any task was
    forcibly cancelled is considered failed from an operational standpoint.

    Parameters
    ----------
    tasks:
        All TaskSummary objects for the run (must be non-empty).

    Returns
    -------
    tuple[bool, WorkflowRunStatus]
        (is_terminal, final_status)

    Raises
    ------
    ContractViolationError
        If `tasks` is empty — this is a caller contract violation.
    """
    if not tasks:
        raise ContractViolationError(
            "is_run_terminal: `tasks` must not be empty. "
            "Caller must pass the complete task list for the run."
        )

    # A run with any WAITING task is suspended at a gate, not terminal
    if any(t.status == WorkflowTaskStatus.WAITING for t in tasks):
        return (False, WorkflowRunStatus.AWAITING_APPROVAL)

    has_failure = False

    for task in tasks:
        if task.status not in _TERMINAL_TASK_STATUSES:
            # At least one task still in flight — run is not terminal
            return (False, WorkflowRunStatus.RUNNING)

        if task.status in (WorkflowTaskStatus.FAILED, WorkflowTaskStatus.CANCELLED):
            has_failure = True

    if has_failure:
        return (True, WorkflowRunStatus.FAILED)

    return (True, WorkflowRunStatus.COMPLETED)
