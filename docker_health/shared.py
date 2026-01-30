# ============================================================================
# DOCKER HEALTH - Shared Infrastructure Subsystem
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Subsystem - Database, Storage, Service Bus
# PURPOSE: Health checks for infrastructure shared between Classic and DAG workers
# CREATED: 29 JAN 2026
# EXPORTS: SharedInfrastructureSubsystem
# DEPENDENCIES: base.WorkerSubsystem, config, psycopg
# ============================================================================
"""
Shared Infrastructure Health Subsystem.

Monitors infrastructure components used by both Classic and DAG workers:
- database: PostgreSQL connectivity and authentication
- storage_containers: Azure Blob Storage access
- service_bus: Azure Service Bus connectivity

These checks run once and are shared across all worker types.
"""

from typing import Dict, Any

from .base import WorkerSubsystem


class SharedInfrastructureSubsystem(WorkerSubsystem):
    """
    Health checks for shared infrastructure components.

    Components:
    - database: PostgreSQL connection and version
    - storage_containers: Azure Blob Storage access
    - service_bus: Azure Service Bus queue connectivity
    """

    name = "shared_infrastructure"
    description = "Database, Storage, and Service Bus (shared by all workers)"
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

        # Check service bus
        sb_result = self._check_service_bus()
        components["service_bus"] = sb_result
        if sb_result["status"] == "unhealthy":
            errors.append("Service Bus unhealthy")

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

    def _check_service_bus(self) -> Dict[str, Any]:
        """Check Azure Service Bus connectivity."""
        from config import get_config

        config = get_config()

        queue_running = False
        queue_name = "N/A"

        if self.queue_worker:
            queue_status = self.queue_worker.get_status()
            queue_running = queue_status.get("running", False)
            queue_name = queue_status.get("queue_name", "N/A")

        return self.build_component(
            status="healthy" if queue_running else "warning",
            description="Azure Service Bus queues",
            source="function_app",  # Shared but owned by Function App
            details={
                "namespace": config.queues.namespace,
                "long_running_queue": queue_name,
                "worker_connected": queue_running,
            }
        )

    def _test_database_connectivity(self) -> dict:
        """
        Test PostgreSQL connectivity using psycopg.

        Returns:
            Dict with connection status, version, user, database
        """
        try:
            import psycopg
            from infrastructure.auth import get_postgres_token
            from config import get_config

            config = get_config()

            # Get OAuth token for managed identity auth
            token = get_postgres_token()

            conn_params = {
                "host": config.database.host,
                "port": config.database.port,
                "dbname": config.database.database,
                "user": config.database.managed_identity_admin_name,
                "password": token,
                "sslmode": "require",
                "connect_timeout": 10,
            }

            with psycopg.connect(**conn_params) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version(), current_user, current_database()")
                    version, user, database = cur.fetchone()

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

            # Try to list containers (limited)
            containers = list(blob_service.list_containers(max_results=1))

            return {
                "connected": True,
                "account": config.storage.silver.account_name,
                "containers_accessible": len(containers) >= 0,  # Even 0 is success
            }

        except Exception as e:
            return {
                "connected": False,
                "error": str(e)[:200],
            }


__all__ = ['SharedInfrastructureSubsystem']
