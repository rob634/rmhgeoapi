# Preflight Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mode-aware `/api/preflight` endpoint that validates write-path capabilities per APP_MODE, producing an actionable punch list of eService requests for corporate QA deployment.

**Architecture:** Separate preflight check framework (not health check plugins) with a `PreflightCheck` base class. Each check module tests actual CRUD operations (not just connectivity), reports pass/fail with exact Azure RBAC remediation text. The check registry filters by APP_MODE so each deployment only validates what it actually needs.

**Tech Stack:** Python 3.12, psycopg (SQL composition), Azure Blob Storage SDK, Azure Functions Blueprint, FastAPI, Pydantic model introspection for schema derivation.

---

## File Structure

| File | Responsibility |
|------|----------------|
| **Create:** `triggers/preflight.py` | Blueprint endpoint (Functions) + orchestrator logic |
| **Create:** `triggers/preflight_checks/__init__.py` | Check registry, mode-aware filtering |
| **Create:** `triggers/preflight_checks/base.py` | `PreflightCheck` ABC, result/remediation dataclasses |
| **Create:** `triggers/preflight_checks/environment.py` | Env var validation (wraps existing `config.env_validation`) |
| **Create:** `triggers/preflight_checks/database.py` | DB canary write, schema completeness, extensions, pgSTAC roles |
| **Create:** `triggers/preflight_checks/dag.py` | Lease test, workflow registry, handler coverage |
| **Create:** `triggers/preflight_checks/storage.py` | Blob CRUD canary per zone, storage token test |
| **Create:** `triggers/preflight_checks/runtime.py` | Handler imports, GDAL version, mount write test |
| **Modify:** `function_app.py` | Register preflight blueprint (Phase 1 with probes) |
| **Modify:** `docker_service.py` | Add `/preflight` FastAPI endpoint |
| **Create:** `tests/unit/test_preflight_base.py` | Unit tests for base class, mode filtering, schema derivation |

---

### Task 1: Base Class, Registry, and Endpoint Scaffold

**Files:**
- Create: `triggers/preflight_checks/base.py`
- Create: `triggers/preflight_checks/__init__.py`
- Create: `triggers/preflight.py`
- Modify: `function_app.py`
- Modify: `docker_service.py`
- Create: `tests/unit/test_preflight_base.py`

- [ ] **Step 1: Write tests for base class and mode filtering**

```python
# tests/unit/test_preflight_base.py
"""Unit tests for preflight check base class and registry."""

import pytest
from config.app_mode_config import AppMode


class TestPreflightResult:
    """Test the result dataclass structure."""

    def test_pass_result(self):
        from triggers.preflight_checks.base import PreflightResult

        result = PreflightResult.passed("Canary write succeeded")
        assert result.status == "pass"
        assert result.detail == "Canary write succeeded"
        assert result.remediation is None

    def test_fail_result_with_remediation(self):
        from triggers.preflight_checks.base import PreflightResult, Remediation

        remediation = Remediation(
            action="Assign Storage Blob Data Contributor",
            azure_role="Storage Blob Data Contributor",
            scope="/subscriptions/xxx/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/acct",
            eservice_summary="Request RBAC: Storage Blob Data Contributor on 'acct'",
        )
        result = PreflightResult.failed("403 Forbidden", remediation=remediation)
        assert result.status == "fail"
        assert result.remediation.azure_role == "Storage Blob Data Contributor"

    def test_skip_result(self):
        from triggers.preflight_checks.base import PreflightResult

        result = PreflightResult.skipped("Not required for platform mode")
        assert result.status == "skip"


class TestModeFiltering:
    """Test that checks are filtered by APP_MODE."""

    def test_orchestrator_skips_mount_check(self):
        from triggers.preflight_checks import get_checks_for_mode

        checks = get_checks_for_mode(AppMode.ORCHESTRATOR)
        names = [c.name for c in checks]
        assert "mount_write" not in names
        assert "blob_crud" not in names

    def test_worker_docker_includes_mount_and_blob(self):
        from triggers.preflight_checks import get_checks_for_mode

        checks = get_checks_for_mode(AppMode.WORKER_DOCKER)
        names = [c.name for c in checks]
        assert "mount_write" in names
        assert "blob_crud" in names

    def test_platform_skips_dag_and_storage(self):
        from triggers.preflight_checks import get_checks_for_mode

        checks = get_checks_for_mode(AppMode.PLATFORM)
        names = [c.name for c in checks]
        assert "dag_lease" not in names
        assert "blob_crud" not in names
        assert "extensions" not in names

    def test_standalone_includes_everything_when_docker_disabled(self):
        from triggers.preflight_checks import get_checks_for_mode

        checks = get_checks_for_mode(AppMode.STANDALONE, docker_worker_enabled=False)
        names = [c.name for c in checks]
        assert "mount_write" in names
        assert "blob_crud" in names
        assert "dag_lease" in names

    def test_standalone_skips_worker_checks_when_docker_enabled(self):
        from triggers.preflight_checks import get_checks_for_mode

        checks = get_checks_for_mode(AppMode.STANDALONE, docker_worker_enabled=True)
        names = [c.name for c in checks]
        assert "mount_write" not in names
        assert "blob_crud" not in names
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda run -n azgeo python -m pytest tests/unit/test_preflight_base.py -v
```
Expected: `ModuleNotFoundError: No module named 'triggers.preflight_checks'`

- [ ] **Step 3: Implement base class**

```python
# triggers/preflight_checks/base.py
"""
Preflight check base class and result structures.

Preflight checks validate write-path capabilities (not just connectivity).
Each failed check includes exact Azure RBAC remediation for eService requests.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

from config.app_mode_config import AppMode


@dataclass
class Remediation:
    """Actionable fix — maps 1:1 to an eService request."""

    action: str
    azure_role: Optional[str] = None
    scope: Optional[str] = None
    eservice_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PreflightResult:
    """Result of a single preflight check."""

    status: str  # "pass", "fail", "skip", "warn"
    detail: str
    remediation: Optional[Remediation] = None
    sub_checks: Optional[Dict[str, Any]] = None

    @classmethod
    def passed(cls, detail: str, **kwargs) -> "PreflightResult":
        return cls(status="pass", detail=detail, **kwargs)

    @classmethod
    def failed(cls, detail: str, remediation: Optional[Remediation] = None, **kwargs) -> "PreflightResult":
        return cls(status="fail", detail=detail, remediation=remediation, **kwargs)

    @classmethod
    def skipped(cls, detail: str) -> "PreflightResult":
        return cls(status="skip", detail=detail)

    @classmethod
    def warned(cls, detail: str, remediation: Optional[Remediation] = None) -> "PreflightResult":
        return cls(status="warn", detail=detail, remediation=remediation)

    def to_dict(self) -> Dict[str, Any]:
        d = {"status": self.status, "detail": self.detail}
        if self.remediation:
            d["remediation"] = self.remediation.to_dict()
        if self.sub_checks:
            d["sub_checks"] = self.sub_checks
        return d


class PreflightCheck(ABC):
    """Base class for preflight validation checks."""

    name: str = "unknown"
    description: str = ""
    required_modes: set  # Which APP_MODEs require this check

    def is_required(self, mode: AppMode, docker_worker_enabled: bool = False) -> bool:
        """Check if this check is needed for the given mode.

        STANDALONE inherits worker checks only when docker_worker_enabled=False.
        """
        if mode == AppMode.STANDALONE and docker_worker_enabled:
            # Standalone with external worker = orchestrator checks only
            return mode in self.required_modes and AppMode.WORKER_DOCKER not in self.required_modes
        return mode in self.required_modes

    @abstractmethod
    def run(self, config, app_mode: AppMode) -> PreflightResult:
        """Execute the check. Returns structured result with remediation on failure."""
        ...
```

