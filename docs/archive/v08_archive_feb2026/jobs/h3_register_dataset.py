# ============================================================================
# H3 REGISTER DATASET JOB
# ============================================================================
# STATUS: Jobs - Single-stage dataset registration workflow
# PURPOSE: Register datasets in h3.dataset_registry before aggregation
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
H3 Register Dataset Job - Single-Stage Registration.

Registers datasets in h3.dataset_registry prior to aggregation. This is the
recommended workflow for production use - ensures metadata is captured and
validated before any aggregation jobs run.

Single-Stage Workflow:
    Stage 1: Register or update dataset in h3.dataset_registry (UPSERT)

Features:
    - UPSERT semantics (create or update existing)
    - Theme validation (must match zonal_stats partition keys)
    - Source type validation (planetary_computer, azure, url)
    - Flexible source_config JSONB for source-specific parameters

Required Fields:
    - id: Unique dataset identifier (e.g., "copdem_glo30")
    - display_name: Human-readable name
    - theme: Data category for partitioning (terrain, water, climate, etc.)
    - data_category: Specific category (elevation, flood_hazard, population, etc.)
    - source_type: Data source type (planetary_computer, azure, url)
    - source_config: Source-specific configuration (JSONB)

Usage:
    POST /api/jobs/submit/h3_register_dataset
    {
        "id": "copdem_glo30",
        "display_name": "Copernicus DEM GLO-30",
        "theme": "terrain",
        "data_category": "elevation",
        "source_type": "planetary_computer",
        "source_config": {
            "collection": "cop-dem-glo-30",
            "item_pattern": "Copernicus_DSM_COG_10_N{lat}_00_E{lon}_00_DEM",
            "asset": "data"
        },
        "stat_types": ["mean", "min", "max", "std"],
        "unit": "meters"
    }

Exports:
    H3RegisterDatasetJob: Single-stage dataset registration job
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class H3RegisterDatasetJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    H3 Register Dataset Job - Single-stage registration workflow.

    Stage 1: Register dataset in h3.dataset_registry (UPSERT)

    JobBaseMixin provides: validate_job_parameters, generate_job_id, create_job_record, queue_job
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================

    # Job metadata
    job_type: str = "h3_register_dataset"
    description: str = "Register dataset in h3.dataset_registry"

    # Single-stage workflow
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "register",
            "task_type": "h3_register_dataset",
            "parallelism": "single",
            "description": "Register or update dataset in h3.dataset_registry"
        }
    ]

    # Valid themes (must match h3_schema.py partitions)
    VALID_THEMES = ['terrain', 'water', 'climate', 'demographics', 'infrastructure', 'landcover', 'vegetation', 'agriculture']

    # Declarative parameter validation
    parameters_schema: Dict[str, Any] = {
        # Required fields
        'id': {
            'type': 'str',
            'required': True,
            'description': 'Unique dataset identifier (e.g., "copdem_glo30")'
        },
        'display_name': {
            'type': 'str',
            'required': True,
            'description': 'Human-readable display name'
        },
        'theme': {
            'type': 'str',
            'required': True,
            'enum': ['terrain', 'water', 'climate', 'demographics', 'infrastructure', 'landcover', 'vegetation'],
            'description': 'Theme for partitioning: terrain, water, climate, demographics, infrastructure, landcover, vegetation'
        },
        'data_category': {
            'type': 'str',
            'required': True,
            'description': 'Specific data category (e.g., elevation, flood_hazard, population)'
        },
        'source_type': {
            'type': 'str',
            'required': True,
            'enum': ['planetary_computer', 'azure', 'url'],
            'description': 'Source type: planetary_computer, azure, or url'
        },
        'source_config': {
            'type': 'dict',
            'required': True,
            'description': 'Source-specific configuration (e.g., collection, asset, container, etc.)'
        },
        # Optional fields
        'stat_types': {
            'type': 'list',
            'default': ['mean', 'sum', 'count'],
            'description': 'Default stat types for aggregation jobs'
        },
        'unit': {
            'type': 'str',
            'default': None,
            'description': 'Unit of measurement (e.g., "meters", "people")'
        },
        'description': {
            'type': 'str',
            'default': None,
            'description': 'Detailed description of the dataset'
        },
        'source_name': {
            'type': 'str',
            'default': None,
            'description': 'Data source name for attribution (e.g., "Copernicus")'
        },
        'source_url': {
            'type': 'str',
            'default': None,
            'description': 'URL to original data source'
        },
        'source_license': {
            'type': 'str',
            'default': None,
            'description': 'License identifier (e.g., "CC-BY-4.0")'
        },
        'recommended_h3_res': {
            'type': 'int',
            'default': None,
            'min': 0,
            'max': 15,
            'description': 'Recommended H3 resolution for this dataset'
        },
        'nodata_value': {
            'type': 'float',
            'default': None,
            'description': 'Default nodata value for this dataset'
        }
    }

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
        Generate task parameters for dataset registration.

        Single-stage workflow:
            Stage 1: Register dataset in h3.dataset_registry

        Args:
            stage: Stage number (1 only)
            job_params: Job parameters (id, display_name, theme, etc.)
            job_id: Job ID for task ID generation
            previous_results: Not used (single-stage job)

        Returns:
            List containing single task dict for registration

        Raises:
            ValueError: Invalid stage number
        """
        if stage == 1:
            # Stage 1: Register dataset
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-register",
                    "task_type": "h3_register_dataset",
                    "parameters": {
                        "id": job_params.get('id'),
                        "display_name": job_params.get('display_name'),
                        "theme": job_params.get('theme'),
                        "data_category": job_params.get('data_category'),
                        "source_type": job_params.get('source_type'),
                        "source_config": job_params.get('source_config'),
                        "stat_types": job_params.get('stat_types', ['mean', 'sum', 'count']),
                        "unit": job_params.get('unit'),
                        "description": job_params.get('description'),
                        "source_name": job_params.get('source_name'),
                        "source_url": job_params.get('source_url'),
                        "source_license": job_params.get('source_license'),
                        "recommended_h3_res": job_params.get('recommended_h3_res'),
                        "nodata_value": job_params.get('nodata_value'),
                        "source_job_id": job_id
                    }
                }
            ]
        else:
            raise ValueError(f"Invalid stage {stage} for h3_register_dataset job (valid: 1)")

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create job summary for dataset registration.

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "H3RegisterDatasetJob.finalize_job")

        if not context:
            logger.warning("⚠️ finalize_job called without context")
            return {
                "job_type": "h3_register_dataset",
                "status": "completed"
            }

        # Extract parameters
        params = context.parameters
        dataset_id = params.get('id', 'unknown')
        theme = params.get('theme', 'unknown')
        source_type = params.get('source_type', 'unknown')

        # Extract result from Stage 1
        task_result = {}
        if context.task_results and len(context.task_results) >= 1:
            if context.task_results[0].result_data:
                task_result = context.task_results[0].result_data.get("result", {})

        action = task_result.get("action", "registered")
        created = task_result.get("created", False)

        logger.info(f"✅ Dataset '{dataset_id}' {action} (theme={theme}, source={source_type})")

        return {
            "job_type": "h3_register_dataset",
            "job_id": context.job_id,
            "status": "completed",
            "dataset_id": dataset_id,
            "theme": theme,
            "source_type": source_type,
            "action": action,
            "created": created,
            "message": f"Dataset '{dataset_id}' {action} successfully"
        }
