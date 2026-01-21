# ============================================================================
# H3 LAND GRID PYRAMID BOOTSTRAP - DOCKER VERSION
# ============================================================================
# STATUS: Jobs - Single-stage Docker H3 pyramid generation (no timeout)
# PURPOSE: Generate complete H3 land-filtered pyramid in one long-running task
# LAST_REVIEWED: 20 JAN 2026
# ============================================================================
"""
H3 Land Grid Pyramid Bootstrap - Docker Optimized.

Generates complete H3 land-filtered grid pyramid for resolutions 2-7 using
a SINGLE long-running Docker task instead of fan-out parallelism.

Why Docker Single-Task (vs Function App Fan-Out):
    - No timeout constraints (can run for hours)
    - No queue overhead (1 message vs 200 messages)
    - Checkpoint-based resume (vs batch tracking table)
    - Simpler debugging (one task to monitor)
    - Docker's strength: long-running, not many-short-tasks

Architecture Comparison:
    Function App: Stage 2 = 200 batch tasks via Service Bus parallelism
    Docker:       Stage 2 = 1 task with internal checkpoints

Expected Performance:
    - Total time: ~20-30 minutes (same as parallel, sequential on one worker)
    - Memory: ~200MB peak (manageable)
    - Checkpoint interval: Every 20 batches (~2 minutes)

Exports:
    BootstrapH3DockerJob: Single-stage Docker H3 pyramid job
"""

