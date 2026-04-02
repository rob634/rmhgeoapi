# DAG Workflow Diagram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render left-to-right DAG diagrams from YAML workflow definitions on the job detail page, with runtime status colors when viewing a specific run.

**Architecture:** Server-side Python converts the workflow definition JSONB to a graph JSON structure (nodes + edges). Client-side JS feeds that into dagre for Sugiyama layout, then renders positioned SVG with distinct node shapes per type and status fill colors.

**Tech Stack:** Python (pure function), dagre.js (vendored ~30KB), vanilla JS SVG rendering, Jinja2 templates, CSS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ui/dag_graph.py` | **Create** | Convert definition dict → graph JSON |
| `tests/test_dag_graph.py` | **Create** | Unit tests for graph conversion |
| `static/js/vendor/dagre.min.js` | **Create** | Vendored dagre library |
| `static/js/dag-diagram.js` | **Create** | Dagre layout + SVG rendering |
| `templates/components/_dag_diagram.html` | **Create** | Template fragment with container + script refs |
| `static/css/dag-diagram.css` | **Create** | Diagram-specific styles |
| `templates/pages/jobs/detail.html` | **Modify** | Include diagram above task table |
| `ui_routes.py` | **Modify** | Generate dag_graph JSON in job_detail route |
| `ui_preview.py` | **Modify** | Add mock definition for local preview |

---

### Task 1: Create `ui/dag_graph.py` — definition to graph converter

**Files:**
- Create: `ui/dag_graph.py`
- Create: `tests/test_dag_graph.py`

- [ ] **Step 1: Write tests for the graph converter**

Create `tests/test_dag_graph.py`:

```python
"""Tests for ui.dag_graph — YAML definition to dagre graph conversion."""
import pytest
from ui.dag_graph import definition_to_graph


# Minimal linear workflow: A → B → C
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
    """Test definition_to_graph with various workflow shapes."""

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
        # Conditional creates edges to branch targets
        assert ("route", "process_large") in edge_map
        assert ("route", "process_small") in edge_map
        # Branch labels
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
        statuses = {"download": "completed"}  # validate and upload missing
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
        assert node_map["gather"]["handler"] is None  # fan_in has no handler
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/test_dag_graph.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ui.dag_graph'`

- [ ] **Step 3: Implement `ui/dag_graph.py`**

```python
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
    # graph = {"workflow_name": "...", "nodes": [...], "edges": [...]}
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
        task_statuses: Optional mapping of task_name → status string.
                       When provided, nodes get runtime status.
                       When None, all nodes get status='definition'.

    Returns:
        {
            "workflow_name": str,
            "nodes": [{"id", "label", "type", "handler", "status"}, ...],
            "edges": [{"source", "target", "optional", "label"}, ...],
        }
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/test_dag_graph.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/dag_graph.py tests/test_dag_graph.py
git commit -m "feat(ui): add DAG graph converter — definition to dagre JSON

Pure function that converts WorkflowDefinition JSONB into
{nodes, edges} for client-side dagre layout. Handles all 5
node types, optional deps, conditional branch edges, and
runtime status mapping."
```

---

### Task 2: Vendor dagre.js

**Files:**
- Create: `static/js/vendor/dagre.min.js`

- [ ] **Step 1: Download dagre from CDN**

```bash
mkdir -p /Users/robertharrison/python_builds/rmhgeoapi/static/js/vendor
curl -sL "https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.4/dist/dagre.min.js" \
  -o /Users/robertharrison/python_builds/rmhgeoapi/static/js/vendor/dagre.min.js
```

- [ ] **Step 2: Verify the file is valid JS and has the dagre API**

```bash
head -1 /Users/robertharrison/python_builds/rmhgeoapi/static/js/vendor/dagre.min.js
wc -c /Users/robertharrison/python_builds/rmhgeoapi/static/js/vendor/dagre.min.js
```

Expected: First line should contain a JS comment or start of minified code. Size should be ~30-50KB.

If the CDN URL fails or returns HTML, use this fallback:

```bash
curl -sL "https://unpkg.com/@dagrejs/dagre@1.1.4/dist/dagre.min.js" \
  -o /Users/robertharrison/python_builds/rmhgeoapi/static/js/vendor/dagre.min.js
```

If both CDN URLs fail, check npm: `npm pack @dagrejs/dagre@1.1.4` and extract `dist/dagre.min.js`.

- [ ] **Step 3: Commit**

```bash
git add static/js/vendor/dagre.min.js
git commit -m "vendor: add dagre.js 1.1.4 for DAG diagram layout"
```

