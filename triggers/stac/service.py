# ============================================================================
# STAC API SERVICE
# ============================================================================
# STATUS: Trigger layer service - Business logic for STAC endpoints
# PURPOSE: Orchestrate STAC API responses with link generation
# CREATED: 24 JAN 2026 (Moved from stac_api/service.py)
# EXPORTS: STACAPIService
# DEPENDENCIES: infrastructure.pgstac_bootstrap
# ============================================================================
"""
STAC API Service Layer.

Business logic for STAC API endpoints.
Calls infrastructure.pgstac_bootstrap for database operations.
"""

from typing import Dict, Any, Optional

from infrastructure.service_latency import track_latency
from .config import STACAPIConfig


class STACAPIService:
    """STAC API business logic layer."""

    def __init__(self, config: STACAPIConfig):
        """Initialize service with configuration."""
        self.config = config

    def get_catalog(self, base_url: str) -> Dict[str, Any]:
        """
        Get STAC catalog descriptor (landing page).

        Args:
            base_url: Base URL for link generation

        Returns:
            STAC Catalog object
        """
        return {
            "id": self.config.catalog_id,
            "type": "Catalog",
            "title": self.config.catalog_title,
            "description": self.config.catalog_description,
            "stac_version": self.config.stac_version,
            "conformsTo": [
                "https://api.stacspec.org/v1.0.0/core",
                "https://api.stacspec.org/v1.0.0/collections",
                "https://api.stacspec.org/v1.0.0/ogcapi-features"
            ],
            "links": [
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac",
                    "title": "This catalog"
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac",
                    "title": "Root catalog"
                },
                {
                    "rel": "conformance",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/conformance",
                    "title": "STAC API conformance classes"
                },
                {
                    "rel": "data",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections",
                    "title": "Collections in this catalog"
                },
                {
                    "rel": "service-desc",
                    "type": "text/html",
                    "href": "https://stacspec.org/en/api/",
                    "title": "STAC API specification"
                }
            ]
        }

    def get_conformance(self) -> Dict[str, Any]:
        """
        Get STAC API conformance classes.

        Returns:
            Conformance object with conformsTo array
        """
        return {
            "conformsTo": [
                "https://api.stacspec.org/v1.0.0/core",
                "https://api.stacspec.org/v1.0.0/collections",
                "https://api.stacspec.org/v1.0.0/ogcapi-features",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
            ]
        }

    @track_latency("stac.get_collections")
    def get_collections(self, base_url: str) -> Dict[str, Any]:
        """
        Get all STAC collections with metadata.

        Args:
            base_url: Base URL for link generation

        Returns:
            Collections object with collections array and links
        """
        from infrastructure.pgstac_bootstrap import get_all_collections

        response = get_all_collections()

        if 'collections' in response:
            response['links'] = [
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections",
                    "title": "This document"
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac",
                    "title": "Root catalog"
                }
            ]

            # Add links to each collection (preserving custom TiTiler links)
            for coll in response['collections']:
                coll_id = coll.get('id', '')

                # Build standard STAC links
                standard_links = [
                    {
                        "rel": "self",
                        "type": "application/json",
                        "href": f"{base_url}/api/stac/collections/{coll_id}",
                        "title": f"Collection {coll_id}"
                    },
                    {
                        "rel": "items",
                        "type": "application/geo+json",
                        "href": f"{base_url}/api/stac/collections/{coll_id}/items",
                        "title": f"Items in {coll_id}"
                    },
                    {
                        "rel": "parent",
                        "type": "application/json",
                        "href": f"{base_url}/api/stac",
                        "title": "Parent catalog"
                    },
                    {
                        "rel": "root",
                        "type": "application/json",
                        "href": f"{base_url}/api/stac",
                        "title": "Root catalog"
                    }
                ]

                # Preserve TiTiler links stored in pgstac database
                existing_links = coll.get('links', [])
                standard_rels = {'self', 'items', 'parent', 'root'}
                custom_links = [link for link in existing_links if link.get('rel') not in standard_rels]

                # Combine: standard links + custom links (TiTiler preview, tilejson, tiles)
                coll['links'] = standard_links + custom_links

        return response

    @track_latency("stac.get_collection")
    def get_collection(self, collection_id: str, base_url: str) -> Dict[str, Any]:
        """
        Get single collection metadata.

        Args:
            collection_id: Collection ID
            base_url: Base URL for link generation

        Returns:
            Collection object with links
        """
        from infrastructure.pgstac_bootstrap import get_collection

        response = get_collection(collection_id)

        if 'error' not in response:
            # Build standard STAC links
            standard_links = [
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}",
                    "title": f"Collection {collection_id}"
                },
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items",
                    "title": f"Items in {collection_id}"
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections",
                    "title": "All collections"
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac",
                    "title": "Root catalog"
                }
            ]

            # Preserve TiTiler links stored in pgstac database
            existing_links = response.get('links', [])
            standard_rels = {'self', 'items', 'parent', 'root'}
            custom_links = [link for link in existing_links if link.get('rel') not in standard_rels]

            # Combine: standard links + custom links
            response['links'] = standard_links + custom_links

        return response

    @track_latency("stac.get_items")
    def get_items(
        self,
        collection_id: str,
        base_url: str,
        limit: int = 10,
        offset: int = 0,
        bbox: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get items from collection (paginated).

        Args:
            collection_id: Collection ID
            base_url: Base URL for link generation
            limit: Max items to return (default: 10)
            offset: Offset for pagination (default: 0)
            bbox: Bounding box filter (optional)

        Returns:
            FeatureCollection with items and pagination links
        """
        from infrastructure.pgstac_bootstrap import get_collection_items

        response = get_collection_items(
            collection_id=collection_id,
            limit=limit,
            bbox=bbox
        )

        if 'error' not in response:
            links = [
                {
                    "rel": "self",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items?limit={limit}",
                    "title": "This document"
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}",
                    "title": f"Collection {collection_id}"
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac",
                    "title": "Root catalog"
                },
                {
                    "rel": "collection",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}",
                    "title": f"Collection {collection_id}"
                }
            ]

            response['links'] = links

        return response

    @track_latency("stac.get_item")
    def get_item(self, collection_id: str, item_id: str, base_url: str) -> Dict[str, Any]:
        """
        Get single item metadata.

        Args:
            collection_id: Collection ID
            item_id: Item ID
            base_url: Base URL for link generation

        Returns:
            Item object with links
        """
        from infrastructure.pgstac_bootstrap import get_item_by_id

        response = get_item_by_id(item_id, collection_id)

        if 'error' not in response:
            links = [
                {
                    "rel": "self",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items/{item_id}",
                    "title": f"Item {item_id}"
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}",
                    "title": f"Collection {collection_id}"
                },
                {
                    "rel": "collection",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}",
                    "title": f"Collection {collection_id}"
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": f"{base_url}/api/stac",
                    "title": "Root catalog"
                }
            ]

            # Add OGC Features API link for vector items
            properties = response.get('properties', {})
            postgis_table = properties.get('postgis:table')
            if postgis_table:
                links.append({
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/items",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/features/collections/{postgis_table}/items",
                    "title": "OGC Features API"
                })

            response['links'] = links

        return response

    # =========================================================================
    # ADMIN — STAC Materialization CRUD (26 FEB 2026)
    # =========================================================================

    def admin_create_collection(
        self,
        collection_id: str,
        description: str = None,
        bbox: list = None,
        license_val: str = "proprietary",
    ) -> Dict[str, Any]:
        """
        Create an empty STAC collection in pgSTAC.

        Args:
            collection_id: Collection identifier
            description: Optional description
            bbox: Spatial extent [minx, miny, maxx, maxy]
            license_val: STAC license

        Returns:
            Dict with success and collection_id
        """
        from services.stac_collection import build_raster_stac_collection
        from infrastructure.pgstac_repository import PgStacRepository

        pgstac = PgStacRepository()

        if pgstac.collection_exists(collection_id):
            return {
                'success': False,
                'error': f"Collection '{collection_id}' already exists. Use PUT to update."
            }

        collection_dict = build_raster_stac_collection(
            collection_id=collection_id,
            bbox=bbox or [-180, -90, 180, 90],
            description=description,
            license_val=license_val,
        )
        pgstac.insert_collection(collection_dict)

        return {'success': True, 'collection_id': collection_id}

    def admin_update_collection(
        self,
        collection_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update collection metadata in pgSTAC.

        Args:
            collection_id: Collection to update
            updates: Dict with fields to update (description, bbox, etc.)

        Returns:
            Dict with success and collection_id
        """
        from infrastructure.pgstac_repository import PgStacRepository

        pgstac = PgStacRepository()
        collection_dict = pgstac.get_collection(collection_id)

        if not collection_dict:
            return {
                'success': False,
                'error': f"Collection '{collection_id}' not found"
            }

        # Patch supported fields
        if 'description' in updates:
            collection_dict['description'] = updates['description']
        if 'bbox' in updates:
            collection_dict.setdefault('extent', {}).setdefault('spatial', {})['bbox'] = [updates['bbox']]
        if 'license' in updates:
            collection_dict['license'] = updates['license']

        pgstac.insert_collection(collection_dict)

        return {'success': True, 'collection_id': collection_id}

    def admin_delete_collection(self, collection_id: str) -> Dict[str, Any]:
        """
        Delete a collection and all its items from pgSTAC.

        Args:
            collection_id: Collection to delete

        Returns:
            Dict with success, items_deleted, collection_id
        """
        from infrastructure.pgstac_repository import PgStacRepository

        pgstac = PgStacRepository()

        if not pgstac.collection_exists(collection_id):
            return {
                'success': False,
                'error': f"Collection '{collection_id}' not found"
            }

        # Delete all items first
        item_ids = pgstac.get_collection_item_ids(collection_id)
        for item_id in item_ids:
            pgstac.delete_item(collection_id, item_id)

        # Delete collection
        pgstac.delete_collection(collection_id)

        return {
            'success': True,
            'collection_id': collection_id,
            'items_deleted': len(item_ids),
        }

    def admin_delete_item(
        self,
        collection_id: str,
        item_id: str
    ) -> Dict[str, Any]:
        """
        Remove an item and recalculate collection extent.

        Delegates to STACMaterializer.dematerialize_item() for
        automatic extent recalculation and empty collection cleanup.

        Args:
            collection_id: Collection containing the item
            item_id: Item to remove

        Returns:
            Dict with success, deleted, collection_action
        """
        from services.stac_materialization import STACMaterializer

        materializer = STACMaterializer()
        return materializer.dematerialize_item(collection_id, item_id)

    def admin_rebuild_all(self) -> Dict[str, Any]:
        """
        Rebuild entire STAC catalog from internal DB.

        Returns:
            Dict with collections_rebuilt, items_rebuilt, errors
        """
        from services.stac_materialization import STACMaterializer

        materializer = STACMaterializer()
        return materializer.rebuild_all_from_db()

    def admin_rebuild_collection(self, collection_id: str) -> Dict[str, Any]:
        """
        Rebuild a single collection from internal DB.

        Args:
            collection_id: Collection to rebuild

        Returns:
            Dict with items_created, bbox, etc.
        """
        from services.stac_materialization import STACMaterializer

        materializer = STACMaterializer()
        return materializer.rebuild_collection_from_db(collection_id)