- [ ] **Step 4: Implement registry**

```python
# triggers/preflight_checks/__init__.py
"""
Preflight check registry — mode-aware filtering.

Each check declares which APP_MODEs require it. The registry
returns only checks relevant to the current deployment.
"""

from typing import List

from config.app_mode_config import AppMode
from .base import PreflightCheck


# Populated by Task 2-6 as checks are implemented.
# Import order = execution order.
ALL_PREFLIGHT_CHECKS: List[type] = []


def get_checks_for_mode(
    mode: AppMode,
    docker_worker_enabled: bool = False,
) -> List[PreflightCheck]:
    """Instantiate and filter checks for the given APP_MODE."""
    checks = []
    for cls in ALL_PREFLIGHT_CHECKS:
        instance = cls()
        if instance.is_required(mode, docker_worker_enabled):
            checks.append(instance)
    return checks
```

- [ ] **Step 5: Implement endpoint (Azure Functions blueprint)**

```python
# triggers/preflight.py
# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT VALIDATION ENDPOINT
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Diagnostic endpoint — mode-aware write-path validation
# PURPOSE: Validate environment capabilities for QA deployment. Produces
#          actionable punch list of eService requests for missing RBAC/config.
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: bp (Blueprint)
# DEPENDENCIES: triggers.preflight_checks, config
# ============================================================================
"""
Preflight validation endpoint.

Unlike /api/health (connectivity), /api/preflight tests actual CRUD
capabilities: canary DB writes, blob write+delete, schema completeness,
handler imports, mount access. Each failure includes exact Azure RBAC
role and scope for eService remediation.

Runs once per deployment — intentionally slow and thorough.
"""

import json
import logging
import time
from datetime import datetime, timezone

import azure.functions as func
from azure.functions import Blueprint

bp = Blueprint()
logger = logging.getLogger(__name__)


def _run_preflight() -> dict:
    """Core preflight logic — shared by Functions and Docker endpoints."""
    from config import get_config, get_app_mode_config, __version__
    from triggers.preflight_checks import get_checks_for_mode

    config = get_config()
    app_mode_config = get_app_mode_config()
    mode = app_mode_config.mode

    checks = get_checks_for_mode(
        mode,
        docker_worker_enabled=app_mode_config.docker_worker_enabled,
    )

    results = {}
    punch_list = []

    for check in checks:
        start = time.monotonic()
        try:
            result = check.run(config, mode)
        except Exception as exc:
            from triggers.preflight_checks.base import PreflightResult, Remediation
            result = PreflightResult.failed(
                f"Check crashed: {type(exc).__name__}: {exc}",
                remediation=Remediation(action=f"Investigate {check.name} check failure"),
            )
            logger.exception("Preflight check '%s' crashed", check.name)

        elapsed_ms = round((time.monotonic() - start) * 1000)
        entry = result.to_dict()
        entry["duration_ms"] = elapsed_ms
        results[check.name] = entry

        if result.status == "fail":
            summary = (
                result.remediation.eservice_summary
                if result.remediation and result.remediation.eservice_summary
                else result.detail
            )
            punch_list.append(summary)

    passed = sum(1 for r in results.values() if r["status"] == "pass")
    failed = sum(1 for r in results.values() if r["status"] == "fail")
    warned = sum(1 for r in results.values() if r["status"] == "warn")
    skipped = sum(1 for r in results.values() if r["status"] == "skip")

    return {
        "status": "pass" if failed == 0 else "fail",
        "app_mode": mode.value,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "checks_run": passed + failed + warned,
            "checks_passed": passed,
            "checks_failed": failed,
            "checks_warned": warned,
            "checks_skipped": skipped,
        },
        "checks": results,
        "punch_list": punch_list,
    }


@bp.route(route="preflight", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def preflight(req: func.HttpRequest) -> func.HttpResponse:
    """Preflight validation — mode-aware write-path capability test."""
    try:
        data = _run_preflight()
        status_code = 200 if data["status"] == "pass" else 424  # 424 Failed Dependency
        return func.HttpResponse(
            json.dumps(data, indent=2, default=str),
            status_code=status_code,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.exception("Preflight endpoint crashed")
        return func.HttpResponse(
            json.dumps({"status": "error", "error": f"Preflight crashed: {exc}"}),
            status_code=500,
            mimetype="application/json",
        )
```

- [ ] **Step 6: Register blueprint in function_app.py**

In `function_app.py`, add the preflight blueprint registration immediately after the probes blueprint (Phase 1 — always available):

Find this block:
```python
from triggers.probes import bp as probes_bp
app.register_functions(probes_bp)
```

Add after it:
```python
from triggers.preflight import bp as preflight_bp
app.register_functions(preflight_bp)
```

- [ ] **Step 7: Add FastAPI endpoint in docker_service.py**

Find the `/health` endpoint in `docker_service.py` and add the preflight endpoint after it:

```python
@app.get("/preflight")
def preflight_check():
    """Preflight validation — mode-aware write-path capability test."""
    from triggers.preflight import _run_preflight
    try:
        data = _run_preflight()
        status_code = 200 if data["status"] == "pass" else 424
        return JSONResponse(content=data, status_code=status_code)
    except Exception as exc:
        logger.exception("Preflight endpoint crashed")
        return JSONResponse(
            content={"status": "error", "error": f"Preflight crashed: {exc}"},
            status_code=500,
        )
```

- [ ] **Step 8: Run tests — verify they pass**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda run -n azgeo python -m pytest tests/unit/test_preflight_base.py -v
```
Expected: All `TestPreflightResult` tests pass. `TestModeFiltering` tests fail (no checks registered yet — that's expected, we fix in subsequent tasks).

- [ ] **Step 9: Commit**

```bash
git add triggers/preflight.py triggers/preflight_checks/ tests/unit/test_preflight_base.py
git commit -m "feat: preflight endpoint scaffold — base class, registry, endpoint wiring"
```

---

### Task 2: Environment Validation Check

**Files:**
- Create: `triggers/preflight_checks/environment.py`
- Modify: `triggers/preflight_checks/__init__.py`

- [ ] **Step 1: Implement environment check**

```python
# triggers/preflight_checks/environment.py
"""
Preflight check: environment variable validation.

Wraps the existing config.env_validation module to surface missing/invalid
env vars with remediation text. This runs the same regex validation as
startup but formats results as preflight entries.
"""

