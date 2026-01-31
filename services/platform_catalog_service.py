# ============================================================================
# PLATFORM CATALOG SERVICE - B2B STAC Access
# ============================================================================
# STATUS: Service - B2B catalog lookup and asset URL generation
# PURPOSE: Provide DDH-identifier-based STAC access for B2B integration
# CREATED: 16 JAN 2026
# EPIC: F12.8 API Documentation Hub - B2B STAC Catalog Access
# ============================================================================
"""
Platform Catalog Service - B2B STAC Access for DDH Integration.

Provides DDH-identifier-based STAC lookup and asset URL generation.
This is the service layer for B2B catalog endpoints that allow DDH
to verify processing results and retrieve asset URLs.

Use Cases:
    1. Lookup: DDH verifies STAC item exists using their identifiers
    2. Assets: DDH retrieves COG URLs and TiTiler preview URLs
    3. Metadata: DDH gets bbox, temporal extent for catalog display

Architecture:
    DDH Identifiers → api_requests → job → result_data → STAC IDs → pgstac.items

    This service uses the Platform thin-tracking pattern to find STAC items:
    1. Generate request_id from DDH identifiers
    2. Lookup api_request → job_id
    3. Get job result → stac IDs (collection_id, stac_item_id)
    4. Verify STAC item exists in pgstac

Exports:
    PlatformCatalogService: Service class for B2B catalog operations
    get_platform_catalog_service: Singleton factory

Dependencies:
    infrastructure.PlatformRepository: Platform thin-tracking
    infrastructure.JobRepository: CoreMachine job lookup
    infrastructure.PgStacRepository: STAC catalog queries
"""

from typing import Dict, Any, Optional, List
from urllib.parse import quote_plus
import logging

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PlatformCatalogService")


