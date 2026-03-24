# ============================================================================
# CLAUDE CONTEXT - DAG FAN ENGINE
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Fan-out expansion, fan-in aggregation, conditional branch routing
# PURPOSE: Evaluate READY conditional nodes, expand fan-out templates into child
#          instances, and aggregate completed fan-out children into fan-in results.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: ConditionalResult, FanOutResult, FanInResult,
#          evaluate_conditionals, expand_fan_outs, aggregate_fan_ins
# DEPENDENCIES: dataclasses, logging, uuid, typing, core.dag_graph_utils,
#               core.models.workflow_definition, core.models.workflow_enums,
#               core.param_resolver, exceptions
# ============================================================================
"""
DAG Fan Engine — conditional branching, fan-out expansion, fan-in aggregation.

Called each orchestrator tick after evaluate_transitions.  All DB mutations
are delegated to WorkflowRunRepository; this module contains no SQL.

Spec: D.5 DAG Fan Engine component.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.dag_graph_utils import TaskSummary, build_adjacency, get_descendants
from core.models.workflow_definition import (
    BranchDef,
    ConditionalNode,
    FanInNode,
    FanOutNode,
    WorkflowDefinition,
)
from core.models.workflow_enums import AggregationMode, WorkflowTaskStatus
from core.param_resolver import (
    ParameterResolutionError,
    resolve_dotted_path,
    resolve_fan_out_params,
)
from exceptions import ContractViolationError

logger = logging.getLogger(__name__)

# Maximum index offset guard to prevent absurd fan-out counts; actual limit is
# enforced per FanOutNode.max_fan_out, this is a hard system ceiling.
_SYSTEM_MAX_FAN_OUT = 10_000

# Sentinel handler names — must not collide with real handlers (see dag_initializer.py)
_HANDLER_CONDITIONAL = "__conditional__"
_HANDLER_FAN_OUT = "__fan_out__"
_HANDLER_FAN_IN = "__fan_in__"

# Operators supported in branch condition strings
# Spec: D.5 — _eval_branch_condition, 14 operators
_TRUTHY_OPERATORS = {"truthy", "is_true", "not_empty"}
_FALSY_OPERATORS = {"falsy", "is_false", "is_empty"}
_COMPARISON_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte"}
_MEMBERSHIP_OPERATORS = {"in", "not_in", "contains", "not_contains"}
_ALL_OPERATORS = (
    _TRUTHY_OPERATORS | _FALSY_OPERATORS | _COMPARISON_OPERATORS | _MEMBERSHIP_OPERATORS
)


# ============================================================================
# RESULT DTOs
# ============================================================================


@dataclass
class ConditionalResult:
    """Summary of all conditional evaluations performed in a single tick."""
    taken: list[str] = field(default_factory=list)    # task_instance_ids of conditionals completed
    skipped: list[str] = field(default_factory=list)  # task_instance_ids skipped (untaken branch targets + descendants)
    failed: list[str] = field(default_factory=list)   # task_instance_ids of conditionals that failed


@dataclass
class FanOutResult:
    """Summary of fan-out expansions performed in a single tick."""
    expanded: list[str] = field(default_factory=list)     # template task_instance_ids expanded
    children_created: int = 0                              # total child instances created across all expansions


@dataclass
class FanInResult:
    """Summary of fan-in aggregations performed in a single tick."""
    aggregated: list[str] = field(default_factory=list)  # fan-in task_instance_ids aggregated → COMPLETED
    failed: list[str] = field(default_factory=list)      # fan-in task_instance_ids failed (child failures)


# ============================================================================
# PRIVATE HELPERS
# ============================================================================


def _eval_branch_condition(condition: str, value: Any) -> bool:
    """
    Evaluate a single branch condition string against a resolved value.

    Spec: D.5 — _eval_branch_condition, 14 operators.
    Format: "operator [operand]" — operator and optional operand separated by a space.

    Supported operators
    -------------------
    Unary (no operand):
        truthy / is_true / not_empty    — bool(value) is True
        falsy / is_false / is_empty     — bool(value) is False

    Binary (operand follows operator):
        eq / ne / lt / lte / gt / gte   — numeric or string comparison
        in / not_in                     — value in/not-in list operand (JSON)
        contains / not_contains         — operand in/not-in value (string or list)

    Parameters
    ----------
    condition:
        Condition string (e.g. ``"eq 42"``, ``"truthy"``, ``"in [1,2,3]"``).
    value:
        The resolved predecessor output value to test.

    Returns
    -------
    bool

    Raises
    ------
    ContractViolationError
        If the operator is unknown — indicates a bad workflow YAML that passed
        schema validation but contains an unsupported operator.
    """
    parts = condition.strip().split(None, 1)  # split on first whitespace only
    operator = parts[0].lower()
    operand_str = parts[1] if len(parts) > 1 else None

    if operator not in _ALL_OPERATORS:
        raise ContractViolationError(
            f"_eval_branch_condition: unknown operator '{operator}'. "
            f"Supported operators: {sorted(_ALL_OPERATORS)}. "
            "Fix the workflow YAML branch condition."
        )

    # --- Unary operators ---
    if operator in _TRUTHY_OPERATORS:
        return bool(value)

    if operator in _FALSY_OPERATORS:
        return not bool(value)

    # --- Binary operators — operand is required ---
    if operand_str is None:
        raise ContractViolationError(
            f"_eval_branch_condition: operator '{operator}' requires an operand "
            "but none was provided. Fix the workflow YAML branch condition."
        )

    # Parse operand — try JSON first (handles numbers, lists, booleans, null)
    try:
        operand = json.loads(operand_str)
    except (json.JSONDecodeError, ValueError):
        # Fall back to raw string
        operand = operand_str

    if operator == "eq":
        return value == operand
    if operator == "ne":
        return value != operand
    if operator in ("lt", "lte", "gt", "gte"):
        try:
            if operator == "lt":
                return value < operand
            if operator == "lte":
                return value <= operand
            if operator == "gt":
                return value > operand
            return value >= operand  # gte
        except TypeError:
            # C10 fix: cross-type comparison (e.g., str < int) → False, not crash
            logger.warning(
                "_eval_branch_condition: type mismatch for '%s': value=%r (%s) operand=%r (%s)",
                operator, value, type(value).__name__, operand, type(operand).__name__,
            )
            return False
    if operator in ("in", "not_in", "contains", "not_contains"):
        try:
            if operator == "in":
                return value in operand
            if operator == "not_in":
                return value not in operand
            if operator == "contains":
                return operand in value
            return operand not in value  # not_contains
        except TypeError:
            logger.warning(
                "_eval_branch_condition: type mismatch for '%s': value=%r (%s) operand=%r (%s)",
                operator, value, type(value).__name__, operand, type(operand).__name__,
            )
            return False

    # Should never reach here — covered by the unknown-operator guard above
    raise ContractViolationError(
        f"_eval_branch_condition: unhandled operator '{operator}' — programming bug."
    )



# ============================================================================
# evaluate_conditionals
# ============================================================================


def evaluate_conditionals(
    run_id: str,
    workflow_def: WorkflowDefinition,
    tasks: list[TaskSummary],
    deps: list[tuple[str, str, bool]],
    predecessor_outputs: dict[str, dict],
    job_params: dict,
    repo,
) -> ConditionalResult:
    """
    Evaluate READY ConditionalNode tasks and route branches.

    Spec: D.5 — evaluate_conditionals.

    Algorithm
    ---------
    For each READY task whose handler is ``__conditional__``:
      1. Resolve the condition path via resolve_dotted_path.
      2. Evaluate non-default branches first (in declaration order), then the
         default branch last.
      3. Taken branch: promote conditional task READY→COMPLETED; promote each
         branch.next target task if it is PENDING (already handled by transition
         engine for the next tick — conditional task is marked COMPLETED here so
         the transition engine will gate them on COMPLETED status).
      4. Untaken branches: skip_task for each branch.next target + descendants.
      5. No branch matches and no default → ContractViolationError (schema
         should enforce at least one default but guard here defensively).

    Parameters
    ----------
    run_id:
        The workflow run primary key (logging context only).
    workflow_def:
        Parsed WorkflowDefinition for the run.
    tasks:
        All TaskSummary rows for the run fetched this tick.
    deps:
        All dep edges for this run.
    predecessor_outputs:
        Map of task_name → result_data for completed predecessors.
    job_params:
        Top-level job parameters.
    repo:
        WorkflowRunRepository instance.

    Returns
    -------
    ConditionalResult
    """
    result = ConditionalResult()
    task_by_name: dict[str, TaskSummary] = {t.task_name: t for t in tasks}
    raw_deps = [(task_iid, dep_iid) for (task_iid, dep_iid, _opt) in deps]
    adjacency = build_adjacency(tasks, raw_deps)

    ready_conditionals = [
        t for t in tasks
        if t.status == WorkflowTaskStatus.READY and t.handler == _HANDLER_CONDITIONAL
    ]

    logger.debug(
        "evaluate_conditionals: run_id=%s ready_conditionals=%d",
        run_id, len(ready_conditionals),
    )

    for task in ready_conditionals:
        node_def = workflow_def.nodes.get(task.task_name)
        if not isinstance(node_def, ConditionalNode):
            raise ContractViolationError(
                f"evaluate_conditionals: task_name={task.task_name!r} has handler "
                f"'{_HANDLER_CONDITIONAL}' but workflow_def node is not a ConditionalNode "
                f"(got {type(node_def).__name__}). DB/definition mismatch."
            )

        # Step 1: Resolve condition value
        # Support "params.X.Y" prefix for job parameter references (same as when-clause)
        try:
            if node_def.condition.startswith("params."):
                segments = node_def.condition.split(".")
                current = job_params
                for seg in segments[1:]:
                    if isinstance(current, dict) and seg in current:
                        current = current[seg]
                    else:
                        current = None
                        break
                condition_value = current
            else:
                condition_value = resolve_dotted_path(node_def.condition, predecessor_outputs)
        except ParameterResolutionError as exc:
            logger.error(
                "evaluate_conditionals: run_id=%s task_name=%r condition resolution failed: %s",
                run_id, task.task_name, exc,
            )
            repo.fail_task(
                task.task_instance_id,
                f"Condition resolution failed: {exc}",
            )
            result.failed.append(task.task_instance_id)
            continue

        # Step 2: Evaluate branches — non-default first, default last
        non_default = [b for b in node_def.branches if not b.default]
        default_branches = [b for b in node_def.branches if b.default]

        taken_branch: BranchDef | None = None
        for branch in non_default:
            if branch.condition is None:
                continue
            try:
                if _eval_branch_condition(branch.condition, condition_value):
                    taken_branch = branch
                    break
            except ContractViolationError:
                raise  # Programming bug — propagate immediately

        if taken_branch is None and default_branches:
            taken_branch = default_branches[0]

        if taken_branch is None:
            raise ContractViolationError(
                f"evaluate_conditionals: run_id={run_id} task_name={task.task_name!r} — "
                f"no branch matched condition value={condition_value!r} and no default branch "
                "was defined. Fix the workflow YAML to include a default branch."
            )

        logger.info(
            "evaluate_conditionals: run_id=%s task_name=%r condition_value=%r taken_branch=%r",
            run_id, task.task_name, condition_value, taken_branch.name,
        )

        # Step 3: Mark taken branch targets — transition engine will gate them on
        # the conditional being COMPLETED; just mark the conditional COMPLETED now.
        # Step 4: Skip untaken branch targets + descendants
        # C5 fix: subtract taken branch targets to avoid skipping shared targets
        taken_target_names: set[str] = set(taken_branch.next)
        untaken_target_names: set[str] = set()
        for branch in node_def.branches:
            if branch is not taken_branch:
                untaken_target_names.update(branch.next)
        untaken_target_names -= taken_target_names  # shared targets stay active

        for target_name in untaken_target_names:
            target_task = task_by_name.get(target_name)
            if target_task is None:
                logger.warning(
                    "evaluate_conditionals: run_id=%s untaken branch target_name=%r "
                    "not found in task list — skipping propagation",
                    run_id, target_name,
                )
                continue
            # Skip target itself — do NOT propagate to descendants.
            # Descendants with optional deps on the skipped target should
            # proceed normally via the transition engine's predecessor gate.
            # (Same fix as _skip_task_and_descendants in transition engine.)
            skipped = repo.skip_task(target_task.task_instance_id)
            if skipped:
                result.skipped.append(target_task.task_instance_id)
            # Descendant propagation disabled — transition engine handles it
            _disabled_descendants = []  # was: get_descendants(target_name, adjacency)
            for desc_name in _disabled_descendants:
                desc_task = task_by_name.get(desc_name)
                if desc_task is None:
                    continue
                skipped = repo.skip_task(desc_task.task_instance_id)
                if skipped:
                    result.skipped.append(desc_task.task_instance_id)

        # Promote conditional task READY → COMPLETED
        promoted = repo.promote_task(
            task.task_instance_id,
            WorkflowTaskStatus.READY,
            WorkflowTaskStatus.COMPLETED,
        )
        if promoted:
            result.taken.append(task.task_instance_id)
            logger.info(
                "evaluate_conditionals: run_id=%s task_name=%r → COMPLETED "
                "taken=%r skipped_targets=%d",
                run_id, task.task_name, taken_branch.name, len(untaken_target_names),
            )

    return result


# ============================================================================
# expand_fan_outs
# ============================================================================


def expand_fan_outs(
    run_id: str,
    workflow_def: WorkflowDefinition,
    tasks: list[TaskSummary],
    deps: list[tuple[str, str, bool]],
    predecessor_outputs: dict[str, dict],
    job_params: dict,
    repo,
) -> FanOutResult:
    """
    Expand READY fan-out template tasks into N child instances.

    Spec: D.5 — expand_fan_outs.

    Algorithm
    ---------
    For each READY FanOutNode task where fan_out_source is None (template only):
      1. Resolve source array via resolve_dotted_path.
      2. Not a list → fail_task.
         len > max_fan_out → ContractViolationError.
         Empty list → expand with 0 children (template → EXPANDED immediately).
      3. Build N child tuples: uuid4 task_instance_id, same task_name, handler
         from node.task.handler, fan_out_index = i, fan_out_source = template_id,
         status = READY, parameters from resolve_fan_out_params.
      4. Build dep edges for fan-in nodes that depend on this fan-out template.
      5. Call repo.expand_fan_out(template_id, children_tuples, dep_tuples).

    Parameters
    ----------
    run_id:
        The workflow run primary key.
    workflow_def:
        Parsed WorkflowDefinition for the run.
    tasks:
        All TaskSummary rows for the run.
    deps:
        All dep edges for this run (task_instance_id, dep_iid, optional).
    predecessor_outputs:
        Map of task_name → result_data for completed predecessors.
    job_params:
        Top-level job parameters.
    repo:
        WorkflowRunRepository instance.

    Returns
    -------
    FanOutResult
    """
    result = FanOutResult()
    now = datetime.now(timezone.utc)

    # Find READY fan-out templates: status=READY, fan_out_source is None
    ready_fan_outs = [
        t for t in tasks
        if t.status == WorkflowTaskStatus.READY and t.fan_out_source is None
        and isinstance(workflow_def.nodes.get(t.task_name), FanOutNode)
    ]

    logger.debug(
        "expand_fan_outs: run_id=%s ready_fan_out_templates=%d",
        run_id, len(ready_fan_outs),
    )

    # Build: template_instance_id → set of fan-in task_instance_ids that depend on it
    id_to_task: dict[str, TaskSummary] = {t.task_instance_id: t for t in tasks}
    name_to_task: dict[str, TaskSummary] = {t.task_name: t for t in tasks}

    for template_task in ready_fan_outs:
        node_def = workflow_def.nodes.get(template_task.task_name)
        if not isinstance(node_def, FanOutNode):
            # Should not happen — filter above already checks; guard defensively
            raise ContractViolationError(
                f"expand_fan_outs: task_name={template_task.task_name!r} expected FanOutNode "
                f"but got {type(node_def).__name__}. DB/definition mismatch."
            )

        # Step 1: Resolve source array
        try:
            source_value = resolve_dotted_path(node_def.source, predecessor_outputs)
        except ParameterResolutionError as exc:
            logger.error(
                "expand_fan_outs: run_id=%s task_name=%r source resolution failed: %s",
                run_id, template_task.task_name, exc,
            )
            repo.fail_task(
                template_task.task_instance_id,
                f"Fan-out source resolution failed: {exc}",
            )
            continue

        # Step 2: Validate type and length
        if not isinstance(source_value, list):
            repo.fail_task(
                template_task.task_instance_id,
                f"Fan-out source '{node_def.source}' resolved to {type(source_value).__name__}, "
                "expected list.",
            )
            logger.error(
                "expand_fan_outs: run_id=%s task_name=%r source not a list (got %s) — failing",
                run_id, template_task.task_name, type(source_value).__name__,
            )
            continue

        if len(source_value) > node_def.max_fan_out:
            raise ContractViolationError(
                f"expand_fan_outs: run_id={run_id} task_name={template_task.task_name!r} — "
                f"source list length {len(source_value)} exceeds max_fan_out={node_def.max_fan_out}. "
                "Either reduce the source list or increase max_fan_out in the workflow YAML."
            )

        # Step 3: Build child task tuples
        child_tuples = []
        for index, item in enumerate(source_value):
            child_id = str(uuid4())
            try:
                params = resolve_fan_out_params(
                    node_def.task, item, index, job_params, predecessor_outputs
                )
            except ParameterResolutionError as exc:
                logger.error(
                    "expand_fan_outs: run_id=%s task_name=%r index=%d param resolution failed: %s",
                    run_id, template_task.task_name, index, exc,
                )
                repo.fail_task(
                    template_task.task_instance_id,
                    f"Fan-out param resolution failed at index {index}: {exc}",
                )
                break  # stop building children for this template
            else:
                # Match 20-column order from workflow_run_repository._task_to_params
                max_retries = node_def.task.retry.max_attempts if node_def.task.retry else 3
                child_tuples.append((
                    child_id,                              # task_instance_id
                    run_id,                                # run_id
                    template_task.task_name,               # task_name (same name, different index)
                    node_def.task.handler,                 # handler
                    WorkflowTaskStatus.READY.value,        # status
                    index,                                 # fan_out_index
                    template_task.task_instance_id,        # fan_out_source
                    None,                                  # when_clause
                    json.dumps(params),                    # parameters (JSONB)
                    None,                                  # result_data
                    None,                                  # error_details
                    0,                                     # retry_count
                    max_retries,                           # max_retries
                    None,                                  # claimed_by
                    None,                                  # last_pulse
                    None,                                  # execute_after
                    None,                                  # started_at
                    None,                                  # completed_at
                    now,                                   # created_at
                    now,                                   # updated_at
                ))
        else:
            # Only reached if the for-loop completed without break (no errors)

            # Step 4: Build dep edges for fan-in nodes that depend on this template
            dep_tuples: list[tuple[str, str, bool]] = []
            # Find fan-in tasks that have a dep on this template
            fan_in_task_iids = [
                task_iid for (task_iid, dep_iid, _opt) in deps
                if dep_iid == template_task.task_instance_id
                and task_iid in id_to_task  # C2 fix: guard against unknown task_iid
                and isinstance(workflow_def.nodes.get(id_to_task[task_iid].task_name), FanInNode)
            ]

            for child_tuple in child_tuples:
                child_id = child_tuple[0]
                # Each fan-in that depended on the template now also depends on each child
                for fi_iid in fan_in_task_iids:
                    dep_tuples.append((fi_iid, child_id, False))

            # Step 5: Atomically expand
            expanded = repo.expand_fan_out(
                template_task.task_instance_id,
                child_tuples,
                dep_tuples,
            )
            if expanded:
                result.expanded.append(template_task.task_instance_id)
                result.children_created += len(child_tuples)
                logger.info(
                    "expand_fan_outs: run_id=%s task_name=%r template_id=%s children=%d",
                    run_id, template_task.task_name,
                    template_task.task_instance_id, len(child_tuples),
                )
            else:
                logger.debug(
                    "expand_fan_outs: run_id=%s task_name=%r already expanded (idempotent)",
                    run_id, template_task.task_name,
                )

    return result


# ============================================================================
# aggregate_fan_ins
# ============================================================================


def aggregate_fan_ins(
    run_id: str,
    workflow_def: WorkflowDefinition,
    tasks: list[TaskSummary],
    deps: list[tuple[str, str, bool]],
    repo,
) -> FanInResult:
    """
    Aggregate completed fan-out children into fan-in task result data.

    Spec: D.5 — aggregate_fan_ins.

    Algorithm
    ---------
    For each PENDING FanInNode task:
      1. Find the fan-out template task from depends_on (by matching a task whose
         node definition is a FanOutNode).
      2. Find all child instances by fan_out_source == template.task_instance_id.
      3. Check template is EXPANDED and all children are terminal.
      4. Any FAILED child → fail_task(fan_in).
      5. Aggregate child result_data by AggregationMode:
         - COLLECT  → {"items": [result_data, ...]} (index-ordered)
         - CONCAT   → merge all dicts (last writer wins on collision)
         - SUM      → {"total": sum(result_data["value"] for each child)}
         - FIRST    → first child's result_data
         - LAST     → last child's result_data
      6. Call repo.aggregate_fan_in(fan_in_id, aggregated_result).

    Parameters
    ----------
    run_id:
        The workflow run primary key (logging context only).
    workflow_def:
        Parsed WorkflowDefinition for the run.
    tasks:
        All TaskSummary rows for the run.
    deps:
        All dep edges for this run.
    repo:
        WorkflowRunRepository instance.

    Returns
    -------
    FanInResult
    """
    result = FanInResult()

    name_to_task: dict[str, TaskSummary] = {t.task_name: t for t in tasks}
    id_to_task: dict[str, TaskSummary] = {t.task_instance_id: t for t in tasks}

    # Find READY fan-in tasks (transition engine promotes PENDING→READY when
    # all predecessors are terminal; we process them here, not via the worker)
    pending_fan_ins = [
        t for t in tasks
        if t.status in (WorkflowTaskStatus.PENDING, WorkflowTaskStatus.READY)
        and isinstance(workflow_def.nodes.get(t.task_name), FanInNode)
    ]

    logger.debug(
        "aggregate_fan_ins: run_id=%s pending_fan_ins=%d",
        run_id, len(pending_fan_ins),
    )

    for fan_in_task in pending_fan_ins:
        node_def = workflow_def.nodes.get(fan_in_task.task_name)
        if not isinstance(node_def, FanInNode):
            raise ContractViolationError(
                f"aggregate_fan_ins: task_name={fan_in_task.task_name!r} expected FanInNode "
                f"but got {type(node_def).__name__}. DB/definition mismatch."
            )

        # Step 1: Locate the fan-out template from deps
        upstream_ids = [
            dep_iid for (task_iid, dep_iid, _opt) in deps
            if task_iid == fan_in_task.task_instance_id
        ]
        template_task: TaskSummary | None = None
        for up_id in upstream_ids:
            upstream = id_to_task.get(up_id)
            if upstream and isinstance(workflow_def.nodes.get(upstream.task_name), FanOutNode):
                template_task = upstream
                break

        if template_task is None:
            logger.debug(
                "aggregate_fan_ins: run_id=%s task_name=%r no fan-out template dep found — "
                "skipping (waiting for expansion)",
                run_id, fan_in_task.task_name,
            )
            continue

        # Step 2: Find child instances
        children = [
            t for t in tasks
            if t.fan_out_source == template_task.task_instance_id
        ]

        # Step 3: Check template EXPANDED and all children terminal
        _TERMINAL = frozenset({
            WorkflowTaskStatus.COMPLETED,
            WorkflowTaskStatus.FAILED,
            WorkflowTaskStatus.SKIPPED,
            WorkflowTaskStatus.CANCELLED,
        })

        if template_task.status != WorkflowTaskStatus.EXPANDED:
            logger.debug(
                "aggregate_fan_ins: run_id=%s task_name=%r template_status=%s — not EXPANDED yet",
                run_id, fan_in_task.task_name, template_task.status.value,
            )
            continue

        if not all(c.status in _TERMINAL for c in children):
            logger.debug(
                "aggregate_fan_ins: run_id=%s task_name=%r %d/%d children terminal — waiting",
                run_id, fan_in_task.task_name,
                sum(1 for c in children if c.status in _TERMINAL),
                len(children),
            )
            continue

        # Step 4: Fail fan-in if any child failed
        failed_children = [c for c in children if c.status == WorkflowTaskStatus.FAILED]
        if failed_children:
            error_msg = (
                f"Fan-in aggregation failed: {len(failed_children)} of {len(children)} "
                f"children FAILED: {[c.task_instance_id for c in failed_children[:5]]}"
            )
            repo.fail_task(fan_in_task.task_instance_id, error_msg)
            result.failed.append(fan_in_task.task_instance_id)
            logger.error(
                "aggregate_fan_ins: run_id=%s task_name=%r %d failed children — failing fan-in",
                run_id, fan_in_task.task_name, len(failed_children),
            )
            continue

        # Step 5: Aggregate by mode
        # Sort children by fan_out_index for deterministic ordering
        ordered_children = sorted(children, key=lambda c: (c.fan_out_index or 0))
        aggregation_mode = node_def.aggregation
        aggregated: dict

        if aggregation_mode == AggregationMode.COLLECT:
            aggregated = {"items": [c.result_data for c in ordered_children]}

        elif aggregation_mode == AggregationMode.CONCAT:
            merged: dict = {}
            for child in ordered_children:
                if isinstance(child.result_data, dict):
                    merged.update(child.result_data)
            aggregated = merged

        elif aggregation_mode == AggregationMode.SUM:
            total = sum(
                c.result_data.get("value", 0)
                for c in ordered_children
                if isinstance(c.result_data, dict)
            )
            aggregated = {"total": total}

        elif aggregation_mode == AggregationMode.FIRST:
            aggregated = ordered_children[0].result_data if ordered_children else {}

        elif aggregation_mode == AggregationMode.LAST:
            aggregated = ordered_children[-1].result_data if ordered_children else {}

        else:
            raise ContractViolationError(
                f"aggregate_fan_ins: unknown AggregationMode={aggregation_mode!r} "
                f"for task_name={fan_in_task.task_name!r}. "
                "Add a handler for this mode."
            )

        # Step 6: Persist aggregated result
        repo.aggregate_fan_in(fan_in_task.task_instance_id, aggregated or {})
        result.aggregated.append(fan_in_task.task_instance_id)
        logger.info(
            "aggregate_fan_ins: run_id=%s task_name=%r mode=%s children=%d → COMPLETED",
            run_id, fan_in_task.task_name, aggregation_mode.value, len(children),
        )

    return result
