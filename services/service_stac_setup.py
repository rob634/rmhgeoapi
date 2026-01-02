"""
STAC Database Setup Service.

Service handlers for PgSTAC installation, configuration, and verification.
One-time database setup operations for STAC catalog infrastructure.

Exports:
    get_connection_string: Get PostgreSQL connection string
    install_pgstac: Install PgSTAC schema handler
    configure_pgstac_roles: Configure database roles handler
    verify_pgstac_installation: Verify installation handler
"""

import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import psycopg
from psycopg import sql

from core.models.results import TaskResult
from core.models.enums import TaskStatus
from task_factory import TaskContext
from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.SERVICE, __name__)


def get_connection_string(as_admin: bool = False) -> str:
    """
    Get PostgreSQL connection string with managed identity support.

    ARCHITECTURE PRINCIPLE (16 NOV 2025):
    All database connections must support managed identity authentication.
    Uses the centralized helper function which respects USE_MANAGED_IDENTITY.

    Args:
        as_admin: If True, use admin credentials (for schema operations)
                  Note: With managed identity, this parameter is ignored

    Returns:
        PostgreSQL connection string (managed identity or password-based)
    """
    # Use centralized helper for managed identity support (16 NOV 2025)
    from config import get_postgres_connection_string
    return get_postgres_connection_string()


# ============================================================================
# HANDLER METADATA FOR EXPLICIT REGISTRATION
# ============================================================================
# Static metadata for TaskCatalog registration during migration from decorators

INSTALL_PGSTAC_INFO = {
    'task_type': 'install_pgstac',
    'description': 'Install PgSTAC schema, tables, and functions in PostgreSQL',
    'timeout_seconds': 300,
    'max_retries': 1,
    'required_services': ['PostgreSQL', 'pypgstac'],
    'stage': 1,
    'features': ['database_migration', 'schema_creation', 'postgis_integration'],
    'critical': True,
    'one_time_operation': True
}

CONFIGURE_PGSTAC_ROLES_INFO = {
    'task_type': 'configure_pgstac_roles',
    'description': 'Configure database roles and permissions for PgSTAC',
    'timeout_seconds': 60,
    'max_retries': 2,
    'required_services': ['PostgreSQL'],
    'stage': 2,
    'features': ['role_management', 'permission_configuration', 'security_setup'],
    'depends_on': 'install_pgstac'
}

VERIFY_PGSTAC_INSTALLATION_INFO = {
    'task_type': 'verify_pgstac_installation',
    'description': 'Verify PgSTAC installation and create Bronze collection',
    'timeout_seconds': 60,
    'max_retries': 2,
    'required_services': ['PostgreSQL', 'PgSTAC'],
    'stage': 3,
    'features': ['installation_verification', 'collection_creation', 'health_check'],
    'depends_on': 'configure_pgstac_roles',
    'creates_collection': True
}


