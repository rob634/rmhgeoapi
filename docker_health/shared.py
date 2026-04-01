# ============================================================================
# DOCKER HEALTH - Shared Infrastructure Subsystem
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Subsystem - Database, Storage, Task Polling, Config, Schema, Connectivity
# PURPOSE: Health checks for Docker Worker shared infrastructure
# CREATED: 29 JAN 2026
# LAST_REVIEWED: 24 MAR 2026
# EXPORTS: SharedInfrastructureSubsystem
# DEPENDENCIES: base.WorkerSubsystem, config, psycopg, httpx
# ============================================================================
"""
Shared Infrastructure Health Subsystem.

Monitors infrastructure components used by the Docker Worker:
- database: PostgreSQL connectivity and authentication
- storage_containers: Azure Blob Storage access
- task_polling: DB-polling queue worker status
- config_checklist: Required and optional environment variable presence
- schema_validation: Critical app schema tables and enums
- outbound_connectivity: TiTiler reachability

These checks run once and are shared across all worker types.

15 MAR 2026: Replaced Service Bus health check with task polling check.
Docker worker now claims tasks via PostgreSQL SKIP LOCKED instead of SB.
24 MAR 2026: Added config checklist, schema validation, TiTiler connectivity.
"""

from typing import Dict, Any

from .base import WorkerSubsystem


