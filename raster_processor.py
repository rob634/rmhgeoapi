"""
Raster processing service for geospatial ETL pipeline
Orchestrates the full Bronze → Silver raster processing pipeline
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import os

logger = logging.getLogger(__name__)

from config import Config, RasterConfig
from services import BaseProcessingService

# These imports may fail in Azure Functions due to GDAL dependencies
try:
    from raster_validator import RasterValidator
    from raster_reprojector import RasterReprojector
    from cog_converter import COGConverter
    from stac_cog_cataloger import STACCOGCataloger
    from raster_mosaic import RasterMosaicService
    RASTER_LIBS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Raster processing libraries not available: {e}")
    RASTER_LIBS_AVAILABLE = False


class RasterProcessorService(BaseProcessingService):
    """
    Main raster processing service that orchestrates:
    1. Validation
    2. Reprojection to EPSG:4326
    3. COG conversion
    4. Bronze → Silver movement
    """
    
    def __init__(self):
        """Initialize raster processing components"""
        super().__init__()
        
        # Initialize components that inherit from BaseRasterProcessor
        # Each has its own storage access through base class
        self.validator = RasterValidator()
        self.reprojector = RasterReprojector()
        self.cog_converter = COGConverter()
        self.mosaic_service = RasterMosaicService()
        self.stac_cataloger = None  # Initialize on demand to avoid DB connection if not needed
        
        # Container configuration
        self.bronze_container = Config.BRONZE_CONTAINER_NAME or "rmhazuregeobronze"
        self.silver_container = Config.SILVER_CONTAINER_NAME or "rmhazuregeosilver"
    
    def get_supported_operations(self) -> list[str]:
        """Return list of supported operations"""
        return ["process_raster", "cog_conversion", "mosaic_cog"]
        
    def process(
        self,
        job_id: str,
        dataset_id: str,
        resource_id: str,
        version_id: str,
        operation_type: str,
        system: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Process raster from Bronze to Silver tier
        
        Expected parameters:
        - dataset_id: Source container (typically bronze)
        - resource_id: Raster file name OR comma-separated list for mosaic
        - version_id: Not used for single raster, or output name for mosaic
        - Additional kwargs:
            - input_epsg: Optional EPSG code if raster has no CRS
            - skip_validation: Skip validation step
            - skip_cog: Skip COG conversion (just reproject)
            - mosaic_mode: If true, treat resource_id as multiple files
            - target_crs: Target CRS for mosaic (default: EPSG:4326)
            
        Returns:
            Processing result with metadata
        """
        start_time = datetime.now(timezone.utc)
        result = {
            "job_id": job_id,
            "operation": "raster_processing",
            "timestamp": start_time.isoformat(),
            "source_container": dataset_id,
            "source_file": resource_id,
            "status": "started",
            "steps": {}
        }
        
        # Extract additional parameters
        input_epsg = kwargs.get("input_epsg")
        skip_validation = kwargs.get("skip_validation", False)
        skip_cog = kwargs.get("skip_cog", False)
        mosaic_mode = kwargs.get("mosaic_mode", False) or operation_type == "mosaic_cog"
        target_crs = kwargs.get("target_crs", "EPSG:4326")
        
        # Use dataset_id as container name (for flexibility)
        source_container = dataset_id if dataset_id else self.bronze_container
        
        # Check if we're processing multiple files (mosaic)
        if mosaic_mode or ',' in resource_id or resource_id.startswith('['):
            # Multiple input files - mosaic mode
            return self._process_mosaic(
                job_id, source_container, resource_id, version_id,
                target_crs, skip_validation, result
            )
        
        # Single file processing
        base_name = os.path.basename(resource_id)
        name_without_ext = base_name.rsplit('.', 1)[0]
        output_name = f"{name_without_ext}_cog.tif"
        
        logger.info(f"Processing raster: {resource_id} from {source_container} to {self.silver_container}/{output_name}")
        
        try:
            # Step 1: Validation
            if not skip_validation:
                logger.info(f"Step 1: Validating raster {resource_id}")
                validation_result = self.validator.validate_raster(
                    source_container,
                    resource_id,
                    input_epsg
                )
                
                result["steps"]["validation"] = {
                    "valid": validation_result["valid"],
                    "errors": validation_result.get("errors", []),
                    "warnings": validation_result.get("warnings", []),
                    "metadata": validation_result.get("metadata", {})
                }
                
                if not validation_result["valid"]:
                    result["status"] = "failed"
                    result["error"] = f"Validation failed: {'; '.join(validation_result['errors'])}"
                    return result
                    
                # Extract EPSG from validation
                source_epsg = validation_result["metadata"].get("epsg")
                if not source_epsg:
                    result["status"] = "failed"
                    result["error"] = "No EPSG code found or provided for raster"
                    return result
            else:
                # If skipping validation, we need input_epsg
                if not input_epsg:
                    result["status"] = "failed"
                    result["error"] = "Cannot skip validation without providing input_epsg"
                    return result
                source_epsg = input_epsg
                result["steps"]["validation"] = {"skipped": True}
                
            # Check file size before processing (Premium Plan limit)
            file_size_mb = result["steps"]["validation"].get("metadata", {}).get("size_mb", 0)
            file_size_gb = file_size_mb / 1024
            
            if file_size_gb > RasterConfig.MAX_PROCESSING_SIZE_GB:
                logger.error(f"File size {file_size_gb:.2f}GB exceeds maximum {RasterConfig.MAX_PROCESSING_SIZE_GB}GB for Premium Plan")
                result["status"] = "failed"
                result["error"] = (
                    f"File size {file_size_gb:.2f}GB exceeds maximum {RasterConfig.MAX_PROCESSING_SIZE_GB}GB. "
                    "Premium Plan memory limitation. Future enhancement will support sequential batch processing for very large GeoTIFFs."
                )
                return result
            elif file_size_gb > 3:  # Warning threshold at 3GB
                logger.warning(f"Large file warning: {file_size_gb:.2f}GB approaching {RasterConfig.MAX_PROCESSING_SIZE_GB}GB limit")
                result["steps"]["validation"]["warnings"].append(
                    f"Large file ({file_size_gb:.2f}GB) - approaching memory limits. Processing may fail if reprojection is needed."
                )
            
            # Step 2: Reprojection to EPSG:4326
            logger.info(f"Step 2: Reprojecting raster from EPSG:{source_epsg} to EPSG:{RasterConfig.TARGET_EPSG}")
            
            # Use temporary name for reprojected file
            temp_reprojected = f"_temp/{job_id}/{name_without_ext}_4326.tif"
            
            reproject_result = self.reprojector.reproject_raster(
                source_container,
                resource_id,
                self.silver_container,  # Use silver for temp storage
                temp_reprojected,
                source_epsg,
                RasterConfig.TARGET_EPSG
            )
            
            result["steps"]["reprojection"] = {
                "success": reproject_result["success"],
                "errors": reproject_result.get("errors", []),
                "warnings": reproject_result.get("warnings", []),
                "metadata": reproject_result.get("metadata", {})
            }
            
            if not reproject_result["success"]:
                result["status"] = "failed"
                result["error"] = f"Reprojection failed: {'; '.join(reproject_result['errors'])}"
                return result
                
            # Step 3: COG Conversion
            if not skip_cog:
                logger.info(f"Step 3: Converting to Cloud Optimized GeoTIFF")
                
                # Determine source for COG conversion
                if reproject_result["metadata"].get("reprojected", False):
                    cog_source = temp_reprojected
                else:
                    # File was already in correct projection, use original
                    cog_source = resource_id
                    
                cog_result = self.cog_converter.convert_to_cog(
                    self.silver_container if reproject_result["metadata"].get("reprojected", False) else source_container,
                    cog_source,
                    self.silver_container,
                    output_name
                )
                
                result["steps"]["cog_conversion"] = {
                    "success": cog_result["success"],
                    "errors": cog_result.get("errors", []),
                    "warnings": cog_result.get("warnings", []),
                    "metadata": cog_result.get("metadata", {})
                }
                
                if not cog_result["success"]:
                    result["status"] = "failed"
                    result["error"] = f"COG conversion failed: {'; '.join(cog_result['errors'])}"
                    return result
                    
                # Clean up temporary reprojected file if it exists
                if reproject_result["metadata"].get("reprojected", False):
                    try:
                        # Use the reprojector's storage to delete temp file
                        self.reprojector.storage.delete_blob(temp_reprojected, self.silver_container)
                        logger.info(f"Cleaned up temporary file: {temp_reprojected}")
                    except Exception as e:
                        logger.warning(f"Could not clean up temp file {temp_reprojected}: {e}")
            else:
                result["steps"]["cog_conversion"] = {"skipped": True}
                output_name = temp_reprojected  # Use reprojected file as final output
                
            # Success!
            result["status"] = "completed"
            result["output_container"] = self.silver_container
            result["output_file"] = output_name
            result["processing_time_seconds"] = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            # Add summary
            result["summary"] = {
                "source": f"{source_container}/{resource_id}",
                "destination": f"{self.silver_container}/{output_name}",
                "source_epsg": source_epsg,
                "target_epsg": RasterConfig.TARGET_EPSG,
                "cog_created": not skip_cog,
                "warnings_count": sum(len(step.get("warnings", [])) for step in result["steps"].values() if isinstance(step, dict))
            }
            
            # Step 4: Catalog in STAC (optional but recommended)
            catalog_to_stac = kwargs.get("catalog_to_stac", True)
            if catalog_to_stac and result["status"] == "completed":
                logger.info(f"Step 4: Cataloging COG in STAC database")
                try:
                    # Initialize STAC cataloger if not already done
                    if self.stac_cataloger is None:
                        self.stac_cataloger = STACCOGCataloger()
                    
                    # Prepare source info for STAC
                    source_info = {
                        "container": source_container,
                        "file": resource_id,
                        "epsg": source_epsg
                    }
                    
                    # Prepare processing info for STAC
                    processing_info = {
                        "reprojected": result["steps"].get("reprojection", {}).get("metadata", {}).get("reprojected", False),
                        "cog_profile": result["steps"].get("cog_conversion", {}).get("metadata", {}).get("cog_profile", "lzw"),
                        "cog_size_mb": result["steps"].get("cog_conversion", {}).get("metadata", {}).get("cog_size_mb", 0)
                    }
                    
                    # Catalog the COG
                    stac_result = self.stac_cataloger.catalog_cog(
                        self.silver_container,
                        output_name,
                        source_info,
                        processing_info
                    )
                    
                    result["steps"]["stac_cataloging"] = {
                        "success": stac_result["success"],
                        "errors": stac_result.get("errors", []),
                        "warnings": stac_result.get("warnings", []),
                        "stac_item_id": stac_result.get("stac_item", {}).get("id") if stac_result["success"] else None
                    }
                    
                    if stac_result["success"]:
                        logger.info(f"Successfully cataloged COG in STAC: {stac_result['stac_item']['id']}")
                        result["summary"]["stac_cataloged"] = True
                        result["summary"]["stac_item_id"] = stac_result["stac_item"]["id"]
                    else:
                        logger.warning(f"Failed to catalog COG in STAC: {stac_result.get('errors', [])}")
                        result["summary"]["stac_cataloged"] = False
                        
                except Exception as e:
                    logger.error(f"Error during STAC cataloging: {e}")
                    result["steps"]["stac_cataloging"] = {
                        "success": False,
                        "errors": [str(e)],
                        "warnings": []
                    }
                    result["summary"]["stac_cataloged"] = False
            elif not catalog_to_stac:
                result["steps"]["stac_cataloging"] = {"skipped": True}
                logger.info("Skipping STAC cataloging as requested")
            
            logger.info(f"Successfully processed raster: {resource_id} → {output_name}")
            
        except Exception as e:
            logger.error(f"Unexpected error processing raster: {e}")
            result["status"] = "failed"
            result["error"] = str(e)
            
        return result


    def _process_mosaic(self, job_id: str, source_container: str, resource_id: str,
                       version_id: str, target_crs: str, skip_validation: bool,
                       result: Dict) -> Dict:
        """
        Process multiple raster files into a single mosaic COG
        
        Args:
            job_id: Job ID
            source_container: Source container name
            resource_id: Comma-separated list of file names or JSON array
            version_id: Output file name (without extension)
            target_crs: Target CRS for mosaic
            skip_validation: Skip validation step
            result: Result dictionary to update
            
        Returns:
            Processing result
        """
        import json
        import tempfile
        
        try:
            # Parse input files
            if resource_id.startswith('['):
                # JSON array format
                input_files = json.loads(resource_id)
            else:
                # Comma-separated format
                input_files = [f.strip() for f in resource_id.split(',')]
            
            logger.info(f"Creating mosaic from {len(input_files)} input files")
            result["input_files"] = input_files
            result["operation"] = "mosaic_cog_creation"
            
            # Use storage from one of our components (they all share the same instance)
            storage_repo = self.validator.storage
            
            # Check total file size to determine if we need chunked processing
            total_size_mb = 0
            file_sizes = []
            for file_name in input_files:
                try:
                    blob_properties = storage_repo.get_blob_properties(source_container, file_name)
                    size_mb = blob_properties.get('size', 0) / (1024 * 1024)
                    file_sizes.append(size_mb)
                    total_size_mb += size_mb
                except Exception as e:
                    logger.warning(f"Could not get size for {file_name}: {e}")
                    file_sizes.append(0)
            
            logger.info(f"Total input size for mosaic: {total_size_mb:.2f} MB across {len(input_files)} files")
            
            # If total size > 1GB or more than 10 files, use chunked processing
            USE_CHUNKED_THRESHOLD_MB = 1000  # 1GB
            USE_CHUNKED_FILE_COUNT = 10
            
            if total_size_mb > USE_CHUNKED_THRESHOLD_MB or len(input_files) > USE_CHUNKED_FILE_COUNT:
                logger.warning(f"Mosaic operation exceeds thresholds (size: {total_size_mb:.2f}MB, files: {len(input_files)})")
                logger.info("Switching to chunked processing for large mosaic operation")
                
                # Initialize chunked processor
                from raster_chunked_processor import ChunkedMosaicService
                chunked_service = ChunkedMosaicService()
                
                # Start chunked mosaic operation
                chunked_result = chunked_service.start_chunked_mosaic(
                    job_id=job_id,
                    input_files=input_files,
                    source_container=source_container,
                    output_name=version_id if version_id != "v1" else "mosaic_output",
                    target_crs=target_crs
                )
                
                result.update(chunked_result)
                result["processing_mode"] = "chunked"
                result["info"] = f"Large mosaic operation started with chunked processing. Total size: {total_size_mb:.2f}MB"
                return result
            
            # Continue with standard mosaic processing for smaller operations
            logger.info("Using standard mosaic processing (within size limits)")
            
            # Validate all input files exist and are compatible
            if not skip_validation:
                logger.info("Validating input files for mosaic compatibility")
                
                # Generate SAS URLs for all input files
                input_urls = []
                for file_name in input_files:
                    file_url = storage_repo.get_blob_sas_url(
                        source_container,
                        file_name,
                        expiry_hours=2
                    )
                    input_urls.append(file_url)
                
                # Validate mosaic compatibility
                validation_result = self.mosaic_service.validate_inputs(input_urls)
                result["steps"]["validation"] = validation_result
                
                if not validation_result.get("valid", False):
                    result["status"] = "failed"
                    result["error"] = validation_result.get("error", "Input validation failed")
                    return result
                
                # Detect tile pattern
                pattern_info = self.mosaic_service.detect_tile_pattern(input_files)
                result["tile_pattern"] = pattern_info
            else:
                # If skipping validation, still need to generate URLs
                input_urls = []
                for file_name in input_files:
                    file_url = storage_repo.get_blob_sas_url(
                        source_container,
                        file_name,
                        expiry_hours=2
                    )
                    input_urls.append(file_url)
            
            # Generate output name
            if version_id and version_id != "v1":
                output_name = f"{version_id}_mosaic_cog.tif" if not version_id.endswith('.tif') else version_id
            else:
                # Use base name from first file or pattern
                base_name = result.get("tile_pattern", {}).get("base_name", "merged")
                output_name = f"{base_name}_mosaic_cog.tif"
            
            # Create temporary file for mosaic
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp_file:
                temp_mosaic_path = tmp_file.name
            
            logger.info(f"Creating mosaic at temporary path: {temp_mosaic_path}")
            
            # Step 1: Create mosaic
            mosaic_result = self.mosaic_service.create_mosaic(
                input_files=input_urls,
                output_path=temp_mosaic_path,
                target_crs=target_crs,
                resampling_method='bilinear'
            )
            
            result["steps"]["mosaic"] = mosaic_result
            
            if not mosaic_result.get("success", False):
                result["status"] = "failed"
                result["error"] = mosaic_result.get("error", "Mosaic creation failed")
                return result
            
            # Step 2: Convert mosaic to COG
            logger.info("Converting mosaic to COG format")
            with tempfile.NamedTemporaryFile(suffix='_cog.tif', delete=False) as tmp_cog:
                temp_cog_path = tmp_cog.name
            
            cog_result = self.cog_converter.convert_to_cog(
                temp_mosaic_path,
                temp_cog_path,
                validate_result=False  # Skip re-validation
            )
            
            result["steps"]["cog_conversion"] = cog_result
            
            if not cog_result.get("success", False):
                result["status"] = "failed"
                result["error"] = cog_result.get("error", "COG conversion failed")
                return result
            
            # Step 3: Upload to Silver container
            logger.info(f"Uploading mosaic COG to {self.silver_container}/{output_name}")
            
            with open(temp_cog_path, 'rb') as cog_file:
                upload_result = storage_repo.upload_blob(
                    blob_name=output_name,
                    data=cog_file.read(),
                    container_name=self.silver_container,
                    overwrite=True
                )
            
            result["steps"]["upload"] = {
                "success": bool(upload_result),
                "uploaded_name": upload_result,
                "destination": f"{self.silver_container}/{output_name}"
            }
            
            # Clean up temporary files
            import os
            try:
                os.remove(temp_mosaic_path)
                os.remove(temp_cog_path)
            except:
                pass
            
            # Mark as completed
            result["status"] = "completed"
            result["summary"] = {
                "input_count": len(input_files),
                "output_file": output_name,
                "output_container": self.silver_container,
                "mosaic_bounds": mosaic_result.get("output_bounds"),
                "mosaic_shape": mosaic_result.get("output_shape"),
                "target_crs": target_crs
            }
            
            logger.info(f"Mosaic COG created successfully: {self.silver_container}/{output_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in mosaic processing: {str(e)}")
            result["status"] = "failed"
            result["error"] = str(e)
            return result


class RasterValidationService(BaseProcessingService):
    """Service for validating rasters only (no processing)"""
    
    def __init__(self):
        """Initialize validator"""
        super().__init__()
        self.validator = RasterValidator()
    
    def get_supported_operations(self) -> list[str]:
        """Return list of supported operations"""
        return ["validate_raster"]
        
    def process(
        self,
        job_id: str,
        dataset_id: str,
        resource_id: str,
        version_id: str,
        operation_type: str,
        system: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Validate a raster file
        
        Parameters:
        - dataset_id: Container name
        - resource_id: Raster file name
        - kwargs:
            - input_epsg: Optional EPSG if raster has no CRS
        """
        container = dataset_id if dataset_id else "rmhazuregeobronze"
        input_epsg = kwargs.get("input_epsg")
        
        logger.info(f"Validating raster: {resource_id} in {container}")
        
        result = self.validator.validate_raster(
            container,
            resource_id,
            input_epsg
        )
        
        # Add job context
        result["job_id"] = job_id
        result["container"] = container
        result["file"] = resource_id
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        return result