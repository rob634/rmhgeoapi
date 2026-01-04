# ============================================================================
# H3 RASTER AGGREGATION JOB
# ============================================================================
# STATUS: Jobs - 3-stage raster zonal statistics workflow
# PURPOSE: Compute zonal stats from COG rasters and store in h3.zonal_stats
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
H3 Raster Aggregation Job - 3-Stage Workflow.

Computes zonal statistics from COG rasters and stores results in h3.zonal_stats.
Supports multiple source types: Azure Blob Storage, Planetary Computer, or direct URLs.

3-Stage Workflow:
    Stage 1: Inventory cells for scope (iso3/bbox/polygon_wkt)
    Stage 2: Compute zonal stats (batched fan-out, N parallel tasks)
    Stage 3: Finalize (update registry provenance, verify counts)

Features:
    - Multiple source types: Azure Blob, Planetary Computer, direct URLs
    - Supports iso3, bbox, and polygon_wkt spatial scopes
    - Multiple stat types: mean, sum, min, max, count, std, median
    - Configurable batch size for memory management
    - Optional append_history mode (preserves existing values)
    - Dataset registry integration for metadata catalog

Usage (Azure):
    POST /api/jobs/submit/h3_raster_aggregation
    {
        "source_type": "azure",
        "container": "silver-cogs",
        "blob_path": "population/worldpop_2020.tif",
        "dataset_id": "worldpop_2020",
        "resolution": 6,
        "iso3": "GRC",
        "stats": ["sum", "mean", "count"]
    }

