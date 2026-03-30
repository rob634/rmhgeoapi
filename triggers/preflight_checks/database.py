# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT CHECK: DATABASE WRITE-PATH
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Preflight check - database canary, schema completeness, extensions
# PURPOSE: Validate database write-path capabilities and schema alignment
#          with Pydantic model registry
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: DatabaseCanaryCheck, SchemaCompletenessCheck, ExtensionsCheck,
#          PgSTACRolesCheck, _derive_expected_tables, _derive_expected_enums
# DEPENDENCIES: psycopg, config, core.models, core.schema.sql_generator
# ============================================================================
"""
Preflight checks: database write-path validation.

Four checks:
1. DatabaseCanaryCheck   — INSERT/SELECT/DELETE round-trip (all modes)
2. SchemaCompletenessCheck — tables + enums vs Pydantic model registry
3. ExtensionsCheck       — postgis, h3
4. PgSTACRolesCheck      — pgstac_admin, pgstac_ingest, pgstac_read
"""

import inspect
import logging
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Set

import psycopg
from psycopg import sql
from pydantic import BaseModel

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

# ============================================================================
# Mode sets
# ============================================================================

_ALL_MODES = {
    AppMode.STANDALONE,
    AppMode.PLATFORM,
    AppMode.ORCHESTRATOR,
    AppMode.WORKER_DOCKER,
}

_NON_PLATFORM = {
    AppMode.STANDALONE,
    AppMode.ORCHESTRATOR,
    AppMode.WORKER_DOCKER,
}

# ============================================================================
# Legacy model -> table name map (pre-V0.8 models without __sql_table_name)
# ============================================================================

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

# ETL tracking models -- live in app schema but have __sql_table_name
# (included here as fallback for column derivation convenience)
_ETL_TRACKING_MODELS: Dict[str, str] = {
    "VectorEtlTracking": "vector_etl_tracking",
    "RasterEtlTracking": "raster_etl_tracking",
    "RasterRenderConfig": "raster_render_configs",
}

# Geo schema model names (have __sql_table_name with schema="geo")
_GEO_MODEL_NAMES = frozenset([
    "GeoTableCatalog",
    "FeatureCollectionStyles",
    "B2CRoute",
    "B2BRoute",
])


# ============================================================================
# Helper: derive expected tables from Pydantic model registry
# ============================================================================

def _derive_expected_tables() -> Dict[str, Dict[str, Any]]:
    """Derive expected database tables from the Pydantic model registry.

    Returns dict keyed by "schema.table_name" with value:
        {"schema": str, "table": str, "columns": [str]}

    Strategy:
        1. Try PydanticToSQL.get_model_sql_metadata(model) for each model class.
           Models with __sql_table_name + __sql_schema are picked up automatically.
        2. Legacy models (pre-V0.8) lack those ClassVars -- fall back to _LEGACY_TABLE_MAP.
        3. Columns come from model.model_fields.keys() in both cases.
    """
    import core.models as models_pkg
    from core.schema.sql_generator import PydanticToSQL

    result: Dict[str, Dict[str, Any]] = {}
    seen_classes: set = set()

    for attr_name in dir(models_pkg):
        obj = getattr(models_pkg, attr_name)

        # Only look at classes
        if not inspect.isclass(obj):
            continue

        # Only Pydantic BaseModel subclasses (skip Enum, str, etc.)
        if not issubclass(obj, BaseModel):
            continue

        # Skip abstract BaseModel itself
        if obj is BaseModel:
            continue

        class_name = obj.__name__

        # Avoid processing the same class twice (aliased imports)
        if class_name in seen_classes:
            continue
        seen_classes.add(class_name)

        # ---- Strategy 1: model-driven metadata ----
        try:
            meta = PydanticToSQL.get_model_sql_metadata(obj)
            table_name = meta["table_name"]
            schema = meta["schema"]
            columns = list(obj.model_fields.keys())
            key = f"{schema}.{table_name}"
            result[key] = {"schema": schema, "table": table_name, "columns": columns}
            continue
        except (ValueError, AttributeError):
            pass  # No __sql_table_name -- try legacy map

        # ---- Strategy 2: legacy map ----
        if class_name in _LEGACY_TABLE_MAP:
            table_name = _LEGACY_TABLE_MAP[class_name]
            # Legacy models default to app schema
            schema = "app"
            columns = list(obj.model_fields.keys())
            key = f"{schema}.{table_name}"
            result[key] = {"schema": schema, "table": table_name, "columns": columns}
            continue

        # ---- Strategy 3: ETL tracking models ----
        if class_name in _ETL_TRACKING_MODELS:
            table_name = _ETL_TRACKING_MODELS[class_name]
            schema = "app"
            columns = list(obj.model_fields.keys())
            key = f"{schema}.{table_name}"
            result[key] = {"schema": schema, "table": table_name, "columns": columns}
            continue

        # Not a table-backed model (e.g. TaskResult, SpatialExtent) -- skip

    return result


