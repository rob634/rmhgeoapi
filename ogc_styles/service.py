# ============================================================================
# CLAUDE CONTEXT - OGC STYLES SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Business logic - OGC Styles orchestration
# PURPOSE: Coordinate style lookup, translation, and response formatting
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: OGCStylesService
# DEPENDENCIES: ogc_styles.repository, ogc_styles.translator
# ============================================================================
"""
OGC Styles Service Layer.

Business logic for OGC API Styles:
- List styles for a collection
- Get style in requested format (CartoSym, Leaflet, Mapbox)
- Format OGC API-compliant responses

Usage:
    service = OGCStylesService()

    # List styles
    styles_list = service.list_styles("countries", base_url)

    # Get style in Leaflet format
    style_doc, content_type = service.get_style("countries", "default", "leaflet")

Created: 18 DEC 2025
"""

import logging
from typing import Any, Dict, Optional, Tuple

from .repository import OGCStylesRepository
from .translator import StyleTranslator

logger = logging.getLogger(__name__)


# Content type mappings for different formats
CONTENT_TYPES = {
    "cartosym": "application/vnd.ogc.cartosym+json",
    "leaflet": "application/vnd.leaflet.style+json",
    "mapbox": "application/vnd.mapbox.style+json"
}


class OGCStylesService:
    """
    OGC API Styles business logic.

    Orchestrates style retrieval, translation, and OGC-compliant formatting.
    Coordinates between repository (data access) and translator (format conversion).
    """

    def __init__(self, repository: Optional[OGCStylesRepository] = None):
        """
        Initialize service with optional repository.

        Args:
            repository: Style repository (creates default if not provided)
        """
        self.repository = repository or OGCStylesRepository()
        logger.info("OGCStylesService initialized")

    def list_styles(self, collection_id: str, base_url: str) -> Dict[str, Any]:
        """
        List available styles for a collection.

        Returns OGC API Styles-compliant response with links to each style
        in different output formats.

        Args:
            collection_id: Collection identifier
            base_url: Base URL for link generation

        Returns:
            OGC API Styles list response

        Raises:
            ValueError: If collection has no styles or styles table doesn't exist
        """
        # Check if styles table exists
        if not self.repository.styles_table_exists():
            logger.warning("geo.feature_collection_styles table does not exist")
            return {
                "styles": [],
                "links": [
                    {
                        "rel": "self",
                        "href": f"{base_url}/api/features/collections/{collection_id}/styles",
                        "type": "application/json"
                    }
                ]
            }

        # Get styles from repository
        styles_data = self.repository.list_styles(collection_id)

        styles_url = f"{base_url}/api/features/collections/{collection_id}/styles"

        styles = []
        for row in styles_data:
            style_entry = {
                "id": row["style_id"],
                "title": row["title"],
                "description": row["description"],
                "default": row["is_default"],
                "links": [
                    {
                        "rel": "describedby",
                        "href": f"{styles_url}/{row['style_id']}",
                        "type": CONTENT_TYPES["cartosym"],
                        "title": "CartoSym-JSON (canonical)"
                    },
                    {
                        "rel": "describedby",
                        "href": f"{styles_url}/{row['style_id']}?f=leaflet",
                        "type": CONTENT_TYPES["leaflet"],
                        "title": "Leaflet style"
                    },
                    {
                        "rel": "describedby",
                        "href": f"{styles_url}/{row['style_id']}?f=mapbox",
                        "type": CONTENT_TYPES["mapbox"],
                        "title": "Mapbox GL style"
                    }
                ]
            }
            styles.append(style_entry)

        logger.info(f"Listed {len(styles)} styles for collection '{collection_id}'")

        return {
            "styles": styles,
            "links": [
                {
                    "rel": "self",
                    "href": styles_url,
                    "type": "application/json"
                }
            ]
        }

    def get_style(
        self,
        collection_id: str,
        style_id: str,
        output_format: str = "leaflet"
    ) -> Tuple[Dict[str, Any], str]:
        """
        Get a style document in the requested format.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier
            output_format: Output format (cartosym, leaflet, mapbox)

        Returns:
            Tuple of (style_document, content_type)

        Raises:
            ValueError: If style not found or format unsupported
        """
        # Check if styles table exists
        if not self.repository.styles_table_exists():
            raise ValueError(
                f"Style '{style_id}' not found for collection '{collection_id}' "
                "(styles table does not exist)"
            )

        # Get style from repository
        style_data = self.repository.get_style(collection_id, style_id)

        if not style_data:
            raise ValueError(f"Style '{style_id}' not found for collection '{collection_id}'")

        cartosym = style_data["style_spec"]

        # Return canonical format
        if output_format == "cartosym":
            logger.info(f"Serving style '{style_id}' as CartoSym-JSON")
            return cartosym, CONTENT_TYPES["cartosym"]

        # Translate to requested format
        translator = StyleTranslator(cartosym)

        if output_format == "leaflet":
            logger.info(f"Serving style '{style_id}' as Leaflet format")
            return translator.to_leaflet(), CONTENT_TYPES["leaflet"]
        elif output_format == "mapbox":
            logger.info(f"Serving style '{style_id}' as Mapbox GL format")
            return translator.to_mapbox(), CONTENT_TYPES["mapbox"]
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

    def get_default_style(
        self,
        collection_id: str,
        output_format: str = "leaflet"
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Get the default style for a collection.

        Args:
            collection_id: Collection identifier
            output_format: Output format (cartosym, leaflet, mapbox)

        Returns:
            Tuple of (style_document, content_type) or (None, "") if no default
        """
        # Check if styles table exists
        if not self.repository.styles_table_exists():
            return None, ""

        # Get default style
        style_data = self.repository.get_default_style(collection_id)

        if not style_data:
            return None, ""

        cartosym = style_data["style_spec"]

        # Return canonical format
        if output_format == "cartosym":
            return cartosym, CONTENT_TYPES["cartosym"]

        # Translate to requested format
        translator = StyleTranslator(cartosym)

        if output_format == "leaflet":
            return translator.to_leaflet(), CONTENT_TYPES["leaflet"]
        elif output_format == "mapbox":
            return translator.to_mapbox(), CONTENT_TYPES["mapbox"]
        else:
            return None, ""

    def create_default_style(
        self,
        collection_id: str,
        geometry_type: str,
        fill_color: str = "#3388ff",
        stroke_color: str = "#2266cc"
    ) -> bool:
        """
        Create a default style for a collection.

        Used by ETL to auto-generate styles after table creation.

        Args:
            collection_id: Collection identifier
            geometry_type: PostGIS geometry type
            fill_color: Fill color (hex)
            stroke_color: Stroke color (hex)

        Returns:
            True if created successfully
        """
        # Check if styles table exists
        if not self.repository.styles_table_exists():
            logger.warning(
                f"Cannot create default style for '{collection_id}' - "
                "geo.feature_collection_styles table does not exist"
            )
            return False

        return self.repository.create_default_style_for_collection(
            collection_id=collection_id,
            geometry_type=geometry_type,
            fill_color=fill_color,
            stroke_color=stroke_color
        )

    def negotiate_format(self, accept_header: str, format_param: Optional[str]) -> str:
        """
        Determine output format from Accept header and query parameter.

        Query parameter takes precedence over Accept header.

        Args:
            accept_header: HTTP Accept header value
            format_param: Value of ?f= query parameter

        Returns:
            Output format string (cartosym, leaflet, mapbox)
        """
        # Query parameter takes precedence
        if format_param:
            format_lower = format_param.lower()
            if format_lower in CONTENT_TYPES:
                return format_lower
            logger.warning(f"Unknown format '{format_param}', defaulting to leaflet")

        # Parse Accept header
        if accept_header:
            if "vnd.leaflet" in accept_header:
                return "leaflet"
            elif "vnd.mapbox" in accept_header:
                return "mapbox"
            elif "vnd.ogc.cartosym" in accept_header:
                return "cartosym"

        # Default for web clients
        return "leaflet"
