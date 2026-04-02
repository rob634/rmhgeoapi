# DAG UI Rewire — Workflow Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire the DAG Brain admin UI to read from `app.workflow_runs` / `app.workflow_tasks` instead of the legacy `app.jobs` / `app.tasks` tables.

**Architecture:** The UI routes call `WorkflowRunRepository` directly (no HTTP proxy). Repository methods `list_runs()` and `list_task_details()` return dicts. We skip DTOs — templates consume dicts directly via Jinja2's transparent dict/attribute access. The converters.py and dto.py legacy adapter layer is replaced by thin dict-returning helpers where needed.

**Tech Stack:** FastAPI routes, Jinja2 templates, WorkflowRunRepository (psycopg3), vanilla JS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ui_routes.py` | **Modify** | Rewire 3 routes + dashboard stats to WorkflowRunRepository |
| `templates/pages/jobs/list.html` | **Modify** | Update field names + status values for workflow_runs |
| `templates/pages/jobs/detail.html` | **Modify** | Replace stage progress with task progress, update field names |
| `templates/components/_job_card.html` | **Modify** | Update field names for workflow_run dicts |
| `templates/pages/dashboard.html` | **Modify** | Update stats labels (jobs → runs) |

**Not touched (future cleanup):**
- `ui/adapters/converters.py` — legacy JobRecord converters, unused after rewire
- `ui/adapters/__init__.py` — will be cleaned separately
- `ui/dto.py` — DTO classes no longer used by routes

---

## Data Shape Reference

**`list_runs()` returns:**
```python
{"run_id", "workflow_name", "status", "created_at", "started_at", "completed_at", "request_id"}
```
Status values: `pending`, `running`, `completed`, `failed`, `awaiting_approval`

**`get_by_run_id()` returns `WorkflowRun` Pydantic model with:**
```python
run_id, workflow_name, parameters, status, definition, platform_version,
result_data, created_at, started_at, completed_at, request_id, asset_id,
release_id, schedule_id, legacy_job_id
```

**`list_task_details()` returns:**
```python
{"task_instance_id", "task_name", "handler", "status", "fan_out_index",
 "fan_out_source", "when_clause", "result_data", "error_details",
 "retry_count", "max_retries", "claimed_by", "last_pulse", "execute_after",
 "started_at", "completed_at", "created_at"}
