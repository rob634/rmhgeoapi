# ============================================================================
# CLAUDE CONTEXT - DAG INITIALIZER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Converts WorkflowDefinition into live WorkflowRun + tasks atomically
# PURPOSE: Validate DAG structure, generate deterministic IDs, and atomically
#          persist a WorkflowRun, WorkflowTask rows, and WorkflowTaskDep edges.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: DAGInitializer
# DEPENDENCIES: hashlib, json, logging, core.models.workflow_definition,
#               core.models.workflow_run, core.models.workflow_task,
#               core.models.workflow_task_dep, core.models.workflow_enums,
#               exceptions
# ============================================================================

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from core.models.workflow_definition import (
    WorkflowDefinition,
    TaskNode,
    ConditionalNode,
    FanOutNode,
    FanInNode,
)
from core.models.workflow_enums import WorkflowRunStatus, WorkflowTaskStatus
from core.models.workflow_run import WorkflowRun
from core.models.workflow_task import WorkflowTask
from core.models.workflow_task_dep import WorkflowTaskDep
from exceptions import ContractViolationError

logger = logging.getLogger(__name__)


# ============================================================================
# PRIVATE PURE FUNCTIONS
# ============================================================================


def _canonical_json_default(obj):
    """
    Explicit JSON serializer for deterministic hashing.

    Raises ContractViolationError for unknown types rather than silently
    converting via str() — prevents fragile hash generation.
    """
    from datetime import datetime as _dt, date as _d
    from decimal import Decimal
    from enum import Enum
    from uuid import UUID

    if isinstance(obj, _dt):
        return obj.isoformat()
    if isinstance(obj, _d):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return obj.hex
    if isinstance(obj, Enum):
        return obj.value
    raise ContractViolationError(
        f"_generate_run_id: parameter contains non-serializable type "
        f"{type(obj).__name__}. Convert to a JSON-native type before submission."
    )


