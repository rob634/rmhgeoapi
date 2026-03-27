# ============================================================================
# CLAUDE CONTEXT - RASTER PROCESS SINGLE TILE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5)
# STATUS: Atomic handler - Fan-out child: extract window → COG → stamp → upload
# PURPOSE: Process one tile of a large raster. Each instance is independently
#          retryable. Source raster stays on mount; this handler reads its
#          window, creates a COG, stamps metadata, and uploads to silver.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_process_single_tile
# DEPENDENCIES: rasterio, services.raster_cog, infrastructure.blob
# ============================================================================
"""
Raster Process Single Tile — fan-out child handler.

Each fan-out instance processes one tile from the source raster:
1. Open source raster on mount (concurrent reads are safe)
2. Extract tile window to a local GeoTIFF on mount
3. COG-translate the tile (reproject if needed)
4. Stamp color interpretation + nodata
5. Upload to silver blob storage
6. Return tile metadata

The source raster path and tile spec (window coordinates) come from
the fan-out template's Jinja2 params.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def raster_process_single_tile(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Process a single tile: extract → COG → stamp → upload.

    Params (from fan-out template):
        source_path (str): Path to source raster on mount
        tile_spec (dict): {tile_index, row, col, window: {col_off, row_off, width, height}, bounds_4326}
        collection_id (str): STAC collection for silver path
        source_crs (str): Source CRS from validation
        target_crs (str): Target CRS (default EPSG:4326)
        needs_reprojection (bool): Whether to reproject
        raster_type (dict): From validation
        nodata (float|None): Nodata value
        job_id (str): For deterministic blob naming
        _run_id (str): System-injected
        _node_name (str): System-injected

    Returns:
        {"success": True, "result": {tile_index, blob_path, container, bounds_4326, ...}}
    """
    source_path = params.get("source_path")
    tile_spec = params.get("tile_spec")
    collection_id = params.get("collection_id")
    source_crs = params.get("source_crs")
    target_crs = params.get("target_crs", "EPSG:4326")
    needs_reprojection = params.get("needs_reprojection", False)
    raster_type = params.get("raster_type", {})
    nodata = params.get("nodata")
    job_id = params.get("job_id", params.get("_run_id", "unknown"))
    run_id = params.get("_run_id", "")
    node_name = params.get("_node_name", "")

    # Parse tile_spec — may be a JSON string from Jinja2 rendering
    if isinstance(tile_spec, str):
        import json
        try:
            tile_spec = json.loads(tile_spec)
        except (json.JSONDecodeError, TypeError):
            return {
                "success": False,
                "error": f"tile_spec is not valid JSON: {tile_spec[:100]}",
                "error_type": "ValidationError",
                "retryable": False,
            }

    # Validate required params
    missing = []
    if not source_path:
        missing.append("source_path")
    if not tile_spec:
        missing.append("tile_spec")
    if not collection_id:
        missing.append("collection_id")
    if not source_crs:
        missing.append("source_crs")
    if not run_id:
        missing.append("_run_id")
    if missing:
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    tile_index = tile_spec.get("tile_index", 0)
    row = tile_spec.get("row", 0)
    col = tile_spec.get("col", 0)
    pixel_window = tile_spec.get("pixel_window", {})
    tile_bounds_4326 = tile_spec.get("bounds_4326")

    log_prefix = f"[{run_id[:8]}][tile_r{row}_c{col}]"

    try:
        import rasterio
        from rasterio.windows import Window
        import numpy as np

        start = time.monotonic()

        if not os.path.exists(source_path):
            return {
                "success": False,
                "error": f"Source raster not found: {source_path}",
                "error_type": "FileNotFoundError",
                "retryable": False,
            }

        # -------------------------------------------------------------------
        # Step 1: Extract tile window from source raster
        # -------------------------------------------------------------------
        from config import get_config
        config = get_config()
        mount_path = config.docker.etl_mount_path or "/mnt/etl"
        tile_dir = os.path.join(mount_path, run_id, "tiles")
        os.makedirs(tile_dir, exist_ok=True)

        tile_filename = f"tile_r{row}_c{col}.tif"
        tile_path = os.path.join(tile_dir, tile_filename)

        if not pixel_window:
            return {
                "success": False,
                "error": f"Tile r{row}_c{col} has no pixel_window — tiling scheme may be malformed",
                "error_type": "ValidationError",
                "retryable": False,
            }

        win = Window(
            col_off=pixel_window.get("col_off", 0),
            row_off=pixel_window.get("row_off", 0),
            width=pixel_window.get("width", 256),
            height=pixel_window.get("height", 256),
        )

        with rasterio.open(source_path) as src:
            tile_data = src.read(window=win)
            tile_profile = src.profile.copy()
            tile_profile.update({
                "width": win.width,
                "height": win.height,
                "transform": rasterio.windows.transform(win, src.transform),
            })

        with rasterio.open(tile_path, "w", **tile_profile) as dst:
            dst.write(tile_data)

        tile_size_bytes = os.path.getsize(tile_path)
        logger.info(
            "%s Extracted tile window (%dx%d) → %s (%.1f MB)",
            log_prefix, win.width, win.height, tile_path,
            tile_size_bytes / 1024 / 1024,
        )

        # -------------------------------------------------------------------
        # Step 2: COG-translate the tile
        # -------------------------------------------------------------------
        from services.raster_cog import create_cog

        cog_blob_name = f"{job_id[:8]}/tile_r{row}_c{col}.tif"

        cog_params = {
            "_local_source_path": tile_path,
            "container_name": None,
            "blob_name": None,
            "source_crs": source_crs,
            "target_crs": target_crs,
            "raster_type": raster_type,
            "output_blob_name": cog_blob_name,
            "output_tier": params.get("output_tier", "analysis"),
            "in_memory": False,
            # Use tile-specific ID so each fan-out child gets a unique temp file
            # (create_cog names output as output_{task_id[:16]}.cog.tif)
            "_task_id": f"{run_id[:8]}_r{row}_c{col}",
            "_skip_cleanup": True,   # We manage cleanup
            "_skip_upload": False,   # Let create_cog upload to silver
        }

        cog_response = create_cog(cog_params)

        if not cog_response.get("success"):
            return {
                "success": False,
                "error": f"COG creation failed for tile r{row}_c{col}: {cog_response.get('error')}",
                "error_type": "COGCreationError",
                "retryable": False,
            }

        cog_result = cog_response.get("result", {})
        cog_blob = cog_result.get("output_blob") or cog_result.get("cog_blob") or cog_blob_name
        cog_container = cog_result.get("cog_container") or config.storage.silver.cogs

        # -------------------------------------------------------------------
        # Step 3: Stamp COG metadata (color interpretation + nodata)
        # -------------------------------------------------------------------
        # Find the local COG file for stamping (tile-specific task ID)
        tile_task_id = f"{run_id[:8]}_r{row}_c{col}"
        local_cog = os.path.join(mount_path, f"output_{tile_task_id[:16]}.cog.tif")

        if os.path.exists(local_cog):
            try:
                from services.raster_cog import stamp_cog_metadata
                stamp_result = stamp_cog_metadata(local_cog)
                if stamp_result.get("stamped"):
                    logger.info("%s COG stamped: %s", log_prefix, stamp_result)
            except Exception as stamp_exc:
                logger.warning("%s COG stamp failed (non-fatal): %s", log_prefix, stamp_exc)

        # -------------------------------------------------------------------
        # Step 4: Cleanup local tile files
        # -------------------------------------------------------------------
        for f in [tile_path, local_cog]:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass  # Non-fatal

        # -------------------------------------------------------------------
        # Step 5: Generate tile identifiers
        # -------------------------------------------------------------------
        from services.raster.identifiers import derive_stac_item_id
        tile_item_id = derive_stac_item_id(collection_id, cog_blob)

        cog_url = f"/vsiaz/{cog_container}/{cog_blob}"

        elapsed = time.monotonic() - start
        logger.info(
            "%s Tile complete: %s (%.1fs)",
            log_prefix, cog_blob, elapsed,
        )

        return {
            "success": True,
            "result": {
                "tile_index": tile_index,
                "row": row,
                "col": col,
                "item_id": tile_item_id,
                "blob_path": cog_blob,
                "container": cog_container,
                "cog_url": cog_url,
                "bounds_4326": tile_bounds_4326,
                "width": win.width,
                "height": win.height,
                "cog_size_bytes": cog_result.get("cog_bytes_on_disk", 0),
                "processing_time_seconds": round(elapsed, 2),
            },
        }

    except Exception as exc:
        import traceback
        logger.error("%s Tile processing failed: %s\n%s", log_prefix, exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"Tile r{row}_c{col} failed: {exc}",
            "error_type": "TileProcessingError",
            "retryable": False,
        }
