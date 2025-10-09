"""
STAC Vector Cataloging Handlers

Handlers for extracting STAC metadata from PostGIS vector tables.
Follows the same pattern as raster STAC cataloging.

Author: Robert and Geospatial Claude Legion
Date: 8 OCT 2025
"""

from typing import Any
from datetime import datetime


def extract_vector_stac_metadata(params: dict) -> dict[str, Any]:
    """
    Extract STAC metadata for a PostGIS vector table.

    This handler follows the same pattern as extract_stac_metadata for rasters:
    - Idempotency check before insertion
    - Comprehensive logging
    - Error handling with explicit returns

    Args:
        params: {
            "schema": str,           # PostgreSQL schema (e.g., "geo")
            "table_name": str,       # Table name
            "collection_id": str,    # STAC collection (default: "vectors")
            "source_file": str       # Optional: Original file path
        }

    Returns:
        Dict with success status and STAC metadata:
        {
            "success": True,
            "result": {
                "item_id": str,
                "table_name": str,
                "collection_id": str,
                "bbox": [float, float, float, float],
                "geometry_types": [str],
                "row_count": int,
                "srid": int,
                "inserted_to_pgstac": bool,
                "item_skipped": bool,
                "skip_reason": str,
                "stac_item": {...}  # Full STAC Item
            }
        }
    """
    import sys
    print(f"🚀 HANDLER ENTRY: extract_vector_stac_metadata called with params: {list(params.keys())}", file=sys.stderr, flush=True)
    print(f"🚀 HANDLER ENTRY: table={params.get('schema')}.{params.get('table_name')}", file=sys.stderr, flush=True)

    # STEP 0: Import dependencies
    logger = None
    try:
        print(f"📦 STEP 0A: Importing logger...", file=sys.stderr, flush=True)
        from util_logger import LoggerFactory, ComponentType
        import traceback
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "extract_vector_stac_metadata")
        logger.info("✅ STEP 0A: Logger initialized")
        print(f"✅ STEP 0A: Logger initialized", file=sys.stderr, flush=True)

        print(f"📦 STEP 0B: Importing StacVectorService...", file=sys.stderr, flush=True)
        from services.service_stac_vector import StacVectorService
        logger.info("✅ STEP 0B: StacVectorService imported")
        print(f"✅ STEP 0B: Imports complete", file=sys.stderr, flush=True)

    except ImportError as e:
        error_msg = f"IMPORT FAILED: {e}"
        print(f"❌ {error_msg}", file=sys.stderr, flush=True)
        if logger:
            logger.error(f"❌ {error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "ImportError",
            "import_failed": True
        }

    # Extract parameters
    schema = params.get("schema")
    table_name = params.get("table_name")
    collection_id = params.get("collection_id", "vectors")
    source_file = params.get("source_file")

    if not schema or not table_name:
        error_msg = "Missing required parameters: schema and table_name"
        logger.error(f"❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "ValidationError"
        }

    start_time = datetime.utcnow()
    logger.info(f"🗺️ Starting STAC cataloging for {schema}.{table_name}")

    try:
        # STEP 1: Initialize STAC service
        logger.info(f"📦 STEP 1: Initializing StacVectorService...")
        stac_service = StacVectorService()
        logger.info(f"✅ STEP 1: StacVectorService initialized")

        # STEP 2: Extract STAC Item from PostGIS table
        logger.info(f"🔍 STEP 2: Extracting STAC metadata from {schema}.{table_name}...")
        extract_start = datetime.utcnow()

        item = stac_service.extract_item_from_table(
            schema=schema,
            table_name=table_name,
            collection_id=collection_id,
            source_file=source_file
        )

        extract_duration = (datetime.utcnow() - extract_start).total_seconds()
        logger.info(f"✅ STEP 2: STAC extraction completed in {extract_duration:.2f}s - item_id={item.id}")

        # STEP 3: Initialize PgSTAC infrastructure
        logger.info(f"🗄️ STEP 3: Initializing StacInfrastructure...")
        from infrastructure.stac import StacInfrastructure
        stac_infra = StacInfrastructure()
        logger.info(f"✅ STEP 3: StacInfrastructure initialized")

        # STEP 4: Insert into PgSTAC (with idempotency check)
        insert_start = datetime.utcnow()

        # Check if item already exists (idempotency)
        logger.debug(f"🔍 STEP 4A: Checking if item {item.id} already exists in collection {collection_id}...")
        if stac_infra.item_exists(item.id, collection_id):
            logger.info(f"⏭️ STEP 4: Item {item.id} already exists in PgSTAC - skipping insertion (idempotent)")
            insert_result = {
                'success': True,
                'item_id': item.id,
                'collection': collection_id,
                'skipped': True,
                'reason': 'Item already exists (idempotent operation)'
            }
        else:
            # Item doesn't exist - insert it
            logger.info(f"💾 STEP 4B: Inserting new item {item.id} into PgSTAC collection {collection_id}...")
            insert_result = stac_infra.insert_item(item, collection_id)
            logger.info(f"✅ STEP 4B: PgSTAC insert completed - success={insert_result.get('success')}")

        insert_duration = (datetime.utcnow() - insert_start).total_seconds()
        logger.info(f"✅ STEP 4: PgSTAC operation completed in {insert_duration:.2f}s")

        # STEP 5: Extract metadata for summary
        logger.debug(f"📊 STEP 5: Extracting metadata summary...")
        item_dict = item.model_dump(mode='json', by_alias=True)
        bbox = item.bbox
        geometry_types = item_dict.get('properties', {}).get('postgis:geometry_types', [])
        row_count = item_dict.get('properties', {}).get('postgis:row_count', 0)
        srid = item_dict.get('properties', {}).get('postgis:srid', 0)

        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"✅ STEP 5: Metadata extracted - rows={row_count}, srid={srid}, types={geometry_types}")

        # SUCCESS
        logger.info(f"🎉 SUCCESS: Vector STAC cataloging completed in {duration:.2f}s for {schema}.{table_name}")
        return {
            "success": True,
            "result": {
                "item_id": item.id,
                "schema": schema,
                "table_name": table_name,
                "collection_id": collection_id,
                "bbox": bbox,
                "geometry_types": geometry_types,
                "row_count": row_count,
                "srid": srid,
                "inserted_to_pgstac": insert_result.get('success', False),
                "item_skipped": insert_result.get('skipped', False),
                "skip_reason": insert_result.get('reason') if insert_result.get('skipped') else None,
                "insert_error": insert_result.get('error') if not insert_result.get('success') else None,
                "execution_time_seconds": round(duration, 2),
                "extract_time_seconds": round(extract_duration, 2),
                "insert_time_seconds": round(insert_duration, 2),
                "stac_item": item_dict  # Full STAC Item for reference
            }
        }

    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds() if 'start_time' in locals() else 0
        error_msg = str(e) or type(e).__name__
        logger.error(f"💥 FAILURE after {duration:.2f}s: {error_msg}\n{traceback.format_exc()}")

        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "schema": schema,
            "table_name": table_name,
            "execution_time_seconds": round(duration, 2)
        }
