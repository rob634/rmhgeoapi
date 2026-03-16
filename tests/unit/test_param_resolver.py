# ============================================================================
# CLAUDE CONTEXT - PARAMETER RESOLVER TESTS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Tests - Pure function tests for parameter resolution logic
# PURPOSE: Unit tests for resolve_dotted_path, resolve_task_params,
#          resolve_fan_out_params
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: TestResolveDottedPath, TestResolveTaskParams, TestResolveFanOutParams
# DEPENDENCIES: pytest, core.param_resolver, core.models.workflow_definition
# ============================================================================

import pytest

from core.param_resolver import (
    ParameterResolutionError,
    resolve_dotted_path,
    resolve_fan_out_params,
    resolve_task_params,
)
from core.models.workflow_definition import FanOutTaskDef, TaskNode


# ============================================================================
# TestResolveDottedPath
# ============================================================================


class TestResolveDottedPath:
    """Tests for resolve_dotted_path — dotted-string navigation into predecessor outputs."""

    def test_two_segment_path(self):
        """'validate.metadata' returns the metadata dict."""
        outputs = {"validate": {"metadata": {"crs": "EPSG:4326"}}}
        result = resolve_dotted_path("validate.metadata", outputs)
        assert result == {"crs": "EPSG:4326"}

    def test_three_segment_path(self):
        """'validate.metadata.crs' drills into nested dict."""
        outputs = {"validate": {"metadata": {"crs": "EPSG:4326"}}}
        result = resolve_dotted_path("validate.metadata.crs", outputs)
        assert result == "EPSG:4326"

    def test_list_index_path(self):
        """'validate.items.0' uses integer index on a list."""
        outputs = {"validate": {"items": ["first", "second", "third"]}}
        result = resolve_dotted_path("validate.items.0", outputs)
        assert result == "first"

    def test_missing_node_raises(self):
        """Unknown node name raises ParameterResolutionError."""
        outputs = {"validate": {"field": "value"}}
        with pytest.raises(ParameterResolutionError, match="node 'nonexistent' not found"):
            resolve_dotted_path("nonexistent.field", outputs)

    def test_missing_key_raises(self):
        """Missing key within a known node raises ParameterResolutionError."""
        outputs = {"validate": {"metadata": {"crs": "EPSG:4326"}}}
        with pytest.raises(ParameterResolutionError, match="failed at segment 'nonexistent'"):
            resolve_dotted_path("validate.nonexistent", outputs)

    def test_non_subscriptable_intermediate_raises(self):
        """Traversing past a string value raises ParameterResolutionError."""
        outputs = {"validate": {"metadata": {"crs": "EPSG:4326"}}}
        with pytest.raises(ParameterResolutionError, match="failed at segment 'oops'"):
            resolve_dotted_path("validate.metadata.crs.oops", outputs)

    def test_none_node_output_raises(self):
        """Node output of None raises ParameterResolutionError."""
        outputs = {"validate": None}
        with pytest.raises(ParameterResolutionError, match="output for node 'validate' is None"):
            resolve_dotted_path("validate.field", outputs)

    def test_single_segment_path_raises(self):
        """A path with only one segment is malformed."""
        outputs = {"validate": {"field": "value"}}
        with pytest.raises(ParameterResolutionError, match="malformed"):
            resolve_dotted_path("validate", outputs)

    def test_empty_segment_raises(self):
        """A path with empty segments ('validate..field') is malformed."""
        outputs = {"validate": {"field": "value"}}
        with pytest.raises(ParameterResolutionError, match="malformed"):
            resolve_dotted_path("validate..field", outputs)

    def test_integer_value_preserved(self):
        """Numeric values are returned as their original type, not stringified."""
        outputs = {"validate": {"count": 42}}
        result = resolve_dotted_path("validate.count", outputs)
        assert result == 42
        assert isinstance(result, int)


# ============================================================================
# TestResolveTaskParams
# ============================================================================


class TestResolveTaskParams:
    """Tests for resolve_task_params — builds concrete params for a TaskNode."""

    def test_list_params_filters_job_params(self):
        """List params extracts named keys, ignoring extras."""
        node = TaskNode(handler="process", params=["blob_name", "crs"])
        result = resolve_task_params(
            node,
            job_params={"blob_name": "test.tif", "crs": "4326", "extra": "ignored"},
            predecessor_outputs={},
        )
        assert result == {"blob_name": "test.tif", "crs": "4326"}
        assert "extra" not in result

    def test_dict_params_literal(self):
        """Dict params are passed through as literal values."""
        node = TaskNode(handler="process", params={"key": "literal_value"})
        result = resolve_task_params(node, job_params={}, predecessor_outputs={})
        assert result == {"key": "literal_value"}

    def test_empty_params_returns_empty_dict(self):
        """Empty params list produces empty dict (before receives)."""
        node = TaskNode(handler="process", params=[])
        result = resolve_task_params(node, job_params={}, predecessor_outputs={})
        assert result == {}

    def test_receives_overlay(self):
        """Receives adds resolved predecessor data to the result."""
        node = TaskNode(
            handler="process",
            params=["blob_name"],
            receives={"metadata": "validate.metadata"},
        )
        result = resolve_task_params(
            node,
            job_params={"blob_name": "test.tif"},
            predecessor_outputs={"validate": {"metadata": {"crs": "EPSG:4326"}}},
        )
        assert result["blob_name"] == "test.tif"
        assert result["metadata"] == {"crs": "EPSG:4326"}

    def test_receives_overwrites_params_collision(self):
        """When params and receives produce the same key, receives wins."""
        node = TaskNode(
            handler="process",
            params=["crs"],
            receives={"crs": "validate.metadata.crs"},
        )
        result = resolve_task_params(
            node,
            job_params={"crs": "original"},
            predecessor_outputs={"validate": {"metadata": {"crs": "from_predecessor"}}},
        )
        assert result["crs"] == "from_predecessor"

    def test_missing_job_param_raises(self):
        """Requesting a key absent from job_params raises ParameterResolutionError."""
        node = TaskNode(handler="process", params=["nonexistent"])
        with pytest.raises(ParameterResolutionError, match="required job_param key 'nonexistent'"):
            resolve_task_params(node, job_params={}, predecessor_outputs={})

    def test_missing_receives_node_raises(self):
        """A receives path pointing to an unknown node raises ParameterResolutionError."""
        node = TaskNode(
            handler="process",
            params=[],
            receives={"x": "nonexistent.field"},
        )
        with pytest.raises(ParameterResolutionError, match="node 'nonexistent' not found"):
            resolve_task_params(node, job_params={}, predecessor_outputs={})


