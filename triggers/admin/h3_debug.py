"""
H3 Debug Admin Trigger.

H3 bootstrap monitoring and debugging endpoints.

Exports:
    AdminH3DebugTrigger: HTTP trigger class for H3 debugging
    admin_h3_debug_trigger: Singleton instance of AdminH3DebugTrigger
"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure.h3_repository import H3Repository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminH3Debug")


class AdminH3DebugTrigger:
    """
    Admin trigger for H3 bootstrap monitoring and debugging.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminH3DebugTrigger'] = None

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

        logger.info("🔧 Initializing AdminH3DebugTrigger")
        self._initialized = True
        logger.info("✅ AdminH3DebugTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminH3DebugTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def h3_repo(self) -> H3Repository:
        """Lazy initialization of H3 repository."""
        if not hasattr(self, '_h3_repo'):
            logger.debug("🔧 Lazy loading H3 repository")
            self._h3_repo = H3Repository()
        return self._h3_repo

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route H3 debug requests based on operation parameter.

        Query parameter:
            operation: str - Required operation name

        Operations:
            schema_status, grid_summary, grid_details, reference_filters,
            reference_filter_details, sample_cells, parent_child_check
        """
        try:
            # Get operation from query params
            operation = req.params.get('operation')
            logger.info(f"🔍 H3 debug request: {req.method} operation={operation}")

            if not operation:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Missing 'operation' parameter",
                        "usage": "/api/admin/h3?operation={op}&{params}",
                        "available_operations": [
                            "schema_status",
                            "grid_summary",
                            "grid_details (requires grid_id param)",
                            "reference_filters",
                            "reference_filter_details (requires filter_name param)",
                            "sample_cells (requires grid_id param)",
                            "parent_child_check (requires parent_id param)",
                            "deploy_normalized_schema (requires confirm=yes)",
                            "drop_normalized_schema (requires confirm=yes)"
                        ]
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            # Route to appropriate handler
            if operation == 'schema_status':
                return self._schema_status(req)
            elif operation == 'grid_summary':
                return self._grid_summary(req)
            elif operation == 'grid_details':
                return self._grid_details(req)
            elif operation == 'reference_filters':
                return self._reference_filters(req)
            elif operation == 'reference_filter_details':
                return self._reference_filter_details(req)
            elif operation == 'sample_cells':
                return self._sample_cells(req)
            elif operation == 'parent_child_check':
                return self._parent_child_check(req)
            elif operation == 'delete_grids':
                return self._delete_grids(req)
            elif operation == 'nuke_h3':
                return self._nuke_h3(req)
            elif operation == 'deploy_normalized_schema':
                return self._deploy_normalized_schema(req)
            elif operation == 'drop_normalized_schema':
                return self._drop_normalized_schema(req)
            elif operation == 'seed_country_cells':
                return self._seed_country_cells(req)
            else:
                return func.HttpResponse(
                    json.dumps({
                        "error": f"Unknown operation: {operation}",
                        "available_operations": [
                            "schema_status",
                            "grid_summary",
                            "grid_details",
                            "reference_filters",
                            "reference_filter_details",
                            "sample_cells",
                            "parent_child_check",
                            "delete_grids",
                            "nuke_h3",
                            "deploy_normalized_schema",
                            "drop_normalized_schema",
                            "seed_country_cells"
                        ]
                    }),
                    status_code=404,
                    mimetype="application/json"
                )

        except Exception as e:
            logger.error(f"❌ H3 debug error: {e}\n{traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }),
                status_code=500,
                mimetype="application/json"
            )

    def _schema_status(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check H3 schema existence and table status.

        Returns:
            {
                "schema_exists": bool,
                "tables": ["grids", "grid_metadata", "reference_filters"],
                "table_counts": {"grids": 5882, ...},
                "indexes": [...]
            }
        """
        try:
            from psycopg import sql

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check schema exists
                    cur.execute("""
                        SELECT schema_name
                        FROM information_schema.schemata
                        WHERE schema_name = 'h3'
                    """)
                    schema_exists = cur.fetchone() is not None

                    if not schema_exists:
                        return func.HttpResponse(
                            json.dumps({
                                "schema_exists": False,
                                "error": "h3 schema does not exist - use /api/admin/h3?operation=deploy_normalized_schema&confirm=yes or POST /api/dbadmin/maintenance?action=full-rebuild&confirm=yes"
                            }),
                            status_code=404,
                            mimetype="application/json"
                        )

                    # Get tables in h3 schema
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'h3'
                        ORDER BY table_name
                    """)
                    tables = [row['table_name'] for row in cur.fetchall()]

                    # Get row counts for each table
                    table_counts = {}
                    for table in tables:
                        count_query = sql.SQL("SELECT COUNT(*) as count FROM {schema}.{table}").format(
                            schema=sql.Identifier('h3'),
                            table=sql.Identifier(table)
                        )
                        cur.execute(count_query)
                        table_counts[table] = cur.fetchone()['count']

                    # Get indexes
                    cur.execute("""
                        SELECT
                            schemaname,
                            tablename,
                            indexname,
                            indexdef
                        FROM pg_indexes
                        WHERE schemaname = 'h3'
                        ORDER BY tablename, indexname
                    """)
                    indexes = [dict(row) for row in cur.fetchall()]

                    # Get schema ownership info
                    cur.execute("""
                        SELECT
                            n.nspname as schema_name,
                            pg_catalog.pg_get_userbyid(n.nspowner) as owner,
                            current_user as current_user
                        FROM pg_catalog.pg_namespace n
                        WHERE n.nspname IN ('h3', 'app', 'geo', 'pgstac')
                        ORDER BY n.nspname
                    """)
                    ownership = {row['schema_name']: row['owner'] for row in cur.fetchall()}

                    # Check if current user can modify h3 schema
                    cur.execute("SELECT current_user")
                    current_user = cur.fetchone()['current_user']

            result = {
                "schema_exists": True,
                "tables": tables,
                "table_counts": table_counts,
                "index_count": len(indexes),
                "indexes": indexes,
                "schema_ownership": ownership,
                "current_user": current_user,
                "ownership_ok": ownership.get('h3') == current_user,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Schema status error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _grid_summary(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get summary of all H3 grids from grid_metadata.

        Returns bootstrap progress for all resolutions.
        """
        try:
            from psycopg import sql

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            grid_id,
                            resolution,
                            status,
                            cell_count,
                            land_cell_count,
                            source_job_id,
                            parent_grid_id,
                            created_at,
                            updated_at
                        FROM h3.grid_metadata
                        ORDER BY resolution
                    """)
                    grids = [dict(row) for row in cur.fetchall()]

                    # Convert timestamps to ISO format
                    for grid in grids:
                        if grid.get('created_at'):
                            grid['created_at'] = grid['created_at'].isoformat()
                        if grid.get('updated_at'):
                            grid['updated_at'] = grid['updated_at'].isoformat()

            result = {
                "total_grids": len(grids),
                "grids": grids,
                "summary": {
                    "completed": len([g for g in grids if g.get('status') == 'completed']),
                    "pending": len([g for g in grids if g.get('status') == 'pending']),
                    "processing": len([g for g in grids if g.get('status') == 'processing']),
                    "failed": len([g for g in grids if g.get('status') == 'failed'])
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Grid summary error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _grid_details(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get detailed statistics for a specific grid.

        Query params:
            grid_id: str - Required
            include_sample: bool - Include sample cells
        """
        try:
            from psycopg import sql

            grid_id = req.params.get('grid_id')
            if not grid_id:
                return func.HttpResponse(
                    json.dumps({"error": "grid_id parameter required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            include_sample = req.params.get('include_sample', 'false').lower() == 'true'

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get metadata
                    cur.execute("""
                        SELECT *
                        FROM h3.grid_metadata
                        WHERE grid_id = %s
                    """, (grid_id,))
                    metadata = dict(cur.fetchone()) if cur.rowcount > 0 else None

                    if not metadata:
                        return func.HttpResponse(
                            json.dumps({"error": f"Grid '{grid_id}' not found in grid_metadata"}),
                            status_code=404,
                            mimetype="application/json"
                        )

                    # Get actual cell count from grids table
                    cur.execute("""
                        SELECT
                            COUNT(*) as actual_count,
                            COUNT(*) FILTER (WHERE is_land = TRUE) as land_count,
                            COUNT(DISTINCT country_code) as country_count,
                            MIN(ST_XMin(geom)) as bbox_minx,
                            MIN(ST_YMin(geom)) as bbox_miny,
                            MAX(ST_XMax(geom)) as bbox_maxx,
                            MAX(ST_YMax(geom)) as bbox_maxy
                        FROM h3.grids
                        WHERE grid_id = %s
                    """, (grid_id,))
                    stats = dict(cur.fetchone())

                    # Sample cells if requested
                    sample_cells = None
                    if include_sample:
                        cur.execute("""
                            SELECT
                                h3_index,
                                resolution,
                                is_land,
                                country_code,
                                parent_res2,
                                parent_h3_index,
                                ST_AsText(geom) as geom_wkt
                            FROM h3.grids
                            WHERE grid_id = %s
                            ORDER BY h3_index
                            LIMIT 10
                        """, (grid_id,))
                        sample_cells = [dict(row) for row in cur.fetchall()]

            # Convert timestamps
            if metadata.get('created_at'):
                metadata['created_at'] = metadata['created_at'].isoformat()
            if metadata.get('updated_at'):
                metadata['updated_at'] = metadata['updated_at'].isoformat()

            result = {
                "grid_id": grid_id,
                "metadata": metadata,
                "statistics": stats,
                "sample_cells": sample_cells if include_sample else "Use ?include_sample=true to include",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Grid details error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _reference_filters(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all reference filters.

        Returns parent ID array metadata (without full arrays).
        """
        try:
            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            filter_name,
                            description,
                            resolution,
                            cell_count,
                            source_grid_id,
                            source_job_id,
                            array_length(h3_indices, 1) as array_length,
                            created_at,
                            updated_at
                        FROM h3.reference_filters
                        ORDER BY resolution
                    """)
                    filters = [dict(row) for row in cur.fetchall()]

                    # Convert timestamps
                    for f in filters:
                        if f.get('created_at'):
                            f['created_at'] = f['created_at'].isoformat()
                        if f.get('updated_at'):
                            f['updated_at'] = f['updated_at'].isoformat()

            result = {
                "total_filters": len(filters),
                "filters": filters,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Reference filters error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _reference_filter_details(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get detailed information about a specific reference filter.

        Query params:
            filter_name: str - Required
            include_ids: bool - Include first 100 parent IDs
        """
        try:
            filter_name = req.params.get('filter_name')
            if not filter_name:
                return func.HttpResponse(
                    json.dumps({"error": "filter_name parameter required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            include_ids = req.params.get('include_ids', 'false').lower() == 'true'

            filter_data = self.h3_repo.get_reference_filter(filter_name)

            if not filter_data:
                return func.HttpResponse(
                    json.dumps({"error": f"Reference filter '{filter_name}' not found"}),
                    status_code=404,
                    mimetype="application/json"
                )

            # Get metadata
            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT *
                        FROM h3.reference_filters
                        WHERE filter_name = %s
                    """, (filter_name,))
                    metadata = dict(cur.fetchone())

            # Convert timestamps
            if metadata.get('created_at'):
                metadata['created_at'] = metadata['created_at'].isoformat()
            if metadata.get('updated_at'):
                metadata['updated_at'] = metadata['updated_at'].isoformat()

            result = {
                "filter_name": filter_name,
                "metadata": metadata,
                "array_length": len(filter_data),
                "parent_ids": filter_data[:100] if include_ids else "Use ?include_ids=true to include first 100 IDs",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Reference filter details error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _sample_cells(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get sample cells from a grid.

        Query params:
            grid_id: str - Required
            limit: int - Default 10, max 100
            is_land: bool - Filter by land cells
        """
        try:
            grid_id = req.params.get('grid_id')
            if not grid_id:
                return func.HttpResponse(
                    json.dumps({"error": "grid_id parameter required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            limit = min(int(req.params.get('limit', 10)), 100)
            is_land = req.params.get('is_land')

            from psycopg import sql

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT
                            h3_index,
                            resolution,
                            is_land,
                            country_code,
                            parent_res2,
                            parent_h3_index,
                            grid_id,
                            grid_type,
                            ST_AsText(geom) as geom_wkt,
                            created_at
                        FROM h3.grids
                        WHERE grid_id = %s
                    """

                    params = [grid_id]

                    if is_land is not None:
                        is_land_bool = is_land.lower() == 'true'
                        query += " AND is_land = %s"
                        params.append(is_land_bool)

                    query += " ORDER BY h3_index LIMIT %s"
                    params.append(limit)

                    cur.execute(query, params)
                    cells = [dict(row) for row in cur.fetchall()]

                    # Convert timestamps
                    for cell in cells:
                        if cell.get('created_at'):
                            cell['created_at'] = cell['created_at'].isoformat()

            result = {
                "grid_id": grid_id,
                "filter": {"is_land": is_land} if is_land else None,
                "limit": limit,
                "cell_count": len(cells),
                "cells": cells,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Sample cells error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _parent_child_check(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Validate parent-child relationships.

        Query params:
            parent_id: int - Parent H3 index to check children
        """
        try:
            parent_id = req.params.get('parent_id')
            if not parent_id:
                return func.HttpResponse(
                    json.dumps({"error": "parent_id parameter required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            parent_id = int(parent_id)

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get parent cell
                    cur.execute("""
                        SELECT
                            h3_index,
                            resolution,
                            grid_id,
                            is_land,
                            country_code,
                            parent_res2
                        FROM h3.grids
                        WHERE h3_index = %s
                        LIMIT 1
                    """, (parent_id,))
                    parent = dict(cur.fetchone()) if cur.rowcount > 0 else None

                    if not parent:
                        return func.HttpResponse(
                            json.dumps({"error": f"Parent cell {parent_id} not found"}),
                            status_code=404,
                            mimetype="application/json"
                        )

                    # Get children
                    cur.execute("""
                        SELECT
                            h3_index,
                            resolution,
                            grid_id,
                            is_land,
                            country_code,
                            parent_h3_index,
                            parent_res2
                        FROM h3.grids
                        WHERE parent_h3_index = %s
                        ORDER BY h3_index
                    """, (parent_id,))
                    children = [dict(row) for row in cur.fetchall()]

            result = {
                "parent": parent,
                "children_count": len(children),
                "expected_children": 7 if parent['resolution'] < 7 else 0,
                "children": children,
                "validation": {
                    "count_match": len(children) == 7 if parent['resolution'] < 7 else True,
                    "all_children_reference_parent": all(c['parent_h3_index'] == parent_id for c in children),
                    "parent_res2_propagated": all(c.get('parent_res2') == parent.get('parent_res2') for c in children)
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Parent-child check error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _delete_grids(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Delete grids by prefix from h3.grids and h3.grid_metadata.

        Query params:
            grid_id_prefix: str - Required, prefix to match (e.g., "test_albania")
            confirm: str - Must be "yes" to actually delete

        Example:
            /api/h3/debug?operation=delete_grids&grid_id_prefix=test_albania&confirm=yes
        """
        try:
            grid_id_prefix = req.params.get('grid_id_prefix')
            confirm = req.params.get('confirm', '').lower() == 'yes'

            if not grid_id_prefix:
                return func.HttpResponse(
                    json.dumps({
                        "error": "grid_id_prefix parameter required",
                        "usage": "?operation=delete_grids&grid_id_prefix=test_albania&confirm=yes"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            from psycopg import sql

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Count grids to delete
                    cur.execute("""
                        SELECT COUNT(*) as count FROM h3.grids
                        WHERE grid_id LIKE %s
                    """, (f"{grid_id_prefix}%",))
                    cells_to_delete = cur.fetchone()['count']

                    cur.execute("""
                        SELECT COUNT(*) as count FROM h3.grid_metadata
                        WHERE grid_id LIKE %s
                    """, (f"{grid_id_prefix}%",))
                    metadata_to_delete = cur.fetchone()['count']

                    if not confirm:
                        return func.HttpResponse(
                            json.dumps({
                                "dry_run": True,
                                "grid_id_prefix": grid_id_prefix,
                                "cells_to_delete": cells_to_delete,
                                "metadata_to_delete": metadata_to_delete,
                                "message": "Add &confirm=yes to actually delete",
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }),
                            mimetype="application/json"
                        )

                    # Actually delete
                    cur.execute("""
                        DELETE FROM h3.grids
                        WHERE grid_id LIKE %s
                    """, (f"{grid_id_prefix}%",))
                    cells_deleted = cur.rowcount

                    cur.execute("""
                        DELETE FROM h3.grid_metadata
                        WHERE grid_id LIKE %s
                    """, (f"{grid_id_prefix}%",))
                    metadata_deleted = cur.rowcount

                conn.commit()

            logger.info(f"🗑️ Deleted grids: {cells_deleted} cells, {metadata_deleted} metadata for prefix '{grid_id_prefix}'")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "grid_id_prefix": grid_id_prefix,
                    "cells_deleted": cells_deleted,
                    "metadata_deleted": metadata_deleted,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Delete grids error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _nuke_h3(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Truncate all H3 tables (both legacy and normalized schema).

        Tables truncated:
            Legacy: grids, grid_metadata, batch_progress, reference_filters
            Normalized: cells, cell_admin0, cell_admin1, zonal_stats, point_stats

        Query params:
            confirm: str - Must be "yes" to actually truncate

        WARNING: This is destructive and cannot be undone!
        """
        try:
            confirm = req.params.get('confirm', '').lower() == 'yes'

            # All H3 tables (legacy + normalized)
            all_tables = [
                'grids', 'grid_metadata', 'batch_progress', 'reference_filters',  # Legacy
                'cells', 'cell_admin0', 'cell_admin1', 'zonal_stats', 'point_stats'  # Normalized
            ]

            from psycopg import sql

            with self.h3_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Count rows before
                    counts_before = {}
                    for table in all_tables:
                        try:
                            count_query = sql.SQL("SELECT COUNT(*) as count FROM {schema}.{table}").format(
                                schema=sql.Identifier('h3'),
                                table=sql.Identifier(table)
                            )
                            cur.execute(count_query)
                            counts_before[table] = cur.fetchone()['count']
                        except Exception:
                            counts_before[table] = 0

                    if not confirm:
                        return func.HttpResponse(
                            json.dumps({
                                "dry_run": True,
                                "tables_to_truncate": list(counts_before.keys()),
                                "rows_to_delete": counts_before,
                                "total_rows": sum(counts_before.values()),
                                "message": "Add &confirm=yes to actually truncate",
                                "warning": "⚠️ This is DESTRUCTIVE and cannot be undone!",
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }),
                            mimetype="application/json"
                        )

                    # Truncate all tables (normalized first due to FK constraints)
                    # Order: mapping tables → main tables
                    truncate_order = [
                        'cell_admin0', 'cell_admin1', 'zonal_stats', 'point_stats',  # Normalized mappings
                        'cells',  # Normalized main
                        'grids', 'grid_metadata', 'batch_progress', 'reference_filters'  # Legacy
                    ]
                    for table in truncate_order:
                        try:
                            truncate_query = sql.SQL("TRUNCATE TABLE {schema}.{table} CASCADE").format(
                                schema=sql.Identifier('h3'),
                                table=sql.Identifier(table)
                            )
                            cur.execute(truncate_query)
                        except Exception as e:
                            logger.warning(f"Could not truncate h3.{table}: {e}")

                conn.commit()

            logger.warning(f"🔥 NUKED H3 TABLES: {counts_before}")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "rows_deleted": counts_before,
                    "total_rows": sum(counts_before.values()),
                    "tables_truncated": truncate_order,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Nuke H3 error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

    def _deploy_normalized_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Deploy H3 normalized schema (cells, cell_admin0, cell_admin1, zonal_stats, point_stats).

        Query params:
            confirm: str - Must be "yes" to actually deploy

        Returns:
            Deployment results with steps and status
        """
        try:
            confirm = req.params.get('confirm', '').lower() == 'yes'

            if not confirm:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Deployment requires confirm=yes",
                        "usage": "/api/admin/h3?operation=deploy_normalized_schema&confirm=yes",
                        "warning": "This will CREATE h3.cells, h3.cell_admin0, h3.cell_admin1, h3.zonal_stats, h3.point_stats tables",
                        "note": "Safe to run - uses IF NOT EXISTS, will not overwrite data"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            # Import and deploy
            from infrastructure.h3_schema import H3SchemaDeployer

            logger.info("🚀 Deploying H3 normalized schema...")
            deployer = H3SchemaDeployer()
            result = deployer.deploy_all()

            status_code = 200 if result.get('success') else 500
            logger.info(f"{'✅' if result.get('success') else '❌'} Schema deployment: {result}")

            return func.HttpResponse(
                json.dumps(result, default=str),
                status_code=status_code,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Deploy normalized schema error: {e}\n{traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }),
                status_code=500,
                mimetype="application/json"
            )

    def _drop_normalized_schema(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Drop H3 normalized schema tables (preserves legacy h3.grids).

        Query params:
            confirm: str - Must be "yes" to actually drop

        WARNING: Destructive operation!
        """
        try:
            confirm = req.params.get('confirm', '').lower() == 'yes'

            if not confirm:
                return func.HttpResponse(
                    json.dumps({
                        "error": "Drop requires confirm=yes",
                        "usage": "/api/admin/h3?operation=drop_normalized_schema&confirm=yes",
                        "warning": "DESTRUCTIVE: Will DROP h3.cells, cell_admin0, cell_admin1, zonal_stats, point_stats",
                        "note": "Legacy h3.grids table will NOT be affected"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            # Import and drop
            from infrastructure.h3_schema import H3SchemaDeployer

            logger.warning("🔥 Dropping H3 normalized schema tables...")
            deployer = H3SchemaDeployer()
            result = deployer.drop_all(confirm=True)

            logger.warning(f"Drop result: {result}")

            return func.HttpResponse(
                json.dumps(result, default=str),
                status_code=200,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Drop normalized schema error: {e}\n{traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }),
                status_code=500,
                mimetype="application/json"
            )

    def _seed_country_cells(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Seed H3 cells for a country using bbox-based polyfill.

        DEV/TEST ONLY - Generates H3 cells for a country without requiring admin0 table.
        Uses predefined bboxes for common test countries.

        Query params:
            iso3: str - ISO3 country code (e.g., "GRC" for Greece)
            resolution: int - H3 resolution (default: 6)
            confirm: str - Must be "yes" to actually insert

        Example:
            /api/h3/debug?operation=seed_country_cells&iso3=GRC&resolution=6&confirm=yes
        """
        try:
            iso3 = req.params.get('iso3', '').upper()
            resolution = int(req.params.get('resolution', 6))
            confirm = req.params.get('confirm', '').lower() == 'yes'

            # Predefined bboxes for test countries (minx, miny, maxx, maxy)
            COUNTRY_BBOXES = {
                'GRC': (19.3, 34.8, 29.7, 41.8),   # Greece
                'ALB': (19.3, 39.6, 21.1, 42.7),   # Albania
                'MLT': (14.1, 35.8, 14.6, 36.1),   # Malta (small, fast test)
                'CYP': (32.2, 34.6, 34.6, 35.7),   # Cyprus
                'RWA': (28.8, -2.9, 30.9, -1.0),   # Rwanda
            }

            if not iso3:
                return func.HttpResponse(
                    json.dumps({
                        "error": "iso3 parameter required",
                        "available_countries": list(COUNTRY_BBOXES.keys()),
                        "usage": "?operation=seed_country_cells&iso3=GRC&resolution=6&confirm=yes"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            if iso3 not in COUNTRY_BBOXES:
                return func.HttpResponse(
                    json.dumps({
                        "error": f"Unknown country code: {iso3}",
                        "available_countries": list(COUNTRY_BBOXES.keys()),
                        "hint": "Add new countries to COUNTRY_BBOXES in h3_debug.py"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            if resolution < 0 or resolution > 10:
                return func.HttpResponse(
                    json.dumps({
                        "error": f"Resolution must be 0-10, got {resolution}",
                        "hint": "Resolution 6 is recommended for country-level analysis"
                    }),
                    status_code=400,
                    mimetype="application/json"
                )

            bbox = COUNTRY_BBOXES[iso3]

            # Generate cells using h3 polyfill
            import h3
            from shapely.geometry import Polygon

            polygon = Polygon([
                (bbox[0], bbox[1]),
                (bbox[2], bbox[1]),
                (bbox[2], bbox[3]),
                (bbox[0], bbox[3]),
                (bbox[0], bbox[1])
            ])

            # Get H3 cells
            h3_cells = list(h3.geo_to_cells(polygon, res=resolution))
            cell_count = len(h3_cells)

            if not confirm:
                return func.HttpResponse(
                    json.dumps({
                        "dry_run": True,
                        "iso3": iso3,
                        "resolution": resolution,
                        "bbox": bbox,
                        "cells_to_insert": cell_count,
                        "message": f"Add &confirm=yes to insert {cell_count:,} cells",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }),
                    mimetype="application/json"
                )

            # Convert to cell dicts with geometry
            cells_data = []
            mappings_data = []

            for h3_str in h3_cells:
                h3_index = h3.str_to_int(h3_str)
                # Get cell boundary
                boundary = h3.cell_to_boundary(h3_str)
                # Create WKT polygon (h3 returns lat,lon so we swap to lon,lat)
                coords = [(lon, lat) for lat, lon in boundary]
                coords.append(coords[0])  # Close polygon
                wkt = "POLYGON((" + ",".join(f"{x} {y}" for x, y in coords) + "))"

                # Skip parent_h3_index to avoid FK constraint issues during test seeding
                # In production, use bootstrap_h3_land_grid_pyramid for proper hierarchy
                cells_data.append({
                    'h3_index': h3_index,
                    'resolution': resolution,
                    'geom_wkt': wkt,
                    'parent_h3_index': None,  # Skip hierarchy for test seeding
                    'is_land': True
                })

                mappings_data.append({
                    'h3_index': h3_index,
                    'iso3': iso3,
                    'coverage_pct': 1.0
                })

            # Insert cells and mappings
            cells_inserted = self.h3_repo.insert_cells(cells_data, source_job_id=f"seed_{iso3}_res{resolution}")
            mappings_inserted = self.h3_repo.insert_cell_admin0_mappings(mappings_data)

            logger.info(f"✅ Seeded {cells_inserted} cells and {mappings_inserted} mappings for {iso3} at res {resolution}")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "iso3": iso3,
                    "resolution": resolution,
                    "bbox": bbox,
                    "cells_inserted": cells_inserted,
                    "mappings_inserted": mappings_inserted,
                    "duplicates_skipped": cell_count - cells_inserted,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Seed country cells error: {e}\n{traceback.format_exc()}")
            return func.HttpResponse(
                json.dumps({
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }),
                status_code=500,
                mimetype="application/json"
            )


# ============================================================================
# MODULE EXPORT (Singleton instance for function_app.py)
# ============================================================================
admin_h3_debug_trigger = AdminH3DebugTrigger.instance()