---

### Task 3: Create `static/js/dag-diagram.js` — SVG renderer

**Files:**
- Create: `static/js/dag-diagram.js`

- [ ] **Step 1: Create the diagram renderer**

```javascript
/**
 * DAG Diagram Renderer
 *
 * Reads graph JSON from #dag-graph-data, runs dagre layout,
 * renders positioned SVG into #dag-diagram container.
 *
 * Dependencies: dagre.min.js must be loaded first.
 */
(function () {
    'use strict';

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    var CONFIG = {
        rankdir: 'LR',
        ranksep: 60,
        nodesep: 30,
        edgesep: 20,
        marginx: 20,
        marginy: 20,
        nodeHeight: 40,
        minNodeWidth: 100,
        charWidth: 7.5,
        diamondSize: 70,
    };

    var STATUS_COLORS = {
        completed:  { fill: '#d1fae5', stroke: '#059669' },
        running:    { fill: '#dbeafe', stroke: '#0071BC' },
        failed:     { fill: '#fee2e2', stroke: '#dc2626' },
        pending:    { fill: '#f1f5f9', stroke: '#cbd5e1' },
        ready:      { fill: '#f1f5f9', stroke: '#94a3b8' },
        waiting:    { fill: '#fef3c7', stroke: '#f59e0b' },
        skipped:    { fill: '#f1f5f9', stroke: '#cbd5e1' },
        expanded:   { fill: '#ede9fe', stroke: '#8b5cf6' },
        cancelled:  { fill: '#f1f5f9', stroke: '#cbd5e1' },
        definition: { fill: '#f0f9ff', stroke: '#0284c7' },
    };

    var TYPE_COLORS = {
        task:        { fill: '#f0f9ff', stroke: '#0284c7' },
        conditional: { fill: '#fffbeb', stroke: '#d97706' },
        fan_out:     { fill: '#f5f3ff', stroke: '#8b5cf6' },
        fan_in:      { fill: '#f5f3ff', stroke: '#8b5cf6' },
        gate:        { fill: '#fffbeb', stroke: '#f59e0b' },
    };

    // ========================================================================
    // HELPERS
    // ========================================================================

    function nodeWidth(label) {
        return Math.max(label.length * CONFIG.charWidth + 24, CONFIG.minNodeWidth);
    }

    function getColors(node) {
        if (node.status === 'definition') {
            return TYPE_COLORS[node.type] || TYPE_COLORS.task;
        }
        return STATUS_COLORS[node.status] || STATUS_COLORS.pending;
    }

    function svgEl(tag, attrs) {
        var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        if (attrs) {
            for (var k in attrs) {
                el.setAttribute(k, attrs[k]);
            }
        }
        return el;
    }

    // ========================================================================
    // SHAPE RENDERERS
    // ========================================================================

    function renderRect(svg, x, y, w, h, colors, label) {
        var rect = svgEl('rect', {
            x: x - w / 2, y: y - h / 2,
            width: w, height: h, rx: 6,
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '1.5',
        });
        svg.appendChild(rect);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '11', 'font-weight': '500',
        });
        text.textContent = label;
        svg.appendChild(text);
        return rect;
    }

    function renderDiamond(svg, x, y, size, colors, label) {
        var hs = size / 2;
        var points = [x, y - hs, x + hs, y, x, y + hs, x - hs, y].join(',');
        var poly = svgEl('polygon', {
            points: points,
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '1.5',
        });
        svg.appendChild(poly);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '10', 'font-weight': '500',
        });
        text.textContent = label.length > 12 ? label.substring(0, 11) + '…' : label;
        svg.appendChild(text);
    }

    function renderTrapezoid(svg, x, y, w, h, colors, label, inverted) {
        var hw = w / 2, hh = h / 2;
        var inset = 10;
        var pts;
        if (inverted) {
            // fan_in: narrow top, wide bottom
            pts = [x - hw + inset, y - hh, x + hw - inset, y - hh, x + hw, y + hh, x - hw, y + hh];
        } else {
            // fan_out: wide top, narrow bottom
            pts = [x - hw, y - hh, x + hw, y - hh, x + hw - inset, y + hh, x - hw + inset, y + hh];
        }
        var poly = svgEl('polygon', {
            points: pts.join(','),
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '1.5',
        });
        svg.appendChild(poly);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '10', 'font-weight': '500',
        });
        text.textContent = label;
        svg.appendChild(text);
    }

    function renderOctagon(svg, x, y, w, h, colors, label) {
        var hw = w / 2, hh = h / 2;
        var cut = 10;
        var pts = [
            x - hw + cut, y - hh,
            x + hw - cut, y - hh,
            x + hw, y - hh + cut,
            x + hw, y + hh - cut,
            x + hw - cut, y + hh,
            x - hw + cut, y + hh,
            x - hw, y + hh - cut,
            x - hw, y - hh + cut,
        ];
        var poly = svgEl('polygon', {
            points: pts.join(','),
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '2',
        });
        svg.appendChild(poly);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '10', 'font-weight': '600',
        });
        text.textContent = label;
        svg.appendChild(text);
    }

    // ========================================================================
    // STATUS BADGES
    // ========================================================================

    function renderStatusBadge(svg, x, y, w, h, status) {
        var bx = x + w / 2 - 2;
        var by = y - h / 2 - 2;
        var r = 7;

        if (status === 'completed' || status === 'expanded') {
            var circle = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#059669' });
            svg.appendChild(circle);
            var check = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '10', 'font-weight': 'bold' });
            check.textContent = '✓';
            svg.appendChild(check);
        } else if (status === 'failed') {
            var circle = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#dc2626' });
            svg.appendChild(circle);
            var x_mark = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '10', 'font-weight': 'bold' });
            x_mark.textContent = '✕';
            svg.appendChild(x_mark);
        } else if (status === 'running') {
            var circle = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#0071BC' });
            svg.appendChild(circle);
            var anim = svgEl('animate', { attributeName: 'r', values: '6;8;6', dur: '1.5s', repeatCount: 'indefinite' });
            circle.appendChild(anim);
            var play = svgEl('text', { x: bx, y: by + 3.5, 'text-anchor': 'middle', fill: 'white', 'font-size': '8', 'font-weight': 'bold' });
            play.textContent = '▶';
            svg.appendChild(play);
        } else if (status === 'waiting') {
            var circle = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#f59e0b' });
            svg.appendChild(circle);
            var pause = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '9', 'font-weight': 'bold' });
            pause.textContent = '⏸';
            svg.appendChild(pause);
        } else if (status === 'skipped') {
            var circle = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#94a3b8' });
            svg.appendChild(circle);
            var dash = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '12', 'font-weight': 'bold' });
            dash.textContent = '–';
            svg.appendChild(dash);
        }
        // pending, ready, definition: no badge
    }

    // ========================================================================
    // EDGE RENDERER
    // ========================================================================

    function renderEdge(svg, points, optional, label) {
        var d = 'M ' + points[0].x + ',' + points[0].y;
        if (points.length === 2) {
            d += ' L ' + points[1].x + ',' + points[1].y;
        } else if (points.length >= 3) {
            // Use quadratic bezier through intermediate points
            for (var i = 1; i < points.length - 1; i++) {
                var cp = points[i];
                var end = (i < points.length - 2)
                    ? { x: (cp.x + points[i + 1].x) / 2, y: (cp.y + points[i + 1].y) / 2 }
                    : points[i + 1];
                d += ' Q ' + cp.x + ',' + cp.y + ' ' + end.x + ',' + end.y;
            }
        }

        var attrs = {
            d: d, fill: 'none',
            stroke: optional ? '#cbd5e1' : '#94a3b8',
            'stroke-width': '1.5',
            'marker-end': optional ? 'url(#arrow-opt)' : 'url(#arrow)',
        };
        if (optional) {
            attrs['stroke-dasharray'] = '5,3';
        }
        svg.appendChild(svgEl('path', attrs));

        // Edge label
        if (label) {
            var mid = points[Math.floor(points.length / 2)];
            var labelEl = svgEl('text', {
                x: mid.x, y: mid.y - 8,
                'text-anchor': 'middle', fill: '#6b7280',
                'font-size': '9', 'font-style': 'italic',
            });
            labelEl.textContent = label;
            svg.appendChild(labelEl);
        }
    }

    // ========================================================================
    // MAIN RENDER
    // ========================================================================

    function renderDiagram(containerId, dataId) {
        var dataEl = document.getElementById(dataId);
        if (!dataEl) return;

        var graphData;
        try {
            graphData = JSON.parse(dataEl.textContent);
        } catch (e) {
            return;
        }

        if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
            var container = document.getElementById(containerId);
            if (container) container.innerHTML = '<p style="color: #94a3b8; padding: 16px;">No workflow definition available.</p>';
            return;
        }

        // Build dagre graph
        var g = new dagre.graphlib.Graph();
        g.setGraph({
            rankdir: CONFIG.rankdir,
            ranksep: CONFIG.ranksep,
            nodesep: CONFIG.nodesep,
            edgesep: CONFIG.edgesep,
            marginx: CONFIG.marginx,
            marginy: CONFIG.marginy,
        });
        g.setDefaultEdgeLabel(function () { return {}; });

        // Add nodes
        var nodeMap = {};
        graphData.nodes.forEach(function (n) {
            nodeMap[n.id] = n;
            var w, h;
            if (n.type === 'conditional') {
                w = CONFIG.diamondSize;
                h = CONFIG.diamondSize;
            } else {
                w = nodeWidth(n.label);
                h = CONFIG.nodeHeight;
            }
            g.setNode(n.id, { width: w, height: h, label: n.label });
        });

        // Add edges
        graphData.edges.forEach(function (e) {
            if (g.hasNode(e.source) && g.hasNode(e.target)) {
                g.setEdge(e.source, e.target, { label: e.label || '', optional: e.optional });
            }
        });

        // Run layout
        dagre.layout(g);

        // Create SVG
        var graph = g.graph();
        var svgWidth = graph.width || 600;
        var svgHeight = graph.height || 200;

        var svg = svgEl('svg', {
            viewBox: '0 0 ' + svgWidth + ' ' + svgHeight,
            width: '100%',
            style: 'min-width: ' + Math.min(svgWidth, 400) + 'px; height: auto; font-family: system-ui, -apple-system, sans-serif;',
        });

        // Arrow markers
        var defs = svgEl('defs');
        var marker = svgEl('marker', {
            id: 'arrow', markerWidth: '8', markerHeight: '6', refX: '8', refY: '3', orient: 'auto',
        });
        marker.appendChild(svgEl('path', { d: 'M0,0 L8,3 L0,6', fill: '#94a3b8' }));
        defs.appendChild(marker);

        var markerOpt = svgEl('marker', {
            id: 'arrow-opt', markerWidth: '8', markerHeight: '6', refX: '8', refY: '3', orient: 'auto',
        });
        markerOpt.appendChild(svgEl('path', { d: 'M0,0 L8,3 L0,6', fill: '#cbd5e1' }));
        defs.appendChild(markerOpt);
        svg.appendChild(defs);

        // Render edges (behind nodes)
        g.edges().forEach(function (e) {
            var edgeData = g.edge(e);
            var edgeDef = graphData.edges.find(function (ed) {
                return ed.source === e.v && ed.target === e.w;
            });
            renderEdge(svg, edgeData.points, edgeDef ? edgeDef.optional : false, edgeDef ? edgeDef.label : '');
        });

        // Render nodes
        g.nodes().forEach(function (id) {
            var pos = g.node(id);
            var node = nodeMap[id];
            if (!node) return;

            var colors = getColors(node);
            var w = pos.width, h = pos.height;

            switch (node.type) {
                case 'conditional':
                    renderDiamond(svg, pos.x, pos.y, CONFIG.diamondSize, colors, node.label);
                    break;
                case 'fan_out':
                    renderTrapezoid(svg, pos.x, pos.y, w, h, colors, node.label, false);
                    break;
                case 'fan_in':
                    renderTrapezoid(svg, pos.x, pos.y, w, h, colors, node.label, true);
                    break;
                case 'gate':
                    renderOctagon(svg, pos.x, pos.y, w, h, colors, node.label);
                    break;
                default:
                    renderRect(svg, pos.x, pos.y, w, h, colors, node.label);
            }

            // Status badge (only for run context)
            if (node.status !== 'definition') {
                renderStatusBadge(svg, pos.x, pos.y, w, h, node.status);
            }
        });

        // Mount
        var container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = '';
            container.appendChild(svg);
        }
    }

    // ========================================================================
    // INIT
    // ========================================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            renderDiagram('dag-diagram', 'dag-graph-data');
        });
    } else {
        renderDiagram('dag-diagram', 'dag-graph-data');
    }

})();
```

