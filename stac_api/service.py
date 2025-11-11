"""
STAC API Service Layer

Business logic for STAC API endpoints.
Calls infrastructure.stac for database operations.

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
Updated: 11 NOV 2025 - Added all STAC v1.0.0 endpoints
"""

from typing import Dict, Any, Optional
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
                    "rel": "search",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/search",
                    "method": "GET",
                    "title": "STAC search endpoint (GET)"
                },
                {
                    "rel": "search",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/search",
                    "method": "POST",
                    "title": "STAC search endpoint (POST)"
                },
                {
                    "rel": "service-desc",
                    "type": "text/html",
                    "href": "https://stacspec.org/en/api/",
                    "title": "STAC API specification"
                },
                {
                    "rel": "service-doc",
                    "type": "text/html",
                    "href": f"{base_url}/api/stac/collections/summary",
                    "title": "Custom collections summary endpoint"
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

    def get_collections(self, base_url: str) -> Dict[str, Any]:
        """
        Get all STAC collections with metadata.

        Args:
            base_url: Base URL for link generation

        Returns:
            Collections object with collections array and links
        """
        # Import here to avoid circular dependency
        from infrastructure.stac import get_all_collections

        response = get_all_collections()

        # Add links to response
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

            # Add links to each collection
            for coll in response['collections']:
                coll_id = coll.get('id', '')
                coll['links'] = [
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

        return response

    def get_collection(self, collection_id: str, base_url: str) -> Dict[str, Any]:
        """
        Get single collection metadata.

        Args:
            collection_id: Collection ID
            base_url: Base URL for link generation

        Returns:
            Collection object with links
        """
        from infrastructure.stac import get_collection

        response = get_collection(collection_id)

        if 'error' not in response and 'collection' in response:
            collection = response['collection']
            collection['links'] = [
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
            return collection

        return response

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
        from infrastructure.stac import get_collection_items

        response = get_collection_items(
            collection_id=collection_id,
            limit=limit,
            offset=offset,
            bbox=bbox
        )

        if 'error' not in response:
            # Build pagination links
            links = [
                {
                    "rel": "self",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items?limit={limit}&offset={offset}",
                    "title": "This page"
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

            # Add next/prev links if applicable
            number_returned = response.get('numberReturned', 0)
            number_matched = response.get('numberMatched', 0)

            if offset + limit < number_matched:
                links.append({
                    "rel": "next",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items?limit={limit}&offset={offset + limit}",
                    "title": "Next page"
                })

            if offset > 0:
                prev_offset = max(0, offset - limit)
                links.append({
                    "rel": "prev",
                    "type": "application/geo+json",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items?limit={limit}&offset={prev_offset}",
                    "title": "Previous page"
                })

            response['links'] = links

        return response

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
        from infrastructure.stac import get_item_by_id

        response = get_item_by_id(item_id, collection_id)

        if 'error' not in response and 'item' in response:
            item = response['item']
            item['links'] = [
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
            return item

        return response
