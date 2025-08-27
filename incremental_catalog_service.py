"""
Incremental Cataloging Service - Tracks and processes only changed files.

Provides differential updates to STAC catalog by comparing container contents
with existing catalog entries to identify new, modified, or deleted files.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from services import BaseProcessingService
from repositories import StorageRepository
from database_client import DatabaseClient
from logger_setup import get_logger

logger = get_logger(__name__)


@dataclass
class FileChangeInfo:
    """Information about a file change"""
    file_path: str
    change_type: str  # 'new', 'modified', 'deleted', 'unchanged'
    last_modified: Optional[datetime]
    size: Optional[int]
    stac_updated_at: Optional[datetime]
    priority: int = 1  # Processing priority (1=high, 5=low)


class IncrementalCatalogService(BaseProcessingService):
    """
    Service for incremental STAC cataloging.
    
    Identifies changes between container contents and STAC catalog,
    enabling efficient processing of only modified files.
    """
    
    def __init__(self):
        """Initialize the incremental catalog service"""
        super().__init__()
        self.storage_repo = StorageRepository()
        self.db_client = DatabaseClient()
        self.logger = get_logger(self.__class__.__name__)
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return [
            "analyze_changes",
            "get_incremental_updates",
            "mark_files_processed"
        ]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process incremental cataloging operations
        
        Args:
            job_id: Job identifier
            dataset_id: Container name
            resource_id: Operation specific parameter
            version_id: Collection ID
            operation_type: Type of incremental operation
            
        Returns:
            Results of incremental analysis
        """
        if operation_type == "analyze_changes":
            return self.analyze_container_changes(dataset_id, version_id)
        elif operation_type == "get_incremental_updates":
            max_age_hours = int(resource_id) if resource_id.isdigit() else 24
            return self.get_files_needing_update(dataset_id, max_age_hours)
        else:
            raise ValueError(f"Unsupported operation: {operation_type}")
    
    def analyze_container_changes(self, container_name: str, 
                                collection_id: str = None) -> Dict:
        """
        Analyze changes between container contents and STAC catalog.
        
        Args:
            container_name: Name of storage container
            collection_id: STAC collection to compare against
            
        Returns:
            Analysis of changes with processing recommendations
        """
        self.logger.info(f"🔄 Analyzing changes for container: {container_name}")
        
        try:
            # Get current container contents
            self.logger.info("📦 Fetching current container contents...")
            container_contents = self.storage_repo.list_container_contents(container_name)
            
            if not container_contents or 'blobs' not in container_contents:
                return {
                    'status': 'completed',
                    'message': f'No files found in container {container_name}',
                    'changes': []
                }
            
            current_files = {blob['name']: blob for blob in container_contents['blobs']}
            
            # Get existing STAC items for this collection/container
            self.logger.info("🗄️ Fetching existing STAC catalog entries...")
            existing_items = self._get_existing_stac_items(container_name, collection_id)
            
            # Analyze changes
            changes = self._compare_files_with_catalog(current_files, existing_items)
            
            # Generate processing recommendations
            recommendations = self._generate_processing_recommendations(changes)
            
            # Calculate statistics
            stats = self._calculate_change_statistics(changes)
            
            result = {
                'status': 'completed',
                'container': container_name,
                'collection_id': collection_id,
                'analysis_timestamp': datetime.now(timezone.utc).isoformat(),
                'statistics': stats,
                'changes': [self._serialize_change(change) for change in changes],
                'recommendations': recommendations,
                'message': f"Found {stats['total_changes']} changes requiring processing"
            }
            
            self.logger.info(f"✅ Analysis complete: {stats['total_changes']} changes found")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error analyzing container changes: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'message': 'Failed to analyze container changes'
            }
    
    def get_files_needing_update(self, container_name: str, 
                               max_age_hours: int = 24) -> List[str]:
        """
        Get list of files that need cataloging based on modification time.
        
        Args:
            container_name: Container to check
            max_age_hours: Consider files modified within this many hours
            
        Returns:
            List of file paths that need processing
        """
        try:
            # Get recent changes
            changes = self.analyze_container_changes(container_name)
            
            if changes['status'] != 'completed':
                return []
            
            # Filter for files that need processing
            files_needing_update = []
            
            for change_data in changes['changes']:
                change_type = change_data['change_type']
                
                if change_type in ['new', 'modified']:
                    # Check if within time window
                    if change_data.get('last_modified'):
                        mod_time = datetime.fromisoformat(change_data['last_modified'].replace('Z', '+00:00'))
                        hours_ago = (datetime.now(timezone.utc) - mod_time).total_seconds() / 3600
                        
                        if hours_ago <= max_age_hours:
                            files_needing_update.append(change_data['file_path'])
                    else:
                        # No timestamp, assume it needs processing
                        files_needing_update.append(change_data['file_path'])
            
            self.logger.info(f"📝 Found {len(files_needing_update)} files needing update")
            return files_needing_update
            
        except Exception as e:
            self.logger.error(f"❌ Error getting files for update: {e}")
            return []
    
    def should_refresh_inventory(self, container_name: str) -> bool:
        """
        Check if inventory needs refresh based on age and completeness.
        
        Args:
            container_name: Container to check
            
        Returns:
            True if inventory should be refreshed
        """
        try:
            # Check if we have a blob inventory service
            from blob_inventory_service import BlobInventoryService
            inventory_service = BlobInventoryService()
            
            # Get existing inventory
            inventory = inventory_service.get_inventory(container_name)
            if not inventory:
                self.logger.info(f"📦 No inventory found for {container_name} - refresh needed")
                return True
            
            # Check age - refresh if older than 6 hours
            scan_time_str = inventory.get('scan_time')
            if scan_time_str:
                scan_time = datetime.fromisoformat(scan_time_str.replace('Z', '+00:00'))
                age_hours = (datetime.now(timezone.utc) - scan_time).total_seconds() / 3600
                
                if age_hours > 6:
                    self.logger.info(f"⏰ Inventory is {age_hours:.1f} hours old - refresh needed")
                    return True
            
            # Check completeness - refresh if missing geo-only index
            if not inventory_service.has_geo_index(container_name):
                self.logger.info(f"📋 Missing geo index for {container_name} - refresh needed")
                return True
            
            self.logger.info(f"✅ Inventory for {container_name} is fresh and complete")
            return False
            
        except Exception as e:
            self.logger.warning(f"⚠️ Could not check inventory status: {e}")
            return True  # Default to refresh on error
    
    def _get_existing_stac_items(self, container_name: str, 
                               collection_id: str = None) -> Dict[str, Dict]:
        """Get existing STAC items for comparison"""
        try:
            # Build query to get existing items
            query = """
                SELECT 
                    id,
                    properties->>'file:name' as file_path,
                    properties->>'file:container' as container,
                    updated_at,
                    created_at,
                    (properties->>'file:size')::bigint as file_size
                FROM geo.items 
                WHERE properties->>'file:container' = %s
            """
            params = [container_name]
            
            if collection_id:
                query += " AND collection_id = %s"
                params.append(collection_id)
            
            items = self.db_client.execute(query, params)
            
            # Index by file path for easy lookup
            items_by_path = {}
            for item in items:
                if item['file_path']:
                    items_by_path[item['file_path']] = item
            
            return items_by_path
            
        except Exception as e:
            self.logger.error(f"Error fetching existing STAC items: {e}")
            return {}
    
    def _compare_files_with_catalog(self, current_files: Dict, 
                                  existing_items: Dict) -> List[FileChangeInfo]:
        """Compare current files with cataloged items"""
        changes = []
        
        # Check for new and modified files
        for file_path, file_info in current_files.items():
            # Skip non-geospatial files
            if not self._is_geospatial_file(file_path):
                continue
            
            last_modified = file_info.get('last_modified')
            if isinstance(last_modified, str):
                last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
            
            if file_path not in existing_items:
                # New file
                changes.append(FileChangeInfo(
                    file_path=file_path,
                    change_type='new',
                    last_modified=last_modified,
                    size=file_info.get('size'),
                    stac_updated_at=None,
                    priority=1
                ))
            else:
                # Check if modified
                existing_item = existing_items[file_path]
                stac_updated = existing_item.get('updated_at')
                
                if isinstance(stac_updated, str):
                    stac_updated = datetime.fromisoformat(stac_updated.replace('Z', '+00:00'))
                
                # Compare modification times and sizes
                needs_update = False
                
                if last_modified and stac_updated:
                    # File is newer than catalog entry
                    if last_modified > stac_updated:
                        needs_update = True
                
                # Also check size differences
                catalog_size = existing_item.get('file_size')
                if catalog_size and file_info.get('size') != catalog_size:
                    needs_update = True
                
                if needs_update:
                    changes.append(FileChangeInfo(
                        file_path=file_path,
                        change_type='modified',
                        last_modified=last_modified,
                        size=file_info.get('size'),
                        stac_updated_at=stac_updated,
                        priority=2
                    ))
        
        # Check for deleted files (in catalog but not in container)
        for file_path in existing_items:
            if file_path not in current_files:
                existing_item = existing_items[file_path]
                stac_updated = existing_item.get('updated_at')
                if isinstance(stac_updated, str):
                    stac_updated = datetime.fromisoformat(stac_updated.replace('Z', '+00:00'))
                
                changes.append(FileChangeInfo(
                    file_path=file_path,
                    change_type='deleted',
                    last_modified=None,
                    size=None,
                    stac_updated_at=stac_updated,
                    priority=5  # Lower priority for deletions
                ))
        
        return changes
    
    def _is_geospatial_file(self, file_path: str) -> bool:
        """Check if file is a geospatial format"""
        geospatial_extensions = {
            '.tif', '.tiff', '.geotiff', '.jp2', '.j2k', '.img', 
            '.hdf', '.hdf5', '.h5', '.nc', '.grib', '.grib2', '.vrt',
            '.geojson', '.json', '.shp', '.gpkg', '.kml', '.kmz', '.gml',
            '.mbtiles', '.cog', '.zarr'
        }
        
        file_lower = file_path.lower()
        return any(file_lower.endswith(ext) for ext in geospatial_extensions)
    
    def _generate_processing_recommendations(self, changes: List[FileChangeInfo]) -> List[Dict]:
        """Generate processing recommendations based on changes"""
        recommendations = []
        
        new_files = [c for c in changes if c.change_type == 'new']
        modified_files = [c for c in changes if c.change_type == 'modified']
        deleted_files = [c for c in changes if c.change_type == 'deleted']
        
        if new_files:
            recommendations.append({
                'type': 'processing',
                'priority': 'high',
                'action': f'Process {len(new_files)} new files for STAC cataloging',
                'files_affected': len(new_files),
                'estimated_time_minutes': len(new_files) * 2  # Rough estimate
            })
        
        if modified_files:
            recommendations.append({
                'type': 'update',
                'priority': 'medium', 
                'action': f'Update {len(modified_files)} modified files in STAC catalog',
                'files_affected': len(modified_files),
                'estimated_time_minutes': len(modified_files) * 1.5
            })
        
        if deleted_files:
            recommendations.append({
                'type': 'cleanup',
                'priority': 'low',
                'action': f'Remove {len(deleted_files)} deleted files from STAC catalog',
                'files_affected': len(deleted_files),
                'estimated_time_minutes': len(deleted_files) * 0.5
            })
        
        # Large file recommendations
        large_files = [c for c in changes if c.size and c.size > 1024*1024*1024]  # >1GB
        if large_files:
            recommendations.append({
                'type': 'optimization',
                'priority': 'medium',
                'action': f'Use smart mode for {len(large_files)} large files (>1GB)',
                'files_affected': len(large_files),
                'note': 'Smart mode will use header-only metadata extraction'
            })
        
        return recommendations
    
    def _calculate_change_statistics(self, changes: List[FileChangeInfo]) -> Dict:
        """Calculate statistics about changes"""
        stats = {
            'total_changes': len(changes),
            'new_files': len([c for c in changes if c.change_type == 'new']),
            'modified_files': len([c for c in changes if c.change_type == 'modified']),
            'deleted_files': len([c for c in changes if c.change_type == 'deleted']),
            'total_size_mb': 0,
            'priority_breakdown': {}
        }
        
        # Calculate total size of changes
        for change in changes:
            if change.size:
                stats['total_size_mb'] += change.size / (1024 * 1024)
        
        # Priority breakdown
        for change in changes:
            priority = change.priority
            if priority not in stats['priority_breakdown']:
                stats['priority_breakdown'][priority] = 0
            stats['priority_breakdown'][priority] += 1
        
        stats['total_size_mb'] = round(stats['total_size_mb'], 2)
        
        return stats
    
    def _serialize_change(self, change: FileChangeInfo) -> Dict:
        """Serialize FileChangeInfo to dict"""
        return {
            'file_path': change.file_path,
            'change_type': change.change_type,
            'last_modified': change.last_modified.isoformat() if change.last_modified else None,
            'size': change.size,
            'stac_updated_at': change.stac_updated_at.isoformat() if change.stac_updated_at else None,
            'priority': change.priority
        }