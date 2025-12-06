"""
STAC Vector Cataloging Handlers

Handlers for extracting STAC metadata from PostGIS vector tables.
Follows the same pattern as raster STAC cataloging.

Updated: 18 OCT 2025 - Added create_vector_stac handler (Priority 0A)
"""

from typing import Any
from datetime import datetime
import logging
from util_logger import LoggerFactory, ComponentType
from config.defaults import STACDefaults

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "stac_vector_catalog"
)


def create_vector_stac(params: dict) -> dict[str, Any]:
    """
    Create System STAC Item for completed PostGIS table.

    This is the Stage 3 handler for process_vector job.
    Creates a STAC Item in the 'system-vectors' collection to track
    the PostGIS table created by ETL.

    Args:
        params: {
            "schema": str,              # PostgreSQL schema (e.g., "geo")
            "table_name": str,          # Table name
            "collection_id": str,       # STAC collection (default: "system-vectors")
            "source_file": str,         # Original blob name (e.g., "kba_shp.zip")
            "source_format": str,       # File extension (e.g., "shp")
            "job_id": str               # Job ID for tracking
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
                "inserted_to_pgstac": bool,
                "stac_item": {...}
            }
        }
    """
    import traceback
    from services.service_stac_vector import StacVectorService
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    logger.info(f"🗺️ STAC Stage 3: Creating STAC Item for {params.get('schema')}.{params.get('table_name')}")

    # Extract parameters
    schema = params.get("schema")
    table_name = params.get("table_name")
    collection_id = params.get("collection_id", STACDefaults.VECTOR_COLLECTION)
    source_file = params.get("source_file")
    source_format = params.get("source_format")
    job_id = params.get("job_id")

    if not schema or not table_name:
        error_msg = "Missing required parameters: schema and table_name"
        logger.error(f"❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "ValidationError"
        }

    start_time = datetime.utcnow()

    try:
        # STEP 1: Extract STAC Item from PostGIS table
        # Use app database geo schema (default behavior)
        logger.info(f"📊 STEP 1: Extracting STAC metadata from {schema}.{table_name}...")
        stac_service = StacVectorService(target_database="app")

        # Build additional properties for ETL tracking
        additional_properties = {
            "etl:job_id": job_id,
            "vector:source_format": source_format,
            "vector:source_file": source_file,
            "system:reserved": collection_id == "system-vectors",  # NEW: Phase 2 (9 NOV 2025) - Mark system datasets
            "created": datetime.utcnow().isoformat() + "Z"
        }

        # NEW: Phase 2 (9 NOV 2025) - Document geometry processing if applied
        # This helps users understand if they're querying full or generalized geometries
        geometry_params = params.get("geometry_params", {})
        if geometry_params:
            additional_properties["processing:geometry"] = geometry_params

        item = stac_service.extract_item_from_table(
            schema=schema,
            table_name=table_name,
            collection_id=collection_id,
            source_file=source_file,
            additional_properties=additional_properties
        )

        logger.info(f"✅ STEP 1: STAC Item extracted - item_id={item.id}")

        # STEP 2: Insert into PgSTAC (with idempotency check)
        logger.info(f"💾 STEP 2: Inserting STAC Item into PgSTAC collection '{collection_id}'...")
        stac_infra = PgStacBootstrap()

        # Check if item already exists (idempotency)
        if stac_infra.item_exists(item.id, collection_id):
            logger.info(f"⏭️ STEP 2: Item {item.id} already exists in PgSTAC - skipping insertion (idempotent)")
            insert_result = {
                'success': True,
                'item_id': item.id,
                'collection': collection_id,
                'skipped': True,
                'reason': 'Item already exists (idempotent operation)'
            }
        else:
            # Item doesn't exist - insert it
            insert_result = stac_infra.insert_item(item, collection_id)
            logger.info(f"✅ STEP 2: PgSTAC insert completed - success={insert_result.get('success')}")

        # Extract metadata for response
        item_dict = item.model_dump(mode='json', by_alias=True)
        bbox = item.bbox
        geometry_types = item_dict.get('properties', {}).get('postgis:geometry_types', [])
        row_count = item_dict.get('properties', {}).get('postgis:row_count', 0)

        duration = (datetime.utcnow() - start_time).total_seconds()

        # SUCCESS
        logger.info(f"🎉 SUCCESS: STAC cataloging completed in {duration:.2f}s for {schema}.{table_name}")
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
                "inserted_to_pgstac": insert_result.get('success', False),
                "item_skipped": insert_result.get('skipped', False),
                "skip_reason": insert_result.get('reason') if insert_result.get('skipped') else None,
                "execution_time_seconds": round(duration, 2),
                "stac_item": item_dict
            }
        }

    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        error_msg = str(e) or type(e).__name__
        logger.error(f"💥 FAILURE after {duration:.2f}s: {error_msg}\n{traceback.format_exc()}")

        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "schema": schema,
            "table_name": table_name,
            "execution_time_seconds": round(duration, 2),
            "traceback": traceback.format_exc()
        }


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
    import traceback
    from services.service_stac_vector import StacVectorService
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    logger.info(f"🚀 HANDLER ENTRY: extract_vector_stac_metadata called with params: {list(params.keys())}")
    logger.info(f"🚀 HANDLER ENTRY: table={params.get('schema')}.{params.get('table_name')}")

    # Extract parameters
    schema = params.get("schema")
    table_name = params.get("table_name")
    collection_id = params.get("collection_id", STACDefaults.VECTORS_COLLECTION)
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
        # Use target_database param if provided, default to app (original behavior)
        target_database = params.get("target_database", "app")
        logger.info(f"📦 STEP 1: Initializing StacVectorService (target_database={target_database})...")
        stac_service = StacVectorService(target_database=target_database)
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
        logger.info(f"🗄️ STEP 3: Initializing PgStacBootstrap...")
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        stac_infra = PgStacBootstrap()
        logger.info(f"✅ STEP 3: PgStacBootstrap initialized")

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
