# ============================================================================
# CLAUDE CONTEXT - WORKFLOW LOADER TESTS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Tests - Workflow definition model validation
# PURPOSE: Unit tests for workflow enums, supporting models, node types, and WorkflowDefinition
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: TestWorkflowEnums, TestSupportingModels, TestNodeTypeDiscrimination
# DEPENDENCIES: pytest, pydantic
# ============================================================================

import pytest
from pydantic import ValidationError, TypeAdapter

from core.models.workflow_enums import NodeType, AggregationMode, BackoffStrategy
from core.models.workflow_definition import (
    RetryPolicy,
    BranchDef,
    FanOutTaskDef,
    FinalizeDef,
    ParameterDef,
    ValidatorDef,
    TaskNode,
    ConditionalNode,
    FanOutNode,
    FanInNode,
    NodeDefinition,
    WorkflowDefinition,
)


class TestWorkflowEnums:
    """Tests for workflow enum definitions."""

    def test_node_type_has_four_values(self):
        assert len(NodeType) == 4

    def test_node_type_string_values(self):
        assert NodeType.TASK.value == "task"
        assert NodeType.CONDITIONAL.value == "conditional"
        assert NodeType.FAN_OUT.value == "fan_out"
        assert NodeType.FAN_IN.value == "fan_in"

    def test_aggregation_mode_has_five_values(self):
        assert len(AggregationMode) == 5

    def test_backoff_strategy_has_three_values(self):
        assert len(BackoffStrategy) == 3


class TestSupportingModels:
    """Tests for supporting Pydantic models."""

    def test_retry_policy_defaults(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff == BackoffStrategy.EXPONENTIAL
        assert policy.initial_delay_seconds == 5
        assert policy.max_delay_seconds == 300

    def test_retry_policy_max_attempts_bounds(self):
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=0)
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=11)

    def test_branch_def_requires_name_and_next(self):
        with pytest.raises(ValidationError):
            BranchDef()  # missing name and next
        branch = BranchDef(name="yes", next=["step_2"])
        assert branch.name == "yes"
        assert branch.next == ["step_2"]
        assert branch.default is False

    def test_parameter_def_type_validated(self):
        with pytest.raises(ValidationError):
            ParameterDef(type="string")  # not a valid literal
        param = ParameterDef(type="str")
        assert param.type == "str"

    def test_fan_out_task_def_requires_handler(self):
        with pytest.raises(ValidationError):
            FanOutTaskDef()  # missing handler
        task = FanOutTaskDef(handler="process_chunk")
        assert task.handler == "process_chunk"
        assert task.timeout_seconds == 3600

    def test_validator_def_allows_extra_fields(self):
        v = ValidatorDef(type="bbox", min_lat=-90, max_lat=90)
        assert v.type == "bbox"
        assert v.min_lat == -90
        assert v.max_lat == 90


class TestNodeTypeDiscrimination:
    """Tests for node type models and discriminated union."""

    def test_task_node_default_type(self):
        node = TaskNode(handler="do_work")
        assert node.type == "task"
        assert node.depends_on == []
        assert node.params == []

    def test_task_node_with_all_fields(self):
        node = TaskNode(
            handler="process",
            depends_on=["step_1"],
            params={"key": "value"},
            receives={"input": "step_1.output"},
            when="params.enable_feature == true",
            retry=RetryPolicy(max_attempts=5),
            timeout_seconds=600,
        )
        assert node.handler == "process"
        assert node.depends_on == ["step_1"]
        assert node.params == {"key": "value"}
        assert node.receives == {"input": "step_1.output"}
        assert node.when == "params.enable_feature == true"
        assert node.retry.max_attempts == 5
        assert node.timeout_seconds == 600

    def test_conditional_node_requires_condition_and_branches(self):
        with pytest.raises(ValidationError):
            ConditionalNode(type="conditional")  # missing condition and branches

    def test_conditional_node_rejects_one_branch(self):
        with pytest.raises(ValidationError):
            ConditionalNode(
                type="conditional",
                condition="params.mode",
                branches=[BranchDef(name="only", next=["a"])],
            )

    def test_fan_out_node_requires_source_and_task(self):
        with pytest.raises(ValidationError):
            FanOutNode(type="fan_out")  # missing source and task
        node = FanOutNode(
            type="fan_out",
            source="items_list",
            task=FanOutTaskDef(handler="process_item"),
        )
        assert node.source == "items_list"
        assert node.max_fan_out == 500

    def test_fan_in_node_requires_depends_on(self):
        with pytest.raises(ValidationError):
            FanInNode(type="fan_in")  # depends_on is required (no default)
        node = FanInNode(type="fan_in", depends_on=["scatter"])
        assert node.aggregation == AggregationMode.COLLECT

    def test_fan_out_node_has_no_handler_field(self):
        """FanOutNode has no direct handler — it's on FanOutTaskDef."""
        assert "handler" not in FanOutNode.model_fields

    def test_discriminated_union_selects_correct_type(self):
        adapter = TypeAdapter(NodeDefinition)
        task = adapter.validate_python({"type": "task", "handler": "do_work"})
        assert isinstance(task, TaskNode)

        fan_in = adapter.validate_python(
            {"type": "fan_in", "depends_on": ["scatter"]}
        )
        assert isinstance(fan_in, FanInNode)

    def test_wrong_fields_for_type_rejected(self):
        """handler is not a field on FanInNode, and extra='forbid' rejects it."""
        adapter = TypeAdapter(NodeDefinition)
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {"type": "fan_in", "depends_on": ["x"], "handler": "bad"}
            )
