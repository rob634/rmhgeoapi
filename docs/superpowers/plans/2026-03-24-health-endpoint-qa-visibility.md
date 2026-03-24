# Health Endpoint QA Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add health check components that surface Azure configuration state, DAG workflow registry status, database schema validation, outbound TiTiler connectivity, and active schedule listing — enabling QA teams to self-diagnose deployment issues without Azure portal access.

**Architecture:** Five new health check components added to existing subsystems. `SharedInfrastructureSubsystem` gains config_checklist, schema_validation, and outbound_connectivity. `DAGBrainSubsystem` gains workflow_registry and extends scheduler with active schedule details. All follow the existing `build_component()` pattern.

**Tech Stack:** Python, psycopg, httpx, existing `docker_health` subsystem framework

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `docker_health/shared.py` | Modify | Add `_check_config_checklist()`, `_check_schema_validation()`, `_check_outbound_connectivity()` |
| `docker_health/dag_brain.py` | Modify | Add `_check_workflow_registry()`, extend `_check_scheduler()` with active schedules |
| `docker_health/__init__.py` | No change | Subsystem wiring unchanged — new checks are inside existing subsystems |

No new files. All changes extend existing subsystems with new components.

---

### Task 1: Config Checklist Component

**Files:**
- Modify: `docker_health/shared.py`

Surfaces which required environment variables are set vs missing, what values they have (secrets masked), and what managed identity names are configured. This is the single most valuable check for QA first-deploy.

- [ ] **Step 1: Add `_check_config_checklist()` method to `SharedInfrastructureSubsystem`**

Add after `_check_task_polling()` method:

```python
def _check_config_checklist(self) -> Dict[str, Any]:
    """Check required Azure configuration for deployment validation."""
    import os

    # Required env vars — app won't function without these
    required = {
        "POSTGIS_HOST": "PostgreSQL server hostname",
        "POSTGIS_DATABASE": "PostgreSQL database name",
        "APP_SCHEMA": "Application schema (default: app)",
        "POSTGIS_SCHEMA": "PostGIS schema (default: geo)",
        "PGSTAC_SCHEMA": "pgSTAC schema (default: pgstac)",
        "H3_SCHEMA": "H3 schema (default: h3)",
        "BRONZE_STORAGE_ACCOUNT": "Bronze zone storage account",
        "APP_MODE": "Application mode (worker_docker | orchestrator | standalone)",
    }

    # Important but optional — app works without but features degraded
    optional = {
        "DB_ADMIN_MANAGED_IDENTITY_NAME": "Managed identity for DB admin auth",
        "DB_READER_MANAGED_IDENTITY_NAME": "Managed identity for DB reader auth",
        "TITILER_BASE_URL": "TiTiler/TiPG service layer URL",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "App Insights telemetry",
        "LOG_LEVEL": "Logging level (default: INFO)",
        "ENVIRONMENT": "Environment name (default: dev)",
    }

    missing_required = []
    config_items = {}

    for var, desc in required.items():
        val = os.environ.get(var)
        config_items[var] = {
            "set": val is not None,
            "value": val if val else "[NOT SET]",
            "required": True,
            "description": desc,
        }
        if val is None:
            missing_required.append(var)

    for var, desc in optional.items():
        val = os.environ.get(var)
        # Mask connection strings and secrets
        display_val = val
        if val and ("instrumentationkey" in var.lower() or "connection_string" in var.lower()):
            display_val = val[:20] + "..." if len(val) > 20 else val
        config_items[var] = {
            "set": val is not None,
            "value": display_val if val else "[NOT SET]",
            "required": False,
            "description": desc,
        }

    if missing_required:
        status = "unhealthy"
    else:
        status = "healthy"

    return self.build_component(
        status=status,
        description="Azure configuration checklist",
        source="docker_worker",
        details={
            "total_required": len(required),
            "missing_required": missing_required,
            "missing_count": len(missing_required),
            "config": config_items,
        },
    )
```

- [ ] **Step 2: Wire `_check_config_checklist()` into `get_health()`**

In `SharedInfrastructureSubsystem.get_health()`, add after the storage check block:

```python
        # Check configuration (Azure env vars)
        config_result = self._check_config_checklist()
        components["config_checklist"] = config_result
        if config_result["status"] == "unhealthy":
            errors.append(f"Missing required config: {', '.join(config_result['details']['missing_required'])}")
```