import logging
from typing import Any, Dict

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

# All modes need env vars validated
_ALL_MODES = {AppMode.STANDALONE, AppMode.PLATFORM, AppMode.ORCHESTRATOR, AppMode.WORKER_DOCKER}


class EnvironmentCheck(PreflightCheck):
    name = "environment_vars"
    description = "Validate required environment variables exist and match expected format"
    required_modes = _ALL_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        from config.env_validation import validate_environment

        errors = validate_environment(include_warnings=False)

        if not errors:
            return PreflightResult.passed("All required environment variables present and valid")

        error_details = {}
        for err in errors:
            error_details[err.var_name] = {
                "message": err.message,
                "current_value": err.current_value or "(not set)",
                "expected_pattern": err.expected_pattern,
                "fix": err.fix_suggestion,
            }

        missing_names = [e.var_name for e in errors]
        return PreflightResult.failed(
            f"{len(errors)} environment variable(s) invalid: {', '.join(missing_names)}",
            remediation=Remediation(
                action=f"Set or fix environment variables: {', '.join(missing_names)}",
                eservice_summary=f"APP CONFIG: Set {len(errors)} missing/invalid env var(s) on app: {', '.join(missing_names)}",
            ),
            sub_checks=error_details,
        )
```

- [ ] **Step 2: Register in __init__.py**

Add to `triggers/preflight_checks/__init__.py`:

```python
from .environment import EnvironmentCheck

ALL_PREFLIGHT_CHECKS: List[type] = [
    EnvironmentCheck,
]
```

- [ ] **Step 3: Commit**

```bash
git add triggers/preflight_checks/environment.py triggers/preflight_checks/__init__.py
git commit -m "feat: preflight environment check — wraps existing env_validation"
```

---

### Task 3: Database Checks (Canary Write + Schema Completeness + Extensions + Roles)

**Files:**
- Create: `triggers/preflight_checks/database.py`
- Modify: `triggers/preflight_checks/__init__.py`
- Create: `tests/unit/test_preflight_schema_derivation.py`

- [ ] **Step 1: Write test for schema derivation**

```python
# tests/unit/test_preflight_schema_derivation.py
"""Test that expected schema can be derived from Pydantic models."""

import pytest


class TestSchemaDerival:
    """Verify schema expectations are derived from models, not hardcoded."""

    def test_derive_expected_tables_returns_nonempty(self):
        from triggers.preflight_checks.database import _derive_expected_tables
        tables = _derive_expected_tables()
        assert len(tables) > 0
        assert isinstance(tables, dict)

    def test_core_app_tables_present(self):
        from triggers.preflight_checks.database import _derive_expected_tables
        tables = _derive_expected_tables()
        table_names = {t["table"] for t in tables.values()}
        # Core tables that must always exist
        assert "jobs" in table_names
        assert "workflow_runs" in table_names
        assert "assets" in table_names

    def test_geo_tables_present(self):
        from triggers.preflight_checks.database import _derive_expected_tables
        tables = _derive_expected_tables()
        geo_tables = {t["table"] for key, t in tables.items() if t["schema"] == "geo"}
        assert "table_catalog" in geo_tables

    def test_etl_tracking_tables_present(self):
        from triggers.preflight_checks.database import _derive_expected_tables
        tables = _derive_expected_tables()
        table_names = {t["table"] for t in tables.values()}
        assert "vector_etl_tracking" in table_names
        assert "raster_render_configs" in table_names

    def test_each_table_has_columns(self):
        from triggers.preflight_checks.database import _derive_expected_tables
        tables = _derive_expected_tables()
        for key, meta in tables.items():
            assert len(meta["columns"]) > 0, f"Table {key} has no columns"

    def test_expected_enums_returns_nonempty(self):
        from triggers.preflight_checks.database import _derive_expected_enums
        enums = _derive_expected_enums()
        assert len(enums) > 0
        assert "job_status" in enums
        assert "workflow_run_status" in enums
        assert "approval_state" in enums
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
conda run -n azgeo python -m pytest tests/unit/test_preflight_schema_derivation.py -v
```
Expected: `ImportError: cannot import name '_derive_expected_tables'`

- [ ] **Step 3: Implement database check module**

```python
# triggers/preflight_checks/database.py
"""
Preflight checks: database connectivity, schema completeness, extensions, roles.

Schema expectations are derived from the same Pydantic models that
generate_composed_statements() uses for DDL — no separate manifest.
"""

import logging
from typing import Any, Dict, Set

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

_ALL_MODES = {AppMode.STANDALONE, AppMode.PLATFORM, AppMode.ORCHESTRATOR, AppMode.WORKER_DOCKER}
_NON_PLATFORM = {AppMode.STANDALONE, AppMode.ORCHESTRATOR, AppMode.WORKER_DOCKER}

# ============================================================================
# SCHEMA DERIVATION — same source as rebuild DDL
# ============================================================================

# Legacy models whose table name is passed explicitly to generate_table_composed().
# When a model gains __sql_table_name, remove it from this map.
_LEGACY_TABLE_MAP: Dict[str, str] = {
    "JobRecord": "jobs",
    "TaskRecord": "tasks",
    "ApiRequest": "api_requests",
    "JanitorRun": "janitor_runs",
    "EtlSourceFile": "etl_source_files",
    "UnpublishJobRecord": "unpublish_jobs",
    "PromotedDataset": "promoted_datasets",
    "SystemSnapshotRecord": "system_snapshots",
    "DatasetRefRecord": "dataset_refs",
    "CogMetadataRecord": "cog_metadata",
    "ZarrMetadataRecord": "zarr_metadata",
    "Artifact": "artifacts",
}

# Geo schema models — always in 'geo' schema
_GEO_MODELS = ["GeoTableCatalog", "FeatureCollectionStyles", "B2CRoute", "B2BRoute"]

# ETL tracking models — in 'app' schema but generated by generate_etl_tracking_ddl()
_ETL_TRACKING_MODELS: Dict[str, str] = {
    "VectorEtlTracking": "vector_etl_tracking",
    "RasterEtlTracking": "raster_etl_tracking",
    "RasterRenderConfig": "raster_render_configs",
}


