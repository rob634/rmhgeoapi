# ============================================================================
# CLAUDE CONTEXT - RASTER GENERATE TILING SCHEME ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5)
# STATUS: Atomic handler - Compute tile grid from source raster on mount
# PURPOSE: Read source raster dimensions/CRS, compute optimal tile grid,
#          return tile_specs list for fan-out processing
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_generate_tiling_scheme_atomic
# DEPENDENCIES: services.tiling_scheme.generate_tiling_scheme_from_raster
# ============================================================================
"""
Raster Generate Tiling Scheme — atomic handler for DAG workflows.

Reads the source raster on the ETL mount and computes a tiling grid.
Returns a list of tile_specs, each containing the window coordinates
and output path for one tile. The fan_out node iterates this list.

Wraps the existing generate_tiling_scheme_from_raster() function which
already supports local file paths via rasterio.open().
"""

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def raster_generate_tiling_scheme_atomic(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Compute tiling scheme from source raster on ETL mount.

    Params:
        source_path (str, required): Local path to source raster on mount
        processing_options (dict, optional): Contains tile_size, overlap overrides
        _run_id (str, required): System-injected
        _node_name (str, required): System-injected

    Returns:
        {"success": True, "result": {tile_specs: [...], total_tiles, grid, ...}}
    """
    source_path = params.get("source_path")
    processing_options = params.get("processing_options", {})
    run_id = params.get("_run_id", "")
    node_name = params.get("_node_name", "")

    if not run_id or not node_name:
        return {
            "success": False,
            "error": "Missing system parameters: _run_id and _node_name required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    if not source_path:
        return {
            "success": False,
            "error": "source_path is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    log_prefix = f"[{run_id[:8]}][{node_name}]"

    try:
        if not os.path.exists(source_path):
            return {
                "success": False,
                "error": f"Source raster not found on mount: {source_path}",
                "error_type": "FileNotFoundError",
                "retryable": False,
            }

        tile_size = processing_options.get("tile_size")  # None = auto
        overlap = processing_options.get("overlap", 512)
        target_crs = processing_options.get("target_crs", "EPSG:4326")

        logger.info(
            "%s Generating tiling scheme from %s (tile_size=%s, overlap=%s)",
            log_prefix, source_path, tile_size or "auto", overlap,
        )

        start = time.monotonic()

        from services.tiling_scheme import generate_tiling_scheme_from_raster

        geojson = generate_tiling_scheme_from_raster(
            raster_path=source_path,
            tile_size=tile_size,
            overlap=overlap,
            target_crs=target_crs,
        )

        elapsed = time.monotonic() - start

        # Extract tile specs from the GeoJSON features
        features = geojson.get("features", [])
        total_tiles = len(features)
        grid = geojson.get("metadata", {}).get("grid", {})

        # Build tile_specs list for fan-out — each entry has everything
        # the process_single_tile handler needs
        tile_specs = []
        for feat in features:
            props = feat.get("properties", {})
            tile_specs.append({
                "tile_index": props.get("task_id", 0),
                "row": props.get("row", 0),
                "col": props.get("col", 0),
                "pixel_window": props.get("pixel_window"),  # {col_off, row_off, width, height}
                "bounds_4326": props.get("bounds_4326"),  # [minx, miny, maxx, maxy]
                "target_width_pixels": props.get("target_width_pixels"),
                "target_height_pixels": props.get("target_height_pixels"),
            })

        logger.info(
            "%s Tiling scheme: %d tiles (%s grid) in %.1fs",
            log_prefix, total_tiles,
            f"{grid.get('rows', '?')}x{grid.get('cols', '?')}",
            elapsed,
        )

        return {
            "success": True,
            "result": {
                "tile_specs": tile_specs,
                "total_tiles": total_tiles,
                "grid": grid,
                "source_crs": geojson.get("metadata", {}).get("source_crs"),
                "target_crs": target_crs,
                "target_bounds": geojson.get("metadata", {}).get("target_bounds"),
                "target_dimensions": geojson.get("metadata", {}).get("target_dimensions"),
                "target_resolution": geojson.get("metadata", {}).get("target_resolution"),
                "processing_time_seconds": round(elapsed, 2),
            },
        }

    except Exception as exc:
        import traceback
        logger.error("%s Tiling scheme generation failed: %s\n%s", log_prefix, exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"Tiling scheme generation failed: {exc}",
            "error_type": "TilingError",
            "retryable": False,
        }
