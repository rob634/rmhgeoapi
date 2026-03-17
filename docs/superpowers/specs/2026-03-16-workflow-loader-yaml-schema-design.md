# Design Spec: Workflow Loader + YAML Schema (Story 5.1)

**Date**: 16 MAR 2026
**Version**: v0.12.0 target (Stream B: DAG Foundation)
**Epic**: V10 DAG Migration
**Status**: DESIGN
**Dependencies**: None — pure new code, no conflicts with F2/F3/F4

---

## Purpose

Build the foundational layer that reads YAML workflow definitions (blueprints) and produces validated, typed Python models that the DAG orchestrator, initializer, and parameter resolver consume. This is the schema contract that everything else in the DAG system depends on.

## Context

The V10 migration replaces 14 Python job classes with YAML workflow definitions. Each YAML file defines a directed acyclic graph of nodes — task, conditional, fan_out, and fan_in — that the orchestrator evaluates at runtime.

**Key conceptual model** (from V10_MIGRATION.md):
- **Node** = blueprint template in YAML (static, reusable)
- **Task** = runtime execution of a node in the database (mutable, per-run)
- **Workflow** = collection of nodes forming a DAG
- **Run** = one execution of a workflow with real parameters

Stages are eliminated. Ordering is expressed through `depends_on` edges. The handler library is a menu of operations; workflows are recipes.

**Source reference**: Port from `rmhdagmaster` — `services/workflow_service.py` (184 lines) + `core/models/workflow.py` (260 lines). Adapt to V10's `depends_on` backward pointers, `receives:` parameter mapping, and discriminated union node types.

**Supersedes**: This spec supersedes V10_MIGRATION.md's YAML examples where they conflict. Specifically:
- V10_MIGRATION.md was updated to use `nodes:` as the top-level key (15 MAR 2026), matching this spec.
- V10_MIGRATION.md's inline `fan_out:` field on task nodes is replaced by the explicit `type: fan_out` node with nested `task:` template (designed in brainstorming session, 16 MAR 2026).
- V10_MIGRATION.md's `item_param` approach is replaced by Jinja2 templates (`{{ item }}`, `{{ index }}`) in fan-out `task.params` only.
- Explicit `type: fan_in` node replaces implicit fan-in via `depends_on` + `result[]` syntax.

### Single Codebase, Multiple Roles

All code lives in one repository (`rmhgeoapi`). The deployment target is selected by `APP_MODE` environment variable (already exists in config):

| APP_MODE | Role | Entry Point | Needs GDAL? |
|----------|------|------------|-------------|
| `standalone` | Function App (HTTP + legacy orchestration) | `function_app.py` | No |
| `platform` | Function App (B2B gateway) | `function_app.py` | No |
| `worker_docker` | Docker worker (SKIP LOCKED poll, handler execution) | `docker_service.py` | Yes |
| `orchestrator` | DAG orchestrator (DAG eval poll, no handler execution) | `entrypoint_orchestrator.py` | No (but tolerates it) |

The workflow loader, registry, and Pydantic models live in `core/` — imported by all roles. The orchestrator can initially deploy using the same heavy Docker image as workers (`APP_MODE=orchestrator`). A slim `Dockerfile.orchestrator` (~250MB vs ~2-3GB) is an optimization for F6, not a blocker.

Function App deploys via `func azure functionapp publish` — `.funcignore` excludes Docker files. Docker deploys via ACR build — `Dockerfile` excludes Function App runtime.

---

## YAML Workflow Schema

### Top-Level Structure

