# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - PROCESS FATHOM FLOOD HAZARD DATA
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job workflow - Fathom Global Flood Hazard ETL pipeline
# PURPOSE: Consolidate Fathom 1°×1° flood tiles into multi-band regional COGs
# LAST_REVIEWED: 26 NOV 2025
# EXPORTS: ProcessFathomWorkflow class
# INTERFACES: JobBase contract, JobBaseMixin for boilerplate elimination
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin, GDAL, rasterio
# SOURCE: bronze-fathom container (Fathom Global Flood Maps v3)
# SCOPE: Regional flood hazard data consolidation (CI pilot → global)
# VALIDATION: Declarative schema via JobBaseMixin
# PATTERNS: Mixin pattern, fan-out/fan-in, multi-band COG consolidation
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "process_fathom"
# INDEX: ProcessFathomWorkflow:45, stages:67, parameters_schema:93, create_tasks_for_stage:140
# ============================================================================

"""
Process Fathom Workflow - Flood Hazard Data Consolidation

Multi-stage workflow for consolidating Fathom Global Flood Hazard Maps
from millions of small 1°×1° tiles into manageable regional multi-band COGs.

Data Architecture:
- Input: 5 flood types × 4 years × 8 return periods × N tiles
- Output: Multi-band COGs with return periods as bands (8 bands each)
- Consolidation: Country-based spatial merge (CI pilot: 44 tiles → 1 merged extent)

Four-Stage Workflow:
1. INVENTORY: Parse file list, group 15,392 files into 65 output targets
2. MERGE_STACK: Fan-out - 65 parallel tasks merge tiles + stack bands
3. UPLOAD: Upload COGs to silver-cogs container
4. STAC_REGISTER: Create STAC items with band metadata in pgstac

Output File Structure:
- 8 bands per file (return periods: 1in5, 1in10, 1in20, 1in50, 1in100, 1in200, 1in500, 1in1000)
- Filename: fathom_{region}_{flood_type}_{year}[_{ssp}].tif
- Example: fathom_ci_fluvial-defended_2050_ssp245.tif

Consolidation Results (Côte d'Ivoire Pilot):
- Before: 15,392 files (~50 KB each)
- After: 65 files (~200-350 MB each)
- Reduction: 237x fewer files/STAC records

Author: Robert and Geospatial Claude Legion
Date: 26 NOV 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config import FathomDefaults


class ProcessFathomWorkflow(JobBaseMixin, JobBase):
    """
    Fathom Global Flood Hazard data consolidation workflow.

    Consolidates millions of small tiles into regional multi-band COGs
    with return periods as bands.

    Stages:
    1. inventory: Parse CSV, create 65 merge groups
    2. merge_stack: Fan-out merge tiles + stack return periods as bands
    3. upload: Upload consolidated COGs to silver storage
    4. stac_register: Create STAC items in pgstac
    """

    job_type: str = "process_fathom"
    description: str = "Consolidate Fathom flood hazard tiles into multi-band regional COGs"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "fathom_inventory",
            "description": "Parse file list CSV and create merge groups (65 output targets)",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "merge_stack",
            "task_type": "fathom_merge_stack",
            "description": "Fan-out: merge tiles spatially + stack 8 return periods as bands",
            "parallelism": "fan_out"
        },
        {
            "number": 3,
            "name": "stac_register",
            "task_type": "fathom_stac_register",
            "description": "Fan-in: create STAC collection and items in pgstac",
            "parallelism": "fan_in"
        }
    ]

    # Declarative parameter validation (JobBaseMixin handles validation!)
    parameters_schema: Dict[str, Any] = {
        "region_code": {
            "type": "str",
            "required": True,
            "description": "ISO 3166-1 alpha-2 country code (e.g., 'CI' for Côte d'Ivoire)"
        },
        "region_name": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Human-readable region name (e.g., 'Côte d\\'Ivoire'). If None, derived from region_code."
        },
        "source_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.SOURCE_CONTAINER,
            "description": "Source container with Fathom flood tiles"
        },
        "file_list_csv": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Path to CSV file with file list. If None, uses '{region_code}_{region_name}_file_list.csv'"
        },
        "output_container": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE2_OUTPUT_CONTAINER,
            "description": "Output container for consolidated COGs"
        },
        "output_prefix": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE2_OUTPUT_PREFIX,
            "description": "Output folder prefix in silver container"
        },
        "flood_types": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "List of flood types to process. If None, processes all 5 types."
        },
        "years": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "List of years to process. If None, processes all 4 years (2020, 2030, 2050, 2080)."
        },
        "ssp_scenarios": {
            "type": "list",
            "required": False,
            "default": None,
            "description": "List of SSP scenarios for future years. If None, processes all 4 (SSP1_2.6, SSP2_4.5, SSP3_7.0, SSP5_8.5)."
        },
        "collection_id": {
            "type": "str",
            "required": False,
            "default": FathomDefaults.PHASE2_COLLECTION_ID,
            "description": "STAC collection ID for metadata registration"
        },
        "dry_run": {
            "type": "bool",
            "required": False,
            "default": False,
            "description": "If True, only create inventory without processing files"
        },
        "force_reprocess": {
            "type": "bool",
            "required": False,
            "default": False,
            "description": "If True, reprocess all tiles even if output COG already exists (idempotency override)"
        }
    }

    # Return period band mapping (constant across all files)
    RETURN_PERIODS = ["1in5", "1in10", "1in20", "1in50", "1in100", "1in200", "1in500", "1in1000"]

    # Flood type normalizations
    FLOOD_TYPES = {
        "COASTAL_DEFENDED": {"flood_type": "coastal", "defense_status": "defended"},
        "COASTAL_UNDEFENDED": {"flood_type": "coastal", "defense_status": "undefended"},
        "FLUVIAL_DEFENDED": {"flood_type": "fluvial", "defense_status": "defended"},
        "FLUVIAL_UNDEFENDED": {"flood_type": "fluvial", "defense_status": "undefended"},
        "PLUVIAL_DEFENDED": {"flood_type": "pluvial", "defense_status": "defended"}
    }

    # SSP scenario normalizations
    SSP_SCENARIOS = {
        "SSP1_2.6": "ssp126",
        "SSP2_4.5": "ssp245",
        "SSP3_7.0": "ssp370",
        "SSP5_8.5": "ssp585"
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

        Stage 1: Single inventory task - parse CSV and create merge groups
        Stage 2: Fan-out - 65 parallel merge/stack tasks
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
            # Stage 1: Inventory - parse CSV and create merge groups
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "fathom_inventory",
                "parameters": {
                    "region_code": job_params["region_code"],
                    "region_name": job_params.get("region_name"),
                    "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                    "file_list_csv": job_params.get("file_list_csv"),
                    "flood_types": job_params.get("flood_types"),
                    "years": job_params.get("years"),
                    "ssp_scenarios": job_params.get("ssp_scenarios"),
                    "dry_run": job_params.get("dry_run", False)
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out merge/stack tasks
            # Get merge groups from Stage 1 inventory
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 1 failed - no inventory created")

            stage1_result = previous_results[0]["result"]
            merge_groups = stage1_result.get("merge_groups", [])

            if not merge_groups:
                raise ValueError("Stage 1 returned no merge groups")

            # Check for dry run
            if job_params.get("dry_run", False):
                # Return empty list for dry run - skip actual processing
                return []

            # Create one task per merge group
            tasks = []
            for idx, group in enumerate(merge_groups):
                # Generate descriptive task ID
                output_name = group["output_name"]  # e.g., "fathom_ci_fluvial-defended_2050_ssp245"
                task_id = f"{job_id[:8]}-s2-{idx:03d}-{output_name[-20:]}"  # Truncate for readability

                tasks.append({
                    "task_id": task_id,
                    "task_type": "fathom_merge_stack",
                    "parameters": {
                        "merge_group": group,
                        "source_container": job_params.get("source_container", FathomDefaults.SOURCE_CONTAINER),
                        "output_container": job_params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER),
                        "output_prefix": job_params.get("output_prefix", FathomDefaults.PHASE2_OUTPUT_PREFIX),
                        "region_code": job_params["region_code"],
                        "force_reprocess": job_params.get("force_reprocess", False)
                    }
                })

            return tasks

        elif stage == 3:
            # Stage 3: Fan-in STAC registration
            # Collect successful COG outputs from Stage 2
            if not previous_results:
                raise ValueError("Stage 2 failed - no COGs created")

            successful_cogs = [
                r["result"]
                for r in previous_results
                if r.get("success") and r.get("result")
            ]

            if not successful_cogs:
                # Check if this was a dry run
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
                raise ValueError("Stage 2 failed - no COGs created")

            return [{
                "task_id": f"{job_id[:8]}-s3-stac",
                "task_type": "fathom_stac_register",
                "parameters": {
                    "cog_results": successful_cogs,
                    "region_code": job_params["region_code"],
                    "collection_id": job_params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID),
                    "output_container": job_params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER)
                }
            }]

        else:
            raise ValueError(f"Invalid stage: {stage}. ProcessFathomWorkflow has 3 stages.")

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary.

        Args:
            context: JobExecutionContext with task results (optional)

        Returns:
            Job completion summary
        """
        if not context:
            return {
                "status": "completed",
                "job_type": "process_fathom"
            }

        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "ProcessFathomWorkflow.finalize_job"
        )

        task_results = context.task_results
        params = context.parameters

        # Extract inventory summary (Stage 1)
        inventory_tasks = [t for t in task_results if t.task_type == "fathom_inventory"]
        inventory_summary = {}
        if inventory_tasks and inventory_tasks[0].result_data:
            inv_result = inventory_tasks[0].result_data.get("result", {})
            inventory_summary = {
                "total_source_files": inv_result.get("total_files", 0),
                "merge_groups_created": inv_result.get("merge_group_count", 0),
                "flood_types": inv_result.get("flood_types", []),
                "years": inv_result.get("years", [])
            }

        # Extract merge/stack summary (Stage 2)
        merge_tasks = [t for t in task_results if t.task_type == "fathom_merge_stack"]
        successful_merges = [t for t in merge_tasks if t.result_data and t.result_data.get("success")]
        skipped_merges = [t for t in merge_tasks if t.result_data and t.result_data.get("skipped")]
        failed_merges = [t for t in merge_tasks if t.result_data and not t.result_data.get("success")]

        merge_summary = {
            "total_tasks": len(merge_tasks),
            "successful": len(successful_merges),
            "skipped": len(skipped_merges),  # Idempotent skips (26 NOV 2025)
            "processed": len(successful_merges) - len(skipped_merges),  # Actually processed
            "failed": len(failed_merges),
            "output_files": [
                t.result_data.get("result", {}).get("output_blob")
                for t in successful_merges
                if t.result_data.get("result", {}).get("output_blob")
            ]
        }

        # Extract STAC registration summary (Stage 3)
        stac_tasks = [t for t in task_results if t.task_type == "fathom_stac_register"]
        stac_summary = {}
        if stac_tasks and stac_tasks[0].result_data:
            stac_result = stac_tasks[0].result_data.get("result", {})
            stac_summary = {
                "collection_id": stac_result.get("collection_id"),
                "items_created": stac_result.get("items_created", 0),
                "stac_catalog_url": stac_result.get("stac_catalog_url")
            }

        # Build comprehensive summary
        summary = {
            "status": "completed",
            "job_type": "process_fathom",
            "region_code": params.get("region_code"),
            "dry_run": params.get("dry_run", False),
            "inventory": inventory_summary,
            "merge_stack": merge_summary,
            "stac_registration": stac_summary,
            "consolidation_ratio": f"{inventory_summary.get('total_source_files', 0)} → {merge_summary.get('successful', 0)} files"
        }

        logger.info(f"✅ Fathom ETL completed: {summary['consolidation_ratio']}")

        return summary

    @classmethod
    def generate_job_id(cls, params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Excludes dry_run from hash (testing parameter, not job identity).

        Args:
            params: Validated job parameters

        Returns:
            SHA256 hash as hex string
        """
        # Exclude testing/control parameters from job_id hash
        # dry_run: testing parameter, force_reprocess: idempotency override
        hash_params = {k: v for k, v in params.items() if k not in ('dry_run', 'force_reprocess')}

        # Create canonical representation
        canonical = json.dumps({
            'job_type': cls.job_type,
            **hash_params
        }, sort_keys=True)

        # Generate SHA256 hash
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
