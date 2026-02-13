# ============================================================================
# H3 EXPORT DATASET JOB
# ============================================================================
# STATUS: Jobs - 3-stage H3 export to denormalized wide-format tables
# PURPOSE: Create GeoParquet-style exports from H3 zonal_stats for mapping
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
H3 Export Dataset Job - 3-Stage Workflow.

Creates denormalized, wide-format exports from H3 zonal_stats for mapping and
download applications. Joins h3.cells with selected variables from h3.zonal_stats
and pivots from long format (normalized) to wide format (one column per stat).

Use Case:
    "I want a specific map" or "I want a copy of a specific extract"
    NOT for analytics (use normalized zonal_stats for that)

3-Stage Workflow:
    Stage 1: Validate (check table exists, verify datasets in registry)
    Stage 2: Build (join + pivot + export to geo schema)
    Stage 3: Register (update export catalog with metadata)

Features:
    - Explicit overwrite control (fail if table exists unless overwrite=true)
    - Auto-routes to theme tables based on dataset registry
    - Supports both polygon and centroid geometry options
    - Spatial scope filtering (iso3, bbox, polygon_wkt)
    - Variable selection from multiple datasets

Output:
    geo.{table_name} with columns:
    - h3_index BIGINT PRIMARY KEY
    - geom GEOMETRY(Polygon/Point, 4326)
    - iso3 VARCHAR(3)
    - {dataset_id}_{stat_type} columns for each selected variable

Usage:
    POST /api/jobs/submit/h3_export_dataset
    {
        "table_name": "rwanda_terrain_res6",
        "resolution": 6,
        "iso3": "RWA",
        "variables": [
            {"dataset_id": "cop_dem_rwanda_res6", "stat_types": ["mean", "min", "max"]}
        ],
        "geometry_type": "polygon",
        "overwrite": false
    }

