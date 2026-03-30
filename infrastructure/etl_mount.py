# ============================================================================
# CLAUDE CONTEXT - ETL MOUNT UTILITIES
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.9)
# STATUS: Infrastructure utility — mount path management for ETL workflows
# PURPOSE: Centralize mount path resolution, directory management, cleanup,
#          and blob-to-mount download. Single file for all mount conventions.
# LAST_REVIEWED: 27 MAR 2026
# EXPORTS: resolve_run_dir, ensure_dir, cleanup_run, list_files,
#          validate_path, download_blob_to_mount, download_prefix_to_mount
# DEPENDENCIES: config, infrastructure.blob
# ============================================================================
"""
ETL Mount Utilities.

Thin module-level functions for managing the Docker ETL mount filesystem
used by DAG workflow handlers. Centralizes path resolution, directory
lifecycle, path validation, and blob-to-mount streaming that was previously
duplicated across individual handlers.

Mount layout::

    {etl_mount_path}/
        {run_id}/
            blob_name_a.tif
            subdir/blob_name_b.nc
            ...

Usage::

    from infrastructure.etl_mount import resolve_run_dir, ensure_dir, download_blob_to_mount

    run_dir = resolve_run_dir(run_id)
    work_dir = ensure_dir(run_dir, "output")
    local_path = download_blob_to_mount(blob_repo, "bronze-raster", "tiles/flood.tif", run_dir)
"""

import glob as _glob
import logging
import os
import shutil
from typing import List

logger = logging.getLogger(__name__)

_DEFAULT_MOUNT_ROOT = "/mnt/etl"

# Cloud URL schemes recognised by the Zarr passthrough path.
# download_to_mount returns abfs:// URLs for native Zarr inputs;
# downstream handlers use this check to add storage_options.
_CLOUD_SCHEMES = ("abfs://", "az://")


def is_cloud_source(path: str) -> bool:
    """
    Return True if *path* is a cloud blob URL rather than a local mount path.

    Native Zarr inputs bypass the mount download — ``download_to_mount``
    returns the ``abfs://`` cloud URL as ``mount_path``.  All handlers
    that accept ``mount_path`` should use this function to decide whether
    ``storage_options`` are needed for ``xr.open_zarr``.

    Centralised here so the URL-scheme check lives in exactly one place.
    """
    return path.startswith(_CLOUD_SCHEMES) if path else False


# =============================================================================
# 1. resolve_run_dir
# =============================================================================

def resolve_run_dir(run_id: str) -> str:
    """
    Build the run-scoped directory path on the ETL mount.

    Reads the mount root from ``get_config().docker.etl_mount_path``,
    falling back to ``/mnt/etl`` when config is unavailable or the
    attribute is not set.

    Does NOT create the directory — use :func:`ensure_dir` for that.

    Args:
        run_id: DAG run identifier (typically a UUID or short hash).

    Returns:
        Absolute path ``{mount_root}/{run_id}``.
    """
    mount_root = _DEFAULT_MOUNT_ROOT
    try:
        from config import get_config
        cfg = get_config()
        if cfg.docker and cfg.docker.etl_mount_path:
            mount_root = cfg.docker.etl_mount_path
    except Exception:
        # Config not available (e.g. unit tests) — use default
        pass
    return os.path.join(mount_root, run_id)


# =============================================================================
# 2. ensure_dir
# =============================================================================

def ensure_dir(base: str, *subdirs: str) -> str:
    """
    Join *base* with optional *subdirs* and create the directory tree.

    Args:
        base: Root directory path.
        *subdirs: Additional path segments to append.

    Returns:
        The resulting absolute path (created on disk).
    """
    path = os.path.join(base, *subdirs)
    os.makedirs(path, exist_ok=True)
    return path


# =============================================================================
# 3. cleanup_run
# =============================================================================

def cleanup_run(run_id: str) -> dict:
    """
    Remove the run-scoped directory and all its contents.

    Args:
        run_id: DAG run identifier whose directory should be cleaned.

    Returns:
        Dict with cleanup summary::

            {"cleaned": True, "path": "...", "files_removed": N, "bytes_freed": N}

        or if the directory did not exist::

            {"cleaned": False, "reason": "not found"}
    """
    path = resolve_run_dir(run_id)

    if not os.path.exists(path):
        return {"cleaned": False, "reason": "not found"}

    # Tally files and bytes before removal
    file_count = 0
    total_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                total_bytes += os.path.getsize(fpath)
            except OSError:
                pass
            file_count += 1

    shutil.rmtree(path, ignore_errors=True)

    logger.info(
        "cleanup_run: removed %s — %d files, %.1f MB freed",
        path, file_count, total_bytes / (1024 * 1024),
    )

    return {
        "cleaned": True,
        "path": path,
        "files_removed": file_count,
        "bytes_freed": total_bytes,
    }


# =============================================================================
# 4. list_files
# =============================================================================

def list_files(directory: str, pattern: str = "*") -> List[str]:
    """
    List files matching *pattern* inside *directory*.

    Args:
        directory: Directory to search.
        pattern: Glob pattern (default ``"*"``).

    Returns:
        Sorted list of absolute file paths.  Empty list if *directory*
        does not exist.
    """
    if not os.path.isdir(directory):
        return []
    return sorted(_glob.glob(os.path.join(directory, pattern)))


# =============================================================================
# 5. validate_path
# =============================================================================