- [ ] **Step 3: Verify locally**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "
from docker_health.shared import SharedInfrastructureSubsystem
s = SharedInfrastructureSubsystem()
result = s._check_config_checklist()
import json; print(json.dumps(result, indent=2))
"
```

Expected: JSON with config items showing which vars are set/missing.

- [ ] **Step 4: Commit**

```bash
git add docker_health/shared.py
git commit -m "feat: config checklist health component for QA deployment validation"
```

---

### Task 2: Schema Validation Component

**Files:**
- Modify: `docker_health/shared.py`

Checks that critical DAG tables and enums exist in the database. Catches "forgot to run schema rebuild after deploy."

- [ ] **Step 1: Add `_check_schema_validation()` method to `SharedInfrastructureSubsystem`**

Add after `_check_config_checklist()`:

```python
def _check_schema_validation(self) -> Dict[str, Any]:
    """Validate critical database tables and enums exist."""
    try:
        from infrastructure.db_auth import ManagedIdentityAuth
        from infrastructure.db_connections import ConnectionManager
        from psycopg.rows import dict_row

        cm = ConnectionManager(ManagedIdentityAuth())

        required_tables = [
            ("app", "jobs"),
            ("app", "tasks"),
            ("app", "workflow_runs"),
            ("app", "workflow_tasks"),
            ("app", "workflow_task_deps"),
            ("app", "schedules"),
            ("app", "scheduled_datasets"),
            ("app", "api_requests"),
            ("app", "geospatial_assets"),
            ("app", "asset_releases"),
        ]

        required_enums = [
            "job_status",
            "task_status",
            "schedule_status",
            "approval_state",
            "clearance_state",
        ]

        with cm.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Check tables
                cur.execute("""
                    SELECT schemaname, tablename
                    FROM pg_tables
                    WHERE schemaname = 'app'
                    ORDER BY tablename
                """)
                existing_tables = {
                    (r["schemaname"], r["tablename"]) for r in cur.fetchall()
                }

                # Check enums
                cur.execute("""
                    SELECT t.typname
                    FROM pg_type t
                    JOIN pg_namespace n ON t.typnamespace = n.oid
                    WHERE n.nspname = 'app' AND t.typtype = 'e'
                    ORDER BY t.typname
                """)
                existing_enums = {r["typname"] for r in cur.fetchall()}

                # Get counts
                cur.execute("""
                    SELECT COUNT(*) as table_count FROM pg_tables WHERE schemaname = 'app'
                """)
                total_tables = cur.fetchone()["table_count"]

                cur.execute("""
                    SELECT COUNT(*) as idx_count
                    FROM pg_indexes WHERE schemaname = 'app'
                """)
                total_indexes = cur.fetchone()["idx_count"]

        missing_tables = [
            f"{s}.{t}" for s, t in required_tables
            if (s, t) not in existing_tables
        ]
        missing_enums = [
            e for e in required_enums if e not in existing_enums
        ]

        if missing_tables or missing_enums:
            status = "unhealthy"
        else:
            status = "healthy"

        return self.build_component(
            status=status,
            description="Database schema validation",
            source="docker_worker",
            details={
                "total_tables": total_tables,
                "total_indexes": total_indexes,
                "required_tables_checked": len(required_tables),
                "missing_tables": missing_tables,
                "required_enums_checked": len(required_enums),
                "missing_enums": missing_enums,
                "existing_enums": sorted(existing_enums),
            },
        )
    except Exception as e:
        return self.build_component(
            status="unhealthy",
            description="Database schema validation",
            source="docker_worker",
            details={"error": str(e)},
        )
```

- [ ] **Step 2: Wire into `get_health()`**

Add after the config checklist block:

```python
        # Check schema (tables + enums)
        schema_result = self._check_schema_validation()
        components["schema_validation"] = schema_result
        if schema_result["status"] == "unhealthy":
            errors.append("Database schema validation failed — run action=ensure")
