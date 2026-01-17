# ============================================================================
# UNPUBLISH RASTER JOB
# ============================================================================
# STATUS: Jobs - 3-stage surgical raster removal (STAC+COG+MosaicJSON)
# PURPOSE: Reverse process_raster workflows with dry_run safety by default
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
UnpublishRasterJob - Surgical removal of raster STAC items and associated blobs.

Reverses process_raster_v2, process_large_raster_v2, and stac_catalog_container workflows.
Removes STAC items, COG blobs, MosaicJSON files, and tile COGs.

Three-Stage Workflow:
    Stage 1 (inventory): Query STAC item, extract asset hrefs for deletion
    Stage 2 (delete_blobs): Fan-out deletion of COG/MosaicJSON blobs
    Stage 3 (cleanup): Delete STAC item, cleanup empty collection, audit record

Safety Features:
    - dry_run=True by default (preview only, no deletions)
    - Pre-flight validation confirms STAC item exists
    - Idempotent blob deletion (succeeds if already deleted)
    - System collections protected (STACDefaults.SYSTEM_COLLECTIONS)
    - Full audit trail in app.unpublish_jobs table

Exports:
    UnpublishRasterJob: Raster unpublish workflow implementation
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class UnpublishRasterJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    Unpublish raster job using JobBaseMixin pattern.

    Removes raster STAC item and associated storage artifacts:
    - Single COG files (from process_raster_v2)
    - Tile COGs + MosaicJSON (from process_large_raster_v2)
    - COG collections (from stac_catalog_container)

    Three-Stage Workflow:
    1. Stage 1 (inventory): Query STAC item, extract blob hrefs
    2. Stage 2 (delete_blobs): Fan-out per-blob deletion
    3. Stage 3 (cleanup): Delete STAC item, audit, cleanup collection
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "unpublish_raster"
    description = "Remove raster STAC item and associated COG/MosaicJSON blobs"

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "unpublish_inventory_raster",
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
        "force_approved": {
            "type": "bool",
            "default": False  # 16 JAN 2026: Must explicitly override to unpublish approved items
        }
    }

    # Pre-flight validation - fail fast if STAC item doesn't exist
    resource_validators = [
        {
            "type": "stac_item_exists",
            "item_id_param": "stac_item_id",
            "collection_id_param": "collection_id",
            "error": "STAC item not found in collection - cannot unpublish"
        }
    ]

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

        Stage 1: Single inventory task
        Stage 2: Fan-out - one task per blob to delete
        Stage 3: Single cleanup task

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters (stac_item_id, collection_id, dry_run)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Stage 1: Inventory - query STAC item and extract blob list
            # Pass through _stac_item from validator for handler to use
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "unpublish_inventory_raster",
                "parameters": {
                    "stac_item_id": job_params["stac_item_id"],
                    "collection_id": job_params["collection_id"],
                    "dry_run": job_params.get("dry_run", True),
                    "force_approved": job_params.get("force_approved", False),  # 16 JAN 2026
                    # Pass through validated STAC item data from resource_validators
                    "_stac_item": job_params.get("_stac_item"),
                    "_stac_item_assets": job_params.get("_stac_item_assets"),
                    "_stac_original_job_id": job_params.get("_stac_original_job_id")
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
                # No blobs found - this is okay for stac_catalog_container items
                # They just catalog existing COGs without creating new blobs
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
            # IMPORTANT: At Stage 3, previous_results contains Stage 2 results
            # (delete_blob tasks), NOT Stage 1 inventory results!
            #
            # Get inventory data from job_params._stac_item (set by validator)
            stac_item = job_params.get("_stac_item", {})
            properties = stac_item.get("properties", {}) if stac_item else {}

            # Extract original job info from STAC item properties
            original_job_id = properties.get("app:job_id")
            original_job_type = properties.get("app:job_type")

            # previous_results from Stage 2 are delete_blob result dicts
            # Each contains: {blob_deleted: bool, blob_path: str, etc.}
            blobs_deleted = previous_results if previous_results else []

            return [{
                "task_id": f"{job_id[:8]}-s3-cleanup",
                "task_type": "unpublish_delete_stac",
                "parameters": {
                    "stac_item_id": job_params["stac_item_id"],
                    "collection_id": job_params["collection_id"],
                    "dry_run": job_params.get("dry_run", True),
                    "unpublish_job_id": job_id,
                    "unpublish_type": "raster",
                    # Pass through inventory data for audit record
                    "original_job_id": original_job_id,
                    "original_job_type": original_job_type,
                    "original_parameters": None,  # Not stored in STAC item
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

        Args:
            context: JobExecutionContext with task results

        Returns:
            Job summary with unpublish results
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "UnpublishRasterJob.finalize_job"
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
                        f"🔍 DRY RUN - Unpublish raster job {context.job_id[:16]}... "
                        f"previewed (no deletions)"
                    )
                else:
                    logger.info(
                        f"✅ Unpublish raster job {context.job_id[:16]}... completed - "
                        f"STAC item {cleanup.get('stac_item_id')} deleted"
                    )

                return {
                    "job_type": "unpublish_raster",
                    "status": "completed",
                    "dry_run": dry_run,
                    "stac_item_id": cleanup.get("stac_item_id"),
                    "collection_id": cleanup.get("collection_id"),
                    "blobs_deleted": len(cleanup.get("blobs_deleted", [])),
                    "collection_deleted": cleanup.get("collection_deleted", False)
                }

        logger.info("✅ Unpublish raster job completed (no context provided)")

        return {
            "job_type": "unpublish_raster",
            "status": "completed"
        }
