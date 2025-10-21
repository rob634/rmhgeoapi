# ============================================================================
# CLAUDE CONTEXT - MOSAICJSON SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - MosaicJSON generation from COG collections
# PURPOSE: Create virtual mosaics from multiple COG tiles for dynamic tiling
# LAST_REVIEWED: 20 OCT 2025
# EXPORTS: create_mosaicjson
# INTERFACES: None (service function)
# PYDANTIC_MODELS: None (returns dict)
# DEPENDENCIES: cogeo-mosaic, azure-storage-blob, tempfile
# SOURCE: COG blob URLs from Stage 2 (create_cog tasks)
# SCOPE: Service-level utility for mosaic creation
# VALIDATION: URL validation, bounds calculation
# PATTERNS: Pure function, tempfile cleanup, blob upload
# ENTRY_POINTS: Called from process_raster_collection Stage 3
# INDEX:
#   - create_mosaicjson: Line 45
# ============================================================================

"""
MosaicJSON Service - Create virtual mosaics from COG collections

Creates MosaicJSON files that enable:
- Client-side tile selection (no server-side processing)
- Dynamic mosaics from multiple COGs
- Integration with Titiler, QGIS, GDAL

MosaicJSON Format:
- Standards-compliant JSON file
- Quadkey-based spatial indexing
- COG URL references for each tile
- Automatic zoom level calculation

Author: Robert and Geospatial Claude Legion
Date: 20 OCT 2025
"""

from typing import List, Dict, Any
import tempfile
import os
import json
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "raster_mosaicjson")


