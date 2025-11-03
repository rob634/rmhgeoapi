# ============================================================================
# CLAUDE CONTEXT - STAC COLLECTION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - STAC collection creation and management
# PURPOSE: Create STAC collections for raster tile sets with MosaicJSON assets
# LAST_REVIEWED: 20 OCT 2025
# EXPORTS: create_stac_collection
# INTERFACES: PgSTAC collections table, pystac.Collection
# PYDANTIC_MODELS: None (uses pystac models)
# DEPENDENCIES: pystac, psycopg (pool), azure-storage-blob
# SOURCE: MosaicJSON blobs, collection metadata, spatial extents
# SCOPE: Multi-tile raster collections
# VALIDATION: pystac built-in validation
# PATTERNS: Service layer, PgSTAC integration
# ENTRY_POINTS: create_stac_collection()
# INDEX: create_stac_collection:50, _calculate_collection_extent:150
# ============================================================================

"""
STAC Collection Service

Creates STAC collections for multi-tile raster datasets with MosaicJSON assets.
Similar to raster_stac.py but creates collection-level STAC items instead of
individual raster items.

Key Features:
- Collection-level STAC items with MosaicJSON as primary asset
- Spatial/temporal extent calculation from constituent tiles
- PgSTAC collections table integration
- Azure Blob Storage URL generation for assets

Author: Robert and Geospatial Claude Legion
Date: 20 OCT 2025
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from psycopg_pool import ConnectionPool
from azure.storage.blob import BlobServiceClient

import pystac
from pystac import Collection, Extent, SpatialExtent, TemporalExtent, Asset, Link

from util_logger import LoggerFactory, ComponentType


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
            - container: Container name (default: "rmhazuregeosilver")
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
        previous_results = params.get("previous_results", [])
        job_parameters = params.get("job_parameters", {})

        # Get parameters from job_parameters (passed by CoreMachine for fan_in tasks)
        collection_id = job_parameters.get("collection_id") or params.get("collection_id")
        stac_item_id = job_parameters.get("stac_item_id") or params.get("stac_item_id")
        description = job_parameters.get("collection_description") or params.get("description")
        license = params.get("license", "proprietary")
        container = params.get("container", "rmhazuregeosilver")

        # Use stac_item_id if provided, otherwise use collection_id
        final_collection_id = stac_item_id if stac_item_id else collection_id

        logger.info(f"🔄 STAC collection task handler invoked (fan_in aggregation)")
        logger.info(f"   Collection: {collection_id}")
        logger.info(f"   Custom STAC ID: {stac_item_id}")
        logger.info(f"   Final ID: {final_collection_id}")
        logger.info(f"   Previous results count: {len(previous_results)}")

        # Get MosaicJSON result from Stage 3
        if not previous_results:
            return {
                "success": False,
                "error": "No MosaicJSON result from Stage 3",
                "error_type": "ValueError"
            }

        mosaic_result = previous_results[0].get("result_data", {})
        if not mosaic_result.get("success"):
            return {
                "success": False,
                "error": "Stage 3 MosaicJSON creation failed",
                "error_type": "ValueError"
            }

        mosaicjson_blob = mosaic_result.get("mosaicjson_blob")
        spatial_extent = mosaic_result.get("bounds")
        tile_blobs = mosaic_result.get("cog_blobs", [])

        if not mosaicjson_blob:
            return {
                "success": False,
                "error": "No mosaicjson_blob in Stage 3 result",
                "error_type": "ValueError"
            }

        logger.info(f"📊 Extracted MosaicJSON blob: {mosaicjson_blob}")
        logger.info(f"📊 Tile count: {len(tile_blobs)}")

        # Call internal implementation
        result = _create_stac_collection_impl(
            collection_id=final_collection_id,  # Use final_collection_id (custom or default)
            mosaicjson_blob=mosaicjson_blob,
            description=description,
            tile_blobs=tile_blobs,
            container=container,
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
    license: str,
    spatial_extent: Optional[List[float]],
    temporal_extent: Optional[List[str]]
) -> dict:
    """
    Internal implementation: Create STAC collection.

    Separated from task handler for easier testing and reuse.

    Args:
        collection_id: Collection identifier
        mosaicjson_blob: MosaicJSON blob path
        description: Collection description
        tile_blobs: COG blob paths
        container: Azure container
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
        # Get Azure storage account name
        storage_account = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "rmhazuregeo")

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

        # Add MosaicJSON as primary asset
        mosaicjson_url = f"https://{storage_account}.blob.core.windows.net/{container}/{mosaicjson_blob}"
        collection.add_asset(
            "mosaicjson",
            Asset(
                href=mosaicjson_url,
                media_type="application/json",
                roles=["mosaic", "index"],
                title="MosaicJSON Dynamic Tiling Index",
                description="MosaicJSON file for dynamic tile rendering across collection"
            )
        )

        # Add individual COG tiles as assets (for reference)
        for i, tile_blob in enumerate(tile_blobs):
            tile_url = f"https://{storage_account}.blob.core.windows.net/{container}/{tile_blob}"
            tile_name = tile_blob.split('/')[-1].replace('_cog.tif', '').replace('.tif', '')
            collection.add_asset(
                f"tile_{i}",
                Asset(
                    href=tile_url,
                    media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                    roles=["data", "cog"],
                    title=f"COG Tile: {tile_name}"
                )
            )

        # Validate STAC collection
        collection.validate()
        logger.info(f"STAC collection validated: {collection.id}")

        # Convert to dict for PgSTAC
        collection_dict = collection.to_dict()

        # Insert into PgSTAC collections table
        pgstac_id = _insert_into_pgstac_collections(collection_dict)
        logger.info(f"Inserted into PgSTAC collections: {pgstac_id}")

        return {
            "success": True,
            "collection_id": collection_id,
            "stac_id": collection.id,
            "pgstac_id": pgstac_id,
            "tile_count": len(tile_blobs),
            "spatial_extent": spatial_extent,
            "mosaicjson_url": mosaicjson_url
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

    # Get Azure credentials
    storage_account = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "rmhazuregeo")
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
    Insert STAC collection into PgSTAC collections table.

    Uses the pgstac.create_collection() PostgreSQL function to insert
    the collection with proper indexing and validation.

    Args:
        collection_dict: STAC collection as dictionary

    Returns:
        PgSTAC collection ID

    Raises:
        Exception: PgSTAC insertion failure
    """
    logger.info(f"Inserting collection into PgSTAC: {collection_dict['id']}")

    # Get database connection
    db_host = os.environ.get("PGHOST")
    db_name = os.environ.get("PGDATABASE")
    db_user = os.environ.get("PGUSER")
    db_password = os.environ.get("PGPASSWORD")

    conninfo = f"host={db_host} dbname={db_name} user={db_user} password={db_password} sslmode=require"

    try:
        pool = ConnectionPool(conninfo, min_size=1, max_size=5)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Use PgSTAC's upsert_collection function
                cur.execute(
                    """
                    SELECT pgstac.create_collection(%s::jsonb)
                    """,
                    (json.dumps(collection_dict),)
                )

                result = cur.fetchone()
                conn.commit()

                pgstac_id = result[0] if result else collection_dict['id']
                logger.info(f"PgSTAC collection created: {pgstac_id}")
                return pgstac_id

    except Exception as e:
        logger.error(f"PgSTAC insertion failed: {e}", exc_info=True)
        raise
    finally:
        pool.close()
