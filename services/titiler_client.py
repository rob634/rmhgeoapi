# ============================================================================
# CLAUDE CONTEXT - TITILER HTTP CLIENT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Layer - TiTiler proxy client for raster operations
# PURPOSE: HTTP client for TiTiler endpoints with STAC item URL resolution
# LAST_REVIEWED: 19 DEC 2025
# EXPORTS: TiTilerClient
# DEPENDENCIES: httpx (sync)
# PORTABLE: Yes - no config imports, works in rmhgeoapi and rmhogcapi
# ============================================================================
"""
TiTiler HTTP Client Service (SYNC VERSION).

Provides sync HTTP client for TiTiler endpoints:
- COG endpoints (/cog/...) for Cloud Optimized GeoTIFFs
- xarray endpoints (/xarray/...) for Zarr files
- PgSTAC endpoints (/searches/...) for mosaic queries

Used by raster_api module for convenience wrapper endpoints.

PORTABILITY:
    This module is designed to work in both rmhgeoapi and rmhogcapi.
    It does NOT import from config - instead accepts base_url as constructor
    param or falls back to TITILER_BASE_URL environment variable.

SYNC VERSION (19 DEC 2025):
    Converted from async to sync for Reader API migration.
    Uses httpx.Client instead of httpx.AsyncClient.
    All methods are synchronous - no async/await.
"""

import os
import httpx
import logging
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TiTilerResponse:
    """Response wrapper for TiTiler API calls."""
    success: bool
    status_code: int
    data: Optional[Union[Dict, bytes]] = None
    content_type: Optional[str] = None
    error: Optional[str] = None


