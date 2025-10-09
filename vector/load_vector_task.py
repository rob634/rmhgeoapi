"""
Load Vector File Task - Load a vector file from blob storage to GeoDataFrame.

This task demonstrates how converters are used within the task framework.
It composes: StorageHandler + ConverterRegistry to load and convert files.
"""

from typing import Dict, Any

from converters import ConverterRegistry
from api_clients import StorageHandler
from utils import logger


# This would be registered with TaskRegistry in actual implementation
# @TaskRegistry.instance().register(task_type="load_vector_file")
class LoadVectorFileTask:
    """
    Task that loads a vector file from blob storage and converts to GeoDataFrame.
    
    This task:
    1. Gets file from blob storage (via StorageHandler)
    2. Determines appropriate converter (via ConverterRegistry)
    3. Converts to GeoDataFrame (via converter.convert())
    
    Usage in a job handler:
        def create_stage_1_tasks(self, context):
            return [
                TaskDefinition(
                    task_type="load_vector_file",
                    parameters={
                        "blob_name": "data/parcels.gpkg",
                        "container_name": "uploads",
                        "file_extension": "gpkg",
                        "layer_name": "parcels"  # Format-specific param
                    }
                )
            ]
    """
    
    def execute(self, task_definition: 'TaskDefinition') -> Dict[str, Any]:
        """
        Execute vector file loading task.
        
        Args:
            task_definition: Task definition with parameters:
                - blob_name: Name of file in blob storage
                - container_name: Container containing the file
                - file_extension: File extension (determines converter)
                - **converter_params: Format-specific parameters
                    (e.g., lat_name/lon_name for CSV, layer_name for GPKG)
        
        Returns:
            Dict containing:
                - gdf: GeoDataFrame (or serialized version)
                - row_count: Number of rows
                - geometry_types: List of geometry types in the GDF
                - bounds: Bounding box of geometries
        
        Raises:
            ValueError: If converter not found or conversion fails
            FileNotFoundError: If blob not found
        """
        params = task_definition.parameters
        
        # Extract required parameters
        blob_name = params.get('blob_name')
        container_name = params.get('container_name')
        file_extension = params.get('file_extension')
        
        if not all([blob_name, container_name, file_extension]):
            raise ValueError(
                "Missing required parameters. Need: blob_name, container_name, file_extension. "
                f"Received: {params.keys()}"
            )
        
        logger.info(
            f"Loading vector file: {blob_name} from container: {container_name}, "
            f"format: {file_extension}"
        )
        
        # Extract converter-specific parameters
        converter_params = {
            k: v for k, v in params.items()
            if k not in ['blob_name', 'container_name', 'file_extension']
        }
        
        # Step 1: Get file from blob storage
        logger.debug(f"Retrieving blob: {blob_name}")
        try:
            storage = StorageHandler(workspace_container_name=container_name)
            
            # Check if file exists
            if not storage.blob_exists(blob_name=blob_name, container_name=container_name):
                raise FileNotFoundError(
                    f"Blob {blob_name} not found in container {container_name}"
                )
            
            # Get file data as BytesIO
            file_data = storage.blob_to_bytesio(blob_name)
            logger.info(f"Retrieved blob: {blob_name}")
            
        except Exception as e:
            logger.error(f"Error retrieving blob {blob_name}: {e}")
            raise
        
        # Step 2: Get appropriate converter
        logger.debug(f"Getting converter for extension: {file_extension}")
        try:
            converter = ConverterRegistry.instance().get_converter(file_extension)
            logger.info(f"Using converter: {converter.__class__.__name__}")
            
        except ValueError as e:
            logger.error(f"No converter found for extension: {file_extension}")
            raise
        
        # Step 3: Convert to GeoDataFrame
        logger.debug(f"Converting file with parameters: {converter_params}")
        try:
            gdf = converter.convert(file_data, **converter_params)
            logger.info(
                f"Conversion successful: {len(gdf)} rows, "
                f"geometry types: {gdf.geometry.type.unique().tolist()}"
            )
            
        except Exception as e:
            logger.error(f"Error converting {blob_name}: {e}")
            raise
        
        # Step 4: Prepare result
        result = {
            'gdf': gdf,  # In production, might serialize this
            'row_count': len(gdf),
            'geometry_types': gdf.geometry.type.unique().tolist(),
            'bounds': gdf.total_bounds.tolist(),  # [minx, miny, maxx, maxy]
            'crs': str(gdf.crs) if gdf.crs else None,
            'columns': gdf.columns.tolist(),
            'blob_name': blob_name,
            'container_name': container_name,
        }
        
        logger.info(
            f"Task complete: Loaded {result['row_count']} features from {blob_name}"
        )
        
        return result


# Example usage in a job handler:
"""
from jobs.registry import JobRegistry
from core.models.task import TaskDefinition

@JobRegistry.instance().register(job_type="upload_vector_to_postgis")
class UploadVectorToPostGISJob:
    
    def create_stage_1_tasks(self, context):
        '''Stage 1: Load the vector file'''
        return [
            TaskDefinition(
                task_type="load_vector_file",
                parameters={
                    "blob_name": context.parameters["file_name"],
                    "container_name": context.parameters.get("container_name", "uploads"),
                    "file_extension": context.parameters["file_extension"],
                    
                    # Format-specific parameters (passed to converter)
                    **context.parameters.get("converter_params", {})
                    # e.g., {"layer_name": "parcels"} for GPKG
                    # e.g., {"lat_name": "lat", "lon_name": "lon"} for CSV
                }
            )
        ]
    
    def aggregate_stage_results(self, stage, results):
        '''Extract GeoDataFrame from stage 1 result'''
        if stage == 1:
            return {
                "gdf": results[0]["gdf"],
                "metadata": {
                    "row_count": results[0]["row_count"],
                    "geometry_types": results[0]["geometry_types"],
                    "bounds": results[0]["bounds"],
                }
            }
        return {}
"""
