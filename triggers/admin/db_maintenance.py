# ============================================================================
# DATABASE MAINTENANCE ADMIN TRIGGER
# ============================================================================
# STATUS: Trigger layer - POST /api/dbadmin/maintenance
# PURPOSE: Database maintenance operations (ensure, rebuild, cleanup)
# LAST_REVIEWED: 16 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: AdminDbMaintenanceTrigger, admin_db_maintenance_trigger
# ============================================================================
"""
Database Maintenance Admin Trigger.

Database maintenance operations with SQL injection prevention.

SCHEMA EVOLUTION PATTERN (16 JAN 2026):
    Use 'ensure' for safe additive updates, 'rebuild' for destructive resets.

    action=ensure  -> SAFE: Creates missing tables/indexes, preserves data
    action=rebuild -> DESTRUCTIVE: Drops and recreates schemas (data loss!)
    action=cleanup -> SAFE: Removes old completed jobs/tasks

Endpoint patterns:
    POST /api/dbadmin/maintenance?action=ensure&confirm=yes               # SAFE - additive sync
    POST /api/dbadmin/maintenance?action=rebuild&confirm=yes              # DESTRUCTIVE - both schemas
    POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes   # DESTRUCTIVE - app only
    POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes # DESTRUCTIVE - pgstac only
    POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30      # SAFE - remove old records

When to use each:
    - Deploying new tables/features -> action=ensure (safe, no data loss)
    - Fresh dev/test environment -> action=rebuild (wipes everything)
    - Disk space cleanup -> action=cleanup (removes old jobs)

See: docs_claude/SCHEMA_EVOLUTION.md for full patterns

Exports:
    AdminDbMaintenanceTrigger: HTTP trigger class for maintenance operations
    admin_db_maintenance_trigger: Singleton instance of AdminDbMaintenanceTrigger
"""

import azure.functions as func
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import traceback

import psycopg
from psycopg import sql

from infrastructure import RepositoryFactory, PostgreSQLRepository
from config import get_config
from config.defaults import STACDefaults, AzureDefaults
from util_logger import LoggerFactory, ComponentType

# Import extracted operation modules (12 JAN 2026 - F7.16 code maintenance)
from .data_cleanup import DataCleanupOperations
from .geo_table_operations import GeoTableOperations

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbMaintenance")


@dataclass
class RouteDefinition:
    """Route configuration for registry pattern."""
    route: str
    methods: list
    handler: str
    description: str