```

- [ ] **Step 3: Verify locally**

```bash
python -c "
from docker_health.shared import SharedInfrastructureSubsystem
s = SharedInfrastructureSubsystem()
result = s._check_schema_validation()
import json; print(json.dumps(result, indent=2))
"
```

Expected: healthy status with table/index counts and no missing tables.

- [ ] **Step 4: Commit**

```bash
git add docker_health/shared.py
git commit -m "feat: schema validation health component — checks tables and enums exist"
```

---

### Task 3: Outbound TiTiler Connectivity Component

**Files:**
- Modify: `docker_health/shared.py`

Probes TiTiler/TiPG service layer reachability. Catches NSG/firewall issues in corporate networks.

- [ ] **Step 1: Add `_check_outbound_connectivity()` method to `SharedInfrastructureSubsystem`**

Add after `_check_schema_validation()`:

```python
def _check_outbound_connectivity(self) -> Dict[str, Any]:
    """Check outbound connectivity to TiTiler/TiPG service layer."""
    import os
    import httpx

    titiler_url = os.environ.get("TITILER_BASE_URL", "").rstrip("/")

    if not titiler_url:
        return self.build_component(
            status="warning",
            description="Outbound connectivity (TiTiler/TiPG)",
            source="docker_worker",
            details={
                "titiler": {"status": "not_configured", "url": None},
                "note": "TITILER_BASE_URL not set — TiPG refresh webhook will fail",
            },
        )

    probes = {}

    # TiTiler/TiPG liveness
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{titiler_url}/livez")
            if resp.status_code == 200:
                body = resp.json()
                probes["titiler"] = {
                    "status": "reachable",
                    "url": titiler_url,
                    "http_code": 200,
                    "app": body.get("app"),
                    "role": body.get("role"),
                }
            else:
                probes["titiler"] = {
                    "status": "unhealthy",
                    "url": titiler_url,
                    "http_code": resp.status_code,
                }
    except httpx.ConnectError as e:
        probes["titiler"] = {
            "status": "unreachable",
            "url": titiler_url,
            "error": f"Connection failed: {e}",
        }
    except Exception as e:
        probes["titiler"] = {
            "status": "error",
            "url": titiler_url,
            "error": str(e),
        }

    all_reachable = all(
        p.get("status") == "reachable" for p in probes.values()
    )

    return self.build_component(
        status="healthy" if all_reachable else "warning",
        description="Outbound connectivity (TiTiler/TiPG)",
        source="docker_worker",
        details=probes,
    )
```

- [ ] **Step 2: Wire into `get_health()`**

Add after the schema validation block:

```python
        # Check outbound connectivity (TiTiler)
        outbound_result = self._check_outbound_connectivity()
        components["outbound_connectivity"] = outbound_result
        if outbound_result["status"] == "unhealthy":
            errors.append("Outbound connectivity check failed")
```

- [ ] **Step 3: Verify locally**

```bash
python -c "
import os
os.environ['TITILER_BASE_URL'] = 'https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net'
from docker_health.shared import SharedInfrastructureSubsystem
s = SharedInfrastructureSubsystem()
result = s._check_outbound_connectivity()
import json; print(json.dumps(result, indent=2))
"
```

Expected: healthy with titiler status "reachable".

- [ ] **Step 4: Commit**

```bash
git add docker_health/shared.py
git commit -m "feat: outbound TiTiler connectivity health component"
```

---

### Task 4: Workflow Registry Component

**Files:**
- Modify: `docker_health/dag_brain.py`

Shows which YAML workflows loaded, which handlers are registered, and whether all handler references in YAMLs are satisfied. Catches missing YAML files or unregistered handlers.

- [ ] **Step 1: Add `_check_workflow_registry()` method to `DAGBrainSubsystem`**

Add after `_check_lifecycle()`:

```python
def _check_workflow_registry(self) -> Dict[str, Any]:
    """Check DAG workflow registry — loaded workflows and handler coverage."""
    try:
        from pathlib import Path
        from core.workflow_registry import WorkflowRegistry
        from services import ALL_HANDLERS

        workflows_dir = Path(__file__).parent.parent / "workflows"
        registry = WorkflowRegistry(
            workflows_dir=workflows_dir,
            handler_names=set(ALL_HANDLERS.keys()),
        )
        loaded_count = registry.load_all()

        # Get all workflow names
        workflow_names = registry.list_workflows()

        # Check handler coverage: which handlers do YAMLs reference?
        referenced_handlers = set()
        for wf_name in workflow_names:
            defn = registry.get(wf_name)
            if defn and defn.nodes:
                for node in defn.nodes.values():
                    if hasattr(node, "handler") and node.handler:
                        referenced_handlers.add(node.handler)

        registered_handlers = set(ALL_HANDLERS.keys())
        missing_handlers = sorted(referenced_handlers - registered_handlers)
        unused_handlers = sorted(registered_handlers - referenced_handlers)

        if missing_handlers:
            status = "unhealthy"
        elif loaded_count == 0:
            status = "warning"
        else:
            status = "healthy"

        return self.build_component(
            status=status,
            description="DAG workflow registry",
            source="dag_brain",
            details={
                "workflows_loaded": loaded_count,
                "workflow_names": workflow_names,
                "handlers_registered": len(registered_handlers),
                "handlers_referenced_by_workflows": len(referenced_handlers),
                "missing_handlers": missing_handlers,
                "workflows_dir": str(workflows_dir),
            },
        )
    except Exception as e:
        return self.build_component(
            status="unhealthy",
            description="DAG workflow registry",
            source="dag_brain",
            details={"error": str(e)},
        )
