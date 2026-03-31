# ============================================================================
# CLAUDE CONTEXT - ZARR DOWNLOAD TO MOUNT HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9 unified zarr ingest)
# STATUS: Atomic handler - Source acquisition (download or passthrough)
# PURPOSE: First node in unified zarr ingest — downloads NC to mount,
#          passes through cloud URL for native Zarr (no mount copy)
# LAST_REVIEWED: 30 MAR 2026
# EXPORTS: zarr_download_to_mount
# DEPENDENCIES: infrastructure.etl_mount, infrastructure.blob
# ============================================================================
"""
Zarr Download to Mount — source acquisition for unified zarr ingest.

**NetCDF inputs**: Parses ``abfs://`` URL into container + prefix, then
streams blobs to a run-scoped ``source/`` directory on the Docker ETL mount.
NetCDF is not cloud-native, so local copy is required for ``open_mfdataset``.

**Native Zarr inputs** (``.zarr`` suffix): Bypasses mount download entirely.
Zarr is a cloud-native format designed for direct remote reads — copying
hundreds of chunk files to a fileshare is wasteful and error-prone. Returns
the ``abfs://`` cloud URL as ``mount_path`` so downstream handlers
(``validate``, ``rechunk``, ``generate_pyramid``) read directly from blob.
"""

import time
from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_download_to_mount")


