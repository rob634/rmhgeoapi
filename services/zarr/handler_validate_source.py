# ============================================================================
# CLAUDE CONTEXT - ZARR VALIDATE SOURCE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Detect input type (NC/Zarr), validate, report dims
# PURPOSE: First node in unified zarr ingest workflow — routes NC vs Zarr path
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: zarr_validate_source
# DEPENDENCIES: adlfs, xarray, fsspec
# ============================================================================
"""
Zarr Validate Source — detect input type and validate structure.

Inspects source URL to determine if input is NetCDF (.nc files) or Zarr
(zarr.json or .zmetadata present). Reports dimensions, current chunk sizes,
and whether rechunking is needed (spatial chunks not 256 or 512).
"""

import logging
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
        source_url (str): abfs:// URL or blob path to source data
        source_account (str): Azure storage account name
        dataset_id (str): Dataset identifier for logging
        resource_id (str): Resource identifier for logging

    Returns:
        {
            "success": True,
            "input_type": "netcdf" | "zarr",
            "file_list": [...],
            "dimensions": {"time": N, "lat": N, "lon": N},
            "current_chunks": {...},
            "needs_rechunk": bool,
            "variable_count": int,
            "total_size_bytes": int
        }
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")

    if not source_url or not source_account:
        return {
            "success": False,
            "error": "source_url and source_account are required",
            "error_type": "ValidationError",
        }

    logger.info(
        "zarr_validate_source: source=%s account=%s dataset=%s",
        source_url, source_account, dataset_id,
    )

    try:
        import fsspec
        from infrastructure.blob import BlobRepository

        # Use BlobRepository for managed identity credentials
        blob_repo = BlobRepository.for_zone("bronze")
        storage_options = {"account_name": blob_repo.account_name, "credential": blob_repo.credential}
        fs = fsspec.filesystem("az", **storage_options)

        source_path = source_url.replace("abfs://", "")
        entries = fs.ls(source_path, detail=False)
        entry_names = [e.split("/")[-1] for e in entries]

        zarr_markers = {"zarr.json", ".zmetadata", ".zgroup", ".zattrs"}
        nc_extensions = {".nc", ".nc4", ".netcdf"}

        is_zarr = bool(zarr_markers & set(entry_names))
        nc_files = [e for e in entries if any(e.endswith(ext) for ext in nc_extensions)]
        is_netcdf = len(nc_files) > 0 and not is_zarr

        if not is_zarr and not is_netcdf:
            return {
                "success": False,
                "error": f"Cannot detect input type at {source_url}. "
                         f"No Zarr markers or .nc files found. "
                         f"Found: {entry_names[:10]}",
                "error_type": "ValidationError",
            }

        input_type = "zarr" if is_zarr else "netcdf"
        logger.info("zarr_validate_source: detected input_type=%s", input_type)

        if is_zarr:
            import xarray as xr

            try:
                ds = xr.open_zarr(source_url, storage_options=storage_options, consolidated=True)
            except Exception:
                logger.info("zarr_validate_source: consolidated metadata not available, retrying without")
                ds = xr.open_zarr(source_url, storage_options=storage_options, consolidated=False)
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
                }
            finally:
                ds.close()

        else:
            import xarray as xr

            nc_files = sorted(nc_files)

            first_url = f"abfs://{nc_files[0]}" if not nc_files[0].startswith("abfs://") else nc_files[0]
            ds = xr.open_dataset(
                first_url,
                engine="netcdf4",
                storage_options=storage_options,
            )
            try:
                dimensions = dict(ds.sizes)
                variable_count = len(ds.data_vars)
                total_size_bytes = sum(fs.info(f).get("size", 0) for f in nc_files)
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
                "file_list": nc_files,
                "dimensions": dimensions,
                "current_chunks": {},
                "needs_rechunk": False,
                "variable_count": variable_count,
                "total_size_bytes": total_size_bytes,
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_validate_source failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