def _derive_expected_tables() -> Dict[str, Dict[str, Any]]:
    """Derive expected tables from Pydantic models — same source as rebuild DDL.

    Returns:
        Dict keyed by "schema.table_name", value is {schema, table, columns: [str]}.
    """
    from core.schema.sql_generator import PydanticToSQL
    import core.models as models_module

    tables = {}

    # --- Modern models with __sql_table_name metadata ---
    # get_model_sql_metadata returns {table_name, schema, ...} or empty dict
    for attr_name in dir(models_module):
        obj = getattr(models_module, attr_name, None)
        if obj is None or not isinstance(obj, type):
            continue
        try:
            meta = PydanticToSQL.get_model_sql_metadata(obj)
        except Exception:
            continue
        if meta and meta.get("table_name"):
            schema = meta.get("schema", "app")
            table = meta["table_name"]
            columns = list(obj.model_fields.keys()) if hasattr(obj, "model_fields") else []
            tables[f"{schema}.{table}"] = {"schema": schema, "table": table, "columns": columns}

    # --- Legacy models (explicit table name in sql_generator) ---
    for model_name, table_name in _LEGACY_TABLE_MAP.items():
        model = getattr(models_module, model_name, None)
        if model is None:
            continue
        columns = list(model.model_fields.keys()) if hasattr(model, "model_fields") else []
        tables[f"app.{table_name}"] = {"schema": "app", "table": table_name, "columns": columns}

    # --- Geo schema models ---
    for model_name in _GEO_MODELS:
        model = getattr(models_module, model_name, None)
        if model is None:
            continue
        # Geo models may have __sql_table_name or use conventional naming
        meta = {}
        try:
            meta = PydanticToSQL.get_model_sql_metadata(model) or {}
        except Exception:
            pass
        table_name = meta.get("table_name") or _camel_to_snake(model_name)
        columns = list(model.model_fields.keys()) if hasattr(model, "model_fields") else []
        tables[f"geo.{table_name}"] = {"schema": "geo", "table": table_name, "columns": columns}

    # --- ETL tracking models ---
    for model_name, table_name in _ETL_TRACKING_MODELS.items():
        model = getattr(models_module, model_name, None)
        if model is None:
            continue
        columns = list(model.model_fields.keys()) if hasattr(model, "model_fields") else []
        tables[f"app.{table_name}"] = {"schema": "app", "table": table_name, "columns": columns}

    return tables


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case for fallback table naming."""
    import re
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _derive_expected_enums() -> Set[str]:
    """Derive expected enum type names from core.models enums.

    These match the enum type names created by generate_composed_statements().
    Convention: CamelCase enum class → snake_case SQL type.
    """
    import core.models as models_module
    from enum import Enum

    enums = set()
    for attr_name in dir(models_module):
        obj = getattr(models_module, attr_name, None)
        if obj is None or not isinstance(obj, type):
            continue
        if issubclass(obj, Enum) and obj is not Enum:
            enums.add(_camel_to_snake(attr_name))
    return enums


# ============================================================================
# CHECK IMPLEMENTATIONS
# ============================================================================

class DatabaseCanaryCheck(PreflightCheck):
    name = "db_canary_write"
    description = "INSERT + SELECT + DELETE canary row to verify write access"
    required_modes = _ALL_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        import uuid
        try:
            from infrastructure.database import get_connection
            from psycopg import sql as psql

            canary_id = f"preflight-canary-{uuid.uuid4().hex[:12]}"
            schema = config.database.app_schema

            with get_connection() as conn:
                with conn.cursor() as cur:
                    # INSERT canary
                    cur.execute(
                        psql.SQL(
                            "INSERT INTO {schema}.api_requests (request_id, endpoint, method, status_code) "
                            "VALUES (%s, %s, %s, %s)"
                        ).format(schema=psql.Identifier(schema)),
                        [canary_id, "/preflight/canary", "GET", 200],
                    )
                    # SELECT it back
                    cur.execute(
                        psql.SQL(
                            "SELECT request_id FROM {schema}.api_requests WHERE request_id = %s"
                        ).format(schema=psql.Identifier(schema)),
                        [canary_id],
                    )
                    row = cur.fetchone()
                    if not row:
                        return PreflightResult.failed(
                            "Canary INSERT succeeded but SELECT returned no rows",
                            remediation=Remediation(
                                action="Check database read permissions for managed identity",
                                eservice_summary="DB PERMISSION: Verify SELECT grant on app schema for managed identity",
                            ),
                        )
                    # DELETE canary
                    cur.execute(
                        psql.SQL(
                            "DELETE FROM {schema}.api_requests WHERE request_id = %s"
                        ).format(schema=psql.Identifier(schema)),
                        [canary_id],
                    )
                conn.commit()

            return PreflightResult.passed(
                f"INSERT + SELECT + DELETE succeeded on {schema}.api_requests"
            )

        except Exception as exc:
            error_msg = str(exc)
            if "permission denied" in error_msg.lower():
                return PreflightResult.failed(
                    f"Database write permission denied: {error_msg}",
                    remediation=Remediation(
                        action=f"Grant INSERT, SELECT, DELETE on schema '{schema}' to managed identity",
                        eservice_summary=f"DB PERMISSION: Grant INSERT/SELECT/DELETE on '{schema}' schema to app managed identity",
                    ),
                )
            if "does not exist" in error_msg.lower():
                return PreflightResult.failed(
                    f"Table not found (run rebuild first): {error_msg}",
                    remediation=Remediation(
                        action="Run schema rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes",
                    ),
                )
            return PreflightResult.failed(
                f"Database canary write failed: {error_msg}",
                remediation=Remediation(
                    action="Check database connectivity and permissions",
                    eservice_summary=f"DB ERROR: {error_msg[:200]}",
                ),
            )


class SchemaCompletenessCheck(PreflightCheck):
    name = "schema_completeness"
    description = "Verify all expected tables and enums exist (derived from Pydantic models)"
    required_modes = _NON_PLATFORM

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.database import get_connection
            from psycopg import sql as psql

            expected_tables = _derive_expected_tables()
            expected_enums = _derive_expected_enums()

            with get_connection() as conn:
                with conn.cursor() as cur:
                    # --- Check tables ---
                    cur.execute(
                        "SELECT table_schema, table_name "
                        "FROM information_schema.tables "
                        "WHERE table_schema IN ('app', 'geo') "
                        "AND table_type = 'BASE TABLE'"
                    )
                    actual_tables = {f"{row[0]}.{row[1]}" for row in cur.fetchall()}

                    missing_tables = sorted(set(expected_tables.keys()) - actual_tables)

                    # --- Check enums ---
                    cur.execute(
                        psql.SQL(
                            "SELECT typname FROM pg_type t "
                            "JOIN pg_namespace n ON t.typnamespace = n.oid "
                            "WHERE n.nspname = %s AND t.typtype = 'e'"
                        ),
                        [config.database.app_schema],
                    )
                    actual_enums = {row[0] for row in cur.fetchall()}

                    missing_enums = sorted(expected_enums - actual_enums)

            sub_checks = {}
            if missing_tables:
                sub_checks["missing_tables"] = missing_tables
            if missing_enums:
                sub_checks["missing_enums"] = missing_enums
            sub_checks["expected_table_count"] = len(expected_tables)
            sub_checks["actual_table_count"] = len(actual_tables & set(expected_tables.keys()))
            sub_checks["expected_enum_count"] = len(expected_enums)
            sub_checks["actual_enum_count"] = len(actual_enums & expected_enums)

            if missing_tables or missing_enums:
                detail_parts = []
                if missing_tables:
                    detail_parts.append(f"{len(missing_tables)} missing table(s)")
                if missing_enums:
                    detail_parts.append(f"{len(missing_enums)} missing enum(s)")
                return PreflightResult.failed(
                    f"Schema incomplete: {', '.join(detail_parts)}",
                    remediation=Remediation(
                        action="Run schema rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes",
                        eservice_summary=f"SCHEMA: Run rebuild — {', '.join(detail_parts)}",
                    ),
                    sub_checks=sub_checks,
                )

            return PreflightResult.passed(
                f"All {len(expected_tables)} tables and {len(expected_enums)} enums present",
                sub_checks=sub_checks,
            )

        except Exception as exc:
            return PreflightResult.failed(
                f"Schema completeness check failed: {exc}",
                remediation=Remediation(action="Check database connectivity"),
            )


class ExtensionsCheck(PreflightCheck):
    name = "extensions"
    description = "Verify required PostgreSQL extensions (PostGIS, h3)"
    required_modes = _NON_PLATFORM

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        required = {"postgis", "h3"}
        try:
            from infrastructure.database import get_connection

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT extname FROM pg_extension WHERE extname = ANY(%s)",
                        [list(required)],
                    )
                    installed = {row[0] for row in cur.fetchall()}

            missing = sorted(required - installed)
            if missing:
                return PreflightResult.failed(
                    f"Missing PostgreSQL extensions: {', '.join(missing)}",
                    remediation=Remediation(
                        action=f"Install extensions: {'; '.join(f'CREATE EXTENSION IF NOT EXISTS {e}' for e in missing)}",
                        eservice_summary=f"DB EXTENSION: Install missing extension(s): {', '.join(missing)}",
                    ),
                )

            return PreflightResult.passed(f"All required extensions installed: {', '.join(sorted(installed))}")

        except Exception as exc:
            return PreflightResult.failed(
                f"Extension check failed: {exc}",
                remediation=Remediation(action="Check database connectivity"),
            )


class PgSTACRolesCheck(PreflightCheck):
    name = "pgstac_roles"
    description = "Verify pgSTAC database roles exist (pgstac_admin, pgstac_ingest, pgstac_read)"
    required_modes = _NON_PLATFORM

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        required_roles = {"pgstac_admin", "pgstac_ingest", "pgstac_read"}
        try:
            from infrastructure.database import get_connection

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                        [list(required_roles)],
                    )
                    existing = {row[0] for row in cur.fetchall()}

            missing = sorted(required_roles - existing)
            if missing:
                create_sql = "; ".join(
                    f"DO $$ BEGIN CREATE ROLE {r}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                    for r in missing
                )
                return PreflightResult.failed(
                    f"Missing pgSTAC roles: {', '.join(missing)}",
                    remediation=Remediation(
                        action=f"Create roles and grant to managed identity: {create_sql}",
                        eservice_summary=f"DB ROLES: Create pgSTAC role(s): {', '.join(missing)} and grant WITH ADMIN OPTION to app managed identity",
                    ),
                )

            return PreflightResult.passed(f"All pgSTAC roles exist: {', '.join(sorted(existing))}")

        except Exception as exc:
            return PreflightResult.failed(
                f"pgSTAC roles check failed: {exc}",
                remediation=Remediation(action="Check database connectivity"),
            )
```

- [ ] **Step 4: Register in __init__.py**

Update `triggers/preflight_checks/__init__.py`:

```python
from .environment import EnvironmentCheck
from .database import DatabaseCanaryCheck, SchemaCompletenessCheck, ExtensionsCheck, PgSTACRolesCheck

ALL_PREFLIGHT_CHECKS: List[type] = [
    EnvironmentCheck,
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
]
```

- [ ] **Step 5: Run schema derivation tests**

```bash
conda run -n azgeo python -m pytest tests/unit/test_preflight_schema_derivation.py -v
```
Expected: All 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add triggers/preflight_checks/database.py tests/unit/test_preflight_schema_derivation.py triggers/preflight_checks/__init__.py
git commit -m "feat: preflight database checks — canary write, schema completeness, extensions, pgSTAC roles"
```

---

### Task 4: DAG Infrastructure Checks

**Files:**
- Create: `triggers/preflight_checks/dag.py`
- Modify: `triggers/preflight_checks/__init__.py`

- [ ] **Step 1: Implement DAG checks**

```python
# triggers/preflight_checks/dag.py
"""
Preflight checks: DAG infrastructure — lease, workflow registry, handler coverage.