Exports:
    H3ExportDatasetJob: 3-stage export job
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class H3ExportDatasetJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    H3 Export Dataset Job - 3-stage workflow.

    Stage 1: Validate (check preconditions)
    Stage 2: Build (join + pivot + export)
    Stage 3: Register (update catalog)

    JobBaseMixin provides: validate_job_parameters, generate_job_id, create_job_record, queue_job
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================

    # Job metadata
    job_type: str = "h3_export_dataset"
    description: str = "Export H3 zonal stats to denormalized geo table"

    # 3-stage workflow
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "h3_export_validate",
            "parallelism": "single",
            "description": "Check table existence, verify datasets in registry"
        },
        {
            "number": 2,
            "name": "build",
            "task_type": "h3_export_build",
            "parallelism": "single",
            "description": "Join cells + zonal_stats, pivot to wide, export to geo schema"
        },
        {
            "number": 3,
            "name": "register",
            "task_type": "h3_export_register",
            "parallelism": "single",
            "description": "Update export catalog with metadata"
        }
    ]

    # Declarative parameter validation
    parameters_schema: Dict[str, Any] = {
        'table_name': {
            'type': 'str',
            'required': True,
            'description': 'Output table name in geo schema (e.g., "rwanda_terrain_res6")'
        },
        'resolution': {
            'type': 'int',
            'required': True,
            'min': 0,
            'max': 15,
            'description': 'H3 resolution level for export'
        },
        'variables': {
            'type': 'list',
            'required': True,
            'description': 'List of variable defs: [{"dataset_id": "...", "stat_types": ["mean", "sum"]}]'
        },
        'geometry_type': {
            'type': 'str',
            'default': 'polygon',
            'enum': ['polygon', 'centroid'],
            'description': 'Geometry type for output: polygon (full hex) or centroid (point)'
        },
        'iso3': {
            'type': 'str',
            'default': None,
            'description': 'Optional ISO3 country code for spatial filtering'
        },
        'bbox': {
            'type': 'list',
            'default': None,
            'description': 'Optional bounding box [minx, miny, maxx, maxy]'
        },
        'polygon_wkt': {
            'type': 'str',
            'default': None,
            'description': 'Optional WKT polygon for custom spatial scope'
        },
        'overwrite': {
            'type': 'bool',
            'default': False,
            'description': 'If True, drop existing table. If False (default), fail if table exists.'
        },
        'include_iso3_column': {
            'type': 'bool',
            'default': True,
            'description': 'Include iso3 country code column in output'
        },
        'display_name': {
            'type': 'str',
            'default': None,
            'description': 'Human-readable name for export catalog'
        },
        'description': {
            'type': 'str',
            'default': None,
            'description': 'Description for export catalog'
        }
    }

    # ========================================================================
    # CUSTOM VALIDATION
    # ========================================================================

    @classmethod
    def validate_job_parameters(cls, params: dict) -> dict:
        """
        Validate job parameters with H3 export-specific requirements.

        - Validates table_name format (no special chars except underscore)
        - Validates each variable definition has dataset_id and stat_types
        - Verifies datasets exist in registry (pre-flight validation)
        """
        # First, run base validation (applies schema defaults and type checks)
        validated = super().validate_job_parameters(params)

        # Validate table_name format
        table_name = validated.get('table_name', '')
        if not table_name:
            raise ValueError("'table_name' is required")

        # Only allow alphanumeric and underscore
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', table_name):
            raise ValueError(
                f"Invalid table_name '{table_name}'. "
                f"Must start with letter, contain only letters, numbers, underscores."
            )

        # Validate variables list
        variables = validated.get('variables', [])
        if not variables:
            raise ValueError("'variables' is required and must not be empty")

        if not isinstance(variables, list):
            raise ValueError("'variables' must be a list of variable definitions")

        # Validate each variable definition
        for i, var in enumerate(variables):
            if not isinstance(var, dict):
                raise ValueError(f"Variable at index {i} must be a dict")

            if 'dataset_id' not in var:
                raise ValueError(f"Variable at index {i} missing 'dataset_id'")

            if 'stat_types' not in var:
                raise ValueError(f"Variable at index {i} missing 'stat_types'")

            if not isinstance(var['stat_types'], list) or len(var['stat_types']) == 0:
                raise ValueError(f"Variable at index {i}: 'stat_types' must be non-empty list")

        # PRE-FLIGHT VALIDATION: Verify datasets exist in registry
        from infrastructure.h3_repository import H3Repository
        h3_repo = H3Repository()

        missing_datasets = []
        for var in variables:
            dataset_id = var['dataset_id']
            dataset = h3_repo.get_dataset(dataset_id)
            if not dataset:
                missing_datasets.append(dataset_id)

        if missing_datasets:
            raise ValueError(
                f"Dataset(s) not found in h3.dataset_registry: {missing_datasets}. "
                f"Run h3_raster_aggregation job first to create datasets."
            )

        return validated

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Task Creation
    # ========================================================================

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for each stage of export workflow.

        3-stage workflow:
            Stage 1: Validate (1 task)
            Stage 2: Build (1 task)
            Stage 3: Register (1 task)

        Args:
            stage: Stage number (1-3)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage tasks

        Returns:
            List of task dicts for current stage

        Raises:
            ValueError: Invalid stage or validation failure
        """
        # Extract common parameters
        table_name = job_params.get('table_name')
        resolution = job_params.get('resolution')
        variables = job_params.get('variables', [])
        geometry_type = job_params.get('geometry_type', 'polygon')
        iso3 = job_params.get('iso3')
        bbox = job_params.get('bbox')
        polygon_wkt = job_params.get('polygon_wkt')
        overwrite = job_params.get('overwrite', False)
        include_iso3_column = job_params.get('include_iso3_column', True)
        display_name = job_params.get('display_name') or table_name
        description = job_params.get('description')

        if stage == 1:
            # STAGE 1: Validate preconditions
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-validate",
                    "task_type": "h3_export_validate",
                    "parameters": {
                        "table_name": table_name,
                        "variables": variables,
                        "overwrite": overwrite,
                        "source_job_id": job_id
                    }
                }
            ]

        elif stage == 2:
            # STAGE 2: Build export table
            if not previous_results or len(previous_results) == 0:
                raise ValueError("Stage 2 requires Stage 1 results")

            # Check validation passed
            validate_result = previous_results[0]
            if isinstance(validate_result, dict):
                result_data = validate_result.get('result', {})
                if not result_data.get('validation_passed', False):
                    error = result_data.get('error', 'Unknown validation error')
                    raise ValueError(f"Validation failed: {error}")

            return [
                {
                    "task_id": f"{job_id[:8]}-s2-build",
                    "task_type": "h3_export_build",
                    "parameters": {
                        "table_name": table_name,
                        "resolution": resolution,
                        "variables": variables,
                        "geometry_type": geometry_type,
                        "iso3": iso3,
                        "bbox": bbox,
                        "polygon_wkt": polygon_wkt,
                        "overwrite": overwrite,
                        "include_iso3_column": include_iso3_column,
                        "source_job_id": job_id
                    }
                }
            ]

        elif stage == 3:
            # STAGE 3: Register in catalog
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Get row count from build result
            build_result = previous_results[0]
            if isinstance(build_result, dict):
                result_data = build_result.get('result', {})
            else:
                result_data = {}

            row_count = result_data.get('row_count', 0)
            column_count = result_data.get('column_count', 0)

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-register",
                    "task_type": "h3_export_register",
                    "parameters": {
                        "table_name": table_name,
                        "display_name": display_name,
                        "description": description,
                        "resolution": resolution,
                        "variables": variables,
                        "geometry_type": geometry_type,
                        "iso3": iso3,
                        "row_count": row_count,
                        "column_count": column_count,
                        "source_job_id": job_id
                    }
                }
            ]

        else:
            raise ValueError(f"Invalid stage {stage} for h3_export_dataset job (valid: 1-3)")

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary with export details.

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Comprehensive job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "H3ExportDatasetJob.finalize_job")

        if not context:
            logger.warning("finalize_job called without context")
            return {
                "job_type": "h3_export_dataset",
                "status": "completed"
            }

        # Extract parameters
        params = context.parameters
        table_name = params.get('table_name', 'unknown')
        resolution = params.get('resolution', 0)
        iso3 = params.get('iso3')
        geometry_type = params.get('geometry_type', 'polygon')
        variables = params.get('variables', [])

        # Build scope description
        if iso3:
            scope = f"country: {iso3}"
        elif params.get('bbox'):
            scope = f"bbox: {params.get('bbox')}"
        elif params.get('polygon_wkt'):
            scope = "custom polygon"
        else:
            scope = "global"

        # Extract results from stages
        task_results = context.task_results

        # Stage 2: Build result
        build_result = {}
        if len(task_results) >= 2 and task_results[1].result_data:
            build_result = task_results[1].result_data.get("result", {})

        row_count = build_result.get("row_count", 0)
        column_count = build_result.get("column_count", 0)

        logger.info(f"Job {context.job_id} completed: geo.{table_name} ({row_count:,} rows, {column_count} columns)")

        return {
            "job_type": "h3_export_dataset",
            "job_id": context.job_id,
            "status": "completed",
            "table_name": f"geo.{table_name}",
            "resolution": resolution,
            "scope": scope,
            "geometry_type": geometry_type,
            "variables": [v['dataset_id'] for v in variables],
            "results": {
                "row_count": row_count,
                "column_count": column_count
            },
            "metadata": {
                "workflow": "3-stage (validate -> build -> register)",
                "pattern": "JobBaseMixin"
            }
        }
