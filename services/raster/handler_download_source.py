# ============================================================================
# CLAUDE CONTEXT - RASTER DOWNLOAD SOURCE ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Stream raster blob from bronze to ETL mount
# PURPOSE: Stream a single blob from Azure Blob Storage (bronze zone) to the
#          Docker ETL mount, producing a local file path for downstream handlers.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_download_source
# DEPENDENCIES: infrastructure.blob, config
# ============================================================================
"""
Raster Download Source — atomic handler for DAG workflows.

Streams a source raster file from Azure Blob Storage (bronze zone) to the
ETL mount under a run-scoped subdirectory, returning the local path and
transfer metrics for downstream handlers.

This is an architecturally new handler with no direct monolith equivalent.
The monolith (handler_process_raster_complete.py) operated on blob URLs via
VSI paths or held bytes in memory; this handler streams to disk on the Docker
ETL mount so GDAL-based downstream handlers can read local files.

Implemented behaviours (from build spec 2026-03-20):
  D-B1  Create {etl_mount_path}/{_run_id}/ subdirectory for namespace isolation
  D-B2  Stream blob bytes from bronze storage to local file (via BlobRepository)
  D-B3  Return file_size_bytes metric for downstream logging/metrics
  D-N1  Path traversal guard: reject blob_name containing '..' or starting '/'
  D-N2  ETL mount existence check before write (writability probe)
  D-N3  Idempotent directory creation via os.makedirs(exist_ok=True)
"""

import logging
import os
import time
import traceback
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# HANDLER ENTRY POINT
# =============================================================================

