# ============================================================================
# CLAUDE CONTEXT - TITILER SEARCH SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - TiTiler-PgSTAC search registration and URL generation
# PURPOSE: Register pgSTAC searches with TiTiler and generate visualization URLs
# LAST_REVIEWED: 12 NOV 2025
# EXPORTS: TiTilerSearchService class
# INTERFACES: Service layer for TiTiler-PgSTAC integration
# PYDANTIC_MODELS: None - uses dicts for search payloads
# DEPENDENCIES: httpx (async HTTP client), config, typing
# SOURCE: TiTiler-PgSTAC API endpoints (search registration)
# SCOPE: TiTiler search registration for OAuth-only mosaic pattern
# VALIDATION: HTTP response validation, search_id verification
# PATTERNS: Service layer, Async HTTP
# ENTRY_POINTS: TiTilerSearchService().register_search(), generate_*_url()
# INDEX:
#   - TiTilerSearchService class: Line 60
#   - register_search: Line 100
#   - generate_viewer_url: Line 180
#   - generate_tilejson_url: Line 200
#   - generate_tiles_url: Line 220
#   - validate_search: Line 240
# ============================================================================

"""
TiTiler-PgSTAC Search Service

Manages registration of pgSTAC searches with TiTiler for OAuth-only mosaic visualization.
Replaces MosaicJSON pattern which requires two-tier authentication (HTTPS + OAuth).

Key Responsibilities:
- Register pgSTAC searches via TiTiler API
- Generate viewer/tilejson/tiles URLs for collections
- Validate search registration
- Handle HTTP errors gracefully

Strategy:
- pgSTAC searches use OAuth Managed Identity throughout (no SAS tokens)
- Searches are dynamic (always reflect current collection contents)
- Search IDs are stored in collection metadata for reuse

Author: Robert and Geospatial Claude Legion
Date: 12 NOV 2025
"""

from typing import Dict, Any, Optional
import urllib.parse

try:
    import httpx
except ImportError:
    httpx = None

from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "TiTilerSearchService")


