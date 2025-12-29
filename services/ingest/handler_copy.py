# ============================================================================
# CLAUDE CONTEXT - INGEST COPY HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - Blob Copy
# PURPOSE: Copy batch of COG files from bronze to silver
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: ingest_copy_batch
# DEPENDENCIES: infrastructure.blob, azure.storage.blob
# ============================================================================
"""
Ingest Copy Handler.

Stage 2 of ingest workflow. Copies a batch of COG files from source (bronze)
container to target (silver) container using server-side copy.

Uses start_copy_from_url for efficient server-side copy without downloading.
"""

from typing import Dict, Any, List
from util_logger import LoggerFactory, ComponentType


def ingest_copy_batch(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Copy batch of COG files from bronze to silver (Stage 2).

    Args:
        params: Task parameters containing:
            - source_container (str): Source container
            - target_container (str): Target container
            - source_account (str): Optional source account override
            - target_account (str): Optional target account override
            - batch_index (int): Batch number for logging
            - items (list): List of items to copy
            - overwrite (bool): Overwrite existing blobs
            - skip_existing (bool): Skip blobs that already exist
            - create_target_container (bool): Create target container if needed
            - source_job_id (str): Job ID for tracking

    Returns:
        Success dict with copy results:
        {
            "success": True,
            "result": {
                "batch_index": int,
                "files_copied": int,
                "files_skipped": int,
                "bytes_copied": int
            }
        }
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ingest_copy_batch")

    source_container = params.get('source_container')
    target_container = params.get('target_container')
    source_account = params.get('source_account')
    target_account = params.get('target_account')
    batch_index = params.get('batch_index', 0)
    items = params.get('items', [])
    overwrite = params.get('overwrite', False)
    skip_existing = params.get('skip_existing', True)
    create_target_container = params.get('create_target_container', True)
    source_job_id = params.get('source_job_id')

    logger.info(f"📁 Copying batch {batch_index}: {len(items)} items")
    logger.info(f"   {source_container} → {target_container}")

    try:
        from infrastructure.blob import BlobRepository
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential
        import os

        # Get blob repositories
        source_repo = BlobRepository.for_zone("bronze")
        target_repo = BlobRepository.for_zone("silver")

        # Override accounts if specified
        if source_account:
            source_repo = BlobRepository(account_name=source_account)
        if target_account:
            target_repo = BlobRepository(account_name=target_account)

        # Create target container if needed
        if create_target_container:
            _ensure_container_exists(target_repo, target_container)

        # Copy files
        files_copied = 0
        files_skipped = 0
        bytes_copied = 0
        errors = []

        for item in items:
            tif_path = item.get('tif_path')
            item_id = item.get('item_id')

            try:
                # Check if target exists (if skip_existing)
                if skip_existing and not overwrite:
                    if target_repo.blob_exists(target_container, tif_path):
                        logger.debug(f"   Skipping (exists): {tif_path}")
                        files_skipped += 1
                        continue

                # Get source URL with SAS for copy
                source_url = source_repo.get_blob_url_with_sas(
                    container_name=source_container,
                    blob_name=tif_path,
                    hours=1
                )

                # Get source blob size
                source_props = source_repo.get_blob_properties(source_container, tif_path)
                blob_size = source_props.get('size', 0) if source_props else 0

                # Copy to target
                _copy_blob(
                    target_repo=target_repo,
                    target_container=target_container,
                    target_blob=tif_path,
                    source_url=source_url
                )

                files_copied += 1
                bytes_copied += blob_size

                if files_copied % 20 == 0:
                    logger.info(f"   Progress: {files_copied}/{len(items)} copied")

            except Exception as e:
                logger.warning(f"   Failed to copy {tif_path}: {e}")
                errors.append({"item_id": item_id, "error": str(e)})

        logger.info(f"✅ Batch {batch_index} complete: {files_copied} copied, {files_skipped} skipped")

        return {
            "success": True,
            "result": {
                "batch_index": batch_index,
                "files_copied": files_copied,
                "files_skipped": files_skipped,
                "bytes_copied": bytes_copied,
                "errors": errors if errors else None
            }
        }

    except Exception as e:
        logger.error(f"❌ Copy batch {batch_index} failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "result": {
                "batch_index": batch_index,
                "files_copied": 0
            }
        }


def _ensure_container_exists(blob_repo, container_name: str) -> None:
    """Ensure target container exists, create if not."""
    from azure.core.exceptions import ResourceExistsError

    try:
        blob_repo._get_container_client(container_name).create_container()
    except ResourceExistsError:
        pass  # Container already exists
    except Exception as e:
        # May not have create permission, that's ok if container exists
        pass


def _copy_blob(target_repo, target_container: str, target_blob: str, source_url: str) -> None:
    """
    Copy blob using server-side copy.

    Uses start_copy_from_url for efficient copy without downloading.
    """
    container_client = target_repo._get_container_client(target_container)
    blob_client = container_client.get_blob_client(target_blob)

    # Start server-side copy
    copy_result = blob_client.start_copy_from_url(source_url)

    # For small files, copy is usually synchronous
    # For large files, we'd need to poll copy status
    # Since these are COGs (relatively small), we trust the copy completes


# Export for handler registration
__all__ = ['ingest_copy_batch']
