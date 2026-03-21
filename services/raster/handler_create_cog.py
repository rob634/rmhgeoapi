# ============================================================================
# CLAUDE CONTEXT - RASTER CREATE COG ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - COG creation from local mount path
# PURPOSE: Transform a local raster file on the ETL mount into a Cloud-
#          Optimized GeoTIFF, extract STAC-relevant metadata, and return
#          the local COG path plus all fields needed by downstream handlers.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_create_cog
# DEPENDENCIES: services.raster_cog.create_cog, rasterio, config
# ============================================================================
"""
raster_create_cog -- atomic DAG handler for COG creation.

Delegates transformation to the existing create_cog() in services/raster_cog.py
(disk-based path, in_memory=False). After create_cog() returns, opens the output
COG with rasterio to extract band statistics, transform, resolution, and rescale
range, then computes a SHA-256 checksum of the file.

Design decisions (from GATE2 / build spec section 3.3):
- create_cog() is called as-is; it handles BOTH transformation AND upload to
  silver internally (disk-based path: ETL mount -> cog_translate -> stream to
  blob). The raster_upload_cog handler will verify the blob exists rather than
  re-uploading.
- in_memory is hardcoded to False (C-B2). Docker always uses disk.
- The full raster_type dict is passed to create_cog (C-B3 / CR-6).
- _run_id replaces _task_id for temp-file namespace isolation (C-S2).
- Config defaults are used for jpeg_quality, overview_resampling, and
  reproject_resampling when job params do not specify them (C-S3).
- raster_bands, transform, resolution, rescale_range extracted here so that
  raster_persist_app_tables performs zero blob reads (CR-1, C-N1..C-N4).
- file_checksum (SHA-256) computed here while the file is on local disk (C-N5).

Ported from: services/handler_process_raster_complete.py Phase 2 (L1684-1834)
Supporting module: services/raster_cog.py (create_cog, disk-based path)
"""

import hashlib
import logging
import os
import time
import traceback
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_sha256(file_path: str) -> str:
    """Return 'sha256:<hex>' for the file at file_path."""
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _extract_cog_metadata(cog_path: str) -> Dict[str, Any]:
    """
    Open the output COG with rasterio and extract STAC-relevant metadata.

    Returns a dict with keys:
        raster_bands   - list of per-band dicts (band, data_type, nodata, statistics)
        rescale_range  - [global_min, global_max] from band 1 statistics
        transform      - 6-element affine list [a, b, c, d, e, f]
        resolution     - [abs(pixel_width), abs(pixel_height)]
        interleave     - str (BAND or PIXEL)
        crs            - str (e.g. "EPSG:4326")
        bounds_4326    - [minx, miny, maxx, maxy]
        shape          - [height, width]
        compression    - str
        tile_size      - [tile_width, tile_height] or [512, 512] default

    Raises RuntimeError if rasterio cannot open the file or stats unavailable.
    """
    import rasterio

    with rasterio.open(cog_path) as ds:
        transform = ds.transform
        transform_list = [
            transform.a,
            transform.b,
            transform.c,
            transform.d,
            transform.e,
            transform.f,
        ]
        resolution = [abs(transform.a), abs(transform.e)]

        bounds = ds.bounds
        shape = [ds.height, ds.width]
        crs_str = str(ds.crs) if ds.crs else "UNKNOWN"

        # Ensure bounds_4326 is actually in EPSG:4326 — reproject if needed
        if ds.crs and str(ds.crs) != "EPSG:4326":
            from rasterio.warp import transform_bounds
            reprojected = transform_bounds(ds.crs, "EPSG:4326", *bounds)
            bounds_4326 = list(reprojected)
        else:
            bounds_4326 = [bounds.left, bounds.bottom, bounds.right, bounds.top]

        # Profile fields
        profile = ds.profile
        compression = (profile.get("compress") or "unknown").upper()
        interleave = (profile.get("interleave") or "BAND").upper()

        # Tile size from profile (blockxsize/blockysize)
        tile_w = profile.get("blockxsize") or 512
        tile_h = profile.get("blockysize") or 512
        tile_size = [tile_w, tile_h]

        # Per-band metadata
        raster_bands = []
        global_min = None
        global_max = None

        for band_idx in range(1, ds.count + 1):
            nodata_val = ds.nodata
            dtype_str = str(ds.dtypes[band_idx - 1])

            # Compute statistics using windowed reads — O(block_size) memory, not O(full_band).
            # This preserves the disk-based handler's memory efficiency (~100MB ceiling).
            import numpy as np
            running_min = float('inf')
            running_max = float('-inf')
            running_sum = 0.0
            running_sq_sum = 0.0
            running_count = 0

            for _, window in ds.block_windows(band_idx):
                block = ds.read(band_idx, window=window)
                if nodata_val is not None:
                    valid = block[block != nodata_val]
                else:
                    valid = block.ravel()

                if valid.size > 0:
                    running_min = min(running_min, float(np.nanmin(valid)))
                    running_max = max(running_max, float(np.nanmax(valid)))
                    running_sum += float(np.nansum(valid))
                    running_sq_sum += float(np.nansum(valid.astype(np.float64) ** 2))
                    running_count += valid.size

            if running_count > 0:
                b_min = running_min
                b_max = running_max
                b_mean = running_sum / running_count
                b_std = float(np.sqrt(max(0, running_sq_sum / running_count - b_mean ** 2)))
            else:
                b_min = b_max = b_mean = b_std = 0.0

            raster_bands.append({
                "band": band_idx,
                "data_type": dtype_str,
                "nodata": nodata_val,
                "statistics": {
                    "min": b_min,
                    "max": b_max,
                    "mean": b_mean,
                    "stddev": b_std,
                },
            })

            # Track global min/max from band 1 only (for rescale_range)
            if band_idx == 1:
                global_min = b_min
                global_max = b_max

    # Guard against degenerate [0.0, 0.0] when all bands are nodata
    if global_min is not None and global_max is not None and global_min != global_max:
        rescale_range = [global_min, global_max]
    elif global_min is not None and global_min == global_max and global_min != 0.0:
        # Constant-value raster (not all-nodata) — use small range around the value
        rescale_range = [global_min, global_min + 1.0]
    else:
        # All-nodata or truly zero — set None so downstream uses dtype defaults
        rescale_range = None

    return {
        "raster_bands": raster_bands,
        "rescale_range": rescale_range,
        "transform": transform_list,
        "resolution": resolution,
        "interleave": interleave,
        "crs": crs_str,
        "bounds_4326": bounds_4326,
        "shape": shape,
        "compression": compression,
        "tile_size": tile_size,
    }


