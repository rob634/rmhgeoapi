# ============================================================================
# CLAUDE CONTEXT - DAG GRAPH CONVERTER
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: UI - Convert workflow definition to dagre-compatible graph JSON
# PURPOSE: Parse YAML definition dict into {nodes, edges} for client-side rendering
# LAST_REVIEWED: 02 APR 2026
# EXPORTS: definition_to_graph
# DEPENDENCIES: none (pure function)
# ============================================================================
"""
DAG Graph Converter.

Converts a WorkflowDefinition dict (from WorkflowRun.definition JSONB)
into a graph JSON structure for dagre layout + SVG rendering.

Usage:
    from ui.dag_graph import definition_to_graph

    graph = definition_to_graph(run.definition, task_statuses={"validate": "completed"})
"""
from typing import Optional


def definition_to_graph(
    definition: dict,
    task_statuses: Optional[dict[str, str]] = None,
) -> dict:
    """
    Convert workflow YAML definition to a dagre-compatible graph.

    Args:
        definition: Workflow definition dict (from WorkflowRun.definition).
                    Must have 'workflow' (str) and 'nodes' (dict) keys.
        task_statuses: Optional mapping of task_name -> status string.
                       When provided, nodes get runtime status.
                       When None, all nodes get status='definition'.

    Returns:
        {"workflow_name": str, "nodes": [...], "edges": [...]}
    """
    workflow_name = definition.get("workflow", "unknown")
    raw_nodes = definition.get("nodes", {})

    nodes = []
    edges = []

    for name, node_def in raw_nodes.items():
        node_type = node_def.get("type", "task")

        # Resolve handler (only task and fan_out have one)
        handler = None
        if node_type == "task":
            handler = node_def.get("handler")
        elif node_type == "fan_out":
            task_def = node_def.get("task", {})
            handler = task_def.get("handler")

        # Resolve status
        if task_statuses is not None:
            status = task_statuses.get(name, "pending")
        else:
            status = "definition"

        nodes.append({
            "id": name,
            "label": name,
            "type": node_type,
            "handler": handler,
            "status": status,
        })

        # Extract edges from depends_on
        for dep in node_def.get("depends_on", []):
            optional = dep.endswith("?")
            dep_name = dep.rstrip("?")
            edges.append({
                "source": dep_name,
                "target": name,
                "optional": optional,
                "label": "",
            })

        # Extract edges from conditional branches
        if node_type == "conditional":
            for branch in node_def.get("branches", []):
                branch_name = branch.get("name", "")
                for target in branch.get("next", []):
                    edges.append({
                        "source": name,
                        "target": target,
                        "optional": False,
                        "label": branch_name,
                    })

    return {
        "workflow_name": workflow_name,
        "nodes": nodes,
        "edges": edges,
    }
