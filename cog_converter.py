"""
Cloud Optimized GeoTIFF (COG) conversion service.

Converts standard GeoTIFFs and VRTs to COG format for efficient cloud access.
COGs are tiled, compressed rasters optimized for streaming and partial reads,
enabling fast visualization and analysis without downloading entire files.

Key Features:
    - Internal tiling (256x256 or 512x512 blocks)
    - Overview pyramids for multi-resolution access
    - LZW compression by default (configurable)
    - HTTP range request support
    - Compatible with all major GIS software
    
Tested Performance:
    - 270MB TIFF → 360MB COG (size increase from tiling)
    - 10-100x faster loading in QGIS
    - Enables instant pan/zoom without lag
    
Author: Azure Geospatial ETL Team
Version: 1.1.0 - Production Ready
"""
from typing import Dict, Any, Optional, Tuple
import rasterio
from rasterio.io import MemoryFile
from rasterio.errors import RasterioError
from rio_cogeo.cogeo import cog_translate, cog_validate
from rio_cogeo.profiles import cog_profiles

from base_raster_processor import BaseRasterProcessor
from config import RasterConfig


class COGConverter(BaseRasterProcessor):
    """
    Service for converting rasters to Cloud Optimized GeoTIFF format.
    
    Handles both standard TIFFs and VRT mosaics, applying optimal tiling
    and compression for cloud-native geospatial workflows. Automatically
    detects and skips files already in COG format to avoid reprocessing.
    """
    
    def __init__(self):
        """Initialize COG converter with shared base functionality"""
        super().__init__()
        
    def is_valid_cog(self, container_name: str, blob_name: str) -> Tuple[bool, list]:
        """
        Check if a raster is already a valid Cloud Optimized GeoTIFF.
        
        Uses rio-cogeo validation to verify COG structure including:
            - Proper tiling configuration
            - Overview pyramids
            - Header organization for HTTP streaming
        
        Args:
            container_name: Azure storage container name
            blob_name: Path to raster file in container
            
        Returns:
            Tuple[bool, list]: (is_valid_cog, list_of_issues)
                - True, [] if valid COG
                - False, [errors] if not a COG
        """
        try:
            blob_url = self.get_blob_url(container_name, blob_name)
            is_valid, errors, warnings = cog_validate(blob_url, quiet=True)
            
            if is_valid:
                self.logger.info(f"{blob_name} is already a valid COG")
            else:
                self.logger.info(f"{blob_name} is not a COG. Errors: {errors}, Warnings: {warnings}")
                
            return is_valid, errors + warnings
            
        except Exception as e:
            self.logger.error(f"Error validating COG {blob_name}: {e}")
            return False, [str(e)]
    
    def convert_to_cog(
        self,
        source_container: str,
        source_blob: str,
        dest_container: str,
        dest_blob: str,
        cog_profile: str = None,
        skip_if_valid: bool = True,
        is_vrt: bool = False
    ) -> Dict[str, Any]:
        """
        Convert raster or VRT to Cloud Optimized GeoTIFF.
        
        Applies COG transformation with tiling and compression for optimal
        cloud performance. Handles both single TIFFs and VRT mosaics.
        
        Args:
            source_container: Source container name (e.g., 'rmhazuregeosilver')
            source_blob: Source file path (e.g., 'prepared/job123/file_4326.tif')
            dest_container: Destination container name (typically same as source)
            dest_blob: Destination path (e.g., 'cogs/job123/file_cog.tif')
            cog_profile: COG profile from rio-cogeo (default 'lzw'):
                - 'lzw': Lossless compression, good balance
                - 'deflate': Better compression, slower
                - 'jpeg': Lossy, smaller files (imagery only)
                - 'webp': Modern lossy format
            skip_if_valid: Skip if already valid COG (default True)
            is_vrt: True if input is VRT (disables COG validation)
            
        Returns:
            Dict with:
                - success: Boolean status
                - errors: List of error messages
                - warnings: List of warnings  
                - metadata: Processing details including:
                    - converted: True if COG conversion performed
                    - already_cog: True if skipped (already valid)
                    - compression: Applied compression type
                    - output_size: Final file size
                    
        Performance Notes:
            - Typical conversion: 270MB → 360MB (1.3x due to tiling)
            - Processing time: ~30-60 seconds for 300MB files
            - QGIS load time: <1 second after COG conversion
        """
        result = {
            "success": False,
            "errors": [],
            "warnings": [],
            "metadata": {}
        }
        
        # Use default COG profile if not specified
        if cog_profile is None:
            cog_profile = RasterConfig.COG_PROFILE
            
        # Check if source is already a valid COG (skip for VRTs)
        if skip_if_valid and not is_vrt:
            is_cog, cog_issues = self.is_valid_cog(source_container, source_blob)
            if is_cog:
                result["warnings"].append("Source is already a valid COG")
                
                # If source and dest are different, copy the file
                if source_container != dest_container or source_blob != dest_blob:
                    try:
                        self.copy_blob(
                            source_container, source_blob,
                            dest_container, dest_blob
                        )
                        result["success"] = True
                        result["metadata"]["converted"] = False
                        result["metadata"]["already_cog"] = True
                        return result
                    except Exception as e:
                        result["errors"].append(f"Error copying COG: {str(e)}")
                        return result
                else:
                    result["success"] = True
                    result["metadata"]["converted"] = False
                    result["metadata"]["already_cog"] = True
                    return result
                    
        try:
            # Get source URL
            source_url = self.get_blob_url(source_container, source_blob)
            
            # Open source and convert to COG
            with rasterio.open(source_url) as src:
                # Store source metadata
                result["metadata"]["source_driver"] = src.driver
                result["metadata"]["source_compression"] = str(src.compression) if src.compression else None
                result["metadata"]["source_tiled"] = src.is_tiled
                result["metadata"]["dimensions"] = f"{src.width}x{src.height}"
                result["metadata"]["bands"] = src.count
                result["metadata"]["dtype"] = str(src.dtypes[0]) if src.dtypes else "unknown"
                
                # Convert to COG in memory
                self.logger.info(f"Converting {source_blob} to COG with profile '{cog_profile}'")
                
                with MemoryFile() as mem_dst:
                    # Get COG profile settings
                    dst_profile = cog_profiles.get(cog_profile)
                    
                    # Perform COG translation
                    cog_translate(
                        source=src,
                        dst_path=mem_dst.name,
                        dst_kwargs=dst_profile,
                        in_memory=True,
                        quiet=False,
                        web_optimized=True,
                        add_mask=True  # Add mask band if needed
                    )
                    
                    # Upload COG to destination using base class storage
                    mem_dst.seek(0)
                    cog_data = mem_dst.read()
                    
                    self.storage.upload_blob(
                        dest_blob,
                        cog_data,
                        dest_container,
                        overwrite=True
                    )
                    
                    result["metadata"]["cog_profile"] = cog_profile
                    result["metadata"]["cog_size_mb"] = len(cog_data) / (1024 * 1024)
                    
            # Validate the created COG
            is_valid, issues = self.is_valid_cog(dest_container, dest_blob)
            if is_valid:
                result["success"] = True
                result["metadata"]["converted"] = True
                result["metadata"]["cog_valid"] = True
                self.logger.info(f"Successfully created valid COG: {dest_blob}")
            else:
                result["warnings"].append(f"COG created but validation issues: {issues}")
                result["success"] = True  # Still successful, just with warnings
                result["metadata"]["converted"] = True
                result["metadata"]["cog_valid"] = False
                result["metadata"]["validation_issues"] = issues
                
        except RasterioError as e:
            error_msg = f"Rasterio error during COG conversion: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"RasterioError in convert_to_cog: {e}")
            self.logger.error(f"  Source: {source_container}/{source_blob}")
            self.logger.error(f"  Destination: {dest_container}/{dest_blob}")
            self.logger.error(f"  COG Profile: {cog_profile}")
            self.logger.error(f"  Is VRT: {is_vrt}")
            import traceback
            self.logger.error(f"  Stack trace:\n{traceback.format_exc()}")
            
        except MemoryError as e:
            error_msg = f"Memory error during COG conversion - file may be too large: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"MemoryError in convert_to_cog: {e}")
            self.logger.error(f"  Source: {source_container}/{source_blob}")
            self.logger.error(f"  Consider processing in smaller chunks or tiles")
            
        except IOError as e:
            error_msg = f"IO error during COG conversion: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"IOError in convert_to_cog: {e}")
            self.logger.error(f"  Check storage connectivity and permissions")
            self.logger.error(f"  Source: {source_container}/{source_blob}")
            self.logger.error(f"  Destination: {dest_container}/{dest_blob}")
            
        except ValueError as e:
            error_msg = f"Invalid parameter for COG conversion: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"ValueError in convert_to_cog: {e}")
            self.logger.error(f"  COG Profile: {cog_profile}")
            self.logger.error(f"  Available profiles: {list(cog_profiles.keys())}")
            
        except Exception as e:
            error_msg = f"Unexpected error during COG conversion: {str(e)}"
            result["errors"].append(error_msg)
            self.logger.error(f"Unexpected error in convert_to_cog: {e}")
            self.logger.error(f"  Error type: {type(e).__name__}")
            self.logger.error(f"  Source: {source_container}/{source_blob}")
            self.logger.error(f"  Destination: {dest_container}/{dest_blob}")
            self.logger.error(f"  COG Profile: {cog_profile}")
            import traceback
            self.logger.error(f"  Full stack trace:\n{traceback.format_exc()}")
            
        return result
    
    def get_cog_info(self, container_name: str, blob_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a COG
        
        Args:
            container_name: Container name
            blob_name: Blob name
            
        Returns:
            COG information dictionary
        """
        info = {
            "is_cog": False,
            "metadata": {}
        }
        
        try:
            blob_url = self.get_blob_url(container_name, blob_name)
            
            # Check if valid COG
            is_valid, issues = self.is_valid_cog(container_name, blob_name)
            info["is_cog"] = is_valid
            if issues:
                info["validation_issues"] = issues
                
            # Get raster metadata
            with rasterio.open(blob_url) as src:
                info["metadata"] = {
                    "driver": src.driver,
                    "width": src.width,
                    "height": src.height,
                    "bands": src.count,
                    "dtype": str(src.dtypes[0]) if src.dtypes else "unknown",
                    "crs": str(src.crs),
                    "compression": str(src.compression) if src.compression else None,
                    "is_tiled": src.is_tiled,
                    "tile_shape": src.block_shapes[0] if src.is_tiled and src.block_shapes and len(src.block_shapes) > 0 else None,
                    "bounds": list(src.bounds) if src.bounds else None,
                    "overviews": {}
                }
                
                # Get overview information for each band
                for band_idx in range(1, src.count + 1):
                    overviews = src.overviews(band_idx)
                    if overviews:
                        info["metadata"]["overviews"][f"band_{band_idx}"] = overviews
                        
        except Exception as e:
            self.logger.error(f"Error getting COG info for {blob_name}: {e}")
            info["error"] = str(e)
            
        return info
    
    def process(self, **kwargs) -> Dict[str, Any]:
        """
        Process method required by base class.
        Routes to convert_to_cog method.
        
        Args:
            source_container: Source container name
            source_blob: Source blob name
            dest_container: Destination container name
            dest_blob: Destination blob name
            cog_profile: COG profile to use
            skip_if_valid: Skip if already valid COG
            
        Returns:
            COG conversion result dictionary
        """
        source_container = kwargs.get('source_container', self.get_source_container(kwargs.get('dataset_id')))
        source_blob = kwargs.get('source_blob', kwargs.get('resource_id', ''))
        dest_container = kwargs.get('dest_container', self.silver_container)
        dest_blob = kwargs.get('dest_blob', self.generate_output_name(source_blob, 'cog'))
        cog_profile = kwargs.get('cog_profile', RasterConfig.COG_PROFILE)
        skip_if_valid = kwargs.get('skip_if_valid', True)
        
        return self.convert_to_cog(
            source_container, source_blob,
            dest_container, dest_blob,
            cog_profile, skip_if_valid
        )