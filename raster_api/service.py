"""
Raster API Service Layer.

Business logic for raster convenience endpoints.
Coordinates between STAC client (item lookup) and TiTiler client (raster ops).
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .config import RasterAPIConfig, get_raster_api_config
from services.stac_client import STACClient, STACItem
from services.titiler_client import TiTilerClient, TiTilerResponse

logger = logging.getLogger(__name__)


@dataclass
class RasterServiceResponse:
    """Response from raster service operations."""
    success: bool
    status_code: int
    data: Optional[bytes] = None
    content_type: Optional[str] = None
    json_data: Optional[Dict] = None
    error: Optional[str] = None


class RasterAPIService:
    """
    Raster API business logic.

    Orchestrates STAC item lookup and TiTiler requests.
    """

    def __init__(self, config: Optional[RasterAPIConfig] = None):
        """Initialize service with configuration."""
        self.config = config or get_raster_api_config()
        self.stac_client = STACClient()
        self.titiler_client = TiTilerClient()

    async def close(self):
        """Close client connections."""
        await self.stac_client.close()
        await self.titiler_client.close()

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

        # Check named locations
        return self.config.named_locations.get(location.lower())

    def _validate_bbox(self, bbox: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Validate bbox string format.

        Args:
            bbox: Bounding box string "minx,miny,maxx,maxy"

        Returns:
            Tuple of (validated_bbox, error_message). One will be None.
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

            return bbox, None  # Return original string for TiTiler

        except ValueError:
            return None, f"Invalid bbox format: '{bbox}'. Use 'minx,miny,maxx,maxy' with numeric values"

    async def _get_stac_item(
        self,
        collection_id: str,
        item_id: str
    ) -> Tuple[Optional[STACItem], Optional[str]]:
        """
        Get STAC item, return (item, error).

        Returns:
            Tuple of (STACItem, None) on success or (None, error_message) on failure
        """
        response = await self.stac_client.get_item(collection_id, item_id)
        if not response.success:
            return None, response.error
        return response.item, None

    async def extract_bbox(
        self,
        collection_id: str,
        item_id: str,
        bbox: str,
        format: str = "tif",
        asset: str = "data",
        time_index: int = 1,
        colormap: Optional[str] = None,
        rescale: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> RasterServiceResponse:
        """
        Extract bbox from raster as image.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            bbox: Bounding box "minx,miny,maxx,maxy"
            format: Output format (tif, png, npy)
            asset: Asset key in STAC item
            time_index: Time index for Zarr (1-based)
            colormap: Colormap name for visualization
            rescale: Rescale range "min,max"
            width: Output width in pixels
            height: Output height in pixels

        Returns:
            RasterServiceResponse with image bytes
        """
        # Validate bbox
        validated_bbox, bbox_error = self._validate_bbox(bbox)
        if bbox_error:
            return RasterServiceResponse(success=False, status_code=400, error=bbox_error)

        # Get STAC item
        item, error = await self._get_stac_item(collection_id, item_id)
        if error:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Get asset URL
        asset_url = item.get_asset_url(asset)
        if not asset_url:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        # Build TiTiler params
        kwargs = {}
        if colormap:
            kwargs["colormap_name"] = colormap
        if rescale:
            kwargs["rescale"] = rescale
        if width:
            kwargs["width"] = width
        if height:
            kwargs["height"] = height

        # Route to correct TiTiler endpoint based on asset type
        if item.is_zarr(asset):
            variable = item.get_variable()
            if not variable:
                return RasterServiceResponse(
                    success=False,
                    status_code=400,
                    error="Cannot determine variable name for Zarr dataset"
                )

            response = await self.titiler_client.get_xarray_bbox(
                url=asset_url,
                bbox=bbox,
                variable=variable,
                bidx=time_index,
                format=format,
                **kwargs
            )
        else:
            response = await self.titiler_client.get_cog_bbox(
                url=asset_url,
                bbox=bbox,
                format=format,
                **kwargs
            )

        if not response.success:
            return RasterServiceResponse(
                success=False,
                status_code=response.status_code,
                error=response.error
            )

        return RasterServiceResponse(
            success=True,
            status_code=200,
            data=response.data,
            content_type=response.content_type
        )

    async def point_query(
        self,
        collection_id: str,
        item_id: str,
        location: str,
        asset: str = "data",
        time_index: int = 1
    ) -> RasterServiceResponse:
        """
        Get raster value at a point.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            location: Location as "lon,lat" or named location
            asset: Asset key in STAC item
            time_index: Time index for Zarr (1-based)

        Returns:
            RasterServiceResponse with JSON data
        """
        # Resolve location
        coords = self._resolve_location(location)
        if not coords:
            return RasterServiceResponse(
                success=False,
                status_code=400,
                error=f"Invalid location: {location}. Use 'lon,lat' or a named location."
            )

        lon, lat = coords

        # Get STAC item
        item, error = await self._get_stac_item(collection_id, item_id)
        if error:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Get asset URL
        asset_url = item.get_asset_url(asset)
        if not asset_url:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        # Route to correct TiTiler endpoint
        if item.is_zarr(asset):
            variable = item.get_variable()
            if not variable:
                return RasterServiceResponse(
                    success=False,
                    status_code=400,
                    error="Cannot determine variable name for Zarr dataset"
                )

            response = await self.titiler_client.get_xarray_point(
                url=asset_url,
                lon=lon,
                lat=lat,
                variable=variable,
                bidx=time_index
            )
        else:
            response = await self.titiler_client.get_cog_point(
                url=asset_url,
                lon=lon,
                lat=lat
            )

        if not response.success:
            return RasterServiceResponse(
                success=False,
                status_code=response.status_code,
                error=response.error
            )

        # Enrich response with context
        result = {
            "location": [lon, lat],
            "location_name": location if location in self.config.named_locations else None,
            "collection_id": collection_id,
            "item_id": item_id,
            "asset": asset,
            "time_index": time_index if item.is_zarr(asset) else None,
            "values": response.data.get("values") if isinstance(response.data, dict) else response.data
        }

        return RasterServiceResponse(
            success=True,
            status_code=200,
            json_data=result
        )

    async def clip_by_geometry(
        self,
        collection_id: str,
        item_id: str,
        geometry: Dict,
        format: str = "tif",
        asset: str = "data",
        time_index: int = 1,
        colormap: Optional[str] = None,
        rescale: Optional[str] = None
    ) -> RasterServiceResponse:
        """
        Clip raster to GeoJSON geometry.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            geometry: GeoJSON geometry dict
            format: Output format (tif, png)
            asset: Asset key in STAC item
            time_index: Time index for Zarr (1-based)
            colormap: Colormap name
            rescale: Rescale range

        Returns:
            RasterServiceResponse with clipped image
        """
        # Get STAC item
        item, error = await self._get_stac_item(collection_id, item_id)
        if error:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Get asset URL
        asset_url = item.get_asset_url(asset)
        if not asset_url:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        # Build kwargs
        kwargs = {}
        if colormap:
            kwargs["colormap_name"] = colormap
        if rescale:
            kwargs["rescale"] = rescale

        # Route to correct TiTiler endpoint
        if item.is_zarr(asset):
            variable = item.get_variable()
            if not variable:
                return RasterServiceResponse(
                    success=False,
                    status_code=400,
                    error="Cannot determine variable name for Zarr dataset"
                )

            response = await self.titiler_client.get_xarray_feature(
                url=asset_url,
                geometry=geometry,
                variable=variable,
                bidx=time_index,
                format=format,
                **kwargs
            )
        else:
            response = await self.titiler_client.get_cog_feature(
                url=asset_url,
                geometry=geometry,
                format=format,
                **kwargs
            )

        if not response.success:
            return RasterServiceResponse(
                success=False,
                status_code=response.status_code,
                error=response.error
            )

        return RasterServiceResponse(
            success=True,
            status_code=200,
            data=response.data,
            content_type=response.content_type
        )

    async def preview(
        self,
        collection_id: str,
        item_id: str,
        format: str = "png",
        asset: str = "data",
        time_index: int = 1,
        max_size: int = 512,
        colormap: Optional[str] = None,
        rescale: Optional[str] = None
    ) -> RasterServiceResponse:
        """
        Get preview image of raster.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            format: Output format (png, jpeg, webp)
            asset: Asset key in STAC item
            time_index: Time index for Zarr (1-based)
            max_size: Maximum dimension in pixels
            colormap: Colormap name
            rescale: Rescale range

        Returns:
            RasterServiceResponse with preview image
        """
        # Get STAC item
        item, error = await self._get_stac_item(collection_id, item_id)
        if error:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=error
            )

        # Get asset URL
        asset_url = item.get_asset_url(asset)
        if not asset_url:
            return RasterServiceResponse(
                success=False,
                status_code=404,
                error=f"Asset '{asset}' not found in item"
            )

        # Build kwargs
        kwargs = {}
        if colormap:
            kwargs["colormap_name"] = colormap
        if rescale:
            kwargs["rescale"] = rescale

        # Route to correct TiTiler endpoint
        if item.is_zarr(asset):
            variable = item.get_variable()
            if not variable:
                return RasterServiceResponse(
                    success=False,
                    status_code=400,
                    error="Cannot determine variable name for Zarr dataset"
                )

            response = await self.titiler_client.get_xarray_preview(
                url=asset_url,
                variable=variable,
                bidx=time_index,
                format=format,
                max_size=max_size,
                **kwargs
            )
        else:
            response = await self.titiler_client.get_cog_preview(
                url=asset_url,
                format=format,
                max_size=max_size,
                **kwargs
            )

        if not response.success:
            return RasterServiceResponse(
                success=False,
                status_code=response.status_code,
                error=response.error
            )

        return RasterServiceResponse(
            success=True,
            status_code=200,
            data=response.data,
            content_type=response.content_type
        )
