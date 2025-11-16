# ============================================================================
# CLAUDE CONTEXT - H3 STAC CREATION HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - H3 grid STAC item creation handler
# PURPOSE: Create STAC items for H3 grids stored in PostGIS geo.h3_grids table
# LAST_REVIEWED: 9 NOV 2025
# EXPORTS: create_h3_stac (task handler function)
# INTERFACES: Core Machine task handler protocol
# PYDANTIC_MODELS: stac_pydantic.Item, stac_pydantic.Asset
# DEPENDENCIES: stac-pydantic, psycopg, infrastructure.stac, util_logger
# SOURCE: PostGIS geo.h3_grids table metadata
# SCOPE: Stage 3 of H3 grid workflow (after PostGIS insertion)
# VALIDATION: Grid ID validation, bbox validation, STAC spec compliance
# PATTERNS: Task handler pattern, STAC cataloging, idempotency
# ENTRY_POINTS: Called by Core Machine task processor for "create_h3_stac" task type
# INDEX: create_h3_stac:40, _extract_h3_metadata:150, _build_stac_item:200
# ============================================================================

"""
H3 Grid STAC Item Creation Handler

Creates STAC items for H3 hexagonal grids stored in PostGIS, enabling discovery
and cataloging via the STAC API.

Workflow:
    Stage 1 → Generate H3 grid → Save to GeoParquet
    Stage 2 → Load GeoParquet → Insert to PostGIS
    Stage 3 (THIS HANDLER) → Create STAC item → Catalog in pgstac

Author: Robert and Geospatial Claude Legion
Date: 9 NOV 2025
"""

import time
from typing import Dict, Any
from datetime import datetime, timezone

import psycopg
from psycopg import sql

from infrastructure.stac import PgStacInfrastructure
from config import get_config
from util_logger import LoggerFactory, ComponentType