def _generate_run_id(workflow_name: str, parameters: dict) -> str:
    """
    Produce a deterministic SHA256 run identifier.

    Spec: DAGInitializer.create_run — Step 1 (idempotency via deterministic ID).
    Uses _canonical_json_default for explicit type handling — rejects unknown types
    instead of silently converting via str().
    """
    canonical = json.dumps(
        {"workflow_name": workflow_name, "parameters": parameters},
        sort_keys=True,
        default=_canonical_json_default,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _generate_task_instance_id(run_id: str, task_name: str) -> str:
    """
    Produce a deterministic task instance ID scoped to a run.

    Spec: _build_tasks_and_deps — Pass 2, task_instance_id generation.
    Format: '{run_id[:12]}-{task_name}' — human-readable and collision-free within a run.
    """
    return f"{run_id[:12]}-{task_name}"


def _resolve_handler(node_name: str, node) -> str:
    """
    Map a node definition to its handler string.

    Spec: _build_tasks_and_deps — Pass 2, handler resolution per node type.
    Raises ContractViolationError on unknown node type — indicates a bug in the
    workflow model discriminated union, not a user error.

    RK-6: Sentinel values '__conditional__' and '__fan_in__' are reserved and
    must not collide with real handler names.
    """
    if isinstance(node, TaskNode):
        return node.handler
    if isinstance(node, FanOutNode):
        return "__fan_out__"
    if isinstance(node, ConditionalNode):
        return "__conditional__"
    if isinstance(node, FanInNode):
        return "__fan_in__"
    raise ContractViolationError(
        f"Unknown node type for node '{node_name}': {type(node).__name__}. "
        "This is a programming bug — update _resolve_handler to handle this type."
    )


def _resolve_max_retries(node) -> int:
    """
    Return the maximum retry count for a node.

    Spec: _build_tasks_and_deps — Pass 2, max_retries per node type.
    TaskNode and FanOutNode honour their RetryPolicy; structural nodes (Conditional,
    FanIn) are never retried because they perform no user work.
    """
    if isinstance(node, TaskNode):
        return node.retry.max_attempts if node.retry else 3
    if isinstance(node, FanOutNode):
        return node.task.retry.max_attempts if node.task.retry else 3
    # ConditionalNode and FanInNode are structural — never retried
    return 0


def _parse_dep(dep: str) -> tuple[str, bool]:
    """
    Parse a dependency string, stripping the optional '?' suffix.

    Spec: _build_tasks_and_deps — Pass 1 and Pass 3, dependency resolution.
    Returns (node_name, is_optional). Optional deps tolerate skipped (not failed)
    upstream tasks per WorkflowTaskDep.optional semantics.
    """
    if dep.endswith("?"):
        return dep[:-1], True
    return dep, False


def _build_tasks_and_deps(
    run_id: str,
    workflow_def: WorkflowDefinition,
) -> tuple[list[WorkflowTask], list[WorkflowTaskDep]]:
    """
    Pure function — converts a WorkflowDefinition into task and dep lists.

    Spec: _build_tasks_and_deps — three-pass algorithm for validation, task
    construction, and edge construction.

    Pass 1: Validate all dependency references. Compute all_downstream_names.
            Identify root nodes (no incoming edges). Raise ContractViolationError
            if any ref is missing or no roots exist (cycle indicator).

    Pass 2: Build WorkflowTask rows — one per node. Root nodes start READY;
            others start PENDING. Builds instance_id_map for Pass 3.

    Pass 3: Build WorkflowTaskDep rows. Deduplicates edges via a set of
            (task_instance_id, depends_on_instance_id) tuples (RK-3).

    Raises ContractViolationError for:
      - Missing node references in depends_on or branch.next
      - No root nodes (indicates a structural cycle)
      - Unknown node types (propagated from _resolve_handler)
    """
    nodes = workflow_def.nodes
    node_names: set[str] = set(nodes.keys())

    # ------------------------------------------------------------------ #
    # Pass 1 — Validate refs, discover all_downstream_names, find roots  #
    # ------------------------------------------------------------------ #
    all_downstream_names: set[str] = set()

    for node_name, node in nodes.items():
        # Validate and record depends_on edges
        for raw_dep in node.depends_on:
            dep_name, _ = _parse_dep(raw_dep)
            if dep_name not in node_names:
                raise ContractViolationError(
                    f"Node '{node_name}' depends_on unknown node '{dep_name}'. "
                    "Fix the workflow YAML — this node does not exist."
                )
            all_downstream_names.add(node_name)

        # Validate ConditionalNode branch targets
        if isinstance(node, ConditionalNode):
            for branch in node.branches:
                for target in branch.next:
                    if target not in node_names:
                        raise ContractViolationError(
                            f"ConditionalNode '{node_name}' branch '{branch.name}' "
                            f"references unknown node '{target}'. "
                            "Fix the workflow YAML — this node does not exist."
                        )
                    all_downstream_names.add(target)

    root_names: set[str] = node_names - all_downstream_names
    if not root_names:
        raise ContractViolationError(
            f"Workflow '{workflow_def.workflow}' has no root nodes — all nodes have "
            "incoming edges. This indicates a structural cycle. Fix the workflow YAML."
        )

    logger.debug(
        "DAG root computation: workflow=%s nodes=%d roots=%s",
        workflow_def.workflow,
        len(nodes),
        sorted(root_names),
    )

    # ------------------------------------------------------------------ #
    # Pass 2 — Build WorkflowTask rows                                    #
    # ------------------------------------------------------------------ #
    tasks: list[WorkflowTask] = []
    instance_id_map: dict[str, str] = {}
    now = datetime.now(timezone.utc)

    for node_name, node in nodes.items():
        task_instance_id = _generate_task_instance_id(run_id, node_name)
        instance_id_map[node_name] = task_instance_id

        status = (
            WorkflowTaskStatus.READY
            if node_name in root_names
            else WorkflowTaskStatus.PENDING
        )
        handler = _resolve_handler(node_name, node)  # raises ContractViolationError on unknown
        max_retries = _resolve_max_retries(node)
        when_clause = node.when if isinstance(node, TaskNode) else None

        tasks.append(
            WorkflowTask(
                task_instance_id=task_instance_id,
                run_id=run_id,
                task_name=node_name,
                handler=handler,
                status=status,
                fan_out_index=None,
                fan_out_source=None,
                when_clause=when_clause,
                parameters=None,
                max_retries=max_retries,
                created_at=now,
                updated_at=now,
            )
        )

    # ------------------------------------------------------------------ #
    # Pass 3 — Build WorkflowTaskDep rows (deduplicated)                 #
    # ------------------------------------------------------------------ #
    deps: list[WorkflowTaskDep] = []
    seen_edges: set[tuple[str, str]] = set()

    for node_name, node in nodes.items():
        this_id = instance_id_map[node_name]

        # depends_on edges: this node depends on the named node
        for raw_dep in node.depends_on:
            dep_name, is_optional = _parse_dep(raw_dep)
            upstream_id = instance_id_map[dep_name]
            edge = (this_id, upstream_id)
            if edge not in seen_edges:
                seen_edges.add(edge)
                deps.append(
                    WorkflowTaskDep(
                        task_instance_id=this_id,
                        depends_on_instance_id=upstream_id,
                        optional=is_optional,
                    )
                )

        # ConditionalNode branch.next edges: target depends on this conditional
        if isinstance(node, ConditionalNode):
            for branch in node.branches:
                for target in branch.next:
                    target_id = instance_id_map[target]
                    edge = (target_id, this_id)
                    if edge not in seen_edges:  # RK-3: deduplicate overlapping edges
                        seen_edges.add(edge)
                        deps.append(
                            WorkflowTaskDep(
                                task_instance_id=target_id,
                                depends_on_instance_id=this_id,
                                optional=False,
                            )
                        )

    return tasks, deps


# ============================================================================
# DAGInitializer CLASS
# ============================================================================


class DAGInitializer:
    """
    Converts a WorkflowDefinition into a live WorkflowRun atomically.

    Spec: Component 1 — DAGInitializer class.
    Orchestrates: ID generation → structural validation → atomic DB persistence → idempotency.
    """

    def __init__(self, repository) -> None:
        """
        Inject the WorkflowRunRepository.

        Spec: DAGInitializer.__init__ — dependency injection, no direct DB access in this class.
        """
        self._repo = repository

    def create_run(
        self,
        workflow_def: WorkflowDefinition,
        parameters: dict,
        platform_version: str,
        *,
        request_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        release_id: Optional[str] = None,
        legacy_job_id: Optional[str] = None,
    ) -> WorkflowRun:
        """
        Atomically create a WorkflowRun, WorkflowTask rows, and WorkflowTaskDep edges.

        Spec: DAGInitializer.create_run — all five steps.
        Idempotent: if run_id already exists, fetches and returns the existing WorkflowRun.

        Steps:
          1. _generate_run_id — deterministic SHA256 from workflow_name + parameters
          2. _build_tasks_and_deps — pure structural validation and row construction
          3. Build WorkflowRun model (status=PENDING, definition=snapshot)
          4. repo.insert_run_atomic — single transaction; returns False on duplicate
          5. On duplicate: fetch existing run and log WARNING

        Raises:
          ContractViolationError — structural YAML problems (missing refs, cycles, unknown types).
          BusinessLogicError — transient DB failures from the repository layer.
        """
        t_start = time.monotonic()

        run_id = _generate_run_id(workflow_def.workflow, parameters)

        # Step 2: pure validation — fast-fail before touching the DB
        tasks, deps = _build_tasks_and_deps(run_id, workflow_def)

        # Step 3: build the WorkflowRun model
        run = WorkflowRun(
            run_id=run_id,
            workflow_name=workflow_def.workflow,
            parameters=parameters,
            status=WorkflowRunStatus.PENDING,
            definition=workflow_def.model_dump(),
            platform_version=platform_version,
            request_id=request_id,
            asset_id=asset_id,
            release_id=release_id,
            legacy_job_id=legacy_job_id,
        )

        # Step 4: atomic DB write
        created = self._repo.insert_run_atomic(run, tasks, deps)
        elapsed_ms = round((time.monotonic() - t_start) * 1000)

        if created:
            logger.info(
                "WorkflowRun created: run_id=%s workflow=%s tasks=%d deps=%d elapsed_ms=%d",
                run_id,
                workflow_def.workflow,
                len(tasks),
                len(deps),
                elapsed_ms,
            )
            return run

        # Step 5: idempotent path — run already existed
        existing = self._repo.get_by_run_id(run_id)
        logger.warning(
            "Idempotent return: run_id=%s workflow=%s existing_status=%s elapsed_ms=%d",
            run_id,
            workflow_def.workflow,
            existing.status if existing else "unknown",
            elapsed_ms,
        )
        # Return the existing run if fetchable; fall back to the constructed model
        # if the fetch returned None (race condition window, extremely unlikely).
        return existing if existing is not None else run
