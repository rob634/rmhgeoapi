"""
Raster Workflows Base Class.

Shared logic for raster collection workflows (multi-tile processing).

Used by:
    ProcessRasterCollectionWorkflow: 4 stages (validate, COG, MosaicJSON, STAC)
    ProcessLargeRasterWorkflow: 5 stages (tile, extract, COG, MosaicJSON, STAC)

Key Features:
    DRY principle: Common finalization logic in one place
    Bug fixes propagate to all workflows automatically
    Stages converge to same COG→MosaicJSON→STAC pattern

Design Pattern:
    Mixin class providing shared implementation methods
    Workflows inherit and call _finalize_cog_mosaicjson_stac_stages()

Exports:
    RasterWorkflowsBase: Mixin with shared finalization logic
"""

from typing import Dict, Any, List
from util_logger import LoggerFactory, ComponentType
from core.models import TaskStatus
from config.defaults import STACDefaults


class RasterWorkflowsBase:
    """
    Base class for raster collection workflows.

    Provides shared finalization logic for workflows that:
    1. Create COGs from tiles (parallel fan-out stage)
    2. Create MosaicJSON from COGs (fan-in aggregation)
    3. Create STAC collection from MosaicJSON (fan-in metadata)

    Workflows can have different earlier stages (validation, tiling, extraction)
    but converge to the same COG→MosaicJSON→STAC completion pattern.
    """

    @staticmethod
    def _finalize_cog_mosaicjson_stac_stages(
        context,
        job_type: str,
        cog_stage_num: int,
        mosaicjson_stage_num: int,
        stac_stage_num: int,
        extra_summaries: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Finalize job with COG + MosaicJSON + STAC results.

        Extracted from process_raster_collection.finalize_job() (PRODUCTION READY).

        This method handles the common completion pattern:
        - Extract COG results (fan-out stage with N tasks)
        - Extract MosaicJSON result (fan-in stage with 1 task)
        - Extract STAC collection result (fan-in stage with 1 task)
        - Generate TiTiler visualization URLs

        Args:
            context: JobExecutionContext with task_results
            job_type: Job type string (e.g., "process_raster_collection")
            cog_stage_num: Stage number that created COGs (2 or 3)
            mosaicjson_stage_num: Stage number that created MosaicJSON (3 or 4)
            stac_stage_num: Stage number that created STAC (4 or 5)
            extra_summaries: Optional dict with workflow-specific summaries
                            (e.g., {"tiling": {...}, "extraction": {...}})

        Returns:
            Complete job summary dict with:
            - job_type, job_id, collection_id
            - cogs: {total_count, successful, failed, total_size_mb}
            - mosaicjson: {blob_path, url, bounds, tile_count}
            - stac: {collection_id, stac_id, search_id, items_created}
            - titiler_urls: {viewer_url, tilejson_url, tiles_url, search_id}
            - share_url: Primary URL for end users
            - Extra summaries if provided

        CRITICAL BUG FIXES (from process_raster_collection):
        - Line 808: result_data IS the result (NOT .get("result"))
        - Line 837: result_data IS the result (NOT .get("result"))
        - Fan-in handlers return unwrapped dicts
        """
        from config import get_config

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            f"{job_type}.finalize_job"
        )

        task_results = context.task_results
        params = context.parameters
        config = get_config()

        # ================================================================
        # Extract COG results (fan-out stage - N tasks)
        # ================================================================
        cog_tasks = [t for t in task_results if t.task_type == "create_cog"]
        successful_cogs = [t for t in cog_tasks if t.status == TaskStatus.COMPLETED]
        failed_cogs = [t for t in cog_tasks if t.status == TaskStatus.FAILED]

        total_size_mb = 0
        for cog_task in successful_cogs:
            if cog_task.result_data and cog_task.result_data.get("result"):
                size_mb = cog_task.result_data["result"].get("size_mb", 0)
                total_size_mb += size_mb

        cog_summary = {
            "total_count": len(successful_cogs),
            "successful": len(successful_cogs),
            "failed": len(failed_cogs),
            "total_size_mb": round(total_size_mb, 2)
        }

        # ================================================================
        # Extract MosaicJSON result (fan-in stage - 1 task)
        # ================================================================
        mosaicjson_tasks = [t for t in task_results if t.task_type == "create_mosaicjson"]
        mosaicjson_summary = {}
        if mosaicjson_tasks and mosaicjson_tasks[0].result_data:
            # CRITICAL (11 NOV 2025): result_data IS the result dict already.
            # CoreMachine stores raw handler return: {"success": True, "mosaicjson_blob": "...", ...}
            # DO NOT access .get("result") - fan-in handlers return unwrapped dicts
            mosaicjson_result = mosaicjson_tasks[0].result_data

            # DIAGNOSTIC LOGGING (11 NOV 2025): Verify structure for debugging
            logger.debug(f"🔍 [MOSAIC-RESULT] mosaicjson_result structure:")
            logger.debug(f"   Type: {type(mosaicjson_result)}")
            logger.debug(f"   Keys: {list(mosaicjson_result.keys()) if isinstance(mosaicjson_result, dict) else 'NOT A DICT'}")
            logger.debug(f"   blob_path: {mosaicjson_result.get('mosaicjson_blob')}")

            mosaicjson_summary = {
                "blob_path": mosaicjson_result.get("mosaicjson_blob"),
                "url": mosaicjson_result.get("mosaicjson_url"),
                "bounds": mosaicjson_result.get("bounds"),
                "tile_count": mosaicjson_result.get("tile_count")
            }

            logger.debug(f"✅ [MOSAIC-RESULT] mosaicjson_summary: {mosaicjson_summary}")

        # ================================================================
        # Extract STAC result (fan-in stage - 1 task)
        # ================================================================
        stac_tasks = [t for t in task_results if t.task_type == "create_stac_collection"]
        stac_summary = {}
        titiler_urls = None
        share_url = None

        if stac_tasks and stac_tasks[0].result_data:
            # CRITICAL FIX (20 NOV 2025): result_data IS the result dict already (not wrapped in "result" key)
            # Same bug pattern as MosaicJSON fix on line 808 (11 NOV 2025)
            # OLD BUG: stac_result = stac_tasks[0].result_data.get("result", {})  # Returns {} because no "result" key.
            # CORRECT: result_data IS the result
            stac_result = stac_tasks[0].result_data
            collection_id = stac_result.get("collection_id", STACDefaults.COGS_COLLECTION)
            item_id = stac_result.get("stac_id") or stac_result.get("pgstac_id")

            # Extract pgSTAC search URLs (16 NOV 2025 - Option B: pgSTAC search for visualization)
            search_id = stac_result.get("search_id")

            stac_summary = {
                "collection_id": collection_id,
                "stac_id": item_id,
                "pgstac_id": stac_result.get("pgstac_id"),
                "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
                "ready_for_titiler": True,
                "search_id": search_id,  # pgSTAC search ID (16 NOV 2025)
                "items_created": stac_result.get("items_created", 0),
                "items_failed": stac_result.get("items_failed", 0)
            }

        # ================================================================
        # Generate TiTiler URLs (pgSTAC search pattern - 16 NOV 2025)
        # ================================================================
        # MosaicJSON file is created and stored as STAC asset (archival/metadata)
        # BUT pgSTAC search is the primary visualization method (OAuth-only)
        if stac_tasks and stac_tasks[0].result_data:
            # CRITICAL FIX (20 NOV 2025): Same bug as above - result_data IS the result (not wrapped)
            stac_result = stac_tasks[0].result_data
            search_id = stac_result.get("search_id")

            if search_id:
                # Use pgSTAC search URLs (OAuth-only, no SAS tokens)
                titiler_urls = {
                    "viewer_url": stac_result.get("viewer_url"),
                    "tilejson_url": stac_result.get("tilejson_url"),
                    "tiles_url": stac_result.get("tiles_url"),
                    "search_id": search_id
                }
                share_url = stac_result.get("viewer_url")
                logger.info(f"✅ Using pgSTAC search for visualization: {search_id}")
            else:
                # Fallback: pgSTAC search registration failed (non-fatal)
                logger.warning("⚠️  pgSTAC search not registered - no visualization URLs available")
                titiler_urls = None
                share_url = None

        logger.info(
            f"✅ {job_type} job {context.job_id[:16]} completed: "
            f"{len(successful_cogs)} COGs, MosaicJSON created, pgSTAC search registered"
        )

        # ================================================================
        # Build final job summary
        # ================================================================
        result = {
            "job_type": job_type,
            "job_id": context.job_id,
            "collection_id": params.get("collection_id"),
            "cogs": cog_summary,
            "mosaicjson": mosaicjson_summary,
            "stac": stac_summary,
            "titiler_urls": titiler_urls,  # All TiTiler endpoints (unified method)
            "share_url": share_url,  # PRIMARY URL - share this with end users!
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }

        # Add workflow-specific summaries if provided
        if extra_summaries:
            result.update(extra_summaries)

        return result
