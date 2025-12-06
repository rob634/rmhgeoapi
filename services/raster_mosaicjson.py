"""
MosaicJSON Service - Virtual Mosaics from COG Collections.

Creates MosaicJSON files that enable:
    - Client-side tile selection (no server-side processing)
    - Dynamic mosaics from multiple COGs
    - Integration with TiTiler, QGIS, GDAL

MosaicJSON Format:
    - Standards-compliant JSON file
    - Quadkey-based spatial indexing
    - COG URL references for each tile
    - Automatic zoom level calculation

Exports:
    create_mosaicjson: Generate MosaicJSON from COG collection
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
            - maxzoom (int, optional): Maximum zoom level for tile serving.
                If not specified, uses config.raster_mosaicjson_maxzoom (default: 19).
                Zoom 18 = 0.60m/pixel, 19 = 0.30m/pixel, 20 = 0.15m/pixel, 21 = 0.07m/pixel.
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

        # Get collection_id from job_parameters (passed by controller)
        collection_id = job_parameters.get("collection_id")
        if not collection_id:
            raise ValueError("collection_id is required parameter")

        # Get mosaicjson_container from job_parameters (12 NOV 2025)
        # This is WHERE the MosaicJSON file will be WRITTEN
        # Falls back to config default if not provided
        mosaicjson_container = job_parameters.get("mosaicjson_container")
        if not mosaicjson_container:
            # Use config default for MosaicJSON storage
            from config import get_config
            config = get_config()
            mosaicjson_container = config.resolved_intermediate_tiles_container
            logger.info(f"   Using default mosaicjson_container from config: {mosaicjson_container}")

        # Get cog_container from job_parameters (12 NOV 2025)
        # This is WHERE the COG files are located (for SAS URL generation)
        # MosaicJSON will REFERENCE these COGs in its tile URLs
        # NOTE (25 NOV 2025): For fan_in stages, cog_container is usually extracted from
        # previous_results (Stage 3 COG tasks). Only check job_parameters as fallback.
        cog_container_from_params = job_parameters.get("cog_container") or job_parameters.get("output_container")
        if cog_container_from_params:
            logger.info(f"   cog_container from job_parameters: {cog_container_from_params}")

        # Optional output_folder (None = flat namespace, write to container root)
        output_folder = job_parameters.get("output_folder")

        logger.info(f"🔄 MosaicJSON task handler invoked (fan_in aggregation)")
        logger.info(f"   Collection: {collection_id}")
        logger.info(f"   MosaicJSON Container (where JSON file is written): {mosaicjson_container}")
        logger.info(f"   Output Folder: {output_folder or '(root - flat namespace)'}")
        logger.info(f"   Previous results count: {len(previous_results)}")

        # DIAGNOSTIC LOGGING (11 NOV 2025): Log structure of previous_results
        logger.debug(f"🔍 [MOSAIC-DEBUG] previous_results structure check:")
        logger.debug(f"   Type: {type(previous_results)}")
        logger.debug(f"   Length: {len(previous_results)}")
        if previous_results:
            logger.debug(f"   First item type: {type(previous_results[0])}")
            if isinstance(previous_results[0], dict):
                logger.debug(f"   First item keys: {list(previous_results[0].keys())}")
                logger.debug(f"   First item['success']: {previous_results[0].get('success')}")
                if 'result' in previous_results[0]:
                    logger.debug(f"   First item['result'] keys: {list(previous_results[0]['result'].keys()) if isinstance(previous_results[0]['result'], dict) else 'NOT A DICT'}")

        # Extract COG blobs from Stage 2 results
        # Note: previous_results is list of result_data dicts from completed tasks
        # Structure: result_data = {"success": True, "result": {"cog_blob": "path/to/file.tif", "cog_container": "silver-cogs", ...}}
        cog_blobs = []
        cog_container = None  # Extract from first successful result (11 NOV 2025)
        failed_results = []
        for idx, result_data in enumerate(previous_results):
            logger.debug(f"🔍 [MOSAIC-DEBUG] Processing result {idx+1}/{len(previous_results)}")
            logger.debug(f"   Type: {type(result_data)}")
            logger.debug(f"   Keys: {list(result_data.keys()) if isinstance(result_data, dict) else 'NOT A DICT'}")

            if result_data.get("success"):
                # Extract cog_blob from nested result dict
                result = result_data.get("result", {})
                cog_blob = result.get("cog_blob")
                logger.debug(f"   success=True, cog_blob={cog_blob}")
                if cog_blob:
                    cog_blobs.append(cog_blob)
                    # Extract cog_container from first successful result (11 NOV 2025)
                    if cog_container is None:
                        cog_container = result.get("cog_container")
                        logger.debug(f"   cog_container extracted: {cog_container}")
                else:
                    logger.warning(f"⚠️ [MOSAIC-WARNING] Result {idx+1} has success=True but no cog_blob!")
                    logger.warning(f"   result dict: {result}")
            else:
                failed_results.append(idx + 1)
                error_msg = result_data.get("error", "Unknown error")
                logger.warning(f"⚠️ [MOSAIC-WARNING] Result {idx+1} has success=False: {error_msg}")

        if failed_results:
            logger.warning(f"⚠️ [MOSAIC-WARNING] {len(failed_results)} of {len(previous_results)} COG tasks failed: {failed_results}")

        if not cog_blobs:
            logger.error(f"❌ [MOSAIC-ERROR] No COG blobs found in Stage 2 results")
            logger.error(f"   Total results: {len(previous_results)}")
            logger.error(f"   Failed results: {len(failed_results)}")
            logger.error(f"   First result sample: {previous_results[0] if previous_results else 'EMPTY'}")
            return {
                "success": False,
                "error": f"No COG blobs found in Stage 2 results ({len(failed_results)} tasks failed)",
                "error_type": "ValueError"
            }

        logger.info(f"📊 Extracted {len(cog_blobs)} COG blobs from previous results")
        logger.debug(f"🔍 [MOSAIC-DEBUG] COG blobs: {cog_blobs}")

        # FIX (25 NOV 2025): Fall back to job_parameters if cog_container not in previous_results
        if not cog_container:
            cog_container = cog_container_from_params
            if cog_container:
                logger.info(f"   Using cog_container from job_parameters: {cog_container}")
            else:
                raise ValueError("cog_container not found in previous_results or job_parameters")

        logger.info(f"   COG Container (where COG files are located): {cog_container}")

        # Call internal implementation
        result = _create_mosaicjson_impl(
            cog_blobs=cog_blobs,
            collection_name=collection_id,
            mosaicjson_container=mosaicjson_container,
            cog_container=cog_container,
            output_folder=output_folder,
            job_parameters=job_parameters
        )

        # Add cog_blobs and cog_container to result for Stage 4 (11 NOV 2025)
        # Stage 4 needs these to create STAC Items for each COG
        result["cog_blobs"] = cog_blobs
        result["cog_container"] = cog_container

        return result

    except Exception as e:
        logger.error(f"❌ MosaicJSON task handler failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def _convert_urls_to_vsiaz(mosaic_dict: dict, container: str) -> dict:
    """
    Convert HTTPS SAS URLs in MosaicJSON to /vsiaz/ paths for OAuth-based TiTiler access.

    CRITICAL (12 NOV 2025): MosaicJSON creation uses SAS URLs temporarily so cogeo-mosaic
    can READ the COGs to extract bounds. But the STORED MosaicJSON must use /vsiaz/ paths
    for OAuth-based TiTiler access (not expiring SAS tokens).

    Args:
        mosaic_dict: MosaicJSON dict with HTTPS SAS URLs in tiles
        container: Azure storage container name

    Returns:
        Modified mosaic_dict with /vsiaz/ paths

    Example transformation:
        Before: "https://account.blob.core.windows.net/container/path/file.tif?st=..."
        After:  "/vsiaz/container/path/file.tif"
    """
    logger.debug(f"🔄 Converting MosaicJSON URLs to /vsiaz/ paths...")

    tiles = mosaic_dict.get('tiles', {})
    converted_count = 0

    for quadkey, urls in tiles.items():
        new_urls = []
        for url in urls:
            if url.startswith('https://') or url.startswith('http://'):
                # Parse URL: https://account.blob.core.windows.net/container/blob/path.tif?sas...
                # Extract: container/blob/path.tif
                # Result: /vsiaz/container/blob/path.tif

                # Remove SAS token (everything after ?)
                url_without_sas = url.split('?')[0]

                # Extract path after .blob.core.windows.net/
                # Example: https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif
                #          → silver-cogs/file.tif
                parts = url_without_sas.split('.blob.core.windows.net/')
                if len(parts) == 2:
                    blob_path = parts[1]  # e.g., "silver-cogs/file.tif"
                    vsiaz_path = f"/vsiaz/{blob_path}"
                    new_urls.append(vsiaz_path)
                    converted_count += 1
                else:
                    # Fallback: couldn't parse, keep original
                    logger.warning(f"   ⚠️  Could not parse URL for /vsiaz/ conversion: {url_without_sas}")
                    new_urls.append(url)
            else:
                # Already /vsiaz/ or other format, keep as-is
                new_urls.append(url)

        tiles[quadkey] = new_urls

    logger.info(f"✅ Converted {converted_count} URLs to /vsiaz/ paths")
    return mosaic_dict


def _create_mosaicjson_impl(
    cog_blobs: List[str],
    collection_name: str,
    mosaicjson_container: str,
    cog_container: str,
    output_folder: str,
    job_parameters: Dict[str, Any] = None
) -> dict:
    """
    Internal implementation: Create MosaicJSON from COG list.

    This is separated from the task handler to allow for easier testing
    and reuse.

    Args:
        cog_blobs: List of COG blob paths
        collection_name: Collection name
        mosaicjson_container: Container where MosaicJSON file will be written (12 NOV 2025)
        cog_container: Container where COG files are located (for SAS URL generation) (12 NOV 2025)
        output_folder: Output folder path
        job_parameters: Optional job parameters (for maxzoom override)

    Returns:
        Dict with success=True and MosaicJSON details

    Raises:
        ValueError: If cog_blobs is empty
        ImportError: If cogeo-mosaic not installed
        Exception: If MosaicJSON creation or upload fails
    """
    if job_parameters is None:
        job_parameters = {}
    logger.info(f"🔄 Creating MosaicJSON from {len(cog_blobs)} COG files...")
    logger.info(f"   Collection: {collection_name}")
    logger.info(f"   MosaicJSON Container: {mosaicjson_container}")
    logger.info(f"   COG Container: {cog_container}")
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
    # CRITICAL (12 NOV 2025): Use cog_container (where COGs are stored), not mosaicjson_container
    blob_repo = BlobRepository.instance()
    cog_urls = []
    logger.info(f"🔐 Generating SAS URLs for {len(cog_blobs)} COG blobs from container '{cog_container}'...")
    for blob in cog_blobs:
        url = blob_repo.get_blob_url_with_sas(
            container_name=cog_container,
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

    # Memory checkpoint 1 (DEBUG_MODE only)
    from util_logger import log_memory_checkpoint
    log_memory_checkpoint(logger, "Before processing COG list", cog_count=len(cog_urls))

    # Get maxzoom setting (parameter overrides config default)
    from config import get_config
    config_obj = get_config()

    maxzoom_param = job_parameters.get('maxzoom')
    if maxzoom_param is not None:
        maxzoom = maxzoom_param
        logger.info(f"   Using user-specified maxzoom={maxzoom}")
    else:
        maxzoom = config_obj.raster_mosaicjson_maxzoom
        logger.info(f"   Using config default maxzoom={maxzoom}")

    # Calculate resolution at equator for this zoom level
    resolution_meters = round(156543.03392 / (2 ** maxzoom), 2)
    logger.info(f"   Max zoom level: {maxzoom} (~{resolution_meters}m/pixel at equator)")

    try:
        # Create mosaic definition
        # cogeo-mosaic will read each COG to determine tile bounds
        logger.info("🔍 Analyzing COG bounds and creating quadkey index...")
        logger.debug(f"🔍 [MOSAIC-DEBUG] Calling MosaicJSON.from_urls with:")
        logger.debug(f"   URL count: {len(cog_urls)}")
        logger.debug(f"   maxzoom: {maxzoom}")
        logger.debug(f"   max_threads: 10")

        mosaic = MosaicJSON.from_urls(
            cog_urls,
            minzoom=None,  # Auto-calculate optimal zoom range
            maxzoom=maxzoom,  # Use parameter or config default
            max_threads=10,  # Parallel COG reads
            quiet=False
        )

        logger.info(f"✅ MosaicJSON created:")
        logger.info(f"   Bounds: {mosaic.bounds}")
        logger.info(f"   Zoom range: {mosaic.minzoom} - {mosaic.maxzoom}")
        logger.info(f"   Quadkeys: {len(mosaic.tiles)}")
        logger.info(f"   Center: {mosaic.center}")
        logger.debug(f"🔍 [MOSAIC-DEBUG] Mosaic object type: {type(mosaic)}")
        logger.debug(f"🔍 [MOSAIC-DEBUG] Mosaic tiles sample: {list(mosaic.tiles.keys())[:5] if mosaic.tiles else 'EMPTY'}")

        # Memory checkpoint 2 (DEBUG_MODE only)
        from util_logger import log_memory_checkpoint
        log_memory_checkpoint(logger, "After mosaic creation",
                              quadkey_count=len(mosaic.tiles),
                              tile_count=len(cog_urls))

    except Exception as e:
        logger.error(f"❌ [MOSAIC-ERROR] MosaicJSON.from_urls failed: {e}")
        logger.error(f"   Exception type: {type(e).__name__}")
        logger.error(f"   COG URLs attempted: {len(cog_urls)}")
        logger.error(f"   First URL: {cog_urls[0] if cog_urls else 'NONE'}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        raise Exception(f"Failed to create MosaicJSON: {e}")

    # Generate output path (flat namespace if no output_folder)
    if output_folder:
        output_blob_name = f"{output_folder}/{collection_name}.json"
    else:
        output_blob_name = f"{collection_name}.json"  # Flat namespace - root of container

    # Save to temporary file
    tmp_path = None
    try:
        logger.debug(f"🔍 [MOSAIC-DEBUG] Creating temporary file for MosaicJSON...")

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as tmp:
            # Convert mosaic to dict
            logger.debug(f"🔍 [MOSAIC-DEBUG] Converting mosaic to dict...")
            mosaic_dict = mosaic.model_dump(mode='json')
            logger.debug(f"🔍 [MOSAIC-DEBUG] Dict keys: {list(mosaic_dict.keys())}")

            # CRITICAL (12 NOV 2025): Convert HTTPS SAS URLs to /vsiaz/ paths
            # SAS URLs were used temporarily so cogeo-mosaic could READ the COGs
            # Now replace with /vsiaz/ paths for OAuth-based TiTiler access
            # Use cog_container (where COGs are stored) for path construction
            mosaic_dict = _convert_urls_to_vsiaz(mosaic_dict, cog_container)

            logger.debug(f"🔍 [MOSAIC-DEBUG] Writing JSON to temp file...")
            json.dump(mosaic_dict, tmp, indent=2)
            tmp_path = tmp.name

        logger.info(f"💾 MosaicJSON written to temp file: {tmp_path}")
        logger.debug(f"🔍 [MOSAIC-DEBUG] Temp file size: {os.path.getsize(tmp_path)} bytes")

        # Upload to blob storage using BlobRepository
        # CRITICAL (12 NOV 2025): Use mosaicjson_container (where JSON file is written)
        logger.info(f"☁️ Uploading MosaicJSON to blob storage: {output_blob_name}")
        logger.debug(f"🔍 [MOSAIC-DEBUG] Upload details:")
        logger.debug(f"   Container: {mosaicjson_container}")
        logger.debug(f"   Blob path: {output_blob_name}")
        logger.debug(f"   Content type: application/json")

        with open(tmp_path, 'rb') as f:
            file_data = f.read()
            logger.debug(f"🔍 [MOSAIC-DEBUG] Read {len(file_data)} bytes from temp file")

            upload_result = blob_repo.write_blob(
                container=mosaicjson_container,
                blob_path=output_blob_name,
                data=file_data,
                content_type='application/json',
                overwrite=True
            )
            logger.debug(f"🔍 [MOSAIC-DEBUG] Upload result: {upload_result}")

        logger.info(f"✅ MosaicJSON uploaded successfully to {mosaicjson_container}/{output_blob_name}")

        # Memory checkpoint 3 (DEBUG_MODE only)
        from util_logger import log_memory_checkpoint
        log_memory_checkpoint(logger, "After mosaic upload",
                              blob_path=output_blob_name)

        # Generate public URL for the uploaded MosaicJSON (repository layer responsibility)
        mosaicjson_url = blob_repo.get_blob_url(mosaicjson_container, output_blob_name)

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
