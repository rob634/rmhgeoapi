"""
Raster reprojection service for geospatial ETL pipeline
Reprojects rasters to target CRS (EPSG:4326 for Silver tier)
"""
import logging
from typing import Optional, Dict, Any
import rasterio
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.io import MemoryFile
from rasterio.errors import RasterioError

from config import Config, RasterConfig
from repositories import StorageRepository

logger = logging.getLogger(__name__)


class RasterReprojector:
    """Service for reprojecting raster files"""
    
    def __init__(self):
        """Initialize with storage repository"""
        self.storage_repo = StorageRepository()
        self.bronze_container = Config.BRONZE_CONTAINER_NAME or "rmhazuregeobronze"
        self.silver_container = Config.SILVER_CONTAINER_NAME or "rmhazuregeosilver"
        
    def needs_reprojection(self, current_epsg: int, target_epsg: int = None) -> bool:
        """
        Check if reprojection is needed
        
        Args:
            current_epsg: Current EPSG code
            target_epsg: Target EPSG code (defaults to RasterConfig.TARGET_EPSG)
            
        Returns:
            True if reprojection needed, False otherwise
        """
        if target_epsg is None:
            target_epsg = RasterConfig.TARGET_EPSG
            
        return current_epsg != target_epsg
    
    def reproject_raster(
        self,
        source_container: str,
        source_blob: str,
        dest_container: str,
        dest_blob: str,
        source_epsg: int,
        target_epsg: int = None,
        use_smart_mode: bool = None
    ) -> Dict[str, Any]:
        """
        Reproject raster to target CRS
        
        Args:
            source_container: Source container name
            source_blob: Source blob name
            dest_container: Destination container name  
            dest_blob: Destination blob name
            source_epsg: Source EPSG code
            target_epsg: Target EPSG code (defaults to 4326)
            use_smart_mode: Use URL access for large files (auto-detected if None)
            
        Returns:
            Result dictionary with status and metadata
        """
        result = {
            "success": False,
            "errors": [],
            "warnings": [],
            "metadata": {}
        }
        
        # Default to WGS84 for Silver tier
        if target_epsg is None:
            target_epsg = RasterConfig.TARGET_EPSG
            logger.info(f"Using default target EPSG:{target_epsg} for Silver tier")
            
        # Check if reprojection is needed
        if not self.needs_reprojection(source_epsg, target_epsg):
            result["warnings"].append(f"Raster already in EPSG:{target_epsg}, no reprojection needed")
            
            # Copy file as-is to destination
            try:
                self.storage_repo.copy_blob(
                    source_blob, dest_blob,
                    source_container, dest_container,
                    overwrite=True
                )
                result["success"] = True
                result["metadata"]["reprojected"] = False
                result["metadata"]["source_epsg"] = source_epsg
                result["metadata"]["target_epsg"] = target_epsg
                return result
            except Exception as e:
                result["errors"].append(f"Error copying raster: {str(e)}")
                return result
                
        # Determine if we should use smart mode (URL access) based on file size
        if use_smart_mode is None:
            blob_props = self.storage_repo.get_blob_properties(source_container, source_blob)
            if blob_props:
                size_mb = blob_props.get("size", 0) / (1024 * 1024)
                use_smart_mode = size_mb > RasterConfig.MAX_DOWNLOAD_SIZE_MB
                if use_smart_mode:
                    logger.info(f"File size {size_mb:.1f}MB exceeds threshold, using smart mode")
                    
        try:
            # Create CRS objects
            crs_in = CRS.from_epsg(source_epsg)
            crs_out = CRS.from_epsg(target_epsg)
            
            # Get source URL for rasterio
            source_url = self.storage_repo.get_blob_sas_url(source_container, source_blob)
            
            # Open source raster
            with rasterio.open(source_url) as src:
                # Calculate transform for new CRS
                transform, width, height = calculate_default_transform(
                    crs_in, crs_out, 
                    src.width, src.height, 
                    *src.bounds
                )
                
                # Update metadata for output
                kwargs = src.meta.copy()
                kwargs.update({
                    'crs': crs_out,
                    'transform': transform,
                    'width': width,
                    'height': height
                })
                
                # Store metadata
                result["metadata"]["source_epsg"] = source_epsg
                result["metadata"]["target_epsg"] = target_epsg
                result["metadata"]["source_dimensions"] = f"{src.width}x{src.height}"
                result["metadata"]["target_dimensions"] = f"{width}x{height}"
                result["metadata"]["bands"] = src.count
                
                # Reproject to memory
                logger.info(f"Reprojecting {source_blob} from EPSG:{source_epsg} to EPSG:{target_epsg}")
                
                with MemoryFile() as memfile:
                    with memfile.open(**kwargs) as dst:
                        # Reproject each band
                        for band_idx in range(1, src.count + 1):
                            reproject(
                                source=rasterio.band(src, band_idx),
                                destination=rasterio.band(dst, band_idx),
                                src_transform=src.transform,
                                src_crs=crs_in,
                                dst_transform=transform,
                                dst_crs=crs_out,
                                resampling=Resampling.bilinear  # Using bilinear as defined in config
                            )
                            
                    # Upload reprojected raster
                    memfile.seek(0)
                    self.storage_repo.upload_blob(
                        dest_blob,
                        memfile.read(),
                        dest_container,
                        overwrite=True
                    )
                    
                result["success"] = True
                result["metadata"]["reprojected"] = True
                logger.info(f"Successfully reprojected {source_blob} to {dest_blob}")
                
        except RasterioError as e:
            result["errors"].append(f"Rasterio error during reprojection: {str(e)}")
            logger.error(f"Rasterio error: {e}")
        except Exception as e:
            result["errors"].append(f"Error during reprojection: {str(e)}")
            logger.error(f"Reprojection error: {e}")
            
        return result