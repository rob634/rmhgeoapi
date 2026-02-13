# ============================================================================
# CLAUDE CONTEXT - H3 AGGREGATION MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Module - H3 Aggregation Handlers
# PURPOSE: Zonal statistics and point aggregation for H3 hexagonal grids
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: h3_inventory_cells, h3_raster_zonal_stats, h3_aggregation_finalize, h3_register_dataset
# DEPENDENCIES: rasterstats, h3, shapely
# ============================================================================
"""
H3 Aggregation Module.

Provides task handlers for aggregating data to H3 hexagonal grids:
- Raster zonal statistics (local COGs)
- Planetary Computer raster aggregation
- Vector point aggregation (PostGIS)
- Vector line/polygon aggregation (future)

Architecture:
    Job → Stage 1: Inventory cells → Stage 2: Compute stats (fan-out) → Stage 3: Finalize

Usage:
    # Register handlers in services/__init__.py
    from services.h3_aggregation import ALL_HANDLERS as H3_AGG_HANDLERS
    ALL_HANDLERS.update(H3_AGG_HANDLERS)

Handlers:
    h3_inventory_cells: Load H3 cells for scope, return batch ranges
    h3_raster_zonal_stats: Compute zonal stats for cell batch
    h3_aggregation_finalize: Verify and update registry provenance
    h3_register_dataset: Register dataset in h3.dataset_registry
"""

from typing import Dict, Callable

# Import handlers
from .handler_inventory import h3_inventory_cells
from .handler_raster_zonal import h3_raster_zonal_stats
from .handler_finalize import h3_aggregation_finalize
from .handler_register import h3_register_dataset
from .handler_export import h3_export_validate, h3_export_build, h3_export_register

# Handler registry for this module
ALL_HANDLERS: Dict[str, Callable] = {
    "h3_inventory_cells": h3_inventory_cells,
    "h3_raster_zonal_stats": h3_raster_zonal_stats,
    "h3_aggregation_finalize": h3_aggregation_finalize,
    "h3_register_dataset": h3_register_dataset,
    # H3 Export handlers (28 DEC 2025)
    "h3_export_validate": h3_export_validate,
    "h3_export_build": h3_export_build,
    "h3_export_register": h3_export_register,
}

__all__ = [
    'ALL_HANDLERS',
]