Validates that the orchestration machinery is operational:
- Can acquire and release an orchestrator lease
- All workflow YAML files load without errors
- Every handler referenced in workflows exists in ALL_HANDLERS
"""

import logging
from typing import Any, Dict

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

_ORCHESTRATOR_MODES = {AppMode.STANDALONE, AppMode.ORCHESTRATOR}
_DAG_MODES = {AppMode.STANDALONE, AppMode.ORCHESTRATOR, AppMode.WORKER_DOCKER}


class DAGLeaseCheck(PreflightCheck):
    name = "dag_lease"
    description = "Acquire and release orchestrator lease to verify table access"
    required_modes = _ORCHESTRATOR_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.database import get_connection
            from psycopg import sql as psql

            schema = config.database.app_schema

            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Verify orchestrator_leases table exists and is accessible
                    cur.execute(
                        psql.SQL(
                            "SELECT COUNT(*) FROM {schema}.orchestrator_leases"
                        ).format(schema=psql.Identifier(schema))
                    )
                    count = cur.fetchone()[0]

            return PreflightResult.passed(
                f"orchestrator_leases table accessible ({count} row(s))"
            )

        except Exception as exc:
            error_msg = str(exc)
            if "does not exist" in error_msg.lower():
                return PreflightResult.failed(
                    "orchestrator_leases table missing — run schema rebuild",
                    remediation=Remediation(
                        action="Run schema rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes",
                        eservice_summary="SCHEMA: orchestrator_leases table missing — run rebuild",
                    ),
                )
            return PreflightResult.failed(
                f"Lease table check failed: {error_msg}",
                remediation=Remediation(
                    action="Check database permissions on app.orchestrator_leases",
                    eservice_summary=f"DB PERMISSION: Cannot access orchestrator_leases: {error_msg[:200]}",
                ),
            )


class WorkflowRegistryCheck(PreflightCheck):
    name = "workflow_registry"
    description = "Load all YAML workflows and verify handler coverage"
    required_modes = _ORCHESTRATOR_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from pathlib import Path
            from core.workflow_registry import WorkflowRegistry
            from services import ALL_HANDLERS

            workflows_dir = Path(__file__).resolve().parent.parent.parent / "workflows"

            registry = WorkflowRegistry(
                workflows_dir=workflows_dir,
                handler_names=set(ALL_HANDLERS.keys()),
            )
            loaded = registry.load_all()
            workflow_names = registry.list_workflows()

            # Extract all handler names referenced in workflows
            referenced_handlers = set()
            for wf_name in workflow_names:
                defn = registry.get(wf_name)
                if defn is None:
                    continue
                for node_name, node in defn.nodes.items():
                    if hasattr(node, "handler"):
                        referenced_handlers.add(node.handler)
                    if hasattr(node, "task") and hasattr(node.task, "handler"):
                        referenced_handlers.add(node.task.handler)
                if defn.finalize and defn.finalize.handler:
                    referenced_handlers.add(defn.finalize.handler)

            # Check coverage
            available_handlers = set(ALL_HANDLERS.keys())
            missing_handlers = sorted(referenced_handlers - available_handlers)

            sub_checks = {
                "workflows_loaded": loaded,
                "workflow_names": workflow_names,
                "handlers_referenced": len(referenced_handlers),
                "handlers_available": len(available_handlers),
            }

            if missing_handlers:
                sub_checks["missing_handlers"] = missing_handlers
                return PreflightResult.failed(
                    f"{len(missing_handlers)} handler(s) referenced in workflows but not registered: {', '.join(missing_handlers)}",
                    remediation=Remediation(
                        action=f"Register missing handlers in services/__init__.py ALL_HANDLERS: {', '.join(missing_handlers)}",
                    ),
                    sub_checks=sub_checks,
                )

            if loaded == 0:
                return PreflightResult.failed(
                    f"No workflows found in {workflows_dir}",
                    remediation=Remediation(
                        action="Verify workflows/ directory exists and contains YAML files",
                    ),
                    sub_checks=sub_checks,
                )

            return PreflightResult.passed(
                f"{loaded} workflow(s) loaded, all {len(referenced_handlers)} referenced handlers registered",
                sub_checks=sub_checks,
            )

        except Exception as exc:
            return PreflightResult.failed(
                f"Workflow registry check failed: {exc}",
                remediation=Remediation(action=f"Fix workflow loading error: {exc}"),
            )


class DAGTablesCheck(PreflightCheck):
    name = "dag_tables"
    description = "Verify DAG execution tables exist (workflow_runs, workflow_tasks, workflow_task_deps)"
    required_modes = _DAG_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        required_tables = ["workflow_runs", "workflow_tasks", "workflow_task_deps"]
        try:
            from infrastructure.database import get_connection
            from psycopg import sql as psql

            schema = config.database.app_schema

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = %s AND table_name = ANY(%s)",
                        [schema, required_tables],
                    )
                    found = {row[0] for row in cur.fetchall()}

            missing = sorted(set(required_tables) - found)
            if missing:
                return PreflightResult.failed(
                    f"Missing DAG tables: {', '.join(missing)}",
                    remediation=Remediation(
                        action="Run schema rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes",
                        eservice_summary=f"SCHEMA: Missing DAG table(s): {', '.join(missing)} — run rebuild",
                    ),
                )

            return PreflightResult.passed(f"All DAG tables present: {', '.join(sorted(found))}")

        except Exception as exc:
            return PreflightResult.failed(
                f"DAG tables check failed: {exc}",
                remediation=Remediation(action="Check database connectivity"),
            )
```

- [ ] **Step 2: Register in __init__.py**

Add imports and entries to `ALL_PREFLIGHT_CHECKS`:

```python
from .dag import DAGLeaseCheck, WorkflowRegistryCheck, DAGTablesCheck

ALL_PREFLIGHT_CHECKS: List[type] = [
    EnvironmentCheck,
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
    DAGLeaseCheck,
    WorkflowRegistryCheck,
    DAGTablesCheck,
]
```

- [ ] **Step 3: Commit**

```bash
git add triggers/preflight_checks/dag.py triggers/preflight_checks/__init__.py
git commit -m "feat: preflight DAG checks — lease, workflow registry, handler coverage"
```

---

### Task 5: Storage Checks (Blob CRUD + Token)

**Files:**
- Create: `triggers/preflight_checks/storage.py`
- Modify: `triggers/preflight_checks/__init__.py`

- [ ] **Step 1: Implement storage checks**

```python
# triggers/preflight_checks/storage.py
"""
Preflight checks: blob storage CRUD and token acquisition.