# ============================================================================
# Helper: derive expected enum types from Pydantic model registry
# ============================================================================

def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _derive_expected_enums() -> Set[str]:
    """Derive expected PostgreSQL enum type names from the model registry.

    Iterates core.models for Enum subclasses and converts CamelCase names
    to snake_case to match the PostgreSQL type naming convention used by
    PydanticToSQL.generate_enum().

    Returns set of expected enum type names (e.g. "job_status", "approval_state").
    """
    import core.models as models_pkg

    enums: Set[str] = set()
    seen: set = set()

    for attr_name in dir(models_pkg):
        obj = getattr(models_pkg, attr_name)

        if not inspect.isclass(obj):
            continue
        if not issubclass(obj, Enum):
            continue
        if obj is Enum:
            continue

        class_name = obj.__name__
        if class_name in seen:
            continue
        seen.add(class_name)

        enums.add(_camel_to_snake(class_name))

    return enums


# ============================================================================
# Check 1: Database canary — INSERT/SELECT/DELETE round-trip
# ============================================================================

class DatabaseCanaryCheck(PreflightCheck):
    """Write-path canary: INSERT/SELECT/DELETE round-trip against app.api_requests."""

    name = "database_canary"
    description = "INSERT/SELECT/DELETE round-trip to verify database write permissions"
    required_modes = _ALL_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository(config=config)
            schema = config.database.app_schema

            canary_id = f"preflight-canary-{uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc).isoformat()

            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    # INSERT
                    cur.execute(
                        sql.SQL(
                            "INSERT INTO {schema}.api_requests "
                            "(request_id, endpoint, method, timestamp) "
                            "VALUES (%s, %s, %s, %s)"
                        ).format(schema=sql.Identifier(schema)),
                        (canary_id, "/preflight/canary", "PREFLIGHT", now),
                    )

                    # SELECT back
                    cur.execute(
                        sql.SQL(
                            "SELECT request_id FROM {schema}.api_requests "
                            "WHERE request_id = %s"
                        ).format(schema=sql.Identifier(schema)),
                        (canary_id,),
                    )
                    row = cur.fetchone()

                    # DELETE
                    cur.execute(
                        sql.SQL(
                            "DELETE FROM {schema}.api_requests "
                            "WHERE request_id = %s"
                        ).format(schema=sql.Identifier(schema)),
                        (canary_id,),
                    )
                    # R68-B5: verify DELETE actually removed the row
                    if cur.rowcount != 1:
                        conn.commit()
                        return PreflightResult.failed(
                            "Canary DELETE affected 0 rows — possible row-level security blocking deletes",
                            remediation=Remediation(
                                action="Check DELETE permissions on app.api_requests for managed identity",
                            ),
                        )

                conn.commit()

            if row is None:
                return PreflightResult.failed(
                    "Canary INSERT succeeded but SELECT returned no rows",
                    remediation=Remediation(
                        action="Investigate row-level security or replication lag",
                    ),
                )

            # R68-A7: don't leak canary ID in response
            return PreflightResult.passed(
                "INSERT/SELECT/DELETE round-trip succeeded on api_requests"
            )

        except psycopg.errors.InsufficientPrivilege as exc:
            return PreflightResult.failed(
                f"Permission denied: {exc}",
                remediation=Remediation(
                    action="Grant INSERT/SELECT/DELETE on app schema tables to the app identity",
                    azure_role="Database contributor or custom role with DML grants",
                    eservice_summary=(
                        "DB GRANT: The managed identity needs INSERT/SELECT/DELETE "
                        "on the app schema. Run: GRANT INSERT, SELECT, DELETE ON ALL "
                        "TABLES IN SCHEMA app TO <identity>;"
                    ),
                ),
            )
        except psycopg.errors.UndefinedTable as exc:
            return PreflightResult.failed(
                f"Table does not exist: {exc}",
                remediation=Remediation(
                    action="Run schema rebuild to create missing tables",
                    eservice_summary=(
                        "DB SCHEMA: app.api_requests table missing. "
                        "Run: POST /api/dbadmin/maintenance?action=ensure&confirm=yes"
                    ),
                ),
            )
        except Exception as exc:
            logger.warning("DatabaseCanaryCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"Database canary failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check database connectivity and credentials",
                ),
            )


# ============================================================================
# Check 2: Schema completeness — tables + enums vs Pydantic registry
# ============================================================================

