# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT CHECK: DAG INFRASTRUCTURE
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Preflight check - DAG lease table, workflow registry, DAG tables
# PURPOSE: Validate DAG orchestration infrastructure: lease table access,
#          workflow YAML loading, handler coverage, and DAG schema tables
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: DAGLeaseCheck, WorkflowRegistryCheck, DAGTablesCheck
# DEPENDENCIES: psycopg, config, core.workflow_registry, services
# ============================================================================
"""
Preflight checks: DAG orchestration infrastructure.

Three checks:
1. DAGLeaseCheck          — orchestrator_lease table accessible
2. WorkflowRegistryCheck  — YAML workflows load, all referenced handlers exist
3. DAGTablesCheck         — workflow_runs, workflow_tasks, workflow_task_deps tables exist
"""

import logging
from pathlib import Path

import psycopg
from psycopg import sql

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

# ============================================================================
# Mode sets
# ============================================================================

_ORCHESTRATOR_MODES = {AppMode.STANDALONE, AppMode.ORCHESTRATOR}

_DAG_TABLE_MODES = {AppMode.STANDALONE, AppMode.ORCHESTRATOR, AppMode.WORKER_DOCKER}


# ============================================================================
# Check 1: DAG lease table — verify orchestrator_lease is accessible
# ============================================================================

class DAGLeaseCheck(PreflightCheck):
    """Verify orchestrator_lease table exists and is queryable."""

    name = "dag_lease_table"
    description = "Verify orchestrator_lease table exists and is accessible"
    required_modes = _ORCHESTRATOR_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository(config=config)
            schema = config.database.app_schema

            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            "SELECT COUNT(*) AS cnt FROM {schema}.orchestrator_lease"
                        ).format(schema=sql.Identifier(schema)),
                    )
                    row = cur.fetchone()

            count = row["cnt"] if row else 0
            return PreflightResult.passed(
                f"orchestrator_lease accessible ({count} active lease(s))"
            )

        except psycopg.errors.UndefinedTable as exc:
            return PreflightResult.failed(
                f"orchestrator_lease table does not exist: {exc}",
                remediation=Remediation(
                    action="Run schema rebuild to create DAG tables",
                    eservice_summary=(
                        "DB SCHEMA: app.orchestrator_lease table missing. "
                        "Run: POST /api/dbadmin/maintenance?action=ensure&confirm=yes"
                    ),
                ),
            )
        except Exception as exc:
            logger.warning("DAGLeaseCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"DAG lease check failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check database connectivity and permissions for orchestrator_lease",
                ),
            )


# ============================================================================
# Check 2: Workflow registry — YAML loading + handler coverage
# ============================================================================

class WorkflowRegistryCheck(PreflightCheck):
    """Load all YAML workflows and verify every referenced handler is registered."""

    name = "workflow_registry"
    description = "Load workflow YAMLs and verify all referenced handlers exist in ALL_HANDLERS"
    required_modes = _ORCHESTRATOR_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from services import ALL_HANDLERS
            from core.workflow_registry import WorkflowRegistry
            from core.models.workflow_definition import (
                TaskNode, FanOutNode,
            )

            workflows_dir = Path(__file__).resolve().parent.parent.parent / "workflows"
            handler_names = set(ALL_HANDLERS.keys())

            registry = WorkflowRegistry(
                workflows_dir=workflows_dir,
                handler_names=handler_names,
            )
            workflow_count = registry.load_all()

            if workflow_count == 0:
                return PreflightResult.failed(
                    f"No workflows loaded from {workflows_dir}",
                    remediation=Remediation(
                        action="Ensure YAML workflow files exist in the workflows/ directory",
                    ),
                )

            # Extract all handler names referenced by loaded workflows
            referenced_handlers: set[str] = set()
            for wf_name in registry.list_workflows():
                defn = registry.get(wf_name)
                if defn is None:
                    continue

                for _node_name, node in defn.nodes.items():
                    if hasattr(node, "handler"):
                        referenced_handlers.add(node.handler)
                    if hasattr(node, "task") and hasattr(node.task, "handler"):
                        referenced_handlers.add(node.task.handler)

                if defn.finalize and hasattr(defn.finalize, "handler"):
                    referenced_handlers.add(defn.finalize.handler)

            # Compare against registered handlers
            missing = sorted(referenced_handlers - handler_names)

            sub_checks = {
                "workflows_loaded": workflow_count,
                "handlers_referenced": len(referenced_handlers),
                "handlers_registered": len(handler_names),
                "missing_handlers": missing,
            }

            if missing:
                return PreflightResult.failed(
                    f"{len(missing)} handler(s) referenced in workflows but not registered: "
                    f"{', '.join(missing)}",
                    remediation=Remediation(
                        action="Register missing handlers in services/__init__.py ALL_HANDLERS",
                    ),
                    sub_checks=sub_checks,
                )

            return PreflightResult.passed(
                f"{workflow_count} workflow(s) loaded, "
                f"{len(referenced_handlers)} handler(s) verified",
                sub_checks=sub_checks,
            )

        except Exception as exc:
            logger.warning("WorkflowRegistryCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"Workflow registry check failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check workflow YAML files for syntax or validation errors",
                ),
            )


# ============================================================================
# Check 3: DAG tables — workflow_runs, workflow_tasks, workflow_task_deps
# ============================================================================

class DAGTablesCheck(PreflightCheck):
    """Verify DAG schema tables exist: workflow_runs, workflow_tasks, workflow_task_deps."""

    name = "dag_tables"
    description = "Check for required DAG tables (workflow_runs, workflow_tasks, workflow_task_deps)"
    required_modes = _DAG_TABLE_MODES

    _REQUIRED_TABLES = ["workflow_runs", "workflow_tasks", "workflow_task_deps"]

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository(config=config)
            schema = config.database.app_schema

            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = %s "
                            "AND table_name = ANY(%s) "
                            "AND table_type = 'BASE TABLE'"
                        ),
                        (schema, self._REQUIRED_TABLES),
                    )
                    existing = {r["table_name"] for r in cur.fetchall()}

            missing = [t for t in self._REQUIRED_TABLES if t not in existing]

            if missing:
                return PreflightResult.failed(
                    f"Missing DAG table(s): {', '.join(missing)}",
                    remediation=Remediation(
                        action="Run schema rebuild to create DAG tables",
                        eservice_summary=(
                            f"DB SCHEMA: Missing DAG tables: {', '.join(missing)}. "
                            "Run: POST /api/dbadmin/maintenance?action=ensure&confirm=yes"
                        ),
                    ),
                )

            return PreflightResult.passed(
                f"All {len(self._REQUIRED_TABLES)} DAG tables present: "
                f"{', '.join(self._REQUIRED_TABLES)}"
            )

        except Exception as exc:
            logger.warning("DAGTablesCheck failed: %s", exc, exc_info=True)
            return PreflightResult.failed(
                f"DAG tables check failed: {type(exc).__name__}: {exc}",
                remediation=Remediation(
                    action="Check database connectivity and credentials",
                ),
            )