from typing import List, Dict, Any, Optional

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class BootstrapH3DockerJob(JobBaseMixin, JobBase):
    """
    H3 Land Grid Pyramid Bootstrap - Docker optimized single-task job.

    Consolidates base generation + cascade + finalization into ONE handler.
    Uses checkpoint phases for resumability after container restart.

    JobBaseMixin provides: validate_job_parameters, generate_job_id, create_job_record, queue_job
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================

    job_type: str = "bootstrap_h3_docker"
    description: str = "Generate H3 land-filtered grid pyramid (res 2-7) - DOCKER SINGLE TASK"

    # Single stage - handler does everything with checkpoints
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "h3_pyramid_complete",
            "task_type": "h3_pyramid_complete",
            "parallelism": "single",
            "description": "Generate base + cascade + finalize in one task (Docker)"
        }
    ]

    # Same parameters as Function App version for compatibility
    parameters_schema: Dict[str, Any] = {
        'grid_id_prefix': {
            'type': 'str',
            'default': 'land',
            'description': 'Prefix for grid IDs (e.g., "land" → "land_res2", "land_res3"...)'
        },
        'country_filter': {
            'type': 'str',
            'default': None,
            'description': 'Optional ISO3 country code for testing (e.g., "ALB" for Albania)'
        },
        'bbox_filter': {
            'type': 'list',
            'default': None,
            'description': 'Optional bounding box [minx, miny, maxx, maxy] for spatial filtering'
        },
        'base_resolution': {
            'type': 'int',
            'default': 2,
            'min': 0,
            'max': 5,
            'description': 'Base resolution to start from (default: 2)'
        },
        'target_resolutions': {
            'type': 'list',
            'default': [3, 4, 5, 6, 7],
            'description': 'Target resolutions for cascade (default: 3-7)'
        },
        'cascade_batch_size': {
            'type': 'int',
            'default': 10,
            'min': 1,
            'max': 100,
            'description': 'Number of parent cells per internal batch (for checkpointing)'
        },
        'checkpoint_interval': {
            'type': 'int',
            'default': 20,
            'min': 1,
            'max': 100,
            'description': 'Save checkpoint every N batches (default: 20)'
        }
    }

    # ========================================================================
    # HELPER: Dynamic Admin0 Table Lookup
    # ========================================================================

    @staticmethod
    def _resolve_admin0_table() -> str:
        """
        Resolve admin0 table name via Promote Service.

        Returns:
            Table name (without schema prefix, e.g., 'curated_admin0')

        Raises:
            ValueError: If no system dataset with role 'admin0_boundaries' is registered
        """
        from services.promote_service import PromoteService
        from core.models.promoted import SystemRole

        service = PromoteService()
        table = service.get_system_table_name(SystemRole.ADMIN0_BOUNDARIES.value)

        if not table:
            raise ValueError(
                "No system-reserved dataset found with role 'admin0_boundaries'. "
                "You must first:\n"
                "  1. Create admin0 table via process_vector job\n"
                "  2. Promote it: POST /api/promote with is_system_reserved=true, system_role='admin0_boundaries'\n"
                "Then retry this job."
            )

        if '.' in table:
            table = table.split('.')[-1]
        return table

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Task Creation
    # ========================================================================

    @classmethod
    def create_tasks_for_stage(
        cls,
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate single task for complete H3 pyramid generation.

        Args:
            stage: Stage number (must be 1)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Not used (single stage)

        Returns:
            List with single task dict
        """
        from core.task_id import generate_deterministic_task_id

        if stage != 1:
            raise ValueError(f"BootstrapH3DockerJob has 1 stage, got stage {stage}")

        # Resolve admin0 table
        spatial_filter_table = cls._resolve_admin0_table()

        # Extract parameters with defaults
        grid_id_prefix = job_params.get('grid_id_prefix', 'land')
        country_filter = job_params.get('country_filter')
        bbox_filter = job_params.get('bbox_filter')
        base_resolution = job_params.get('base_resolution', 2)
        target_resolutions = job_params.get('target_resolutions', [3, 4, 5, 6, 7])
        cascade_batch_size = job_params.get('cascade_batch_size', 10)
        checkpoint_interval = job_params.get('checkpoint_interval', 20)

        task_params = {
            # Grid configuration
            'grid_id_prefix': grid_id_prefix,
            'base_resolution': base_resolution,
            'target_resolutions': target_resolutions,

            # Spatial filtering
            'spatial_filter_table': f"geo.{spatial_filter_table}",
            'country_filter': country_filter,
            'bbox_filter': bbox_filter,

            # Processing configuration
            'cascade_batch_size': cascade_batch_size,
            'checkpoint_interval': checkpoint_interval,

            # Job tracking
            'source_job_id': job_id,
        }

        return [{
            'task_id': generate_deterministic_task_id(job_id, 1, "h3_pyramid_complete"),
            'task_type': 'h3_pyramid_complete',
            'parameters': task_params
        }]

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create job summary from the single task result.

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Job summary dict
        """
        if not context:
            return {
                "job_type": "bootstrap_h3_docker",
                "status": "completed"
            }

        params = context.parameters
        task_results = context.task_results

        # Get the single task result
        if not task_results:
            return {
                "job_type": "bootstrap_h3_docker",
                "success": False,
                "error": "No task results available"
            }

        task = task_results[0]
        result_data = task.result_data or {}
        unwrapped = result_data.get('result', {})

        return {
            "job_type": "bootstrap_h3_docker",
            "job_id": context.job_id,
            "status": "completed",
            "grid_id_prefix": params.get('grid_id_prefix', 'land'),
            "filter_type": "country" if params.get('country_filter') else (
                "bbox" if params.get('bbox_filter') else "land"
            ),
            "filter_value": params.get('country_filter') or params.get('bbox_filter'),

            # Results from handler
            "base_cells": unwrapped.get('base_cells', 0),
            "total_cells": unwrapped.get('total_cells', 0),
            "cells_per_resolution": unwrapped.get('cells_per_resolution', {}),
            "total_batches": unwrapped.get('total_batches', 0),
            "elapsed_time": unwrapped.get('elapsed_time', 0),

            # Verification
            "verification": unwrapped.get('verification', {}),

            "metadata": {
                "workflow": "Docker single-task (base + cascade + finalize)",
                "architecture": "Checkpoint-based resume (no batch tracking table)",
                "handler": "h3_pyramid_complete",
                "processing_mode": "docker_single_stage"
            }
        }
