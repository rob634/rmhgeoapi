# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Single-stage H3 base grid generation (resolutions 0-4)
# PURPOSE: Generate complete H3 hexagonal grids at resolutions 0-4 (no filtering)
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: CreateH3BaseJob (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict parameters)
# DEPENDENCIES: jobs.base.JobBase
# SOURCE: HTTP job submission for H3 grid generation
# SCOPE: Global H3 grids at resolutions 0-4 (complete hierarchical structure)
# VALIDATION: Resolution range validation (0-4)
# PATTERNS: Single-stage job, Hierarchical grid generation, No filtering
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "create_h3_base"
# INDEX: CreateH3BaseJob:17, stages:29, create_tasks_for_stage:49
# ============================================================================

"""
Create H3 Base Grid Job Declaration

Generates complete H3 hexagonal grids at resolutions 0-4 without any filtering.
Pure hierarchical generation using H3's deterministic structure.

Author: Robert and Geospatial Claude Legion
Date: 15 OCT 2025
Updated: 15 OCT 2025 - Phase 2: Migrated to JobBase ABC
Last Updated: 29 OCT 2025
"""

from typing import List, Dict, Any

from jobs.base import JobBase


class CreateH3BaseJob(JobBase):
    """
    H3 Base Grid Generation - Single-stage job that creates complete global grids.

    Resolutions:
        0: 122 cells (~1,108 km edge)
        1: 842 cells (~418 km edge)
        2: 5,882 cells (~158 km edge)
        3: 41,162 cells (~59.8 km edge)
        4: 288,122 cells (~22.6 km edge)

    This is PURE DATA - no execution logic, just job declaration.
    """

    # Job metadata
    job_type: str = "create_h3_base"
    description: str = "Generate complete H3 hexagonal grid at specified resolution"

    # Three-stage job: generate → PostGIS → STAC
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "generate",
            "task_type": "h3_base_generate",
            "parallelism": "single",
            "description": "Generate complete H3 grid and save to GeoParquet"
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
            "description": "Create STAC item for H3 grid in system-h3-grids collection"
        }
    ]

    # Parameter schema with validation
    parameters_schema: Dict[str, Any] = {
        "resolution": {
            "type": "int",
            "min": 0,
            "max": 4,
            "required": True,
            "description": "H3 resolution level (0=coarsest, 4=finest supported)"
        },
        "exclude_antimeridian": {
            "type": "bool",
            "default": True,
            "description": "Exclude cells crossing 180° longitude (prevents rendering issues)"
        },
        "output_folder": {
            "type": "str",
            "default": "h3/base",
            "description": "Output folder in gold container"
        },
        "output_filename": {
            "type": "str",
            "default": None,
            "description": "Output filename (auto-generated if not provided: h3_res{N}_global.parquet)"
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
        Generate task parameters for each stage of H3 base grid workflow.

        Three-stage workflow:
            Stage 1: Generate H3 grid → GeoParquet
            Stage 2: Load GeoParquet → Insert to PostGIS
            Stage 3: Query PostGIS → Create STAC item

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters (resolution, exclude_antimeridian, etc.)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage tasks

        Returns:
            List with single task dict for current stage

        Raises:
            ValueError: Invalid stage number or missing previous results
        """
        resolution = job_params.get('resolution')

        if stage == 1:
            # STAGE 1: Generate H3 grid and save to GeoParquet
            if resolution is None:
                raise ValueError("resolution parameter is required")

            if not isinstance(resolution, int) or resolution < 0 or resolution > 4:
                raise ValueError(f"resolution must be 0-4, got {resolution}")

            task_params = {
                "resolution": resolution,
                "exclude_antimeridian": job_params.get('exclude_antimeridian', True),
                "output_folder": job_params.get('output_folder', 'h3/base'),
                "output_filename": job_params.get('output_filename')
            }

            return [
                {
                    "task_id": f"{job_id[:8]}-h3base-res{resolution}-stage1",
                    "task_type": "h3_base_generate",
                    "parameters": task_params
                }
            ]

        elif stage == 2:
            # STAGE 2: Insert to PostGIS
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            # Extract blob_path from Stage 1 result
            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            result_data = stage_1_result.get('result', {})
            blob_path = result_data.get('blob_path')

            if not blob_path:
                raise ValueError("Stage 1 did not return blob_path")

            task_params = {
                "blob_path": blob_path,
                "grid_id": f"global_res{resolution}",
                "grid_type": "global",
                "resolution": resolution,
                "source_job_id": job_id
            }

            return [
                {
                    "task_id": f"{job_id[:8]}-h3base-res{resolution}-stage2",
                    "task_type": "insert_h3_to_postgis",
                    "parameters": task_params
                }
            ]

        elif stage == 3:
            # STAGE 3: Create STAC item
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Extract metadata from Stage 2 result
            stage_2_result = previous_results[0]
            if not stage_2_result.get('success'):
                raise ValueError(f"Stage 2 failed: {stage_2_result.get('error')}")

            result_data = stage_2_result.get('result', {})
            grid_id = result_data.get('grid_id')
            bbox = result_data.get('bbox')
            table_name = result_data.get('table_name', 'geo.h3_grids')

            if not grid_id or not bbox:
                raise ValueError("Stage 2 did not return grid_id and bbox")

            # Get blob_path from Stage 1 for STAC asset
            stage_1_results = [r for r in previous_results if 'blob_path' in r.get('result', {})]
            source_blob = stage_1_results[0]['result']['blob_path'] if stage_1_results else ""

            task_params = {
                "grid_id": grid_id,
                "table_name": table_name,
                "bbox": bbox,
                "resolution": resolution,
                "collection_id": "system-h3-grids",
                "source_blob": source_blob
            }

            return [
                {
                    "task_id": f"{job_id[:8]}-h3base-res{resolution}-stage3",
                    "task_type": "create_h3_stac",
                    "parameters": task_params
                }
            ]

        else:
            raise ValueError(f"Invalid stage {stage} for create_h3_base job (valid: 1-3)")

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters before submission.

        Args:
            params: Raw job parameters

        Returns:
            Validated and normalized parameters

        Raises:
            ValueError: If parameters are invalid
        """
        # Resolution is required
        if 'resolution' not in params:
            raise ValueError("'resolution' parameter is required")

        resolution = params['resolution']
        if not isinstance(resolution, int):
            raise ValueError(f"resolution must be an integer, got {type(resolution).__name__}")

        if resolution < 0 or resolution > 4:
            raise ValueError(f"resolution must be 0-4, got {resolution}")

        # Validate filename if provided
        filename = params.get('output_filename')
        if filename:
            if not isinstance(filename, str):
                raise ValueError(f"output_filename must be string, got {type(filename).__name__}")
            if not filename.endswith('.parquet'):
                raise ValueError("output_filename must end with .parquet")

        # Return normalized params
        return {
            "resolution": resolution,
            "exclude_antimeridian": params.get('exclude_antimeridian', True),
            "output_folder": params.get('output_folder', 'h3/base'),
            "output_filename": filename
        }

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID for idempotency.
        
        Same parameters = same job ID = deduplication.
        
        Args:
            params: Validated job parameters
            
        Returns:
            SHA256 hash as hex string
        """
        import hashlib
        import json
        
        # Create deterministic string from job type + params
        id_string = f"create_h3_base:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(id_string.encode()).hexdigest()

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create job record for database storage.
        
        Args:
            job_id: Generated job ID
            params: Validated parameters
            
        Returns:
            Job record dict
        """
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus
        
        # Create job record object
        job_record = JobRecord(
            job_id=job_id,
            job_type="create_h3_base",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=3,  # Three-stage job: generate → PostGIS → STAC
            stage_results={},
            metadata={
                "description": f"H3 Base Grid Generation - Resolution {params['resolution']}",
                "created_by": "CreateH3BaseJob",
                "expected_cells": {
                    0: 122, 1: 842, 2: 5882, 3: 41162, 4: 288122
                }.get(params['resolution'], 0),
                "workflow": "3-stage: GeoParquet → PostGIS → STAC"
            }
        )
        
        # Persist to database
        repos = RepositoryFactory.create_repositories()
        repos['job_repo'].create_job(job_record)
        
        return {"job_id": job_id, "status": "queued"}
    
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
        from util_logger import LoggerFactory, ComponentType
        import uuid
        
        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "CreateH3BaseJob.queue_job")
        
        # Create Service Bus message
        message = JobQueueMessage(
            job_id=job_id,
            job_type="create_h3_base",
            stage=1,
            parameters=params,
            message_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4())[:8]
        )
        
        # Send to Service Bus
        config = get_config()
        service_bus = ServiceBusRepository(
            connection_string=config.get_service_bus_connection(),
            queue_name=config.jobs_queue_name
        )
        
        result = service_bus.send_message(message.model_dump_json())
        logger.info(f"✅ Job {job_id[:16]}... queued to Service Bus")
        
        return {
            "queued": True,
            "queue_type": "service_bus",
            "message_id": message.message_id
        }

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary with task result extraction.

        Extracts statistics from Stage 1 task result (h3_base_generate handler):
        - Total H3 cells created
        - Blob storage path
        - File size and processing time
        - Resolution metadata

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Comprehensive job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "CreateH3BaseJob.finalize_job")

        # Handle missing context (shouldn't happen, but defensive)
        if not context:
            logger.warning("⚠️ finalize_job called without context")
            return {
                "job_type": "create_h3_base",
                "status": "completed"
            }

        # Extract task results (3 stages)
        task_results = context.task_results
        params = context.parameters

        # Extract Stage 1 result (grid generation)
        stage_1_result = task_results[0] if len(task_results) > 0 else None
        stage_1_data = stage_1_result.result_data.get("result", {}) if stage_1_result and stage_1_result.result_data else {}

        # Extract Stage 2 result (PostGIS insertion)
        stage_2_result = task_results[1] if len(task_results) > 1 else None
        stage_2_data = stage_2_result.result_data.get("result", {}) if stage_2_result and stage_2_result.result_data else {}

        # Extract Stage 3 result (STAC creation)
        stage_3_result = task_results[2] if len(task_results) > 2 else None
        stage_3_data = stage_3_result.result_data.get("result", {}) if stage_3_result and stage_3_result.result_data else {}

        # Extract comprehensive statistics
        total_cells = stage_1_data.get("total_cells", 0)
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

        # Build OGC Features URL (for PostGIS access)
        ogc_features_url = ""
        if grid_id:
            ogc_features_url = f"https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/h3_grids/items?grid_id={grid_id}"

        # Build STAC Item URL
        stac_item_url = ""
        if stac_item_id and stac_collection:
            stac_item_url = f"https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/collections/{stac_collection}/items/{stac_item_id}"

        logger.info(f"✅ Job {context.job_id} completed: {total_cells} cells → PostGIS → STAC")

        return {
            "job_type": "create_h3_base",
            "job_id": context.job_id,
            "status": "completed",
            "resolution": params.get("resolution"),
            "total_cells": total_cells,
            "exclude_antimeridian": params.get("exclude_antimeridian", True),
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
                "stage_1_generate": {
                    "total_cells": total_cells,
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
