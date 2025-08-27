"""
Standalone STAC Cataloging Service
Catalogs any geospatial file (raster or vector) into appropriate STAC collections
Independent of ETL pipelines for robust design
"""
import logging
import json
import hashlib
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import rasterio
from rasterio.warp import transform_bounds
from rasterio.errors import RasterioError

from config import Config
from services import BaseProcessingService
from repositories import StorageRepository
from database_client import STACDatabase

logger = logging.getLogger(__name__)


class STACCatalogService(BaseProcessingService):
    """Standalone service for cataloging files in STAC"""
    
    def __init__(self):
        """Initialize with storage and database clients"""
        super().__init__()
        self.storage_repo = StorageRepository()
        self.db_client = STACDatabase(
            host=Config.POSTGIS_HOST,
            database=Config.POSTGIS_DATABASE,
            user=Config.POSTGIS_USER,
            password=Config.POSTGIS_PASSWORD,
            port=Config.POSTGIS_PORT,
            schema=Config.POSTGIS_SCHEMA or "geo"
        )
        
        # Collection mappings
        self.collections = {
            "rmhazuregeobronze": "bronze-assets",
            "rmhazuregeosilver": "silver-assets",
            "rmhazuregeogold": "gold-assets"
        }
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return ["catalog_file", "setup_stac_collections"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str, **kwargs) -> Dict[str, Any]:
        """
        Process STAC cataloging request
        
        Args:
            job_id: Job identifier
            dataset_id: Container name (e.g., 'rmhazuregeobronze')
            resource_id: File name to catalog
            version_id: Optional collection override
            operation_type: Operation type (should be 'catalog_file')
            
        Returns:
            Processing result
        """
        result = {
            "job_id": job_id,
            "operation": "stac_catalog",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "container": dataset_id,
            "file": resource_id,
            "success": False,
            "errors": [],
            "warnings": [],
            "stac_item": None
        }
        
        try:
            # Determine collection from container or use override
            if version_id and version_id != "v1":
                collection_id = version_id
            else:
                collection_id = self.collections.get(dataset_id, "bronze-assets")
            
            # Ensure collection exists
            self._ensure_collection_exists(collection_id, dataset_id)
            
            # Determine file type
            file_ext = resource_id.lower().split('.')[-1]
            
            if file_ext in ['tif', 'tiff', 'jp2', 'img', 'hdf']:
                # Raster file
                stac_result = self._catalog_raster(dataset_id, resource_id, collection_id)
            elif file_ext in ['geojson', 'json']:
                # Vector GeoJSON
                stac_result = self._catalog_geojson(dataset_id, resource_id, collection_id)
            elif file_ext in ['shp', 'gpkg', 'kml', 'kmz', 'gml']:
                # Other vector formats
                stac_result = self._catalog_vector(dataset_id, resource_id, collection_id)
            else:
                result["errors"].append(f"Unsupported file type: {file_ext}")
                return result
            
            if stac_result["success"]:
                result["success"] = True
                result["stac_item"] = stac_result["stac_item"]
                logger.info(f"Successfully cataloged {resource_id} in collection {collection_id}")
            else:
                result["errors"].extend(stac_result.get("errors", []))
                result["warnings"].extend(stac_result.get("warnings", []))
            
        except Exception as e:
            logger.error(f"Error cataloging file: {e}")
            result["errors"].append(str(e))
        
        return result
    
    def _ensure_collection_exists(self, collection_id: str, container_name: str) -> bool:
        """Ensure STAC collection exists"""
        # Check if collection exists
        existing = self.db_client.execute(
            f"SELECT id FROM {self.db_client.schema}.collections WHERE id = %s",
            (collection_id,),
            fetch=True
        )
        
        if existing:
            return True
        
        # Create collection based on tier
        if "bronze" in collection_id:
            title = "Bronze Tier Assets"
            description = "Raw geospatial data as ingested"
        elif "silver" in collection_id:
            title = "Silver Tier Assets"
            description = "Processed and standardized geospatial data (COGs, PostGIS)"
        elif "gold" in collection_id:
            title = "Gold Tier Assets"
            description = "Analysis-ready data products"
        else:
            title = f"Collection {collection_id}"
            description = f"Geospatial assets from {container_name}"
        
        collection_data = {
            'id': collection_id,
            'title': title,
            'description': description,
            'keywords': '{geospatial,stac,' + collection_id.replace('-', ',') + '}',
            'license': 'proprietary',
            'providers': json.dumps([{
                'name': 'RMH Geospatial Pipeline',
                'roles': ['processor', 'host']
            }]),
            'extent': json.dumps({
                'spatial': {'bbox': [[-180, -90, 180, 90]]},
                'temporal': {'interval': [[None, None]]}
            }),
            'summaries': json.dumps({})
        }
        
        try:
            self.db_client.insert('collections', collection_data, schema_name=self.db_client.schema)
            logger.info(f"Created STAC collection '{collection_id}'")
            return True
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return False
    
    def _catalog_raster(self, container_name: str, blob_name: str, collection_id: str) -> Dict:
        """Catalog a raster file"""
        result = {
            "success": False,
            "errors": [],
            "warnings": [],
            "stac_item": None
        }
        
        try:
            # Generate unique item ID
            item_id = hashlib.md5(f"{container_name}/{blob_name}".encode()).hexdigest()
            
            # Get SAS URL for raster access
            blob_url = self.storage_repo.get_blob_sas_url(container_name, blob_name)
            
            with rasterio.open(blob_url) as src:
                # Get bounds
                bounds = src.bounds
                epsg = src.crs.to_epsg() if src.crs else None
                
                # Transform to EPSG:4326 if needed
                if epsg and epsg != 4326:
                    left, bottom, right, top = transform_bounds(src.crs, 'EPSG:4326', *bounds)
                    bbox = [left, bottom, right, top]
                else:
                    bbox = [bounds.left, bounds.bottom, bounds.right, bounds.top]
                
                # Create geometry
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
                
                # Get file size from blob properties
                blob_props = self.storage_repo.get_blob_properties(container_name, blob_name)
                file_size = blob_props.get('size', 0) if blob_props else 0
                
                # Check if it's a COG
                is_cog = src.driver == "GTiff" and src.is_tiled
                
                # Build properties
                properties = {
                    "datetime": datetime.now(timezone.utc).isoformat(),
                    "created": datetime.now(timezone.utc).isoformat(),
                    "type": "raster",
                    "file:size": file_size,
                    "file:container": container_name,
                    "file:name": blob_name,
                    "proj:epsg": epsg,
                    "proj:wkt2": src.crs.to_wkt() if src.crs else None,
                    "raster:bands": src.count,
                    "width": src.width,
                    "height": src.height,
                    "driver": src.driver,
                    "dtype": str(src.dtypes[0]) if src.dtypes else None,
                    "compression": str(src.compression) if src.compression else None,
                    "is_tiled": src.is_tiled,
                    "is_cog": is_cog,
                    
                    # COG provenance for direct cataloging
                    "processing:was_already_cog": is_cog if container_name == "rmhazuregeobronze" else None,
                    "processing:cog_converted": False if container_name == "rmhazuregeobronze" else None,
                    "processing:cataloged_directly": True
                }
                
                # Build assets
                assets = {
                    "data": {
                        "href": f"https://{Config.STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{container_name}/{blob_name}",
                        "type": self._get_media_type(blob_name),
                        "title": blob_name,
                        "roles": ["data"],
                        "file:size": file_size
                    }
                }
                
                # Build links
                links = self._build_links(collection_id, item_id)
                
                # Insert into database
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
                    # Only return a summary to avoid Table Storage 64KB limit
                    result["stac_item"] = {
                        "id": item_id,
                        "collection": collection_id,
                        "bbox": bbox,
                        "type": "raster",
                        "file_size": file_size,
                        "is_cog": is_cog,
                        "bands": src.count,
                        "epsg": epsg,
                        "message": f"STAC item created in PostgreSQL geo.items table"
                    }
                else:
                    result["errors"].append("Failed to insert STAC item")
                    
        except RasterioError as e:
            result["errors"].append(f"Error reading raster: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Error cataloging raster: {str(e)}")
        
        return result
    
    def _catalog_geojson(self, container_name: str, blob_name: str, collection_id: str) -> Dict:
        """Catalog a GeoJSON file"""
        result = {
            "success": False,
            "errors": [],
            "warnings": [],
            "stac_item": None
        }
        
        try:
            # Generate unique item ID
            item_id = hashlib.md5(f"{container_name}/{blob_name}".encode()).hexdigest()
            
            # Download and parse GeoJSON
            blob_content = self.storage_repo.download_blob(blob_name, container_name)
            geojson = json.loads(blob_content)
            
            # Extract bounds and geometry
            if geojson.get("type") == "FeatureCollection":
                # Calculate bounds from all features
                all_coords = []
                for feature in geojson.get("features", []):
                    if feature.get("geometry"):
                        coords = self._extract_coordinates(feature["geometry"])
                        all_coords.extend(coords)
                
                if all_coords:
                    lons = [c[0] for c in all_coords]
                    lats = [c[1] for c in all_coords]
                    bbox = [min(lons), min(lats), max(lons), max(lats)]
                else:
                    bbox = [-180, -90, 180, 90]  # Default global bounds
                    
                # Use convex hull or bbox as geometry
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
                feature_count = len(geojson.get("features", []))
                
            elif geojson.get("type") == "Feature":
                # Single feature
                geometry = geojson.get("geometry", {})
                coords = self._extract_coordinates(geometry)
                if coords:
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    bbox = [min(lons), min(lats), max(lons), max(lats)]
                else:
                    bbox = [-180, -90, 180, 90]
                feature_count = 1
                
            else:
                # Direct geometry
                geometry = geojson
                coords = self._extract_coordinates(geometry)
                if coords:
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    bbox = [min(lons), min(lats), max(lons), max(lats)]
                else:
                    bbox = [-180, -90, 180, 90]
                feature_count = 1
            
            # Get file size
            blob_props = self.storage_repo.get_blob_properties(container_name, blob_name)
            file_size = blob_props.get('size', 0) if blob_props else len(blob_content)
            
            # Build properties
            properties = {
                "datetime": datetime.now(timezone.utc).isoformat(),
                "created": datetime.now(timezone.utc).isoformat(),
                "type": "vector",
                "file:size": file_size,
                "file:container": container_name,
                "file:name": blob_name,
                "vector:format": "geojson",
                "vector:features": feature_count,
                "proj:epsg": 4326  # GeoJSON is always WGS84
            }
            
            # Build assets
            assets = {
                "data": {
                    "href": f"https://{Config.STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{container_name}/{blob_name}",
                    "type": "application/geo+json",
                    "title": blob_name,
                    "roles": ["data"],
                    "file:size": file_size
                }
            }
            
            # Build links
            links = self._build_links(collection_id, item_id)
            
            # Insert into database
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
                # Only return a summary to avoid Table Storage 64KB limit
                result["stac_item"] = {
                    "id": item_id,
                    "collection": collection_id,
                    "bbox": bbox,
                    "type": "vector-geojson",
                    "feature_count": feature_count,
                    "file_size": file_size,
                    "message": f"STAC item created in PostgreSQL geo.items table"
                }
            else:
                result["errors"].append("Failed to insert STAC item")
                
        except json.JSONDecodeError as e:
            result["errors"].append(f"Invalid GeoJSON: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Error cataloging GeoJSON: {str(e)}")
        
        return result
    
    def _catalog_vector(self, container_name: str, blob_name: str, collection_id: str) -> Dict:
        """Catalog other vector formats (shapefile, geopackage, etc)"""
        result = {
            "success": False,
            "errors": [],
            "warnings": [],
            "stac_item": None
        }
        
        try:
            # Generate unique item ID
            item_id = hashlib.md5(f"{container_name}/{blob_name}".encode()).hexdigest()
            
            # Get file info
            blob_props = self.storage_repo.get_blob_properties(container_name, blob_name)
            file_size = blob_props.get('size', 0) if blob_props else 0
            
            # For now, use global bounds (could enhance with OGR later)
            bbox = [-180, -90, 180, 90]
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
            
            # Determine format
            file_ext = blob_name.lower().split('.')[-1]
            format_map = {
                'shp': 'shapefile',
                'gpkg': 'geopackage',
                'kml': 'kml',
                'kmz': 'kmz',
                'gml': 'gml'
            }
            vector_format = format_map.get(file_ext, file_ext)
            
            # Build properties
            properties = {
                "datetime": datetime.now(timezone.utc).isoformat(),
                "created": datetime.now(timezone.utc).isoformat(),
                "type": "vector",
                "file:size": file_size,
                "file:container": container_name,
                "file:name": blob_name,
                "vector:format": vector_format
            }
            
            # Build assets
            assets = {
                "data": {
                    "href": f"https://{Config.STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{container_name}/{blob_name}",
                    "type": self._get_media_type(blob_name),
                    "title": blob_name,
                    "roles": ["data"],
                    "file:size": file_size
                }
            }
            
            # Build links
            links = self._build_links(collection_id, item_id)
            
            # Insert into database
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
                # Only return a summary to avoid Table Storage 64KB limit
                result["stac_item"] = {
                    "id": item_id,
                    "collection": collection_id,
                    "bbox": bbox,
                    "type": f"vector-{vector_format}",
                    "file_size": file_size,
                    "message": f"STAC item created in PostgreSQL geo.items table"
                }
                result["warnings"].append(f"Using default global bounds for {vector_format} file")
            else:
                result["errors"].append("Failed to insert STAC item")
                
        except Exception as e:
            result["errors"].append(f"Error cataloging vector file: {str(e)}")
        
        return result
    
    def _extract_coordinates(self, geometry: Dict) -> List[List[float]]:
        """Extract all coordinates from a geometry"""
        coords = []
        if not geometry:
            return coords
            
        geom_type = geometry.get("type", "")
        
        if geom_type == "Point":
            coords.append(geometry["coordinates"])
        elif geom_type == "LineString":
            coords.extend(geometry["coordinates"])
        elif geom_type == "Polygon":
            for ring in geometry["coordinates"]:
                coords.extend(ring)
        elif geom_type == "MultiPoint":
            coords.extend(geometry["coordinates"])
        elif geom_type == "MultiLineString":
            for line in geometry["coordinates"]:
                coords.extend(line)
        elif geom_type == "MultiPolygon":
            for polygon in geometry["coordinates"]:
                for ring in polygon:
                    coords.extend(ring)
        elif geom_type == "GeometryCollection":
            for geom in geometry.get("geometries", []):
                coords.extend(self._extract_coordinates(geom))
        
        return coords
    
    def _get_media_type(self, filename: str) -> str:
        """Get media type for file"""
        ext = filename.lower().split('.')[-1]
        media_types = {
            'tif': 'image/tiff; application=geotiff',
            'tiff': 'image/tiff; application=geotiff',
            'jp2': 'image/jp2',
            'geojson': 'application/geo+json',
            'json': 'application/geo+json',
            'shp': 'application/x-shapefile',
            'gpkg': 'application/geopackage+sqlite3',
            'kml': 'application/vnd.google-earth.kml+xml',
            'kmz': 'application/vnd.google-earth.kmz',
            'gml': 'application/gml+xml'
        }
        return media_types.get(ext, 'application/octet-stream')
    
    def _build_links(self, collection_id: str, item_id: str) -> List[Dict]:
        """Build standard STAC links"""
        return [
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