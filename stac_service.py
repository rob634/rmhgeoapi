"""
STAC Service - Business logic layer for STAC operations
Integrates with the existing job processing system
"""
import json
import logging
from typing import Dict, List
from logging_utils import create_buffered_logger
from services import BaseProcessingService

from stac_repository import STACRepository
from stac_models import (
    STACCollection, STACItem, STACQuery, STACGeometry, 
    STACBoundingBox, STACAsset, STACLink
)


class STACService(BaseProcessingService):
    """Service for STAC operations integrated with job processing system"""
    
    def __init__(self):
        self.logger = create_buffered_logger(
            name=f"{__name__}.STACService",
            capacity=50,
            flush_level=logging.INFO
        )
        self.stac_repo = STACRepository()
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported STAC operations"""
        return [
            "stac_create_collection",
            "stac_ingest_item",
            "stac_search",
            "stac_get_collection",
            "stac_get_item",
            "stac_delete_item",
            "stac_delete_collection"
        ]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process STAC operations
        
        Args:
            job_id: Unique job identifier
            dataset_id: Used as collection_id or search parameters
            resource_id: Used as item_id or additional parameters
            version_id: Used for versioning or operation-specific data
            operation_type: STAC operation to perform
            
        Returns:
            Dict containing operation results
        """
        self.logger.info(f"Starting STAC operation: {operation_type}")
        
        try:
            if operation_type == "stac_create_collection":
                return self._create_collection(dataset_id, resource_id, version_id)
            
            elif operation_type == "stac_ingest_item":
                return self._ingest_item(dataset_id, resource_id, version_id)
            
            elif operation_type == "stac_search":
                return self._search_items(dataset_id, resource_id, version_id)
            
            elif operation_type == "stac_get_collection":
                return self._get_collection(dataset_id)
            
            elif operation_type == "stac_get_item":
                return self._get_item(dataset_id, resource_id)
            
            elif operation_type == "stac_delete_item":
                return self._delete_item(dataset_id, resource_id)
            
            elif operation_type == "stac_delete_collection":
                return self._delete_collection(dataset_id)
            
            else:
                raise ValueError(f"Unsupported STAC operation: {operation_type}")
        
        except Exception as e:
            self.logger.error(f"Error in STAC operation {operation_type}: {str(e)}")
            raise
    
    def _create_collection(self, collection_data: str, metadata: str, version: str) -> Dict:
        """
        Create a new STAC collection
        
        Args:
            collection_data: JSON string with collection details
            metadata: Additional metadata JSON string
            version: Collection version
        """
        try:
            # Parse collection data from dataset_id (JSON string)
            collection_info = json.loads(collection_data)
            
            # Create STAC collection
            collection = STACCollection(
                id=collection_info['id'],
                title=collection_info['title'],
                description=collection_info['description']
            )
            
            # Add optional metadata
            if 'license' in collection_info:
                collection.license = collection_info['license']
            if 'keywords' in collection_info:
                collection.keywords = collection_info['keywords']
            if 'providers' in collection_info:
                collection.providers = collection_info['providers']
            
            # Add spatial extent if provided
            if 'spatial_extent' in collection_info:
                bbox_data = collection_info['spatial_extent']
                bbox = STACBoundingBox(
                    west=bbox_data[0], south=bbox_data[1],
                    east=bbox_data[2], north=bbox_data[3]
                )
                collection.add_spatial_extent(bbox)
            
            # Add temporal extent if provided
            if 'temporal_extent' in collection_info:
                temporal = collection_info['temporal_extent']
                collection.add_temporal_extent(temporal.get('start'), temporal.get('end'))
            
            # Save collection
            is_new = self.stac_repo.save_collection(collection)
            
            self.logger.info(f"{'Created' if is_new else 'Updated'} STAC collection: {collection.id}")
            
            return {
                "status": "completed",
                "message": f"STAC collection {'created' if is_new else 'updated'} successfully",
                "collection": collection.to_stac_dict(),
                "is_new": is_new
            }
            
        except Exception as e:
            self.logger.error(f"Error creating STAC collection: {str(e)}")
            raise
    
    def _ingest_item(self, collection_id: str, item_data: str, assets_data: str) -> Dict:
        """
        Ingest a new STAC item
        
        Args:
            collection_id: ID of the collection for this item
            item_data: JSON string with item details
            assets_data: JSON string with asset information
        """
        try:
            # Parse item data
            item_info = json.loads(item_data)
            
            # Create geometry
            geometry = STACGeometry(
                type=item_info['geometry']['type'],
                coordinates=item_info['geometry']['coordinates']
            )
            
            # Create bounding box
            bbox = STACBoundingBox.from_list(item_info['bbox'])
            
            # Create STAC item
            item = STACItem(
                id=item_info['id'],
                collection_id=collection_id,
                geometry=geometry,
                bbox=bbox,
                datetime_str=item_info['datetime'],
                properties=item_info.get('properties', {})
            )
            
            # Add assets if provided
            if assets_data and assets_data != "none":
                assets_info = json.loads(assets_data)
                for asset_key, asset_data in assets_info.items():
                    asset = STACAsset(
                        href=asset_data['href'],
                        title=asset_data.get('title'),
                        description=asset_data.get('description'),
                        type=asset_data.get('type'),
                        roles=asset_data.get('roles')
                    )
                    item.add_asset(asset_key, asset)
            
            # Save item
            is_new = self.stac_repo.save_item(item)
            
            self.logger.info(f"{'Ingested' if is_new else 'Updated'} STAC item: {item.id}")
            
            return {
                "status": "completed",
                "message": f"STAC item {'ingested' if is_new else 'updated'} successfully",
                "item": item.to_stac_dict(),
                "is_new": is_new,
                "collection_id": collection_id
            }
            
        except Exception as e:
            self.logger.error(f"Error ingesting STAC item: {str(e)}")
            raise
    
    def _search_items(self, query_params: str, filters: str, options: str) -> Dict:
        """
        Search STAC items
        
        Args:
            query_params: JSON string with search parameters
            filters: Additional filters JSON string  
            options: Search options JSON string
        """
        try:
            # Parse query parameters
            query_data = json.loads(query_params) if query_params != "none" else {}
            
            # Create STAC query
            query = STACQuery(
                collections=query_data.get('collections'),
                bbox=STACBoundingBox.from_list(query_data['bbox']) if 'bbox' in query_data else None,
                datetime=query_data.get('datetime'),
                limit=query_data.get('limit', 10),
                offset=query_data.get('offset', 0),
                ids=query_data.get('ids')
            )
            
            # Validate query
            is_valid, error_msg = query.validate()
            if not is_valid:
                raise ValueError(f"Invalid STAC query: {error_msg}")
            
            # Execute search
            results = self.stac_repo.search_items(query)
            
            self.logger.info(f"STAC search returned {results['numberReturned']} items")
            
            return {
                "status": "completed",
                "message": f"STAC search completed - found {results['numberReturned']} items",
                "search_results": results,
                "query": query_data
            }
            
        except Exception as e:
            self.logger.error(f"Error searching STAC items: {str(e)}")
            raise
    
    def _get_collection(self, collection_id: str) -> Dict:
        """Get a specific STAC collection"""
        try:
            collection = self.stac_repo.get_collection(collection_id)
            
            if not collection:
                return {
                    "status": "completed",
                    "message": f"STAC collection not found: {collection_id}",
                    "collection": None,
                    "found": False
                }
            
            return {
                "status": "completed",
                "message": f"STAC collection retrieved: {collection_id}",
                "collection": collection.to_stac_dict(),
                "found": True
            }
            
        except Exception as e:
            self.logger.error(f"Error getting STAC collection {collection_id}: {str(e)}")
            raise
    
    def _get_item(self, collection_id: str, item_id: str) -> Dict:
        """Get a specific STAC item"""
        try:
            item = self.stac_repo.get_item(item_id, collection_id)
            
            if not item:
                return {
                    "status": "completed",
                    "message": f"STAC item not found: {item_id} in collection {collection_id}",
                    "item": None,
                    "found": False
                }
            
            return {
                "status": "completed",
                "message": f"STAC item retrieved: {item_id}",
                "item": item.to_stac_dict(),
                "found": True
            }
            
        except Exception as e:
            self.logger.error(f"Error getting STAC item {item_id}: {str(e)}")
            raise
    
    def _delete_item(self, collection_id: str, item_id: str) -> Dict:
        """Delete a STAC item"""
        try:
            deleted = self.stac_repo.delete_item(item_id, collection_id)
            
            return {
                "status": "completed",
                "message": f"STAC item {'deleted' if deleted else 'not found'}: {item_id}",
                "deleted": deleted,
                "item_id": item_id,
                "collection_id": collection_id
            }
            
        except Exception as e:
            self.logger.error(f"Error deleting STAC item {item_id}: {str(e)}")
            raise
    
    def _delete_collection(self, collection_id: str) -> Dict:
        """Delete a STAC collection"""
        try:
            deleted = self.stac_repo.delete_collection(collection_id)
            
            return {
                "status": "completed",
                "message": f"STAC collection {'deleted' if deleted else 'not found'}: {collection_id}",
                "deleted": deleted,
                "collection_id": collection_id
            }
            
        except Exception as e:
            self.logger.error(f"Error deleting STAC collection {collection_id}: {str(e)}")
            raise
    
    # Utility methods for STAC API endpoints
    
    def create_sample_collection(self) -> STACCollection:
        """Create a sample collection for testing"""
        collection = STACCollection(
            id="sample-imagery",
            title="Sample Satellite Imagery Collection",
            description="A sample collection of satellite imagery for testing STAC implementation"
        )
        
        collection.keywords = ["satellite", "imagery", "sample", "test"]
        collection.license = "CC-BY-4.0"
        collection.providers = [
            {
                "name": "Sample Data Provider",
                "roles": ["producer"],
                "url": "https://example.com"
            }
        ]
        
        # Add NYC area spatial extent
        nyc_bbox = STACBoundingBox(west=-74.25, south=40.5, east=-73.7, north=40.9)
        collection.add_spatial_extent(nyc_bbox)
        
        # Add temporal extent
        collection.add_temporal_extent("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z")
        
        return collection
    
    def create_sample_item(self, collection_id: str = "sample-imagery") -> STACItem:
        """Create a sample item for testing"""
        
        # Create geometry (point in NYC)
        geometry = STACGeometry(
            type="Point",
            coordinates=[-73.97, 40.76]  # Times Square
        )
        
        # Create bounding box around the point
        bbox = STACBoundingBox(west=-73.98, south=40.75, east=-73.96, north=40.77)
        
        # Create item
        item = STACItem(
            id="sample-item-001",
            collection_id=collection_id,
            geometry=geometry,
            bbox=bbox,
            datetime_str="2024-06-15T14:30:00Z",
            properties={
                "platform": "Landsat-8",
                "instruments": ["OLI", "TIRS"],
                "mission": "Landsat",
                "gsd": 30,
                "cloud_cover": 5.2
            }
        )
        
        # Add sample assets
        item.add_asset("thumbnail", STACAsset(
            href="https://example.com/sample-item-001/thumbnail.jpg",
            title="Thumbnail",
            type="image/jpeg",
            roles=["thumbnail"]
        ))
        
        item.add_asset("data", STACAsset(
            href="https://example.com/sample-item-001/data.tif",
            title="COG Data",
            type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"]
        ))
        
        return item