# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - H3 Land Grid Pyramid Bootstrap (7-stage workflow)
# PURPOSE: Generate complete H3 land-filtered grid pyramid from resolution 2-7
# LAST_REVIEWED: 14 NOV 2025
# EXPORTS: BootstrapH3LandGridPyramidJob (JobBase implementation)
# INTERFACES: JobBase (implements 6-method contract)
# PYDANTIC_MODELS: None (uses dict parameters)
# DEPENDENCIES: jobs.base.JobBase, services.handler_generate_h3_grid
# SOURCE: HTTP job submission for H3 bootstrap workflow
# SCOPE: Land-filtered H3 grids for World Bank Agricultural Geography Platform
# VALIDATION: Resolution range validation (2-7)
# PATTERNS: Multi-stage job, Universal handler, Fan-out parallelism, DRY architecture
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "bootstrap_h3_land_grid_pyramid"
# INDEX: BootstrapH3LandGridPyramidJob:17, stages:68, create_tasks_for_stage:148
# ============================================================================

"""
H3 Land Grid Pyramid Bootstrap Job

Generates complete H3 land-filtered grid pyramid for resolutions 2-7 using the
universal generate_h3_grid handler with DRY principles.

7-Stage Workflow:
    Stage 1: Generate res 2 with spatial filter (base generation)
    Stage 2: Generate res 3 from res 2 parents (cascade, batched)
    Stage 3: Generate res 4 from res 3 parents (cascade, batched)
    Stage 4: Generate res 5 from res 4 parents (cascade, batched)
    Stage 5: Generate res 6 from res 5 parents (cascade, batched)
    Stage 6: Generate res 7 from res 6 parents (cascade, batched)
    Stage 7: Finalize pyramid (verify counts, update metadata)

Expected Cell Counts (land-filtered, approximate):
    Res 2: ~2,000 cells (varies by filter)
    Res 3: ~14,000 cells
    Res 4: ~98,000 cells
    Res 5: ~686,000 cells
    Res 6: ~4.8M cells
    Res 7: ~33.6M cells
    Total: ~39.2M cells

Architecture:
    - Uses single universal handler "generate_h3_grid" for ALL resolutions (DRY)
    - Stage 1: Base generation with spatial_filter_table (use_cascade=False)
    - Stages 2-6: Cascade from parent resolution with batching (use_cascade=True)
    - Stage 7: Finalization handler for verification and metadata

Author: Robert and Geospatial Claude Legion
Date: 14 NOV 2025
"""

from typing import List, Dict, Any

from jobs.base import JobBase


