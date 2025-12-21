# ============================================================================
# CLAUDE CONTEXT - XARRAY API SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Layer - xarray direct access for time-series operations
# PURPOSE: Business logic for xarray endpoints - point timeseries, regional stats
# LAST_REVIEWED: 19 DEC 2025
# EXPORTS: XarrayAPIService
# DEPENDENCIES: services.stac_client, services.xarray_reader
# PORTABLE: Yes - uses config-independent service clients
# ============================================================================
"""
xarray API Service Layer (SYNC VERSION).

Business logic for xarray direct access endpoints:
- /api/xarray/timeseries/{collection}/{item} - Point time-series extraction
- /api/xarray/stats/{collection}/{item} - Regional statistics over time
- /api/xarray/aggregate/{collection}/{item} - Temporal aggregation

Coordinates between STAC client (item lookup) and xarray reader (Zarr ops).

PORTABILITY:
    This module is designed to work in both rmhgeoapi and rmhogcapi.
    Uses config-independent service clients (STACClient, XarrayReader).

SYNC VERSION (19 DEC 2025):
    Converted from async to sync for Reader API migration.
    All methods are synchronous - no async/await.
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime
import re

from .config import XarrayAPIConfig, get_xarray_api_config
from services.stac_client import STACClient, STACItem
from services.xarray_reader import XarrayReader, TimeSeriesResult, AggregationResult, RegionalStatsResult

logger = logging.getLogger(__name__)


@dataclass
class XarrayServiceResponse:
    """Response from xarray service operations."""
    success: bool
    status_code: int
    json_data: Optional[Dict] = None
    binary_data: Optional[bytes] = None
    content_type: Optional[str] = None
    error: Optional[str] = None


class XarrayAPIService:
    """
    xarray API business logic (SYNC VERSION).

    Orchestrates STAC item lookup and xarray Zarr reads.

    PORTABILITY:
        Works in both rmhgeoapi and rmhogcapi without modification.
        Uses config-independent service clients.

    Usage:
        service = XarrayAPIService()

        # Point timeseries (SYNC - no await)
        response = service.point_timeseries("collection", "item", "-77.0,38.9")

        # Regional statistics
        response = service.regional_statistics("collection", "item", "-77,-39,-76,-38")

        # Always close when done
        service.close()
    """

    def __init__(self, config: Optional[XarrayAPIConfig] = None):
        """Initialize service with configuration."""
        self.config = config or get_xarray_api_config()
        self.stac_client = STACClient()
        self.xarray_reader = XarrayReader(storage_account=self.config.storage_account)

    def close(self):
        """Close client connections."""
        self.stac_client.close()
        self.xarray_reader.close()

    def _resolve_location(self, location: str) -> Optional[Tuple[float, float]]:
        """
        Resolve location string to coordinates.

        Args:
            location: Either "lon,lat" or named location

        Returns:
            Tuple of (lon, lat) or None if not found
        """
        if "," in location:
            try:
                parts = location.split(",")
                return (float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                return None

        return self.config.named_locations.get(location.lower())

    def _validate_date(self, date_str: Optional[str], param_name: str) -> Optional[str]:
        """
        Validate ISO date string format.

        Args:
            date_str: Date string to validate (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            param_name: Parameter name for error messages

        Returns:
            Error message if invalid, None if valid
        """
        if date_str is None:
            return None

        # Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS formats
        iso_pattern = r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?)?$'
        if not re.match(iso_pattern, date_str):
            return f"Invalid {param_name} format: '{date_str}'. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"

        # Validate the date is parseable
        try:
            if 'T' in date_str:
                datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            else:
                datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return f"Invalid {param_name} date: '{date_str}'. Check month/day values."

        return None

    def _validate_bbox(self, bbox: str) -> Tuple[Optional[Tuple[float, float, float, float]], Optional[str]]:
        """
        Validate and parse bbox string.

        Args:
            bbox: Bounding box string "minx,miny,maxx,maxy"

        Returns:
            Tuple of (parsed_bbox, error_message). One will be None.
        """
        try:
            parts = bbox.split(",")
            if len(parts) != 4:
                return None, f"Invalid bbox: expected 4 values, got {len(parts)}"

            minx, miny, maxx, maxy = map(float, parts)

            # Validate coordinate ranges
            if not (-180 <= minx <= 180 and -180 <= maxx <= 180):
                return None, f"Invalid bbox: longitude must be between -180 and 180"
            if not (-90 <= miny <= 90 and -90 <= maxy <= 90):
                return None, f"Invalid bbox: latitude must be between -90 and 90"
            if minx >= maxx:
                return None, f"Invalid bbox: minx ({minx}) must be less than maxx ({maxx})"
            if miny >= maxy:
                return None, f"Invalid bbox: miny ({miny}) must be less than maxy ({maxy})"

            return (minx, miny, maxx, maxy), None

        except ValueError:
            return None, f"Invalid bbox format: '{bbox}'. Use 'minx,miny,maxx,maxy' with numeric values"

    def _get_stac_item(
        self,
        collection_id: str,
        item_id: str
    ) -> Tuple[Optional[STACItem], Optional[str]]:
        """Get STAC item, return (item, error)."""
        response = self.stac_client.get_item(collection_id, item_id)
        if not response.success:
            return None, response.error
        return response.item, None

    def point_timeseries(
        self,
        collection_id: str,
        item_id: str,
        location: str,
        asset: str = "data",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        aggregation: str = "none"
    ) -> XarrayServiceResponse:
        """
        Get time-series at a point.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            location: Location as "lon,lat" or named location
            asset: Asset key in STAC item
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            aggregation: Temporal aggregation (none, daily, monthly, yearly)

        Returns:
            XarrayServiceResponse with time-series JSON
        """
        # Validate date ranges
        date_error = self._validate_date(start_time, "start_time")
        if date_error:
            return XarrayServiceResponse(success=False, status_code=400, error=date_error)
        date_error = self._validate_date(end_time, "end_time")
        if date_error:
            return XarrayServiceResponse(success=False, status_code=400, error=date_error)

        # Resolve location
        coords = self._resolve_location(location)
        if not coords:
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Invalid location: {location}. Use 'lon,lat' or a named location."
            )

        lon, lat = coords

        # Get STAC item
        item, error = self._get_stac_item(collection_id, item_id)
        if error:
            return XarrayServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Check if it's a Zarr dataset
        if not item.is_zarr(asset):
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Item asset '{asset}' is not a Zarr dataset. Use /api/raster/ for COGs."
            )

        # Get asset URL and variable
        zarr_url = item.get_asset_url(asset)
        if not zarr_url:
            return XarrayServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        variable = item.get_variable()
        if not variable:
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error="Cannot determine variable name for Zarr dataset"
            )

        # Read time-series
        result = self.xarray_reader.get_point_timeseries(
            zarr_url=zarr_url,
            variable=variable,
            lon=lon,
            lat=lat,
            start_time=start_time,
            end_time=end_time,
            aggregation=aggregation
        )

        if not result.success:
            return XarrayServiceResponse(
                success=False,
                status_code=500,
                error=result.error
            )

        # Build response
        response_data = {
            "location": [lon, lat],
            "location_name": location if location in self.config.named_locations else None,
            "collection_id": collection_id,
            "item_id": item_id,
            "variable": variable,
            "unit": result.unit,
            "time_range": {
                "start": start_time,
                "end": end_time
            },
            "aggregation": aggregation,
            "time_series": [
                {"time": p.time, "value": p.value, "bidx": p.bidx}
                for p in result.time_series
            ],
            "statistics": result.statistics
        }

        return XarrayServiceResponse(
            success=True,
            status_code=200,
            json_data=response_data
        )

    def regional_statistics(
        self,
        collection_id: str,
        item_id: str,
        bbox: str,
        asset: str = "data",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        temporal_resolution: str = "monthly"
    ) -> XarrayServiceResponse:
        """
        Get regional statistics over time.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            bbox: Bounding box "minx,miny,maxx,maxy"
            asset: Asset key in STAC item
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            temporal_resolution: Time grouping (daily, monthly, yearly)

        Returns:
            XarrayServiceResponse with statistics JSON
        """
        # Validate date ranges
        date_error = self._validate_date(start_time, "start_time")
        if date_error:
            return XarrayServiceResponse(success=False, status_code=400, error=date_error)
        date_error = self._validate_date(end_time, "end_time")
        if date_error:
            return XarrayServiceResponse(success=False, status_code=400, error=date_error)

        # Validate and parse bbox
        bbox_tuple, bbox_error = self._validate_bbox(bbox)
        if bbox_error:
            return XarrayServiceResponse(success=False, status_code=400, error=bbox_error)

        # Get STAC item
        item, error = self._get_stac_item(collection_id, item_id)
        if error:
            return XarrayServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Check if it's a Zarr dataset
        if not item.is_zarr(asset):
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Item asset '{asset}' is not a Zarr dataset. Use /api/raster/ for COGs."
            )

        # Get asset URL and variable
        zarr_url = item.get_asset_url(asset)
        if not zarr_url:
            return XarrayServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        variable = item.get_variable()
        if not variable:
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error="Cannot determine variable name for Zarr dataset"
            )

        # Compute regional statistics
        result = self.xarray_reader.get_regional_statistics(
            zarr_url=zarr_url,
            variable=variable,
            bbox=bbox_tuple,
            start_time=start_time or "1900-01-01",
            end_time=end_time or "2100-12-31",
            temporal_resolution=temporal_resolution
        )

        if not result.success:
            return XarrayServiceResponse(
                success=False,
                status_code=500,
                error=result.error
            )

        # Build response
        response_data = {
            "bbox": list(bbox_tuple),
            "collection_id": collection_id,
            "item_id": item_id,
            "variable": variable,
            "time_range": {
                "start": start_time,
                "end": end_time
            },
            "temporal_resolution": temporal_resolution,
            "time_series": result.time_series
        }

        return XarrayServiceResponse(
            success=True,
            status_code=200,
            json_data=response_data
        )

    def temporal_aggregation(
        self,
        collection_id: str,
        item_id: str,
        bbox: str,
        asset: str = "data",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        aggregation: str = "mean",
        format: str = "json"
    ) -> XarrayServiceResponse:
        """
        Compute temporal aggregation over a region.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            bbox: Bounding box "minx,miny,maxx,maxy"
            asset: Asset key in STAC item
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            aggregation: Aggregation method (mean, max, min, sum)
            format: Output format (json, tif, png, npy)

        Returns:
            XarrayServiceResponse with aggregated data
        """
        # Validate date ranges
        date_error = self._validate_date(start_time, "start_time")
        if date_error:
            return XarrayServiceResponse(success=False, status_code=400, error=date_error)
        date_error = self._validate_date(end_time, "end_time")
        if date_error:
            return XarrayServiceResponse(success=False, status_code=400, error=date_error)

        # Validate and parse bbox
        bbox_tuple, bbox_error = self._validate_bbox(bbox)
        if bbox_error:
            return XarrayServiceResponse(success=False, status_code=400, error=bbox_error)

        # Get STAC item
        item, error = self._get_stac_item(collection_id, item_id)
        if error:
            return XarrayServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Check if it's a Zarr dataset
        if not item.is_zarr(asset):
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Item asset '{asset}' is not a Zarr dataset. Use /api/raster/ for COGs."
            )

        # Get asset URL and variable
        zarr_url = item.get_asset_url(asset)
        if not zarr_url:
            return XarrayServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        variable = item.get_variable()
        if not variable:
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error="Cannot determine variable name for Zarr dataset"
            )

        # Compute temporal aggregation
        result = self.xarray_reader.get_temporal_aggregation(
            zarr_url=zarr_url,
            variable=variable,
            bbox=bbox_tuple,
            start_time=start_time or "1900-01-01",
            end_time=end_time or "2100-12-31",
            aggregation=aggregation
        )

        if not result.success:
            return XarrayServiceResponse(
                success=False,
                status_code=500,
                error=result.error
            )

        # Format output
        if format == "json":
            # Return statistics only (data is too large for JSON)
            import numpy as np
            data = result.data
            response_data = {
                "bbox": list(bbox_tuple),
                "collection_id": collection_id,
                "item_id": item_id,
                "variable": variable,
                "aggregation": aggregation,
                "time_range": {
                    "start": start_time,
                    "end": end_time
                },
                "shape": list(data.shape),
                "statistics": {
                    "min": float(np.nanmin(data)),
                    "max": float(np.nanmax(data)),
                    "mean": float(np.nanmean(data)),
                    "std": float(np.nanstd(data)),
                    "valid_pixels": int(np.count_nonzero(~np.isnan(data)))
                }
            }
            return XarrayServiceResponse(
                success=True,
                status_code=200,
                json_data=response_data
            )

        elif format == "npy":
            # Return raw numpy array
            import numpy as np
            return XarrayServiceResponse(
                success=True,
                status_code=200,
                binary_data=result.data.tobytes(),
                content_type="application/octet-stream"
            )

        elif format in ["tif", "png"]:
            # Use output helpers
            from .output import create_geotiff, render_png

            if format == "tif":
                tif_bytes = create_geotiff(
                    result.data,
                    bbox_tuple,
                    result.lat_coords,
                    result.lon_coords
                )
                return XarrayServiceResponse(
                    success=True,
                    status_code=200,
                    binary_data=tif_bytes,
                    content_type="image/tiff"
                )
            else:  # png
                png_bytes = render_png(
                    result.data,
                    colormap=self.config.default_colormap
                )
                return XarrayServiceResponse(
                    success=True,
                    status_code=200,
                    binary_data=png_bytes,
                    content_type="image/png"
                )

        else:
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Unknown format: {format}"
            )
