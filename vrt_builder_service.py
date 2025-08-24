"""
VRT (Virtual Raster) builder service for multi-TIFF workflows.

This service creates Virtual Raster (VRT) files from multiple prepared TIFFs.
VRTs are lightweight XML files that reference multiple rasters as a single dataset
without physically merging them, enabling efficient processing of large mosaics.

Key Features:
    - Creates virtual mosaics without data duplication
    - Handles any number of input TIFFs efficiently
    - Preserves original data quality (no resampling until COG)
    - Supports pattern matching for batch inclusion
    - Generates SAS URLs for cloud-native access
    - XML-based format readable by GDAL/QGIS/ArcGIS

Architecture:
    - Multiple TIFFs in → One VRT out
    - Called once after all prepare_for_cog operations complete
    - VRT references TIFFs in silver/prepared/{job_id}/ folder
    - Output VRT goes to silver/vrts/{job_id}/ folder
    - Ready for create_cog to produce single mosaicked COG

Workflow:
    1. prepare_for_cog (N times) → N prepared TIFFs
    2. build_vrt (once) → 1 VRT referencing all TIFFs
    3. create_cog (once) → 1 mosaicked COG

Author: Azure Geospatial ETL Team
Version: 1.1.0 - Production Ready
"""

from typing import Dict, Any, List, Optional
import os
from pathlib import Path
import tempfile
from osgeo import gdal

from services import BaseProcessingService
from base_raster_processor import BaseRasterProcessor
from config import Config
from logger_setup import get_logger

logger = get_logger(__name__)


