# ============================================================================
# PLATFORM CATALOG SERVICE - B2B STAC Access
# ============================================================================
# STATUS: Service - B2B catalog lookup and asset URL generation
# PURPOSE: Provide DDH-identifier-based STAC access for B2B integration
# CREATED: 16 JAN 2026
# LAST_REVIEWED: 21 FEB 2026
# EPIC: F12.8 API Documentation Hub - B2B STAC Catalog Access
# V0.9: Unified catalog ops use Asset+Release instead of GeospatialAsset
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
        from infrastructure import AssetRepositoryV2, ReleaseRepository
        from infrastructure.pgstac_repository import PgStacRepository
        from config import get_config

        self._platform_repo = PlatformRepository()
        self._job_repo = JobRepository()
        self._stac_repo = PgStacRepository()
        self._asset_repo = AssetRepositoryV2()
        self._release_repo = ReleaseRepository()
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
    # COLLECTION OPERATIONS (STAC-based, legacy)
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

    # =========================================================================
    # UNIFIED CATALOG OPERATIONS (V0.9 - Asset+Release entity split)
    # =========================================================================
    # These methods query app.assets + app.asset_releases (source of truth).
    # Works for both vectors AND rasters.
    # V0.9 (21 FEB 2026): Replaced GeospatialAsset with Asset+Release.
    # See: docs_claude/UNIFIED_B2B_CATALOG.md

    def lookup_unified(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Dict[str, Any]:
        """
        Unified lookup - works for both raster and vector data.

        Queries Asset+Release directly, bypasses STAC/OGC APIs.
        This is the recommended B2B lookup method for V0.9+.

        Strategy:
            1. Find Asset by identity (platform=ddh, dataset_id, resource_id)
            2. If version_id provided, get that specific Release version
            3. Otherwise, get the latest approved Release
            4. Build response from both Asset and Release data

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            Dict with unified response format including bbox and service URLs

        Example:
            >>> result = service.lookup_unified("eleventhhourtest", "v8_testing", "v1.0")
            >>> if result["found"]:
            ...     print(f"Type: {result['data_type']}, bbox: {result['metadata']['bbox']}")
        """
        from datetime import datetime, timezone

        logger.info(
            f"Unified catalog lookup: dataset={dataset_id}, "
            f"resource={resource_id}, version={version_id}"
        )

        # Step 1: Find Asset by identity triple
        asset = self._asset_repo.get_by_identity("ddh", dataset_id, resource_id)

        if not asset:
            logger.debug("   No asset found for these DDH identifiers")
            return {
                "found": False,
                "reason": "asset_not_found",
                "message": "No asset found for these DDH identifiers. "
                           "The data may not have been submitted through the Platform API.",
                "suggestion": "Submit the data via POST /api/platform/submit",
                "ddh_refs": {
                    "dataset_id": dataset_id,
                    "resource_id": resource_id,
                    "version_id": version_id
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 2: Get Release - specific version or latest
        if version_id:
            release = self._release_repo.get_by_version(asset.asset_id, version_id)
        else:
            release = self._release_repo.get_latest(asset.asset_id)

        if not release:
            logger.debug(f"   No release found for asset {asset.asset_id[:16]}...")
            return {
                "found": False,
                "reason": "release_not_found",
                "message": f"Asset exists but no {'version ' + version_id if version_id else 'approved release'} found.",
                "asset_id": asset.asset_id,
                "ddh_refs": {
                    "dataset_id": dataset_id,
                    "resource_id": resource_id,
                    "version_id": version_id
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Step 3: Build response based on data_type
        asset_dict = asset.to_dict()
        release_dict = release.to_dict()
        data_type = asset.data_type

        if data_type == 'vector':
            response = self._build_vector_response(asset_dict, release_dict)
        elif data_type == 'raster':
            response = self._build_raster_response(asset_dict, release_dict)
        else:
            logger.warning(f"   Unknown data_type: {data_type}")
            response = self._build_generic_response(asset_dict, release_dict)

        logger.info(f"   Found {data_type}: {asset.asset_id[:16]}...")
        return response

    def _build_vector_response(self, asset: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build vector-specific response with TiPG URLs.

        V0.9: Takes separate asset and release dicts. Status and lineage
        fields come from the release, identity from the asset.

        Args:
            asset: Asset dict from Asset.to_dict()
            release: Release dict from AssetRelease.to_dict()

        Returns:
            Unified response format with vector-specific fields
        """
        from datetime import datetime, timezone

        table_name = release.get('table_name')

        # Generate TiPG URLs
        tile_urls = self._config.generate_vector_tile_urls(table_name, schema="geo") if table_name else {}

        return {
            "found": True,
            "asset_id": asset.get('asset_id'),
            "data_type": "vector",

            "status": {
                "processing": release.get('processing_status', 'pending'),
                "approval": release.get('approval_state', 'pending_review'),
                "clearance": release.get('clearance_state', 'uncleared')
            },

            "metadata": {
                "bbox": None,  # V0.9: bbox requires metadata JOIN (not yet implemented)
                "created_at": asset.get('created_at')
            },

            "vector": {
                "table_name": table_name,
                "schema": "geo",
                "endpoints": {
                    "features": f"/api/features/collections/{table_name}/items" if table_name else None,
                    "collection": f"/api/features/collections/{table_name}" if table_name else None
                },
                "tiles": {
                    "mvt": tile_urls.get('mvt'),
                    "tilejson": tile_urls.get('tilejson'),
                    "viewer": f"/api/interface/vector-tiles?collection=geo.{table_name}" if table_name else None
                }
            },

            "ddh_refs": {
                "dataset_id": asset.get('dataset_id'),
                "resource_id": asset.get('resource_id'),
                "version_id": release.get('version_id')
            },

            "lineage": {
                "asset_id": asset.get('asset_id'),
                "version_id": release.get('version_id'),
                "version_ordinal": release.get('version_ordinal'),
                "is_latest": release.get('is_latest'),
                "is_served": release.get('is_served')
            },

            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _build_raster_response(self, asset: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build raster-specific response with TiTiler URLs.

        V0.9: Takes separate asset and release dicts. Physical outputs
        (blob_path, stac IDs) and status come from the release.

        Args:
            asset: Asset dict from Asset.to_dict()
            release: Release dict from AssetRelease.to_dict()

        Returns:
            Unified response format with raster-specific fields
        """
        from datetime import datetime, timezone
        from urllib.parse import quote_plus

        blob_path = release.get('blob_path')
        stac_collection_id = release.get('stac_collection_id')
        stac_item_id = release.get('stac_item_id')

        # Generate TiTiler URLs if we have blob_path
        titiler_urls = {}
        if blob_path:
            # Build full blob URL (COGs are stored in silver zone)
            storage_account = self._config.storage.silver.account_name
            container = "silver-cogs"  # COGs are stored in silver container
            cog_url = f"https://{storage_account}.blob.core.windows.net/{container}/{blob_path}"
            encoded_url = quote_plus(cog_url)

            titiler_base = self._config.titiler_base_url

            titiler_urls = {
                "xyz": f"{titiler_base}/cog/tiles/{{z}}/{{x}}/{{y}}?url={encoded_url}",
                "tilejson": f"{titiler_base}/cog/tilejson.json?url={encoded_url}",
                "preview": f"{titiler_base}/cog/preview?url={encoded_url}",
                "info": f"{titiler_base}/cog/info?url={encoded_url}",
                "statistics": f"{titiler_base}/cog/statistics?url={encoded_url}",
                "viewer": f"/api/interface/raster-viewer?url={encoded_url}"
            }

        return {
            "found": True,
            "asset_id": asset.get('asset_id'),
            "data_type": "raster",

            "status": {
                "processing": release.get('processing_status', 'pending'),
                "approval": release.get('approval_state', 'pending_review'),
                "clearance": release.get('clearance_state', 'uncleared')
            },

            "metadata": {
                "bbox": None,  # V0.9: bbox requires metadata JOIN (not yet implemented)
                "created_at": asset.get('created_at')
            },

            "raster": {
                "blob_path": blob_path,
                "container": "silver-cogs",
                "stac": {
                    "collection_id": stac_collection_id,
                    "item_id": stac_item_id
                } if stac_item_id else None,
                "tiles": titiler_urls
            },

            "ddh_refs": {
                "dataset_id": asset.get('dataset_id'),
                "resource_id": asset.get('resource_id'),
                "version_id": release.get('version_id')
            },

            "lineage": {
                "asset_id": asset.get('asset_id'),
                "version_id": release.get('version_id'),
                "version_ordinal": release.get('version_ordinal'),
                "is_latest": release.get('is_latest'),
                "is_served": release.get('is_served')
            },

            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _build_generic_response(self, asset: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build generic response for unknown data types.

        V0.9: Takes separate asset and release dicts.

        Args:
            asset: Asset dict from Asset.to_dict()
            release: Release dict from AssetRelease.to_dict()

        Returns:
            Basic response with available fields
        """
        from datetime import datetime, timezone

        return {
            "found": True,
            "asset_id": asset.get('asset_id'),
            "data_type": asset.get('data_type'),

            "status": {
                "processing": release.get('processing_status', 'pending'),
                "approval": release.get('approval_state', 'pending_review'),
                "clearance": release.get('clearance_state', 'uncleared')
            },

            "metadata": {
                "bbox": None,
                "created_at": asset.get('created_at')
            },

            "ddh_refs": {
                "dataset_id": asset.get('dataset_id'),
                "resource_id": asset.get('resource_id'),
                "version_id": release.get('version_id')
            },

            "lineage": {
                "asset_id": asset.get('asset_id'),
                "version_id": release.get('version_id'),
                "version_ordinal": release.get('version_ordinal'),
                "is_latest": release.get('is_latest'),
                "is_served": release.get('is_served')
            },

            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def get_unified_urls(self, asset_id: str) -> Dict[str, Any]:
        """
        Get service URLs by asset_id.

        Retrieves an Asset and its latest approved Release, then returns
        appropriate service URLs based on data_type.

        Args:
            asset_id: Asset identifier

        Returns:
            Dict with service URLs for the asset
        """
        from datetime import datetime, timezone

        logger.info(f"Getting URLs for asset: {asset_id[:16]}...")

        asset = self._asset_repo.get_by_id(asset_id)

        if not asset or not asset.is_active():
            return {
                "found": False,
                "reason": "asset_not_found",
                "message": f"Asset '{asset_id}' not found",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Get latest approved release
        release = self._release_repo.get_latest(asset.asset_id)

        if not release:
            return {
                "found": False,
                "reason": "release_not_found",
                "message": f"Asset '{asset_id}' exists but has no approved release",
                "asset_id": asset_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        asset_dict = asset.to_dict()
        release_dict = release.to_dict()

        if asset.data_type == 'vector':
            return self._build_vector_response(asset_dict, release_dict)
        elif asset.data_type == 'raster':
            return self._build_raster_response(asset_dict, release_dict)
        else:
            return self._build_generic_response(asset_dict, release_dict)

    def list_dataset_unified(
        self,
        dataset_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        List all assets for a dataset with their latest releases.

        V0.9: JOINs app.assets with app.asset_releases to get both
        identity and versioned artifact data in a single query.

        Args:
            dataset_id: DDH dataset identifier
            limit: Maximum items to return
            offset: Number of items to skip

        Returns:
            Dict with assets list and count
        """
        from datetime import datetime, timezone
        from psycopg import sql

        logger.info(f"Unified listing for dataset: {dataset_id}")

        # JOIN assets with their latest release
        query = sql.SQL("""
            SELECT a.asset_id, a.platform_id, a.dataset_id, a.resource_id,
                   a.data_type, a.created_at as asset_created_at,
                   r.release_id, r.version_id, r.version_ordinal,
                   r.is_latest, r.is_served,
                   r.blob_path, r.table_name,
                   r.stac_item_id, r.stac_collection_id,
                   r.processing_status, r.approval_state, r.clearance_state,
                   r.created_at as release_created_at
            FROM {schema}.{assets} a
            LEFT JOIN {schema}.{releases} r
                ON r.asset_id = a.asset_id AND r.is_latest = true
            WHERE a.platform_id = 'ddh'
              AND a.dataset_id = %s
              AND a.deleted_at IS NULL
            ORDER BY r.created_at DESC NULLS LAST
            LIMIT %s OFFSET %s
        """).format(
            schema=sql.Identifier("app"),
            assets=sql.Identifier("assets"),
            releases=sql.Identifier("asset_releases")
        )

        with self._asset_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (dataset_id, limit, offset))
                rows = cur.fetchall()

        items = []
        for row in rows:
            data_type = row.get('data_type')
            item = {
                "asset_id": row.get('asset_id'),
                "data_type": data_type,
                "processing_status": row.get('processing_status'),
                "approval_state": row.get('approval_state'),
                "created_at": row['asset_created_at'].isoformat() if row.get('asset_created_at') else None,
                "ddh_refs": {
                    "dataset_id": row.get('dataset_id'),
                    "resource_id": row.get('resource_id'),
                    "version_id": row.get('version_id')
                },
                "lineage": {
                    "asset_id": row.get('asset_id'),
                    "version_id": row.get('version_id'),
                    "version_ordinal": row.get('version_ordinal'),
                    "is_latest": row.get('is_latest'),
                    "is_served": row.get('is_served')
                }
            }

            # Add type-specific identifiers
            if data_type == 'vector':
                item["table_name"] = row.get('table_name')
            elif data_type == 'raster':
                item["stac_item_id"] = row.get('stac_item_id')
                item["stac_collection_id"] = row.get('stac_collection_id')

            items.append(item)

        return {
            "dataset_id": dataset_id,
            "count": len(items),
            "limit": limit,
            "offset": offset,
            "items": items,
            "timestamp": datetime.now(timezone.utc).isoformat()
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
