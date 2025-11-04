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
            path = req.url.split('/api/db/maintenance/')[-1].strip('/')

            logger.info(f"📥 Admin DB Maintenance request: {path}")

            # Route to appropriate handler
            if path == 'nuke':
                return self._nuke_schema(req)
            elif path == 'redeploy':
                return self._redeploy_schema(req)
            elif path == 'cleanup':
                return self._cleanup_old_records(req)
            else:
                return func.HttpResponse(
                    body=json.dumps({'error': f'Unknown operation: {path}'}),
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

        Note: This migrates the existing /api/db/schema/nuke endpoint
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

        try:
            # Import existing trigger for nuke operation
            from triggers.db_query import schema_nuke_trigger

            # Delegate to existing implementation
            result = schema_nuke_trigger.handle_request(req)

            logger.info("✅ Schema nuke completed")
            return result

        except Exception as e:
            logger.error(f"❌ Error during schema nuke: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
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

        try:
            # The redeploy operation is currently handled in function_app.py
            # We'll return a reference to use that endpoint for now
            # TODO: Extract redeploy logic to a service module

            return func.HttpResponse(
                body=json.dumps({
                    'message': 'Schema redeploy operation',
                    'note': 'This endpoint is a placeholder - use existing /api/db/schema/redeploy for now',
                    'migration_status': 'pending',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=501,  # Not Implemented
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