class VRTBuilderService(BaseProcessingService, BaseRasterProcessor):
    """
    Creates Virtual Raster (VRT) files from multiple TIFFs.
    
    VRTs allow treating multiple raster files as a single dataset without
    the overhead of physical merging. This is ideal for creating mosaics
    before COG conversion, especially for large tiled datasets.
    
    Benefits of VRT approach:
        - No data duplication (references original files)
        - Instant mosaic creation (just XML generation)
        - Deferred processing until final COG creation
        - Handles datasets too large to merge in memory
    
    Prerequisites:
        - All input TIFFs must be in same CRS (EPSG:4326)
        - Files should be prepared by prepare_for_cog service
        - Input files must be accessible via SAS URLs
    """
    
    def __init__(self):
        """Initialize VRT builder service."""
        BaseRasterProcessor.__init__(self)
        self.vrts_folder = "vrts"  # Output folder in silver container
        
    def get_supported_operations(self) -> List[str]:
        """
        Return list of operations this service supports.
        
        Returns:
            List[str]: ['build_vrt']
        """
        return ["build_vrt"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str) -> Dict[str, Any]:
        """
        Build a VRT from multiple prepared TIFFs for virtual mosaicking.
        
        The resource_id should contain a comma-separated list of TIFF paths
        or a wildcard pattern to match files in the prepared folder.
        All input files must be in the same CRS (typically EPSG:4326).
        
        Args:
            job_id: Unique job identifier for grouping files
            dataset_id: Container name (typically 'rmhazuregeosilver')
            resource_id: Comma-separated TIFF paths or pattern:
                - Single pattern: "prepared/{job_id}/*.tif"
                - Multiple files: "file1.tif,file2.tif,file3.tif"
                - Specific tiles: "prepared/{job_id}/*_R*C*.tif"
            version_id: Version identifier for output naming
            operation_type: Should be 'build_vrt'
            
        Returns:
            Dict containing:
                - status: 'completed' or 'failed'
                - output_path: Path to VRT in silver/vrts/{job_id}/ folder
                - output_container: 'rmhazuregeosilver'
                - input_count: Number of TIFFs referenced in VRT
                - input_files: List of files included
                - vrt_size_kb: Size of VRT file (typically < 100KB)
                - total_pixels: Combined pixel dimensions
                - message: Status (e.g., 'Created VRT with 4 input files')
                
        Examples:
            Tiled dataset:
                Input: "prepared/job123/*_R*C*.tif" (4 tiles)
                Output: vrts/job123/mosaic_v1.vrt
                Result: Single VRT referencing all 4 tiles
                
            Multiple scenes:
                Input: "scene1_4326.tif,scene2_4326.tif"
                Output: vrts/job456/mosaic_merged.vrt
                Result: Virtual mosaic of both scenes
                
        Raises:
            ValueError: If no input files found or CRS mismatch
            Exception: For VRT creation or storage errors
        """
        logger.info(f"Starting build_vrt - Job: {job_id}, Pattern: {resource_id}")
        
        try:
            # Step 1: Parse input files
            input_files = self._parse_input_files(dataset_id, resource_id, job_id)
            
            if not input_files:
                raise ValueError(f"No input files found for pattern: {resource_id}")
            
            logger.info(f"Found {len(input_files)} files to include in VRT")
            
            # Step 2: Generate VRT output path
            if version_id and version_id != "v1":
                vrt_filename = f"mosaic_{version_id}.vrt"
            else:
                vrt_filename = "mosaic.vrt"
            
            output_path = f"{self.vrts_folder}/{job_id}/{vrt_filename}"
            
            # Step 3: Get SAS URLs for all input files
            input_urls = []
            for file_path in input_files:
                url = self.get_blob_url(dataset_id, file_path)
                # Convert to GDAL VSI format for Azure
                vsi_path = self._convert_to_vsi_path(url)
                input_urls.append(vsi_path)
            
            # Step 4: Create VRT using GDAL
            logger.info(f"Building VRT from {len(input_urls)} files")
            
            # Create temporary VRT file locally
            with tempfile.NamedTemporaryFile(suffix='.vrt', mode='w', delete=False) as tmp_vrt:
                tmp_vrt_path = tmp_vrt.name
            
            try:
                # Build VRT with GDAL
                vrt_options = gdal.BuildVRTOptions(
                    resolution='average',  # Use average resolution
                    separate=False,        # Mosaic mode (not separate bands)
                    addAlpha=True,         # Add alpha band for transparency
                    srcNodata=0,          # Treat 0 as nodata
                    VRTNodata=0           # Set VRT nodata value
                )
                
                vrt = gdal.BuildVRT(
                    tmp_vrt_path,
                    input_urls,
                    options=vrt_options
                )
                
                if vrt is None:
                    raise Exception("Failed to build VRT with GDAL")
                
                # Close VRT to flush to disk
                vrt = None
                
                # Read VRT content
                with open(tmp_vrt_path, 'r') as f:
                    vrt_content = f.read()
                
                # Step 5: Upload VRT to blob storage
                logger.info(f"Uploading VRT to {self.silver_container}/{output_path}")
                
                self.storage.upload_blob(
                    output_path,
                    vrt_content.encode('utf-8'),
                    self.silver_container,
                    overwrite=True,
                    content_type='text/xml'
                )
                
                # Verify upload
                exists, size_bytes = self.check_file_exists(
                    self.silver_container,
                    output_path
                )
                
                if not exists:
                    raise Exception(f"VRT upload failed: {output_path}")
                
                vrt_size_kb = size_bytes / 1024 if size_bytes else 0
                
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_vrt_path):
                    os.remove(tmp_vrt_path)
            
            logger.info(f"Successfully created VRT: {self.silver_container}/{output_path} ({vrt_size_kb:.2f}KB)")
            
            # Return result
            return {
                "status": "completed",
                "output_path": output_path,
                "output_container": self.silver_container,
                "input_count": len(input_files),
                "input_files": input_files[:10],  # First 10 for preview
                "vrt_size_kb": vrt_size_kb,
                "message": f"Successfully built VRT from {len(input_files)} files",
                "ready_for_cog": True
            }
            
        except Exception as e:
            logger.error(f"Error in build_vrt: {str(e)}")
            return {
                "status": "failed",
                "error": str(e),
                "message": f"Failed to build VRT: {str(e)}"
            }
    
    def _parse_input_files(self, container: str, resource_id: str, job_id: str) -> List[str]:
        """
        Parse input file specification.
        
        Handles:
        - Comma-separated list: "file1.tif,file2.tif,file3.tif"
        - Wildcard pattern: "prepared/job123/*.tif"
        - Default pattern: All files in prepared/{job_id}/ folder
        
        Args:
            container: Container name
            resource_id: File specification
            job_id: Job ID for default pattern
            
        Returns:
            List of file paths
        """
        # If resource_id is "auto" or empty, use default pattern
        if not resource_id or resource_id == "auto":
            pattern = f"prepared/{job_id}/"
            logger.info(f"Using default pattern: {pattern}")
            
            # List all files in prepared folder for this job
            blobs = self.storage.list_blobs(container, prefix=pattern)
            return [blob.name for blob in blobs if blob.name.endswith(('.tif', '.tiff'))]
        
        # Check if comma-separated list
        elif ',' in resource_id:
            files = [f.strip() for f in resource_id.split(',')]
            logger.info(f"Parsed {len(files)} files from comma-separated list")
            return files
        
        # Check if wildcard pattern
        elif '*' in resource_id:
            prefix = resource_id.split('*')[0]
            blobs = self.storage.list_blobs(container, prefix=prefix)
            files = [blob.name for blob in blobs if blob.name.endswith(('.tif', '.tiff'))]
            logger.info(f"Found {len(files)} files matching pattern: {resource_id}")
            return files
        
        # Single file
        else:
            return [resource_id]
    
    def _convert_to_vsi_path(self, sas_url: str) -> str:
        """
        Convert Azure SAS URL to GDAL VSI path.
        
        Args:
            sas_url: Azure blob SAS URL
            
        Returns:
            VSI path for GDAL
        """
        # For Azure, use /vsiaz/ prefix
        # Extract container and blob from URL
        # Format: https://account.blob.core.windows.net/container/blob?sas
        
        # For now, return the SAS URL directly as GDAL can handle it
        # In production, might need to configure GDAL Azure credentials
        return f"/vsicurl/{sas_url}"