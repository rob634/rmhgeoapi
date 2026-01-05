# ============================================================================
# STAC COLLECTION SERVICE
# ============================================================================
# STATUS: Service layer - STAC collection creation for multi-tile rasters
# PURPOSE: Create STAC collections with MosaicJSON assets for tile datasets
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: create_stac_collection
# DEPENDENCIES: pystac, psycopg, azure-storage-blob
# ============================================================================
"""
STAC Collection Service.

Creates STAC collections for multi-tile raster datasets with MosaicJSON assets.

Key Features:
    - Collection-level STAC items with MosaicJSON as primary asset
    - Spatial/temporal extent calculation from constituent tiles
    - PgSTAC collections table integration
    - Azure Blob Storage URL generation for assets

Exports:
    create_stac_collection: Create STAC collection from raster tiles
"""

import os
import json
import traceback  # For fail-fast error reporting (11 NOV 2025)
# asyncio removed (17 NOV 2025) - direct database writes are synchronous
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import psycopg  # Simple connections - NO pooling for Azure Functions (11 NOV 2025)
from azure.storage.blob import BlobServiceClient

import pystac
from pystac import Collection, Extent, SpatialExtent, TemporalExtent, Asset, Link

from util_logger import LoggerFactory, ComponentType
from config import get_config  # For TiTiler base URL and other config (17 NOV 2025)
from infrastructure.pgstac_repository import PgStacRepository  # For collection/item operations (Phase 2B: 17 NOV 2025)
from services.pgstac_search_registration import PgSTACSearchRegistration  # NEW (17 NOV 2025): Direct database registration (Option A)


# Logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "STACCollectionService"
)


