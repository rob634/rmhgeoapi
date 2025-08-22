"""
Blob Inventory Service - Stores container listings as JSON in blob storage
Solves the problem of large container listings exceeding Table Storage limits
"""
import json
import gzip
from typing import Dict, List, Optional
from datetime import datetime, timezone
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from config import Config
from logger_setup import logger


class BlobInventoryService:
    """
    Service for storing and retrieving container inventories in blob storage
    Handles large file listings that exceed Table Storage limits
    """
    
    def __init__(self):
        self.inventory_container = "rmhazuregeoinventory"
        account_url = Config.get_storage_account_url('blob')
        self.blob_service = BlobServiceClient(account_url, credential=DefaultAzureCredential())
        self._ensure_container_exists()
    
    def _ensure_container_exists(self):
        """Create inventory container if it doesn't exist"""
        try:
            container_client = self.blob_service.get_container_client(self.inventory_container)
            if not container_client.exists():
                container_client.create_container()
                logger.info(f"Created inventory container: {self.inventory_container}")
        except Exception as e:
            logger.error(f"Error ensuring inventory container exists: {e}")
    
    def store_inventory(self, container_name: str, files: List[Dict], 
                       metadata: Optional[Dict] = None) -> Dict:
        """
        Store container inventory as compressed JSON in blob storage
        
        Args:
            container_name: Name of the container being inventoried
            files: List of file dictionaries with metadata
            metadata: Optional additional metadata to store
            
        Returns:
            Dict with summary and blob URLs
        """
        try:
            scan_time = datetime.now(timezone.utc).isoformat()
            
            # Create full inventory object
            inventory = {
                "version": "1.0",
                "container": container_name,
                "scan_time": scan_time,
                "total_files": len(files),
                "total_size_bytes": sum(f.get('size', 0) for f in files),
                "files": files
            }
            
            if metadata:
                inventory["metadata"] = metadata
            
            # Calculate statistics
            total_size_gb = inventory["total_size_bytes"] / (1024**3)
            
            # Categorize files
            geospatial_extensions = {'.tif', '.tiff', '.geotiff', '.cog', '.jp2', 
                                    '.geojson', '.json', '.gpkg', '.shp', '.kml', 
                                    '.kmz', '.gml', '.mbtiles'}
            
            geospatial_files = []
            other_files = []
            
            for f in files:
                name = f.get('name', '').lower()
                is_geo = any(name.endswith(ext) for ext in geospatial_extensions)
                if is_geo:
                    geospatial_files.append(f)
                else:
                    other_files.append(f)
            
            # Store full inventory (compressed)
            full_blob_name = f"current/{container_name}.json.gz"
            full_url = self._store_compressed_json(full_blob_name, inventory)
            
            # Store geospatial-only inventory (compressed)
            geo_inventory = {
                **inventory,
                "files": geospatial_files,
                "total_files": len(geospatial_files),
                "total_size_bytes": sum(f.get('size', 0) for f in geospatial_files)
            }
            geo_blob_name = f"current/{container_name}_geo.json.gz"
            geo_url = self._store_compressed_json(geo_blob_name, geo_inventory)
            
            # Create summary (this is what goes in Table Storage)
            summary = {
                "container": container_name,
                "scan_time": scan_time,
                "total_files": len(files),
                "geospatial_files": len(geospatial_files),
                "other_files": len(other_files),
                "total_size_gb": round(total_size_gb, 2),
                "inventory_urls": {
                    "full": full_url,
                    "geospatial": geo_url
                },
                "file_extensions": self._count_extensions(files)
            }
            
            # Also store uncompressed summary for quick access
            summary_blob_name = f"current/{container_name}_summary.json"
            summary_url = self._store_json(summary_blob_name, summary)
            summary["summary_url"] = summary_url
            
            logger.info(f"Stored inventory for {container_name}: {len(files)} files, "
                       f"{len(geospatial_files)} geospatial")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error storing inventory: {str(e)}")
            raise
    
    def get_inventory(self, container_name: str, geo_only: bool = False) -> Optional[Dict]:
        """
        Retrieve inventory from blob storage
        
        Args:
            container_name: Name of the container
            geo_only: If True, get geospatial-only inventory
            
        Returns:
            Inventory dict or None if not found
        """
        try:
            blob_name = f"current/{container_name}{'_geo' if geo_only else ''}.json.gz"
            
            blob_client = self.blob_service.get_blob_client(
                container=self.inventory_container,
                blob=blob_name
            )
            
            if not blob_client.exists():
                logger.warning(f"Inventory not found: {blob_name}")
                return None
            
            # Download and decompress
            compressed_data = blob_client.download_blob().readall()
            json_data = gzip.decompress(compressed_data).decode('utf-8')
            inventory = json.loads(json_data)
            
            logger.info(f"Retrieved inventory for {container_name}: "
                       f"{inventory.get('total_files', 0)} files")
            
            return inventory
            
        except Exception as e:
            logger.error(f"Error retrieving inventory: {str(e)}")
            return None
    
    def get_summary(self, container_name: str) -> Optional[Dict]:
        """
        Get just the summary (lightweight)
        
        Args:
            container_name: Name of the container
            
        Returns:
            Summary dict or None if not found
        """
        try:
            blob_name = f"current/{container_name}_summary.json"
            
            blob_client = self.blob_service.get_blob_client(
                container=self.inventory_container,
                blob=blob_name
            )
            
            if not blob_client.exists():
                return None
            
            json_data = blob_client.download_blob().readall()
            summary = json.loads(json_data)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error retrieving summary: {str(e)}")
            return None
    
    def _store_compressed_json(self, blob_name: str, data: Dict) -> str:
        """Store compressed JSON to blob"""
        json_str = json.dumps(data, separators=(',', ':'))  # Compact JSON
        compressed = gzip.compress(json_str.encode('utf-8'), compresslevel=9)
        
        blob_client = self.blob_service.get_blob_client(
            container=self.inventory_container,
            blob=blob_name
        )
        
        blob_client.upload_blob(
            compressed, 
            overwrite=True
        )
        
        # Log compression ratio
        original_size = len(json_str)
        compressed_size = len(compressed)
        ratio = (1 - compressed_size / original_size) * 100
        logger.info(f"Stored {blob_name}: {compressed_size:,} bytes "
                   f"({ratio:.1f}% compression)")
        
        return blob_client.url
    
    def _store_json(self, blob_name: str, data: Dict) -> str:
        """Store uncompressed JSON to blob"""
        json_str = json.dumps(data, indent=2)
        
        blob_client = self.blob_service.get_blob_client(
            container=self.inventory_container,
            blob=blob_name
        )
        
        blob_client.upload_blob(
            json_str, 
            overwrite=True
        )
        
        return blob_client.url
    
    def _count_extensions(self, files: List[Dict]) -> Dict[str, int]:
        """Count file extensions"""
        extensions = {}
        for f in files:
            name = f.get('name', '')
            if '.' in name:
                ext = '.' + name.rsplit('.', 1)[-1].lower()
                extensions[ext] = extensions.get(ext, 0) + 1
            else:
                extensions['no_extension'] = extensions.get('no_extension', 0) + 1
        
        # Sort by count and limit to top 10
        sorted_ext = sorted(extensions.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_ext[:10])
    
    def delete_inventory(self, container_name: str) -> bool:
        """Delete all inventory files for a container"""
        try:
            container_client = self.blob_service.get_container_client(self.inventory_container)
            
            # List and delete all blobs for this container
            prefix = f"current/{container_name}"
            blobs = container_client.list_blobs(name_starts_with=prefix)
            
            count = 0
            for blob in blobs:
                blob_client = container_client.get_blob_client(blob.name)
                blob_client.delete_blob()
                count += 1
            
            logger.info(f"Deleted {count} inventory files for {container_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting inventory: {str(e)}")
            return False