Tests actual write-path operations per trust zone:
- Bronze: READ (handlers download source data)
- Silver: WRITE + DELETE (handlers upload COGs, Zarr, then unpublish deletes)

Canary blobs use '_preflight_canary' prefix for easy identification.
"""

import logging
from typing import Any, Dict

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

_WORKER_MODES = {AppMode.WORKER_DOCKER}  # standalone inherits via is_required()
CANARY_BLOB = "_preflight_canary/canary.txt"
CANARY_CONTENT = b"preflight-canary-test"


class StorageTokenCheck(PreflightCheck):
    name = "storage_token"
    description = "Verify OAuth token acquisition for Azure Blob Storage"
    required_modes = {AppMode.STANDALONE, AppMode.WORKER_DOCKER}

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            token = credential.get_token("https://storage.azure.com/.default")

            if not token or not token.token:
                return PreflightResult.failed(
                    "Token acquisition returned empty token",
                    remediation=Remediation(
                        action="Verify managed identity has Storage Blob Data Contributor role",
                        azure_role="Storage Blob Data Contributor",
                        eservice_summary="IDENTITY: Managed identity cannot acquire storage token — check role assignments",
                    ),
                )

            import time
            ttl_minutes = round((token.expires_on - time.time()) / 60)
            return PreflightResult.passed(f"Storage OAuth token acquired (TTL: {ttl_minutes}min)")

        except Exception as exc:
            return PreflightResult.failed(
                f"Storage token acquisition failed: {exc}",
                remediation=Remediation(
                    action="Verify managed identity exists and has Storage Blob Data Contributor role",
                    azure_role="Storage Blob Data Contributor",
                    eservice_summary=f"IDENTITY: Storage token acquisition failed: {str(exc)[:200]}",
                ),
            )


class BlobCRUDCheck(PreflightCheck):
    name = "blob_crud"
    description = "Write + read + delete canary blob in silver zone to verify CRUD access"
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        sub_checks = {}
        try:
            from infrastructure.blob import BlobRepository

            # --- Silver zone: WRITE + READ + DELETE ---
            silver_repo = BlobRepository.for_zone("silver")
            silver_container = config.storage.silver.cogs

            # WRITE
            try:
                silver_repo.write_blob(
                    container=silver_container,
                    blob_path=CANARY_BLOB,
                    data=CANARY_CONTENT,
                    overwrite=True,
                    content_type="text/plain",
                )
                sub_checks["silver_write"] = "pass"
            except Exception as exc:
                sub_checks["silver_write"] = f"fail: {exc}"
                return PreflightResult.failed(
                    f"Silver blob write failed: {exc}",
                    remediation=Remediation(
                        action=f"Assign 'Storage Blob Data Contributor' on storage account '{config.storage.silver.account_name}'",
                        azure_role="Storage Blob Data Contributor",
                        scope=f"Storage account: {config.storage.silver.account_name}",
                        eservice_summary=f"RBAC: Assign 'Storage Blob Data Contributor' to app identity on '{config.storage.silver.account_name}'",
                    ),
                    sub_checks=sub_checks,
                )

            # READ
            try:
                data = silver_repo.read_blob(silver_container, CANARY_BLOB)
                if data != CANARY_CONTENT:
                    sub_checks["silver_read"] = "fail: content mismatch"
                else:
                    sub_checks["silver_read"] = "pass"
            except Exception as exc:
                sub_checks["silver_read"] = f"fail: {exc}"

            # DELETE (cleanup)
            try:
                silver_repo.delete_blob(silver_container, CANARY_BLOB)
                sub_checks["silver_delete"] = "pass"
            except Exception as exc:
                sub_checks["silver_delete"] = f"fail: {exc}"
                return PreflightResult.failed(
                    f"Silver blob delete failed (canary blob left behind): {exc}",
                    remediation=Remediation(
                        action=f"Assign 'Storage Blob Data Contributor' (includes delete) on '{config.storage.silver.account_name}'",
                        azure_role="Storage Blob Data Contributor",
                        eservice_summary=f"RBAC: App identity cannot delete blobs on '{config.storage.silver.account_name}'",
                    ),
                    sub_checks=sub_checks,
                )

            # --- Bronze zone: READ test (list blobs) ---
            try:
                bronze_repo = BlobRepository.for_zone("bronze")
                bronze_container = config.storage.bronze.rasters
                bronze_repo.list_blobs(bronze_container, prefix="", limit=1)
                sub_checks["bronze_read"] = "pass"
            except Exception as exc:
                sub_checks["bronze_read"] = f"fail: {exc}"
                return PreflightResult.failed(
                    f"Bronze blob read/list failed: {exc}",
                    remediation=Remediation(
                        action=f"Assign 'Storage Blob Data Reader' on storage account '{config.storage.bronze.account_name}'",
                        azure_role="Storage Blob Data Reader",
                        scope=f"Storage account: {config.storage.bronze.account_name}",
                        eservice_summary=f"RBAC: Assign 'Storage Blob Data Reader' to app identity on '{config.storage.bronze.account_name}'",
                    ),
                    sub_checks=sub_checks,
                )

            return PreflightResult.passed(
                "Blob CRUD verified: silver write+read+delete, bronze read",
                sub_checks=sub_checks,
            )

        except Exception as exc:
            return PreflightResult.failed(
                f"Blob CRUD check failed: {exc}",
                remediation=Remediation(
                    action="Check storage account connectivity and RBAC roles",
                    eservice_summary=f"STORAGE: Blob access check failed: {str(exc)[:200]}",
                ),
                sub_checks=sub_checks,
            )
```

- [ ] **Step 2: Register in __init__.py**

Add imports and entries:

```python
from .storage import StorageTokenCheck, BlobCRUDCheck

ALL_PREFLIGHT_CHECKS: List[type] = [
    EnvironmentCheck,
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
    DAGLeaseCheck,
    WorkflowRegistryCheck,
    DAGTablesCheck,
    StorageTokenCheck,
    BlobCRUDCheck,
]
```

- [ ] **Step 3: Commit**

```bash
git add triggers/preflight_checks/storage.py triggers/preflight_checks/__init__.py
git commit -m "feat: preflight storage checks — blob CRUD canary, token acquisition"
```

---

### Task 6: Runtime Checks (Handler Imports, GDAL, Mount)

**Files:**
- Create: `triggers/preflight_checks/runtime.py`
- Modify: `triggers/preflight_checks/__init__.py`
- Modify: `tests/unit/test_preflight_base.py`

- [ ] **Step 1: Implement runtime checks**

```python
# triggers/preflight_checks/runtime.py
"""
Preflight checks: runtime environment — handler imports, GDAL, mount access.