def create_install_pgstac_handler():
    """Factory function for install_pgstac handler."""

    async def install_pgstac(task_context: TaskCtx) -> Dict[str, Any]:
        """
        Install PgSTAC schema and functions in PostgreSQL.

        This handler:
        1. Optionally drops existing PgSTAC schema (if drop_existing=True)
        2. Runs PgSTAC migrations using pypgstac
        3. Verifies installation by checking for key tables and functions

        Args:
            task_context: Task execution context with parameters

        Returns:
            TaskResult with installation details
        """
        try:
            logger.info(f"🚀 Starting PgSTAC installation for task {task_context.task_id}")

            # Extract parameters
            params = task_context.parameters
            pgstac_version = params.get("pgstac_version", "0.8.5")
            drop_existing = params.get("drop_existing", False)
            run_migrations = params.get("run_migrations", True)

            # Import pypgstac (lazy import to avoid dependency issues)
            try:
                from pypgstac.migrate import Migrate
                from pypgstac.db import PgstacDB
            except ImportError as e:
                logger.error(f"❌ pypgstac not installed: {e}")
                return TaskResult(
                    task_id=task_context.task_id,
                    job_id=task_context.job_id,
                    stage_number=task_context.stage,
                    task_type=task_context.task_type,
                    status=TaskStatus.FAILED,
                    success=False,
                    error_details=f"pypgstac not installed: {str(e)}",
                    execution_time_seconds=0
                )

            dsn = get_connection_string(as_admin=True)
            tables_created = []
            functions_created = []
            migrations_applied = 0

            # Drop existing schema if requested (DANGEROUS!)
            if drop_existing:
                logger.warning("⚠️ Dropping existing PgSTAC schema...")
                with psycopg.connect(dsn) as conn:
                    with conn.cursor() as cur:
                        cur.execute("DROP SCHEMA IF EXISTS pgstac CASCADE")
                        conn.commit()
                        logger.info("✅ Existing PgSTAC schema dropped")

            # Run migrations
            if run_migrations:
                logger.info(f"📦 Running PgSTAC migrations (version: {pgstac_version})...")
                try:
                    migrate = Migrate(dsn)
                    migrate.run_migration()
                    migrations_applied = 1  # pypgstac doesn't return count
                    logger.info("✅ PgSTAC migrations completed")
                except Exception as e:
                    logger.error(f"❌ Migration failed: {e}")
                    raise

            # Verify installation by checking for key objects
            logger.info("🔍 Verifying PgSTAC installation...")
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    # Check for tables
                    cur.execute("""
                        SELECT tablename
                        FROM pg_tables
                        WHERE schemaname = 'pgstac'
                        ORDER BY tablename
                    """)
                    tables_created = [row[0] for row in cur.fetchall()]
                    logger.info(f"📋 Found {len(tables_created)} PgSTAC tables")

                    # Check for functions
                    cur.execute("""
                        SELECT proname
                        FROM pg_proc p
                        JOIN pg_namespace n ON p.pronamespace = n.oid
                        WHERE n.nspname = 'pgstac'
                        ORDER BY proname
                        LIMIT 20
                    """)
                    functions_created = [row[0] for row in cur.fetchall()]
                    logger.info(f"🔧 Found {len(functions_created)}+ PgSTAC functions")

                    # Get installed version
                    try:
                        cur.execute("SELECT pgstac.get_version()")
                        version_installed = cur.fetchone()[0]
                        logger.info(f"✅ PgSTAC version {version_installed} installed")
                    except Exception:
                        version_installed = pgstac_version

            return TaskResult(
                task_id=task_context.task_id,
                job_id=task_context.job_id,
                stage_number=task_context.stage,
                task_type=task_context.task_type,
                status=TaskStatus.COMPLETED,
                success=True,
                result_data={
                    "version_installed": version_installed,
                    "migrations_applied": migrations_applied,
                    "tables_created": tables_created[:10],  # Limit for logging
                    "table_count": len(tables_created),
                    "functions_created": functions_created[:10],  # Limit for logging
                    "function_count": len(functions_created),
                    "message": f"✅ PgSTAC {version_installed} installed successfully"
                },
                execution_time_seconds=0  # Will be calculated by framework
            )

        except Exception as e:
            logger.error(f"❌ PgSTAC installation failed: {e}")
            return TaskResult(
                task_id=task_context.task_id,
                job_id=task_context.job_id,
                stage_number=task_context.stage,
                task_type=task_context.task_type,
                status=TaskStatus.FAILED,
                success=False,
                error_details=str(e),
                execution_time_seconds=0
            )

    return install_pgstac


