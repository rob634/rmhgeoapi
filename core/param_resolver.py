# ============================================================================
# CLAUDE CONTEXT - PARAMETER RESOLVER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Resolves task parameters from job_params and predecessor outputs
# PURPOSE: Pure functions that build the concrete parameter dict for each task
#          node and fan-out item at dispatch time; no DB, no I/O.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: ParameterResolutionError, resolve_dotted_path, resolve_param_or_predecessor,
#          resolve_task_params, resolve_fan_out_params
# DEPENDENCIES: jinja2, core.models.workflow_definition, exceptions
# ============================================================================

import logging
from typing import Any

from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.nativetypes import NativeEnvironment
from jinja2.runtime import Undefined

from core.models.workflow_definition import FanOutTaskDef, TaskNode
from exceptions import BusinessLogicError

logger = logging.getLogger(__name__)

# Module-level Jinja2 environment — NativeEnvironment preserves Python types
# (int, bool, list) rather than stringifying them.  StrictUndefined means any
# reference to a missing context key raises UndefinedError immediately.
_JINJA_ENV = NativeEnvironment(undefined=StrictUndefined)


# ============================================================================
# EXCEPTION
# ============================================================================


class ParameterResolutionError(BusinessLogicError):
    """
    Runtime resolution failure.

    Spec: D.4 — Exception.  The orchestrator catches this and FAILs the task
    rather than letting an untyped exception propagate up the call stack.
    """

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.context: dict = context or {}


# ============================================================================
# resolve_dotted_path
# ============================================================================


def resolve_dotted_path(path: str, predecessor_outputs: dict[str, dict]) -> Any:
    """
    Navigate predecessor_outputs using a dotted path string.

    Spec: D.4 — resolve_dotted_path.
    First segment = node name (top-level key in predecessor_outputs).
    Subsequent segments traverse into that node's result_data dict by string
    key; if the current value is a list and the segment is a decimal integer,
    list index access is attempted.

    Returns the resolved value, which MAY be None (stored null is valid).

    Raises:
        ParameterResolutionError — malformed path, unknown node, or missing key
                                   at any traversal step.
    """
    # Step 1 — split and validate structure
    segments = path.split(".")
    if len(segments) < 2 or any(s == "" for s in segments):
        raise ParameterResolutionError(
            f"Dotted path '{path}' is malformed: must have at least two non-empty segments.",
            context={"path": path},
        )

    node_name = segments[0]

    # Step 2 — validate node presence
    if node_name not in predecessor_outputs:
        raise ParameterResolutionError(
            f"Path '{path}': node '{node_name}' not found in predecessor outputs.",
            context={
                "path": path,
                "node_name": node_name,
                "available_nodes": list(predecessor_outputs.keys()),
            },
        )

    current: Any = predecessor_outputs[node_name]

    # Step 3 — guard against a None node output before traversal
    if current is None:
        raise ParameterResolutionError(
            f"Path '{path}': predecessor output for node '{node_name}' is None.",
            context={"path": path, "node_name": node_name},
        )

    # Step 4 — traverse remaining segments
    traversed = node_name
    for segment in segments[1:]:
        try:
            if isinstance(current, list) and segment.isdigit():
                current = current[int(segment)]
            else:
                current = current[segment]
        except (KeyError, IndexError, TypeError) as exc:
            available: Any
            if isinstance(current, dict):
                available = list(current.keys())
            elif isinstance(current, list):
                available = f"list of length {len(current)}"
            else:
                available = f"non-subscriptable type {type(current).__name__}"

            raise ParameterResolutionError(
                f"Path '{path}': failed at segment '{segment}' "
                f"(traversed so far: '{traversed}'). {exc}",
                context={
                    "path": path,
                    "node_name": node_name,
                    "segment": segment,
                    "traversed": traversed,
                    "available_keys": available,
                },
            ) from exc

        traversed = f"{traversed}.{segment}"

    logger.debug("resolve_dotted_path: '%s' → %r", path, current)
    return current


# ============================================================================
# resolve_param_or_predecessor
# ============================================================================


def resolve_param_or_predecessor(
    expr: str,
    predecessor_outputs: dict[str, dict],
    job_params: dict,
    *,
    strict: bool = False,
) -> Any:
    """
    Resolve an expression that may reference either job params or predecessor outputs.

    If `expr` starts with "params.", navigates job_params using the dotted path.
    With strict=False (default), returns None on missing keys (safe for when-clauses).
    With strict=True, raises ParameterResolutionError on missing keys (for conditionals).

    Otherwise, delegates to resolve_dotted_path.
    """
    if expr.startswith("params."):
        segments = expr.split(".")
        current = job_params
        for seg in segments[1:]:  # skip "params" prefix
            if isinstance(current, dict) and seg in current:
                current = current[seg]
            else:
                if strict:
                    raise ParameterResolutionError(
                        f"Path '{expr}': key '{seg}' not found in job_params",
                        context={"path": expr, "segment": seg,
                                 "available_keys": list(current.keys()) if isinstance(current, dict) else []},
                    )
                return None
        return current

    return resolve_dotted_path(expr, predecessor_outputs)