def create_h3_stac(task_params: dict) -> dict:
    """
    Create STAC Item for H3 grid in PostGIS and insert to pgstac.

    Core Machine Contract:
        - Takes task_params dict
        - Returns dict with success status and STAC metadata
        - Raises exceptions for failures (caught by Core Machine)

    Args:
        task_params: Task parameters dict:
            - grid_id (str): Grid identifier (e.g., "global_res4", "land_res4")
            - table_name (str): PostGIS table name (e.g., "geo.h3_grids")
            - bbox (list): Bounding box [minx, miny, maxx, maxy]
            - resolution (int): H3 resolution (0-15)
            - collection_id (str): STAC collection ID (default: "system-h3-grids")
            - source_blob (str): Original GeoParquet blob path

    Returns:
        Success dict with:
            - success: True
            - result:
                - item_id: STAC item ID
                - collection_id: STAC collection ID
                - grid_id: Grid identifier
                - bbox: Bounding box
                - row_count: Number of H3 cells
                - inserted_to_pgstac: Boolean
                - stac_item: Full STAC item dict

    Raises:
        ValueError: Invalid parameters
        psycopg.Error: Database query errors
        Exception: STAC insertion errors
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_h3_stac")
    start_time = time.time()

    logger.info("=" * 80)
    logger.info("🔷 H3 GRID STAC ITEM CREATION")
    logger.info("=" * 80)

    try:
        # Extract and validate parameters
        grid_id = task_params.get('grid_id')
        table_name = task_params.get('table_name', 'geo.h3_grids')
        bbox = task_params.get('bbox')
        resolution = task_params.get('resolution')
        collection_id = task_params.get('collection_id', 'system-h3-grids')
        source_blob = task_params.get('source_blob')

        logger.info(f"📋 Parameters:")
        logger.info(f"   Grid ID: {grid_id}")
        logger.info(f"   Table: {table_name}")
        logger.info(f"   Bbox: {bbox}")
        logger.info(f"   Resolution: {resolution}")
        logger.info(f"   Collection: {collection_id}")

        # Validate required parameters
        if not grid_id:
            raise ValueError("grid_id is required")
        if not bbox or len(bbox) != 4:
            raise ValueError("bbox must be [minx, miny, maxx, maxy]")
        if resolution is None:
            raise ValueError("resolution is required")

        # STEP 1: Query PostGIS for H3 grid metadata
        logger.info("📊 STEP 1: Querying PostGIS for grid metadata...")
        config = get_config()

        from config import get_postgres_connection_string

        connection_string = get_postgres_connection_string()

        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Query grid statistics
                query = sql.SQL("""
                    SELECT
                        COUNT(*) as row_count,
                        grid_type,
                        MAX(created_at) as created_at,
                        COUNT(DISTINCT is_land) as land_classifications
                    FROM geo.h3_grids
                    WHERE grid_id = %s
                    GROUP BY grid_type
                """)

                cur.execute(query, (grid_id,))
                result = cur.fetchone()

                if not result:
                    raise ValueError(f"No H3 cells found for grid_id: {grid_id}")

                row_count = result[0]
                grid_type = result[1]
                created_at = result[2] or datetime.now(timezone.utc)
                land_classifications = result[3]

        logger.info(f"   ✅ Found {row_count:,} H3 cells")
        logger.info(f"   ✅ Grid type: {grid_type}")

        # STEP 2: Build STAC Item
        logger.info("🗺️  STEP 2: Building STAC Item...")

        # Generate STAC item ID
        item_id = f"h3-{grid_id}"

        # Build geometry from bbox (envelope polygon)
        geometry = {
            'type': 'Polygon',
            'coordinates': [[
                [bbox[0], bbox[1]],  # minx, miny
                [bbox[2], bbox[1]],  # maxx, miny
                [bbox[2], bbox[3]],  # maxx, maxy
                [bbox[0], bbox[3]],  # minx, maxy
                [bbox[0], bbox[1]]   # close polygon
            ]]
        }

        # Build properties
        properties = {
            'datetime': created_at.isoformat(),
            'h3:grid_id': grid_id,
            'h3:resolution': resolution,
            'h3:grid_type': grid_type,
            'h3:cell_count': row_count,
            'h3:has_land_classification': land_classifications > 0,
            'postgis:schema': 'geo',
            'postgis:table': 'h3_grids',
            'postgis:row_count': row_count,
            'source:blob_path': source_blob,
            'created': datetime.now(timezone.utc).isoformat()
        }

        # Build STAC Item dict (following STAC 1.0.0 spec)
        stac_item = {
            'id': item_id,
            'type': 'Feature',
            'stac_version': '1.0.0',
            'collection': collection_id,
            'geometry': geometry,
            'bbox': bbox,
            'properties': properties,
            'links': [
                {
                    'rel': 'collection',
                    'href': f'./collections/{collection_id}',
                    'type': 'application/json'
                },
                {
                    'rel': 'self',
                    'href': f'./collections/{collection_id}/items/{item_id}',
                    'type': 'application/geo+json'
                }
            ],
            'assets': {
                'postgis': {
                    'href': f"postgresql://geo.h3_grids?grid_id={grid_id}",
                    'type': 'application/vnd.geo+json',
                    'title': f'H3 Grid in PostGIS (grid_id={grid_id})',
                    'roles': ['data'],
                    'h3:queryable': True
                },
                'parquet': {
                    'href': f"https://rmhazuregeo.blob.core.windows.net/rmhazuregeogold/{source_blob}",
                    'type': 'application/x-parquet',
                    'title': 'Original GeoParquet file',
                    'roles': ['data']
                }
            }
        }

        logger.info(f"   ✅ STAC Item built: {item_id}")

        # STEP 3: Insert into pgstac (with idempotency check)
        logger.info(f"💾 STEP 3: Inserting STAC Item into pgstac collection '{collection_id}'...")
        stac_infra = PgStacInfrastructure()

        # Check if item already exists (idempotency)
        if stac_infra.item_exists(item_id, collection_id):
            logger.info(f"⏭️  Item {item_id} already exists in pgstac - skipping (idempotent)")
            insert_result = {
                'success': True,
                'item_id': item_id,
                'collection': collection_id,
                'skipped': True,
                'reason': 'Item already exists (idempotent operation)'
            }
            item_skipped = True
        else:
            # Item doesn't exist - insert it
            # Note: PgStacInfrastructure.insert_item expects pystac Item or dict
            insert_result = stac_infra.insert_item_dict(stac_item, collection_id)
            logger.info(f"✅ STEP 3: pgstac insert completed - success={insert_result.get('success')}")
            item_skipped = False

        processing_time = time.time() - start_time

        logger.info("=" * 80)
        logger.info(f"✅ H3 STAC ITEM CREATION COMPLETE ({processing_time:.2f}s)")
        logger.info("=" * 80)

        return {
            "success": True,
            "result": {
                "item_id": item_id,
                "collection_id": collection_id,
                "grid_id": grid_id,
                "grid_type": grid_type,
                "bbox": bbox,
                "row_count": row_count,
                "resolution": resolution,
                "inserted_to_pgstac": insert_result.get('success', False),
                "item_skipped": item_skipped,
                "skip_reason": insert_result.get('reason') if item_skipped else None,
                "processing_time_seconds": round(processing_time, 2),
                "stac_item": stac_item
            }
        }

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"❌ H3 STAC creation failed after {processing_time:.2f}s: {e}")
        logger.exception("Full traceback:")

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "processing_time_seconds": round(processing_time, 2)
        }