```

- [ ] **Step 2: Wire into `get_health()`**

Add after `components["lifecycle"]` line:

```python
        # Check workflow registry
        components["workflow_registry"] = self._check_workflow_registry()
```

- [ ] **Step 3: Verify locally**

```bash
python -c "
from docker_health.dag_brain import DAGBrainSubsystem
s = DAGBrainSubsystem()
result = s._check_workflow_registry()
import json; print(json.dumps(result, indent=2))
"
```

Expected: healthy with workflow count, names list, and zero missing handlers.

- [ ] **Step 4: Commit**

```bash
git add docker_health/dag_brain.py
git commit -m "feat: workflow registry health component — loaded workflows + handler coverage"
```

---

### Task 5: Active Schedules in Scheduler Component

**Files:**
- Modify: `docker_health/dag_brain.py`

Extends the existing `_check_scheduler()` to include what schedules are configured and their last-fired state.

- [ ] **Step 1: Extend `_check_scheduler()` with active schedule listing**

Replace the existing `_check_scheduler()` method. The change is adding a DB query block after the thread status check:

```python
def _check_scheduler(self) -> Dict[str, Any]:
    """Check DAGScheduler background thread status and active schedules."""
    if not self._scheduler:
        return self.build_component(
            status="warning",
            description="DAG Scheduler (cron-based workflow submission)",
            source="dag_brain",
            details={"note": "Scheduler not initialized"},
        )

    thread = self._scheduler._thread
    thread_alive = thread is not None and thread.is_alive()

    details = {
        "thread_alive": thread_alive,
        "total_polls": self._scheduler._total_polls,
        "total_fired": self._scheduler._total_fired,
        "last_poll_at": (
            self._scheduler._last_poll_at.isoformat()
            if self._scheduler._last_poll_at else None
        ),
        "config": {
            "poll_interval": self._scheduler._config.poll_interval,
        },
    }

    # Query active schedules for visibility
    try:
        from infrastructure.schedule_repository import ScheduleRepository
        repo = ScheduleRepository()
        active_schedules = repo.list_all(status="active")
        details["active_schedules"] = [
            {
                "schedule_id": s["schedule_id"],
                "workflow_name": s["workflow_name"],
                "cron_expression": s["cron_expression"],
                "last_run_at": (
                    s["last_run_at"].isoformat()
                    if s.get("last_run_at") else None
                ),
                "description": s.get("description"),
            }
            for s in active_schedules
        ]
        details["active_schedule_count"] = len(active_schedules)
    except Exception as e:
        details["active_schedules_error"] = str(e)
        details["active_schedule_count"] = None

    return self.build_component(
        status="healthy" if thread_alive else "unhealthy",
        description="DAG Scheduler (cron-based workflow submission)",
        source="dag_brain",
        details=details,
    )
```

- [ ] **Step 2: Check `ScheduleRepository.list_all()` accepts status param**

Read `infrastructure/schedule_repository.py` and confirm `list_all(status=)` is supported. If it only accepts `schedule_id`, adjust the query to filter in Python or add the status parameter.

- [ ] **Step 3: Verify locally**

```bash
python -c "
from docker_health.dag_brain import DAGBrainSubsystem
s = DAGBrainSubsystem()
result = s._check_scheduler()
import json; print(json.dumps(result, indent=2))
"
```

Expected: warning (scheduler not initialized locally) with no crash. The `active_schedules` field should either show schedules or an error string.

- [ ] **Step 4: Commit**

```bash
git add docker_health/dag_brain.py
git commit -m "feat: active schedule listing in scheduler health component"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Deploy to Docker worker and DAG Brain**

Use `deploy.sh` to deploy all apps with the new health components.

- [ ] **Step 2: Verify worker health endpoint**

```bash
curl -s https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net/health | python3 -m json.tool
```

Confirm new components appear in `subsystems.shared_infrastructure.components`:
- `config_checklist` — all required vars set
- `schema_validation` — tables and enums present
- `outbound_connectivity` — TiTiler reachable

- [ ] **Step 3: Verify DAG Brain health endpoint**

```bash
curl -s https://rmhdagmaster-cxhkh2fgeqbzayhx.eastus-01.azurewebsites.net/health | python3 -m json.tool
```

Confirm new components appear in `subsystems.dag_brain.components`:
- `workflow_registry` — workflows loaded, zero missing handlers
- `scheduler` — includes `active_schedules` array

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: health endpoint adjustments from deployment testing"
```
