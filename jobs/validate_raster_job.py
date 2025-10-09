# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - VALIDATE RASTER
# ============================================================================
# PURPOSE: Single-stage workflow for validating rasters without processing
# EXPORTS: ValidateRasterJob class
# INTERFACES: Job workflow pattern with single stage
# PYDANTIC_MODELS: None (class attributes)
# DEPENDENCIES: None at module level
# SOURCE: Bronze container rasters
# SCOPE: Standalone validation for any raster file
# VALIDATION: CRS, bit-depth, type detection, bounds checking
# PATTERNS: Single-stage workflow, validation only
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS
# ============================================================================

"""
Validate Raster Job - Standalone Validation

Single-stage workflow for validating raster files without COG processing.

Use Cases:
- Quick validation check before committing to COG pipeline
- Testing raster files for CRS, bit-depth, type issues
- Batch validation of multiple files
- Pre-flight checks for large datasets

Stage 1 (Only): Validate Raster
- Check CRS (file metadata, user override, or fail)
- Analyze bit-depth efficiency (flag 64-bit as CRITICAL)
- Auto-detect raster type (RGB, RGBA, DEM, categorical, etc.)
- Validate type match if user specified
- Return validation results without processing

Author: Robert and Geospatial Claude Legion
Date: 9 OCT 2025
"""

from typing import List, Dict, Any


class ValidateRasterJob:
    """
    Standalone raster validation job.

    Single stage that validates a raster file and returns results.
    Does not create COG or modify the file.
    """

    job_type: str = "validate_raster_job"
    description: str = "Validate raster file (CRS, bit-depth, type detection)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "description": "Validate raster: CRS, bit-depth, type detection, bounds",
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
        "strict_mode": {"type": "bool", "required": False, "default": False},
        "_skip_validation": {"type": "bool", "required": False, "default": False},  # TESTING ONLY
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            blob_name: str - Blob path in container

        Optional:
            container: str - Container name (default: config.bronze_container_name)
            input_crs: str - User-provided CRS override
            raster_type: str - Expected type for validation
            strict_mode: bool - Fail on warnings
            _skip_validation: bool - TESTING ONLY

        Returns:
            Validated parameters dict

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}

        # Validate blob_name (required)
        if "blob_name" not in params:
            raise ValueError("blob_name is required")

        blob_name = params["blob_name"]
        if not isinstance(blob_name, str) or not blob_name.strip():
            raise ValueError("blob_name must be a non-empty string")

        validated["blob_name"] = blob_name.strip()

        # Validate container (optional)
        container = params.get("container")
        if container is not None:
            if not isinstance(container, str) or not container.strip():
                raise ValueError("container must be a non-empty string")
            validated["container"] = container.strip()
        else:
            validated["container"] = None

        # Validate input_crs (optional)
        input_crs = params.get("input_crs")
        if input_crs is not None:
            if not isinstance(input_crs, str) or not input_crs.strip():
                raise ValueError("input_crs must be a non-empty string")
            validated["input_crs"] = input_crs.strip()

        # Validate raster_type (optional)
        raster_type = params.get("raster_type", "auto")
        allowed_types = ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
        if raster_type not in allowed_types:
            raise ValueError(f"raster_type must be one of {allowed_types}, got {raster_type}")
        validated["raster_type"] = raster_type

        # Validate strict_mode (optional)
        strict_mode = params.get("strict_mode", False)
        if not isinstance(strict_mode, bool):
            raise ValueError("strict_mode must be boolean")
        validated["strict_mode"] = strict_mode

        # Validate _skip_validation (optional, testing only)
        skip_validation = params.get("_skip_validation", False)
        if not isinstance(skip_validation, bool):
            raise ValueError("_skip_validation must be boolean")
        validated["_skip_validation"] = skip_validation

        return validated

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
        """
        Generate task parameters for stage.

        Stage 1 (Only): Single task to validate raster

        Args:
            stage: Stage number (only 1 for this job)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Not used (single stage)

        Returns:
            List with single task parameter dict

        Raises:
            ValueError: If stage != 1
        """
        from core.task_id import generate_deterministic_task_id
        from config import get_config
        from infrastructure.blob import BlobRepository

        if stage != 1:
            raise ValueError(f"ValidateRasterJob only has 1 stage, got stage {stage}")

        config = get_config()

        # Use config default if container not specified
        container = job_params.get('container') or config.bronze_container_name

        # Build blob URL with SAS token
        blob_repo = BlobRepository.instance()
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=container,
            blob_name=job_params['blob_name'],
            hours=1
        )

        task_id = generate_deterministic_task_id(job_id, 1, "validate")

        return [
            {
                "task_id": task_id,
                "task_type": "validate_raster",
                "parameters": {
                    "blob_url": blob_url,
                    "blob_name": job_params['blob_name'],
                    "container_name": container,
                    "input_crs": job_params.get('input_crs'),
                    "raster_type": job_params.get('raster_type', 'auto'),
                    "strict_mode": job_params.get('strict_mode', False),
                    "_skip_validation": job_params.get('_skip_validation', False)
                }
            }
        ]