- [ ] **Step 2: Commit**

```bash
git add static/js/dag-diagram.js
git commit -m "feat(ui): add DAG diagram SVG renderer

Client-side JS that reads graph JSON, runs dagre layout,
and renders positioned SVG with distinct shapes per node
type and status fill colors. Supports task (rect), conditional
(diamond), fan_out (trapezoid), fan_in (inv. trapezoid),
and gate (octagon) shapes."
```

---

### Task 4: Create template fragment and CSS

**Files:**
- Create: `templates/components/_dag_diagram.html`
- Create: `static/css/dag-diagram.css`

- [ ] **Step 1: Create the template fragment**

Create `templates/components/_dag_diagram.html`:

```html
{# ============================================================================
   DAG DIAGRAM COMPONENT
   ============================================================================
   Renders a workflow DAG diagram from definition JSON.

   Context variables:
       dag_graph: Dict from definition_to_graph() with nodes + edges,
                  or None if no definition available.
   ============================================================================ #}

{% if dag_graph %}
<div class="section-card dag-diagram-section">
    <h3 class="section-title">Workflow</h3>
    <div id="dag-diagram" class="dag-container"></div>
    <div class="dag-legend">
        {% set status_val = dag_graph.nodes[0].status if dag_graph.nodes else 'definition' %}
        {% if status_val != 'definition' %}
        <span class="dag-legend-item"><span class="dag-legend-dot" style="background: #d1fae5; border-color: #059669;"></span>Completed</span>
        <span class="dag-legend-item"><span class="dag-legend-dot" style="background: #dbeafe; border-color: #0071BC;"></span>Running</span>
        <span class="dag-legend-item"><span class="dag-legend-dot" style="background: #f1f5f9; border-color: #cbd5e1;"></span>Pending</span>
        <span class="dag-legend-item"><span class="dag-legend-dot" style="background: #fee2e2; border-color: #dc2626;"></span>Failed</span>
        <span class="dag-legend-item"><span class="dag-legend-dot" style="background: #fef3c7; border-color: #f59e0b;"></span>Waiting</span>
        {% endif %}
        <span class="dag-legend-item dag-legend-shape">&#x25AD; task</span>
        <span class="dag-legend-item dag-legend-shape">&#x25C7; conditional</span>
        <span class="dag-legend-item dag-legend-shape">&#x2B21; gate</span>
    </div>
</div>
<script type="application/json" id="dag-graph-data">{{ dag_graph | tojson }}</script>
{% endif %}
```

