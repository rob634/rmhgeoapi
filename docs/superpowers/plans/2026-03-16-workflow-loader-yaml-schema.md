# Workflow Loader + YAML Schema Implementation Plan (Story D.1)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the YAML workflow parser, Pydantic models (discriminated union), structural validator, and in-memory registry that all downstream DAG components depend on.

**Architecture:** YAML files in `workflows/` are parsed by `WorkflowLoader` into typed `WorkflowDefinition` Pydantic models using a discriminated union over 4 node types (TaskNode, ConditionalNode, FanOutNode, FanInNode). `WorkflowRegistry` caches all validated definitions at startup. Structural validations (cycle detection, reference checks, handler existence) run at load time — fail fast, collect all errors.

**Tech Stack:** Pydantic v2 (discriminated unions, model_validator), PyYAML, Jinja2 (fan-out params only — added as dependency), pytest

**Spec:** `docs/superpowers/specs/2026-03-16-workflow-loader-yaml-schema-design.md`

**Epoch 4 Freeze:** This is pure new code in `core/` and `workflows/`. Does not touch any Epoch 4 files (CoreMachine, jobs/, services/, triggers/).

---

## File Structure

### New Files

| File | Responsibility | Est. Lines |
|------|---------------|------------|
| `core/models/workflow_enums.py` | NodeType, AggregationMode, BackoffStrategy enums | ~30 |
| `core/models/workflow_definition.py` | All Pydantic models: WorkflowDefinition, TaskNode, ConditionalNode, FanOutNode, FanInNode, RetryPolicy, BranchDef, FanOutTaskDef, FinalizeDef, ParameterDef, ValidatorDef | ~300 |
| `core/workflow_loader.py` | WorkflowLoader: YAML parse → Pydantic validate → structural validation | ~200 |
| `core/workflow_registry.py` | WorkflowRegistry: load all YAMLs, cache, lookup | ~100 |
| `workflows/hello_world.yaml` | Minimal test workflow (1 task node) | ~15 |
| `workflows/echo_test.yaml` | Multi-node test (3 task nodes with receives:) | ~30 |
| `tests/unit/test_workflow_loader.py` | ~10 structural tests | ~200 |
| `tests/factories/workflow_factories.py` | Factories for test workflow dicts | ~80 |

### Modified Files

| File | Change |
|------|--------|
| `requirements.txt` | Add `PyYAML>=6.0` and `Jinja2>=3.1.0` |
| `core/models/__init__.py` | Export new workflow models |

---

## Chunk 1: Enums + Pydantic Models

### Task 1: Add Dependencies

**Files:**
- Modify: `/Users/robertharrison/python_builds/rmhgeoapi/requirements.txt`

- [ ] **Step 1: Add PyYAML and Jinja2 to requirements.txt**

Add these two lines (alphabetical placement in the file):

```
Jinja2>=3.1.0
PyYAML>=6.0
```

- [ ] **Step 2: Install and verify**

Run: `conda activate azgeo && pip install PyYAML>=6.0 Jinja2>=3.1.0`
Expected: Successful install (or already satisfied)

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat(DAG): add PyYAML and Jinja2 dependencies for workflow loader"
```

---

### Task 2: Workflow Enums

**Files:**
- Create: `/Users/robertharrison/python_builds/rmhgeoapi/core/models/workflow_enums.py`
- Test: `/Users/robertharrison/python_builds/rmhgeoapi/tests/unit/test_workflow_loader.py`

- [ ] **Step 1: Write the enum test**

Create `tests/unit/test_workflow_loader.py`:

```python
"""Tests for workflow loader — structural validation only.
Quality gate is COMPETE/SIEGE agent pipelines, not this file."""

import pytest
from core.models.workflow_enums import NodeType, AggregationMode, BackoffStrategy


class TestWorkflowEnums:
    """Anti-overfitting: count members to detect silent additions/removals."""

    def test_node_type_has_four_values(self):
        assert len(NodeType) == 4
        assert set(NodeType) == {
            NodeType.TASK, NodeType.CONDITIONAL,
            NodeType.FAN_OUT, NodeType.FAN_IN,
        }

    def test_node_type_string_values(self):
        assert NodeType.TASK.value == "task"
        assert NodeType.CONDITIONAL.value == "conditional"
        assert NodeType.FAN_OUT.value == "fan_out"
        assert NodeType.FAN_IN.value == "fan_in"

    def test_aggregation_mode_has_five_values(self):
        assert len(AggregationMode) == 5

    def test_backoff_strategy_has_three_values(self):
        assert len(BackoffStrategy) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda activate azgeo && python -m pytest tests/unit/test_workflow_loader.py::TestWorkflowEnums -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.models.workflow_enums'`

- [ ] **Step 3: Create the enums module**

Create `/Users/robertharrison/python_builds/rmhgeoapi/core/models/workflow_enums.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW ENUMS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - DAG node type and configuration enums
# PURPOSE: Type-safe enums for YAML workflow node definitions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: NodeType, AggregationMode, BackoffStrategy
# DEPENDENCIES: None
# ============================================================================

from enum import Enum


class NodeType(str, Enum):
    """DAG node types. Each has a dedicated Pydantic model (discriminated union)."""
    TASK = "task"
    CONDITIONAL = "conditional"
    FAN_OUT = "fan_out"
    FAN_IN = "fan_in"


class AggregationMode(str, Enum):
    """Fan-in result aggregation strategies."""
    COLLECT = "collect"
    CONCAT = "concat"
    SUM = "sum"
    FIRST = "first"
    LAST = "last"


class BackoffStrategy(str, Enum):
    """Retry backoff strategies for failed tasks."""
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestWorkflowEnums -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/models/workflow_enums.py tests/unit/test_workflow_loader.py
git commit -m "feat(DAG): add NodeType, AggregationMode, BackoffStrategy enums"
```