async def configure_pgstac_roles(task_context: TaskContext) -> TaskResult:
    """
    Configure database roles and permissions for PgSTAC.

    Creates three roles:
    - pgstac_admin: Full control over pgstac schema
    - pgstac_ingest: Read/write for data operations
    - pgstac_read: Read-only access

    Args:
        task_context: Task execution context

    Returns:
        TaskResult with role configuration details
    """
    try:
        logger.info(f"👥 Configuring PgSTAC roles for task {task_context.task_id}")

        params = task_context.parameters
        roles = params.get("roles", ["pgstac_admin", "pgstac_ingest", "pgstac_read"])

        # Get app_user from params or config - NO HARDCODED USERS
        config = get_config()
        app_user = params.get("app_user") or config.database.managed_identity_admin_name
        if not app_user:
            raise ValueError("app_user not provided and database.managed_identity_admin_name not configured")

        dsn = get_connection_string(as_admin=True)
        roles_created = []
        permissions_granted = []

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                # Create roles if they don't exist
                for role in roles:
                    try:
                        cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
                        roles_created.append(role)
                        logger.info(f"✅ Created role: {role}")
                    except psycopg.errors.DuplicateObject:
                        logger.info(f"ℹ️ Role already exists: {role}")

                # Grant permissions based on role
                # pgstac_admin - full control
                if "pgstac_admin" in roles:
                    cur.execute("GRANT ALL ON SCHEMA pgstac TO pgstac_admin")
                    cur.execute("GRANT ALL ON ALL TABLES IN SCHEMA pgstac TO pgstac_admin")
                    cur.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA pgstac TO pgstac_admin")
                    cur.execute("GRANT ALL ON ALL FUNCTIONS IN SCHEMA pgstac TO pgstac_admin")
                    permissions_granted.append("pgstac_admin: ALL on pgstac schema")

                # pgstac_ingest - read/write
                if "pgstac_ingest" in roles:
                    cur.execute("GRANT USAGE ON SCHEMA pgstac TO pgstac_ingest")
                    cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pgstac TO pgstac_ingest")
                    cur.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO pgstac_ingest")
                    cur.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO pgstac_ingest")
                    permissions_granted.append("pgstac_ingest: READ/WRITE on pgstac")

                # pgstac_read - read only
                if "pgstac_read" in roles:
                    cur.execute("GRANT USAGE ON SCHEMA pgstac TO pgstac_read")
                    cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO pgstac_read")
                    cur.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO pgstac_read")
                    permissions_granted.append("pgstac_read: READ on pgstac")

                # Grant pgstac_ingest to app user for normal operations
                cur.execute(sql.SQL("GRANT pgstac_ingest TO {}").format(sql.Identifier(app_user)))
                permissions_granted.append(f"{app_user}: granted pgstac_ingest role")

                # Also ensure app user can use the schema
                cur.execute(sql.SQL("GRANT USAGE ON SCHEMA pgstac TO {}").format(sql.Identifier(app_user)))

                conn.commit()
                logger.info(f"✅ Configured {len(roles)} roles with permissions")

        return TaskResult(
            task_id=task_context.task_id,
            job_id=task_context.job_id,
            stage_number=task_context.stage,
            task_type=task_context.task_type,
            status=TaskStatus.COMPLETED,
            success=True,
            result_data={
                "roles_created": roles_created,
                "roles_configured": roles,
                "permissions_granted": permissions_granted,
                "app_user_configured": app_user,
                "message": f"✅ Configured {len(roles)} PgSTAC roles"
            },
            execution_time_seconds=0
        )

    except Exception as e:
        logger.error(f"❌ Role configuration failed: {e}")
        return TaskResult(
            task_id=task_context.task_id,
            job_id=task_context.job_id,
            stage_number=task_context.stage,
            task_type=task_context.task_type,
            status=TaskStatus.FAILED,
            success=False,
            error_details=str(e),
            execution_time_seconds=0
        )


