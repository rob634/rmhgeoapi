# D.2: DAG Database Tables Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `workflow_runs`, `workflow_tasks`, `workflow_task_deps` tables with Pydantic models, DDL registration, and factory/test support.

**Architecture:** Three new tables in the `app` schema following the existing `__sql_*` ClassVar metadata pattern. Two new enums (`workflow_run_status`, `workflow_task_status`). Models registered in `sql_generator.py` via `generate_table_from_model()` + `generate_indexes_from_model()`. Deployable via `action=ensure` (additive, no data loss).

**Tech Stack:** Pydantic v2, psycopg3 `sql.Composed`, pytest

**Spec:** `V10_MIGRATION.md` lines 292-374 (SQL schema), lines 1757-1768 (acceptance criteria)

---

## Chunk 1: Enums + Pydantic Models

### Task 1: New enums in `core/models/workflow_enums.py`

**Files:**
- Modify: `core/models/workflow_enums.py` (add 2 new enums)

- [ ] **Step 1: Write failing test for new enums**

File: `tests/unit/test_workflow_dag_models.py`

```python
"""Tests for D.2 DAG database models — workflow_runs, workflow_tasks, workflow_task_deps."""
import pytest
from core.models.workflow_enums import (
    NodeType, AggregationMode, BackoffStrategy,
    WorkflowRunStatus, WorkflowTaskStatus,
)


class TestWorkflowRunStatusEnum:
    def test_has_exactly_4_values(self):
        assert len(WorkflowRunStatus) == 4

    def test_expected_members(self):
        names = {s.name for s in WorkflowRunStatus}
        assert names == {"PENDING", "RUNNING", "COMPLETED", "FAILED"}

    def test_all_values_lowercase(self):
        for s in WorkflowRunStatus:
            assert s.value == s.value.lower()


class TestWorkflowTaskStatusEnum:
    def test_has_exactly_8_values(self):
        assert len(WorkflowTaskStatus) == 8

    def test_expected_members(self):
        names = {s.name for s in WorkflowTaskStatus}
        assert names == {
            "PENDING", "READY", "RUNNING", "COMPLETED",
            "FAILED", "SKIPPED", "EXPANDED", "CANCELLED",
        }

    def test_all_values_lowercase(self):
        for s in WorkflowTaskStatus:
            assert s.value == s.value.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py -v`
Expected: ImportError — `WorkflowRunStatus` not found

- [ ] **Step 3: Implement enums**

Add to bottom of `core/models/workflow_enums.py`:

```python
class WorkflowRunStatus(str, Enum):
    """Status of a workflow run (replaces JobStatus for DAG workflows)."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowTaskStatus(str, Enum):
    """
    Status of a workflow task instance.

    Transitions:
        pending  -> ready     (orchestrator: all deps satisfied)
        pending  -> skipped   (orchestrator: when clause false, or conditional untaken branch)
        ready    -> running   (worker: claimed via SKIP LOCKED)
        ready    -> expanded  (orchestrator: fan-out template, N child instances created)
        running  -> completed (worker: handler returned success)
        running  -> failed    (worker: handler returned failure or exception)
        running  -> ready     (janitor: stale heartbeat, retry_count < max)
        failed   -> ready     (manual: retry via admin endpoint)
    """
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    EXPANDED = "expanded"
    CANCELLED = "cancelled"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowRunStatusEnum tests/unit/test_workflow_dag_models.py::TestWorkflowTaskStatusEnum -v`
Expected: PASS

---

### Task 2: WorkflowRun Pydantic model

**Files:**
- Create: `core/models/workflow_run.py`

- [ ] **Step 1: Write failing tests for WorkflowRun**

Append to `tests/unit/test_workflow_dag_models.py`:

