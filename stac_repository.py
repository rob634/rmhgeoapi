"""
STAC Repository - Table Storage data access layer for STAC Collections and Items
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List
from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from config import Config
from logger_setup import create_buffered_logger
from stac_models import STACCollection, STACItem, STACQuery, STACBoundingBox


class STACRepository:
    """Repository for STAC Collections and Items in Azure Table Storage"""
    
    def __init__(self):
        self.logger = create_buffered_logger(
            name=f"{__name__}.STACRepository",
            capacity=100,
            flush_level=logging.ERROR
        )
        
        # Always use managed identity in Azure Functions
        if not Config.STORAGE_ACCOUNT_NAME:
            raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set for managed identity")
        
        from azure.identity import DefaultAzureCredential
        account_url = Config.get_storage_account_url('table')
        self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        
        self.collections_table = "staccollections"
        self.items_table = "stacitems"
    
    def _ensure_tables_exist(self):
        """Create STAC tables if they don't exist"""
        try:
            self.table_service.create_table(self.collections_table)
            self.logger.info(f"Created STAC collections table: {self.collections_table}")
        except ResourceExistsError:
            self.logger.debug(f"STAC collections table already exists: {self.collections_table}")
        
        try:
            self.table_service.create_table(self.items_table)
            self.logger.info(f"Created STAC items table: {self.items_table}")
        except ResourceExistsError:
            self.logger.debug(f"STAC items table already exists: {self.items_table}")
    
    # STAC Collections CRUD
    
    def save_collection(self, collection: STACCollection) -> bool:
        """
        Save STAC collection to table storage
        Returns True if new collection, False if updated existing
        """
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.collections_table)
            
            # Check if collection exists
            existing = self.get_collection(collection.id)
            is_new = existing is None
            
            # Update timestamp
            collection.updated_at = datetime.now(timezone.utc).isoformat()
            
            # Create or update entity
            entity = collection.to_table_entity()
            
            if is_new:
                table_client.create_entity(entity)
                self.logger.info(f"Created new STAC collection: {collection.id}")
            else:
                table_client.update_entity(entity, mode='replace')
                self.logger.info(f"Updated STAC collection: {collection.id}")
            
            return is_new
            
        except Exception as e:
            self.logger.error(f"Error saving STAC collection {collection.id}: {str(e)}")
            raise
    
    def get_collection(self, collection_id: str) -> Optional[STACCollection]:
        """Get STAC collection by ID"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.collections_table)
            entity = table_client.get_entity('collections', collection_id)
            
            return STACCollection.from_table_entity(entity)
            
        except ResourceNotFoundError:
            self.logger.debug(f"STAC collection not found: {collection_id}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting STAC collection {collection_id}: {str(e)}")
            raise
    
    def list_collections(self, limit: int = 100) -> List[STACCollection]:
        """List all STAC collections"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.collections_table)
            
            query_filter = "PartitionKey eq 'collections'"
            entities = table_client.query_entities(query_filter, results_per_page=limit)
            
            collections = []
            for entity in entities:
                collections.append(STACCollection.from_table_entity(entity))
            
            self.logger.info(f"Listed {len(collections)} STAC collections")
            return collections
            
        except Exception as e:
            self.logger.error(f"Error listing STAC collections: {str(e)}")
            raise
    
    def delete_collection(self, collection_id: str) -> bool:
        """Delete STAC collection"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.collections_table)
            
            table_client.delete_entity('collections', collection_id)
            self.logger.info(f"Deleted STAC collection: {collection_id}")
            return True
            
        except ResourceNotFoundError:
            self.logger.warning(f"STAC collection not found for deletion: {collection_id}")
            return False
        except Exception as e:
            self.logger.error(f"Error deleting STAC collection {collection_id}: {str(e)}")
            raise
    
    # STAC Items CRUD
    
    def save_item(self, item: STACItem) -> bool:
        """
        Save STAC item to table storage
        Returns True if new item, False if updated existing
        """
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.items_table)
            
            # Check if item exists
            existing = self.get_item(item.id, item.collection)
            is_new = existing is None
            
            # Update timestamp
            item.updated_at = datetime.now(timezone.utc).isoformat()
            
            # Create or update entity
            entity = item.to_table_entity()
            
            if is_new:
                table_client.create_entity(entity)
                self.logger.info(f"Created new STAC item: {item.id} in collection {item.collection}")
                
                # Update collection item count
                self._increment_collection_item_count(item.collection)
            else:
                table_client.update_entity(entity, mode='replace')
                self.logger.info(f"Updated STAC item: {item.id} in collection {item.collection}")
            
            return is_new
            
        except Exception as e:
            self.logger.error(f"Error saving STAC item {item.id}: {str(e)}")
            raise
    
    def get_item(self, item_id: str, collection_id: str) -> Optional[STACItem]:
        """Get STAC item by ID and collection"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.items_table)
            
            # Need to query by RowKey since we don't know the spatial partition
            query_filter = f"RowKey eq '{item_id}' and collection eq '{collection_id}'"
            entities = list(table_client.query_entities(query_filter))
            
            if not entities:
                return None
            
            return STACItem.from_table_entity(entities[0])
            
        except Exception as e:
            self.logger.error(f"Error getting STAC item {item_id}: {str(e)}")
            raise
    
    def search_items(self, query: STACQuery) -> Dict:
        """Search STAC items with spatial and temporal filters"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.items_table)
            
            # Build query filter
            filters = []
            
            # Collection filter
            if query.collections:
                collection_filters = [f"collection eq '{c}'" for c in query.collections]
                filters.append(f"({' or '.join(collection_filters)})")
            
            # ID filter (most specific)
            if query.ids:
                id_filters = [f"RowKey eq '{id}'" for id in query.ids]
                filters.append(f"({' or '.join(id_filters)})")
            
            # Combine filters
            query_filter = " and ".join(filters) if filters else None
            
            # Execute query with pagination
            entities = list(table_client.query_entities(
                query_filter, 
                results_per_page=query.limit
            ))
            
            # Apply spatial filter (post-query since Table Storage doesn't support geo queries)
            filtered_items = []
            for entity in entities:
                item = STACItem.from_table_entity(entity)
                
                # Apply bbox filter if specified
                if query.bbox and not self._bbox_intersects(item.bbox, query.bbox):
                    continue
                
                # Apply datetime filter if specified
                if query.datetime and not self._datetime_matches(item.datetime, query.datetime):
                    continue
                
                filtered_items.append(item)
            
            # Apply offset and limit after filtering
            start_idx = query.offset
            end_idx = start_idx + query.limit
            paginated_items = filtered_items[start_idx:end_idx]
            
            self.logger.info(f"STAC search returned {len(paginated_items)} items (filtered from {len(entities)})")
            
            return {
                "type": "FeatureCollection",
                "features": [item.to_stac_dict() for item in paginated_items],
                "numberMatched": len(filtered_items),
                "numberReturned": len(paginated_items),
                "links": []  # TODO: Add pagination links
            }
            
        except Exception as e:
            self.logger.error(f"Error searching STAC items: {str(e)}")
            raise
    
    def list_collection_items(self, collection_id: str, limit: int = 100) -> List[STACItem]:
        """List all items in a collection"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.items_table)
            
            # Query by collection (will scan multiple partitions)
            query_filter = f"collection eq '{collection_id}'"
            entities = list(table_client.query_entities(query_filter, results_per_page=limit))
            
            items = []
            for entity in entities:
                items.append(STACItem.from_table_entity(entity))
            
            self.logger.info(f"Listed {len(items)} items from collection {collection_id}")
            return items
            
        except Exception as e:
            self.logger.error(f"Error listing items for collection {collection_id}: {str(e)}")
            raise
    
    def delete_item(self, item_id: str, collection_id: str) -> bool:
        """Delete STAC item"""
        try:
            # First get the item to find its partition
            item = self.get_item(item_id, collection_id)
            if not item:
                return False
            
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.items_table)
            
            # Delete using full partition key
            partition_key = f"{collection_id}_{item.spatial_index}"
            table_client.delete_entity(partition_key, item_id)
            
            # Update collection item count
            self._decrement_collection_item_count(collection_id)
            
            self.logger.info(f"Deleted STAC item: {item_id} from collection {collection_id}")
            return True
            
        except ResourceNotFoundError:
            self.logger.warning(f"STAC item not found for deletion: {item_id}")
            return False
        except Exception as e:
            self.logger.error(f"Error deleting STAC item {item_id}: {str(e)}")
            raise
    
    # Helper methods
    
    def _increment_collection_item_count(self, collection_id: str):
        """Increment item count for a collection"""
        try:
            collection = self.get_collection(collection_id)
            if collection:
                collection.item_count += 1
                self.save_collection(collection)
        except Exception as e:
            self.logger.warning(f"Failed to update collection item count: {e}")
    
    def _decrement_collection_item_count(self, collection_id: str):
        """Decrement item count for a collection"""
        try:
            collection = self.get_collection(collection_id)
            if collection and collection.item_count > 0:
                collection.item_count -= 1
                self.save_collection(collection)
        except Exception as e:
            self.logger.warning(f"Failed to update collection item count: {e}")
    
    def _bbox_intersects(self, item_bbox: STACBoundingBox, query_bbox: STACBoundingBox) -> bool:
        """Check if two bounding boxes intersect"""
        return not (
            item_bbox.east < query_bbox.west or
            item_bbox.west > query_bbox.east or
            item_bbox.north < query_bbox.south or
            item_bbox.south > query_bbox.north
        )
    
    def _datetime_matches(self, item_datetime: str, query_datetime: str) -> bool:
        """Check if item datetime matches query (simplified)"""
        # TODO: Implement proper ISO 8601 interval parsing
        # For now, just check if item datetime contains query string
        return query_datetime in item_datetime
    
    def get_statistics(self) -> Dict:
        """Get STAC repository statistics"""
        try:
            collections = self.list_collections()
            total_collections = len(collections)
            total_items = sum(c.item_count for c in collections)
            
            return {
                "total_collections": total_collections,
                "total_items": total_items,
                "collections": [
                    {
                        "id": c.id,
                        "title": c.title,
                        "item_count": c.item_count,
                        "created_at": c.created_at
                    }
                    for c in collections
                ]
            }
            
        except Exception as e:
            self.logger.error(f"Error getting STAC statistics: {str(e)}")
            raise