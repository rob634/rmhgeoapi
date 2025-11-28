# ============================================================================
# CLAUDE CONTEXT - DATABASE MAINTENANCE ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - PostgreSQL maintenance operations
# PURPOSE: HTTP trigger for database maintenance operations (vacuum, reindex, cleanup)
# LAST_REVIEWED: 16 NOV 2025 (SQL injection prevention hardening)
# EXPORTS: AdminDbMaintenanceTrigger - Singleton trigger for maintenance operations
# INTERFACES: Azure Functions HTTP trigger
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: azure.functions, psycopg, psycopg.sql, infrastructure.postgresql, util_logger
# SOURCE: PostgreSQL database for direct maintenance operations
# SCOPE: Write operations for database maintenance (requires confirmation)
# VALIDATION: Requires confirmation parameters for all destructive operations
# SECURITY: SQL injection prevention via psycopg.sql composition (16 NOV 2025)
# PATTERNS: Singleton trigger, RESTful admin API, Confirmation-required operations
# ENTRY_POINTS: AdminDbMaintenanceTrigger.instance().handle_request(req)
# INDEX: AdminDbMaintenanceTrigger:50, nuke_schema:150, redeploy_schema:250, cleanup:350
# ============================================================================

"""
Database Maintenance Admin Trigger

Provides database maintenance operations:
- App schema nuke (drop all objects)
- App schema redeploy (nuke + redeploy)
- pgSTAC schema redeploy (nuke + pypgstac migrate)
- Cleanup old records (completed jobs >30 days)

Endpoints:
    POST /api/dbadmin/maintenance/nuke
    POST /api/dbadmin/maintenance/redeploy
    POST /api/dbadmin/maintenance/pgstac/redeploy
    POST /api/dbadmin/maintenance/cleanup

All operations require explicit confirmation parameters.

Critical for:
- Development/test environment resets
- Production data cleanup
- Emergency schema recovery
- pgSTAC function installation (search_tohash, search_hash)

"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import traceback

import psycopg
from psycopg import sql

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbMaintenance")


class AdminDbMaintenanceTrigger:
    """
    Admin trigger for PostgreSQL maintenance operations.

    Singleton pattern for consistent configuration across requests.
    All operations require confirmation parameters.
    """

    _instance: Optional['AdminDbMaintenanceTrigger'] = None

    def __new__(cls):
        """Singleton pattern - reuse instance across requests."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize trigger (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("🔧 Initializing AdminDbMaintenanceTrigger")
        self._initialized = True
        logger.info("✅ AdminDbMaintenanceTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbMaintenanceTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def db_repo(self) -> PostgreSQLRepository:
        """Lazy initialization of database repository."""
        if not hasattr(self, '_db_repo'):
            logger.debug("🔧 Lazy loading database repository")
            repos = RepositoryFactory.create_repositories()
            self._db_repo = repos['job_repo']
        return self._db_repo

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route admin database maintenance requests.

        Routes:
            POST /api/dbadmin/maintenance/nuke
            POST /api/dbadmin/maintenance/redeploy
            POST /api/dbadmin/maintenance/cleanup

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with operation results
        """
        try:
            # Determine operation from path
            # Handle current routes (/api/dbadmin/maintenance/*) and deprecated routes (/api/db/*)
            url = req.url

            # Extract operation name
            if '/dbadmin/maintenance/' in url:
                # Current route pattern (16 NOV 2025)
                path = url.split('/dbadmin/maintenance/')[-1].split('?')[0].strip('/')
            elif 'dbadmin/maintenance/' in url:
                # Current route pattern (no leading slash)
                path = url.split('dbadmin/maintenance/')[-1].split('?')[0].strip('/')
            elif '/db/maintenance/' in url:
                # Deprecated route pattern
                path = url.split('/db/maintenance/')[-1].split('?')[0].strip('/')
            elif 'db/maintenance/' in url:
                # Deprecated route pattern (no leading slash)
                path = url.split('db/maintenance/')[-1].split('?')[0].strip('/')
            elif '/db/schema/' in url:
                # Deprecated route pattern (old)
                path = url.split('/db/schema/')[-1].split('?')[0].strip('/')
            elif 'db/schema/' in url:
                # Deprecated route pattern (old, no leading slash)
                path = url.split('db/schema/')[-1].split('?')[0].strip('/')
            else:
                path = ''

            logger.info(f"📥 Admin DB Maintenance request: url={url}, operation={path}")

            # Route to appropriate handler
            if path == 'nuke':
                return self._nuke_schema(req)
            elif path == 'redeploy':
                return self._redeploy_schema(req)
            elif path == 'pgstac/redeploy' or path == 'redeploy-pgstac':
                return self._redeploy_pgstac_schema(req)
            elif path == 'full-rebuild':
                return self._full_rebuild(req)
            elif path == 'cleanup':
                return self._cleanup_old_records(req)
            else:
                return func.HttpResponse(
                    body=json.dumps({'error': f'Unknown operation: {path}', 'url': url}),
                    status_code=404,
                    mimetype='application/json'
                )

        except Exception as e:
            logger.error(f"❌ Error in AdminDbMaintenanceTrigger: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _nuke_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Drop all schema objects (DESTRUCTIVE).

        POST /api/admin/db/maintenance/nuke?confirm=yes

        Query Parameters:
            confirm: Must be "yes" (required)

        Returns:
            {
                "status": "success",
                "operations": [...],
                "total_objects_dropped": 50,
                "timestamp": "2025-11-03T..."
            }

        Note: Uses repository pattern for managed identity authentication (16 NOV 2025)
        """
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'Schema nuke requires explicit confirmation',
                    'usage': 'POST /api/admin/db/maintenance/nuke?confirm=yes',
                    'warning': 'This will DESTROY ALL DATA in app schema'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning("🚨 NUCLEAR: Nuking schema (all objects will be dropped)")

        nuke_results = []
        app_schema = self.db_repo.schema_name  # From repository configuration

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. DISCOVER & DROP FUNCTIONS
                    cur.execute("""
                        SELECT
                            p.proname AS function_name,
                            pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments
                        FROM pg_catalog.pg_proc p
                        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = %s AND p.prokind = 'f'
                    """, (app_schema,))

                    functions = cur.fetchall()
                    for row in functions:
                        func_name = row['function_name']
                        args = row['arguments']
                        # args is already properly formatted by pg_get_function_identity_arguments
                        # Build function signature: schema.function_name(args)
                        # Note: func_name and args come from pg_catalog (trusted source)
                        # Schema uses Identifier, function signature uses SQL composition (16 NOV 2025)
                        drop_stmt = sql.SQL("DROP FUNCTION IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.SQL(f"{func_name}({args})")  # Trusted: from pg_catalog
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped function: {func_name}({args})")

                    nuke_results.append({
                        "step": "drop_functions",
                        "count": len(functions),
                        "dropped": [f"{row['function_name']}({row['arguments']})" for row in functions[:5]]
                    })

                    # 2. DISCOVER & DROP TABLES
                    cur.execute("""
                        SELECT tablename FROM pg_tables WHERE schemaname = %s
                    """, (app_schema,))

                    tables = cur.fetchall()
                    for row in tables:
                        table_name = row['tablename']
                        drop_stmt = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(table_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped table: {table_name}")

                    nuke_results.append({
                        "step": "drop_tables",
                        "count": len(tables),
                        "dropped": [row['tablename'] for row in tables]
                    })

                    # 3. DISCOVER & DROP ENUMS
                    cur.execute("""
                        SELECT t.typname
                        FROM pg_type t
                        JOIN pg_namespace n ON t.typnamespace = n.oid
                        WHERE n.nspname = %s AND t.typtype = 'e'
                    """, (app_schema,))

                    enums = cur.fetchall()
                    for row in enums:
                        enum_name = row['typname']
                        drop_stmt = sql.SQL("DROP TYPE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(enum_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped enum: {enum_name}")

                    nuke_results.append({
                        "step": "drop_enums",
                        "count": len(enums),
                        "dropped": [row['typname'] for row in enums]
                    })

                    # 4. DISCOVER & DROP SEQUENCES
                    cur.execute("""
                        SELECT sequence_name
                        FROM information_schema.sequences
                        WHERE sequence_schema = %s
                    """, (app_schema,))

                    sequences = cur.fetchall()
                    for row in sequences:
                        seq_name = row['sequence_name']
                        drop_stmt = sql.SQL("DROP SEQUENCE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(seq_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped sequence: {seq_name}")

                    nuke_results.append({
                        "step": "drop_sequences",
                        "count": len(sequences),
                        "dropped": [row['sequence_name'] for row in sequences]
                    })

                    # 5. DISCOVER & DROP VIEWS
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.views
                        WHERE table_schema = %s
                    """, (app_schema,))

                    views = cur.fetchall()
                    for row in views:
                        view_name = row['table_name']
                        drop_stmt = sql.SQL("DROP VIEW IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(view_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped view: {view_name}")

                    nuke_results.append({
                        "step": "drop_views",
                        "count": len(views),
                        "dropped": [row['table_name'] for row in views]
                    })

                    # Commit all drops
                    conn.commit()

                    # Calculate total objects dropped
                    total_dropped = sum(r['count'] for r in nuke_results)

                    logger.info(f"✅ Schema nuke completed: {total_dropped} objects dropped")

                    return func.HttpResponse(
                        body=json.dumps({
                            "status": "success",
                            "message": f"🚨 NUCLEAR: Schema {app_schema} completely reset",
                            "implementation": "Repository pattern with managed identity (16 NOV 2025)",
                            "total_objects_dropped": total_dropped,
                            "operations": nuke_results,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }, indent=2),
                        status_code=200,
                        mimetype='application/json'
                    )

        except Exception as e:
            error_msg = str(e) if str(e) else repr(e)
            error_type = type(e).__name__
            logger.error(f"❌ Nuke operation failed: {error_type}: {error_msg}")
            logger.error(traceback.format_exc())

            return func.HttpResponse(
                body=json.dumps({
                    "status": "error",
                    "error": error_msg,
                    "error_type": error_type,
                    "traceback": traceback.format_exc(),
                    "operations_completed": nuke_results,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=500,
                mimetype='application/json'
            )

    def _redeploy_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Nuke and redeploy schema in one operation (DESTRUCTIVE).

        POST /api/admin/db/maintenance/redeploy?confirm=yes

        Query Parameters:
            confirm: Must be "yes" (required)

        Returns:
            {
                "status": "success",
                "steps": [
                    {"step": "nuke_schema", "status": "success", ...},
                    {"step": "deploy_schema", "status": "success", ...},
                    {"step": "create_system_stac_collections", "status": "success", ...}
                ],
                "overall_status": "success",
                "timestamp": "2025-11-03T..."
            }

        Note: This migrates the existing /api/db/schema/redeploy endpoint
        """
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'Schema redeploy requires explicit confirmation',
                    'usage': 'POST /api/admin/db/maintenance/redeploy?confirm=yes',
                    'warning': 'This will DESTROY ALL DATA and rebuild the schema'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning("🔄 REDEPLOY: Nuking and redeploying schema")

        results = {
            "operation": "schema_redeploy",
            "steps": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            # Step 1: Nuke existing schema (call internal nuke method)
            logger.info("📥 Step 1: Nuking existing schema...")
            nuke_response = self._nuke_schema(req)
            nuke_data = json.loads(nuke_response.get_body().decode('utf-8'))

            results["steps"].append({
                "step": "nuke_schema",
                "status": nuke_data.get("status", "failed"),
                "objects_dropped": nuke_data.get("total_objects_dropped", 0),
                "details": nuke_data.get("operations", [])[:5]  # Limit details to first 5
            })

            # Only proceed with deploy if nuke succeeded
            if nuke_response.status_code != 200:
                results["overall_status"] = "failed_at_nuke"
                results["message"] = "Nuke operation failed"
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            # Step 2: Deploy fresh schema
            logger.info("📦 Step 2: Deploying fresh schema...")
            from triggers.schema_pydantic_deploy import pydantic_deploy_trigger
            deploy_response = pydantic_deploy_trigger.handle_request(req)
            deploy_data = json.loads(deploy_response.get_body().decode('utf-8'))

            results["steps"].append({
                "step": "deploy_schema",
                "status": deploy_data.get("status", "failed"),
                "objects_created": deploy_data.get("statistics", {}),
                "verification": deploy_data.get("verification", {})
            })

            if deploy_response.status_code != 200:
                results["overall_status"] = "failed_at_deploy"
                results["message"] = "Nuke succeeded but deploy failed"
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            # Step 3: Create System STAC collections (18 OCT 2025 - System STAC Layer 1)
            logger.info("🗺️ Step 3: Creating System STAC collections...")

            stac_collections_result = {
                "status": "pending",
                "collections_created": [],
                "collections_failed": []
            }

            try:
                from triggers.stac_collections import stac_collections_trigger
                from infrastructure.pgstac_bootstrap import get_system_stac_collections

                system_collections = get_system_stac_collections()

                for collection_data in system_collections:
                    try:
                        logger.info(f"📌 Creating STAC collection: {collection_data['id']}")

                        # Create mock request with collection data as JSON body
                        import io
                        mock_request = func.HttpRequest(
                            method='POST',
                            url='/api/stac/create-collection',
                            body=json.dumps(collection_data).encode('utf-8')
                        )

                        result_response = stac_collections_trigger.handle_request(mock_request)
                        result = json.loads(result_response.get_body().decode('utf-8'))

                        if result.get('success'):
                            stac_collections_result["collections_created"].append({
                                "id": collection_data['id'],
                                "status": "created"
                            })
                        else:
                            stac_collections_result["collections_failed"].append({
                                "id": collection_data['id'],
                                "error": result.get('error', 'Unknown error')
                            })

                    except Exception as col_e:
                        logger.error(f"❌ Failed to create collection {collection_data['id']}: {col_e}")
                        stac_collections_result["collections_failed"].append({
                            "id": collection_data['id'],
                            "error": str(col_e)
                        })

                stac_collections_result["status"] = "success" if len(stac_collections_result["collections_created"]) >= 1 else "partial"

            except Exception as e:
                logger.error(f"❌ Step 3 exception: {e}")
                logger.error(traceback.format_exc())
                stac_collections_result["status"] = "failed"
                stac_collections_result["error"] = str(e)

            results["steps"].append({
                "step": "create_system_stac_collections",
                "status": stac_collections_result.get("status", "failed"),
                "collections_created": stac_collections_result.get("collections_created", []),
                "collections_failed": stac_collections_result.get("collections_failed", [])
            })

            # Overall status
            results["overall_status"] = "success"
            results["message"] = "Schema redeployed successfully"

            logger.info(f"✅ Schema redeploy complete: {len(results['steps'])} steps")

            return func.HttpResponse(
                body=json.dumps(results, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error during schema redeploy: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _redeploy_pgstac_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Nuke and redeploy pgSTAC schema using pypgstac migrate (DESTRUCTIVE).

        POST /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes

        Query Parameters:
            confirm: Must be "yes" (required)

        Returns:
            {
                "status": "success",
                "steps": [
                    {"step": "drop_pgstac_schema", "status": "success"},
                    {"step": "run_pypgstac_migrate", "status": "success", "version": "0.9.8"},
                    {"step": "verify_installation", "status": "success", ...}
                ],
                "overall_status": "success",
                "timestamp": "2025-11-18T..."
            }

        Note: This is separate from app schema redeploy - allows independent
              pgSTAC maintenance without affecting job/task tables.

        
        Date: 18 NOV 2025
        """
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'pgSTAC schema redeploy requires explicit confirmation',
                    'usage': 'POST /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes',
                    'warning': 'This will DESTROY ALL STAC DATA (collections, items, searches) and rebuild the pgstac schema'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning("🔄 PGSTAC REDEPLOY: Nuking and redeploying pgstac schema")

        results = {
            "operation": "pgstac_schema_redeploy",
            "steps": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            # Step 1: Drop pgstac schema
            logger.info("💣 Step 1: Dropping pgstac schema...")
            drop_result = {"step": "drop_pgstac_schema", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                pgstac_repo = PostgreSQLRepository(schema_name='pgstac')

                with pgstac_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Drop pgstac schema (CASCADE removes all objects)
                        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier('pgstac')
                        ))
                        conn.commit()
                        logger.info("✅ pgstac schema dropped")

                drop_result["status"] = "success"
                drop_result["message"] = "pgstac schema and all objects dropped"

            except Exception as e:
                logger.error(f"❌ Failed to drop pgstac schema: {e}")
                drop_result["status"] = "failed"
                drop_result["error"] = str(e)
                results["steps"].append(drop_result)
                results["overall_status"] = "failed_at_drop"
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            results["steps"].append(drop_result)

            # Step 2: Run pypgstac migrate
            logger.info("📦 Step 2: Running pypgstac migrate...")
            migrate_result = {"step": "run_pypgstac_migrate", "status": "pending"}

            try:
                from infrastructure.pgstac_bootstrap import PgStacBootstrap
                bootstrap = PgStacBootstrap()

                # Run pypgstac migrate (creates fresh schema with all functions)
                migration_output = bootstrap.install_pgstac(
                    drop_existing=False,  # Already dropped in Step 1
                    run_migrations=True
                )

                if migration_output.get('success'):
                    migrate_result["status"] = "success"
                    migrate_result["version"] = migration_output.get('version')
                    migrate_result["tables_created"] = migration_output.get('tables_created', 0)
                    migrate_result["roles_created"] = migration_output.get('roles_created', [])
                    logger.info(f"✅ pypgstac migrate completed: version {migrate_result['version']}")
                else:
                    migrate_result["status"] = "failed"
                    migrate_result["error"] = migration_output.get('error', 'Unknown migration error')
                    logger.error(f"❌ pypgstac migrate failed: {migrate_result['error']}")
                    results["steps"].append(migrate_result)
                    results["overall_status"] = "failed_at_migrate"
                    return func.HttpResponse(
                        body=json.dumps(results, indent=2),
                        status_code=500,
                        mimetype='application/json'
                    )

            except Exception as e:
                logger.error(f"❌ Exception during pypgstac migrate: {e}")
                logger.error(traceback.format_exc())
                migrate_result["status"] = "failed"
                migrate_result["error"] = str(e)
                migrate_result["traceback"] = traceback.format_exc()[:500]
                results["steps"].append(migrate_result)
                results["overall_status"] = "failed_at_migrate"
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            results["steps"].append(migrate_result)

            # Step 3: Verify installation (comprehensive checks)
            logger.info("🔍 Step 3: Verifying pgSTAC installation...")
            verify_result = {"step": "verify_installation", "status": "pending"}

            try:
                from infrastructure.pgstac_bootstrap import PgStacBootstrap
                bootstrap = PgStacBootstrap()

                verification = bootstrap.verify_installation()

                if verification.get('valid'):
                    verify_result["status"] = "success"
                    verify_result["checks_passed"] = {
                        "schema_exists": verification.get('schema_exists'),
                        "version_query": verification.get('version_query'),
                        "tables_exist": verification.get('tables_exist'),
                        "roles_configured": verification.get('roles_configured'),
                        "search_available": verification.get('search_available'),
                        "search_hash_functions": verification.get('search_hash_functions')
                    }
                    verify_result["version"] = verification.get('version')
                    verify_result["tables_count"] = verification.get('tables_count')
                    logger.info(f"✅ pgSTAC verification passed: {verify_result['version']}")
                else:
                    verify_result["status"] = "partial"
                    verify_result["errors"] = verification.get('errors', [])
                    verify_result["warning"] = "Installation succeeded but verification found issues"
                    logger.warning(f"⚠️ pgSTAC verification had issues: {verify_result['errors']}")

            except Exception as e:
                logger.error(f"❌ Exception during verification: {e}")
                verify_result["status"] = "failed"
                verify_result["error"] = str(e)

            results["steps"].append(verify_result)

            # Overall status
            if verify_result["status"] == "success":
                results["overall_status"] = "success"
                results["message"] = "pgSTAC schema redeployed successfully with all functions"
            elif verify_result["status"] == "partial":
                results["overall_status"] = "partial_success"
                results["message"] = "pgSTAC schema redeployed but verification found issues"
            else:
                results["overall_status"] = "success_with_verification_failure"
                results["message"] = "pgSTAC migration succeeded but verification failed"

            logger.info(f"✅ pgSTAC redeploy complete: {results['overall_status']}")

            return func.HttpResponse(
                body=json.dumps(results, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Unexpected error during pgSTAC redeploy: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'traceback': traceback.format_exc(),
                    'steps_completed': results.get("steps", []),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=500,
                mimetype='application/json'
            )

    def _full_rebuild(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Full infrastructure rebuild: Nuke and redeploy BOTH app and pgstac schemas atomically.

        POST /api/dbadmin/maintenance/full-rebuild?confirm=yes

        ARCHITECTURE PRINCIPLE (25 NOV 2025):
        App and pgstac schemas must be wiped together to maintain referential integrity:
        - Job IDs in app.jobs correspond to STAC items in pgstac.items
        - Wiping one without the other creates orphaned references
        - This endpoint enforces atomic rebuild of both schemas

        NEVER TOUCHED:
        - geo schema (business data - user uploads)
        - h3 schema (static bootstrap data)
        - public schema (PostgreSQL/PostGIS extensions)

        Query Parameters:
            confirm: Must be "yes" (required)

        Returns:
            {
                "operation": "full_rebuild",
                "status": "success",
                "execution_time_ms": 3500,
                "steps": [...],
                "warning": "..."
            }
        """
        import time
        start_time = time.time()

        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'Full rebuild requires explicit confirmation',
                    'usage': 'POST /api/dbadmin/maintenance/full-rebuild?confirm=yes',
                    'warning': 'This will DESTROY ALL job/task data AND all STAC collections/items, then rebuild both schemas from code. geo schema (business data) is NOT touched.'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning("🔥 FULL REBUILD: Nuking and rebuilding app + pgstac schemas atomically")

        results = {
            "operation": "full_rebuild",
            "steps": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            # ================================================================
            # STEP 1: Drop app schema
            # ================================================================
            logger.info("💣 Step 1/8: Dropping app schema...")
            step1 = {"step": 1, "action": "drop_app_schema", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                app_repo = PostgreSQLRepository(schema_name='app')

                with app_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier('app')
                        ))
                        conn.commit()
                        logger.info("✅ app schema dropped")

                step1["status"] = "success"

            except Exception as e:
                logger.error(f"❌ Failed to drop app schema: {e}")
                step1["status"] = "failed"
                step1["error"] = str(e)
                results["steps"].append(step1)
                results["status"] = "failed"
                results["failed_at"] = "drop_app_schema"
                results["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            results["steps"].append(step1)

            # ================================================================
            # STEP 2: Drop pgstac schema
            # ================================================================
            logger.info("💣 Step 2/8: Dropping pgstac schema...")
            step2 = {"step": 2, "action": "drop_pgstac_schema", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                pgstac_repo = PostgreSQLRepository(schema_name='pgstac')

                with pgstac_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier('pgstac')
                        ))
                        conn.commit()
                        logger.info("✅ pgstac schema dropped")

                step2["status"] = "success"

            except Exception as e:
                logger.error(f"❌ Failed to drop pgstac schema: {e}")
                step2["status"] = "failed"
                step2["error"] = str(e)
                results["steps"].append(step2)
                results["status"] = "failed"
                results["failed_at"] = "drop_pgstac_schema"
                results["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            results["steps"].append(step2)

            # ================================================================
            # STEP 3: Redeploy app schema from Pydantic models
            # ================================================================
            logger.info("🏗️ Step 3/8: Deploying app schema from Pydantic models...")
            step3 = {"step": 3, "action": "deploy_app_schema", "status": "pending"}

            try:
                from triggers.schema_pydantic_deploy import pydantic_deploy_trigger
                from unittest.mock import MagicMock

                # Create a mock request with confirm=yes
                mock_req = MagicMock()
                mock_req.params = {'confirm': 'yes', 'action': 'deploy'}
                mock_req.method = 'POST'

                deploy_response = pydantic_deploy_trigger.handle_request(mock_req)
                deploy_result = json.loads(deploy_response.get_body().decode('utf-8'))

                if deploy_response.status_code == 200 and deploy_result.get('status') == 'success':
                    step3["status"] = "success"
                    step3["objects"] = {
                        "tables": deploy_result.get('statistics', {}).get('tables_created', 0),
                        "functions": deploy_result.get('statistics', {}).get('functions_created', 0),
                        "enums": deploy_result.get('statistics', {}).get('enums_processed', 0),
                        "indexes": deploy_result.get('statistics', {}).get('indexes_created', 0),
                        "triggers": deploy_result.get('statistics', {}).get('triggers_created', 0)
                    }
                    logger.info(f"✅ app schema deployed: {step3['objects']}")
                else:
                    step3["status"] = "failed"
                    step3["error"] = deploy_result.get('error', 'Unknown deployment error')
                    results["steps"].append(step3)
                    results["status"] = "failed"
                    results["failed_at"] = "deploy_app_schema"
                    results["execution_time_ms"] = int((time.time() - start_time) * 1000)
                    return func.HttpResponse(
                        body=json.dumps(results, indent=2),
                        status_code=500,
                        mimetype='application/json'
                    )

            except Exception as e:
                logger.error(f"❌ Exception during app schema deployment: {e}")
                logger.error(traceback.format_exc())
                step3["status"] = "failed"
                step3["error"] = str(e)
                results["steps"].append(step3)
                results["status"] = "failed"
                results["failed_at"] = "deploy_app_schema"
                results["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            results["steps"].append(step3)

            # ================================================================
            # STEP 4: Redeploy pgstac schema via pypgstac migrate
            # ================================================================
            logger.info("📦 Step 4/8: Running pypgstac migrate...")
            step4 = {"step": 4, "action": "deploy_pgstac_schema", "status": "pending"}

            try:
                from infrastructure.pgstac_bootstrap import PgStacBootstrap
                bootstrap = PgStacBootstrap()

                migration_output = bootstrap.install_pgstac(
                    drop_existing=False,  # Already dropped in Step 2
                    run_migrations=True
                )

                if migration_output.get('success'):
                    step4["status"] = "success"
                    step4["version"] = migration_output.get('version')
                    step4["tables_created"] = migration_output.get('tables_created', 0)
                    logger.info(f"✅ pgstac schema deployed: version {step4['version']}")
                else:
                    step4["status"] = "failed"
                    step4["error"] = migration_output.get('error', 'Unknown migration error')
                    results["steps"].append(step4)
                    results["status"] = "failed"
                    results["failed_at"] = "deploy_pgstac_schema"
                    results["execution_time_ms"] = int((time.time() - start_time) * 1000)
                    return func.HttpResponse(
                        body=json.dumps(results, indent=2),
                        status_code=500,
                        mimetype='application/json'
                    )

            except Exception as e:
                logger.error(f"❌ Exception during pypgstac migrate: {e}")
                logger.error(traceback.format_exc())
                step4["status"] = "failed"
                step4["error"] = str(e)
                results["steps"].append(step4)
                results["status"] = "failed"
                results["failed_at"] = "deploy_pgstac_schema"
                results["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=500,
                    mimetype='application/json'
                )

            results["steps"].append(step4)

            # ================================================================
            # STEP 5: Grant pgstac_read role to rmhpgflexreader
            # ================================================================
            # ARCHITECTURE PRINCIPLE (25 NOV 2025):
            # rmhpgflexreader is the read-only PostgreSQL user used by the OGC/STAC API
            # function app. After pypgstac migrate recreates the pgstac schema and roles,
            # we must grant pgstac_read to rmhpgflexreader so it can query STAC data.
            logger.info("🔐 Step 5/8: Granting pgstac_read role to rmhpgflexreader...")
            step5 = {"step": 5, "action": "grant_pgstac_read_role", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                pgstac_repo = PostgreSQLRepository(schema_name='pgstac')

                with pgstac_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Grant pgstac_read role to rmhpgflexreader
                        # This allows the read-only OGC/STAC API to query pgstac tables
                        cur.execute("GRANT pgstac_read TO rmhpgflexreader")
                        conn.commit()
                        logger.info("✅ Granted pgstac_read to rmhpgflexreader")

                step5["status"] = "success"
                step5["role_granted"] = "pgstac_read"
                step5["granted_to"] = "rmhpgflexreader"

            except Exception as e:
                # Non-fatal error - log warning but continue
                # The role grant might fail if rmhpgflexreader doesn't exist yet
                logger.warning(f"⚠️ Failed to grant pgstac_read to rmhpgflexreader: {e}")
                step5["status"] = "warning"
                step5["error"] = str(e)
                step5["note"] = "Role grant failed - OGC/STAC API may not have read access"

            results["steps"].append(step5)

            # ================================================================
            # STEP 5b: Grant geo schema permissions to rmhpgflexreader
            # ================================================================
            # ARCHITECTURE PRINCIPLE (27 NOV 2025):
            # rmhpgflexreader needs SELECT on geo schema tables for OGC Features API.
            # Unlike pgstac (which has the pgstac_read role), geo schema tables
            # are created dynamically by process_vector jobs. We:
            # 1. Grant SELECT on ALL existing geo tables
            # 2. Set DEFAULT PRIVILEGES so future tables auto-grant SELECT
            logger.info("🔐 Step 5b/8: Granting geo schema permissions to rmhpgflexreader...")
            step5b = {"step": "5b", "action": "grant_geo_schema_permissions", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                geo_repo = PostgreSQLRepository(schema_name='geo')

                with geo_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # 1. Grant USAGE on geo schema
                        cur.execute("GRANT USAGE ON SCHEMA geo TO rmhpgflexreader")

                        # 2. Grant SELECT on ALL existing tables in geo schema
                        cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA geo TO rmhpgflexreader")

                        # 3. Set default privileges for FUTURE tables created in geo schema
                        # This ensures process_vector created tables auto-grant SELECT
                        cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO rmhpgflexreader")

                        # 4. Also grant on h3 schema (static bootstrap data)
                        cur.execute("GRANT USAGE ON SCHEMA h3 TO rmhpgflexreader")
                        cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO rmhpgflexreader")
                        cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT ON TABLES TO rmhpgflexreader")

                        conn.commit()
                        logger.info("✅ Granted geo+h3 schema permissions to rmhpgflexreader (existing + future tables)")

                step5b["status"] = "success"
                step5b["grants"] = [
                    "USAGE ON SCHEMA geo",
                    "SELECT ON ALL TABLES IN SCHEMA geo",
                    "DEFAULT PRIVILEGES SELECT ON TABLES IN geo",
                    "USAGE ON SCHEMA h3",
                    "SELECT ON ALL TABLES IN SCHEMA h3",
                    "DEFAULT PRIVILEGES SELECT ON TABLES IN h3"
                ]
                step5b["granted_to"] = "rmhpgflexreader"

            except Exception as e:
                # Non-fatal error - log warning but continue
                # The grants might fail if rmhpgflexreader doesn't exist yet
                logger.warning(f"⚠️ Failed to grant geo schema permissions to rmhpgflexreader: {e}")
                step5b["status"] = "warning"
                step5b["error"] = str(e)
                step5b["note"] = "Geo schema grants failed - OGC Features API may not have read access to geo tables"

            results["steps"].append(step5b)

            # ================================================================
            # STEP 6: Create system STAC collections
            # ================================================================
            # FIX (26 NOV 2025): Use create_production_collection() directly
            # instead of going through mock HTTP trigger which was silently failing
            logger.info("📚 Step 6/8: Creating system STAC collections...")
            step6 = {"step": 6, "action": "create_system_collections", "status": "pending", "collections": []}

            try:
                from infrastructure.pgstac_bootstrap import PgStacBootstrap

                # Create system collections directly via PgStacBootstrap
                # This bypasses the HTTP trigger which requires route_params
                bootstrap = PgStacBootstrap()
                system_collection_types = ['system-vectors', 'system-rasters']

                for collection_type in system_collection_types:
                    try:
                        result = bootstrap.create_production_collection(collection_type)

                        if result.get('success'):
                            step6["collections"].append(collection_type)
                            if result.get('existed'):
                                logger.info(f"⏭️ Collection {collection_type} already exists (idempotent)")
                            else:
                                logger.info(f"✅ Created collection: {collection_type}")
                        else:
                            logger.warning(f"⚠️ Failed to create collection {collection_type}: {result.get('error')}")

                    except Exception as col_e:
                        logger.warning(f"⚠️ Exception creating collection {collection_type}: {col_e}")

                step6["status"] = "success" if len(step6["collections"]) >= 2 else "partial"

            except Exception as e:
                logger.error(f"❌ Exception during system collections creation: {e}")
                step6["status"] = "partial"
                step6["error"] = str(e)

            results["steps"].append(step6)

            # ================================================================
            # STEP 7: Verify app schema
            # ================================================================
            logger.info("🔍 Step 7/8: Verifying app schema...")
            step7 = {"step": 7, "action": "verify_app_schema", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                app_repo = PostgreSQLRepository(schema_name='app')

                with app_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Count tables
                        cur.execute("SELECT COUNT(*) as cnt FROM pg_tables WHERE schemaname = 'app'")
                        tables_count = cur.fetchone()['cnt']

                        # Count functions
                        cur.execute("""
                            SELECT COUNT(*) as cnt FROM pg_proc p
                            JOIN pg_namespace n ON p.pronamespace = n.oid
                            WHERE n.nspname = 'app'
                        """)
                        functions_count = cur.fetchone()['cnt']

                        # Count enums
                        cur.execute("""
                            SELECT COUNT(*) as cnt FROM pg_type t
                            JOIN pg_namespace n ON t.typnamespace = n.oid
                            WHERE n.nspname = 'app' AND t.typtype = 'e'
                        """)
                        enums_count = cur.fetchone()['cnt']

                step7["status"] = "success"
                step7["counts"] = {
                    "tables": tables_count,
                    "functions": functions_count,
                    "enums": enums_count
                }
                logger.info(f"✅ app schema verified: {step7['counts']}")

            except Exception as e:
                logger.error(f"❌ Exception during app schema verification: {e}")
                step7["status"] = "failed"
                step7["error"] = str(e)

            results["steps"].append(step7)

            # ================================================================
            # STEP 8: Verify pgstac schema
            # ================================================================
            logger.info("🔍 Step 8/8: Verifying pgstac schema...")
            step8 = {"step": 8, "action": "verify_pgstac_schema", "status": "pending"}

            try:
                from infrastructure.pgstac_bootstrap import PgStacBootstrap
                bootstrap = PgStacBootstrap()

                verification = bootstrap.verify_installation()

                if verification.get('valid'):
                    step8["status"] = "success"
                    step8["checks"] = {
                        "version": verification.get('version'),
                        "hash_functions": verification.get('search_hash_functions', False),
                        "tables_count": verification.get('tables_count', 0)
                    }
                    logger.info(f"✅ pgstac schema verified: version {step8['checks']['version']}")
                else:
                    step8["status"] = "partial"
                    step8["errors"] = verification.get('errors', [])
                    logger.warning(f"⚠️ pgstac verification issues: {step8['errors']}")

            except Exception as e:
                logger.error(f"❌ Exception during pgstac verification: {e}")
                step8["status"] = "failed"
                step8["error"] = str(e)

            results["steps"].append(step8)

            # ================================================================
            # Final result
            # ================================================================
            execution_time_ms = int((time.time() - start_time) * 1000)
            results["execution_time_ms"] = execution_time_ms
            results["status"] = "success"
            results["warning"] = "All job/task data and STAC items have been cleared. geo schema (business data) preserved."

            logger.info(f"✅ FULL REBUILD COMPLETE in {execution_time_ms}ms")

            return func.HttpResponse(
                body=json.dumps(results, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Unexpected error during full rebuild: {e}")
            logger.error(traceback.format_exc())
            results["status"] = "failed"
            results["error"] = str(e)
            results["traceback"] = traceback.format_exc()[:1000]
            results["execution_time_ms"] = int((time.time() - start_time) * 1000)
            return func.HttpResponse(
                body=json.dumps(results, indent=2),
                status_code=500,
                mimetype='application/json'
            )

    def _cleanup_old_records(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Clean up old completed jobs and tasks.

        POST /api/admin/db/maintenance/cleanup?confirm=yes&days=30

        Query Parameters:
            confirm: Must be "yes" (required)
            days: Delete records older than N days (default: 30)

        Returns:
            {
                "status": "success",
                "deleted": {
                    "jobs": 150,
                    "tasks": 3500
                },
                "cutoff_date": "2025-10-04T...",
                "timestamp": "2025-11-03T..."
            }
        """
        confirm = req.params.get('confirm')
        days = int(req.params.get('days', 30))

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'Cleanup requires explicit confirmation',
                    'usage': f'POST /api/admin/db/maintenance/cleanup?confirm=yes&days={days}',
                    'warning': f'This will DELETE all completed jobs older than {days} days'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.info(f"🧹 Cleaning up records older than {days} days")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Delete old completed jobs (SQL injection safe - 16 NOV 2025)
                    delete_jobs_query = sql.SQL("""
                        DELETE FROM {schema}.jobs
                        WHERE status = 'completed'
                        AND updated_at < %s
                        RETURNING job_id;
                    """).format(schema=sql.Identifier(self.db_repo.schema_name))

                    cursor.execute(delete_jobs_query, (cutoff_date,))
                    deleted_jobs = cursor.rowcount

                    # Delete orphaned tasks (tasks whose jobs were deleted)
                    delete_orphaned_query = sql.SQL("""
                        DELETE FROM {schema}.tasks
                        WHERE parent_job_id NOT IN (
                            SELECT job_id FROM {schema}.jobs
                        )
                        RETURNING task_id;
                    """).format(schema=sql.Identifier(self.db_repo.schema_name))

                    cursor.execute(delete_orphaned_query)
                    deleted_tasks = cursor.rowcount

                    # Also delete old completed tasks for existing jobs
                    delete_old_tasks_query = sql.SQL("""
                        DELETE FROM {schema}.tasks t
                        WHERE t.status = 'completed'
                        AND t.updated_at < %s
                        RETURNING task_id;
                    """).format(schema=sql.Identifier(self.db_repo.schema_name))

                    cursor.execute(delete_old_tasks_query, (cutoff_date,))
                    deleted_tasks += cursor.rowcount

                    conn.commit()

            logger.info(f"✅ Cleanup: {deleted_jobs} jobs, {deleted_tasks} tasks deleted")

            return func.HttpResponse(
                body=json.dumps({
                    'status': 'success',
                    'deleted': {
                        'jobs': deleted_jobs,
                        'tasks': deleted_tasks
                    },
                    'cutoff_date': cutoff_date.isoformat(),
                    'days': days,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


# Create singleton instance
admin_db_maintenance_trigger = AdminDbMaintenanceTrigger.instance()