```python
from core.models.workflow_run import WorkflowRun
from core.models.workflow_enums import WorkflowRunStatus


class TestWorkflowRunModel:

    class TestDefaults:
        def test_status_defaults_to_pending(self):
            run = WorkflowRun(
                run_id="test-run-001",
                workflow_name="hello_world",
                parameters={"msg": "hi"},
                definition={"workflow": "hello_world", "version": 1},
                platform_version="0.11.0",
            )
            assert run.status == WorkflowRunStatus.PENDING

        def test_timestamps_auto_populated(self):
            run = WorkflowRun(
                run_id="test-run-002",
                workflow_name="hello_world",
                parameters={},
                definition={},
                platform_version="0.11.0",
            )
            assert run.created_at is not None
            assert run.started_at is None
            assert run.completed_at is None

        def test_optional_fields_default_none(self):
            run = WorkflowRun(
                run_id="test-run-003",
                workflow_name="hello_world",
                parameters={},
                definition={},
                platform_version="0.11.0",
            )
            assert run.result_data is None
            assert run.request_id is None
            assert run.asset_id is None
            assert run.release_id is None
            assert run.legacy_job_id is None

    class TestSqlMetadata:
        def test_table_name(self):
            assert WorkflowRun._WorkflowRun__sql_table_name == "workflow_runs"

        def test_schema(self):
            assert WorkflowRun._WorkflowRun__sql_schema == "app"

        def test_primary_key(self):
            assert WorkflowRun._WorkflowRun__sql_primary_key == ["run_id"]

        def test_has_indexes(self):
            indexes = WorkflowRun._WorkflowRun__sql_indexes
            names = {idx["name"] for idx in indexes}
            assert "idx_workflow_runs_status" in names
            assert "idx_workflow_runs_workflow_name" in names
            assert "idx_workflow_runs_created" in names

    class TestSerialization:
        def test_model_dump_preserves_jsonb(self):
            run = WorkflowRun(
                run_id="test-run-004",
                workflow_name="hello_world",
                parameters={"key": "value"},
                definition={"workflow": "hello_world"},
                platform_version="0.11.0",
            )
            dumped = run.model_dump()
            assert isinstance(dumped["parameters"], dict)
            assert isinstance(dumped["definition"], dict)

        def test_json_mode_serializes_status(self):
            run = WorkflowRun(
                run_id="test-run-005",
                workflow_name="hello_world",
                parameters={},
                definition={},
                platform_version="0.11.0",
            )
            dumped = run.model_dump(mode="json")
            assert dumped["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowRunModel -v`
Expected: ImportError — `workflow_run` module not found

- [ ] **Step 3: Create `core/models/workflow_run.py`**

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW RUN MODEL (DAG EXECUTION TRACKING)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - D.2 DAG Database Tables
# PURPOSE: Pydantic model for workflow_runs table — tracks DAG workflow executions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowRun
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
WorkflowRun — tracks execution of a YAML workflow DAG.

Replaces app.jobs for DAG workflows. Legacy jobs remain in app.jobs
during the strangler fig migration.

Table: app.workflow_runs
Primary Key: run_id
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from .workflow_enums import WorkflowRunStatus