- [ ] **Step 2: Create the CSS**

Create `static/css/dag-diagram.css`:

```css
/* DAG Diagram Component */
.dag-diagram-section {
    margin-bottom: 16px;
}

.dag-container {
    overflow-x: auto;
    padding: 12px 0;
    max-height: 350px;
    background: #fafbfc;
    border-radius: 3px;
    border: 1px solid #e9ecef;
}

.dag-container svg {
    display: block;
    margin: 0 auto;
}

.dag-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    padding: 8px 12px;
    font-size: 11px;
    color: #626F86;
    border-top: 1px solid #e9ecef;
}

.dag-legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
}

.dag-legend-dot {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 2px;
    border: 1.5px solid;
}

.dag-legend-shape {
    color: #94a3b8;
    font-size: 12px;
}
```

- [ ] **Step 3: Commit**

```bash
git add templates/components/_dag_diagram.html static/css/dag-diagram.css
git commit -m "feat(ui): add DAG diagram template fragment and CSS

Template includes diagram container, graph JSON injection,
and status/shape legend. CSS handles scroll container and legend strip."
```

---

### Task 5: Wire into job detail page and route

**Files:**
- Modify: `templates/pages/jobs/detail.html`
- Modify: `ui_routes.py`

- [ ] **Step 1: Add diagram include to detail template**

