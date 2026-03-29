# ============================================================================
# CLAUDE CONTEXT - VECTOR CREATE SPLIT VIEWS ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Create per-value PostgreSQL views on a PostGIS table
# PURPOSE: Standalone DAG node wrapping view_splitter.py functions in sequence
# LAST_REVIEWED: 19 MAR 2026
# EXPORTS: vector_create_split_views
# DEPENDENCIES: services.vector.view_splitter, services.vector.column_sanitizer,
#               infrastructure.postgresql
# ============================================================================
"""
Vector Create Split Views - atomic handler for DAG workflows.

Creates filtered PostgreSQL VIEWs on a PostGIS table based on distinct values
in a categorical column. Each view auto-registers in TiPG as a separate
OGC Feature collection.

Sequence: sanitize column name -> validate column -> discover values ->
          cleanup stale entries -> create views -> register catalog entries

Extracted from: handler_vector_docker_complete Phase 3.7 (line 1023)
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def vector_create_split_views(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Create split views on a PostGIS table from a categorical column.

    Params:
        table_name: Base PostGIS table name (already loaded)
        schema_name: PostGIS schema (default: "geo")
        split_column: Column name to split on (pre- or post-sanitization)
        geometry_type: Geometry type of base table (e.g., "MultiPolygon")
        srid: SRID of base table (default: 4326)
        title: Optional base title for catalog entries

    Returns:
        {"success": True, "result": {views_created, view_names, ...}}
    """
    table_name = params.get('table_name')
    schema_name = params.get('schema_name', 'geo')
    split_column = params.get('split_column') or (params.get('processing_options') or {}).get('split_column')
    geometry_type = params.get('geometry_type') or (params.get('processing_options') or {}).get('geometry_type')
    srid = params.get('srid') or (params.get('processing_options') or {}).get('srid', 4326)
    title = params.get('title')

    if not table_name:
        return {"success": False, "error": "table_name is required"}
    if not split_column:
        return {"success": False, "error": "split_column is required"}

    try:
        from services.vector.column_sanitizer import sanitize_column_name
        from services.vector.view_splitter import (
            validate_split_column,
            discover_split_values,
            create_split_views,
            register_split_views,
            cleanup_split_view_metadata,
        )
        from infrastructure.postgresql import PostgreSQLRepository

        # Normalize column name to post-sanitization form
        split_column_sanitized = sanitize_column_name(split_column)
        if split_column_sanitized != split_column:
            logger.info(f"Split column sanitized: '{split_column}' -> '{split_column_sanitized}'")

        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            # Step 1: Validate column exists and has categorical type
            col_info = validate_split_column(conn, table_name, schema_name, split_column_sanitized)
            logger.info(f"Split column validated: '{split_column_sanitized}' type={col_info['data_type']}")

            # Step 2: Discover distinct values (enforces cardinality limit)
            values = discover_split_values(conn, table_name, schema_name, split_column_sanitized)
            logger.info(f"Found {len(values)} distinct values for split")

            # Step 3: Clean up stale catalog entries (handles overwrite scenario)
            cleanup_split_view_metadata(conn, table_name)

            # Step 4: Create views (all in one transaction)
            views = create_split_views(conn, table_name, schema_name, split_column_sanitized, values)

            # Step 5: Register catalog entries
            registered = register_split_views(
                conn=conn,
                views=views,
                base_table_name=table_name,
                schema=schema_name,
                split_column=split_column_sanitized,
                base_title=title,
                geometry_type=geometry_type,
                srid=srid,
            )

            conn.commit()

        return {
            "success": True,
            "result": {
                "split_column": split_column_sanitized,
                "values": [str(v) for v in values],
                "views_created": len(views),
                "catalog_entries": registered,
                "view_names": [v['view_name'] for v in views],
            },
        }

    except ValueError as e:
        # Validation failures (column not found, bad type, cardinality)
        return {"success": False, "error": str(e), "error_type": "ValueError"}
    except Exception as e:
        logger.error(f"vector_create_split_views failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
