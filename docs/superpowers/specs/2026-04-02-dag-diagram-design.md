# DAG Workflow Diagram — Design Spec

**Date:** 02 APR 2026
**Status:** Approved
**Author:** Robert + Claude

---

## Goal

Render a left-to-right DAG diagram from YAML workflow definitions on the job detail page. When viewing a specific workflow run, node fill colors reflect runtime task status. The diagram sits above the task execution table, giving structural overview while the table gives execution details.

## Architecture

Three layers, each with a single responsibility:

### Layer 1: YAML → Graph JSON (Python, server-side)

**File:** `ui/dag_graph.py`

Pure function that takes a workflow definition dict (the `definition` JSONB from `WorkflowRun`, which is a snapshot of the YAML at submission time) and returns a graph JSON structure:

```python
def definition_to_graph(definition: dict, task_statuses: dict[str, str] | None = None) -> dict:
    """
    Convert workflow YAML definition to a dagre-compatible graph.

    Args:
        definition: The workflow YAML definition dict (from WorkflowRun.definition)
        task_statuses: Optional mapping of task_name → status string
                       (from list_task_details). When provided, nodes get
                       a 'status' field. When None, nodes get status='definition'
                       (for future standalone YAML viewer).

    Returns:
        {
            "nodes": [
                {"id": "validate", "label": "validate", "type": "task", "handler": "raster_validate_atomic", "status": "completed"},
                {"id": "route_by_size", "label": "route_by_size", "type": "conditional", "status": "pending"},
                ...
            ],
            "edges": [
                {"source": "download_source", "target": "validate", "optional": false},
                {"source": "persist_single", "target": "approval_gate", "optional": true, "label": ""},
                ...
            ],
            "workflow_name": "process_raster"
        }
    """
```

**Edge extraction rules:**
- `depends_on: [node_a]` → edge from `node_a` to this node, `optional: false`
- `depends_on: ["node_a?"]` → edge from `node_a` to this node, `optional: true` (strip `?`)
- `conditional.branches[].next: [node_b]` → edge from conditional to `node_b`, with branch `name` as label
- `fan_out` → edge from fan_out to its implicit fan_in (via `depends_on` on the fan_in node)

**Status mapping:** When `task_statuses` is provided, match `task_name` to the task status. Fan-out nodes use the template node's status (expanded/completed). If a task_name has no match, default to `"pending"`.

### Layer 2: Dagre Layout (JS, client-side)

**File:** `static/js/vendor/dagre.min.js` (vendored, ~30KB)

Dagre is a JavaScript implementation of the Sugiyama hierarchical layout algorithm. It computes node positions and edge control points.

Configuration:
```javascript
var g = new dagre.graphlib.Graph();
g.setGraph({rankdir: 'LR', ranksep: 60, nodesep: 30, edgesep: 20, marginx: 20, marginy: 20});
g.setDefaultEdgeLabel(function() { return {}; });
```

Node dimensions are set based on type:
- `task`: width = max(label.length * 8, 100), height = 40
- `conditional`: width = 80, height = 80
- `fan_out`, `fan_in`: width = max(label.length * 8, 90), height = 40
- `gate`: width = max(label.length * 8, 80), height = 40

### Layer 3: SVG Rendering (JS, client-side)

**File:** `static/js/dag-diagram.js`

Reads graph JSON from a `<script type="application/json">` tag injected by the template. Runs dagre layout, then draws SVG into a container div.

**Node shapes by type:**

| Type | Shape | SVG Element |
|------|-------|-------------|
| `task` | Rounded rectangle | `<rect rx="6">` |
| `conditional` | Diamond | `<polygon>` (4 points, rotated square) |
| `fan_out` | Trapezoid (wide top) | `<polygon>` (4 points) |
| `fan_in` | Inverted trapezoid (wide bottom) | `<polygon>` (4 points) |
| `gate` | Octagon | `<polygon>` (8 points) |

**Status colors (when viewing a run):**