# ---------------------------------------------------------------------------
# Handler entry point
# ---------------------------------------------------------------------------

def raster_create_cog(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Atomic DAG handler: transform a local raster into a COG.

    Params (injected by DAG Brain via YAML receives + job params):
        source_path          str   local path on ETL mount (from download handler)
        raster_type          dict  full raster_type dict from validate handler
        source_crs           str   detected CRS string (e.g. "EPSG:32637")
        target_crs           str   reprojection target (default "EPSG:4326")
        needs_reprojection   bool  pre-computed by validate handler
        nodata               float|None  nodata value (optional)
        output_tier          str   COG tier (default "analysis")
        output_blob_name     str   custom output blob name (optional)
        jpeg_quality         int   JPEG quality override (optional)
        overview_resampling  str   resampling for overviews (optional)
        reproject_resampling str   resampling for reprojection (optional)
        _run_id              str   DAG Brain run ID (namespace isolation)

    Returns (success):
        {
          "success": true,
          "result": {
            "cog_path": str,             # local path on ETL mount
            "cog_size_bytes": int,
            "processing_time_seconds": float,
            "compression": str,
            "resampling": str,
            "tile_size": [int, int],
            "overview_levels": list,
            "bounds_4326": [float, float, float, float],
            "shape": [int, int],
            "raster_bands": [...],
            "rescale_range": [float, float],
            "transform": [float, float, float, float, float, float],
            "resolution": [float, float],
            "file_checksum": "sha256:...",
            "interleave": str,
            "crs": str,
            "cog_blob": str,             # silver blob path (from create_cog)
            "cog_container": str,
          }
        }

    Returns (failure):
        {
          "success": false,
          "error": str,
          "error_type": str,
          "retryable": bool
        }
    """
    handler_start = time.time()

    try:
        # ------------------------------------------------------------------
        # 1. Extract parameters
        # ------------------------------------------------------------------
        source_path = params.get("source_path")
        raster_type = params.get("raster_type", {})
        source_crs = params.get("source_crs")
        target_crs = params.get("target_crs")
        output_tier = params.get("output_tier", "analysis")
        output_blob_name = params.get("output_blob_name")
        nodata = params.get("nodata")

        # System-injected by DAG Brain
        run_id = params.get("_run_id")
        task_id = params.get("_task_id")

        # ------------------------------------------------------------------
        # 2. Validate required params
        # ------------------------------------------------------------------
        missing = []
        if not source_path:
            missing.append("source_path")
        if not source_crs:
            missing.append("source_crs")
        if not target_crs:
            missing.append("target_crs")
        if not output_blob_name:
            missing.append("output_blob_name")
        if not run_id:
            missing.append("_run_id")

        if missing:
            return {
                "success": False,
                "error": f"Missing required parameters: {', '.join(missing)}",
                "error_type": "InvalidParameterError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 3. Source file existence guard (fail-fast, never retry same input)
        # ------------------------------------------------------------------
        if not os.path.exists(source_path):
            return {
                "success": False,
                "error": f"Source file not found on ETL mount: {source_path}",
                "error_type": "FileNotFoundError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 4. Load config defaults (C-S3)
        # ------------------------------------------------------------------
        from config import get_config

        config_obj = get_config()
        raster_cfg = config_obj.raster

        # target_crs is now required (validated above) — no fallback needed

        jpeg_quality = params.get("jpeg_quality") or raster_cfg.cog_jpeg_quality
        overview_resampling = (
            params.get("overview_resampling")
            or raster_type.get("optimal_cog_settings", {}).get("overview_resampling")
            or raster_cfg.overview_resampling
        )
        reproject_resampling = (
            params.get("reproject_resampling")
            or raster_type.get("optimal_cog_settings", {}).get("reproject_resampling")
            or raster_cfg.reproject_resampling
        )

        # ------------------------------------------------------------------
        # 5. Validate raster_type is a dict (CR-6 guard)
        # ------------------------------------------------------------------
        if not isinstance(raster_type, dict):
            return {
                "success": False,
                "error": (
                    f"raster_type must be a dict with keys 'detected_type', "
                    f"'optimal_cog_settings', etc. Got: {type(raster_type).__name__}"
                ),
                "error_type": "InvalidParameterError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 6. Build cog_params and delegate to existing create_cog()
        #
        # create_cog() in raster_cog.py handles BOTH transformation AND upload
        # to silver when the disk-based path is active (use_etl_mount=True).
        # We pass _local_source_path so it skips the blob download step.
        # We also pass in_memory=False (C-B2) unconditionally.
        # _task_id receives _run_id for temp-file namespace isolation (C-S2).
        # ------------------------------------------------------------------
        from services.raster_cog import create_cog

        cog_params = {
            # Source: local file on mount (skips blob download in create_cog)
            "_local_source_path": source_path,
            # create_cog still needs container/blob for its fallback logic; pass
            # None explicitly — local_source_path mode tolerates None here.
            "container_name": None,
            "blob_name": None,
            # CRS settings
            "source_crs": source_crs,
            "target_crs": target_crs,
            # Full raster_type dict (C-B3 / CR-6)
            "raster_type": raster_type,
            # Output
            "output_blob_name": output_blob_name,
            "output_tier": output_tier,
            # Processing settings
            "in_memory": False,          # Always disk-based in Docker (C-B2)
            "jpeg_quality": jpeg_quality,
            "overview_resampling": overview_resampling,
            "reproject_resampling": reproject_resampling,
            # Namespace isolation: use _run_id (C-S2)
            "_task_id": run_id,
            # V0.10.5 DAG mode: keep output file for metadata extraction + separate upload
            "_skip_cleanup": True,
            "_skip_upload": True,
        }

        logger.info(
            "raster_create_cog: calling create_cog "
            "[source=%s, tier=%s, target_crs=%s, in_memory=False]",
            source_path, output_tier, target_crs,
        )

        cog_response = create_cog(cog_params)

        # ------------------------------------------------------------------
        # 7. Handle create_cog failure (C-B5)
        # ------------------------------------------------------------------
        if not cog_response.get("success"):
            raw_error = cog_response.get("error", "") or ""
            raw_message = cog_response.get("message", "") or ""

            # Detect disk-space error for retryable classification
            combined = (raw_error + " " + raw_message).lower()
            is_disk_space = any(
                kw in combined
                for kw in ("disk space", "no space left", "enospc", "insufficient")
            )

            logger.error(
                "raster_create_cog: create_cog() failed — error=%s message=%s",
                raw_error, raw_message,
            )
            return {
                "success": False,
                "error": raw_message or raw_error or "create_cog() returned failure",
                "error_type": "DiskSpaceError" if is_disk_space else "COGCreationError",
                "retryable": is_disk_space,
            }

        cog_result = cog_response.get("result", {})

        # ------------------------------------------------------------------
        # 8. Resolve local COG path on mount (C-B4 naming inconsistency)
        #
        # create_cog disk-based path writes to:
        #   {mount_path}/output_{task_short}.cog.tif
        # The output_path is returned inside disk_result, which is NOT exposed
        # directly through COGCreationData. We derive it from config.
        # ------------------------------------------------------------------
        mount_path = config_obj.docker.etl_mount_path
        task_short = run_id[:16] if run_id else "unknown"
        cog_path = os.path.join(mount_path, f"output_{task_short}.cog.tif")

        if not os.path.exists(cog_path):
            # create_cog completed without error but produced no local file.
            # This can happen if the disk-based path cleaned up its temp output
            # after upload. The COG is in silver; local path is unavailable.
            # Log the situation and surface as non-retryable.
            logger.error(
                "raster_create_cog: expected local COG at %s but file is absent "
                "(create_cog may have deleted it after upload — see ESC-2)",
                cog_path,
            )
            return {
                "success": False,
                "error": (
                    f"COG file not found on ETL mount after create_cog: {cog_path}. "
                    "create_cog may have deleted the temp file after upload."
                ),
                "error_type": "COGCreationError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 9. Extract raster metadata from output COG (C-N1 through C-N4)
        # ------------------------------------------------------------------
        logger.info("raster_create_cog: extracting metadata from %s", cog_path)
        try:
            cog_meta = _extract_cog_metadata(cog_path)
        except Exception as meta_exc:
            logger.error(
                "raster_create_cog: metadata extraction failed — %s\n%s",
                meta_exc, traceback.format_exc(),
            )
            return {
                "success": False,
                "error": f"Failed to extract metadata from output COG: {meta_exc}",
                "error_type": "COGCreationError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 10. (REMOVED) SHA-256 checksum — computed but never persisted to any DB table.
        #     Removed to avoid wasting I/O on large COGs. Re-add when cog_metadata
        #     schema includes a file_checksum column.
        file_checksum = None

        # ------------------------------------------------------------------
        # 11. Resolve COG blob path from create_cog result (C-B4)
        # ------------------------------------------------------------------
        cog_blob = cog_result.get("output_blob") or cog_result.get("cog_blob")
        cog_container = cog_result.get("cog_container")
        cog_size_bytes = cog_result.get("file_size") or os.path.getsize(cog_path)
        processing_time = round(time.time() - handler_start, 2)

        # overview_levels: create_cog disk path does not capture these;
        # pass through whatever is in the result (may be empty list).
        overview_levels = cog_result.get("overview_levels", [])

        result = {
            # Local file on ETL mount
            "cog_path": cog_path,
            "cog_size_bytes": cog_size_bytes,
            "processing_time_seconds": processing_time,
            # Compression / encoding
            "compression": cog_meta["compression"],
            "interleave": cog_meta["interleave"],
            "tile_size": cog_meta["tile_size"],
            "overview_levels": overview_levels,
            # Spatial metadata
            "bounds_4326": cog_meta["bounds_4326"],
            "shape": cog_meta["shape"],
            "crs": cog_meta["crs"],
            # Band metadata (C-N1, C-N4)
            "raster_bands": cog_meta["raster_bands"],
            "rescale_range": cog_meta["rescale_range"],
            # Affine transform (C-N2, C-N3)
            "transform": cog_meta["transform"],
            "resolution": cog_meta["resolution"],
            # Checksum (C-N5)
            "file_checksum": file_checksum,
            # Silver blob location (written by create_cog internally)
            "cog_blob": cog_blob,
            "cog_container": cog_container,
            # Passthrough from create_cog for diagnostics
            "resampling": overview_resampling,
        }

        logger.info(
            "raster_create_cog: complete in %.1fs — "
            "size=%d bytes, cog_blob=%s, checksum=%s...",
            processing_time,
            cog_size_bytes,
            cog_blob,
            file_checksum[:20] if file_checksum else "none",
        )

        return {"success": True, "result": result}

    except OSError as os_exc:
        # Disk-space errors surface as OSError with errno.ENOSPC
        import errno as _errno
        is_space = getattr(os_exc, "errno", None) == _errno.ENOSPC
        logger.error(
            "raster_create_cog: OSError — %s\n%s", os_exc, traceback.format_exc()
        )
        return {
            "success": False,
            "error": f"Disk I/O error during COG creation: {os_exc}",
            "error_type": "DiskSpaceError" if is_space else "COGCreationError",
            "retryable": is_space,
        }

    except Exception as exc:
        logger.error(
            "raster_create_cog: unhandled exception — %s\n%s",
            exc, traceback.format_exc(),
        )
        return {
            "success": False,
            "error": f"Unexpected error in raster_create_cog: {exc}",
            "error_type": "COGCreationError",
            "retryable": False,
        }
