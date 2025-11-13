# ============================================================================
# CLAUDE CONTEXT - H3 DEBUG ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Admin API - H3 bootstrap monitoring and debugging
# PURPOSE: HTTP trigger for H3 grid status, cell counts, and bootstrap progress
# LAST_REVIEWED: 10 NOV 2025
# EXPORTS: AdminH3DebugTrigger - Singleton trigger for H3 debugging
# INTERFACES: Azure Functions HTTP trigger
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: azure.functions, infrastructure.h3_repository, util_logger
# SOURCE: PostgreSQL h3.grids, h3.grid_metadata, h3.reference_filters
# SCOPE: Read-only query analysis for debugging H3 bootstrap operations
# VALIDATION: None yet (future APIM authentication)
# PATTERNS: Singleton trigger, RESTful admin API
# ENTRY_POINTS: AdminH3DebugTrigger.instance().handle_request(req)
# INDEX:
#   - AdminH3DebugTrigger:50
#   - schema_status:120 - Check h3 schema exists
#   - grid_summary:180 - Grid metadata for all resolutions
#   - grid_details:250 - Detailed cell counts and stats
#   - reference_filters:320 - Parent ID arrays for cascade
#   - sample_cells:390 - Sample H3 cells for verification
#   - parent_child_check:460 - Validate hierarchy
# ============================================================================

"""
H3 Debug Admin Trigger

Single consolidated endpoint for all H3 bootstrap monitoring and debugging.

Endpoint:
    GET /api/admin/h3?operation={op}&{params}

Operations:
    - schema_status: Check h3 schema exists and table status
    - grid_summary: Grid metadata for all resolutions
    - grid_details: Detailed stats for specific grid (param: grid_id, include_sample)
    - reference_filters: List all reference filters
    - reference_filter_details: Details for specific filter (param: filter_name, include_ids)
    - sample_cells: Sample cells from grid (params: grid_id, limit, is_land)
    - parent_child_check: Validate hierarchy (param: parent_id)

Examples:
    /api/admin/h3?operation=schema_status
    /api/admin/h3?operation=grid_summary
    /api/admin/h3?operation=grid_details&grid_id=land_res2&include_sample=true
    /api/admin/h3?operation=reference_filters
    /api/admin/h3?operation=sample_cells&grid_id=land_res2&limit=10&is_land=true
    /api/admin/h3?operation=parent_child_check&parent_id=12345

Critical for:
- Verifying Phase 1 schema deployment
- Monitoring Phase 2 bootstrap progress (res 2 spatial filtering)
- Debugging Phase 3 cascade operations (res 3-7)
- Validating cell counts match expected values
- Inspecting parent-child relationships

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
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
                            "parent_child_check (requires parent_id param)"
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
                            "parent_child_check"
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
                                "error": "h3 schema does not exist - run sql/init/00_create_h3_schema.sql"
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

            result = {
                "schema_exists": True,
                "tables": tables,
                "table_counts": table_counts,
                "index_count": len(indexes),
                "indexes": indexes,
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


# ============================================================================
# MODULE EXPORT (Singleton instance for function_app.py)
# ============================================================================
admin_h3_debug_trigger = AdminH3DebugTrigger.instance()