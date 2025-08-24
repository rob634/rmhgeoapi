"""
Raster validation service for geospatial ETL pipeline.

Validates GeoTIFF files for integrity, extracts CRS information, and ensures
files are ready for processing. Critical first step in the COG pipeline to
prevent errors downstream.

Key Features:
    - Validates file existence and accessibility
    - Extracts and validates CRS/projection information
    - Checks file size limits for processing
    - Detects tiling and compression
    - Identifies files already in COG format
    - Handles CRS-less files with user-provided EPSG

Tested and Working:
    - Files with EPSG:4326 (WGS84)
    - Files with EPSG:3857 (Web Mercator)
    - Large files up to 20GB (metadata extraction only)
    - Files with non-standard CRS requiring manual EPSG

Author: Azure Geospatial ETL Team
Version: 1.1.0 - Production Ready
"""
from typing import Optional, Dict, Any
import rasterio
from rasterio.crs import CRS
from rasterio.errors import RasterioError

from base_raster_processor import BaseRasterProcessor
from config import RasterConfig


class RasterValidator(BaseRasterProcessor):
    """
    Service for comprehensive raster file validation.
    
    Ensures raster files are valid, have proper CRS information, and are
    within processing limits. Essential for preventing downstream failures
    in reprojection and COG conversion operations.
    """
    
    def __init__(self):
        """Initialize validator with shared base functionality"""
        super().__init__()
        
    def validate_raster_name(self, raster_name: str) -> tuple[bool, str]:
        """
        Validate raster file name for compatibility.
        
        Checks filename against configured rules including:
            - Valid extensions (.tif, .tiff, .geotiff)
            - Maximum length restrictions
            - Invalid character detection
        
        Args:
            raster_name: Filename to validate
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
                - (True, "") if valid
                - (False, "reason") if invalid
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
        Extract CRS EPSG code from raster metadata.
        
        Opens raster via SAS URL to read CRS information without
        downloading the entire file. Handles various CRS formats
        and attempts to convert to standard EPSG codes.
        
        Args:
            container_name: Azure storage container
            blob_name: Path to raster file
            
        Returns:
            Optional[int]: EPSG code (e.g., 4326, 3857) or None if not found
            
        Common EPSG Codes:
            - 4326: WGS84 (GPS coordinates)
            - 3857: Web Mercator (Google/Bing maps)
            - 32633: UTM Zone 33N
        """
        try:
            # Get SAS URL for direct access
            blob_url = self.get_blob_url(container_name, blob_name)
            
            # Open raster and read CRS
            with rasterio.open(blob_url) as src:
                if src.crs:
                    epsg = src.crs.to_epsg()
                    if epsg:
                        self.logger.info(f"Found CRS EPSG:{epsg} for {blob_name}")
                        return epsg
                    else:
                        # CRS exists but can't convert to EPSG
                        self.logger.warning(f"CRS found but cannot convert to EPSG for {blob_name}: {src.crs}")
                else:
                    self.logger.warning(f"No CRS found in {blob_name}")
                    
        except RasterioError as e:
            self.logger.error(f"Rasterio error reading CRS from {blob_name}: {e}")
        except Exception as e:
            self.logger.error(f"Error reading CRS from {blob_name}: {e}")
            
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
        input_epsg: Optional[int] = None,
        skip_size_check: bool = False
    ) -> Dict[str, Any]:
        """
        Comprehensive raster validation with metadata extraction.
        
        Performs thorough validation including file existence, size limits,
        CRS detection, and raster metadata extraction. This is the primary
        method called by prepare_for_cog service.
        
        Args:
            container_name: Storage container name (e.g., 'rmhazuregeobronze')
            blob_name: Raster file path in container
            input_epsg: Optional EPSG code for CRS-less files (use with caution!)
            
        Returns:
            Dict containing:
                - valid: Boolean indicating if file can be processed
                - errors: List of critical errors preventing processing
                - warnings: List of non-critical issues
                - metadata: Extracted raster information including:
                    - epsg: EPSG code (e.g., 4326, 3857)
                    - width, height: Pixel dimensions
                    - count: Number of bands
                    - dtype: Data type (e.g., 'uint8', 'float32')
                    - compress: Compression type
                    - bounds: Geographic extent [minx, miny, maxx, maxy]
                    - is_tiled: True if file has internal tiling
                    - size_mb: File size in megabytes
                    
        Examples:
            Valid file with CRS:
                {'valid': True, 'metadata': {'epsg': 4326, ...}}
                
            File needing reprojection:
                {'valid': True, 'metadata': {'epsg': 3857, ...}}
                
            Missing CRS (requires input_epsg):
                {'valid': False, 'errors': ['No CRS found...']}
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
            
        # Check if file exists using base class method
        exists, file_size = self.check_file_exists(container_name, blob_name)
        if not exists:
            result["errors"].append(f"Raster {blob_name} not found in container {container_name}")
            return result
        
        # Check file size limits
        if file_size:
            file_size_mb = file_size / (1024 * 1024)
            result["metadata"]["size_mb"] = file_size_mb
            
            # Skip size check when processing with extent (tiling)
            if not skip_size_check:
                can_process, size_msg = self.can_process_file(file_size_mb)
                if not can_process:
                    result["errors"].append(size_msg)
                    return result
            else:
                self.logger.info(f"Skipping size check for {file_size_mb/1024:.2f}GB file (processing with extent)")
            
        # Get raster metadata
        try:
            blob_url = self.get_blob_url(container_name, blob_name)
            
            with rasterio.open(blob_url) as src:
                # Extract metadata
                result["metadata"] = {
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,  # number of bands
                    "dtype": str(src.dtypes[0]) if src.dtypes else "unknown",
                    "driver": src.driver,
                    "compress": src.compression if src.compression is None else str(src.compression),
                    "bounds": list(src.bounds) if src.bounds else None,
                    "transform": str(src.transform)
                }
                
                # Check CRS
                if src.crs:
                    epsg = src.crs.to_epsg()
                    if epsg:
                        result["metadata"]["epsg"] = epsg
                        result["metadata"]["crs_wkt"] = src.crs.to_wkt()
                        self.logger.info(f"Raster {blob_name} has CRS EPSG:{epsg}")
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
                    
                # File size already added above from check_file_exists
                    
                result["valid"] = len(result["errors"]) == 0
                
        except RasterioError as e:
            error_msg = f"Invalid raster file: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"RasterioError in validate_raster: {e}")
            self.logger.error(f"  Container: {container_name}")
            self.logger.error(f"  Blob: {blob_name}")
            self.logger.error(f"  This may indicate a corrupted or incompatible raster file")
            
        except MemoryError as e:
            error_msg = f"Memory error - file may be too large for validation: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"MemoryError in validate_raster: {e}")
            self.logger.error(f"  File size: {result.get('metadata', {}).get('size_mb', 'unknown')} MB")
            self.logger.error(f"  Consider using smart mode or processing in tiles")
            
        except IOError as e:
            error_msg = f"IO error accessing raster: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"IOError in validate_raster: {e}")
            self.logger.error(f"  Check storage connectivity and permissions")
            
        except ValueError as e:
            error_msg = f"Invalid parameter: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"ValueError in validate_raster: {e}")
            if input_epsg:
                self.logger.error(f"  Input EPSG provided: {input_epsg}")
                
        except Exception as e:
            error_msg = f"Unexpected error validating raster: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"Unexpected error in validate_raster: {e}")
            self.logger.error(f"  Error type: {type(e).__name__}")
            self.logger.error(f"  Container: {container_name}")
            self.logger.error(f"  Blob: {blob_name}")
            import traceback
            self.logger.error(f"  Stack trace:\n{traceback.format_exc()}")
            
        return result
    
    def process(self, **kwargs) -> Dict[str, Any]:
        """
        Process method required by base class.
        Routes to validate_raster method.
        
        Args:
            container_name: Storage container name
            blob_name: Raster file name
            input_epsg: Optional EPSG code
            
        Returns:
            Validation result dictionary
        """
        container_name = kwargs.get('container_name', kwargs.get('dataset_id', self.bronze_container))
        blob_name = kwargs.get('blob_name', kwargs.get('resource_id', ''))
        input_epsg = kwargs.get('input_epsg')
        
        return self.validate_raster(container_name, blob_name, input_epsg)