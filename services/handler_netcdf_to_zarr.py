# ============================================================================
# CLAUDE CONTEXT - NETCDF TO ZARR TASK HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Services - NetCDF-to-Zarr pipeline task handlers
# PURPOSE: Scan, copy-to-mount, validate, convert, and register native Zarr
# LAST_REVIEWED: 03 MAR 2026
# EXPORTS: netcdf_scan, netcdf_copy, netcdf_validate, netcdf_convert, netcdf_register
# DEPENDENCIES: xarray, zarr, adlfs (all lazy-imported)
# ============================================================================
"""
NetCDF-to-Zarr Task Handlers - Scan, Copy, Validate, Convert, Register.

Five handler functions for the netcdf_to_zarr job pipeline. All heavy libraries
(xarray, zarr, adlfs) are lazy-imported inside function bodies to avoid
import-time overhead.

Handler Contract:
    All handlers return {"success": True/False, ...}
    Never raise exceptions to caller - catch and return error dicts.

Registration: services/__init__.py -> ALL_HANDLERS

Handlers:
    netcdf_scan:      List NetCDF files in bronze, build manifest
    netcdf_copy:      Copy single file from bronze → /mounts/etl-temp/{job_id}/
    netcdf_validate:  Validate single file's structure with xarray
    netcdf_convert:   xr.open_mfdataset() → ds.to_zarr() to silver-zarr
    netcdf_register:  Build STAC item, update release record
"""

import time
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_netcdf_to_zarr")


# =============================================================================
# HELPERS
# =============================================================================

# Container helper lives in jobs/netcdf_to_zarr.py (mirrors virtualzarr pattern)
from jobs.netcdf_to_zarr import _get_silver_zarr_container


def _get_storage_account() -> str:
    """Get silver storage account name from config."""
    from config import get_config
    return get_config().storage.silver.account_name


def _get_spatial_extent(ds) -> list | None:
    """Extract [lon_min, lat_min, lon_max, lat_max] bbox from xarray dataset."""
    import numpy as np
    lat_names = ["lat", "latitude", "y"]
    lon_names = ["lon", "longitude", "x"]
    lat_coord = next((ds.coords[n] for n in lat_names if n in ds.coords), None)
    lon_coord = next((ds.coords[n] for n in lon_names if n in ds.coords), None)
    if lat_coord is None or lon_coord is None:
        return None
    try:
        return [
            float(np.nanmin(lon_coord.values)),
            float(np.nanmin(lat_coord.values)),
            float(np.nanmax(lon_coord.values)),
            float(np.nanmax(lat_coord.values)),
        ]
    except Exception:
        return None


def _build_zarr_encoding(ds, spatial_chunk_size=256, time_chunk_size=1,
                         compressor_name="lz4", compression_level=5,
                         zarr_format=3):
    """
    Build optimized Zarr encoding for tile-serving performance.

    Generates target chunk sizes and per-variable encoding dicts for
    ds.to_zarr(encoding=...). Only encodes data variables, not coordinates.

    Args:
        ds: xarray.Dataset to encode
        spatial_chunk_size: Chunk size for spatial dims (lat/lon/y/x), clamped to dim size
        time_chunk_size: Chunk size for time dim, clamped to dim size
        compressor_name: "lz4", "zstd", or "none"
        compression_level: 1-9 (passed to Blosc clevel)
        zarr_format: 2 or 3 — determines codec objects and encoding keys

    Returns:
        (target_chunks, encoding) tuple:
            target_chunks: dict for ds.chunk() — {dim_name: chunk_size}
            encoding: dict for ds.to_zarr(encoding=...) — {var_name: {...}}
    """
    # Detect spatial and time dimensions
    spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
    time_names = {"time", "t"}

    target_chunks = {}
    for dim_name, dim_size in ds.sizes.items():
        dim_lower = dim_name.lower()
        if dim_lower in spatial_names:
            target_chunks[dim_name] = min(spatial_chunk_size, dim_size)
        elif dim_lower in time_names:
            target_chunks[dim_name] = min(time_chunk_size, dim_size)
        else:
            target_chunks[dim_name] = dim_size

    # Build compressor — format-specific codec objects
    compressor_obj = None
    if compressor_name != "none":
        if zarr_format == 2:
            import numcodecs
            compressor_obj = numcodecs.Blosc(
                cname=compressor_name,
                clevel=compression_level,
                shuffle=numcodecs.Blosc.BITSHUFFLE,
            )
        else:
            from zarr.codecs import BloscCodec
            compressor_obj = BloscCodec(
                cname=compressor_name,
                clevel=compression_level,
                shuffle="bitshuffle",
            )

    # Build per-variable encoding (data vars only, not coords)
    encoding = {}
    for var_name in ds.data_vars:
        var = ds[var_name]
        var_chunks = tuple(
            target_chunks.get(dim, ds.sizes[dim])
            for dim in var.dims
        )
        enc = {"chunks": var_chunks}
        if compressor_obj is not None:
            if zarr_format == 2:
                enc["compressor"] = compressor_obj
            else:
                enc["compressors"] = [compressor_obj]
        encoding[var_name] = enc

    logger.info(
        f"_build_zarr_encoding: zarr_format={zarr_format}, "
        f"spatial={spatial_chunk_size}, "
        f"time={time_chunk_size}, compressor={compressor_name}(L{compression_level}), "
        f"{len(encoding)} vars encoded, chunks={target_chunks}"
    )

    return target_chunks, encoding


