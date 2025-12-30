"""
H3 Land Grid Pyramid Bootstrap Job - 3-Stage Cascade Architecture.

Generates complete H3 land-filtered grid pyramid for resolutions 2-7 using
optimized 3-stage cascade approach with batched parallelism.

3-Stage Workflow:
    Stage 1: Generate filtered res 2 base (~2,000 land cells, 1 task)
    Stage 2: Cascade res 2 → res 3,4,5,6,7 (batched fan-out, N parallel tasks)
    Stage 3: Finalize pyramid (verify counts, update metadata, 1 task)

Cascade Mathematics:
    1 res 2 cell → 7^5 = 16,807 descendants to res 7
    2,000 res 2 cells → 33.6M descendants to res 7

Expected Cell Counts (land-filtered):
    Res 2: ~2,000 | Res 3: ~14,000 | Res 4: ~98,000
    Res 5: ~686,000 | Res 6: ~4.8M | Res 7: ~33.6M
    Total: ~39.2M cells

Features:
    - Batch-level idempotency (jobs can resume from partial failures)
    - Country/bbox filtering for testing (e.g., country_filter="ALB")
    - Cell-level idempotency via ON CONFLICT DO NOTHING

Exports:
    BootstrapH3LandGridPyramidJob: 3-stage cascade H3 pyramid job
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
            "task_type": "h3_generate_grid",
            "parallelism": "single",
            "description": "Generate res 2 base grid with land/country/bbox filter"
        },
        {
            "number": 2,
            "name": "cascade_descendants",
            "task_type": "h3_cascade_descendants",
            "parallelism": "fan_out",
            "description": "Cascade res 2 → res 3,4,5,6,7 (batched parallel tasks)"
        },
        {
            "number": 3,
            "name": "finalize_pyramid",
            "task_type": "h3_finalize_pyramid",
            "parallelism": "single",
            "description": "Verify cell counts and update metadata (all resolutions)"
        }
    ]

    # Declarative parameter validation (JobBaseMixin handles validation!)
    # NOTE: spatial_filter_table is auto-resolved via Promote Service (system_role='admin0_boundaries')
    # No fallback - the system dataset MUST be registered before running this job
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
    # HELPER: Dynamic Admin0 Table Lookup (23 DEC 2025)
    # ========================================================================

    @staticmethod
    def _resolve_admin0_table() -> str:
        """
        Resolve admin0 table name via Promote Service.

        Looks up the system dataset with role='admin0_boundaries'.
        FAILS EXPLICITLY if not found - no fallback to config defaults.

        This enforces the system-reserved dataset workflow:
        1. Process vector data via ETL pipeline
        2. Promote dataset with is_system_reserved=true, system_role='admin0_boundaries'
        3. Then H3 bootstrap can discover the table

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

        # Remove schema prefix if present
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
        # Dynamic admin0 table lookup via Promote Service (23 DEC 2025)
        # REQUIRES system_role='admin0_boundaries' to be registered - no fallback
        spatial_filter_table = cls._resolve_admin0_table()
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
                    "task_type": "h3_generate_grid",
                    "parameters": task_params
                }
            ]

        elif stage == 2:
            # STAGE 2: Cascade res 2 → res 3,4,5,6,7 (batched fan-out)
            # Create N parallel tasks based on parent count and batch size
            # IDEMPOTENCY: Skip batches that already completed (enables resumable jobs)

            if not previous_results or len(previous_results) == 0:
                raise ValueError("Stage 2 requires Stage 1 results")

            # Query actual parent count from database (normalized schema: h3.cells by resolution)
            from infrastructure.h3_repository import H3Repository
            h3_repo = H3Repository()
            parent_count = h3_repo.get_cell_count_by_resolution(resolution=2)

            if parent_count == 0:
                raise ValueError(f"No cells found at resolution 2 - cannot cascade")

            # Calculate number of batches
            from math import ceil
            num_batches = ceil(parent_count / cascade_batch_size)

            # IDEMPOTENCY: Query completed batches to skip them
            # This enables resumable jobs - only incomplete batches get new tasks
            from infrastructure.h3_batch_tracking import H3BatchTracker
            batch_tracker = H3BatchTracker()
            completed_batch_ids = batch_tracker.get_completed_batch_ids(job_id, stage_number=2)

            # Create fan-out tasks (one per batch), skipping completed batches
            tasks = []
            skipped_count = 0
            for batch_idx in range(num_batches):
                batch_id = f"{job_id[:8]}-s2-batch{batch_idx}"

                # Skip already completed batches (idempotency)
                if batch_id in completed_batch_ids:
                    skipped_count += 1
                    continue

                batch_start = batch_idx * cascade_batch_size

                task_params = {
                    "parent_grid_id": f"{grid_id_prefix}_res2",
                    "target_resolutions": target_resolutions,
                    "grid_id_prefix": grid_id_prefix,
                    "batch_start": batch_start,
                    "batch_size": cascade_batch_size,
                    "batch_index": batch_idx,  # For idempotency tracking
                    "source_job_id": job_id
                }

                # Pass country_code for admin0 mappings in normalized schema
                if country_filter:
                    task_params["country_code"] = country_filter

                tasks.append({
                    "task_id": batch_id,
                    "task_type": "h3_cascade_descendants",
                    "parameters": task_params
                })

            # Log idempotency status
            if skipped_count > 0:
                from util_logger import LoggerFactory, ComponentType
                logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "BootstrapH3LandGridPyramidJob")
                logger.info(
                    f"♻️  IDEMPOTENT RESUME: {skipped_count}/{num_batches} batches already complete, "
                    f"creating {len(tasks)} new tasks"
                )

            return tasks

        elif stage == 3:
            # STAGE 3: Finalize pyramid (verify counts, update metadata)
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Determine resolutions to verify (res 2 + target resolutions)
            all_resolutions = [2] + target_resolutions

            # Calculate expected cell counts DYNAMICALLY based on actual base count
            # For filtered grids (country/bbox), we can't use hardcoded global estimates
            # Use H3 multiplier: each parent has 7 children
            # Find Stage 1 result to get actual base count
            stage1_result = None
            for result in previous_results:
                if isinstance(result, dict) and result.get('result', {}).get('resolution') == 2:
                    stage1_result = result.get('result', {})
                    break

            # Get actual base cell count from Stage 1
            base_cell_count = stage1_result.get('cells_inserted', 0) if stage1_result else 0

            # Calculate expected counts dynamically if we have base count
            # H3 multiplier: 7 children per parent per resolution level
            if base_cell_count > 0:
                expected_cells = {2: base_cell_count}
                for res in target_resolutions:
                    # Each res N cell has 7 children at res N+1
                    # Cumulative from res 2: 7^(res-2) multiplier
                    multiplier = 7 ** (res - 2)
                    expected_cells[res] = base_cell_count * multiplier
            else:
                # Fallback to global estimates if base count unknown
                expected_cells = {k: v for k, v in BootstrapH3LandGridPyramidJob.EXPECTED_CELLS.items() if k in all_resolutions}

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-finalize",
                    "task_type": "h3_finalize_pyramid",
                    "parameters": {
                        "grid_id_prefix": grid_id_prefix,
                        "resolutions": all_resolutions,
                        "expected_cells": expected_cells,
                        "source_job_id": job_id,
                        "base_cell_count": base_cell_count  # Pass for logging/debugging
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
            # Stage 2 results are cascade tasks (task_type = "h3_cascade_descendants")
            stage2_results = [tr for tr in task_results if tr.task_type == "h3_cascade_descendants"]
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
                "cascade_handler": "h3_cascade_descendants (multi-level)",
                "pattern": "JobBaseMixin (77% less boilerplate)",
                "performance": f"Batched fan-out with {cascade_batch_size} parents per task"
            }
        }
