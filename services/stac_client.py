# ============================================================================
# CLAUDE CONTEXT - INTERNAL STAC CLIENT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Layer - Internal STAC API client for item resolution
# PURPOSE: Query internal STAC API to resolve collection/item to asset URLs
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: STACClient
# DEPENDENCIES: httpx, config.app_config
# ============================================================================
"""
Internal STAC Client Service.

Queries our own STAC API (pgSTAC) to resolve:
- Collection metadata
- Item metadata
- Asset URLs (COG, Zarr, MosaicJSON)

Used by raster_api and xarray_api modules to look up asset URLs
from friendly collection/item identifiers.
"""

import httpx
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from config.app_config import get_config

logger = logging.getLogger(__name__)


@dataclass
class STACItem:
    """Parsed STAC item with asset information."""
    id: str
    collection: str
    geometry: Optional[Dict] = None
    bbox: Optional[List[float]] = None
    properties: Dict = field(default_factory=dict)
    assets: Dict = field(default_factory=dict)
    links: List[Dict] = field(default_factory=list)

    def get_asset_url(self, asset_key: str = "data") -> Optional[str]:
        """Get URL for specified asset."""
        asset = self.assets.get(asset_key)
        if asset:
            return asset.get("href")
        return None

    def get_asset_type(self, asset_key: str = "data") -> Optional[str]:
        """Get media type for specified asset."""
        asset = self.assets.get(asset_key)
        if asset:
            return asset.get("type")
        return None

    def is_zarr(self, asset_key: str = "data") -> bool:
        """Check if asset is a Zarr dataset."""
        media_type = self.get_asset_type(asset_key) or ""
        url = self.get_asset_url(asset_key) or ""
        return "zarr" in media_type.lower() or url.endswith(".zarr")

    def is_cog(self, asset_key: str = "data") -> bool:
        """Check if asset is a COG."""
        media_type = self.get_asset_type(asset_key) or ""
        url = self.get_asset_url(asset_key) or ""
        return (
            "geotiff" in media_type.lower() or
            "tiff" in media_type.lower() or
            url.endswith(".tif") or
            url.endswith(".tiff")
        )

    def get_variable(self) -> Optional[str]:
        """Get primary variable name for Zarr datasets."""
        # Check cube:variables extension
        cube_vars = self.properties.get("cube:variables", {})
        if cube_vars:
            return list(cube_vars.keys())[0]

        # Check xarray:variable property
        xarray_var = self.properties.get("xarray:variable")
        if xarray_var:
            return xarray_var

        # Check app:variable property
        app_var = self.properties.get("app:variable")
        if app_var:
            return app_var

        return None

    def get_time_dimension_size(self) -> Optional[int]:
        """Get number of time steps for Zarr datasets."""
        cube_dims = self.properties.get("cube:dimensions", {})
        time_dim = cube_dims.get("time", {})
        if "values" in time_dim:
            return len(time_dim["values"])
        return time_dim.get("size")


@dataclass
class STACCollection:
    """Parsed STAC collection metadata."""
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    extent: Optional[Dict] = None
    links: List[Dict] = field(default_factory=list)


@dataclass
class STACClientResponse:
    """Response wrapper for STAC API calls."""
    success: bool
    status_code: int
    item: Optional[STACItem] = None
    collection: Optional[STACCollection] = None
    items: Optional[List[STACItem]] = None
    error: Optional[str] = None


