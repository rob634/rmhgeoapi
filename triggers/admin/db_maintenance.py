# ============================================================================
# CLAUDE CONTEXT - DATABASE MAINTENANCE ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - PostgreSQL maintenance operations
# PURPOSE: HTTP trigger for database maintenance operations (vacuum, reindex, cleanup)
# LAST_REVIEWED: 03 NOV 2025
# EXPORTS: AdminDbMaintenanceTrigger - Singleton trigger for maintenance operations
# INTERFACES: Azure Functions HTTP trigger
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: azure.functions, psycopg, infrastructure.postgresql, util_logger
# SOURCE: PostgreSQL database for direct maintenance operations
# SCOPE: Write operations for database maintenance (requires confirmation)
# VALIDATION: Requires confirmation parameters for all destructive operations
# PATTERNS: Singleton trigger, RESTful admin API, Confirmation-required operations
# ENTRY_POINTS: AdminDbMaintenanceTrigger.instance().handle_request(req)
# INDEX: AdminDbMaintenanceTrigger:50, nuke_schema:150, redeploy_schema:250, cleanup:350
# ============================================================================

"""
Database Maintenance Admin Trigger

Provides database maintenance operations:
- Schema nuke (drop all objects)
- Schema redeploy (nuke + redeploy)
- Cleanup old records (completed jobs >30 days)

Endpoints:
    POST /api/admin/db/maintenance/nuke
    POST /api/admin/db/maintenance/redeploy
    POST /api/admin/db/maintenance/cleanup

All operations require explicit confirmation parameters.

Critical for:
- Development/test environment resets
- Production data cleanup
- Emergency schema recovery

Author: Robert and Geospatial Claude Legion
Date: 03 NOV 2025
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
            POST /api/db/maintenance/nuke
            POST /api/db/maintenance/redeploy
            POST /api/db/maintenance/cleanup

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with operation results
        """
        try:
            # Determine operation from path
            # Handle both new routes (/api/db/maintenance/*) and deprecated routes (/api/db/schema/*)
            url = req.url

            # Extract operation name
            if '/db/maintenance/' in url:
                path = url.split('/db/maintenance/')[-1].split('?')[0].strip('/')
            elif 'db/maintenance/' in url:
                path = url.split('db/maintenance/')[-1].split('?')[0].strip('/')
            elif '/db/schema/' in url:
                # Deprecated route format
                path = url.split('/db/schema/')[-1].split('?')[0].strip('/')
            elif 'db/schema/' in url:
                # Deprecated route format
                path = url.split('db/schema/')[-1].split('?')[0].strip('/')
            else:
                path = ''

            logger.info(f"📥 Admin DB Maintenance request: url={url}, operation={path}")

            # Route to appropriate handler
            if path == 'nuke':
                return self._nuke_schema(req)
            elif path == 'redeploy':
                return self._redeploy_schema(req)
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
                    # Using sql.SQL composition for consistency with DDL statements
                    cur.execute(
                        sql.SQL("""
                            SELECT
                                p.proname AS function_name,
                                pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments
                            FROM pg_catalog.pg_proc p
                            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                            WHERE n.nspname = {} AND p.prokind = 'f'
                        """).format(sql.Literal(app_schema))
                    )

                    functions = cur.fetchall()
                    for func_name, args in functions:
                        # args is already properly formatted by pg_get_function_identity_arguments
                        drop_stmt = sql.SQL("DROP FUNCTION IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.SQL(f"{func_name}({args})")
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped function: {func_name}({args})")

                    nuke_results.append({
                        "step": "drop_functions",
                        "count": len(functions),
                        "dropped": [f"{f[0]}({f[1]})" for f in functions[:5]]  # First 5 for visibility
                    })

                    # 2. DISCOVER & DROP TABLES
                    cur.execute(
                        sql.SQL("SELECT tablename FROM pg_tables WHERE schemaname = {}").format(
                            sql.Literal(app_schema)
                        )
                    )

                    tables = cur.fetchall()
                    for (table_name,) in tables:
                        drop_stmt = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(table_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped table: {table_name}")

                    nuke_results.append({
                        "step": "drop_tables",
                        "count": len(tables),
                        "dropped": [t[0] for t in tables]
                    })

                    # 3. DISCOVER & DROP ENUMS
                    cur.execute(
                        sql.SQL("""
                            SELECT t.typname
                            FROM pg_type t
                            JOIN pg_namespace n ON t.typnamespace = n.oid
                            WHERE n.nspname = {} AND t.typtype = 'e'
                        """).format(sql.Literal(app_schema))
                    )

                    enums = cur.fetchall()
                    for (enum_name,) in enums:
                        drop_stmt = sql.SQL("DROP TYPE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(enum_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped enum: {enum_name}")

                    nuke_results.append({
                        "step": "drop_enums",
                        "count": len(enums),
                        "dropped": [e[0] for e in enums]
                    })

                    # 4. DISCOVER & DROP SEQUENCES
                    cur.execute(
                        sql.SQL("""
                            SELECT sequence_name
                            FROM information_schema.sequences
                            WHERE sequence_schema = {}
                        """).format(sql.Literal(app_schema))
                    )

                    sequences = cur.fetchall()
                    for (seq_name,) in sequences:
                        drop_stmt = sql.SQL("DROP SEQUENCE IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(seq_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped sequence: {seq_name}")

                    nuke_results.append({
                        "step": "drop_sequences",
                        "count": len(sequences),
                        "dropped": [s[0] for s in sequences]
                    })

                    # 5. DISCOVER & DROP VIEWS
                    cur.execute(
                        sql.SQL("""
                            SELECT table_name
                            FROM information_schema.views
                            WHERE table_schema = {}
                        """).format(sql.Literal(app_schema))
                    )

                    views = cur.fetchall()
                    for (view_name,) in views:
                        drop_stmt = sql.SQL("DROP VIEW IF EXISTS {}.{} CASCADE").format(
                            sql.Identifier(app_schema),
                            sql.Identifier(view_name)
                        )
                        cur.execute(drop_stmt)
                        logger.debug(f"Dropped view: {view_name}")

                    nuke_results.append({
                        "step": "drop_views",
                        "count": len(views),
                        "dropped": [v[0] for v in views]
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
            logger.error(f"❌ Nuke operation failed: {e}")
            logger.error(traceback.format_exc())

            return func.HttpResponse(
                body=json.dumps({
                    "status": "error",
                    "error": str(e),
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
                from infrastructure.stac import get_system_stac_collections

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
                    # Delete old completed jobs
                    cursor.execute(f"""
                        DELETE FROM {self.db_repo.schema_name}.jobs
                        WHERE status = 'completed'
                        AND updated_at < %s
                        RETURNING job_id;
                    """, (cutoff_date,))
                    deleted_jobs = cursor.rowcount

                    # Delete orphaned tasks (tasks whose jobs were deleted)
                    cursor.execute(f"""
                        DELETE FROM {self.db_repo.schema_name}.tasks
                        WHERE job_id NOT IN (
                            SELECT job_id FROM {self.db_repo.schema_name}.jobs
                        )
                        RETURNING task_id;
                    """)
                    deleted_tasks = cursor.rowcount

                    # Also delete old completed tasks for existing jobs
                    cursor.execute(f"""
                        DELETE FROM {self.db_repo.schema_name}.tasks t
                        WHERE t.status = 'completed'
                        AND t.updated_at < %s
                        RETURNING task_id;
                    """, (cutoff_date,))
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
