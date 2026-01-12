# ============================================================================
# DATA CLEANUP OPERATIONS
# ============================================================================
# STATUS: Trigger layer - Database cleanup operations
# PURPOSE: Clean up old jobs/tasks and check prerequisites
# CREATED: 12 JAN 2026 (split from db_maintenance.py)
# ============================================================================
"""
Data Cleanup Operations.

Extracted from db_maintenance.py (2,673 lines) for maintainability.
Handles cleanup of old records and prerequisite checks.

Exports:
    DataCleanupOperations: Class with cleanup methods
"""

import azure.functions as func
import json
import logging
import traceback
from datetime import datetime, timezone, timedelta

from psycopg import sql

from infrastructure import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "DataCleanup")


class DataCleanupOperations:
    """
    Data cleanup operations for database maintenance.

    Handles:
    - Cleanup of old completed jobs and tasks
    - pgSTAC prerequisite checks
    """

    def __init__(self, db_repo: PostgreSQLRepository):
        """Initialize with database repository."""
        self.db_repo = db_repo

    def cleanup_old_records(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Clean up old completed jobs and tasks.

        POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30

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
                    'usage': f'POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days={days}',
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

    def check_pgstac_prerequisites(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check if DBA prerequisites for pypgstac are in place (5 DEC 2025).

        GET /api/dbadmin/maintenance?action=check-prerequisites
        GET /api/dbadmin/maintenance?action=check-prerequisites&identity=migeoetldbadminqa

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
