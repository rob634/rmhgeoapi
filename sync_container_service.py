"""
Container Sync Service - Lists container contents and queues individual STAC cataloging jobs
Implements fan-out pattern for parallel processing in Azure Functions
"""
import json
import hashlib
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from services import BaseProcessingService
from repositories import StorageRepository, JobRepository, TaskRepository
from config import Config
from logger_setup import create_buffered_logger
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential
import base64

logger = create_buffered_logger(__name__)

# Geospatial file extensions to process
GEOSPATIAL_EXTENSIONS = {
    # Raster formats
    '.tif', '.tiff', '.geotiff',  # GeoTIFF
    '.jp2', '.j2k',                # JPEG2000
    '.img',                        # ERDAS Imagine
    '.hdf', '.hdf5', '.h5',        # HDF
    '.nc',                         # NetCDF
    '.grib', '.grib2',             # GRIB
    '.vrt',                        # GDAL Virtual
    
    # Vector formats
    '.geojson', '.json',           # GeoJSON
    '.shp',                        # Shapefile (would need accompanying files)
    '.gpkg',                       # GeoPackage
    '.kml', '.kmz',                # KML/KMZ
    '.gml',                        # GML
    '.mbtiles',                    # MBTiles
    
    # Cloud optimized
    '.cog',                        # Cloud Optimized GeoTIFF
    '.zarr',                       # Zarr
}