def zarr_download_to_mount(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Download source data (NetCDF or Zarr) from bronze blob to ETL mount.

    Params:
        source_url (str): abfs:// URL to source (e.g. ``abfs://wargames/good-data``)
        source_account (str): Storage account name (for BlobRepository)
        _run_id (str): System-injected DAG run ID
        dry_run (bool): If True, list blobs but don't download (default True)

    Returns:
        On success::

            {"success": True, "mount_path": "...", "file_count": N, "total_bytes": N}

        On dry_run success::

            {"success": True, "dry_run": True, "file_count": N, "total_bytes": N,
             "container": "...", "prefix": "..."}

        On failure::

            {"success": False, "error": "...", "error_type": "ValidationError"|...}
    """
    start = time.time()

    # ------------------------------------------------------------------
    # 1. Extract and validate parameters
    # ------------------------------------------------------------------
    source_url = params.get("source_url")
    source_account = params.get("source_account")
    run_id = params.get("_run_id")
    dry_run = params.get("dry_run", True)

    missing = []
    if not source_url:
        missing.append("source_url")
    if not source_account:
        missing.append("source_account")
    if not run_id:
        missing.append("_run_id")

    if missing:
        return {
            "success": False,
            "error": f"Missing required parameter(s): {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    # ------------------------------------------------------------------
    # 2. Parse container and prefix from abfs:// URL
    # ------------------------------------------------------------------
    # abfs:// is the ONLY accepted scheme. Reject https://, wasbs://, az://,
    # or bare paths explicitly — they indicate a misconfigured submission.
    if not source_url.startswith("abfs://"):
        return {
            "success": False,
            "error": (
                f"source_url must use abfs:// scheme, got: {source_url}. "
                f"https://, wasbs://, and other schemes are not supported."
            ),
            "error_type": "ValidationError",
            "retryable": False,
        }

    stripped = source_url[len("abfs://"):].strip("/")

    parts = stripped.split("/", 1)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return {
            "success": False,
            "error": f"source_url must be abfs://{{container}}/{{prefix}}, got: {source_url}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    container = parts[0]
    prefix = parts[1]

    # ------------------------------------------------------------------
    # 2a. Validate source format — only .zarr and .nc/.nc4/.netcdf supported
    # ------------------------------------------------------------------
    # Reject unsupported formats at the gate, not after downloading.
    # HDF5, GRIB, and other multidimensional formats are not supported
    # by this pipeline even though xarray can read them.
    last_segment = prefix.rstrip("/").rsplit("/", 1)[-1]
    supported_extensions = (".zarr", ".nc", ".nc4", ".netcdf")
    has_extension = "." in last_segment
    if has_extension and not any(last_segment.endswith(ext) for ext in supported_extensions):
        return {
            "success": False,
            "error": (
                f"Unsupported source format: '{last_segment}'. "
                f"Only .zarr and .nc/.nc4/.netcdf are supported by ingest_zarr. "
                f"Got: {source_url}"
            ),
            "error_type": "ValidationError",
            "retryable": False,
        }

    logger.info(
        "zarr_download_to_mount: container=%s prefix=%s run_id=%s dry_run=%s",
        container, prefix, run_id, dry_run,
    )

    # ------------------------------------------------------------------
    # 2b. Native Zarr bypass — skip mount download entirely
    # ------------------------------------------------------------------
    # Zarr is cloud-native: xarray can read directly from blob storage
    # via storage_options. Downloading hundreds of chunk files to a
    # fileshare is slow, wastes disk, and causes [Errno 17] on retries.
    # Return the cloud URL as "mount_path" — downstream handlers detect
    # the abfs:// scheme and add storage_options accordingly.
    if prefix.rstrip("/").endswith(".zarr"):
        elapsed = time.time() - start
        cloud_url = source_url if source_url.startswith("abfs://") else f"abfs://{container}/{prefix}"
        logger.info(
            "zarr_download_to_mount: native Zarr detected — bypassing mount download, "
            "returning cloud URL: %s (dry_run=%s, %0.1fs)",
            cloud_url, dry_run, elapsed,
        )
        return {
            "success": True,
            "mount_path": cloud_url,  # downstream reads directly from blob
            "file_count": 0,
            "total_bytes": 0,
            "zarr_passthrough": True,
            "dry_run": dry_run,
        }

    try:
        from infrastructure.blob import BlobRepository
        from infrastructure.etl_mount import (
            download_prefix_to_mount,
            ensure_dir,
            resolve_run_dir,
        )

        # ------------------------------------------------------------------
        # 3. Resolve mount directory (overwrite if exists — ephemeral data)
        # ------------------------------------------------------------------
        import shutil
        import os
        run_dir = resolve_run_dir(run_id)
        if os.path.exists(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)
            logger.info("zarr_download_to_mount: cleared stale mount dir %s", run_dir)
        source_dir = ensure_dir(run_dir, "source")

        # ------------------------------------------------------------------
        # 4. Get blob repository for bronze zone
        # ------------------------------------------------------------------
        blob_repo = BlobRepository.for_zone("bronze")

        # ------------------------------------------------------------------
        # 5. Dry run — list only
        # ------------------------------------------------------------------
        if dry_run:
            blobs = blob_repo.list_blobs(container, prefix=prefix)
            file_count = len(blobs)
            total_bytes = sum(b.get("size", 0) for b in blobs)

            elapsed = time.time() - start
            logger.info(
                "zarr_download_to_mount: dry_run — %d blobs, %.1f MB (%0.1fs)",
                file_count, total_bytes / (1024 * 1024), elapsed,
            )

            return {
                "success": True,
                "dry_run": True,
                "file_count": file_count,
                "total_bytes": total_bytes,
                "container": container,
                "prefix": prefix,
            }

        # ------------------------------------------------------------------
        # 6. Real download — stream blobs to mount
        # ------------------------------------------------------------------
        result = download_prefix_to_mount(blob_repo, container, prefix, source_dir)

        elapsed = time.time() - start
        logger.info(
            "zarr_download_to_mount: complete — %d files, %.1f MB -> %s (%0.1fs)",
            result["file_count"],
            result["total_bytes"] / (1024 * 1024),
            result["mount_path"],
            elapsed,
        )

        return {
            "success": True,
            "mount_path": result["mount_path"],
            "file_count": result["file_count"],
            "total_bytes": result["total_bytes"],
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.error("zarr_download_to_mount failed: %s (%0.1fs)", e, elapsed)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "retryable": True,  # Download/mount errors are typically transient
        }