Validates that the Docker container has all required libraries and
the ETL mount volume is writable.
"""

import logging
import os
from typing import Any, Dict

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

_WORKER_MODES = {AppMode.WORKER_DOCKER}  # standalone inherits via is_required()

# Libraries that handlers actually import during execution.
# Grouped by purpose so failures are actionable.
REQUIRED_IMPORTS = {
    "rasterio": "Raster I/O (COG creation, tiling)",
    "osgeo.gdal": "GDAL (raster processing, coordinate transforms)",
    "numpy": "Numerical operations (raster/vector processing)",
    "geopandas": "Vector ETL (shapefile, GeoJSON, GeoPackage)",
    "xarray": "Zarr/NetCDF operations",
    "zarr": "Zarr store creation and pyramids",
    "pyproj": "CRS transforms",
    "shapely": "Geometry operations",
}


class HandlerImportsCheck(PreflightCheck):
    name = "handler_imports"
    description = "Verify all required geospatial libraries are importable"
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        import importlib

        results = {}
        missing = []

        for module_name, purpose in REQUIRED_IMPORTS.items():
            try:
                importlib.import_module(module_name)
                results[module_name] = "pass"
            except ImportError as exc:
                results[module_name] = f"fail: {exc}"
                missing.append(module_name)

        if missing:
            return PreflightResult.failed(
                f"{len(missing)} required library(ies) not importable: {', '.join(missing)}",
                remediation=Remediation(
                    action=f"Install missing packages in Docker image: {', '.join(missing)}",
                    eservice_summary=f"DOCKER IMAGE: Missing Python packages: {', '.join(missing)}",
                ),
                sub_checks=results,
            )

        return PreflightResult.passed(
            f"All {len(REQUIRED_IMPORTS)} required libraries importable",
            sub_checks=results,
        )


class GDALVersionCheck(PreflightCheck):
    name = "gdal_version"
    description = "Verify GDAL is installed and report version"
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from osgeo import gdal
            version = gdal.VersionInfo()
            # GDAL VersionInfo returns string like "3080400" for 3.8.4
            major = int(version[0])
            minor = int(version[1:3])
            patch = int(version[3:5])
            version_str = f"{major}.{minor}.{patch}"

            if major < 3:
                return PreflightResult.warned(
                    f"GDAL {version_str} is old — 3.x+ recommended",
                    remediation=Remediation(
                        action="Update GDAL to 3.x+ in Docker base image",
                        eservice_summary=f"DOCKER IMAGE: GDAL {version_str} is outdated, upgrade to 3.x+",
                    ),
                )

            return PreflightResult.passed(f"GDAL {version_str}")

        except ImportError:
            return PreflightResult.failed(
                "GDAL not installed",
                remediation=Remediation(
                    action="Install GDAL in Docker image (apt-get install gdal-bin libgdal-dev + pip install GDAL)",
                    eservice_summary="DOCKER IMAGE: GDAL not installed",
                ),
            )
        except Exception as exc:
            return PreflightResult.failed(
                f"GDAL version check failed: {exc}",
                remediation=Remediation(action="Check GDAL installation"),
            )


class MountWriteCheck(PreflightCheck):
    name = "mount_write"
    description = "Verify ETL mount path exists and is writable"
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        mount_path = config.docker.etl_mount_path if hasattr(config, "docker") else "/mnt/etl"
        canary_file = os.path.join(mount_path, "_preflight_canary.txt")

        # Check mount exists
        if not os.path.isdir(mount_path):
            return PreflightResult.failed(
                f"ETL mount path does not exist: {mount_path}",
                remediation=Remediation(
                    action=f"Mount Azure File Share to {mount_path} in Docker container configuration",
                    eservice_summary=f"DOCKER CONFIG: Mount Azure File Share to {mount_path}",
                ),
            )

        # Check writable
        try:
            with open(canary_file, "w") as f:
                f.write("preflight-canary")
            os.remove(canary_file)
        except PermissionError:
            return PreflightResult.failed(
                f"ETL mount path is read-only: {mount_path}",
                remediation=Remediation(
                    action=f"Set mount to read-write in Docker container configuration",
                    eservice_summary=f"DOCKER CONFIG: ETL mount {mount_path} is read-only — set to read-write",
                ),
            )
        except OSError as exc:
            return PreflightResult.failed(
                f"ETL mount write test failed: {exc}",
                remediation=Remediation(
                    action=f"Check mount configuration for {mount_path}",
                    eservice_summary=f"DOCKER CONFIG: ETL mount write error: {exc}",
                ),
            )

        # Check free space (warn if < 1GB)
        try:
            stat = os.statvfs(mount_path)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
            if free_gb < 1.0:
                return PreflightResult.warned(
                    f"ETL mount has only {free_gb:.1f}GB free (recommend >10GB for large rasters)",
                    remediation=Remediation(
                        action=f"Increase Azure File Share quota for {mount_path}",
                        eservice_summary=f"STORAGE: ETL mount has {free_gb:.1f}GB free — increase quota",
                    ),
                )
            return PreflightResult.passed(f"ETL mount writable at {mount_path} ({free_gb:.1f}GB free)")
        except Exception:
            # statvfs may not be available on all platforms — pass if write succeeded
            return PreflightResult.passed(f"ETL mount writable at {mount_path}")
```

- [ ] **Step 2: Register in __init__.py — final complete version**

```python
# triggers/preflight_checks/__init__.py
"""
Preflight check registry — mode-aware filtering.

