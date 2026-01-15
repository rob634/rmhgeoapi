# ============================================================================
# DATABASE DIAGNOSTICS ADMIN TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET /api/dbadmin/diagnostics
# PURPOSE: Database diagnostics and system testing endpoints
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: AdminDbDiagnosticsTrigger, admin_db_diagnostics_trigger
# ============================================================================
"""
Database Diagnostics Admin Trigger.

Database diagnostics and system testing endpoints.

Consolidated endpoint pattern (15 DEC 2025, updated 15 JAN 2026):
    GET /api/dbadmin/diagnostics?type={stats|enums|functions|all|config|errors|geo_integrity|user_privileges}
    GET /api/dbadmin/diagnostics?type=lineage&job_id={job_id}
    GET /api/dbadmin/diagnostics?type=user_privileges&username={username}
    POST /api/dbadmin/diagnostics?type=grant_reader_privileges  (grants SELECT to reader UMI)

Exports:
    AdminDbDiagnosticsTrigger: HTTP trigger class for diagnostics
    admin_db_diagnostics_trigger: Singleton instance of AdminDbDiagnosticsTrigger
"""

import azure.functions as func
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbDiagnostics")


# ============================================================================
# ROUTE REGISTRY PATTERN (15 DEC 2025)
# ============================================================================
# Single source of truth for route definitions.
# Used by function_app.py to register routes dynamically.
# ============================================================================

@dataclass
class RouteDefinition:
    """Route configuration for registry pattern."""
    route: str
    methods: list
    handler: str  # Method name on trigger class
    description: str