def raster_download_source(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Stream a raster blob from bronze storage to the Docker ETL mount.

    Params:
        container_name (str, required): Azure blob container holding the source raster.
        blob_name (str, required): Blob path within the container.
        _run_id (str, required): System-injected DAG run identifier used to create
            an isolated subdirectory on the mount (namespace isolation).
        _node_name (str, required): System-injected DAG node name (for log prefix).
        etl_mount_path (str, optional): Override for the ETL mount root. Defaults
            to config.docker.etl_mount_path. Not normally supplied by callers.

    Returns:
        Success::

            {
                "success": True,
                "result": {
                    "source_path": "/mnt/etl/{_run_id}/{blob_name}",
                    "file_size_bytes": int,
                    "transfer_duration_seconds": float,
                    "content_type": str | None
                }
            }

        Failure::

            {
                "success": False,
                "error": "...",
                "error_type": "...",
                "retryable": bool
            }
    """
    # -------------------------------------------------------------------------
    # PARAM VALIDATION (fail immediately, no I/O)
    # -------------------------------------------------------------------------
    _run_id = params.get('_run_id')
    if not _run_id:
        return {
            "success": False,
            "error": "_run_id is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    _node_name = params.get('_node_name')
    if not _node_name:
        return {
            "success": False,
            "error": "_node_name is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    container_name = params.get('container_name')
    if not container_name:
        return {
            "success": False,
            "error": "container_name is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    blob_name = params.get('blob_name')
    if not blob_name:
        return {
            "success": False,
            "error": "blob_name is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    # D-N1: Path traversal guard — blob_name must not start with '/' or contain '..'
    if blob_name.startswith('/'):
        return {
            "success": False,
            "error": f"blob_name must not start with '/': '{blob_name}'",
            "error_type": "InvalidParameterError",
            "retryable": False,
        }
    if '..' in blob_name.split('/'):
        return {
            "success": False,
            "error": f"blob_name must not contain '..': '{blob_name}'",
            "error_type": "InvalidParameterError",
            "retryable": False,
        }

    log_prefix = f"[{_run_id[:8]}][{_node_name}]"
    logger.info(f"{log_prefix} raster_download_source starting: {container_name}/{blob_name}")

    try:
        # ---------------------------------------------------------------------
        # Resolve ETL mount root
        # Callers may pass etl_mount_path for testing; otherwise read from config.
        # ---------------------------------------------------------------------
        etl_mount_path = params.get('etl_mount_path')
        if not etl_mount_path:
            from config import get_config
            _config = get_config()
            if not (_config.docker and _config.docker.etl_mount_path):
                return {
                    "success": False,
                    "error": "config.docker.etl_mount_path is not configured",
                    "error_type": "MountUnavailableError",
                    "retryable": True,
                }
            etl_mount_path = _config.docker.etl_mount_path

        # D-B1 / D-N3: Create run-scoped subdirectory (idempotent)
        run_dir = os.path.join(etl_mount_path, _run_id)
        try:
            os.makedirs(run_dir, exist_ok=True)
        except Exception as mkdir_err:
            return {
                "success": False,
                "error": f"Failed to create run directory '{run_dir}': {mkdir_err}",
                "error_type": "MountUnavailableError",
                "retryable": True,
            }

        # D-N2: Writability probe — detect mount-level permission/availability issues
        probe_path = os.path.join(run_dir, ".write-test")
        try:
            with open(probe_path, "w") as fh:
                fh.write("ok")
            os.remove(probe_path)
        except Exception as probe_err:
            return {
                "success": False,
                "error": f"ETL mount at '{run_dir}' is not writable: {probe_err}",
                "error_type": "MountUnavailableError",
                "retryable": True,
            }

        # ---------------------------------------------------------------------
        # D-B2: Stream blob from bronze storage to mount
        # Destination path mirrors the blob_name basename under the run directory.
        # Using basename preserves the filename for GDAL driver auto-detection
        # while avoiding nested subdirectory creation from deep blob paths.
        # ---------------------------------------------------------------------
        from infrastructure.blob import BlobRepository
        from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

        blob_repo = BlobRepository.for_zone("bronze")
        # Prefix with run_id[:8] to prevent collisions when deep blob paths
        # share the same filename (e.g., region-a/flood.tif and region-b/flood.tif)
        dest_filename = f"{run_id[:8]}_{os.path.basename(blob_name)}"
        dest_path = os.path.join(run_dir, dest_filename)

        logger.info(f"{log_prefix} Streaming {blob_name} -> {dest_path}")

        transfer_start = time.monotonic()
        try:
            transfer_result = blob_repo.stream_blob_to_mount(
                container_name,
                blob_name,
                dest_path,
                chunk_size_mb=32,
            )
        except ResourceNotFoundError:
            return {
                "success": False,
                "error": f"Blob not found: {container_name}/{blob_name}",
                "error_type": "BlobNotFoundError",
                "retryable": True,
            }
        except HttpResponseError as auth_err:
            if auth_err.status_code in (401, 403):
                return {
                    "success": False,
                    "error": f"Storage auth failure for {container_name}/{blob_name}: {auth_err}",
                    "error_type": "StorageAuthError",
                    "retryable": True,
                }
            return {
                "success": False,
                "error": f"Storage HTTP error for {container_name}/{blob_name}: {auth_err}",
                "error_type": "BlobStreamError",
                "retryable": True,
            }
        except OSError as disk_err:
            return {
                "success": False,
                "error": f"Disk write failure streaming '{blob_name}' to '{dest_path}': {disk_err}",
                "error_type": "DiskSpaceError",
                "retryable": True,
            }

        transfer_duration = time.monotonic() - transfer_start

        # D-B3: File size from disk (authoritative — avoids trusting transfer_result)
        file_size_bytes = os.path.getsize(dest_path)
        size_mb = file_size_bytes / (1024 * 1024)

        # Extract content_type from transfer result if the blob repo populated it
        content_type = transfer_result.get('content_type') if isinstance(transfer_result, dict) else None

        logger.info(
            f"{log_prefix} raster_download_source complete: "
            f"{size_mb:.1f} MB in {transfer_duration:.1f}s -> {dest_path}"
        )

        return {
            "success": True,
            "result": {
                "source_path": dest_path,
                "file_size_bytes": file_size_bytes,
                "transfer_duration_seconds": round(transfer_duration, 3),
                "content_type": content_type,
            },
        }

    except Exception as exc:
        return {
            "success": False,
            "error": (
                f"Unexpected error in raster_download_source: {exc}\n"
                f"{traceback.format_exc()}"
            ),
            "error_type": "HandlerError",
            "retryable": False,
        }
