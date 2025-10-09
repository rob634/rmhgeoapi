# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - PROCESS RASTER
# ============================================================================
# PURPOSE: 2-stage workflow for processing rasters to COGs (<= 1GB)
# EXPORTS: ProcessRasterWorkflow class
# INTERFACES: Job workflow pattern with stages
# PYDANTIC_MODELS: None (class attributes)
# DEPENDENCIES: core.models.enums.TaskStatus
# SOURCE: Bronze container rasters
# SCOPE: Small file raster processing pipeline (<= 1GB)
# VALIDATION: Stage 1 validates, Stage 2 creates COG
# PATTERNS: Multi-stage workflow with result passing
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS
# ============================================================================

"""
Process Raster Workflow - Small File Pipeline (<= 1GB)

Two-stage workflow for converting rasters to Cloud Optimized GeoTIFFs:

Stage 1: Validate Raster
- Check CRS (file metadata, user override, or fail)
- Analyze bit-depth efficiency (flag 64-bit as CRITICAL)
- Auto-detect raster type (RGB, RGBA, DEM, categorical, etc.)
- Validate type match if user specified
- Recommend optimal COG settings

Stage 2: Reproject + Create COG
- Single-pass reprojection + COG creation using rio-cogeo
- Auto-select compression and resampling based on raster type
- Upload to silver container
- No intermediate storage needed

Key Innovation:
- rio-cogeo combines reprojection + COG creation in one pass
- Eliminates intermediate files
- Type-specific optimization (JPEG for RGB, WebP for RGBA, LERC for DEM)
"""

from typing import List, Dict, Any


class ProcessRasterWorkflow:
    """
    Small file raster processing workflow (<= 1GB).

    Stages:
    1. Validate: CRS, bit-depth, type detection
    2. Create COG: Reproject + COG in single operation
    """

    job_type: str = "process_raster"
    description: str = "Process raster to COG (files <= 1GB)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "description": "Validate raster, check CRS, analyze bit-depth, detect type",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "create_cog",
            "task_type": "create_cog",
            "description": "Reproject to EPSG:4326 and create COG (single operation)",
            "parallelism": "single"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "container": {"type": "str", "required": True, "default": None},  # Uses config.bronze_container_name if None
        "input_crs": {"type": "str", "required": False, "default": None},
        "raster_type": {
            "type": "str",
            "required": False,
            "default": "auto",
            "allowed": ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
        },
        "compression": {"type": "str", "required": False, "default": None},  # Auto-selected if None
        "jpeg_quality": {"type": "int", "required": False, "default": 85},
        "overview_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected
        "reproject_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected
        "strict_mode": {"type": "bool", "required": False, "default": False},
        "_skip_validation": {"type": "bool", "required": False, "default": False},  # TESTING ONLY
    }

    @staticmethod
    def create_stage_1_tasks(context) -> List[Dict[str, Any]]:
        """
        Create Stage 1 task: Validate raster.

        Returns single task to validate the raster file.
        """
        from config import get_config
        from infrastructure.blob import BlobRepository

        params = context.parameters
        config = get_config()

        # Use config default if container not specified
        container = params.get('container') or config.bronze_container_name

        # Build blob URL with SAS token
        blob_infra = BlobRepository()

        blob_url = blob_infra.get_blob_url_with_sas(
            container_name=container,
            blob_name=params.get('blob_name')
        )

        return [{
            "task_type": "validate_raster",
            "parameters": {
                "blob_url": blob_url,
                "blob_name": params.get('blob_name'),
                "container": container,
                "input_crs": params.get('input_crs'),
                "raster_type": params.get('raster_type', 'auto'),
                "strict_mode": params.get('strict_mode', False),
                "_skip_validation": params.get('_skip_validation', False)
            }
        }]

    @staticmethod
    def create_stage_2_tasks(context) -> List[Dict[str, Any]]:
        """
        Create Stage 2 task: Create COG with optional reprojection.

        Uses validation results from Stage 1 to determine:
        - Source CRS
        - Raster type (for optimal settings)
        - Whether reprojection is needed
        """
        from config import get_config
        from infrastructure.blob import BlobRepository

        params = context.parameters
        config = get_config()
        stage_1_results = context.stage_results.get(1, [])

        if not stage_1_results:
            raise ValueError("Stage 1 validation results not found")

        validation_result = stage_1_results[0].result_data.get('result', {})

        # Get source CRS from validation
        source_crs = validation_result.get('source_crs')
        if not source_crs:
            raise ValueError("No source_crs found in validation results")

        # Use config default if container not specified
        container = params.get('container') or config.bronze_container_name

        # Build blob URL with SAS token
        blob_infra = BlobRepository()

        blob_url = blob_infra.get_blob_url_with_sas(
            container_name=container,
            blob_name=params.get('blob_name')
        )

        # Output blob name in silver container
        # Pattern: same path as bronze but in silver, with _cog suffix
        blob_name = params.get('blob_name')
        if blob_name.lower().endswith('.tif'):
            output_blob_name = blob_name[:-4] + '_cog.tif'
        else:
            output_blob_name = blob_name + '_cog.tif'

        return [{
            "task_type": "create_cog",
            "parameters": {
                "blob_url": blob_url,
                "blob_name": params.get('blob_name'),
                "container": container,
                "source_crs": source_crs,
                "target_crs": "EPSG:4326",
                "raster_type": validation_result.get('raster_type', {}),
                "output_blob_name": output_blob_name,
                "compression": params.get('compression'),  # User override or None
                "jpeg_quality": params.get('jpeg_quality', 85),
                "overview_resampling": params.get('overview_resampling'),  # User override or None
                "reproject_resampling": params.get('reproject_resampling'),  # User override or None
            }
        }]

    @staticmethod
    def aggregate_job_results(context) -> Dict[str, Any]:
        """
        Aggregate results from all completed tasks into job summary.
        """
        from core.models.enums import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Separate by stage
        stage_1_tasks = [t for t in task_results if t.task_type == "validate_raster"]
        stage_2_tasks = [t for t in task_results if t.task_type == "create_cog"]

        # Extract validation results
        validation_summary = {}
        if stage_1_tasks and stage_1_tasks[0].result_data:
            validation_result = stage_1_tasks[0].result_data.get("result", {})
            validation_summary = {
                "source_crs": validation_result.get("source_crs"),
                "raster_type": validation_result.get("raster_type", {}).get("detected_type"),
                "confidence": validation_result.get("raster_type", {}).get("confidence"),
                "bit_depth_efficient": validation_result.get("bit_depth_check", {}).get("efficient"),
                "warnings": validation_result.get("warnings", [])
            }

        # Extract COG results
        cog_summary = {}
        if stage_2_tasks and stage_2_tasks[0].result_data:
            cog_result = stage_2_tasks[0].result_data.get("result", {})
            cog_summary = {
                "cog_blob": cog_result.get("cog_blob"),
                "cog_container": cog_result.get("cog_container"),
                "reprojection_performed": cog_result.get("reprojection_performed"),
                "size_mb": cog_result.get("size_mb"),
                "compression": cog_result.get("compression"),
                "processing_time_seconds": cog_result.get("processing_time_seconds")
            }

        return {
            "job_type": "process_raster",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container"),
            "validation": validation_summary,
            "cog": cog_summary,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
