# ============================================================================
# CLAUDE CONTEXT - INGEST INVENTORY HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - Collection Inventory
# PURPOSE: Parse collection.json and create batch plan for ingest
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: ingest_inventory
# DEPENDENCIES: infrastructure.blob
# ============================================================================
"""
Ingest Inventory Handler.

Stage 1 of ingest workflow. Downloads and parses collection.json from
source container, extracts item links, and creates batches for parallel
copy and registration stages.

Returns:
    - collection_id: STAC collection ID
    - collection_data: Parsed collection JSON
    - total_items: Total item count
    - batches: List of item batches for fan-out stages
"""

import json
from typing import Dict, Any, List
from util_logger import LoggerFactory, ComponentType


def ingest_inventory(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Parse collection.json and create batch plan (Stage 1).

    Args:
        params: Task parameters containing:
            - source_container (str): Container with collection.json
            - source_account (str): Optional storage account override
            - collection_json_path (str): Path to collection.json
            - batch_size (int): Items per batch
            - source_job_id (str): Job ID for tracking

    Returns:
        Success dict with inventory results:
        {
            "success": True,
            "result": {
                "collection_id": str,
                "collection_data": dict,
                "total_items": int,
                "batches": [[item1, item2, ...], ...]
            }
        }
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "ingest_inventory")

    source_container = params.get('source_container')
    source_account = params.get('source_account')
    collection_json_path = params.get('collection_json_path', 'collection.json')
    batch_size = params.get('batch_size', 100)
    source_job_id = params.get('source_job_id')

    logger.info(f"📦 Inventorying collection from {source_container}")
    logger.info(f"   Collection JSON: {collection_json_path}")
    logger.info(f"   Batch size: {batch_size}")

    try:
        from infrastructure.blob import BlobRepository

        # Get blob repository for bronze zone
        blob_repo = BlobRepository.for_zone("bronze")
        if source_account:
            # Override account if specified
            blob_repo = BlobRepository(account_name=source_account)

        # Download collection.json
        logger.info(f"   Downloading {collection_json_path}...")
        collection_bytes = blob_repo.download_blob_content(
            container_name=source_container,
            blob_name=collection_json_path
        )

        if not collection_bytes:
            raise ValueError(f"collection.json not found at {source_container}/{collection_json_path}")

        collection_data = json.loads(collection_bytes)

        # Validate STAC collection
        if collection_data.get('type') != 'Collection':
            raise ValueError(f"Invalid STAC collection: type={collection_data.get('type')}")

        collection_id = collection_data.get('id')
        if not collection_id:
            raise ValueError("Collection missing 'id' field")

        logger.info(f"   Collection ID: {collection_id}")
        logger.info(f"   STAC version: {collection_data.get('stac_version')}")

        # Extract item links
        links = collection_data.get('links', [])
        item_links = [l for l in links if l.get('rel') == 'item']

        logger.info(f"   Found {len(item_links)} item links")

        # Extract item info (json path and corresponding tif path)
        items = []
        for link in item_links:
            href = link.get('href', '')
            # Remove leading ./ if present
            if href.startswith('./'):
                href = href[2:]

            # Extract item ID from href (remove .json extension)
            item_id = href.replace('.json', '') if href.endswith('.json') else href

            # Infer TIF path from JSON path
            tif_path = href.replace('.json', '.tif')

            items.append({
                'item_id': item_id,
                'json_path': href,
                'tif_path': tif_path,
                'title': link.get('title', item_id)
            })

        # Create batches
        batches = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batches.append(batch)

        logger.info(f"   Created {len(batches)} batches of up to {batch_size} items")

        # Extract summaries for later use
        summaries = collection_data.get('summaries', {})
        logger.info(f"   Summaries: {list(summaries.keys())}")

        logger.info(f"✅ Inventory complete: {collection_id}")

        return {
            "success": True,
            "result": {
                "collection_id": collection_id,
                "collection_data": collection_data,
                "total_items": len(items),
                "batch_count": len(batches),
                "batches": batches,
                "summaries": summaries,
                "source_container": source_container
            }
        }

    except Exception as e:
        logger.error(f"❌ Inventory failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# Export for handler registration
__all__ = ['ingest_inventory']
