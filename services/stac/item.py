"""STAC Item service for cataloging geospatial files."""

from typing import Dict, List, Any
import os
import hashlib
from datetime import datetime, timezone
from services.base import BaseProcessingService
from core.constants import ProcessingMode, FileSizeLimits, GeospatialExtensions
from core.exceptions import STACProcessingError
from utils.logger import logger


class STACItemService(BaseProcessingService):
    """Service for STAC item cataloging with multiple processing modes."""
    
    def __init__(self):
        super().__init__()
        self.storage_repo = None
        self.stac_repo = None
        self._init_repositories()
    
    def _init_repositories(self):
        """Initialize repository dependencies."""
        try:
            from repositories import StorageRepository
            from repositories.stac import STACRepository
            self.storage_repo = StorageRepository()
            self.stac_repo = STACRepository()
        except Exception as e:
            logger.error(f"Failed to initialize repositories: {e}")
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported STAC operations."""
        return [
            "stac_item_quick",
            "stac_item_full",
            "stac_item_smart",
            "stac_item_update",
            "stac_item_validate"
        ]
    
    def process(
        self,
        job_id: str,
        dataset_id: str,
        resource_id: str,
        version_id: str,
        operation_type: str
    ) -> Dict[str, Any]:
        """
        Process STAC item update.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Container name
            resource_id: Blob path/name
            version_id: Processing mode or 'auto'
            operation_type: Type of STAC operation
            
        Returns:
            Dictionary with processing results
        """
        logger.info(f"Processing STAC item: {resource_id} (job: {job_id})")
        
        try:
            # Validate file is geospatial
            if not self._is_geospatial_file(resource_id):
                return self._skip_non_geospatial(resource_id)
            
            # Get blob metadata
            blob_properties = self.storage_repo.get_blob_properties(dataset_id, resource_id)
            if not blob_properties:
                raise STACProcessingError(f"Blob not found: {resource_id}")
            
            # Determine processing mode
            mode = self._determine_mode(operation_type, version_id, blob_properties.size)
            logger.info(f"Using {mode.value} mode for {resource_id}")
            
            # Extract metadata based on mode - pass all parameters for traceability
            metadata = self._extract_metadata(
                mode, dataset_id, resource_id, blob_properties,
                job_id=job_id, version_id=version_id
            )
            
            # Generate STAC item ID
            item_id = self._generate_item_id(dataset_id, resource_id)
            
            # Update STAC catalog
            self.stac_repo.upsert_item(
                collection_id=f"container_{dataset_id}",
                item_id=item_id,
                blob_name=resource_id,
                metadata=metadata
            )
            
            return {
                "status": "success",
                "mode": mode.value,
                "item_id": item_id,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"STAC processing failed: {e}")
            raise STACProcessingError(f"Failed to process {resource_id}: {e}")
    
    def _is_geospatial_file(self, filename: str) -> bool:
        """Check if file has geospatial extension."""
        ext = os.path.splitext(filename)[1].lower()
        return ext in GeospatialExtensions.ALL
    
    def _skip_non_geospatial(self, filename: str) -> Dict[str, Any]:
        """Return skip response for non-geospatial files."""
        ext = os.path.splitext(filename)[1].lower()
        return {
            "status": "skipped",
            "message": f"Not a geospatial file: {filename}",
            "extension": ext
        }
    
    def _determine_mode(
        self,
        operation_type: str,
        version_id: str,
        size_bytes: int
    ) -> ProcessingMode:
        """Determine processing mode based on inputs."""
        # Check explicit operation type
        if "quick" in operation_type:
            return ProcessingMode.QUICK
        elif "smart" in operation_type:
            return ProcessingMode.SMART
        elif "full" in operation_type:
            return ProcessingMode.FULL
        
        # Check version_id parameter
        if version_id in [m.value for m in ProcessingMode]:
            return ProcessingMode(version_id)
        
        # Auto mode - determine based on file size
        size_mb = FileSizeLimits.bytes_to_mb(size_bytes)
        
        if size_mb > FileSizeLimits.QUICK_MODE_THRESHOLD:
            return ProcessingMode.QUICK
        elif size_mb > FileSizeLimits.SMART_MODE_THRESHOLD:
            return ProcessingMode.SMART
        else:
            return ProcessingMode.FULL
    
    def _generate_item_id(self, container_name: str, blob_name: str) -> str:
        """Generate STAC item ID from container and blob name."""
        # Handle long paths by using hash
        full_path = f"{container_name}/{blob_name}"
        if len(full_path) > 200:
            # Use MD5 hash for long paths
            return hashlib.md5(full_path.encode()).hexdigest()
        else:
            # Use safe version of path as ID
            return full_path.replace('/', '_').replace('.', '_').lower()
    
    def _extract_metadata(
        self,
        mode: ProcessingMode,
        container_name: str,
        blob_name: str,
        blob_properties: Any,
        job_id: str = None,
        version_id: str = None
    ) -> Dict[str, Any]:
        """Extract metadata based on processing mode."""
        base_metadata = {
            "datetime": blob_properties.last_modified.isoformat() if blob_properties.last_modified else datetime.now(timezone.utc).isoformat(),
            "file_size": blob_properties.size,
            "file_path": blob_name,
            "sync_mode": mode.value,
            "container": container_name,
            # Add explicit job parameters for traceability
            "dataset_id": container_name,  # Explicit dataset_id
            "resource_id": blob_name,      # Explicit resource_id
            "version_id": version_id,       # Original version parameter
            "job_id": job_id,              # Hashed job ID for traceability
            "stac_item_id": self._generate_item_id(container_name, blob_name)  # The STAC item ID
        }
        
        if mode == ProcessingMode.QUICK:
            # Quick mode - metadata only
            return {
                **base_metadata,
                "bbox": [-0.001, -0.001, 0.001, 0.001],  # Placeholder
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-0.001, -0.001],
                        [0.001, -0.001],
                        [0.001, 0.001],
                        [-0.001, 0.001],
                        [-0.001, -0.001]
                    ]]
                }
            }
        
        elif mode == ProcessingMode.SMART:
            # Smart mode - header-only access for rasters
            return self._extract_smart_metadata(container_name, blob_name, base_metadata)
        
        elif mode == ProcessingMode.FULL:
            # Full mode - download and process
            return self._extract_full_metadata(container_name, blob_name, base_metadata)
        
        return base_metadata
    
    def _extract_smart_metadata(
        self,
        container_name: str,
        blob_name: str,
        base_metadata: Dict
    ) -> Dict[str, Any]:
        """Extract metadata using smart mode (header-only for rasters)."""
        try:
            # Get SAS URI for direct access
            sas_uri = self.storage_repo.get_blob_sas_uri(container_name, blob_name)
            
            import rasterio
            from rasterio.warp import transform_bounds
            from rasterio.crs import CRS
            
            with rasterio.open(sas_uri) as src:
                # Get bounds in WGS84
                bounds = src.bounds
                if src.crs:
                    bounds_wgs84 = transform_bounds(
                        src.crs,
                        CRS.from_epsg(4326),
                        *bounds
                    )
                else:
                    bounds_wgs84 = bounds
                
                return {
                    **base_metadata,
                    "bbox": list(bounds_wgs84),
                    "geometry": self._bounds_to_polygon(bounds_wgs84),
                    "proj:epsg": src.crs.to_epsg() if src.crs else None,
                    "width": src.width,
                    "height": src.height,
                    "raster:bands": src.count,
                    "gsd": src.res[0] if src.res else None
                }
        except Exception as e:
            logger.warning(f"Smart extraction failed, falling back to quick: {e}")
            return {
                **base_metadata,
                "bbox": [-0.001, -0.001, 0.001, 0.001],
                "geometry": self._placeholder_geometry()
            }
    
    def _extract_full_metadata(
        self,
        container_name: str,
        blob_name: str,
        base_metadata: Dict
    ) -> Dict[str, Any]:
        """Extract metadata using full mode (download file)."""
        # For now, use smart mode logic
        # In production, this would download and fully process the file
        return self._extract_smart_metadata(container_name, blob_name, base_metadata)
    
    def _bounds_to_polygon(self, bounds: tuple) -> Dict:
        """Convert bounds to polygon geometry."""
        min_x, min_y, max_x, max_y = bounds
        return {
            "type": "Polygon",
            "coordinates": [[
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y]
            ]]
        }
    
    def _placeholder_geometry(self) -> Dict:
        """Create placeholder polygon geometry."""
        return {
            "type": "Polygon",
            "coordinates": [[
                [-0.001, -0.001],
                [0.001, -0.001],
                [0.001, 0.001],
                [-0.001, 0.001],
                [-0.001, -0.001]
            ]]
        }