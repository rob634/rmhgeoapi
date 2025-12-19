"""
xarray API Service Layer.

Business logic for xarray direct access endpoints.
Coordinates between STAC client (item lookup) and xarray reader (Zarr ops).
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime

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
    xarray API business logic.

    Orchestrates STAC item lookup and xarray Zarr reads.
    """

    def __init__(self, config: Optional[XarrayAPIConfig] = None):
        """Initialize service with configuration."""
        self.config = config or get_xarray_api_config()
        self.stac_client = STACClient()
        self.xarray_reader = XarrayReader(storage_account=self.config.storage_account)

    async def close(self):
        """Close client connections."""
        await self.stac_client.close()
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

    async def _get_stac_item(
        self,
        collection_id: str,
        item_id: str
    ) -> Tuple[Optional[STACItem], Optional[str]]:
        """Get STAC item, return (item, error)."""
        response = await self.stac_client.get_item(collection_id, item_id)
        if not response.success:
            return None, response.error
        return response.item, None

    async def point_timeseries(
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
        item, error = await self._get_stac_item(collection_id, item_id)
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

    async def regional_statistics(
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
        # Parse bbox
        try:
            parts = bbox.split(",")
            bbox_tuple = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
        except (ValueError, IndexError):
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Invalid bbox format: {bbox}. Use 'minx,miny,maxx,maxy'"
            )

        # Get STAC item
        item, error = await self._get_stac_item(collection_id, item_id)
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

    async def temporal_aggregation(
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
        # Parse bbox
        try:
            parts = bbox.split(",")
            bbox_tuple = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
        except (ValueError, IndexError):
            return XarrayServiceResponse(
                success=False,
                status_code=400,
                error=f"Invalid bbox format: {bbox}. Use 'minx,miny,maxx,maxy'"
            )

        # Get STAC item
        item, error = await self._get_stac_item(collection_id, item_id)
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
