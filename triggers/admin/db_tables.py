# ============================================================================
# DATABASE TABLES ADMIN TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET /api/dbadmin/tables/{table_identifier}
# PURPOSE: Table-level inspection with PostGIS support
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: AdminDbTablesTrigger, admin_db_tables_trigger
# ============================================================================
"""
Database Tables Admin Trigger.

Table-level inspection of PostgreSQL tables with PostGIS support.

Consolidated endpoint pattern (15 DEC 2025):
    GET /api/dbadmin/tables/{table_identifier}?type={details|sample|columns|indexes}

Exports:
    AdminDbTablesTrigger: HTTP trigger class for table operations
    admin_db_tables_trigger: Singleton instance of AdminDbTablesTrigger
"""

import azure.functions as func
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, date
from typing import Dict, Any, List, Optional
import traceback
from decimal import Decimal

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbTables")


@dataclass
class RouteDefinition:
    """Route configuration for registry pattern."""
    route: str
    methods: list
    handler: str
    description: str


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


class AdminDbTablesTrigger:
    """
    Admin trigger for PostgreSQL table inspection.

    Singleton pattern for consistent configuration across requests.
    Handles geometry columns gracefully for geo schema.

    Consolidated API (15 DEC 2025):
        GET /api/dbadmin/tables/{table_identifier}?type={details|sample|columns|indexes}
    """

    _instance: Optional['AdminDbTablesTrigger'] = None

    # ========================================================================
    # ROUTE REGISTRY - Single source of truth for function_app.py
    # ========================================================================
    ROUTES = [
        RouteDefinition(
            route="dbadmin/tables/{table_identifier}",
            methods=["GET"],
            handler="handle_tables",
            description="Consolidated table ops: ?type={details|sample|columns|indexes}"
        ),
    ]

    # ========================================================================
    # OPERATIONS REGISTRY - Maps type param to handler method
    # ========================================================================
    OPERATIONS = {
        "details": "_get_table_details",
        "sample": "_get_table_sample",
        "columns": "_get_table_columns",
        "indexes": "_get_table_indexes",
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

        logger.info("🔧 Initializing AdminDbTablesTrigger")
        self._initialized = True
        logger.info("✅ AdminDbTablesTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbTablesTrigger':
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

    def handle_tables(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated table endpoint with type parameter.

        GET /api/dbadmin/tables/{table_identifier}?type={details|sample|columns|indexes}

        Path Parameters:
            table_identifier: Schema.table format (e.g., "geo.parcels")

        Query Parameters:
            type: Operation type (default: details)
                - details: Table statistics and overview
                - sample: Sample rows with geometry conversion
                - columns: Column definitions
                - indexes: Index definitions

        Returns:
            JSON response with requested table data
        """
        try:
            # Parse schema.table from route
            table_param = req.route_params.get('table_identifier')
            if not table_param or '.' not in table_param:
                return func.HttpResponse(
                    body=json.dumps({'error': 'table_identifier must be in format schema.table'}),
                    status_code=400,
                    mimetype='application/json'
                )

            schema_name, table_name = table_param.split('.', 1)
            op_type = req.params.get('type', 'details')

            logger.info(f"📥 Table request: {schema_name}.{table_name}, type={op_type}")

            if op_type not in self.OPERATIONS:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f"Unknown operation type: {op_type}",
                        'valid_types': list(self.OPERATIONS.keys()),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            handler_method = getattr(self, self.OPERATIONS[op_type])
            return handler_method(req, schema_name, table_name)

        except Exception as e:
            logger.error(f"❌ Error in handle_tables: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_table_details(self, req: func.HttpRequest, schema_name: str, table_name: str) -> func.HttpResponse:
        """
        Get complete table details.

        GET /api/dbadmin/tables/{schema}.{table}

        Returns:
            {
                "schema": "app",
                "table": "jobs",
                "row_count": 150,
                "total_size": "64 KB",
                "data_size": "32 KB",
                "index_size": "32 KB",
                "columns": [...],
                "indexes": [...],
                "constraints": [...]
            }
        """
        logger.info(f"📊 Getting details for table: {schema_name}.{table_name}")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Get table statistics
                    cursor.execute("""
                        SELECT
                            s.n_live_tup as row_count,
                            pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
                            pg_size_pretty(pg_relation_size(c.oid)) as data_size,
                            pg_size_pretty(pg_indexes_size(c.oid)) as index_size,
                            s.last_vacuum,
                            s.last_autovacuum,
                            s.last_analyze
                        FROM pg_stat_user_tables s
                        JOIN pg_class c ON c.oid = s.relid
                        WHERE s.schemaname = %s AND s.relname = %s;
                    """, (schema_name, table_name))
                    stats_row = cursor.fetchone()

                    if not stats_row:
                        return func.HttpResponse(
                            body=json.dumps({'error': f'Table {schema_name}.{table_name} not found'}),
                            status_code=404,
                            mimetype='application/json'
                        )

                    # Get columns
                    cursor.execute("""
                        SELECT
                            column_name,
                            data_type,
                            is_nullable,
                            column_default,
                            character_maximum_length
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position;
                    """, (schema_name, table_name))
                    column_rows = cursor.fetchall()

                    columns = []
                    for row in column_rows:
                        columns.append({
                            'column_name': row['column_name'],
                            'data_type': row['data_type'],
                            'nullable': row['is_nullable'] == 'YES',
                            'default': row['column_default'],
                            'max_length': row['character_maximum_length']
                        })

                    # Get indexes
                    cursor.execute("""
                        SELECT
                            i.indexname,
                            i.indexdef,
                            pg_size_pretty(pg_relation_size(c.oid)) as size
                        FROM pg_indexes i
                        JOIN pg_namespace n ON n.nspname = i.schemaname
                        JOIN pg_class c ON c.relname = i.indexname AND c.relnamespace = n.oid
                        WHERE i.schemaname = %s AND i.tablename = %s;
                    """, (schema_name, table_name))
                    index_rows = cursor.fetchall()

                    indexes = []
                    for row in index_rows:
                        indexes.append({
                            'index_name': row['indexname'],
                            'definition': row['indexdef'],
                            'size': row['size']
                        })

            result = {
                'schema': schema_name,
                'table': table_name,
                'row_count': stats_row['row_count'] or 0,
                'total_size': stats_row['total_size'],
                'data_size': stats_row['data_size'],
                'index_size': stats_row['index_size'],
                'last_vacuum': stats_row['last_vacuum'].isoformat() if stats_row['last_vacuum'] else None,
                'last_autovacuum': stats_row['last_autovacuum'].isoformat() if stats_row['last_autovacuum'] else None,
                'last_analyze': stats_row['last_analyze'].isoformat() if stats_row['last_analyze'] else None,
                'column_count': len(columns),
                'index_count': len(indexes),
                'columns': columns,
                'indexes': indexes,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Table details: {stats_row['row_count']} rows, {len(columns)} columns, {len(indexes)} indexes")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting table details: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_table_sample(self, req: func.HttpRequest, schema_name: str, table_name: str) -> func.HttpResponse:
        """
        Get sample rows from table.

        GET /api/dbadmin/tables/{schema}.{table}/sample?limit=10&offset=0&order_by=id

        Query Parameters:
            limit: Number of rows (default: 10, max: 100)
            offset: Starting offset (default: 0)
            order_by: Column to order by (default: first column)

        Special Handling:
            - geo schema: Converts geometry columns via ST_AsGeoJSON
            - Auto-detects geometry columns from information_schema

        Returns:
            {
                "schema": "geo",
                "table": "parcels",
                "rows": [...],
                "count": 10,
                "limit": 10,
                "offset": 0,
                "geometry_columns": ["geom"]
            }
        """
        # Parse query parameters
        limit = min(int(req.params.get('limit', 10)), 100)
        offset = int(req.params.get('offset', 0))
        order_by = req.params.get('order_by')

        logger.info(f"📊 Sampling table: {schema_name}.{table_name} (limit={limit}, offset={offset})")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Detect geometry columns
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        AND (
                            data_type = 'USER-DEFINED'
                            OR udt_name IN ('geometry', 'geography')
                        );
                    """, (schema_name, table_name))
                    geom_cols = [row['column_name'] for row in cursor.fetchall()]

                    # Get all column names
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position;
                    """, (schema_name, table_name))
                    all_cols = [row['column_name'] for row in cursor.fetchall()]

                    if not all_cols:
                        return func.HttpResponse(
                            body=json.dumps({'error': f'Table {schema_name}.{table_name} not found'}),
                            status_code=404,
                            mimetype='application/json'
                        )

                    # Build SELECT clause with geometry handling
                    select_parts = []
                    for col in all_cols:
                        if col in geom_cols:
                            select_parts.append(f'ST_AsGeoJSON({col}) as {col}')
                        else:
                            select_parts.append(col)

                    select_clause = ', '.join(select_parts)

                    # Determine order by column
                    if not order_by or order_by not in all_cols:
                        order_by = all_cols[0]

                    # Query sample rows
                    query = f"""
                        SELECT {select_clause}
                        FROM {schema_name}.{table_name}
                        ORDER BY {order_by} DESC
                        LIMIT %s OFFSET %s;
                    """

                    cursor.execute(query, (limit, offset))
                    rows = cursor.fetchall()

                    # Convert rows to dicts
                    result_rows = []
                    for row in rows:
                        row_dict = {}
                        for col in all_cols:
                            val = row[col]
                            if col in geom_cols and val:
                                # Parse GeoJSON string
                                try:
                                    row_dict[col] = json.loads(val)
                                except (json.JSONDecodeError, TypeError) as e:
                                    logger.debug(f"Could not parse GeoJSON for column {col}: {e}")
                                    row_dict[col] = val
                            else:
                                row_dict[col] = val
                        result_rows.append(row_dict)

            logger.info(f"✅ Sampled {len(result_rows)} rows from {schema_name}.{table_name}")

            result = {
                'schema': schema_name,
                'table': table_name,
                'rows': result_rows,
                'count': len(result_rows),
                'limit': limit,
                'offset': offset,
                'order_by': order_by,
                'geometry_columns': geom_cols,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                body=json.dumps(result, indent=2, default=json_serial),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error sampling table: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_table_columns(self, req: func.HttpRequest, schema_name: str, table_name: str) -> func.HttpResponse:
        """
        Get detailed column information for table.

        GET /api/dbadmin/tables/{schema}.{table}/columns

        Returns:
            {
                "schema": "app",
                "table": "jobs",
                "columns": [
                    {
                        "column_name": "job_id",
                        "ordinal_position": 1,
                        "data_type": "character varying",
                        "character_maximum_length": 255,
                        "is_nullable": "NO",
                        "column_default": null,
                        "is_geometry": false
                    },
                    ...
                ],
                "count": 12
            }
        """
        logger.info(f"📊 Getting columns for table: {schema_name}.{table_name}")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT
                            column_name,
                            ordinal_position,
                            data_type,
                            character_maximum_length,
                            numeric_precision,
                            numeric_scale,
                            is_nullable,
                            column_default,
                            udt_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position;
                    """, (schema_name, table_name))
                    rows = cursor.fetchall()

                    columns = []
                    for row in rows:
                        is_geometry = row['udt_name'] in ('geometry', 'geography') or row['data_type'] == 'USER-DEFINED'
                        columns.append({
                            'column_name': row['column_name'],
                            'ordinal_position': row['ordinal_position'],
                            'data_type': row['data_type'],
                            'character_maximum_length': row['character_maximum_length'],
                            'numeric_precision': row['numeric_precision'],
                            'numeric_scale': row['numeric_scale'],
                            'is_nullable': row['is_nullable'] == 'YES',
                            'column_default': row['column_default'],
                            'udt_name': row['udt_name'],
                            'is_geometry': is_geometry
                        })

            logger.info(f"✅ Found {len(columns)} columns")

            return func.HttpResponse(
                body=json.dumps({
                    'schema': schema_name,
                    'table': table_name,
                    'columns': columns,
                    'count': len(columns),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting table columns: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_table_indexes(self, req: func.HttpRequest, schema_name: str, table_name: str) -> func.HttpResponse:
        """
        Get index information for table.

        GET /api/dbadmin/tables/{schema}.{table}/indexes

        Returns:
            {
                "schema": "geo",
                "table": "parcels",
                "indexes": [
                    {
                        "index_name": "idx_parcels_geom",
                        "index_type": "gist",
                        "definition": "CREATE INDEX ...",
                        "size": "128 KB",
                        "columns": ["geom"]
                    },
                    ...
                ],
                "count": 3
            }
        """
        logger.info(f"📊 Getting indexes for table: {schema_name}.{table_name}")

        try:
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT
                            i.indexname,
                            i.indexdef,
                            pg_size_pretty(pg_relation_size(c.oid)) as size,
                            am.amname as index_type
                        FROM pg_indexes i
                        JOIN pg_namespace n ON n.nspname = i.schemaname
                        JOIN pg_class c ON c.relname = i.indexname AND c.relnamespace = n.oid
                        JOIN pg_am am ON am.oid = c.relam
                        WHERE i.schemaname = %s AND i.tablename = %s
                        ORDER BY i.indexname;
                    """, (schema_name, table_name))
                    rows = cursor.fetchall()

                    indexes = []
                    for row in rows:
                        indexes.append({
                            'index_name': row['indexname'],
                            'definition': row['indexdef'],
                            'size': row['size'],
                            'index_type': row['index_type']
                        })

            logger.info(f"✅ Found {len(indexes)} indexes")

            return func.HttpResponse(
                body=json.dumps({
                    'schema': schema_name,
                    'table': table_name,
                    'indexes': indexes,
                    'count': len(indexes),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting table indexes: {e}")
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
admin_db_tables_trigger = AdminDbTablesTrigger.instance()
