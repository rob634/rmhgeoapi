"""
STAC cataloging service for COG outputs
Automatically catalogs successfully created COGs in the geo schema STAC tables
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import json
import hashlib
import rasterio
from rasterio.warp import transform_bounds

from config import Config
from database_client import STACDatabase

logger = logging.getLogger(__name__)


class STACCOGCataloger:
    """Service for cataloging COG outputs in STAC database"""
    
    def __init__(self):
        """Initialize with STAC database client"""
        self.db_client = STACDatabase(
            host=Config.POSTGIS_HOST,
            database=Config.POSTGIS_DATABASE,
            user=Config.POSTGIS_USER,
            password=Config.POSTGIS_PASSWORD,
            port=Config.POSTGIS_PORT,
            schema=Config.POSTGIS_SCHEMA or "geo"
        )
        self.default_collection = "silver-cogs"
        
    def ensure_collection_exists(self, collection_id: str = None) -> bool:
        """
        Ensure the COG collection exists in STAC
        
        Args:
            collection_id: Collection ID (defaults to 'silver-cogs')
            
        Returns:
            True if collection exists or was created
        """
        if collection_id is None:
            collection_id = self.default_collection
            
        # Check if collection exists
        existing = self.db_client.execute(
            f"SELECT id FROM {self.db_client.schema}.collections WHERE id = %s",
            (collection_id,),
            fetch=True
        )
        
        if existing:
            logger.info(f"STAC collection '{collection_id}' already exists")
            return True
            
        # Create collection for Silver tier COGs
        # Note: PostgreSQL array types need special handling
        collection_data = {
            'id': collection_id,
            'title': 'Silver Tier COGs',
            'description': 'Cloud Optimized GeoTIFFs processed to Silver tier (EPSG:4326)',
            'keywords': '{COG,raster,silver,EPSG:4326}',  # PostgreSQL array format
            'license': 'proprietary',
            'providers': json.dumps([{
                'name': 'RMH Geospatial Pipeline',
                'roles': ['processor', 'host']
            }]),
            'extent': json.dumps({
                'spatial': {'bbox': [[-180, -90, 180, 90]]},
                'temporal': {'interval': [[None, None]]}
            }),
            'summaries': json.dumps({
                'proj:epsg': [4326],
                'raster:bands': [],
                'file:size': []
            })
        }
        
        try:
            self.db_client.insert('collections', collection_data, schema_name=self.db_client.schema)
            logger.info(f"Created STAC collection '{collection_id}'")
            return True
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return False
    
    def catalog_cog(
        self,
        container_name: str,
        blob_name: str,
        source_info: Dict[str, Any],
        processing_info: Dict[str, Any],
        collection_id: str = None
    ) -> Dict[str, Any]:
        """
        Catalog a COG in the STAC database
        
        Args:
            container_name: Container where COG is stored (e.g., 'rmhazuregeosilver')
            blob_name: Name of the COG blob
            source_info: Information about the source file
            processing_info: Information about the processing (reprojection, COG conversion, etc.)
            collection_id: STAC collection ID (defaults to 'silver-cogs')
            
        Returns:
            Result dictionary with cataloging status
        """
        result = {
            "success": False,
            "errors": [],
            "warnings": [],
            "stac_item": None
        }
        
        if collection_id is None:
            collection_id = self.default_collection
            
        # Ensure collection exists
        if not self.ensure_collection_exists(collection_id):
            result["errors"].append(f"Failed to ensure collection '{collection_id}' exists")
            return result
            
        try:
            # Generate item ID (hash of container + blob name for uniqueness)
            item_id = hashlib.md5(f"{container_name}/{blob_name}".encode()).hexdigest()
            
            # Get COG metadata using rasterio
            from repositories import StorageRepository
            storage = StorageRepository()
            blob_url = storage.get_blob_sas_url(container_name, blob_name)
            
            with rasterio.open(blob_url) as src:
                # Get bounds in EPSG:4326
                bounds = src.bounds
                if src.crs and src.crs.to_epsg() != 4326:
                    # Transform bounds to EPSG:4326 if needed
                    # transform_bounds returns tuple (left, bottom, right, top)
                    left, bottom, right, top = transform_bounds(src.crs, 'EPSG:4326', *bounds)
                    bbox = [left, bottom, right, top]
                else:
                    # Use bounds object attributes
                    bbox = [bounds.left, bounds.bottom, bounds.right, bounds.top]
                
                # Create geometry (polygon of bbox)
                geometry = {
                    "type": "Polygon",
                    "coordinates": [[
                        [bbox[0], bbox[1]],
                        [bbox[2], bbox[1]],
                        [bbox[2], bbox[3]],
                        [bbox[0], bbox[3]],
                        [bbox[0], bbox[1]]
                    ]]
                }
                
                # Build properties
                properties = {
                    "datetime": datetime.now(timezone.utc).isoformat(),
                    "created": datetime.now(timezone.utc).isoformat(),
                    "updated": datetime.now(timezone.utc).isoformat(),
                    
                    # Raster properties
                    "proj:epsg": 4326,  # Always 4326 for Silver tier
                    "proj:wkt2": src.crs.to_wkt() if src.crs else None,
                    "raster:bands": [],
                    
                    # File properties
                    "file:size": processing_info.get("cog_size_mb", 0) * 1024 * 1024,  # Convert to bytes
                    "file:container": container_name,
                    "file:name": blob_name,
                    
                    # Processing metadata
                    "processing:source_container": source_info.get("container"),
                    "processing:source_file": source_info.get("file"),
                    "processing:source_epsg": source_info.get("epsg"),
                    "processing:reprojected": processing_info.get("reprojected", False),
                    "processing:cog_profile": processing_info.get("cog_profile", "lzw"),
                    "processing:software": "rmhgeoapi",
                    "processing:datetime": datetime.now(timezone.utc).isoformat(),
                    
                    # COG provenance - was it already a COG or did we convert it?
                    "processing:was_already_cog": processing_info.get("already_cog", False),
                    "processing:cog_converted": processing_info.get("converted", True),
                    "processing:cog_valid": processing_info.get("cog_valid", True)
                }
                
                # Add band information
                for band_idx in range(1, src.count + 1):
                    band_info = {
                        "data_type": str(src.dtypes[band_idx - 1]) if band_idx <= len(src.dtypes) else "unknown",
                        "statistics": {}
                    }
                    
                    # Try to get band statistics (min, max, mean, stddev)
                    try:
                        stats = src.statistics(band_idx)
                        if stats:
                            band_info["statistics"] = {
                                "minimum": stats.min,
                                "maximum": stats.max,
                                "mean": stats.mean,
                                "stddev": stats.stddev
                            }
                    except:
                        pass  # Statistics might not be available
                        
                    properties["raster:bands"].append(band_info)
                
                # Build assets
                assets = {
                    "cog": {
                        "href": f"https://{Config.STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{container_name}/{blob_name}",
                        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                        "title": "Cloud Optimized GeoTIFF",
                        "roles": ["data", "visual"],
                        "proj:epsg": 4326,
                        "file:size": properties["file:size"]
                    }
                }
                
                # Build links
                links = [
                    {
                        "rel": "self",
                        "href": f"/collections/{collection_id}/items/{item_id}",
                        "type": "application/geo+json"
                    },
                    {
                        "rel": "parent",
                        "href": f"/collections/{collection_id}",
                        "type": "application/json"
                    },
                    {
                        "rel": "collection",
                        "href": f"/collections/{collection_id}",
                        "type": "application/json"
                    },
                    {
                        "rel": "root",
                        "href": "/",
                        "type": "application/json"
                    }
                ]
                
            # Insert into STAC database
            success = self.db_client.insert_stac_item(
                item_id=item_id,
                collection_id=collection_id,
                geometry=geometry,
                bbox=bbox,
                properties=properties,
                assets=assets,
                links=links,
                stac_version="1.0.0"
            )
            
            if success:
                result["success"] = True
                result["stac_item"] = {
                    "id": item_id,
                    "collection": collection_id,
                    "bbox": bbox,
                    "geometry": geometry,
                    "properties": properties,
                    "assets": assets
                }
                logger.info(f"Successfully cataloged COG {blob_name} as STAC item {item_id}")
            else:
                result["errors"].append("Failed to insert STAC item into database")
                
        except Exception as e:
            logger.error(f"Error cataloging COG: {e}")
            result["errors"].append(f"Error cataloging COG: {str(e)}")
            
        return result
    
    def get_cog_stac_item(self, container_name: str, blob_name: str) -> Optional[Dict]:
        """
        Get STAC item for a COG if it exists
        
        Args:
            container_name: Container name
            blob_name: Blob name
            
        Returns:
            STAC item dict or None if not found
        """
        try:
            # Generate the same item ID
            item_id = hashlib.md5(f"{container_name}/{blob_name}".encode()).hexdigest()
            
            result = self.db_client.execute(
                f"""
                SELECT id, collection_id, ST_AsGeoJSON(geometry) as geometry, 
                       ST_AsGeoJSON(bbox) as bbox, properties, assets, links, stac_version
                FROM {self.db_client.schema}.items 
                WHERE id = %s
                """,
                (item_id,),
                fetch=True
            )
            
            if result and len(result) > 0:
                row = result[0]
                return {
                    "id": row['id'],
                    "collection_id": row['collection_id'],
                    "geometry": json.loads(row['geometry']) if row['geometry'] else None,
                    "bbox": json.loads(row['bbox']) if row['bbox'] else None,
                    "properties": row['properties'],
                    "assets": row['assets'],
                    "links": row['links'],
                    "stac_version": row['stac_version']
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting STAC item: {e}")
            return None