"""
Database Maintenance Admin Trigger.

Database maintenance operations with SQL injection prevention.

Exports:
    AdminDbMaintenanceTrigger: HTTP trigger class for maintenance operations
    admin_db_maintenance_trigger: Singleton instance of AdminDbMaintenanceTrigger
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
from config import get_config
from config.defaults import STACDefaults, AzureDefaults
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
            elif path == 'pgstac/check-prerequisites' or path == 'check-prerequisites':
                return self._check_pgstac_prerequisites(req)
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

        # Step 0: Clear Service Bus queues (30 NOV 2025)
        # Prevents stale job/task messages from blocking new jobs after schema rebuild
        logger.info("🧹 Step 0: Clearing Service Bus queues...")
        try:
            from infrastructure.service_bus import ServiceBusRepository
            from config import get_config

            config = get_config()
            service_bus = ServiceBusRepository.instance()

            queues_cleared = {}
            # Clear all 3 queues (11 DEC 2025 - No Legacy Fallbacks)
            queue_names = [
                config.service_bus_jobs_queue,
                config.queues.raster_tasks_queue,
                config.queues.vector_tasks_queue
            ]

            for queue_name in queue_names:
                try:
                    deleted_count = service_bus.clear_queue(queue_name)
                    queues_cleared[queue_name] = {"deleted": deleted_count, "status": "success"}
                    logger.info(f"   ✅ Cleared {deleted_count} messages from {queue_name}")
                except Exception as e:
                    queues_cleared[queue_name] = {"error": str(e), "status": "failed"}
                    logger.warning(f"   ⚠️ Failed to clear {queue_name}: {e}")

            results["steps"].append({
                "step": "clear_queues",
                "status": "success",
                "queues": queues_cleared
            })
        except Exception as e:
            logger.warning(f"⚠️ Queue clearing failed (continuing with rebuild): {e}")
            results["steps"].append({
                "step": "clear_queues",
                "status": "failed",
                "error": str(e)
            })
            # Continue with schema rebuild even if queue clear fails

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

        # Track pgstac failures - pgstac is optional, app schema is critical
        # Jobs in app schema populate pgstac (one-way reference: app → pgstac)
        # System can function without pgstac, STAC features just won't work
        pgstac_failed = False

        try:
            # ================================================================
            # STEP 1: Drop app schema
            # ================================================================
            logger.info("💣 Step 1/11: Dropping app schema...")
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
            logger.info("💣 Step 2/11: Dropping pgstac schema...")
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
                # NON-FATAL: pgstac drop failure should not block app schema deployment
                # App schema is critical, pgstac is optional for core system function
                logger.warning(f"⚠️ Failed to drop pgstac schema (continuing): {e}")
                step2["status"] = "failed"
                step2["error"] = str(e)
                pgstac_failed = True
                # Continue - don't block app schema deployment

            results["steps"].append(step2)

            # ================================================================
            # STEP 3: Redeploy app schema from Pydantic models
            # ================================================================
            logger.info("🏗️ Step 3/11: Deploying app schema from Pydantic models...")
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
            # STEP 4: Ensure geo schema exists and grant permissions
            # ================================================================
            # ARCHITECTURE PRINCIPLE (08 DEC 2025 - Updated):
            # The geo schema stores vector data created by process_vector jobs.
            # Unlike app/pgstac (rebuilt from code), geo contains USER DATA and is never dropped.
            # CRITICAL: Must exist BEFORE any vector jobs run - moved to step 4 for this reason.
            # Single admin identity is used for all database operations (ETL, OGC/STAC, TiTiler).
            config = get_config()
            admin_identity = config.database.managed_identity_admin_name
            logger.info(f"🗺️ Step 4/11: Ensuring geo schema exists and granting permissions to {admin_identity}...")
            step4 = {"step": 4, "action": "ensure_geo_schema_and_grant_permissions", "status": "pending"}

            try:
                from infrastructure.postgresql import PostgreSQLRepository
                geo_repo = PostgreSQLRepository(schema_name='geo')

                with geo_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # 0. Create geo schema if it doesn't exist (04 DEC 2025)
                        # This is idempotent and safe - preserves existing data
                        cur.execute("CREATE SCHEMA IF NOT EXISTS geo")
                        logger.info("✅ Ensured geo schema exists")

                        # 0b. Create geo.table_metadata registry table (06 DEC 2025)
                        # Stores table-level metadata for vector datasets:
                        # - ETL traceability (job_id, source_file, source_format, source_crs)
                        # - STAC linkage (stac_item_id, stac_collection_id)
                        # - Pre-computed bbox for OGC Features performance
                        # This is the SOURCE OF TRUTH - STAC copies for catalog convenience
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS geo.table_metadata (
                                table_name VARCHAR(255) PRIMARY KEY,
                                schema_name VARCHAR(63) DEFAULT 'geo',

                                -- ETL Traceability (populated at Stage 1)
                                etl_job_id VARCHAR(64),
                                source_file VARCHAR(500),
                                source_format VARCHAR(50),
                                source_crs VARCHAR(50),

                                -- STAC Linkage (populated at Stage 3)
                                stac_item_id VARCHAR(100),
                                stac_collection_id VARCHAR(100),

                                -- Statistics (populated at Stage 1)
                                feature_count INTEGER,
                                geometry_type VARCHAR(50),

                                -- Timestamps
                                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

                                -- Pre-computed extent for fast OGC collection response
                                -- Avoids ST_Extent query on every /collections/{id} request
                                bbox_minx DOUBLE PRECISION,
                                bbox_miny DOUBLE PRECISION,
                                bbox_maxx DOUBLE PRECISION,
                                bbox_maxy DOUBLE PRECISION,

                                -- User-provided descriptive metadata (09 DEC 2025)
                                -- Optional fields for OGC/STAC catalog presentation
                                title VARCHAR(500),              -- User-friendly display name
                                description TEXT,                -- Full dataset description
                                attribution VARCHAR(500),        -- Data source attribution
                                license VARCHAR(100),            -- SPDX license identifier (CC-BY-4.0, etc.)
                                keywords TEXT,                   -- Comma-separated tags for discoverability

                                -- Temporal extent (09 DEC 2025)
                                -- Auto-detected from temporal_property column or user-provided
                                temporal_start TIMESTAMP WITH TIME ZONE,
                                temporal_end TIMESTAMP WITH TIME ZONE,
                                temporal_property VARCHAR(100)   -- Column name containing date data
                            )
                        """)

                        # Index for job lookups (find all tables from a job)
                        cur.execute("""
                            CREATE INDEX IF NOT EXISTS idx_table_metadata_etl_job_id
                            ON geo.table_metadata(etl_job_id)
                        """)

                        # Index for STAC linkage lookups
                        cur.execute("""
                            CREATE INDEX IF NOT EXISTS idx_table_metadata_stac_item_id
                            ON geo.table_metadata(stac_item_id)
                        """)

                        logger.info("✅ Ensured geo.table_metadata registry table exists")

                        # 0c. Add columns that may be missing from older deployments (10 DEC 2025)
                        # ALTER TABLE ADD COLUMN IF NOT EXISTS is idempotent
                        alter_columns = [
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS title VARCHAR(500)",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS description TEXT",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS attribution VARCHAR(500)",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS license VARCHAR(100)",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS keywords TEXT",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS temporal_start TIMESTAMP WITH TIME ZONE",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS temporal_end TIMESTAMP WITH TIME ZONE",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS temporal_property VARCHAR(100)",
                        ]
                        for alter_sql in alter_columns:
                            cur.execute(alter_sql)
                        logger.info("✅ Ensured geo.table_metadata has all required columns")

                        # 1. Create h3 schema if it doesn't exist (04 DEC 2025)
                        # h3 schema stores static bootstrap H3 grid data
                        cur.execute("CREATE SCHEMA IF NOT EXISTS h3")
                        logger.info("✅ Ensured h3 schema exists")

                        # 2. Grant USAGE on geo schema
                        # Use sql.Identifier to safely inject the role name
                        admin_ident = sql.Identifier(admin_identity)
                        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA geo TO {}").format(admin_ident))

                        # 3. Grant SELECT on ALL existing tables in geo schema
                        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA geo TO {}").format(admin_ident))

                        # 4. Set default privileges for FUTURE tables created in geo schema
                        # This ensures process_vector created tables auto-grant SELECT
                        cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO {}").format(admin_ident))

                        # 5. Grant on h3 schema (static bootstrap data)
                        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA h3 TO {}").format(admin_ident))
                        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO {}").format(admin_ident))
                        cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT ON TABLES TO {}").format(admin_ident))

                        conn.commit()
                        logger.info(f"✅ Granted geo+h3 schema permissions to {admin_identity} (existing + future tables)")

                step4["status"] = "success"
                step4["schema_created"] = "geo, h3 (if not exists)"
                step4["tables_created"] = ["geo.table_metadata (vector metadata registry)"]
                step4["grants"] = [
                    "USAGE ON SCHEMA geo",
                    "SELECT ON ALL TABLES IN SCHEMA geo",
                    "DEFAULT PRIVILEGES SELECT ON TABLES IN geo",
                    "USAGE ON SCHEMA h3",
                    "SELECT ON ALL TABLES IN SCHEMA h3",
                    "DEFAULT PRIVILEGES SELECT ON TABLES IN h3"
                ]
                step4["granted_to"] = admin_identity

            except Exception as e:
                # Non-fatal error - log warning but continue
                # The grants might fail if admin identity doesn't exist yet
                logger.warning(f"⚠️ Failed to ensure geo schema or grant permissions to {admin_identity}: {e}")
                step4["status"] = "warning"
                step4["error"] = str(e)
                step4["note"] = "Geo schema setup failed - vector workflows and OGC Features API may not work"

            results["steps"].append(step4)

            # ================================================================
            # STEP 5: Redeploy pgstac schema via pypgstac migrate
            # ================================================================
            # NON-FATAL: pgstac deployment failure should not block system operation
            # App schema (jobs/tasks) is already deployed - core system is functional
            # STAC features just won't work until pgstac is fixed
            logger.info("📦 Step 5/11: Running pypgstac migrate...")
            step5 = {"step": 5, "action": "deploy_pgstac_schema", "status": "pending"}

            if pgstac_failed:
                # Skip if drop already failed - no point trying to deploy
                logger.warning("⏭️ Skipping pgstac deploy - drop step already failed")
                step5["status"] = "skipped"
                step5["reason"] = "pgstac drop failed in step 2"
            else:
                try:
                    from infrastructure.pgstac_bootstrap import PgStacBootstrap
                    bootstrap = PgStacBootstrap()

                    migration_output = bootstrap.install_pgstac(
                        drop_existing=False,  # Already dropped in Step 2
                        run_migrations=True
                    )

                    if migration_output.get('success'):
                        step5["status"] = "success"
                        step5["version"] = migration_output.get('version')
                        step5["tables_created"] = migration_output.get('tables_created', 0)
                        logger.info(f"✅ pgstac schema deployed: version {step5['version']}")
                    else:
                        # NON-FATAL: migration returned failure but app schema is deployed
                        logger.warning(f"⚠️ pypgstac migrate failed (continuing): {migration_output.get('error')}")
                        step5["status"] = "failed"
                        step5["error"] = migration_output.get('error', 'Unknown migration error')
                        pgstac_failed = True
                        # Continue - app schema is deployed, system functional

                except Exception as e:
                    # NON-FATAL: exception during migration but app schema is deployed
                    logger.warning(f"⚠️ Exception during pypgstac migrate (continuing): {e}")
                    logger.error(traceback.format_exc())
                    step5["status"] = "failed"
                    step5["error"] = str(e)
                    pgstac_failed = True
                    # Continue - app schema is deployed, system functional

            results["steps"].append(step5)

            # ================================================================
            # STEP 6: Grant pgstac_read role to admin identity
            # ================================================================
            # ARCHITECTURE PRINCIPLE (08 DEC 2025 - Updated):
            # Single admin identity is used for all database operations (ETL, OGC/STAC, TiTiler).
            # After pypgstac migrate recreates the pgstac schema and roles,
            # we grant pgstac_read to the admin identity for STAC catalog access.
            # Note: admin_identity already defined in step 4 (geo schema)
            logger.info(f"🔐 Step 6/11: Granting pgstac_read role to {admin_identity}...")
            step6 = {"step": 6, "action": "grant_pgstac_read_role", "status": "pending"}

            if pgstac_failed:
                # Skip if pgstac deployment failed - role doesn't exist
                logger.warning("⏭️ Skipping pgstac_read grant - pgstac deployment failed")
                step6["status"] = "skipped"
                step6["reason"] = "pgstac deployment failed"
            else:
                try:
                    from infrastructure.postgresql import PostgreSQLRepository
                    pgstac_repo = PostgreSQLRepository(schema_name='pgstac')

                    with pgstac_repo._get_connection() as conn:
                        with conn.cursor() as cur:
                            # Grant pgstac_read role to admin identity
                            # This allows OGC/STAC API and TiTiler to query pgstac tables
                            # Use sql.Identifier to safely inject the role name
                            cur.execute(
                                sql.SQL("GRANT pgstac_read TO {}").format(
                                    sql.Identifier(admin_identity)
                                )
                            )
                            conn.commit()
                            logger.info(f"✅ Granted pgstac_read to {admin_identity}")

                    step6["status"] = "success"
                    step6["role_granted"] = "pgstac_read"
                    step6["granted_to"] = admin_identity

                except Exception as e:
                    # Non-fatal error - log warning but continue
                    # The role grant might fail if admin identity doesn't exist yet
                    logger.warning(f"⚠️ Failed to grant pgstac_read to {admin_identity}: {e}")
                    step6["status"] = "warning"
                    step6["error"] = str(e)
                    step6["note"] = "Role grant failed - OGC/STAC API may not have read access"

            results["steps"].append(step6)

            # ================================================================
            # STEP 7: Create system STAC collections
            # ================================================================
            # FIX (26 NOV 2025): Use create_production_collection() directly
            # instead of going through mock HTTP trigger which was silently failing
            logger.info("📚 Step 7/11: Creating system STAC collections...")
            step7 = {"step": 7, "action": "create_system_collections", "status": "pending", "collections": []}

            if pgstac_failed:
                # Skip if pgstac deployment failed - can't create collections without pgstac schema
                logger.warning("⏭️ Skipping STAC collections creation - pgstac deployment failed")
                step7["status"] = "skipped"
                step7["reason"] = "pgstac deployment failed"
            else:
                try:
                    from infrastructure.pgstac_bootstrap import PgStacBootstrap

                    # Create system collections directly via PgStacBootstrap
                    # This bypasses the HTTP trigger which requires route_params
                    bootstrap = PgStacBootstrap()
                    # Use first 2 system collections (vectors and rasters)
                    # system-h3-grids is created on-demand by H3 jobs
                    system_collection_types = STACDefaults.SYSTEM_COLLECTIONS[:2]

                    for collection_type in system_collection_types:
                        try:
                            result = bootstrap.create_production_collection(collection_type)

                            if result.get('success'):
                                step7["collections"].append(collection_type)
                                if result.get('existed'):
                                    logger.info(f"⏭️ Collection {collection_type} already exists (idempotent)")
                                else:
                                    logger.info(f"✅ Created collection: {collection_type}")
                            else:
                                logger.warning(f"⚠️ Failed to create collection {collection_type}: {result.get('error')}")

                        except Exception as col_e:
                            logger.warning(f"⚠️ Exception creating collection {collection_type}: {col_e}")

                    step7["status"] = "success" if len(step7["collections"]) >= 2 else "partial"

                except Exception as e:
                    logger.error(f"❌ Exception during system collections creation: {e}")
                    step7["status"] = "partial"
                    step7["error"] = str(e)

            results["steps"].append(step7)

            # ================================================================
            # STEP 8: Verify app schema
            # ================================================================
            logger.info("🔍 Step 8/11: Verifying app schema...")
            step8 = {"step": 8, "action": "verify_app_schema", "status": "pending"}

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

                step8["status"] = "success"
                step8["counts"] = {
                    "tables": tables_count,
                    "functions": functions_count,
                    "enums": enums_count
                }
                logger.info(f"✅ app schema verified: {step8['counts']}")

            except Exception as e:
                logger.error(f"❌ Exception during app schema verification: {e}")
                step8["status"] = "failed"
                step8["error"] = str(e)

            results["steps"].append(step8)

            # ================================================================
            # STEP 9: Verify pgstac schema
            # ================================================================
            logger.info("🔍 Step 9/11: Verifying pgstac schema...")
            step9 = {"step": 9, "action": "verify_pgstac_schema", "status": "pending"}

            if pgstac_failed:
                # Skip if pgstac deployment failed - nothing to verify
                logger.warning("⏭️ Skipping pgstac verification - pgstac deployment failed")
                step9["status"] = "skipped"
                step9["reason"] = "pgstac deployment failed"
            else:
                try:
                    from infrastructure.pgstac_bootstrap import PgStacBootstrap
                    bootstrap = PgStacBootstrap()

                    verification = bootstrap.verify_installation()

                    if verification.get('valid'):
                        step9["status"] = "success"
                        step9["checks"] = {
                            "version": verification.get('version'),
                            "hash_functions": verification.get('search_hash_functions', False),
                            "tables_count": verification.get('tables_count', 0)
                        }
                        logger.info(f"✅ pgstac schema verified: version {step9['checks']['version']}")
                    else:
                        step9["status"] = "partial"
                        step9["errors"] = verification.get('errors', [])
                        logger.warning(f"⚠️ pgstac verification issues: {step9['errors']}")

                except Exception as e:
                    logger.error(f"❌ Exception during pgstac verification: {e}")
                    step9["status"] = "failed"
                    step9["error"] = str(e)

            results["steps"].append(step9)

            # ================================================================
            # STEP 10: Ensure Service Bus queues exist (08 DEC 2025)
            # Multi-Function App Architecture requires 4 queues
            # ================================================================
            logger.info("🚌 Step 10/11: Ensuring Service Bus queues exist...")
            step10 = {"step": 10, "action": "ensure_service_bus_queues", "status": "pending"}

            try:
                from infrastructure.service_bus import ServiceBusRepository

                service_bus = ServiceBusRepository.instance()
                queue_results = service_bus.ensure_all_queues_exist()

                if queue_results.get("all_queues_ready"):
                    step10["status"] = "success"
                    step10["queues_checked"] = queue_results.get("queues_checked", 0)
                    step10["queues_created"] = queue_results.get("queues_created", 0)
                    step10["queues_existed"] = queue_results.get("queues_existed", 0)
                    logger.info(f"✅ All {step10['queues_checked']} Service Bus queues ready "
                               f"({step10['queues_existed']} existed, {step10['queues_created']} created)")
                else:
                    # Some queues failed - non-fatal but should be logged
                    step10["status"] = "partial"
                    step10["errors"] = queue_results.get("errors", [])
                    step10["queue_results"] = queue_results.get("queue_results", {})
                    logger.warning(f"⚠️ Some Service Bus queues failed: {step10['errors']}")

            except Exception as e:
                # Non-fatal error - schema rebuild succeeded, just queue setup failed
                logger.warning(f"⚠️ Failed to ensure Service Bus queues: {e}")
                step10["status"] = "failed"
                step10["error"] = str(e)
                step10["note"] = "Schema rebuild succeeded but queue verification failed - tasks may not route correctly"

            results["steps"].append(step10)

            # ================================================================
            # STEP 11: Ensure critical storage containers exist (09 DEC 2025)
            # Bronze and Silver zones must have containers for ETL to function
            # ================================================================
            logger.info("📦 Step 11/11: Ensuring critical storage containers exist...")
            step11 = {"step": 11, "action": "ensure_storage_containers", "status": "pending"}

            try:
                from infrastructure.blob import BlobRepository
                from config.defaults import VectorDefaults

                # Define critical containers per zone
                critical_containers = {
                    "bronze": [
                        (config.storage.bronze.vectors, "Raw vector uploads"),
                        (config.storage.bronze.rasters, "Raw raster uploads"),
                    ],
                    "silver": [
                        (config.storage.silver.cogs, "Cloud Optimized GeoTIFFs"),
                        (VectorDefaults.PICKLE_CONTAINER, "Vector ETL intermediate storage"),
                    ]
                }

                containers_checked = 0
                containers_created = 0
                containers_existed = 0
                container_errors = []
                container_results = {}

                for zone, containers in critical_containers.items():
                    try:
                        blob_repo = BlobRepository.for_zone(zone)
                        zone_results = {}

                        for container_name, description in containers:
                            containers_checked += 1
                            result = blob_repo.ensure_container_exists(container_name)
                            zone_results[container_name] = result

                            if result.get("success"):
                                if result.get("created"):
                                    containers_created += 1
                                    logger.info(f"   ✅ Created {zone}/{container_name}: {description}")
                                else:
                                    containers_existed += 1
                                    logger.debug(f"   ⏭️ Exists {zone}/{container_name}")
                            else:
                                container_errors.append({
                                    "zone": zone,
                                    "container": container_name,
                                    "error": result.get("error", "Unknown error")
                                })
                                logger.warning(f"   ⚠️ Failed {zone}/{container_name}: {result.get('error')}")

                        container_results[zone] = zone_results

                    except Exception as zone_error:
                        logger.warning(f"⚠️ Failed to access {zone} zone: {zone_error}")
                        container_errors.append({
                            "zone": zone,
                            "error": str(zone_error)
                        })

                # Determine status
                if not container_errors:
                    step11["status"] = "success"
                    logger.info(f"✅ All {containers_checked} storage containers ready "
                               f"({containers_existed} existed, {containers_created} created)")
                else:
                    step11["status"] = "partial"
                    step11["errors"] = container_errors
                    logger.warning(f"⚠️ Some storage containers failed: {len(container_errors)} errors")

                step11["containers_checked"] = containers_checked
                step11["containers_created"] = containers_created
                step11["containers_existed"] = containers_existed
                step11["container_results"] = container_results

            except Exception as e:
                # Non-fatal error - schema rebuild succeeded, just container setup failed
                logger.warning(f"⚠️ Failed to ensure storage containers: {e}")
                step11["status"] = "failed"
                step11["error"] = str(e)
                step11["note"] = "Schema rebuild succeeded but container creation failed - ETL may fail on first run"

            results["steps"].append(step11)

            # ================================================================
            # Final result
            # ================================================================
            execution_time_ms = int((time.time() - start_time) * 1000)
            results["execution_time_ms"] = execution_time_ms

            if pgstac_failed:
                # Partial success: app schema deployed but pgstac failed
                # System is functional for job processing, STAC features unavailable
                results["status"] = "partial_success"
                results["pgstac_failed"] = True
                results["warning"] = (
                    "App schema deployed successfully - core system functional. "
                    "pgstac deployment FAILED - STAC features unavailable until fixed. "
                    "geo schema (business data) preserved."
                )
                logger.warning(f"⚠️ FULL REBUILD PARTIAL SUCCESS in {execution_time_ms}ms - pgstac failed")

                return func.HttpResponse(
                    body=json.dumps(results, indent=2),
                    status_code=207,  # Multi-Status - partial success
                    mimetype='application/json'
                )
            else:
                # Full success: both app and pgstac schemas deployed
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

    def _check_pgstac_prerequisites(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check if DBA prerequisites for pypgstac are in place (5 DEC 2025).

        GET /api/dbadmin/maintenance/pgstac/check-prerequisites
        GET /api/dbadmin/maintenance/pgstac/check-prerequisites?identity=migeoetldbadminqa

        In corporate/QA environments, a DBA must:
        1. Create pgstac roles (pgstac_admin, pgstac_ingest, pgstac_read)
        2. Grant those roles to the managed identity

        This endpoint verifies these prerequisites BEFORE running pypgstac migrate.

        Query Parameters:
            identity: Optional managed identity name to check (defaults to config value)

        Returns:
            {
                "ready": true/false,
                "roles_exist": {"pgstac_admin": true, ...},
                "roles_granted": {"pgstac_admin": true, ...},
                "identity_name": "rmhpgflexadmin",
                "missing_roles": [],
                "missing_grants": [],
                "dba_sql": "-- SQL for DBA to run if not ready"
            }
        """
        logger.info("🔍 Checking pgSTAC DBA prerequisites...")

        try:
            # Get optional identity parameter
            identity_name = req.params.get('identity')

            from infrastructure.pgstac_bootstrap import PgStacBootstrap
            bootstrap = PgStacBootstrap()

            # Run prerequisite check
            result = bootstrap.check_dba_prerequisites(identity_name=identity_name)

            result["timestamp"] = datetime.now(timezone.utc).isoformat()

            status_code = 200 if result.get('ready') else 200  # Always 200, ready status in body

            logger.info(f"✅ DBA prerequisites check: ready={result.get('ready')}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=status_code,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error checking DBA prerequisites: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    # =========================================================================
    # GEO SCHEMA TABLE MANAGEMENT (10 DEC 2025)
    # =========================================================================
    # Methods for managing vector tables in the geo schema.
    # Supports both tracked tables (with metadata) and orphaned tables.
    # =========================================================================

    def _unpublish_geo_table(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Cascade delete a vector table from geo schema.

        POST /api/dbadmin/geo/unpublish?table_name={name}&confirm=yes

        Handles both tracked tables (with metadata) and orphaned tables:
        - Tracked: Delete STAC item → Delete metadata → Drop table
        - Orphaned: Just drop the table (warnings logged)

        Query Parameters:
            table_name: Required. Table name (without schema prefix)
            confirm: Required. Must be "yes" to execute

        Returns:
            {
                "success": true,
                "table_name": "world_countries",
                "deleted": {
                    "stac_item": "postgis-geo-world_countries",
                    "metadata_row": true,
                    "geo_table": true
                },
                "warnings": [...],
                "was_orphaned": false
            }
        """
        table_name = req.params.get('table_name')
        confirm = req.params.get('confirm')

        # Validate parameters
        if not table_name:
            return func.HttpResponse(
                body=json.dumps({
                    "error": "table_name parameter required",
                    "usage": "POST /api/dbadmin/geo/unpublish?table_name={name}&confirm=yes"
                }),
                status_code=400,
                mimetype='application/json'
            )

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    "error": "Confirmation required",
                    "message": "Add ?confirm=yes to execute this destructive operation",
                    "table_name": table_name,
                    "warning": "⚠️ This will permanently delete the table and associated metadata"
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.info(f"🗑️ Unpublishing geo table: {table_name}")

        result = {
            "success": False,
            "table_name": table_name,
            "deleted": {
                "stac_item": None,
                "metadata_row": False,
                "geo_table": False
            },
            "warnings": [],
            "was_orphaned": False
        }

        try:
            repo = PostgreSQLRepository()

            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Step 0: Verify table exists in geo schema
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = %s
                        ) as table_exists
                    """, (table_name,))
                    row = cur.fetchone()
                    exists = row['table_exists'] if row else False

                    if not exists:
                        result["error"] = f"Table '{table_name}' does not exist in geo schema"
                        return func.HttpResponse(
                            body=json.dumps(result),
                            status_code=404,
                            mimetype='application/json'
                        )

                    # Step 1: Look up STAC item ID from metadata (if exists)
                    stac_item_id = None
                    stac_collection_id = None

                    # Check if geo.table_metadata exists first
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        ) as metadata_table_exists
                    """)
                    metadata_table_exists = cur.fetchone()['metadata_table_exists']

                    if metadata_table_exists:
                        cur.execute("""
                            SELECT stac_item_id, stac_collection_id
                            FROM geo.table_metadata
                            WHERE table_name = %s
                        """, (table_name,))
                        metadata_row = cur.fetchone()

                        if metadata_row:
                            stac_item_id = metadata_row.get('stac_item_id')
                            stac_collection_id = metadata_row.get('stac_collection_id')
                            logger.info(f"Found metadata for {table_name}: STAC item={stac_item_id}")
                        else:
                            result["was_orphaned"] = True
                            result["warnings"].append(
                                "No metadata found - table was orphaned (created outside ETL or metadata wiped)"
                            )
                    else:
                        result["was_orphaned"] = True
                        result["warnings"].append(
                            "geo.table_metadata table does not exist - cannot lookup STAC linkage"
                        )

                    # Step 2: Delete STAC item (if we have an ID)
                    # Use SAVEPOINT to isolate STAC deletion failures (pgstac triggers can fail
                    # if partition tables are missing after schema rebuild)
                    if stac_item_id:
                        try:
                            # Check if pgstac.items exists
                            cur.execute("""
                                SELECT EXISTS (
                                    SELECT 1 FROM information_schema.tables
                                    WHERE table_schema = 'pgstac' AND table_name = 'items'
                                ) as pgstac_exists
                            """)
                            pgstac_exists = cur.fetchone()['pgstac_exists']

                            if pgstac_exists:
                                # Use savepoint to isolate potential trigger failures
                                cur.execute("SAVEPOINT stac_delete")
                                try:
                                    cur.execute("""
                                        DELETE FROM pgstac.items
                                        WHERE id = %s
                                        RETURNING id
                                    """, (stac_item_id,))
                                    deleted_stac = cur.fetchone()
                                    if deleted_stac:
                                        result["deleted"]["stac_item"] = stac_item_id
                                        logger.info(f"✅ Deleted STAC item: {stac_item_id}")
                                        cur.execute("RELEASE SAVEPOINT stac_delete")
                                    else:
                                        result["warnings"].append(
                                            f"STAC item '{stac_item_id}' not found in pgstac.items (already deleted)"
                                        )
                                        cur.execute("RELEASE SAVEPOINT stac_delete")
                                except Exception as stac_error:
                                    # Rollback just the STAC deletion, continue with metadata/table
                                    cur.execute("ROLLBACK TO SAVEPOINT stac_delete")
                                    result["warnings"].append(
                                        f"STAC item deletion failed (pgstac trigger error): {stac_error}"
                                    )
                                    logger.warning(f"STAC item deletion failed, continuing: {stac_error}")
                            else:
                                result["warnings"].append(
                                    "pgstac.items table does not exist - STAC deletion skipped"
                                )
                        except Exception as e:
                            result["warnings"].append(f"Failed to delete STAC item: {e}")
                            logger.warning(f"STAC item deletion failed: {e}")
                    elif not result["was_orphaned"]:
                        result["warnings"].append(
                            "No STAC item ID in metadata (STAC cataloging may have been skipped or degraded mode)"
                        )

                    # Step 3: Delete metadata row (if table exists)
                    if metadata_table_exists:
                        cur.execute("""
                            DELETE FROM geo.table_metadata
                            WHERE table_name = %s
                            RETURNING table_name
                        """, (table_name,))
                        deleted_metadata = cur.fetchone()
                        result["deleted"]["metadata_row"] = deleted_metadata is not None
                        if deleted_metadata:
                            logger.info(f"✅ Deleted metadata row for {table_name}")

                    # Step 4: DROP TABLE CASCADE
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {schema}.{table} CASCADE").format(
                            schema=sql.Identifier("geo"),
                            table=sql.Identifier(table_name)
                        )
                    )
                    result["deleted"]["geo_table"] = True
                    logger.info(f"✅ Dropped table geo.{table_name}")

                    conn.commit()

            result["success"] = True
            logger.info(f"🎉 Successfully unpublished geo.{table_name}")

            return func.HttpResponse(
                body=json.dumps(result, default=str),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error unpublishing geo.{table_name}: {e}")
            logger.error(traceback.format_exc())
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
            return func.HttpResponse(
                body=json.dumps(result, default=str),
                status_code=500,
                mimetype='application/json'
            )

    def _list_geo_tables(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all tables in the geo schema with metadata status.

        GET /api/dbadmin/geo/tables

        Returns tables with their tracking status (has metadata, has STAC item).
        Useful for discovering orphaned tables after a full-rebuild.

        Returns:
            {
                "tables": [
                    {
                        "table_name": "world_countries",
                        "has_metadata": true,
                        "has_stac_item": true,
                        "feature_count": 250,
                        "title": "World Countries",
                        "etl_job_id": "abc123...",
                        "created_at": "2025-12-09T10:00:00Z"
                    },
                    {
                        "table_name": "orphaned_test",
                        "has_metadata": false,
                        "has_stac_item": false,
                        "feature_count": null,
                        "title": null,
                        "etl_job_id": null,
                        "created_at": null
                    }
                ],
                "summary": {
                    "total": 2,
                    "tracked": 1,
                    "orphaned": 1
                }
            }
        """
        logger.info("📋 Listing geo schema tables...")

        try:
            repo = PostgreSQLRepository()
            tables = []

            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get all tables in geo schema (excluding system tables)
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'geo'
                        AND table_type = 'BASE TABLE'
                        AND table_name != 'table_metadata'
                        ORDER BY table_name
                    """)
                    geo_tables = [row['table_name'] for row in cur.fetchall()]

                    # Check if geo.table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        ) as metadata_table_exists
                    """)
                    metadata_table_exists = cur.fetchone()['metadata_table_exists']

                    # Check if pgstac.items exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'pgstac' AND table_name = 'items'
                        ) as pgstac_exists
                    """)
                    pgstac_exists = cur.fetchone()['pgstac_exists']

                    # Build metadata lookup dict if table exists
                    metadata_lookup = {}
                    if metadata_table_exists:
                        cur.execute("""
                            SELECT
                                table_name,
                                title,
                                feature_count,
                                etl_job_id,
                                stac_item_id,
                                created_at
                            FROM geo.table_metadata
                        """)
                        for row in cur.fetchall():
                            metadata_lookup[row['table_name']] = {
                                'title': row.get('title'),
                                'feature_count': row.get('feature_count'),
                                'etl_job_id': row.get('etl_job_id'),
                                'stac_item_id': row.get('stac_item_id'),
                                'created_at': row['created_at'].isoformat() if row.get('created_at') else None
                            }

                    # Build STAC item lookup if table exists
                    stac_item_ids = set()
                    if pgstac_exists:
                        cur.execute("SELECT id FROM pgstac.items")
                        stac_item_ids = {row['id'] for row in cur.fetchall()}

                    # Build table list with status
                    tracked_count = 0
                    orphaned_count = 0

                    for table_name in geo_tables:
                        metadata = metadata_lookup.get(table_name)
                        has_metadata = metadata is not None
                        stac_item_id = metadata.get('stac_item_id') if metadata else None
                        has_stac_item = stac_item_id in stac_item_ids if stac_item_id else False

                        table_info = {
                            "table_name": table_name,
                            "has_metadata": has_metadata,
                            "has_stac_item": has_stac_item,
                            "feature_count": metadata.get('feature_count') if metadata else None,
                            "title": metadata.get('title') if metadata else None,
                            "etl_job_id": metadata.get('etl_job_id')[:8] + "..." if metadata and metadata.get('etl_job_id') else None,
                            "created_at": metadata.get('created_at') if metadata else None
                        }
                        tables.append(table_info)

                        if has_metadata:
                            tracked_count += 1
                        else:
                            orphaned_count += 1

            result = {
                "tables": tables,
                "summary": {
                    "total": len(tables),
                    "tracked": tracked_count,
                    "orphaned": orphaned_count
                },
                "schema_status": {
                    "geo_table_metadata_exists": metadata_table_exists,
                    "pgstac_items_exists": pgstac_exists
                }
            }

            logger.info(f"📋 Found {len(tables)} geo tables ({tracked_count} tracked, {orphaned_count} orphaned)")

            return func.HttpResponse(
                body=json.dumps(result, default=str, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error listing geo tables: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    # =========================================================================
    # GEO METADATA QUERY ENDPOINT (10 DEC 2025)
    # =========================================================================

    def _list_metadata(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all records in geo.table_metadata with filtering options.

        GET /api/dbadmin/geo/metadata
        GET /api/dbadmin/geo/metadata?job_id=abc123
        GET /api/dbadmin/geo/metadata?has_stac=true
        GET /api/dbadmin/geo/metadata?limit=50&offset=0

        Query Parameters:
            job_id: Filter by ETL job ID
            has_stac: Filter by STAC linkage (true/false)
            limit: Max records (default: 100, max: 500)
            offset: Pagination offset (default: 0)

        Returns:
            JSON with metadata records, total count, and filters applied
        """
        # Parse query parameters
        job_id = req.params.get('job_id')
        has_stac = req.params.get('has_stac')

        try:
            limit = int(req.params.get('limit', 100))
        except ValueError:
            limit = 100
        try:
            offset = int(req.params.get('offset', 0))
        except ValueError:
            offset = 0

        # Clamp limits
        limit = min(max(1, limit), 500)  # 1-500
        offset = max(0, offset)

        filters_applied = {}

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                        )
                    """)
                    if not cur.fetchone()['exists']:
                        return func.HttpResponse(
                            body=json.dumps({
                                'error': 'geo.table_metadata table does not exist',
                                'hint': 'Run full-rebuild to create schema'
                            }),
                            status_code=404,
                            mimetype='application/json'
                        )

                    # Build dynamic WHERE clause
                    conditions = []
                    params = []

                    if job_id:
                        conditions.append("etl_job_id = %s")
                        params.append(job_id)
                        filters_applied['job_id'] = job_id

                    if has_stac is not None:
                        if has_stac.lower() == 'true':
                            conditions.append("stac_item_id IS NOT NULL")
                            filters_applied['has_stac'] = True
                        elif has_stac.lower() == 'false':
                            conditions.append("stac_item_id IS NULL")
                            filters_applied['has_stac'] = False

                    where_clause = ""
                    if conditions:
                        where_clause = "WHERE " + " AND ".join(conditions)

                    # Get total count
                    count_sql = f"SELECT COUNT(*) FROM geo.table_metadata {where_clause}"
                    cur.execute(count_sql, params)
                    total = cur.fetchone()['count']

                    # Discover which columns actually exist in the table
                    # This handles schema evolution gracefully
                    cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'geo' AND table_name = 'table_metadata'
                    """)
                    existing_columns = set(row['column_name'] for row in cur.fetchall())

                    # Define columns we want, in order (only include if they exist)
                    desired_columns = [
                        'table_name', 'schema_name',
                        'title', 'description', 'attribution', 'license', 'keywords',
                        'feature_count', 'geometry_type',
                        'source_file', 'source_format', 'source_crs',
                        'etl_job_id', 'stac_item_id', 'stac_collection_id',
                        'bbox_minx', 'bbox_miny', 'bbox_maxx', 'bbox_maxy',
                        'temporal_start', 'temporal_end', 'temporal_property',
                        'created_at', 'updated_at'
                    ]

                    # Only select columns that exist
                    select_columns = [c for c in desired_columns if c in existing_columns]

                    # Get records
                    query = f"""
                        SELECT {', '.join(select_columns)}
                        FROM geo.table_metadata
                        {where_clause}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """
                    cur.execute(query, params + [limit, offset])

                    # Helper to safely get value from row (handles missing columns)
                    def safe_get(row_dict, key, default=None):
                        if key in existing_columns:
                            return row_dict.get(key, default)
                        return default

                    metadata = []
                    for row in cur.fetchall():
                        item = {
                            'table_name': row['table_name'],  # Required column
                            'schema_name': safe_get(row, 'schema_name', 'geo'),
                            'feature_count': safe_get(row, 'feature_count'),
                            'geometry_type': safe_get(row, 'geometry_type'),
                            'source_file': safe_get(row, 'source_file'),
                            'source_format': safe_get(row, 'source_format'),
                            'source_crs': safe_get(row, 'source_crs'),
                            'etl_job_id': safe_get(row, 'etl_job_id'),
                            'stac_item_id': safe_get(row, 'stac_item_id'),
                            'stac_collection_id': safe_get(row, 'stac_collection_id'),
                        }

                        # Timestamps
                        created_at = safe_get(row, 'created_at')
                        updated_at = safe_get(row, 'updated_at')
                        item['created_at'] = created_at.isoformat() if created_at else None
                        item['updated_at'] = updated_at.isoformat() if updated_at else None

                        # New metadata columns (may not exist in older schemas)
                        if 'title' in existing_columns:
                            item['title'] = safe_get(row, 'title')
                        if 'description' in existing_columns:
                            item['description'] = safe_get(row, 'description')
                        if 'attribution' in existing_columns:
                            item['attribution'] = safe_get(row, 'attribution')
                        if 'license' in existing_columns:
                            item['license'] = safe_get(row, 'license')
                        if 'keywords' in existing_columns:
                            item['keywords'] = safe_get(row, 'keywords')

                        # Add bbox if present
                        bbox_cols = ['bbox_minx', 'bbox_miny', 'bbox_maxx', 'bbox_maxy']
                        if all(c in existing_columns for c in bbox_cols):
                            bbox_vals = [safe_get(row, c) for c in bbox_cols]
                            if all(v is not None for v in bbox_vals):
                                item['bbox'] = bbox_vals

                        # Add temporal extent if columns exist
                        if 'temporal_start' in existing_columns or 'temporal_end' in existing_columns:
                            ts = safe_get(row, 'temporal_start')
                            te = safe_get(row, 'temporal_end')
                            if ts or te:
                                item['temporal_extent'] = {
                                    'start': ts.isoformat() if ts else None,
                                    'end': te.isoformat() if te else None,
                                    'property': safe_get(row, 'temporal_property')
                                }

                        metadata.append(item)

            logger.info(f"📋 Listed {len(metadata)} metadata records (total: {total}, filters: {filters_applied})")

            return func.HttpResponse(
                body=json.dumps({
                    'metadata': metadata,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                    'filters_applied': filters_applied
                }, default=str, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error listing metadata: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    # =========================================================================
    # GEO ORPHAN CHECK ENDPOINT (10 DEC 2025)
    # =========================================================================

    def _check_geo_orphans(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check for orphaned tables and metadata in geo schema.

        GET /api/dbadmin/geo/orphans

        Detects:
        - Orphaned Tables: Tables in geo schema without metadata records
        - Orphaned Metadata: Metadata records for non-existent tables

        Detection only - does NOT delete anything.

        Returns:
            JSON with orphaned tables, orphaned metadata, tracked tables, and summary
        """
        from services.janitor_service import geo_orphan_detector

        logger.info("🔍 Running geo orphan detection...")

        result = geo_orphan_detector.run()
        status_code = 200 if result.get("success") else 500

        return func.HttpResponse(
            body=json.dumps(result, default=str, indent=2),
            status_code=status_code,
            mimetype='application/json'
        )


# Create singleton instance
admin_db_maintenance_trigger = AdminDbMaintenanceTrigger.instance()
