# ============================================================================
# CLAUDE CONTEXT - UNPUBLISH VECTOR MULTI-SOURCE JOB
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Jobs - 3-stage surgical multi-source vector removal
# PURPOSE: Drop N PostGIS tables from a multi-source release, cleanup metadata
# CREATED: 09 MAR 2026
# EXPORTS: UnpublishVectorMultiSourceJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
UnpublishVectorMultiSourceJob -- Surgical removal of multi-source vector tables.

Reverses this ETL workflow:
    - vector_multi_source_docker: N files/layers -> N PostGIS tables

Uses app.release_tables as the single source of truth for which tables
a release owns. Drops each table individually (parallel fan-out), then
cleans up STAC item and audit trail.

Three-Stage Workflow:
    Stage 1 (inventory): Query release_tables for all table names
    Stage 2 (drop_tables): Fan-out -- one task per table (parallel DROP)
    Stage 3 (cleanup): Delete STAC item if linked, record audit

Safety Features:
    - dry_run=False by default (executes deletions)
    - Idempotent table drops (succeeds if already dropped)
    - System collections protected (STACDefaults.SYSTEM_COLLECTIONS)
    - Full audit trail in app.unpublish_jobs table

Exports:
    UnpublishVectorMultiSourceJob
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class UnpublishVectorMultiSourceJob(JobBaseMixin, JobBase):  # Mixin FIRST!
    """
    Unpublish multi-source vector job using JobBaseMixin pattern.

    Removes all PostGIS tables belonging to a multi-source release:
    1. Query app.release_tables for all tables owned by the release
    2. DROP each table in parallel + delete metadata rows
    3. Delete STAC item if linked, record audit

    Primary identifier: release_id (looks up tables via ReleaseTableRepository)
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "unpublish_vector_multi_source"
    description = "Unpublish multi-source vector: drop N tables, cleanup metadata"

    # Declarative ETL linkage
    reverses = [
        "vector_multi_source_docker",
    ]

    # Stage definitions
    stages = [
        {
            "number": 1,
            "name": "inventory",
            "task_type": "unpublish_inventory_vector_multi",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "drop_tables",
            "task_type": "unpublish_drop_table",
            "parallelism": "fan_out"  # One task per table from stage 1 results
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
        "release_id": {
            "type": "str",
            "required": True
        },
        "dataset_id": {
            "type": "str",
            "default": None
        },
        "resource_id": {
            "type": "str",
            "default": None
        },
        "version_id": {
            "type": "str",
            "default": None
        },
        "stac_item_id": {
            "type": "str",
            "default": None
        },
        "collection_id": {
            "type": "str",
            "default": None
        },
        "dry_run": {
            "type": "bool",
            "default": True
        },
        "force_approved": {
            "type": "bool",
            "default": False
        }
    }

    # No resource_validators -- inventory handler validates via release_tables
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

        Stage 1: Inventory -- query release_tables for all table names
        Stage 2: Fan-out -- one DROP task per table from Stage 1 results
        Stage 3: Cleanup -- delete STAC item if linked, record audit

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters (release_id, dry_run, etc.)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        dry_run = job_params.get("dry_run", False)

        if stage == 1:
            # Stage 1: Inventory -- look up all tables for this release
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": "unpublish_inventory_vector_multi",
                "parameters": {
                    "release_id": job_params["release_id"],
                    "dataset_id": job_params.get("dataset_id"),
                    "resource_id": job_params.get("resource_id"),
                    "version_id": job_params.get("version_id"),
                    "stac_item_id": job_params.get("stac_item_id"),
                    "dry_run": dry_run,
                    "force_approved": job_params.get("force_approved", False),
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out table drops
            # previous_results[0] is the inventory result dict from Stage 1
            if not previous_results:
                return []

            inventory_result = previous_results[0]
            tables = inventory_result.get("tables", [])

            if not tables:
                # No tables found -- nothing to drop
                return []

            # Create one task per table, reusing the existing drop_postgis_table handler
            tasks = []
            for i, table_info in enumerate(tables):
                table_name = table_info.get("table_name")
                schema_name = table_info.get("schema", "geo")

                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-drop{i}",
                    "task_type": "unpublish_drop_table",
                    "parameters": {
                        "table_name": table_name,
                        "schema_name": schema_name,
                        "delete_metadata": True,
                        "dry_run": dry_run,
                        # Pass inventory data through for Stage 3
                        "_inventory_data": inventory_result,
                    }
                })

            return tasks

        elif stage == 3:
            # Stage 3: Cleanup -- delete STAC item if linked, record audit
            #
            # previous_results contains Stage 2 drop results.
            # _inventory_data was passed through from Stage 1.
            stage2_results = previous_results if previous_results else []

            # Extract inventory data passed through from any Stage 2 task
            inventory_data = {}
            tables_dropped = 0
            for result in stage2_results:
                if result.get("_inventory_data"):
                    inventory_data = result["_inventory_data"]
                if result.get("table_dropped", False):
                    tables_dropped += 1

            # Resolve STAC identifiers: prefer job_params, fallback to inventory
            stac_item_id = job_params.get("stac_item_id") or inventory_data.get("stac_item_id")
            collection_id = job_params.get("collection_id") or inventory_data.get("collection_id")

            return [{
                "task_id": f"{job_id[:8]}-s3-cleanup",
                "task_type": "unpublish_delete_stac",
                "parameters": {
                    "stac_item_id": stac_item_id,
                    "collection_id": collection_id,
                    "dry_run": dry_run,
                    "unpublish_job_id": job_id,
                    "unpublish_type": "vector_multi_source",
                    "original_job_id": inventory_data.get("original_job_id"),
                    "original_job_type": "vector_multi_source_docker",
                    "original_parameters": None,
                    "tables_dropped": tables_dropped,
                    "table_count": inventory_data.get("table_count", 0),
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
            "UnpublishVectorMultiSourceJob.finalize_job"
        )

        if context:
            # Extract results from each stage
            inventory_data = {}
            tables_dropped = 0
            total_tables = 0
            stac_deleted = False
            dry_run = False

            for result in context.task_results:
                task_type = getattr(result, "task_type", None)
                task_result = getattr(result, "result_data", {}) or {}

                if task_type == "unpublish_inventory_vector_multi":
                    inventory_data = task_result
                    total_tables = task_result.get("table_count", 0)
                elif task_type == "unpublish_drop_table":
                    if task_result.get("table_dropped", False):
                        tables_dropped += 1
                elif task_type == "unpublish_delete_stac":
                    stac_deleted = task_result.get("stac_item_deleted", False)
                    dry_run = task_result.get("dry_run", False)

            release_id = inventory_data.get("release_id", "unknown")

            if dry_run:
                logger.info(
                    f"DRY RUN - Unpublish multi-source vector job "
                    f"{context.job_id[:16]}... previewed release "
                    f"{release_id[:16]}... ({total_tables} tables, no deletions)"
                )
            else:
                logger.info(
                    f"Unpublish multi-source vector job "
                    f"{context.job_id[:16]}... completed - "
                    f"release {release_id[:16]}..., "
                    f"{tables_dropped}/{total_tables} tables dropped, "
                    f"stac_deleted={stac_deleted}"
                )

            return {
                "job_type": "unpublish_vector_multi_source",
                "status": "completed",
                "dry_run": dry_run,
                "release_id": release_id,
                "tables_dropped": tables_dropped,
                "total_tables": total_tables,
                "stac_item_deleted": stac_deleted,
                "stac_item_id": inventory_data.get("stac_item_id"),
                "table_names": inventory_data.get("table_names", []),
            }

        logger.info("Unpublish multi-source vector job completed (no context)")

        return {
            "job_type": "unpublish_vector_multi_source",
            "status": "completed"
        }
