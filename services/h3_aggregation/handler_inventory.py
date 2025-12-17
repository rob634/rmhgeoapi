# ============================================================================
# CLAUDE CONTEXT - H3 INVENTORY CELLS HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - H3 Cell Inventory
# PURPOSE: Load H3 cells for aggregation scope and calculate batch ranges
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: h3_inventory_cells
# DEPENDENCIES: infrastructure.h3_repository
# ============================================================================
"""
H3 Inventory Cells Handler.

Stage 1 of H3 aggregation workflows. Loads cell count for scope,
calculates batch ranges for fan-out parallelism, and optionally
registers the dataset in stat_registry.

Usage:
    result = h3_inventory_cells({
        "resolution": 6,
        "iso3": "GRC",
        "batch_size": 1000,
        "dataset_id": "worldpop_2020",
        "stat_category": "raster_zonal"
    })
"""

from typing import Dict, Any
from util_logger import LoggerFactory, ComponentType

from .base import (
    resolve_spatial_scope,
    calculate_batch_ranges,
    validate_resolution,
    validate_dataset_id
)


def h3_inventory_cells(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Load H3 cells for aggregation scope and calculate batch ranges.

    Stage 1 handler that:
    1. Validates parameters
    2. Counts cells matching scope (iso3/bbox/polygon_wkt/global)
    3. Calculates batch ranges for fan-out parallelism
    4. Optionally registers dataset in stat_registry

    Args:
        params: Task parameters containing:
            - resolution (int): H3 resolution level (required)
            - iso3 (str, optional): ISO3 country code
            - bbox (list, optional): Bounding box [minx, miny, maxx, maxy]
            - polygon_wkt (str, optional): WKT polygon
            - batch_size (int): Cells per batch (default: 1000)
            - source_job_id (str): Job ID for tracking
            - dataset_id (str, optional): Dataset ID for stat_registry
            - stat_category (str, optional): Category for stat_registry
            - display_name (str, optional): Human-readable name
            - source_name (str, optional): Data source name
            - stat_types (list, optional): Available stat types

        context: Optional execution context (not used)

    Returns:
        Success dict with inventory results:
        {
            "success": True,
            "result": {
                "total_cells": int,
                "num_batches": int,
                "batch_ranges": [{"batch_index": 0, "batch_start": 0, "batch_size": 1000}, ...],
                "scope": {"scope_type": str, "description": str},
                "resolution": int,
                "dataset_registered": bool
            }
        }

    Raises:
        ValueError: If required parameters missing or invalid
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_inventory_cells")

    # STEP 1: Validate required parameters
    resolution = params.get('resolution')
    if resolution is None:
        raise ValueError("resolution is required")
    validate_resolution(resolution)

    batch_size = params.get('batch_size', 1000)
    source_job_id = params.get('source_job_id')

    # Optional registry parameters
    dataset_id = params.get('dataset_id')
    stat_category = params.get('stat_category')
    display_name = params.get('display_name')
    source_name = params.get('source_name')
    source_url = params.get('source_url')
    source_license = params.get('source_license')
    unit = params.get('unit')
    stat_types = params.get('stat_types')

    logger.info(f"📋 H3 Inventory - Resolution {resolution}, batch_size={batch_size}")

    try:
        from infrastructure.h3_repository import H3Repository

        h3_repo = H3Repository()

        # STEP 2: Resolve spatial scope
        scope = resolve_spatial_scope(params)
        iso3 = params.get('iso3')
        bbox = params.get('bbox')
        polygon_wkt = params.get('polygon_wkt')

        logger.info(f"   Scope: {scope['description']}")

        # STEP 3: Count cells matching scope
        total_cells = h3_repo.count_cells_for_aggregation(
            resolution=resolution,
            iso3=iso3,
            bbox=bbox,
            polygon_wkt=polygon_wkt
        )

        logger.info(f"   Found {total_cells:,} cells")

        # STEP 4: Calculate batch ranges
        batch_ranges = calculate_batch_ranges(total_cells, batch_size)
        num_batches = len(batch_ranges)

        logger.info(f"   Calculated {num_batches} batches (batch_size={batch_size})")

        # STEP 5: Register dataset in stat_registry (if dataset_id provided)
        dataset_registered = False
        if dataset_id and stat_category:
            validate_dataset_id(dataset_id)

            h3_repo.register_stat_dataset(
                id=dataset_id,
                stat_category=stat_category,
                display_name=display_name or dataset_id,
                description=f"Aggregation at H3 resolution {resolution}",
                source_name=source_name,
                source_url=source_url,
                source_license=source_license,
                resolution_range=[resolution],
                stat_types=stat_types,
                unit=unit
            )
            dataset_registered = True
            logger.info(f"   ✅ Registered dataset: {dataset_id}")

        # STEP 6: Build success result
        logger.info(f"✅ Inventory complete: {total_cells:,} cells in {num_batches} batches")

        return {
            "success": True,
            "result": {
                "total_cells": total_cells,
                "num_batches": num_batches,
                "batch_ranges": batch_ranges,
                "scope": {
                    "scope_type": scope["scope_type"],
                    "description": scope["description"]
                },
                "resolution": resolution,
                "batch_size": batch_size,
                "dataset_id": dataset_id,
                "dataset_registered": dataset_registered,
                "source_job_id": source_job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Inventory failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": f"Inventory failed: {str(e)}",
            "error_type": type(e).__name__
        }


# Export for handler registration
__all__ = ['h3_inventory_cells']
