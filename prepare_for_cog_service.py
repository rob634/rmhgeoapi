"""
Service for preparing TIFFs for Cloud Optimized GeoTIFF (COG) conversion.

This service validates and reprojects TIFFs to EPSG:4326 (WGS84), creating COG-ready
intermediate files. Designed to be called multiple times per job (once per TIFF)
before a single VRT→COG conversion or direct COG conversion.

Key Features:
    - Validates raster files for corruption and readability
    - Automatically detects source CRS from file metadata
    - Reprojects to EPSG:4326 if needed (adds _4326 suffix)
    - Preserves original if already in EPSG:4326
    - Handles files up to 5GB (configurable)
    - Smart mode for large files (>500MB)

Architecture:
    - One TIFF in → One validated/reprojected TIFF out
    - Can be called N times for N TIFFs in a job
    - Outputs go to silver/prepared/{job_id}/ folder
    - Maintains original filename with _4326 suffix if reprojected
    - Ready for VRT creation or direct COG conversion

Tested and Working:
    - Files already in EPSG:4326 (e.g., pse10oct2023south_R2C2.tif)
    - Files requiring reprojection from EPSG:3857 (e.g., granule_R0C1.tif)
    - Output files load quickly in QGIS

Author: Azure Geospatial ETL Team
Version: 1.1.0 - Production Ready
"""

from typing import Dict, Any, Optional
import os
from pathlib import Path

from services import BaseProcessingService
from base_raster_processor import BaseRasterProcessor
from raster_validator import RasterValidator
from raster_reprojector import RasterReprojector
from config import Config, RasterConfig
from logger_setup import get_logger

logger = get_logger(__name__)


