# ============================================================================
# XARRAY API MODULE
# ============================================================================
# STATUS: API module - Direct Zarr access for time-series operations
# PURPOSE: xarray + fsspec endpoints for efficient chunked reads
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: get_xarray_triggers
# DEPENDENCIES: services.stac_client, services.xarray_reader
# ============================================================================
"""
xarray API Portable Module.

Provides direct Zarr access endpoints for time-series operations.
Uses xarray + fsspec for efficient chunked reads (no TiTiler roundtrip).

Endpoints:
- GET /api/xarray/point/{collection}/{item} - Time-series at a point
- GET /api/xarray/statistics/{collection}/{item} - Regional stats over time
- GET /api/xarray/aggregate/{collection}/{item} - Temporal aggregation export

Integration (in function_app.py):
    from xarray_api import get_xarray_triggers

    for trigger in get_xarray_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Created: 18 DEC 2025
"""

from .triggers import get_xarray_triggers

__all__ = ['get_xarray_triggers']
