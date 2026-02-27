# ============================================================================
# CLAUDE CONTEXT - VIRTUALZARR TASK HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Services - VirtualiZarr pipeline task handlers
# PURPOSE: Scan, validate, combine, and register virtual Zarr references
# LAST_REVIEWED: 27 FEB 2026
# EXPORTS: virtualzarr_scan, virtualzarr_copy, virtualzarr_validate, virtualzarr_combine, virtualzarr_register
# DEPENDENCIES: fsspec, adlfs, h5py, virtualizarr, xarray (all lazy-imported)
# ============================================================================
"""
VirtualZarr Task Handlers - Scan, Copy, Validate, Combine, Register.

Five handler functions for the virtualzarr job pipeline. All heavy libraries
(h5py, virtualizarr, xarray) are lazy-imported inside function bodies to
avoid import-time overhead.

Handler Contract:
    All handlers return {"success": True/False, ...}
    Never raise exceptions to caller - catch and return error dicts.

Registration: services/__init__.py -> ALL_HANDLERS

Handlers:
    virtualzarr_scan:     List NetCDF files, build source→silver manifest
    virtualzarr_copy:     Copy single file from bronze → silver-netcdf
    virtualzarr_validate: Validate single file's HDF5 structure
    virtualzarr_combine:  Combine virtual datasets into reference JSON
    virtualzarr_register: Build STAC item, update release record
"""

import logging
import time
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_virtualzarr")


# =============================================================================
# HELPERS
# =============================================================================

def _get_storage_account() -> str:
    """Get silver storage account name from config."""
    from config import get_config
    return get_config().storage.silver.account_name


def _get_silver_netcdf_container() -> str:
    """Get the silver-netcdf container name from config."""
    from config import get_config
    return get_config().storage.silver.netcdf


def _get_blob_fs():
    """
    Create an Azure Blob filesystem using DefaultAzureCredential.

    Returns:
        adlfs.AzureBlobFileSystem instance
    """
    from adlfs import AzureBlobFileSystem
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    return AzureBlobFileSystem(
        account_name=_get_storage_account(),
        credential=credential,
    )


# =============================================================================
# HANDLER 1: virtualzarr_scan
# =============================================================================