class PrepareForCOGService(BaseProcessingService):
    """
    Prepares TIFFs for COG conversion through validation and reprojection.
    
    This service ensures TIFFs are:
        - Valid raster files with readable metadata and CRS information
        - Reprojected to EPSG:4326 (WGS84) for global consistency
        - Stored in organized silver container structure for processing
        - Ready for VRT creation (multi-TIFF) or direct COG conversion (single TIFF)
    
    Designed for both single-TIFF and multi-TIFF workflows:
        - Single TIFF: prepare_for_cog → create_cog
        - Multi-TIFF: prepare_for_cog (N times) → build_vrt → create_cog
    
    Performance:
        - Handles reprojection from any CRS to EPSG:4326
        - Typical processing: 270MB EPSG:3857 → 280MB EPSG:4326
        - Uses GDAL/rasterio for high-performance geospatial operations
    """
    
    def __init__(self):
        """Initialize service with validator and reprojector components."""
        self.validator = RasterValidator()
        self.reprojector = RasterReprojector()
        self.silver_container = Config.SILVER_CONTAINER_NAME or "rmhazuregeosilver"
        self.prepared_folder = "prepared"  # Output folder in silver container
        
    def get_supported_operations(self) -> list[str]:
        """
        Return list of operations this service supports.
        
        Returns:
            List[str]: ['prepare_for_cog']
        """
        return ["prepare_for_cog"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str, 
                processing_extent: Optional[Dict[str, float]] = None,
                tile_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Prepare a TIFF for COG conversion with validation and optional reprojection.
        
        Validates the input TIFF and reprojects to EPSG:4326 if needed.
        Files already in EPSG:4326 are copied as-is to preserve quality.
        Output is stored in silver/prepared/{job_id}/ folder for organized processing.
        
        Args:
            job_id: Unique job identifier for grouping related files
            dataset_id: Source container name (typically 'rmhazuregeobronze')
            resource_id: Path to input TIFF file in container
            version_id: Version identifier for output naming
            operation_type: Should be 'prepare_for_cog'
            processing_extent: Optional bounding box for spatial subsetting:
                - minx: West boundary (longitude)
                - miny: South boundary (latitude)
                - maxx: East boundary (longitude)
                - maxy: North boundary (latitude)
                Example: {"minx": -180, "miny": -90, "maxx": 180, "maxy": 90}
            tile_id: Optional tile identifier for output naming (e.g., "X1_Y2")
            
        Returns:
            Dict containing:
                - status: 'completed' or 'failed'
                - output_path: Path to prepared TIFF in silver container
                - output_container: Silver container name ('rmhazuregeosilver')
                - was_reprojected: Boolean (True if reprojected, False if copied)
                - was_clipped: Boolean (True if spatially subset)
                - original_crs: Original EPSG code (e.g., 3857, 4326)
                - target_crs: Always 4326 (WGS84)
                - input_size_mb: Original file size
                - output_size_mb: Prepared file size
                - message: Human-readable status (e.g., 'Reprojected from 3857 to 4326')
                - ready_for_vrt: Always True when successful
                - processing_extent: Bounding box used for clipping (if provided)
                - tile_id: Tile identifier (if provided)
                
        Examples:
            Already in EPSG:4326:
                Input: pse10oct2023south_R2C2.tif
                Output: prepared/{job_id}/pse10oct2023south_R2C2.tif (copied)
                
            Needs reprojection:
                Input: granule_R0C1.tif (EPSG:3857)
                Output: prepared/{job_id}/granule_R0C1_4326.tif (reprojected)
                
            With spatial subsetting (tiling):
                Input: huge_image.tif, processing_extent={minx:-100, miny:30, maxx:-90, maxy:40}
                Output: prepared/{job_id}/huge_image_tile_X1_Y2_4326.tif
                
        Raises:
            ValueError: If input file is not a valid raster or has no CRS
            Exception: For storage access or processing errors
        """
        logger.info(f"Starting prepare_for_cog - Job: {job_id}, File: {resource_id}")
        
        try:
            # Step 1: Validate input TIFF
            logger.info(f"Validating raster: {dataset_id}/{resource_id}")
            # Skip size check when processing with extent (tiling)
            skip_size_check = processing_extent is not None
            if skip_size_check:
                logger.info(f"Processing with extent {processing_extent}, skipping size check")
            validation_result = self.validator.validate_raster(
                container_name=dataset_id,
                blob_name=resource_id,
                skip_size_check=skip_size_check
            )
            
            # Log the full validation result for debugging
            logger.info(f"Validation result: valid={validation_result.get('valid')}, "
                       f"errors={validation_result.get('errors')}, "
                       f"warnings={validation_result.get('warnings')}")
            
            if not validation_result.get("valid", False):
                errors = validation_result.get("errors", [])
                error_msg = "; ".join(errors) if errors else "Unknown validation error"
                logger.error(f"Validation failed: {error_msg}")
                logger.error(f"Full validation result: {validation_result}")
                raise ValueError(f"Invalid raster file: {error_msg}")
            
            # Extract metadata from validation
            source_crs = validation_result["metadata"].get("epsg")
            if not source_crs:
                # Check if there's a CRS warning about non-EPSG CRS
                if validation_result.get("warnings"):
                    raise ValueError(f"Raster has unsupported CRS: {', '.join(validation_result['warnings'])}")
                else:
                    raise ValueError("Raster has no CRS information")
            
            file_size_mb = validation_result["metadata"].get("size_mb", 0)
            
            logger.info(f"Validated: CRS=EPSG:{source_crs}, Size={file_size_mb:.2f}MB")
            
            # Check if processing extent is provided for spatial subsetting
            if processing_extent:
                logger.info(f"Processing extent provided: {processing_extent}")
                if tile_id:
                    logger.info(f"Tile ID: {tile_id}")
            
            # Step 2: Determine if reprojection needed
            needs_reprojection = source_crs != RasterConfig.TARGET_EPSG
            needs_clipping = processing_extent is not None
            
            # Step 3: Prepare output path
            filename = os.path.basename(resource_id)
            name_without_ext = Path(filename).stem
            extension = Path(filename).suffix or ".tif"
            
            # Build output filename with appropriate suffixes
            output_filename = name_without_ext
            
            # Add tile identifier if provided
            if tile_id:
                output_filename = f"{output_filename}_tile_{tile_id}"
            elif processing_extent:
                # If no tile_id but extent provided, add a generic tile suffix
                output_filename = f"{output_filename}_tiled"
            
            # Add _4326 suffix if reprojecting
            if needs_reprojection:
                output_filename = f"{output_filename}_4326"
                
            output_filename = f"{output_filename}{extension}"
            
            # Organize by job_id for multi-file workflows
            output_path = f"{self.prepared_folder}/{job_id}/{output_filename}"
            
            # Step 4: Process file (reproject and/or clip)
            if needs_reprojection or needs_clipping:
                logger.info(f"Processing file: reproject={needs_reprojection}, clip={needs_clipping}")
                
                reproject_result = self.reprojector.reproject_raster(
                    source_container=dataset_id,
                    source_blob=resource_id,
                    dest_container=self.silver_container,
                    dest_blob=output_path,
                    source_epsg=source_crs,
                    target_epsg=RasterConfig.TARGET_EPSG,
                    processing_extent=processing_extent  # Pass the extent for clipping
                )
                
                if not reproject_result.get("success", False):
                    raise Exception(f"Processing failed: {reproject_result.get('error', 'Unknown error')}")
                
                was_reprojected = needs_reprojection
                was_clipped = needs_clipping
                
                operations = []
                if was_clipped:
                    operations.append(f"Clipped to extent")
                if was_reprojected:
                    operations.append(f"Reprojected from {source_crs} to {RasterConfig.TARGET_EPSG}")
                message = " and ".join(operations)
                
            else:
                # Already in EPSG:4326 and no clipping needed, just copy to silver container
                logger.info(f"File already in {RasterConfig.TARGET_EPSG}, no clipping needed, copying to silver")
                
                # Use base class copy_blob method
                success = self.reprojector.copy_blob(
                    source_container=dataset_id,
                    source_blob=resource_id,
                    dest_container=self.silver_container,
                    dest_blob=output_path
                )
                
                if not success:
                    raise Exception("Failed to copy file to silver container")
                
                was_reprojected = False
                was_clipped = False
                message = f"File already in {RasterConfig.TARGET_EPSG}, copied as-is"
            
            # Step 5: Verify output exists
            exists, size_bytes = self.reprojector.check_file_exists(
                self.silver_container,
                output_path
            )
            
            if not exists:
                raise Exception(f"Output file not found after processing: {output_path}")
            
            output_size_mb = size_bytes / (1024 * 1024) if size_bytes else 0
            
            logger.info(f"Successfully prepared TIFF: {self.silver_container}/{output_path} ({output_size_mb:.2f}MB)")
            
            # Return comprehensive result
            result = {
                "status": "completed",
                "output_path": output_path,
                "output_container": self.silver_container,
                "was_reprojected": was_reprojected,
                "was_clipped": was_clipped,
                "original_crs": source_crs,
                "target_crs": RasterConfig.TARGET_EPSG,
                "input_size_mb": file_size_mb,
                "output_size_mb": output_size_mb,
                "message": message,
                "ready_for_vrt": True
            }
            
            # Add processing extent and tile_id if provided
            if processing_extent:
                result["processing_extent"] = processing_extent
            if tile_id:
                result["tile_id"] = tile_id
                
            return result
            
        except ValueError as e:
            logger.error(f"ValueError in prepare_for_cog: {str(e)}")
            logger.error(f"  Job ID: {job_id}")
            logger.error(f"  Input: {dataset_id}/{resource_id}")
            logger.error(f"  Version: {version_id}")
            if processing_extent:
                logger.error(f"  Processing extent: {processing_extent}")
            if tile_id:
                logger.error(f"  Tile ID: {tile_id}")
            return {
                "status": "failed",
                "error": f"Invalid parameter: {str(e)}",
                "message": f"Failed to prepare TIFF: Invalid parameter - {str(e)}",
                "input_file": f"{dataset_id}/{resource_id}",
                "job_id": job_id,
                "tile_id": tile_id
            }
            
        except MemoryError as e:
            logger.error(f"MemoryError in prepare_for_cog: {str(e)}")
            logger.error(f"  File too large for available memory")
            logger.error(f"  Consider using smaller tiles for processing")
            return {
                "status": "failed", 
                "error": f"Memory error: {str(e)}",
                "message": f"Failed to prepare TIFF: Out of memory - consider smaller tiles",
                "input_file": f"{dataset_id}/{resource_id}",
                "job_id": job_id
            }
            
        except IOError as e:
            logger.error(f"IOError in prepare_for_cog: {str(e)}")
            logger.error(f"  Error accessing storage")
            logger.error(f"  Source: {dataset_id}/{resource_id}")
            logger.error(f"  Target: {self.silver_container}/{output_path if 'output_path' in locals() else 'unknown'}")
            return {
                "status": "failed",
                "error": f"IO error: {str(e)}",
                "message": f"Failed to prepare TIFF: Storage access error - {str(e)}",
                "input_file": f"{dataset_id}/{resource_id}",
                "job_id": job_id
            }
            
        except Exception as e:
            logger.error(f"Unexpected error in prepare_for_cog: {str(e)}")
            logger.error(f"  Error type: {type(e).__name__}")
            logger.error(f"  Job ID: {job_id}")
            logger.error(f"  Input: {dataset_id}/{resource_id}")
            logger.error(f"  Version: {version_id}")
            logger.error(f"  Operation: {operation_type}")
            if processing_extent:
                logger.error(f"  Processing extent: {processing_extent}")
            if tile_id:
                logger.error(f"  Tile ID: {tile_id}")
            
            # Log stack trace for debugging
            import traceback
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
            
            return {
                "status": "failed",
                "error": f"{type(e).__name__}: {str(e)}",
                "message": f"Failed to prepare TIFF: {type(e).__name__} - {str(e)}",
                "input_file": f"{dataset_id}/{resource_id}",
                "job_id": job_id,
                "error_type": type(e).__name__,
                "tile_id": tile_id if tile_id else None
            }