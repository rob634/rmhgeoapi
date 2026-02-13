# ============================================================================
# UNPUBLISH VECTOR JOB
# ============================================================================
# STATUS: Jobs - 3-stage surgical vector removal (PostGIS+metadata+STAC)
# PURPOSE: Drop tables and cleanup with dry_run safety by default
# LAST_REVIEWED: 13 FEB 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
UnpublishVectorJob - Surgical removal of vector PostGIS tables and metadata.

Reverses these ETL workflows:
    - vector_docker_etl: PostGIS table + metadata + STAC item

Primary data source is geo.table_metadata (OGC Features source of truth).
STAC is optional - deleted if linked in metadata.

Three-Stage Workflow:
    Stage 1 (inventory): Query geo.table_metadata for ETL/STAC linkage info
    Stage 2 (drop_table): Drop PostGIS table and delete metadata row
    Stage 3 (cleanup): Delete STAC item if linked, record audit

Safety Features:
    - dry_run=True by default (preview only, no deletions)
    - Pre-flight validation confirms table exists
    - Idempotent operations (succeed if already deleted)
    - System collections protected (STACDefaults.SYSTEM_COLLECTIONS)
    - Full audit trail in app.unpublish_jobs table

Exports:
    UnpublishVectorJob: Vector unpublish workflow implementation

Date: 13 DEC 2025 - Refactored to use PostGIS table as primary source (not STAC)
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class UnpublishVectorJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    Unpublish vector job using JobBaseMixin pattern.

    Removes vector data in order:
    1. Query geo.table_metadata for ETL/STAC linkage info
    2. DROP PostGIS table + DELETE metadata row
    3. Delete STAC item if linked, record audit

    Primary identifier: table_name (not stac_item_id!)
    STAC is optional metadata, not required.
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "unpublish_vector"
    description = "Remove PostGIS vector table, metadata, and optional STAC item"

    # Declarative ETL linkage - which forward workflows this job reverses
    reverses = [
        "vector_docker_etl",
    ]

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "unpublish_inventory_vector",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "drop_table",
            "task_type": "unpublish_drop_table",
            "parallelism": "single"
        },
        {
            "number": 3,
            "name": "cleanup",
            "task_type": "unpublish_delete_stac",
            "parallelism": "single"
        }
    ]

    # Declarative parameter validation
    # PRIMARY IDENTIFIER: table_name (not stac_item_id!)
    parameters_schema = {
        "table_name": {
            "type": "str",
            "required": True
        },
        "schema_name": {
            "type": "str",
            "default": "geo"  # Can be overridden, defaults to geo schema
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

    # Pre-flight validation - use existing table_exists validator
    # No STAC requirement! PostGIS table is the primary source.
    resource_validators = [
        {
            "type": "table_exists",
            "table_param": "table_name",
            "schema_param": "schema_name",
            "default_schema": "geo",
            "error": "PostGIS table not found - cannot unpublish"
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

        Stage 1: Inventory - query geo.table_metadata
        Stage 2: Drop table + delete metadata row
        Stage 3: Cleanup - delete STAC if linked, audit

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters (table_name, schema_name, dry_run)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        # Get schema from params or use default
        schema_name = job_params.get("schema_name", "geo")
        table_name = job_params.get("table_name")
        dry_run = job_params.get("dry_run", True)

        if stage == 1:
            # Stage 1: Inventory - query geo.table_metadata for ETL/STAC linkage
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "unpublish_inventory_vector",
                "parameters": {
                    "table_name": table_name,
                    "schema_name": schema_name,
                    "dry_run": dry_run,
                    "force_approved": job_params.get("force_approved", False)  # 16 JAN 2026
                }
            }]

        elif stage == 2:
            # Stage 2: Drop PostGIS table and delete metadata row
            #
            # IMPORTANT: previous_results at Stage 2 contains Stage 1 results directly.
            # CoreMachine._get_completed_stage_results() returns result_data dicts.
            # We need to pass Stage 1 inventory data through to Stage 3 via task params.
            inventory_data = previous_results[0] if previous_results else {}

            return [{
                "task_id": f"{job_id[:8]}-s2-drop",
                "task_type": "unpublish_drop_table",
                "parameters": {
                    "table_name": table_name,
                    "schema_name": schema_name,
                    "dry_run": dry_run,
                    "delete_metadata": True,  # Also delete from geo.table_metadata
                    # Pass through Stage 1 inventory data for Stage 3
                    "_inventory_data": inventory_data
                }
            }]

        elif stage == 3:
            # Stage 3: Cleanup - delete STAC if linked, record audit
            #
            # IMPORTANT: previous_results at Stage 3 contains Stage 2 results.
            # The Stage 2 handler should have passed through _inventory_data.
            stage2_result = previous_results[0] if previous_results else {}

            # Extract inventory data passed through from Stage 2
            inventory_data = stage2_result.get("_inventory_data", {})
            table_dropped = stage2_result.get("table_dropped", False)

            return [{
                "task_id": f"{job_id[:8]}-s3-cleanup",
                "task_type": "unpublish_delete_stac",
                "parameters": {
                    # Use STAC info from inventory if available
                    "stac_item_id": inventory_data.get("stac_item_id"),
                    "collection_id": inventory_data.get("stac_collection_id"),
                    "dry_run": dry_run,
                    "unpublish_job_id": job_id,
                    "unpublish_type": "vector",
                    # Pass through inventory data for audit record
                    "original_job_id": inventory_data.get("etl_job_id"),
                    "original_job_type": inventory_data.get("original_job_type", "vector_docker_etl"),
                    "original_parameters": inventory_data.get("original_parameters"),
                    "postgis_table": f"{schema_name}.{table_name}",
                    "table_dropped": table_dropped,
                    "metadata_snapshot": inventory_data.get("metadata_snapshot")
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
            # Extract results from each stage - task_results are objects with attributes
            inventory_data = {}
            table_dropped = False
            stac_deleted = False
            dry_run = True

            for result in context.task_results:
                task_type = getattr(result, "task_type", None)
                task_result = getattr(result, "result_data", {}) or {}

                if task_type == "unpublish_inventory_vector":
                    inventory_data = task_result
                elif task_type == "unpublish_drop_table":
                    table_dropped = task_result.get("table_dropped", False)
                elif task_type == "unpublish_delete_stac":
                    stac_deleted = task_result.get("stac_item_deleted", False)
                    dry_run = task_result.get("dry_run", True)

            table_name = inventory_data.get("table_name", "unknown")

            if dry_run:
                logger.info(
                    f"🔍 DRY RUN - Unpublish vector job {context.job_id[:16]}... "
                    f"previewed table '{table_name}' (no deletions)"
                )
            else:
                logger.info(
                    f"✅ Unpublish vector job {context.job_id[:16]}... completed - "
                    f"table '{table_name}' dropped={table_dropped}, stac_deleted={stac_deleted}"
                )

            return {
                "job_type": "unpublish_vector",
                "status": "completed",
                "dry_run": dry_run,
                "table_name": table_name,
                "schema_name": inventory_data.get("schema_name", "geo"),
                "table_dropped": table_dropped,
                "metadata_deleted": inventory_data.get("metadata_found", False),
                "stac_item_deleted": stac_deleted,
                "stac_item_id": inventory_data.get("stac_item_id"),
                "etl_job_id": inventory_data.get("etl_job_id")
            }

        logger.info("✅ Unpublish vector job completed (no context provided)")

        return {
            "job_type": "unpublish_vector",
            "status": "completed"
        }
