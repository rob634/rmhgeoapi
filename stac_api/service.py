"""
STAC API Service Layer

Business logic for STAC API endpoints.
Calls infrastructure.stac for database operations.

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

from typing import Dict, Any
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

    def get_collections(self) -> Dict[str, Any]:
        """
        Get all STAC collections with metadata.

        Returns:
            Collections object with collections array and links
        """
        # Import here to avoid circular dependency
        from infrastructure.stac import get_all_collections

        return get_all_collections()
