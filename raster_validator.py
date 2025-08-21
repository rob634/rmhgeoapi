"""
Raster validation service for geospatial ETL pipeline
Validates GeoTIFF files and extracts CRS information
"""
import logging
from typing import Optional, Dict, Any
import rasterio
from rasterio.crs import CRS
from rasterio.errors import RasterioError

from config import Config, RasterConfig
from repositories import StorageRepository

logger = logging.getLogger(__name__)


class RasterValidator:
    """Service for validating raster files"""
    
    def __init__(self):
        """Initialize with storage repository"""
        self.storage_repo = StorageRepository()
        self.bronze_container = Config.BRONZE_CONTAINER_NAME or "rmhazuregeobronze"
        
    def validate_raster_name(self, raster_name: str) -> tuple[bool, str]:
        """
        Validate raster file name
        
        Returns:
            (is_valid, error_message)
        """
        if not raster_name or not isinstance(raster_name, str):
            return False, "Invalid raster name: must be a non-empty string"
            
        # Check extension
        has_valid_ext = any(raster_name.lower().endswith(ext) for ext in RasterConfig.VALID_EXTENSIONS)
        if not has_valid_ext:
            return False, f"Invalid extension. Must be one of: {', '.join(RasterConfig.VALID_EXTENSIONS)}"
            
        # Check length
        if len(raster_name) > RasterConfig.MAX_RASTER_NAME_LENGTH:
            return False, f"Raster name exceeds maximum length of {RasterConfig.MAX_RASTER_NAME_LENGTH} characters"
            
        # Check for invalid characters
        name_without_ext = raster_name.rsplit('.', 1)[0]
        if '.' in name_without_ext:
            return False, "Raster name contains invalid character: '.' (except for extension)"
            
        return True, ""
    
    def get_raster_crs(self, container_name: str, blob_name: str) -> Optional[int]:
        """
        Extract CRS EPSG code from raster
        
        Returns:
            EPSG code if found, None otherwise
        """
        try:
            # Get SAS URL for direct access
            blob_url = self.storage_repo.get_blob_sas_url(container_name, blob_name)
            
            # Open raster and read CRS
            with rasterio.open(blob_url) as src:
                if src.crs:
                    epsg = src.crs.to_epsg()
                    if epsg:
                        logger.info(f"Found CRS EPSG:{epsg} for {blob_name}")
                        return epsg
                    else:
                        # CRS exists but can't convert to EPSG
                        logger.warning(f"CRS found but cannot convert to EPSG for {blob_name}: {src.crs}")
                else:
                    logger.warning(f"No CRS found in {blob_name}")
                    
        except RasterioError as e:
            logger.error(f"Rasterio error reading CRS from {blob_name}: {e}")
        except Exception as e:
            logger.error(f"Error reading CRS from {blob_name}: {e}")
            
        return None
    
    def validate_epsg_code(self, epsg_code: int) -> bool:
        """
        Validate that EPSG code is valid
        
        Returns:
            True if valid, False otherwise
        """
        if not epsg_code or not isinstance(epsg_code, int):
            return False
            
        try:
            CRS.from_epsg(epsg_code)
            return True
        except Exception:
            return False
    
    def validate_raster(
        self, 
        container_name: str, 
        blob_name: str,
        input_epsg: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive raster validation
        
        Args:
            container_name: Storage container name
            blob_name: Raster file name
            input_epsg: Optional EPSG code to use if raster has no CRS
            
        Returns:
            Validation result dictionary
        """
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "metadata": {}
        }
        
        # Validate name
        name_valid, name_error = self.validate_raster_name(blob_name)
        if not name_valid:
            result["errors"].append(name_error)
            return result
            
        # Check if file exists
        if not self.storage_repo.blob_exists(blob_name, container_name):
            result["errors"].append(f"Raster {blob_name} not found in container {container_name}")
            return result
            
        # Get raster metadata
        try:
            blob_url = self.storage_repo.get_blob_sas_url(container_name, blob_name)
            
            with rasterio.open(blob_url) as src:
                # Extract metadata
                result["metadata"] = {
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,  # number of bands
                    "dtype": str(src.dtypes[0]) if src.dtypes else "unknown",
                    "driver": src.driver,
                    "compress": src.compression,
                    "bounds": list(src.bounds) if src.bounds else None,
                    "transform": str(src.transform)
                }
                
                # Check CRS
                if src.crs:
                    epsg = src.crs.to_epsg()
                    if epsg:
                        result["metadata"]["epsg"] = epsg
                        result["metadata"]["crs_wkt"] = src.crs.to_wkt()
                        logger.info(f"Raster {blob_name} has CRS EPSG:{epsg}")
                    else:
                        # Has CRS but not EPSG
                        result["metadata"]["crs_wkt"] = src.crs.to_wkt()
                        result["warnings"].append(f"CRS found but cannot convert to EPSG: {src.crs}")
                        
                        # Use input EPSG if provided
                        if input_epsg and self.validate_epsg_code(input_epsg):
                            result["metadata"]["epsg"] = input_epsg
                            result["metadata"]["epsg_source"] = "user_provided"
                            result["warnings"].append(f"Using user-provided EPSG:{input_epsg} (DANGEROUS - verify this is correct!)")
                        else:
                            result["errors"].append("Raster has non-standard CRS and no valid input EPSG provided")
                            return result
                else:
                    # No CRS at all
                    result["warnings"].append("No CRS found in raster")
                    
                    if input_epsg and self.validate_epsg_code(input_epsg):
                        result["metadata"]["epsg"] = input_epsg
                        result["metadata"]["epsg_source"] = "user_provided"
                        result["warnings"].append(f"Using user-provided EPSG:{input_epsg} for CRS-less raster (DANGEROUS - verify this is correct!)")
                    else:
                        result["errors"].append(
                            "Raster has no CRS. Please provide 'input_epsg' parameter with the correct projection "
                            "(e.g., 4326 for WGS84, 3857 for Web Mercator). Warning: Specifying incorrect projection will produce invalid results!"
                        )
                        return result
                
                # Check if it's already a COG
                # Simple check - COGs typically have tiled structure
                if src.is_tiled:
                    result["metadata"]["is_tiled"] = True
                    result["metadata"]["tile_shape"] = src.block_shapes[0] if src.block_shapes and len(src.block_shapes) > 0 else None
                    
                # Get file size from blob properties
                blob_props = self.storage_repo.get_blob_properties(container_name, blob_name)
                if blob_props:
                    result["metadata"]["size_mb"] = blob_props.get("size", 0) / (1024 * 1024)
                    
                result["valid"] = len(result["errors"]) == 0
                
        except RasterioError as e:
            result["errors"].append(f"Invalid raster file: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Error validating raster: {str(e)}")
            
        return result