class TiTilerClient:
    """
    Sync HTTP client for TiTiler tile server (SYNC VERSION).

    Supports three TiTiler deployment modes:
    - vanilla: Basic COG tile serving
    - pgstac: PgSTAC mosaic integration
    - xarray: Zarr/NetCDF support

    PORTABILITY:
        Works in both rmhgeoapi and rmhogcapi without modification.
        Does not import from config - uses constructor params or env vars.

    Usage:
        # Option 1: Explicit base_url
        client = TiTilerClient(base_url="https://titiler.../")

        # Option 2: From environment variable TITILER_BASE_URL
        client = TiTilerClient()

        # Get COG info (SYNC - no await)
        response = client.get_cog_info(cog_url)

        # Get point value from Zarr
        response = client.get_xarray_point(zarr_url, lon, lat, variable, bidx=1)

        # Extract bbox as GeoTIFF
        response = client.get_cog_bbox(cog_url, bbox, format="tif")

        # Always close when done
        client.close()
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        """
        Initialize TiTiler client.

        Args:
            base_url: TiTiler server URL. If not provided, uses TITILER_BASE_URL env var.
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If no base_url provided and TITILER_BASE_URL not set.
        """
        # Config-independent: accept param or use env var
        self.base_url = (base_url or os.getenv("TITILER_BASE_URL", "")).rstrip('/')
        if not self.base_url:
            raise ValueError(
                "TiTilerClient requires base_url parameter or TITILER_BASE_URL environment variable"
            )
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        """Get or create sync HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True
            )
        return self._client

    def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_body: Optional[Dict] = None,
        return_binary: bool = False
    ) -> TiTilerResponse:
        """
        Make HTTP request to TiTiler.

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path
            params: Query parameters
            json_body: JSON body for POST requests
            return_binary: If True, return raw bytes instead of JSON

        Returns:
            TiTilerResponse with result or error
        """
        url = f"{self.base_url}{endpoint}"
        client = self._get_client()

        try:
            if method == "GET":
                response = client.get(url, params=params)
            elif method == "POST":
                response = client.post(url, params=params, json=json_body)
            else:
                return TiTilerResponse(
                    success=False,
                    status_code=400,
                    error=f"Unsupported HTTP method: {method}"
                )

            if response.status_code >= 400:
                error_text = response.text[:500] if response.text else "Unknown error"
                return TiTilerResponse(
                    success=False,
                    status_code=response.status_code,
                    error=f"TiTiler error: {error_text}"
                )

            content_type = response.headers.get("content-type", "")

            if return_binary:
                return TiTilerResponse(
                    success=True,
                    status_code=response.status_code,
                    data=response.content,
                    content_type=content_type
                )
            else:
                return TiTilerResponse(
                    success=True,
                    status_code=response.status_code,
                    data=response.json() if "json" in content_type else {"raw": response.text},
                    content_type=content_type
                )

        except httpx.TimeoutException:
            return TiTilerResponse(
                success=False,
                status_code=504,
                error=f"TiTiler request timeout after {self.timeout}s"
            )
        except httpx.RequestError as e:
            return TiTilerResponse(
                success=False,
                status_code=500,
                error=f"TiTiler request error: {str(e)}"
            )
        except Exception as e:
            logger.exception(f"Unexpected error calling TiTiler: {e}")
            return TiTilerResponse(
                success=False,
                status_code=500,
                error=f"Unexpected error: {str(e)}"
            )

    # =========================================================================
    # COG Endpoints
    # =========================================================================

    def get_cog_info(self, url: str) -> TiTilerResponse:
        """Get COG metadata/info."""
        return self._request("GET", "/cog/info", params={"url": url})

    def get_cog_statistics(self, url: str) -> TiTilerResponse:
        """Get COG band statistics."""
        return self._request("GET", "/cog/statistics", params={"url": url})

    def get_cog_point(
        self,
        url: str,
        lon: float,
        lat: float,
        **kwargs
    ) -> TiTilerResponse:
        """
        Get COG value at a point.

        Args:
            url: COG URL
            lon: Longitude
            lat: Latitude
            **kwargs: Additional TiTiler parameters
        """
        params = {"url": url, **kwargs}
        return self._request("GET", f"/cog/point/{lon},{lat}", params=params)

    def get_cog_bbox(
        self,
        url: str,
        bbox: str,
        format: str = "tif",
        **kwargs
    ) -> TiTilerResponse:
        """
        Extract COG bbox as image.

        Args:
            url: COG URL
            bbox: Bounding box as "minx,miny,maxx,maxy"
            format: Output format (tif, png, npy)
            **kwargs: Additional TiTiler parameters (width, height, rescale, colormap_name)
        """
        params = {"url": url, **kwargs}
        return self._request(
            "GET",
            f"/cog/bbox/{bbox}.{format}",
            params=params,
            return_binary=True
        )

    def get_cog_preview(
        self,
        url: str,
        format: str = "png",
        max_size: int = 512,
        **kwargs
    ) -> TiTilerResponse:
        """
        Get COG preview image.

        Args:
            url: COG URL
            format: Output format (png, jpeg, webp)
            max_size: Maximum dimension in pixels
            **kwargs: Additional TiTiler parameters
        """
        params = {"url": url, "max_size": max_size, **kwargs}
        return self._request(
            "GET",
            f"/cog/preview.{format}",
            params=params,
            return_binary=True
        )

    def get_cog_feature(
        self,
        url: str,
        geometry: Dict,
        format: str = "tif",
        **kwargs
    ) -> TiTilerResponse:
        """
        Extract COG clipped to GeoJSON geometry.

        Args:
            url: COG URL
            geometry: GeoJSON geometry dict
            format: Output format (tif, png, npy)
            **kwargs: Additional TiTiler parameters
        """
        params = {"url": url, **kwargs}
        feature = {
            "type": "Feature",
            "properties": {},
            "geometry": geometry
        }
        return self._request(
            "POST",
            f"/cog/feature.{format}",
            params=params,
            json_body=feature,
            return_binary=True
        )

    # =========================================================================
    # xarray Endpoints (Zarr)
    # =========================================================================

    def get_xarray_info(
        self,
        url: str,
        variable: Optional[str] = None,
        decode_times: bool = False
    ) -> TiTilerResponse:
        """Get Zarr dataset info."""
        params = {
            "url": url,
            "decode_times": str(decode_times).lower()
        }
        if variable:
            params["variable"] = variable
        return self._request("GET", "/xarray/info", params=params)

    def get_xarray_point(
        self,
        url: str,
        lon: float,
        lat: float,
        variable: str,
        bidx: int = 1,
        decode_times: bool = False,
        **kwargs
    ) -> TiTilerResponse:
        """
        Get Zarr value at a point for specific time index.

        Args:
            url: Zarr URL
            lon: Longitude
            lat: Latitude
            variable: Variable name in dataset
            bidx: Band/time index (1-based)
            decode_times: Whether to decode time coordinates
            **kwargs: Additional parameters
        """
        params = {
            "url": url,
            "variable": variable,
            "bidx": bidx,
            "decode_times": str(decode_times).lower(),
            **kwargs
        }
        return self._request("GET", f"/xarray/point/{lon},{lat}", params=params)

    def get_xarray_bbox(
        self,
        url: str,
        bbox: str,
        variable: str,
        bidx: int = 1,
        format: str = "tif",
        decode_times: bool = False,
        **kwargs
    ) -> TiTilerResponse:
        """
        Extract Zarr bbox as image for specific time index.

        Args:
            url: Zarr URL
            bbox: Bounding box as "minx,miny,maxx,maxy"
            variable: Variable name
            bidx: Band/time index (1-based)
            format: Output format (tif, png, npy)
            decode_times: Whether to decode time coordinates
            **kwargs: Additional parameters (width, height, rescale, colormap_name)
        """
        params = {
            "url": url,
            "variable": variable,
            "bidx": bidx,
            "decode_times": str(decode_times).lower(),
            **kwargs
        }
        return self._request(
            "GET",
            f"/xarray/bbox/{bbox}.{format}",
            params=params,
            return_binary=True
        )

    def get_xarray_preview(
        self,
        url: str,
        variable: str,
        bidx: int = 1,
        format: str = "png",
        max_size: int = 512,
        decode_times: bool = False,
        **kwargs
    ) -> TiTilerResponse:
        """
        Get Zarr preview image for specific time index.

        Args:
            url: Zarr URL
            variable: Variable name
            bidx: Band/time index (1-based)
            format: Output format (png, jpeg, webp)
            max_size: Maximum dimension in pixels
            decode_times: Whether to decode time coordinates
            **kwargs: Additional parameters
        """
        params = {
            "url": url,
            "variable": variable,
            "bidx": bidx,
            "max_size": max_size,
            "decode_times": str(decode_times).lower(),
            **kwargs
        }
        return self._request(
            "GET",
            f"/xarray/preview.{format}",
            params=params,
            return_binary=True
        )

    def get_xarray_feature(
        self,
        url: str,
        geometry: Dict,
        variable: str,
        bidx: int = 1,
        format: str = "tif",
        decode_times: bool = False,
        **kwargs
    ) -> TiTilerResponse:
        """
        Extract Zarr clipped to GeoJSON geometry.

        Args:
            url: Zarr URL
            geometry: GeoJSON geometry dict
            variable: Variable name
            bidx: Band/time index (1-based)
            format: Output format (tif, png, npy)
            decode_times: Whether to decode time coordinates
            **kwargs: Additional parameters
        """
        params = {
            "url": url,
            "variable": variable,
            "bidx": bidx,
            "decode_times": str(decode_times).lower(),
            **kwargs
        }
        feature = {
            "type": "Feature",
            "properties": {},
            "geometry": geometry
        }
        return self._request(
            "POST",
            f"/xarray/feature.{format}",
            params=params,
            json_body=feature,
            return_binary=True
        )

    # =========================================================================
    # Health Check
    # =========================================================================

    def health_check(self) -> TiTilerResponse:
        """Check TiTiler server health."""
        return self._request("GET", "/healthz")