# =============================================================================
# HANDLER 1: netcdf_scan
# =============================================================================

def netcdf_scan(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Scan source container for NetCDF files and write manifest.

    Lists blobs matching file_pattern under source_url, builds a manifest
    with source URLs and planned local file paths, and writes the manifest
    to silver-zarr alongside the eventual output.

    Supports single-file mode: if source_url ends with a file extension
    matching file_pattern, treats it as a single file (skips listing).

    Args:
        params: Task parameters
            - source_url (str): abfs:// URL to source container/prefix (or single file)
            - source_account (str): Source storage account name
            - file_pattern (str): Glob pattern for filtering (default "*.nc")
            - max_files (int): Maximum file count cap
            - output_folder (str): Output folder in silver-zarr container
        context: Optional execution context

    Returns:
        {"success": True, "result": {"manifest_url": ..., "file_count": N, "total_size_bytes": N}}
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    file_pattern = params.get("file_pattern", "*.nc")
    max_files = params.get("max_files", 500)
    output_folder = params.get("output_folder")

    logger.info(
        f"netcdf_scan: source_url={source_url}, "
        f"source_account={source_account}, "
        f"pattern={file_pattern}, max_files={max_files}"
    )

    try:
        import fnmatch
        import json
        from infrastructure import BlobRepository

        zarr_container = _get_silver_zarr_container()

        # Parse source_url to get container and prefix
        source_path = source_url.replace("abfs://", "")
        parts = source_path.split("/", 1)
        source_container = parts[0]
        source_prefix = parts[1] if len(parts) > 1 else ""

        # Use explicit source_account from job params (set by submit trigger).
        if source_account:
            blob_repo = BlobRepository(account_name=source_account)
        else:
            blob_repo = BlobRepository.for_zone("bronze")

        # Single-file detection: if source_url ends with a matching extension
        if source_prefix and fnmatch.fnmatch(source_prefix.rsplit("/", 1)[-1], file_pattern):
            filename = source_prefix.rsplit("/", 1)[-1]
            try:
                props = blob_repo.get_blob_properties(source_container, source_prefix)
                file_size = props.get("size", 0)
            except Exception:
                file_size = 0

            matched_files = [{
                "source_url": source_url,
                "blob_name": source_prefix,
                "relative_path": filename,
                "size_bytes": file_size,
            }]
            total_size_bytes = file_size
            logger.info(f"netcdf_scan: Single file mode — {filename}")
        else:
            # Multi-file mode — list blobs under the prefix.
            blob_list = blob_repo.list_blobs(source_container, prefix=source_prefix)

            matched_files = []
            total_size_bytes = 0
            for blob_info in blob_list:
                blob_name = blob_info["name"]
                filename = blob_name.rsplit("/", 1)[-1]
                if fnmatch.fnmatch(filename, file_pattern):
                    if source_prefix and blob_name.startswith(source_prefix):
                        relative = blob_name[len(source_prefix):].lstrip("/")
                    else:
                        relative = filename
                    size = blob_info.get("size", 0)
                    matched_files.append({
                        "source_url": f"abfs://{source_container}/{blob_name}",
                        "blob_name": blob_name,
                        "relative_path": relative,
                        "size_bytes": size,
                    })
                    total_size_bytes += size

            matched_files.sort(key=lambda f: f["source_url"])

        # Fail if zero files found
        if not matched_files:
            elapsed = time.time() - start
            logger.warning(
                f"netcdf_scan: No files matching '{file_pattern}' "
                f"found at {source_url} ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": f"No files matching '{file_pattern}' found at {source_url}",
                "error_type": "FileNotFoundError",
            }

        # Enforce max_files cap
        if len(matched_files) > max_files:
            elapsed = time.time() - start
            logger.warning(
                f"netcdf_scan: Found {len(matched_files)} files, "
                f"exceeds max_files={max_files} ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"Found {len(matched_files)} files matching '{file_pattern}', "
                    f"exceeds max_files limit of {max_files}. "
                    f"Increase max_files or narrow file_pattern."
                ),
                "error_type": "ValueError",
            }

        # Build files[] array with source info
        files = []
        for f in matched_files:
            files.append({
                "source_url": f["source_url"],
                "relative_path": f["relative_path"],
                "size_bytes": f["size_bytes"],
            })

        # Build local_files[] convenience list (mount paths for validate stage)
        # The actual local_dir is set per-task in create_tasks_for_stage,
        # but we store relative paths here for reconstruction.
        local_files = [entry["relative_path"] for entry in files]

        # Build manifest
        manifest = {
            "source_url": source_url,
            "file_pattern": file_pattern,
            "file_count": len(files),
            "total_size_bytes": total_size_bytes,
            "output_folder": output_folder,
            "files": files,
            "local_files": local_files,
        }

        # Write manifest to silver-zarr container
        from jobs.netcdf_to_zarr import _manifest_blob_path
        manifest_blob_path = _manifest_blob_path(output_folder)
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

        silver_repo = BlobRepository.for_zone("silver")
        silver_repo.write_blob(
            zarr_container,
            manifest_blob_path,
            manifest_bytes,
            content_type="application/json",
        )

        manifest_url = f"abfs://{zarr_container}/{manifest_blob_path}"

        elapsed = time.time() - start
        logger.info(
            f"netcdf_scan: Found {len(files)} files, "
            f"total_size={total_size_bytes} bytes, "
            f"manifest={manifest_url} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "manifest_url": manifest_url,
                "file_count": len(files),
                "total_size_bytes": total_size_bytes,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"netcdf_scan failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 2: netcdf_copy
# =============================================================================

def netcdf_copy(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Copy a single NetCDF file from bronze to local mounted storage.

    Downloads the file from Azure Blob Storage to {etl_mount_path}/{job_id}/
    for fast local processing in subsequent stages. Mount path is resolved
    at execution time from config (not baked into task params).

    Args:
        params: Task parameters
            - source_url (str): abfs:// URL to the source file
            - source_account (str): Source storage account name
            - job_id (str): Job ID (used to build local dir on mount)
            - filename (str): Target filename within local_dir
            - size_bytes (int): Expected file size for verification
        context: Optional execution context

    Returns:
        {"success": True, "result": {"local_path": ..., "bytes_copied": N}}
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    job_id = params.get("job_id")
    filename = params.get("filename")
    expected_size = params.get("size_bytes", 0)

    # Resolve mount path at execution time (on Docker worker)
    from config import get_config
    etl_mount_path = get_config().docker.etl_mount_path
    if not etl_mount_path:
        return {
            "success": False,
            "error": "RASTER_ETL_MOUNT_PATH not configured — cannot copy files to local mount",
        }
    local_dir = f"{etl_mount_path}/{job_id}"

    logger.info(
        f"netcdf_copy: {source_url} → {local_dir}/{filename}"
    )

    try:
        import os
        from infrastructure import BlobRepository

        # Parse source_url → (container, blob_path)
        source_path = source_url.replace("abfs://", "")
        parts = source_path.split("/", 1)
        source_container = parts[0]
        source_blob = parts[1] if len(parts) > 1 else ""

        # Use explicit source_account from job params
        if source_account:
            source_repo = BlobRepository(account_name=source_account)
        else:
            source_repo = BlobRepository.for_zone("bronze")
        data = source_repo.read_blob(source_container, source_blob)

        # Verify size if expected_size > 0
        if expected_size > 0 and len(data) != expected_size:
            elapsed = time.time() - start
            logger.error(
                f"netcdf_copy: Size mismatch for {source_url}. "
                f"Expected {expected_size}, got {len(data)} ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"Size mismatch: expected {expected_size} bytes, "
                    f"got {len(data)} bytes"
                ),
                "error_type": "IntegrityError",
            }

        # Ensure local directory exists
        os.makedirs(local_dir, exist_ok=True)

        # Write to local mount
        local_path = os.path.join(local_dir, filename)

        # Ensure subdirectories exist for nested paths
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        with open(local_path, "wb") as f:
            f.write(data)

        bytes_copied = len(data)

        elapsed = time.time() - start
        logger.info(
            f"netcdf_copy: Copied {bytes_copied} bytes → "
            f"{local_path} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "local_path": local_path,
                "bytes_copied": bytes_copied,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(
            f"netcdf_copy failed for {source_url}: {e} ({elapsed:.1f}s)"
        )
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 3: netcdf_validate
# =============================================================================

def netcdf_validate(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validate a single NetCDF file's structure from local mount.

    Opens the file with xarray from local disk, extracts variable metadata
    (shape, dtype, chunks, encoding), and generates warnings for
    problematic chunking configurations. Mount path is resolved at execution
    time from config (not baked into task params).

    Args:
        params: Task parameters
            - job_id (str): Job ID (used to build local dir on mount)
            - relative_path (str): Relative path within job's mount dir
            - fail_on_warnings (bool): If True, return success=False when warnings found
        context: Optional execution context

    Returns:
        {"success": True/False, "result": {"local_path": ..., "status": ..., "variables": {...}, ...}}
    """
    start = time.time()

    job_id = params.get("job_id")
    relative_path = params.get("relative_path")
    fail_on_warnings = params.get("fail_on_warnings", False)

    # Resolve mount path at execution time (on Docker worker)
    from config import get_config
    etl_mount_path = get_config().docker.etl_mount_path
    if not etl_mount_path:
        return {
            "success": False,
            "error": "RASTER_ETL_MOUNT_PATH not configured — cannot access local mount",
        }
    local_path = f"{etl_mount_path}/{job_id}/{relative_path}"

    logger.info(f"netcdf_validate: local_path={local_path}, fail_on_warnings={fail_on_warnings}")

    try:
        import xarray as xr

        LARGE_VAR_THRESHOLD = 100 * 1024 * 1024  # 100 MB
        LARGE_CHUNK_THRESHOLD = 100 * 1024 * 1024  # 100 MB
        LARGE_COORD_THRESHOLD = 50 * 1024 * 1024  # 50 MB

        variables = {}
        dimensions = {}
        warnings_list = []

        with xr.open_dataset(local_path, engine="netcdf4") as ds:
            # Record dimensions
            for dim_name, dim_size in ds.dims.items():
                dimensions[dim_name] = dim_size

            # Extract variable metadata
            for name, var in ds.data_vars.items():
                shape = list(var.shape)
                dtype = str(var.dtype)
                encoding = var.encoding

                # Chunksizes from encoding (NetCDF4 HDF5 chunking)
                chunks = encoding.get("chunksizes")
                if chunks:
                    chunks = list(chunks)
                compression = encoding.get("zlib") or encoding.get("complevel")

                var_size_bytes = var.dtype.itemsize
                for dim_len in shape:
                    var_size_bytes *= dim_len

                variables[name] = {
                    "shape": shape,
                    "dtype": dtype,
                    "chunks": chunks,
                    "compression": compression,
                    "size_bytes": var_size_bytes,
                }

                # Warning: No chunking on large variables
                if chunks is None and var_size_bytes > LARGE_VAR_THRESHOLD:
                    warnings_list.append(
                        f"Variable '{name}' is contiguous (no chunking) "
                        f"and {var_size_bytes / (1024*1024):.0f} MB - "
                        f"will require full read for any access"
                    )

                # Warning: Individual chunk size too large
                if chunks is not None:
                    chunk_size_bytes = var.dtype.itemsize
                    for c in chunks:
                        chunk_size_bytes *= c
                    if chunk_size_bytes > LARGE_CHUNK_THRESHOLD:
                        warnings_list.append(
                            f"Variable '{name}' has chunk size "
                            f"{chunk_size_bytes / (1024*1024):.0f} MB - "
                            f"exceeds 100 MB threshold"
                        )

                # Warning: 2D coordinate variable too large
                if len(shape) == 2 and var_size_bytes > LARGE_COORD_THRESHOLD:
                    warnings_list.append(
                        f"Variable '{name}' is a 2D coordinate "
                        f"({var_size_bytes / (1024*1024):.0f} MB) - "
                        f"exceeds 50 MB threshold for coordinate variables"
                    )

        status = "warning" if warnings_list else "success"

        # If fail_on_warnings and warnings present, return failure
        if fail_on_warnings and warnings_list:
            elapsed = time.time() - start
            logger.warning(
                f"netcdf_validate: {local_path} failed with "
                f"{len(warnings_list)} warnings ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"Validation warnings on {local_path}: "
                    + "; ".join(warnings_list)
                ),
                "error_type": "ChunkingWarning",
                "result": {
                    "local_path": local_path,
                    "status": status,
                    "variables": variables,
                    "dimensions": dimensions,
                    "warnings": warnings_list,
                },
            }

        elapsed = time.time() - start
        logger.info(
            f"netcdf_validate: {local_path} status={status}, "
            f"{len(variables)} variables, {len(warnings_list)} warnings ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "local_path": local_path,
                "status": status,
                "variables": variables,
                "dimensions": dimensions,
                "warnings": warnings_list,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"netcdf_validate failed for {local_path}: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 4: netcdf_convert
# =============================================================================

def netcdf_convert(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert local NetCDF files to a native Zarr store in silver-zarr.

    Opens all NetCDF files from local mount with xr.open_mfdataset(),
    writes to silver-zarr container via adlfs, then cleans up temp files.

    Applies optimized chunking (spatial 256×256, time=1) with Blosc+LZ4
    compression. Mount path is resolved at execution time from config.

    Args:
        params: Task parameters
            - job_id (str): Job ID (used to build local dir on mount)
            - file_pattern (str): Glob pattern (default "*.nc")
            - concat_dim (str): Dimension to concatenate along (default "time")
            - output_folder (str): Output folder in silver-zarr container
            - zarr_container (str): Silver-zarr container name
            - dataset_id (str): Dataset identifier for logging
            - resource_id (str): Resource identifier for logging
        context: Optional execution context

    Returns:
        {"success": True, "result": {"zarr_store_url": ..., "source_file_count": N, ...}}
    """
    start = time.time()

    # Resolve mount path at execution time (on Docker worker)
    job_id = params.get("job_id")
    from config import get_config as _get_config
    _etl_mount = _get_config().docker.etl_mount_path
    if not _etl_mount:
        return {
            "success": False,
            "error": "RASTER_ETL_MOUNT_PATH not configured — cannot access local mount",
        }
    local_dir = f"{_etl_mount}/{job_id}"
    file_pattern = params.get("file_pattern", "*.nc")
    concat_dim = params.get("concat_dim", "time")
    output_folder = params.get("output_folder")
    zarr_container = params.get("zarr_container")
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")

    # Chunking optimization params
    spatial_chunk_size = params.get("spatial_chunk_size", 256)
    time_chunk_size = params.get("time_chunk_size", 1)
    compressor_name = params.get("compressor", "lz4")
    compression_level = params.get("compression_level", 5)
    zarr_format = params.get("zarr_format", 3)

    logger.info(
        f"netcdf_convert: local_dir={local_dir}, "
        f"concat_dim={concat_dim}, "
        f"output={zarr_container}/{output_folder}, "
        f"dataset_id={dataset_id}, "
        f"chunks=spatial:{spatial_chunk_size}/time:{time_chunk_size}, "
        f"compressor={compressor_name}(L{compression_level})"
    )

    import shutil

    ds = None
    try:
        import glob
        import os
        import numpy as np
        import xarray as xr
        from infrastructure import BlobRepository

        # Find all NetCDF files in local dir
        nc_pattern = os.path.join(local_dir, "**", file_pattern)
        nc_files = sorted(glob.glob(nc_pattern, recursive=True))

        if not nc_files:
            # Try flat pattern too
            nc_pattern_flat = os.path.join(local_dir, file_pattern)
            nc_files = sorted(glob.glob(nc_pattern_flat))

        if not nc_files:
            elapsed = time.time() - start
            logger.error(
                f"netcdf_convert: No files matching '{file_pattern}' "
                f"in {local_dir} ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": f"No files matching '{file_pattern}' found in {local_dir}",
                "error_type": "FileNotFoundError",
            }

        logger.info(f"netcdf_convert: Found {len(nc_files)} files to convert")

        # Open dataset(s) — single file or multi-file
        if len(nc_files) == 1:
            ds = xr.open_dataset(nc_files[0], engine="netcdf4")
            logger.info("netcdf_convert: Single file — opened directly")
        else:
            # Check concat_dim exists before trying
            test_ds = xr.open_dataset(nc_files[0], engine="netcdf4")
            available_dims = list(test_ds.dims)
            test_ds.close()

            if concat_dim not in available_dims:
                elapsed = time.time() - start
                logger.error(
                    f"netcdf_convert: concat_dim '{concat_dim}' not found. "
                    f"Available dims: {available_dims} ({elapsed:.1f}s)"
                )
                return {
                    "success": False,
                    "error": (
                        f"Concat dimension '{concat_dim}' not found in dataset. "
                        f"Available: {available_dims}"
                    ),
                    "error_type": "ValueError",
                }

            ds = xr.open_mfdataset(
                nc_files,
                engine="netcdf4",
                concat_dim=concat_dim,
                combine="nested",
            )

        # Extract metadata before writing
        all_dims = {dim: int(size) for dim, size in ds.dims.items()}
        all_variables = list(ds.data_vars)

        # Extract spatial extent from lat/lon coordinate variables
        spatial_extent = _get_spatial_extent(ds)

        # Extract time range from time coordinate
        time_range = None
        time_names = ["time", "t"]
        for name in time_names:
            if name in ds.coords:
                try:
                    time_vals = ds.coords[name].values
                    time_min = str(np.nanmin(time_vals))
                    time_max = str(np.nanmax(time_vals))
                    time_range = [time_min, time_max]
                except Exception as time_err:
                    logger.warning(f"netcdf_convert: Could not extract time range: {time_err}")
                break

        # Write to silver-zarr via adlfs/fsspec
        silver_repo = BlobRepository.for_zone("silver")
        zarr_az_url = f"az://{zarr_container}/{output_folder}"
        storage_options = {
            "account_name": silver_repo.account_name,
            "credential": silver_repo.credential,
        }

        # Apply optimized chunking for tile serving
        target_chunks, encoding = _build_zarr_encoding(
            ds, spatial_chunk_size, time_chunk_size,
            compressor_name, compression_level,
            zarr_format=zarr_format,
        )
        ds = ds.chunk(target_chunks)

        # Pre-cleanup: delete existing blobs at target prefix to prevent
        # orphan metadata when format/chunking changes (ZARR_NOTES.md §153)
        cleanup = silver_repo.delete_blobs_by_prefix(zarr_container, output_folder)
        if cleanup["deleted_count"] > 0:
            logger.info(
                f"netcdf_convert: pre-cleanup deleted {cleanup['deleted_count']} "
                f"existing blobs under {zarr_container}/{output_folder}"
            )

        logger.info(f"netcdf_convert: Writing Zarr to {zarr_az_url}")

        ds.to_zarr(
            zarr_az_url,
            mode="w",
            consolidated=True,
            storage_options=storage_options,
            encoding=encoding,
            zarr_format=zarr_format,
        )

        zarr_store_url = f"abfs://{zarr_container}/{output_folder}"

        elapsed = time.time() - start
        logger.info(
            f"netcdf_convert: Converted {len(nc_files)} files to Zarr, "
            f"dims={all_dims}, vars={len(all_variables)}, "
            f"spatial={spatial_extent}, time={time_range} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "zarr_store_url": zarr_store_url,
                "source_file_count": len(nc_files),
                "dimensions": all_dims,
                "variables": all_variables,
                "time_range": time_range,
                "spatial_extent": spatial_extent,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"netcdf_convert failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
    finally:
        # Always close dataset and clean up temp dir
        if ds is not None:
            try:
                ds.close()
            except Exception:
                pass
        try:
            shutil.rmtree(local_dir)
            logger.info(f"netcdf_convert: Cleaned up temp dir {local_dir}")
        except Exception as cleanup_err:
            logger.warning(
                f"netcdf_convert: Failed to cleanup {local_dir}: {cleanup_err} "
                f"(janitor will handle it)"
            )


# =============================================================================
# HANDLER 5: netcdf_register
# =============================================================================

def netcdf_register(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build STAC item and update release record for native Zarr store.

    Re-opens the Zarr store from silver to verify, constructs a STAC item dict,
    caches it on the release record, and updates physical outputs and processing
    status.

    Closely follows ingest_zarr_register — same output format (native Zarr store).

    Args:
        params: Task parameters
            - release_id (str): Release to update
            - zarr_store_url (str): abfs:// URL to the silver-zarr store
            - stac_item_id (str): STAC item identifier
            - collection_id (str): STAC collection identifier
            - dataset_id (str): Dataset identifier
            - resource_id (str): Resource identifier
            - version_id (str): Version identifier
            - title (str): Optional title
            - description (str): Optional description
            - tags (list): Optional tags
            - access_level (str): Access level
            - spatial_extent (list): [west, south, east, north] from convert stage
            - time_range (list): [start, end] datetime strings from convert stage
            - variables (list): List of variable names
            - dimensions (dict): Dimension name -> size mapping
            - source_file_count (int): Number of source NetCDF files
        context: Optional execution context

    Returns:
        {"success": True, "result": {"stac_item_cached": True, "release_updated": True, ...}}
    """
    start = time.time()

    release_id = params.get("release_id")
    zarr_store_url = params.get("zarr_store_url")
    stac_item_id = params.get("stac_item_id")
    collection_id = params.get("collection_id")
    dataset_id = params.get("dataset_id")
    resource_id = params.get("resource_id")
    version_id = params.get("version_id")
    title = params.get("title")
    description = params.get("description")
    tags = params.get("tags", [])
    access_level = params.get("access_level")
    spatial_extent = params.get("spatial_extent")
    time_range = params.get("time_range")
    variables = params.get("variables", [])
    dimensions = params.get("dimensions", {})
    source_file_count = params.get("source_file_count", 0)

    logger.info(
        f"netcdf_register: release_id={release_id}, "
        f"stac_item_id={stac_item_id}, collection_id={collection_id}, "
        f"zarr_store_url={zarr_store_url}"
    )

    try:
        from datetime import datetime, timezone
        import xarray as xr
        from infrastructure import BlobRepository
        from infrastructure.release_repository import ReleaseRepository
        from core.models.asset import ProcessingStatus

        # Parse zarr_store_url to get container and prefix
        store_path = zarr_store_url.replace("abfs://", "")
        parts = store_path.split("/", 1)
        silver_container = parts[0]
        store_prefix = parts[1] if len(parts) > 1 else ""

        silver_repo = BlobRepository.for_zone("silver")
        silver_account = silver_repo.account_name

        # Verify Zarr store is readable before registering
        zarr_az_url = f"az://{silver_container}/{store_prefix}"
        storage_options = {
            "account_name": silver_account,
            "credential": silver_repo.credential,
        }
        try:
            verify_ds = xr.open_zarr(zarr_az_url, storage_options=storage_options, consolidated=True)
        except Exception:
            verify_ds = xr.open_zarr(zarr_az_url, storage_options=storage_options, consolidated=False)
        verify_ds.close()
        logger.info(f"netcdf_register: Zarr store verified at {zarr_az_url}")

        # Build geometry and bbox from spatial_extent
        if spatial_extent and len(spatial_extent) == 4:
            west, south, east, north = spatial_extent
            bbox = [west, south, east, north]
            geometry = {
                "type": "Polygon",
                "coordinates": [[
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]],
            }
        else:
            # Global fallback if no spatial extent available
            bbox = [-180, -90, 180, 90]
            geometry = {
                "type": "Polygon",
                "coordinates": [[
                    [-180, -90],
                    [180, -90],
                    [180, 90],
                    [-180, 90],
                    [-180, -90],
                ]],
            }

        # Build datetime properties
        now_iso = datetime.now(timezone.utc).isoformat()
        properties = {
            "created": now_iso,
            "updated": now_iso,
            "geoetl:data_type": "zarr",
            "geoetl:pipeline": "netcdf_to_zarr",
            "geoetl:dataset_id": dataset_id,
            "geoetl:resource_id": resource_id,
            "geoetl:source_files": source_file_count,
            "xarray:open_kwargs": {
                "engine": "zarr",
                "chunks": {},
                "storage_options": {
                    "account_name": silver_account,
                },
            },
            "zarr:variables": variables,
            "zarr:dimensions": dimensions,
        }

        if title:
            properties["title"] = title
        if description:
            properties["description"] = description
        if tags:
            properties["geoetl:tags"] = tags
        if access_level:
            properties["geoetl:access_level"] = access_level

        if time_range and len(time_range) == 2:
            properties["start_datetime"] = time_range[0]
            properties["end_datetime"] = time_range[1]
            properties["datetime"] = None  # Required when using start/end
        else:
            properties["datetime"] = now_iso

        # Build abfs:// URL for the Zarr store asset
        # TiTiler-xarray passes URLs to fsspec which routes abfs:// to
        # Azure Blob with managed identity. https:// would be anonymous.
        zarr_abfs_url = f"abfs://{silver_container}/{store_prefix}"

        # Build STAC item
        stac_item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "stac_extensions": [],
            "id": stac_item_id,
            "collection": collection_id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": properties,
            "links": [],
            "assets": {
                "zarr-store": {
                    "href": zarr_abfs_url,
                    "type": "application/vnd+zarr",
                    "title": "Native Zarr Store (converted from NetCDF)",
                    "roles": ["data"],
                },
            },
        }

        # Update release record
        release_repo = ReleaseRepository()

        # Cache STAC item JSON
        stac_updated = release_repo.update_stac_item_json(release_id, stac_item)

        # Update physical outputs
        outputs_updated = release_repo.update_physical_outputs(
            release_id,
            blob_path=store_prefix,
            stac_item_id=stac_item_id,
            output_mode="zarr_store",
        )

        # Update processing status to completed
        status_updated = release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )

        elapsed = time.time() - start
        logger.info(
            f"netcdf_register: STAC cached={stac_updated}, "
            f"outputs={outputs_updated}, status={status_updated}, "
            f"store_prefix={store_prefix} ({elapsed:.1f}s)"
        )

        # Fail on any partial DB update — incomplete release records
        # are worse than a failed task that can be retried
        if not stac_updated or not outputs_updated or not status_updated:
            failed = []
            if not stac_updated: failed.append("stac_item_json")
            if not outputs_updated: failed.append("physical_outputs")
            if not status_updated: failed.append("processing_status")
            return {
                "success": False,
                "error": f"Partial DB update failure: {', '.join(failed)} not updated for release {release_id}",
                "error_type": "DatabaseError",
            }

        return {
            "success": True,
            "result": {
                "stac_item_cached": stac_updated,
                "release_updated": True,
                "blob_path": store_prefix,
                "zarr_url": zarr_abfs_url,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"netcdf_register failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
