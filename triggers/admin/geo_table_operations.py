# ============================================================================
# GEO TABLE OPERATIONS
# ============================================================================
# STATUS: Trigger layer - Geo schema table management
# PURPOSE: List, unpublish, and manage tables in geo schema
# CREATED: 12 JAN 2026 (split from db_maintenance.py)
# ============================================================================
"""
Geo Table Operations.

Extracted from db_maintenance.py (2,673 lines) for maintainability.
Handles vector table management in the geo schema.

Exports:
    GeoTableOperations: Class with geo table management methods
"""

import azure.functions as func
import json
import logging
import traceback
from datetime import datetime, timezone

from psycopg import sql

from infrastructure import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "GeoTableOperations")


class GeoTableOperations:
    """
    Geo schema table management operations.

    Handles:
    - Listing tables with metadata status
    - Unpublishing tables (cascade delete)
    - Listing metadata records
    - Checking for orphaned tables/metadata
    """

    def __init__(self, db_repo: PostgreSQLRepository):
        """Initialize with database repository."""
        self.db_repo = db_repo

    def unpublish_geo_table(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Cascade delete a vector table from geo schema.

        POST /api/dbadmin/geo?action=unpublish&table_name={name}&confirm=yes

        Handles both tracked tables (with metadata) and orphaned tables:
        - Tracked: Delete STAC item -> Delete metadata -> Drop table
        - Orphaned: Just drop the table (warnings logged)

        Query Parameters:
            table_name: Required. Table name (without schema prefix)
            confirm: Required. Must be "yes" to execute

        Returns:
            JSON with deletion status and warnings
        """
        table_name = req.params.get('table_name')
        confirm = req.params.get('confirm')

        # Validate parameters
        if not table_name:
            return func.HttpResponse(
                body=json.dumps({
                    "error": "table_name parameter required",
                    "usage": "POST /api/dbadmin/geo?action=unpublish&table_name={name}&confirm=yes"
                }),
                status_code=400,
                mimetype='application/json'
            )

        if confirm != 'yes':
            return func.HttpResponse(
                body=json.dumps({
                    "error": "Confirmation required",
                    "message": "Add &confirm=yes to execute this destructive operation",
                    "table_name": table_name,
                    "warning": "This will permanently delete the table and associated metadata"
                }),
                status_code=400,
                mimetype='application/json'
            )

        # Curated table protection (15 DEC 2025)
        force_curated = req.params.get('force') == 'curated'
        if table_name.startswith('curated_') and not force_curated:
            logger.warning(
                f"Attempted to unpublish protected curated table: {table_name}. "
                f"Use force=curated or curated dataset management API."
            )
            return func.HttpResponse(
                body=json.dumps({
                    "error": f"Cannot unpublish curated table '{table_name}'",
                    "message": "Curated tables are system-managed and protected. "
                               "Use the curated dataset management API instead.",
                    "table_name": table_name,
                    "is_curated": True,
                    "bypass_hint": "Add &force=curated if you have authorization to drop curated tables"
                }),
                status_code=403,
                mimetype='application/json'
            )

        logger.info(f"Unpublishing geo table: {table_name}")

        result = {
            "success": False,
            "table_name": table_name,
            "deleted": {
                "stac_item": None,
                "metadata_row": False,
                "geo_table": False
            },
            "warnings": [],
            "was_orphaned": False
        }

        try:
            repo = PostgreSQLRepository()

            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Step 0: Verify table exists in geo schema
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = %s
                        ) as table_exists
                    """, (table_name,))
                    row = cur.fetchone()
                    exists = row['table_exists'] if row else False

                    if not exists:
                        result["error"] = f"Table '{table_name}' does not exist in geo schema"
                        return func.HttpResponse(
                            body=json.dumps(result),
                            status_code=404,
                            mimetype='application/json'
                        )

                    # Step 1: Look up STAC item ID from catalog (21 JAN 2026: geo.table_catalog)
                    stac_item_id = None
                    stac_collection_id = None

                    # Check if geo.table_catalog exists first
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_catalog'
                        ) as catalog_table_exists
                    """)
                    catalog_table_exists = cur.fetchone()['catalog_table_exists']

                    if catalog_table_exists:
                        cur.execute("""
                            SELECT stac_item_id, stac_collection_id
                            FROM geo.table_catalog
                            WHERE table_name = %s
                        """, (table_name,))
                        catalog_row = cur.fetchone()

                        if catalog_row:
                            stac_item_id = catalog_row.get('stac_item_id')
                            stac_collection_id = catalog_row.get('stac_collection_id')
                            logger.info(f"Found catalog for {table_name}: STAC item={stac_item_id}")
                        else:
                            result["was_orphaned"] = True
                            result["warnings"].append(
                                "No catalog found - table was orphaned (created outside ETL or catalog wiped)"
                            )
                    else:
                        result["was_orphaned"] = True
                        result["warnings"].append(
                            "geo.table_catalog table does not exist - cannot lookup STAC linkage"
                        )

                    # Step 2: Delete STAC item (if we have an ID)
                    if stac_item_id:
                        try:
                            # Check if pgstac.items exists
                            cur.execute("""
                                SELECT EXISTS (
                                    SELECT 1 FROM information_schema.tables
                                    WHERE table_schema = 'pgstac' AND table_name = 'items'
                                ) as pgstac_exists
                            """)
                            pgstac_exists = cur.fetchone()['pgstac_exists']

                            if pgstac_exists:
                                # Use savepoint to isolate potential trigger failures
                                cur.execute("SAVEPOINT stac_delete")
                                try:
                                    cur.execute("""
                                        DELETE FROM pgstac.items
                                        WHERE id = %s
                                        RETURNING id
                                    """, (stac_item_id,))
                                    deleted_stac = cur.fetchone()
                                    if deleted_stac:
                                        result["deleted"]["stac_item"] = stac_item_id
                                        logger.info(f"Deleted STAC item: {stac_item_id}")
                                        cur.execute("RELEASE SAVEPOINT stac_delete")
                                    else:
                                        result["warnings"].append(
                                            f"STAC item '{stac_item_id}' not found in pgstac.items (already deleted)"
                                        )
                                        cur.execute("RELEASE SAVEPOINT stac_delete")
                                except Exception as stac_error:
                                    # Rollback just the STAC deletion, continue with metadata/table
                                    cur.execute("ROLLBACK TO SAVEPOINT stac_delete")
                                    result["warnings"].append(
                                        f"STAC item deletion failed (pgstac trigger error): {stac_error}"
                                    )
                                    logger.warning(f"STAC item deletion failed, continuing: {stac_error}")
                            else:
                                result["warnings"].append(
                                    "pgstac.items table does not exist - STAC deletion skipped"
                                )
                        except Exception as e:
                            result["warnings"].append(f"Failed to delete STAC item: {e}")
                            logger.warning(f"STAC item deletion failed: {e}")
                    elif not result["was_orphaned"]:
                        result["warnings"].append(
                            "No STAC item ID in metadata (STAC cataloging may have been skipped or degraded mode)"
                        )

                    # Step 3: Delete catalog and ETL tracking rows (21 JAN 2026)
                    if catalog_table_exists:
                        cur.execute("""
                            DELETE FROM geo.table_catalog
                            WHERE table_name = %s
                            RETURNING table_name
                        """, (table_name,))
                        deleted_catalog = cur.fetchone()
                        result["deleted"]["catalog_row"] = deleted_catalog is not None
                        if deleted_catalog:
                            logger.info(f"Deleted catalog row for {table_name}")

                        # Also delete ETL tracking rows (may have multiple)
                        cur.execute("""
                            DELETE FROM app.vector_etl_tracking
                            WHERE table_name = %s
                            RETURNING table_name
                        """, (table_name,))
                        deleted_etl = cur.fetchone()
                        result["deleted"]["etl_tracking_rows"] = deleted_etl is not None
                        if deleted_etl:
                            logger.info(f"Deleted ETL tracking rows for {table_name}")

                    # Step 4: DROP TABLE CASCADE
                    cur.execute(
                        sql.SQL("DROP TABLE IF EXISTS {schema}.{table} CASCADE").format(
                            schema=sql.Identifier("geo"),
                            table=sql.Identifier(table_name)
                        )
                    )
                    result["deleted"]["geo_table"] = True
                    logger.info(f"Dropped table geo.{table_name}")

                    conn.commit()

            result["success"] = True
            logger.info(f"Successfully unpublished geo.{table_name}")

            return func.HttpResponse(
                body=json.dumps(result, default=str),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"Error unpublishing geo.{table_name}: {e}")
            logger.error(traceback.format_exc())
            result["error"] = str(e)
            result["error_type"] = type(e).__name__
            return func.HttpResponse(
                body=json.dumps(result, default=str),
                status_code=500,
                mimetype='application/json'
            )

    def list_geo_tables(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all tables in the geo schema with metadata status.

        GET /api/dbadmin/geo?type=tables

        Returns tables with their tracking status (has metadata, has STAC item).
        Useful for discovering orphaned tables after a full-rebuild.

        Returns:
            JSON with tables list and summary
        """
        logger.info("Listing geo schema tables...")

        try:
            repo = PostgreSQLRepository()
            tables = []

            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get all tables in geo schema (excluding system tables)
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'geo'
                        AND table_type = 'BASE TABLE'
                        AND table_name NOT IN ('table_catalog', 'table_metadata', 'feature_collection_styles')
                        ORDER BY table_name
                    """)
                    geo_tables = [row['table_name'] for row in cur.fetchall()]

                    # Check if geo.table_catalog exists (21 JAN 2026)
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_catalog'
                        ) as catalog_table_exists
                    """)
                    catalog_table_exists = cur.fetchone()['catalog_table_exists']

                    # Check if pgstac.items exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'pgstac' AND table_name = 'items'
                        ) as pgstac_exists
                    """)
                    pgstac_exists = cur.fetchone()['pgstac_exists']

                    # Build catalog lookup dict if table exists (21 JAN 2026)
                    catalog_lookup = {}
                    if catalog_table_exists:
                        cur.execute("""
                            SELECT
                                table_name,
                                title,
                                feature_count,
                                stac_item_id,
                                created_at
                            FROM geo.table_catalog
                        """)
                        for row in cur.fetchall():
                            catalog_lookup[row['table_name']] = {
                                'title': row.get('title'),
                                'feature_count': row.get('feature_count'),
                                'stac_item_id': row.get('stac_item_id'),
                                'created_at': row['created_at'].isoformat() if row.get('created_at') else None
                            }

                    # Build STAC item lookup if table exists
                    stac_item_ids = set()
                    if pgstac_exists:
                        cur.execute("SELECT id FROM pgstac.items")
                        stac_item_ids = {row['id'] for row in cur.fetchall()}

                    # Build table list with status (21 JAN 2026: use catalog_lookup)
                    tracked_count = 0
                    orphaned_count = 0

                    for table_name in geo_tables:
                        catalog = catalog_lookup.get(table_name)
                        has_catalog = catalog is not None
                        stac_item_id = catalog.get('stac_item_id') if catalog else None
                        has_stac_item = stac_item_id in stac_item_ids if stac_item_id else False

                        table_info = {
                            "table_name": table_name,
                            "has_catalog": has_catalog,
                            "has_stac_item": has_stac_item,
                            "feature_count": catalog.get('feature_count') if catalog else None,
                            "title": catalog.get('title') if catalog else None,
                            "created_at": catalog.get('created_at') if catalog else None
                        }
                        tables.append(table_info)

                        if has_catalog:
                            tracked_count += 1
                        else:
                            orphaned_count += 1

            result = {
                "tables": tables,
                "summary": {
                    "total": len(tables),
                    "tracked": tracked_count,
                    "orphaned": orphaned_count
                },
                "schema_status": {
                    "geo_table_catalog_exists": catalog_table_exists,
                    "pgstac_items_exists": pgstac_exists
                }
            }

            logger.info(f"Found {len(tables)} geo tables ({tracked_count} tracked, {orphaned_count} orphaned)")

            return func.HttpResponse(
                body=json.dumps(result, default=str, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"Error listing geo tables: {e}")
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

    def list_metadata(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all records in geo.table_catalog with filtering options.

        GET /api/dbadmin/geo?type=metadata
        GET /api/dbadmin/geo?type=metadata&has_stac=true
        GET /api/dbadmin/geo?type=metadata&limit=50&offset=0

        NOTE (21 JAN 2026): Changed from geo.table_metadata to geo.table_catalog.
        ETL fields (etl_job_id, source_file, etc.) are now in app.vector_etl_tracking.

        Query Parameters:
            has_stac: Filter by STAC linkage (true/false)
            limit: Max records (default: 100, max: 500)
            offset: Pagination offset (default: 0)

        Returns:
            JSON with catalog records, total count, and filters applied
        """
        # Parse query parameters
        has_stac = req.params.get('has_stac')

        try:
            limit = int(req.params.get('limit', 100))
        except ValueError:
            limit = 100
        try:
            offset = int(req.params.get('offset', 0))
        except ValueError:
            offset = 0

        # Clamp limits
        limit = min(max(1, limit), 500)  # 1-500
        offset = max(0, offset)

        filters_applied = {}

        try:
            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if table_catalog exists (21 JAN 2026)
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo' AND table_name = 'table_catalog'
                        )
                    """)
                    if not cur.fetchone()['exists']:
                        return func.HttpResponse(
                            body=json.dumps({
                                'error': 'geo.table_catalog table does not exist',
                                'hint': 'Run full-rebuild to create schema'
                            }),
                            status_code=404,
                            mimetype='application/json'
                        )

                    # Build dynamic WHERE clause
                    conditions = []
                    params = []

                    if has_stac is not None:
                        if has_stac.lower() == 'true':
                            conditions.append("stac_item_id IS NOT NULL")
                            filters_applied['has_stac'] = True
                        elif has_stac.lower() == 'false':
                            conditions.append("stac_item_id IS NULL")
                            filters_applied['has_stac'] = False

                    where_clause = ""
                    if conditions:
                        where_clause = "WHERE " + " AND ".join(conditions)

                    # Get total count
                    count_sql = f"SELECT COUNT(*) FROM geo.table_catalog {where_clause}"
                    cur.execute(count_sql, params)
                    total = cur.fetchone()['count']

                    # Discover which columns actually exist in the table
                    cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'geo' AND table_name = 'table_catalog'
                    """)
                    existing_columns = set(row['column_name'] for row in cur.fetchall())

                    # Define columns we want (21 JAN 2026: service layer only, no ETL fields)
                    desired_columns = [
                        'table_name', 'schema_name',
                        'title', 'description', 'attribution', 'license', 'keywords',
                        'feature_count', 'geometry_type',
                        'stac_item_id', 'stac_collection_id',
                        'bbox_minx', 'bbox_miny', 'bbox_maxx', 'bbox_maxy',
                        'temporal_start', 'temporal_end', 'temporal_property',
                        'created_at', 'updated_at'
                    ]

                    # Only select columns that exist
                    select_columns = [c for c in desired_columns if c in existing_columns]

                    # Get records
                    query = f"""
                        SELECT {', '.join(select_columns)}
                        FROM geo.table_catalog
                        {where_clause}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """
                    cur.execute(query, params + [limit, offset])

                    # Helper to safely get value from row
                    def safe_get(row_dict, key, default=None):
                        if key in existing_columns:
                            return row_dict.get(key, default)
                        return default

                    catalog_records = []
                    for row in cur.fetchall():
                        item = {
                            'table_name': row['table_name'],
                            'schema_name': safe_get(row, 'schema_name', 'geo'),
                            'feature_count': safe_get(row, 'feature_count'),
                            'geometry_type': safe_get(row, 'geometry_type'),
                            'stac_item_id': safe_get(row, 'stac_item_id'),
                            'stac_collection_id': safe_get(row, 'stac_collection_id'),
                        }

                        # Timestamps
                        created_at = safe_get(row, 'created_at')
                        updated_at = safe_get(row, 'updated_at')
                        item['created_at'] = created_at.isoformat() if created_at else None
                        item['updated_at'] = updated_at.isoformat() if updated_at else None

                        # New metadata columns (may not exist in older schemas)
                        if 'title' in existing_columns:
                            item['title'] = safe_get(row, 'title')
                        if 'description' in existing_columns:
                            item['description'] = safe_get(row, 'description')
                        if 'attribution' in existing_columns:
                            item['attribution'] = safe_get(row, 'attribution')
                        if 'license' in existing_columns:
                            item['license'] = safe_get(row, 'license')
                        if 'keywords' in existing_columns:
                            item['keywords'] = safe_get(row, 'keywords')

                        # Add bbox if present
                        bbox_cols = ['bbox_minx', 'bbox_miny', 'bbox_maxx', 'bbox_maxy']
                        if all(c in existing_columns for c in bbox_cols):
                            bbox_vals = [safe_get(row, c) for c in bbox_cols]
                            if all(v is not None for v in bbox_vals):
                                item['bbox'] = bbox_vals

                        # Add temporal extent if columns exist
                        if 'temporal_start' in existing_columns or 'temporal_end' in existing_columns:
                            ts = safe_get(row, 'temporal_start')
                            te = safe_get(row, 'temporal_end')
                            if ts or te:
                                item['temporal_extent'] = {
                                    'start': ts.isoformat() if ts else None,
                                    'end': te.isoformat() if te else None,
                                    'property': safe_get(row, 'temporal_property')
                                }

                        catalog_records.append(item)

            logger.info(f"Listed {len(catalog_records)} catalog records (total: {total}, filters: {filters_applied})")

            return func.HttpResponse(
                body=json.dumps({
                    'catalog': catalog_records,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                    'filters_applied': filters_applied
                }, default=str, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"Error listing metadata: {e}")
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

    def check_geo_orphans(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Check for orphaned tables and metadata in geo schema.

        GET /api/dbadmin/geo?type=orphans

        Detects:
        - Orphaned Tables: Tables in geo schema without metadata records
        - Orphaned Metadata: Metadata records for non-existent tables

        Detection only - does NOT delete anything.

        Returns:
            JSON with orphaned tables, orphaned metadata, tracked tables, and summary
        """
        from services.janitor_service import geo_orphan_detector

        logger.info("Running geo orphan detection...")

        result = geo_orphan_detector.run()
        status_code = 200 if result.get("success") else 500

        return func.HttpResponse(
            body=json.dumps(result, default=str, indent=2),
            status_code=status_code,
            mimetype='application/json'
        )
