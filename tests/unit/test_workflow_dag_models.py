"""Tests for D.2 DAG database models — workflow_runs, workflow_tasks, workflow_task_deps."""
import pytest

from core.models.workflow_enums import (
    NodeType, AggregationMode, BackoffStrategy,
    WorkflowRunStatus, WorkflowTaskStatus,
)
from core.models.workflow_run import WorkflowRun
from core.models.workflow_task import WorkflowTask
from core.models.workflow_task_dep import WorkflowTaskDep


# ============================================================================
# ENUM TESTS
# ============================================================================

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


# ============================================================================
# WORKFLOW RUN MODEL TESTS
# ============================================================================

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

        def test_status_index_is_partial(self):
            indexes = WorkflowRun._WorkflowRun__sql_indexes
            status_idx = next(i for i in indexes if i["name"] == "idx_workflow_runs_status")
            assert "partial_where" in status_idx

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


# ============================================================================
# WORKFLOW TASK MODEL TESTS
# ============================================================================

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

        def test_retry_defaults(self):
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

        def test_ready_poll_index_is_composite(self):
            indexes = WorkflowTask._WorkflowTask__sql_indexes
            poll_idx = next(i for i in indexes if i["name"] == "idx_workflow_tasks_ready_poll")
            assert len(poll_idx["columns"]) == 3
            assert poll_idx["columns"] == ["status", "execute_after", "created_at"]

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


# ============================================================================
# WORKFLOW TASK DEP MODEL TESTS
# ============================================================================

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


# ============================================================================
# DDL GENERATION TESTS
# ============================================================================

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
