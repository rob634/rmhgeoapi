# ============================================================================
# PROCESS FATHOM MERGE JOB
# ============================================================================
# STATUS: Jobs - Phase 2 Fathom spatial merge workflow
# PURPOSE: Merge NxN stacked tiles into consolidated COGs (~40K outputs)
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Process Fathom Merge Job - Phase 2: Spatial Merge.

Phase 2 of Two-Phase Fathom ETL Architecture:
    - Input: 1M multi-band 1×1 COGs from Phase 1
    - Output: 40K merged COGs with configurable grid size
    - Memory: ~2-3GB per task (band-by-band processing)

Exports:
    ProcessFathomMergeJob: Job class for spatial merge operations
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config import FathomDefaults


class ProcessFathomMergeJob(JobBaseMixin, JobBase):
    """
    Fathom Phase 2: Spatial merge workflow.

    Merges NxN stacked tiles into larger consolidated COGs.
    Uses band-by-band processing for memory efficiency.

    Stages:
    1. grid_inventory: Group Phase 1 outputs by NxN grid cell
    2. spatial_merge: Merge tiles band-by-band (fan-out, ~2-3GB/task)
    3. stac_register: Create STAC items in pgstac
    """

    job_type: str = "process_fathom_merge"
    description: str = "Merge Fathom tiles into NxN grid cells (Phase 2)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "grid_inventory",
            "task_type": "fathom_grid_inventory",
            "description": "Group Phase 1 outputs by NxN grid cell",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "spatial_merge",
            "task_type": "fathom_spatial_merge",
            "description": "Fan-out: Merge NxN tiles band-by-band",
            "parallelism": "fan_out"
        },
        {
            "number": 3,
            "name": "stac_register",
            "task_type": "fathom_stac_register",
            "description": "Fan-in: Create STAC collection and items",
            "parallelism": "fan_in"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "region_code": {
            "type": "str",
            "required": True,
            "description": "ISO 3166-1 alpha-2 country code (e.g., 'CI' for Côte d'Ivoire)"
        },
        "bbox": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Bounding box [west, south, east, north] in EPSG:4326 to filter grid cells spatially"
        },
        "grid_size": {
            "type": "int",
            "required": False,
            "default": FathomDefaults.DEFAULT_GRID_SIZE,
            "min": 2,
            "max": 10,
            "description": "Grid cell size in degrees (5 = 5×5 merge, 4 = 4×4 merge)"
        },
        "source_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE1_OUTPUT_CONTAINER,
            "description": "Container with Phase 1 stacked COGs"
        },
        "source_prefix": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE1_OUTPUT_PREFIX,
            "description": "Folder prefix for Phase 1 outputs"
        },
        "output_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE2_OUTPUT_CONTAINER,
            "description": "Output container for merged COGs"
        },
        "output_prefix": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE2_OUTPUT_PREFIX,
            "description": "Output folder prefix for Phase 2 outputs"
        },
        "collection_id": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE2_COLLECTION_ID,
            "description": "STAC collection ID for Phase 2 outputs"
        },
        "skip_existing_stac": {
            "type": "bool",
            "required": False,
            "default": True,
            "description": "If True, skip grid cells already registered in STAC (STAC-driven idempotency)"
        },
        "dry_run": {
            "type": "bool",
            "required": False,
            "default": False,
            "description": "If True, only create inventory without processing"
        },
        "force_reprocess": {
            "type": "bool",
            "required": False,
            "default": False,
            "description": "If True, reprocess even if output COG exists (idempotency override)"
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
        Generate tasks for each stage.

        Stage 1: Single inventory task - group by NxN grid cell
        Stage 2: Fan-out - one task per grid group (~2-3GB each)
        Stage 3: Fan-in - single STAC registration task

        Args:
            stage: Current stage (1-3)
            job_params: Job parameters
            job_id: Job ID for task generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        region_code = job_params["region_code"].lower()

        if stage == 1:
            # Stage 1: Grid inventory
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "fathom_grid_inventory",
                "parameters": {
                    "region_code": job_params["region_code"],
                    "grid_size": job_params.get("grid_size", FathomDefaults.DEFAULT_GRID_SIZE),
                    "source_container": job_params.get("source_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER),
                    "source_prefix": job_params.get("source_prefix", FathomDefaults.PHASE1_OUTPUT_PREFIX),
                    "bbox": job_params.get("bbox"),  # Spatial filter
                    "collection_id": job_params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID),
                    "skip_existing_stac": job_params.get("skip_existing_stac", True)
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out spatial merge
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 1 failed - no grid inventory created")

            stage1_result = previous_results[0]["result"]
            grid_groups = stage1_result.get("grid_groups", [])

            if not grid_groups:
                raise ValueError("Stage 1 returned no grid groups (no Phase 1 outputs found?)")

            # Check for dry run
            if job_params.get("dry_run", False):
                return []

            # Create one task per grid group
            tasks = []
            for idx, group in enumerate(grid_groups):
                grid_cell = group["grid_cell"]
                task_id = f"{job_id[:8]}-s2-{idx:04d}-{grid_cell[:15]}"

                tasks.append({
                    "task_id": task_id,
                    "task_type": "fathom_spatial_merge",
                    "parameters": {
                        "grid_group": group,
                        "source_container": job_params.get("source_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER),
                        "output_container": job_params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER),
                        "output_prefix": job_params.get("output_prefix", FathomDefaults.PHASE2_OUTPUT_PREFIX),
                        "region_code": job_params["region_code"],
                        "force_reprocess": job_params.get("force_reprocess", False),
                        "job_id": job_id  # For tracking in app.etl_fathom
                    }
                })

            return tasks

        elif stage == 3:
            # Stage 3: Fan-in STAC registration
            if not previous_results:
                if job_params.get("dry_run", False):
                    return [{
                        "task_id": f"{job_id[:8]}-s3-stac-dryrun",
                        "task_type": "fathom_stac_register",
                        "parameters": {
                            "dry_run": True,
                            "region_code": job_params["region_code"],
                            "collection_id": job_params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID)
                        }
                    }]
                raise ValueError("Stage 2 failed - no merged COGs created")

            successful_cogs = [
                r["result"]
                for r in previous_results
                if r.get("success") and r.get("result")
            ]

            if not successful_cogs and not job_params.get("dry_run", False):
                raise ValueError("Stage 2 failed - no successful merges")

            # Pass job_id instead of cog_results to avoid Service Bus 256KB limit
            # The handler will query the database for Stage 2 task results
            return [{
                "task_id": f"{job_id[:8]}-s3-stac",
                "task_type": "fathom_stac_register",
                "parameters": {
                    "job_id": job_id,
                    "stage": 2,  # Query Stage 2 results
                    "cog_count": len(successful_cogs),  # For validation
                    "region_code": job_params["region_code"],
                    "collection_id": job_params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID),
                    "output_container": job_params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER)
                }
            }]

        else:
            raise ValueError(f"Invalid stage: {stage}. ProcessFathomMergeJob has 3 stages.")

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "process_fathom_merge",
                "phase": 2
            }

        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "ProcessFathomMergeJob.finalize_job"
        )

        task_results = context.task_results
        params = context.parameters

        # Extract inventory summary (Stage 1)
        inventory_tasks = [t for t in task_results if t.task_type == "fathom_grid_inventory"]
        inventory_summary = {}
        if inventory_tasks and inventory_tasks[0].result_data:
            inv_result = inventory_tasks[0].result_data.get("result", {})
            inventory_summary = {
                "grid_size": inv_result.get("grid_size", FathomDefaults.DEFAULT_GRID_SIZE),
                "unique_grid_cells": inv_result.get("unique_grid_cells", 0),
                "grid_groups": inv_result.get("grid_group_count", 0),
                "total_source_tiles": inv_result.get("total_tiles", 0)
            }

        # Extract merge summary (Stage 2)
        merge_tasks = [t for t in task_results if t.task_type == "fathom_spatial_merge"]
        successful = [t for t in merge_tasks if t.result_data and t.result_data.get("success")]
        skipped = [t for t in merge_tasks if t.result_data and t.result_data.get("skipped")]
        failed = [t for t in merge_tasks if t.result_data and not t.result_data.get("success")]

        merge_summary = {
            "total_tasks": len(merge_tasks),
            "successful": len(successful),
            "skipped": len(skipped),
            "processed": len(successful) - len(skipped),
            "failed": len(failed)
        }

        # Extract STAC summary (Stage 3)
        stac_tasks = [t for t in task_results if t.task_type == "fathom_stac_register"]
        stac_summary = {}
        if stac_tasks and stac_tasks[0].result_data:
            stac_result = stac_tasks[0].result_data.get("result", {})
            stac_summary = {
                "collection_id": stac_result.get("collection_id"),
                "items_created": stac_result.get("items_created", 0)
            }

        grid_size = inventory_summary.get("grid_size", FathomDefaults.DEFAULT_GRID_SIZE)
        summary = {
            "status": "completed",
            "job_type": "process_fathom_merge",
            "phase": 2,
            "region_code": params.get("region_code"),
            "grid_size": grid_size,
            "dry_run": params.get("dry_run", False),
            "inventory": inventory_summary,
            "spatial_merge": merge_summary,
            "stac_registration": stac_summary,
            "reduction": f"{inventory_summary.get('total_source_tiles', 0)} tiles → {merge_summary.get('successful', 0)} COGs ({grid_size}×{grid_size} merge)"
        }

        logger.info(f"✅ Phase 2 complete: {summary['reduction']}")

        return summary

    @classmethod
    def generate_job_id(cls, params: dict) -> str:
        """Generate deterministic job ID from parameters."""
        # Exclude testing/control parameters from hash
        hash_params = {k: v for k, v in params.items() if k not in ('dry_run', 'force_reprocess')}

        canonical = json.dumps({
            'job_type': cls.job_type,
            **hash_params
        }, sort_keys=True)

        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