def validate_path(blob_name: str) -> str:
    """
    Sanitize and validate a blob name before using it as a local path segment.

    Rejects names that contain ``..`` path components or start with ``/``
    to prevent path-traversal attacks.

    Args:
        blob_name: The blob name / relative path to validate.

    Returns:
        The sanitized name (leading whitespace stripped).

    Raises:
        ValueError: If the name is unsafe.
    """
    sanitized = blob_name.lstrip(" \t")

    if sanitized.startswith("/"):
        raise ValueError(
            f"blob_name must not start with '/': '{blob_name}'"
        )

    if ".." in sanitized.split("/"):
        raise ValueError(
            f"blob_name must not contain '..' path component: '{blob_name}'"
        )

    return sanitized


# =============================================================================
# 6. download_blob_to_mount
# =============================================================================

def download_blob_to_mount(
    blob_repo,
    container: str,
    blob_name: str,
    mount_dir: str,
) -> str:
    """
    Stream a single blob to the local mount, preserving its relative path.

    Uses :meth:`BlobRepository.stream_blob_to_mount` for memory-efficient
    chunked transfer (no full-file memory spike).

    Args:
        blob_repo: A :class:`~infrastructure.blob.BlobRepository` instance.
        container: Azure Blob container name.
        blob_name: Blob path within the container.
        mount_dir: Local mount directory to write into.

    Returns:
        Absolute path of the downloaded file on disk.

    Raises:
        ValueError: If *blob_name* fails path validation.
    """
    safe_name = validate_path(blob_name)
    local_path = os.path.join(mount_dir, safe_name)

    # Ensure parent directories exist (blob_name may contain subdirectories)
    ensure_dir(os.path.dirname(local_path))

    logger.debug(
        "download_blob_to_mount: %s/%s -> %s", container, safe_name, local_path,
    )

    blob_repo.stream_blob_to_mount(
        container,
        safe_name,
        local_path,
        chunk_size_mb=32,
    )

    return local_path


# =============================================================================
# 7. download_prefix_to_mount
# =============================================================================

def download_prefix_to_mount(
    blob_repo,
    container: str,
    prefix: str,
    mount_dir: str,
) -> dict:
    """
    Download all blobs under *prefix* to the local mount.

    Lists blobs via :meth:`BlobRepository.list_blobs` then streams each
    one through :func:`download_blob_to_mount`.  Blob paths are made
    relative to *prefix* so the mount directory mirrors the blob subtree.

    Args:
        blob_repo: A :class:`~infrastructure.blob.BlobRepository` instance.
        container: Azure Blob container name.
        prefix: Blob name prefix to enumerate.
        mount_dir: Local mount directory to write into.

    Returns:
        Dict summary::

            {"mount_path": "...", "file_count": N, "total_bytes": N}
    """
    blobs = blob_repo.list_blobs(container, prefix=prefix)

    file_count = 0
    total_bytes = 0

    # Derive the directory portion of the prefix for stripping.
    # For directory prefixes like "data/zarr/" → strip "data/zarr/"
    # For file prefixes like "data/file.nc" → strip "data/" (parent dir)
    # This ensures files land directly in mount_dir (no extra nesting).
    if prefix:
        # Check if prefix looks like a single file (has extension in last segment)
        last_segment = prefix.rstrip("/").rsplit("/", 1)[-1]
        # .zarr is a directory store, not a single file — treat as directory prefix
        is_directory_store = last_segment.endswith(".zarr")
        if "." in last_segment and not is_directory_store:
            # File prefix — strip up to parent directory
            parent = prefix.rsplit("/", 1)[0] + "/" if "/" in prefix else ""
            strip_prefix = parent
        else:
            strip_prefix = prefix.rstrip("/") + "/"
    else:
        strip_prefix = ""

    # Build a set of all blob names for directory-marker detection.
    # Azure Blob Storage creates 0-byte blobs as directory markers
    # (e.g. "lat" alongside "lat/.zarray", "lat/c/0"). Downloading these
    # as files blocks subsequent makedirs for the real subdirectory tree.
    blob_names = {b["name"] for b in blobs}

    for blob_meta in blobs:
        blob_name = blob_meta["name"]
        blob_size = blob_meta.get("size", 0)

        # Derive relative path under the prefix
        if strip_prefix and blob_name.startswith(strip_prefix):
            relative = blob_name[len(strip_prefix):]
        else:
            relative = blob_name

        if not relative:
            # Skip the prefix "directory" marker itself
            continue

        # Skip 0-byte directory marker blobs — any blob that is a prefix
        # of another blob (i.e. "lat" when "lat/.zarray" also exists).
        if blob_size == 0 and any(
            n.startswith(blob_name + "/") for n in blob_names
        ):
            continue

        # Write using relative path (not full blob_name) so files land
        # directly in mount_dir without replicating the blob prefix structure.
        safe_name = validate_path(relative)
        local_path = os.path.join(mount_dir, safe_name)
        ensure_dir(os.path.dirname(local_path))

        blob_repo.stream_blob_to_mount(
            container, blob_name, local_path, chunk_size_mb=32,
        )

        try:
            total_bytes += os.path.getsize(local_path)
        except OSError:
            pass
        file_count += 1

    logger.info(
        "download_prefix_to_mount: %s/%s -> %s — %d files, %.1f MB",
        container, prefix, mount_dir, file_count, total_bytes / (1024 * 1024),
    )

    return {
        "mount_path": mount_dir,
        "file_count": file_count,
        "total_bytes": total_bytes,
    }
