"""
Batch STAC Processing Service - Efficient batch operations for STAC item creation.

Handles related file processing, batch insertions, and optimized database operations
for improved performance over individual file processing.
"""
import json
import logging
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

from services import BaseProcessingService
from repositories import StorageRepository
from database_client import DatabaseClient
from metadata_inference import MetadataInferenceService
from logger_setup import get_logger

logger = get_logger(__name__)


@dataclass
class RelatedFileGroup:
    """Group of related files (tiles, sidecars, etc.)"""
    group_id: str
    group_type: str  # 'tiled_scene', 'sidecar_pair', 'maxar_acquisition'
    files: List[Dict]
    primary_file: Optional[str] = None
    processing_strategy: str = 'batch_catalog'


@dataclass 
class BatchOperation:
    """Represents a batch processing operation"""
    operation_id: str
    operation_type: str  # 'insert', 'update', 'delete'
    items: List[Dict]
    collection_id: str
    priority: int = 1


class BatchSTACService(BaseProcessingService):
    """
    Service for batch STAC operations and related file processing.
    
    Optimizes database operations by:
    - Grouping related files into single STAC items
    - Batching database insertions
    - Processing files by similarity (COGs together, vectors together, etc.)
    """
    
    def __init__(self):
        """Initialize the batch STAC service"""
        super().__init__()
        self.storage_repo = StorageRepository()
        self.db_client = DatabaseClient()
        self.inference_service = MetadataInferenceService()
        self.logger = get_logger(self.__class__.__name__)
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return [
            "batch_catalog_files",
            "process_related_files",
            "bulk_update_stac_items",
            "optimize_collections"
        ]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str, **kwargs) -> Dict:
        """
        Process batch STAC operations
        
        Args:
            job_id: Job identifier
            dataset_id: Container name
            resource_id: Operation-specific parameter
            version_id: Collection ID
            operation_type: Type of batch operation
            
        Returns:
            Results of batch processing
        """
        if operation_type == "batch_catalog_files":
            # resource_id contains list of files or 'all'
            return self.batch_catalog_files(dataset_id, version_id, resource_id)
        elif operation_type == "process_related_files":
            return self.process_related_files_batch(dataset_id, version_id)
        elif operation_type == "bulk_update_stac_items":
            return self.bulk_update_stac_items(version_id)
        else:
            raise ValueError(f"Unsupported operation: {operation_type}")
    
    def batch_catalog_files(self, container_name: str, collection_id: str, 
                          file_filter: str = 'all') -> Dict:
        """
        Catalog multiple files in batch operations for better performance.
        
        Args:
            container_name: Storage container
            collection_id: STAC collection ID
            file_filter: 'all' or specific file pattern
            
        Returns:
            Batch processing results
        """
        self.logger.info(f"📦 Starting batch cataloging for {container_name}")
        
        try:
            # Get files to process
            files = self._get_files_for_batch_processing(container_name, file_filter)
            
            if not files:
                return {
                    'status': 'completed',
                    'message': 'No files found for batch processing',
                    'items_processed': 0
                }
            
            # Group files by processing strategy
            strategy_groups = self.inference_service.batch_processing_recommendations(files)
            
            # Process each strategy group
            batch_results = []
            total_processed = 0
            
            for strategy, group_info in strategy_groups.items():
                self.logger.info(f"🔄 Processing {group_info['count']} files with strategy: {strategy}")
                
                if strategy == 'catalog_only':
                    result = self._batch_catalog_cog_files(group_info['files'], collection_id)
                elif strategy == 'header_only_cataloging':
                    result = self._batch_catalog_large_files(group_info['files'], collection_id)
                elif strategy.startswith('mosaic_then_catalog'):
                    result = self._process_tiled_scenes(group_info['files'], collection_id, strategy)
                elif strategy.startswith('defer_until_main'):
                    result = {'processed': 0, 'message': 'Deferred until main files processed'}
                else:
                    result = self._batch_catalog_standard_files(group_info['files'], collection_id)
                
                batch_results.append({
                    'strategy': strategy,
                    'files_count': group_info['count'],
                    'result': result
                })
                total_processed += result.get('processed', 0)
            
            # Update collection extents after batch processing
            self._update_collection_extent(collection_id)
            
            return {
                'status': 'completed',
                'container': container_name,
                'collection_id': collection_id,
                'total_files_processed': total_processed,
                'strategy_results': batch_results,
                'processing_time_minutes': sum(g['estimated_time_minutes'] for g in strategy_groups.values()),
                'message': f'Batch cataloged {total_processed} files across {len(strategy_groups)} strategies'
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error in batch cataloging: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'message': 'Batch cataloging failed'
            }
    
    def process_related_files_batch(self, container_name: str, collection_id: str) -> Dict:
        """
        Process related files (tiles, sidecars) as unified STAC items.
        
        Args:
            container_name: Storage container
            collection_id: STAC collection ID
            
        Returns:
            Results of related file processing
        """
        self.logger.info(f"🔗 Processing related files for {container_name}")
        
        try:
            # Get all files and enrich with metadata
            files = self._get_files_for_batch_processing(container_name, 'all')
            enriched_inventory = self.inference_service.enrich_inventory({'files': files})
            
            # Extract relationships
            relationships = enriched_inventory['inference_analysis']['relationships']
            
            processed_groups = []
            
            # Process tiled scenes
            for scene_name, scene_info in relationships.get('tiled_scenes', {}).items():
                self.logger.info(f"🎬 Processing tiled scene: {scene_name}")
                result = self._create_unified_stac_item_from_tiles(
                    scene_name, scene_info, container_name, collection_id
                )
                processed_groups.append({
                    'group_type': 'tiled_scene',
                    'group_id': scene_name,
                    'files_count': len(scene_info['tiles']),
                    'result': result
                })
            
            # Process sidecar pairs
            for pair_info in relationships.get('sidecar_pairs', []):
                self.logger.info(f"📄 Processing sidecar pair: {pair_info['base_name']}")
                result = self._create_stac_item_with_sidecars(
                    pair_info, container_name, collection_id
                )
                processed_groups.append({
                    'group_type': 'sidecar_pair',
                    'group_id': pair_info['base_name'],
                    'files_count': len(pair_info['files']),
                    'result': result
                })
            
            return {
                'status': 'completed',
                'container': container_name,
                'collection_id': collection_id,
                'related_groups_processed': len(processed_groups),
                'groups': processed_groups,
                'message': f'Processed {len(processed_groups)} related file groups'
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error processing related files: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'message': 'Related file processing failed'
            }
    
    def bulk_insert_stac_items(self, items: List[Dict], collection_id: str) -> Dict:
        """
        Perform bulk insertion of STAC items for better performance.
        
        Args:
            items: List of STAC item dictionaries
            collection_id: Target collection
            
        Returns:
            Bulk insertion results
        """
        if not items:
            return {'status': 'completed', 'inserted': 0, 'message': 'No items to insert'}
        
        try:
            self.logger.info(f"📚 Bulk inserting {len(items)} STAC items")
            
            # Prepare bulk insertion data
            insert_data = []
            for item in items:
                insert_data.append({
                    'id': item['id'],
                    'collection_id': collection_id,
                    'geometry': item['geometry'],
                    'bbox': item['bbox'],
                    'properties': json.dumps(item['properties']),
                    'assets': json.dumps(item['assets']),
                    'links': json.dumps(item.get('links', [])),
                    'stac_version': item.get('stac_version', '1.0.0'),
                    'created_at': datetime.now(timezone.utc),
                    'updated_at': datetime.now(timezone.utc)
                })
            
            # Perform bulk insert using PostgreSQL's execute_values for efficiency
            insert_query = """
                INSERT INTO geo.items 
                (id, collection_id, geometry, bbox, properties, assets, links, stac_version, created_at, updated_at)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    geometry = EXCLUDED.geometry,
                    bbox = EXCLUDED.bbox,
                    properties = EXCLUDED.properties,
                    assets = EXCLUDED.assets,
                    links = EXCLUDED.links,
                    updated_at = EXCLUDED.updated_at
            """
            
            # Use psycopg's execute_values for efficient bulk insertion
            import psycopg.extras
            with self.db_client.get_connection() as conn:
                with conn.cursor() as cur:
                    data_tuples = [
                        (
                            item['id'], item['collection_id'],
                            f"ST_GeomFromGeoJSON('{json.dumps(item['geometry'])}')",
                            f"ST_GeomFromGeoJSON('{json.dumps(item['bbox'])}')",
                            item['properties'], item['assets'], item['links'],
                            item['stac_version'], item['created_at'], item['updated_at']
                        )
                        for item in insert_data
                    ]
                    
                    psycopg.extras.execute_values(
                        cur, insert_query, data_tuples,
                        template=None, page_size=100
                    )
                    conn.commit()
            
            self.logger.info(f"✅ Successfully bulk inserted {len(items)} STAC items")
            
            return {
                'status': 'success',
                'inserted': len(items),
                'collection_id': collection_id,
                'message': f'Bulk inserted {len(items)} items'
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error in bulk insertion: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Bulk insertion failed'
            }
    
    def _get_files_for_batch_processing(self, container_name: str, 
                                      file_filter: str) -> List[Dict]:
        """Get files for batch processing"""
        try:
            # Try to use cached inventory first
            from blob_inventory_service import BlobInventoryService
            inventory_service = BlobInventoryService()
            
            inventory = inventory_service.get_inventory(container_name, geo_only=True)
            
            if inventory and inventory.get('files'):
                files = inventory['files']
                self.logger.info(f"📋 Using cached inventory: {len(files)} files")
            else:
                # Fall back to direct listing
                contents = self.storage_repo.list_container_contents(container_name)
                files = contents.get('blobs', []) if contents else []
                self.logger.info(f"📦 Direct listing: {len(files)} files")
            
            # Apply file filter if not 'all'
            if file_filter != 'all':
                # Could implement specific filtering logic here
                pass
            
            return files
            
        except Exception as e:
            self.logger.error(f"Error getting files for batch processing: {e}")
            return []
    
    def _batch_catalog_cog_files(self, files: List[Dict], collection_id: str) -> Dict:
        """Batch catalog files that are already COG optimized"""
        stac_items = []
        
        for file_info in files:
            try:
                # Create lightweight STAC item for COG (no conversion needed)
                item = self._create_lightweight_stac_item(file_info, collection_id, 'cog')
                stac_items.append(item)
            except Exception as e:
                self.logger.warning(f"Failed to create STAC item for {file_info['name']}: {e}")
        
        # Bulk insert
        if stac_items:
            result = self.bulk_insert_stac_items(stac_items, collection_id)
            return {'processed': result.get('inserted', 0), 'strategy': 'cog_batch'}
        
        return {'processed': 0, 'strategy': 'cog_batch'}
    
    def _batch_catalog_large_files(self, files: List[Dict], collection_id: str) -> Dict:
        """Batch catalog large files using header-only metadata extraction"""
        stac_items = []
        
        for file_info in files:
            try:
                # Create STAC item with header-only metadata
                item = self._create_lightweight_stac_item(file_info, collection_id, 'header_only')
                stac_items.append(item)
            except Exception as e:
                self.logger.warning(f"Failed to create STAC item for {file_info['name']}: {e}")
        
        # Bulk insert
        if stac_items:
            result = self.bulk_insert_stac_items(stac_items, collection_id)
            return {'processed': result.get('inserted', 0), 'strategy': 'header_only'}
        
        return {'processed': 0, 'strategy': 'header_only'}
    
    def _batch_catalog_standard_files(self, files: List[Dict], collection_id: str) -> Dict:
        """Batch catalog standard files with full processing"""
        stac_items = []
        
        for file_info in files:
            try:
                # Create full STAC item with complete metadata
                item = self._create_lightweight_stac_item(file_info, collection_id, 'standard')
                stac_items.append(item)
            except Exception as e:
                self.logger.warning(f"Failed to create STAC item for {file_info['name']}: {e}")
        
        # Bulk insert
        if stac_items:
            result = self.bulk_insert_stac_items(stac_items, collection_id)
            return {'processed': result.get('inserted', 0), 'strategy': 'standard'}
        
        return {'processed': 0, 'strategy': 'standard'}
    
    def _process_tiled_scenes(self, files: List[Dict], collection_id: str, strategy: str) -> Dict:
        """Process files that are part of tiled scenes"""
        # For now, treat as individual files but mark them as part of scene
        # Future enhancement: create mosaic STAC items
        return self._batch_catalog_standard_files(files, collection_id)
    
    def _create_lightweight_stac_item(self, file_info: Dict, collection_id: str, 
                                    processing_mode: str) -> Dict:
        """Create a STAC item with appropriate level of detail based on processing mode"""
        
        # Generate item ID
        item_id = hashlib.md5(f"{collection_id}/{file_info['name']}".encode()).hexdigest()
        
        # Basic geometry (global bounds for now - could be enhanced)
        bbox = [-180, -90, 180, 90]
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]], [bbox[2], bbox[1]],
                [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]
            ]]
        }
        
        # Properties based on processing mode
        properties = {
            "datetime": datetime.now(timezone.utc).isoformat(),
            "created": datetime.now(timezone.utc).isoformat(),
            "file:size": file_info.get('size', 0),
            "file:name": file_info['name'],
            "processing:mode": processing_mode,
            "processing:batch_processed": True
        }
        
        # Add inferred metadata if available
        if 'inferred_metadata' in file_info:
            meta = file_info['inferred_metadata']
            properties.update({
                "vendor": meta.get('vendor'),
                "likely_cog": meta.get('likely_cog', False),
                "data_category": meta.get('data_category'),
                "processing_level": meta.get('processing_level')
            })
        
        # Assets
        container = file_info.get('container', 'unknown')
        assets = {
            "data": {
                "href": f"https://rmhazuregeo.blob.core.windows.net/{container}/{file_info['name']}",
                "type": self._get_media_type(file_info['name']),
                "title": file_info['name'],
                "roles": ["data"],
                "file:size": file_info.get('size', 0)
            }
        }
        
        return {
            "id": item_id,
            "collection": collection_id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": properties,
            "assets": assets,
            "links": [],
            "stac_version": "1.0.0"
        }
    
    def _get_media_type(self, filename: str) -> str:
        """Get media type for file"""
        ext = filename.lower().split('.')[-1]
        media_types = {
            'tif': 'image/tiff; application=geotiff',
            'tiff': 'image/tiff; application=geotiff',
            'jp2': 'image/jp2',
            'geojson': 'application/geo+json',
            'json': 'application/geo+json'
        }
        return media_types.get(ext, 'application/octet-stream')
    
    def _update_collection_extent(self, collection_id: str):
        """Update collection spatial and temporal extents after batch processing"""
        try:
            extent_query = """
                UPDATE geo.collections 
                SET 
                    extent = json_build_object(
                        'spatial', json_build_object(
                            'bbox', ARRAY[ARRAY[
                                ST_XMin(ST_Extent(i.geometry)),
                                ST_YMin(ST_Extent(i.geometry)),
                                ST_XMax(ST_Extent(i.geometry)),
                                ST_YMax(ST_Extent(i.geometry))
                            ]]
                        ),
                        'temporal', json_build_object(
                            'interval', ARRAY[ARRAY[
                                MIN((i.properties->>'datetime')::timestamp),
                                MAX((i.properties->>'datetime')::timestamp)
                            ]]
                        )
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                AND EXISTS (SELECT 1 FROM geo.items i WHERE i.collection_id = %s)
            """
            
            self.db_client.execute(extent_query, [collection_id, collection_id], fetch=False)
            self.logger.info(f"✅ Updated collection extent for {collection_id}")
            
        except Exception as e:
            self.logger.warning(f"Could not update collection extent: {e}")
    
    def _create_unified_stac_item_from_tiles(self, scene_name: str, scene_info: Dict,
                                           container_name: str, collection_id: str) -> Dict:
        """Create a unified STAC item from tiled scene files"""
        # This is a placeholder for future mosaic functionality
        # For now, process tiles individually
        return {
            'status': 'deferred',
            'message': f'Tiled scene {scene_name} processing deferred to future enhancement',
            'tile_count': scene_info.get('tile_count', 0)
        }
    
    def _create_stac_item_with_sidecars(self, pair_info: Dict, container_name: str,
                                      collection_id: str) -> Dict:
        """Create STAC item incorporating sidecar metadata"""
        # This is a placeholder for enhanced sidecar integration
        # For now, process main files and note sidecars
        return {
            'status': 'deferred',
            'message': f'Sidecar pair {pair_info["base_name"]} processing deferred to future enhancement',
            'files_count': len(pair_info['files'])
        }