Usage (Planetary Computer):
    POST /api/jobs/submit/h3_raster_aggregation
    {
        "source_type": "planetary_computer",
        "collection": "cop-dem-glo-30",
        "item_id": "Copernicus_DSM_COG_10_N35_00_E023_00",
        "asset": "data",
        "dataset_id": "copdem_glo30_greece",
        "resolution": 6,
        "iso3": "GRC",
        "stats": ["mean", "min", "max"]
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
        # Source type (determines which parameters are required)
        'source_type': {
            'type': 'str',
            'default': 'azure',
            'enum': ['azure', 'planetary_computer', 'url'],
            'description': 'Source type: azure (Azure Blob), planetary_computer (PC STAC), url (direct URL)'
        },
        # Azure source parameters
        'container': {
            'type': 'str',
            'default': None,
            'description': 'Azure Blob Storage container name (required for source_type=azure)'
        },
        'blob_path': {
            'type': 'str',
            'default': None,
            'description': 'Path to COG file within container (required for source_type=azure)'
        },
        # Planetary Computer source parameters
        'collection': {
            'type': 'str',
            'default': None,
            'description': 'Planetary Computer collection ID (required for source_type=planetary_computer)'
        },
        'item_id': {
            'type': 'str',
            'default': None,
            'description': 'STAC item ID (single tile mode for source_type=planetary_computer)'
        },
        'source_id': {
            'type': 'str',
            'default': None,
            'description': 'Reference to h3.source_catalog for dynamic tile discovery (alternative to item_id)'
        },
        'asset': {
            'type': 'str',
            'default': 'data',
            'description': 'Asset key within STAC item (default: "data")'
        },
        'theme': {
            'type': 'str',
            'default': None,
            'description': 'Theme for partition routing (auto-detected from source_catalog if source_id provided)'
        },
        # Direct URL source parameter
        'cog_url': {
            'type': 'str',
            'default': None,
            'description': 'Direct HTTPS URL to COG (required for source_type=url)'
        },
        # Common parameters
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
        'nodata': {
            'type': 'float',
            'default': None,
            'description': 'Override nodata value (auto-detected from raster if not provided)'
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
    # CUSTOM VALIDATION: Source-specific parameter requirements
    # ========================================================================

    @classmethod
    def validate_job_parameters(cls, params: dict) -> dict:
        """
        Validate job parameters with source-type-specific requirements.

        Extends base validation to check:
        - Dataset must be registered in h3.dataset_registry (pre-flight validation)
        - Azure source: container + blob_path required
        - Planetary Computer source: collection + item_id required
        - URL source: cog_url required
        """
        # First, run base validation (applies schema defaults and type checks)
        validated = super().validate_job_parameters(params)

        # Get source_type (already has default from schema)
        source_type = validated.get('source_type', 'azure')

        # Validate source-specific requirements
        if source_type == 'azure':
            if not validated.get('container'):
                raise ValueError("'container' is required when source_type='azure'")
            if not validated.get('blob_path'):
                raise ValueError("'blob_path' is required when source_type='azure'")

        elif source_type == 'planetary_computer':
            if not validated.get('collection'):
                raise ValueError("'collection' is required when source_type='planetary_computer'")
            # item_id OR source_id required (source_id enables dynamic tile discovery)
            if not validated.get('item_id') and not validated.get('source_id'):
                raise ValueError("'item_id' or 'source_id' is required when source_type='planetary_computer'")

        elif source_type == 'url':
            if not validated.get('cog_url'):
                raise ValueError("'cog_url' is required when source_type='url'")

        # PRE-FLIGHT VALIDATION: Dataset must be registered
        # This check happens at job submission time, not runtime
        dataset_id = validated.get('dataset_id')
        if dataset_id:
            from infrastructure.h3_repository import H3Repository
            h3_repo = H3Repository()
            dataset = h3_repo.get_dataset(dataset_id)

            if not dataset:
                raise ValueError(
                    f"Dataset '{dataset_id}' not found in h3.dataset_registry. "
                    f"Register the dataset first using:\n"
                    f"  - POST /api/jobs/submit/h3_register_dataset (recommended)\n"
                    f"  - POST /api/h3/datasets (development/testing)\n"
                    f"See job type 'h3_register_dataset' for required parameters."
                )

            # Inject theme from registry for partition routing
            # This ensures Stage 2 handlers have the correct theme
            validated['theme'] = dataset.get('theme')

        return validated

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
        source_type = job_params.get('source_type', 'azure')
        dataset_id = job_params.get('dataset_id')
        band = job_params.get('band', 1)
        nodata = job_params.get('nodata')
        resolution = job_params.get('resolution')
        iso3 = job_params.get('iso3')
        bbox = job_params.get('bbox')
        polygon_wkt = job_params.get('polygon_wkt')
        stats = job_params.get('stats', ['mean', 'sum', 'count'])
        append_history = job_params.get('append_history', False)
        batch_size = job_params.get('batch_size', 1000)

        # Source-specific parameters
        container = job_params.get('container')  # Azure
        blob_path = job_params.get('blob_path')  # Azure
        collection = job_params.get('collection')  # Planetary Computer
        item_id = job_params.get('item_id')  # Planetary Computer (single tile mode)
        source_id = job_params.get('source_id')  # Planetary Computer (dynamic tile discovery)
        asset = job_params.get('asset', 'data')  # Planetary Computer
        cog_url = job_params.get('cog_url')  # Direct URL

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

                # Build task parameters based on source type
                task_params = {
                    "source_type": source_type,
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

                # Add source-specific parameters
                if source_type == 'azure':
                    task_params["container"] = container
                    task_params["blob_path"] = blob_path
                elif source_type == 'planetary_computer':
                    task_params["collection"] = collection
                    task_params["item_id"] = item_id
                    task_params["source_id"] = source_id  # For dynamic tile discovery
                    task_params["asset"] = asset
                elif source_type == 'url':
                    task_params["cog_url"] = cog_url

                # Add nodata if provided
                if nodata is not None:
                    task_params["nodata"] = nodata

                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-batch{batch_idx}",
                    "task_type": "h3_raster_zonal_stats",
                    "parameters": task_params
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
        source_type = params.get('source_type', 'azure')
        dataset_id = params.get('dataset_id', 'unknown')
        resolution = params.get('resolution', 0)
        iso3 = params.get('iso3')
        stats = params.get('stats', [])

        # Build source info based on source_type
        if source_type == 'azure':
            source_info = {
                "type": "azure",
                "container": params.get('container', ''),
                "blob_path": params.get('blob_path', '')
            }
        elif source_type == 'planetary_computer':
            source_info = {
                "type": "planetary_computer",
                "collection": params.get('collection', ''),
                "item_id": params.get('item_id', ''),
                "asset": params.get('asset', 'data')
            }
        else:  # url
            source_info = {
                "type": "url",
                "cog_url": params.get('cog_url', '')[:100] + "..."
            }

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
            "source": source_info,
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
