"""
Process Fathom Stack Job - Phase 1: Band Stacking.

Phase 1 of Two-Phase Fathom ETL Architecture:
    - Input: 8M single-band 1×1 tiles
    - Output: 1M multi-band 1×1 COGs
    - Memory: ~500MB per task

Stacks 8 return period files for each tile+scenario combination.
Phase 2 (process_fathom_merge) handles spatial merging.

Exports:
    ProcessFathomStackJob: Job class for band stacking operations
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config import FathomDefaults


class ProcessFathomStackJob(JobBaseMixin, JobBase):
    """
    Fathom Phase 1: Band stacking workflow.

    Stacks 8 return period files into single multi-band COGs.
    No spatial merging - preserves original 1×1 tile grid.

    Stages:
    1. tile_inventory: Group files by tile + scenario
    2. band_stack: Stack 8 RPs into multi-band COG (fan-out, ~500MB/task)
    3. stac_register: Create STAC items in pgstac
    """

    job_type: str = "process_fathom_stack"
    description: str = "Stack Fathom return periods into multi-band COGs (Phase 1)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "tile_inventory",
            "task_type": "fathom_tile_inventory",
            "description": "Group files by tile + scenario (not country-wide)",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "band_stack",
            "task_type": "fathom_band_stack",
            "description": "Fan-out: Stack 8 return periods into multi-band COG",
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
            "description": "Bounding box [west, south, east, north] in EPSG:4326 to filter tiles spatially"
        },
        "source_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.SOURCE_CONTAINER,
            "description": "Source container with Fathom flood tiles (used for inventory lookup)"
        },
        "output_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE1_OUTPUT_CONTAINER,
            "description": "Output container for stacked COGs"
        },
        "output_prefix": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE1_OUTPUT_PREFIX,
            "description": "Output folder prefix (Phase 1 output location)"
        },
        "flood_types": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Filter: List of flood types to process (e.g., ['COASTAL_DEFENDED'])"
        },
        "years": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Filter: List of years to process (e.g., [2020])"
        },
        "ssp_scenarios": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Filter: List of SSP scenarios (e.g., ['SSP2_4.5'])"
        },
        "collection_id": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE1_COLLECTION_ID,
            "description": "STAC collection ID for Phase 1 outputs"
        },
        "skip_existing_stac": {
            "type": "bool",
            "required": False,
            "default": True,
            "description": "If True, skip tiles already registered in STAC (STAC-driven idempotency)"
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

        Stage 1: Single inventory task - group by tile + scenario
        Stage 2: Fan-out - one task per tile group (~500MB each)
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
            # Stage 1: Tile inventory (queries app.etl_fathom database)
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "fathom_tile_inventory",
                "parameters": {
                    "region_code": job_params["region_code"],
                    "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                    "flood_types": job_params.get("flood_types"),
                    "years": job_params.get("years"),
                    "ssp_scenarios": job_params.get("ssp_scenarios"),
                    "bbox": job_params.get("bbox"),  # Spatial filter
                    "collection_id": job_params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out band stacking
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 1 failed - no inventory created")

            stage1_result = previous_results[0]["result"]
            tile_groups = stage1_result.get("tile_groups", [])

            if not tile_groups:
                raise ValueError("Stage 1 returned no tile groups")

            # Check for dry run
            if job_params.get("dry_run", False):
                return []

            # Create one task per tile group
            tasks = []
            for idx, group in enumerate(tile_groups):
                output_name = group["output_name"]
                task_id = f"{job_id[:8]}-s2-{idx:04d}-{group['tile']}"

                tasks.append({
                    "task_id": task_id,
                    "task_type": "fathom_band_stack",
                    "parameters": {
                        "tile_group": group,
                        "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                        "output_container": job_params.get("output_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER),
                        "output_prefix": job_params.get("output_prefix", FathomDefaults.PHASE1_OUTPUT_PREFIX),
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
                            "collection_id": job_params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID)
                        }
                    }]
                raise ValueError("Stage 2 failed - no COGs created")

            successful_cogs = [
                r["result"]
                for r in previous_results
                if r.get("success") and r.get("result")
            ]

            if not successful_cogs and not job_params.get("dry_run", False):
                raise ValueError("Stage 2 failed - no successful COGs")

            return [{
                "task_id": f"{job_id[:8]}-s3-stac",
                "task_type": "fathom_stac_register",
                "parameters": {
                    "cog_results": successful_cogs,
                    "region_code": job_params["region_code"],
                    "collection_id": job_params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID),
                    "output_container": job_params.get("output_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER)
                }
            }]

        else:
            raise ValueError(f"Invalid stage: {stage}. ProcessFathomStackJob has 3 stages.")

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "process_fathom_stack",
                "phase": 1
            }

        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "ProcessFathomStackJob.finalize_job"
        )

        task_results = context.task_results
        params = context.parameters

        # Extract inventory summary (Stage 1)
        inventory_tasks = [t for t in task_results if t.task_type == "fathom_tile_inventory"]
        inventory_summary = {}
        if inventory_tasks and inventory_tasks[0].result_data:
            inv_result = inventory_tasks[0].result_data.get("result", {})
            inventory_summary = {
                "total_source_files": inv_result.get("total_files", 0),
                "unique_tiles": inv_result.get("unique_tiles", 0),
                "tile_groups": inv_result.get("tile_group_count", 0),
                "flood_types": inv_result.get("flood_types", []),
                "years": inv_result.get("years", [])
            }

        # Extract band stacking summary (Stage 2)
        stack_tasks = [t for t in task_results if t.task_type == "fathom_band_stack"]
        successful = [t for t in stack_tasks if t.result_data and t.result_data.get("success")]
        skipped = [t for t in stack_tasks if t.result_data and t.result_data.get("skipped")]
        failed = [t for t in stack_tasks if t.result_data and not t.result_data.get("success")]

        stack_summary = {
            "total_tasks": len(stack_tasks),
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

        summary = {
            "status": "completed",
            "job_type": "process_fathom_stack",
            "phase": 1,
            "region_code": params.get("region_code"),
            "dry_run": params.get("dry_run", False),
            "inventory": inventory_summary,
            "band_stacking": stack_summary,
            "stac_registration": stac_summary,
            "reduction": f"{inventory_summary.get('total_source_files', 0)} → {stack_summary.get('successful', 0)} files (8× reduction)"
        }

        logger.info(f"✅ Phase 1 complete: {summary['reduction']}")

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