# ============================================================================
# resolve_task_params
# ============================================================================


def resolve_task_params(
    node: TaskNode,
    job_params: dict,
    predecessor_outputs: dict[str, dict],
) -> dict:
    """
    Build the concrete parameter dict for a TaskNode at dispatch time.

    Spec: D.4 — resolve_task_params (three steps).

    Step 1 — base params from node.params:
        list[str]  → extract named keys from job_params; raise if absent; warn on dups.
        dict       → use literal values directly.
        empty      → resolved starts as {}.

    Step 2 — receives overlay:
        Each (local_name, dotted_path) in node.receives resolves via
        resolve_dotted_path and overwrites any Step-1 value (receives always wins).

    Step 3 — return resolved dict.

    Raises:
        ParameterResolutionError — missing job_params key or bad dotted path.
    """
    resolved: dict = {}

    # ------------------------------------------------------------------ #
    # Step 1 — base params                                                #
    # ------------------------------------------------------------------ #
    if not isinstance(node.params, (list, dict)):
        raise ParameterResolutionError(
            f"TaskNode handler='{node.handler}': params must be list or dict, "
            f"got {type(node.params).__name__}.",
            context={"handler": node.handler, "params_type": type(node.params).__name__},
        )

    if isinstance(node.params, list):
        seen_keys: set[str] = set()
        for key in node.params:
            if key in seen_keys:
                logger.warning(
                    "resolve_task_params: duplicate key '%s' in params list for handler '%s'; "
                    "ignoring duplicate.",
                    key,
                    node.handler,
                )
                continue
            seen_keys.add(key)
            if key not in job_params:
                raise ParameterResolutionError(
                    f"TaskNode handler='{node.handler}': required job_param key '{key}' "
                    "is absent from job_params.",
                    context={"handler": node.handler, "missing_key": key,
                             "available_keys": list(job_params.keys())},
                )
            resolved[key] = job_params[key]
    else:
        # dict — use literal values directly (may be empty dict)
        resolved = dict(node.params)

    # ------------------------------------------------------------------ #
    # Step 2 — receives overlay (always wins on collision)                #
    # ------------------------------------------------------------------ #
    for local_name, dotted_path in node.receives.items():
        resolved[local_name] = resolve_dotted_path(dotted_path, predecessor_outputs)

    logger.debug(
        "resolve_task_params: handler='%s' resolved_keys=%s",
        node.handler,
        list(resolved.keys()),
    )
    return resolved


# ============================================================================
# resolve_fan_out_params
# ============================================================================


def resolve_fan_out_params(
    task_template: FanOutTaskDef,
    item: Any,
    index: int,
    job_params: dict,
    predecessor_outputs: dict[str, dict],
) -> dict:
    """
    Build the concrete parameter dict for one fan-out item.

    Spec: D.4 — resolve_fan_out_params.

    Jinja2 context (exhaustive):
        {"item": item, "index": index, "inputs": job_params, "nodes": predecessor_outputs}

    index is zero-based.  item may be any type including None (a WARNING is logged
    when item is None).

    For each (key, value) in task_template.params:
        - If value is str containing '{{': render via _JINJA_ENV; UndefinedError → raise.
        - Otherwise: pass through as-is.

    Raises:
        ParameterResolutionError — Jinja2 UndefinedError for any unresolvable template var.
    """
    context = {
        "item": item,
        "index": index,
        "inputs": job_params,
        "nodes": predecessor_outputs,
    }

    if item is None:
        logger.warning(
            "resolve_fan_out_params: item is None at index=%d handler='%s'",
            index,
            task_template.handler,
        )

    resolved: dict = {}
    for key, value in task_template.params.items():
        if isinstance(value, str) and "{{" in value:
            try:
                rendered = _JINJA_ENV.from_string(value).render(**context)
                # NativeEnvironment returns an Undefined object (not a string)
                # when a variable is missing; force the UndefinedError here so
                # the except clause below can catch it uniformly.
                if isinstance(rendered, Undefined):
                    rendered._fail_with_undefined_error()
                resolved[key] = rendered
            except (UndefinedError, TemplateSyntaxError) as exc:
                raise ParameterResolutionError(
                    f"Fan-out handler='{task_template.handler}' index={index}: "
                    f"Jinja2 template error for key '{key}': {exc}",
                    context={
                        "handler": task_template.handler,
                        "index": index,
                        "key": key,
                        "template": value,
                        "jinja_error": str(exc),
                    },
                ) from exc
        else:
            resolved[key] = value

    logger.debug(
        "resolve_fan_out_params: handler='%s' index=%d resolved_keys=%s",
        task_template.handler,
        index,
        list(resolved.keys()),
    )
    return resolved
