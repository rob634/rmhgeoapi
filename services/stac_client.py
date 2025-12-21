# ============================================================================
# CLAUDE CONTEXT - INTERNAL STAC CLIENT
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Layer - Internal STAC API client for item resolution
# PURPOSE: Query internal STAC API to resolve collection/item to asset URLs
# LAST_REVIEWED: 19 DEC 2025
# EXPORTS: STACClient
# DEPENDENCIES: httpx (sync)
# PORTABLE: Yes - no config imports, works in rmhgeoapi and rmhogcapi
# ============================================================================
"""
Internal STAC Client Service (SYNC VERSION).

Queries our own STAC API (pgSTAC) to resolve:
- Collection metadata
- Item metadata
- Asset URLs (COG, Zarr, MosaicJSON)

Used by raster_api and xarray_api modules to look up asset URLs
from friendly collection/item identifiers.

PORTABILITY:
    This module is designed to work in both rmhgeoapi and rmhogcapi.
    It does NOT import from config - instead accepts base_url as constructor
    param or falls back to STAC_API_BASE_URL environment variable.

SYNC VERSION (19 DEC 2025):
    Converted from async to sync for Reader API migration.
    Uses httpx.Client instead of httpx.AsyncClient.
    All methods are synchronous - no async/await.
"""

import os
import httpx
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


# ============================================================================
# TTL CACHE FOR STAC LOOKUPS
# ============================================================================

class TTLCache:
    """
    Simple thread-safe TTL cache for STAC item lookups.

    Items expire after ttl_seconds and are cleaned up on access.
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000):
        """
        Initialize cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default 5 minutes)
            max_size: Maximum cache entries before eviction
        """
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get item from cache if not expired."""
        with self._lock:
            if key not in self._cache:
                return None

            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None

            return value

    def set(self, key: str, value: Any) -> None:
        """Set item in cache with TTL."""
        with self._lock:
            # Evict oldest entries if at max size
            if len(self._cache) >= self.max_size:
                self._evict_oldest()

            expiry = time.time() + self.ttl_seconds
            self._cache[key] = (value, expiry)

    def _evict_oldest(self) -> None:
        """Remove oldest 10% of entries."""
        if not self._cache:
            return

        # Sort by expiry time and remove oldest
        sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][1])
        to_remove = max(1, len(sorted_keys) // 10)
        for key in sorted_keys[:to_remove]:
            del self._cache[key]

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            now = time.time()
            valid = sum(1 for _, expiry in self._cache.values() if expiry > now)
            return {
                "total_entries": len(self._cache),
                "valid_entries": valid,
                "expired_entries": len(self._cache) - valid
            }


# Global cache instance (shared across requests in same process)
_stac_item_cache = TTLCache(ttl_seconds=300, max_size=500)
_stac_collection_cache = TTLCache(ttl_seconds=3600, max_size=100)  # Collections change rarely


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
    Internal STAC API client (SYNC VERSION).

    Queries our own STAC API to resolve collection/item identifiers
    to actual asset URLs.

    PORTABILITY:
        Works in both rmhgeoapi and rmhogcapi without modification.
        Does not import from config - uses constructor params or env vars.

    Usage:
        # Option 1: Explicit base_url
        client = STACClient(base_url="https://rmhogcapi.../api/stac")

        # Option 2: From environment variable STAC_API_BASE_URL
        client = STACClient()

        # Get single item (SYNC - no await)
        response = client.get_item("cmip6", "tasmax-ssp585")
        if response.success:
            zarr_url = response.item.get_asset_url("data")
            variable = response.item.get_variable()

        # Get collection
        response = client.get_collection("cmip6")

        # Always close when done
        client.close()
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        """
        Initialize STAC client.

        Args:
            base_url: STAC API base URL. If not provided, uses STAC_API_BASE_URL env var.
            timeout: Request timeout in seconds.

        Raises:
            ValueError: If no base_url provided and STAC_API_BASE_URL not set.
        """
        # Config-independent: accept param or use env var
        self.base_url = (base_url or os.getenv("STAC_API_BASE_URL", "")).rstrip('/')
        if not self.base_url:
            raise ValueError(
                "STACClient requires base_url parameter or STAC_API_BASE_URL environment variable"
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

    def get_item(
        self,
        collection_id: str,
        item_id: str,
        use_cache: bool = True
    ) -> STACClientResponse:
        """
        Get a single STAC item by collection and item ID.

        Args:
            collection_id: Collection identifier
            item_id: Item identifier
            use_cache: Whether to use cache (default True)

        Returns:
            STACClientResponse with item or error
        """
        cache_key = f"{collection_id}/{item_id}"

        # Check cache first
        if use_cache:
            cached_item = _stac_item_cache.get(cache_key)
            if cached_item is not None:
                logger.debug(f"STAC cache hit: {cache_key}")
                return STACClientResponse(
                    success=True,
                    status_code=200,
                    item=cached_item
                )

        url = f"{self.base_url}/collections/{collection_id}/items/{item_id}"
        client = self._get_client()

        try:
            response = client.get(url)

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

            # Store in cache
            if use_cache:
                _stac_item_cache.set(cache_key, item)
                logger.debug(f"STAC cache store: {cache_key}")

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

    def get_collection(self, collection_id: str, use_cache: bool = True) -> STACClientResponse:
        """
        Get STAC collection metadata.

        Args:
            collection_id: Collection identifier
            use_cache: Whether to use cache (default True)

        Returns:
            STACClientResponse with collection or error
        """
        # Check cache first
        if use_cache:
            cached_collection = _stac_collection_cache.get(collection_id)
            if cached_collection is not None:
                logger.debug(f"STAC collection cache hit: {collection_id}")
                return STACClientResponse(
                    success=True,
                    status_code=200,
                    collection=cached_collection
                )

        url = f"{self.base_url}/collections/{collection_id}"
        client = self._get_client()

        try:
            response = client.get(url)

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

            # Store in cache
            if use_cache:
                _stac_collection_cache.set(collection_id, collection)
                logger.debug(f"STAC collection cache store: {collection_id}")

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

    def list_items(
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

        client = self._get_client()

        try:
            response = client.get(url, params=params)

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


# ============================================================================
# CACHE MANAGEMENT FUNCTIONS
# ============================================================================

def get_stac_cache_stats() -> Dict[str, Any]:
    """
    Get statistics for STAC caches.

    Returns:
        Dict with cache statistics for items and collections
    """
    return {
        "item_cache": {
            **_stac_item_cache.stats(),
            "ttl_seconds": _stac_item_cache.ttl_seconds,
            "max_size": _stac_item_cache.max_size
        },
        "collection_cache": {
            **_stac_collection_cache.stats(),
            "ttl_seconds": _stac_collection_cache.ttl_seconds,
            "max_size": _stac_collection_cache.max_size
        }
    }


def clear_stac_caches() -> None:
    """Clear all STAC caches."""
    _stac_item_cache.clear()
    _stac_collection_cache.clear()
    logger.info("STAC caches cleared")