class SyncContainerService(BaseProcessingService):
    """
    Service to sync container contents to STAC catalog
    Lists all files and queues individual cataloging jobs
    """
    
    def __init__(self):
        self.logger = create_buffered_logger(
            name=f"{__name__}.SyncContainerService",
            capacity=100,
            flush_level=logging.INFO
        )
        self.storage_repo = StorageRepository()
        self.job_repo = JobRepository()
        self.task_repo = TaskRepository()
        
        # Initialize queue service for sending task messages
        account_url = Config.get_storage_account_url('queue')
        self.queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return ["sync_container"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process container sync operation
        
        Args:
            job_id: Unique job identifier
            dataset_id: Container name to sync (e.g., 'rmhazuregeobronze')
            resource_id: Filter prefix or 'full_sync' for all files
            version_id: Collection to catalog into (e.g., 'bronze-assets' or 'v1')
            operation_type: Should be 'sync_container'
            
        Returns:
            Dict with sync results
        """
        self.logger.info(f"Starting container sync for {dataset_id}")
        
        # Determine target collection based on container name
        collection_id = self._determine_collection(dataset_id, version_id)
        
        try:
            # Check if we have a recent inventory in blob storage
            from blob_inventory_service import BlobInventoryService
            inventory_service = BlobInventoryService()
            
            self.logger.info(f"Checking for existing inventory of container: {dataset_id}")
            
            # Try to get existing inventory first (geo files only for sync)
            inventory = inventory_service.get_inventory(dataset_id, geo_only=True)
            
            if inventory and inventory.get('files'):
                # Use existing inventory
                self.logger.info(f"Using existing inventory from {inventory.get('scan_time')}")
                files = inventory['files']
            else:
                # No inventory exists, need to list and store
                self.logger.info(f"No inventory found, listing container: {dataset_id}")
                
                contents = self.storage_repo.list_container_contents(
                    container_name=dataset_id
                )
                
                if not contents or 'blobs' not in contents:
                    return {
                        "status": "completed",
                        "message": f"No files found in container {dataset_id}",
                        "files_found": 0,
                        "jobs_queued": 0
                    }
                
                # Store inventory for future use
                summary = inventory_service.store_inventory(
                    container_name=dataset_id,
                    files=contents['blobs']
                )
                self.logger.info(f"Stored new inventory with {summary['total_files']} files")
                
                # Get the geospatial-only inventory we just created
                inventory = inventory_service.get_inventory(dataset_id, geo_only=True)
                files = inventory['files'] if inventory else []
            
            self.logger.info(f"Found {len(files)} geospatial files to process")
            
            # Files are already filtered as geospatial from inventory
            geospatial_files = files
            
            # Create tasks for individual file cataloging
            created_tasks = []
            skipped_files = []
            errors = []
            
            for file_info in geospatial_files:
                try:
                    # Generate task ID based on file path and operation
                    task_params = {
                        "parent_job_id": job_id,
                        "dataset_id": dataset_id,
                        "resource_id": file_info['name'],
                        "operation_type": "catalog_file"
                    }
                    param_str = json.dumps(task_params, sort_keys=True)
                    task_id = hashlib.sha256(param_str.encode()).hexdigest()
                    
                    # Check if task already exists
                    existing_task = self.task_repo.get_task(task_id)
                    
                    if existing_task and existing_task.get('status') in ['completed', 'processing', 'queued']:
                        self.logger.debug(f"Task already exists for {file_info['name']}, skipping")
                        skipped_files.append({
                            "file": file_info['name'],
                            "reason": f"Task already {existing_task.get('status')}",
                            "task_id": task_id
                        })
                        continue
                    
                    # Create the task data
                    task_data = {
                        'operation_type': 'catalog_file',
                        'dataset_id': dataset_id,
                        'resource_id': file_info['name'],
                        'version_id': collection_id,
                        'file_size': file_info.get('size', 0),
                        'file_path': file_info['name'],
                        'priority': 1  # Default priority
                    }
                    
                    # Create task in table storage
                    task_created = self.task_repo.create_task(task_id, job_id, task_data)
                    
                    if task_created:
                        # Queue the task for processing
                        queue_message = {
                            "task_id": task_id,
                            "parent_job_id": job_id,
                            "operation_type": "catalog_file",
                            "dataset_id": dataset_id,
                            "resource_id": file_info['name'],
                            "version_id": collection_id,
                            "created_at": datetime.now(timezone.utc).isoformat()
                        }
                        
                        # Send to a separate tasks queue (or same queue with task marker)
                        tasks_queue = self.queue_service.get_queue_client("geospatial-tasks")
                        
                        # Encode message to Base64 as expected by Azure Functions
                        message_json = json.dumps(queue_message)
                        encoded_message = base64.b64encode(message_json.encode('utf-8')).decode('ascii')
                        tasks_queue.send_message(encoded_message)
                        
                        # Update task status to queued
                        self.task_repo.update_task_status(task_id, "queued")
                        
                        created_tasks.append({
                            "task_id": task_id,
                            "file": file_info['name'],
                            "size": file_info.get('size', 0)
                        })
                    
                    self.logger.debug(f"Queued catalog job for {file_info['name']}")
                    
                except Exception as e:
                    self.logger.error(f"Error queuing job for {file_info['name']}: {str(e)}")
                    errors.append({
                        "file": file_info['name'],
                        "error": str(e)
                    })
            
            # Prepare result summary - limit size to avoid Table Storage limits
            result = {
                "status": "completed",
                "message": f"Container sync completed for {dataset_id}",
                "summary": {
                    "container": dataset_id,
                    "collection": collection_id,
                    "total_files": len(files),
                    "geospatial_files": len(geospatial_files),
                    "tasks_created": len(created_tasks),
                    "files_skipped": len(skipped_files),
                    "errors": len(errors)
                },
                "file_types": self._analyze_file_types(geospatial_files)
            }
            
            # Only include samples to avoid exceeding storage limits
            if created_tasks:
                result["sample_tasks"] = [
                    {"file": t["file"], "task_id": t["task_id"][:8] + "..."} 
                    for t in created_tasks[:5]
                ]
                
            if errors:
                result["sample_errors"] = errors[:5]
                
            if len(created_tasks) > 5:
                result["note"] = f"Showing sample of {len(created_tasks)} created tasks"
            
            self.logger.info(
                f"Sync complete: {len(created_tasks)} tasks created, "
                f"{len(skipped_files)} skipped, {len(errors)} errors"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in container sync: {str(e)}")
            return {
                "status": "failed",
                "message": f"Container sync failed: {str(e)}",
                "error": str(e)
            }
    
    def _determine_collection(self, container_name: str, version_id: str) -> str:
        """
        Determine the target STAC collection based on container and version
        
        Args:
            container_name: Name of the storage container
            version_id: Version ID from job parameters
            
        Returns:
            Collection ID for STAC cataloging
        """
        # If version_id looks like a collection name, use it
        if version_id and version_id.endswith('-assets'):
            return version_id
        
        # Map containers to default collections
        container_mapping = {
            'rmhazuregeobronze': 'bronze-assets',
            'rmhazuregeosilver': 'silver-assets',
            'rmhazuregeogold': 'gold-assets'
        }
        
        return container_mapping.get(container_name, 'bronze-assets')
    
    def _filter_geospatial_files(self, files: List[Dict]) -> List[Dict]:
        """
        Filter files to only include geospatial formats
        
        Args:
            files: List of file info dictionaries
            
        Returns:
            List of geospatial files
        """
        geospatial_files = []
        
        for file_info in files:
            file_name = file_info.get('name', '').lower()
            
            # Check if file has a geospatial extension
            for ext in GEOSPATIAL_EXTENSIONS:
                if file_name.endswith(ext):
                    geospatial_files.append(file_info)
                    break
        
        return geospatial_files
    
    def _analyze_file_types(self, files: List[Dict]) -> Dict:
        """
        Analyze the types of files being processed
        
        Args:
            files: List of file info dictionaries
            
        Returns:
            Dictionary with file type statistics
        """
        file_types = {}
        
        for file_info in files:
            file_name = file_info.get('name', '').lower()
            
            # Extract extension
            if '.' in file_name:
                ext = '.' + file_name.rsplit('.', 1)[-1]
                file_types[ext] = file_types.get(ext, 0) + 1
            else:
                file_types['no_extension'] = file_types.get('no_extension', 0) + 1
        
        return file_types