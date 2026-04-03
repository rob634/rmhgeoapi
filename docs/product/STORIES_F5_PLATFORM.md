# Feature F5: Platform & Operations — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Platform & Operations encompasses the orchestration engine, admin tooling, and operational infrastructure that powers all data pipelines. The centerpiece is a custom DAG workflow engine that executes YAML-defined workflows with conditional routing, fan-out/fan-in parallelization, approval gates, and dotted-path parameter resolution. The DAG Brain admin UI provides a complete operational dashboard for job submission, approval management, and system monitoring.

The platform serves 115+ HTTP endpoints across five functional domains (platform, STAC, DAG, admin, OGC Features). A 3-tier observability system feeds Azure Application Insights with inline logging, structured checkpoint events, and status integration. Schema management supports safe additive changes (`ensure`) and destructive rebuilds (`rebuild`) for the 5-schema PostgreSQL architecture.

A rigorous quality assurance pipeline (COMPETE, SIEGE, REFLEXION, TOURNAMENT, ADVOCATE) has executed 70+ adversarial review cycles, discovering and fixing 83 defects across the codebase.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S5.1 | DAG orchestration engine | Done | v0.10.4 | YAML workflows, conditionals, fan-out/fan-in, gates, parameter resolution |
| S5.2 | DAG Brain admin UI | Done | v0.10.5.6 | Dashboard, submit (file browser), approve/reject/revoke, handlers grid, health |
| S5.3 | Scheduled workflows | Done | v0.10.7 | Cron-based DAGScheduler, app.schedules table |
| S5.4 | Health and preflight system | Done | v0.10.x | 20 plugin checks, mode-aware, /livez /readyz /health /preflight |
| S5.5 | 3-tier observability | Done | v0.9.16.0 | Inline logging, structured checkpoints, status integration |
| S5.6 | API surface | Done | v0.10.x | 115+ endpoints: platform, STAC, DAG, admin, OGC Features |
| S5.7 | Schema management | Done | v0.10.x | ensure (safe additive) / rebuild (destructive), Pydantic-to-SQL DDL |
| S5.8 | Worker dual-poll | Done | v0.10.4 | Legacy app.tasks + DAG workflow_tasks, SKIP LOCKED |
| S5.9 | Janitor | Done | v0.10.4 | Stale task recovery (30min TTL, STUCK detection) |
| S5.10 | COMPETE/SIEGE quality pipeline | Done | v0.10.9 | 70+ adversarial reviews, 83 fixes, 7 agent pipelines |
| S5.11 | Deployment tooling | Done | v0.10.x | deploy.sh, health checks, version verification |

---

## Story Detail

### S5.1: DAG Orchestration Engine
**Status**: Done (v0.10.4, 17 MAR 2026)

Custom YAML-defined workflow engine with four core modules:

| Module | Purpose |
|--------|---------|
| **DAGInitializer** | Converts workflow YAML into live database records (3-pass: validate, build tasks, build deps) |
| **DAGOrchestrator** | Main poll loop: load snapshot, evaluate transitions, check terminal state (max 1000 cycles) |
| **Transition Engine** | Promotes PENDING tasks to READY via 8-step gate (predecessor check, when-clause, parameter resolution) |
| **Fan Engine** | Evaluates conditionals (14 operators), expands fan-outs (Jinja2 parameterization), aggregates fan-ins (5 modes) |

**Key capabilities**:
- Conditional routing (14 operators: eq, gt, lt, truthy, in, contains, etc.)
- Fan-out/fan-in (up to 10,000 children per template, Jinja2 context with item/index/inputs/nodes)
- Approval gates (workflow suspension, external signal reconciliation)
- best_effort tasks (failure does not block downstream)
- Optional dependencies (`depends_on: ["task?"]` tolerates skipped upstream)
- Deterministic run_id (SHA256 of workflow + params, prevents duplicates)
- CAS guards on all state transitions

**Workflows**: 10 YAML definitions, 58 registered handlers

**Key files**: `core/dag_orchestrator.py`, `core/dag_initializer.py`, `core/dag_transition_engine.py`, `core/dag_fan_engine.py`, `core/param_resolver.py`, `core/workflow_loader.py`, `workflows/*.yaml`

### S5.2: DAG Brain Admin UI
**Status**: Done (v0.10.5.6, 23 MAR 2026)

Jinja2 + HTMX admin UI served by the DAG Brain app (APP_MODE=orchestrator). No JavaScript frameworks.

**Pages**:
- **Dashboard**: Active workflow runs, system status
- **Jobs**: List/detail with status filtering, task breakdown
- **Submit**: File browser (container selection, blob browsing, validate before submit)
- **Assets**: Approve/reject/revoke modals with release detail
- **Handlers**: Grid of all 58 registered handlers with task types
- **Health**: System health checks

All API calls proxied to Function App via httpx (ORCHESTRATOR_URL). Health checks skip irrelevant ETL mount, GDAL, and task polling checks in orchestrator mode.

**Key files**: `ui/`, `templates/`, `static/`, `docker_service.py`

### S5.3: Scheduled Workflows
**Status**: Done (v0.10.7, 20 MAR 2026)

