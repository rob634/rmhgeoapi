# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - H3 Land Grid Pyramid Bootstrap (3-stage cascade workflow)
# PURPOSE: Generate complete H3 land-filtered grid pyramid from resolution 2-7
# LAST_REVIEWED: 15 NOV 2025
# EXPORTS: BootstrapH3LandGridPyramidJob (JobBase + JobBaseMixin implementation)
# INTERFACES: JobBase (2 methods), JobBaseMixin (provides 4 methods)
# PYDANTIC_MODELS: Uses declarative parameters_schema
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin, services.handler_generate_h3_grid, services.handler_cascade_h3_descendants
# SOURCE: HTTP job submission for H3 bootstrap workflow
# SCOPE: Land-filtered H3 grids for World Bank Agricultural Geography Platform
# VALIDATION: Declarative schema via JobBaseMixin
# PATTERNS: Mixin pattern (composition over inheritance), 3-stage cascade, Batched fan-out, DRY architecture
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "bootstrap_h3_land_grid_pyramid"
# INDEX: BootstrapH3LandGridPyramidJob:60, stages:108, parameters_schema:135, create_tasks_for_stage:180
# ============================================================================

"""
H3 Land Grid Pyramid Bootstrap Job - 3-Stage Cascade Architecture

Generates complete H3 land-filtered grid pyramid for resolutions 2-7 using
optimized 3-stage cascade approach with batched parallelism.

Architecture Optimization (15 NOV 2025):
    OLD: 7 stages (res 2, then res 3, 4, 5, 6, 7 sequentially) → 30+ minute timeout
    NEW: 3 stages (res 2 base, cascade ALL descendants res 3-7, finalize) → <15 minutes

3-Stage Workflow:
    Stage 1: Generate filtered res 2 base (~2,000 land cells, 1 task)
    Stage 2: Cascade res 2 → res 3,4,5,6,7 (batched fan-out, N parallel tasks)
    Stage 3: Finalize pyramid (verify counts, update metadata, 1 task)

Cascade Mathematics:
    1 res 2 cell → 7^5 = 16,807 descendants to res 7
    10 res 2 cells → 168,070 descendants to res 7
    2,000 res 2 cells → 33.6M descendants to res 7

Batching Strategy:
    - Configurable batch size (default: 10 parent cells per task)
    - 2,000 parents ÷ 10 = 200 parallel tasks in Stage 2
    - Each task: 10 parents × 16,807 descendants = 168,070 cells
    - Memory: ~33.6 MB per task (well within Azure Functions limits)

Expected Cell Counts (land-filtered, approximate):
    Res 2: ~2,000 cells (base)
    Res 3: ~14,000 cells (7^1 multiplier)
    Res 4: ~98,000 cells (7^2 multiplier)
    Res 5: ~686,000 cells (7^3 multiplier)
    Res 6: ~4.8M cells (7^4 multiplier)
    Res 7: ~33.6M cells (7^5 multiplier)
    Total: ~39.2M cells

Albania Test Support:
    - Parameter: country_filter="ALB" (ISO3 country code)
    - Parameter: bbox_filter=[19.3, 39.6, 21.1, 42.7]
    - Expected: ~10-20 res 2 cells → ~168K res 7 cells
    - Success Criteria: Complete in <15 minutes with correct parent relationships

Author: Robert and Geospatial Claude Legion
Date: 14 NOV 2025
Last Updated: 15 NOV 2025 - Redesigned for 3-stage cascade architecture
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class BootstrapH3LandGridPyramidJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    H3 Land Grid Pyramid Bootstrap - 3-stage cascade job.

    Stage 1: Generate filtered res 2 base (1 task)
    Stage 2: Cascade res 2 → res 3,4,5,6,7 (batched fan-out)
    Stage 3: Finalize pyramid (1 task)

    JobBaseMixin provides: validate_job_parameters, generate_job_id, create_job_record, queue_job
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================

    # Job metadata
    job_type: str = "bootstrap_h3_land_grid_pyramid"
    description: str = "Generate H3 land-filtered grid pyramid (res 2-7) - 3-STAGE CASCADE"

    # 3-stage workflow using cascade handler (OPTIMIZED ARCHITECTURE)
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "generate_res2_base",
            "task_type": "generate_h3_grid",
            "parallelism": "single",
            "description": "Generate res 2 base grid with land/country/bbox filter"
        },
        {
            "number": 2,
            "name": "cascade_descendants",
            "task_type": "cascade_h3_descendants",
            "parallelism": "fan_out",
            "description": "Cascade res 2 → res 3,4,5,6,7 (batched parallel tasks)"
        },
        {
            "number": 3,
            "name": "finalize_pyramid",
            "task_type": "finalize_h3_pyramid",
            "parallelism": "single",
            "description": "Verify cell counts and update metadata (all resolutions)"
        }
    ]

    # Declarative parameter validation (JobBaseMixin handles validation!)
    parameters_schema: Dict[str, Any] = {
        'spatial_filter_table': {
            'type': 'str',
            'default': 'system_admin0',
            'description': 'PostGIS table name for land filtering (without schema prefix)'
        },
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
        'cascade_batch_size': {
            'type': 'int',
            'default': 10,
            'min': 1,
            'max': 100,
            'description': 'Number of parent cells per cascade task (10 parents = ~168K descendants to res 7)'
        },
        'target_resolutions': {
            'type': 'list',
            'default': [3, 4, 5, 6, 7],
            'description': 'Target resolutions for cascade (default: 3-7)'
        }
    }

    # Expected cell counts for validation (approximate, land-filtered)
    EXPECTED_CELLS = {
        2: 2000,      # Base filtered grid
        3: 14000,     # 7^1 multiplier
        4: 98000,     # 7^2 multiplier
        5: 686000,    # 7^3 multiplier
        6: 4800000,   # 7^4 multiplier
        7: 33600000,  # 7^5 multiplier
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
        Generate task parameters for each stage of H3 bootstrap workflow.

        3-stage workflow:
            Stage 1: Generate res 2 with spatial filter (1 task, base generation)
            Stage 2: Cascade res 2 → res 3,4,5,6,7 (batched fan-out, N tasks)
            Stage 3: Finalize pyramid (1 task, verification)

        Args:
            stage: Stage number (1-3)
            job_params: Job parameters (spatial_filter_table, grid_id_prefix, country_filter, bbox_filter, cascade_batch_size)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage tasks

        Returns:
            List of task dicts for current stage

        Raises:
            ValueError: Invalid stage number or missing previous results
        """
        spatial_filter_table = job_params.get('spatial_filter_table', 'system_admin0')
        grid_id_prefix = job_params.get('grid_id_prefix', 'land')
        country_filter = job_params.get('country_filter')
        bbox_filter = job_params.get('bbox_filter')
        cascade_batch_size = job_params.get('cascade_batch_size', 10)
        target_resolutions = job_params.get('target_resolutions', [3, 4, 5, 6, 7])

        if stage == 1:
            # STAGE 1: Generate res 2 with spatial filter (base generation)
            # Supports country filter (e.g., "ALB") and bbox filter for testing
            task_params = {
                "resolution": 2,
                "grid_id": f"{grid_id_prefix}_res2",
                "grid_type": "land",
                "source_job_id": job_id,
                "use_cascade": False,  # Base generation
                "filter_mode": "intersects"
            }

            # Add spatial filter (country, bbox, or default land table)
            if country_filter:
                # Country filter: Use WHERE clause in spatial_filter_table
                task_params["spatial_filter_table"] = f"geo.{spatial_filter_table}"
                task_params["country_code"] = country_filter  # Pass to handler for WHERE clause
            elif bbox_filter:
                # Bbox filter: Use bounding box
                task_params["spatial_filter_bbox"] = bbox_filter
            else:
                # Default: Filter by all land
                task_params["spatial_filter_table"] = f"geo.{spatial_filter_table}"

            return [
                {
                    "task_id": f"{job_id[:8]}-s1-res2-base",
                    "task_type": "generate_h3_grid",
                    "parameters": task_params
                }
            ]

        elif stage == 2:
            # STAGE 2: Cascade res 2 → res 3,4,5,6,7 (batched fan-out)
            # Create N parallel tasks based on parent count and batch size

            if not previous_results or len(previous_results) == 0:
                raise ValueError("Stage 2 requires Stage 1 results")

            # Extract parent count from Stage 1 result
            stage1_result = previous_results[0].get('result', {})
            rows_inserted = stage1_result.get('rows_inserted', 0)

            if rows_inserted == 0:
                raise ValueError("Stage 1 inserted 0 cells - cannot cascade")

            # Calculate number of batches
            from math import ceil
            num_batches = ceil(rows_inserted / cascade_batch_size)

            # Create fan-out tasks (one per batch)
            tasks = []
            for batch_idx in range(num_batches):
                batch_start = batch_idx * cascade_batch_size

                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-batch{batch_idx}",
                    "task_type": "cascade_h3_descendants",
                    "parameters": {
                        "parent_grid_id": f"{grid_id_prefix}_res2",
                        "target_resolutions": target_resolutions,
                        "grid_id_prefix": grid_id_prefix,
                        "batch_start": batch_start,
                        "batch_size": cascade_batch_size,
                        "source_job_id": job_id
                    }
                })

            return tasks

        elif stage == 3:
            # STAGE 3: Finalize pyramid (verify counts, update metadata)
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Determine resolutions to verify (res 2 + target resolutions)
            all_resolutions = [2] + target_resolutions

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-finalize",
                    "task_type": "finalize_h3_pyramid",
                    "parameters": {
                        "grid_id_prefix": grid_id_prefix,
                        "resolutions": all_resolutions,
                        "expected_cells": {k: v for k, v in BootstrapH3LandGridPyramidJob.EXPECTED_CELLS.items() if k in all_resolutions},
                        "source_job_id": job_id
                    }
                }
            ]

        else:
            raise ValueError(f"Invalid stage {stage} for bootstrap_h3_land_grid_pyramid job (valid: 1-3)")

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary with pyramid statistics.

        3-stage workflow summary:
        - Stage 1: Base generation (res 2 with spatial filter)
        - Stage 2: Cascade generation (res 3-7 from res 2 parents)
        - Stage 3: Finalization and verification

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
        country_filter = params.get('country_filter')
        cascade_batch_size = params.get('cascade_batch_size', 10)
        target_resolutions = params.get('target_resolutions', [3, 4, 5, 6, 7])

        # Extract results from all stages (3 stages total)
        task_results = context.task_results

        # Build resolution stats from Stage 3 finalization result
        resolution_stats = {}
        total_cells = 0

        if len(task_results) >= 3:
            finalization_result = task_results[2].result_data.get("result", {}) if task_results[2].result_data else {}
            total_cells = finalization_result.get("total_cells", 0)

            # Extract per-resolution stats from finalization verification
            verification_details = finalization_result.get("verification_details", {})
            per_resolution = verification_details.get("per_resolution", {})

            for res, res_data in per_resolution.items():
                resolution_stats[f"res{res}"] = {
                    "cells": res_data.get("actual_count", 0),
                    "grid_id": res_data.get("grid_id", f"{grid_id_prefix}_res{res}")
                }

        # Extract cascade statistics from Stage 2
        cascade_stats = {}
        if len(task_results) >= 2:
            # Stage 2 results are list of task results (one per batch)
            stage2_results = [tr for tr in task_results if tr.stage == 2]
            cascade_stats = {
                "batches_completed": len(stage2_results),
                "batch_size": cascade_batch_size,
                "target_resolutions": target_resolutions
            }

        # Determine filter type
        filter_type = "country" if country_filter else ("bbox" if params.get('bbox_filter') else "land")
        filter_value = country_filter if country_filter else (params.get('bbox_filter') if params.get('bbox_filter') else spatial_filter)

        logger.info(f"✅ Job {context.job_id} completed: H3 Pyramid ({total_cells:,} total cells)")

        return {
            "job_type": "bootstrap_h3_land_grid_pyramid",
            "job_id": context.job_id,
            "status": "completed",
            "grid_id_prefix": grid_id_prefix,
            "filter_type": filter_type,
            "filter_value": filter_value,
            "total_cells": total_cells,
            "resolution_stats": resolution_stats,
            "cascade_stats": cascade_stats,
            "metadata": {
                "workflow": "3-stage cascade (base + batched descendants + finalize)",
                "architecture": "Optimized cascade (res 2 → res 3-7 in parallel batches)",
                "cascade_handler": "cascade_h3_descendants (multi-level)",
                "pattern": "JobBaseMixin (77% less boilerplate)",
                "performance": f"Batched fan-out with {cascade_batch_size} parents per task"
            }
        }
