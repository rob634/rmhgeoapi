"""
Unpublish Workflow Handlers.

Task handlers for unpublish_raster and unpublish_vector jobs.
Provides surgical data removal - reverse of raster/vector processing.

Handlers:
    inventory_raster_item: Query STAC item, extract asset hrefs for blob deletion
    inventory_vector_item: Query STAC item, extract PostGIS table reference
    delete_blob: Delete single blob from Azure Storage (idempotent)
    drop_postgis_table: Drop PostGIS table (idempotent)
    delete_stac_and_audit: Delete STAC item, cleanup empty collection, record audit

Date: 12 DEC 2025
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from config.defaults import STACDefaults

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "UnpublishHandlers")


# =============================================================================
# INVENTORY HANDLERS (Stage 1)
# =============================================================================

def inventory_raster_item(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Query STAC item and extract asset hrefs for blob deletion.

    Stage 1 handler for unpublish_raster job.
    Uses pre-validated STAC item from params['_stac_item'] (populated by stac_item_exists validator).

    Extracts:
    - COG blobs from item['assets']['data']['href']
    - MosaicJSON from item['assets']['mosaic']['href'] (if present)
    - Tile COGs from item['assets']['tile_*']['href'] (large raster/collection workflows)

    Args:
        params: {
            'stac_item_id': str,
            'collection_id': str,
            'dry_run': bool,
            '_stac_item': dict (from validator),
            '_stac_item_assets': dict (from validator),
            '_stac_original_job_id': str (if available)
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'blobs_to_delete': [...],  # List of blob paths for Stage 2 fan-out
            'original_job_id': str or None,
            'stac_item_snapshot': dict  # For audit trail
        }
    """
    try:
        stac_item_id = params.get('stac_item_id')
        collection_id = params.get('collection_id')
        dry_run = params.get('dry_run', True)

        # Get pre-validated STAC item from validator
        stac_item = params.get('_stac_item')
        assets = params.get('_stac_item_assets', {})
        original_job_id = params.get('_stac_original_job_id')

        if not stac_item:
            return {
                "success": False,
                "error": "STAC item not found in params - stac_item_exists validator may have failed",
                "error_type": "ValidationError"
            }

        # Extract blob paths from assets
        blobs_to_delete = []

        for asset_key, asset_value in assets.items():
            href = asset_value.get('href', '')

            # Only process Azure blob URLs or relative paths
            if href.startswith('https://') and '.blob.core.windows.net/' in href:
                # Parse blob path from full URL
                # Format: https://{account}.blob.core.windows.net/{container}/{blob_path}
                parts = href.split('.blob.core.windows.net/', 1)
                if len(parts) == 2:
                    container_and_blob = parts[1]
                    if '/' in container_and_blob:
                        container, blob_path = container_and_blob.split('/', 1)
                        blobs_to_delete.append({
                            'container': container,
                            'blob_path': blob_path,
                            'asset_key': asset_key,
                            'href': href
                        })
            elif href.startswith('/') or not href.startswith('http'):
                # Relative path - assume silver-cogs container
                blobs_to_delete.append({
                    'container': 'silver-cogs',
                    'blob_path': href.lstrip('/'),
                    'asset_key': asset_key,
                    'href': href
                })

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Inventoried raster item {collection_id}/{stac_item_id}: "
            f"{len(blobs_to_delete)} blobs to delete"
        )

        return {
            "success": True,
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "blobs_to_delete": blobs_to_delete,
            "blob_count": len(blobs_to_delete),
            "original_job_id": original_job_id,
            "stac_item_snapshot": stac_item,
            "dry_run": dry_run
        }

    except Exception as e:
        logger.error(f"Failed to inventory raster item: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def inventory_vector_item(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Query STAC item and extract PostGIS table reference.

    Stage 1 handler for unpublish_vector job.
    Parses "postgis://geo.table_name" or "postgis://schema.table_name" from asset href.

    Args:
        params: {
            'stac_item_id': str,
            'collection_id': str,
            'drop_table': bool (default True),
            'dry_run': bool,
            '_stac_item': dict (from validator)
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'table_name': str,
            'schema_name': str,
            'original_job_id': str or None,
            'stac_item_snapshot': dict
        }
    """
    try:
        stac_item_id = params.get('stac_item_id')
        collection_id = params.get('collection_id')
        drop_table = params.get('drop_table', True)
        dry_run = params.get('dry_run', True)

        # Get pre-validated STAC item from validator
        stac_item = params.get('_stac_item')
        assets = params.get('_stac_item_assets', {})
        original_job_id = params.get('_stac_original_job_id')

        if not stac_item:
            return {
                "success": False,
                "error": "STAC item not found in params - stac_item_exists validator may have failed",
                "error_type": "ValidationError"
            }

        # Find PostGIS table reference in assets
        table_name = None
        schema_name = 'geo'  # Default schema

        for asset_key, asset_value in assets.items():
            href = asset_value.get('href', '')

            # Parse postgis:// protocol
            if href.startswith('postgis://'):
                # Format: postgis://schema.table_name or postgis://table_name
                ref = href.replace('postgis://', '')
                if '.' in ref:
                    schema_name, table_name = ref.split('.', 1)
                else:
                    table_name = ref
                break

        if not table_name:
            # Try to extract from properties as fallback
            properties = stac_item.get('properties', {})
            table_name = properties.get('postgis:table') or properties.get('table_name')
            if properties.get('postgis:schema'):
                schema_name = properties['postgis:schema']

        if not table_name:
            return {
                "success": False,
                "error": f"No PostGIS table reference found in STAC item {collection_id}/{stac_item_id}",
                "error_type": "ValidationError"
            }

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Inventoried vector item {collection_id}/{stac_item_id}: "
            f"table={schema_name}.{table_name}, drop_table={drop_table}"
        )

        return {
            "success": True,
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "table_name": table_name,
            "schema_name": schema_name,
            "drop_table": drop_table,
            "original_job_id": original_job_id,
            "stac_item_snapshot": stac_item,
            "dry_run": dry_run
        }

    except Exception as e:
        logger.error(f"Failed to inventory vector item: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# DELETE HANDLERS (Stage 2)
# =============================================================================

def delete_blob(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete single blob from Azure Storage (idempotent).

    Uses BlobRepository.delete_blob().
    Returns success even if blob already deleted (idempotent).

    Args:
        params: {
            'container': str,
            'blob_path': str,
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'deleted': bool,  # True if actually deleted, False if already gone
            'container': str,
            'blob_path': str
        }
    """
    from infrastructure.blob import BlobRepository

    try:
        container = params.get('container')
        blob_path = params.get('blob_path')
        dry_run = params.get('dry_run', True)

        if not container or not blob_path:
            return {
                "success": False,
                "error": "Container and blob_path are required",
                "error_type": "ValidationError"
            }

        if dry_run:
            logger.info(f"[DRY-RUN] Would delete blob: {container}/{blob_path}")
            return {
                "success": True,
                "deleted": False,
                "dry_run": True,
                "container": container,
                "blob_path": blob_path
            }

        # Determine zone from container name
        zone = 'silver' if 'silver' in container.lower() else 'bronze'
        blob_repo = BlobRepository.for_zone(zone)

        # Check if blob exists first
        if not blob_repo.blob_exists(container, blob_path):
            logger.info(f"Blob already deleted (idempotent): {container}/{blob_path}")
            return {
                "success": True,
                "deleted": False,
                "already_gone": True,
                "container": container,
                "blob_path": blob_path
            }

        # Delete the blob
        blob_repo.delete_blob(container, blob_path)

        logger.info(f"Deleted blob: {container}/{blob_path}")
        return {
            "success": True,
            "deleted": True,
            "container": container,
            "blob_path": blob_path
        }

    except Exception as e:
        logger.error(f"Failed to delete blob {params.get('container')}/{params.get('blob_path')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def drop_postgis_table(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Drop PostGIS table (idempotent).

    DROP TABLE IF EXISTS {schema}.{table_name} CASCADE
    Respects dry_run parameter.

    Args:
        params: {
            'table_name': str,
            'schema_name': str (default 'geo'),
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'dropped': bool,
            'table_name': str,
            'schema_name': str
        }
    """
    from infrastructure.postgresql import PostgreSQLRepository
    from psycopg import sql

    try:
        table_name = params.get('table_name')
        schema_name = params.get('schema_name', 'geo')
        dry_run = params.get('dry_run', True)

        if not table_name:
            return {
                "success": False,
                "error": "table_name is required",
                "error_type": "ValidationError"
            }

        if dry_run:
            logger.info(f"[DRY-RUN] Would drop table: {schema_name}.{table_name}")
            return {
                "success": True,
                "dropped": False,
                "dry_run": True,
                "table_name": table_name,
                "schema_name": schema_name
            }

        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if table exists first
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    ) as exists
                    """,
                    (schema_name, table_name)
                )
                exists = cur.fetchone()['exists']

                if not exists:
                    logger.info(f"Table already dropped (idempotent): {schema_name}.{table_name}")
                    return {
                        "success": True,
                        "dropped": False,
                        "already_gone": True,
                        "table_name": table_name,
                        "schema_name": schema_name
                    }

                # Drop the table with CASCADE
                drop_query = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name)
                )
                cur.execute(drop_query)
                conn.commit()

        logger.info(f"Dropped table: {schema_name}.{table_name}")
        return {
            "success": True,
            "dropped": True,
            "table_name": table_name,
            "schema_name": schema_name
        }

    except Exception as e:
        logger.error(f"Failed to drop table {params.get('schema_name', 'geo')}.{params.get('table_name')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# CLEANUP HANDLER (Stage 3)
# =============================================================================

def delete_stac_and_audit(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete STAC item, cleanup empty collection, record audit.

    Final stage handler for both unpublish_raster and unpublish_vector jobs.

    Steps:
    1. DELETE FROM pgstac.items WHERE id = ? AND collection = ?
    2. Check if collection empty: COUNT(*) FROM pgstac.items WHERE collection = ?
    3. If empty AND NOT IN STACDefaults.SYSTEM_COLLECTIONS: DELETE FROM pgstac.collections
    4. Record to app.unpublish_jobs audit table
    5. (Optional) Mark original job as unpublished for idempotency

    Args:
        params: {
            'stac_item_id': str,
            'collection_id': str,
            'unpublish_type': str ('raster' or 'vector'),
            'unpublish_job_id': str,  # The unpublish job's ID
            'original_job_id': str or None,
            'original_job_type': str or None,
            'stac_item_snapshot': dict,  # For audit trail
            'artifacts_deleted': dict,  # What was deleted in Stage 2
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'stac_item_deleted': bool,
            'collection_deleted': bool,
            'audit_record_id': str
        }
    """
    from infrastructure.postgresql import PostgreSQLRepository
    from core.models.unpublish import UnpublishJobRecord, UnpublishType, UnpublishStatus

    try:
        stac_item_id = params.get('stac_item_id')
        collection_id = params.get('collection_id')
        unpublish_type = params.get('unpublish_type', 'raster')
        unpublish_job_id = params.get('unpublish_job_id')
        original_job_id = params.get('original_job_id')
        original_job_type = params.get('original_job_type')
        stac_item_snapshot = params.get('stac_item_snapshot', {})
        artifacts_deleted = params.get('artifacts_deleted', {})
        dry_run = params.get('dry_run', True)

        if not stac_item_id or not collection_id:
            return {
                "success": False,
                "error": "stac_item_id and collection_id are required",
                "error_type": "ValidationError"
            }

        # Create audit record
        audit_record = UnpublishJobRecord(
            unpublish_job_id=unpublish_job_id or 'unknown',
            unpublish_type=UnpublishType(unpublish_type),
            original_job_id=original_job_id,
            original_job_type=original_job_type,
            original_parameters=stac_item_snapshot.get('properties', {}).get('processing:parameters'),
            stac_item_id=stac_item_id,
            collection_id=collection_id,
            artifacts_deleted=artifacts_deleted,
            dry_run=dry_run
        )

        if dry_run:
            logger.info(
                f"[DRY-RUN] Would delete STAC item {collection_id}/{stac_item_id} "
                f"and record audit (type={unpublish_type})"
            )
            audit_record.status = UnpublishStatus.DRY_RUN
            return {
                "success": True,
                "stac_item_deleted": False,
                "collection_deleted": False,
                "dry_run": True,
                "audit_record": audit_record.model_dump()
            }

        repo = PostgreSQLRepository()
        stac_deleted = False
        collection_deleted = False

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: Delete STAC item
                cur.execute(
                    "DELETE FROM pgstac.items WHERE id = %s AND collection = %s RETURNING id",
                    (stac_item_id, collection_id)
                )
                deleted_row = cur.fetchone()
                stac_deleted = deleted_row is not None

                if stac_deleted:
                    logger.info(f"Deleted STAC item: {collection_id}/{stac_item_id}")
                else:
                    logger.warning(f"STAC item not found (already deleted?): {collection_id}/{stac_item_id}")

                # Step 2: Check if collection is now empty
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM pgstac.items WHERE collection = %s",
                    (collection_id,)
                )
                item_count = cur.fetchone()['cnt']

                # Step 3: Delete empty collection if not protected
                if item_count == 0 and collection_id not in STACDefaults.SYSTEM_COLLECTIONS:
                    cur.execute(
                        "DELETE FROM pgstac.collections WHERE id = %s RETURNING id",
                        (collection_id,)
                    )
                    deleted_collection = cur.fetchone()
                    collection_deleted = deleted_collection is not None

                    if collection_deleted:
                        logger.info(f"Deleted empty collection: {collection_id}")
                elif item_count == 0:
                    logger.info(f"Collection {collection_id} is empty but protected (system collection)")

                # Step 4: Record to audit table
                audit_record.status = UnpublishStatus.COMPLETED
                audit_record.collection_deleted = collection_deleted
                audit_record.artifacts_deleted = {
                    **artifacts_deleted,
                    'stac_item': stac_item_snapshot
                }
                audit_record.completed_at = datetime.now(timezone.utc)

                cur.execute(
                    """
                    INSERT INTO app.unpublish_jobs (
                        unpublish_id, unpublish_job_id, unpublish_type,
                        original_job_id, original_job_type, original_parameters,
                        stac_item_id, collection_id,
                        artifacts_deleted, collection_deleted,
                        status, dry_run, created_at, completed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        audit_record.unpublish_id,
                        audit_record.unpublish_job_id,
                        audit_record.unpublish_type.value,
                        audit_record.original_job_id,
                        audit_record.original_job_type,
                        str(audit_record.original_parameters) if audit_record.original_parameters else None,
                        audit_record.stac_item_id,
                        audit_record.collection_id,
                        str(audit_record.artifacts_deleted),
                        audit_record.collection_deleted,
                        audit_record.status.value,
                        audit_record.dry_run,
                        audit_record.created_at,
                        audit_record.completed_at
                    )
                )

                conn.commit()

        logger.info(
            f"Unpublish complete: item_deleted={stac_deleted}, "
            f"collection_deleted={collection_deleted}, audit_id={audit_record.unpublish_id}"
        )

        return {
            "success": True,
            "stac_item_deleted": stac_deleted,
            "collection_deleted": collection_deleted,
            "collection_remaining_items": item_count if not collection_deleted else 0,
            "audit_record_id": audit_record.unpublish_id
        }

    except Exception as e:
        logger.error(f"Failed to delete STAC item and audit: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'inventory_raster_item',
    'inventory_vector_item',
    'delete_blob',
    'drop_postgis_table',
    'delete_stac_and_audit',
]
