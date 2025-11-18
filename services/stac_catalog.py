"""
STAC Catalog Services - Two-Stage Pattern for Bulk STAC Extraction

Stage 1: list_raster_files - Returns list of raster file names
Stage 2: extract_stac_metadata - Extracts STAC metadata and inserts into PgSTAC

Author: Robert and Geospatial Claude Legion
Date: 6 OCT 2025
"""

from typing import Any
from datetime import datetime
from infrastructure.blob import BlobRepository
# NOTE: StacMetadataService import moved inside extract_stac_metadata() to avoid
# stac-pydantic import at module load time (allows registry to build without STAC deps)


def list_raster_files(params: dict) -> dict[str, Any]:
    """
    Stage 1: List all raster files in container.

    Returns list of raster file names for Stage 2 fan-out.

    Args:
        params: {
            "container_name": str,
            "extension_filter": str (default: ".tif"),
            "prefix": str (default: ""),
            "file_limit": int | None
        }

    Returns:
        Dict with success status and raster file list:
        {
            "success": True,
            "result": {
                "raster_files": [list of raster file names],
                "total_count": int,
                "extension_filter": str,
                "execution_info": {...}
            }
        }
    """
    try:
        container_name = params["container_name"]
        extension_filter = params.get("extension_filter", ".tif").lower()
        prefix = params.get("prefix", "")
        file_limit = params.get("file_limit")

        blob_repo = BlobRepository.instance()

        start_time = datetime.utcnow()

        # Get all blobs
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=prefix,
            limit=None  # Get all, then filter
        )

        # Filter by extension
        raster_files = []
        for blob in blobs:
            blob_name = blob['name']
            if blob_name.lower().endswith(extension_filter):
                raster_files.append(blob_name)

                # Apply file_limit if specified
                if file_limit and len(raster_files) >= file_limit:
                    break

        duration = (datetime.utcnow() - start_time).total_seconds()

        # SUCCESS - return raster file names for Stage 2
        return {
            "success": True,
            "result": {
                "raster_files": raster_files,
                "total_count": len(raster_files),
                "extension_filter": extension_filter,
                "container_name": container_name,
                "prefix": prefix,
                "execution_info": {
                    "scan_duration_seconds": round(duration, 2),
                    "total_blobs_scanned": len(blobs),
                    "raster_files_found": len(raster_files),
                    "file_limit_applied": file_limit is not None
                }
            }
        }

    except Exception as e:
        # FAILURE - return error
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__,
            "container_name": params.get("container_name")
        }