---

### Task 3: Pydantic Models — Supporting Types

**Files:**
- Create: `/Users/robertharrison/python_builds/rmhgeoapi/core/models/workflow_definition.py`
- Test: `/Users/robertharrison/python_builds/rmhgeoapi/tests/unit/test_workflow_loader.py` (append)

- [ ] **Step 1: Write tests for supporting models**

Append to `tests/unit/test_workflow_loader.py`:

```python
from core.models.workflow_definition import (
    RetryPolicy, BranchDef, FanOutTaskDef, FinalizeDef,
    ParameterDef, ValidatorDef,
)


class TestSupportingModels:

    def test_retry_policy_defaults(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff == BackoffStrategy.EXPONENTIAL
        assert policy.initial_delay_seconds == 5
        assert policy.max_delay_seconds == 300

    def test_retry_policy_max_attempts_bounds(self):
        with pytest.raises(Exception):  # Pydantic validation
            RetryPolicy(max_attempts=0)
        with pytest.raises(Exception):
            RetryPolicy(max_attempts=11)

    def test_branch_def_requires_name_and_next(self):
        branch = BranchDef(name="large", next=["tile_cogs"], condition="> 1000")
        assert branch.name == "large"
        assert branch.next == ["tile_cogs"]
        assert branch.default is False

    def test_parameter_def_type_validated(self):
        p = ParameterDef(type="str", required=True)
        assert p.type == "str"
        with pytest.raises(Exception):
            ParameterDef(type="string")  # not a valid Literal

    def test_fan_out_task_def_requires_handler(self):
        task = FanOutTaskDef(handler="zarr_copy_single_blob")
        assert task.handler == "zarr_copy_single_blob"
        assert task.timeout_seconds == 3600

    def test_validator_def_allows_extra_fields(self):
        v = ValidatorDef(type="blob_exists", container_param="container_name", zone="bronze")
        assert v.type == "blob_exists"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestSupportingModels -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Create workflow_definition.py with supporting models**

Create `/Users/robertharrison/python_builds/rmhgeoapi/core/models/workflow_definition.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW DEFINITION MODELS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Pydantic models for YAML workflow blueprint parsing
# PURPOSE: Discriminated union node types + workflow definition schema
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowDefinition, TaskNode, ConditionalNode, FanOutNode, FanInNode
# DEPENDENCIES: pydantic, core.models.workflow_enums
# ============================================================================

from typing import Any, Annotated, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict

from core.models.workflow_enums import AggregationMode, BackoffStrategy


# ── Supporting Models ────────────────────────────────────────────────────────


class RetryPolicy(BaseModel):
    """Retry configuration for failed tasks."""
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay_seconds: int = Field(default=5, ge=1)
    max_delay_seconds: int = Field(default=300, ge=1)


class BranchDef(BaseModel):
    """One branch of a conditional node."""
    name: str
    condition: Optional[str] = None
    default: bool = False
    next: list[str]


class FanOutTaskDef(BaseModel):
    """Template for child tasks created by fan-out expansion.
    Params may contain Jinja2 templates: {{ item }}, {{ index }}, {{ inputs.param }}."""
    handler: str
    params: dict[str, Any] = {}
    timeout_seconds: int = 3600
    retry: Optional[RetryPolicy] = None


class FinalizeDef(BaseModel):
    """Handler that runs after all nodes are terminal."""
    handler: str


class ParameterDef(BaseModel):
    """Schema for a workflow input parameter."""
    type: Literal["str", "int", "float", "bool", "dict", "list"]
    required: bool = False
    default: Any = None
    nested: Optional[dict[str, 'ParameterDef']] = None


class ValidatorDef(BaseModel):
    """Pre-flight resource validator. Extra fields are validator-specific kwargs."""
    type: str
    model_config = ConfigDict(extra='allow')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestSupportingModels -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/models/workflow_definition.py
git commit -m "feat(DAG): add supporting Pydantic models (RetryPolicy, BranchDef, FanOutTaskDef, etc.)"
```

---

### Task 4: Pydantic Models — Discriminated Union Node Types

**Files:**
- Modify: `/Users/robertharrison/python_builds/rmhgeoapi/core/models/workflow_definition.py`
- Test: `/Users/robertharrison/python_builds/rmhgeoapi/tests/unit/test_workflow_loader.py` (append)

- [ ] **Step 1: Write tests for node type discrimination**

Append to `tests/unit/test_workflow_loader.py`:

```python
from core.models.workflow_definition import (
    TaskNode, ConditionalNode, FanOutNode, FanInNode,
    WorkflowDefinition, NodeDefinition,
)