def create_mosaicjson(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create MosaicJSON from COG collection (fan_in task handler).

    This is a fan_in aggregation task that receives all Stage 2 COG creation
    results via params["previous_results"] from CoreMachine.

    Task Handler Contract:
        - Receives: params (dict), context (dict, optional)
        - Returns: {"success": bool, ...}

    Args:
        params: Task parameters containing:
            - previous_results (list, REQUIRED): List of Stage 2 COG creation results
                STRUCTURE: List of result_data dicts from create_cog handler
                Each item: {
                    "success": bool,
                    "result": {
                        "cog_blob": str,  # ← KEY FIELD consumed by this handler
                        "cog_container": str,
                        ...
                    }
                }
                See services/raster_cog.py create_cog() Returns for full structure.
            - collection_name (str, REQUIRED): Collection identifier
            - output_folder (str, optional): Output folder path (default: "mosaics")
            - container (str, optional): Container name (default: "rmhazuregeosilver")
        context: Optional task context (unused)

    Returns:
        Success case:
        {
            "success": bool,
            "mosaicjson_blob": str,  # Path to MosaicJSON in blob storage
            "mosaicjson_url": str,   # Full HTTPS URL
            "tile_count": int,
            "bounds": [minx, miny, maxx, maxy],
            "minzoom": int,
            "maxzoom": int,
            "quadkey_count": int,
            "center": [lon, lat, zoom],
            "cog_blobs": List[str]  # COG blob paths (for Stage 4)
        }

        Error case:
        {
            "success": False,
            "error": str,
            "error_type": str
        }

    NOTE: This handler extracts result["cog_blob"] from each previous_result.
          See raster_cog.py for upstream contract documentation.
    """
    try:
        # Extract parameters from fan_in pattern
        # CoreMachine passes: {"previous_results": [...], "job_parameters": {...}}
        previous_results = params.get("previous_results", [])
        job_parameters = params.get("job_parameters", {})

        # Get collection_name from job_parameters (fan_in pattern)
        collection_name = job_parameters.get("collection_id")
        output_folder = job_parameters.get("output_folder", "mosaics")
        container = "rmhazuregeosilver"  # Always use silver container for MosaicJSON

        logger.info(f"🔄 MosaicJSON task handler invoked (fan_in aggregation)")
        logger.info(f"   Collection: {collection_name}")
        logger.info(f"   Previous results count: {len(previous_results)}")

        # Extract COG blobs from Stage 2 results
        # Note: previous_results is list of result_data dicts from completed tasks
        # Structure: result_data = {"success": True, "result": {"cog_blob": "path/to/file.tif", ...}}
        cog_blobs = []
        for result_data in previous_results:
            if result_data.get("success"):
                # Extract cog_blob from nested result dict
                result = result_data.get("result", {})
                cog_blob = result.get("cog_blob")
                if cog_blob:
                    cog_blobs.append(cog_blob)

        if not cog_blobs:
            return {
                "success": False,
                "error": "No COG blobs found in Stage 2 results",
                "error_type": "ValueError"
            }

        logger.info(f"📊 Extracted {len(cog_blobs)} COG blobs from previous results")

        # Call internal implementation
        result = _create_mosaicjson_impl(
            cog_blobs=cog_blobs,
            collection_name=collection_name,
            container=container,
            output_folder=output_folder
        )

        # Add cog_blobs to result for Stage 4
        result["cog_blobs"] = cog_blobs

        return result

    except Exception as e:
        logger.error(f"❌ MosaicJSON task handler failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def _create_mosaicjson_impl(
    cog_blobs: List[str],
    collection_name: str,
    container: str,
    output_folder: str
) -> dict:
    """
    Internal implementation: Create MosaicJSON from COG list.

    This is separated from the task handler to allow for easier testing
    and reuse.

    Args:
        cog_blobs: List of COG blob paths
        collection_name: Collection name
        container: Azure storage container
        output_folder: Output folder path

    Returns:
        Dict with success=True and MosaicJSON details

    Raises:
        ValueError: If cog_blobs is empty
        ImportError: If cogeo-mosaic not installed
        Exception: If MosaicJSON creation or upload fails
    """
    logger.info(f"🔄 Creating MosaicJSON from {len(cog_blobs)} COG files...")
    logger.info(f"   Collection: {collection_name}")
    logger.info(f"   Output: {output_folder}/{collection_name}.json")

    if not cog_blobs:
        raise ValueError("cog_blobs cannot be empty")

    try:
        # Lazy import to avoid startup cost
        from cogeo_mosaic.mosaic import MosaicJSON
        from infrastructure.blob import BlobRepository
    except ImportError as e:
        logger.error(f"❌ Missing dependency: {e}")
        raise ImportError(
            "cogeo-mosaic library required. "
            "Install with: pip install cogeo-mosaic>=7.0.0"
        )

    # Convert blob paths to authenticated URLs with SAS tokens
    # MosaicJSON.from_urls() needs to read each COG to determine bounds
    blob_repo = BlobRepository.instance()
    cog_urls = []
    logger.info(f"🔐 Generating SAS URLs for {len(cog_blobs)} COG blobs...")
    for blob in cog_blobs:
        url = blob_repo.get_blob_url_with_sas(
            container_name=container,
            blob_name=blob,
            hours=1  # 1 hour validity for mosaic creation
        )
        cog_urls.append(url)

    logger.info(f"📊 COG URLs prepared:")
    for idx, url in enumerate(cog_urls[:5]):  # Show first 5 (truncated SAS for readability)
        url_parts = url.split('?')
        url_display = f"{url_parts[0]}?{url_parts[1][:50]}..." if len(url_parts) > 1 else url
        logger.info(f"   [{idx+1}] {url_display}")
    if len(cog_urls) > 5:
        logger.info(f"   ... and {len(cog_urls) - 5} more")

    try:
        # Create mosaic definition
        # cogeo-mosaic will read each COG to determine tile bounds
        logger.info("🔍 Analyzing COG bounds and creating quadkey index...")

        mosaic = MosaicJSON.from_urls(
            cog_urls,
            minzoom=None,  # Auto-calculate optimal zoom range
            maxzoom=None,
            max_threads=10,  # Parallel COG reads
            quiet=False
        )

        logger.info(f"✅ MosaicJSON created:")
        logger.info(f"   Bounds: {mosaic.bounds}")
        logger.info(f"   Zoom range: {mosaic.minzoom} - {mosaic.maxzoom}")
        logger.info(f"   Quadkeys: {len(mosaic.tiles)}")
        logger.info(f"   Center: {mosaic.center}")

    except Exception as e:
        logger.error(f"❌ MosaicJSON creation failed: {e}")
        raise Exception(f"Failed to create MosaicJSON: {e}")

    # Generate output path
    output_blob_name = f"{output_folder}/{collection_name}.json"

    # Save to temporary file
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as tmp:
            # Convert mosaic to dict and write JSON
            mosaic_dict = mosaic.model_dump(mode='json')
            json.dump(mosaic_dict, tmp, indent=2)
            tmp_path = tmp.name

        logger.info(f"💾 MosaicJSON written to temp file: {tmp_path}")

        # Upload to blob storage using BlobRepository
        logger.info(f"☁️ Uploading to blob storage: {output_blob_name}")

        with open(tmp_path, 'rb') as f:
            upload_result = blob_repo.write_blob(
                container=container,
                blob_path=output_blob_name,
                data=f.read(),
                content_type='application/json',
                overwrite=True
            )

        logger.info(f"✅ MosaicJSON uploaded successfully")

        # Generate public URL for the uploaded MosaicJSON
        mosaicjson_url = f"https://{blob_repo.storage_account}.blob.core.windows.net/{container}/{output_blob_name}"

        return {
            "success": True,
            "mosaicjson_blob": output_blob_name,
            "mosaicjson_url": mosaicjson_url,
            "tile_count": len(cog_blobs),
            "bounds": mosaic.bounds,
            "minzoom": mosaic.minzoom,
            "maxzoom": mosaic.maxzoom,
            "quadkey_count": len(mosaic.tiles),
            "center": mosaic.center
        }

    except Exception as e:
        logger.error(f"❌ Blob upload failed: {e}")
        raise Exception(f"Failed to upload MosaicJSON: {e}")

    finally:
        # Clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.info(f"🗑️ Cleaned up temp file: {tmp_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete temp file {tmp_path}: {e}")