def extract_stac_metadata(params: dict) -> dict[str, Any]:
    """
    Stage 2: Extract STAC metadata for a single raster file.

    This function is called once per raster file in parallel.
    Extracts STAC Item metadata and inserts into PgSTAC database.

    Args:
        params: {
            "container_name": str,
            "blob_name": str,
            "collection_id": str (default: "dev"),
            "item_id": str (optional: custom STAC item ID, auto-generated if not provided)
        }

    Returns:
        Dict with success status and STAC metadata:
        {
            "success": True,
            "result": {
                "item_id": str,
                "blob_name": str,
                "collection_id": str,
                "bbox": [float, float, float, float],
                "geometry_type": str,
                "bands_count": int,
                "epsg": int,
                "inserted_to_pgstac": bool,
                "stac_item": {...}  # Full STAC Item
            }
        }
    """
    # CRITICAL: Log entry BEFORE any imports to confirm handler is called
    import sys
    print(f"🚀 HANDLER ENTRY: extract_stac_metadata called with params keys: {list(params.keys())}", file=sys.stderr, flush=True)
    print(f"🚀 HANDLER ENTRY: blob_name={params.get('blob_name', 'MISSING')}", file=sys.stderr, flush=True)

    # STEP 0: Import dependencies with explicit error handling
    # These imports are logged separately to catch import failures that prevent handler execution
    logger = None  # Initialize to None for error handling
    try:
        print(f"📦 STEP 0A: Importing LoggerFactory and traceback...", file=sys.stderr, flush=True)
        from util_logger import LoggerFactory, ComponentType
        import traceback
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "extract_stac_metadata")
        logger.info("✅ STEP 0A: Logger initialized successfully")
        print(f"✅ STEP 0A: Logger initialized", file=sys.stderr, flush=True)

        print(f"📦 STEP 0B: Importing StacMetadataService (lazy import - may trigger stac-pydantic)...", file=sys.stderr, flush=True)
        logger.info("📦 STEP 0B: Starting lazy import of StacMetadataService...")
        from .service_stac_metadata import StacMetadataService
        logger.info("✅ STEP 0B: StacMetadataService imported successfully")
        print(f"✅ STEP 0B: StacMetadataService imported", file=sys.stderr, flush=True)

        print(f"📦 STEP 0C: Importing StacInfrastructure...", file=sys.stderr, flush=True)
        logger.info("📦 STEP 0C: Importing StacInfrastructure...")
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        logger.info("✅ STEP 0C: StacInfrastructure imported successfully")
        print(f"✅ STEP 0C: All imports successful!", file=sys.stderr, flush=True)

    except ImportError as e:
        error_msg = f"IMPORT FAILED: {e}"
        print(f"❌ {error_msg}", file=sys.stderr, flush=True)
        if logger:
            logger.error(f"❌ {error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "ImportError",
            "import_failed": True,
            "failed_module": str(e),
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name"),
            "traceback": traceback.format_exc() if 'traceback' in dir() else str(e)
        }
    except Exception as e:
        error_msg = f"UNEXPECTED ERROR DURING IMPORTS: {type(e).__name__}: {e}"
        print(f"❌ {error_msg}", file=sys.stderr, flush=True)
        if logger:
            logger.error(f"❌ {error_msg}\n{traceback.format_exc() if 'traceback' in dir() else ''}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "import_phase_error": True,
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name")
        }

    try:
        # STEP 1: Extract parameters
        try:
            from config import get_config  # Import config for default collection
            config = get_config()

            container_name = params["container_name"]
            blob_name = params["blob_name"]

            # Use config default if collection_id not specified
            collection_id = params.get("collection_id") or config.stac_default_collection
            item_id = params.get("item_id")  # Optional custom item ID

            using_default = params.get("collection_id") is None
            logger.info(
                f"📋 STEP 1: Parameters extracted - container={container_name}, "
                f"blob={blob_name[:50]}..., collection={collection_id}"
                f"{' (default)' if using_default else ''}, custom_item_id={item_id}"
            )
        except Exception as e:
            logger.error(f"❌ STEP 1 FAILED: Parameter extraction error: {e}")
            raise

        start_time = datetime.utcnow()

        # STEP 2: Initialize STAC service
        try:
            logger.debug(f"🔧 STEP 2: Initializing StacMetadataService...")
            stac_service = StacMetadataService()
            logger.info(f"✅ STEP 2: StacMetadataService initialized")
        except Exception as e:
            logger.error(f"❌ STEP 2 FAILED: StacMetadataService initialization error: {e}\n{traceback.format_exc()}")
            raise

        # STEP 3: Extract STAC item from blob (THIS IS THE SLOW PART)
        try:
            logger.info(f"📡 STEP 3: Starting STAC extraction from blob (this may take 30-60s)...")
            extract_start = datetime.utcnow()

            # Pass item_id if provided, otherwise auto-generate
            item = stac_service.extract_item_from_blob(
                container=container_name,
                blob_name=blob_name,
                collection_id=collection_id,
                item_id=item_id  # Will be None if not provided, service will auto-generate
            )

            extract_duration = (datetime.utcnow() - extract_start).total_seconds()
            logger.info(f"✅ STEP 3: STAC extraction completed in {extract_duration:.2f}s - item_id={item.id}")
        except Exception as e:
            extract_duration = (datetime.utcnow() - extract_start).total_seconds() if 'extract_start' in locals() else 0
            logger.error(f"❌ STEP 3 FAILED after {extract_duration:.2f}s: STAC extraction error: {e}\n{traceback.format_exc()}")
            raise

        # STEP 4: Initialize PgSTAC infrastructure
        try:
            logger.debug(f"🗄️ STEP 4: Initializing PgStacBootstrap...")
            stac_infra = PgStacBootstrap()
            logger.info(f"✅ STEP 4: PgStacBootstrap initialized")
        except Exception as e:
            logger.error(f"❌ STEP 4 FAILED: PgStacBootstrap initialization error: {e}\n{traceback.format_exc()}")
            raise

        # STEP 4.5: Check collection exists, auto-create if missing
        try:
            logger.info(f"🔍 STEP 4.5: Checking if collection '{collection_id}' exists...")

            if not stac_infra.collection_exists(collection_id):
                logger.warning(f"⚠️ STEP 4.5: Collection '{collection_id}' does not exist! Auto-creating...")
                logger.warning(f"⚠️ This is expected on first use of '{collection_id}' collection")

                # Create minimal collection for standalone rasters
                # Import at function level to avoid circular dependencies
                from infrastructure.pgstac_repository import PgStacRepository
                import pystac

                pgstac_repo = PgStacRepository()

                # Create pystac.Collection object (not just a dict!)
                # SpatialExtent and TemporalExtent require proper pystac objects
                spatial_extent = pystac.SpatialExtent(bboxes=[[-180, -90, 180, 90]])
                temporal_extent = pystac.TemporalExtent(intervals=[[None, None]])
                extent = pystac.Extent(spatial=spatial_extent, temporal=temporal_extent)

                collection = pystac.Collection(
                    id=collection_id,
                    description=f"Auto-created collection for standalone raster processing (created: {datetime.utcnow().isoformat()}Z)",
                    extent=extent,
                    license="proprietary"
                )

                # Insert collection using PgStacRepository
                collection_id_result = pgstac_repo.insert_collection(collection)

                if not collection_id_result:
                    raise Exception(f"Failed to auto-create collection '{collection_id}'")

                logger.warning(f"✅ STEP 4.5: Collection '{collection_id}' auto-created successfully")
            else:
                logger.info(f"✅ STEP 4.5: Collection '{collection_id}' exists")

        except Exception as e:
            logger.error(f"❌ STEP 4.5 FAILED: Collection check/creation error: {e}\n{traceback.format_exc()}")
            raise

        # STEP 5: Insert into PgSTAC (with idempotency check)
        try:
            insert_start = datetime.utcnow()

            # Check if item already exists (idempotency)
            logger.debug(f"🔍 STEP 5A: Checking if item {item.id} already exists in collection {collection_id}...")
            if stac_infra.item_exists(item.id, collection_id):
                logger.info(f"⏭️ STEP 5: Item {item.id} already exists in PgSTAC - skipping insertion (idempotent)")
                insert_result = {
                    'success': True,
                    'item_id': item.id,
                    'collection': collection_id,
                    'skipped': True,
                    'reason': 'Item already exists (idempotent operation)'
                }
            else:
                # Item doesn't exist - insert it
                logger.info(f"💾 STEP 5B: Inserting new item {item.id} into PgSTAC collection {collection_id}...")
                insert_result = stac_infra.insert_item(item, collection_id)
                logger.info(f"✅ STEP 5B: PgSTAC insert completed - success={insert_result.get('success')}")

            insert_duration = (datetime.utcnow() - insert_start).total_seconds()
            logger.info(f"✅ STEP 5: PgSTAC operation completed in {insert_duration:.2f}s")
        except Exception as e:
            insert_duration = (datetime.utcnow() - insert_start).total_seconds() if 'insert_start' in locals() else 0
            logger.error(f"❌ STEP 5 FAILED after {insert_duration:.2f}s: PgSTAC error: {e}\n{traceback.format_exc()}")
            raise

        duration = (datetime.utcnow() - start_time).total_seconds()

        # STEP 6: Extract metadata for summary
        try:
            logger.debug(f"📊 STEP 6: Extracting metadata summary...")
            item_dict = item.model_dump(mode='json', by_alias=True)
            bbox = item.bbox
            # FIX: item.geometry is Shapely object, not dict - use item_dict instead
            geometry_type = item_dict.get('geometry', {}).get('type', 'Unknown') if item_dict.get('geometry') else 'Unknown'

            # Count raster bands if present
            bands_count = 0
            if 'assets' in item_dict:
                for asset in item_dict['assets'].values():
                    if 'raster:bands' in asset:
                        bands_count = len(asset['raster:bands'])
                        break

            # Get EPSG code
            epsg = item_dict.get('properties', {}).get('proj:epsg')

            logger.info(f"✅ STEP 6: Metadata extracted - bbox={bbox}, epsg={epsg}, bands={bands_count}")
        except Exception as e:
            logger.error(f"❌ STEP 6 FAILED: Metadata extraction error: {e}\n{traceback.format_exc()}")
            raise

        # CRITICAL: Check if pgSTAC insertion succeeded
        # If insert failed, the entire operation is a FAILURE (no silent failures!)
        insert_success = insert_result.get('success', False)
        insert_skipped = insert_result.get('skipped', False)

        if not insert_success and not insert_skipped:
            # Insert failed - this is a FAILURE condition
            error_msg = insert_result.get('error', 'Unknown pgSTAC insertion error')
            logger.error(f"❌ STAC INSERTION FAILED: {error_msg}")
            logger.error(f"💥 Operation cannot complete without successful pgSTAC insertion")

            return {
                "success": False,
                "error": f"Failed to insert STAC item into pgSTAC: {error_msg}",
                "error_type": "STACInsertionError",
                "blob_name": blob_name,
                "container_name": container_name,
                "collection_id": collection_id,
                "item_id": item.id,
                "insert_result": insert_result,
                "execution_time_seconds": round(duration, 2),
                "extract_time_seconds": round(extract_duration, 2),
                "insert_time_seconds": round(insert_duration, 2),
                "stac_item": item_dict  # Include for debugging
            }

        # SUCCESS - STAC metadata extracted AND inserted (or skipped due to existing)
        logger.info(f"🎉 SUCCESS: STAC cataloging completed in {duration:.2f}s for {blob_name}")
        return {
            "success": True,
            "result": {
                "item_id": item.id,
                "blob_name": blob_name,
                "collection_id": collection_id,
                "bbox": bbox,
                "geometry_type": geometry_type,
                "bands_count": bands_count,
                "epsg": epsg,
                "inserted_to_pgstac": insert_success,
                "item_skipped": insert_skipped,
                "skip_reason": insert_result.get('reason') if insert_skipped else None,
                "execution_time_seconds": round(duration, 2),
                "extract_time_seconds": round(extract_duration, 2),
                "insert_time_seconds": round(insert_duration, 2),
                "stac_item": item_dict  # Full STAC Item for reference
            }
        }

    except Exception as e:
        # FAILURE - return error with context
        duration = (datetime.utcnow() - start_time).total_seconds() if 'start_time' in locals() else 0
        error_msg = str(e) or type(e).__name__
        logger.error(f"💥 COMPLETE FAILURE after {duration:.2f}s: {error_msg}\n{traceback.format_exc()}")

        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name"),
            "collection_id": params.get("collection_id"),
            "execution_time_seconds": round(duration, 2),
            "traceback": traceback.format_exc()
        }
