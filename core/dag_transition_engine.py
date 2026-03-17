# ============================================================================
# CLAUDE CONTEXT - DAG TRANSITION ENGINE
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - PENDING→READY promotions, when-clause evaluation, skip propagation
# PURPOSE: Pure orchestration logic: evaluate every PENDING task each tick and
#          promote, skip, or fail it based on predecessor state and when-clauses.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: TransitionResult, evaluate_transitions
# DEPENDENCIES: dataclasses, logging, typing, core.dag_graph_utils,
#               core.models.workflow_definition, core.models.workflow_enums,
#               core.param_resolver, exceptions
# ============================================================================
"""
DAG Transition Engine — evaluates PENDING task gates each orchestrator tick.

Called once per tick after the orchestrator has fetched the current task +
dep snapshot.  All DB mutations are delegated to WorkflowRunRepository;
this module contains no SQL.

Spec: D.5 DAG Transition Engine component.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from core.dag_graph_utils import (
    TaskSummary,
    build_adjacency,
    all_predecessors_terminal,
    get_descendants,
)
from core.models.workflow_definition import TaskNode, WorkflowDefinition
from core.models.workflow_enums import WorkflowTaskStatus
from core.param_resolver import (
    ParameterResolutionError,
    resolve_dotted_path,
    resolve_task_params,
)
from exceptions import ContractViolationError

logger = logging.getLogger(__name__)


# ============================================================================
# RESULT DTO
# ============================================================================


@dataclass
class TransitionResult:
    """
    Summary of all transitions performed in a single evaluate_transitions call.

    Spec: D.5 — TransitionResult DTO. Immutable after construction; callers
    should not mutate the lists after receiving the result.
    """
    promoted: list[str] = field(default_factory=list)   # task_instance_ids promoted PENDING→READY
    skipped: list[str] = field(default_factory=list)    # task_instance_ids skipped (when=False or propagated)
    failed: list[str] = field(default_factory=list)     # task_instance_ids failed (param resolution error)


# ============================================================================
# PRIVATE HELPERS
# ============================================================================


def _evaluate_when_clause(
    expr: str,
    predecessor_outputs: dict[str, dict],
    job_params: dict,
) -> Any:
    """
    Resolve a when-clause expression against predecessor outputs.

    Spec: D.5 — when-clause evaluation.  The expression is a dotted path
    (e.g. ``validate.passed``) resolved via resolve_dotted_path.  job_params
    is provided for completeness but when-clauses conventionally reference
    predecessor output keys, not raw job parameters.

    Parameters
    ----------
    expr:
        Dotted-path expression string from TaskNode.when.
    predecessor_outputs:
        Map of task_name → result_data for completed predecessors.
    job_params:
        Top-level job parameters (available for future extension).

    Returns
    -------
    Any
        The resolved value.  Callers cast to bool().

    Raises
    ------
    ParameterResolutionError
        If the path cannot be resolved (predecessor not yet complete, missing key).
    """
    return resolve_dotted_path(expr, predecessor_outputs)


def _skip_task_and_descendants(
    task: TaskSummary,
    all_tasks: list[TaskSummary],
    adjacency: dict[str, set[str]],
    repo,
    result: TransitionResult,
) -> None:
    """
    Skip `task` and propagate SKIPPED to all downstream descendants.

    Spec: D.5 — skip propagation.  Calls repo.skip_task for `task` itself
    first, then collects all descendant task names via get_descendants and
    skips their corresponding task instances.

    Only PENDING/READY tasks are skipped — skip_task is a guarded UPDATE that
    silently ignores tasks already in non-skippable states (RUNNING, COMPLETED,
    etc.), so over-calling is safe.

    Parameters
    ----------
    task:
        The root task to skip.
    all_tasks:
        Full task list for the run.
    adjacency:
        Upstream adjacency map (task_name → set of upstream task_names).
    repo:
        WorkflowRunRepository instance for DB mutations.
    result:
        TransitionResult to append skipped IDs into.
    """
    # Build name → instance lookup for downstream propagation
    task_by_name: dict[str, TaskSummary] = {t.task_name: t for t in all_tasks}

    # Skip the root task
    skipped = repo.skip_task(task.task_instance_id)
    if skipped:
        result.skipped.append(task.task_instance_id)
        logger.info(
            "_skip_task_and_descendants: skipped root task_instance_id=%s task_name=%r",
            task.task_instance_id,
            task.task_name,
        )
    else:
        logger.debug(
            "_skip_task_and_descendants: skip_task guard rejected for task_instance_id=%s "
            "(already in non-skippable state)",
            task.task_instance_id,
        )

    # Propagate to all descendants
    descendant_names = get_descendants(task.task_name, adjacency)
    for desc_name in descendant_names:
        desc_task = task_by_name.get(desc_name)
        if desc_task is None:
            logger.warning(
                "_skip_task_and_descendants: descendant task_name=%r not found in task list "
                "(run may have partial data) — skipping propagation for this node",
                desc_name,
            )
            continue
        skipped = repo.skip_task(desc_task.task_instance_id)
        if skipped:
            result.skipped.append(desc_task.task_instance_id)
            logger.info(
                "_skip_task_and_descendants: propagated skip to descendant "
                "task_instance_id=%s task_name=%r",
                desc_task.task_instance_id,
                desc_name,
            )


def _build_optional_deps(
    tasks: list[TaskSummary],
    deps: list[tuple[str, str, bool]],
    id_to_name: dict[str, str],
) -> dict[str, set[str]]:
    """
    Build a per-task set of optional upstream task_names.

    Spec: D.5 — optional dependency resolution.  The `deps` list contains the
    raw (task_instance_id, depends_on_instance_id, optional) rows from the DB.
    This helper projects them to the task_name level used by all_predecessors_terminal.

    Parameters
    ----------
    tasks:
        All tasks for the run (used to seed the result dict).
    deps:
        Raw dep edges with the optional flag included.
    id_to_name:
        Map of task_instance_id → task_name for projection.

    Returns
    -------
    dict[str, set[str]]
        Maps each task_name to the set of upstream task_names that are optional.
        Every task_name present in `tasks` is guaranteed to appear as a key.
    """
    # Seed all task names with empty sets
    optional_map: dict[str, set[str]] = {t.task_name: set() for t in tasks}

    for (task_iid, dep_iid, is_optional) in deps:
        if not is_optional:
            continue
        task_name = id_to_name.get(task_iid)
        dep_name = id_to_name.get(dep_iid)
        if task_name is None or dep_name is None:
            # Defensive: unknown IDs — ignore rather than raise (build_adjacency
            # will have already caught structural issues with the same IDs).
            logger.debug(
                "_build_optional_deps: skipping unknown IDs task_iid=%r dep_iid=%r",
                task_iid,
                dep_iid,
            )
            continue
        optional_map[task_name].add(dep_name)

    return optional_map


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================


def evaluate_transitions(
    run_id: str,
    workflow_def: WorkflowDefinition,
    tasks: list[TaskSummary],
    deps: list[tuple[str, str, bool]],
    predecessor_outputs: dict[str, dict],
    job_params: dict,
    repo,
) -> TransitionResult:
    """
    Evaluate all PENDING tasks and promote, skip, or fail each as appropriate.

    Spec: D.5 — evaluate_transitions algorithm (exact).  This is the central
    per-tick gate evaluation function called by DAGOrchestrator.  It is
    idempotent: re-running on the same snapshot produces the same result
    because all DB mutations are guarded CAS operations.

    Algorithm
    ---------
    1. Build adjacency from deps (strip optional bool, call build_adjacency).
    2. Build task_by_name, id_to_name, optional_deps per task.
    3. Filter to PENDING tasks only.
    4. For each PENDING task:
       a. Look up node_def in workflow_def.nodes[task.task_name].
       b. all_predecessors_terminal — if False, skip (stay PENDING, log DEBUG).
       c. If TaskNode with when_clause: resolve via _evaluate_when_clause.
          - ParameterResolutionError → stay PENDING (predecessor output not yet ready).
          - bool(resolved) is False → skip_task + propagate skip to descendants.
       d. If TaskNode: resolve_task_params → ParameterResolutionError → fail_task.
          On success: set_task_parameters before promoting.
       e. promote_task(PENDING → READY) for ALL node types.
    5. Return TransitionResult.

    Parameters
    ----------
    run_id:
        The workflow run primary key (used for logging context only).
    workflow_def:
        The parsed WorkflowDefinition for the run.
    tasks:
        All TaskSummary rows for the run fetched this tick.
    deps:
        All dep edges as (task_instance_id, depends_on_instance_id, optional) triples.
    predecessor_outputs:
        Map of task_name → result_data for completed/expanded predecessors,
        pre-fetched by the orchestrator.
    job_params:
        Top-level job parameters for the run.
    repo:
        WorkflowRunRepository instance for all DB mutations.

    Returns
    -------
    TransitionResult
        Lists of task_instance_ids promoted, skipped, and failed this tick.

    Raises
    ------
    ContractViolationError
        If a task_name in `tasks` is absent from workflow_def.nodes — indicates
        a DB/definition mismatch that must be fixed in the code or data.
    """
    result = TransitionResult()

    if not tasks:
        logger.debug("evaluate_transitions: run_id=%s no tasks — nothing to do", run_id)
        return result

    # ------------------------------------------------------------------
    # Step 1: Build adjacency (strips optional bool from dep tuples)
    # ------------------------------------------------------------------
    raw_deps_for_adjacency: list[tuple[str, str]] = [
        (task_iid, dep_iid) for (task_iid, dep_iid, _optional) in deps
    ]
    adjacency = build_adjacency(tasks, raw_deps_for_adjacency)

    # ------------------------------------------------------------------
    # Step 2: Build supporting lookup structures
    # ------------------------------------------------------------------
    task_by_name: dict[str, TaskSummary] = {t.task_name: t for t in tasks}
    id_to_name: dict[str, str] = {t.task_instance_id: t.task_name for t in tasks}
    optional_deps_by_task = _build_optional_deps(tasks, deps, id_to_name)

    # ------------------------------------------------------------------
    # Step 3: Filter to PENDING tasks
    # ------------------------------------------------------------------
    pending_tasks = [t for t in tasks if t.status == WorkflowTaskStatus.PENDING]

    logger.debug(
        "evaluate_transitions: run_id=%s total_tasks=%d pending=%d",
        run_id, len(tasks), len(pending_tasks),
    )

    # ------------------------------------------------------------------
    # Step 4: Evaluate each PENDING task
    # ------------------------------------------------------------------
    for task in pending_tasks:

        # 4a: Look up node definition — ContractViolationError if absent
        node_def = workflow_def.nodes.get(task.task_name)
        if node_def is None:
            raise ContractViolationError(
                f"evaluate_transitions: task_name={task.task_name!r} not found in "
                f"workflow_def.nodes for run_id={run_id}. "
                "This is a DB/definition mismatch — fix the data or code."
            )

        # 4b: Predecessor gate — if any upstream is not terminal, stay PENDING
        optional_for_task = optional_deps_by_task.get(task.task_name, set())
        if not all_predecessors_terminal(task.task_name, adjacency, task_by_name, optional_for_task):
            logger.debug(
                "evaluate_transitions: run_id=%s task_name=%r blocked — predecessors not terminal",
                run_id, task.task_name,
            )
            continue

        # 4c: when-clause evaluation (TaskNode only)
        if isinstance(node_def, TaskNode) and node_def.when is not None:
            try:
                when_value = _evaluate_when_clause(
                    node_def.when, predecessor_outputs, job_params
                )
            except ParameterResolutionError as exc:
                # Predecessor output not yet available — stay PENDING, retry next tick
                logger.debug(
                    "evaluate_transitions: run_id=%s task_name=%r when-clause unresolvable "
                    "(predecessor not ready): %s",
                    run_id, task.task_name, exc,
                )
                continue

            if not bool(when_value):
                # when-clause is False — skip this task and all its descendants
                logger.info(
                    "evaluate_transitions: run_id=%s task_name=%r when=%r → False — skipping",
                    run_id, task.task_name, node_def.when,
                )
                _skip_task_and_descendants(task, tasks, adjacency, repo, result)
                continue

        # 4d: Parameter resolution (TaskNode only) — fail on error, set params on success
        if isinstance(node_def, TaskNode):
            try:
                resolved_params = resolve_task_params(node_def, job_params, predecessor_outputs)
            except ParameterResolutionError as exc:
                logger.error(
                    "evaluate_transitions: run_id=%s task_name=%r param resolution failed: %s",
                    run_id, task.task_name, exc,
                )
                repo.fail_task(
                    task.task_instance_id,
                    f"Parameter resolution failed: {exc}",
                )
                result.failed.append(task.task_instance_id)
                continue

            # 4d+e: Atomically set params and promote PENDING → READY
            promoted = repo.set_params_and_promote(
                task.task_instance_id,
                resolved_params,
                WorkflowTaskStatus.PENDING,
                WorkflowTaskStatus.READY,
            )
        else:
            # 4e: Non-TaskNode (conditional, fan-out, fan-in) — no params to set
            promoted = repo.promote_task(
                task.task_instance_id,
                WorkflowTaskStatus.PENDING,
                WorkflowTaskStatus.READY,
            )

        if promoted:
            result.promoted.append(task.task_instance_id)
            logger.info(
                "evaluate_transitions: run_id=%s task_name=%r promoted PENDING→READY",
                run_id, task.task_name,
            )
        else:
            logger.debug(
                "evaluate_transitions: run_id=%s task_name=%r promote_task guard rejected "
                "(already transitioned by concurrent tick)",
                run_id, task.task_name,
            )

    logger.info(
        "evaluate_transitions: run_id=%s promoted=%d skipped=%d failed=%d",
        run_id, len(result.promoted), len(result.skipped), len(result.failed),
    )
    return result