# ============================================================================
# TestResolveFanOutParams
# ============================================================================


class TestResolveFanOutParams:
    """Tests for resolve_fan_out_params — Jinja2 template resolution for fan-out items."""

    def test_simple_item_substitution(self):
        """'{{ item }}' is replaced by the item value."""
        template = FanOutTaskDef(handler="process", params={"path": "{{ item }}"})
        result = resolve_fan_out_params(
            template, item="blob_a.zarr", index=0, job_params={}, predecessor_outputs={},
        )
        assert result == {"path": "blob_a.zarr"}

    def test_index_substitution_returns_int(self):
        """'{{ index }}' resolves to an integer, not a string."""
        template = FanOutTaskDef(handler="process", params={"idx": "{{ index }}"})
        result = resolve_fan_out_params(
            template, item="x", index=3, job_params={}, predecessor_outputs={},
        )
        assert result["idx"] == 3
        assert isinstance(result["idx"], int)

    def test_dict_item_field_access(self):
        """'{{ item.name }}' accesses a field on a dict item."""
        template = FanOutTaskDef(handler="process", params={"name": "{{ item.name }}"})
        result = resolve_fan_out_params(
            template,
            item={"name": "test", "size": 100},
            index=0,
            job_params={},
            predecessor_outputs={},
        )
        assert result["name"] == "test"

    def test_inputs_access(self):
        """'{{ inputs.container }}' reads from job_params."""
        template = FanOutTaskDef(handler="process", params={"target": "{{ inputs.container }}"})
        result = resolve_fan_out_params(
            template, item="x", index=0, job_params={"container": "silver"}, predecessor_outputs={},
        )
        assert result["target"] == "silver"

    def test_type_preservation_int(self):
        """NativeEnvironment preserves int type from job_params."""
        template = FanOutTaskDef(handler="process", params={"count": "{{ inputs.count }}"})
        result = resolve_fan_out_params(
            template, item="x", index=0, job_params={"count": 42}, predecessor_outputs={},
        )
        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_mixed_literal_and_template(self):
        """String interpolation with literal prefix and suffix."""
        template = FanOutTaskDef(handler="process", params={"msg": "prefix_{{ item }}_suffix"})
        result = resolve_fan_out_params(
            template, item="middle", index=0, job_params={}, predecessor_outputs={},
        )
        assert result["msg"] == "prefix_middle_suffix"

    def test_non_template_passthrough(self):
        """Values without '{{' pass through unchanged."""
        template = FanOutTaskDef(handler="process", params={"static": "no_braces_here"})
        result = resolve_fan_out_params(
            template, item="x", index=0, job_params={}, predecessor_outputs={},
        )
        assert result["static"] == "no_braces_here"

    def test_missing_template_variable_raises(self):
        """Reference to an undefined variable raises ParameterResolutionError."""
        template = FanOutTaskDef(handler="process", params={"x": "{{ missing_var }}"})
        with pytest.raises(ParameterResolutionError, match="Jinja2 template error"):
            resolve_fan_out_params(
                template, item="x", index=0, job_params={}, predecessor_outputs={},
            )

    def test_bad_template_syntax_raises(self):
        """Malformed Jinja2 syntax raises ParameterResolutionError."""
        template = FanOutTaskDef(handler="process", params={"x": "{{ item"})
        with pytest.raises(ParameterResolutionError, match="Jinja2 template error"):
            resolve_fan_out_params(
                template, item="x", index=0, job_params={}, predecessor_outputs={},
            )

    def test_none_item_returns_none(self):
        """When item is None, '{{ item }}' resolves to None (with warning logged)."""
        template = FanOutTaskDef(handler="process", params={"x": "{{ item }}"})
        result = resolve_fan_out_params(
            template, item=None, index=0, job_params={}, predecessor_outputs={},
        )
        assert result["x"] is None

    def test_nodes_context_available(self):
        """'{{ nodes.validate.crs }}' resolves from predecessor_outputs."""
        template = FanOutTaskDef(handler="process", params={"crs": "{{ nodes.validate.crs }}"})
        result = resolve_fan_out_params(
            template,
            item="x",
            index=0,
            job_params={},
            predecessor_outputs={"validate": {"crs": "4326"}},
        )
        # NativeEnvironment coerces pure-numeric strings to int
        assert result["crs"] == 4326
