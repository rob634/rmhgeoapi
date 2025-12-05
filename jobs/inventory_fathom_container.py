# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - FATHOM CONTAINER INVENTORY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job workflow - Inventory Fathom container to database
# PURPOSE: Scan bronze-fathom container and populate etl_fathom tracking table
# LAST_REVIEWED: 05 DEC 2025
# EXPORTS: InventoryFathomContainerJob class
# INTERFACES: JobBase contract, JobBaseMixin for boilerplate elimination
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin
# SOURCE: bronze-fathom container (Fathom Global Flood Maps v3)
# SCOPE: Full container scan - 8M files inventoried to database
# VALIDATION: Declarative schema via JobBaseMixin
# PATTERNS: Mixin pattern, parallel scan by prefix, batch database inserts
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "inventory_fathom_container"
# INDEX: InventoryFathomContainerJob:35, stages:55, parameters_schema:70, create_tasks_for_stage:110
# ============================================================================

"""
Inventory Fathom Container Job

Scans the bronze-fathom container and populates the app.etl_fathom tracking table.
This enables database-driven processing instead of CSV file parsing.

Parallelization Strategy:
- Stage 1: Generate ~80 scan prefixes (5 flood_types × 4 years × 4 SSPs)
- Stage 2: Parallel scan (one task per prefix, ~8 parallel inserts)
- Stage 3: Assign grid cells for phase 2 grouping
- Stage 4: Generate summary statistics

Benefits:
- Ground truth from actual blob storage (not CSV)
- Idempotent (ON CONFLICT DO UPDATE)
- Enables resumable processing
- SQL-queryable progress tracking

Author: Robert and Geospatial Claude Legion
Date: 05 DEC 2025
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
        stage: Dict[str, Any],
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
        """
        stage_num = stage["number"]
        stage_name = stage["name"]
        task_type = stage["task_type"]
        job_short = job_id[:8]

        if stage_name == "generate_prefixes":
            # Stage 1: Generate list of prefixes to scan
            return [{
                "task_id": f"{job_short}-s{stage_num}-prefixes",
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
                    "task_id": f"{job_short}-s{stage_num}-p{i:03d}",
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
                "task_id": f"{job_short}-s{stage_num}-grid",
                "task_type": task_type,
                "parameters": {
                    "grid_size": job_params.get("grid_size", 5),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        elif stage_name == "generate_summary":
            # Stage 4: Single task for summary statistics
            return [{
                "task_id": f"{job_short}-s{stage_num}-summary",
                "task_type": task_type,
                "parameters": {
                    "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        return []

    @staticmethod
    def finalize_job(context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Finalize the inventory job.

        Returns summary of inventory results from stage 4.
        """
        if not context:
            return {
                "status": "completed",
                "job_type": "inventory_fathom_container",
                "message": "Fathom container inventory completed"
            }

        # Get stage results if available
        stage_results = context.get("stage_results", [])

        # Find summary stage result (stage 4)
        summary = {}
        for result in stage_results:
            if result.get("stage_name") == "generate_summary":
                summary = result.get("result", {})
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
