"""
Simplified COG creation service.

This service creates Cloud Optimized GeoTIFFs from either single TIFFs or VRTs.
Designed to be called once per job after all TIFFs have been prepared.

Architecture:
    - One TIFF/VRT in → One COG out
    - Single operation per job (after all prepare_for_cog calls)
    - Handles both direct TIFF→COG and VRT→COG workflows
    - Outputs to silver/cogs/{job_id}/ folder

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""

from typing import Dict, Any, Optional
import os
from pathlib import Path

from services import BaseProcessingService
from cog_converter import COGConverter
from stac_cog_cataloger import STACCOGCataloger
from config import Config, RasterConfig
from logger_setup import get_logger

logger = get_logger(__name__)


class COGService(BaseProcessingService):
    """
    Creates Cloud Optimized GeoTIFFs from TIFF or VRT inputs.
    
    This service is the final step in the raster processing pipeline:
        - For single files: Direct TIFF → COG conversion
        - For multiple files: VRT (virtual mosaic) → COG conversion
    
    Supports automatic STAC cataloging after successful conversion.
    Skips conversion if input is already a valid COG.
    """
    
    def __init__(self):
        """Initialize service with COG converter and optional STAC cataloger."""
        self.converter = COGConverter()
        # STAC cataloging is optional and can be done separately
        self.cataloger = None  # Can be enabled in future if needed
        self.silver_container = Config.SILVER_CONTAINER_NAME or "rmhazuregeosilver"
        self.cogs_folder = Config.SILVER_COGS_FOLDER or "cogs"
        
    def get_supported_operations(self) -> list[str]:
        """
        Return list of operations this service supports.
        
        Returns:
            List[str]: ['create_cog']
        """
        return ["create_cog"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str) -> Dict[str, Any]:
        """
        Create a Cloud Optimized GeoTIFF from TIFF or VRT input.
        
        Handles both single TIFF files and VRT mosaics. Automatically detects
        if input is already a valid COG and skips conversion if so.
        
        Args:
            job_id: Unique job identifier for output organization
            dataset_id: Source container name (typically 'rmhazuregeosilver')
            resource_id: Path to input TIFF or VRT file (from prepared/ or vrts/)
            version_id: Version identifier for output naming  
            operation_type: Should be 'create_cog'
            
        Returns:
            Dict containing:
                - status: 'completed' or 'failed'
                - output_path: Path to COG in silver/cogs/{job_id}/ folder
                - output_container: 'rmhazuregeosilver'
                - was_already_cog: Boolean (True = skipped, False = converted)
                - input_type: 'TIFF' or 'VRT'
                - input_size_mb: Size of input file in MB
                - output_size_mb: Size of output COG in MB  
                - compression_ratio: Output/input size ratio (< 1.0 = compressed)
                - stac_item_id: STAC catalog ID if cataloged (currently null)
                - message: Status (e.g., 'Successfully converted TIFF to COG')
                - cog_profile: Compression used (default 'lzw')
                
        Examples:
            From prepared TIFF:
                Input: prepared/{job_id}/granule_R0C1_4326.tif (280MB)
                Output: cogs/{job_id}/granule_R0C1_granule_cog_cog.tif (374MB)
                Note: Size increase due to tiling structure, but loads much faster!
                
        Performance:
            - Typical size increase: 1.0-1.3x due to tiling overhead
            - Load time improvement in QGIS: 10-100x faster
            - LZW compression balances size vs. performance
                
        Raises:
            ValueError: If input file not found or invalid
            Exception: For storage access or conversion errors
        """
        logger.info(f"Starting create_cog - Job: {job_id}, Input: {resource_id}")
        
        try:
            # Step 1: Determine input type and validate
            is_vrt = resource_id.lower().endswith('.vrt')
            input_type = "VRT" if is_vrt else "TIFF"
            
            logger.info(f"Processing {input_type} input: {dataset_id}/{resource_id}")
            
            # Check if input exists
            exists, size_bytes = self.converter.check_file_exists(
                dataset_id,
                resource_id
            )
            
            if not exists:
                raise ValueError(f"Input file not found: {dataset_id}/{resource_id}")
            
            input_size_mb = size_bytes / (1024 * 1024) if size_bytes else 0
            logger.info(f"Input file size: {input_size_mb:.2f}MB")
            
            # Step 2: Prepare output path
            filename = os.path.basename(resource_id)
            name_without_ext = Path(filename).stem
            
            # Clean up common suffixes from prepare_for_cog
            for suffix in ['_4326', '_reprojected', '_prepared']:
                name_without_ext = name_without_ext.replace(suffix, '')
            
            # Add version if provided
            if version_id and version_id != "v1":
                output_filename = f"{name_without_ext}_{version_id}_cog.tif"
            else:
                output_filename = f"{name_without_ext}_cog.tif"
            
            # Organize by job_id
            output_path = f"{self.cogs_folder}/{job_id}/{output_filename}"
            
            # Step 3: Check if already a valid COG (skip for VRTs)
            was_already_cog = False
            if not is_vrt:
                logger.info("Checking if input is already a valid COG")
                cog_info = self.converter.get_cog_info(
                    dataset_id,
                    resource_id
                )
                was_already_cog = cog_info.get("is_valid_cog", False)
                
                if was_already_cog:
                    logger.info("Input is already a valid COG, copying to output location")
                    # Just copy the file to the output location
                    success = self.converter.copy_blob(
                        source_container=dataset_id,
                        source_blob=resource_id,
                        dest_container=self.silver_container,
                        dest_blob=output_path
                    )
                    if not success:
                        raise Exception("Failed to copy COG to output location")
                    
                    message = "Input was already a valid COG, copied to output"
            
            # Step 4: Perform COG conversion if needed
            if not was_already_cog:
                logger.info(f"Converting {input_type} to COG with {RasterConfig.COG_PROFILE} profile")
                
                conversion_result = self.converter.convert_to_cog(
                    source_container=dataset_id,
                    source_blob=resource_id,
                    dest_container=self.silver_container,
                    dest_blob=output_path,
                    cog_profile=RasterConfig.COG_PROFILE,
                    is_vrt=is_vrt
                )
                
                if not conversion_result.get("success", False):
                    raise Exception(f"COG conversion failed: {conversion_result.get('error', 'Unknown error')}")
                
                message = f"Successfully converted {input_type} to COG"
            
            # Step 5: Verify output and get size
            exists, output_size_bytes = self.converter.check_file_exists(
                self.silver_container,
                output_path
            )
            
            if not exists:
                raise Exception(f"Output COG not found after conversion: {output_path}")
            
            output_size_mb = output_size_bytes / (1024 * 1024) if output_size_bytes else 0
            
            # Step 6: Optional STAC cataloging
            stac_item_id = None
            if self.cataloger:  # Currently disabled, can be enabled if needed
                logger.info("Cataloging COG to STAC database")
                try:
                    stac_result = self.cataloger.catalog_cog(
                        container_name=self.silver_container,
                        blob_name=output_path,
                        job_id=job_id,
                        was_already_cog=was_already_cog
                    )
                    stac_item_id = stac_result.get("item_id")
                    logger.info(f"COG cataloged to STAC with ID: {stac_item_id}")
                except Exception as e:
                    # Don't fail the job if STAC cataloging fails
                    logger.warning(f"STAC cataloging failed (non-fatal): {str(e)}")
            
            logger.info(f"Successfully created COG: {self.silver_container}/{output_path} ({output_size_mb:.2f}MB)")
            
            # Return comprehensive result
            return {
                "status": "completed",
                "output_path": output_path,
                "output_container": self.silver_container,
                "was_already_cog": was_already_cog,
                "input_type": input_type,
                "input_size_mb": input_size_mb,
                "output_size_mb": output_size_mb,
                "compression_ratio": input_size_mb / output_size_mb if output_size_mb > 0 else 1.0,
                "stac_item_id": stac_item_id,
                "message": message,
                "cog_profile": RasterConfig.COG_PROFILE
            }
            
        except Exception as e:
            logger.error(f"Error in create_cog: {str(e)}")
            return {
                "status": "failed",
                "error": str(e),
                "message": f"Failed to create COG: {str(e)}",
                "input_file": f"{dataset_id}/{resource_id}"
            }