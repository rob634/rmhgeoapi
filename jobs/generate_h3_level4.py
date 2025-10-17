# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW
# ============================================================================
# PURPOSE: Generate global Level 4 H3 land grid and save to gold container
# EXPORTS: GenerateH3Level4Job (job class)
# INTERFACES: Epoch 4 job pattern (stages + create_tasks_for_stage)
# PYDANTIC_MODELS: None (uses dict parameters)
# DEPENDENCIES: services.handler_h3_level4 (h3_level4_generate)
# SOURCE: HTTP POST requests to /api/jobs/submit/generate_h3_level4
# SCOPE: Global H3 Level 4 grid generation (~875 land cells)
# VALIDATION: Parameter validation in handler
# PATTERNS: Single-stage job workflow
# ENTRY_POINTS: Job registered in jobs/__init__.py as "generate_h3_level4"
# INDEX: Stages:30, create_tasks:50
# ============================================================================

"""
Generate H3 Level 4 Land Grid Job.

Single-stage workflow to generate global Level 4 H3 grid filtered by land.

Stage 1: Generate + Filter + Save
    - Generate global Level 4 grid (~3,500 cells)
    - Filter by Overture Divisions land boundaries
    - Save to gold container as GeoParquet (~875 cells)

Output:
    gold/h3/grids/land_h3_level4.parquet

Example:
    POST /api/jobs/submit/generate_h3_level4
    {
        "overture_release": "2024-11-13.0",
        "output_folder": "h3/grids",
        "output_filename": "land_h3_level4.parquet"
    }

Updated: 15 OCT 2025 - Phase 2: Migrated to JobBase ABC
"""

from typing import Dict, Any, List

from jobs.base import JobBase


class GenerateH3Level4Job(JobBase):
    """Generate Level 4 H3 land grid job."""

    # Job configuration
    job_type = "generate_h3_level4"

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "generate_level4_grid",
            "task_type": "h3_level4_generate",
            "parallelism": "single",  # One task generates entire grid
            "description": "Generate global L4 grid, filter by land, save to gold"
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "skip_land_filter": {
            "type": "bool",
            "default": False,
            "description": "If True, skip land filtering and output full global grid"
        },
        "land_geojson_path": {
            "type": "str",
            "default": None,
            "description": "Azure blob path to land GeoJSON (e.g., 'reference/land_boundaries.geojson')"
        },
        "overture_release": {
            "type": "str",
            "default": None,
            "description": "Overture Maps release version (alternative to GeoJSON)"
        },
        "output_folder": {
            "type": "str",
            "default": "h3/grids",
            "description": "Output folder in gold container"
        },
        "output_filename": {
            "type": "str",
            "default": "land_h3_level4.parquet",
            "description": "Output GeoParquet filename"
        }
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for each stage.

        Stage 1: Single task to generate, filter, and save Level 4 grid

        Args:
            stage: Stage number (1)
            job_params: Job parameters from submission
            job_id: Unique job identifier
            previous_results: Results from previous stage (None for stage 1)

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Single task for entire workflow
            return [{
                "task_id": f"{job_id[:8]}-h3level4-generate",
                "task_type": "h3_level4_generate",
                "parameters": {
                    "land_geojson_path": job_params.get("land_geojson_path"),
                    "overture_release": job_params.get("overture_release"),
                    "output_folder": job_params.get("output_folder", "h3/grids"),
                    "output_filename": job_params.get("output_filename", "land_h3_level4.parquet")
                }
            }]

        return []

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate and apply defaults to job parameters.

        Args:
            params: Raw job parameters

        Returns:
            Validated parameters with defaults applied
        """
        validated = {}

        # Land geometry source (priority: GeoJSON > Overture > Default)
        validated["land_geojson_path"] = params.get("land_geojson_path")
        validated["overture_release"] = params.get("overture_release")

        # Validate at least one land source is provided
        if not validated["land_geojson_path"] and not validated["overture_release"]:
            # Use default GeoJSON path
            validated["land_geojson_path"] = "reference/land_boundaries.geojson"

        # Output folder
        validated["output_folder"] = params.get("output_folder", "h3/grids")

        # Output filename
        validated["output_filename"] = params.get("output_filename", "land_h3_level4.parquet")

        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Args:
            params: Job parameters

        Returns:
            SHA256 hash as job ID
        """
        import hashlib
        import json

        # Create deterministic string from params
        param_str = json.dumps(params, sort_keys=True)
        job_id = hashlib.sha256(param_str.encode()).hexdigest()

        return job_id

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create job record in database.

        Args:
            job_id: Generated job ID
            params: Validated parameters

        Returns:
            Job record dict
        """
        from infrastructure.factory import RepositoryFactory
        from core.models import JobRecord, JobStatus

        # Create job record object
        job_record = JobRecord(
            job_id=job_id,
            job_type="generate_h3_level4",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=1,
            stage_results={},
            metadata={
                "description": "Generate Level 4 H3 land grid using Overture Maps",
                "created_by": "GenerateH3Level4Job"
            }
        )

        # Persist to database
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job_repo.create_job(job_record)

        # Return as dict
        return job_record.model_dump()

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """
        Queue job for processing using Service Bus.

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        import uuid

        # Get config
        config = get_config()
        queue_name = config.service_bus_jobs_queue

        # Create Service Bus repository
        service_bus_repo = ServiceBusRepository()

        # Create job queue message
        correlation_id = str(uuid.uuid4())
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type="generate_h3_level4",
            stage=1,
            parameters=params,
            correlation_id=correlation_id
        )

        # Send to Service Bus queue
        message_id = service_bus_repo.send_message(queue_name, job_message)

        return {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }
