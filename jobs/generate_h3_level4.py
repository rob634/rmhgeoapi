# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Single-stage H3 Level 4 land grid generation
# PURPOSE: Generate global Level 4 H3 land grid and save to gold container
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: GenerateH3Level4Job (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict parameters)
# DEPENDENCIES: jobs.base.JobBase, services.handler_h3_level4
# SOURCE: HTTP POST requests to /api/jobs/generate_h3_level4
# SCOPE: Global H3 Level 4 grid generation (~875 land cells filtered)
# VALIDATION: Parameter validation in handler service
# PATTERNS: Single-stage job workflow, Land filtering, GeoParquet output
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "generate_h3_level4"
# INDEX: GenerateH3Level4Job:29, stages:41, create_tasks_for_stage:61
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

    # Three-stage workflow: generate → PostGIS → STAC
    stages = [
        {
            "number": 1,
            "name": "generate_level4_grid",
            "task_type": "h3_level4_generate",
            "parallelism": "single",
            "description": "Generate global L4 grid, filter by land, save to GeoParquet"
        },
        {
            "number": 2,
            "name": "insert_postgis",
            "task_type": "insert_h3_to_postgis",
            "parallelism": "single",
            "description": "Load GeoParquet and insert to PostGIS geo.h3_grids table"
        },
        {
            "number": 3,
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

        Three-stage workflow:
            Stage 1: Generate H3 land grid → GeoParquet
            Stage 2: Load GeoParquet → Insert to PostGIS
            Stage 3: Query PostGIS → Create STAC item

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters from submission
            job_id: Unique job identifier
            previous_results: Results from previous stage (None for stage 1)

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # STAGE 1: Generate land grid and save to GeoParquet
            return [{
                "task_id": f"{job_id[:8]}-h3level4-stage1",
                "task_type": "h3_level4_generate",
                "parameters": {
                    "land_geojson_path": job_params.get("land_geojson_path"),
                    "overture_release": job_params.get("overture_release"),
                    "output_folder": job_params.get("output_folder", "h3/grids"),
                    "output_filename": job_params.get("output_filename", "land_h3_level4.parquet")
                }
            }]

        elif stage == 2:
            # STAGE 2: Insert to PostGIS
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            result_data = stage_1_result.get('result', {})
            blob_path = result_data.get('blob_path')

            if not blob_path:
                raise ValueError("Stage 1 did not return blob_path")

            return [{
                "task_id": f"{job_id[:8]}-h3level4-stage2",
                "task_type": "insert_h3_to_postgis",
                "parameters": {
                    "blob_path": blob_path,
                    "grid_id": "land_res4",
                    "grid_type": "land",
                    "resolution": 4,
                    "source_job_id": job_id
                }
            }]

        elif stage == 3:
            # STAGE 3: Create STAC item
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            stage_2_result = previous_results[0]
            if not stage_2_result.get('success'):
                raise ValueError(f"Stage 2 failed: {stage_2_result.get('error')}")

            result_data = stage_2_result.get('result', {})
            grid_id = result_data.get('grid_id')
            bbox = result_data.get('bbox')

            if not grid_id or not bbox:
                raise ValueError("Stage 2 did not return grid_id and bbox")

            # Get blob_path from Stage 1
            stage_1_results = [r for r in previous_results if 'blob_path' in r.get('result', {})]
            source_blob = stage_1_results[0]['result']['blob_path'] if stage_1_results else ""

            return [{
                "task_id": f"{job_id[:8]}-h3level4-stage3",
                "task_type": "create_h3_stac",
                "parameters": {
                    "grid_id": grid_id,
                    "table_name": "geo.h3_grids",
                    "bbox": bbox,
                    "resolution": 4,
                    "collection_id": "system-h3-grids",
                    "source_blob": source_blob
                }
            }]

        else:
            raise ValueError(f"Invalid stage {stage} for generate_h3_level4 job (valid: 1-3)")

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
            total_stages=3,  # Three-stage job: generate → PostGIS → STAC
            stage_results={},
            metadata={
                "description": "Generate Level 4 H3 land grid using Overture Maps",
                "created_by": "GenerateH3Level4Job",
                "workflow": "3-stage: GeoParquet → PostGIS → STAC"
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

        Extracts statistics from Stage 1 task result (h3_level4_generate handler):
        - Total Level 4 cells generated
        - Land filtering statistics
        - Blob storage path
        - File size and processing time

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

        # Extract task results (3 stages)
        task_results = context.task_results
        params = context.parameters

        # Extract Stage 1 result (grid generation + land filtering)
        stage_1_result = task_results[0] if len(task_results) > 0 else None
        stage_1_data = stage_1_result.result_data.get("result", {}) if stage_1_result and stage_1_result.result_data else {}

        # Extract Stage 2 result (PostGIS insertion)
        stage_2_result = task_results[1] if len(task_results) > 1 else None
        stage_2_data = stage_2_result.result_data.get("result", {}) if stage_2_result and stage_2_result.result_data else {}

        # Extract Stage 3 result (STAC creation)
        stage_3_result = task_results[2] if len(task_results) > 2 else None
        stage_3_data = stage_3_result.result_data.get("result", {}) if stage_3_result and stage_3_result.result_data else {}

        # Extract comprehensive statistics
        total_generated = stage_1_data.get("total_generated", 0)
        total_land_cells = stage_1_data.get("total_land_cells", 0)
        filtering_method = stage_1_data.get("filtering_method", "unknown")
        blob_path = stage_1_data.get("blob_path", "")
        file_size_mb = stage_1_data.get("file_size_mb", 0.0)
        grid_id = stage_2_data.get("grid_id", "")
        table_name = stage_2_data.get("table_name", "")
        bbox = stage_2_data.get("bbox", [])
        stac_item_id = stage_3_data.get("item_id", "")
        stac_collection = stage_3_data.get("collection_id", "")

        # Build download URL
        download_url = ""
        if blob_path:
            download_url = f"https://rmhazuregeo.blob.core.windows.net/rmhazuregeogold/{blob_path}"

        # Build OGC Features URL
        ogc_features_url = ""
        if grid_id:
            ogc_features_url = f"https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/h3_grids/items?grid_id={grid_id}"

        # Build STAC Item URL
        stac_item_url = ""
        if stac_item_id and stac_collection:
            stac_item_url = f"https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/collections/{stac_collection}/items/{stac_item_id}"

        logger.info(
            f"✅ Job {context.job_id} completed: {total_land_cells}/{total_generated} land cells → PostGIS → STAC"
        )

        return {
            "job_type": "generate_h3_level4",
            "job_id": context.job_id,
            "status": "completed",
            "resolution": 4,
            "total_generated": total_generated,
            "total_land_cells": total_land_cells,
            "filtering_method": filtering_method,
            "land_geojson_path": params.get("land_geojson_path"),
            "overture_release": params.get("overture_release"),
            "grid_id": grid_id,
            "bbox": bbox,
            "output_path": blob_path,
            "download_url": download_url,
            "file_size_mb": round(file_size_mb, 2),
            "postgis_table": table_name,
            "ogc_features_url": ogc_features_url,
            "stac_item_id": stac_item_id,
            "stac_collection": stac_collection,
            "stac_item_url": stac_item_url,
            "stage_results": {
                "stage_1_generate_filter": {
                    "total_generated": total_generated,
                    "total_land_cells": total_land_cells,
                    "filtering_method": filtering_method,
                    "blob_path": blob_path,
                    "file_size_mb": file_size_mb
                },
                "stage_2_postgis": {
                    "rows_inserted": stage_2_data.get("rows_inserted", 0),
                    "table_name": table_name,
                    "grid_id": grid_id,
                    "bbox": bbox
                },
                "stage_3_stac": {
                    "item_id": stac_item_id,
                    "collection_id": stac_collection,
                    "inserted_to_pgstac": stage_3_data.get("inserted_to_pgstac", False)
                }
            }
        }
