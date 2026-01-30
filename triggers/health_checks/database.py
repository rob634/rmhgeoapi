# ============================================================================
# DATABASE HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Plugin - Database components
# PURPOSE: PostgreSQL, PgSTAC, DuckDB, Schema health checks
# CREATED: 29 JAN 2026
# MIGRATED: 29 JAN 2026 (Phase 6)
# EXPORTS: DatabaseHealthChecks
# DEPENDENCIES: base.HealthCheckPlugin, psycopg, config
# ============================================================================
"""
Database Health Checks Plugin.

Monitors database components:
- PostgreSQL connectivity and configuration
- PgSTAC (STAC extension) status
- DuckDB analytical engine
- Schema summary and table counts
- Public database (external OGC Features)
- System reference tables (admin0 boundaries)

These checks verify database health and data availability.
"""

import os
from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class DatabaseHealthChecks(HealthCheckPlugin):
    """
    Health checks for database components.

    Checks:
    - database: PostgreSQL connectivity
    - database_config: Configuration validation
    - duckdb: Analytical engine status
    - pgstac: STAC extension health
    - system_reference_tables: Admin0 boundaries
    - schema_summary: Table/row counts
    - public_database: External OGC Features DB
    """

    name = "database"
    description = "PostgreSQL, PgSTAC, DuckDB, and schema health"
    priority = 40  # Run after infrastructure checks

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return database health checks."""
        return [
            ("database", self.check_database),
            ("database_config", self.check_database_configuration),
            ("duckdb", self.check_duckdb),
            ("pgstac", self.check_pgstac),
            ("system_reference_tables", self.check_system_reference_tables),
            ("schema_summary", self.check_schema_summary),
            ("public_database", self.check_public_database),
        ]

    def is_enabled(self, config) -> bool:
        """Database checks are always enabled."""
        return True

    # =========================================================================
    # CHECK: Database
    # =========================================================================

    def check_database(self) -> Dict[str, Any]:
        """
        Enhanced PostgreSQL database health check with query metrics.

        Uses PostgreSQLRepository which respects USE_MANAGED_IDENTITY setting.

        Returns:
            Dict with database connectivity and schema status
        """
        def check_pg():
            import psycopg
            import time
            from config import get_config
            from infrastructure.postgresql import PostgreSQLRepository

            config = get_config()
            start_time = time.time()

            try:
                repo = PostgreSQLRepository(config=config)
                conn_str = repo.conn_string
            except Exception as repo_error:
                return {
                    "component": "database",
                    "status": "unhealthy",
                    "error": f"Failed to initialize PostgreSQL repository: {str(repo_error)}",
                    "error_type": type(repo_error).__name__,
                    "checked_at": time.time()
                }

            with psycopg.connect(conn_str, autocommit=True) as conn:
                with conn.cursor() as cur:
                    connection_time_ms = round((time.time() - start_time) * 1000, 2)

                    # PostgreSQL version
                    cur.execute("SELECT version()")
                    pg_version = cur.fetchone()[0]

                    # PostGIS version
                    cur.execute("SELECT PostGIS_Version()")
                    postgis_version = cur.fetchone()[0]

                    # Check app schema exists
                    try:
                        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (config.app_schema,))
                        app_schema_exists = cur.fetchone() is not None
                    except Exception:
                        app_schema_exists = False

                    # Check postgis schema exists
                    try:
                        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (config.postgis_schema,))
                        postgis_schema_exists = cur.fetchone() is not None
                    except Exception:
                        postgis_schema_exists = False

                    # Count STAC items using pg_stat for performance
                    try:
                        cur.execute("""
                            SELECT n_live_tup FROM pg_stat_user_tables
                            WHERE schemaname = %s AND relname = 'items'
                        """, (config.postgis_schema,))
                        result = cur.fetchone()
                        stac_count = result[0] if result else 0
                    except Exception:
                        stac_count = "unknown"

                    # Check app tables exist
                    app_tables_status = {}
                    table_management_results = {}

                    if app_schema_exists:
                        try:
                            for table_name in ['jobs', 'tasks']:
                                cur.execute("""
                                    SELECT EXISTS (
                                        SELECT FROM information_schema.tables
                                        WHERE table_schema = %s
                                        AND table_name = %s
                                    )
                                """, (config.app_schema, table_name))
                                table_exists = cur.fetchone()[0]
                                app_tables_status[table_name] = table_exists
                                table_management_results[table_name] = "exists" if table_exists else "missing"
                        except Exception as table_check_error:
                            table_management_results['table_check_error'] = f"error: {str(table_check_error)}"
                            app_tables_status['jobs'] = False
                            app_tables_status['tasks'] = False

                    # Detailed schema inspection
                    detailed_schema_info = {}

                    # Inspect table columns
                    try:
                        for table_name in ['jobs', 'tasks']:
                            cur.execute("""
                                SELECT column_name, data_type, is_nullable, column_default
                                FROM information_schema.columns
                                WHERE table_schema = %s AND table_name = %s
                                ORDER BY ordinal_position
                            """, (config.app_schema, table_name))

                            columns = cur.fetchall()
                            detailed_schema_info[f"{table_name}_columns"] = [
                                {
                                    "column_name": col[0],
                                    "data_type": col[1],
                                    "is_nullable": col[2],
                                    "column_default": col[3]
                                } for col in columns
                            ]
                    except Exception as col_error:
                        detailed_schema_info['columns_inspection_error'] = f"Column inspection failed: {str(col_error)}"

                    # Inspect PostgreSQL function signatures
                    try:
                        cur.execute("""
                            SELECT
                                routine_name,
                                data_type as return_type,
                                routine_definition
                            FROM information_schema.routines
                            WHERE routine_schema = %s
                            AND routine_name IN ('check_job_completion', 'complete_task_and_check_stage', 'advance_job_stage')
                            ORDER BY routine_name
                        """, (config.app_schema,))

                        functions = cur.fetchall()
                        detailed_schema_info['postgresql_functions'] = [
                            {
                                "function_name": func[0],
                                "return_type": func[1],
                                "definition_snippet": func[2][:200] + "..." if func[2] and len(func[2]) > 200 else func[2]
                            } for func in functions
                        ]
                    except Exception as func_sig_error:
                        detailed_schema_info['function_signature_error'] = f"Function signature inspection failed: {str(func_sig_error)}"

                    # Test function call
                    try:
                        with conn.transaction():
                            cur.execute(f"SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {config.app_schema}.check_job_completion('test_job_id')")
                            detailed_schema_info['function_test'] = "SUCCESS - Function signature matches query"
                    except Exception as func_error:
                        detailed_schema_info['function_test'] = f"ERROR: {str(func_error)}"
                        detailed_schema_info['function_error_type'] = type(func_error).__name__

                    query_metrics = {
                        "connection_time_ms": connection_time_ms,
                        "note": "Detailed metrics available at /api/dbadmin/stats",
                        "metrics_removed_reason": "Performance optimization - health check should be <5s"
                    }

                    tables_ready = all(status is True for status in app_tables_status.values()) if app_tables_status else False

                    # Build error message if needed
                    error_msg = None
                    impact_msg = None
                    if not app_schema_exists:
                        error_msg = f"CRITICAL: App schema '{config.app_schema}' does not exist - run rebuild"
                        impact_msg = "Job/task orchestration completely unavailable"
                    elif not tables_ready:
                        error_msg = f"App schema exists but required tables missing: {table_management_results}"
                        impact_msg = "Job/task orchestration may fail"

                    result = {
                        "postgresql_version": pg_version.split()[0],
                        "postgis_version": postgis_version,
                        "connection": "successful",
                        "connection_time_ms": connection_time_ms,
                        "schema_health": {
                            "app_schema_name": config.app_schema,
                            "app_schema_exists": app_schema_exists,
                            "app_schema_critical": True,
                            "postgis_schema_name": config.postgis_schema,
                            "postgis_schema_exists": postgis_schema_exists,
                            "app_tables": app_tables_status if app_schema_exists else "schema_not_found"
                        },
                        "table_management": {
                            "auto_creation_enabled": True,
                            "operations_performed": table_management_results,
                            "tables_ready": tables_ready
                        },
                        "stac_data": {
                            "items_count": stac_count,
                            "schema_accessible": postgis_schema_exists
                        },
                        "detailed_schema_inspection": detailed_schema_info,
                        "query_performance": query_metrics
                    }

                    if error_msg:
                        result["error"] = error_msg
                        result["impact"] = impact_msg
                        result["fix"] = "POST /api/dbadmin/maintenance?action=rebuild&confirm=yes"

                    return result

        return self.check_component_health(
            "database",
            check_pg,
            description="PostgreSQL/PostGIS database connectivity and query metrics"
        )

    # =========================================================================
    # CHECK: Database Configuration
    # =========================================================================

    def check_database_configuration(self) -> Dict[str, Any]:
        """
        Check PostgreSQL database configuration.

        Returns:
            Dict with database configuration status
        """
        def check_db_config():
            from config import get_config

            config = get_config()

            required_env_vars = {
                "POSTGIS_DATABASE": os.getenv("POSTGIS_DATABASE"),
                "POSTGIS_HOST": os.getenv("POSTGIS_HOST"),
                "POSTGIS_USER": os.getenv("POSTGIS_USER"),
                "POSTGIS_PORT": os.getenv("POSTGIS_PORT")
            }

            optional_env_vars = {
                "KEY_VAULT": os.getenv("KEY_VAULT"),
                "KEY_VAULT_DATABASE_SECRET": os.getenv("KEY_VAULT_DATABASE_SECRET"),
                "POSTGIS_PASSWORD": bool(os.getenv("POSTGIS_PASSWORD")),
                "POSTGIS_SCHEMA": os.getenv("POSTGIS_SCHEMA", "geo"),
                "APP_SCHEMA": os.getenv("APP_SCHEMA", "app")
            }

            missing_vars = []
            present_vars = {}

            for var_name, var_value in required_env_vars.items():
                if var_value:
                    present_vars[var_name] = var_value
                else:
                    missing_vars.append(var_name)

            config_values = {
                "postgis_host": config.postgis_host,
                "postgis_port": config.postgis_port,
                "postgis_user": config.postgis_user,
                "postgis_database": config.postgis_database,
                "postgis_schema": config.postgis_schema,
                "app_schema": config.app_schema,
                "key_vault_name": config.key_vault_name,
                "key_vault_database_secret": config.key_vault_database_secret,
                "postgis_password_configured": bool(config.postgis_password)
            }

            return {
                "required_env_vars_present": present_vars,
                "missing_required_vars": missing_vars,
                "optional_env_vars": optional_env_vars,
                "loaded_config_values": config_values,
                "configuration_complete": len(missing_vars) == 0
            }

        return self.check_component_health(
            "database_config",
            check_db_config,
            description="PostgreSQL connection environment variables and configuration"
        )

    # =========================================================================
    # CHECK: DuckDB
    # =========================================================================

    def check_duckdb(self) -> Dict[str, Any]:
        """
        Check DuckDB analytical engine health (optional component).

        Returns:
            Dict with DuckDB health status
        """
        def check_duckdb_inner():
            try:
                from infrastructure.factory import RepositoryFactory

                duckdb_repo = RepositoryFactory.create_duckdb_repository()
                health_result = duckdb_repo.health_check()

                health_result["component_type"] = "analytical_engine"
                health_result["optional"] = True
                health_result["purpose"] = "Serverless Parquet queries and GeoParquet exports"

                return health_result

            except ImportError as e:
                return {
                    "status": "not_installed",
                    "optional": True,
                    "message": "DuckDB not installed (optional dependency)",
                    "install_command": "pip install duckdb>=1.1.0 pyarrow>=10.0.0",
                    "impact": "GeoParquet exports and serverless blob queries unavailable"
                }
            except Exception as e:
                import traceback
                return {
                    "status": "error",
                    "optional": True,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "Analytical queries and GeoParquet exports unavailable"
                }

        return self.check_component_health(
            "duckdb",
            check_duckdb_inner,
            description="DuckDB analytical engine for serverless queries and GeoParquet exports"
        )

    # =========================================================================
    # CHECK: PgSTAC
    # =========================================================================

    def check_pgstac(self) -> Dict[str, Any]:
        """
        Check PgSTAC (PostgreSQL STAC extension) health.

        Returns:
            Dict with PgSTAC health status
        """
        def check_pgstac_inner():
            from infrastructure.postgresql import PostgreSQLRepository
            from config import get_config

            config = get_config()
            repo = PostgreSQLRepository(schema_name='pgstac')

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Check schema exists
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'pgstac') as schema_exists"
                        )
                        schema_exists = cur.fetchone()['schema_exists']

                        if not schema_exists:
                            return {
                                "schema_exists": False,
                                "installed": False,
                                "error": "PgSTAC schema not found - run /api/stac/setup to install",
                                "impact": "STAC collections and items cannot be created"
                            }

                        # Get PgSTAC version
                        pgstac_version = None
                        try:
                            cur.execute("SELECT pgstac.get_version() as version")
                            pgstac_version = cur.fetchone()['version']
                        except Exception as ver_error:
                            pgstac_version = f"error: {str(ver_error)[:100]}"

                        # Check critical tables
                        critical_tables = {}
                        for table_name in ['collections', 'items', 'searches']:
                            cur.execute("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables
                                    WHERE table_schema = 'pgstac'
                                    AND table_name = %s
                                ) as table_exists
                            """, (table_name,))
                            table_exists = cur.fetchone()['table_exists']
                            critical_tables[table_name] = table_exists

                        # Get row counts using pg_stat
                        table_counts = {}

                        if critical_tables.get('collections', False):
                            try:
                                cur.execute("""
                                    SELECT n_live_tup FROM pg_stat_user_tables
                                    WHERE schemaname = 'pgstac' AND relname = 'collections'
                                """)
                                result = cur.fetchone()
                                table_counts['collections'] = result['n_live_tup'] if result else 0
                            except Exception:
                                table_counts['collections'] = "error"
                        else:
                            table_counts['collections'] = "table_missing"

                        if critical_tables.get('items', False):
                            try:
                                cur.execute("""
                                    SELECT n_live_tup FROM pg_stat_user_tables
                                    WHERE schemaname = 'pgstac' AND relname = 'items'
                                """)
                                result = cur.fetchone()
                                table_counts['items'] = result['n_live_tup'] if result else 0
                            except Exception:
                                table_counts['items'] = "error"
                        else:
                            table_counts['items'] = "table_missing"

                        searches_table_exists = critical_tables.get('searches', False)

                        # Check critical functions
                        critical_functions = {}
                        function_warnings = []

                        try:
                            cur.execute("""
                                SELECT p.proname
                                FROM pg_proc p
                                JOIN pg_namespace n ON p.pronamespace = n.oid
                                WHERE n.nspname = 'pgstac'
                                AND p.proname IN ('search_tohash', 'search_hash')
                            """)
                            functions_found = [row['proname'] for row in cur.fetchall()]

                            critical_functions['search_tohash'] = 'search_tohash' in functions_found
                            critical_functions['search_hash'] = 'search_hash' in functions_found

                            if searches_table_exists:
                                try:
                                    cur.execute("""
                                        SELECT column_name, is_generated
                                        FROM information_schema.columns
                                        WHERE table_schema = 'pgstac'
                                        AND table_name = 'searches'
                                        AND column_name = 'hash'
                                    """)
                                    hash_column = cur.fetchone()

                                    if hash_column and hash_column.get('is_generated') == 'ALWAYS':
                                        critical_functions['searches_hash_column_generated'] = True
                                    else:
                                        critical_functions['searches_hash_column_generated'] = False
                                        function_warnings.append("searches.hash is not a GENERATED column")
                                except Exception:
                                    critical_functions['searches_hash_column_generated'] = None

                            if not critical_functions['search_tohash']:
                                function_warnings.append("Missing function: pgstac.search_tohash()")
                            if not critical_functions['search_hash']:
                                function_warnings.append("Missing function: pgstac.search_hash()")

                        except Exception as func_error:
                            critical_functions['error'] = str(func_error)[:100]

                        all_tables_exist = all(critical_tables.values())
                        all_functions_exist = critical_functions.get('search_tohash', False) and critical_functions.get('search_hash', False)

                        result = {
                            "schema_exists": True,
                            "installed": True,
                            "pgstac_version": pgstac_version,
                            "critical_tables": critical_tables,
                            "searches_table_exists": searches_table_exists,
                            "critical_functions": critical_functions,
                            "table_counts": table_counts,
                            "all_critical_tables_present": all_tables_exist,
                            "all_critical_functions_present": all_functions_exist,
                            "criticality": "medium"
                        }

                        warnings = []

                        if not searches_table_exists:
                            warnings.append("pgstac.searches table missing - search registration will fail")

                        if not all_functions_exist:
                            warnings.extend(function_warnings)
                            warnings.append("Search registration will fail - run /api/dbadmin/maintenance?action=rebuild&confirm=yes")

                        if warnings:
                            result["warnings"] = warnings
                            result["impact"] = "Cannot register pgSTAC searches for TiTiler visualization"
                            result["fix"] = "POST /api/dbadmin/maintenance?action=rebuild&confirm=yes"
                            if not all_tables_exist or not all_functions_exist:
                                result["error"] = f"PgSTAC incomplete: tables_ok={all_tables_exist}, functions_ok={all_functions_exist}"

                        return result

            except Exception as e:
                import traceback
                return {
                    "schema_exists": False,
                    "installed": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "PgSTAC health check failed - STAC operations may be impacted"
                }

        return self.check_component_health(
            "pgstac",
            check_pgstac_inner,
            description="PgSTAC extension for STAC catalog storage and TiTiler integration"
        )

    # =========================================================================
    # CHECK: System Reference Tables
    # =========================================================================

    def check_system_reference_tables(self) -> Dict[str, Any]:
        """
        Check system reference tables required for spatial operations.

        Returns:
            Dict with system reference tables health status
        """
        def check_system_tables():
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository()

            admin0_table = None
            admin0_source = None
            promoted_dataset_info = None
            promote_error_msg = None

            try:
                from services.promote_service import PromoteService
                from core.models.promoted import SystemRole

                promote_service = PromoteService()
                promoted = promote_service.get_by_system_role(SystemRole.ADMIN0_BOUNDARIES.value)

                if promoted:
                    stac_id = promoted.get('stac_collection_id') or promoted.get('stac_item_id')
                    if stac_id:
                        try:
                            from infrastructure.pgstac_bootstrap import get_item_by_id
                            collection_id = 'system-vectors' if stac_id.startswith('postgis-') else None
                            stac_item = get_item_by_id(stac_id, collection_id=collection_id)
                            if stac_item and 'error' not in stac_item:
                                props = stac_item.get('properties', {})
                                postgis_schema = props.get('postgis:schema', 'geo')
                                postgis_table = props.get('postgis:table')
                                if postgis_table:
                                    admin0_table = f"{postgis_schema}.{postgis_table}"
                                else:
                                    assets = stac_item.get('assets', {})
                                    data_asset = assets.get('data', {})
                                    href = data_asset.get('href', '')
                                    if href.startswith('postgis://') and '/' in href:
                                        table_part = href.split('/')[-1]
                                        if '.' in table_part:
                                            admin0_table = table_part
                                        else:
                                            admin0_table = f"geo.{stac_id}"
                                    else:
                                        admin0_table = f"geo.{stac_id}"
                            else:
                                admin0_table = f"geo.{stac_id}"
                        except Exception as stac_err:
                            if self.logger:
                                self.logger.debug(f"STAC item lookup failed: {stac_err}")
                            admin0_table = f"geo.{stac_id}"

                        admin0_source = "promote_service"
                        promoted_dataset_info = {
                            "promoted_id": promoted.get('promoted_id'),
                            "stac_type": "collection" if promoted.get('stac_collection_id') else "item",
                            "stac_id": stac_id,
                            "system_role": promoted.get('system_role'),
                            "is_system_reserved": promoted.get('is_system_reserved', False)
                        }
            except Exception as promote_error:
                promote_error_msg = str(promote_error)[:200]
                if self.logger:
                    self.logger.debug(f"Promote service lookup failed: {promote_error}")

            if not admin0_table:
                return {
                    "_status": "warning",
                    "admin0_table": None,
                    "admin0_source": "not_configured",
                    "exists": False,
                    "message": "No system-reserved dataset found with role 'admin0_boundaries'",
                    "impact": "ISO3 country attribution and H3 land filtering unavailable",
                    "fix": "1. Create admin0 table via process_vector job\n2. Promote with: POST /api/promote {is_system_reserved: true, system_role: 'admin0_boundaries'}",
                    "promote_service_error": promote_error_msg
                }

            # Parse schema.table
            if '.' in admin0_table:
                schema, table = admin0_table.split('.', 1)
            else:
                schema, table = 'geo', admin0_table

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Check table exists
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables
                                WHERE table_schema = %s AND table_name = %s
                            ) as table_exists
                        """, (schema, table))
                        table_exists = cur.fetchone()['table_exists']

                        if not table_exists:
                            result = {
                                "_status": "warning",
                                "admin0_table": admin0_table,
                                "admin0_source": admin0_source,
                                "exists": False,
                                "message": f"Table {admin0_table} not found",
                                "impact": "ISO3 country attribution will be unavailable for STAC items",
                                "fix": "Run process_vector job to create admin0 table, then promote with system_role='admin0_boundaries'"
                            }
                            if promoted_dataset_info:
                                result["promoted_dataset"] = promoted_dataset_info
                                result["note"] = "Promoted dataset exists but referenced table is missing"
                            return result

                        # Check required columns
                        cur.execute("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = %s AND table_name = %s
                        """, (schema, table))
                        columns = [row['column_name'] for row in cur.fetchall()]

                        has_iso3 = 'iso3' in columns or 'iso_a3' in columns
                        has_geom = 'geom' in columns or 'geometry' in columns
                        has_name = 'name' in columns or 'nam_0' in columns

                        # Check row count
                        row_count = 0
                        try:
                            cur.execute("""
                                SELECT n_live_tup FROM pg_stat_user_tables
                                WHERE schemaname = %s AND relname = %s
                            """, (schema, table))
                            result = cur.fetchone()
                            row_count = result['n_live_tup'] if result else 0
                        except Exception:
                            row_count = "error"

                        # Check spatial index
                        cur.execute("""
                            SELECT COUNT(*) > 0 as has_gist_index
                            FROM pg_indexes
                            WHERE schemaname = %s AND tablename = %s
                            AND indexdef LIKE '%%USING gist%%'
                        """, (schema, table))
                        has_spatial_index = cur.fetchone()['has_gist_index']

                        ready = has_iso3 and has_geom and isinstance(row_count, int) and row_count > 0

                        iso3_col = 'iso3' if 'iso3' in columns else ('iso_a3' if 'iso_a3' in columns else None)
                        geom_col = 'geom' if 'geom' in columns else ('geometry' if 'geometry' in columns else None)
                        name_col = 'name' if 'name' in columns else ('nam_0' if 'nam_0' in columns else None)

                        result = {
                            "admin0_table": admin0_table,
                            "admin0_source": admin0_source,
                            "exists": True,
                            "row_count": row_count,
                            "columns": {
                                "iso3": iso3_col,
                                "geom": geom_col,
                                "name": name_col
                            },
                            "spatial_index": has_spatial_index,
                            "ready_for_attribution": ready,
                            "criticality": "low"
                        }

                        if promoted_dataset_info:
                            result["promoted_dataset"] = promoted_dataset_info

                        warnings = []
                        if not has_iso3:
                            warnings.append("Missing required column: iso3")
                        if not has_geom:
                            warnings.append("Missing required column: geom")
                        if not has_spatial_index:
                            warnings.append("No GIST spatial index - queries will be slow")
                        if isinstance(row_count, int) and row_count == 0:
                            warnings.append("Table is empty - no country boundaries loaded")

                        if warnings:
                            result["warnings"] = warnings
                            result["impact"] = "ISO3 country attribution may fail or be incomplete"
                            result["fix"] = "Ensure table has iso3, geom columns with data and GIST index"

                        return result

            except Exception as e:
                import traceback
                result = {
                    "_status": "warning",
                    "admin0_table": admin0_table,
                    "admin0_source": admin0_source,
                    "exists": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "System reference tables check failed"
                }
                if promoted_dataset_info:
                    result["promoted_dataset"] = promoted_dataset_info
                return result

        return self.check_component_health(
            "system_reference_tables",
            check_system_tables,
            description="Reference data tables for ISO3 country attribution and spatial enrichment"
        )

    # =========================================================================
    # CHECK: Schema Summary
    # =========================================================================

    def check_schema_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive schema summary for remote database inspection.

        Returns:
            Dict with schema summary including tables and counts
        """
        def check_schemas():
            from infrastructure.postgresql import PostgreSQLRepository
            from config import get_config

            config = get_config()
            repo = PostgreSQLRepository()

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        schemas_data = {}
                        target_schemas = ['app', 'geo', 'pgstac', 'h3']

                        for schema_name in target_schemas:
                            # Check if schema exists
                            cur.execute("""
                                SELECT EXISTS(
                                    SELECT 1 FROM pg_namespace WHERE nspname = %s
                                ) as schema_exists
                            """, (schema_name,))
                            schema_exists = cur.fetchone()['schema_exists']

                            if not schema_exists:
                                schemas_data[schema_name] = {
                                    "exists": False,
                                    "tables": [],
                                    "table_count": 0
                                }
                                continue

                            # Get tables in schema
                            cur.execute("""
                                SELECT table_name
                                FROM information_schema.tables
                                WHERE table_schema = %s
                                AND table_type = 'BASE TABLE'
                                ORDER BY table_name
                            """, (schema_name,))
                            tables = [row['table_name'] for row in cur.fetchall()]

                            # Get row counts using pg_stat
                            cur.execute("""
                                SELECT relname, n_live_tup
                                FROM pg_stat_user_tables
                                WHERE schemaname = %s
                                ORDER BY relname
                            """, (schema_name,))
                            table_counts = {row['relname']: row['n_live_tup'] for row in cur.fetchall()}

                            schemas_data[schema_name] = {
                                "exists": True,
                                "tables": tables,
                                "table_count": len(tables),
                                "row_counts": table_counts,
                                "note": "Row counts are approximate (from pg_stat_user_tables)"
                            }

                        # Special handling for pgstac
                        if schemas_data.get('pgstac', {}).get('exists', False):
                            try:
                                cur.execute("""
                                    SELECT relname, n_live_tup
                                    FROM pg_stat_user_tables
                                    WHERE schemaname = 'pgstac' AND relname IN ('collections', 'items')
                                """)
                                stac_counts = {row['relname']: row['n_live_tup'] for row in cur.fetchall()}

                                schemas_data['pgstac']['stac_counts'] = {
                                    "collections": stac_counts.get('collections', 0),
                                    "items": stac_counts.get('items', 0)
                                }
                            except Exception as e:
                                schemas_data['pgstac']['stac_counts'] = {
                                    "error": str(e)[:100]
                                }

                        # Special handling for geo
                        if schemas_data.get('geo', {}).get('exists', False):
                            try:
                                cur.execute("""
                                    SELECT COUNT(*) as count
                                    FROM geometry_columns
                                    WHERE f_table_schema = 'geo'
                                """)
                                geometry_count = cur.fetchone()['count']
                                schemas_data['geo']['geometry_columns'] = geometry_count
                            except Exception:
                                schemas_data['geo']['geometry_columns'] = "error"

                        total_tables = sum(
                            s.get('table_count', 0)
                            for s in schemas_data.values()
                            if isinstance(s, dict)
                        )

                        return {
                            "schemas": schemas_data,
                            "total_tables": total_tables,
                            "schemas_checked": target_schemas
                        }

            except Exception as e:
                import traceback
                return {
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500]
                }

        return self.check_component_health(
            "schema_summary",
            check_schemas,
            description="Database schema inventory with table counts and STAC statistics"
        )

    # =========================================================================
    # CHECK: Public Database
    # =========================================================================

    def check_public_database(self) -> Dict[str, Any]:
        """
        Check public database health (optional).

        Returns:
            Dict with public database health status
        """
        def check_public_db():
            import psycopg
            import time
            from config import get_config
            from infrastructure.postgresql import PostgreSQLRepository

            config = get_config()
            start_time = time.time()

            if not config.is_public_database_configured():
                return {
                    "configured": False,
                    "message": "Public database not configured (PUBLIC_DB_* env vars not set)"
                }

            public_config = config.public_database

            try:
                repo = PostgreSQLRepository(
                    config=config,
                    target_database="public"
                )
                conn_str = repo.conn_string
            except Exception as repo_error:
                return {
                    "configured": True,
                    "host": public_config.host,
                    "database": public_config.database,
                    "connected": False,
                    "error": f"Failed to initialize repository: {str(repo_error)[:200]}",
                    "error_type": type(repo_error).__name__
                }

            try:
                with psycopg.connect(conn_str, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        connection_time_ms = round((time.time() - start_time) * 1000, 2)

                        # Get PostgreSQL version
                        cur.execute("SELECT version()")
                        pg_version = cur.fetchone()[0].split(',')[0]

                        # Check if PostGIS is available
                        try:
                            cur.execute("SELECT PostGIS_Version()")
                            postgis_version = cur.fetchone()[0]
                        except Exception:
                            postgis_version = "not installed"

                        # Check target schema exists
                        target_schema = public_config.db_schema
                        cur.execute("""
                            SELECT EXISTS(
                                SELECT 1 FROM pg_namespace WHERE nspname = %s
                            ) as schema_exists
                        """, (target_schema,))
                        schema_exists = cur.fetchone()[0]

                        # Count tables in schema
                        table_count = 0
                        if schema_exists:
                            cur.execute("""
                                SELECT COUNT(*) FROM information_schema.tables
                                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                            """, (target_schema,))
                            table_count = cur.fetchone()[0]

                        return {
                            "configured": True,
                            "host": public_config.host,
                            "database": public_config.database,
                            "schema": target_schema,
                            "connected": True,
                            "connection_time_ms": connection_time_ms,
                            "postgres_version": pg_version,
                            "postgis_version": postgis_version,
                            "schema_exists": schema_exists,
                            "table_count": table_count,
                            "purpose": "Public-facing OGC Feature Collections"
                        }

            except Exception as conn_error:
                return {
                    "configured": True,
                    "host": public_config.host,
                    "database": public_config.database,
                    "connected": False,
                    "error": str(conn_error)[:200],
                    "error_type": type(conn_error).__name__
                }

        return self.check_component_health(
            "public_database",
            check_public_db,
            description="Public-facing database for OGC Feature Collections"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['DatabaseHealthChecks']