DAGScheduler thread polls `app.schedules` table and submits workflows on cron schedules. CRUD endpoints for schedule management. Manual trigger endpoint for immediate execution. Reference implementation: ACLED sync (S1.8) runs on cron schedule.

**Endpoints**: `POST/GET/PUT/DELETE /api/dag/schedules`, `POST /api/dag/schedules/{id}/trigger`
**Key files**: `core/dag_scheduler.py`, `triggers/dag/dag_bp.py`

### S5.4: Health and Preflight System
**Status**: Done (v0.10.x)

Four probe endpoints with different purposes:
- `/livez` — process alive (always 200)
- `/readyz` — startup complete
- `/health` — comprehensive (20 plugin checks: database, blob, STAC, TiPG, etc.)
- `/preflight` — mode-aware capability validation with remediation guidance (13 checks)

Health checks are APP_MODE-aware — Docker workers skip irrelevant ETL mount checks, orchestrators skip task polling checks.

**Key files**: `triggers/probes.py`, `triggers/admin/admin_preflight.py`

### S5.5: 3-Tier Observability
**Status**: Done (v0.9.16.0, 8 MAR 2026)

| Tier | Method | Purpose |
|------|--------|---------|
| Tier 1 | `logger.info()` | Operation boundaries, 10% progress in long loops |
| Tier 2 | `JobEvent.CHECKPOINT` | Structured, non-fatal progress events with checkpoint_type |
| Tier 3 | Platform status endpoint | Recent checkpoint displayed in PROCESSING status response |

All 3 apps log to a single Application Insights instance. KQL query templates available at `/api/appinsights/templates`.

**Key files**: `core/models/events.py`, `docs_claude/APPLICATION_INSIGHTS.md`

### S5.6: API Surface
**Status**: Done (v0.10.x)

115+ HTTP endpoints across functional domains:

| Domain | Endpoints | Purpose |
|--------|:---------:|---------|
| Platform | 25 | B2B ETL submission, status, approvals, catalog |
| STAC | 19 | OGC STAC API v1.0.0 (collections, items, admin) |
| DAG | 13 | Workflow runs, tasks, schedules, test endpoints |
| Database Admin | 20 | Schema operations, diagnostics, maintenance |
| Admin/Maintenance | 35+ | System stats, cleanup, artifacts, services |
| Health Probes | 4 | Liveness, readiness, health, preflight |

Endpoints are conditionally registered based on APP_MODE (platform, orchestrator, worker, standalone).

**Key files**: `function_app.py`, `triggers/` (all blueprints)

### S5.7: Schema Management
**Status**: Done (v0.10.x)

Two schema operations via `/api/dbadmin/maintenance`:
- **ensure** (safe): Creates missing tables, indexes, enum types. Preserves existing data. Idempotent.
- **rebuild** (destructive): Drops and recreates app + pgstac schemas. Dev/test only.

DDL generated from Pydantic models via `generate_table_from_model()` (newer path with ClassVar PKs) and `generate_table_composed()` (older path with hardcoded PKs). Both coexist.

**Key files**: `core/schema/sql_generator.py`, `triggers/admin/db_maintenance.py`

### S5.8: Worker Dual-Poll
**Status**: Done (v0.10.4, 17 MAR 2026)

Docker workers poll both legacy `app.tasks` (Epoch 4) and DAG `app.workflow_tasks` (Epoch 5) using SKIP LOCKED. Each poll cycle checks both tables. A task claimed from either table is executed through the same handler registry (ALL_HANDLERS).

**Key files**: `docker_service.py`

### S5.9: Janitor
**Status**: Done (v0.10.4)

Background process that detects stale tasks (RUNNING for >30 minutes without heartbeat update). Stale tasks are marked STUCK and can be reclaimed. Prevents workflows from hanging indefinitely when a worker crashes mid-task.

**Known issue**: `validate` handler reclaimed by janitor on large files (60s+ execution exceeds heartbeat interval).

**Key files**: `core/dag_orchestrator.py`

### S5.10: COMPETE/SIEGE Quality Pipeline
**Status**: Done (v0.10.9)

Seven agent pipelines for adversarial quality assurance:

| Pipeline | Runs | Method |
|----------|:----:|--------|
| COMPETE | 70 | Two agents debate; third judges |
| SIEGE | 5 | Live E2E on Azure |
| REFLEXION | 17 | Reverse engineer, fault inject, patch, judge |
| TOURNAMENT | 1 | Full-spectrum (87.2% score) |
| ADVOCATE | 1 | B2B DX audit |
| GREENFIELD | 3 | Architecture from scratch comparison |
| OBSERVATORY | 2 | Observability audit |

**Results**: 83 total fixes. All critical/high findings resolved. SIEGE-DAG Run 5: 84% pass rate (16/19 sequences).

**Key files**: `docs/agent_review/`, `docs_claude/AGENT_PLAYBOOKS.md`

### S5.11: Deployment Tooling
**Status**: Done (v0.10.x)

`deploy.sh` handles all deployments:
- Reads version from `config/__init__.py`
- Deploys to target app (orchestrator, dagbrain, docker, all)
- Waits for restart (45s Function Apps, 60s Docker)
- Runs health check
- Verifies deployed version matches expected

DAG Brain and Docker Worker share the same ACR image — deploy both together.

**Key files**: `deploy.sh`, `config/__init__.py`