class SharedInfrastructureSubsystem(WorkerSubsystem):
    """
    Health checks for shared infrastructure components.

    Components:
    - database: PostgreSQL connection and version
    - storage_containers: Azure Blob Storage access
    - task_polling: DB-polling task worker status
    """

    name = "shared_infrastructure"
    description = "Database, Storage, and Task Polling (shared by all workers)"
    priority = 10  # Run first - other subsystems depend on these

    def __init__(self, queue_worker=None):
        """
        Initialize with optional queue worker reference.

        Args:
            queue_worker: BackgroundQueueWorker for service bus status
        """
        self.queue_worker = queue_worker

    def is_enabled(self) -> bool:
        """Shared infrastructure checks are always enabled."""
        return True

    def get_health(self) -> Dict[str, Any]:
        """Return health status for shared infrastructure."""
        components = {}
        errors = []

        # Check database
        db_result = self._check_database()
        components["database"] = db_result
        if db_result["status"] == "unhealthy":
            errors.append(db_result.get("details", {}).get("error", "Database unhealthy"))

        # Check storage
        storage_result = self._check_storage()
        components["storage_containers"] = storage_result
        if storage_result["status"] == "unhealthy":
            errors.append(storage_result.get("details", {}).get("error", "Storage unhealthy"))

        # Check task polling (DB-based) — worker mode only
        # Orchestrator passes queue_worker=None (it uses janitor/scheduler instead)
        if self.queue_worker is not None:
            poll_result = self._check_task_polling()
            components["task_polling"] = poll_result
            if poll_result["status"] == "unhealthy":
                errors.append("Task polling unhealthy")

        # Check configuration (Azure env vars via env_validation framework)
        config_result = self._check_config_checklist()
        components["config_checklist"] = config_result
        if config_result["status"] == "unhealthy":
            details = config_result.get("details", {})
            error_count = details.get("error_count", 0)
            missing = details.get("required_vars", {}).get("missing", [])
            if missing:
                errors.append(f"Missing required config: {', '.join(missing)}")
            elif error_count > 0:
                errors.append(f"{error_count} env var validation error(s) — check config_checklist details")

        # Check schema (tables + enums)
        schema_result = self._check_schema_validation()
        components["schema_validation"] = schema_result
        if schema_result["status"] == "unhealthy":
            errors.append("Database schema validation failed — run action=ensure")

        # Check outbound connectivity (TiTiler)
        outbound_result = self._check_outbound_connectivity()
        components["outbound_connectivity"] = outbound_result
        if outbound_result["status"] == "unhealthy":
            errors.append("Outbound connectivity check failed")

        return {
            "status": self.compute_status(components),
            "components": components,
            "errors": errors if errors else None,
        }

    def _check_database(self) -> Dict[str, Any]:
        """Check PostgreSQL connectivity."""
        from config import get_config

        config = get_config()

        try:
            # Use the docker_service connectivity test
            db_status = self._test_database_connectivity()
            db_connected = db_status.get("connected", False)

            return self.build_component(
                status="healthy" if db_connected else "unhealthy",
                description="PostgreSQL connection",
                source="function_app",  # Shared but owned by Function App
                details={
                    "host": config.database.host,
                    "database": db_status.get("database", config.database.database),
                    "user": db_status.get("user", "N/A"),
                    "version": db_status.get("version", "N/A"),
                    "managed_identity": config.database.use_managed_identity,
                    "error": db_status.get("error") if not db_connected else None,
                }
            )
        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="PostgreSQL connection",
                source="function_app",
                details={"error": str(e)}
            )

    def _check_storage(self) -> Dict[str, Any]:
        """Check Azure Blob Storage connectivity."""
        from config import get_config

        config = get_config()

        try:
            storage_status = self._test_storage_connectivity()
            storage_connected = storage_status.get("connected", False)

            return self.build_component(
                status="healthy" if storage_connected else "unhealthy",
                description="Azure Blob Storage (Silver zone)",
                source="function_app",  # Shared but owned by Function App
                details={
                    "account": storage_status.get("account", config.storage.silver.account_name),
                    "containers_accessible": storage_status.get("containers_accessible", False),
                    "error": storage_status.get("error") if not storage_connected else None,
                }
            )
        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="Azure Blob Storage (Silver zone)",
                source="function_app",
                details={"error": str(e)}
            )

    def _check_task_polling(self) -> Dict[str, Any]:
        """Check DB-polling task worker status with staleness detection."""
        queue_running = False
        poll_age_seconds = None

        if self.queue_worker:
            queue_status = self.queue_worker.get_status()
            queue_running = queue_status.get("running", False)
            last_poll = queue_status.get("last_poll_time")
            if last_poll:
                from datetime import datetime, timezone
                if isinstance(last_poll, str):
                    last_poll = datetime.fromisoformat(last_poll)
                poll_age_seconds = round(
                    (datetime.now(timezone.utc) - last_poll).total_seconds()
                )

        # Staleness-aware status — consistent with Brain's scan_age_seconds
        if queue_running and poll_age_seconds is not None and poll_age_seconds > 300:
            status = "unhealthy"
        elif queue_running:
            status = "healthy"
        else:
            status = "warning"

        return self.build_component(
            status=status,
            description="PostgreSQL SKIP LOCKED task polling",
            source="docker_worker",
            details={
                "mode": "db_polling",
                "worker_running": queue_running,
                "poll_age_seconds": poll_age_seconds,
            }
        )

    def _check_config_checklist(self) -> Dict[str, Any]:
        """
        Check environment variable configuration using the env_validation framework.

        Uses config.env_validation.get_validation_summary() which validates:
        - Required vars are present (not just set, but non-empty)
        - Format validation via regex (e.g., storage accounts must be lowercase alphanumeric)
        - Catches placeholder values like "your-storage-account-name"
        - Warns on optional vars using defaults
        """
        try:
            from config.env_validation import get_validation_summary

            summary = get_validation_summary(include_warnings=True)

            if not summary["valid"]:
                status = "unhealthy"
            elif summary["warning_count"] > 0:
                status = "warning"
            else:
                status = "healthy"

            return self.build_component(
                status=status,
                description="Environment variable configuration",
                source="docker_worker",
                details=summary,
            )
        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="Environment variable configuration",
                source="docker_worker",
                details={"error": str(e)},
            )

    def _check_schema_validation(self) -> Dict[str, Any]:
        """Check that critical app schema tables and enums exist in PostgreSQL."""
        required_tables = [
            "jobs",
            "tasks",
            "workflow_runs",
            "workflow_tasks",
            "workflow_task_deps",
            "schedules",
            "scheduled_datasets",
            "api_requests",
            "assets",
            "asset_releases",
        ]
        required_enums = [
            "job_status",
            "task_status",
            "schedule_status",
            "approval_state",
            "clearance_state",
        ]

        try:
            from infrastructure.db_auth import ManagedIdentityAuth
            from infrastructure.db_connections import ConnectionManager
            from psycopg.rows import dict_row
            from config import get_config

            app_schema = get_config().database.app_schema

            cm = ConnectionManager(ManagedIdentityAuth())
            with cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    # Check tables
                    cur.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = %s
                          AND table_type = 'BASE TABLE'
                        """,
                        (app_schema,)
                    )
                    existing_tables = {row["table_name"] for row in cur.fetchall()}

                    # Check enums
                    cur.execute(
                        """
                        SELECT typname
                        FROM pg_type
                        JOIN pg_namespace ON pg_namespace.oid = pg_type.typnamespace
                        WHERE typtype = 'e'
                          AND nspname = %s
                        """,
                        (app_schema,)
                    )
                    existing_enums = {row["typname"] for row in cur.fetchall()}

            missing_tables = [t for t in required_tables if t not in existing_tables]
            missing_enums = [e for e in required_enums if e not in existing_enums]

            status = "unhealthy" if (missing_tables or missing_enums) else "healthy"

            return self.build_component(
                status=status,
                description=f"App schema '{app_schema}' tables and enums",
                source="docker_worker",
                details={
                    "schema": app_schema,
                    "tables_checked": len(required_tables),
                    "enums_checked": len(required_enums),
                    "missing_tables": missing_tables,
                    "missing_enums": missing_enums,
                }
            )

        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="App schema tables and enums",
                source="docker_worker",
                details={"error": str(e)[:300]}
            )

    def _check_outbound_connectivity(self) -> Dict[str, Any]:
        """Probe TiTiler /livez to verify outbound connectivity."""
        from config import get_config

        titiler_base_url = (get_config().titiler_base_url or "").rstrip("/")

        if not titiler_base_url:
            return self.build_component(
                status="warning",
                description="Outbound connectivity — TiTiler",
                source="docker_worker",
                details={"message": "TITILER_BASE_URL not configured — skipping probe"}
            )

        probe_url = f"{titiler_base_url}/livez"

        try:
            import httpx

            with httpx.Client(timeout=10.0) as client:
                response = client.get(probe_url)

            reachable = response.status_code == 200

            return self.build_component(
                status="healthy" if reachable else "warning",
                description="Outbound connectivity — TiTiler",
                source="docker_worker",
                details={
                    "url": probe_url,
                    "status_code": response.status_code,
                    "reachable": reachable,
                }
            )

        except Exception as e:
            return self.build_component(
                status="warning",
                description="Outbound connectivity — TiTiler",
                source="docker_worker",
                details={
                    "url": probe_url,
                    "reachable": False,
                    "error": str(e)[:200],
                }
            )

    def _test_database_connectivity(self) -> dict:
        """
        Test PostgreSQL connectivity using ConnectionPoolManager.

        Uses the shared connection pool instead of creating a raw connection,
        which avoids redundant authentication and connection setup (C7.6).

        Returns:
            Dict with connection status, version, user, database
        """
        try:
            from infrastructure.connection_pool import ConnectionPoolManager

            with ConnectionPoolManager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version(), current_user, current_database()")
                    row = cur.fetchone()
                    # dict_row returns a dict; fall back to tuple indexing
                    if isinstance(row, dict):
                        version = row.get("version", "")
                        user = row.get("current_user", "")
                        database = row.get("current_database", "")
                    else:
                        version, user, database = row

            return {
                "connected": True,
                "version": version.split(",")[0] if version else "Unknown",
                "user": user,
                "database": database,
            }

        except Exception as e:
            return {
                "connected": False,
                "error": str(e)[:200],
            }

    def _test_storage_connectivity(self) -> dict:
        """
        Test Azure Blob Storage connectivity.

        Returns:
            Dict with connection status and account info
        """
        try:
            from azure.storage.blob import BlobServiceClient
            from azure.identity import DefaultAzureCredential
            from config import get_config

            config = get_config()

            account_url = f"https://{config.storage.silver.account_name}.blob.core.windows.net"
            credential = DefaultAzureCredential()

            blob_service = BlobServiceClient(
                account_url=account_url,
                credential=credential,
            )

            # Try to list containers (get first one to verify access)
            # Use results_per_page for SDK compatibility
            container_iter = blob_service.list_containers(results_per_page=1)
            first_page = next(container_iter.by_page(), [])
            containers_found = len(list(first_page))

            return {
                "connected": True,
                "account": config.storage.silver.account_name,
                "containers_accessible": True,  # If we got here, access works
            }

        except Exception as e:
            return {
                "connected": False,
                "error": str(e)[:200],
            }


__all__ = ['SharedInfrastructureSubsystem']