```yaml
workflow: process_raster_docker          # unique identifier (replaces job_type)
description: "Single raster → COG + STAC item"
version: 1                               # integer, incremented on breaking changes
reversed_by: unpublish_raster            # optional: paired unpublish workflow
reverses: []                             # optional: forward workflows this unpublishes

parameters:
  blob_name: {type: str, required: true}
  container_name: {type: str, required: true}
  collection_id: {type: str, required: true}
  processing_options:
    type: dict
    default: {}
    nested:
      overwrite: {type: bool, default: false}
      build_overviews: {type: bool, default: false}

validators:
  - type: blob_exists
    container_param: container_name
    blob_param: blob_name
    zone: bronze

nodes:
  validate:
    type: task
    handler: raster_validate_source
    params: [blob_name, container_name]
  # ... more nodes ...

finalize:
  handler: raster_finalize
```

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | str | Yes | Unique identifier. Used in submission, DB, logging. |
| `description` | str | Yes | Human-readable. Shown in dashboard and API responses. |
| `version` | int | Yes | Schema version. Snapshotted in `workflow_runs.definition` at submission. |
| `reversed_by` | str | No | Name of the unpublish workflow that tears this down. |
| `reverses` | list[str] | No | Forward workflows that this workflow unpublishes. |
| `parameters` | dict | Yes | Input parameter schema. Validated at submission time. |
| `validators` | list[dict] | No | Pre-flight resource checks before DAG initialization. |
| `nodes` | dict | Yes | DAG node definitions. Keys are node names. |
| `finalize` | dict | No | Handler that runs after all nodes terminal. Receives all results. |

### Parameter Types

| Type | Python | Example |
|------|--------|---------|
| `str` | `str` | `blob_name: {type: str, required: true}` |
| `int` | `int` | `chunk_size: {type: int, default: 10000}` |
| `float` | `float` | `threshold: {type: float, default: 0.5}` |
| `bool` | `bool` | `overwrite: {type: bool, default: false}` |
| `dict` | `dict` | `processing_options: {type: dict, default: {}}` |
| `list` | `list` | `layer_names: {type: list, required: false}` |

Nested parameters use `nested:` block (same as current rmhgeoapi pattern).

---

## Node Types

Four explicit types. Every node in the YAML declares its type. The graph structure is explicit — no implicit behavior from field presence.

### `task` (default if `type:` omitted)

Runs a handler on a worker via SKIP LOCKED claim. The workhorse node.