```
Status values: `pending`, `ready`, `running`, `completed`, `failed`, `skipped`, `expanded`, `cancelled`, `waiting`

**`get_task_status_counts()` returns:**
```python
{"ready": 3, "running": 1, "completed": 10, ...}
```

---

### Task 1: Rewire ui_routes.py — Job List

**Files:**
- Modify: `ui_routes.py:42-70` (job_list route)

- [ ] **Step 1: Replace job_list route implementation**

Replace the entire `job_list` function with WorkflowRunRepository calls:

```python
@router.get("/jobs", response_class=HTMLResponse)
async def job_list(request: Request, status: Optional[str] = None, limit: int = 50):
    """Workflow run list with filtering."""
    from infrastructure.workflow_run_repository import WorkflowRunRepository
    repo = WorkflowRunRepository()

    runs = repo.list_runs(status=status, limit=limit)

    # Compute stats from the result set
    status_counts = {}
    for r in runs:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    stats = {
        "total": len(runs),
        "running": status_counts.get("running", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "awaiting_approval": status_counts.get("awaiting_approval", 0),
    }

    return render_template(
        request,
        "pages/jobs/list.html",
        jobs=runs,
        stats=stats,
        filters={"status": status, "limit": limit},
        nav_active="/ui/jobs",
    )
```

Remove the old `hours` parameter — `list_runs` doesn't support time-range filtering (it uses `limit` instead). Remove the `from infrastructure.jobs_tasks import JobRepository` import and the `from ui.adapters import jobs_to_dto` import.

- [ ] **Step 2: Verify route compiles**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "from ui_routes import router; print('OK')"`

---

### Task 2: Rewire ui_routes.py — Job Detail

**Files:**
- Modify: `ui_routes.py:73-96` (job_detail route)

- [ ] **Step 1: Replace job_detail route implementation**

```python
@router.get("/jobs/{run_id}", response_class=HTMLResponse)
async def job_detail(request: Request, run_id: str):
    """Workflow run detail with task breakdown."""
    from infrastructure.workflow_run_repository import WorkflowRunRepository
    repo = WorkflowRunRepository()

    run = repo.get_by_run_id(run_id)
    if not run:
        return HTMLResponse(f"Run {run_id} not found", status_code=404)

    tasks = repo.list_task_details(run_id)
    task_counts = repo.get_task_status_counts(run_id)

    return render_template(
        request,
        "pages/jobs/detail.html",
        job=run,
        tasks=tasks,
        task_counts=task_counts,
        nav_active="/ui/jobs",
    )
```

Remove the old `from infrastructure.jobs_tasks import JobRepository, TaskRepository` import and the `from ui.adapters import job_to_dto, tasks_to_dto` import.

- [ ] **Step 2: Verify route compiles**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "from ui_routes import router; print('OK')"`

---

### Task 3: Rewire ui_routes.py — Dashboard Stats

**Files:**
- Modify: `ui_routes.py:157-178` (_get_dashboard_stats function)

- [ ] **Step 1: Replace _get_dashboard_stats**

```python
def _get_dashboard_stats() -> dict:
    """Gather stats for the dashboard from workflow_runs."""
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        repo = WorkflowRunRepository()
        runs = repo.list_runs(limit=200)

        status_counts = {}
        for r in runs:
            s = r.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        from services import ALL_HANDLERS
        handler_count = len(ALL_HANDLERS)
    except Exception as e:
        logger.warning(f"Dashboard stats failed: {e}")
        return {"active": 0, "completed": 0, "failed": 0, "handler_count": 0}

    return {
        "active": status_counts.get("running", 0) + status_counts.get("pending", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "handler_count": handler_count,
    }
```

- [ ] **Step 2: Verify route compiles**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "from ui_routes import router; print('OK')"`

- [ ] **Step 3: Commit routes rewiring**

```bash
git add ui_routes.py
git commit -m "refactor(ui): rewire routes to WorkflowRunRepository

Routes now read from app.workflow_runs / app.workflow_tasks
instead of legacy app.jobs / app.tasks. Removes JobRepository
and DTO adapter dependencies from UI routes."
```

---

### Task 4: Update _job_card.html for workflow_run dicts

**Files:**
- Modify: `templates/components/_job_card.html`

- [ ] **Step 1: Update field references**

The `list_runs()` dicts use these keys. Update the template:

| Old (DTO) | New (workflow_run dict) |
|-----------|----------------------|
| `job.job_id` | `job.run_id` |
| `job.workflow_id` | `job.workflow_name` |
| `job.status` | `job.status` (same) |
| `job.current_step` | *(remove — no step concept)* |
| `job.total_steps` | *(remove — no step concept)* |
| `job.created_at` | `job.created_at` (same) |
| `job.completed_at` | `job.completed_at` (same) |
| `job.event_count` | *(remove — no events in list query)* |
| `job.has_failure` | *(remove)* |
| `job.latest_event` | *(remove)* |

Replace the full template content:

```html
{# ============================================================================
   JOB CARD COMPONENT
   ============================================================================
   Displays a single workflow run in the list.

   Context variables:
       job: Dict from WorkflowRunRepository.list_runs() with:
           - run_id: Workflow run ID
           - workflow_name: YAML workflow name
           - status: pending, running, completed, failed, awaiting_approval
           - created_at: Creation timestamp
           - started_at: When first task was claimed
           - completed_at: Completion timestamp (optional)
           - request_id: Platform request ID (optional)
   ============================================================================ #}

<div class="job-card job-status-{{ job.status|lower }}">
    <div class="job-card-header">
        {# Status Badge #}
        <span class="status-badge status-{{ job.status|lower }}">
            {% if job.status|lower == 'running' %}
                <span class="status-dot pulse"></span>
            {% endif %}
            {{ job.status|replace('_', ' ')|title }}
        </span>

        {# Workflow Name #}
        <span class="job-type">{{ job.workflow_name|replace('_', ' ')|title }}</span>
    </div>

    <div class="job-card-body">
        {# Run ID #}
        <div class="job-id">
            <a href="/ui/jobs/{{ job.run_id }}" title="{{ job.run_id }}">
                {{ job.run_id[:16] }}...
            </a>
        </div>

        {# Timestamps #}
        <div class="job-timestamps">
            <span class="job-created" title="{{ job.created_at }}">
                {{ job.created_at|string|replace('T', ' ')|truncate(19, True, '') }}
            </span>
            {% if job.completed_at and job.created_at %}
            <span class="job-duration">
                {% set duration = (job.completed_at - job.created_at).total_seconds() %}
                {% if duration > 3600 %}
                    {{ (duration / 3600)|round(1) }}h
                {% elif duration > 60 %}
                    {{ (duration / 60)|round(1) }}m
                {% else %}
                    {{ duration|round(0)|int }}s
                {% endif %}
            </span>
            {% endif %}
        </div>

        {# Request ID if present #}
        {% if job.request_id %}
        <div class="job-latest-event">
            <span class="event-type-badge">request</span>
            <span class="event-summary-text">{{ job.request_id[:16] }}...</span>
        </div>
        {% endif %}
    </div>

    <div class="job-card-footer">
        {# Status indicator #}
        <span class="event-count-badge {{ 'has-failure' if job.status == 'failed' else '' }}">
            {% if job.status == 'failed' %}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                Failed
            {% elif job.status == 'awaiting_approval' %}
                Awaiting Approval
            {% else %}
                {{ job.status|replace('_', ' ')|title }}
            {% endif %}
        </span>

        {# Actions #}
        <div class="job-actions">
            <a href="/ui/jobs/{{ job.run_id }}" class="btn btn-sm btn-secondary">
                Details
            </a>
        </div>
    </div>
</div>
```

---

### Task 5: Update list.html for workflow_run data

**Files:**
- Modify: `templates/pages/jobs/list.html`

- [ ] **Step 1: Update filter pills for DAG status values**

Replace the status filter pills (lines 33-41). The DAG statuses are: `pending`, `running`, `completed`, `failed`, `awaiting_approval`. Replace `processing` with `running`.

```html
<button class="filter-pill {{ 'active' if not filters.status else '' }}"
        onclick="filterByStatus(null)">All</button>
<button class="filter-pill {{ 'active' if filters.status == 'running' else '' }}"
        onclick="filterByStatus('running')">Running</button>
<button class="filter-pill {{ 'active' if filters.status == 'completed' else '' }}"
        onclick="filterByStatus('completed')">Completed</button>
<button class="filter-pill {{ 'active' if filters.status == 'failed' else '' }}"
        onclick="filterByStatus('failed')">Failed</button>
<button class="filter-pill {{ 'active' if filters.status == 'awaiting_approval' else '' }}"
        onclick="filterByStatus('awaiting_approval')">Awaiting Approval</button>
```

- [ ] **Step 2: Remove time-range filter**

Remove the hours filter `<div class="filter-group">` block (lines 45-52) — `list_runs()` doesn't support time-range filtering.

- [ ] **Step 3: Update search to use run_id**

In the JS `debounceSearch` function, the redirect is already correct (`/ui/jobs/` + value). No change needed — the route param was renamed but the URL path is the same.

- [ ] **Step 4: Update stats labels**

In the stats banner, rename `Processing` to `Running`:

```html
<div class="stat-item">
    <span class="stat-label">Running</span>
    <span class="stat-value" style="color: var(--ds-status-processing-fg);">{{ stats.running }}</span>
</div>
```

- [ ] **Step 5: Remove HTMX auto-refresh partial endpoint reference**

The `hx-get="/ui/jobs/partial?..."` references a partial endpoint that doesn't exist. Remove the `hx-get`, `hx-trigger`, `hx-swap`, `hx-indicator` attributes from the `job-list-container` div — the list is server-rendered on page load. Keep the manual refresh button which does a full page reload.

Update the `refreshJobList` function to do a page reload:

```javascript
function refreshJobList() {
    window.location.reload();
}
```

---

### Task 6: Update detail.html for WorkflowRun model

**Files:**
- Modify: `templates/pages/jobs/detail.html`

- [ ] **Step 1: Update header to use WorkflowRun fields**

The `job` variable is now a `WorkflowRun` Pydantic model (attribute access works).

Replace the header block (lines 24-54):

```html
{# Page Header #}
<div class="dashboard-header">
    <div class="header-with-count">
        <div>
            <div class="header-title-row">
                <h1>{{ job.workflow_name|replace('_', ' ')|title }}</h1>
                <span class="status-badge status-{{ job.status.value|lower if job.status.value is defined else job.status|lower }} large">
                    {% set status_val = job.status.value if job.status.value is defined else job.status|string|lower %}
                    {% if status_val == 'running' %}
                        <span class="status-dot pulse"></span>
                    {% endif %}
                    {{ status_val|replace('_', ' ')|title }}
                </span>
            </div>
            <p class="subtitle">
                <code>{{ job.run_id }}</code>
            </p>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Update stats banner**

Replace the stats banner (lines 57-89) — remove Stage, add task counts:

```html
{# Stats Banner #}
<div class="stats-banner">
    <div class="stat-item">
        <span class="stat-label">Created</span>
        <span class="stat-value">{{ job.created_at|string|replace('T', ' ')|truncate(19, True, '') if job.created_at else 'N/A' }}</span>
    </div>
    <div class="stat-item">
        <span class="stat-label">Duration</span>
        <span class="stat-value">
            {% set status_val = job.status.value if job.status.value is defined else job.status|string|lower %}
            {% if job.completed_at and job.created_at %}
                {% set duration = (job.completed_at - job.created_at).total_seconds() %}
                {% if duration > 3600 %}
                    {{ (duration / 3600)|round(1) }}h
                {% elif duration > 60 %}
                    {{ (duration / 60)|round(1) }}m
                {% else %}
                    {{ duration|round(0)|int }}s
                {% endif %}
            {% elif status_val == 'running' %}
                <span class="processing-indicator">In Progress...</span>
            {% else %}
                N/A
            {% endif %}
        </span>
    </div>
    <div class="stat-item">
        <span class="stat-label">Tasks</span>
        <span class="stat-value highlight">
            {{ task_counts.get('completed', 0) }}/{{ task_counts.values()|sum }}
        </span>
    </div>
    <div class="stat-item">
        <span class="stat-label">Failed</span>
        <span class="stat-value" style="color: var(--ds-status-failed-fg);">{{ task_counts.get('failed', 0) }}</span>
    </div>
</div>
```

- [ ] **Step 3: Replace stage progress with task list**

Remove the entire Stage Progress section (lines 110-147). Remove the Event Timeline section (lines 149-156) — `_event_timeline.html` doesn't exist. Remove the Failure Analysis sidebar (lines 162-177) — `_failure_context.html` doesn't exist. Remove the Event Summary sidebar (lines 180-192).

Replace with a task table:

```html
{# Main Content #}
<div class="job-detail-grid">
    <div class="job-detail-main">
        {# Job Parameters #}
        {% if job.parameters %}
        <div class="section-card collapsible">
            <div class="section-header" onclick="toggleSection(this)">
                <h3 class="section-title">Parameters</h3>
                <svg class="collapse-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
            </div>
            <div class="section-content">
                <pre class="json-display">{{ job.parameters|tojson(indent=2) }}</pre>
            </div>
        </div>
        {% endif %}

        {# Task Table #}
        <div class="section-card">
            <h3 class="section-title">Tasks ({{ tasks|length }})</h3>
            {% if tasks %}
            <table class="release-table" style="margin-top: 12px;">
                <thead>
                    <tr>
                        <th>Task</th>
                        <th>Handler</th>
                        <th>Status</th>
                        <th>Retries</th>
                        <th>Duration</th>
                        <th>Error</th>
                    </tr>
                </thead>
                <tbody>
                {% for task in tasks %}
                    <tr>
                        <td class="mono" style="font-size: 12px;">{{ task.task_name }}{% if task.fan_out_index is not none %}[{{ task.fan_out_index }}]{% endif %}</td>
                        <td>{{ task.handler }}</td>
                        <td>
                            <span class="status-badge status-{{ task.status|lower }}">
                                {% if task.status == 'running' %}<span class="status-dot pulse"></span>{% endif %}
                                {{ task.status|replace('_', ' ')|title }}
                            </span>
                        </td>
                        <td>{{ task.retry_count }}/{{ task.max_retries }}</td>
                        <td>
                            {% if task.completed_at and task.started_at %}
                                {% set dur = (task.completed_at - task.started_at).total_seconds() %}
                                {% if dur > 60 %}{{ (dur / 60)|round(1) }}m{% else %}{{ dur|round(0)|int }}s{% endif %}
                            {% elif task.status == 'running' %}
                                ...
                            {% else %}
                                -
                            {% endif %}
                        </td>
                        <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{{ task.error_details or '' }}">
                            {{ task.error_details|truncate(60) if task.error_details else '-' }}
                        </td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p style="color: var(--ds-gray); padding: 16px 0;">No tasks yet.</p>
            {% endif %}
        </div>

        {# Result Data #}
        {% if job.result_data %}
        <div class="section-card collapsible">
            <div class="section-header" onclick="toggleSection(this)">
                <h3 class="section-title">Result Data</h3>
                <svg class="collapse-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
            </div>
            <div class="section-content">
                <pre class="json-display">{{ job.result_data|tojson(indent=2) }}</pre>
            </div>
        </div>
        {% endif %}
    </div>

    {# Sidebar #}
    <div class="job-detail-sidebar">
        {# Run Metadata #}
        <div class="section-card">
            <h3 class="section-title">Run Info</h3>
            <div class="type-list">
                <div class="type-item">
                    <span class="stat-label">Workflow</span>
                    <span>{{ job.workflow_name }}</span>
                </div>
                {% if job.request_id %}
                <div class="type-item">
                    <span class="stat-label">Request ID</span>
                    <span class="mono" style="font-size: 12px;">{{ job.request_id[:16] }}...</span>
                </div>
                {% endif %}
                {% if job.asset_id %}
                <div class="type-item">
                    <span class="stat-label">Asset</span>
                    <a href="/ui/assets/{{ job.asset_id }}">{{ job.asset_id[:16] }}...</a>
                </div>
                {% endif %}
                {% if job.schedule_id %}
                <div class="type-item">
                    <span class="stat-label">Schedule</span>
                    <span class="mono" style="font-size: 12px;">{{ job.schedule_id[:16] }}...</span>
                </div>
                {% endif %}
                <div class="type-item">
                    <span class="stat-label">Version</span>
                    <span>{{ job.platform_version }}</span>
                </div>
            </div>
        </div>

        {# Task Status Summary #}
        {% if task_counts %}
        <div class="section-card">
            <h3 class="section-title">Task Summary</h3>
            <div class="type-list">
                {% for status, count in task_counts.items() %}
                <div class="type-item">
                    <span class="status-badge status-{{ status }}">{{ status|replace('_', ' ')|title }}</span>
                    <span class="type-count">{{ count }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
    </div>
</div>
```

- [ ] **Step 4: Remove dead JS and references**

Remove the `resubmitJob` function, the `ORCHESTRATOR_URL` variable, the `events.css` stylesheet link, and the API endpoints sidebar — these referenced legacy endpoints and missing templates.

Keep `toggleSection` — it's still used for collapsible parameter/result sections.

```html
<script>
function toggleSection(header) {
    const card = header.closest('.collapsible');
    card.classList.toggle('collapsed');
}
</script>
```

- [ ] **Step 5: Commit template changes**

```bash
git add templates/components/_job_card.html templates/pages/jobs/list.html templates/pages/jobs/detail.html
git commit -m "refactor(ui): update templates for workflow_runs data shape

Templates now consume WorkflowRunRepository dicts/models
instead of JobRecord DTOs. Status values updated from
Epoch 4 (processing/queued) to DAG (running/pending/
awaiting_approval). Stage progress replaced with task table."
```

---

### Task 7: Update dashboard.html stats labels

**Files:**
- Modify: `templates/pages/dashboard.html`

- [ ] **Step 1: Update stat labels**

Change "Active Jobs" to "Active Runs" and "Completed (24h)" to "Completed" etc. The stats dict keys (`active`, `completed`, `failed`, `handler_count`) are set by `_get_dashboard_stats()` so the template variable names don't change — just the display labels.

```html
<div style="font-size: 13px; color: #626F86;">Active Runs</div>
```
```html
<div style="font-size: 13px; color: #626F86;">Completed</div>
```
```html
<div style="font-size: 13px; color: #626F86;">Failed</div>
```

Also update the Job Monitor link card text:

```html
<h3 style="margin: 0 0 8px 0; color: #053657;">Workflow Monitor</h3>
<p style="margin: 0; color: #626F86; font-size: 13px;">Track workflow execution and task progress</p>
```

- [ ] **Step 2: Commit dashboard changes**

```bash
git add templates/pages/dashboard.html
git commit -m "refactor(ui): update dashboard labels for DAG workflows"
```

---

### Task 8: Add CSS for DAG-specific status badges

**Files:**
- Modify: `static/css/jobs.css`

- [ ] **Step 1: Add status classes for new DAG statuses**

The templates use `status-{{ status }}` CSS classes. DAG introduces new statuses that need styling. Add after the existing status classes:

```css
/* DAG-specific status badges */
.status-badge.status-pending { background: var(--ds-status-pending-bg, #fef3c7); color: var(--ds-status-pending-fg, #d97706); }
.status-badge.status-running { background: var(--ds-status-processing-bg, #dbeafe); color: var(--ds-status-processing-fg, #0071BC); }
.status-badge.status-ready { background: #e0e7ff; color: #4338ca; }
.status-badge.status-awaiting_approval { background: #fef3c7; color: #92400e; }
.status-badge.status-skipped { background: #f3f4f6; color: #6b7280; }
.status-badge.status-expanded { background: #ede9fe; color: #7c3aed; }
.status-badge.status-waiting { background: #fef3c7; color: #92400e; }
.status-badge.status-cancelled { background: #f3f4f6; color: #6b7280; }

.job-card.job-status-running { border-left-color: var(--ds-status-processing-fg, #0071BC); }
.job-card.job-status-pending { border-left-color: var(--ds-status-pending-fg, #d97706); }
.job-card.job-status-awaiting_approval { border-left-color: #92400e; }
```

- [ ] **Step 2: Commit CSS changes**

```bash
git add static/css/jobs.css
git commit -m "style(ui): add CSS for DAG workflow status badges"
```

---

### Task 9: Verify end-to-end

- [ ] **Step 1: Verify all imports resolve**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "
from ui_routes import router
print('Routes OK')
print('Endpoints:', [r.path for r in router.routes])
"
```

- [ ] **Step 2: Check no remaining legacy references in modified files**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && grep -rn 'JobRepository\|TaskRepository\|jobs_to_dto\|job_to_dto\|tasks_to_dto\|from ui.adapters' ui_routes.py
```

Expected: no output (all legacy imports removed).

- [ ] **Step 3: Check templates reference correct field names**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && grep -rn 'job_id\|job_type\|total_stages\|current_stage\|processing' templates/pages/jobs/ templates/components/_job_card.html
```

Expected: no legacy field references. `job_id` should not appear (replaced with `run_id`). `processing` should not appear as a status (replaced with `running`).
