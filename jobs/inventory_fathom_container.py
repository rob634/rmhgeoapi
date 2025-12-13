"""
Inventory Fathom Container Job.

Scans the bronze-fathom container and populates the etl_fathom tracking table.
Enables database-driven processing instead of CSV file parsing.

Parallelization Strategy:
    - Stage 1: Generate ~80 scan prefixes
    - Stage 2: Parallel scan (one task per prefix)
    - Stage 3: Assign grid cells for phase 2 grouping
    - Stage 4: Generate summary statistics

Exports:
    InventoryFathomContainerJob: Main job class for Fathom inventory
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config import FathomDefaults


class InventoryFathomContainerJob(JobBaseMixin, JobBase):
    """
    Fathom Container Inventory Job.

    Scans bronze-fathom container and populates etl_fathom table.
    Parallelizes by blob path prefix for efficient scanning.

    Stages:
    1. generate_prefixes: Create list of prefixes to scan
    2. scan_prefix: Parallel scan + batch insert (fan-out)
    3. assign_grid_cells: Calculate grid cell assignments
    4. generate_summary: Summarize inventory results
    """

    job_type: str = "inventory_fathom_container"
    description: str = "Scan Fathom container and populate ETL tracking table"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "generate_prefixes",
            "task_type": "fathom_generate_scan_prefixes",
            "description": "Generate list of blob prefixes to scan in parallel",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "scan_prefix",
            "task_type": "fathom_scan_prefix",
            "description": "Fan-out: Scan blobs by prefix and insert to database",
            "parallelism": "fan_out"
        },
        {
            "number": 3,
            "name": "assign_grid_cells",
            "task_type": "fathom_assign_grid_cells",
            "description": "Calculate 5×5 degree grid cell assignments",
            "parallelism": "single"
        },
        {
            "number": 4,
            "name": "generate_summary",
            "task_type": "fathom_inventory_summary",
            "description": "Generate inventory statistics summary",
            "parallelism": "single"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "source_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.SOURCE_CONTAINER,
            "description": "Container to inventory (default: bronze-fathom)"
        },
        "flood_types": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Filter: List of flood types to inventory (default: all)"
        },
        "years": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Filter: List of years to inventory (default: all)"
        },
        "ssp_scenarios": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "Filter: List of SSP scenarios (default: all)"
        },
        "batch_size": {
            "type": "int",
            "required": False,
            "default": 1000,
            "min": 100,
            "max": 10000,
            "description": "Batch size for database inserts"
        },
        "grid_size": {
            "type": "int",
            "required": False,
            "default": 5,
            "min": 1,
            "max": 30,
            "description": "Grid cell size in degrees for phase 2 grouping"
        },
        "dry_run": {
            "type": "bool",
            "required": False,
            "default": False,
            "description": "If True, count files but don't insert to database"
        }
    }

    # =========================================================================
    # Flood Types and SSP Scenarios for Prefix Generation
    # =========================================================================
    FLOOD_TYPES = [
        "COASTAL_DEFENDED",
        "COASTAL_UNDEFENDED",
        "FLUVIAL_DEFENDED",
        "FLUVIAL_UNDEFENDED",
        "PLUVIAL_DEFENDED"
    ]

    YEARS = [2020, 2030, 2050, 2080]

    SSP_SCENARIOS = ["SSP1_2.6", "SSP2_4.5", "SSP3_7.0", "SSP5_8.5"]

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate tasks for each stage of the inventory job.

        Stage 1 (generate_prefixes): Single task to generate prefix list
        Stage 2 (scan_prefix): One task per prefix (parallel)
        Stage 3 (assign_grid_cells): Single task to update grid assignments
        Stage 4 (generate_summary): Single task for statistics

        Args:
            stage: Stage number (int) per JobBase contract
            job_params: Job parameters
            job_id: Job ID for task generation
            previous_results: Results from previous stage
        """
        # Look up stage definition from class attribute
        stage_def = next(
            (s for s in InventoryFathomContainerJob.stages if s["number"] == stage),
            None
        )
        if not stage_def:
            raise ValueError(f"Invalid stage number: {stage}")

        stage_name = stage_def["name"]
        task_type = stage_def["task_type"]
        job_short = job_id[:8]

        if stage_name == "generate_prefixes":
            # Stage 1: Generate list of prefixes to scan
            return [{
                "task_id": f"{job_short}-s{stage}-prefixes",
                "task_type": task_type,
                "parameters": {
                    "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                    "flood_types": job_params.get("flood_types"),
                    "years": job_params.get("years"),
                    "ssp_scenarios": job_params.get("ssp_scenarios"),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        elif stage_name == "scan_prefix":
            # Stage 2: Create one task per prefix from stage 1 results
            if not previous_results:
                return []

            # Get prefixes from stage 1 result
            stage1_result = previous_results[0] if previous_results else {}
            prefixes = stage1_result.get("result", {}).get("prefixes", [])

            if not prefixes:
                return []

            tasks = []
            for i, prefix in enumerate(prefixes):
                tasks.append({
                    "task_id": f"{job_short}-s{stage}-p{i:03d}",
                    "task_type": task_type,
                    "parameters": {
                        "prefix": prefix,
                        "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                        "batch_size": job_params.get("batch_size", 1000),
                        "dry_run": job_params.get("dry_run", False)
                    }
                })
            return tasks

        elif stage_name == "assign_grid_cells":
            # Stage 3: Single task to update grid cell assignments
            return [{
                "task_id": f"{job_short}-s{stage}-grid",
                "task_type": task_type,
                "parameters": {
                    "grid_size": job_params.get("grid_size", 5),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        elif stage_name == "generate_summary":
            # Stage 4: Single task for summary statistics
            return [{
                "task_id": f"{job_short}-s{stage}-summary",
                "task_type": task_type,
                "parameters": {
                    "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        return []

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Finalize the inventory job.

        Returns summary of inventory results from stage 4.

        Args:
            context: JobExecutionContext object (not dict) containing:
                - job_id, job_type, parameters
                - task_results: List of TaskRecord objects
                - stage_results: Dict of stage results
        """
        if not context:
            return {
                "status": "completed",
                "job_type": "inventory_fathom_container",
                "message": "Fathom container inventory completed"
            }

        # Access task_results from context object (not dict)
        task_results = context.task_results if hasattr(context, 'task_results') else []

        # Find summary task result (Stage 4: fathom_inventory_summary)
        summary = {}
        for task in task_results:
            task_type = task.task_type if hasattr(task, 'task_type') else task.get('task_type', '')
            if task_type == "fathom_inventory_summary":
                result_data = task.result_data if hasattr(task, 'result_data') else task.get('result_data', {})
                if result_data:
                    summary = result_data.get("result", {}) if isinstance(result_data, dict) else {}
                break

        return {
            "status": "completed",
            "job_type": "inventory_fathom_container",
            "message": "Fathom container inventory completed",
            "summary": summary
        }

    @staticmethod
    def generate_job_id(params: Dict[str, Any]) -> str:
        """
        Generate deterministic job ID for idempotency.

        Excludes dry_run from hash so re-runs can use force.
        """
        # Create stable hash from significant parameters
        hash_params = {
            "job_type": "inventory_fathom_container",
            "source_container": params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
            "flood_types": sorted(params.get("flood_types") or []),
            "years": sorted(params.get("years") or []),
            "ssp_scenarios": sorted(params.get("ssp_scenarios") or [])
        }

        param_str = json.dumps(hash_params, sort_keys=True)
        return hashlib.sha256(param_str.encode()).hexdigest()