| Status | Fill | Border | Annotation |
|--------|------|--------|------------|
| `completed` | `#d1fae5` | `#059669` | Checkmark badge |
| `running` | `#dbeafe` | `#0071BC` | Pulse animation on border |
| `failed` | `#fee2e2` | `#dc2626` | X badge |
| `pending` | `#f1f5f9` | `#cbd5e1` | None (muted) |
| `ready` | `#f1f5f9` | `#94a3b8` | None (slightly less muted than pending) |
| `waiting` | `#fef3c7` | `#f59e0b` | Pause icon badge |
| `skipped` | `#f1f5f9` | `#cbd5e1` | Dash badge |
| `expanded` | `#ede9fe` | `#8b5cf6` | Treat as completed for display |
| `definition` | Type-specific colors | Type-specific border | None (YAML view, no runtime context) |

**Edge rendering:**
- Normal dependency: solid line, `stroke: #94a3b8`, arrow marker at target
- Optional dependency (`?`): dashed line (`stroke-dasharray: 5,3`), lighter stroke `#cbd5e1`
- Conditional branch: edge label positioned at midpoint, italic, small font
- All edges use bezier curves (dagre provides control points)

**Container:**
- Fixed max-height (300px), horizontal scroll if diagram exceeds container width
- SVG `viewBox` computed from dagre's graph dimensions
- Legend strip below the diagram showing status colors

### Template Integration

**File:** `templates/components/_dag_diagram.html`

```html
<div class="section-card dag-diagram-section">
    <h3 class="section-title">Workflow</h3>
    <div id="dag-diagram" class="dag-container"></div>
    <div class="dag-legend">...</div>
</div>
<script type="application/json" id="dag-graph-data">{{ dag_graph | tojson }}</script>
```

Included in `templates/pages/jobs/detail.html` above the task table section.

**File:** `templates/pages/jobs/detail.html` (modified)

Add `{% include "components/_dag_diagram.html" %}` as the first child of `.job-detail-main`, before the Parameters section. Add `<script src="/static/js/vendor/dagre.min.js">` and `<script src="/static/js/dag-diagram.js">` in the scripts block.

### Route Changes

**File:** `ui_routes.py` (modified)

In `job_detail()`, after fetching run and tasks:

```python
from ui.dag_graph import definition_to_graph

# Build status map from task details
task_statuses = {t["task_name"]: t["status"] for t in tasks}

# Generate graph JSON from the YAML snapshot
dag_graph = definition_to_graph(run.definition, task_statuses) if run.definition else None
```

Pass `dag_graph=dag_graph` to `render_template()`.

## Data Flow Summary

```
WorkflowRun.definition (YAML snapshot JSONB)
    ↓
definition_to_graph(definition, task_statuses)  [Python, server-side]
    ↓
Graph JSON {nodes: [...], edges: [...]}
    ↓
<script type="application/json"> in HTML
    ↓
dagre.layout(graph)  [JS, client-side]
    ↓
SVG rendering into #dag-diagram container
```

## Scope

**In scope:**
- Render DAG from workflow definition YAML snapshot
- Left-to-right Sugiyama layout via dagre
- 5 distinct node shapes (task, conditional, fan_out, fan_in, gate)
- Status fill colors when viewing a run
- Optional dependency edges (dashed)
- Conditional branch labels on edges
- Legend strip
- Horizontal scroll for wide diagrams

**Out of scope (future):**
- Real-time status updates (next priority — refresh for now)
- Click-to-select nodes / node detail popover
- Standalone workflow definition browser page
- Expanded fan-out instance visualization (fan-out shows as single node)
- Zoom/pan controls
- Drag-to-rearrange

## File Inventory

| File | Action | Lines (est) |
|------|--------|-------------|
| `ui/dag_graph.py` | **Create** | ~80 |
| `static/js/dag-diagram.js` | **Create** | ~200 |
| `static/js/vendor/dagre.min.js` | **Create** (vendor) | ~30KB |
| `templates/components/_dag_diagram.html` | **Create** | ~30 |
| `templates/pages/jobs/detail.html` | **Modify** | +5 lines |
| `ui_routes.py` | **Modify** | +8 lines |
| `static/css/jobs.css` | **Modify** | +40 lines (diagram styles) |