class AdminDbDiagnosticsTrigger:
    """
    Admin trigger for database diagnostics and testing.

    Singleton pattern for consistent configuration across requests.

    Consolidated API (15 DEC 2025):
        GET /api/dbadmin/diagnostics?type={stats|enums|functions|all|config|errors}
        GET /api/dbadmin/diagnostics?type=lineage&job_id={job_id}
    """

    _instance: Optional['AdminDbDiagnosticsTrigger'] = None

    # ========================================================================
    # ROUTE REGISTRY - Single source of truth for function_app.py
    # ========================================================================
    ROUTES = [
        RouteDefinition(
            route="dbadmin/diagnostics",
            methods=["GET", "POST"],
            handler="handle_diagnostics",
            description="Consolidated diagnostics: ?type={stats|enums|functions|all|config|errors|lineage|geo_integrity|user_privileges|grant_reader_privileges}"
        ),
    ]

    # ========================================================================
    # OPERATIONS REGISTRY - Maps type param to handler method
    # ========================================================================
    OPERATIONS = {
        "stats": "_get_stats",
        "enums": "_get_enum_diagnostic",
        "functions": "_test_functions",
        "all": "_get_all_diagnostics",
        "config": "_get_config_audit",
        "lineage": "_get_etl_lineage",
        "errors": "_get_error_aggregation",
        "geo_integrity": "_get_geo_integrity",  # 14 JAN 2026 - TiPG compatibility check
        "user_privileges": "_get_user_privileges",  # 14 JAN 2026 - Check another user's privileges
        "grant_reader_privileges": "_grant_reader_privileges",  # 15 JAN 2026 - Grant SELECT to reader UMI
    }

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

    def handle_diagnostics(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated diagnostics endpoint (15 DEC 2025, updated 15 JAN 2026).

        GET /api/dbadmin/diagnostics?type={stats|enums|functions|all|config|errors|geo_integrity|user_privileges}
        GET /api/dbadmin/diagnostics?type=lineage&job_id={job_id}
        GET /api/dbadmin/diagnostics?type=user_privileges&username={username}
        POST /api/dbadmin/diagnostics?type=grant_reader_privileges

        Query Parameters:
            type: Diagnostic type (required)
                - stats: Database statistics
                - enums: PostgreSQL enum diagnostics
                - functions: Test PostgreSQL functions
                - all: All diagnostics combined
                - config: Configuration audit
                - lineage: ETL lineage (requires job_id)
                - errors: Error aggregation
                - geo_integrity: Geo schema TiPG compatibility check
                - user_privileges: Check another user's privileges (requires username)
                - grant_reader_privileges: Grant SELECT to reader UMI (POST only)
            job_id: Required when type=lineage
            username: Required when type=user_privileges
            schema: For user_privileges type (default: geo)
            hours: For errors type (default: 24)
            limit: For errors type (default: 10)

        Returns:
            JSON response with diagnostic results
        """
        try:
            diag_type = req.params.get('type', 'all')

            logger.info(f"📥 Diagnostics request: type={diag_type}")

            # Validate type parameter
            if diag_type not in self.OPERATIONS:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f"Invalid diagnostic type: '{diag_type}'",
                        'valid_types': list(self.OPERATIONS.keys()),
                        'usage': 'GET /api/dbadmin/diagnostics?type={type}',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            # Special handling for lineage (requires job_id)
            if diag_type == 'lineage':
                job_id = req.params.get('job_id')
                if not job_id:
                    return func.HttpResponse(
                        body=json.dumps({
                            'error': "job_id parameter required for lineage diagnostic",
                            'usage': 'GET /api/dbadmin/diagnostics?type=lineage&job_id={job_id}',
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }),
                        status_code=400,
                        mimetype='application/json'
                    )
                return self._get_etl_lineage(req, job_id)

            # Dispatch to handler method from registry
            handler_method = getattr(self, self.OPERATIONS[diag_type])
            return handler_method(req)

        except Exception as e:
            logger.error(f"❌ Error in handle_diagnostics: {e}")
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

        GET /api/dbadmin/stats

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
                            relname as tablename,
                            n_tup_ins as inserts,
                            n_tup_upd as updates,
                            n_tup_del as deletes,
                            n_live_tup as live_rows,
                            n_dead_tup as dead_rows
                        FROM pg_stat_user_tables
                        WHERE schemaname = %s
                        ORDER BY relname
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
                            relname as tablename,
                            indexrelname as indexname,
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

        GET /api/dbadmin/diagnostics/enums

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
                    # NOTE: SHOW returns a dict with 'search_path' key due to dict_row
                    cursor.execute("SHOW search_path")
                    search_path_row = cursor.fetchone()
                    diagnostics["current_search_path"] = search_path_row['search_path'] if search_path_row else "unknown"

                    # Check if app schema exists
                    # NOTE: Access by column alias due to dict_row
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.schemata
                            WHERE schema_name = %s
                        ) as app_schema_exists
                    """, (self.config.app_schema,))
                    schema_row = cursor.fetchone()
                    diagnostics["app_schema_exists"] = schema_row['app_schema_exists'] if schema_row else False

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

        GET /api/dbadmin/diagnostics/functions

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

        GET /api/dbadmin/diagnostics/all

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


    def _get_config_audit(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get configuration values with their sources (07 DEC 2025).

        GET /api/dbadmin/diagnostics/config

        Returns all configuration values indicating whether each came from
        environment variable or default. Secrets are masked.

        Returns:
            {
                "config": {
                    "storage_account_name": {
                        "value": "rmhazuregeo",
                        "source": "environment",
                        "env_var": "STORAGE_ACCOUNT_NAME",
                        "is_default": false
                    },
                    ...
                },
                "debug_mode": true,
                "environment": "dev",
                "timestamp": "..."
            }
        """
        logger.info("🔧 Getting configuration audit")
        import os
        from config.defaults import AzureDefaults, DatabaseDefaults, StorageDefaults

        try:
            config_audit = {}

            # Azure resources (MUST override for new tenant)
            # NOTE: STORAGE_ACCOUNT_NAME removed 08 DEC 2025 - use zone-specific accounts instead
            # NOTE: managed_identity_name renamed to managed_identity_admin_name 08 DEC 2025
            # NOTE (15 JAN 2026): managed_identity_reader_name added for TiPG/TiTiler docker app
            azure_configs = [
                ("bronze_storage_account", "BRONZE_STORAGE_ACCOUNT", StorageDefaults.DEFAULT_ACCOUNT_NAME),
                ("managed_identity_admin_name", "DB_ADMIN_MANAGED_IDENTITY_NAME", AzureDefaults.MANAGED_IDENTITY_NAME),
                ("managed_identity_reader_name", "DB_READER_MANAGED_IDENTITY_NAME", None),  # Optional reader UMI
                ("titiler_base_url", "TITILER_BASE_URL", AzureDefaults.TITILER_BASE_URL),
                ("ogc_stac_app_url", "OGC_STAC_APP_URL", AzureDefaults.OGC_STAC_APP_URL),
                ("etl_app_url", "ETL_APP_URL", AzureDefaults.ETL_APP_URL),
            ]

            for config_name, env_var, default_value in azure_configs:
                env_value = os.environ.get(env_var)
                actual_value = env_value if env_value else default_value
                is_default = env_value is None

                config_audit[config_name] = {
                    "value": actual_value,
                    "source": "default" if is_default else "environment",
                    "env_var": env_var,
                    "is_default": is_default,
                    "default_class": "AzureDefaults" if is_default else None
                }

            # Database configs
            db_configs = [
                ("postgis_host", "POSTGIS_HOST", None),  # No default - must be set
                ("postgis_database", "POSTGIS_DATABASE", None),
                ("postgis_user", "POSTGIS_USER", None),
                ("postgis_port", "POSTGIS_PORT", str(DatabaseDefaults.PORT)),
                ("postgis_schema", "POSTGIS_SCHEMA", DatabaseDefaults.POSTGIS_SCHEMA),
                ("app_schema", "APP_SCHEMA", DatabaseDefaults.APP_SCHEMA),
            ]

            for config_name, env_var, default_value in db_configs:
                env_value = os.environ.get(env_var)
                if default_value is not None:
                    actual_value = env_value if env_value else default_value
                    is_default = env_value is None
                else:
                    actual_value = env_value if env_value else "[NOT SET - REQUIRED]"
                    is_default = False  # No default means it's required

                # Mask sensitive values
                display_value = actual_value
                if "password" in config_name.lower() or "secret" in config_name.lower():
                    display_value = "***MASKED***" if actual_value else "[NOT SET]"

                config_audit[config_name] = {
                    "value": display_value,
                    "source": "default" if is_default else "environment",
                    "env_var": env_var,
                    "is_default": is_default,
                    "default_class": "DatabaseDefaults" if is_default and default_value else None
                }

            # Observability mode (10 JAN 2026 - F7.12.C Flag Consolidation)
            from config import get_config
            config = get_config()
            observability_enabled = config.is_observability_enabled()

            result = {
                "config": config_audit,
                "observability_mode": observability_enabled,
                "log_level": os.environ.get("LOG_LEVEL", "INFO"),
                "environment": os.environ.get("ENVIRONMENT", "dev"),
                "using_defaults_count": sum(1 for c in config_audit.values() if c.get("is_default")),
                "from_environment_count": sum(1 for c in config_audit.values() if not c.get("is_default")),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Config audit completed: {result['using_defaults_count']} defaults, {result['from_environment_count']} from env")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting config audit: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_etl_lineage(self, req: func.HttpRequest, job_id: str) -> func.HttpResponse:
        """
        Get full ETL lineage for a job (07 DEC 2025).

        GET /api/dbadmin/diagnostics/lineage/{job_id}

        Returns the complete data lineage: source → processing → destination → STAC.

        Returns:
            {
                "job_id": "abc123...",
                "job_type": "process_vector",
                "status": "completed",
                "source": {
                    "container": "bronze-vectors",
                    "blob": "parks.geojson",
                    "size_mb": 15.2
                },
                "destination": {
                    "schema": "geo",
                    "table": "parks_2024_v1",
                    "rows_created": 1523
                },
                "stac": {
                    "collection_id": "vectors",
                    "item_id": "parks-2024-v1"
                },
                "tasks": [...],
                "timeline": {...}
            }
        """
        logger.info(f"🔍 Getting ETL lineage for job: {job_id}")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            lineage = {"job_id": job_id}

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get job record
                    cursor.execute(f"""
                        SELECT id, job_type, status, stage, parameters, metadata, result_data,
                               created_at, updated_at
                        FROM {self.config.app_schema}.jobs
                        WHERE id = %s
                    """, (job_id,))
                    job_row = cursor.fetchone()

                    if not job_row:
                        return func.HttpResponse(
                            body=json.dumps({
                                'error': f'Job not found: {job_id}',
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }),
                            status_code=404,
                            mimetype='application/json'
                        )

                    lineage["job_type"] = job_row["job_type"]
                    lineage["status"] = job_row["status"]
                    lineage["stage"] = job_row["stage"]

                    # Extract source info from parameters
                    params = job_row["parameters"] or {}
                    lineage["source"] = {
                        "container": params.get("container_name") or params.get("source_container"),
                        "blob": params.get("blob_name") or params.get("blob_path"),
                        "file_path": params.get("file_path"),
                    }
                    # Remove None values
                    lineage["source"] = {k: v for k, v in lineage["source"].items() if v}

                    # Extract destination info
                    lineage["destination"] = {
                        "schema": params.get("schema_name") or params.get("target_schema") or "geo",
                        "table": params.get("table_name") or params.get("target_table"),
                        "output_container": params.get("output_container") or params.get("destination_container"),
                        "output_path": params.get("output_path") or params.get("cog_output_path"),
                    }
                    lineage["destination"] = {k: v for k, v in lineage["destination"].items() if v}

                    # Extract STAC info from result_data or metadata
                    result_data = job_row["result_data"] or {}
                    metadata = job_row["metadata"] or {}
                    lineage["stac"] = {
                        "collection_id": params.get("collection_id") or result_data.get("collection_id"),
                        "item_id": result_data.get("stac_item_id") or result_data.get("item_id"),
                        "stac_url": result_data.get("stac_url"),
                    }
                    lineage["stac"] = {k: v for k, v in lineage["stac"].items() if v}

                    # Timeline
                    lineage["timeline"] = {
                        "created_at": job_row["created_at"].isoformat() if job_row["created_at"] else None,
                        "updated_at": job_row["updated_at"].isoformat() if job_row["updated_at"] else None,
                        "duration_seconds": None
                    }
                    if job_row["created_at"] and job_row["updated_at"]:
                        duration = (job_row["updated_at"] - job_row["created_at"]).total_seconds()
                        lineage["timeline"]["duration_seconds"] = round(duration, 2)

                    # Get tasks for this job
                    cursor.execute(f"""
                        SELECT id, task_type, status, stage, parameters, result_data,
                               created_at, updated_at, retry_count
                        FROM {self.config.app_schema}.tasks
                        WHERE job_id = %s
                        ORDER BY stage, created_at
                    """, (job_id,))
                    task_rows = cursor.fetchall()

                    lineage["tasks"] = []
                    for task in task_rows:
                        task_info = {
                            "task_id": task["id"],
                            "task_type": task["task_type"],
                            "status": task["status"],
                            "stage": task["stage"],
                            "retry_count": task["retry_count"],
                            "created_at": task["created_at"].isoformat() if task["created_at"] else None,
                        }
                        # Include result summary if completed
                        if task["result_data"]:
                            result = task["result_data"]
                            task_info["result_summary"] = {
                                "success": result.get("success"),
                                "rows_processed": result.get("rows_processed") or result.get("row_count"),
                                "error": result.get("error") if not result.get("success") else None,
                            }
                            task_info["result_summary"] = {k: v for k, v in task_info["result_summary"].items() if v is not None}

                        lineage["tasks"].append(task_info)

                    lineage["task_summary"] = {
                        "total": len(task_rows),
                        "completed": len([t for t in task_rows if t["status"] == "completed"]),
                        "failed": len([t for t in task_rows if t["status"] == "failed"]),
                        "pending": len([t for t in task_rows if t["status"] in ("queued", "processing")]),
                    }

            lineage["timestamp"] = datetime.now(timezone.utc).isoformat()

            logger.info(f"✅ ETL lineage retrieved for job {job_id}: {lineage['task_summary']['total']} tasks")

            return func.HttpResponse(
                body=json.dumps(lineage, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting ETL lineage: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'job_id': job_id,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_error_aggregation(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get aggregated error statistics (07 DEC 2025).

        GET /api/dbadmin/diagnostics/errors?hours=24

        Returns error statistics grouped by job type and common error patterns.

        Returns:
            {
                "period": "24h",
                "total_jobs": 150,
                "failed_jobs": 12,
                "failure_rate": "8.0%",
                "by_job_type": {...},
                "common_errors": [...],
                "recent_failures": [...]
            }
        """
        hours = int(req.params.get('hours', '24'))
        limit = int(req.params.get('limit', '10'))

        logger.info(f"📊 Getting error aggregation for last {hours} hours")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            error_stats = {
                "period": f"{hours}h",
                "hours": hours,
            }

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Overall job statistics
                    cursor.execute(f"""
                        SELECT
                            COUNT(*) as total_jobs,
                            COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_jobs,
                            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_jobs,
                            COUNT(CASE WHEN status = 'processing' THEN 1 END) as processing_jobs,
                            COUNT(CASE WHEN status = 'queued' THEN 1 END) as queued_jobs
                        FROM {self.config.app_schema}.jobs
                        WHERE created_at >= NOW() - INTERVAL '%s hours'
                    """, (hours,))
                    stats_row = cursor.fetchone()

                    total = stats_row["total_jobs"] or 0
                    failed = stats_row["failed_jobs"] or 0

                    error_stats["total_jobs"] = total
                    error_stats["completed_jobs"] = stats_row["completed_jobs"] or 0
                    error_stats["failed_jobs"] = failed
                    error_stats["processing_jobs"] = stats_row["processing_jobs"] or 0
                    error_stats["queued_jobs"] = stats_row["queued_jobs"] or 0
                    error_stats["failure_rate"] = f"{(failed / total * 100):.1f}%" if total > 0 else "0%"

                    # Failures by job type
                    cursor.execute(f"""
                        SELECT
                            job_type,
                            COUNT(*) as total,
                            COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
                        FROM {self.config.app_schema}.jobs
                        WHERE created_at >= NOW() - INTERVAL '%s hours'
                        GROUP BY job_type
                        ORDER BY failed DESC, total DESC
                    """, (hours,))
                    type_rows = cursor.fetchall()

                    error_stats["by_job_type"] = {}
                    for row in type_rows:
                        job_total = row["total"] or 0
                        job_failed = row["failed"] or 0
                        error_stats["by_job_type"][row["job_type"]] = {
                            "total": job_total,
                            "completed": row["completed"] or 0,
                            "failed": job_failed,
                            "rate": f"{(job_failed / job_total * 100):.1f}%" if job_total > 0 else "0%"
                        }

                    # Task failures by task type
                    cursor.execute(f"""
                        SELECT
                            task_type,
                            COUNT(*) as total_failed,
                            COUNT(CASE WHEN retry_count > 0 THEN 1 END) as retried
                        FROM {self.config.app_schema}.tasks
                        WHERE status = 'failed'
                          AND created_at >= NOW() - INTERVAL '%s hours'
                        GROUP BY task_type
                        ORDER BY total_failed DESC
                        LIMIT %s
                    """, (hours, limit))
                    task_type_rows = cursor.fetchall()

                    error_stats["failed_task_types"] = []
                    for row in task_type_rows:
                        error_stats["failed_task_types"].append({
                            "task_type": row["task_type"],
                            "count": row["total_failed"],
                            "retried": row["retried"]
                        })

                    # Common error patterns (from result_data)
                    cursor.execute(f"""
                        SELECT
                            result_data->>'error' as error_message,
                            COUNT(*) as count
                        FROM {self.config.app_schema}.jobs
                        WHERE status = 'failed'
                          AND created_at >= NOW() - INTERVAL '%s hours'
                          AND result_data->>'error' IS NOT NULL
                        GROUP BY result_data->>'error'
                        ORDER BY count DESC
                        LIMIT %s
                    """, (hours, limit))
                    error_rows = cursor.fetchall()

                    error_stats["common_errors"] = []
                    for row in error_rows:
                        error_msg = row["error_message"]
                        # Truncate long error messages
                        if error_msg and len(error_msg) > 200:
                            error_msg = error_msg[:200] + "..."
                        error_stats["common_errors"].append({
                            "error": error_msg,
                            "count": row["count"]
                        })

                    # Recent failures with details
                    cursor.execute(f"""
                        SELECT
                            id,
                            job_type,
                            created_at,
                            updated_at,
                            result_data->>'error' as error_message,
                            parameters->>'container_name' as container,
                            parameters->>'blob_name' as blob
                        FROM {self.config.app_schema}.jobs
                        WHERE status = 'failed'
                          AND created_at >= NOW() - INTERVAL '%s hours'
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (hours, limit))
                    recent_rows = cursor.fetchall()

                    error_stats["recent_failures"] = []
                    for row in recent_rows:
                        error_msg = row["error_message"]
                        if error_msg and len(error_msg) > 200:
                            error_msg = error_msg[:200] + "..."
                        error_stats["recent_failures"].append({
                            "job_id": row["id"],
                            "job_type": row["job_type"],
                            "failed_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                            "error_summary": error_msg,
                            "source": f"{row['container']}/{row['blob']}" if row['container'] and row['blob'] else None
                        })

            error_stats["timestamp"] = datetime.now(timezone.utc).isoformat()

            logger.info(f"✅ Error aggregation completed: {error_stats['failed_jobs']}/{error_stats['total_jobs']} failed ({error_stats['failure_rate']})")

            return func.HttpResponse(
                body=json.dumps(error_stats, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting error aggregation: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


    def _get_geo_integrity(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get geo schema integrity validation (14 JAN 2026).

        GET /api/dbadmin/diagnostics?type=geo_integrity

        Validates geo schema tables for TiPG/OGC Features compatibility:
        - Untyped geometry columns (GEOMETRY without POLYGON, POINT, etc.)
        - Missing SRID (srid = 0 or NULL)
        - Missing spatial indexes
        - Tables not registered in geometry_columns view

        Returns:
            {
                "health_status": "HEALTHY|WARNING|DEGRADED",
                "total_tables": 15,
                "valid_tables": 12,
                "invalid_tables": 3,
                "tipg_compatible": 12,
                "tipg_incompatible": 3,
                "delete_candidates": ["geo.old_table1", "geo.bad_table2"],
                "summary": {...},
                "timestamp": "..."
            }
        """
        logger.info("🔍 Running geo schema integrity check")

        try:
            from core.diagnostics import GeoSchemaValidator

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                validator = GeoSchemaValidator(conn, schema='geo')
                report = validator.validate_all(include_row_counts=False)

            # Determine health status
            tipg_incompatible = report.get('tipg_incompatible', 0)
            invalid_count = report.get('invalid_tables', 0)

            # TiPG sync check
            tipg_sync = report.get('tipg_sync', {})
            missing_from_tipg = tipg_sync.get('missing_from_tipg', [])

            if tipg_incompatible > 0:
                health_status = "DEGRADED"
            elif invalid_count > 0 or missing_from_tipg:
                health_status = "WARNING"
            else:
                health_status = "HEALTHY"

            # Build response
            result = {
                "health_status": health_status,
                "total_tables": report.get('total_tables', 0),
                "valid_tables": report.get('valid_tables', 0),
                "invalid_tables": invalid_count,
                "tipg_compatible": report.get('tipg_compatible', 0),
                "tipg_incompatible": tipg_incompatible,
                "tipg_sync": {
                    "in_sync": tipg_sync.get('in_sync'),
                    "missing_from_tipg": missing_from_tipg,
                    "extra_in_tipg": tipg_sync.get('extra_in_tipg', []),
                    "geo_tables_count": tipg_sync.get('geo_tables_count', 0),
                    "tipg_collections_count": tipg_sync.get('tipg_collections_count', 0),
                    "geo_tables": tipg_sync.get('geo_tables', []),
                    "tipg_collections": tipg_sync.get('tipg_collections', []),
                    "tipg_url": tipg_sync.get('tipg_url'),
                    "error": tipg_sync.get('error')
                },
                "delete_candidates": [
                    t['full_name'] for t in report.get('tables', [])
                    if not t.get('is_tipg_compatible')
                ],
                "issues_by_type": report.get('summary', {}).get('issue_counts', {}),
                "geometry_types": report.get('summary', {}).get('geometry_types', {}),
                "srids": report.get('summary', {}).get('srids', {}),
                "tables_without_index": report.get('summary', {}).get('tables_without_index', 0),
                "issues_found": report.get('issues_found', []),
                # Full table details for debugging TiPG discovery issues
                "tables": [
                    {
                        "table_name": t.get('table_name'),
                        "full_name": t.get('full_name'),
                        "geometry_column": t.get('geometry_column'),
                        "geometry_type": t.get('geometry_type'),
                        "srid": t.get('srid'),
                        "has_spatial_index": t.get('has_spatial_index'),
                        "is_tipg_compatible": t.get('is_tipg_compatible'),
                        "issues": t.get('issues', [])
                    }
                    for t in report.get('tables', [])
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            logger.info(
                f"✅ Geo integrity check completed: "
                f"{result['tipg_compatible']}/{result['total_tables']} TiPG-compatible, "
                f"{len(result['delete_candidates'])} delete candidates"
            )

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error running geo integrity check: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


    def _get_user_privileges(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check another user's database privileges (14 JAN 2026).

        GET /api/dbadmin/diagnostics?type=user_privileges&username={username}

        Allows admin managed identity to check what privileges another user has.
        Useful for diagnosing permission issues with reader identities in QA.

        Query Parameters:
            username: PostgreSQL username to check (required)
            schema: Schema to check table privileges for (default: geo)

        Returns:
            {
                "username": "migeoetldbreaderqa",
                "schema": "geo",
                "user_exists": true,
                "role_memberships": ["pgstac_read"],
                "table_privileges": {
                    "table1": {"select": true, "insert": false, ...},
                    ...
                },
                "tables_with_select": 15,
                "tables_without_select": 2,
                "missing_select": ["table_name1", "table_name2"],
                "fix_sql": "GRANT SELECT ON geo.table1 TO username;...",
                "timestamp": "..."
            }
        """
        username = req.params.get('username')
        schema = req.params.get('schema', 'geo')

        if not username:
            return func.HttpResponse(
                body=json.dumps({
                    'error': "username parameter required",
                    'usage': 'GET /api/dbadmin/diagnostics?type=user_privileges&username={username}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.info(f"🔍 Checking privileges for user '{username}' in schema '{schema}'")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            result = {
                "username": username,
                "schema": schema,
                "checked_by": None,
            }

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Who is running this check?
                    cursor.execute("SELECT current_user")
                    result["checked_by"] = cursor.fetchone()['current_user']

                    # 1. Check if user exists
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                        [username]
                    )
                    user_exists = cursor.fetchone()['exists']
                    result["user_exists"] = user_exists

                    if not user_exists:
                        result["error"] = f"User '{username}' does not exist in database"
                        result["timestamp"] = datetime.now(timezone.utc).isoformat()
                        return func.HttpResponse(
                            body=json.dumps(result, indent=2),
                            status_code=200,
                            mimetype='application/json'
                        )

                    # 2. Get role memberships (what roles is this user a member of?)
                    cursor.execute("""
                        SELECT r.rolname as role_name
                        FROM pg_auth_members m
                        JOIN pg_roles r ON m.roleid = r.oid
                        JOIN pg_roles member ON m.member = member.oid
                        WHERE member.rolname = %s
                        ORDER BY r.rolname
                    """, [username])
                    roles = [row['role_name'] for row in cursor.fetchall()]
                    result["role_memberships"] = roles

                    # 3. Get all tables in schema
                    cursor.execute("""
                        SELECT c.relname as table_name
                        FROM pg_class c
                        JOIN pg_namespace n ON c.relnamespace = n.oid
                        WHERE n.nspname = %s
                        AND c.relkind = 'r'
                        ORDER BY c.relname
                    """, [schema])
                    tables = [row['table_name'] for row in cursor.fetchall()]
                    result["total_tables_in_schema"] = len(tables)

                    # 4. Check privileges for each table using has_table_privilege
                    # Note: has_table_privilege(user, table, privilege) can be called by any user
                    table_privileges = {}
                    tables_with_select = []
                    tables_without_select = []

                    for table in tables:
                        full_table = f"{schema}.{table}"
                        cursor.execute("""
                            SELECT
                                has_table_privilege(%s, %s, 'SELECT') as can_select,
                                has_table_privilege(%s, %s, 'INSERT') as can_insert,
                                has_table_privilege(%s, %s, 'UPDATE') as can_update,
                                has_table_privilege(%s, %s, 'DELETE') as can_delete
                        """, [username, full_table, username, full_table,
                              username, full_table, username, full_table])
                        priv_row = cursor.fetchone()

                        table_privileges[table] = {
                            "select": priv_row['can_select'],
                            "insert": priv_row['can_insert'],
                            "update": priv_row['can_update'],
                            "delete": priv_row['can_delete'],
                        }

                        if priv_row['can_select']:
                            tables_with_select.append(table)
                        else:
                            tables_without_select.append(table)

                    result["table_privileges"] = table_privileges
                    result["tables_with_select"] = len(tables_with_select)
                    result["tables_without_select"] = len(tables_without_select)
                    result["missing_select"] = tables_without_select

                    # 5. Generate fix SQL if there are missing privileges
                    if tables_without_select:
                        fix_lines = [
                            f"-- Fix SELECT privileges for {username} in {schema} schema",
                            f"-- Run as database admin/owner",
                            ""
                        ]
                        for table in tables_without_select:
                            fix_lines.append(f"GRANT SELECT ON {schema}.{table} TO {username};")

                        # Also suggest default privileges
                        fix_lines.extend([
                            "",
                            "-- To automatically grant SELECT on future tables:",
                            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {username};",
                        ])

                        result["fix_sql"] = "\n".join(fix_lines)
                    else:
                        result["fix_sql"] = None

                    # 6. Check default privileges (what will future tables get?)
                    cursor.execute("""
                        SELECT
                            defaclrole::regrole::text as grantor,
                            defaclobjtype as object_type,
                            defaclacl::text as acl
                        FROM pg_default_acl d
                        JOIN pg_namespace n ON d.defaclnamespace = n.oid
                        WHERE n.nspname = %s
                    """, [schema])
                    default_privs = cursor.fetchall()
                    result["default_privileges"] = [
                        {
                            "grantor": row['grantor'],
                            "object_type": "table" if row['object_type'] == 'r' else row['object_type'],
                            "acl": row['acl']
                        }
                        for row in default_privs
                    ]

            result["timestamp"] = datetime.now(timezone.utc).isoformat()

            # Determine status
            if result["tables_without_select"] == 0:
                result["status"] = "OK"
                logger.info(f"✅ User '{username}' has SELECT on all {len(tables)} tables in {schema}")
            else:
                result["status"] = "MISSING_PRIVILEGES"
                logger.warning(
                    f"⚠️ User '{username}' missing SELECT on {result['tables_without_select']} "
                    f"of {len(tables)} tables in {schema}"
                )

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error checking user privileges: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'username': username,
                    'schema': schema,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


    def _grant_reader_privileges(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Grant SELECT privileges to reader managed identity (15 JAN 2026).

        POST /api/dbadmin/diagnostics?type=grant_reader_privileges

        Grants the reader UMI (configured via DB_READER_MANAGED_IDENTITY_NAME) SELECT
        access to the geo and h3 schemas. This is idempotent - it checks pg_default_acl
        to see if default privileges are already configured before executing GRANTs.

        The reader identity is used by TiPG/TiTiler docker container which needs to
        read vector tables but doesn't need write access.

        Grants:
            - USAGE on geo and h3 schemas
            - SELECT on all existing tables in geo and h3 schemas
            - ALTER DEFAULT PRIVILEGES for SELECT on future tables

        Returns:
            {
                "reader_identity": "migeoetldbreaderqa",
                "status": "ALREADY_CONFIGURED|GRANTS_APPLIED|NOT_CONFIGURED",
                "schemas_processed": ["geo", "h3"],
                "existing_default_privileges": [...],
                "grants_executed": [...],
                "timestamp": "..."
            }
        """
        from psycopg import sql

        logger.info("🔑 Processing grant_reader_privileges request")

        # Require POST for this operation (modifies database)
        if req.method != "POST":
            return func.HttpResponse(
                body=json.dumps({
                    'error': "grant_reader_privileges requires POST method",
                    'usage': 'POST /api/dbadmin/diagnostics?type=grant_reader_privileges',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=405,
                mimetype='application/json'
            )

        try:
            # Get reader identity from config
            reader_identity = self.config.database.managed_identity_reader_name

            if not reader_identity:
                return func.HttpResponse(
                    body=json.dumps({
                        'status': 'NOT_CONFIGURED',
                        'error': "DB_READER_MANAGED_IDENTITY_NAME environment variable not set",
                        'hint': "Set DB_READER_MANAGED_IDENTITY_NAME to the PostgreSQL username for the reader managed identity",
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            result = {
                "reader_identity": reader_identity,
                "admin_identity": self.config.database.managed_identity_admin_name,
                "schemas_processed": ["geo", "h3"],
                "existing_default_privileges": [],
                "grants_executed": [],
                "status": None,
            }

            schemas_to_grant = ["geo", "h3"]

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check who we are connected as
                    cursor.execute("SELECT current_user")
                    result["executed_by"] = cursor.fetchone()['current_user']

                    # 1. Check if user exists
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = %s) as exists",
                        [reader_identity]
                    )
                    user_exists = cursor.fetchone()['exists']

                    if not user_exists:
                        return func.HttpResponse(
                            body=json.dumps({
                                'status': 'USER_NOT_FOUND',
                                'reader_identity': reader_identity,
                                'error': f"User '{reader_identity}' does not exist in database",
                                'hint': "Create the user first with pgaadauth_create_principal()",
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }),
                            status_code=400,
                            mimetype='application/json'
                        )

                    # 2. Check existing default privileges in pg_default_acl
                    # Look for entries where the reader_identity appears in the ACL
                    cursor.execute("""
                        SELECT
                            n.nspname as schema_name,
                            d.defaclrole::regrole::text as grantor,
                            d.defaclobjtype as object_type,
                            d.defaclacl::text as acl
                        FROM pg_default_acl d
                        JOIN pg_namespace n ON d.defaclnamespace = n.oid
                        WHERE n.nspname IN ('geo', 'h3')
                        AND d.defaclobjtype = 'r'  -- 'r' = relation (table)
                    """)
                    existing_defaults = cursor.fetchall()

                    # Check if reader already has default SELECT privilege
                    reader_has_default_select = {}
                    for row in existing_defaults:
                        schema = row['schema_name']
                        acl = row['acl'] or ""
                        result["existing_default_privileges"].append({
                            "schema": schema,
                            "grantor": row['grantor'],
                            "acl": acl
                        })
                        # ACL format: {grantee=privileges/grantor,...}
                        # SELECT privilege is represented as 'r' (read)
                        # e.g., {reader_identity=r/admin_identity}
                        if f"{reader_identity}=r" in acl or f'"{reader_identity}"=r' in acl:
                            reader_has_default_select[schema] = True

                    # 3. Determine what needs to be granted
                    schemas_needing_grants = [s for s in schemas_to_grant if s not in reader_has_default_select]
                    schemas_already_configured = [s for s in schemas_to_grant if s in reader_has_default_select]

                    if not schemas_needing_grants:
                        # Already configured
                        result["status"] = "ALREADY_CONFIGURED"
                        result["schemas_already_configured"] = schemas_already_configured
                        result["message"] = f"Reader '{reader_identity}' already has DEFAULT PRIVILEGES for SELECT on schemas: {', '.join(schemas_already_configured)}"
                        result["note"] = "No grants executed - privileges already in place"
                        logger.info(f"✅ Reader '{reader_identity}' already has default SELECT privileges on: {', '.join(schemas_already_configured)}")
                    else:
                        # 4. Execute grants (only for schemas that need them, but grant all for consistency)
                        reader_ident = sql.Identifier(reader_identity)

                        # Log what's already configured vs what needs grants
                        if schemas_already_configured:
                            result["schemas_already_configured"] = schemas_already_configured
                            logger.info(f"ℹ️ Reader '{reader_identity}' already has privileges on: {', '.join(schemas_already_configured)}")

                        result["schemas_granted"] = schemas_needing_grants
                        logger.info(f"🔑 Granting privileges to '{reader_identity}' on: {', '.join(schemas_needing_grants)}")

                        for schema in schemas_to_grant:
                            schema_ident = sql.Identifier(schema)

                            # Grant USAGE on schema
                            grant_usage = sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema_ident, reader_ident)
                            cursor.execute(grant_usage)
                            result["grants_executed"].append(f"GRANT USAGE ON SCHEMA {schema} TO {reader_identity}")

                            # Grant SELECT on all existing tables
                            grant_select = sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema_ident, reader_ident)
                            cursor.execute(grant_select)
                            result["grants_executed"].append(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {reader_identity}")

                            # Set default privileges for future tables
                            alter_default = sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(schema_ident, reader_ident)
                            cursor.execute(alter_default)
                            result["grants_executed"].append(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {reader_identity}")

                        conn.commit()
                        result["status"] = "GRANTS_APPLIED"
                        result["message"] = f"Granted SELECT privileges to '{reader_identity}' on schemas: {', '.join(schemas_to_grant)}"
                        logger.info(f"✅ Applied {len(result['grants_executed'])} grants for reader '{reader_identity}' on schemas: {', '.join(schemas_to_grant)}")

            result["timestamp"] = datetime.now(timezone.utc).isoformat()

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error granting reader privileges: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'reader_identity': reader_identity if 'reader_identity' in dir() else None,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


# Create singleton instance
admin_db_diagnostics_trigger = AdminDbDiagnosticsTrigger.instance()