class WorkflowRun(BaseModel):
    """
    Workflow run — one execution of a YAML workflow definition.

    The definition JSONB is a snapshot of the YAML at submission time,
    making each run self-contained and immune to workflow file changes.
    """
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    @field_serializer('created_at', 'started_at', 'completed_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "workflow_runs"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["run_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["workflow_name"], "name": "idx_workflow_runs_workflow_name"},
        {"columns": ["status"], "name": "idx_workflow_runs_status",
         "partial_where": "status IN ('pending', 'running')"},
        {"columns": ["created_at"], "name": "idx_workflow_runs_created", "descending": True},
        {"columns": ["request_id"], "name": "idx_workflow_runs_request",
         "partial_where": "request_id IS NOT NULL"},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    run_id: str = Field(..., max_length=64, description="Unique run identifier")
    workflow_name: str = Field(..., max_length=100, description="Workflow identifier from YAML")

    # =========================================================================
    # EXECUTION STATE
    # =========================================================================
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Validated input parameters")
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.PENDING,
        description="pending -> running -> completed | failed"
    )
    definition: Dict[str, Any] = Field(
        default_factory=dict,
        description="YAML snapshot at submission time (immutable)"
    )
    platform_version: str = Field(..., max_length=20, description="App version at submission")
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Final workflow results")

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = Field(default=None, description="When first task claimed")
    completed_at: Optional[datetime] = Field(default=None, description="When workflow finished")

    # =========================================================================
    # PLATFORM INTEGRATION
    # =========================================================================
    request_id: Optional[str] = Field(default=None, max_length=100, description="B2B request_id for status lookups")
    asset_id: Optional[str] = Field(default=None, max_length=64, description="Linked asset")
    release_id: Optional[str] = Field(default=None, max_length=64, description="Linked release")

    # =========================================================================
    # MIGRATION BRIDGE
    # =========================================================================
    legacy_job_id: Optional[str] = Field(default=None, max_length=64, description="Link to app.jobs during strangler fig")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowRunModel -v`
Expected: PASS

---

### Task 3: WorkflowTask Pydantic model

**Files:**
- Create: `core/models/workflow_task.py`

- [ ] **Step 1: Write failing tests for WorkflowTask**

Append to `tests/unit/test_workflow_dag_models.py`:

```python
from core.models.workflow_task import WorkflowTask
from core.models.workflow_enums import WorkflowTaskStatus


