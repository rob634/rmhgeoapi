# ============================================================================
# CLAUDE CONTEXT - H3 AGGREGATION BASE UTILITIES
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Utilities - H3 Aggregation Shared Code
# PURPOSE: Common utilities for H3 aggregation handlers
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: resolve_spatial_scope, calculate_batch_ranges, validate_resolution
# DEPENDENCIES: shapely
# ============================================================================
"""
H3 Aggregation Base Utilities.

Provides shared functions for all H3 aggregation handlers:
- Spatial scope resolution (iso3 → bbox → polygon_wkt priority)
- Batch range calculation for fan-out parallelism
- Resolution validation
- Common error handling patterns

Usage:
    from services.h3_aggregation.base import resolve_spatial_scope, calculate_batch_ranges

    # In handler:
    scope = resolve_spatial_scope(params)
    batches = calculate_batch_ranges(total_cells=10000, batch_size=1000)
"""

from typing import Dict, Any, List, Optional, Tuple
from math import ceil

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_aggregation.base")


# ============================================================================
# SPATIAL SCOPE RESOLUTION
# ============================================================================

def resolve_spatial_scope(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve spatial scope from job parameters.

    Priority order: iso3 → bbox → polygon_wkt → None (all cells)

    Parameters:
    ----------
    params : Dict[str, Any]
        Job parameters containing optional:
        - iso3: str (ISO 3166-1 alpha-3 country code)
        - bbox: List[float] ([minx, miny, maxx, maxy])
        - polygon_wkt: str (WKT polygon)

    Returns:
    -------
    Dict[str, Any]
        Resolved scope with keys:
        - scope_type: 'iso3' | 'bbox' | 'polygon_wkt' | 'global'
        - scope_value: The actual value (country code, bbox list, WKT, or None)
        - description: Human-readable scope description

    Example:
    -------
    >>> params = {"iso3": "GRC", "resolution": 6}
    >>> scope = resolve_spatial_scope(params)
    >>> scope["scope_type"]
    'iso3'
    >>> scope["scope_value"]
    'GRC'
    """
    iso3 = params.get('iso3')
    bbox = params.get('bbox')
    polygon_wkt = params.get('polygon_wkt')

    if iso3:
        logger.info(f"🎯 Spatial scope: country {iso3}")
        return {
            "scope_type": "iso3",
            "scope_value": iso3,
            "description": f"Country: {iso3}"
        }

    if bbox:
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"bbox must be [minx, miny, maxx, maxy], got: {bbox}")
        logger.info(f"🎯 Spatial scope: bbox {bbox}")
        return {
            "scope_type": "bbox",
            "scope_value": bbox,
            "description": f"Bounding box: [{bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}]"
        }

    if polygon_wkt:
        # Validate WKT
        try:
            from shapely import wkt
            geom = wkt.loads(polygon_wkt)
            if not geom.is_valid:
                raise ValueError(f"Invalid polygon geometry: {geom.validation_reason}")
        except Exception as e:
            raise ValueError(f"Invalid polygon_wkt: {e}")

        logger.info(f"🎯 Spatial scope: custom polygon")
        return {
            "scope_type": "polygon_wkt",
            "scope_value": polygon_wkt,
            "description": "Custom polygon"
        }

    logger.info("🎯 Spatial scope: global (all cells)")
    return {
        "scope_type": "global",
        "scope_value": None,
        "description": "Global (all cells)"
    }


def scope_to_where_clause(scope: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """
    Convert scope to SQL WHERE clause components.

    Parameters:
    ----------
    scope : Dict[str, Any]
        Scope dict from resolve_spatial_scope()

    Returns:
    -------
    Tuple[str, List[Any]]
        (WHERE clause fragment, list of parameters)
        Returns ("", []) for global scope

    Example:
    -------
    >>> scope = {"scope_type": "iso3", "scope_value": "GRC"}
    >>> clause, params = scope_to_where_clause(scope)
    >>> clause
    'a.iso3 = %s'
    >>> params
    ['GRC']
    """
    scope_type = scope["scope_type"]
    scope_value = scope["scope_value"]

    if scope_type == "iso3":
        # Requires JOIN to h3.cell_admin0
        return "a.iso3 = %s", [scope_value]

    if scope_type == "bbox":
        minx, miny, maxx, maxy = scope_value
        return (
            "ST_Intersects(c.geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))",
            [minx, miny, maxx, maxy]
        )

    if scope_type == "polygon_wkt":
        return (
            "ST_Intersects(c.geom, ST_GeomFromText(%s, 4326))",
            [scope_value]
        )

    # Global scope - no filter
    return "", []


# ============================================================================
# BATCH RANGE CALCULATION
# ============================================================================

def calculate_batch_ranges(
    total_cells: int,
    batch_size: int
) -> List[Dict[str, int]]:
    """
    Calculate batch ranges for fan-out parallelism.

    Parameters:
    ----------
    total_cells : int
        Total number of cells to process
    batch_size : int
        Number of cells per batch

    Returns:
    -------
    List[Dict[str, int]]
        List of batch dicts with keys:
        - batch_index: int (0-based)
        - batch_start: int (offset)
        - batch_size: int (may be smaller for last batch)

    Example:
    -------
    >>> ranges = calculate_batch_ranges(total_cells=2500, batch_size=1000)
    >>> len(ranges)
    3
    >>> ranges[0]
    {'batch_index': 0, 'batch_start': 0, 'batch_size': 1000}
    >>> ranges[2]
    {'batch_index': 2, 'batch_start': 2000, 'batch_size': 500}
    """
    if total_cells <= 0:
        return []

    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got: {batch_size}")

    num_batches = ceil(total_cells / batch_size)
    ranges = []

    for i in range(num_batches):
        batch_start = i * batch_size
        remaining = total_cells - batch_start
        actual_size = min(batch_size, remaining)

        ranges.append({
            "batch_index": i,
            "batch_start": batch_start,
            "batch_size": actual_size
        })

    logger.debug(f"📦 Calculated {len(ranges)} batches for {total_cells:,} cells (batch_size={batch_size})")
    return ranges


# ============================================================================
# VALIDATION UTILITIES
# ============================================================================

def validate_resolution(resolution: int) -> None:
    """
    Validate H3 resolution is in valid range.

    Parameters:
    ----------
    resolution : int
        H3 resolution level

    Raises:
    ------
    ValueError
        If resolution is outside 0-15 range
    """
    if not isinstance(resolution, int) or resolution < 0 or resolution > 15:
        raise ValueError(f"H3 resolution must be 0-15, got: {resolution}")


def validate_stat_types(stat_types: List[str]) -> None:
    """
    Validate stat types are supported.

    Parameters:
    ----------
    stat_types : List[str]
        List of stat type names

    Raises:
    ------
    ValueError
        If any stat type is not supported
    """
    SUPPORTED_STATS = {'mean', 'sum', 'min', 'max', 'count', 'std', 'median', 'range'}

    invalid = set(stat_types) - SUPPORTED_STATS
    if invalid:
        raise ValueError(
            f"Unsupported stat types: {invalid}. "
            f"Supported: {SUPPORTED_STATS}"
        )


def validate_dataset_id(dataset_id: str) -> None:
    """
    Validate dataset ID format.

    Parameters:
    ----------
    dataset_id : str
        Dataset identifier

    Raises:
    ------
    ValueError
        If dataset_id is empty or too long
    """
    if not dataset_id:
        raise ValueError("dataset_id is required")

    if len(dataset_id) > 100:
        raise ValueError(f"dataset_id must be ≤100 chars, got: {len(dataset_id)}")

    # Only allow alphanumeric, underscore, hyphen
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', dataset_id):
        raise ValueError(
            f"dataset_id must contain only alphanumeric, underscore, hyphen. "
            f"Got: {dataset_id}"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'resolve_spatial_scope',
    'scope_to_where_clause',
    'calculate_batch_ranges',
    'validate_resolution',
    'validate_stat_types',
    'validate_dataset_id',
]