def virtualzarr_scan(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Scan source container for NetCDF files and write manifest with source→silver mapping.

    Lists blobs matching file_pattern under source_url, computes relative paths,
    maps each file to a silver-netcdf destination, and writes manifest JSON.
    The manifest is the source of truth for the copy stage.

    Supports single-file mode: if source_url ends with a file extension matching
    file_pattern, treats it as a single file (skips listing).

    Args:
        params: Task parameters
            - source_url (str): abfs:// URL to source container/prefix (or single file)
            - file_pattern (str): Glob pattern for filtering (default "*.nc")
            - max_files (int): Maximum file count cap
            - ref_output_prefix (str): Output prefix in silver container
        context: Optional execution context

    Returns:
        {"success": True, "result": {"manifest_url": ..., "file_count": N, "total_size_bytes": N}}
    """
    start = time.time()

    source_url = params.get("source_url")
    file_pattern = params.get("file_pattern", "*.nc")
    max_files = params.get("max_files", 500)
    ref_output_prefix = params.get("ref_output_prefix")

    logger.info(
        f"virtualzarr_scan: source_url={source_url}, "
        f"pattern={file_pattern}, max_files={max_files}"
    )

    try:
        import fnmatch
        import json
        from infrastructure import BlobRepository

        silver_container = _get_silver_netcdf_container()

        # Parse source_url to get container and prefix
        # Expected format: abfs://container/prefix or abfs://container
        source_path = source_url.replace("abfs://", "")
        parts = source_path.split("/", 1)
        source_container = parts[0]
        source_prefix = parts[1] if len(parts) > 1 else ""

        # Determine zone from container name
        zone = "bronze" if source_container.startswith("bronze") else "silver"
        blob_repo = BlobRepository.for_zone(zone)

        # Single-file detection: if source_url ends with a matching extension
        if source_prefix and fnmatch.fnmatch(source_prefix.rsplit("/", 1)[-1], file_pattern):
            # Single file mode — no listing needed
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
            logger.info(f"virtualzarr_scan: Single file mode — {filename}")
        else:
            # Multi-file mode — list blobs under the prefix
            blob_list = blob_repo.list_blobs(source_container, prefix=source_prefix)

            matched_files = []
            total_size_bytes = 0
            for blob_info in blob_list:
                blob_name = blob_info["name"]
                filename = blob_name.rsplit("/", 1)[-1]
                if fnmatch.fnmatch(filename, file_pattern):
                    # Compute relative path by stripping the source prefix
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

            # Sort alphabetically by source URL
            matched_files.sort(key=lambda f: f["source_url"])

        # Fail if zero files found
        if not matched_files:
            elapsed = time.time() - start
            logger.warning(
                f"virtualzarr_scan: No files matching '{file_pattern}' "
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
                f"virtualzarr_scan: Found {len(matched_files)} files, "
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

        # Build files[] array with source→silver mapping
        files = []
        for f in matched_files:
            silver_path = f"{ref_output_prefix}/data/{f['relative_path']}"
            files.append({
                "source_url": f["source_url"],
                "relative_path": f["relative_path"],
                "silver_path": silver_path,
                "size_bytes": f["size_bytes"],
            })

        # Build nc_files[] convenience list (silver URLs for combine stage)
        nc_files = [
            f"abfs://{silver_container}/{entry['silver_path']}"
            for entry in files
        ]

        # Build manifest (source of truth for copy + downstream stages)
        manifest = {
            "source_url": source_url,
            "file_pattern": file_pattern,
            "file_count": len(files),
            "total_size_bytes": total_size_bytes,
            "silver_container": silver_container,
            "ref_output_prefix": ref_output_prefix,
            "files": files,
            "nc_files": nc_files,
        }

        # Write manifest to silver-netcdf via BlobRepository
        manifest_blob_path = f"{ref_output_prefix}/manifest.json"
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

        silver_repo = BlobRepository.for_zone("silver")
        silver_repo.write_blob(
            silver_container,
            manifest_blob_path,
            manifest_bytes,
            content_type="application/json",
        )

        manifest_url = f"abfs://{silver_container}/{manifest_blob_path}"

        elapsed = time.time() - start
        logger.info(
            f"virtualzarr_scan: Found {len(files)} files, "
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
        logger.error(f"virtualzarr_scan failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 2: virtualzarr_copy
# =============================================================================

def virtualzarr_copy(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Copy a single NetCDF file from bronze to silver-netcdf.

    Uses BlobRepository read/write (cross-zone safe regardless of account
    topology). Will be swapped for azcopy later — handler signature stays same.

    Args:
        params: Task parameters
            - source_url (str): abfs:// URL to the source file
            - silver_container (str): Target container (e.g. "silver-netcdf")
            - silver_path (str): Target blob path within silver container
            - size_bytes (int): Expected file size for verification
        context: Optional execution context

    Returns:
        {"success": True, "result": {"silver_url": ..., "bytes_copied": N}}
    """
    start = time.time()

    source_url = params.get("source_url")
    silver_container = params.get("silver_container")
    silver_path = params.get("silver_path")
    expected_size = params.get("size_bytes", 0)

    logger.info(
        f"virtualzarr_copy: {source_url} → "
        f"{silver_container}/{silver_path}"
    )

    try:
        from infrastructure import BlobRepository

        # Parse source_url → (container, blob_path)
        source_path = source_url.replace("abfs://", "")
        parts = source_path.split("/", 1)
        source_container = parts[0]
        source_blob = parts[1] if len(parts) > 1 else ""

        # Zone detection: bronze-* → bronze, else silver
        source_zone = "bronze" if source_container.startswith("bronze") else "silver"

        # Read from source
        source_repo = BlobRepository.for_zone(source_zone)
        data = source_repo.read_blob(source_container, source_blob)

        # Verify size if expected_size > 0
        if expected_size > 0 and len(data) != expected_size:
            logger.warning(
                f"virtualzarr_copy: Size mismatch for {source_url}. "
                f"Expected {expected_size}, got {len(data)}"
            )

        # Write to silver-netcdf
        silver_repo = BlobRepository.for_zone("silver")
        silver_repo.write_blob(silver_container, silver_path, data)

        silver_url = f"abfs://{silver_container}/{silver_path}"
        bytes_copied = len(data)

        elapsed = time.time() - start
        logger.info(
            f"virtualzarr_copy: Copied {bytes_copied} bytes → "
            f"{silver_url} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "silver_url": silver_url,
                "bytes_copied": bytes_copied,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(
            f"virtualzarr_copy failed for {source_url}: {e} ({elapsed:.1f}s)"
        )
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 3: virtualzarr_validate
# =============================================================================

def virtualzarr_validate(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validate a single NetCDF file's HDF5 structure.

    Opens the file with h5py via fsspec (header-only), extracts variable
    metadata (shape, dtype, chunks, compression), and generates warnings
    for problematic chunking configurations.

    Args:
        params: Task parameters
            - nc_url (str): abfs:// URL to the NetCDF file
            - fail_on_warnings (bool): If True, return success=False when warnings found
        context: Optional execution context

    Returns:
        {"success": True/False, "result": {"nc_url": ..., "status": ..., "variables": {...}, ...}}
    """
    start = time.time()

    nc_url = params.get("nc_url")
    fail_on_warnings = params.get("fail_on_warnings", False)

    logger.info(f"virtualzarr_validate: nc_url={nc_url}, fail_on_warnings={fail_on_warnings}")

    try:
        import h5py
        import fsspec

        LARGE_VAR_THRESHOLD = 100 * 1024 * 1024  # 100 MB
        LARGE_CHUNK_THRESHOLD = 100 * 1024 * 1024  # 100 MB
        LARGE_COORD_THRESHOLD = 50 * 1024 * 1024  # 50 MB

        # Open HDF5 file via fsspec (header-only read)
        account_name = _get_storage_account()
        fs = fsspec.filesystem("abfs", account_name=account_name)
        blob_path = nc_url.replace("abfs://", "")

        variables = {}
        dimensions = {}
        warnings_list = []

        with fs.open(blob_path, "rb") as f:
            with h5py.File(f, "r") as h5f:
                # Extract dimensions from root attributes or dimension scales
                for name, dataset in h5f.items():
                    if not isinstance(dataset, h5py.Dataset):
                        continue

                    shape = dataset.shape
                    dtype = str(dataset.dtype)
                    chunks = dataset.chunks  # None if contiguous
                    compression = dataset.compression

                    var_size_bytes = dataset.dtype.itemsize
                    for dim_len in shape:
                        var_size_bytes *= dim_len

                    variables[name] = {
                        "shape": list(shape),
                        "dtype": dtype,
                        "chunks": list(chunks) if chunks else None,
                        "compression": compression,
                        "size_bytes": var_size_bytes,
                    }

                    # Record dimensions (1D variables are often dimension coords)
                    if len(shape) == 1:
                        dimensions[name] = shape[0]

                    # Warning: No HDF5 chunking on large variables
                    if chunks is None and var_size_bytes > LARGE_VAR_THRESHOLD:
                        warnings_list.append(
                            f"Variable '{name}' is contiguous (no HDF5 chunking) "
                            f"and {var_size_bytes / (1024*1024):.0f} MB - "
                            f"will require full read for any access"
                        )

                    # Warning: Individual chunk size too large
                    if chunks is not None:
                        chunk_size_bytes = dataset.dtype.itemsize
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
                f"virtualzarr_validate: {nc_url} failed with "
                f"{len(warnings_list)} warnings ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"Validation warnings on {nc_url}: "
                    + "; ".join(warnings_list)
                ),
                "error_type": "ChunkingWarning",
                "result": {
                    "nc_url": nc_url,
                    "status": status,
                    "variables": variables,
                    "dimensions": dimensions,
                    "warnings": warnings_list,
                },
            }

        elapsed = time.time() - start
        logger.info(
            f"virtualzarr_validate: {nc_url} status={status}, "
            f"{len(variables)} variables, {len(warnings_list)} warnings ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "nc_url": nc_url,
                "status": status,
                "variables": variables,
                "dimensions": dimensions,
                "warnings": warnings_list,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"virtualzarr_validate failed for {nc_url}: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 4: virtualzarr_combine
# =============================================================================

def virtualzarr_combine(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Combine virtual datasets into a single Zarr reference JSON.

    Reads manifest for file list, opens each file with virtualizarr,
    concatenates along concat_dim, exports to kerchunk JSON, and
    extracts spatial/temporal extent metadata.

    Args:
        params: Task parameters
            - manifest_url (str): abfs:// URL to manifest.json
            - combined_ref_url (str): abfs:// URL for output reference JSON
            - concat_dim (str): Dimension to concatenate along (default "time")
            - dataset_id (str): Dataset identifier for logging
        context: Optional execution context

    Returns:
        {"success": True, "result": {"combined_ref_url": ..., "source_files": N, ...}}
    """
    start = time.time()

    manifest_url = params.get("manifest_url")
    combined_ref_url = params.get("combined_ref_url")
    concat_dim = params.get("concat_dim", "time")
    dataset_id = params.get("dataset_id", "unknown")

    logger.info(
        f"virtualzarr_combine: manifest={manifest_url}, "
        f"concat_dim={concat_dim}, dataset_id={dataset_id}"
    )

    try:
        import json
        import numpy as np
        import xarray as xr
        import fsspec
        from virtualizarr import open_virtual_dataset

        account_name = _get_storage_account()
        fs = fsspec.filesystem("abfs", account_name=account_name)

        # Read manifest for file list
        manifest_path = manifest_url.replace("abfs://", "")
        with fs.open(manifest_path, "r") as f:
            manifest = json.load(f)
        nc_files = manifest.get("nc_files", [])

        if not nc_files:
            elapsed = time.time() - start
            logger.error(f"virtualzarr_combine: Empty manifest at {manifest_url} ({elapsed:.1f}s)")
            return {
                "success": False,
                "error": f"Manifest at {manifest_url} contains no files",
                "error_type": "ValueError",
            }

        logger.info(f"virtualzarr_combine: Processing {len(nc_files)} files")

        # Pre-check: open first file to get reference variable/dimension info
        first_url = nc_files[0]
        first_path = first_url.replace("abfs://", "")
        storage_options = {"account_name": account_name}

        first_vds = open_virtual_dataset(
            first_path,
            indexes={},
            reader_options={"storage_options": storage_options},
        )
        reference_vars = set(first_vds.data_vars)
        reference_dims = {}
        for dim_name, dim_size in first_vds.dims.items():
            if dim_name != concat_dim:
                reference_dims[dim_name] = dim_size

        # Open all virtual datasets
        virtual_datasets = [first_vds]
        for nc_url in nc_files[1:]:
            nc_path = nc_url.replace("abfs://", "")
            vds = open_virtual_dataset(
                nc_path,
                indexes={},
                reader_options={"storage_options": storage_options},
            )

            # Verify variables match
            current_vars = set(vds.data_vars)
            if current_vars != reference_vars:
                missing = reference_vars - current_vars
                extra = current_vars - reference_vars
                elapsed = time.time() - start
                logger.error(
                    f"virtualzarr_combine: Variable mismatch in {nc_url}. "
                    f"Missing: {missing}, Extra: {extra} ({elapsed:.1f}s)"
                )
                return {
                    "success": False,
                    "error": (
                        f"Variable mismatch in {nc_url}. "
                        f"Missing: {missing}, Extra: {extra}"
                    ),
                    "error_type": "ValueError",
                }

            # Verify non-concat dimensions match
            for dim_name, expected_size in reference_dims.items():
                actual_size = vds.dims.get(dim_name)
                if actual_size is not None and actual_size != expected_size:
                    elapsed = time.time() - start
                    logger.error(
                        f"virtualzarr_combine: Dimension '{dim_name}' mismatch in {nc_url}. "
                        f"Expected {expected_size}, got {actual_size} ({elapsed:.1f}s)"
                    )
                    return {
                        "success": False,
                        "error": (
                            f"Dimension '{dim_name}' size mismatch in {nc_url}. "
                            f"Expected {expected_size}, got {actual_size}"
                        ),
                        "error_type": "ValueError",
                    }

            virtual_datasets.append(vds)

        # Concatenate along concat_dim
        combined = xr.concat(virtual_datasets, dim=concat_dim)

        # Export to kerchunk reference JSON
        combined_path = combined_ref_url.replace("abfs://", "")
        combined.virtualize.to_kerchunk(combined_path, format="json")

        # Extract metadata from the combined dataset
        all_dims = dict(combined.dims)
        all_variables = list(combined.data_vars)

        # Extract spatial extent from lat/lon coordinate variables
        spatial_extent = None
        lat_names = ["lat", "latitude", "y"]
        lon_names = ["lon", "longitude", "x"]

        lat_coord = None
        lon_coord = None
        for name in lat_names:
            if name in combined.coords:
                lat_coord = combined.coords[name]
                break
        for name in lon_names:
            if name in combined.coords:
                lon_coord = combined.coords[name]
                break

        if lat_coord is not None and lon_coord is not None:
            try:
                lat_min = float(np.nanmin(lat_coord.values))
                lat_max = float(np.nanmax(lat_coord.values))
                lon_min = float(np.nanmin(lon_coord.values))
                lon_max = float(np.nanmax(lon_coord.values))
                spatial_extent = [lon_min, lat_min, lon_max, lat_max]
            except Exception as ext_err:
                logger.warning(f"virtualzarr_combine: Could not extract spatial extent: {ext_err}")

        # Extract time range from time coordinate
        time_range = None
        time_names = ["time", "t"]
        for name in time_names:
            if name in combined.coords:
                try:
                    time_vals = combined.coords[name].values
                    time_min = str(np.nanmin(time_vals))
                    time_max = str(np.nanmax(time_vals))
                    time_range = [time_min, time_max]
                except Exception as time_err:
                    logger.warning(f"virtualzarr_combine: Could not extract time range: {time_err}")
                break

        # Validation read: try opening combined reference to verify
        try:
            validation_ds = xr.open_dataset(
                "reference://",
                engine="zarr",
                backend_kwargs={
                    "consolidated": False,
                    "storage_options": {
                        "fo": combined_path,
                        "remote_protocol": "abfs",
                        "remote_options": {"account_name": account_name},
                    },
                },
            )
            validation_ds.close()
            logger.info("virtualzarr_combine: Validation read succeeded")
        except Exception as val_err:
            logger.warning(f"virtualzarr_combine: Validation read failed (non-fatal): {val_err}")

        elapsed = time.time() - start
        logger.info(
            f"virtualzarr_combine: Combined {len(nc_files)} files, "
            f"dims={all_dims}, vars={len(all_variables)}, "
            f"spatial={spatial_extent}, time={time_range} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "combined_ref_url": combined_ref_url,
                "source_files": len(nc_files),
                "dimensions": all_dims,
                "variables": all_variables,
                "time_range": time_range,
                "spatial_extent": spatial_extent,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"virtualzarr_combine failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 5: virtualzarr_register
# =============================================================================

def virtualzarr_register(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build STAC item and update release record.

    Constructs a STAC item dict from combine results, caches it on the
    release record, updates physical outputs and processing status.

    Args:
        params: Task parameters
            - release_id (str): Release to update
            - stac_item_id (str): STAC item identifier
            - collection_id (str): STAC collection identifier
            - dataset_id (str): Dataset identifier
            - resource_id (str): Resource identifier
            - combined_ref_url (str): URL to the combined reference JSON
            - spatial_extent (list): [west, south, east, north] or None
            - time_range (list): [start, end] datetime strings or None
            - variables (list): List of variable names
            - dimensions (dict): Dimension name -> size mapping
            - source_files (int): Number of source NetCDF files
        context: Optional execution context

    Returns:
        {"success": True, "result": {"stac_item_cached": True, "release_updated": True, ...}}
    """
    start = time.time()

    release_id = params.get("release_id")
    stac_item_id = params.get("stac_item_id")
    collection_id = params.get("collection_id")
    dataset_id = params.get("dataset_id")
    resource_id = params.get("resource_id")
    combined_ref_url = params.get("combined_ref_url")
    spatial_extent = params.get("spatial_extent")
    time_range = params.get("time_range")
    variables = params.get("variables", [])
    dimensions = params.get("dimensions", {})
    source_files = params.get("source_files", 0)

    logger.info(
        f"virtualzarr_register: release_id={release_id}, "
        f"stac_item_id={stac_item_id}, collection_id={collection_id}"
    )

    try:
        from datetime import datetime, timezone
        from infrastructure.release_repository import ReleaseRepository
        from core.models.asset import ProcessingStatus

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
            "geoetl:pipeline": "virtualzarr",
            "geoetl:dataset_id": dataset_id,
            "geoetl:resource_id": resource_id,
            "geoetl:source_files": source_files,
            "xarray:open_kwargs": {
                "engine": "zarr",
                "backend_kwargs": {
                    "consolidated": False,
                    "storage_options": {
                        "fo": combined_ref_url,
                        "remote_protocol": "abfs",
                        "remote_options": {
                            "account_name": _get_storage_account(),
                        },
                    },
                },
            },
            "zarr:variables": variables,
            "zarr:dimensions": dimensions,
        }

        if time_range and len(time_range) == 2:
            properties["start_datetime"] = time_range[0]
            properties["end_datetime"] = time_range[1]
            properties["datetime"] = None  # Required when using start/end
        else:
            properties["datetime"] = now_iso

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
                "reference": {
                    "href": combined_ref_url,
                    "type": "application/json",
                    "title": "Virtual Zarr Reference (Kerchunk)",
                    "roles": ["data"],
                },
            },
        }

        # Update release record
        release_repo = ReleaseRepository()

        # Cache STAC item JSON
        stac_updated = release_repo.update_stac_item_json(release_id, stac_item)
        if not stac_updated:
            logger.warning(f"virtualzarr_register: Failed to update STAC item for release {release_id}")

        # Extract blob path from combined_ref_url for physical outputs
        ref_blob_path = combined_ref_url.replace("abfs://", "")

        # Update physical outputs
        outputs_updated = release_repo.update_physical_outputs(
            release_id,
            blob_path=ref_blob_path,
            stac_item_id=stac_item_id,
            output_mode="zarr_reference",
        )
        if not outputs_updated:
            logger.warning(
                f"virtualzarr_register: Failed to update physical outputs for release {release_id}"
            )

        # Update processing status to completed
        status_updated = release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        if not status_updated:
            logger.warning(
                f"virtualzarr_register: Failed to update processing status for release {release_id}"
            )

        elapsed = time.time() - start
        logger.info(
            f"virtualzarr_register: STAC cached={stac_updated}, "
            f"outputs={outputs_updated}, status={status_updated}, "
            f"blob_path={ref_blob_path} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "stac_item_cached": stac_updated,
                "release_updated": outputs_updated and status_updated,
                "blob_path": ref_blob_path,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"virtualzarr_register failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
