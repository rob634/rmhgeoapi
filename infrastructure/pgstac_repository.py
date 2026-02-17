# ============================================================================
# PGSTAC REPOSITORY
# ============================================================================
# STATUS: Infrastructure - PgSTAC data operations (CRUD)
# PURPOSE: Insert/update/delete collections and items in PgSTAC schema
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
PgSTAC Repository - Data Operations for Collections and Items.

Encapsulates all PgSTAC data operations (CRUD) following Repository pattern.
Separated from PgStacBootstrap (which handles schema setup/installation).

Key Responsibilities:
    - Insert/update/delete collections
    - Insert/update/delete items
    - Query collections and items
    - Update collection metadata (for search_id storage)

Exports:
    PgStacRepository: Repository for pgSTAC database operations
"""

from typing import Dict, Any, Optional, List
import json
import psycopg
from psycopg import sql

try:
    import pystac
except ImportError:
    pystac = None

try:
    from stac_pydantic import Item as StacPydanticItem
except ImportError:
    StacPydanticItem = None

from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "PgStacRepository")


class PgStacRepository:
    """
    Repository for PgSTAC collections and items data operations.

    Handles all CRUD operations for PgSTAC database. Uses simple connections
    (no pooling) suitable for Azure Functions serverless environment.

    Separation of Concerns:
    - PgStacBootstrap: Schema setup, installation, version management
    - PgStacRepository: Data CRUD operations (this class)

    
    Date: 12 NOV 2025
    """

    PGSTAC_SCHEMA = "pgstac"

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize PgSTAC repository.

        Args:
            connection_string: PostgreSQL connection string (uses config if not provided)
        """
        from infrastructure.postgresql import PostgreSQLRepository

        self.config = get_config()

        # Use PostgreSQLRepository for managed identity support (16 NOV 2025)
        if connection_string:
            self._pg_repo = PostgreSQLRepository(
                connection_string=connection_string,
                schema_name='pgstac'
            )
        else:
            self._pg_repo = PostgreSQLRepository(schema_name='pgstac')

        # Keep connection_string attribute for backward compatibility
        self.connection_string = self._pg_repo.conn_string

    # =========================================================================
    # COLLECTION OPERATIONS
    # =========================================================================

    def insert_collection(self, collection: 'pystac.Collection') -> str:
        """
        Insert STAC collection into PgSTAC.

        Args:
            collection: pystac.Collection object

        Returns:
            Collection ID (string)

        Raises:
            RuntimeError: If collection insert fails
            ValueError: If collection is invalid

        Note:
            Uses PgSTAC's insert_collection() SQL function which handles:
            - Collection validation
            - Partition creation for items
            - Upsert semantics (updates if exists)
        """
        if not pystac:
            raise ImportError("pystac library required for collection operations")

        if not isinstance(collection, pystac.Collection):
            raise ValueError(f"Expected pystac.Collection, got {type(collection).__name__}")

        collection_id = collection.id
        logger.info(f"🔄 Inserting collection into PgSTAC: {collection_id}")

        try:
            # Convert collection to dict and serialize to JSON
            collection_dict = collection.to_dict()
            collection_json = json.dumps(collection_dict)

            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Use PgSTAC's upsert function for process_raster (19 NOV 2025)
                    # upsert_collection handles duplicates gracefully (updates if exists)
                    # create_collection fails with unique constraint error on duplicate
                    cur.execute(
                        "SELECT * FROM pgstac.upsert_collection(%s::jsonb)",
                        (collection_json,)
                    )
                    result = cur.fetchone()
                    # Result is dict thanks to dict_row, pgstac function returns jsonb
                    conn.commit()

                    logger.info(f"✅ Collection inserted: {collection_id}")
                    return collection_id

        except Exception as e:
            logger.error(f"❌ Failed to insert collection '{collection_id}': {e}")
            raise RuntimeError(f"PgSTAC collection insert failed: {e}")

    def update_collection_metadata(
        self,
        collection_id: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Update collection metadata (for storing search_id, links, etc.).

        Args:
            collection_id: Collection ID to update
            metadata: Dict with fields to update (e.g., {"summaries": {...}, "links": [...]})

        Returns:
            True if updated successfully

        Raises:
            RuntimeError: If update fails

        Note:
            This merges metadata into existing collection record.
            Useful for adding search_id after collection creation.
        """
        logger.info(f"🔄 Updating collection metadata: {collection_id}")
        logger.debug(f"   Metadata keys: {list(metadata.keys())}")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # First, get existing collection
                    cur.execute(
                        "SELECT content FROM pgstac.collections WHERE id = %s",
                        (collection_id,)
                    )
                    result = cur.fetchone()

                    if not result:
                        raise ValueError(f"Collection '{collection_id}' not found")

                    existing_content = result['content']

                    # Merge metadata into existing content
                    for key, value in metadata.items():
                        existing_content[key] = value

                    # Update collection using PgSTAC function
                    collection_json = json.dumps(existing_content)
                    cur.execute(
                        "SELECT pgstac.update_collection(%s::jsonb)",
                        (collection_json,)
                    )
                    conn.commit()

                    logger.info(f"✅ Collection metadata updated: {collection_id}")
                    return True

        except Exception as e:
            logger.error(f"❌ Failed to update collection '{collection_id}': {e}")
            raise RuntimeError(f"PgSTAC collection update failed: {e}")

    def collection_exists(self, collection_id: str) -> bool:
        """
        Check if collection exists in PgSTAC.

        Args:
            collection_id: Collection ID to check

        Returns:
            True if collection exists

        Note:
            CRITICAL for pgSTAC - collections must exist before items
            because collections create partitions that items use.
        """
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s)",
                        (collection_id,)
                    )
                    result = cur.fetchone()
                    exists = result['exists']
                    logger.debug(f"   Collection '{collection_id}' exists: {exists}")
                    return exists

        except Exception as e:
            logger.error(f"❌ Error checking collection existence: {e}")
            return False

    # =========================================================================
    # ITEM OPERATIONS
    # =========================================================================

    def insert_item(self, item, collection_id: str) -> str:
        """
        Insert STAC item into PgSTAC.

        Args:
            item: STAC item as pystac.Item, stac_pydantic.Item, or plain dict
            collection_id: Collection ID that item belongs to

        Returns:
            Item ID (string)

        Raises:
            RuntimeError: If item insert fails
            ValueError: If item is invalid or collection doesn't exist

        Note:
            Collection MUST exist before inserting items (PgSTAC requirement).
            Uses PgSTAC's insert_item() which handles partitioning.
        """
        # Accept pystac.Item, stac_pydantic.Item, or plain dict (V0.9 P3.1)
        is_pystac_item = pystac and isinstance(item, pystac.Item)
        is_pydantic_item = StacPydanticItem and isinstance(item, StacPydanticItem)
        is_dict_item = isinstance(item, dict)

        if not (is_pystac_item or is_pydantic_item or is_dict_item):
            raise ValueError(
                f"Expected pystac.Item, stac_pydantic.Item, or dict, got {type(item).__name__}"
            )

        item_id = item['id'] if is_dict_item else item.id
        logger.info(f"🔄 Inserting item into PgSTAC: {item_id} (collection: {collection_id})")

        try:
            # Verify collection exists first
            if not self.collection_exists(collection_id):
                raise ValueError(
                    f"Collection '{collection_id}' does not exist. "
                    f"Collections must exist before inserting items."
                )

            # Convert item to dict and serialize to JSON
            # Use Pydantic's model_dump for proper JSON serialization
            if hasattr(item, 'model_dump'):
                # stac-pydantic Item
                item_dict = item.model_dump(mode='json', by_alias=True)
            elif hasattr(item, 'to_dict'):
                # pystac Item
                item_dict = item.to_dict()
            else:
                # Already a dict
                item_dict = item

            # Ensure collection field is set
            item_dict['collection'] = collection_id

            item_json = json.dumps(item_dict)

            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Use PgSTAC's upsert_item for idempotent inserts (13 JAN 2026)
                    # upsert_item updates if exists, create_item fails on duplicate
                    # This allows job resubmission without manual cleanup
                    cur.execute(
                        "SELECT * FROM pgstac.upsert_item(%s)",
                        (item_json,)
                    )
                    conn.commit()

                    logger.info(f"✅ Item upserted: {item_id}")
                    return item_id

        except Exception as e:
            logger.error(f"❌ Failed to insert item '{item_id}': {e}")
            raise RuntimeError(f"PgSTAC item insert failed: {e}")

    # =========================================================================
    # QUERY OPERATIONS
    # =========================================================================

    def get_collection(self, collection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get collection by ID.

        Args:
            collection_id: Collection ID to retrieve

        Returns:
            Collection dict or None if not found
        """
        logger.debug(f"🔍 Fetching collection: {collection_id}")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT content FROM pgstac.collections WHERE id = %s",
                        (collection_id,)
                    )
                    result = cur.fetchone()

                    if result:
                        logger.debug(f"   ✅ Collection found: {collection_id}")
                        return result['content']  # content is JSONB, returns dict
                    else:
                        logger.debug(f"   ❌ Collection not found: {collection_id}")
                        return None

        except Exception as e:
            logger.error(f"❌ Error fetching collection '{collection_id}': {e}")
            return None

    def get_item(self, item_id: str, collection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get item by ID and collection.

        Args:
            item_id: Item ID to retrieve
            collection_id: Collection ID the item belongs to

        Returns:
            Item dict or None if not found
        """
        logger.debug(f"🔍 Fetching item: {item_id} (collection: {collection_id})")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT content
                        FROM pgstac.items
                        WHERE id = %s AND collection = %s
                        """,
                        (item_id, collection_id)
                    )
                    result = cur.fetchone()

                    if result:
                        logger.debug(f"   ✅ Item found: {item_id}")
                        return result['content']  # content is JSONB, returns dict
                    else:
                        logger.debug(f"   ❌ Item not found: {item_id}")
                        return None

        except Exception as e:
            logger.error(f"❌ Error fetching item '{item_id}': {e}")
            return None

    def update_item_properties(
        self,
        item_id: str,
        collection_id: str,
        properties_update: Dict[str, Any]
    ) -> bool:
        """
        Update specific properties of a STAC item.

        Args:
            item_id: Item ID to update
            collection_id: Collection ID the item belongs to
            properties_update: Dict of properties to merge/update

        Returns:
            True if update succeeded, False otherwise

        Note:
            Uses PostgreSQL jsonb_set to update properties in place.
            Only updates specified properties, preserves others.
        """
        logger.info(f"🔄 Updating item properties: {item_id} (collection: {collection_id})")
        logger.debug(f"   Properties update: {properties_update}")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Update properties using jsonb concatenation (||)
                    # This merges the new properties with existing ones
                    cur.execute(
                        """
                        UPDATE pgstac.items
                        SET content = jsonb_set(
                            content,
                            '{properties}',
                            (content->'properties') || %s::jsonb
                        )
                        WHERE id = %s AND collection = %s
                        RETURNING id
                        """,
                        (json.dumps(properties_update), item_id, collection_id)
                    )
                    result = cur.fetchone()
                    conn.commit()

                    if result:
                        logger.info(f"✅ Item properties updated: {item_id}")
                        return True
                    else:
                        logger.warning(f"⚠️ Item not found for update: {item_id}")
                        return False

        except Exception as e:
            logger.error(f"❌ Error updating item properties '{item_id}': {e}")
            return False

    def get_collection_item_ids(self, collection_id: str) -> List[str]:
        """
        Get all item IDs in a collection.

        Used for collection-level operations like bulk unpublish.

        Args:
            collection_id: STAC collection ID

        Returns:
            List of item IDs in the collection
        """
        logger.debug(f"🔍 Getting item IDs for collection '{collection_id}'")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id
                        FROM pgstac.items
                        WHERE collection = %s
                        ORDER BY id
                        """,
                        (collection_id,)
                    )
                    results = cur.fetchall()
                    item_ids = [row['id'] for row in results]
                    logger.debug(f"   ✅ Found {len(item_ids)} items in collection '{collection_id}'")
                    return item_ids

        except Exception as e:
            logger.error(f"❌ Error getting item IDs for collection '{collection_id}': {e}")
            return []

    def delete_item(self, collection_id: str, item_id: str) -> bool:
        """
        Delete a STAC item from PgSTAC (12 JAN 2026).

        Used by job resubmit to clean up old STAC items before reprocessing.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID to delete

        Returns:
            True if deleted, False if not found or error

        Note:
            pgstac schema uses (collection, id) as composite primary key.
        """
        logger.info(f"🗑️ Deleting STAC item '{item_id}' from collection '{collection_id}'")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM pgstac.items
                        WHERE collection = %s AND id = %s
                        RETURNING id
                        """,
                        (collection_id, item_id)
                    )
                    result = cur.fetchone()
                    conn.commit()

                    if result:
                        logger.info(f"   ✅ Deleted STAC item '{item_id}'")
                        return True
                    else:
                        logger.warning(f"   ⚠️ STAC item '{item_id}' not found in collection '{collection_id}'")
                        return False

        except Exception as e:
            logger.error(f"❌ Error deleting STAC item '{item_id}': {e}")
            return False

    def list_collections(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        List all collections.

        Args:
            limit: Maximum number of collections to return
            offset: Number of collections to skip

        Returns:
            List of collection dicts
        """
        logger.debug(f"🔍 Listing collections (limit={limit}, offset={offset})")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT content
                        FROM pgstac.collections
                        ORDER BY id
                        LIMIT %s OFFSET %s
                        """,
                        (limit, offset)
                    )
                    results = cur.fetchall()

                    collections = [row['content'] for row in results]
                    logger.debug(f"   ✅ Found {len(collections)} collections")
                    return collections

        except Exception as e:
            logger.error(f"❌ Error listing collections: {e}")
            return []

    # =========================================================================
    # B2B CATALOG OPERATIONS (16 JAN 2026 - F12.8)
    # =========================================================================
    # These methods support B2B STAC catalog access for DDH integration.
    # DDH can lookup STAC items using their identifiers (dataset_id, resource_id, version_id).
    # =========================================================================

    def search_by_platform_ids(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Search for STAC item by DDH platform identifiers.

        Uses the platform:* properties stored in STAC item properties.
        This enables B2B catalog lookup where DDH can find STAC items
        using their own identifiers without knowing our internal STAC IDs.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            STAC item dict if found, None otherwise

        Note:
            This query uses JSONB containment operator (@>) which can leverage
            GIN indexes if available on pgstac.items.content.

        Created: 16 JAN 2026 - F12.8 B2B STAC Catalog Access
        """
        logger.debug(
            f"🔍 Searching by platform IDs: dataset={dataset_id}, "
            f"resource={resource_id}, version={version_id}"
        )

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Use JSONB containment for efficient matching
                    # This allows the query to use GIN indexes if available
                    cur.execute(
                        """
                        SELECT content, collection, id
                        FROM pgstac.items
                        WHERE content->'properties' @> %s::jsonb
                        LIMIT 1
                        """,
                        (json.dumps({
                            "platform:dataset_id": dataset_id,
                            "platform:resource_id": resource_id,
                            "platform:version_id": version_id
                        }),)
                    )
                    result = cur.fetchone()

                    if result:
                        logger.debug(
                            f"   ✅ Found item: {result['id']} "
                            f"(collection: {result['collection']})"
                        )
                        return result['content']
                    else:
                        logger.debug("   ❌ No item found for platform IDs")
                        return None

        except Exception as e:
            logger.error(f"❌ Error searching by platform IDs: {e}")
            return None

    def get_items_by_platform_dataset(
        self,
        dataset_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get all STAC items for a DDH dataset.

        Returns all items that have the specified platform:dataset_id,
        regardless of resource_id or version_id. Useful for finding
        all versions/resources within a DDH dataset.

        Args:
            dataset_id: DDH dataset identifier
            limit: Maximum items to return (default 100)

        Returns:
            List of STAC item dicts (with id and collection added)

        Note:
            pgstac stores id and collection as table columns, not in content.
            We merge them into the returned dict for convenience.

        Created: 16 JAN 2026 - F12.8 B2B STAC Catalog Access
        """
        logger.debug(f"🔍 Getting items for platform dataset: {dataset_id}")

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Include id and collection columns (not in content JSON)
                    cur.execute(
                        """
                        SELECT id, collection, content
                        FROM pgstac.items
                        WHERE content->'properties'->>'platform:dataset_id' = %s
                        ORDER BY content->'properties'->>'datetime' DESC
                        LIMIT %s
                        """,
                        (dataset_id, limit)
                    )
                    results = cur.fetchall()

                    # Merge id and collection into content dict
                    items = []
                    for row in results:
                        item = row['content']
                        item['id'] = row['id']
                        item['collection'] = row['collection']
                        items.append(item)

                    logger.debug(f"   ✅ Found {len(items)} items for dataset {dataset_id}")
                    return items

        except Exception as e:
            logger.error(f"❌ Error getting items for platform dataset: {e}")
            return []


# Export the repository class
__all__ = ['PgStacRepository']