class AdminDbMaintenanceTrigger:
    """
    Admin trigger for PostgreSQL maintenance operations.

    Singleton pattern for consistent configuration across requests.
    All operations require confirmation parameters.

    Consolidated API (08 JAN 2026):
        POST /api/dbadmin/maintenance?action=rebuild&confirm=yes              # Both schemas (RECOMMENDED)
        POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes   # App only (with warning)
        POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes # pgSTAC only (with warning)
        POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30      # Clean old records
    """

    _instance: Optional['AdminDbMaintenanceTrigger'] = None

    # ========================================================================
    # ROUTE REGISTRY - Single source of truth for function_app.py
    # ========================================================================
    ROUTES = [
        RouteDefinition(
            route="dbadmin/maintenance",
            methods=["POST", "GET"],
            handler="handle_maintenance",
            description="Consolidated maintenance: ?action=rebuild[&target=app|pgstac] or ?action=cleanup"
        ),
        RouteDefinition(
            route="dbadmin/geo",
            methods=["GET", "POST"],
            handler="handle_geo",
            description="Consolidated geo ops: ?type={tables|metadata|orphans} or ?action=unpublish"
        ),
    ]

    # ========================================================================
    # OPERATIONS REGISTRY - Maps action param to handler method
    # ========================================================================
    OPERATIONS = {
        "rebuild": "_rebuild",  # Consolidated rebuild (08 JAN 2026)
        "cleanup": "_cleanup_old_records",
        "ensure": "_ensure_tables",  # Additive schema sync (16 JAN 2026)
        # Legacy aliases (deprecated - will be removed in future version)
        "full-rebuild": "_rebuild",  # Alias for backward compatibility
    }

    GEO_READ_OPERATIONS = {
        "tables": "_list_geo_tables",
        "metadata": "_list_metadata",
        "orphans": "_check_geo_orphans",
    }

    GEO_WRITE_OPERATIONS = {
        "unpublish": "_unpublish_geo_table",
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

        logger.info("🔧 Initializing AdminDbMaintenanceTrigger")

        # Initialize operation modules (12 JAN 2026 - F7.16 code maintenance)
        # These are lazily initialized when first accessed via db_repo property
        self._data_cleanup_ops = None
        self._geo_table_ops = None

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

    @property
    def data_cleanup_ops(self) -> DataCleanupOperations:
        """Lazy initialization of data cleanup operations (12 JAN 2026)."""
        if self._data_cleanup_ops is None:
            self._data_cleanup_ops = DataCleanupOperations(self.db_repo)
        return self._data_cleanup_ops

    @property
    def geo_table_ops(self) -> GeoTableOperations:
        """Lazy initialization of geo table operations (12 JAN 2026)."""
        if self._geo_table_ops is None:
            self._geo_table_ops = GeoTableOperations(self.db_repo)
        return self._geo_table_ops

    def handle_maintenance(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated maintenance endpoint (08 JAN 2026).

        POST /api/dbadmin/maintenance?action=rebuild&confirm=yes              # Both schemas (RECOMMENDED)
        POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes   # App only (with warning)
        POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes # pgSTAC only (with warning)
        POST /api/dbadmin/maintenance?action=ensure&confirm=yes               # Additive - create missing tables/indexes
        POST /api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30      # Clean old records

        Query Parameters:
            action: Operation to perform (required)
                - rebuild: Rebuild schema(s) - RECOMMENDED for fresh start
                - ensure: Additive sync - creates missing tables/indexes without dropping (SAFE)
                - cleanup: Remove old completed jobs/tasks
            target: Schema target for rebuild (default: all)
                - all: Both app+pgstac schemas (RECOMMENDED - maintains referential integrity)
                - app: Application schema only (jobs, tasks) - WARNING: may orphan STAC items
                - pgstac: STAC catalog schema only - WARNING: may orphan job references
            confirm: Must be 'yes' for destructive operations
            days: For cleanup, records older than N days (default: 30)

        Returns:
            JSON response with operation results
        """
        try:
            action = req.params.get('action')
            target = req.params.get('target', 'all')  # Default to 'all' for rebuild

            logger.info(f"📥 Maintenance request: action={action}, target={target}")

            # Validate action parameter
            if not action:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': "action parameter required",
                        'valid_actions': ['rebuild', 'ensure', 'cleanup'],
                        'usage': 'POST /api/dbadmin/maintenance?action=ensure&confirm=yes',
                        'recommended': 'Use action=ensure for safe additive updates, action=rebuild for fresh start',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            if action not in self.OPERATIONS:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f"Invalid action: '{action}'",
                        'valid_actions': ['rebuild', 'ensure', 'cleanup'],
                        'usage': 'POST /api/dbadmin/maintenance?action=ensure&confirm=yes',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            # Dispatch to handler method from registry
            handler_method = getattr(self, self.OPERATIONS[action])
            return handler_method(req)

        except Exception as e:
            logger.error(f"❌ Error in handle_maintenance: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def handle_geo(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated geo schema operations (15 DEC 2025).

        GET /api/dbadmin/geo?type={tables|metadata|orphans}
        POST /api/dbadmin/geo?action=unpublish&table_name={name}&confirm=yes

        GET Query Parameters:
            type: Read operation type (default: tables)
                - tables: List geo tables with tracking status
                - metadata: List geo.table_metadata records
                - orphans: Check for orphaned tables/metadata

        POST Query Parameters:
            action: Write operation (required)
                - unpublish: Cascade delete table
            table_name: Table to unpublish (required for unpublish)
            confirm: Must be 'yes' for destructive operations

        Returns:
            JSON response with requested data
        """
        try:
            if req.method == 'POST':
                # Write operations
                action = req.params.get('action')
                logger.info(f"📥 Geo write request: action={action}")

                if not action:
                    return func.HttpResponse(
                        body=json.dumps({
                            'error': "action parameter required for POST",
                            'valid_actions': list(self.GEO_WRITE_OPERATIONS.keys()),
                            'usage': 'POST /api/dbadmin/geo?action=unpublish&table_name={name}&confirm=yes',
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }),
                        status_code=400,
                        mimetype='application/json'
                    )

                if action not in self.GEO_WRITE_OPERATIONS:
                    return func.HttpResponse(
                        body=json.dumps({
                            'error': f"Invalid action: '{action}'",
                            'valid_actions': list(self.GEO_WRITE_OPERATIONS.keys()),
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }),
                        status_code=400,
                        mimetype='application/json'
                    )

                handler_method = getattr(self, self.GEO_WRITE_OPERATIONS[action])
                return handler_method(req)

            else:
                # Read operations (GET)
                op_type = req.params.get('type', 'tables')
                logger.info(f"📥 Geo read request: type={op_type}")

                if op_type not in self.GEO_READ_OPERATIONS:
                    return func.HttpResponse(
                        body=json.dumps({
                            'error': f"Invalid type: '{op_type}'",
                            'valid_types': list(self.GEO_READ_OPERATIONS.keys()),
                            'timestamp': datetime.now(timezone.utc).isoformat()
                        }),
                        status_code=400,
                        mimetype='application/json'
                    )

                handler_method = getattr(self, self.GEO_READ_OPERATIONS[op_type])
                return handler_method(req)

        except Exception as e:
            logger.error(f"❌ Error in handle_geo: {e}")
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

        POST /api/dbadmin/maintenance/nuke?confirm=yes

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
                    'usage': 'POST /api/dbadmin/maintenance/nuke?confirm=yes',
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

    # ========================================================================
    # ENSURE TABLES - ADDITIVE SCHEMA SYNC (16 JAN 2026)
    # ========================================================================

    def _ensure_tables(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Additive schema sync - creates missing tables/indexes without dropping existing data.

        POST /api/dbadmin/maintenance?action=ensure&confirm=yes

        This is SAFE to run at any time:
        - Uses CREATE TABLE IF NOT EXISTS
        - Uses CREATE INDEX IF NOT EXISTS
        - Skips existing enums (checks pg_type catalog)
        - Does NOT drop any existing data
        - Idempotent - can be run multiple times safely

        Implementation Notes (16 JAN 2026):
        - Uses AUTOCOMMIT mode so each statement is independent
        - Skips DROP TYPE statements (destructive, not additive)
        - Checks pg_type before creating enums to avoid errors
        - Failures in one statement don't affect others

        Use Cases:
        - After deploying new code with new tables
        - Adding new indexes to existing tables
        - Adding new enum values (note: enum modification has limitations)

        Query Parameters:
            confirm: Must be 'yes' (required)
            target: Schema to sync (default: app)
                - app: Application schema only (jobs, tasks, approvals, etc.)

        Returns:
            {
                "operation": "ensure_tables",
                "status": "success",
                "created": {"tables": [...], "indexes": [...], "enums": [...]},
                "skipped": {"tables": [...], "indexes": [...], "enums": [...]},
                "execution_time_ms": 150
            }
        """
        import time
        start_time = time.time()

        confirm = req.params.get('confirm')
        target = req.params.get('target', 'app')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'Ensure tables requires explicit confirmation',
                    'usage': 'POST /api/dbadmin/maintenance?action=ensure&confirm=yes',
                    'info': 'This is SAFE - it only creates missing tables/indexes, never drops data'
                }),
                status_code=400,
                mimetype='application/json'
            )

        if target != 'app':
            return func.HttpResponse(
                body=json.dumps({
                    'error': f"Invalid target: '{target}'",
                    'valid_targets': ['app'],
                    'info': 'Only app schema supports additive ensure. Use action=rebuild for pgstac.'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.info("🔧 ENSURE TABLES: Running additive schema sync for app schema")

        results = {
            "operation": "ensure_tables",
            "target": target,
            "created": {"enums": [], "tables": [], "indexes": [], "functions": [], "triggers": [], "other": []},
            "skipped": {"enums": [], "tables": [], "indexes": [], "functions": [], "triggers": [], "other": []},
            "errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            from infrastructure.postgresql import PostgreSQLRepository
            from core.schema.sql_generator import PydanticToSQL

            # Get SQL generator for app schema
            sql_gen = PydanticToSQL(schema_name='app')
            statements = sql_gen.generate_composed_statements()

            logger.info(f"📋 Generated {len(statements)} SQL statements to process")

            repo = PostgreSQLRepository(schema_name='app')

            # Get existing enums from pg_type catalog (to skip DROP/CREATE pairs)
            existing_enums = set()
            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT t.typname
                        FROM pg_type t
                        JOIN pg_namespace n ON t.typnamespace = n.oid
                        WHERE n.nspname = 'app' AND t.typtype = 'e'
                    """)
                    existing_enums = {row['typname'] for row in cur.fetchall()}
            logger.info(f"📊 Found {len(existing_enums)} existing enums in app schema")

            # Use autocommit mode - each statement is its own transaction
            # This prevents rollback of successful statements when one fails
            with repo._get_connection() as conn:
                # Enable autocommit mode
                conn.autocommit = True

                with conn.cursor() as cur:
                    for i, stmt in enumerate(statements):
                        try:
                            # Convert to string for logging/categorization
                            stmt_str = stmt.as_string(conn)
                            stmt_upper = stmt_str.upper()
                            stmt_preview = stmt_str[:100].replace('\n', ' ')

                            # Categorize the statement
                            if 'DROP TYPE' in stmt_upper:
                                category = 'enums'
                                # SKIP DROP TYPE in ensure mode - it's destructive
                                # Extract enum name to check if we should skip the CREATE too
                                # Pattern: DROP TYPE IF EXISTS app."enum_name" CASCADE
                                match = re.search(r'DROP TYPE IF EXISTS "app"\."(\w+)"', stmt_str)
                                if match:
                                    enum_name = match.group(1)
                                    if enum_name in existing_enums:
                                        results["skipped"]["enums"].append(f"DROP {enum_name} (exists)")
                                        logger.debug(f"⏭️ [{i+1}/{len(statements)}] Skipped DROP TYPE (enum exists): {enum_name}")
                                        continue
                                # If enum doesn't exist, we still skip DROP (nothing to drop)
                                logger.debug(f"⏭️ [{i+1}/{len(statements)}] Skipped DROP TYPE (ensure mode): {stmt_preview}")
                                continue

                            elif 'CREATE TYPE' in stmt_upper:
                                category = 'enums'
                                # Check if this enum already exists
                                match = re.search(r'CREATE TYPE "app"\."(\w+)"', stmt_str)
                                if match:
                                    enum_name = match.group(1)
                                    if enum_name in existing_enums:
                                        results["skipped"]["enums"].append(f"CREATE {enum_name} (exists)")
                                        logger.debug(f"⏭️ [{i+1}/{len(statements)}] Skipped CREATE TYPE (exists): {enum_name}")
                                        continue

                            elif 'CREATE TABLE' in stmt_upper:
                                category = 'tables'
                            elif 'CREATE INDEX' in stmt_upper or 'CREATE UNIQUE INDEX' in stmt_upper:
                                category = 'indexes'
                            elif 'CREATE OR REPLACE FUNCTION' in stmt_upper or 'CREATE FUNCTION' in stmt_upper:
                                category = 'functions'
                            elif 'CREATE TRIGGER' in stmt_upper or 'DROP TRIGGER' in stmt_upper:
                                category = 'triggers'
                            else:
                                category = 'other'

                            # Execute the statement
                            cur.execute(stmt)

                            # If we get here, statement succeeded
                            if category in results["created"]:
                                results["created"][category].append(stmt_preview)
                            logger.debug(f"✅ [{i+1}/{len(statements)}] Executed: {stmt_preview}...")

                        except Exception as stmt_error:
                            error_str = str(stmt_error).lower()

                            # Check if it's an "already exists" error (expected for IF NOT EXISTS)
                            if 'already exists' in error_str or 'duplicate' in error_str:
                                if category in results["skipped"]:
                                    results["skipped"][category].append(stmt_preview)
                                logger.debug(f"⏭️ [{i+1}/{len(statements)}] Skipped (exists): {stmt_preview}...")
                            else:
                                # Real error - log it and continue
                                # In autocommit mode, this only affects this statement
                                results["errors"].append({
                                    "statement": stmt_preview,
                                    "error": str(stmt_error)
                                })
                                logger.warning(f"⚠️ [{i+1}/{len(statements)}] Error: {stmt_error}")

            results["status"] = "success" if not results["errors"] else "partial"
            results["execution_time_ms"] = int((time.time() - start_time) * 1000)
            results["summary"] = {
                "enums_created": len(results["created"]["enums"]),
                "tables_created": len(results["created"]["tables"]),
                "indexes_created": len(results["created"]["indexes"]),
                "functions_created": len(results["created"]["functions"]),
                "triggers_created": len(results["created"]["triggers"]),
                "enums_existed": len(results["skipped"]["enums"]),
                "tables_existed": len(results["skipped"]["tables"]),
                "indexes_existed": len(results["skipped"]["indexes"]),
                "functions_existed": len(results["skipped"]["functions"]),
                "triggers_existed": len(results["skipped"]["triggers"]),
                "errors": len(results["errors"])
            }

            logger.info(f"✅ Ensure tables completed: {results['summary']}")

            return func.HttpResponse(
                body=json.dumps(results, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Ensure tables failed: {e}")
            logger.error(traceback.format_exc())

            results["status"] = "failed"
            results["error"] = str(e)
            results["traceback"] = traceback.format_exc()
            results["execution_time_ms"] = int((time.time() - start_time) * 1000)

            return func.HttpResponse(
                body=json.dumps(results, indent=2),
                status_code=500,
                mimetype='application/json'
            )

    # ========================================================================
    # REBUILD - DESTRUCTIVE SCHEMA REBUILD
    # ========================================================================

    def _rebuild(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated rebuild endpoint (08 JAN 2026).

        Routes to appropriate rebuild method based on target parameter.

        POST /api/dbadmin/maintenance?action=rebuild&confirm=yes              # Both (RECOMMENDED)
        POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes   # App only
        POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes # pgSTAC only

        Query Parameters:
            target: Schema target (default: all)
                - all: Both app+pgstac schemas (RECOMMENDED - maintains referential integrity)
                - app: Application schema only (WARNING: may orphan STAC items)
                - pgstac: STAC catalog only (WARNING: may orphan job references)
            confirm: Must be 'yes' (required)

        Returns:
            JSON response with rebuild results
        """
        target = req.params.get('target', 'all')
        confirm = req.params.get('confirm')

        # Validate target parameter
        valid_targets = ['all', 'app', 'pgstac']
        if target not in valid_targets:
            return func.HttpResponse(
                body=json.dumps({
                    'error': f"Invalid target: '{target}'",
                    'valid_targets': valid_targets,
                    'usage': 'POST /api/dbadmin/maintenance?action=rebuild&confirm=yes',
                    'recommended': 'Use target=all (default) for atomic rebuild of both schemas',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=400,
                mimetype='application/json'
            )

        # Add warnings for partial rebuilds
        if target == 'app':
            logger.warning("⚠️ PARTIAL REBUILD: App schema only - STAC items may become orphaned")
            # Call existing _redeploy_schema (app only)
            response = self._redeploy_schema(req)
            # Inject warning into response
            try:
                data = json.loads(response.get_body().decode('utf-8'))
                data['warning'] = 'App schema rebuilt independently. STAC items may reference non-existent jobs. Consider full rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes'
                data['recommended'] = 'POST /api/dbadmin/maintenance?action=rebuild&confirm=yes'
                return func.HttpResponse(
                    body=json.dumps(data, indent=2),
                    status_code=response.status_code,
                    mimetype='application/json'
                )
            except Exception:
                return response

        elif target == 'pgstac':
            logger.warning("⚠️ PARTIAL REBUILD: pgSTAC schema only - Job references may become orphaned")
            # Call existing _redeploy_pgstac_schema
            response = self._redeploy_pgstac_schema(req)
            # Inject warning into response
            try:
                data = json.loads(response.get_body().decode('utf-8'))
                data['warning'] = 'pgSTAC schema rebuilt independently. Jobs may reference non-existent STAC items. Consider full rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes'
                data['recommended'] = 'POST /api/dbadmin/maintenance?action=rebuild&confirm=yes'
                return func.HttpResponse(
                    body=json.dumps(data, indent=2),
                    status_code=response.status_code,
                    mimetype='application/json'
                )
            except Exception:
                return response

        else:  # target == 'all' (default, recommended)
            logger.info("✅ FULL REBUILD: Both app + pgstac schemas atomically (RECOMMENDED)")
            return self._full_rebuild(req)

    def _redeploy_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Rebuild app schema only (INTERNAL - use _rebuild with target=app).

        POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes

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

        """
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'Schema rebuild requires explicit confirmation',
                    'usage': 'POST /api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes',
                    'recommended': 'POST /api/dbadmin/maintenance?action=rebuild&confirm=yes (both schemas)',
                    'warning': 'This will DESTROY ALL app schema DATA. Consider full rebuild for consistency.'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning("🔄 REBUILD (app only): Nuking and redeploying app schema")

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
        Rebuild pgSTAC schema only (INTERNAL - use _rebuild with target=pgstac).

        POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes

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

        Note: This is separate from app schema rebuild - allows independent
              pgSTAC maintenance without affecting job/task tables.
              However, rebuilding both together is RECOMMENDED for consistency.
        """
        confirm = req.params.get('confirm')

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    'error': 'pgSTAC schema rebuild requires explicit confirmation',
                    'usage': 'POST /api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes',
                    'recommended': 'POST /api/dbadmin/maintenance?action=rebuild&confirm=yes (both schemas)',
                    'warning': 'This will DESTROY ALL STAC DATA. Consider full rebuild for consistency.'
                }),
                status_code=400,
                mimetype='application/json'
            )

        logger.warning("🔄 REBUILD (pgstac only): Nuking and redeploying pgstac schema")

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
                    'error': 'Rebuild requires explicit confirmation',
                    'usage': 'POST /api/dbadmin/maintenance?action=rebuild&confirm=yes',
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

                        # 0d. Add table_type column for curated dataset tracking (15 DEC 2025)
                        cur.execute("""
                            ALTER TABLE geo.table_metadata
                            ADD COLUMN IF NOT EXISTS table_type VARCHAR(20) DEFAULT 'user'
                        """)
                        logger.info("✅ Ensured geo.table_metadata has table_type column")

                        # 0f. Add Unified Metadata columns (09 JAN 2026 - F7.8)
                        # Per METADATA.md design document - adds STAC-aligned fields
                        f78_columns = [
                            # STAC providers (array of provider objects)
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS providers JSONB",
                            # STAC extensions URIs
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS stac_extensions JSONB",
                            # Table Extension fields
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS column_definitions JSONB",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS primary_geometry VARCHAR(100) DEFAULT 'geom'",
                            # Processing Extension fields
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS processing_software JSONB",
                            # Scientific metadata
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS sci_doi VARCHAR(200)",
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS sci_citation TEXT",
                            # Custom properties (extension point)
                            "ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS custom_properties JSONB DEFAULT '{}'",
                        ]
                        for alter_sql in f78_columns:
                            cur.execute(alter_sql)
                        logger.info("✅ Ensured geo.table_metadata has F7.8 unified metadata columns")

                        # 0e. Migrate system_admin0 to curated_admin0 (15 DEC 2025)
                        # Curated datasets use curated_ prefix for protection
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'geo' AND table_name = 'system_admin0'
                            ) as old_exists,
                            EXISTS (
                                SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'geo' AND table_name = 'curated_admin0'
                            ) as new_exists
                        """)
                        migration_check = cur.fetchone()

                        if migration_check['old_exists'] and not migration_check['new_exists']:
                            # Old table exists, new doesn't - do the rename
                            cur.execute("ALTER TABLE geo.system_admin0 RENAME TO curated_admin0")
                            logger.info("✅ Migrated geo.system_admin0 → geo.curated_admin0")

                            # Update table_metadata if it exists
                            cur.execute("""
                                UPDATE geo.table_metadata
                                SET table_name = 'curated_admin0',
                                    table_type = 'curated'
                                WHERE table_name = 'system_admin0'
                            """)
                            logger.info("✅ Updated table_metadata for curated_admin0")
                        elif migration_check['new_exists']:
                            logger.info("✅ geo.curated_admin0 already exists (no migration needed)")
                        else:
                            logger.info("⚠️  geo.system_admin0 not found (load country boundaries later)")

                        # 0f. Create OGC API Styles table (18 DEC 2025)
                        # Stores CartoSym-JSON styles for OGC Features collections
                        # Serves multiple output formats: Leaflet, Mapbox GL
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS geo.feature_collection_styles (
                                id SERIAL PRIMARY KEY,
                                collection_id TEXT NOT NULL,           -- matches OGC Features collection (table name)
                                style_id TEXT NOT NULL,                -- url-safe identifier (e.g., "default", "by-category")
                                title TEXT,                            -- human-readable title
                                description TEXT,                      -- style description
                                style_spec JSONB NOT NULL,             -- CartoSym-JSON document
                                is_default BOOLEAN DEFAULT false,      -- default style for collection
                                created_at TIMESTAMPTZ DEFAULT now(),
                                updated_at TIMESTAMPTZ DEFAULT now(),
                                UNIQUE(collection_id, style_id)
                            )
                        """)

                        # Index for fast lookups by collection
                        cur.execute("""
                            CREATE INDEX IF NOT EXISTS idx_styles_collection
                            ON geo.feature_collection_styles(collection_id)
                        """)

                        # Ensure only one default per collection (partial unique index)
                        cur.execute("""
                            CREATE UNIQUE INDEX IF NOT EXISTS idx_styles_default
                            ON geo.feature_collection_styles(collection_id)
                            WHERE is_default = true
                        """)

                        logger.info("✅ Ensured geo.feature_collection_styles table exists")

                        # 1. Create h3 schema if it doesn't exist (04 DEC 2025)
                        # h3 schema stores static bootstrap H3 grid data
                        cur.execute("CREATE SCHEMA IF NOT EXISTS h3")
                        logger.info("✅ Ensured h3 schema exists")

                        # COMMIT table/schema creation BEFORE grants (18 DEC 2025)
                        # This ensures tables are created even if GRANTs fail
                        # (e.g., when tables exist that we don't own)
                        conn.commit()
                        logger.info("✅ Committed geo/h3 schema and table changes")

                # Tables are now committed. GRANTs in separate block (18 DEC 2025)
                # If GRANTs fail, tables still exist
                grant_warnings = []
                try:
                    with geo_repo._get_connection() as grant_conn:
                        with grant_conn.cursor() as grant_cur:
                            # 2. Grant USAGE on geo schema
                            admin_ident = sql.Identifier(admin_identity)
                            grant_cur.execute(sql.SQL("GRANT USAGE ON SCHEMA geo TO {}").format(admin_ident))

                            # 3. Grant SELECT on ALL existing tables in geo schema
                            grant_cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA geo TO {}").format(admin_ident))

                            # 4. Set default privileges for FUTURE tables created in geo schema
                            grant_cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO {}").format(admin_ident))

                            # 5. Grant on h3 schema (static bootstrap data)
                            grant_cur.execute(sql.SQL("GRANT USAGE ON SCHEMA h3 TO {}").format(admin_ident))
                            grant_cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO {}").format(admin_ident))
                            grant_cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT ON TABLES TO {}").format(admin_ident))

                            grant_conn.commit()
                            logger.info(f"✅ Granted geo+h3 schema permissions to {admin_identity} (existing + future tables)")

                except Exception as grant_err:
                    # GRANTs failed but tables are already committed
                    logger.warning(f"⚠️ GRANT statements failed (tables still created): {grant_err}")
                    grant_warnings.append(str(grant_err))

                if grant_warnings:
                    step4["status"] = "partial"
                    step4["tables_created"] = ["geo.table_metadata", "geo.feature_collection_styles"]
                    step4["grant_warnings"] = grant_warnings
                    step4["note"] = "Tables created but some GRANTs failed - may need manual permission fixes"
                else:
                    step4["status"] = "success"
                    step4["schema_created"] = "geo, h3 (if not exists)"
                    step4["tables_created"] = ["geo.table_metadata (vector metadata registry)", "geo.feature_collection_styles (OGC Styles)"]
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
                # The table creation might fail if there's a fundamental DB issue
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
        Delegates to DataCleanupOperations (12 JAN 2026 - F7.16).
        """
        return self.data_cleanup_ops.cleanup_old_records(req)

    def _check_pgstac_prerequisites(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check if DBA prerequisites for pypgstac are in place.
        Delegates to DataCleanupOperations (12 JAN 2026 - F7.16).
        """
        return self.data_cleanup_ops.check_pgstac_prerequisites(req)

    # =========================================================================
    # GEO SCHEMA TABLE MANAGEMENT
    # Delegates to GeoTableOperations (12 JAN 2026 - F7.16 code maintenance)
    # =========================================================================

    def _unpublish_geo_table(self, req: func.HttpRequest) -> func.HttpResponse:
        """Delegates to GeoTableOperations.unpublish_geo_table."""
        return self.geo_table_ops.unpublish_geo_table(req)

    def _list_geo_tables(self, req: func.HttpRequest) -> func.HttpResponse:
        """Delegates to GeoTableOperations.list_geo_tables."""
        return self.geo_table_ops.list_geo_tables(req)

    def _list_metadata(self, req: func.HttpRequest) -> func.HttpResponse:
        """Delegates to GeoTableOperations.list_metadata."""
        return self.geo_table_ops.list_metadata(req)

    def _check_geo_orphans(self, req: func.HttpRequest) -> func.HttpResponse:
        """Delegates to GeoTableOperations.check_geo_orphans."""
        return self.geo_table_ops.check_geo_orphans(req)


# Create singleton instance
admin_db_maintenance_trigger = AdminDbMaintenanceTrigger.instance()


# ===========================================================================
# LEGACY CODE REMOVED (12 JAN 2026 - F7.16)
# ===========================================================================
# The following methods were extracted to separate modules:
# - _cleanup_old_records -> data_cleanup.py:DataCleanupOperations
# - _check_pgstac_prerequisites -> data_cleanup.py:DataCleanupOperations
# - _unpublish_geo_table -> geo_table_operations.py:GeoTableOperations
# - _list_geo_tables -> geo_table_operations.py:GeoTableOperations
# - _list_metadata -> geo_table_operations.py:GeoTableOperations
# - _check_geo_orphans -> geo_table_operations.py:GeoTableOperations
#
# Schema operations (_nuke_schema, _rebuild, _redeploy_schema,
# _redeploy_pgstac_schema, _full_rebuild) remain in this file for now.
# Future: Extract to schema_operations.py (~1,400 lines)
# ===========================================================================
