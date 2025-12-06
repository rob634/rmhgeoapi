"""
Generate H3 Level 4 Land Grid Job.

Two-stage workflow to generate global Level 4 H3 grid filtered by land.

Workflow:
    Stage 1: Generate land grid using h3-py and stream to PostGIS
    Stage 2: Create STAC item for H3 land grid

Output: PostGIS geo.h3_grids table + STAC metadata

Exports:
    GenerateH3Level4Job: Two-stage H3 Level 4 land grid job
"""

from typing import Dict, Any, List

from jobs.base import JobBase
from config.defaults import STACDefaults


class GenerateH3Level4Job(JobBase):
    """Generate Level 4 H3 land grid job."""

    # Job configuration
    job_type = "generate_h3_level4"

    # Two-stage workflow: generate+insert → STAC (Phase 3: h3-py native streaming - 9 NOV 2025)
    stages = [
        {
            "number": 1,
            "name": "generate_streaming",
            "task_type": "h3_native_streaming_postgis",
            "parallelism": "single",
            "description": "Generate H3 Level 4 land grid using h3-py and stream directly to PostGIS (3.5x faster)"
        },
        {
            "number": 2,
            "name": "create_stac",
            "task_type": "create_h3_stac",
            "parallelism": "single",
            "description": "Create STAC item for H3 land grid in system-h3-grids collection"
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
        Generate task parameters for each stage of H3 Level 4 land grid workflow.

        Two-stage workflow (Phase 3 - h3-py native streaming):
            Stage 1: Generate H3 land grid using h3-py → stream directly to PostGIS
            Stage 2: Query PostGIS → Create STAC item

        Args:
            stage: Stage number (1 or 2)
            job_params: Job parameters from submission
            job_id: Unique job identifier
            previous_results: Results from previous stage (None for stage 1)

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # STAGE 1: Generate land grid using h3-py and stream to PostGIS
            # NOTE: Land filtering will be added to h3_native_streaming_postgis handler in future
            return [{
                "task_id": f"{job_id[:8]}-h3level4-stage1",
                "task_type": "h3_native_streaming_postgis",
                "parameters": {
                    "resolution": 4,
                    "grid_id": "land_res4",
                    "grid_type": "land",
                    "source_job_id": job_id,
                    "land_filter": job_params.get("skip_land_filter", False) == False  # TODO: Implement in handler
                }
            }]

        elif stage == 2:
            # STAGE 2: Create STAC item
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            result_data = stage_1_result.get('result', {})
            grid_id = result_data.get('grid_id')
            bbox = result_data.get('bbox')

            if not grid_id or not bbox:
                raise ValueError("Stage 1 did not return grid_id and bbox")

            return [{
                "task_id": f"{job_id[:8]}-h3level4-stage2",
                "task_type": "create_h3_stac",
                "parameters": {
                    "grid_id": grid_id,
                    "table_name": "geo.h3_grids",
                    "bbox": bbox,
                    "resolution": 4,
                    "collection_id": STACDefaults.H3_COLLECTION,
                    "source_blob": ""  # No GeoParquet intermediate file in Phase 3
                }
            }]

        else:
            raise ValueError(f"Invalid stage {stage} for generate_h3_level4 job (valid: 1-2)")

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
            total_stages=2,  # Two-stage job: h3-py streaming → STAC (Phase 3 optimization - 9 NOV 2025)
            stage_results={},
            metadata={
                "description": "Generate Level 4 H3 land grid using Overture Maps",
                "created_by": "GenerateH3Level4Job",
                "workflow": "2-stage: h3-py native streaming → STAC (3.5x faster)"
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
        correlation_id = str(uuid.uuid4())[:8]
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

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary with task result extraction.

        Phase 3 - Two-stage workflow (9 NOV 2025):
        - Stage 1: h3-py native streaming to PostGIS (with land filtering TODO)
        - Stage 2: STAC item creation

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Comprehensive job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "GenerateH3Level4Job.finalize_job")

        # Handle missing context (shouldn't happen, but defensive)
        if not context:
            logger.warning("⚠️ finalize_job called without context")
            return {
                "job_type": "generate_h3_level4",
                "status": "completed"
            }

        # Extract task results (2 stages in Phase 3)
        task_results = context.task_results
        params = context.parameters

        # Extract Stage 1 result (h3-py streaming to PostGIS)
        stage_1_result = task_results[0] if len(task_results) > 0 else None
        stage_1_data = stage_1_result.result_data.get("result", {}) if stage_1_result and stage_1_result.result_data else {}

        # Extract Stage 2 result (STAC creation)
        stage_2_result = task_results[1] if len(task_results) > 1 else None
        stage_2_data = stage_2_result.result_data.get("result", {}) if stage_2_result and stage_2_result.result_data else {}

        # Extract comprehensive statistics from Stage 1 (h3_native_streaming_postgis)
        grid_id = stage_1_data.get("grid_id", "")
        table_name = stage_1_data.get("table_name", "geo.h3_grids")
        rows_inserted = stage_1_data.get("rows_inserted", 0)
        bbox = stage_1_data.get("bbox", [])
        processing_time_seconds = stage_1_data.get("processing_time_seconds", 0.0)
        memory_used_mb = stage_1_data.get("memory_used_mb", 0.0)

        # Extract STAC metadata from Stage 2
        stac_item_id = stage_2_data.get("item_id", "")
        stac_collection = stage_2_data.get("collection_id", "")

        # Build OGC Features URL
        ogc_features_url = ""
        if grid_id:
            ogc_features_url = f"https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/h3_grids/items?grid_id={grid_id}"

        # Build STAC Item URL
        stac_item_url = ""
        if stac_item_id and stac_collection:
            stac_item_url = f"https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/collections/{stac_collection}/items/{stac_item_id}"

        logger.info(
            f"✅ Job {context.job_id} completed: {rows_inserted} cells → PostGIS → STAC (Phase 3 h3-py streaming)"
        )

        return {
            "job_type": "generate_h3_level4",
            "job_id": context.job_id,
            "status": "completed",
            "resolution": 4,
            "total_cells": rows_inserted,
            "land_filter_note": "Land filtering TODO - currently generates all cells",
            "grid_id": grid_id,
            "bbox": bbox,
            "postgis_table": table_name,
            "ogc_features_url": ogc_features_url,
            "stac_item_id": stac_item_id,
            "stac_collection": stac_collection,
            "stac_item_url": stac_item_url,
            "performance": {
                "processing_time_seconds": round(processing_time_seconds, 2),
                "memory_used_mb": round(memory_used_mb, 2),
                "workflow": "h3-py native streaming (Phase 3 - 3.5x faster)"
            },
            "stage_results": {
                "stage_1_streaming": {
                    "rows_inserted": rows_inserted,
                    "table_name": table_name,
                    "grid_id": grid_id,
                    "bbox": bbox,
                    "processing_time_seconds": processing_time_seconds,
                    "memory_used_mb": memory_used_mb
                },
                "stage_2_stac": {
                    "item_id": stac_item_id,
                    "collection_id": stac_collection,
                    "inserted_to_pgstac": stage_2_data.get("inserted_to_pgstac", False)
                }
            }
        }
