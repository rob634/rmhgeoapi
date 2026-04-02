"""Tests for ui.dag_graph — YAML definition to dagre graph conversion."""
import pytest
from ui.dag_graph import definition_to_graph


# Minimal linear workflow: A -> B -> C
LINEAR_DEF = {
    "workflow": "test_linear",
    "nodes": {
        "download": {"type": "task", "handler": "download_handler", "depends_on": []},
        "validate": {"type": "task", "handler": "validate_handler", "depends_on": ["download"]},
        "upload": {"type": "task", "handler": "upload_handler", "depends_on": ["validate"]},
    }
}

# Workflow with conditional branching
CONDITIONAL_DEF = {
    "workflow": "test_conditional",
    "nodes": {
        "validate": {"type": "task", "handler": "validate_handler", "depends_on": []},
        "route": {
            "type": "conditional",
            "depends_on": ["validate"],
            "condition": "validate.result.size",
            "branches": [
                {"name": "large", "condition": "gt 1000", "default": False, "next": ["process_large"]},
                {"name": "small", "default": True, "next": ["process_small"]},
            ],
        },
        "process_large": {"type": "task", "handler": "large_handler", "depends_on": []},
        "process_small": {"type": "task", "handler": "small_handler", "depends_on": []},
    }
}

# Workflow with fan-out, fan-in, and gate
FANOUT_GATE_DEF = {
    "workflow": "test_fanout",
    "nodes": {
        "prepare": {"type": "task", "handler": "prep_handler", "depends_on": []},
        "scatter": {
            "type": "fan_out",
            "depends_on": ["prepare"],
            "source": "prepare.result.items",
            "task": {"handler": "item_handler", "params": {}},
        },
        "gather": {"type": "fan_in", "depends_on": ["scatter"], "aggregation": "collect"},
        "gate": {"type": "gate", "depends_on": ["gather"], "gate_type": "approval"},
        "finalize": {"type": "task", "handler": "final_handler", "depends_on": ["gate"]},
    }
}

# Workflow with optional dependencies (? suffix)
OPTIONAL_DEF = {
    "workflow": "test_optional",
    "nodes": {
        "path_a": {"type": "task", "handler": "a_handler", "depends_on": []},
        "path_b": {"type": "task", "handler": "b_handler", "depends_on": []},
        "merge": {"type": "task", "handler": "merge_handler", "depends_on": ["path_a?", "path_b?"]},
    }
}


class TestDefinitionToGraph:
    def test_linear_nodes(self):
        result = definition_to_graph(LINEAR_DEF)
        assert result["workflow_name"] == "test_linear"
        assert len(result["nodes"]) == 3
        ids = {n["id"] for n in result["nodes"]}
        assert ids == {"download", "validate", "upload"}

    def test_linear_edges(self):
        result = definition_to_graph(LINEAR_DEF)
        edges = result["edges"]
        assert len(edges) == 2
        edge_pairs = [(e["source"], e["target"]) for e in edges]
        assert ("download", "validate") in edge_pairs
        assert ("validate", "upload") in edge_pairs
        assert all(e["optional"] is False for e in edges)

    def test_node_types_preserved(self):
        result = definition_to_graph(CONDITIONAL_DEF)
        node_map = {n["id"]: n for n in result["nodes"]}
        assert node_map["validate"]["type"] == "task"
        assert node_map["route"]["type"] == "conditional"

    def test_conditional_branch_edges(self):
        result = definition_to_graph(CONDITIONAL_DEF)
        edges = result["edges"]
        edge_map = {(e["source"], e["target"]): e for e in edges}
        assert ("route", "process_large") in edge_map
        assert ("route", "process_small") in edge_map
        assert edge_map[("route", "process_large")]["label"] == "large"
        assert edge_map[("route", "process_small")]["label"] == "small"

    def test_fanout_gate_types(self):
        result = definition_to_graph(FANOUT_GATE_DEF)
        node_map = {n["id"]: n for n in result["nodes"]}
        assert node_map["scatter"]["type"] == "fan_out"
        assert node_map["gather"]["type"] == "fan_in"
        assert node_map["gate"]["type"] == "gate"

    def test_optional_dependencies(self):
        result = definition_to_graph(OPTIONAL_DEF)
        edges = result["edges"]
        edge_map = {(e["source"], e["target"]): e for e in edges}
        assert edge_map[("path_a", "merge")]["optional"] is True
        assert edge_map[("path_b", "merge")]["optional"] is True

    def test_status_mapping(self):
        statuses = {"download": "completed", "validate": "running", "upload": "pending"}
        result = definition_to_graph(LINEAR_DEF, task_statuses=statuses)
        node_map = {n["id"]: n for n in result["nodes"]}
        assert node_map["download"]["status"] == "completed"
        assert node_map["validate"]["status"] == "running"
        assert node_map["upload"]["status"] == "pending"

    def test_no_status_defaults_to_definition(self):
        result = definition_to_graph(LINEAR_DEF)
        assert all(n["status"] == "definition" for n in result["nodes"])

    def test_missing_status_defaults_to_pending(self):
        statuses = {"download": "completed"}
        result = definition_to_graph(LINEAR_DEF, task_statuses=statuses)
        node_map = {n["id"]: n for n in result["nodes"]}
        assert node_map["download"]["status"] == "completed"
        assert node_map["validate"]["status"] == "pending"
        assert node_map["upload"]["status"] == "pending"

    def test_empty_definition_returns_empty_graph(self):
        result = definition_to_graph({"workflow": "empty", "nodes": {}})
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_handler_included_for_task_nodes(self):
        result = definition_to_graph(LINEAR_DEF)
        node_map = {n["id"]: n for n in result["nodes"]}
        assert node_map["download"]["handler"] == "download_handler"

    def test_handler_none_for_non_task_nodes(self):
        result = definition_to_graph(FANOUT_GATE_DEF)
        node_map = {n["id"]: n for n in result["nodes"]}
        assert node_map["gather"]["handler"] is None
