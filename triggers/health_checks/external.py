# ============================================================================
# CLAUDE CONTEXT - EXTERNAL ENVIRONMENT HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Health checks for external hosting environment
# PURPOSE: Verify external DB, storage, and TiTiler connectivity
# CREATED: 10 MAR 2026
# EXPORTS: ExternalEnvironmentHealthChecks
# DEPENDENCIES: config, infrastructure.postgresql, requests
# ============================================================================
"""
External Environment Health Check Plugin.

Checks connectivity to the external hosting environment:
- external_database: PostgreSQL connectivity + schema verification
- external_storage: Blob access to external storage account
- external_titiler: HTTP health check on external TiTiler instance

Only enabled when EXTERNAL_DB_HOST or EXTERNAL_DB_NAME is configured.
"""

from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class ExternalEnvironmentHealthChecks(HealthCheckPlugin):
    """Health checks for the external hosting environment (DB + storage + TiTiler)."""

    name = "external_environment"
    description = "External database, storage, and TiTiler health"
    priority = 55  # After external services (50)

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return external environment health checks."""
        return [
            ("external_database", self.check_external_database),
            ("external_storage", self.check_external_storage),
            ("external_titiler", self.check_external_titiler),
        ]

    def is_enabled(self, config) -> bool:
        """Only run when external environment is configured."""
        return config.is_external_configured()

    # =========================================================================
    # CHECK: External Database
    # =========================================================================

    def check_external_database(self) -> Dict[str, Any]:
        """Check external database health — connectivity, schemas, table counts."""
        def check_ext_db():
            import psycopg
            import time
            from config import get_config
            from infrastructure.postgresql import PostgreSQLRepository

            config = get_config()
            start_time = time.time()

            if not config.is_external_configured():
                return {
                    "configured": False,
                    "message": "External database not configured (EXTERNAL_DB_* env vars not set)"
                }

            ext_config = config.external

            try:
                repo = PostgreSQLRepository(
                    config=config,
                    target_database="external"
                )
                conn_str = repo.conn_string
            except Exception as repo_error:
                return {
                    "configured": True,
                    "host": ext_config.db_host,
                    "database": ext_config.db_name,
                    "connected": False,
                    "error": f"Failed to initialize repository: {str(repo_error)[:200]}",
                    "error_type": type(repo_error).__name__
                }

            try:
                with psycopg.connect(conn_str, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        connection_time_ms = round(
                            (time.time() - start_time) * 1000, 2
                        )

                        # PostgreSQL version
                        cur.execute("SELECT version()")
                        pg_version = cur.fetchone()[0].split(',')[0]

                        # PostGIS version
                        try:
                            cur.execute("SELECT PostGIS_Version()")
                            postgis_version = cur.fetchone()[0]
                        except Exception:
                            postgis_version = "not installed"

                        # Geo schema check
                        geo_schema = ext_config.db_schema
                        cur.execute("""
                            SELECT EXISTS(
                                SELECT 1 FROM pg_namespace WHERE nspname = %s
                            ) as schema_exists
                        """, (geo_schema,))
                        geo_schema_exists = cur.fetchone()[0]

                        geo_table_count = 0
                        if geo_schema_exists:
                            cur.execute("""
                                SELECT COUNT(*) FROM information_schema.tables
                                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                            """, (geo_schema,))
                            geo_table_count = cur.fetchone()[0]

                        # pgstac schema check
                        pgstac_schema = ext_config.pgstac_schema
                        cur.execute("""
                            SELECT EXISTS(
                                SELECT 1 FROM pg_namespace WHERE nspname = %s
                            ) as schema_exists
                        """, (pgstac_schema,))
                        pgstac_schema_exists = cur.fetchone()[0]

                        pgstac_version = None
                        if pgstac_schema_exists:
                            try:
                                cur.execute("SELECT pgstac.get_version() as version")
                                pgstac_version = cur.fetchone()[0]
                            except Exception:
                                pgstac_version = "query failed"

                        return {
                            "configured": True,
                            "host": ext_config.db_host,
                            "database": ext_config.db_name,
                            "connected": True,
                            "connection_time_ms": connection_time_ms,
                            "postgres_version": pg_version,
                            "postgis_version": postgis_version,
                            "geo_schema": {
                                "name": geo_schema,
                                "exists": geo_schema_exists,
                                "table_count": geo_table_count,
                            },
                            "pgstac_schema": {
                                "name": pgstac_schema,
                                "exists": pgstac_schema_exists,
                                "version": pgstac_version,
                            },
                            "purpose": "External hosting environment for publicly-cleared data"
                        }

            except Exception as conn_error:
                return {
                    "configured": True,
                    "host": ext_config.db_host,
                    "database": ext_config.db_name,
                    "connected": False,
                    "error": str(conn_error)[:200],
                    "error_type": type(conn_error).__name__
                }

        return self.check_component_health(
            "external_database",
            check_ext_db,
            description="External database for publicly-cleared data"
        )

    # =========================================================================
    # CHECK: External Storage
    # =========================================================================

    def check_external_storage(self) -> Dict[str, Any]:
        """Check external storage account accessibility."""
        def check_ext_storage():
            from config import get_config

            config = get_config()

            if not config.external or not config.external.storage_account:
                return {
                    "configured": False,
                    "message": "External storage not configured (EXTERNAL_STORAGE_ACCOUNT not set)"
                }

            account = config.external.storage_account

            try:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import BlobServiceClient

                credential = DefaultAzureCredential()
                service_client = BlobServiceClient(
                    account_url=f"https://{account}.blob.core.windows.net",
                    credential=credential
                )

                # List containers (lightweight connectivity check)
                containers = []
                for container in service_client.list_containers(results_per_page=10):
                    containers.append(container['name'])
                    if len(containers) >= 10:
                        break

                return {
                    "configured": True,
                    "account": account,
                    "accessible": True,
                    "container_count": len(containers),
                    "containers_sample": containers[:5],
                }

            except Exception as e:
                return {
                    "configured": True,
                    "account": account,
                    "accessible": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__
                }

        return self.check_component_health(
            "external_storage",
            check_ext_storage,
            description="External storage account for public blob data"
        )

    # =========================================================================
    # CHECK: External TiTiler
    # =========================================================================

    def check_external_titiler(self) -> Dict[str, Any]:
        """Check external TiTiler instance health via HTTP GET to /healthz."""
        def check_ext_titiler():
            import time
            from config import get_config
            from config.defaults import ExternalDefaults

            config = get_config()

            if not config.external or not config.external.titiler_url:
                return {
                    "configured": False,
                    "message": "External TiTiler not configured (EXTERNAL_TITILER_URL not set)"
                }

            titiler_url = config.external.titiler_url.rstrip('/')
            health_path = ExternalDefaults.TITILER_HEALTH_PATH
            health_url = f"{titiler_url}{health_path}"

            try:
                import urllib.request
                start_time = time.time()

                req = urllib.request.Request(health_url, method='GET')
                req.add_header('User-Agent', 'rmhgeoapi-healthcheck')

                with urllib.request.urlopen(req, timeout=10) as response:
                    response_time_ms = round(
                        (time.time() - start_time) * 1000, 2
                    )
                    status_code = response.status
                    body = response.read().decode('utf-8')[:200]

                return {
                    "configured": True,
                    "url": titiler_url,
                    "health_endpoint": health_url,
                    "healthy": 200 <= status_code < 300,
                    "status_code": status_code,
                    "response_time_ms": response_time_ms,
                    "response_body": body,
                }

            except Exception as e:
                return {
                    "configured": True,
                    "url": titiler_url,
                    "health_endpoint": health_url,
                    "healthy": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__
                }

        return self.check_component_health(
            "external_titiler",
            check_ext_titiler,
            description="External TiTiler tile server for public data"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ExternalEnvironmentHealthChecks']
