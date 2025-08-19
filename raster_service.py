"""
Raster Processing Service for Geospatial ETL Pipeline
Handles COG conversion, reprojection, and raster validation
Based on proven processing logic with modern service architecture
"""
from typing import Dict, List, Optional, Tuple
import uuid
from io import BytesIO

try:
    from rasterio import open as rasterio_open
    from rasterio import band as rasterio_band
    from rasterio.crs import CRS
    from rasterio.io import MemoryFile
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rio_cogeo.cogeo import cog_translate, cog_validate
    from rio_cogeo.profiles import cog_profiles
except ImportError as e:
    # Log but don't fail - allows deployment even if rasterio not installed
    import logging
    logging.warning(f"Raster processing libraries not available: {e}")
    rasterio_open = None

from services import BaseProcessingService
from repositories import StorageRepository
from config import Config
from logger_setup import logger, log_job_stage, log_service_processing


class RasterProcessingService(BaseProcessingService):
    """
    Service for raster processing operations including:
    - COG (Cloud Optimized GeoTIFF) conversion
    - Raster reprojection
    - Format validation
    """
    
    DEFAULT_EPSG = 4326  # WGS84 - standard web mapping projection
    VALID_EXTENSIONS = {'.tif', '.tiff', '.geotiff', '.geotif'}
    MAX_RASTER_NAME_LENGTH = 255
    
    def __init__(self):
        """Initialize raster processing service"""
        self.storage_repo = StorageRepository()
        self.operation_id = None
        
    def get_supported_operations(self) -> List[str]:
        """Return list of supported raster operations"""
        return [
            "cog_conversion",
            "reproject_raster", 
            "validate_raster",
            "raster_info"
        ]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str) -> Dict:
        """
        Process raster operations
        
        Args:
            job_id: Unique job identifier (used for tracking)
            dataset_id: Container name for input data
            resource_id: Input raster filename
            version_id: Processing parameters (format: "key1:value1,key2:value2")
                Examples:
                - "epsg:3857" - reproject to Web Mercator
                - "epsg:3857,compress:lzw" - reproject and compress
                - "cog:true,overview:4" - create COG with 4 overview levels
            operation_type: Type of operation to perform
            
        Returns:
            Dict with processing results
        """
        # Check if rasterio is available
        if rasterio_open is None:
            raise ImportError("Raster processing libraries not installed. Run: pip install rasterio rio-cogeo")
        
        self.operation_id = job_id[:8]  # Use first 8 chars for file naming
        
        logger.info(f"Starting raster processing - Job: {job_id}, Operation: {operation_type}")
        log_job_stage(job_id, f"raster_{operation_type}_start", "processing")
        
        try:
            # Parse parameters from version_id
            params = self._parse_params(version_id)
            logger.debug(f"Parsed parameters: {params}")
            
            # Route to appropriate processor
            if operation_type == "cog_conversion":
                result = self._process_cog_conversion(
                    container_name=dataset_id,
                    raster_name=resource_id,
                    params=params
                )
            elif operation_type == "reproject_raster":
                result = self._process_reprojection(
                    container_name=dataset_id,
                    raster_name=resource_id,
                    params=params
                )
            elif operation_type == "validate_raster":
                result = self._validate_raster(
                    container_name=dataset_id,
                    raster_name=resource_id
                )
            elif operation_type == "raster_info":
                result = self._get_raster_info(
                    container_name=dataset_id,
                    raster_name=resource_id
                )
            else:
                raise ValueError(f"Unsupported raster operation: {operation_type}")
            
            log_job_stage(job_id, f"raster_{operation_type}_complete", "completed")
            log_service_processing("RasterProcessingService", operation_type, job_id, "completed")
            
            return result
            
        except Exception as e:
            logger.error(f"Raster processing failed for job {job_id}: {str(e)}")
            log_service_processing("RasterProcessingService", operation_type, job_id, "failed")
            raise
    
    def _parse_params(self, version_id: str) -> Dict:
        """
        Parse parameters from version_id string
        
        Format: "key1:value1,key2:value2"
        Example: "epsg:3857,compress:lzw,overview:4"
        """
        params = {}
        if version_id and version_id not in ['none', 'None', 'null']:
            for param in version_id.split(','):
                if ':' in param:
                    key, value = param.split(':', 1)
                    # Convert numeric values
                    if value.isdigit():
                        params[key.lower()] = int(value)
                    elif value.lower() in ['true', 'false']:
                        params[key.lower()] = value.lower() == 'true'
                    else:
                        params[key.lower()] = value
        return params
    
    def _process_cog_conversion(self, container_name: str, 
                                raster_name: str, params: Dict) -> Dict:
        """
        Convert raster to Cloud Optimized GeoTIFF
        
        Pipeline:
        1. Validate input raster
        2. Reproject if target EPSG specified
        3. Create COG with compression
        4. Save to silver container
        """
        logger.info(f"Starting COG conversion for {raster_name}")
        
        # Validate input exists
        if not self.storage_repo.blob_exists(raster_name, container_name):
            raise FileNotFoundError(f"Input raster not found: {raster_name} in {container_name}")
        
        # Get current and target EPSG
        current_epsg = self._get_raster_epsg(container_name, raster_name)
        target_epsg = int(params.get('epsg', current_epsg or self.DEFAULT_EPSG))
        
        # Determine compression profile
        compress = params.get('compress', 'lzw').lower()
        if compress not in cog_profiles:
            logger.warning(f"Unknown compression {compress}, using LZW")
            compress = 'lzw'
        
        # Generate output names
        name_base = raster_name.split('.')[0][:30]
        intermediate_name = f"{name_base}_{self.operation_id}_reproj.tif"
        output_name = f"{name_base}_{self.operation_id}_cog.tif"
        
        # Step 1: Reproject if needed
        working_raster = raster_name
        if current_epsg and current_epsg != target_epsg:
            logger.info(f"Reprojecting from EPSG:{current_epsg} to EPSG:{target_epsg}")
            working_raster = self._reproject_raster(
                container_name=container_name,
                input_name=raster_name,
                output_name=intermediate_name,
                target_epsg=target_epsg
            )
        
        # Step 2: Create COG
        logger.info(f"Creating COG from {working_raster} with {compress} compression")
        cog_data = self._create_cog(
            container_name=container_name,
            raster_name=working_raster,
            compress_profile=compress
        )
        
        # Step 3: Save to output container
        output_container = Config.SILVER_CONTAINER_NAME or container_name
        self.storage_repo.upload_blob_data(
            blob_data=cog_data,
            dest_blob_name=output_name,
            container_name=output_container,
            overwrite=True
        )
        
        # Step 4: Validate COG
        is_valid_cog = self._validate_cog(output_container, output_name)
        
        # Clean up intermediate files
        if working_raster != raster_name and self.storage_repo.blob_exists(working_raster, container_name):
            logger.debug(f"Cleaning up intermediate file: {working_raster}")
            self.storage_repo.delete_blob(working_raster, container_name)
        
        # Get output file size
        output_size = self.storage_repo.get_blob_size(output_name, output_container)
        
        logger.info(f"COG conversion complete: {output_name} ({output_size / 1024 / 1024:.2f} MB)")
        
        return {
            "status": "completed",
            "operation": "cog_conversion",
            "input": {
                "container": container_name,
                "raster": raster_name,
                "epsg": current_epsg
            },
            "output": {
                "container": output_container,
                "raster": output_name,
                "epsg": target_epsg,
                "format": "COG",
                "compression": compress,
                "valid_cog": is_valid_cog,
                "size_mb": round(output_size / 1024 / 1024, 2)
            },
            "processing": {
                "reprojected": current_epsg != target_epsg,
                "operation_id": self.operation_id
            }
        }
    
    def _process_reprojection(self, container_name: str,
                              raster_name: str, params: Dict) -> Dict:
        """
        Reproject raster to target CRS
        """
        logger.info(f"Starting reprojection for {raster_name}")
        
        # Validate input
        if not self.storage_repo.blob_exists(raster_name, container_name):
            raise FileNotFoundError(f"Input raster not found: {raster_name} in {container_name}")
        
        # Get target EPSG
        target_epsg = int(params.get('epsg', self.DEFAULT_EPSG))
        current_epsg = self._get_raster_epsg(container_name, raster_name)
        
        if current_epsg == target_epsg:
            logger.info(f"Raster already in EPSG:{target_epsg}, no reprojection needed")
            return {
                "status": "completed",
                "operation": "reproject_raster",
                "message": f"Already in target projection EPSG:{target_epsg}",
                "input": {
                    "container": container_name,
                    "raster": raster_name,
                    "epsg": current_epsg
                }
            }
        
        # Generate output name
        name_base = raster_name.split('.')[0][:30]
        output_name = f"{name_base}_{self.operation_id}_epsg{target_epsg}.tif"
        
        # Perform reprojection
        output_name = self._reproject_raster(
            container_name=container_name,
            input_name=raster_name,
            output_name=output_name,
            target_epsg=target_epsg
        )
        
        # Save to silver container
        output_container = Config.SILVER_CONTAINER_NAME or container_name
        if output_container != container_name:
            # Copy to silver container
            self.storage_repo.copy_blob(
                source_blob_name=output_name,
                source_container_name=container_name,
                dest_blob_name=output_name,
                dest_container_name=output_container,
                overwrite=True
            )
            # Delete from workspace
            self.storage_repo.delete_blob(output_name, container_name)
        
        output_size = self.storage_repo.get_blob_size(output_name, output_container)
        
        return {
            "status": "completed",
            "operation": "reproject_raster",
            "input": {
                "container": container_name,
                "raster": raster_name,
                "epsg": current_epsg
            },
            "output": {
                "container": output_container,
                "raster": output_name,
                "epsg": target_epsg,
                "size_mb": round(output_size / 1024 / 1024, 2)
            }
        }
    
    def _get_raster_epsg(self, container_name: str, raster_name: str) -> Optional[int]:
        """Get EPSG code from raster CRS"""
        sas_uri = self.storage_repo.get_blob_sas_uri(container_name, raster_name)
        
        try:
            with rasterio_open(sas_uri) as src:
                if src.crs:
                    epsg = src.crs.to_epsg()
                    if epsg:
                        logger.debug(f"Detected EPSG:{epsg} for {raster_name}")
                        return epsg
                    else:
                        logger.warning(f"CRS found but no EPSG code for {raster_name}: {src.crs}")
                        return None
                else:
                    logger.warning(f"No CRS found in {raster_name}")
                    return None
        except Exception as e:
            logger.error(f"Error reading CRS from {raster_name}: {e}")
            return None
    
    def _reproject_raster(self, container_name: str, input_name: str,
                          output_name: str, target_epsg: int) -> str:
        """
        Reproject raster to target CRS
        
        Returns: output filename
        """
        sas_uri = self.storage_repo.get_blob_sas_uri(container_name, input_name)
        target_crs = CRS.from_epsg(target_epsg)
        
        logger.debug(f"Reprojecting {input_name} to EPSG:{target_epsg}")
        
        with rasterio_open(sas_uri) as src:
            # Calculate transform for new CRS
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds
            )
            
            # Copy metadata and update for new projection
            kwargs = src.meta.copy()
            kwargs.update({
                'crs': target_crs,
                'transform': transform,
                'width': width,
                'height': height
            })
            
            # Process in memory
            with MemoryFile() as memfile:
                with memfile.open(**kwargs) as dst:
                    # Reproject each band
                    for band_id in range(1, src.count + 1):
                        reproject(
                            source=rasterio_band(src, band_id),
                            destination=rasterio_band(dst, band_id),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=target_crs,
                            resampling=Resampling.bilinear
                        )
                
                # Save to storage
                memfile.seek(0)
                self.storage_repo.upload_blob_data(
                    blob_data=memfile.read(),
                    dest_blob_name=output_name,
                    container_name=container_name,
                    overwrite=True
                )
        
        logger.info(f"Reprojection complete: {output_name}")
        return output_name
    
    def _create_cog(self, container_name: str, raster_name: str,
                    compress_profile: str = 'lzw') -> bytes:
        """
        Create Cloud Optimized GeoTIFF
        
        Returns: COG data as bytes
        """
        sas_uri = self.storage_repo.get_blob_sas_uri(container_name, raster_name)
        
        with rasterio_open(sas_uri) as src:
            with MemoryFile() as memfile:
                # Create COG with specified compression
                cog_translate(
                    source=src,
                    dst_path=memfile.name,
                    dst_kwargs=cog_profiles.get(compress_profile),
                    web_optimized=True,
                    in_memory=True,
                    quiet=False  # Show progress
                )
                memfile.seek(0)
                return memfile.read()
    
    def _validate_cog(self, container_name: str, raster_name: str) -> bool:
        """Validate if raster is a valid COG"""
        try:
            sas_uri = self.storage_repo.get_blob_sas_uri(container_name, raster_name)
            # cog_validate returns True and warnings list
            is_valid, errors, warnings = cog_validate(sas_uri, quiet=True)
            
            if errors:
                logger.warning(f"COG validation errors for {raster_name}: {errors}")
            if warnings:
                logger.debug(f"COG validation warnings for {raster_name}: {warnings}")
                
            return is_valid
        except Exception as e:
            logger.error(f"Error validating COG {raster_name}: {e}")
            return False
    
    def _validate_raster(self, container_name: str, raster_name: str) -> Dict:
        """Validate raster file and return metadata"""
        if not self.storage_repo.blob_exists(raster_name, container_name):
            raise FileNotFoundError(f"Raster not found: {raster_name} in {container_name}")
        
        # Validate filename
        is_valid_name, name_errors = self._validate_raster_name(raster_name)
        
        # Get raster info
        info = self._get_raster_info(container_name, raster_name)
        
        # Check if it's a COG
        is_cog = self._validate_cog(container_name, raster_name)
        
        return {
            "status": "completed",
            "operation": "validate_raster",
            "validation": {
                "valid_filename": is_valid_name,
                "filename_errors": name_errors,
                "is_cog": is_cog,
                "has_crs": info.get("crs", {}).get("epsg") is not None
            },
            "raster_info": info
        }
    
    def _get_raster_info(self, container_name: str, raster_name: str) -> Dict:
        """Get detailed raster information"""
        # Download blob to memory first
        blob_client = self.storage_repo.blob_service_client.get_blob_client(
            container=container_name, 
            blob=raster_name
        )
        blob_data = blob_client.download_blob().readall()
        
        # Open from memory using MemoryFile
        with MemoryFile(blob_data) as memfile:
            with memfile.open() as src:
                # Get CRS info
                crs_info = {}
                if src.crs:
                    crs_info = {
                        "epsg": src.crs.to_epsg(),
                        "wkt": src.crs.to_wkt(),
                        "proj4": src.crs.to_proj4() if hasattr(src.crs, 'to_proj4') else None
                    }
                
                # Get bounds in native and lat/lon
                bounds_native = src.bounds
                bounds_latlon = None
                if src.crs:
                    try:
                        from rasterio.warp import transform_bounds
                        bounds_latlon = transform_bounds(src.crs, CRS.from_epsg(4326), *bounds_native)
                    except:
                        pass
                
                return {
                    "filename": raster_name,
                    "container": container_name,
                    "dimensions": {
                        "width": src.width,
                        "height": src.height,
                        "bands": src.count
                    },
                    "crs": crs_info,
                    "bounds": {
                        "native": {
                            "left": bounds_native.left,
                            "bottom": bounds_native.bottom,
                            "right": bounds_native.right,
                            "top": bounds_native.top
                        },
                        "latlon": bounds_latlon if bounds_latlon else None
                    },
                    "pixel_size": {
                        "x": src.transform[0],
                        "y": -src.transform[4]  # Usually negative
                    },
                    "dtypes": [str(src.dtypes[i]) for i in range(src.count)],
                    "nodata": src.nodata,
                    "driver": src.driver,
                    "compress": str(src.compression) if hasattr(src, 'compression') else None
                }
    
    def _validate_raster_name(self, raster_name: str) -> Tuple[bool, List[str]]:
        """
        Validate raster filename
        
        Returns: (is_valid, list_of_errors)
        """
        errors = []
        
        if not raster_name:
            errors.append("Filename is empty")
            return False, errors
        
        # Check extension
        if '.' not in raster_name:
            errors.append("No file extension")
        else:
            ext = '.' + raster_name.split('.')[-1].lower()
            if ext not in self.VALID_EXTENSIONS:
                errors.append(f"Invalid extension {ext}, must be one of {self.VALID_EXTENSIONS}")
        
        # Check length
        if len(raster_name) > self.MAX_RASTER_NAME_LENGTH:
            errors.append(f"Filename exceeds {self.MAX_RASTER_NAME_LENGTH} characters")
        
        # Check for invalid characters (allow alphanumeric, underscore, hyphen, period)
        import re
        if not re.match(r'^[\w\-\.]+$', raster_name):
            errors.append("Filename contains invalid characters")
        
        return len(errors) == 0, errors