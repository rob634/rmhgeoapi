# ============================================================================
# CLAUDE CONTEXT - PGSTAC REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - PgSTAC data operations
# PURPOSE: Repository pattern for PgSTAC collections and items CRUD operations
# LAST_REVIEWED: 12 NOV 2025
# EXPORTS: PgStacRepository class
# INTERFACES: Repository pattern for pgSTAC database operations
# PYDANTIC_MODELS: pystac.Collection, pystac.Item (consumed)
# DEPENDENCIES: psycopg (3.2+), pystac (1.13+), typing, config
# SOURCE: PostgreSQL pgstac schema (collections, items tables)
# SCOPE: PgSTAC data operations (separate from PgStacBootstrap setup)
# VALIDATION: Pydantic models for STAC validation
# PATTERNS: Repository pattern, Separation of Concerns
# ENTRY_POINTS: PgStacRepository().insert_collection(), insert_item(), etc.
# INDEX:
#   - PgStacRepository class: Line 50
#   - insert_collection: Line 90
#   - update_collection_metadata: Line 150
#   - collection_exists: Line 210
#   - insert_item: Line 250
#   - get_collection: Line 310
#   - list_collections: Line 360
# ============================================================================

"""
PgSTAC Repository - Data Operations for Collections and Items

Encapsulates all PgSTAC data operations (CRUD) following Repository pattern.
Separated from PgStacBootstrap (which handles schema setup/installation).

Key Responsibilities:
- Insert/update/delete collections
- Insert/update/delete items
- Query collections and items
- Update collection metadata (for search_id storage)

Author: Robert and Geospatial Claude Legion
Date: 12 NOV 2025
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

    Author: Robert and Geospatial Claude Legion
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
                    # Use PgSTAC's insert_collection function
                    # Returns the collection ID (pgstac.create_collection returns jsonb)
                    cur.execute(
                        "SELECT pgstac.create_collection(%s::jsonb)",
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

    def insert_item(self, item: 'pystac.Item', collection_id: str) -> str:
        """
        Insert STAC item into PgSTAC.

        Args:
            item: pystac.Item object
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
        # Accept both pystac.Item and stac_pydantic.Item (18 NOV 2025)
        # StacMetadataService returns stac_pydantic.Item, but both are valid STAC items
        is_pystac_item = pystac and isinstance(item, pystac.Item)
        is_pydantic_item = StacPydanticItem and isinstance(item, StacPydanticItem)

        if not (is_pystac_item or is_pydantic_item):
            raise ValueError(
                f"Expected pystac.Item or stac_pydantic.Item, got {type(item).__name__}"
            )

        item_id = item.id
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
                    # Use PgSTAC's create_item function (singular - single item)
                    # 18 NOV 2025: Fixed - was create_items (plural) which expects array
                    cur.execute(
                        "SELECT * FROM pgstac.create_item(%s)",
                        (item_json,)
                    )
                    conn.commit()

                    logger.info(f"✅ Item inserted: {item_id}")
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


# Export the repository class
__all__ = ['PgStacRepository']