class TestWorkflowTaskModel:

    class TestDefaults:
        def test_status_defaults_to_pending(self):
            task = WorkflowTask(
                task_instance_id="run001-validate",
                run_id="run001",
                task_name="validate",
                handler="raster_validate",
            )
            assert task.status == WorkflowTaskStatus.PENDING

        def test_retry_defaults_to_zero(self):
            task = WorkflowTask(
                task_instance_id="run001-validate",
                run_id="run001",
                task_name="validate",
                handler="raster_validate",
            )
            assert task.retry_count == 0
            assert task.max_retries == 3

        def test_fan_out_fields_default_none(self):
            task = WorkflowTask(
                task_instance_id="run001-validate",
                run_id="run001",
                task_name="validate",
                handler="raster_validate",
            )
            assert task.fan_out_index is None
            assert task.fan_out_source is None

        def test_worker_fields_default_none(self):
            task = WorkflowTask(
                task_instance_id="run001-validate",
                run_id="run001",
                task_name="validate",
                handler="raster_validate",
            )
            assert task.claimed_by is None
            assert task.last_pulse is None
            assert task.execute_after is None

    class TestSqlMetadata:
        def test_table_name(self):
            assert WorkflowTask._WorkflowTask__sql_table_name == "workflow_tasks"

        def test_foreign_key_to_workflow_runs(self):
            fks = WorkflowTask._WorkflowTask__sql_foreign_keys
            assert "run_id" in fks
            assert "workflow_runs" in fks["run_id"]

        def test_unique_constraint_on_run_task_fanout(self):
            ucs = WorkflowTask._WorkflowTask__sql_unique_constraints
            names = {uc["name"] for uc in ucs}
            assert "uq_workflow_task_identity" in names

        def test_has_partial_indexes(self):
            indexes = WorkflowTask._WorkflowTask__sql_indexes
            partial_names = {
                idx["name"] for idx in indexes if idx.get("partial_where")
            }
            assert "idx_workflow_tasks_status" in partial_names
            assert "idx_workflow_tasks_ready_poll" in partial_names
            assert "idx_workflow_tasks_stale" in partial_names

    class TestSerialization:
        def test_model_dump_preserves_jsonb(self):
            task = WorkflowTask(
                task_instance_id="run001-validate",
                run_id="run001",
                task_name="validate",
                handler="raster_validate",
                parameters={"blob": "test.tif"},
            )
            dumped = task.model_dump()
            assert isinstance(dumped["parameters"], dict)

        def test_json_mode_serializes_status(self):
            task = WorkflowTask(
                task_instance_id="run001-validate",
                run_id="run001",
                task_name="validate",
                handler="raster_validate",
            )
            dumped = task.model_dump(mode="json")
            assert dumped["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowTaskModel -v`
Expected: ImportError

- [ ] **Step 3: Create `core/models/workflow_task.py`**

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW TASK MODEL (DAG NODE EXECUTION)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - D.2 DAG Database Tables
# PURPOSE: Pydantic model for workflow_tasks table — individual node executions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowTask
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
WorkflowTask — one task instance within a workflow run.

Each YAML node becomes one WorkflowTask row when the DAG is initialized.
Fan-out nodes expand into N rows (one per array element) with fan_out_index.

Table: app.workflow_tasks
Primary Key: task_instance_id
Foreign Key: run_id -> app.workflow_runs(run_id)
Unique: (run_id, task_name, fan_out_index)
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from .workflow_enums import WorkflowTaskStatus


class WorkflowTask(BaseModel):
    """
    Workflow task instance — runtime execution of a YAML node.

    Workers claim ready tasks via SELECT FOR UPDATE SKIP LOCKED,
    same pattern as app.tasks (v0.10.3 DB-polling).
    """
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    @field_serializer(
        'last_pulse', 'execute_after', 'started_at', 'completed_at',
        'created_at', 'updated_at'
    )
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS
    # =========================================================================
    __sql_table_name: ClassVar[str] = "workflow_tasks"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["task_instance_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "run_id": "app.workflow_runs(run_id)",
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {
            "columns": ["run_id", "task_name", "fan_out_index"],
            "name": "uq_workflow_task_identity",
        }
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["run_id"], "name": "idx_workflow_tasks_run"},
        {"columns": ["status"], "name": "idx_workflow_tasks_status",
         "partial_where": "status IN ('pending', 'ready', 'running')"},
        {"columns": ["status", "last_pulse"], "name": "idx_workflow_tasks_stale",
         "partial_where": "status = 'running'"},
        {"columns": ["status", "execute_after", "created_at"],
         "name": "idx_workflow_tasks_ready_poll",
         "partial_where": "status = 'ready'"},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    task_instance_id: str = Field(..., max_length=100, description="Unique task instance ID")
    run_id: str = Field(..., max_length=64, description="FK to workflow_runs")
    task_name: str = Field(..., max_length=100, description="Node name from YAML")
    handler: str = Field(..., max_length=100, description="Handler name from ALL_HANDLERS")

    # =========================================================================
    # EXECUTION STATE
    # =========================================================================
    status: WorkflowTaskStatus = Field(
        default=WorkflowTaskStatus.PENDING,
        description="Task lifecycle status"
    )

    # =========================================================================
    # FAN-OUT TRACKING
    # =========================================================================
    fan_out_index: Optional[int] = Field(
        default=None, description="0..N for fan-out instances, NULL for regular tasks"
    )
    fan_out_source: Optional[str] = Field(
        default=None, max_length=100,
        description="Node name that produced the fan-out array"
    )

    # =========================================================================
    # CONDITIONAL / SKIP
    # =========================================================================
    when_clause: Optional[str] = Field(
        default=None, max_length=500,
        description="Condition expression from YAML (NULL = unconditional)"
    )

    # =========================================================================
    # PARAMETERS & RESULTS
    # =========================================================================
    parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="Resolved parameters at execution time"
    )
    result_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Handler output"
    )
    error_details: Optional[str] = Field(default=None, description="Error message if failed")

    # =========================================================================
    # RETRY
    # =========================================================================
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    max_retries: int = Field(default=3, ge=0, description="Max retries before permanent failure")

    # =========================================================================
    # WORKER CLAIM (DB-POLLING)
    # =========================================================================
    claimed_by: Optional[str] = Field(
        default=None, max_length=100,
        description="Worker ID that claimed this task (NULL when unclaimed)"
    )
    last_pulse: Optional[datetime] = Field(
        default=None, description="Heartbeat from worker during execution"
    )
    execute_after: Optional[datetime] = Field(
        default=None, description="Scheduled execution time (NULL = immediate, set for retry backoff)"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    started_at: Optional[datetime] = Field(default=None, description="When worker started execution")
    completed_at: Optional[datetime] = Field(default=None, description="When task finished")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowTaskModel -v`
Expected: PASS

---

### Task 4: WorkflowTaskDep Pydantic model

**Files:**
- Create: `core/models/workflow_task_dep.py`

- [ ] **Step 1: Write failing tests for WorkflowTaskDep**

Append to `tests/unit/test_workflow_dag_models.py`:

```python
from core.models.workflow_task_dep import WorkflowTaskDep


class TestWorkflowTaskDepModel:

    def test_required_fields(self):
        dep = WorkflowTaskDep(
            task_instance_id="run001-create_cog",
            depends_on_instance_id="run001-validate",
        )
        assert dep.task_instance_id == "run001-create_cog"
        assert dep.depends_on_instance_id == "run001-validate"

    def test_optional_defaults_false(self):
        dep = WorkflowTaskDep(
            task_instance_id="run001-consolidate",
            depends_on_instance_id="run001-rechunk",
        )
        assert dep.optional is False

    def test_optional_can_be_true(self):
        dep = WorkflowTaskDep(
            task_instance_id="run001-consolidate",
            depends_on_instance_id="run001-rechunk",
            optional=True,
        )
        assert dep.optional is True

    class TestSqlMetadata:
        def test_table_name(self):
            assert WorkflowTaskDep._WorkflowTaskDep__sql_table_name == "workflow_task_deps"

        def test_composite_primary_key(self):
            pk = WorkflowTaskDep._WorkflowTaskDep__sql_primary_key
            assert pk == ["task_instance_id", "depends_on_instance_id"]

        def test_foreign_keys(self):
            fks = WorkflowTaskDep._WorkflowTaskDep__sql_foreign_keys
            assert "task_instance_id" in fks
            assert "depends_on_instance_id" in fks
            assert "workflow_tasks" in fks["task_instance_id"]
            assert "workflow_tasks" in fks["depends_on_instance_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowTaskDepModel -v`
Expected: ImportError

- [ ] **Step 3: Create `core/models/workflow_task_dep.py`**

```python
# ============================================================================
# CLAUDE CONTEXT - WORKFLOW TASK DEPENDENCY MODEL (DAG EDGES)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - D.2 DAG Database Tables
# PURPOSE: Pydantic model for workflow_task_deps table — DAG edge definitions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowTaskDep
# DEPENDENCIES: pydantic
# ============================================================================
"""
WorkflowTaskDep — DAG edge between two task instances.

Created at workflow initialization time. Each depends_on entry in YAML
becomes one row. Conditional next: pointers also become edges.

Table: app.workflow_task_deps
Primary Key: (task_instance_id, depends_on_instance_id) — composite
Foreign Keys: Both columns reference app.workflow_tasks(task_instance_id)
"""

from typing import Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict


class WorkflowTaskDep(BaseModel):
    """DAG edge: task_instance_id depends on depends_on_instance_id."""
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    # =========================================================================
    # DDL GENERATION HINTS
    # =========================================================================
    __sql_table_name: ClassVar[str] = "workflow_task_deps"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["task_instance_id", "depends_on_instance_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "task_instance_id": "app.workflow_tasks(task_instance_id)",
        "depends_on_instance_id": "app.workflow_tasks(task_instance_id)",
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = []

    # =========================================================================
    # EDGE DEFINITION
    # =========================================================================
    task_instance_id: str = Field(
        ..., max_length=100,
        description="The task that has this dependency"
    )
    depends_on_instance_id: str = Field(
        ..., max_length=100,
        description="The task that must complete first"
    )
    optional: bool = Field(
        default=False,
        description="If true, tolerates skipped (not failed) dependency"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowTaskDepModel -v`
Expected: PASS

- [ ] **Step 5: Commit models**

```bash
git add core/models/workflow_enums.py core/models/workflow_run.py core/models/workflow_task.py core/models/workflow_task_dep.py tests/unit/test_workflow_dag_models.py
git commit -m "feat(D.2): DAG table Pydantic models — WorkflowRun, WorkflowTask, WorkflowTaskDep"
```

---

## Chunk 2: Registration + DDL + Factory

### Task 5: Register models in `core/models/__init__.py`

**Files:**
- Modify: `core/models/__init__.py`

- [ ] **Step 1: Add imports and __all__ entries**

After the existing workflow DAG imports (line ~224), add:

```python
# Workflow DAG execution models (16 MAR 2026 - D.2)
from .workflow_run import WorkflowRun
from .workflow_task import WorkflowTask
from .workflow_task_dep import WorkflowTaskDep
```

And add to `__all__`:

```python
    # Workflow DAG execution models (16 MAR 2026 - D.2)
    'WorkflowRunStatus',
    'WorkflowTaskStatus',
    'WorkflowRun',
    'WorkflowTask',
    'WorkflowTaskDep',
```

Also add `WorkflowRunStatus` and `WorkflowTaskStatus` to the workflow_enums import block.

- [ ] **Step 2: Verify import works**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from core.models import WorkflowRun, WorkflowTask, WorkflowTaskDep; print('OK')"`
Expected: `OK`

---

### Task 6: Register enums and tables in `sql_generator.py`

**Files:**
- Modify: `core/schema/sql_generator.py`

- [ ] **Step 1: Write failing test for DDL generation**

Append to `tests/unit/test_workflow_dag_models.py`:

```python
class TestWorkflowDagDDL:
    """Verify DAG tables appear in generated DDL."""

    @pytest.fixture
    def generator(self):
        from core.schema.sql_generator import PydanticToSQL
        return PydanticToSQL()

    def test_composed_statements_include_workflow_runs(self, generator):
        stmts = generator.generate_composed_statements()
        sql_text = " ".join(str(s) for s in stmts).lower()
        assert "workflow_runs" in sql_text

    def test_composed_statements_include_workflow_tasks(self, generator):
        stmts = generator.generate_composed_statements()
        sql_text = " ".join(str(s) for s in stmts).lower()
        assert "workflow_tasks" in sql_text

    def test_composed_statements_include_workflow_task_deps(self, generator):
        stmts = generator.generate_composed_statements()
        sql_text = " ".join(str(s) for s in stmts).lower()
        assert "workflow_task_deps" in sql_text

    def test_composed_statements_include_new_enums(self, generator):
        stmts = generator.generate_composed_statements()
        sql_text = " ".join(str(s) for s in stmts).lower()
        assert "workflow_run_status" in sql_text
        assert "workflow_task_status" in sql_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowDagDDL -v`
Expected: FAIL — "workflow_runs" not found in DDL output

- [ ] **Step 3: Add enum registration in `sql_generator.py`**

After `release_audit_event_type` enum (line ~1717), add:

```python
        composed.extend(self.generate_enum("workflow_run_status", WorkflowRunStatus))  # DAG workflow runs (16 MAR 2026 - D.2)
        composed.extend(self.generate_enum("workflow_task_status", WorkflowTaskStatus))  # DAG workflow tasks (16 MAR 2026 - D.2)
```

Add imports at top of file (with other model imports):

```python
from core.models.workflow_enums import WorkflowRunStatus, WorkflowTaskStatus
from core.models.workflow_run import WorkflowRun
from core.models.workflow_task import WorkflowTask
from core.models.workflow_task_dep import WorkflowTaskDep
```

- [ ] **Step 4: Add table registration in `sql_generator.py`**

After `ReleaseAuditEvent` table (line ~1744), add:

```python
        # DAG workflow tables (16 MAR 2026 - D.2) — order matters: runs before tasks, tasks before deps
        composed.append(self.generate_table_from_model(WorkflowRun))
        composed.append(self.generate_table_from_model(WorkflowTask))
        composed.append(self.generate_table_from_model(WorkflowTaskDep))
```

After `ReleaseAuditEvent` indexes (line ~1766), add:

```python
        composed.extend(self.generate_indexes_from_model(WorkflowRun))  # DAG runs (16 MAR 2026 - D.2)
        composed.extend(self.generate_indexes_from_model(WorkflowTask))  # DAG tasks (16 MAR 2026 - D.2)
        composed.extend(self.generate_indexes_from_model(WorkflowTaskDep))  # DAG deps (16 MAR 2026 - D.2)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py::TestWorkflowDagDDL -v`
Expected: PASS

---

### Task 7: Factory methods for tests

**Files:**
- Modify: `tests/factories/model_factories.py`

- [ ] **Step 1: Add factory functions**

Add to `tests/factories/model_factories.py`:

```python
def make_workflow_run(run_id: str = None, **overrides):
    """Build a WorkflowRun data dict with randomized non-identity fields."""
    suffix = _random_suffix()
    base = {
        "run_id": run_id or f"run-{suffix}-{uuid.uuid4().hex[:8]}",
        "workflow_name": f"test_workflow_{suffix}",
        "parameters": {"seed": suffix},
        "status": "pending",
        "definition": {"workflow": f"test_workflow_{suffix}", "version": 1},
        "platform_version": "0.11.0",
        "created_at": _random_timestamp(),
    }
    base.update(overrides)
    return base


def make_workflow_task(task_instance_id: str = None, run_id: str = None, **overrides):
    """Build a WorkflowTask data dict with randomized non-identity fields."""
    suffix = _random_suffix()
    base = {
        "task_instance_id": task_instance_id or f"task-{suffix}-{uuid.uuid4().hex[:8]}",
        "run_id": run_id or f"run-{suffix}",
        "task_name": f"step_{suffix}",
        "handler": f"handler_{suffix}",
        "status": "pending",
        "retry_count": 0,
        "max_retries": 3,
        "created_at": _random_timestamp(),
        "updated_at": _random_timestamp(),
    }
    base.update(overrides)
    return base
```

- [ ] **Step 2: Verify factory import works**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from tests.factories.model_factories import make_workflow_run, make_workflow_task; print('OK')"`
Expected: `OK`

---

### Task 8: Run full test suite and commit

- [ ] **Step 1: Run all D.2 tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/ -v --timeout=30`
Expected: All existing tests still PASS

- [ ] **Step 3: Commit**

```bash
git add core/models/__init__.py core/schema/sql_generator.py tests/factories/model_factories.py tests/unit/test_workflow_dag_models.py
git commit -m "feat(D.2): Register DAG tables in sql_generator + factory methods"
```

---

## Summary

| Deliverable | File | Lines (est.) |
|-------------|------|-------------|
| 2 enums | `core/models/workflow_enums.py` | ~35 |
| WorkflowRun model | `core/models/workflow_run.py` | ~85 |
| WorkflowTask model | `core/models/workflow_task.py` | ~100 |
| WorkflowTaskDep model | `core/models/workflow_task_dep.py` | ~50 |
| DDL registration | `core/schema/sql_generator.py` | ~10 |
| Model registration | `core/models/__init__.py` | ~10 |
| Factory methods | `tests/factories/model_factories.py` | ~30 |
| Tests | `tests/unit/test_workflow_dag_models.py` | ~180 |
| **Total** | **8 files** | **~500 lines** |

**Acceptance criteria** (from V10_MIGRATION.md):
- `action=ensure` creates 3 new tables + indexes without touching existing tables
- `workflow_tasks` has partial indexes for orchestrator and worker poll queries
