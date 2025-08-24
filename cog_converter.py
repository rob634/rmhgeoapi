"""
Cloud Optimized GeoTIFF (COG) conversion service
Converts reprojected rasters to COG format for efficient cloud access
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
    """Service for converting rasters to Cloud Optimized GeoTIFF format"""
    
    def __init__(self):
        """Initialize COG converter with shared base functionality"""
        super().__init__()
        
    def is_valid_cog(self, container_name: str, blob_name: str) -> Tuple[bool, list]:
        """
        Check if a raster is already a valid COG
        
        Args:
            container_name: Container name
            blob_name: Blob name
            
        Returns:
            (is_valid, errors/warnings list)
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
        skip_if_valid: bool = True
    ) -> Dict[str, Any]:
        """
        Convert raster to Cloud Optimized GeoTIFF
        
        Args:
            source_container: Source container name
            source_blob: Source blob name
            dest_container: Destination container name
            dest_blob: Destination blob name
            cog_profile: COG profile to use (defaults to RasterConfig.COG_PROFILE)
            skip_if_valid: Skip conversion if already a valid COG
            
        Returns:
            Result dictionary with status and metadata
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
            
        # Check if source is already a valid COG
        if skip_if_valid:
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
            result["errors"].append(f"Rasterio error during COG conversion: {str(e)}")
            self.logger.error(f"Rasterio error: {e}")
        except Exception as e:
            result["errors"].append(f"Error during COG conversion: {str(e)}")
            self.logger.error(f"COG conversion error: {e}")
            
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