class STACClient:
    """
    Internal STAC API client.

    Queries our own STAC API to resolve collection/item identifiers
    to actual asset URLs.

    Usage:
        client = STACClient()

        # Get single item
        response = await client.get_item("cmip6", "tasmax-ssp585")
        if response.success:
            zarr_url = response.item.get_asset_url("data")
            variable = response.item.get_variable()

        # Get collection
        response = await client.get_collection("cmip6")
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        """
        Initialize STAC client.

        Args:
            base_url: STAC API base URL. If not provided, uses config.
            timeout: Request timeout in seconds.
        """
        config = get_config()
        self.base_url = (base_url or config.stac_api_base_url).rstrip('/')
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_item(
        self,
        collection_id: str,
        item_id: str
    ) -> STACClientResponse:
        """
        Get a single STAC item by collection and item ID.

        Args:
            collection_id: Collection identifier
            item_id: Item identifier

        Returns:
            STACClientResponse with item or error
        """
        url = f"{self.base_url}/collections/{collection_id}/items/{item_id}"
        client = await self._get_client()

        try:
            response = await client.get(url)

            if response.status_code == 404:
                return STACClientResponse(
                    success=False,
                    status_code=404,
                    error=f"STAC item not found: {collection_id}/{item_id}"
                )

            if response.status_code >= 400:
                return STACClientResponse(
                    success=False,
                    status_code=response.status_code,
                    error=f"STAC API error: {response.text[:200]}"
                )

            data = response.json()
            item = STACItem(
                id=data.get("id", item_id),
                collection=data.get("collection", collection_id),
                geometry=data.get("geometry"),
                bbox=data.get("bbox"),
                properties=data.get("properties", {}),
                assets=data.get("assets", {}),
                links=data.get("links", [])
            )

            return STACClientResponse(
                success=True,
                status_code=response.status_code,
                item=item
            )

        except httpx.TimeoutException:
            return STACClientResponse(
                success=False,
                status_code=504,
                error=f"STAC API timeout after {self.timeout}s"
            )
        except httpx.RequestError as e:
            return STACClientResponse(
                success=False,
                status_code=500,
                error=f"STAC API request error: {str(e)}"
            )
        except Exception as e:
            logger.exception(f"Unexpected error querying STAC: {e}")
            return STACClientResponse(
                success=False,
                status_code=500,
                error=f"Unexpected error: {str(e)}"
            )

    async def get_collection(self, collection_id: str) -> STACClientResponse:
        """
        Get STAC collection metadata.

        Args:
            collection_id: Collection identifier

        Returns:
            STACClientResponse with collection or error
        """
        url = f"{self.base_url}/collections/{collection_id}"
        client = await self._get_client()

        try:
            response = await client.get(url)

            if response.status_code == 404:
                return STACClientResponse(
                    success=False,
                    status_code=404,
                    error=f"STAC collection not found: {collection_id}"
                )

            if response.status_code >= 400:
                return STACClientResponse(
                    success=False,
                    status_code=response.status_code,
                    error=f"STAC API error: {response.text[:200]}"
                )

            data = response.json()
            collection = STACCollection(
                id=data.get("id", collection_id),
                title=data.get("title"),
                description=data.get("description"),
                extent=data.get("extent"),
                links=data.get("links", [])
            )

            return STACClientResponse(
                success=True,
                status_code=response.status_code,
                collection=collection
            )

        except httpx.TimeoutException:
            return STACClientResponse(
                success=False,
                status_code=504,
                error=f"STAC API timeout after {self.timeout}s"
            )
        except httpx.RequestError as e:
            return STACClientResponse(
                success=False,
                status_code=500,
                error=f"STAC API request error: {str(e)}"
            )
        except Exception as e:
            logger.exception(f"Unexpected error querying STAC: {e}")
            return STACClientResponse(
                success=False,
                status_code=500,
                error=f"Unexpected error: {str(e)}"
            )

    async def list_items(
        self,
        collection_id: str,
        limit: int = 10,
        bbox: Optional[str] = None
    ) -> STACClientResponse:
        """
        List items in a collection.

        Args:
            collection_id: Collection identifier
            limit: Maximum number of items to return
            bbox: Optional bounding box filter

        Returns:
            STACClientResponse with items list or error
        """
        url = f"{self.base_url}/collections/{collection_id}/items"
        params = {"limit": limit}
        if bbox:
            params["bbox"] = bbox

        client = await self._get_client()

        try:
            response = await client.get(url, params=params)

            if response.status_code >= 400:
                return STACClientResponse(
                    success=False,
                    status_code=response.status_code,
                    error=f"STAC API error: {response.text[:200]}"
                )

            data = response.json()
            features = data.get("features", [])

            items = [
                STACItem(
                    id=f.get("id"),
                    collection=f.get("collection", collection_id),
                    geometry=f.get("geometry"),
                    bbox=f.get("bbox"),
                    properties=f.get("properties", {}),
                    assets=f.get("assets", {}),
                    links=f.get("links", [])
                )
                for f in features
            ]

            return STACClientResponse(
                success=True,
                status_code=response.status_code,
                items=items
            )

        except httpx.TimeoutException:
            return STACClientResponse(
                success=False,
                status_code=504,
                error=f"STAC API timeout after {self.timeout}s"
            )
        except httpx.RequestError as e:
            return STACClientResponse(
                success=False,
                status_code=500,
                error=f"STAC API request error: {str(e)}"
            )
        except Exception as e:
            logger.exception(f"Unexpected error querying STAC: {e}")
            return STACClientResponse(
                success=False,
                status_code=500,
                error=f"Unexpected error: {str(e)}"
            )
