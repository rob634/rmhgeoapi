"""
UnpublishVectorJob - Surgical removal of vector STAC items and PostGIS tables.

Reverses process_vector workflow.
Removes STAC items and optionally drops PostGIS tables.

Three-Stage Workflow:
    Stage 1 (inventory): Query STAC item, extract PostGIS table reference
    Stage 2 (drop_table): Drop PostGIS table if requested
    Stage 3 (cleanup): Delete STAC item, cleanup empty collection, audit record

Safety Features:
    - dry_run=True by default (preview only, no deletions)
    - drop_table=True by default (removes PostGIS table)
    - Pre-flight validation confirms STAC item exists
    - Idempotent table drop (succeeds if already dropped)
    - System collections protected (STACDefaults.SYSTEM_COLLECTIONS)
    - Full audit trail in app.unpublish_jobs table

Exports:
    UnpublishVectorJob: Vector unpublish workflow implementation
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class UnpublishVectorJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    Unpublish vector job using JobBaseMixin pattern.

    Removes vector STAC item and associated PostGIS table:
    - STAC item from pgstac.items
    - PostGIS table from geo.{table_name}

    Three-Stage Workflow:
    1. Stage 1 (inventory): Query STAC item, extract table reference
    2. Stage 2 (drop_table): Drop PostGIS table (if drop_table=True)
    3. Stage 3 (cleanup): Delete STAC item, audit, cleanup collection
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "unpublish_vector"
    description = "Remove vector STAC item and optionally drop PostGIS table"

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "inventory_vector_item",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "drop_table",
            "task_type": "drop_postgis_table",
            "parallelism": "single"
        },
        {
            "number": 3,
            "name": "cleanup",
            "task_type": "delete_stac_and_audit",
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
        "drop_table": {
            "type": "bool",
            "default": True  # Drop PostGIS table by default
        },
        "dry_run": {
            "type": "bool",
            "default": True  # Safety default - preview only!
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
        Stage 2: Single table drop task (skipped if drop_table=False)
        Stage 3: Single cleanup task

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters (stac_item_id, collection_id, drop_table, dry_run)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Stage 1: Inventory - query STAC item and extract table reference
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "inventory_vector_item",
                "parameters": {
                    "stac_item_id": job_params["stac_item_id"],
                    "collection_id": job_params["collection_id"],
                    "dry_run": job_params.get("dry_run", True)
                }
            }]

        elif stage == 2:
            # Stage 2: Drop PostGIS table (if requested)
            drop_table = job_params.get("drop_table", True)
            dry_run = job_params.get("dry_run", True)

            # Skip table drop if not requested
            if not drop_table:
                return []

            # Extract table info from stage 1 results
            if not previous_results:
                return []

            inventory_result = previous_results[0].get("result", {})
            table_name = inventory_result.get("postgis_table")

            if not table_name:
                # No table reference found - just skip this stage
                return []

            return [{
                "task_id": f"{job_id[:8]}-s2-drop",
                "task_type": "drop_postgis_table",
                "parameters": {
                    "table_name": table_name,
                    "schema_name": inventory_result.get("schema_name", "geo"),
                    "dry_run": dry_run,
                    "stac_item_id": job_params["stac_item_id"]
                }
            }]

        elif stage == 3:
            # Stage 3: Cleanup - delete STAC item, audit, cleanup empty collection
            # Gather inventory data from stage 1
            inventory_data = {}
            table_dropped = False

            if previous_results:
                for result in previous_results:
                    if result.get("task_type") == "inventory_vector_item":
                        inventory_data = result.get("result", {})
                    elif result.get("task_type") == "drop_postgis_table":
                        table_dropped = result.get("result", {}).get("table_dropped", False)

            return [{
                "task_id": f"{job_id[:8]}-s3-cleanup",
                "task_type": "delete_stac_and_audit",
                "parameters": {
                    "stac_item_id": job_params["stac_item_id"],
                    "collection_id": job_params["collection_id"],
                    "dry_run": job_params.get("dry_run", True),
                    "unpublish_job_id": job_id,
                    "unpublish_type": "vector",
                    # Pass through inventory data for audit record
                    "original_job_id": inventory_data.get("original_job_id"),
                    "original_job_type": inventory_data.get("original_job_type"),
                    "original_parameters": inventory_data.get("original_parameters"),
                    "postgis_table": inventory_data.get("postgis_table"),
                    "table_dropped": table_dropped
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
            "UnpublishVectorJob.finalize_job"
        )

        if context:
            # Extract cleanup result
            cleanup_results = [
                r for r in context.task_results
                if r.get("task_type") == "delete_stac_and_audit"
            ]

            if cleanup_results:
                cleanup = cleanup_results[0].get("result", {})
                dry_run = cleanup.get("dry_run", True)

                if dry_run:
                    logger.info(
                        f"🔍 DRY RUN - Unpublish vector job {context.job_id[:16]}... "
                        f"previewed (no deletions)"
                    )
                else:
                    logger.info(
                        f"✅ Unpublish vector job {context.job_id[:16]}... completed - "
                        f"STAC item {cleanup.get('stac_item_id')} deleted"
                    )

                return {
                    "job_type": "unpublish_vector",
                    "status": "completed",
                    "dry_run": dry_run,
                    "stac_item_id": cleanup.get("stac_item_id"),
                    "collection_id": cleanup.get("collection_id"),
                    "postgis_table": cleanup.get("postgis_table"),
                    "table_dropped": cleanup.get("table_dropped", False),
                    "collection_deleted": cleanup.get("collection_deleted", False)
                }

        logger.info("✅ Unpublish vector job completed (no context provided)")

        return {
            "job_type": "unpublish_vector",
            "status": "completed"
        }