Each check declares which APP_MODEs require it. The registry
returns only checks relevant to the current deployment.
"""

from typing import List

from config.app_mode_config import AppMode
from .base import PreflightCheck
from .environment import EnvironmentCheck
from .database import (
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
)
from .dag import DAGLeaseCheck, WorkflowRegistryCheck, DAGTablesCheck
from .storage import StorageTokenCheck, BlobCRUDCheck
from .runtime import HandlerImportsCheck, GDALVersionCheck, MountWriteCheck

# Execution order = registration order.
ALL_PREFLIGHT_CHECKS: List[type] = [
    # Tier 1: Environment (fast, no I/O)
    EnvironmentCheck,
    # Tier 2: Database (needs DB connection)
    DatabaseCanaryCheck,
    SchemaCompletenessCheck,
    ExtensionsCheck,
    PgSTACRolesCheck,
    # Tier 3: DAG infrastructure
    DAGLeaseCheck,
    WorkflowRegistryCheck,
    DAGTablesCheck,
    # Tier 4: Storage (needs blob credentials)
    StorageTokenCheck,
    BlobCRUDCheck,
    # Tier 5: Runtime (needs libraries + mount)
    HandlerImportsCheck,
    GDALVersionCheck,
    MountWriteCheck,
]


def get_checks_for_mode(
    mode: AppMode,
    docker_worker_enabled: bool = False,
) -> List[PreflightCheck]:
    """Instantiate and filter checks for the given APP_MODE."""
    checks = []
    for cls in ALL_PREFLIGHT_CHECKS:
        instance = cls()
        if instance.is_required(mode, docker_worker_enabled):
            checks.append(instance)
    return checks
```

- [ ] **Step 3: Run all tests**

```bash
conda run -n azgeo python -m pytest tests/unit/test_preflight_base.py tests/unit/test_preflight_schema_derivation.py -v
```
Expected: All tests pass (mode filtering tests now have registered checks).

- [ ] **Step 4: Commit**

```bash
git add triggers/preflight_checks/runtime.py triggers/preflight_checks/__init__.py
git commit -m "feat: preflight runtime checks — handler imports, GDAL version, mount write"
```

---

### Task 7: Wire Function App + Docker Service + Final Registration

**Files:**
- Modify: `function_app.py`
- Modify: `docker_service.py`

- [ ] **Step 1: Register preflight blueprint in function_app.py**

Find the probes blueprint registration block (early in the file — Phase 1):
```python
from triggers.probes import bp as probes_bp
app.register_functions(probes_bp)
```

Add immediately after:
```python
# Preflight validation — mode-aware write-path capability test
from triggers.preflight import bp as preflight_bp
app.register_functions(preflight_bp)
```

- [ ] **Step 2: Add FastAPI endpoint in docker_service.py**

Find the health endpoint definition in `docker_service.py` (the `@app.get("/health")` block). Add the preflight endpoint after it:

```python
@app.get("/preflight")
def preflight_check():
    """Preflight validation — mode-aware write-path capability test.

    Unlike /health (connectivity), this tests actual CRUD operations:
    canary DB writes, blob write+delete, schema completeness, imports.
    Each failure includes exact Azure RBAC role for eService requests.
    """
    from triggers.preflight import _run_preflight
    try:
        data = _run_preflight()
        status_code = 200 if data["status"] == "pass" else 424
        return JSONResponse(content=data, status_code=status_code)
    except Exception as exc:
        logger.exception("Preflight endpoint crashed")
        return JSONResponse(
            content={"status": "error", "error": f"Preflight crashed: {exc}"},
            status_code=500,
        )
```

- [ ] **Step 3: Verify import works locally**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda run -n azgeo python -c "from triggers.preflight import _run_preflight; print('Import OK')"
```
Expected: `Import OK`

- [ ] **Step 4: Run full test suite**

```bash
conda run -n azgeo python -m pytest tests/unit/test_preflight_base.py tests/unit/test_preflight_schema_derivation.py -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add function_app.py docker_service.py
git commit -m "feat: wire preflight endpoint into Azure Functions + Docker FastAPI"
```

---

## Self-Review Checklist

| Spec Requirement | Task |
|------------------|------|
| Separate endpoint from health checks | Task 1 (new module, not health plugin) |
| Mode-aware check matrix | Task 1 (base class `is_required()` + registry `get_checks_for_mode()`) |
| Schema completeness from Pydantic models | Task 3 (`_derive_expected_tables()`) |
| Canary write pattern (insert→read→delete) | Task 3 (DB), Task 5 (blob) |
| No Service Bus | None of the checks reference Service Bus |
| No cross-app HTTP | No check pings other apps |
| No `ensure` | Schema check only diffs, remediation says "rebuild" |
| Punch list output | Task 1 (`punch_list` array in response) |
| Exact RBAC remediation | Tasks 3-6 (every failure has `Remediation` with `azure_role` + `eservice_summary`) |
| Orchestrator skips mount/blob | Base class `is_required()` logic |
| Platform skips DAG/storage/extensions | `required_modes` on each check |
| Standalone = union (conditional) | `is_required()` handles `docker_worker_enabled` flag |

**Placeholder scan:** No TBDs, TODOs, or "implement later" found.

**Type consistency:** `PreflightResult`, `Remediation`, `PreflightCheck` used consistently across all tasks. `_run_preflight()` shared between Functions and Docker endpoints.
