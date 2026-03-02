# ============================================================================
# CLAUDE CONTEXT - INGEST ZARR HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler functions - Native Zarr store ingest pipeline
# PURPOSE: validate, copy, register handlers for ingest_zarr job
# LAST_REVIEWED: 02 MAR 2026
# EXPORTS: ingest_zarr_validate, ingest_zarr_copy, ingest_zarr_register
# DEPENDENCIES: xarray, fsspec, adlfs, infrastructure.blob_repository
# ============================================================================
"""
IngestZarr Task Handlers - Validate, Copy, Register.

Three handler functions for the ingest_zarr job pipeline. All heavy libraries
(xarray, adlfs, fsspec) are lazy-imported inside function bodies to avoid
import-time overhead.

Handler Contract:
    All handlers return {"success": True/False, ...}
    Never raise exceptions to caller - catch and return error dicts.

Registration: services/__init__.py -> ALL_HANDLERS

Handlers:
    ingest_zarr_validate:  Validate native Zarr store, extract metadata, list blobs
    ingest_zarr_copy:      Copy chunk of Zarr blobs from bronze to silver-zarr
    ingest_zarr_register:  Build STAC item, update release record
"""

import logging
import time
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_ingest_zarr")


# =============================================================================
# HELPERS
# =============================================================================

# Container helper lives in jobs/ingest_zarr.py (mirrors virtualzarr pattern)
from jobs.ingest_zarr import _get_silver_zarr_container


def _get_storage_account() -> str:
    """Get silver storage account name from config."""
    from config import get_config
    return get_config().storage.silver.account_name


def _get_blob_fs(zone: str = "silver"):
    """
    Create an Azure Blob filesystem using BlobRepository's credential.

    Auth is owned by BlobRepository -- this helper reuses the singleton's
    credential so all handlers authenticate through the same path.

    Args:
        zone: Trust zone to connect to (default "silver")

    Returns:
        adlfs.AzureBlobFileSystem instance
    """
    from adlfs import AzureBlobFileSystem
    from infrastructure import BlobRepository

    repo = BlobRepository.for_zone(zone)
    return AzureBlobFileSystem(
        account_name=repo.account_name,
        credential=repo.credential,
    )


# =============================================================================
# HANDLER 1: ingest_zarr_validate
# =============================================================================

