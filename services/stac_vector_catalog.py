# ============================================================================
# STAC VECTOR CATALOGING HANDLERS
# ============================================================================
# STATUS: Service layer - STAC metadata extraction from PostGIS tables
# PURPOSE: Create and register STAC Items for vector tables in pgSTAC
# LAST_REVIEWED: 22 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: create_vector_stac, extract_vector_stac_metadata
# DEPENDENCIES: psycopg, stac-pydantic, artifact_service
# ============================================================================
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
            "job_id": str,              # Job ID for tracking
            "item_id": str              # Optional: Custom STAC item ID (30 JAN 2026 - DDH format)
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
    # 30 JAN 2026: Custom item_id support for DDH format (Platform jobs)
    item_id = params.get("item_id")

    if not schema or not table_name:
        error_msg = "Missing required parameters: schema and table_name"
        logger.error(f"❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "ValidationError"
        }

    # =========================================================================
    # GRACEFUL DEGRADATION CHECK (6 DEC 2025)
    # =========================================================================
    # If pgSTAC is unavailable, skip STAC cataloging but report success with warning.
    # Vector data is still in PostGIS and queryable via OGC Features API.
    # Note: PgStacBootstrap already imported at function start (line 59)
    if not PgStacBootstrap.is_available():
        logger.warning(f"⚠️ pgSTAC unavailable - skipping STAC cataloging for {schema}.{table_name} (degraded mode)")
        return {
            "success": True,
            "degraded": True,
            "warning": "pgSTAC schema not available - STAC cataloging skipped",
            "result": {
                "stac_item_created": False,
                "ogc_features_available": True,
                "table_name": table_name,
                "schema": schema,
                "collection_id": collection_id,
                "degraded_reason": "pgSTAC schema not installed or unavailable",
                "available_access": f"OGC Features API: /api/features/collections/{table_name}/items"
            }
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
            additional_properties=additional_properties,
            item_id=item_id  # 30 JAN 2026: DDH format support
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

        # STEP 3: Update table_metadata with STAC backlink (06 DEC 2025)
        # This establishes the PostGIS → STAC linkage in the source of truth
        try:
            from services.vector.postgis_handler import VectorToPostGISHandler
            handler = VectorToPostGISHandler()
            handler.update_table_stac_link(
                table_name=table_name,
                stac_item_id=item.id,
                stac_collection_id=collection_id
            )
            logger.info(f"✅ STEP 3: Updated geo.table_metadata with STAC link")
        except Exception as link_error:
            # Non-fatal - STAC item was created, just the backlink failed
            logger.warning(f"⚠️ STEP 3: Failed to update table_metadata STAC link: {link_error}")

        # STEP 4: Upsert DDH refs to app.dataset_refs (09 JAN 2026 - F7.8)
        # This links internal dataset_id to external DDH identifiers
        try:
            from infrastructure.dataset_refs_repository import get_dataset_refs_repository
            refs_repo = get_dataset_refs_repository()
            refs_repo.upsert_ref(
                dataset_id=table_name,
                data_type="vector",
                ddh_dataset_id=params.get("dataset_id"),
                ddh_resource_id=params.get("resource_id"),
                ddh_version_id=params.get("version_id")
            )
            logger.debug(f"✅ STEP 4: Upserted app.dataset_refs for {table_name}")
        except Exception as refs_error:
            # Non-fatal - STAC item and metadata were created
            logger.warning(f"⚠️ STEP 4: Failed to upsert dataset_refs: {refs_error}")

        # =====================================================================
        # STEP 5: ARTIFACT REGISTRY (22 JAN 2026)
        # =====================================================================
        # Create artifact record for lineage/revision tracking
        # Vector artifacts reference PostGIS tables rather than blob paths
        artifact_id = None
        try:
            from services.artifact_service import ArtifactService

            # Build client_refs from platform parameters (DDH identifiers)
            client_refs = {}
            if params.get('dataset_id'):
                client_refs['dataset_id'] = params['dataset_id']
            if params.get('resource_id'):
                client_refs['resource_id'] = params['resource_id']
            if params.get('version_id'):
                client_refs['version_id'] = params['version_id']

            # Only create artifact if we have client refs (platform job)
            if client_refs:
                artifact_service = ArtifactService()
                artifact = artifact_service.create_artifact(
                    storage_account='postgis',  # Indicates PostGIS storage
                    container=schema,  # Schema acts as container
                    blob_path=table_name,  # Table name as path
                    client_type='ddh',  # Platform client type
                    client_refs=client_refs,
                    stac_collection_id=collection_id,
                    stac_item_id=item.id,
                    source_job_id=job_id,
                    source_task_id=params.get('_task_id'),
                    content_hash=None,  # No content hash for tables
                    size_bytes=row_count,  # Use row count as size metric
                    content_type='application/x-postgis-table',
                    metadata={
                        'geometry_types': geometry_types,
                        'bbox': bbox,
                        'source_format': source_format,
                        'source_file': source_file,
                    },
                    overwrite=True  # Platform jobs always overwrite
                )
                artifact_id = str(artifact.artifact_id)
                logger.info(f"📦 STEP 5: Artifact created: {artifact_id} (revision {artifact.revision})")
            else:
                logger.debug("📦 STEP 5: Skipping artifact creation - no client_refs (non-platform job)")
        except Exception as artifact_error:
            # Artifact creation is non-fatal - log warning but continue
            import traceback as tb
            logger.warning(f"⚠️ STEP 5: Artifact creation failed (non-fatal): {artifact_error}")
            logger.debug(f"⚠️ Artifact error traceback: {tb.format_exc()}")

        duration = (datetime.utcnow() - start_time).total_seconds()

        # SUCCESS
        logger.info(f"🎉 SUCCESS: STAC cataloging completed in {duration:.2f}s for {schema}.{table_name}")
        result = {
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
        # Include artifact_id if created (22 JAN 2026)
        if artifact_id:
            result["result"]["artifact_id"] = artifact_id
        return result

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