class BootstrapH3LandGridPyramidJob(JobBase):
    """
    H3 Land Grid Pyramid Bootstrap - 7-stage job for complete pyramid generation.

    Uses universal handler following DRY principles - single handler for all resolutions.
    Stages 2-6 use fan-out parallelism with batching for efficient cascade generation.
    """

    # Job metadata
    job_type: str = "bootstrap_h3_land_grid_pyramid"
    description: str = "Generate complete H3 land-filtered grid pyramid (res 2-7)"

    # 7-stage workflow using universal handler
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "generate_res2_base",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 2 base grid with land filter (spatial_filter_table)"
        },
        {
            "number": 2,
            "name": "generate_res3_cascade",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 3 from res 2 parents (batched cascade)"
        },
        {
            "number": 3,
            "name": "generate_res4_cascade",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 4 from res 3 parents (batched cascade)"
        },
        {
            "number": 4,
            "name": "generate_res5_cascade",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 5 from res 4 parents (batched cascade)"
        },
        {
            "number": 5,
            "name": "generate_res6_cascade",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 6 from res 5 parents (batched cascade)"
        },
        {
            "number": 6,
            "name": "generate_res7_cascade",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 7 from res 6 parents (batched cascade)"
        },
        {
            "number": 7,
            "name": "finalize_pyramid",
            "task_type": "finalize_h3_pyramid",
            "parallelism": "single",
            "description": "Verify cell counts and update metadata"
        }
    ]

    # Batch sizes per resolution (parent cells per task)
    BATCH_SIZES = {
        3: 500,   # Res 3: 500 parent cells per task (~7 children each = 3,500 cells/task)
        4: 500,   # Res 4: 500 parent cells per task
        5: 500,   # Res 5: 500 parent cells per task
        6: 200,   # Res 6: 200 parent cells per task (larger output)
        7: 100,   # Res 7: 100 parent cells per task (largest output)
    }

    # Expected cell counts for validation (approximate, land-filtered)
    EXPECTED_CELLS = {
        2: 2000,      # Base filtered grid
        3: 14000,     # 7x multiplier
        4: 98000,     # 7x multiplier
        5: 686000,    # 7x multiplier
        6: 4800000,   # 7x multiplier
        7: 33600000,  # 7x multiplier
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for each stage of H3 bootstrap workflow.

        7-stage workflow:
            Stage 1: Generate res 2 with spatial filter (1 task, base generation)
            Stages 2-6: Generate res N from res N-1 parents (batched fan-out)
            Stage 7: Finalize pyramid (1 task, verification)

        Args:
            stage: Stage number (1-7)
            job_params: Job parameters (spatial_filter_table, grid_id_prefix, etc.)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage tasks

        Returns:
            List of task dicts for current stage

        Raises:
            ValueError: Invalid stage number or missing previous results
        """
        spatial_filter_table = job_params.get('spatial_filter_table', 'system_admin0')
        grid_id_prefix = job_params.get('grid_id_prefix', 'land')

        if stage == 1:
            # STAGE 1: Generate res 2 with spatial filter (base generation)
            # Use generate_h3_grid with use_cascade=False and spatial_filter_table
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-res2-base",
                    "task_type": "generate_h3_grid",
                    "parameters": {
                        "resolution": 2,
                        "grid_id": f"{grid_id_prefix}_res2",
                        "grid_type": "land",
                        "source_job_id": job_id,
                        "use_cascade": False,  # Base generation
                        "spatial_filter_table": f"geo.{spatial_filter_table}",
                        "filter_mode": "intersects"
                    }
                }
            ]

        elif stage in [2, 3, 4, 5, 6]:
            # STAGES 2-6: Generate res N from res N-1 parents (cascade with batching)
            resolution = stage  # Stage 2 = res 3, Stage 3 = res 4, etc.
            parent_resolution = resolution - 1
            parent_grid_id = f"{grid_id_prefix}_res{parent_resolution}"
            grid_id = f"{grid_id_prefix}_res{resolution}"

            # For now, create single task (batching to be implemented in Phase 2)
            # Phase 2 will use previous_results to get parent cell count and create batches
            return [
                {
                    "task_id": f"{job_id[:8]}-s{stage}-res{resolution}-cascade",
                    "task_type": "generate_h3_grid",
                    "parameters": {
                        "resolution": resolution,
                        "grid_id": grid_id,
                        "grid_type": "land",
                        "source_job_id": job_id,
                        "use_cascade": True,  # Cascade from parents
                        "parent_grid_id": parent_grid_id,
                        "filter_mode": "intersects"
                    }
                }
            ]

        elif stage == 7:
            # STAGE 7: Finalize pyramid (verify counts, update metadata)
            if not previous_results:
                raise ValueError("Stage 7 requires Stage 6 results")

            return [
                {
                    "task_id": f"{job_id[:8]}-s7-finalize",
                    "task_type": "finalize_h3_pyramid",
                    "parameters": {
                        "grid_id_prefix": grid_id_prefix,
                        "resolutions": [2, 3, 4, 5, 6, 7],
                        "expected_cells": BootstrapH3LandGridPyramidJob.EXPECTED_CELLS,
                        "source_job_id": job_id
                    }
                }
            ]

        else:
            raise ValueError(f"Invalid stage {stage} for bootstrap_h3_land_grid_pyramid job (valid: 1-7)")

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
        # Spatial filter table (optional, has default)
        spatial_filter_table = params.get('spatial_filter_table', 'system_admin0')
        if not isinstance(spatial_filter_table, str):
            raise ValueError(f"spatial_filter_table must be string, got {type(spatial_filter_table).__name__}")

        # Grid ID prefix (optional, has default)
        grid_id_prefix = params.get('grid_id_prefix', 'land')
        if not isinstance(grid_id_prefix, str):
            raise ValueError(f"grid_id_prefix must be string, got {type(grid_id_prefix).__name__}")

        # Return normalized params
        return {
            "spatial_filter_table": spatial_filter_table,
            "grid_id_prefix": grid_id_prefix
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
        id_string = f"bootstrap_h3_land_grid_pyramid:{json.dumps(params, sort_keys=True)}"
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
            job_type="bootstrap_h3_land_grid_pyramid",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=7,
            stage_results={},
            metadata={
                "description": "H3 Land Grid Pyramid Bootstrap (res 2-7)",
                "created_by": "BootstrapH3LandGridPyramidJob",
                "expected_total_cells": sum(BootstrapH3LandGridPyramidJob.EXPECTED_CELLS.values()),
                "workflow": "7-stage: base → cascade → cascade → cascade → cascade → cascade → finalize",
                "spatial_filter": params.get('spatial_filter_table', 'system_admin0'),
                "grid_id_prefix": params.get('grid_id_prefix', 'land')
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "BootstrapH3LandGridPyramidJob.queue_job")

        # Create Service Bus message
        message = JobQueueMessage(
            job_id=job_id,
            job_type="bootstrap_h3_land_grid_pyramid",
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
        logger.info(f"✅ Job {job_id[:16]}... queued to Service Bus (H3 Land Pyramid Bootstrap)")

        return {
            "queued": True,
            "queue_type": "service_bus",
            "message_id": message.message_id
        }

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary with pyramid statistics.

        7-stage workflow summary:
        - Stages 1-6: Grid generation (base + 5 cascade levels)
        - Stage 7: Finalization and verification

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Comprehensive job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "BootstrapH3LandGridPyramidJob.finalize_job")

        # Handle missing context (shouldn't happen, but defensive)
        if not context:
            logger.warning("⚠️ finalize_job called without context")
            return {
                "job_type": "bootstrap_h3_land_grid_pyramid",
                "status": "completed"
            }

        # Extract parameters
        params = context.parameters
        grid_id_prefix = params.get('grid_id_prefix', 'land')
        spatial_filter = params.get('spatial_filter_table', 'system_admin0')

        # Extract results from all stages (7 stages total)
        task_results = context.task_results

        # Build resolution stats from stages 1-6 (generation stages)
        resolution_stats = {}
        total_cells = 0

        for stage_num in range(1, 7):  # Stages 1-6 are generation stages
            if len(task_results) >= stage_num:
                stage_result = task_results[stage_num - 1]
                result_data = stage_result.result_data.get("result", {}) if stage_result.result_data else {}

                resolution = stage_num + 1  # Stage 1 = res 2, Stage 2 = res 3, etc.
                rows_inserted = result_data.get("rows_inserted", 0)
                grid_id = result_data.get("grid_id", f"{grid_id_prefix}_res{resolution}")

                resolution_stats[f"res{resolution}"] = {
                    "cells": rows_inserted,
                    "grid_id": grid_id
                }
                total_cells += rows_inserted

        # Extract finalization result (Stage 7)
        finalization_result = {}
        if len(task_results) >= 7:
            finalization_result = task_results[6].result_data.get("result", {}) if task_results[6].result_data else {}

        logger.info(f"✅ Job {context.job_id} completed: H3 Land Pyramid ({total_cells:,} total cells across res 2-7)")

        return {
            "job_type": "bootstrap_h3_land_grid_pyramid",
            "job_id": context.job_id,
            "status": "completed",
            "grid_id_prefix": grid_id_prefix,
            "spatial_filter": spatial_filter,
            "total_cells": total_cells,
            "resolution_stats": resolution_stats,
            "finalization": finalization_result,
            "metadata": {
                "workflow": "7-stage bootstrap (base + 5 cascade + finalize)",
                "universal_handler": "generate_h3_grid (DRY architecture)",
                "expected_cells": sum(BootstrapH3LandGridPyramidJob.EXPECTED_CELLS.values()),
                "actual_cells": total_cells
            }
        }
