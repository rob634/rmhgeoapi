"""
Create H3 Base Grid Job Declaration

Generates complete H3 hexagonal grids at resolutions 0-4 without any filtering.
Pure hierarchical generation using H3's deterministic structure.

Author: Robert and Geospatial Claude Legion
Date: 15 OCT 2025
Updated: 15 OCT 2025 - Phase 2: Migrated to JobBase ABC
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

    # Single-stage job: just generate the grid
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "generate",
            "task_type": "h3_base_generate",
            "parallelism": "fixed",
            "count": 1,  # Single task generates entire grid
            "description": "Generate complete H3 grid using hierarchical expansion"
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
        Generate task parameters for H3 base grid generation.

        Single-stage job: always returns one task with the grid generation parameters.

        Args:
            stage: Stage number (always 1 for this job)
            job_params: Job parameters (resolution, exclude_antimeridian, etc.)
            job_id: Job ID for task ID generation
            previous_results: Not used (no previous stages)

        Returns:
            List with single task dict
        """
        if stage != 1:
            raise ValueError(f"Invalid stage {stage} for create_h3_base job (only has 1 stage)")

        # Extract and validate resolution
        resolution = job_params.get('resolution')
        if resolution is None:
            raise ValueError("resolution parameter is required")

        if not isinstance(resolution, int) or resolution < 0 or resolution > 4:
            raise ValueError(f"resolution must be 0-4, got {resolution}")

        # Build task parameters
        task_params = {
            "resolution": resolution,
            "exclude_antimeridian": job_params.get('exclude_antimeridian', True),
            "output_folder": job_params.get('output_folder', 'h3/base'),
            "output_filename": job_params.get('output_filename')
        }

        # Create single task
        return [
            {
                "task_id": f"{job_id[:8]}-h3base-res{resolution}",
                "task_type": "h3_base_generate",
                "parameters": task_params
            }
        ]

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
            total_stages=1,  # Single-stage job
            stage_results={},
            metadata={
                "description": f"H3 Base Grid Generation - Resolution {params['resolution']}",
                "created_by": "CreateH3BaseJob",
                "expected_cells": {
                    0: 122, 1: 842, 2: 5882, 3: 41162, 4: 288122
                }.get(params['resolution'], 0)
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
            correlation_id=str(uuid.uuid4())
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
