# ============================================================================
# CLAUDE CONTEXT - INGEST REGISTER HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handlers - pgSTAC Registration
# PURPOSE: Register collection and items in pgSTAC
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: ingest_register_collection, ingest_register_items, ingest_finalize
# DEPENDENCIES: infrastructure.pgstac_repository, infrastructure.blob
# ============================================================================
"""
Ingest Register Handlers.

Stages 3, 4, 5 of ingest workflow:
- ingest_register_collection: Register collection in pgSTAC
- ingest_register_items: Register batch of items in pgSTAC
- ingest_finalize: Create source_catalog entry, finalize
"""

import json
from typing import Dict, Any, List
from util_logger import LoggerFactory, ComponentType


# ============================================================================
# STAGE 3: REGISTER COLLECTION
# ============================================================================

def ingest_register_collection(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Register collection in pgSTAC (Stage 3).

    Downloads collection.json from source, updates hrefs to target container,
    and upserts to pgSTAC.

    Args:
        params: Task parameters containing:
            - source_container (str): Container with collection.json
            - target_container (str): Target container for updated hrefs
            - target_account (str): Target storage account
            - collection_id (str): Collection ID
            - collection_json_path (str): Path to collection.json
            - source_account (str): Source storage account
            - source_job_id (str): Job ID for tracking

    Returns:
        Success dict with registration result
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ingest_register_collection")

    source_container = params.get('source_container')
    target_container = params.get('target_container')
    target_account = params.get('target_account')
    collection_id = params.get('collection_id')
    collection_json_path = params.get('collection_json_path', 'collection.json')
    source_account = params.get('source_account')
    source_job_id = params.get('source_job_id')

    logger.info(f"📝 Registering collection: {collection_id}")

    try:
        from infrastructure.blob import BlobRepository
        from infrastructure.pgstac_repository import PgStacRepository

        # Get blob repository
        blob_repo = BlobRepository.for_zone("bronze")
        if source_account:
            blob_repo = BlobRepository(account_name=source_account)

        # Download collection.json
        collection_bytes = blob_repo.download_blob_content(
            container_name=source_container,
            blob_name=collection_json_path
        )
        collection_data = json.loads(collection_bytes)

        # Update collection hrefs to point to target
        # Remove item links (pgSTAC handles item-collection relationships)
        collection_data['links'] = [
            l for l in collection_data.get('links', [])
            if l.get('rel') not in ['item']
        ]

        # Add self link pointing to our API
        collection_data['links'].append({
            "rel": "self",
            "href": f"/api/stac/collections/{collection_id}",
            "type": "application/json"
        })

        # Add root link
        collection_data['links'].append({
            "rel": "root",
            "href": "/api/stac",
            "type": "application/json"
        })

        # Register in pgSTAC
        pgstac_repo = PgStacRepository()
        result = pgstac_repo.upsert_collection(collection_data)

        logger.info(f"✅ Collection registered: {collection_id}")

        return {
            "success": True,
            "result": {
                "collection_id": collection_id,
                "registered": True,
                "summaries": list(collection_data.get('summaries', {}).keys())
            }
        }

    except Exception as e:
        logger.error(f"❌ Collection registration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# ============================================================================
# STAGE 4: REGISTER ITEMS
# ============================================================================

def ingest_register_items(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Register batch of items in pgSTAC (Stage 4).

    Downloads item JSONs from source, updates asset hrefs to target container,
    and upserts to pgSTAC.

    Args:
        params: Task parameters containing:
            - source_container (str): Container with item JSONs
            - target_container (str): Target container for COGs
            - source_account (str): Source storage account
            - target_account (str): Target storage account
            - collection_id (str): Collection ID for items
            - batch_index (int): Batch number
            - items (list): List of item dicts with json_path, tif_path
            - source_job_id (str): Job ID

    Returns:
        Success dict with registration results
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ingest_register_items")

    source_container = params.get('source_container')
    target_container = params.get('target_container')
    source_account = params.get('source_account')
    target_account = params.get('target_account')
    collection_id = params.get('collection_id')
    batch_index = params.get('batch_index', 0)
    items = params.get('items', [])
    source_job_id = params.get('source_job_id')

    logger.info(f"📝 Registering items batch {batch_index}: {len(items)} items")

    try:
        from infrastructure.blob import BlobRepository
        from infrastructure.pgstac_repository import PgStacRepository
        from config import get_config

        config = get_config()

        # Get blob repository
        blob_repo = BlobRepository.for_zone("bronze")
        if source_account:
            blob_repo = BlobRepository(account_name=source_account)

        # Get target blob repo for URL generation
        target_blob_repo = BlobRepository.for_zone("silver")
        if target_account:
            target_blob_repo = BlobRepository(account_name=target_account)

        pgstac_repo = PgStacRepository()

        items_registered = 0
        errors = []

        for item_info in items:
            json_path = item_info.get('json_path')
            tif_path = item_info.get('tif_path')
            item_id = item_info.get('item_id')

            try:
                # Download item JSON
                item_bytes = blob_repo.download_blob_content(
                    container_name=source_container,
                    blob_name=json_path
                )
                item_data = json.loads(item_bytes)

                # Update asset href to target container
                if 'assets' in item_data and 'data' in item_data['assets']:
                    # Build URL to silver container
                    silver_url = _build_blob_url(
                        account=target_account or config.storage.silver_account,
                        container=target_container,
                        blob=tif_path
                    )
                    item_data['assets']['data']['href'] = silver_url

                # Ensure collection reference
                item_data['collection'] = collection_id

                # Update links
                item_data['links'] = [
                    {
                        "rel": "collection",
                        "href": f"/api/stac/collections/{collection_id}",
                        "type": "application/json"
                    },
                    {
                        "rel": "root",
                        "href": "/api/stac",
                        "type": "application/json"
                    },
                    {
                        "rel": "self",
                        "href": f"/api/stac/collections/{collection_id}/items/{item_id}",
                        "type": "application/geo+json"
                    }
                ]

                # Register in pgSTAC
                pgstac_repo.upsert_item(item_data)
                items_registered += 1

                if items_registered % 50 == 0:
                    logger.info(f"   Progress: {items_registered}/{len(items)} registered")

            except Exception as e:
                logger.warning(f"   Failed to register {item_id}: {e}")
                errors.append({"item_id": item_id, "error": str(e)})

        logger.info(f"✅ Batch {batch_index} complete: {items_registered} items registered")

        return {
            "success": True,
            "result": {
                "batch_index": batch_index,
                "items_registered": items_registered,
                "errors": errors if errors else None
            }
        }

    except Exception as e:
        logger.error(f"❌ Item registration batch {batch_index} failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "result": {
                "batch_index": batch_index,
                "items_registered": 0
            }
        }


# ============================================================================
# STAGE 5: FINALIZE
# ============================================================================

def ingest_finalize(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Finalize ingest by creating source_catalog entry (Stage 5).

    Creates an entry in h3.source_catalog for H3 pipeline integration.

    Args:
        params: Task parameters containing:
            - source_container (str): Original source container
            - target_container (str): Target container
            - target_account (str): Target storage account
            - collection_id (str): Collection ID
            - h3_theme (str): H3 theme (optional, inferred if not set)
            - total_items (int): Total item count
            - files_copied (int): Files copied
            - bytes_copied (int): Bytes copied
            - items_registered (int): Items registered
            - source_job_id (str): Job ID

    Returns:
        Success dict with finalization results
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ingest_finalize")

    target_container = params.get('target_container')
    target_account = params.get('target_account')
    collection_id = params.get('collection_id')
    h3_theme = params.get('h3_theme')
    total_items = params.get('total_items', 0)
    files_copied = params.get('files_copied', 0)
    bytes_copied = params.get('bytes_copied', 0)
    items_registered = params.get('items_registered', 0)
    source_job_id = params.get('source_job_id')

    logger.info(f"🎯 Finalizing ingest: {collection_id}")
    logger.info(f"   Items: {total_items}")
    logger.info(f"   Files copied: {files_copied}")
    logger.info(f"   Items registered: {items_registered}")

    try:
        # Infer theme from collection keywords if not provided
        if not h3_theme:
            h3_theme = _infer_theme(collection_id)
            logger.info(f"   Inferred theme: {h3_theme}")

        # Create source_catalog entry for H3 integration
        source_catalog_entry = _create_source_catalog_entry(
            collection_id=collection_id,
            target_container=target_container,
            target_account=target_account,
            h3_theme=h3_theme,
            total_items=total_items,
            source_job_id=source_job_id
        )

        logger.info(f"✅ Ingest finalized: {collection_id}")
        logger.info(f"   Source catalog entry created: {source_catalog_entry.get('created', False)}")

        return {
            "success": True,
            "result": {
                "collection_id": collection_id,
                "target_container": target_container,
                "h3_theme": h3_theme,
                "total_items": total_items,
                "files_copied": files_copied,
                "bytes_copied": bytes_copied,
                "items_registered": items_registered,
                "source_catalog_created": source_catalog_entry.get('created', False)
            }
        }

    except Exception as e:
        logger.error(f"❌ Finalization failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _build_blob_url(account: str, container: str, blob: str) -> str:
    """Build Azure Blob Storage URL."""
    return f"https://{account}.blob.core.windows.net/{container}/{blob}"


def _infer_theme(collection_id: str) -> str:
    """Infer H3 theme from collection ID or keywords."""
    collection_lower = collection_id.lower()

    # Theme inference rules
    if any(kw in collection_lower for kw in ['agriculture', 'crop', 'farm', 'mapspam', 'spam']):
        return 'agriculture'
    elif any(kw in collection_lower for kw in ['dem', 'elevation', 'terrain', 'slope']):
        return 'terrain'
    elif any(kw in collection_lower for kw in ['flood', 'water', 'precipitation']):
        return 'water'
    elif any(kw in collection_lower for kw in ['population', 'demographic', 'census']):
        return 'demographics'
    elif any(kw in collection_lower for kw in ['landcover', 'land_cover', 'lulc']):
        return 'landcover'
    elif any(kw in collection_lower for kw in ['vegetation', 'ndvi', 'forest']):
        return 'vegetation'
    elif any(kw in collection_lower for kw in ['climate', 'temperature', 'era5']):
        return 'climate'
    elif any(kw in collection_lower for kw in ['infrastructure', 'road', 'building']):
        return 'infrastructure'
    else:
        return 'vegetation'  # Default


def _create_source_catalog_entry(
    collection_id: str,
    target_container: str,
    target_account: str,
    h3_theme: str,
    total_items: int,
    source_job_id: str
) -> Dict[str, Any]:
    """
    Create entry in h3.source_catalog for H3 pipeline integration.
    """
    try:
        from infrastructure.h3_source_repository import H3SourceRepository

        repo = H3SourceRepository()

        source_entry = {
            "id": collection_id,
            "display_name": collection_id.replace('-', ' ').replace('_', ' ').title(),
            "description": f"Ingested STAC collection from {target_container}",
            "source_type": "stac_collection",
            "collection_id": collection_id,
            "theme": h3_theme,
            "tile_count": total_items,
            "coverage_type": "global",
            "is_temporal_series": False,
            "source_provider": "Ingested via ingest_collection job",
            "source_url": f"/api/stac/collections/{collection_id}",
        }

        result = repo.register_source(source_entry)
        return result

    except Exception as e:
        # Don't fail the job if source_catalog registration fails
        # It's optional for H3 integration
        import logging
        logging.warning(f"Failed to create source_catalog entry: {e}")
        return {"created": False, "error": str(e)}


# Export for handler registration
__all__ = ['ingest_register_collection', 'ingest_register_items', 'ingest_finalize']