class PlatformCatalogService:
    """
    Service for B2B STAC catalog access.

    Provides DDH-identifier-based lookup and asset URL generation
    for the Platform Catalog API endpoints.

    Usage:
        service = PlatformCatalogService()

        # Lookup by DDH identifiers
        result = service.lookup_by_ddh_ids("dataset-1", "res-001", "v1.0")

        # Get asset URLs with TiTiler
        assets = service.get_asset_urls("collection-1", "item-1")
    """

    def __init__(self):
        """Initialize with repository dependencies."""
        from infrastructure import PlatformRepository, JobRepository
        from infrastructure.pgstac_repository import PgStacRepository
        from config import get_config

        self._platform_repo = PlatformRepository()
        self._job_repo = JobRepository()
        self._stac_repo = PgStacRepository()
        self._config = get_config()

        logger.debug("PlatformCatalogService initialized")

    # =========================================================================
    # LOOKUP OPERATIONS
    # =========================================================================

    def lookup_by_ddh_ids(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Dict[str, Any]:
        """
        Lookup STAC item by DDH identifiers.

        This is the primary B2B lookup method. DDH provides their identifiers
        and we return whether a STAC item exists and its location.

        Strategy:
            1. Generate request_id from DDH IDs (SHA256 hash)
            2. Lookup api_request → job_id (Platform thin tracking)
            3. Get job result → stac IDs (collection_id, stac_item_id)
            4. Verify STAC item exists in pgstac

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            Dict with lookup results:
            - If found: {"found": true, "stac": {...}, "processing": {...}}
            - If not found: {"found": false, "reason": "..."}

        Example:
            >>> result = service.lookup_by_ddh_ids("flood-data", "res-001", "v1.0")
            >>> if result["found"]:
            ...     print(f"STAC item: {result['stac']['collection_id']}/{result['stac']['item_id']}")
        """
        from config import generate_platform_request_id

        logger.info(
            f"🔍 Catalog lookup: dataset={dataset_id}, "
            f"resource={resource_id}, version={version_id}"
        )

        # Step 1: Generate request_id from DDH identifiers
        request_id = generate_platform_request_id(dataset_id, resource_id, version_id)
        logger.debug(f"   Generated request_id: {request_id[:16]}...")

        # Step 2: Lookup via Platform thin tracking
        api_request = self._platform_repo.get_request(request_id)

        if not api_request:
            logger.debug("   No Platform request found")
            return {
                "found": False,
                "reason": "no_platform_request",
                "message": "No Platform request found for these DDH identifiers. "
                           "The data may not have been submitted through the Platform API.",
                "suggestion": "Submit the data via POST /api/platform/raster or /api/platform/submit"
            }

        # Step 3: Get job result
        job = self._job_repo.get_job(api_request.job_id)

        if not job:
            logger.warning(f"   Job {api_request.job_id} not found")
            return {
                "found": False,
                "reason": "job_not_found",
                "message": f"CoreMachine job {api_request.job_id[:16]}... not found",
                "request_id": request_id
            }

        # Check job status
        job_status = job.status.value if hasattr(job.status, 'value') else str(job.status)

        if job_status != "completed":
            logger.debug(f"   Job status: {job_status}")
            return {
                "found": False,
                "reason": "job_not_completed",
                "message": f"Job is {job_status}. STAC item will be available when job completes.",
                "job_status": job_status,
                "request_id": request_id,
                "job_id": api_request.job_id,
                "status_url": f"/api/platform/status/{request_id}"
            }

        # Step 4: Extract STAC IDs from job result
        # V0.8 FIX (30 JAN 2026): STAC info is nested under 'stac' key
        result_data = job.result_data or {}
        stac_data = result_data.get("stac", {})
        collection_id = stac_data.get("collection_id")
        item_id = stac_data.get("item_id")

        if not collection_id or not item_id:
            logger.warning("   STAC IDs not in job result")
            return {
                "found": False,
                "reason": "stac_ids_missing",
                "message": "Job completed but STAC item IDs not found in result. "
                           "The job may have failed during STAC cataloging.",
                "request_id": request_id,
                "job_id": api_request.job_id
            }

        # Step 5: Verify STAC item exists in catalog
        item = self._stac_repo.get_item(item_id, collection_id)

        if not item:
            logger.warning(f"   STAC item {item_id} not found in collection {collection_id}")
            return {
                "found": False,
                "reason": "stac_item_not_in_catalog",
                "message": f"Job result references STAC item '{item_id}' in collection "
                           f"'{collection_id}', but item was not found in catalog.",
                "stac": {
                    "collection_id": collection_id,
                    "item_id": item_id
                },
                "request_id": request_id,
                "job_id": api_request.job_id
            }

        # Success - item found
        logger.info(f"   ✅ Found: {collection_id}/{item_id}")

        return {
            "found": True,
            "stac": {
                "collection_id": collection_id,
                "item_id": item_id,
                "item_url": f"/api/platform/catalog/item/{collection_id}/{item_id}",
                "assets_url": f"/api/platform/catalog/assets/{collection_id}/{item_id}"
            },
            "processing": {
                "request_id": request_id,
                "job_id": api_request.job_id,
                "job_type": job.job_type,
                "completed_at": job.updated_at.isoformat() if job.updated_at else None,
                "data_type": api_request.data_type
            },
            "metadata": {
                "bbox": item.get("bbox"),
                "datetime": item.get("properties", {}).get("datetime"),
                "title": item.get("properties", {}).get("title")
            }
        }

    def lookup_direct(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Direct STAC lookup by DDH identifiers (bypasses Platform tracking).

        Queries pgstac.items directly using platform:* properties.
        Use this when Platform thin-tracking may be inconsistent or
        for items that were created outside the normal Platform flow.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            STAC item dict if found, None otherwise
        """
        logger.debug(f"🔍 Direct STAC lookup: dataset={dataset_id}")

        return self._stac_repo.search_by_platform_ids(
            dataset_id, resource_id, version_id
        )

    # =========================================================================
    # ASSET URL OPERATIONS
    # =========================================================================

    def get_asset_urls(
        self,
        collection_id: str,
        item_id: str,
        include_titiler: bool = True
    ) -> Dict[str, Any]:
        """
        Get asset URLs with optional TiTiler visualization URLs.

        Retrieves the STAC item's assets and generates TiTiler URLs
        for visualization. This is the primary method for DDH to get
        URLs for displaying data in their UI.

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID
            include_titiler: Include TiTiler URLs (default: True)

        Returns:
            Dict with asset information:
            {
                "item_id": "...",
                "collection_id": "...",
                "assets": {
                    "data": {"href": "...", "type": "..."}
                },
                "titiler": {
                    "preview": "...",
                    "tiles": "...",
                    "info": "..."
                },
                "bbox": [...],
                "temporal": {...}
            }

        Example:
            >>> assets = service.get_asset_urls("flood-collection", "flood-item-1")
            >>> preview_url = assets["titiler"]["preview"]
        """
        logger.info(f"🔗 Getting asset URLs: {collection_id}/{item_id}")

        # Get STAC item
        item = self._stac_repo.get_item(item_id, collection_id)

        if not item:
            logger.warning(f"   Item not found: {collection_id}/{item_id}")
            return {
                "error": "item_not_found",
                "message": f"STAC item '{item_id}' not found in collection '{collection_id}'",
                "collection_id": collection_id,
                "item_id": item_id
            }

        assets = item.get("assets", {})
        properties = item.get("properties", {})

        result = {
            "item_id": item_id,
            "collection_id": collection_id,
            "bbox": item.get("bbox"),
            "assets": {},
            "temporal": {
                "datetime": properties.get("datetime"),
                "start_datetime": properties.get("start_datetime"),
                "end_datetime": properties.get("end_datetime")
            },
            "platform_refs": {
                "dataset_id": properties.get("platform:dataset_id"),
                "resource_id": properties.get("platform:resource_id"),
                "version_id": properties.get("platform:version_id")
            }
        }

        # Process assets
        for asset_key, asset in assets.items():
            asset_info = {
                "href": asset.get("href"),
                "type": asset.get("type"),
                "title": asset.get("title"),
                "roles": asset.get("roles", [])
            }

            # Add file size if available
            if "file:size" in asset:
                asset_info["size_bytes"] = asset["file:size"]
                asset_info["size_mb"] = round(asset["file:size"] / (1024 * 1024), 2)

            result["assets"][asset_key] = asset_info

        # Generate TiTiler URLs for COG assets
        if include_titiler:
            result["titiler"] = self._generate_titiler_urls(assets, properties)

        logger.debug(f"   ✅ Returning {len(result['assets'])} assets")
        return result

    def _generate_titiler_urls(
        self,
        assets: Dict[str, Any],
        properties: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """
        Generate TiTiler URLs for raster visualization.

        Creates pre-built TiTiler URLs that DDH can use directly
        in their UI without having to construct URLs themselves.

        Args:
            assets: STAC item assets dict
            properties: STAC item properties dict

        Returns:
            Dict with TiTiler URLs, or None if no suitable asset
        """
        # Look for the data asset (primary COG)
        cog_url = None

        # Check common asset keys in priority order
        for asset_key in ["data", "visual", "image", "cog"]:
            if asset_key in assets:
                asset = assets[asset_key]
                asset_type = asset.get("type", "")

                # Verify it's a COG
                if "geotiff" in asset_type.lower() or "tiff" in asset_type.lower():
                    cog_url = asset.get("href")
                    break

        if not cog_url:
            logger.debug("   No COG asset found for TiTiler URLs")
            return None

        # Get TiTiler base URL from config
        titiler_base = self._config.titiler_base_url
        encoded_url = quote_plus(cog_url)

        # Build TiTiler URLs
        titiler_urls = {
            "preview": f"{titiler_base}/cog/preview?url={encoded_url}",
            "info": f"{titiler_base}/cog/info?url={encoded_url}",
            "statistics": f"{titiler_base}/cog/statistics?url={encoded_url}",
            "tiles": f"{titiler_base}/cog/tiles/{{z}}/{{x}}/{{y}}?url={encoded_url}",
            "tilejson": f"{titiler_base}/cog/tilejson.json?url={encoded_url}",
            "wmts": f"{titiler_base}/cog/WMTSCapabilities.xml?url={encoded_url}",
            "bounds": f"{titiler_base}/cog/bounds?url={encoded_url}"
        }

        # Add colormap for DEMs/elevation data
        raster_type = properties.get("raster:type")
        if raster_type in ["dem", "elevation", "dsm", "dtm"]:
            titiler_urls["preview_terrain"] = (
                f"{titiler_base}/cog/preview?url={encoded_url}&colormap_name=terrain"
            )

        # Add band selection for multi-band rasters
        band_count = None
        for asset in assets.values():
            if "raster:bands" in asset:
                band_count = len(asset["raster:bands"])
                break

        if band_count and band_count > 3:
            # For multi-band, suggest RGB composite
            titiler_urls["preview_rgb"] = (
                f"{titiler_base}/cog/preview?url={encoded_url}&bidx=1&bidx=2&bidx=3"
            )

        logger.debug(f"   Generated {len(titiler_urls)} TiTiler URLs")
        return titiler_urls

    # =========================================================================
    # COLLECTION OPERATIONS
    # =========================================================================

    def list_items_for_dataset(
        self,
        dataset_id: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        List all STAC items for a DDH dataset.

        Returns all items that have the specified platform:dataset_id,
        useful for DDH to see all versions/resources within a dataset.

        Args:
            dataset_id: DDH dataset identifier
            limit: Maximum items to return (default 100)

        Returns:
            Dict with items list and count
        """
        logger.info(f"📋 Listing items for dataset: {dataset_id}")

        items = self._stac_repo.get_items_by_platform_dataset(dataset_id, limit)

        return {
            "dataset_id": dataset_id,
            "count": len(items),
            "items": [
                {
                    "item_id": item.get("id"),
                    "collection_id": item.get("collection"),
                    "bbox": item.get("bbox"),
                    "datetime": item.get("properties", {}).get("datetime"),
                    "resource_id": item.get("properties", {}).get("platform:resource_id"),
                    "version_id": item.get("properties", {}).get("platform:version_id")
                }
                for item in items
            ]
        }


# ============================================================================
# SINGLETON FACTORY
# ============================================================================

_instance: Optional[PlatformCatalogService] = None


def get_platform_catalog_service() -> PlatformCatalogService:
    """
    Get singleton PlatformCatalogService instance.

    Returns:
        PlatformCatalogService singleton

    Usage:
        service = get_platform_catalog_service()
        result = service.lookup_by_ddh_ids(...)
    """
    global _instance
    if _instance is None:
        _instance = PlatformCatalogService()
    return _instance


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'PlatformCatalogService',
    'get_platform_catalog_service'
]