```yaml
validate:
  type: task                        # optional — default if omitted
  handler: raster_validate          # REQUIRED: handler name from ALL_HANDLERS
  depends_on: [some_node]           # optional: prerequisite node names
  params: [blob_name, crs]          # optional: job parameter names to pass through
  receives:                         # optional: values from predecessor results
    metadata: "validate.result.metadata"
  when: "params.processing_options.build_overviews"  # optional: skip if falsy
  retry:                            # optional: override default retry policy
    max_attempts: 5
    backoff: exponential
    initial_delay_seconds: 10
  timeout_seconds: 3600             # optional: default from config
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"task"` | No | Default if omitted. |
| `handler` | str | **Yes** | Handler name from `ALL_HANDLERS` registry. |
| `depends_on` | list[str] | No | Prerequisite node names. `?` suffix = optional (proceed if skipped). See [Optional Dependencies](#optional-dependencies). |
| `params` | list[str] or dict | No | Job parameter names to pass through, or explicit key:value pairs. |
| `receives` | dict[str, str] | No | `{local_name: "node.result.path"}` — values from predecessor results. |
| `when` | str | No | Dotted-path truthiness check. If falsy → task marked SKIPPED. |
| `retry` | RetryPolicy | No | Override default retry behavior. |
| `timeout_seconds` | int | No | Override default timeout. |

### `conditional`

Evaluates a condition against predecessor output and routes to exactly one branch. Does NOT execute a handler — the orchestrator evaluates inline.

```yaml
route_by_size:
  type: conditional                     # REQUIRED
  depends_on: [validate]                # optional: prerequisites
  condition: "validate.result.file_size" # REQUIRED: dotted path to value
  branches:                             # REQUIRED: at least 2, one must be default
    - name: large
      condition: "> 1000000000"
      next: [tile_cogs]
    - name: small
      default: true
      next: [single_cog]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"conditional"` | **Yes** | Must be explicit. |
| `depends_on` | list[str] | No | Prerequisites. |
| `condition` | str | **Yes** | Dotted path to the value to evaluate. |
| `branches` | list[BranchDef] | **Yes** | At least 2 branches. One must have `default: true`. |

**Branch fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Human-readable branch name (logged, shown in dashboard). |
| `condition` | str | No | Operator + value, e.g. `"> 1000000"`, `"contains foo"`. Omit for default. |
| `default` | bool | No | `true` = fallback if no other branch matches. |
| `next` | list[str] | Yes | Node names to activate if this branch is taken. |

**Supported operators**: `>`, `>=`, `<`, `<=`, `==`, `!=`, `contains`, `starts_with`, `ends_with`, `in`, `not_in`, `is_null`, `is_not_null`, `true`, `false`

**Routing rules:**
- Exactly one branch taken per execution.
- Branches evaluated in order; first match wins.
- `default: true` branch taken if no condition matches.
- Must have at least one branch with `default: true`.
- Untaken branches: all `next:` nodes (and their exclusive descendants) marked SKIPPED.
- `next:` is a forward pointer (exception to `depends_on` convention) because the conditional *creates* routing.

### `fan_out`

Expands a source array into N child tasks, each running the same handler.

```yaml
copy_blobs:
  type: fan_out                          # REQUIRED
  depends_on: [validate]                 # optional: prerequisites
  source: "validate.result.blob_list"    # REQUIRED: expression → array
  task:                                  # REQUIRED: template for each child
    handler: zarr_copy_single_blob
    params:
      blob_path: "{{ item }}"           # current array element
      index: "{{ index }}"              # 0-based position
      source_url: "{{ inputs.source_url }}"
    timeout_seconds: 600
    retry:
      max_attempts: 3
      backoff: exponential
      initial_delay_seconds: 5
  max_fan_out: 500                       # optional: ceiling (default 500)
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"fan_out"` | **Yes** | Must be explicit. |
| `depends_on` | list[str] | No | Prerequisites. |
| `source` | str | **Yes** | Dotted path resolving to an array. |
| `task` | FanOutTaskDef | **Yes** | Template for child tasks. |
| `max_fan_out` | int | No | Maximum expansion size (default 500). |

**Fan-out task template fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `handler` | str | Yes | Handler name for each child task. |
| `params` | dict[str, Any] | No | Jinja2 templates. `{{ item }}`, `{{ index }}`, `{{ item.field }}`, `{{ inputs.param }}`. |
| `timeout_seconds` | int | No | Per-child timeout. |
| `retry` | RetryPolicy | No | Per-child retry policy. |

**Fan-out rules:**
- `source:` must resolve to an array at runtime.
- Each child is an independent execution task (claimed by workers via SKIP LOCKED).
- The fan_out node itself is marked `expanded` (not executed by a worker).
- `{{ item }}` and `{{ index }}` are reserved template variables.
- If item is a dict: `{{ item.field_name }}` accesses nested values.
- If source resolves to empty array: fan_out node marked FAILED.
- If expansion exceeds `max_fan_out`: fan_out node marked FAILED.

### `fan_in`

Waits for all children of a fan_out node, aggregates their results. Does NOT execute a handler — the orchestrator aggregates inline.

```yaml
aggregate_blobs:
  type: fan_in                           # REQUIRED
  depends_on: [copy_blobs]              # REQUIRED: must reference a fan_out node
  aggregation: collect                   # optional: default "collect"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"fan_in"` | **Yes** | Must be explicit. |
| `depends_on` | list[str] | **Yes** | Must include exactly one `fan_out` node. |
| `aggregation` | str | No | `collect` (default), `concat`, `sum`, `first`, `last`. |

**Aggregation modes:**
- `collect` — list of all child outputs `{"results": [...], "count": N}`
- `concat` — flatten arrays from child outputs
- `sum` — sum numeric values from child outputs
- `first` / `last` — single child output

**Fan-in rules:**
- Blocks until ALL children of the referenced fan_out are terminal (completed, failed, skipped).
- If any children failed: fan_in fails with summary of child errors.
- Fan-in output stored in `result_data`, available to downstream nodes via `receives:`.
- `depends_on` must include exactly one `fan_out` node. May include additional non-fan_out dependencies.

### Optional Dependencies

Any node with `depends_on` supports the `?` suffix to mark a dependency as optional:

```yaml
consolidate:
  type: task
  handler: zarr_consolidate_metadata
  depends_on:
    - copy_blobs           # required: must complete successfully
    - rechunk?             # optional: proceed even if rechunk was skipped
```

**Rules:**
- `depends_on: [A]` — A must reach terminal state `completed` before this node becomes ready.
- `depends_on: [A?]` — A must reach terminal state `completed` OR `skipped`. If A was skipped, this node still proceeds.
- If an optional dependency FAILED (not skipped), the dependent still blocks — `?` only tolerates `skipped`, not failures.
- The `?` suffix is stripped during parsing: `"rechunk?"` → dependency on node `"rechunk"` with `optional=true`.

This is essential for conditional workflows where a `when:` clause may skip a node, and downstream nodes should proceed regardless.

### Conditional `next:` and Implicit Dependencies

Conditional nodes use `next:` (forward pointers) to route execution. This creates an **implicit dependency** — target nodes do NOT also need `depends_on: [conditional_node]`.

```yaml
route:
  type: conditional
  depends_on: [validate]
  condition: "validate.result.file_size"
  branches:
    - name: large
      condition: "> 1000000000"
      next: [tile_cogs]       # tile_cogs does NOT need depends_on: [route]
    - name: small
      default: true
      next: [single_cog]      # single_cog does NOT need depends_on: [route]

tile_cogs:
  type: task
  handler: raster_create_tiled_cogs
  # no depends_on needed — conditional next: creates implicit edge
```

The DAG initializer (Story 5.3) creates dependency edges from conditional `next:` pointers in addition to explicit `depends_on` edges. This means:
- Cycle detection must include both `depends_on` (backward) and `next:` (forward) edges — both express predecessor→successor relationships.
- If a target node also declares `depends_on: [route]`, it's redundant but not an error.
- Untaken branch targets (and their exclusive descendants) are marked SKIPPED by the orchestrator.

### Jinja2 Scope

Jinja2 templates (`{{ ... }}`) are used in **two places only**:

1. **Fan-out `task.params`** — `{{ item }}`, `{{ index }}`, `{{ item.field }}`, `{{ inputs.param_name }}`
2. **Fan-out `source:`** expressions (if the source path needs input parameter interpolation)

All other parameter resolution uses the `receives:` dotted-path mapping (Story 5.4), which is a simple programmatic lookup — not Jinja2. This keeps the template engine scoped to fan-out expansion only.

---

## Complete Workflow Example

```yaml
workflow: ingest_zarr
description: "Ingest native Zarr store with optional rechunking"
version: 1
reversed_by: unpublish_zarr

parameters:
  source_url: {type: str, required: true}
  dataset_id: {type: str, required: true}
  target_container: {type: str, default: "zarr"}
  rechunk: {type: bool, default: false}
  collection_id: {type: str, required: true}

validators:
  - type: blob_exists
    container_param: source_url
    zone: bronze

nodes:
  validate:
    type: task
    handler: zarr_validate_store
    params: [source_url, dataset_id]

  copy_blobs:
    type: fan_out
    depends_on: [validate]
    source: "validate.result.blob_list"
    task:
      handler: zarr_copy_single_blob
      params:
        blob_path: "{{ item }}"
        source_url: "{{ inputs.source_url }}"
        target_container: "{{ inputs.target_container }}"

  aggregate_copies:
    type: fan_in
    depends_on: [copy_blobs]
    aggregation: collect

  rechunk:
    type: task
    handler: zarr_rechunk_store
    depends_on: [aggregate_copies]
    when: "params.rechunk"
    params: [target_container, dataset_id]

  consolidate:
    type: task
    handler: zarr_consolidate_metadata
    depends_on: [rechunk]
    params: [target_container, dataset_id]

  create_stac_item:
    type: task
    handler: stac_create_item
    depends_on: [consolidate]
    params: [collection_id, dataset_id]
    receives:
      zarr_metadata: "validate.result.metadata"

  register:
    type: task
    handler: zarr_register_metadata
    depends_on: [create_stac_item]
    receives:
      stac_item_id: "create_stac_item.result.stac_item_id"

finalize:
  handler: zarr_finalize
```

---

## Pydantic Models

### Design Decision: Discriminated Union

Each node type is a separate Pydantic model with only its own fields. No `Optional` fields that don't belong to the type. Pydantic v2's `Field(discriminator='type')` selects the correct model based on the `type:` field in YAML.

**Rationale**: A single model with `Optional` fields creates ambiguity — `None` could mean "YAML author forgot this" or "this node type doesn't use this field." Discriminated unions eliminate this class of bugs at the type level.

### File: `core/models/workflow_enums.py` (~30 lines)

```python
from enum import Enum

class NodeType(str, Enum):
    TASK = "task"
    CONDITIONAL = "conditional"
    FAN_OUT = "fan_out"
    FAN_IN = "fan_in"

class AggregationMode(str, Enum):
    COLLECT = "collect"
    CONCAT = "concat"
    SUM = "sum"
    FIRST = "first"
    LAST = "last"

class BackoffStrategy(str, Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
```

### File: `core/models/workflow_definition.py` (~300 lines)

```python
from __future__ import annotations
from typing import Any, Annotated, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

from core.models.workflow_enums import NodeType, AggregationMode, BackoffStrategy


# ── Supporting Models ────────────────────────────────────────────

class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay_seconds: int = Field(default=5, ge=1)
    max_delay_seconds: int = Field(default=300, ge=1)


class BranchDef(BaseModel):
    name: str
    condition: Optional[str] = None       # operator + value, e.g. "> 1000000"
    default: bool = False
    next: list[str]                       # node names to activate


class FanOutTaskDef(BaseModel):
    handler: str
    params: dict[str, Any] = {}           # Jinja2 templates: {{ item }}, {{ index }}
    timeout_seconds: int = 3600
    retry: Optional[RetryPolicy] = None


class FinalizeDef(BaseModel):
    handler: str


class ParameterDef(BaseModel):
    type: Literal["str", "int", "float", "bool", "dict", "list"]
    required: bool = False
    default: Any = None
    nested: Optional[dict[str, ParameterDef]] = None


class ValidatorDef(BaseModel):
    type: str                             # blob_exists, table_not_exists, etc.
    model_config = ConfigDict(extra='allow')


# ── Node Type Models (Discriminated Union) ───────────────────────

class TaskNode(BaseModel):
    """Runs a handler on a worker. The workhorse node."""
    type: Literal["task"] = "task"
    handler: str                          # from ALL_HANDLERS
    depends_on: list[str] = []
    params: list[str] | dict[str, Any] = []
    receives: dict[str, str] = {}         # {local_name: "node.result.path"}
    when: Optional[str] = None            # truthiness skip condition
    retry: Optional[RetryPolicy] = None
    timeout_seconds: Optional[int] = None


class ConditionalNode(BaseModel):
    """Evaluates condition, routes to exactly one branch."""
    type: Literal["conditional"]
    depends_on: list[str] = []
    condition: str                        # dotted path to value
    branches: list[BranchDef] = Field(..., min_length=2)  # at least 2, one must be default


class FanOutNode(BaseModel):
    """Expands source array into N child tasks."""
    type: Literal["fan_out"]
    depends_on: list[str] = []
    source: str                           # dotted path → array
    task: FanOutTaskDef                   # template for child tasks
    max_fan_out: int = Field(default=500, ge=1, le=10000)


class FanInNode(BaseModel):
    """Waits for fan_out children, aggregates results."""
    type: Literal["fan_in"]
    depends_on: list[str]                 # must reference a fan_out node
    aggregation: AggregationMode = AggregationMode.COLLECT


# Note: depends_on entries may have '?' suffix (e.g., "rechunk?").
# The loader strips the suffix during structural validation and stores
# parsed dependencies as (node_name, optional: bool) tuples internally.
# Pydantic models keep the raw strings; parsing happens in WorkflowLoader.

NodeDefinition = Annotated[
    TaskNode | ConditionalNode | FanOutNode | FanInNode,
    Field(discriminator='type')
]


# ── Top-Level Workflow Model ─────────────────────────────────────

class WorkflowDefinition(BaseModel):
    """Complete workflow blueprint parsed from YAML."""
    workflow: str
    description: str
    version: int
    reversed_by: Optional[str] = None
    reverses: list[str] = []
    parameters: dict[str, ParameterDef]
    validators: list[ValidatorDef] = []
    nodes: dict[str, NodeDefinition]
    finalize: Optional[FinalizeDef] = None

    def get_node(self, name: str) -> NodeDefinition:
        """Get node by name or raise KeyError."""
        return self.nodes[name]

    def get_root_nodes(self) -> list[str]:
        """Nodes with no depends_on — entry points of the DAG."""
        return [
            name for name, node in self.nodes.items()
            if not node.depends_on
        ]

    def get_leaf_nodes(self) -> list[str]:
        """Nodes that have no successors — exit points of the DAG."""
        # A node has successors if:
        # - Another node lists it in depends_on
        # - It is a conditional and its branches have next: targets
        has_successors = set()
        for name, node in self.nodes.items():
            # Nodes referenced in depends_on have successors (this node is their successor)
            for dep in node.depends_on:
                dep_name = dep.rstrip('?')  # strip optional suffix
                has_successors.add(dep_name)  # dep_name has at least one successor
            # Conditional nodes have successors via next:
            if isinstance(node, ConditionalNode):
                has_successors.add(name)  # the conditional itself has successors
        return [name for name in self.nodes if name not in has_successors]
```

---

## Workflow Loader

### File: `core/workflow_loader.py` (~200 lines)

```python
import yaml
from pathlib import Path
from pydantic import ValidationError

from core.models.workflow_definition import WorkflowDefinition, ConditionalNode, FanOutNode, FanInNode
from core.errors.workflow_errors import WorkflowValidationError


class WorkflowLoader:
    """Parse and validate a single YAML workflow file."""

    @staticmethod
    def load(path: Path) -> WorkflowDefinition:
        """
        Load workflow from YAML file.

        1. Read YAML → raw dict
        2. Pydantic parse with discriminated union
        3. Structural validation
        4. Return validated definition

        Raises:
            WorkflowValidationError on any failure.
        """
        # Step 1: Parse YAML
        raw = WorkflowLoader._read_yaml(path)

        # Step 2: Pydantic validation (field types, discriminated union)
        try:
            definition = WorkflowDefinition.model_validate(raw)
        except ValidationError as e:
            errors = [err['msg'] for err in e.errors()]
            raise WorkflowValidationError(
                workflow_name=raw.get('workflow', path.stem),
                errors=errors,
            )

        # Step 3: Structural validation
        WorkflowLoader._validate_structure(definition)

        return definition

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        """Read YAML file, return raw dict."""
        # Implementation: yaml.safe_load(path.read_text())

    @staticmethod
    def _validate_structure(defn: WorkflowDefinition) -> None:
        """
        Structural validations beyond Pydantic field checks.
        Collects all errors and raises once.
        """
        errors = []

        # 1. Cycle detection (topological sort)
        errors.extend(WorkflowLoader._check_cycles(defn))

        # 2. depends_on references exist
        errors.extend(WorkflowLoader._check_dependency_refs(defn))

        # 3. Conditional branch next: references exist
        errors.extend(WorkflowLoader._check_branch_refs(defn))

        # 4. Conditional has default branch
        errors.extend(WorkflowLoader._check_conditional_defaults(defn))

        # 5. Fan-in depends_on includes a fan_out
        errors.extend(WorkflowLoader._check_fan_in_refs(defn))

        # 6. Handler exists in ALL_HANDLERS
        errors.extend(WorkflowLoader._check_handlers(defn))

        # 7. params: references exist in parameters:
        errors.extend(WorkflowLoader._check_param_refs(defn))

        # 8. No orphan nodes (all reachable from root)
        errors.extend(WorkflowLoader._check_reachability(defn))

        if errors:
            raise WorkflowValidationError(
                workflow_name=defn.workflow,
                errors=errors,
            )
```

### Cycle Detection

Uses Kahn's algorithm (topological sort). Builds adjacency from both `depends_on` edges and conditional `next:` forward edges. If any nodes remain after the sort, there's a cycle — error lists the involved nodes.

### Handler Validation

Calls into `ALL_HANDLERS` registry at load time. This means handlers must be registered before workflows are loaded — which is already the case (handlers registered at import time in `services/__init__.py`).

---

## Workflow Registry

### File: `core/workflow_registry.py` (~100 lines)

```python
from pathlib import Path
from typing import Optional

from core.workflow_loader import WorkflowLoader
from core.models.workflow_definition import WorkflowDefinition
from core.errors.workflow_errors import WorkflowValidationError


class WorkflowRegistry:
    """In-memory cache of validated workflow definitions."""

    def __init__(self, workflows_dir: Path):
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._dir = workflows_dir

    def load_all(self) -> int:
        """
        Load all *.yaml from workflows_dir.
        Called once at app startup.
        Fail-fast: raises on first invalid workflow.
        Returns count loaded.
        """
        count = 0
        for path in sorted(self._dir.glob("*.yaml")):
            defn = WorkflowLoader.load(path)
            if defn.workflow in self._workflows:
                raise WorkflowValidationError(
                    workflow_name=defn.workflow,
                    errors=[f"Duplicate workflow name (also in {self._workflows[defn.workflow]})"],
                )
            self._workflows[defn.workflow] = defn
            count += 1
        return count

    def get(self, workflow_name: str) -> Optional[WorkflowDefinition]:
        """Get by name, or None."""
        return self._workflows.get(workflow_name)

    def get_or_raise(self, workflow_name: str) -> WorkflowDefinition:
        """Get by name, or raise WorkflowNotFoundError."""
        defn = self._workflows.get(workflow_name)
        if defn is None:
            raise WorkflowNotFoundError(workflow_name)
        return defn

    def list_workflows(self) -> list[str]:
        """All loaded workflow names."""
        return list(self._workflows.keys())

    def get_reverse_workflow(self, workflow_name: str) -> Optional[str]:
        """Given a forward workflow, return its reversed_by name."""
        defn = self._workflows.get(workflow_name)
        return defn.reversed_by if defn else None
```

---

## Error Handling

### File: `core/errors/workflow_errors.py` (~30 lines)

```python
class WorkflowValidationError(Exception):
    """Raised when a workflow YAML definition is invalid."""
    def __init__(self, workflow_name: str, errors: list[str]):
        self.workflow_name = workflow_name
        self.errors = errors
        super().__init__(
            f"Workflow '{workflow_name}' invalid: {'; '.join(errors)}"
        )


class WorkflowNotFoundError(Exception):
    """Raised when a workflow name is not in the registry."""
    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        super().__init__(f"Workflow not found: '{workflow_name}'")
```

---

## File Layout

```
core/
  workflow_loader.py            # WorkflowLoader (~200 lines)
  workflow_registry.py          # WorkflowRegistry (~100 lines)
  models/
    workflow_definition.py      # All Pydantic models (~300 lines)
    workflow_enums.py           # NodeType, AggregationMode, BackoffStrategy (~30 lines)
  errors/
    workflow_errors.py          # WorkflowValidationError, WorkflowNotFoundError (~30 lines)
workflows/
  hello_world.yaml              # Minimal test workflow (1 task node)
  echo_test.yaml                # Parameter passing test (2-3 task nodes)
```

**Total new code**: ~660 lines across 5 files + 2 YAML workflows.

---

## Testing Strategy

### Unit Tests: Minimal, Structural (~10 tests)

File: `tests/test_workflow_loader.py`

Purpose: Prevent regressions in basic parsing. NOT a quality gate.

| Test | What |
|------|------|
| Valid simple workflow loads | hello_world.yaml parses without error |
| Valid complex workflow loads | Zarr ingest with fan_out/fan_in parses correctly |
| Each node type parses to correct union variant | TaskNode, ConditionalNode, FanOutNode, FanInNode |
| Wrong fields for type rejected | `handler` on fan_in → Pydantic error |
| Cycle detected | A→B→A raises WorkflowValidationError |
| Missing handler rejected | `handler: nonexistent` raises error |
| Missing dependency ref rejected | `depends_on: [typo]` raises error |
| Conditional without default rejected | No `default: true` branch → error |
| Fan-in without fan-out dep rejected | fan_in depends_on a task → error |
| Duplicate workflow name rejected | Two YAMLs with same `workflow:` → error |

### Agent Pipelines: Quality Gate

- **COMPETE**: Adversarial review of loader code post-implementation. Crafts edge-case YAMLs, looks for validation bypasses.
- **SIEGE**: End-to-end regression once loader is integrated with DAG tables and initializer.

Unit tests are scaffolding. Agent pipelines are the quality gate.

---

## Structural Validations Summary

| # | Validation | Catches |
|---|-----------|---------|
| 1 | No cycles (topological sort on `depends_on` + conditional `next:` edges) | Circular dependency chains |
| 2 | `depends_on` references exist (after stripping `?` suffix) | Typos in dependency names |
| 3 | Conditional `next:` references exist | Routing to nonexistent nodes |
| 4 | Conditional has `default: true` branch | Non-exhaustive routing |
| 5 | Fan-in `depends_on` includes exactly one `fan_out` node | Meaningless or ambiguous fan-in |
| 6 | All handlers exist in `ALL_HANDLERS` (task nodes + fan_out task templates) | Missing handler implementations |
| 7 | `params:` list items exist in `parameters:` | Referencing undeclared parameters |
| 8 | All nodes reachable from root | Orphaned disconnected subgraphs |
| 9 | `receives:` node references exist | `"nonexistent.result.field"` caught at load time (node name portion only; field path is runtime) |
| 10 | `when:` only on task nodes | Conditional/fan_out/fan_in do not support `when:` — use conditional node for branching |

All validations collect errors and report together — not one-at-a-time.

---

## Integration Points

| Consumer | How It Uses WorkflowDefinition |
|----------|-------------------------------|
| **DAG Initializer** (Story 5.3) | Reads `nodes` dict → creates `workflow_tasks` + `workflow_task_deps` rows |
| **DAG Orchestrator** (Story 5.5) | Reads node types to decide behavior: promote task, evaluate conditional, expand fan_out, aggregate fan_in |
| **Parameter Resolver** (Story 5.4) | Reads `receives:` mappings and `FanOutTaskDef.params` templates |
| **Gateway Submit** (Story 5.8) | Validates parameters against `parameters:` schema, snapshots `definition` JSONB |
| **Platform Status** (Story 5.8) | Reads node names for progress reporting ("running: create_cog") |

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Explicit node types | 4 types: task, conditional, fan_out, fan_in | DAG operations are explicit, not inferred from field presence |
| Discriminated union | Separate Pydantic model per type | Eliminates None ambiguity — each model has only its own fields |
| No START/END nodes | Inferred from graph structure | Root nodes (no deps) = start. All terminal = end. No boilerplate. |
| Explicit fan_in | Separate node type, not implicit | Named aggregation point with configurable mode |
| `depends_on` backward pointers | Not `next:` forward pointers | Better for DAGs. Exception: conditional `next:` for routing. |
| `type: task` is default | Can omit `type:` field | Simple workflows stay clean |
| Fail-fast on load | Registry raises on first invalid workflow | Don't start the app with broken workflows |
| Collect all validation errors | Report together, not one-at-a-time | YAML author fixes everything in one pass |
| Optional deps via `?` suffix | `depends_on: [rechunk?]` tolerates skipped | Essential for conditional workflows where `when:` may skip nodes |
| Conditional `next:` = implicit dep | Target nodes don't need `depends_on` | Routing creates the edge; redundant declaration allowed but not required |
| Jinja2 scoped to fan-out only | `{{ item }}`, `{{ index }}` in `task.params` | All other param resolution uses `receives:` dotted-path lookup |
| Fan-out/fan-in as explicit types | Separate from task nodes | Supersedes V10_MIGRATION.md's inline `fan_out:` field approach |
| ParameterDef.type is Literal | Enum of 6 types, not free string | Catches typos at load time |
| Branches min_length=2 | Pydantic constraint | Conditional must have at least 2 branches |

---

*Spec created: 16 MAR 2026*
*Story: 5.1 — Workflow Loader + YAML Schema*
*Author: Claude + Robert Harrison*
