# ============================================================================
# CLAUDE CONTEXT - ZARR VALIDATE SOURCE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Detect input type (NC/Zarr), validate, report dims
# PURPOSE: First node in unified zarr ingest workflow — routes NC vs Zarr path
# LAST_REVIEWED: 26 MAR 2026
# EXPORTS: zarr_validate_source
# DEPENDENCIES: xarray, os
# ============================================================================
"""
Zarr Validate Source — detect input type and validate structure.

Inspects local mount path to determine if input is NetCDF (.nc files) or Zarr
(zarr.json or .zmetadata present). Reports dimensions, current chunk sizes,
and whether rechunking is needed (spatial chunks not 256 or 512).
"""

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ACCEPTABLE_SPATIAL_CHUNKS = {256, 512}


def zarr_validate_source(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Detect input type (NetCDF vs Zarr) and validate source structure.

    Params:
        mount_path (str): Local mount path where source data was copied
        dataset_id (str): Dataset identifier for logging
        resource_id (str): Resource identifier for logging

    Returns:
        {
            "success": True,
            "input_type": "netcdf" | "zarr",
            "file_list": ["/mount/etl-temp/{run_id}/source/file1.nc", ...],
            "dimensions": {"time": N, "lat": N, "lon": N},
            "current_chunks": {...},
            "needs_rechunk": bool,
            "variable_count": int,
            "total_size_bytes": int,
            "mount_path": "/mount/etl-temp/{run_id}/source"
        }
    """
    start = time.time()

    mount_path = params.get("mount_path")
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")

    if not mount_path:
        return {
            "success": False,
            "error": "mount_path is required",
            "error_type": "ValidationError",
        }

    logger.info(
        "zarr_validate_source: mount_path=%s dataset=%s resource=%s",
        mount_path, dataset_id, resource_id,
    )

    try:
        entries = os.listdir(mount_path)

        zarr_markers = {"zarr.json", ".zmetadata", ".zgroup", ".zattrs"}
        nc_extensions = {".nc", ".nc4", ".netcdf"}

        is_zarr = bool(zarr_markers & set(entries))
        nc_files = [e for e in entries if any(e.endswith(ext) for ext in nc_extensions)]
        is_netcdf = len(nc_files) > 0 and not is_zarr

        if not is_zarr and not is_netcdf:
            return {
                "success": False,
                "error": f"Cannot detect input type at {mount_path}. "
                         f"No Zarr markers or .nc files found. "
                         f"Found: {entries[:10]}",
                "error_type": "ValidationError",
            }

        input_type = "zarr" if is_zarr else "netcdf"
        logger.info("zarr_validate_source: detected input_type=%s", input_type)

        if is_zarr:
            import xarray as xr

            try:
                ds = xr.open_zarr(mount_path, consolidated=True)
            except Exception:
                logger.info("zarr_validate_source: consolidated metadata not available, retrying without")
                ds = xr.open_zarr(mount_path, consolidated=False)
            try:
                dimensions = dict(ds.sizes)
                variable_count = len(ds.data_vars)

                current_chunks = {}
                spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
                needs_rechunk = False

                if ds.data_vars:
                    first_var = list(ds.data_vars)[0]
                    var_chunks = ds[first_var].encoding.get("chunks")
                    if var_chunks:
                        for dim, size in zip(ds[first_var].dims, var_chunks):
                            current_chunks[dim] = size
                            if dim.lower() in spatial_names and size not in ACCEPTABLE_SPATIAL_CHUNKS:
                                needs_rechunk = True

                total_size_bytes = sum(ds[v].nbytes for v in ds.data_vars)

                elapsed = time.time() - start
                logger.info(
                    "zarr_validate_source: zarr validated — dims=%s, chunks=%s, "
                    "needs_rechunk=%s, vars=%d (%0.1fs)",
                    dimensions, current_chunks, needs_rechunk, variable_count, elapsed,
                )

                return {
                    "success": True,
                    "input_type": "zarr",
                    "file_list": [],
                    "dimensions": dimensions,
                    "current_chunks": current_chunks,
                    "needs_rechunk": needs_rechunk,
                    "variable_count": variable_count,
                    "total_size_bytes": total_size_bytes,
                    "mount_path": mount_path,
                }
            finally:
                ds.close()

        else:
            import xarray as xr

            nc_files = sorted(nc_files)
            nc_full_paths = [os.path.join(mount_path, f) for f in nc_files]

            ds = xr.open_dataset(
                nc_full_paths[0],
                engine="netcdf4",
            )
            try:
                dimensions = dict(ds.sizes)
                variable_count = len(ds.data_vars)
                total_size_bytes = sum(os.path.getsize(f) for f in nc_full_paths)
            finally:
                ds.close()

            elapsed = time.time() - start
            logger.info(
                "zarr_validate_source: netcdf validated — %d files, dims=%s, "
                "vars=%d, total_size=%d bytes (%0.1fs)",
                len(nc_files), dimensions, variable_count, total_size_bytes, elapsed,
            )

            return {
                "success": True,
                "input_type": "netcdf",
                "file_list": nc_full_paths,
                "dimensions": dimensions,
                "current_chunks": {},
                "needs_rechunk": False,
                "variable_count": variable_count,
                "total_size_bytes": total_size_bytes,
                "mount_path": mount_path,
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_validate_source failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