In `templates/pages/jobs/detail.html`, add three things:

1. Add CSS link in `{% block head %}` after `jobs.css`:
```html
<link rel="stylesheet" href="/static/css/dag-diagram.css">
```

2. Add the diagram include as the FIRST child inside `.job-detail-main`, before the Parameters section:
```html
{% include "components/_dag_diagram.html" %}
```

3. Add script includes at the end, before `{% endblock %}`:
```html
<script src="/static/js/vendor/dagre.min.js"></script>
<script src="/static/js/dag-diagram.js"></script>
```

- [ ] **Step 2: Add graph generation to the route**

In `ui_routes.py`, modify `job_detail()`. After the existing `tasks = repo.list_task_details(run_id)` line, add:

```python
    # Build DAG graph JSON from workflow definition snapshot
    dag_graph = None
    if run.definition:
        from ui.dag_graph import definition_to_graph
        task_statuses = {t["task_name"]: t["status"] for t in tasks}
        dag_graph = definition_to_graph(run.definition, task_statuses=task_statuses)
```

Then add `dag_graph=dag_graph` to the `render_template()` call.

- [ ] **Step 3: Verify route compiles**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from ui_routes import router; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add templates/pages/jobs/detail.html ui_routes.py
git commit -m "feat(ui): wire DAG diagram into job detail page