class SchemaCompletenessCheck(PreflightCheck):
    """Verify all Pydantic-derived tables and enums exist in the database."""

    name = "schema_completeness"
    description = "Compare database tables/enums against Pydantic model registry"
    required_modes = _NON_PLATFORM

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository(config=config)

            # --- Derive expected ---
            expected_tables = _derive_expected_tables()
            expected_enums = _derive_expected_enums()

            # --- Query actual tables ---
            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            "SELECT table_schema, table_name "
                            "FROM information_schema.tables "
                            "WHERE table_schema = ANY(%s) "
                            "AND table_type = 'BASE TABLE'"
                        ),
                        ([config.database.app_schema, "geo"],),
                    )
                    actual_tables = {
                        f"{r['table_schema']}.{r['table_name']}" for r in cur.fetchall()
                    }

                    # --- Query actual enum types ---
                    cur.execute(
                        sql.SQL(
                            "SELECT t.typname "
                            "FROM pg_type t "
                            "JOIN pg_namespace n ON t.typnamespace = n.oid "
                            "WHERE n.nspname = %s "
                            "AND t.typtype = 'e'"
                        ),
                        (config.database.app_schema,),
                    )
                    actual_enums = {r["typname"] for r in cur.fetchall()}

            # --- Compare ---
            missing_tables = sorted(set(expected_tables.keys()) - actual_tables)
            missing_enums = sorted(expected_enums - actual_enums)

            sub_checks: Dict[str, Any] = {
                "expected_tables": len(expected_tables),
                "actual_tables": len(actual_tables),
                "missing_tables": missing_tables,
                "expected_enums": len(expected_enums),
                "actual_enums": len(actual_enums),
                "missing_enums": missing_enums,
            }

            if missing_tables or missing_enums:
                parts = []
                if missing_tables:
                    parts.append(f"{len(missing_tables)} missing table(s): {', '.join(missing_tables)}")
                if missing_enums:
                    parts.append(f"{len(missing_enums)} missing enum(s): {', '.join(missing_enums)}")
                detail = "; ".join(parts)

                return PreflightResult.failed(
                    detail,
                    remediation=Remediation(
                        action="Run schema ensure to create missing objects",
                        eservice_summary=(
                            "DB SCHEMA: Missing tables/enums. "
                            "Run: POST /api/dbadmin/maintenance?action=ensure&confirm=yes"
                        ),
                    ),
                    sub_checks=sub_checks,
                )

            return PreflightResult.passed(
                f"All {len(expected_tables)} tables and {len(expected_enums)} enums present",
                sub_checks=sub_checks,
            )

        except Exception as exc:
            logger.warning("SchemaCompletenessCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"Schema completeness check failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check database connectivity and credentials",
                ),
            )


# ============================================================================
# Check 3: Required PostgreSQL extensions
# ============================================================================

class ExtensionsCheck(PreflightCheck):
    """Verify required PostgreSQL extensions are installed."""

    name = "pg_extensions"
    description = "Check for required PostgreSQL extensions (postgis, h3)"
    required_modes = _NON_PLATFORM

    _REQUIRED_EXTENSIONS = ["postgis", "h3"]

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository(config=config)

            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SELECT extname FROM pg_extension")
                    )
                    installed = {r["extname"] for r in cur.fetchall()}

            missing = [ext for ext in self._REQUIRED_EXTENSIONS if ext not in installed]

            if missing:
                commands = [f"CREATE EXTENSION IF NOT EXISTS {ext};" for ext in missing]
                return PreflightResult.failed(
                    f"Missing PostgreSQL extension(s): {', '.join(missing)}",
                    remediation=Remediation(
                        action=f"Install missing extensions: {' '.join(commands)}",
                        eservice_summary=(
                            f"DB EXTENSION: Missing {', '.join(missing)}. "
                            f"Requires server-level admin to run: {' '.join(commands)}"
                        ),
                    ),
                )

            return PreflightResult.passed(
                f"All required extensions installed: {', '.join(self._REQUIRED_EXTENSIONS)}"
            )

        except Exception as exc:
            logger.warning("ExtensionsCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"Extensions check failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check database connectivity and credentials",
                ),
            )


# ============================================================================
# Check 4: pgSTAC roles
# ============================================================================

class PgSTACRolesCheck(PreflightCheck):
    """Verify pgSTAC roles exist in the database."""

    name = "pgstac_roles"
    description = "Check for required pgSTAC roles (pgstac_admin, pgstac_ingest, pgstac_read)"
    required_modes = _NON_PLATFORM

    _REQUIRED_ROLES = ["pgstac_admin", "pgstac_ingest", "pgstac_read"]

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository(config=config)

            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)"),
                        (self._REQUIRED_ROLES,),
                    )
                    existing = {r["rolname"] for r in cur.fetchall()}

            missing = [role for role in self._REQUIRED_ROLES if role not in existing]

            if missing:
                commands = [f"CREATE ROLE {role};" for role in missing]
                return PreflightResult.failed(
                    f"Missing pgSTAC role(s): {', '.join(missing)}",
                    remediation=Remediation(
                        action=f"Create missing roles: {' '.join(commands)}",
                        eservice_summary=(
                            f"DB ROLE: Missing {', '.join(missing)}. "
                            f"Run pgSTAC bootstrap or create manually: {' '.join(commands)}"
                        ),
                    ),
                )

            return PreflightResult.passed(
                f"All required pgSTAC roles exist: {', '.join(self._REQUIRED_ROLES)}"
            )

        except Exception as exc:
            logger.warning("PgSTACRolesCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"pgSTAC roles check failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check database connectivity and credentials",
                ),
            )