def create_stac_collection(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create STAC collection (fan_in task handler).

    This is a fan_in aggregation task that receives Stage 3 MosaicJSON result
    via params["previous_results"] from CoreMachine.

    Task Handler Contract:
        - Receives: params (dict), context (dict, optional)
        - Returns: {"success": bool, ...}

    Args:
        params: Task parameters containing:
            - previous_results: List with single Stage 3 MosaicJSON result
            - collection_id: Collection identifier
            - stac_item_id: Optional custom STAC collection ID (overrides collection_id)
            - description: Collection description
            - license: STAC license (default: "proprietary")
            - container: Container name (default: config.storage.silver.cogs)
        context: Optional task context (unused)

    Returns:
        {
            "success": bool,
            "collection_id": str,
            "stac_id": str,
            "pgstac_id": str,
            "tile_count": int,
            "spatial_extent": [minx, miny, maxx, maxy],
            "mosaicjson_url": str
        }

    Error Return:
        {
            "success": False,
            "error": str,
            "error_type": str
        }
    """
    try:
        # Extract parameters from fan_in pattern
        # DATABASE REFERENCE PATTERN (05 JAN 2026): CoreMachine now passes fan_in_source
        # instead of embedding previous_results. Handler queries DB directly.
        if "fan_in_source" in params:
            from core.fan_in import load_fan_in_results, get_job_parameters
            previous_results = load_fan_in_results(params)
            job_parameters = get_job_parameters(params)
            logger.info(f"📊 Fan-in DB reference: loaded {len(previous_results)} results")
        else:
            # Legacy path: previous_results embedded in params
            previous_results = params.get("previous_results", [])
            job_parameters = params.get("job_parameters", {})

        # Get parameters from job_parameters (passed by CoreMachine for fan_in tasks)
        collection_id = job_parameters.get("collection_id") or params.get("collection_id")
        stac_item_id = job_parameters.get("stac_item_id") or params.get("stac_item_id")
        # FIX (25 NOV 2025): Provide default description to satisfy STAC 1.1.0 validation
        # STAC spec requires description to be a non-empty string, not None
        description = job_parameters.get("collection_description") or params.get("description") or f"Raster collection: {collection_id}"
        license = params.get("license", "proprietary")
        # Use config for default container (silver zone for processed data)
        from config import get_config
        config = get_config()
        container = params.get("container", config.storage.silver.cogs)

        # Use stac_item_id if provided, otherwise use collection_id
        final_collection_id = stac_item_id if stac_item_id else collection_id

        logger.info(f"🔄 STAC collection task handler invoked (fan_in aggregation)")
        logger.info(f"   Collection: {collection_id}")
        logger.info(f"   Custom STAC ID: {stac_item_id}")
        logger.info(f"   Final ID: {final_collection_id}")
        logger.info(f"   Previous results count: {len(previous_results)}")

        # Get MosaicJSON result from Stage 3
        # CRITICAL (11 NOV 2025): previous_results IS the result_data list already.
        # CoreMachine extracts task.result_data, so previous_results[0] is the dict directly.
        # DO NOT access .get("result_data") - that was the bug causing silent failures.
        if not previous_results:
            logger.error("❌ [STAC-ERROR] No previous_results from Stage 3 MosaicJSON")
            return {
                "success": False,
                "error": "No MosaicJSON result from Stage 3",
                "error_type": "ValueError"
            }

        logger.debug(f"🔍 [STAC-DEBUG] previous_results structure check:")
        logger.debug(f"   Type: {type(previous_results)}")
        logger.debug(f"   Length: {len(previous_results)}")
        logger.debug(f"   First item type: {type(previous_results[0]) if previous_results else 'N/A'}")
        logger.debug(f"   First item keys: {list(previous_results[0].keys()) if previous_results and isinstance(previous_results[0], dict) else 'N/A'}")

        # BUG FIX (11 NOV 2025): Access previous_results[0] directly, NOT .get("result_data")
        # previous_results IS already the list of result_data dicts from CoreMachine
        mosaic_result = previous_results[0]

        logger.debug(f"🔍 [STAC-DEBUG] mosaic_result structure:")
        logger.debug(f"   Type: {type(mosaic_result)}")
        logger.debug(f"   Keys: {list(mosaic_result.keys()) if isinstance(mosaic_result, dict) else 'N/A'}")
        logger.debug(f"   success field: {mosaic_result.get('success') if isinstance(mosaic_result, dict) else 'N/A'}")

        if not mosaic_result.get("success"):
            error_detail = mosaic_result.get("error", "Unknown error")
            error_type = mosaic_result.get("error_type", "Unknown")
            logger.error(f"❌ [STAC-ERROR] Stage 3 MosaicJSON creation failed:")
            logger.error(f"   Error: {error_detail}")
            logger.error(f"   Type: {error_type}")
            return {
                "success": False,
                "error": f"Stage 3 MosaicJSON creation failed: {error_detail}",
                "error_type": error_type
            }

        logger.info(f"✅ [STAC-SUCCESS] Stage 3 MosaicJSON result validated")

        mosaicjson_blob = mosaic_result.get("mosaicjson_blob")
        spatial_extent = mosaic_result.get("bounds")
        tile_blobs = mosaic_result.get("cog_blobs", [])
        cog_container = mosaic_result.get("cog_container")  # NEW (11 NOV 2025): COG container for STAC Items

        logger.debug(f"🔍 [STAC-DEBUG] Extracted fields:")
        logger.debug(f"   mosaicjson_blob: {mosaicjson_blob}")
        logger.debug(f"   spatial_extent: {spatial_extent}")
        logger.debug(f"   tile_blobs count: {len(tile_blobs)}")
        logger.debug(f"   cog_container: {cog_container}")  # NEW (11 NOV 2025)

        if not cog_container:
            logger.error(f"❌ [STAC-ERROR] No cog_container in Stage 3 result")
            logger.error(f"   This is required to create STAC Items for COG tiles")
            logger.error(f"   Available keys: {list(mosaic_result.keys())}")
            return {
                "success": False,
                "error": "No cog_container in Stage 3 MosaicJSON result - cannot create STAC Items",
                "error_type": "ValueError"
            }

        if not mosaicjson_blob:
            logger.error(f"❌ [STAC-ERROR] No mosaicjson_blob in Stage 3 result")
            logger.error(f"   Available keys: {list(mosaic_result.keys())}")
            return {
                "success": False,
                "error": "No mosaicjson_blob in Stage 3 result",
                "error_type": "ValueError"
            }

        logger.info(f"📊 Extracted MosaicJSON blob: {mosaicjson_blob}")
        logger.info(f"📊 Tile count: {len(tile_blobs)}")
        logger.info(f"📊 COG container: {cog_container}")

        # Call internal implementation (11 NOV 2025: Added cog_container for orthodox STAC)
        result = _create_stac_collection_impl(
            collection_id=final_collection_id,  # Use final_collection_id (custom or default)
            mosaicjson_blob=mosaicjson_blob,
            description=description,
            tile_blobs=tile_blobs,
            container=container,
            cog_container=cog_container,  # NEW (11 NOV 2025): For creating STAC Items
            license=license,
            spatial_extent=spatial_extent,
            temporal_extent=None
        )

        return result

    except Exception as e:
        logger.error(f"❌ STAC collection task handler failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def _create_stac_collection_impl(
    collection_id: str,
    mosaicjson_blob: str,
    description: str,
    tile_blobs: List[str],
    container: str,
    cog_container: str,
    license: str,
    spatial_extent: Optional[List[float]],
    temporal_extent: Optional[List[str]]
) -> dict:
    """
    Internal implementation: Create STAC collection with orthodox STAC Items.

    Separated from task handler for easier testing and reuse.

    ORTHODOX STAC PATTERN (11 NOV 2025):
    1. Create STAC Items for each COG tile (searchable, with geometry/datetime)
    2. Create STAC Collection with MosaicJSON asset only
    3. Items are linked to Collection via collection_id field

    Args:
        collection_id: Collection identifier
        mosaicjson_blob: MosaicJSON blob path
        description: Collection description
        tile_blobs: COG blob paths
        container: MosaicJSON container (silver-tiles)
        cog_container: COG files container (silver-cogs)
        license: STAC license
        spatial_extent: Spatial bounds or None to calculate
        temporal_extent: Temporal range or None for current time

    Returns:
        Dict with success=True and STAC collection details

    Raises:
        Exception: STAC creation or PgSTAC insertion failures
    """
    logger.info(f"Creating STAC collection: {collection_id}")

    try:
        # Get Azure storage account name from config (08 DEC 2025)
        from config import get_config
        config = get_config()
        storage_account = config.storage.silver.account_name

        # Calculate spatial extent if not provided
        if spatial_extent is None:
            logger.info(f"Calculating spatial extent from {len(tile_blobs)} tiles")
            spatial_extent = _calculate_spatial_extent_from_tiles(tile_blobs, container)

        # Calculate temporal extent if not provided
        if temporal_extent is None:
            # Use current time as single timestamp
            now = datetime.now(timezone.utc).isoformat()
            temporal_extent = [now, now]

        # Create STAC collection
        collection = Collection(
            id=collection_id,
            description=description,
            license=license,
            extent=Extent(
                spatial=SpatialExtent(bboxes=[spatial_extent]),
                temporal=TemporalExtent(intervals=[[
                    datetime.fromisoformat(temporal_extent[0].replace('Z', '+00:00')),
                    datetime.fromisoformat(temporal_extent[1].replace('Z', '+00:00'))
                ]])
            ),
            stac_extensions=[],
            extra_fields={
                "tile_count": len(tile_blobs),
                "created": datetime.now(timezone.utc).isoformat()
            }
        )

        # Add MosaicJSON as primary asset (11 NOV 2025: Use /vsiaz/ path for OAuth compatibility)
        # Pattern matches service_stac_metadata.py lines 270-314 for OAuth-based TiTiler access
        mosaicjson_vsiaz = f"/vsiaz/{container}/{mosaicjson_blob}"
        mosaicjson_url = f"https://{storage_account}.blob.core.windows.net/{container}/{mosaicjson_blob}"  # For reference only
        collection.add_asset(
            "mosaicjson",
            Asset(
                href=mosaicjson_vsiaz,  # OAuth-compatible /vsiaz/ path (not HTTPS)
                media_type="application/json",
                roles=["mosaic", "index"],
                title="MosaicJSON Dynamic Tiling Index",
                description="MosaicJSON file for dynamic tile rendering across collection"
            )
        )

        # Add ISO3 country attribution to collection extra_fields (25 NOV 2025)
        # Uses centralized ISO3AttributionService for geographic metadata
        try:
            from services.iso3_attribution import ISO3AttributionService
            iso3_service = ISO3AttributionService()
            iso3_attribution = iso3_service.get_attribution_for_bbox(spatial_extent)

            if iso3_attribution.available and iso3_attribution.iso3_codes:
                collection.extra_fields['geo:iso3'] = iso3_attribution.iso3_codes
                collection.extra_fields['geo:primary_iso3'] = iso3_attribution.primary_iso3
                if iso3_attribution.countries:
                    collection.extra_fields['geo:countries'] = iso3_attribution.countries
                logger.debug(f"   Added ISO3 attribution to collection: {iso3_attribution.primary_iso3}")
        except Exception as e:
            # Non-fatal: Log warning but continue - collection can exist without country codes
            logger.warning(f"   ISO3 attribution failed for collection (non-fatal): {e}")

        # CRITICAL (12 NOV 2025): CREATE COLLECTION FIRST before Items
        # PgSTAC requires collections to exist before items because collections
        # create table partitions that items use. Without collection, item insertion
        # fails with: "no partition of relation 'items' found for row"

        # Validate STAC collection
        collection.validate()
        logger.info(f"✅ STAC collection validated: {collection.id}")

        # CRITICAL FIX (18 NOV 2025): Use SINGLE repository instance
        # Problem: _insert_into_pgstac_collections() creates PgStacRepository instance A,
        #          StacMetadataService.stac creates PgStacBootstrap instance B
        #          Two instances = two connections = READ AFTER WRITE consistency issue
        # Solution: Create repository once, use for both insert and verification
        from infrastructure.pgstac_repository import PgStacRepository
        pgstac_repo = PgStacRepository()

        # Insert collection into PgSTAC FIRST (creates partition for items)
        pgstac_id = pgstac_repo.insert_collection(collection)
        logger.info(f"✅ Collection inserted into PgSTAC: {pgstac_id}")

        # Validate collection exists before creating Items (18 NOV 2025: Use SAME repository!)
        # This defensive check ensures PgSTAC partition is ready
        if not pgstac_repo.collection_exists(collection_id):
            raise RuntimeError(
                f"Collection '{collection_id}' was not found in PgSTAC after insertion. "
                f"Cannot create STAC Items without a collection partition. "
                f"This indicates a PgSTAC insertion failure."
            )
        logger.info(f"✅ Collection '{collection_id}' verified in PgSTAC - ready for Items")

        # Import STAC metadata service for item creation
        from services.service_stac_metadata import StacMetadataService
        stac_service = StacMetadataService()

        # ORTHODOX STAC (11 NOV 2025): Create STAC Items for each COG tile
        # Items are searchable with geometry, datetime, and properties
        # NOW collection partition exists, so Items can be inserted safely
        logger.info(f"📝 Creating STAC Items for {len(tile_blobs)} COG tiles...")

        created_items = []
        failed_items = []

        for i, tile_blob in enumerate(tile_blobs):
            try:
                logger.info(f"   Creating STAC Item {i+1}/{len(tile_blobs)}: {tile_blob}")

                # Generate semantic item ID from blob name
                tile_name = tile_blob.split('/')[-1].replace('_cog.tif', '').replace('.tif', '')
                item_id = f"{collection_id}_{tile_name}"

                # Create STAC Item using existing service (reuses process_raster logic)
                item = stac_service.extract_item_from_blob(
                    container=cog_container,
                    blob_name=tile_blob,
                    collection_id=collection_id,
                    item_id=item_id
                )

                # Insert Item into PgSTAC
                # CRITICAL (12 NOV 2025): Use Pydantic model_dump() for proper JSON serialization
                # stac-pydantic.Item is a Pydantic model - use model_dump(mode='json') pattern
                # This properly serializes datetime objects to ISO strings
                pgstac_id = stac_service.stac.insert_item(item, collection_id)
                created_items.append(item_id)
                logger.debug(f"   ✅ STAC Item created: {item_id} (pgstac_id: {pgstac_id})")

            except Exception as e:
                logger.error(f"   ❌ Failed to create STAC Item for {tile_blob}: {e}")
                logger.error(f"      Container: {cog_container}")
                logger.error(f"      Item ID: {item_id}")
                logger.error(f"      Progress: {i+1}/{len(tile_blobs)}")
                logger.error(f"      Traceback: {traceback.format_exc()}")
                failed_items.append(tile_blob)
                # CRITICAL (11 NOV 2025): Fail fast if Item creation fails
                # Orthodox STAC requires Items - if they fail, the collection is incomplete
                # Better to fail with clear error than succeed with broken/missing Items
                raise RuntimeError(
                    f"STAC Item creation failed for tile {i+1}/{len(tile_blobs)}: {tile_blob} "
                    f"in container {cog_container}. "
                    f"Created {len(created_items)} items before failure. "
                    f"Error: {e}"
                )

        logger.info(f"✅ Created {len(created_items)} STAC Items successfully")
        if len(created_items) != len(tile_blobs):
            logger.warning(
                f"   ⚠️  Only {len(created_items)} of {len(tile_blobs)} items created - "
                f"this should not happen with fail-fast error handling!"
            )

        # =========================================================================
        # Phase 4: Register pgSTAC Search (Direct Database - 17 NOV 2025)
        # =========================================================================
        # OPTION A ARCHITECTURE (Production Security):
        # - ETL pipeline writes directly to pgstac.searches table
        # - TiTiler has read-only database access (better security)
        # - No APIM needed to protect /searches/register endpoint
        # - Atomic operations (collection + search in same workflow)
        # - search_id computed as SHA256 hash (deterministic, permanent)
        # =========================================================================

        search_id = None
        viewer_url = None
        tilejson_url = None
        tiles_url = None

        try:
            logger.info(f"🔍 Registering pgSTAC search (direct database write) for collection: {collection_id}")

            # Initialize search registration service (17 NOV 2025 - Option A: Direct database writes)
            search_registrar = PgSTACSearchRegistration()

            # Register search directly in database (NO TiTiler API call)
            # Pass collection bbox so TileJSON returns correct bounds for auto-zoom (21 NOV 2025)
            # Extract bbox from collection extent (pystac Collection object)
            collection_bbox = None
            if collection.extent and collection.extent.spatial and collection.extent.spatial.bboxes:
                collection_bbox = collection.extent.spatial.bboxes[0]  # First bbox
                logger.debug(f"   Collection bbox for TileJSON: {collection_bbox}")

            search_id = search_registrar.register_collection_search(
                collection_id=collection_id,
                metadata={"name": f"{collection_id} mosaic"},
                bbox=collection_bbox
            )

            logger.info(f"✅ Search registered: {search_id}")
            logger.info(f"🔍 DEBUG: search_id type={type(search_id)}, value='{search_id}', len={len(search_id) if isinstance(search_id, str) else 'N/A'}")

            # Generate visualization URLs
            config = get_config()
            urls = search_registrar.get_search_urls(
                search_id=search_id,
                titiler_base_url=config.titiler_base_url,
                assets=["data"]
            )
            viewer_url = urls["viewer"]
            tilejson_url = urls["tilejson"]
            tiles_url = urls["tiles"]

            logger.info(f"📊 Generated visualization URLs:")
            logger.info(f"   Viewer: {viewer_url}")
            logger.info(f"   TileJSON: {tilejson_url}")
            logger.info(f"   Tiles: {tiles_url}")

            # Update collection metadata with search info
            logger.info(f"🔄 Updating collection with search metadata...")

            # Serialize existing links to dicts (pystac Link objects need conversion)
            existing_links = []
            for link in collection.links:
                if hasattr(link, 'to_dict'):
                    existing_links.append(link.to_dict())
                elif isinstance(link, dict):
                    existing_links.append(link)
                else:
                    # Fallback: convert to dict manually
                    existing_links.append({
                        "rel": getattr(link, 'rel', 'related'),
                        "href": getattr(link, 'href', str(link))
                    })

            # Add search_id to summaries and links to collection
            metadata_update = {
                "summaries": {
                    "mosaic:search_id": [search_id]  # STAC summaries use arrays
                },
                "links": existing_links + [
                    {
                        "rel": "preview",
                        "href": viewer_url,
                        "type": "text/html",
                        "title": "Interactive map preview (TiTiler-PgSTAC)"
                    },
                    {
                        "rel": "tilejson",
                        "href": tilejson_url,
                        "type": "application/json",
                        "title": "TileJSON specification for web maps"
                    },
                    {
                        "rel": "tiles",
                        "href": tiles_url,
                        "type": "image/png",
                        "title": "XYZ tile endpoint (templated)"
                    }
                ]
            }

            # Update collection in pgSTAC
            pgstac_repo = PgStacRepository()
            pgstac_repo.update_collection_metadata(collection_id, metadata_update)

            logger.info(f"✅ Collection metadata updated with search_id: {search_id}")

        except Exception as e:
            # CRITICAL FIX (18 NOV 2025): Eliminate silent errors - propagate exception to task record
            # Search registration failures should fail the entire collection creation task
            # This ensures we know WHY visualization URLs are missing (not silent nulls)
            logger.error(f"❌ Search registration failed - failing task to expose root cause")
            logger.error(f"   Collection: {collection_id}")
            logger.error(f"   Error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Traceback: {traceback.format_exc()}")

            # Clean up: Remove collection from PgSTAC since we can't provide visualization
            try:
                logger.info(f"🧹 Cleaning up collection '{collection_id}' due to search registration failure...")
                pgstac_repo = PgStacRepository()
                with pgstac_repo._pg_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Delete collection (CASCADE will delete items)
                        cur.execute("DELETE FROM pgstac.collections WHERE id = %s", (collection_id,))
                        conn.commit()
                logger.info(f"✅ Collection cleanup complete")
            except Exception as cleanup_error:
                logger.error(f"⚠️  Failed to cleanup collection: {cleanup_error}")
                # Don't mask original error with cleanup failure

            # Propagate original exception to task record (fail task)
            raise RuntimeError(
                f"Search registration failed for collection '{collection_id}': {e}"
            ) from e

        # Collection already validated and inserted above (12 NOV 2025)
        # search_id, URLs added if search registration succeeded

        return {
            "success": True,
            "collection_id": collection_id,
            "stac_id": collection.id,
            "pgstac_id": pgstac_id,
            "tile_count": len(tile_blobs),
            "items_created": len(created_items),  # NEW (11 NOV 2025): Orthodox STAC Items
            "items_failed": len(failed_items),    # NEW (11 NOV 2025): Failed Item creation
            "spatial_extent": spatial_extent,
            "mosaicjson_url": mosaicjson_url,
            # NEW (12 NOV 2025): pgSTAC search visualization
            "search_id": search_id,
            "viewer_url": viewer_url,
            "tilejson_url": tilejson_url,
            "tiles_url": tiles_url
        }

    except Exception as e:
        logger.error(f"Failed to create STAC collection: {e}", exc_info=True)
        raise


def _calculate_spatial_extent_from_tiles(
    tile_blobs: List[str],
    container: str
) -> List[float]:
    """
    Calculate spatial extent (bbox) from constituent COG tiles.

    Reads the bounding box from each COG's metadata and computes the
    union of all bboxes to determine the collection extent.

    Args:
        tile_blobs: List of COG blob paths
        container: Azure storage container

    Returns:
        [minx, miny, maxx, maxy] in WGS84

    Raises:
        Exception: If unable to read tile metadata
    """
    import rasterio
    from rasterio.warp import transform_bounds

    logger.info(f"Calculating spatial extent from {len(tile_blobs)} tiles")

    # Initialize extent with extreme values
    minx, miny = float('inf'), float('inf')
    maxx, maxy = float('-inf'), float('-inf')

    # Get Azure credentials from config (08 DEC 2025)
    from config import get_config
    config = get_config()
    storage_account = config.storage.silver.account_name
    storage_key = os.environ.get("AZURE_STORAGE_KEY")

    tiles_read = 0
    for tile_blob in tile_blobs:
        try:
            # Construct vsi path for Azure
            vsi_path = f"/vsiaz/{container}/{tile_blob}"

            # Set Azure credentials for GDAL
            with rasterio.Env(
                AZURE_STORAGE_ACCOUNT=storage_account,
                AZURE_STORAGE_ACCESS_KEY=storage_key
            ):
                with rasterio.open(vsi_path) as src:
                    # Get bounds in source CRS
                    bounds = src.bounds
                    src_crs = src.crs

                    # Transform to WGS84 if needed
                    if src_crs and src_crs.to_string() != 'EPSG:4326':
                        tile_bounds = transform_bounds(
                            src_crs,
                            'EPSG:4326',
                            bounds.left, bounds.bottom,
                            bounds.right, bounds.top
                        )
                    else:
                        tile_bounds = (bounds.left, bounds.bottom, bounds.right, bounds.top)

                    # Update extent
                    minx = min(minx, tile_bounds[0])
                    miny = min(miny, tile_bounds[1])
                    maxx = max(maxx, tile_bounds[2])
                    maxy = max(maxy, tile_bounds[3])

                    tiles_read += 1
                    logger.debug(f"Tile {tiles_read}/{len(tile_blobs)}: {tile_blob} → {tile_bounds}")

        except Exception as e:
            logger.warning(f"Could not read extent from {tile_blob}: {e}")
            continue

    if tiles_read == 0:
        raise Exception("Could not read spatial extent from any tiles")

    extent = [minx, miny, maxx, maxy]
    logger.info(f"Calculated extent from {tiles_read} tiles: {extent}")
    return extent


def _insert_into_pgstac_collections(collection_dict: Dict[str, Any]) -> str:
    """
    DEPRECATED (18 NOV 2025): Use PgStacRepository().insert_collection() directly.

    This function creates a new repository instance which causes READ AFTER WRITE
    consistency issues. Use single repository instance pattern instead.

    Insert STAC collection into PgSTAC collections table.

    Uses PgStacRepository which handles managed identity authentication
    and connection management properly.

    Args:
        collection_dict: STAC collection as dictionary

    Returns:
        PgSTAC collection ID

    Raises:
        Exception: PgSTAC insertion failure

    Migration History:
        - Phase 2B (17 NOV 2025): Refactored to use PgStacRepository
        - Phase 2B Fix (18 NOV 2025): DEPRECATED - causes connection consistency issues
    """
    logger.info(f"Inserting collection into PgSTAC: {collection_dict['id']}")

    try:
        # Convert dict to pystac.Collection object
        # PgStacRepository.insert_collection() requires pystac.Collection
        collection = Collection.from_dict(collection_dict)

        # Use repository pattern for managed identity authentication (17 NOV 2025)
        repo = PgStacRepository()
        pgstac_id = repo.insert_collection(collection)

        logger.info(f"✅ [STAC-SUCCESS] PgSTAC collection created via repository: {pgstac_id}")
        return pgstac_id

    except Exception as e:
        logger.error(f"❌ [STAC-ERROR] Failed to insert collection via repository: {e}", exc_info=True)
        logger.error(f"   Exception type: {type(e).__name__}")
        logger.error(f"   Collection ID: {collection_dict.get('id', 'UNKNOWN')}")
        raise Exception(f"PgSTAC insertion failed: {str(e)}") from e
