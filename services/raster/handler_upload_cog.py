# ============================================================================
# CLAUDE CONTEXT - RASTER UPLOAD COG ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Upload COG from ETL mount to silver blob storage
# PURPOSE: Verify COG exists in silver, generate deterministic identifiers,
#          clean up mount files, return blob coordinates for downstream handlers.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_upload_cog
# DEPENDENCIES: infrastructure.blob (BlobRepository)
# ============================================================================
"""
Raster Upload COG — atomic handler for DAG workflows.

Uploads a COG file from the ETL mount to silver blob storage using
stream_mount_to_blob (memory-efficient, chunked streaming). Generates
deterministic stac_item_id and cog_url. Cleans up mount files after a
successful upload. Returns blob coordinates for the persist_app_tables
and stac_materialize handlers downstream.

Extracted from: monolith handler_process_raster_complete.py
  - Upload: raster_cog.py (embedded inside create_cog, step 6, L1105-1139)
  - Post-upload verification: L1796-1813 (checkpoint validate_cog_exists)
  - stac_item_id derivation: L1849-1851

CRITICAL NOTES:
  - U-S1: safe_name is derived from the silver blob path (cog_path on silver),
    NOT from the original source blob_name. This must be consistent with what
    raster_persist_app_tables and stac_materialize_item expect.
  - U-S2: The handler constructs the silver blob path as:
      cogs/{collection_id}/{output_name}
    where output_name is either output_blob_name (if supplied) or the basename
    of blob_name. The create_cog handler appends a tier suffix; upload_cog
    receives cog_path already containing that suffix and uses its basename.
  - Mount cleanup is non-fatal: failure is logged as a warning and does not
    affect the success return value.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def raster_upload_cog(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Upload a COG from the ETL mount to silver blob storage.

    Params:
        cog_path       (str, required): Absolute path to the COG file on the ETL mount.
                                        Produced by raster_create_cog.
        source_path    (str, required): Absolute path to the original downloaded source
                                        file on the ETL mount. Produced by raster_download.
        container_name (str, required): Silver container name (e.g. "silver-cogs").
        blob_name      (str, required): Original source blob path (used to derive the
                                        silver output path when output_blob_name is absent).
        collection_id  (str, required): Collection identifier (e.g. "flood-analysis").
        output_blob_name (str, optional): Custom silver blob path. When absent the handler
                                          derives it from collection_id + blob_name basename.

    Returns (success):
        {
            "success": True,
            "result": {
                "stac_item_id": str,
                "silver_container": str,
                "silver_blob_path": str,
                "cog_url": str,
                "cog_size_bytes": int,
                "etag": str | None,
                "blob_version_id": str | None,
                "transfer_duration_seconds": float,
                "mount_cleanup": {
                    "source_deleted": bool,
                    "cog_deleted": bool,
                },
            },
        }

    Returns (failure):
        {
            "success": False,
            "error": str,
            "error_type": str,
            "retryable": bool,
        }
    """
    try:
        # ------------------------------------------------------------------
        # 1. Extract and validate required parameters
        # ------------------------------------------------------------------
        cog_path = params.get('cog_path')
        source_path = params.get('source_path')
        container_name = params.get('container_name')
        blob_name = params.get('blob_name')
        collection_id = params.get('collection_id')
        output_blob_name = params.get('output_blob_name')  # optional

        missing = []
        if not cog_path:
            missing.append('cog_path')
        if not source_path:
            missing.append('source_path')
        if not container_name:
            missing.append('container_name')
        if not blob_name:
            missing.append('blob_name')
        if not collection_id:
            missing.append('collection_id')

        if missing:
            return {
                "success": False,
                "error": f"Missing required parameters: {', '.join(missing)}",
                "error_type": "InvalidParameterError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 2. Validate COG file exists on mount and is non-empty
        # ------------------------------------------------------------------
        cog_path_obj = Path(cog_path)

        if not cog_path_obj.exists():
            logger.error("COG file not found on mount: %s", cog_path)
            return {
                "success": False,
                "error": f"COG file not found on mount: {cog_path}",
                "error_type": "FileNotFoundError",
                "retryable": False,
            }

        cog_size_bytes = cog_path_obj.stat().st_size
        if cog_size_bytes == 0:
            logger.error("COG file is 0 bytes: %s", cog_path)
            return {
                "success": False,
                "error": f"COG file is 0 bytes: {cog_path}",
                "error_type": "InvalidFileError",
                "retryable": False,
            }

        logger.info(
            "raster_upload_cog: COG validated on mount (%.2f MB): %s",
            cog_size_bytes / (1024 * 1024),
            cog_path,
        )

        # ------------------------------------------------------------------
        # 3. Derive the silver blob path
        #
        # Convention: cogs/{collection_id}/{output_name}
        #
        # output_name is taken from output_blob_name when supplied (it already
        # carries the tier suffix applied by create_cog). When absent, fall back
        # to the basename of cog_path (which create_cog wrote to the mount with
        # the tier suffix already appended).
        # ------------------------------------------------------------------
        if output_blob_name:
            # Caller explicitly provided the silver destination path.
            silver_blob_path = output_blob_name
        else:
            # Derive from the local COG file's basename so the tier suffix
            # (e.g. _analysis) is preserved exactly as create_cog produced it.
            cog_basename = cog_path_obj.name
            silver_blob_path = f"cogs/{collection_id}/{cog_basename}"

        logger.info("raster_upload_cog: silver_blob_path = %s", silver_blob_path)

        # ------------------------------------------------------------------
        # 4. Derive deterministic identifiers (U-B2, U-B3, U-S1)
        #
        # stac_item_id = "{collection_id}-{safe_name}"
        # safe_name    = silver_blob_path with '/' -> '-' and '.' -> '-'
        #
        # CRITICAL: safe_name input is the *silver blob path*, not blob_name.
        # This matches monolith L1850: `safe_name = cog_blob.replace('/', '-').replace('.', '-')`
        # ------------------------------------------------------------------
        from services.raster.identifiers import derive_stac_item_id
        stac_item_id = derive_stac_item_id(collection_id, silver_blob_path)

        # cog_url for GDAL /vsiaz/ access
        cog_url = f"/vsiaz/{container_name}/{silver_blob_path}"

        logger.info("raster_upload_cog: stac_item_id = %s", stac_item_id)
        logger.info("raster_upload_cog: cog_url = %s", cog_url)

        # ------------------------------------------------------------------
        # 5. Upload COG from mount to silver blob storage (U-B1, U-N3)
        #
        # stream_mount_to_blob reads the file in chunks — no full-file
        # memory load. Essential for large COGs on Docker workers.
        # ------------------------------------------------------------------
        try:
            from infrastructure.blob import BlobRepository
            silver_repo = BlobRepository.for_zone('silver')
        except Exception as auth_err:
            logger.error("Storage auth failed for silver zone: %s", auth_err)
            return {
                "success": False,
                "error": f"Storage auth failed for silver zone: {auth_err}",
                "error_type": "StorageAuthError",
                "retryable": True,
            }

        logger.info(
            "raster_upload_cog: uploading %s -> %s/%s",
            cog_path,
            container_name,
            silver_blob_path,
        )

        upload_start = time.time()
        try:
            upload_result = silver_repo.stream_mount_to_blob(
                container=container_name,
                blob_path=silver_blob_path,
                mount_path=cog_path,
                content_type='image/tiff',
                overwrite_existing=True,
            )
        except Exception as upload_err:
            logger.error("COG upload failed: %s", upload_err)
            return {
                "success": False,
                "error": f"COG upload failed: {upload_err}",
                "error_type": "UploadError",
                "retryable": True,
            }

        transfer_duration = time.time() - upload_start

        if not upload_result.get('success', False):
            upload_error = upload_result.get('error', 'unknown upload error')
            logger.error("stream_mount_to_blob returned failure: %s", upload_error)
            return {
                "success": False,
                "error": f"COG upload failed: {upload_error}",
                "error_type": "UploadError",
                "retryable": True,
            }

        etag = upload_result.get('etag')
        # stream_mount_to_blob does not return blob_version_id (Azure SDK upload_blob
        # response does not expose version_id via the streaming path). Set to None;
        # downstream handlers that need version_id should call get_blob_properties.
        blob_version_id = upload_result.get('blob_version_id')

        throughput_mbps = upload_result.get('throughput_mbps', 0.0)
        logger.info(
            "raster_upload_cog: upload complete (%.2f MB in %.1fs, %.1f MB/s, etag=%s)",
            cog_size_bytes / (1024 * 1024),
            transfer_duration,
            throughput_mbps,
            etag,
        )

        # ------------------------------------------------------------------
        # 6. Post-upload verification — confirm blob is present in silver (U-B4, U-N2)
        #
        # Guards against silent upload failures or Azure eventual-consistency
        # edge cases. Adapted from monolith checkpoint validate_cog_exists (L1796-1813).
        # ------------------------------------------------------------------
        try:
            blob_confirmed = silver_repo.blob_exists(container_name, silver_blob_path)
        except Exception as verify_err:
            logger.error(
                "Post-upload verification call raised exception: %s", verify_err
            )
            return {
                "success": False,
                "error": f"Post-upload verification failed: {verify_err}",
                "error_type": "UploadVerificationError",
                "retryable": True,
            }

        if not blob_confirmed:
            logger.error(
                "Post-upload verification failed: blob not found in %s/%s",
                container_name,
                silver_blob_path,
            )
            return {
                "success": False,
                "error": (
                    f"Post-upload verification failed: blob not found at "
                    f"{container_name}/{silver_blob_path}"
                ),
                "error_type": "UploadVerificationError",
                "retryable": True,
            }

        logger.info(
            "raster_upload_cog: blob confirmed in silver: %s/%s",
            container_name,
            silver_blob_path,
        )

        # ------------------------------------------------------------------
        # 7. Mount file cleanup — non-fatal (U-N1)
        #
        # Delete source_path and cog_path from the ETL mount. Failures are
        # logged as warnings and do not affect the handler's success return.
        # ------------------------------------------------------------------
        source_deleted = False
        cog_deleted = False

        try:
            os.remove(source_path)
            source_deleted = True
            logger.info("raster_upload_cog: removed source file from mount: %s", source_path)
        except Exception as cleanup_err:
            logger.warning(
                "raster_upload_cog: could not remove source file %s (non-fatal): %s",
                source_path,
                cleanup_err,
            )

        try:
            os.remove(cog_path)
            cog_deleted = True
            logger.info("raster_upload_cog: removed COG file from mount: %s", cog_path)
        except Exception as cleanup_err:
            logger.warning(
                "raster_upload_cog: could not remove COG file %s (non-fatal): %s",
                cog_path,
                cleanup_err,
            )

        # ------------------------------------------------------------------
        # 8. Return blob coordinates and transfer metrics
        # ------------------------------------------------------------------
        return {
            "success": True,
            "result": {
                "stac_item_id": stac_item_id,
                "silver_container": container_name,
                "silver_blob_path": silver_blob_path,
                "cog_url": cog_url,
                "cog_size_bytes": cog_size_bytes,
                "etag": etag,
                "blob_version_id": blob_version_id,
                "transfer_duration_seconds": round(transfer_duration, 2),
                "mount_cleanup": {
                    "source_deleted": source_deleted,
                    "cog_deleted": cog_deleted,
                },
            },
        }

    except Exception as exc:
        logger.exception("raster_upload_cog: unexpected error: %s", exc)
        return {
            "success": False,
            "error": f"Unexpected error in raster_upload_cog: {exc}",
            "error_type": type(exc).__name__,
            "retryable": False,
        }
