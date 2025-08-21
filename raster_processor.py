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
        self.validator = RasterValidator()
        self.reprojector = RasterReprojector()
        self.cog_converter = COGConverter()
        self.stac_cataloger = None  # Initialize on demand to avoid DB connection if not needed
        
        # Container configuration
        self.bronze_container = Config.BRONZE_CONTAINER_NAME or "rmhazuregeobronze"
        self.silver_container = Config.SILVER_CONTAINER_NAME or "rmhazuregeosilver"
    
    def get_supported_operations(self) -> list[str]:
        """Return list of supported operations"""
        return ["process_raster", "cog_conversion"]
        
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
        - resource_id: Raster file name
        - version_id: Not used for raster processing
        - Additional kwargs:
            - input_epsg: Optional EPSG code if raster has no CRS
            - skip_validation: Skip validation step
            - skip_cog: Skip COG conversion (just reproject)
            
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
        
        # Use dataset_id as container name (for flexibility)
        source_container = dataset_id if dataset_id else self.bronze_container
        
        # Generate output file name (remove path, add _cog suffix)
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
                        from repositories import StorageRepository
                        storage = StorageRepository()
                        storage.delete_blob(temp_reprojected, self.silver_container)
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