Detail page now shows workflow diagram above task table.
Route generates graph JSON from WorkflowRun.definition
with runtime task statuses mapped onto nodes."
```

---

### Task 6: Update preview server with mock definition

**Files:**
- Modify: `ui_preview.py`

- [ ] **Step 1: Add mock definition and graph generation to preview**

In `ui_preview.py`, add a `MOCK_DEFINITION` dict that mirrors `process_raster` YAML structure (the `definition` JSONB after `model_dump()`). Then update the `job_detail` route to generate `dag_graph` and pass it to the template.

Add this constant after `MOCK_TASK_COUNTS`:

```python
MOCK_DEFINITION = {
    "workflow": "process_raster",
    "nodes": {
        "download_source": {"type": "task", "handler": "raster_download_source", "depends_on": []},
        "validate": {"type": "task", "handler": "raster_validate_atomic", "depends_on": ["download_source"]},
        "route_by_size": {
            "type": "conditional",
            "depends_on": ["validate"],
            "condition": "download_source.result.file_size_bytes",
            "branches": [
                {"name": "large", "condition": "gt 2000000000", "default": False, "next": ["generate_tiling_scheme"]},
                {"name": "standard", "default": True, "next": ["create_single_cog"]},
            ],
        },
        "create_single_cog": {"type": "task", "handler": "raster_create_cog_atomic", "depends_on": []},
        "upload_single_cog": {"type": "task", "handler": "raster_upload_cog", "depends_on": ["create_single_cog"]},
        "persist_single": {"type": "task", "handler": "raster_persist_app_tables", "depends_on": ["upload_single_cog"]},
        "generate_tiling_scheme": {"type": "task", "handler": "raster_generate_tiling_scheme_atomic", "depends_on": []},
        "process_tiles": {
            "type": "fan_out",
            "depends_on": ["generate_tiling_scheme"],
            "source": "generate_tiling_scheme.result.tile_specs",
            "task": {"handler": "raster_process_single_tile", "params": {}},
        },
        "aggregate_tiles": {"type": "fan_in", "depends_on": ["process_tiles"], "aggregation": "collect"},
        "persist_tiled": {"type": "task", "handler": "raster_persist_tiled", "depends_on": ["aggregate_tiles"]},
        "approval_gate": {"type": "gate", "depends_on": ["persist_single?", "persist_tiled?"], "gate_type": "approval"},
        "materialize_single_item": {"type": "task", "handler": "stac_materialize_item", "depends_on": ["approval_gate"]},
        "materialize_collection": {"type": "task", "handler": "stac_materialize_collection", "depends_on": ["materialize_single_item?"]},
    },
}
```

Then update the `job_detail` route to pass `dag_graph`:

```python
@router.get("/jobs/{run_id}", response_class=HTMLResponse)
async def job_detail(request: Request, run_id: str):
    run_data = next((r for r in MOCK_RUNS if r["run_id"] == run_id), MOCK_RUNS[0])

    run = MockRun(run_data)
    run.status = MockRun.status_proxy(run_data["status"])
    run.definition = MOCK_DEFINITION

    # Build DAG graph with mock statuses
    from ui.dag_graph import definition_to_graph
    task_statuses = {t["task_name"]: t["status"] for t in MOCK_TASKS}
    dag_graph = definition_to_graph(MOCK_DEFINITION, task_statuses=task_statuses)

    return render_template(
        request, "pages/jobs/detail.html",
        job=run, tasks=MOCK_TASKS, task_counts=MOCK_TASK_COUNTS,
        dag_graph=dag_graph, nav_active="/ui/jobs",
    )
```

- [ ] **Step 2: Test locally**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python ui_preview.py
```

Open `http://localhost:8090/ui/jobs/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6abcd` — should show the DAG diagram above the task table.

Verify:
- Diagram renders left-to-right
- `download_source` → `validate` → `route_by_size` (diamond) → branches
- Status colors: completed nodes are green, running are blue, pending are gray
- Approval gate shows as octagon
- Fan-out/fan-in show as trapezoids
- Legend strip visible below diagram

- [ ] **Step 3: Kill the preview server and commit**

```bash
lsof -ti:8090 | xargs kill 2>/dev/null
git add ui_preview.py
git commit -m "feat(ui): add mock workflow definition to preview server

Preview now shows DAG diagram with process_raster workflow
and mixed task statuses for visual testing."
```