def ingest_zarr_validate(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validate a native Zarr store is readable and extract metadata.

    Opens the Zarr store via xarray, validates structure markers exist,
    extracts variable/dimension info, and enumerates all blobs for the
    copy stage fan-out.

    Args:
        params: Task parameters
            - source_url (str): abfs:// URL to source Zarr store (abfs://container/prefix)
            - source_account (str): Source storage account name
            - dataset_id (str): Dataset identifier for logging
            - resource_id (str): Resource identifier for logging
        context: Optional execution context

    Returns:
        {"success": True, "result": {"blob_list": [...], "blob_count": N, ...}}
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")

    logger.info(
        f"ingest_zarr_validate: source_url={source_url}, "
        f"source_account={source_account}, "
        f"dataset_id={dataset_id}, resource_id={resource_id}"
    )

    try:
        import numpy as np
        import xarray as xr
        from infrastructure import BlobRepository

        # Parse source_url to get container and prefix
        # Expected format: abfs://container/prefix
        source_path = source_url.replace("abfs://", "")
        parts = source_path.split("/", 1)
        source_container = parts[0]
        source_prefix = parts[1] if len(parts) > 1 else ""

        # Get blob repo for source zone
        if source_account:
            blob_repo = BlobRepository(account_name=source_account)
        else:
            blob_repo = BlobRepository.for_zone("bronze")

        # List all blobs under prefix
        blob_list_raw = blob_repo.list_blobs(source_container, prefix=source_prefix)

        if not blob_list_raw:
            elapsed = time.time() - start
            logger.warning(
                f"ingest_zarr_validate: No blobs found at {source_url} ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": f"No blobs found at {source_url}",
                "error_type": "FileNotFoundError",
            }

        # Build simple blob name list for copy stage
        blob_names = [b["name"] for b in blob_list_raw]
        blob_count = len(blob_names)

        # Check for Zarr structure markers (.zmetadata, .zattrs, .zarray)
        marker_suffixes = (".zmetadata", ".zattrs", ".zarray")
        has_zarr_marker = any(
            any(name.endswith(suffix) for suffix in marker_suffixes)
            for name in blob_names
        )

        if not has_zarr_marker:
            elapsed = time.time() - start
            logger.warning(
                f"ingest_zarr_validate: No Zarr markers found at {source_url}. "
                f"Expected .zmetadata, .zattrs, or .zarray ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"No Zarr structure markers (.zmetadata, .zattrs, .zarray) "
                    f"found at {source_url}. Not a valid Zarr store."
                ),
                "error_type": "ValueError",
            }

        # Check for consolidated metadata
        has_consolidated_metadata = any(
            name.endswith(".zmetadata") for name in blob_names
        )

        # Open with xarray to validate readability and extract metadata
        # Use az:// protocol with storage_options for adlfs
        zarr_az_url = f"az://{source_container}/{source_prefix}"
        storage_options = {
            "account_name": blob_repo.account_name,
            "credential": blob_repo.credential,
        }

        ds = xr.open_zarr(
            zarr_az_url,
            storage_options=storage_options,
            consolidated=has_consolidated_metadata,
        )

        # Extract variable names
        variables = list(ds.data_vars)

        # Extract dimensions with sizes
        dimensions = {dim: int(size) for dim, size in ds.dims.items()}

        # Extract spatial extent from lat/lon coordinates
        spatial_extent = None
        lat_names = ["lat", "latitude", "y"]
        lon_names = ["lon", "longitude", "x"]

        lat_coord = None
        lon_coord = None
        for name in lat_names:
            if name in ds.coords:
                lat_coord = ds.coords[name]
                break
        for name in lon_names:
            if name in ds.coords:
                lon_coord = ds.coords[name]
                break

        if lat_coord is not None and lon_coord is not None:
            try:
                lat_min = float(np.nanmin(lat_coord.values))
                lat_max = float(np.nanmax(lat_coord.values))
                lon_min = float(np.nanmin(lon_coord.values))
                lon_max = float(np.nanmax(lon_coord.values))
                spatial_extent = [lon_min, lat_min, lon_max, lat_max]
            except Exception as ext_err:
                logger.warning(
                    f"ingest_zarr_validate: Could not extract spatial extent: {ext_err}"
                )

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
                    logger.warning(
                        f"ingest_zarr_validate: Could not extract time range: {time_err}"
                    )
                break

        ds.close()

        elapsed = time.time() - start
        logger.info(
            f"ingest_zarr_validate: Valid Zarr store at {source_url}, "
            f"{blob_count} blobs, {len(variables)} variables, "
            f"dims={dimensions}, spatial={spatial_extent}, "
            f"time={time_range} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "blob_list": blob_names,
                "blob_count": blob_count,
                "variables": variables,
                "dimensions": dimensions,
                "spatial_extent": spatial_extent,
                "time_range": time_range,
                "has_consolidated_metadata": has_consolidated_metadata,
                "source_container": source_container,
                "source_prefix": source_prefix,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"ingest_zarr_validate failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 2: ingest_zarr_copy
# =============================================================================

def ingest_zarr_copy(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Copy a chunk of Zarr blobs from bronze to silver-zarr.

    Reads each blob from the source account and writes it to the silver
    target. Uses BlobRepository read/write (cross-zone safe regardless
    of account topology).

    Args:
        params: Task parameters
            - source_url (str): abfs:// URL to source Zarr store
            - source_account (str): Source storage account name
            - blob_list (list): List of blob names to copy
            - target_container (str): Target container (e.g. "silver-zarr")
            - target_prefix (str): Target blob prefix within container
        context: Optional execution context

    Returns:
        {"success": True, "result": {"copied_count": N, "failed_count": N, ...}}
    """
    start = time.time()

    source_url = params.get("source_url")
    source_account = params.get("source_account")
    blob_list = params.get("blob_list", [])
    target_container = params.get("target_container")
    target_prefix = params.get("target_prefix")

    logger.info(
        f"ingest_zarr_copy: source_url={source_url}, "
        f"blob_count={len(blob_list)}, "
        f"target={target_container}/{target_prefix}"
    )

    try:
        from infrastructure import BlobRepository

        # Parse source_url to get source container and prefix
        source_path = source_url.replace("abfs://", "")
        parts = source_path.split("/", 1)
        source_container = parts[0]
        source_prefix = parts[1] if len(parts) > 1 else ""

        # Get source and target blob repos
        if source_account:
            source_repo = BlobRepository(account_name=source_account)
        else:
            source_repo = BlobRepository.for_zone("bronze")
        silver_repo = BlobRepository.for_zone("silver")

        copied_count = 0
        failed_count = 0
        failed_blobs = []

        for blob_name in blob_list:
            try:
                # Compute relative path by stripping the source prefix
                if source_prefix and blob_name.startswith(source_prefix):
                    relative = blob_name[len(source_prefix):].lstrip("/")
                else:
                    relative = blob_name

                # Compute target path
                target_path = f"{target_prefix}/{relative}"

                # Read from source, write to silver
                data = source_repo.read_blob(source_container, blob_name)
                silver_repo.write_blob(target_container, target_path, data)

                copied_count += 1

            except Exception as blob_err:
                failed_count += 1
                failed_blobs.append(blob_name)
                logger.warning(
                    f"ingest_zarr_copy: Failed to copy {blob_name}: {blob_err}"
                )

        elapsed = time.time() - start

        # Fail the task if any blob failed to copy
        if failed_count > 0:
            logger.error(
                f"ingest_zarr_copy: {failed_count}/{len(blob_list)} blobs failed "
                f"({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"{failed_count} of {len(blob_list)} blobs failed to copy. "
                    f"First failures: {failed_blobs[:5]}"
                ),
                "error_type": "BlobCopyError",
                "result": {
                    "copied_count": copied_count,
                    "failed_count": failed_count,
                    "failed_blobs": failed_blobs[:10],
                    "target_container": target_container,
                    "target_prefix": target_prefix,
                },
            }

        logger.info(
            f"ingest_zarr_copy: Copied {copied_count} blobs to "
            f"{target_container}/{target_prefix} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "copied_count": copied_count,
                "failed_count": 0,
                "target_container": target_container,
                "target_prefix": target_prefix,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"ingest_zarr_copy failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 3: ingest_zarr_register
# =============================================================================

def ingest_zarr_register(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build STAC item and update release record for native Zarr store.

    Re-opens the Zarr store from silver to extract metadata, constructs
    a STAC item dict, caches it on the release record, and updates
    physical outputs and processing status.

    Closely follows virtualzarr_register but with:
    - geoetl:pipeline = "ingest_zarr" (not "virtualzarr")
    - output_mode = "zarr_store" (not "zarr_reference")
    - Asset href = HTTPS URL to Zarr store prefix (not kerchunk JSON)
    - Asset type = "application/vnd+zarr" with roles ["data"]

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

    logger.info(
        f"ingest_zarr_register: release_id={release_id}, "
        f"stac_item_id={stac_item_id}, collection_id={collection_id}, "
        f"zarr_store_url={zarr_store_url}"
    )

    try:
        import numpy as np
        import xarray as xr
        from datetime import datetime, timezone
        from infrastructure import BlobRepository
        from infrastructure.release_repository import ReleaseRepository
        from core.models.asset import ProcessingStatus

        # Parse zarr_store_url to get container and prefix
        store_path = zarr_store_url.replace("abfs://", "")
        parts = store_path.split("/", 1)
        silver_container = parts[0]
        store_prefix = parts[1] if len(parts) > 1 else ""

        # Open Zarr store from silver to extract metadata
        silver_repo = BlobRepository.for_zone("silver")
        silver_account = silver_repo.account_name

        zarr_az_url = f"az://{silver_container}/{store_prefix}"
        storage_options = {
            "account_name": silver_account,
            "credential": silver_repo.credential,
        }

        # Try consolidated first, fall back to non-consolidated
        ds = None
        try:
            ds = xr.open_zarr(
                zarr_az_url,
                storage_options=storage_options,
                consolidated=True,
            )
        except Exception:
            ds = xr.open_zarr(
                zarr_az_url,
                storage_options=storage_options,
                consolidated=False,
            )

        # Extract metadata
        variables = list(ds.data_vars)
        dimensions = {dim: int(size) for dim, size in ds.dims.items()}

        # Extract spatial extent
        spatial_extent = None
        lat_names = ["lat", "latitude", "y"]
        lon_names = ["lon", "longitude", "x"]

        lat_coord = None
        lon_coord = None
        for name in lat_names:
            if name in ds.coords:
                lat_coord = ds.coords[name]
                break
        for name in lon_names:
            if name in ds.coords:
                lon_coord = ds.coords[name]
                break

        if lat_coord is not None and lon_coord is not None:
            try:
                lat_min = float(np.nanmin(lat_coord.values))
                lat_max = float(np.nanmax(lat_coord.values))
                lon_min = float(np.nanmin(lon_coord.values))
                lon_max = float(np.nanmax(lon_coord.values))
                spatial_extent = [lon_min, lat_min, lon_max, lat_max]
            except Exception as ext_err:
                logger.warning(
                    f"ingest_zarr_register: Could not extract spatial extent: {ext_err}"
                )

        # Extract time range
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
                    logger.warning(
                        f"ingest_zarr_register: Could not extract time range: {time_err}"
                    )
                break

        ds.close()

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
            "geoetl:pipeline": "ingest_zarr",
            "geoetl:dataset_id": dataset_id,
            "geoetl:resource_id": resource_id,
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

        # Build HTTPS URL for the Zarr store asset
        zarr_https_url = (
            f"https://{silver_account}.blob.core.windows.net/"
            f"{silver_container}/{store_prefix}"
        )

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
                    "href": zarr_https_url,
                    "type": "application/vnd+zarr",
                    "title": "Native Zarr Store",
                    "roles": ["data"],
                },
            },
        }

        # Update release record
        release_repo = ReleaseRepository()

        # Cache STAC item JSON
        stac_updated = release_repo.update_stac_item_json(release_id, stac_item)
        if not stac_updated:
            logger.warning(
                f"ingest_zarr_register: Failed to update STAC item for release {release_id}"
            )

        # Update physical outputs
        outputs_updated = release_repo.update_physical_outputs(
            release_id,
            blob_path=store_prefix,
            stac_item_id=stac_item_id,
            output_mode="zarr_store",
        )
        if not outputs_updated:
            logger.warning(
                f"ingest_zarr_register: Failed to update physical outputs for release {release_id}"
            )

        # Update processing status to completed
        status_updated = release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        if not status_updated:
            logger.warning(
                f"ingest_zarr_register: Failed to update processing status for release {release_id}"
            )

        elapsed = time.time() - start
        logger.info(
            f"ingest_zarr_register: STAC cached={stac_updated}, "
            f"outputs={outputs_updated}, status={status_updated}, "
            f"store_prefix={store_prefix} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "stac_item_cached": stac_updated,
                "release_updated": outputs_updated and status_updated,
                "blob_path": store_prefix,
                "zarr_https_url": zarr_https_url,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"ingest_zarr_register failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
