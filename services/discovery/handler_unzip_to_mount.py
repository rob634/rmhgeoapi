# ============================================================================
# CLAUDE CONTEXT - UNZIP TO MOUNT HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Atomic handler - Download ZIP from blob and extract to mount
# PURPOSE: Download a ZIP archive from blob storage, extract to the ETL mount,
#          return a content listing for downstream classification.
# CREATED: 03 APR 2026
# EXPORTS: unzip_to_mount
# DEPENDENCIES: infrastructure.blob.BlobRepository, infrastructure.etl_mount
# ============================================================================
"""
Unzip To Mount -- download ZIP from blob storage and extract to ETL mount.

Safety limits enforced:
  - Max extracted size (DISCOVERY_MAX_EXTRACT_SIZE_MB env var)
  - Max file count inside ZIP (default 100)
  - ZIP bomb detection (extracted > 10x compressed size)
"""

import logging
import os
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_EXTRACT_SIZE_MB = 2048
DEFAULT_MAX_FILE_COUNT = 100
ZIP_BOMB_RATIO = 10


def unzip_to_mount(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Download a ZIP from blob storage and extract to mount.

    Params:
        container_name (str, required): Target container (for BlobRepository zone).
        blob_name (str, required): ZIP blob path.
        source_container (str, optional): Container to download from. Defaults to container_name.
        _run_id (str, system-injected): DAG run ID for mount path scoping.

    Returns:
        Success: {"success": True, "result": {"extract_path": "...", "contents": [...], ...}}
    """
    container_name = params.get("container_name")
    blob_name = params.get("blob_name")
    source_container = params.get("source_container") or container_name
    run_id = params.get("_run_id", "unknown")

    if not container_name:
        return {"success": False, "error": "container_name is required",
                "error_type": "ValidationError", "retryable": False}
    if not blob_name:
        return {"success": False, "error": "blob_name is required",
                "error_type": "ValidationError", "retryable": False}

    stem = PurePosixPath(blob_name).stem

    # Resolve mount paths
    from infrastructure.etl_mount import resolve_run_dir, ensure_dir
    run_dir = resolve_run_dir(run_id)
    extract_dir = ensure_dir(run_dir, stem)
    zip_path = os.path.join(run_dir, f"{stem}.zip")

    # Read safety limits from env
    max_extract_mb = int(os.environ.get(
        "DISCOVERY_MAX_EXTRACT_SIZE_MB", DEFAULT_MAX_EXTRACT_SIZE_MB
    ))
    max_file_count = int(os.environ.get(
        "DISCOVERY_MAX_FILE_COUNT", DEFAULT_MAX_FILE_COUNT
    ))

    # Download ZIP from blob
    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.for_zone("bronze")

    try:
        blob_repo.download_blob_to_file(source_container, blob_name, zip_path)
    except Exception as exc:
        return {"success": False, "error": f"Failed to download ZIP: {exc}",
                "error_type": "DownloadError", "retryable": True}

    compressed_size = os.path.getsize(zip_path)

    # Extract and validate
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()

            # Safety: file count limit
            if len(members) > max_file_count:
                return {
                    "success": False,
                    "error": f"ZIP contains {len(members)} files, exceeds limit of {max_file_count}",
                    "error_type": "SafetyLimitExceeded", "retryable": False,
                }

            # Safety: total extracted size
            total_uncompressed = sum(m.file_size for m in members)
            max_extract_bytes = max_extract_mb * 1024 * 1024

            if total_uncompressed > max_extract_bytes:
                return {
                    "success": False,
                    "error": (
                        f"Extracted size {total_uncompressed / (1024*1024):.0f} MB "
                        f"exceeds limit of {max_extract_mb} MB"
                    ),
                    "error_type": "SafetyLimitExceeded", "retryable": False,
                }

            # Safety: ZIP bomb detection
            if compressed_size > 0 and total_uncompressed > compressed_size * ZIP_BOMB_RATIO:
                return {
                    "success": False,
                    "error": (
                        f"ZIP bomb detected: {total_uncompressed / (1024*1024):.0f} MB extracted "
                        f"from {compressed_size / (1024*1024):.0f} MB compressed "
                        f"(ratio {total_uncompressed / compressed_size:.1f}x, limit {ZIP_BOMB_RATIO}x)"
                    ),
                    "error_type": "ZipBombDetected", "retryable": False,
                }

            # Extract all
            zf.extractall(extract_dir)

    except zipfile.BadZipFile as exc:
        return {"success": False, "error": f"Corrupt ZIP file: {exc}",
                "error_type": "CorruptArchive", "retryable": False}

    # Build content listing from extracted files
    contents = []
    total_extracted = 0

    for root, _dirs, files in os.walk(extract_dir):
        for fname in files:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, extract_dir)
            size = os.path.getsize(full_path)
            ext = PurePosixPath(fname).suffix.lower()

            contents.append({
                "relative_path": rel_path,
                "size_bytes": size,
                "extension": ext,
            })
            total_extracted += size

    # Clean up the ZIP file (keep extracted contents)
    try:
        os.remove(zip_path)
    except OSError:
        pass

    logger.info(
        "unzip_to_mount: %s — %d files extracted to %s (%.1f MB)",
        blob_name, len(contents), extract_dir, total_extracted / (1024 * 1024),
    )

    return {
        "success": True,
        "result": {
            "extract_path": extract_dir,
            "contents": contents,
            "total_extracted_size_bytes": total_extracted,
            "compressed_size_bytes": compressed_size,
            "file_count": len(contents),
        },
    }
