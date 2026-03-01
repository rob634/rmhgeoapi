# ============================================================================
# CLAUDE CONTEXT - UNPUBLISH ZARR JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Jobs - 3-stage surgical zarr removal (references+data+STAC)
# PURPOSE: Reverse virtualzarr pipeline with dry_run safety by default
# LAST_REVIEWED: 28 FEB 2026
# EXPORTS: UnpublishZarrJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
UnpublishZarrJob - Surgical removal of zarr STAC items and associated artifacts.

Reverses this ETL workflow:
    - virtualzarr: Virtual Zarr reference pipeline (kerchunk + NetCDF)

Removes STAC items, kerchunk reference JSON, manifest JSON,
and optionally copied NetCDF data files from silver-netcdf.

Three-Stage Workflow:
    Stage 1 (inventory): Query STAC item (pgstac + Release fallback),
        extract reference/data file paths for deletion
    Stage 2 (delete_blobs): Fan-out deletion of reference/data blobs
    Stage 3 (cleanup): Delete STAC item, cleanup empty collection, audit record

Safety Features:
    - dry_run=True by default (preview only, no deletions)
    - Pre-flight validation via inventory handler (pgstac + Release fallback)
    - Idempotent blob deletion (succeeds if already deleted)
    - System collections protected (STACDefaults.SYSTEM_COLLECTIONS)
    - Full audit trail in app.unpublish_jobs table

Exports:
    UnpublishZarrJob: Zarr unpublish workflow implementation
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class UnpublishZarrJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    Unpublish zarr job using JobBaseMixin pattern.

    Removes zarr STAC item and associated storage artifacts:
    - combined_ref.json (kerchunk reference)
    - manifest.json (pipeline manifest)
    - data/*.nc files (copied NetCDF files, optional via delete_data_files)

    Three-Stage Workflow:
    1. Stage 1 (inventory): Query STAC item (pgstac + Release fallback),
       classify blobs for deletion
    2. Stage 2 (delete_blobs): Fan-out per-blob deletion
    3. Stage 3 (cleanup): Delete STAC item, audit, cleanup collection

    Implements spec Component 2: UnpublishZarrJob.
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "unpublish_zarr"
    description = "Remove zarr STAC item, kerchunk references, manifest, and optionally copied NetCDF files"

    # Declarative ETL linkage - which forward workflows this job reverses
    reverses = ["virtualzarr"]

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "unpublish_inventory_zarr",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "delete_blobs",
            "task_type": "unpublish_delete_blob",
            "parallelism": "fan_out"  # One task per blob from stage 1 results
        },
        {
            "number": 3,
            "name": "cleanup",
            "task_type": "unpublish_delete_stac",
            "parallelism": "single"
        }
    ]

    # Declarative parameter validation
    parameters_schema = {
        "stac_item_id": {
            "type": "str",
            "required": True
        },
        "collection_id": {
            "type": "str",
            "required": True
        },
        "dry_run": {
            "type": "bool",
            "default": True  # Safety default - preview only!
        },
        "delete_data_files": {
            "type": "bool",
            "default": True  # Delete copied NetCDF files by default
        },
        "force_approved": {
            "type": "bool",
            "default": False  # Must explicitly override to unpublish approved items
        }
    }

    # NO resource_validators -- zarr items may not be materialized to pgstac.
    # Inventory handler validates existence via pgstac + Release fallback.
    # Spec Component 2: resource_validators intentionally empty.
    resource_validators = []

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
        Generate task parameters for each stage.

        Implements spec Component 2: create_tasks_for_stage.

        Stage 1: Single inventory task — discover zarr artifacts
        Stage 2: Fan-out — one task per blob to delete
        Stage 3: Single cleanup task — delete STAC item + audit

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters (stac_item_id, collection_id, dry_run, etc.)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Stage 1: Inventory - query STAC/Release and extract artifact list
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "unpublish_inventory_zarr",
                "parameters": {
                    "stac_item_id": job_params["stac_item_id"],
                    "collection_id": job_params["collection_id"],
                    "dry_run": job_params.get("dry_run", True),
                    "delete_data_files": job_params.get("delete_data_files", True),
                    "force_approved": job_params.get("force_approved", False),
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out blob deletion
            # Extract blob list from stage 1 results
            if not previous_results:
                # No blobs to delete - return empty list
                return []

            # IMPORTANT: CoreMachine._get_completed_stage_results() returns
            # result_data dicts DIRECTLY, not TaskRecord objects.
            # So previous_results[0] IS the inventory result dict.
            inventory_result = previous_results[0]
            blobs_to_delete = inventory_result.get("blobs_to_delete", [])
            dry_run = job_params.get("dry_run", True)

            if not blobs_to_delete:
                # No blobs found - reference-only deletion
                return []

            # Create one task per blob
            tasks = []
            for i, blob_info in enumerate(blobs_to_delete):
                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-blob{i}",
                    "task_type": "unpublish_delete_blob",
                    "parameters": {
                        "container": blob_info.get("container"),
                        "blob_path": blob_info.get("blob_path"),
                        "dry_run": dry_run,
                        "stac_item_id": job_params["stac_item_id"]
                    }
                })

            return tasks

        elif stage == 3:
            # Stage 3: Cleanup - delete STAC item, audit, cleanup empty collection
            #
            # NOTE (spec Component 2): At Stage 3, previous_results contains
            # Stage 2 results (delete_blob tasks), NOT Stage 1 inventory results.
            # original_job_id is NOT available from Stage 2 outputs.
            # Pass original_job_id=None -- the handler handles this gracefully.

            # previous_results from Stage 2 are delete_blob result dicts
            blobs_deleted = previous_results if previous_results else []

            return [{
                "task_id": f"{job_id[:8]}-s3-cleanup",
                "task_type": "unpublish_delete_stac",
                "parameters": {
                    "stac_item_id": job_params["stac_item_id"],
                    "collection_id": job_params["collection_id"],
                    "dry_run": job_params.get("dry_run", True),
                    "unpublish_job_id": job_id,
                    "unpublish_type": "zarr",
                    # original_job_id not available from Stage 2 results
                    "original_job_id": None,
                    "original_job_type": "virtualzarr",
                    "original_parameters": None,
                    "blobs_deleted": blobs_deleted
                }
            }]

        else:
            return []

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary.

        Implements spec Component 2: finalize_job.
        Logs completion, returns summary dict.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Job summary with unpublish results
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "UnpublishZarrJob.finalize_job"
        )

        if context:
            # Extract cleanup result - task_results are objects with attributes
            cleanup_results = [
                r for r in context.task_results
                if getattr(r, "task_type", None) == "unpublish_delete_stac"
            ]

            if cleanup_results:
                # Access result_data as attribute, then treat as dict
                cleanup = getattr(cleanup_results[0], "result_data", {}) or {}
                dry_run = cleanup.get("dry_run", True)

                if dry_run:
                    logger.info(
                        f"DRY RUN - Unpublish zarr job {context.job_id[:16]}... "
                        f"previewed (no deletions)"
                    )
                else:
                    logger.info(
                        f"Unpublish zarr job {context.job_id[:16]}... completed - "
                        f"STAC item {cleanup.get('stac_item_id')} deleted"
                    )

                return {
                    "job_type": "unpublish_zarr",
                    "status": "completed",
                    "dry_run": dry_run,
                    "stac_item_id": cleanup.get("stac_item_id"),
                    "collection_id": cleanup.get("collection_id"),
                }

        logger.info("Unpublish zarr job completed (no context provided)")

        return {
            "job_type": "unpublish_zarr",
            "status": "completed"
        }