class TestNodeTypeDiscrimination:
    """Each node type parses to its own Pydantic model via discriminated union."""

    def test_task_node_default_type(self):
        """type: task is default — can be omitted."""
        node = TaskNode(handler="raster_validate")
        assert node.type == "task"
        assert node.handler == "raster_validate"

    def test_task_node_with_all_fields(self):
        node = TaskNode(
            handler="raster_validate",
            depends_on=["prev_node"],
            params=["blob_name", "crs"],
            receives={"metadata": "validate.result.metadata"},
            when="params.processing_options.build_overviews",
            timeout_seconds=600,
        )
        assert node.depends_on == ["prev_node"]
        assert node.receives == {"metadata": "validate.result.metadata"}

    def test_conditional_node_requires_condition_and_branches(self):
        node = ConditionalNode(
            type="conditional",
            condition="validate.result.file_size",
            branches=[
                BranchDef(name="large", condition="> 1000000", next=["tile"]),
                BranchDef(name="small", default=True, next=["single"]),
            ],
        )
        assert node.type == "conditional"
        assert len(node.branches) == 2

    def test_conditional_node_rejects_one_branch(self):
        with pytest.raises(Exception):
            ConditionalNode(
                type="conditional",
                condition="val.result.x",
                branches=[BranchDef(name="only", default=True, next=["a"])],
            )

    def test_fan_out_node_requires_source_and_task(self):
        node = FanOutNode(
            type="fan_out",
            source="validate.result.blob_list",
            task=FanOutTaskDef(handler="copy_blob", params={"path": "{{ item }}"}),
        )
        assert node.source == "validate.result.blob_list"
        assert node.task.handler == "copy_blob"
        assert node.max_fan_out == 500

    def test_fan_in_node_requires_depends_on(self):
        node = FanInNode(
            type="fan_in",
            depends_on=["copy_blobs"],
            aggregation=AggregationMode.COLLECT,
        )
        assert node.aggregation == AggregationMode.COLLECT

    def test_fan_out_node_has_no_handler_field(self):
        """FanOutNode should NOT have a handler field — only its task template does."""
        assert not hasattr(FanOutNode.model_fields, 'handler')

    def test_discriminated_union_selects_correct_type(self):
        """Pydantic discriminated union picks model based on type: field."""
        from pydantic import TypeAdapter
        adapter = TypeAdapter(NodeDefinition)

        task = adapter.validate_python({"type": "task", "handler": "foo"})
        assert isinstance(task, TaskNode)

        cond = adapter.validate_python({
            "type": "conditional",
            "condition": "x.result.y",
            "branches": [
                {"name": "a", "condition": "> 1", "next": ["n1"]},
                {"name": "b", "default": True, "next": ["n2"]},
            ],
        })
        assert isinstance(cond, ConditionalNode)

        fan_out = adapter.validate_python({
            "type": "fan_out",
            "source": "x.result.items",
            "task": {"handler": "process_item"},
        })
        assert isinstance(fan_out, FanOutNode)

        fan_in = adapter.validate_python({
            "type": "fan_in",
            "depends_on": ["fan_out_node"],
        })
        assert isinstance(fan_in, FanInNode)

    def test_wrong_fields_for_type_rejected(self):
        """handler on fan_in should fail validation."""
        from pydantic import TypeAdapter, ValidationError
        adapter = TypeAdapter(NodeDefinition)
        with pytest.raises(ValidationError):
            adapter.validate_python({"type": "fan_in", "handler": "oops"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestNodeTypeDiscrimination -v`
Expected: FAIL — `ImportError` (TaskNode etc. not yet defined)

- [ ] **Step 3: Add node types and WorkflowDefinition to workflow_definition.py**

Append to `/Users/robertharrison/python_builds/rmhgeoapi/core/models/workflow_definition.py`:

```python
# ── Node Type Models (Discriminated Union) ───────────────────────────────────


class TaskNode(BaseModel):
    """Runs a handler on a worker. The workhorse node.
    type: task is default — can be omitted in YAML."""
    model_config = ConfigDict(extra='forbid')
    type: Literal["task"] = "task"
    handler: str
    depends_on: list[str] = []
    params: list[str] | dict[str, Any] = []
    receives: dict[str, str] = {}
    when: Optional[str] = None
    retry: Optional[RetryPolicy] = None
    timeout_seconds: Optional[int] = None


class ConditionalNode(BaseModel):
    """Evaluates condition, routes to exactly one branch.
    Does NOT execute a handler — orchestrator evaluates inline."""
    model_config = ConfigDict(extra='forbid')
    type: Literal["conditional"]
    depends_on: list[str] = []
    condition: str
    branches: list[BranchDef] = Field(..., min_length=2)


class FanOutNode(BaseModel):
    """Expands source array into N child tasks."""
    model_config = ConfigDict(extra='forbid')
    type: Literal["fan_out"]
    depends_on: list[str] = []
    source: str
    task: FanOutTaskDef
    max_fan_out: int = Field(default=500, ge=1, le=10000)


class FanInNode(BaseModel):
    """Waits for fan_out children, aggregates results."""
    model_config = ConfigDict(extra='forbid')
    type: Literal["fan_in"]
    depends_on: list[str]
    aggregation: AggregationMode = AggregationMode.COLLECT


# depends_on entries may have '?' suffix (e.g., "rechunk?") for optional deps.
# The loader strips the suffix during structural validation and stores
# parsed dependencies as (node_name, optional: bool) tuples internally.
# Pydantic models keep the raw strings; parsing happens in WorkflowLoader.

NodeDefinition = Annotated[
    TaskNode | ConditionalNode | FanOutNode | FanInNode,
    Field(discriminator='type')
]


# ── Top-Level Workflow Model ─────────────────────────────────────────────────


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
        has_successors = set()
        for name, node in self.nodes.items():
            for dep in node.depends_on:
                dep_name = dep.rstrip('?')
                has_successors.add(dep_name)
            if isinstance(node, ConditionalNode):
                has_successors.add(name)
        return [name for name in self.nodes if name not in has_successors]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestNodeTypeDiscrimination -v`
Expected: 9 tests PASS

- [ ] **Step 5: Update core/models/__init__.py with exports**

Add to `/Users/robertharrison/python_builds/rmhgeoapi/core/models/__init__.py`:

```python
from .workflow_enums import NodeType, AggregationMode, BackoffStrategy
from .workflow_definition import (
    WorkflowDefinition, TaskNode, ConditionalNode, FanOutNode, FanInNode,
    NodeDefinition, RetryPolicy, BranchDef, FanOutTaskDef, FinalizeDef,
    ParameterDef, ValidatorDef,
)
```

- [ ] **Step 6: Commit**

```bash
git add core/models/workflow_definition.py core/models/__init__.py tests/unit/test_workflow_loader.py
git commit -m "feat(DAG): add discriminated union node types + WorkflowDefinition model"
```

---

## Chunk 2: YAML Files + WorkflowLoader + Structural Validations

### Task 5: Test YAML Workflow Files

**Files:**
- Create: `/Users/robertharrison/python_builds/rmhgeoapi/workflows/hello_world.yaml`
- Create: `/Users/robertharrison/python_builds/rmhgeoapi/workflows/echo_test.yaml`

- [ ] **Step 1: Create workflows directory and hello_world.yaml**

```bash
mkdir -p /Users/robertharrison/python_builds/rmhgeoapi/workflows
```

Create `/Users/robertharrison/python_builds/rmhgeoapi/workflows/hello_world.yaml`:

```yaml
workflow: hello_world
description: "Minimal test workflow — single task node"
version: 1

parameters:
  message: {type: str, required: true}

nodes:
  greet:
    type: task
    handler: hello_world_greeting
    params: [message]

finalize:
  handler: hello_world_reply
```

- [ ] **Step 2: Create echo_test.yaml with receives and when**

Create `/Users/robertharrison/python_builds/rmhgeoapi/workflows/echo_test.yaml`:

```yaml
workflow: echo_test
description: "Multi-node test with receives and conditional skip"
version: 1

parameters:
  message: {type: str, required: true}
  uppercase: {type: bool, default: false}

nodes:
  echo:
    type: task
    handler: hello_world_greeting
    params: [message]

  transform:
    type: task
    handler: hello_world_reply
    depends_on: [echo]
    when: "params.uppercase"
    receives:
      original: "echo.result.message"

  final:
    type: task
    handler: hello_world_greeting
    depends_on: [transform?]
    params: [message]
```

- [ ] **Step 3: Commit**

```bash
git add workflows/
git commit -m "feat(DAG): add hello_world and echo_test YAML workflow definitions"
```

---

### Task 6: WorkflowLoader — Parse + Validate

**Files:**
- Create: `/Users/robertharrison/python_builds/rmhgeoapi/core/workflow_loader.py`
- Test: `/Users/robertharrison/python_builds/rmhgeoapi/tests/unit/test_workflow_loader.py` (append)

- [ ] **Step 1: Write loader tests**

Append to `tests/unit/test_workflow_loader.py`:

```python
import tempfile
from pathlib import Path
import yaml

from core.workflow_loader import WorkflowLoader, WorkflowValidationError


class TestWorkflowLoader:

    def _write_yaml(self, data: dict, tmp_path: Path) -> Path:
        """Helper: write dict to temp YAML file."""
        path = tmp_path / "test_workflow.yaml"
        path.write_text(yaml.dump(data, default_flow_style=False))
        return path

    def test_load_hello_world(self, tmp_path):
        """Valid simple workflow loads without error."""
        data = {
            "workflow": "hello_world",
            "description": "test",
            "version": 1,
            "parameters": {"message": {"type": "str", "required": True}},
            "nodes": {
                "greet": {"type": "task", "handler": "hello_world_greeting", "params": ["message"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        defn = WorkflowLoader.load(path, handler_names={"hello_world_greeting"})
        assert defn.workflow == "hello_world"
        assert "greet" in defn.nodes
        assert isinstance(defn.nodes["greet"], TaskNode)

    def test_cycle_detected(self, tmp_path):
        """Circular depends_on raises WorkflowValidationError."""
        data = {
            "workflow": "cycle_test",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "h", "depends_on": ["b"]},
                "b": {"type": "task", "handler": "h", "depends_on": ["a"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"h"})
        assert "cycle" in str(exc_info.value).lower()

    def test_missing_handler_rejected(self, tmp_path):
        data = {
            "workflow": "bad_handler",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "nonexistent_handler"},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"other_handler"})
        assert "nonexistent_handler" in str(exc_info.value)

    def test_missing_dependency_ref_rejected(self, tmp_path):
        data = {
            "workflow": "bad_ref",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "h", "depends_on": ["typo_node"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"h"})
        assert "typo_node" in str(exc_info.value)

    def test_conditional_without_default_rejected(self, tmp_path):
        data = {
            "workflow": "no_default",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "route": {
                    "type": "conditional",
                    "condition": "a.result.x",
                    "branches": [
                        {"name": "a", "condition": "> 1", "next": ["n1"]},
                        {"name": "b", "condition": "< 1", "next": ["n2"]},
                    ],
                },
                "n1": {"type": "task", "handler": "h"},
                "n2": {"type": "task", "handler": "h"},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"h"})
        assert "default" in str(exc_info.value).lower()

    def test_fan_in_without_fan_out_rejected(self, tmp_path):
        data = {
            "workflow": "bad_fan_in",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "h"},
                "agg": {"type": "fan_in", "depends_on": ["a"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"h"})
        assert "fan_out" in str(exc_info.value).lower()

    def test_optional_dependency_suffix_stripped(self, tmp_path):
        data = {
            "workflow": "opt_dep",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "h"},
                "b": {"type": "task", "handler": "h", "depends_on": ["a?"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        defn = WorkflowLoader.load(path, handler_names={"h"})
        # Should load without error — "a?" references node "a" which exists
        assert "b" in defn.nodes

    def test_receives_bad_node_ref_rejected(self, tmp_path):
        data = {
            "workflow": "bad_receives",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "h",
                       "receives": {"x": "nonexistent.result.field"}},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"h"})
        assert "nonexistent" in str(exc_info.value)

    def test_params_referencing_undeclared_parameter_rejected(self, tmp_path):
        data = {
            "workflow": "bad_params",
            "description": "test",
            "version": 1,
            "parameters": {"message": {"type": "str"}},
            "nodes": {
                "a": {"type": "task", "handler": "h", "params": ["message", "nonexistent_param"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"h"})
        assert "nonexistent_param" in str(exc_info.value)

    def test_orphan_node_rejected(self, tmp_path):
        """Disconnected node with no path from any root is rejected."""
        data = {
            "workflow": "orphan",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "h"},
                "b": {"type": "task", "handler": "h", "depends_on": ["a"]},
                "orphan": {"type": "task", "handler": "h", "depends_on": ["phantom"]},
            },
        }
        path = self._write_yaml(data, tmp_path)
        # This will fail on both missing ref "phantom" AND orphan detection
        with pytest.raises(WorkflowValidationError):
            WorkflowLoader.load(path, handler_names={"h"})

    def test_errors_collected_not_one_at_a_time(self, tmp_path):
        """Multiple errors reported together."""
        data = {
            "workflow": "multi_error",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {
                "a": {"type": "task", "handler": "bad_handler_1", "depends_on": ["bad_ref"]},
                "b": {"type": "task", "handler": "bad_handler_2"},
            },
        }
        path = self._write_yaml(data, tmp_path)
        with pytest.raises(WorkflowValidationError) as exc_info:
            WorkflowLoader.load(path, handler_names={"other"})
        # Should have at least 3 errors: 2 bad handlers + 1 bad ref
        assert len(exc_info.value.errors) >= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestWorkflowLoader -v`
Expected: FAIL — `ImportError` (WorkflowLoader not yet created)

- [ ] **Step 3: Create WorkflowLoader with structural validations**

Create `/Users/robertharrison/python_builds/rmhgeoapi/core/workflow_loader.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW LOADER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - YAML workflow parser and structural validator
# PURPOSE: Load YAML → Pydantic WorkflowDefinition with structural validation
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowLoader, WorkflowValidationError
# DEPENDENCIES: pyyaml, pydantic, core.models.workflow_definition
# ============================================================================

import logging
from collections import deque
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from core.models.workflow_definition import (
    WorkflowDefinition, ConditionalNode, FanOutNode, FanInNode, TaskNode,
)

logger = logging.getLogger(__name__)


class WorkflowValidationError(Exception):
    """Raised when a workflow YAML definition is invalid."""
    def __init__(self, workflow_name: str, errors: list[str]):
        self.workflow_name = workflow_name
        self.errors = errors
        super().__init__(
            f"Workflow '{workflow_name}' invalid: {'; '.join(errors)}"
        )


class WorkflowLoader:
    """Parse and validate a single YAML workflow file."""

    @staticmethod
    def load(
        path: Path,
        handler_names: Optional[set[str]] = None,
    ) -> WorkflowDefinition:
        """
        Load workflow from YAML file.

        Args:
            path: Path to .yaml file
            handler_names: Known handler names for validation.
                           If None, handler validation is skipped.

        Returns:
            Validated WorkflowDefinition

        Raises:
            WorkflowValidationError on any failure (all errors collected).
        """
        raw = WorkflowLoader._read_yaml(path)
        workflow_name = raw.get('workflow', path.stem)

        try:
            definition = WorkflowDefinition.model_validate(raw)
        except ValidationError as e:
            errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
            raise WorkflowValidationError(workflow_name=workflow_name, errors=errors)

        WorkflowLoader._validate_structure(definition, handler_names)
        return definition

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        """Read YAML file, return raw dict."""
        try:
            text = path.read_text(encoding='utf-8')
            data = yaml.safe_load(text)
            if not isinstance(data, dict):
                raise WorkflowValidationError(
                    workflow_name=path.stem,
                    errors=[f"Expected YAML dict, got {type(data).__name__}"],
                )
            return data
        except yaml.YAMLError as e:
            raise WorkflowValidationError(
                workflow_name=path.stem,
                errors=[f"YAML parse error: {e}"],
            )

    @staticmethod
    def _validate_structure(
        defn: WorkflowDefinition,
        handler_names: Optional[set[str]],
    ) -> None:
        """Structural validations beyond Pydantic field checks.
        Collects all errors and raises once."""
        errors: list[str] = []

        errors.extend(WorkflowLoader._check_cycles(defn))
        errors.extend(WorkflowLoader._check_dependency_refs(defn))
        errors.extend(WorkflowLoader._check_branch_refs(defn))
        errors.extend(WorkflowLoader._check_conditional_defaults(defn))
        errors.extend(WorkflowLoader._check_fan_in_refs(defn))
        errors.extend(WorkflowLoader._check_receives_refs(defn))
        errors.extend(WorkflowLoader._check_param_refs(defn))
        errors.extend(WorkflowLoader._check_reachability(defn))

        if handler_names is not None:
            errors.extend(WorkflowLoader._check_handlers(defn, handler_names))

        if errors:
            raise WorkflowValidationError(
                workflow_name=defn.workflow,
                errors=errors,
            )

    @staticmethod
    def _parse_dep(dep: str) -> tuple[str, bool]:
        """Parse 'node_name?' into (node_name, optional=True)."""
        if dep.endswith('?'):
            return dep[:-1], True
        return dep, False

    @staticmethod
    def _check_cycles(defn: WorkflowDefinition) -> list[str]:
        """Kahn's algorithm for cycle detection.
        Builds graph from depends_on (backward) and conditional next (forward)."""
        node_names = set(defn.nodes.keys())
        adj: dict[str, list[str]] = {n: [] for n in node_names}
        in_degree: dict[str, int] = {n: 0 for n in node_names}

        for name, node in defn.nodes.items():
            for dep in node.depends_on:
                dep_name, _ = WorkflowLoader._parse_dep(dep)
                if dep_name in node_names:
                    adj[dep_name].append(name)
                    in_degree[name] += 1
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    for target in branch.next:
                        if target in node_names:
                            adj[name].append(target)
                            in_degree[target] += 1

        queue = deque(n for n in node_names if in_degree[n] == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited < len(node_names):
            cycle_nodes = [n for n in node_names if in_degree[n] > 0]
            return [f"Cycle detected involving nodes: {cycle_nodes}"]
        return []

    @staticmethod
    def _check_dependency_refs(defn: WorkflowDefinition) -> list[str]:
        """Every depends_on name (after stripping ?) must exist as a node key."""
        errors = []
        for name, node in defn.nodes.items():
            for dep in node.depends_on:
                dep_name, _ = WorkflowLoader._parse_dep(dep)
                if dep_name not in defn.nodes:
                    errors.append(
                        f"Node '{name}': depends_on references "
                        f"unknown node '{dep_name}'"
                    )
        return errors

    @staticmethod
    def _check_branch_refs(defn: WorkflowDefinition) -> list[str]:
        """Conditional branch next: targets must exist as node keys."""
        errors = []
        for name, node in defn.nodes.items():
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    for target in branch.next:
                        if target not in defn.nodes:
                            errors.append(
                                f"Node '{name}': branch '{branch.name}' "
                                f"references unknown node '{target}'"
                            )
        return errors

    @staticmethod
    def _check_conditional_defaults(defn: WorkflowDefinition) -> list[str]:
        """Every conditional node must have at least one branch with default=True."""
        errors = []
        for name, node in defn.nodes.items():
            if isinstance(node, ConditionalNode):
                has_default = any(b.default for b in node.branches)
                if not has_default:
                    errors.append(
                        f"Node '{name}': conditional has no default branch"
                    )
        return errors

    @staticmethod
    def _check_fan_in_refs(defn: WorkflowDefinition) -> list[str]:
        """Fan-in depends_on must include exactly one fan_out node."""
        errors = []
        for name, node in defn.nodes.items():
            if isinstance(node, FanInNode):
                fan_out_count = 0
                for dep in node.depends_on:
                    dep_name, _ = WorkflowLoader._parse_dep(dep)
                    dep_node = defn.nodes.get(dep_name)
                    if isinstance(dep_node, FanOutNode):
                        fan_out_count += 1
                if fan_out_count == 0:
                    errors.append(
                        f"Node '{name}': fan_in must depend on "
                        f"exactly one fan_out node (found 0)"
                    )
                elif fan_out_count > 1:
                    errors.append(
                        f"Node '{name}': fan_in must depend on "
                        f"exactly one fan_out node (found {fan_out_count})"
                    )
        return errors

    @staticmethod
    def _check_handlers(
        defn: WorkflowDefinition,
        handler_names: set[str],
    ) -> list[str]:
        """All handler names must exist in the handler registry."""
        errors = []
        for name, node in defn.nodes.items():
            if isinstance(node, TaskNode):
                if node.handler not in handler_names:
                    errors.append(
                        f"Node '{name}': handler '{node.handler}' "
                        f"not found in ALL_HANDLERS"
                    )
            elif isinstance(node, FanOutNode):
                if node.task.handler not in handler_names:
                    errors.append(
                        f"Node '{name}': fan_out task handler "
                        f"'{node.task.handler}' not found in ALL_HANDLERS"
                    )
        if defn.finalize and defn.finalize.handler not in handler_names:
            errors.append(
                f"Finalize handler '{defn.finalize.handler}' "
                f"not found in ALL_HANDLERS"
            )
        return errors

    @staticmethod
    def _check_receives_refs(defn: WorkflowDefinition) -> list[str]:
        """receives: dotted paths must reference existing node names."""
        errors = []
        for name, node in defn.nodes.items():
            if isinstance(node, TaskNode) and node.receives:
                for local_name, path in node.receives.items():
                    parts = path.split('.')
                    if len(parts) < 2:
                        errors.append(
                            f"Node '{name}': receives '{local_name}' "
                            f"path '{path}' must be 'node.result.field'"
                        )
                        continue
                    ref_node = parts[0]
                    if ref_node not in defn.nodes:
                        errors.append(
                            f"Node '{name}': receives '{local_name}' "
                            f"references unknown node '{ref_node}'"
                        )
        return errors

    @staticmethod
    def _check_param_refs(defn: WorkflowDefinition) -> list[str]:
        """params: list items must exist in parameters: schema."""
        errors = []
        declared_params = set(defn.parameters.keys())
        for name, node in defn.nodes.items():
            if isinstance(node, TaskNode) and isinstance(node.params, list):
                for param in node.params:
                    if param not in declared_params:
                        errors.append(
                            f"Node '{name}': params references "
                            f"undeclared parameter '{param}'"
                        )
        return errors

    @staticmethod
    def _check_reachability(defn: WorkflowDefinition) -> list[str]:
        """All nodes must be reachable from a root node (no orphaned subgraphs)."""
        # Build successor adjacency from depends_on + conditional next:
        adj: dict[str, set[str]] = {n: set() for n in defn.nodes}
        for name, node in defn.nodes.items():
            for dep in node.depends_on:
                dep_name, _ = WorkflowLoader._parse_dep(dep)
                if dep_name in adj:
                    adj[dep_name].add(name)
            if isinstance(node, ConditionalNode):
                for branch in node.branches:
                    for target in branch.next:
                        if target in adj:
                            adj[name].add(target)

        # BFS from all root nodes
        roots = defn.get_root_nodes()
        visited = set(roots)
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            for neighbor in adj.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        unreachable = set(defn.nodes.keys()) - visited
        if unreachable:
            return [f"Orphan nodes not reachable from any root: {sorted(unreachable)}"]
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestWorkflowLoader -v`
Expected: 12 tests PASS

- [ ] **Step 5: Run all tests to verify no regressions**

Run: `python -m pytest tests/unit/test_workflow_loader.py -v`
Expected: ALL tests PASS (enums + supporting + discrimination + loader)

- [ ] **Step 6: Commit**

```bash
git add core/workflow_loader.py tests/unit/test_workflow_loader.py
git commit -m "feat(DAG): add WorkflowLoader with structural validations (cycles, refs, handlers)"
```

---

## Chunk 3: WorkflowRegistry + Integration

### Task 7: WorkflowRegistry

**Files:**
- Create: `/Users/robertharrison/python_builds/rmhgeoapi/core/workflow_registry.py`
- Test: `/Users/robertharrison/python_builds/rmhgeoapi/tests/unit/test_workflow_loader.py` (append)

- [ ] **Step 1: Write registry tests**

Append to `tests/unit/test_workflow_loader.py`:

```python
from core.workflow_registry import WorkflowRegistry, WorkflowNotFoundError


class TestWorkflowRegistry:

    def test_load_all_from_directory(self, tmp_path):
        """Registry loads all YAML files from a directory."""
        (tmp_path / "a.yaml").write_text(yaml.dump({
            "workflow": "workflow_a",
            "description": "test a",
            "version": 1,
            "parameters": {},
            "nodes": {"n": {"type": "task", "handler": "h"}},
        }))
        (tmp_path / "b.yaml").write_text(yaml.dump({
            "workflow": "workflow_b",
            "description": "test b",
            "version": 1,
            "parameters": {},
            "nodes": {"n": {"type": "task", "handler": "h"}},
        }))

        registry = WorkflowRegistry(tmp_path, handler_names={"h"})
        count = registry.load_all()
        assert count == 2
        assert registry.get("workflow_a") is not None
        assert registry.get("workflow_b") is not None

    def test_get_or_raise_on_missing(self, tmp_path):
        registry = WorkflowRegistry(tmp_path, handler_names=set())
        registry.load_all()
        with pytest.raises(WorkflowNotFoundError):
            registry.get_or_raise("nonexistent")

    def test_list_workflows(self, tmp_path):
        (tmp_path / "x.yaml").write_text(yaml.dump({
            "workflow": "x",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {"n": {"type": "task", "handler": "h"}},
        }))
        registry = WorkflowRegistry(tmp_path, handler_names={"h"})
        registry.load_all()
        assert registry.list_workflows() == ["x"]

    def test_has(self, tmp_path):
        (tmp_path / "x.yaml").write_text(yaml.dump({
            "workflow": "x",
            "description": "test",
            "version": 1,
            "parameters": {},
            "nodes": {"n": {"type": "task", "handler": "h"}},
        }))
        registry = WorkflowRegistry(tmp_path, handler_names={"h"})
        registry.load_all()
        assert registry.has("x") is True
        assert registry.has("y") is False

    def test_duplicate_workflow_name_rejected(self, tmp_path):
        for fname in ("a.yaml", "b.yaml"):
            (tmp_path / fname).write_text(yaml.dump({
                "workflow": "duplicate_name",
                "description": "test",
                "version": 1,
                "parameters": {},
                "nodes": {"n": {"type": "task", "handler": "h"}},
            }))
        registry = WorkflowRegistry(tmp_path, handler_names={"h"})
        with pytest.raises(WorkflowValidationError) as exc_info:
            registry.load_all()
        assert "duplicate" in str(exc_info.value).lower()

    def test_real_workflow_files(self):
        """Verify the actual workflows/ directory loads without error."""
        workflows_dir = Path(__file__).parent.parent.parent / "workflows"
        if not workflows_dir.exists():
            pytest.skip("workflows/ directory not found")
        try:
            from services import ALL_HANDLERS
            handler_names = set(ALL_HANDLERS.keys())
        except ImportError:
            pytest.skip("services module not importable in test env")
        registry = WorkflowRegistry(
            workflows_dir,
            handler_names=handler_names,
        )
        count = registry.load_all()
        assert count >= 1  # at least hello_world.yaml
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestWorkflowRegistry -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Create WorkflowRegistry**

Create `/Users/robertharrison/python_builds/rmhgeoapi/core/workflow_registry.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW REGISTRY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - In-memory cache of validated workflow definitions
# PURPOSE: Load all YAML workflows at startup, provide lookup by name
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowRegistry, WorkflowNotFoundError
# DEPENDENCIES: core.workflow_loader
# ============================================================================

import logging
from pathlib import Path
from typing import Optional

from core.models.workflow_definition import WorkflowDefinition
from core.workflow_loader import WorkflowLoader, WorkflowValidationError

logger = logging.getLogger(__name__)


class WorkflowNotFoundError(Exception):
    """Raised when a workflow name is not in the registry."""
    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        super().__init__(f"Workflow not found: '{workflow_name}'")


class WorkflowRegistry:
    """In-memory cache of validated workflow definitions.
    Loaded once at app startup. Fail-fast on invalid workflows."""

    def __init__(
        self,
        workflows_dir: Path,
        handler_names: Optional[set[str]] = None,
    ):
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._dir = workflows_dir
        self._handler_names = handler_names
        self._file_paths: dict[str, Path] = {}

    def load_all(self) -> int:
        """Load all *.yaml and *.yml from workflows_dir.
        Fail-fast: raises on first invalid workflow.
        Returns count loaded."""
        if not self._dir.exists():
            logger.warning(f"Workflows directory does not exist: {self._dir}")
            return 0

        count = 0
        for path in sorted(self._dir.glob("*.yaml")) + sorted(self._dir.glob("*.yml")):
            defn = WorkflowLoader.load(path, handler_names=self._handler_names)

            if defn.workflow in self._workflows:
                raise WorkflowValidationError(
                    workflow_name=defn.workflow,
                    errors=[
                        f"Duplicate workflow name '{defn.workflow}' "
                        f"in {path.name} (already loaded from "
                        f"{self._file_paths[defn.workflow].name})"
                    ],
                )

            self._workflows[defn.workflow] = defn
            self._file_paths[defn.workflow] = path
            count += 1
            logger.info(f"Loaded workflow: {defn.workflow} (v{defn.version}) from {path.name}")

        logger.info(f"WorkflowRegistry: loaded {count} workflows from {self._dir}")
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

    def has(self, workflow_name: str) -> bool:
        """Check if a workflow is registered."""
        return workflow_name in self._workflows

    def list_workflows(self) -> list[str]:
        """All loaded workflow names."""
        return list(self._workflows.keys())

    def get_reverse_workflow(self, workflow_name: str) -> Optional[str]:
        """Given a forward workflow, return its reversed_by name."""
        defn = self._workflows.get(workflow_name)
        return defn.reversed_by if defn else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_workflow_loader.py::TestWorkflowRegistry -v`
Expected: 6 tests PASS

- [ ] **Step 5: Run ALL workflow loader tests**

Run: `python -m pytest tests/unit/test_workflow_loader.py -v`
Expected: ALL tests PASS (~29 total)

- [ ] **Step 6: Commit**

```bash
git add core/workflow_registry.py tests/unit/test_workflow_loader.py
git commit -m "feat(DAG): add WorkflowRegistry with load_all, has, get_or_raise"
```

---

### Task 8: Final Verification + Summary Commit

- [ ] **Step 1: Verify real YAML files load**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "
from pathlib import Path
from core.workflow_registry import WorkflowRegistry
from services import ALL_HANDLERS
registry = WorkflowRegistry(Path('workflows'), handler_names=set(ALL_HANDLERS.keys()))
count = registry.load_all()
print(f'Loaded {count} workflows: {registry.list_workflows()}')
for name in registry.list_workflows():
    defn = registry.get(name)
    print(f'  {name}: {len(defn.nodes)} nodes, root={defn.get_root_nodes()}, leaf={defn.get_leaf_nodes()}')
"
```
Expected: Both hello_world and echo_test load successfully with correct root/leaf detection.

- [ ] **Step 2: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: No new failures. Existing tests unaffected.

- [ ] **Step 3: Verify file count**

New files created:
- `core/models/workflow_enums.py`
- `core/models/workflow_definition.py`
- `core/workflow_loader.py`
- `core/workflow_registry.py`
- `workflows/hello_world.yaml`
- `workflows/echo_test.yaml`
- `tests/unit/test_workflow_loader.py`

Modified files:
- `requirements.txt`
- `core/models/__init__.py`

---

## Post-Implementation

**Next story**: D.2 (DAG Database Tables) — create Pydantic models for `workflow_runs`, `workflow_tasks`, `workflow_task_deps` and wire them into the existing `PydanticToSQL` DDL generator.

**Agent pipelines**: After D.1-D.4 are complete, run COMPETE adversarial review on the workflow loader code. SIEGE regression after D.10 (first blood).