async def verify_pgstac_installation(task_context: TaskContext) -> TaskResult:
    """
    Verify PgSTAC installation and optionally create Bronze collection.

    Runs test queries to verify:
    1. PgSTAC version is accessible
    2. Core functions work
    3. Collections table exists
    4. Search function works

    Optionally creates the Bronze tier collection.

    Args:
        task_context: Task execution context

    Returns:
        TaskResult with verification details
    """
    try:
        logger.info(f"🔍 Verifying PgSTAC installation for task {task_context.task_id}")

        params = task_context.parameters
        create_collection = params.get("create_collection", True)
        collection_id = params.get("collection_id", "rmhazure-bronze")
        collection_title = params.get("collection_title", "RMH Azure Bronze Tier")
        collection_description = params.get("collection_description", "Raw geospatial data")
        test_queries = params.get("test_queries", [])

        dsn = get_connection_string()
        test_results = {}
        pgstac_version = None
        collection_count = 0
        collection_created = False

        with psycopg.connect(dsn) as conn:
            # Set search path to include pgstac
            with conn.cursor() as cur:
                cur.execute("SET search_path TO pgstac, public")

                # Test 1: Get PgSTAC version
                try:
                    cur.execute("SELECT pgstac.get_version()")
                    pgstac_version = cur.fetchone()[0]
                    test_results["version_check"] = f"✅ Version: {pgstac_version}"
                    logger.info(f"✅ PgSTAC version: {pgstac_version}")
                except Exception as e:
                    test_results["version_check"] = f"❌ Failed: {str(e)}"
                    logger.error(f"❌ Version check failed: {e}")

                # Test 2: Check collections table
                try:
                    cur.execute("SELECT COUNT(*) FROM pgstac.collections")
                    collection_count = cur.fetchone()[0]
                    test_results["collections_table"] = f"✅ Found {collection_count} collections"
                    logger.info(f"✅ Collections table accessible: {collection_count} collections")
                except Exception as e:
                    test_results["collections_table"] = f"❌ Failed: {str(e)}"
                    logger.error(f"❌ Collections table check failed: {e}")

                # Test 3: Test search function
                try:
                    cur.execute("SELECT pgstac.search('{}') LIMIT 1")
                    test_results["search_function"] = "✅ Search function works"
                    logger.info("✅ Search function operational")
                except Exception as e:
                    test_results["search_function"] = f"❌ Failed: {str(e)}"
                    logger.error(f"❌ Search function test failed: {e}")

                # Create Bronze collection if requested
                if create_collection:
                    try:
                        collection_json = {
                            "id": collection_id,
                            "type": "Collection",
                            "stac_version": "1.0.0",
                            "title": collection_title,
                            "description": collection_description,
                            "license": "proprietary",
                            "extent": {
                                "spatial": {
                                    "bbox": [[-180, -90, 180, 90]]
                                },
                                "temporal": {
                                    "interval": [[None, None]]
                                }
                            },
                            "links": [],
                            "keywords": ["bronze", "raw", "azure", "geospatial"],
                            "providers": [{
                                "name": "RMH Azure",
                                "roles": ["producer", "host"]
                            }]
                        }

                        cur.execute(
                            "SELECT pgstac.create_collection(%s::jsonb)",
                            (json.dumps(collection_json),)
                        )
                        conn.commit()
                        collection_created = True
                        collection_count += 1
                        logger.info(f"✅ Created Bronze collection: {collection_id}")
                        test_results["bronze_collection"] = f"✅ Created: {collection_id}"

                    except psycopg.errors.UniqueViolation:
                        logger.info(f"ℹ️ Collection already exists: {collection_id}")
                        test_results["bronze_collection"] = f"ℹ️ Already exists: {collection_id}"
                    except Exception as e:
                        logger.error(f"❌ Failed to create collection: {e}")
                        test_results["bronze_collection"] = f"❌ Creation failed: {str(e)}"

                # Run any additional test queries
                for i, query in enumerate(test_queries[:3]):  # Limit to 3 custom tests
                    try:
                        cur.execute(query)
                        result = cur.fetchone()
                        test_results[f"custom_test_{i+1}"] = f"✅ Passed"
                        logger.info(f"✅ Custom test {i+1} passed")
                    except Exception as e:
                        test_results[f"custom_test_{i+1}"] = f"❌ Failed: {str(e)[:50]}"
                        logger.warning(f"⚠️ Custom test {i+1} failed: {e}")

        # Determine overall success
        success = pgstac_version is not None and "❌" not in str(test_results.get("search_function", ""))

        return TaskResult(
            task_id=task_context.task_id,
            job_id=task_context.job_id,
            stage_number=task_context.stage,
            task_type=task_context.task_type,
            status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
            success=success,
            result_data={
                "pgstac_version": pgstac_version,
                "collection_count": collection_count,
                "collection_created": collection_created,
                "test_results": test_results,
                "message": "✅ PgSTAC verification complete" if success else "❌ Verification failed"
            },
            execution_time_seconds=0
        )

    except Exception as e:
        logger.error(f"❌ PgSTAC verification failed: {e}")
        return TaskResult(
            task_id=task_context.task_id,
            job_id=task_context.job_id,
            stage_number=task_context.stage,
            task_type=task_context.task_type,
            status=TaskStatus.FAILED,
            success=False,
            error_details=str(e),
            execution_time_seconds=0
        )