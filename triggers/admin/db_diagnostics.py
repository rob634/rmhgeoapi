# ============================================================================
# CLAUDE CONTEXT - DATABASE DIAGNOSTICS ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - Database diagnostics and system testing
# PURPOSE: HTTP trigger for database stats, enum diagnostics, and PostgreSQL function testing
# LAST_REVIEWED: 10 NOV 2025
# EXPORTS: AdminDbDiagnosticsTrigger - Singleton trigger for diagnostics
# INTERFACES: Azure Functions HTTP trigger
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: azure.functions, psycopg, infrastructure.postgresql, util_logger
# SOURCE: PostgreSQL system catalogs, pg_stat views, custom functions
# SCOPE: Read-only diagnostics for debugging and system health monitoring
# VALIDATION: None yet (future APIM authentication)
# PATTERNS: Singleton trigger, RESTful admin API
# ENTRY_POINTS: AdminDbDiagnosticsTrigger.instance().handle_request(req)
# INDEX: AdminDbDiagnosticsTrigger:70, _get_stats:150, _get_enum_diagnostic:300, _test_functions:450
# ============================================================================

"""
Database Diagnostics Admin Trigger

Provides diagnostic and testing endpoints for database health monitoring:
- Database statistics (table sizes, index usage, activity summary)
- Enum diagnostics (enum type locations, search path, privileges)
- PostgreSQL function testing (CoreMachine functions availability)

Endpoints:
    GET /api/admin/db/stats
    GET /api/admin/db/diagnostics/enums
    GET /api/admin/db/diagnostics/functions
    GET /api/admin/db/diagnostics/all

Features:
- Comprehensive database statistics
- Enum type diagnostics for troubleshooting
- PostgreSQL function availability testing
- Execution time tracking
- Error handling with detailed logging

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbDiagnostics")


class AdminDbDiagnosticsTrigger:
    """
    Admin trigger for database diagnostics and testing.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminDbDiagnosticsTrigger'] = None

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

        logger.info("🔧 Initializing AdminDbDiagnosticsTrigger")
        self.config = get_config()
        self._initialized = True
        logger.info("✅ AdminDbDiagnosticsTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbDiagnosticsTrigger':
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
        Route admin database diagnostics requests.

        Routes:
            GET /api/admin/db/stats
            GET /api/admin/db/diagnostics/enums
            GET /api/admin/db/diagnostics/functions
            GET /api/admin/db/diagnostics/all

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with diagnostic results
        """
        try:
            # Parse route to determine operation
            # Azure Functions provides URL without /api/ prefix in route
            # URL format: dbadmin/stats or dbadmin/diagnostics/enums
            url = req.url

            # Extract path after dbadmin/
            if '/dbadmin/' in url:
                path = url.split('/dbadmin/')[-1].strip('/')
            elif 'dbadmin/' in url:
                path = url.split('dbadmin/')[-1].strip('/')
            else:
                path = ''

            path_parts = path.split('/') if path else []

            logger.info(f"📥 Admin DB Diagnostics request: url={url}, path={path}, parts={path_parts}, method={req.method}")

            # Route to appropriate handler
            if path_parts[0] == 'stats':
                return self._get_stats(req)

            elif path_parts[0] == 'diagnostics':
                if len(path_parts) < 2:
                    return func.HttpResponse(
                        body=json.dumps({'error': 'Invalid diagnostics path'}),
                        status_code=400,
                        mimetype='application/json'
                    )

                diagnostic_type = path_parts[1]

                if diagnostic_type == 'enums':
                    return self._get_enum_diagnostic(req)
                elif diagnostic_type == 'functions':
                    return self._test_functions(req)
                elif diagnostic_type == 'all':
                    return self._get_all_diagnostics(req)
                else:
                    return func.HttpResponse(
                        body=json.dumps({'error': f'Unknown diagnostic type: {diagnostic_type}'}),
                        status_code=404,
                        mimetype='application/json'
                    )
            else:
                return func.HttpResponse(
                    body=json.dumps({'error': f'Unknown operation: {path_parts[0]}'}),
                    status_code=404,
                    mimetype='application/json'
                )

        except Exception as e:
            logger.error(f"❌ Error in AdminDbDiagnosticsTrigger: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_stats(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get comprehensive database statistics.

        GET /api/admin/db/stats

        Returns:
            {
                "database_statistics": {
                    "table_statistics": [...],
                    "index_usage": [...],
                    "activity_summary": [...]
                },
                "generated_at": "..."
            }
        """
        logger.info("📊 Getting database statistics")

        try:
            stats = {}

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Table statistics
                    table_stats_query = f"""
                        SELECT
                            schemaname,
                            tablename,
                            n_tup_ins as inserts,
                            n_tup_upd as updates,
                            n_tup_del as deletes,
                            n_live_tup as live_rows,
                            n_dead_tup as dead_rows
                        FROM pg_stat_user_tables
                        WHERE schemaname = %s
                        ORDER BY tablename
                    """
                    cursor.execute(table_stats_query, (self.config.app_schema,))
                    table_rows = cursor.fetchall()

                    stats["table_statistics"] = []
                    for row in table_rows:
                        stats["table_statistics"].append({
                            "schema": row['schemaname'],
                            "table": row['tablename'],
                            "inserts": row['inserts'],
                            "updates": row['updates'],
                            "deletes": row['deletes'],
                            "live_rows": row['live_rows'],
                            "dead_rows": row['dead_rows']
                        })

                    # Index usage statistics
                    index_stats_query = f"""
                        SELECT
                            schemaname,
                            tablename,
                            indexname,
                            idx_scan as scans,
                            idx_tup_read as tuples_read,
                            idx_tup_fetch as tuples_fetched
                        FROM pg_stat_user_indexes
                        WHERE schemaname = %s
                        ORDER BY idx_scan DESC
                        LIMIT 10
                    """
                    cursor.execute(index_stats_query, (self.config.app_schema,))
                    index_rows = cursor.fetchall()

                    stats["index_usage"] = []
                    for row in index_rows:
                        stats["index_usage"].append({
                            "schema": row['schemaname'],
                            "table": row['tablename'],
                            "index": row['indexname'],
                            "scans": row['scans'],
                            "tuples_read": row['tuples_read'],
                            "tuples_fetched": row['tuples_fetched']
                        })

                    # Activity summary (last hour, last 24 hours)
                    activity_query = f"""
                        SELECT
                            'jobs' as table_name,
                            COUNT(*) as total_records,
                            COUNT(CASE WHEN created_at >= NOW() - INTERVAL '1 hour' THEN 1 END) as last_hour,
                            COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                            MAX(created_at) as latest_record
                        FROM {self.config.app_schema}.jobs

                        UNION ALL

                        SELECT
                            'tasks' as table_name,
                            COUNT(*) as total_records,
                            COUNT(CASE WHEN created_at >= NOW() - INTERVAL '1 hour' THEN 1 END) as last_hour,
                            COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                            MAX(created_at) as latest_record
                        FROM {self.config.app_schema}.tasks
                    """
                    cursor.execute(activity_query)
                    activity_rows = cursor.fetchall()

                    stats["activity_summary"] = []
                    for row in activity_rows:
                        stats["activity_summary"].append({
                            "table": row['table_name'],
                            "total_records": row['total_records'],
                            "last_hour": row['last_hour'],
                            "last_24h": row['last_24h'],
                            "latest_record": row['latest_record'].isoformat() if row['latest_record'] else None
                        })

            result = {
                'database_statistics': stats,
                'generated_at': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Generated database statistics")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting database statistics: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_enum_diagnostic(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Diagnose PostgreSQL enum types.

        GET /api/admin/db/diagnostics/enums

        Returns:
            {
                "enum_diagnostics": {
                    "enum_locations": [...],
                    "current_search_path": "...",
                    "app_schema_exists": true,
                    "privileges": {...}
                },
                "recommended_fix": {...}
            }
        """
        logger.info("🔍 Running enum diagnostics")

        try:
            diagnostics = {}

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check for enum types in all schemas
                    enum_query = """
                        SELECT
                            n.nspname as schema_name,
                            t.typname as enum_name,
                            array_agg(e.enumlabel ORDER BY e.enumsortorder) as enum_values
                        FROM pg_type t
                        JOIN pg_enum e ON t.oid = e.enumtypid
                        JOIN pg_namespace n ON t.typnamespace = n.oid
                        WHERE t.typname IN ('job_status', 'task_status')
                        GROUP BY n.nspname, t.typname
                        ORDER BY n.nspname, t.typname
                    """
                    cursor.execute(enum_query)
                    enum_rows = cursor.fetchall()

                    diagnostics["enum_locations"] = []
                    for row in enum_rows:
                        diagnostics["enum_locations"].append({
                            "schema": row['schema_name'],
                            "enum_name": row['enum_name'],
                            "values": row['enum_values']
                        })

                    # Check current search_path
                    cursor.execute("SHOW search_path")
                    search_path_row = cursor.fetchone()
                    diagnostics["current_search_path"] = search_path_row[0] if search_path_row else "unknown"

                    # Check if app schema exists
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.schemata
                            WHERE schema_name = %s
                        ) as app_schema_exists
                    """, (self.config.app_schema,))
                    schema_row = cursor.fetchone()
                    diagnostics["app_schema_exists"] = schema_row[0] if schema_row else False

                    # Check current user privileges
                    cursor.execute(f"""
                        SELECT
                            has_schema_privilege(%s, 'CREATE') as can_create_in_app,
                            has_schema_privilege('public', 'CREATE') as can_create_in_public,
                            current_user as current_user
                    """, (self.config.app_schema,))
                    priv_row = cursor.fetchone()

                    diagnostics["privileges"] = {
                        "can_create_in_app": priv_row['can_create_in_app'],
                        "can_create_in_public": priv_row['can_create_in_public'],
                        "current_user": priv_row['current_user']
                    }

            result = {
                'enum_diagnostics': diagnostics,
                'recommended_fix': {
                    'description': 'Create missing enum types in app schema',
                    'sql_commands': [
                        f"SET search_path TO {self.config.app_schema}, public;",
                        f"CREATE TYPE {self.config.app_schema}.job_status AS ENUM ('queued', 'processing', 'completed', 'failed');",
                        f"CREATE TYPE {self.config.app_schema}.task_status AS ENUM ('queued', 'processing', 'completed', 'failed', 'retrying');"
                    ]
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Enum diagnostics completed")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error running enum diagnostics: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _test_functions(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Test PostgreSQL functions availability.

        GET /api/admin/db/diagnostics/functions

        Returns:
            {
                "function_tests": [...],
                "summary": {
                    "total_functions": 3,
                    "available_functions": 3,
                    "failed_functions": 0
                }
            }
        """
        logger.info("🧪 Testing PostgreSQL functions")

        try:
            function_tests = []

            functions_to_test = [
                {
                    "name": "complete_task_and_check_stage",
                    "query": f"SET search_path TO {self.config.app_schema}, public; SELECT task_updated, is_last_task_in_stage, job_id, stage_number, remaining_tasks FROM {self.config.app_schema}.complete_task_and_check_stage('test_nonexistent_task', 'test_job_id', 1)",
                    "description": "Tests task completion and stage detection (with search_path fix)"
                },
                {
                    "name": "advance_job_stage",
                    "query": f"SET search_path TO {self.config.app_schema}, public; SELECT job_updated, new_stage, is_final_stage FROM {self.config.app_schema}.advance_job_stage('test_nonexistent_job', 1)",
                    "description": "Tests job stage advancement (with search_path fix)"
                },
                {
                    "name": "check_job_completion",
                    "query": f"SET search_path TO {self.config.app_schema}, public; SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {self.config.app_schema}.check_job_completion('test_nonexistent_job')",
                    "description": "Tests job completion detection (with search_path fix)"
                }
            ]

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    for func_test in functions_to_test:
                        import time
                        start_time = time.time()

                        try:
                            cursor.execute(func_test["query"])
                            result_row = cursor.fetchone()
                            execution_time = round((time.time() - start_time) * 1000, 2)

                            columns = [desc[0] for desc in cursor.description] if cursor.description else []

                            function_tests.append({
                                "function_name": func_test["name"],
                                "description": func_test["description"],
                                "status": "available",
                                "execution_time_ms": execution_time,
                                "result_columns": columns,
                                "sample_result": dict(zip(columns, result_row)) if result_row else None
                            })

                        except Exception as func_e:
                            execution_time = round((time.time() - start_time) * 1000, 2)

                            function_tests.append({
                                "function_name": func_test["name"],
                                "description": func_test["description"],
                                "status": "error",
                                "error": str(func_e)[:500],
                                "error_type": type(func_e).__name__,
                                "execution_time_ms": execution_time
                            })

            result = {
                'function_tests': function_tests,
                'summary': {
                    'total_functions': len(function_tests),
                    'available_functions': len([f for f in function_tests if f["status"] == "available"]),
                    'failed_functions': len([f for f in function_tests if f["status"] == "error"])
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Function testing completed: {result['summary']['available_functions']}/{result['summary']['total_functions']} available")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error testing functions: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_all_diagnostics(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get all diagnostics (stats + enums + functions).

        GET /api/admin/db/diagnostics/all

        Returns:
            {
                "stats": {...},
                "enums": {...},
                "functions": {...},
                "generated_at": "..."
            }
        """
        logger.info("📊 Getting all diagnostics")

        try:
            # Call each diagnostic method and combine results
            stats_response = self._get_stats(req)
            enums_response = self._get_enum_diagnostic(req)
            functions_response = self._test_functions(req)

            # Parse JSON responses
            stats = json.loads(stats_response.get_body().decode('utf-8'))
            enums = json.loads(enums_response.get_body().decode('utf-8'))
            functions = json.loads(functions_response.get_body().decode('utf-8'))

            result = {
                'stats': stats.get('database_statistics', {}),
                'enums': enums.get('enum_diagnostics', {}),
                'functions': functions.get('function_tests', []),
                'function_summary': functions.get('summary', {}),
                'generated_at': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ All diagnostics completed")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting all diagnostics: {e}")
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
admin_db_diagnostics_trigger = AdminDbDiagnosticsTrigger.instance()
