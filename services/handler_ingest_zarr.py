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

import time
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_ingest_zarr")


# =============================================================================
# HELPERS
# =============================================================================

# Container helper lives in jobs/ingest_zarr.py
from jobs.ingest_zarr import _get_silver_zarr_container

# Shared Zarr helpers from netcdf_to_zarr (where _build_zarr_encoding also lives)
from services.zarr import extract_spatial_extent as _get_spatial_extent


def _get_storage_account() -> str:
    """Get silver storage account name from config."""
    from config import get_config
    return get_config().storage.silver.account_name


def _emit_checkpoint(params: dict, name: str, data: dict = None):
    """Emit a CHECKPOINT event to job_events table. Non-fatal on failure."""
    try:
        from infrastructure.job_event_repository import JobEventRepository
        from core.models.job_event import JobEventType, JobEventStatus
        job_id = params.get('_job_id')
        task_id = params.get('_task_id')
        stage = params.get('_stage')
        if not job_id or not task_id:
            return
        JobEventRepository().record_task_event(
            job_id=job_id,
            task_id=task_id,
            stage=stage or 0,
            event_type=JobEventType.CHECKPOINT,
            event_status=JobEventStatus.INFO,
            checkpoint_name=name,
            event_data=data or {},
        )
    except Exception:
        pass



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

        # Check for Zarr structure markers (v2: .zmetadata, .zattrs, .zarray; v3: zarr.json)
        v2_suffixes = (".zmetadata", ".zattrs", ".zarray")
        v3_suffixes = ("zarr.json",)
        has_zarr_marker = any(
            any(name.endswith(suffix) for suffix in v2_suffixes + v3_suffixes)
            for name in blob_names
        )

        if not has_zarr_marker:
            elapsed = time.time() - start
            logger.warning(
                f"ingest_zarr_validate: No Zarr markers found at {source_url}. "
                f"Expected .zmetadata/.zattrs/.zarray (v2) or zarr.json (v3) ({elapsed:.1f}s)"
            )
            return {
                "success": False,
                "error": (
                    f"No Zarr structure markers found at {source_url}. "
                    f"Expected .zmetadata/.zattrs/.zarray (v2) or zarr.json (v3). Not a valid Zarr store."
                ),
                "error_type": "ValueError",
            }

        # Check for consolidated metadata (v2) or zarr.json (v3)
        has_consolidated_metadata = any(
            name.endswith(".zmetadata") or name.endswith("zarr.json")
            for name in blob_names
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
        try:
            # Extract variable names
            variables = list(ds.data_vars)
            logger.info(
                f"ingest_zarr_validate: Opened source Zarr: "
                f"{len(ds.data_vars)} vars, {blob_count} blobs, "
                f"dims={dict(ds.dims)}"
            )

            # Extract dimensions with sizes
            dimensions = {dim: int(size) for dim, size in ds.dims.items()}

            # Extract spatial extent from lat/lon coordinates
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
                        logger.warning(
                            f"ingest_zarr_validate: Could not extract time range: {time_err}"
                        )
                    break
        finally:
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

    cleanup_before_copy = params.get("cleanup_before_copy", False)

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

        # Pre-cleanup: first copy task deletes existing blobs at target
        # prefix to prevent orphan metadata when format/chunking changes
        if cleanup_before_copy:
            cleanup = silver_repo.delete_blobs_by_prefix(
                target_container, target_prefix
            )
            if cleanup["deleted_count"] > 0:
                logger.info(
                    f"ingest_zarr_copy: pre-cleanup deleted "
                    f"{cleanup['deleted_count']} existing blobs under "
                    f"{target_container}/{target_prefix}"
                )

        copied_count = 0
        failed_count = 0
        failed_blobs = []
        total_blobs = len(blob_list)
        log_interval = max(1, total_blobs // 10)

        _emit_checkpoint(params, "copy_started", {
            "blob_count": total_blobs, "target": f"{target_container}/{target_prefix}",
        })

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

                # Tier 1: progress log every ~10%
                if copied_count % log_interval == 0 or copied_count == total_blobs:
                    pct = 100 * copied_count // total_blobs
                    elapsed_so_far = time.time() - start
                    logger.info(
                        f"ingest_zarr_copy: progress {copied_count}/{total_blobs} "
                        f"({pct}%) [{elapsed_so_far:.1f}s]"
                    )
                    # Tier 2: checkpoint every ~10%
                    _emit_checkpoint(params, "copy_progress", {
                        "copied": copied_count, "total": total_blobs, "pct": pct,
                    })

            except Exception as blob_err:
                failed_count += 1
                failed_blobs.append(blob_name)
                logger.warning(
                    f"ingest_zarr_copy: Failed to copy {blob_name}: {blob_err}"
                )

        elapsed = time.time() - start

        _emit_checkpoint(params, "copy_complete", {
            "copied": copied_count, "failed": failed_count, "elapsed_s": round(elapsed, 1),
        })

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

    Registers STAC metadata for ingested Zarr store:
    - geoetl:pipeline = "ingest_zarr"
    - output_mode = "zarr_store"
    - Asset href = HTTPS URL to Zarr store prefix
    - Asset type = "application/vnd+zarr" with roles ["data"]

    Args:
        params: Task parameters
            - release_id (str): Release to update
            - zarr_store_url (str): abfs:// URL to the silver-zarr store
            - stac_item_id (str): STAC item identifier
            - collection_id (str): STAC collection identifier
            - dataset_id (str): Dataset identifier
            - resource_id (str): Resource identifier
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
        spatial_extent = _get_spatial_extent(ds)

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
                    "title": "Native Zarr Store",
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
            f"ingest_zarr_register: STAC cached={stac_updated}, "
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
        logger.error(f"ingest_zarr_register failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


# =============================================================================
# HANDLER 4: ingest_zarr_rechunk
# =============================================================================

def ingest_zarr_rechunk(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Rechunk a source Zarr store and write optimized output to silver-zarr.

    Opens the source Zarr, applies optimized chunking for tile serving
    (spatial 256x256, time 1, Blosc+LZ4), and writes to silver blob storage.

    Accepts both local mount paths and ``abfs://`` cloud URLs as
    ``mount_path``. Native Zarr inputs arrive as cloud URLs because
    ``download_to_mount`` bypasses the mount for cloud-native formats —
    no data is copied to the fileshare. Cloud URLs are opened with
    ``storage_options`` for direct blob reads.

    Args:
        params: Task parameters
            - mount_path (str): Local path or abfs:// cloud URL to source Zarr
            - target_container (str): Target container (e.g. "silver-zarr")
            - target_prefix (str): Target blob prefix within container
            - spatial_chunk_size (int): Spatial chunk dim (default 256)
            - time_chunk_size (int): Time chunk dim (default 1)
            - compressor (str): "lz4", "zstd", or "none"
            - compression_level (int): 1-9
            - dataset_id (str): Dataset identifier for logging
            - resource_id (str): Resource identifier for logging
        context: Optional execution context

    Returns:
        {"success": True, "result": {"target_chunks": {...}, "compressor": "...", ...}}
    """
    start = time.time()

    mount_path = params.get("mount_path")
    target_container = params.get("target_container")
    target_prefix = params.get("target_prefix")
    spatial_chunk_size = params.get("spatial_chunk_size", 256)
    time_chunk_size = params.get("time_chunk_size", 1)
    compressor_name = params.get("compressor", "lz4")
    compression_level = params.get("compression_level", 5)
    zarr_format = params.get("zarr_format", 3)
    dry_run = params.get("dry_run", True)
    dataset_id = params.get("dataset_id", "unknown")
    resource_id = params.get("resource_id", "unknown")

    if not mount_path:
        return {
            "success": False,
            "error": "mount_path is required — local path or abfs:// cloud URL to source Zarr",
            "error_type": "ValueError",
        }

    logger.info(
        f"ingest_zarr_rechunk: mount_path={mount_path}, "
        f"target={target_container}/{target_prefix}, "
        f"chunks=spatial:{spatial_chunk_size}/time:{time_chunk_size}, "
        f"compressor={compressor_name}(L{compression_level})"
    )

    # Check if rechunking can be skipped (chunks already 256 or 512)
    current_chunks = params.get("current_chunks", {})
    if current_chunks:
        spatial_names = {"lat", "latitude", "y", "lon", "longitude", "x"}
        spatial_chunk_values = [
            v for k, v in current_chunks.items()
            if k.lower() in spatial_names
        ]
        acceptable = {256, 512}
        if spatial_chunk_values and all(v in acceptable for v in spatial_chunk_values):
            elapsed = time.time() - start
            logger.info(
                "ingest_zarr_rechunk: spatial chunks %s already optimal, "
                "skipping rechunk (%0.1fs)",
                spatial_chunk_values, elapsed,
            )
            return {
                "success": True,
                "result": {
                    "rechunked": False,
                    "zarr_store_url": mount_path,
                    "target_container": target_container,
                    "target_prefix": target_prefix,
                    "reason": f"Spatial chunks {spatial_chunk_values} already in {acceptable}",
                },
            }

    try:
        import xarray as xr
        from infrastructure import BlobRepository
        from services.handler_netcdf_to_zarr import _build_zarr_encoding

        # Open source Zarr — cloud URL (native Zarr passthrough) or local mount
        # Native Zarr arrives as abfs:// URL because download_to_mount bypasses
        # the mount for cloud-native formats. Local paths need no storage_options.
        from infrastructure.etl_mount import is_cloud_source
        is_cloud_url = is_cloud_source(mount_path)
        if is_cloud_url:
            from infrastructure.blob import BlobRepository
            source_repo = BlobRepository.for_zone("bronze")
            source_storage_options = {
                "account_name": source_repo.account_name,
                "credential": source_repo.credential,
            }
        else:
            source_storage_options = {}

        open_kwargs = {"consolidated": True}
        if source_storage_options:
            open_kwargs["storage_options"] = source_storage_options

        try:
            ds = xr.open_zarr(mount_path, **open_kwargs)
        except Exception:
            open_kwargs["consolidated"] = False
            ds = xr.open_zarr(mount_path, **open_kwargs)
        try:
            logger.info(
                f"ingest_zarr_rechunk: Opened source Zarr: "
                f"{len(ds.data_vars)} vars, dims={dict(ds.dims)}"
            )
            _emit_checkpoint(params, "zarr_opened", {
                "variables": len(ds.data_vars), "dims": dict(ds.dims),
            })

            # Build optimized encoding
            target_chunks, encoding = _build_zarr_encoding(
                ds, spatial_chunk_size, time_chunk_size,
                compressor_name, compression_level,
                zarr_format=zarr_format,
            )

            # Rechunk in-memory
            ds = ds.chunk(target_chunks)
            logger.info(
                f"ingest_zarr_rechunk: Rechunked dataset: target_chunks={target_chunks}"
            )
            _emit_checkpoint(params, "rechunk_applied", {
                "target_chunks": target_chunks, "compressor": compressor_name,
            })

            # Clear inherited v2 encoding (e.g. numcodecs.Blosc) to prevent
            # codec type mismatch when writing as zarr_format=3.
            # Only clear data variables — coordinate encoding (dtype, calendar)
            # should be preserved.
            for var in ds.data_vars:
                ds[var].encoding.clear()

            # dry_run gate: return plan without writing to silver
            if dry_run:
                elapsed = time.time() - start
                logger.info(
                    "ingest_zarr_rechunk: [DRY-RUN] would rechunk %d vars to "
                    "chunks=%s, compressor=%s (%0.1fs)",
                    len(ds.data_vars), target_chunks, compressor_name, elapsed,
                )
                return {
                    "success": True,
                    "result": {
                        "rechunked": False,
                        "zarr_store_url": mount_path,
                        "target_chunks": target_chunks,
                        "compressor": compressor_name,
                        "compression_level": compression_level,
                        "target_container": target_container,
                        "target_prefix": target_prefix,
                        "dry_run": True,
                    },
                }

            # Write to silver-zarr
            silver_repo = BlobRepository.for_zone("silver")
            target_az_url = f"az://{target_container}/{target_prefix}"
            target_storage_options = {
                "account_name": silver_repo.account_name,
                "credential": silver_repo.credential,
            }

            # Pre-cleanup: delete existing blobs at target prefix to prevent
            # orphan metadata when format/chunking changes
            cleanup = silver_repo.delete_blobs_by_prefix(target_container, target_prefix)
            if cleanup["deleted_count"] > 0:
                logger.info(
                    f"ingest_zarr_rechunk: pre-cleanup deleted {cleanup['deleted_count']} "
                    f"existing blobs under {target_container}/{target_prefix}"
                )
            _emit_checkpoint(params, "pre_cleanup_done", {
                "deleted_count": cleanup["deleted_count"],
            })

            # Estimate chunk count for logging
            import math
            n_chunks = 0
            for var_name in ds.data_vars:
                var = ds[var_name]
                chunks_per_var = 1
                for dim in var.dims:
                    dim_size = ds.dims[dim]
                    chunk_size = target_chunks.get(dim, dim_size)
                    chunks_per_var *= math.ceil(dim_size / chunk_size)
                n_chunks += chunks_per_var

            logger.info(
                f"ingest_zarr_rechunk: Writing {len(ds.data_vars)} variables, "
                f"estimated {n_chunks} chunks to {target_az_url}"
            )
            _emit_checkpoint(params, "zarr_write_started", {
                "target_url": target_az_url, "zarr_format": zarr_format,
            })

            write_start = time.time()
            ds.to_zarr(
                target_az_url,
                mode="w",
                consolidated=True,
                storage_options=target_storage_options,
                encoding=encoding,
                zarr_format=zarr_format,
            )

            # ZARR_NOTES.md §11: xarray's consolidated=True writes an empty
            # metadata block for Zarr v3 — explicit consolidation is mandatory
            if zarr_format == 3:
                import zarr
                consolidate_store = zarr.storage.FsspecStore.from_url(
                    target_az_url, storage_options=target_storage_options,
                )
                zarr.consolidate_metadata(consolidate_store)
                logger.info("ingest_zarr_rechunk: Consolidated metadata (Zarr v3)")

            write_elapsed = time.time() - write_start

            logger.info(
                f"ingest_zarr_rechunk: Zarr write complete ({write_elapsed:.1f}s)"
            )
            _emit_checkpoint(params, "zarr_write_complete", {
                "write_seconds": round(write_elapsed, 1), "target_chunks": target_chunks,
            })
        finally:
            ds.close()

        elapsed = time.time() - start
        logger.info(
            f"ingest_zarr_rechunk: Completed rechunk to "
            f"{target_container}/{target_prefix}, "
            f"chunks={target_chunks}, compressor={compressor_name} ({elapsed:.1f}s)"
        )

        return {
            "success": True,
            "result": {
                "rechunked": True,
                "zarr_store_url": f"abfs://{target_container}/{target_prefix}",
                "target_chunks": target_chunks,
                "compressor": compressor_name,
                "compression_level": compression_level,
                "target_container": target_container,
                "target_prefix": target_prefix,
            },
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"ingest_zarr_rechunk failed: {e} ({elapsed:.1f}s)")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }
