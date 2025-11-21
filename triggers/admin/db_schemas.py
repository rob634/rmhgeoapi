# ============================================================================
# CLAUDE CONTEXT - DATABASE SCHEMAS ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - PostgreSQL schema inspection
# PURPOSE: HTTP trigger for schema-level database inspection (app, geo, pgstac schemas)
# LAST_REVIEWED: 03 NOV 2025
# EXPORTS: AdminDbSchemasTrigger - Singleton trigger for schema operations
# INTERFACES: Azure Functions HTTP trigger
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: azure.functions, psycopg, infrastructure.postgresql, util_logger
# SOURCE: PostgreSQL information_schema and pg_catalog
# SCOPE: Read-only schema inspection for monitoring and debugging
# VALIDATION: None yet (future APIM authentication)
# PATTERNS: Singleton trigger, RESTful admin API
# ENTRY_POINTS: AdminDbSchemasTrigger.instance().handle_request(req)
# INDEX: AdminDbSchemasTrigger:50, list_schemas:150, get_schema_details:250, list_schema_tables:350
# ============================================================================

"""
Database Schemas Admin Trigger

Provides schema-level inspection of PostgreSQL database:
- List all schemas with sizes and table counts
- Get detailed schema information
- List tables in a schema

Endpoints:
    GET /api/admin/db/schemas
    GET /api/admin/db/schemas/{schema_name}
    GET /api/admin/db/schemas/{schema_name}/tables

"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbSchemas")


class AdminDbSchemasTrigger:
    """
    Admin trigger for PostgreSQL schema inspection.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminDbSchemasTrigger'] = None

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

        logger.info("🔧 Initializing AdminDbSchemasTrigger")
        self._initialized = True
        logger.info("✅ AdminDbSchemasTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbSchemasTrigger':
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
        Route admin database schema requests.

        Routes:
            GET /api/db/schemas
            GET /api/db/schemas/{schema_name}
            GET /api/db/schemas/{schema_name}/tables

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with schema information
        """
        try:
            # Get route path
            route = req.route_params
            schema_name = route.get('schema_name')
            path = req.url.split('/api/db/schemas')[-1].strip('/')

            logger.info(f"📥 Admin DB Schemas request: path={path}, schema={schema_name}")

            # Route to appropriate handler
            if not path:
                # GET /api/admin/db/schemas
                return self._list_schemas(req)
            elif '/' in path:
                # GET /api/admin/db/schemas/{schema_name}/tables
                parts = path.split('/')
                schema = parts[0]
                return self._list_schema_tables(req, schema)
            else:
                # GET /api/admin/db/schemas/{schema_name}
                return self._get_schema_details(req, path)

        except Exception as e:
            logger.error(f"❌ Error in AdminDbSchemasTrigger: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _list_schemas(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all schemas with sizes and table counts.

        GET /api/admin/db/schemas

        Returns:
            {
                "schemas": [
                    {
                        "schema_name": "app",
                        "table_count": 2,
                        "total_size": "128 KB",
                        "data_size": "64 KB",
                        "index_size": "64 KB"
                    },
                    ...
                ],
                "count": 3,
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info("📊 Listing all schemas")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Query for all relevant schemas with sizes
                    query = """
                        SELECT
                            n.nspname as schema_name,
                            COUNT(DISTINCT c.relname) FILTER (WHERE c.relkind = 'r') as table_count,
                            pg_size_pretty(
                                COALESCE(SUM(pg_total_relation_size(c.oid)) FILTER (WHERE c.relkind = 'r'), 0)
                            ) as total_size,
                            pg_size_pretty(
                                COALESCE(SUM(pg_relation_size(c.oid)) FILTER (WHERE c.relkind = 'r'), 0)
                            ) as data_size,
                            pg_size_pretty(
                                COALESCE(SUM(pg_total_relation_size(c.oid) - pg_relation_size(c.oid)) FILTER (WHERE c.relkind = 'r'), 0)
                            ) as index_size
                        FROM pg_namespace n
                        LEFT JOIN pg_class c ON c.relnamespace = n.oid
                        WHERE n.nspname IN ('app', 'geo', 'pgstac', 'public')
                        GROUP BY n.nspname
                        ORDER BY n.nspname;
                    """

                    cursor.execute(query)
                    rows = cursor.fetchall()

                    schemas = []
                    for row in rows:
                        schemas.append({
                            'schema_name': row['schema_name'],
                            'table_count': row['table_count'] or 0,
                            'total_size': row['total_size'],
                            'data_size': row['data_size'],
                            'index_size': row['index_size']
                        })

            logger.info(f"✅ Found {len(schemas)} schemas")

            return func.HttpResponse(
                body=json.dumps({
                    'schemas': schemas,
                    'count': len(schemas),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error listing schemas: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_schema_details(self, req: func.HttpRequest, schema_name: str) -> func.HttpResponse:
        """
        Get detailed information about a specific schema.

        GET /api/admin/db/schemas/{schema_name}

        Args:
            schema_name: Name of schema (app, geo, pgstac, public)

        Returns:
            {
                "schema_name": "app",
                "table_count": 2,
                "function_count": 5,
                "total_size": "128 KB",
                "tables": [...],
                "functions": [...],
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info(f"📊 Getting details for schema: {schema_name}")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get tables in schema
                    cursor.execute("""
                        SELECT
                            t.tablename,
                            pg_size_pretty(pg_total_relation_size(c.oid)) as size
                        FROM pg_tables t
                        JOIN pg_namespace n ON n.nspname = t.schemaname
                        JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = n.oid
                        WHERE t.schemaname = %s
                        ORDER BY t.tablename;
                    """, (schema_name,))
                    table_rows = cursor.fetchall()

                    tables = [{'table_name': row['tablename'], 'size': row['size']} for row in table_rows]

                    # Get functions in schema
                    cursor.execute("""
                        SELECT
                            p.proname as function_name,
                            pg_get_functiondef(p.oid) as definition
                        FROM pg_proc p
                        JOIN pg_namespace n ON p.pronamespace = n.oid
                        WHERE n.nspname = %s
                        ORDER BY p.proname
                        LIMIT 20;
                    """, (schema_name,))
                    function_rows = cursor.fetchall()

                    functions = [{'function_name': row['function_name']} for row in function_rows]

                    # Get total schema size
                    cursor.execute("""
                        SELECT pg_size_pretty(
                            COALESCE(SUM(pg_total_relation_size(c.oid)), 0)
                        ) as total_size
                        FROM pg_tables t
                        JOIN pg_namespace n ON n.nspname = t.schemaname
                        JOIN pg_class c ON c.relname = t.tablename AND c.relnamespace = n.oid
                        WHERE t.schemaname = %s;
                    """, (schema_name,))
                    total_size = cursor.fetchone()['total_size']

            logger.info(f"✅ Schema {schema_name}: {len(tables)} tables, {len(functions)} functions")

            return func.HttpResponse(
                body=json.dumps({
                    'schema_name': schema_name,
                    'table_count': len(tables),
                    'function_count': len(functions),
                    'total_size': total_size,
                    'tables': tables,
                    'functions': functions,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting schema details: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _list_schema_tables(self, req: func.HttpRequest, schema_name: str) -> func.HttpResponse:
        """
        List all tables in a schema with row counts and sizes.

        GET /api/admin/db/schemas/{schema_name}/tables

        Args:
            schema_name: Name of schema

        Returns:
            {
                "schema_name": "app",
                "tables": [
                    {
                        "table_name": "jobs",
                        "row_count": 150,
                        "total_size": "64 KB",
                        "data_size": "32 KB",
                        "index_size": "32 KB",
                        "last_vacuum": "2025-11-01T...",
                        "last_analyze": "2025-11-01T..."
                    },
                    ...
                ],
                "count": 2,
                "timestamp": "2025-11-03T..."
            }
        """
        logger.info(f"📊 Listing tables in schema: {schema_name}")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get tables with statistics
                    cursor.execute("""
                        SELECT
                            s.schemaname,
                            s.relname as tablename,
                            s.n_live_tup as row_count,
                            pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
                            pg_size_pretty(pg_relation_size(c.oid)) as data_size,
                            pg_size_pretty(pg_indexes_size(c.oid)) as index_size,
                            s.last_vacuum,
                            s.last_autovacuum,
                            s.last_analyze,
                            s.last_autoanalyze
                        FROM pg_stat_user_tables s
                        JOIN pg_class c ON c.oid = s.relid
                        WHERE s.schemaname = %s
                        ORDER BY pg_total_relation_size(c.oid) DESC;
                    """, (schema_name,))
                    rows = cursor.fetchall()

                    tables = []
                    for row in rows:
                        tables.append({
                            'table_name': row['tablename'],
                            'row_count': row['row_count'] or 0,
                            'total_size': row['total_size'],
                            'data_size': row['data_size'],
                            'index_size': row['index_size'],
                            'last_vacuum': row['last_vacuum'].isoformat() if row['last_vacuum'] else None,
                            'last_autovacuum': row['last_autovacuum'].isoformat() if row['last_autovacuum'] else None,
                            'last_analyze': row['last_analyze'].isoformat() if row['last_analyze'] else None,
                            'last_autoanalyze': row['last_autoanalyze'].isoformat() if row['last_autoanalyze'] else None
                        })

            logger.info(f"✅ Found {len(tables)} tables in schema {schema_name}")

            return func.HttpResponse(
                body=json.dumps({
                    'schema_name': schema_name,
                    'tables': tables,
                    'count': len(tables),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error listing schema tables: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


# Singleton instance - created lazily on first route access
# Avoid module-level instantiation for Azure Functions cold start
admin_db_schemas_trigger = AdminDbSchemasTrigger.instance()
