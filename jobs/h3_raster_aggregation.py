# ============================================================================
# CLAUDE CONTEXT - H3 RASTER AGGREGATION JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job Definition - H3 Raster Zonal Statistics
# PURPOSE: Aggregate local COG rasters to H3 hexagonal grid cells
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: H3RasterAggregationJob
# DEPENDENCIES: jobs.base, jobs.mixins, infrastructure.h3_repository
# ============================================================================
"""
H3 Raster Aggregation Job - 3-Stage Workflow.

Computes zonal statistics from local COG rasters (Azure Blob Storage)
and stores results in h3.zonal_stats table.

3-Stage Workflow:
    Stage 1: Inventory cells for scope (iso3/bbox/polygon_wkt)
    Stage 2: Compute zonal stats (batched fan-out, N parallel tasks)
    Stage 3: Finalize (update registry provenance, verify counts)

Features:
    - Supports iso3, bbox, and polygon_wkt spatial scopes
    - Multiple stat types: mean, sum, min, max, count, std, median
    - Configurable batch size for memory management
    - Optional append_history mode (preserves existing values)
    - Dataset registry integration for metadata catalog

Usage:
    POST /api/jobs/submit/h3_raster_aggregation
    {
        "container": "silver-cogs",
        "blob_path": "population/worldpop_2020.tif",
        "dataset_id": "worldpop_2020",
        "resolution": 6,
        "iso3": "GRC",
        "stats": ["sum", "mean", "count"]
    }

Exports:
    H3RasterAggregationJob: 3-stage raster aggregation job
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class H3RasterAggregationJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    H3 Raster Aggregation Job - 3-stage workflow.

    Stage 1: Inventory cells for scope (1 task)
    Stage 2: Compute zonal stats (batched fan-out, N tasks)
    Stage 3: Finalize and update registry (1 task)

    JobBaseMixin provides: validate_job_parameters, generate_job_id, create_job_record, queue_job
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================

    # Job metadata
    job_type: str = "h3_raster_aggregation"
    description: str = "Aggregate raster data to H3 cells (local COGs)"

    # 3-stage workflow
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "inventory_cells",
            "task_type": "h3_inventory_cells",
            "parallelism": "single",
            "description": "Load H3 cells for scope, return batch ranges"
        },
        {
            "number": 2,
            "name": "compute_stats",
            "task_type": "h3_raster_zonal_stats",
            "parallelism": "fan_out",
            "description": "Compute zonal stats for cell batches (parallel)"
        },
        {
            "number": 3,
            "name": "finalize",
            "task_type": "h3_aggregation_finalize",
            "parallelism": "single",
            "description": "Update registry provenance, verify counts"
        }
    ]

    # Declarative parameter validation
    parameters_schema: Dict[str, Any] = {
        'container': {
            'type': 'str',
            'required': True,
            'description': 'Azure Blob Storage container name (e.g., "silver-cogs")'
        },
        'blob_path': {
            'type': 'str',
            'required': True,
            'description': 'Path to COG file within container (e.g., "population/worldpop_2020.tif")'
        },
        'dataset_id': {
            'type': 'str',
            'required': True,
            'description': 'Unique dataset identifier for stat_registry (e.g., "worldpop_2020")'
        },
        'band': {
            'type': 'int',
            'default': 1,
            'min': 1,
            'description': 'Raster band to aggregate (1-indexed)'
        },
        'resolution': {
            'type': 'int',
            'required': True,
            'min': 0,
            'max': 15,
            'description': 'H3 resolution level for aggregation'
        },
        'iso3': {
            'type': 'str',
            'default': None,
            'description': 'Optional ISO3 country code for spatial filtering (e.g., "GRC")'
        },
        'bbox': {
            'type': 'list',
            'default': None,
            'description': 'Optional bounding box [minx, miny, maxx, maxy]'
        },
        'polygon_wkt': {
            'type': 'str',
            'default': None,
            'description': 'Optional WKT polygon for custom spatial scope'
        },
        'stats': {
            'type': 'list',
            'default': ['mean', 'sum', 'count'],
            'description': 'Stat types to compute: mean, sum, min, max, count, std, median'
        },
        'append_history': {
            'type': 'bool',
            'default': False,
            'description': 'If True, skip existing values. If False (default), overwrite.'
        },
        'batch_size': {
            'type': 'int',
            'default': 1000,
            'min': 100,
            'max': 10000,
            'description': 'Number of cells per batch task'
        },
        'display_name': {
            'type': 'str',
            'default': None,
            'description': 'Human-readable name for stat_registry (auto-generated if not provided)'
        },
        'source_name': {
            'type': 'str',
            'default': None,
            'description': 'Data source name for attribution (e.g., "WorldPop")'
        },
        'source_url': {
            'type': 'str',
            'default': None,
            'description': 'URL to original data source'
        },
        'source_license': {
            'type': 'str',
            'default': None,
            'description': 'License identifier (e.g., "CC-BY-4.0")'
        },
        'unit': {
            'type': 'str',
            'default': None,
            'description': 'Unit of measurement (e.g., "people", "meters")'
        }
    }

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
        Generate task parameters for each stage of raster aggregation workflow.

        3-stage workflow:
            Stage 1: Inventory cells for scope (1 task)
            Stage 2: Compute zonal stats (batched fan-out, N tasks)
            Stage 3: Finalize and update registry (1 task)

        Args:
            stage: Stage number (1-3)
            job_params: Job parameters (container, blob_path, dataset_id, resolution, etc.)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage tasks

        Returns:
            List of task dicts for current stage

        Raises:
            ValueError: Invalid stage number or missing previous results
        """
        # Extract common parameters
        container = job_params.get('container')
        blob_path = job_params.get('blob_path')
        dataset_id = job_params.get('dataset_id')
        band = job_params.get('band', 1)
        resolution = job_params.get('resolution')
        iso3 = job_params.get('iso3')
        bbox = job_params.get('bbox')
        polygon_wkt = job_params.get('polygon_wkt')
        stats = job_params.get('stats', ['mean', 'sum', 'count'])
        append_history = job_params.get('append_history', False)
        batch_size = job_params.get('batch_size', 1000)

        # Registry metadata
        display_name = job_params.get('display_name') or dataset_id
        source_name = job_params.get('source_name')
        source_url = job_params.get('source_url')
        source_license = job_params.get('source_license')
        unit = job_params.get('unit')

        if stage == 1:
            # STAGE 1: Inventory cells for scope
            # Also registers dataset in stat_registry
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-inventory",
                    "task_type": "h3_inventory_cells",
                    "parameters": {
                        "resolution": resolution,
                        "iso3": iso3,
                        "bbox": bbox,
                        "polygon_wkt": polygon_wkt,
                        "batch_size": batch_size,
                        "source_job_id": job_id,
                        # Registry metadata for auto-registration
                        "dataset_id": dataset_id,
                        "stat_category": "raster_zonal",
                        "display_name": display_name,
                        "source_name": source_name,
                        "source_url": source_url,
                        "source_license": source_license,
                        "unit": unit,
                        "stat_types": stats
                    }
                }
            ]

        elif stage == 2:
            # STAGE 2: Compute zonal stats (batched fan-out)
            if not previous_results or len(previous_results) == 0:
                raise ValueError("Stage 2 requires Stage 1 results")

            # Extract inventory results from Stage 1
            inventory_result = previous_results[0]
            if isinstance(inventory_result, dict):
                result_data = inventory_result.get('result', {})
            else:
                result_data = {}

            total_cells = result_data.get('total_cells', 0)
            num_batches = result_data.get('num_batches', 0)
            batch_ranges = result_data.get('batch_ranges', [])

            if total_cells == 0:
                from util_logger import LoggerFactory, ComponentType
                logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "H3RasterAggregationJob")
                logger.warning(f"⚠️ No cells found for scope - creating empty stage 2")
                return []

            # Create fan-out tasks (one per batch)
            tasks = []
            for batch_info in batch_ranges:
                batch_idx = batch_info.get('batch_index', 0)
                batch_start = batch_info.get('batch_start', 0)
                actual_batch_size = batch_info.get('batch_size', batch_size)

                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-batch{batch_idx}",
                    "task_type": "h3_raster_zonal_stats",
                    "parameters": {
                        "container": container,
                        "blob_path": blob_path,
                        "dataset_id": dataset_id,
                        "band": band,
                        "resolution": resolution,
                        "iso3": iso3,
                        "bbox": bbox,
                        "polygon_wkt": polygon_wkt,
                        "batch_start": batch_start,
                        "batch_size": actual_batch_size,
                        "batch_index": batch_idx,
                        "stats": stats,
                        "append_history": append_history,
                        "source_job_id": job_id
                    }
                })

            return tasks

        elif stage == 3:
            # STAGE 3: Finalize and update registry
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Calculate total stats computed from Stage 2 results
            total_stats_computed = 0
            total_cells_processed = 0
            for result in previous_results:
                if isinstance(result, dict):
                    result_data = result.get('result', {})
                    total_stats_computed += result_data.get('stats_inserted', 0)
                    total_cells_processed += result_data.get('cells_processed', 0)

            return [
                {
                    "task_id": f"{job_id[:8]}-s3-finalize",
                    "task_type": "h3_aggregation_finalize",
                    "parameters": {
                        "dataset_id": dataset_id,
                        "resolution": resolution,
                        "total_stats_computed": total_stats_computed,
                        "total_cells_processed": total_cells_processed,
                        "source_job_id": job_id
                    }
                }
            ]

        else:
            raise ValueError(f"Invalid stage {stage} for h3_raster_aggregation job (valid: 1-3)")

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization
    # ========================================================================

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create comprehensive job summary with aggregation statistics.

        Args:
            context: JobExecutionContext with task_results and parameters

        Returns:
            Comprehensive job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "H3RasterAggregationJob.finalize_job")

        if not context:
            logger.warning("⚠️ finalize_job called without context")
            return {
                "job_type": "h3_raster_aggregation",
                "status": "completed"
            }

        # Extract parameters
        params = context.parameters
        dataset_id = params.get('dataset_id', 'unknown')
        resolution = params.get('resolution', 0)
        container = params.get('container', '')
        blob_path = params.get('blob_path', '')
        iso3 = params.get('iso3')
        stats = params.get('stats', [])

        # Build scope description
        if iso3:
            scope = f"country: {iso3}"
        elif params.get('bbox'):
            scope = f"bbox: {params.get('bbox')}"
        elif params.get('polygon_wkt'):
            scope = "custom polygon"
        else:
            scope = "global"

        # Extract results from stages
        task_results = context.task_results

        # Stage 1: Inventory
        inventory_result = {}
        if len(task_results) >= 1 and task_results[0].result_data:
            inventory_result = task_results[0].result_data.get("result", {})

        total_cells = inventory_result.get("total_cells", 0)
        num_batches = inventory_result.get("num_batches", 0)

        # Stage 3: Finalization
        finalization_result = {}
        if len(task_results) >= 3 and task_results[-1].result_data:
            finalization_result = task_results[-1].result_data.get("result", {})

        total_stats = finalization_result.get("total_stats_computed", 0)

        logger.info(f"✅ Job {context.job_id} completed: {dataset_id} aggregation ({total_stats:,} stats)")

        return {
            "job_type": "h3_raster_aggregation",
            "job_id": context.job_id,
            "status": "completed",
            "dataset_id": dataset_id,
            "resolution": resolution,
            "scope": scope,
            "source": {
                "container": container,
                "blob_path": blob_path
            },
            "stats_computed": stats,
            "results": {
                "total_cells": total_cells,
                "total_stats": total_stats,
                "num_batches": num_batches
            },
            "metadata": {
                "workflow": "3-stage (inventory → compute → finalize)",
                "pattern": "JobBaseMixin"
            }
        }
