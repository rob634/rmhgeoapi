# ============================================================================
# CLAUDE CONTEXT - ZARR VALIDATE SOURCE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Detect input type (NC/Zarr), validate, report dims
# PURPOSE: Validates source data and routes NC vs Zarr path. Accepts both
#          local mount paths (NetCDF) and abfs:// cloud URLs (native Zarr).
# LAST_REVIEWED: 30 MAR 2026
# EXPORTS: zarr_validate_source
# DEPENDENCIES: xarray, os
# ============================================================================
"""
Zarr Validate Source — detect input type and validate structure.

Accepts two forms of ``mount_path``:

- **Local path** (from NetCDF download): Uses ``os.listdir`` to detect .nc files.
- **Cloud URL** (``abfs://`` from native Zarr passthrough): Opens directly via
  ``xr.open_zarr`` with ``storage_options``. Native Zarr is never copied to the
  mount — ``download_to_mount`` returns the cloud URL for Zarr inputs.

Reports dimensions, current chunk sizes, and whether rechunking is needed.
"""

import os
import time
from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_validate_source")

ACCEPTABLE_SPATIAL_CHUNKS = {256, 512}

# Spatial dimension names recognised by this handler and downstream pyramid generation
_LAT_NAMES = {"lat", "latitude", "y"}
_LON_NAMES = {"lon", "longitude", "x"}

from services.zarr import extract_spatial_extent as _extract_spatial_extent


def _check_spatial_dims(dimensions: dict) -> tuple:
    """
    IV-H5: Verify dataset has at least one lat and one lon dimension.

    Returns (lat_dim, lon_dim) or raises ValueError for early rejection
    before expensive rechunk/pyramid steps.
    """
    lat_dim = lon_dim = None
    for dim in dimensions:
        dim_lower = dim.lower()
        if dim_lower in _LAT_NAMES and lat_dim is None:
            lat_dim = dim
        elif dim_lower in _LON_NAMES and lon_dim is None:
            lon_dim = dim
    if not lat_dim or not lon_dim:
        raise ValueError(
            f"Dataset has no recognisable spatial dimensions. "
            f"Expected at least one of {sorted(_LAT_NAMES)} and one of "
            f"{sorted(_LON_NAMES)}, but found only: {sorted(dimensions.keys())}. "
            f"Non-spatial datasets cannot be processed by this pipeline."
        )
    return lat_dim, lon_dim


def zarr_validate_source(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Detect input type (NetCDF vs Zarr) and validate source structure.

    Params:
        mount_path (str): Local mount path (NetCDF) or abfs:// cloud URL (native Zarr)
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
            "mount_path": "<local path or abfs:// URL, passed through to downstream>"
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
            "retryable": False,
        }

    logger.info(
        "zarr_validate_source: mount_path=%s dataset=%s resource=%s",
        mount_path, dataset_id, resource_id,
    )

    try:
        # --------------------------------------------------------------
        # Cloud URL path (native Zarr passthrough from download_to_mount)
        # --------------------------------------------------------------
        # Native Zarr is never copied to the mount — download_to_mount
        # returns the abfs:// cloud URL directly. We open it with
        # storage_options for direct blob reads.
        from infrastructure.etl_mount import is_cloud_source
        is_cloud_url = is_cloud_source(mount_path)

        if is_cloud_url:
            import xarray as xr
            from infrastructure.blob import BlobRepository

            source_repo = BlobRepository.for_zone("bronze")
            storage_options = {
                "account_name": source_repo.account_name,
                "credential": source_repo.credential,
            }

            try:
                ds = xr.open_zarr(mount_path, consolidated=True, storage_options=storage_options)
            except Exception:
                logger.info("zarr_validate_source: consolidated metadata not available, retrying without")
                ds = xr.open_zarr(mount_path, consolidated=False, storage_options=storage_options)

            input_type = "zarr"
            logger.info("zarr_validate_source: detected input_type=zarr (cloud URL)")

        else:
            # ----------------------------------------------------------
            # Local mount path (NetCDF or locally-downloaded Zarr)
            # ----------------------------------------------------------
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
                    "retryable": False,
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

        # --------------------------------------------------------------
        # Zarr validation (shared by cloud URL and local mount paths)
        # --------------------------------------------------------------
        if input_type == "zarr":
            try:
                dimensions = dict(ds.sizes)
                variable_count = len(ds.data_vars)

                # IV-H5: Early spatial dimension check — fail before rechunk/pyramid
                _check_spatial_dims(dimensions)

                current_chunks = {}
                spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
                needs_rechunk = False

                # Inspect ALL data variables for chunk sizes, not just the first.
                # Heterogeneous chunking (rare but possible) must trigger rechunk
                # if ANY variable has non-optimal spatial chunks.
                for var_name in ds.data_vars:
                    var_chunks = ds[var_name].encoding.get("chunks")
                    if var_chunks:
                        for dim, size in zip(ds[var_name].dims, var_chunks):
                            # Keep the first variable's chunks as the representative
                            if dim not in current_chunks:
                                current_chunks[dim] = size
                            if dim.lower() in spatial_names and size not in ACCEPTABLE_SPATIAL_CHUNKS:
                                needs_rechunk = True

                total_size_bytes = sum(ds[v].nbytes for v in ds.data_vars)
                spatial_extent = _extract_spatial_extent(ds)

                elapsed = time.time() - start
                logger.info(
                    "zarr_validate_source: zarr validated — dims=%s, chunks=%s, "
                    "needs_rechunk=%s, vars=%d, bbox=%s (%0.1fs)",
                    dimensions, current_chunks, needs_rechunk, variable_count,
                    spatial_extent, elapsed,
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
                    "spatial_extent": spatial_extent,
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
                # IV-H5: Early spatial dimension check — fail before rechunk/pyramid
                _check_spatial_dims(dimensions)
                total_size_bytes = sum(os.path.getsize(f) for f in nc_full_paths)
                spatial_extent = _extract_spatial_extent(ds)
            finally:
                ds.close()

            elapsed = time.time() - start
            logger.info(
                "zarr_validate_source: netcdf validated — %d files, dims=%s, "
                "vars=%d, total_size=%d bytes, bbox=%s (%0.1fs)",
                len(nc_files), dimensions, variable_count, total_size_bytes,
                spatial_extent, elapsed,
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
                "spatial_extent": spatial_extent,
                "mount_path": mount_path,
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_validate_source failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "retryable": False,  # Validation failures are data issues, not transient
        }