class TiTilerSearchService:
    """
    Service for registering pgSTAC searches with TiTiler-PgSTAC.

    Handles all TiTiler search registration and URL generation for the
    OAuth-only mosaic pattern. Uses async HTTP for non-blocking operations.

    Why This Pattern:
    - MosaicJSON requires two-tier auth (HTTPS for JSON + OAuth for COGs)
    - pgSTAC searches use OAuth throughout (Managed Identity only)
    - Searches are dynamic (always reflect current collection state)

    Author: Robert and Geospatial Claude Legion
    Date: 12 NOV 2025
    """

    def __init__(self, titiler_base_url: Optional[str] = None):
        """
        Initialize TiTiler search service.

        Args:
            titiler_base_url: TiTiler base URL (uses config if not provided)
        """
        self.config = get_config()
        self.titiler_base_url = (titiler_base_url or self.config.titiler_base_url).rstrip('/')

        if not httpx:
            logger.warning("httpx not available - search registration will fail")

    async def register_search(
        self,
        collection_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Register pgSTAC search with TiTiler.

        Creates a new pgSTAC search in TiTiler that queries all items in a collection.
        The search is stored in TiTiler and assigned a unique search_id.

        Args:
            collection_id: STAC collection ID to create search for
            metadata: Optional metadata for the search (CQL2 filters, etc.)

        Returns:
            Dict with search registration details:
            {
                "id": str,              # Search ID (use for URLs)
                "search": dict,         # CQL2 search payload
                "metadata": dict,       # Search metadata
                "links": list           # HAL links to search endpoints
            }

        Raises:
            RuntimeError: If search registration fails
            ImportError: If httpx not installed

        Example:
            >>> service = TiTilerSearchService()
            >>> result = await service.register_search("cogs")
            >>> search_id = result["id"]
            >>> print(f"Registered search: {search_id}")
        """
        if not httpx:
            raise ImportError("httpx required for search registration")

        logger.info(f"🔄 Registering pgSTAC search for collection: {collection_id}")

        # Build CQL2 search payload
        # Query all items in collection (no filters)
        search_payload = {
            "collections": [collection_id],
            "filter-lang": "cql2-json"
        }

        # Add metadata with default assets if not provided
        # TiTiler-PgSTAC requires assets to be specified for rendering
        if metadata:
            search_payload["metadata"] = metadata
        else:
            # Default: use "data" asset (standard for our STAC items)
            search_payload["metadata"] = {
                "assets": ["data"]  # Asset name from STAC items
            }

        logger.debug(f"   Search payload: {search_payload}")

        try:
            # POST to TiTiler /searches/register endpoint
            url = f"{self.titiler_base_url}/searches/register"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=search_payload
                )
                response.raise_for_status()

                result = response.json()
                search_id = result.get("id")

                logger.info(f"✅ Search registered: {search_id}")
                logger.debug(f"   Search result: {result}")

                return result

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP error registering search: {e.response.status_code}")
            logger.error(f"   Response: {e.response.text}")
            raise RuntimeError(f"TiTiler search registration failed: {e}")

        except httpx.RequestError as e:
            logger.error(f"❌ Request error registering search: {e}")
            raise RuntimeError(f"TiTiler request failed: {e}")

        except Exception as e:
            logger.error(f"❌ Unexpected error registering search: {e}")
            raise RuntimeError(f"Search registration failed: {e}")

    def generate_viewer_url(self, search_id: str) -> str:
        """
        Generate TiTiler viewer URL for pgSTAC search.

        Args:
            search_id: Search ID from register_search()

        Returns:
            Interactive map viewer URL

        Example:
            >>> url = service.generate_viewer_url("abc123")
            >>> print(url)
            'https://rmhtitiler-.../searches/abc123/map'
        """
        url = f"{self.titiler_base_url}/searches/{search_id}/viewer"
        logger.debug(f"   Generated viewer URL: {url}")
        return url

    def generate_tilejson_url(self, search_id: str) -> str:
        """
        Generate TileJSON URL for pgSTAC search.

        TileJSON spec provides metadata for web map integration
        (bounds, minzoom, maxzoom, tile URLs).

        Args:
            search_id: Search ID from register_search()

        Returns:
            TileJSON specification URL

        Example:
            >>> url = service.generate_tilejson_url("abc123")
            >>> print(url)
            'https://rmhtitiler-.../searches/abc123/WebMercatorQuad/tilejson.json'
        """
        url = f"{self.titiler_base_url}/searches/{search_id}/WebMercatorQuad/tilejson.json"
        logger.debug(f"   Generated TileJSON URL: {url}")
        return url

    def generate_tiles_url(self, search_id: str) -> str:
        """
        Generate XYZ tile URL template for pgSTAC search.

        Returns templated URL for use in web maps (Leaflet, OpenLayers, etc.).
        The {z}/{x}/{y} placeholders are replaced by the mapping library.

        Args:
            search_id: Search ID from register_search()

        Returns:
            Templated XYZ tile URL

        Example:
            >>> url = service.generate_tiles_url("abc123")
            >>> print(url)
            'https://rmhtitiler-.../searches/abc123/WebMercatorQuad/tiles/{z}/{x}/{y}'
        """
        url = f"{self.titiler_base_url}/searches/{search_id}/WebMercatorQuad/tiles/{{z}}/{{x}}/{{y}}"
        logger.debug(f"   Generated tiles URL: {url}")
        return url

    async def validate_search(self, search_id: str) -> bool:
        """
        Validate that registered search exists in TiTiler.

        Args:
            search_id: Search ID to validate

        Returns:
            True if search exists and is accessible

        Note:
            This is a lightweight validation - just checks if GET succeeds.
            Does not validate tile rendering or bounds.
        """
        if not httpx:
            logger.warning("httpx not available - skipping validation")
            return False

        logger.debug(f"🔍 Validating search: {search_id}")

        try:
            url = f"{self.titiler_base_url}/searches/{search_id}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                logger.debug(f"   ✅ Search exists: {search_id}")
                return True

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"   ❌ Search not found: {search_id}")
            else:
                logger.error(f"   ❌ HTTP error validating search: {e.response.status_code}")
            return False

        except Exception as e:
            logger.error(f"   ❌ Error validating search: {e}")
            return False


# Export the service class
__all__ = ['TiTilerSearchService']
