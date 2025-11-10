# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC API Landing Page (Catalog Root)
# PURPOSE: STAC API v1.0.0 landing page endpoint - entry point for STAC clients
# LAST_REVIEWED: 10 NOV 2025
# EXPORTS: stac_api_landing_trigger (StacApiLandingTrigger instance)
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None (static JSON catalog descriptor)
# DEPENDENCIES: http_base.BaseHttpTrigger, config, util_logger
# SOURCE: HTTP GET requests to /api/stac/ (root endpoint)
# SCOPE: STAC API discovery - provides catalog metadata and navigation links
# VALIDATION: None (static response)
# PATTERNS: Template Method (base class), Static JSON response
# ENTRY_POINTS: GET /api/stac/
# INDEX: StacApiLandingTrigger:45, process_request:65
# ============================================================================

"""
STAC API Landing Page HTTP Trigger

Provides the STAC API landing page (catalog root) per STAC API v1.0.0 Core specification.
This is the entry point for STAC clients to discover collections, search, and other endpoints.

Specification: https://api.stacspec.org/v1.0.0/core

Endpoints:
- GET /api/stac/ - STAC catalog root (landing page)

Key Features:
- Returns catalog descriptor with title, description, STAC version
- Provides conformance class URIs
- Includes navigation links to collections, search, conformance endpoints
- Static response (no database queries)

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

import azure.functions as func
import json
from typing import Dict, Any, List

from triggers.http_base import BaseHttpTrigger
from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "StacApiLandingTrigger")


class StacApiLandingTrigger(BaseHttpTrigger):
    """
    STAC API Landing Page Trigger.

    Returns the STAC catalog root descriptor - the entry point for STAC API clients.
    Provides links to collections, search, and conformance endpoints.
    """

    def __init__(self):
        """Initialize the trigger."""
        super().__init__(trigger_name="stac_api_landing")

    def get_allowed_methods(self) -> List[str]:
        """Return allowed HTTP methods."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Process STAC API landing page request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC Catalog JSON descriptor
        """
        try:
            logger.info("🗺️ STAC API Landing Page requested")

            # Get configuration
            config = get_config()

            # Determine base URL (use Azure Functions URL from config or request)
            base_url = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"

            # Build STAC Catalog descriptor
            catalog = {
                "id": "rmh-geospatial-stac",
                "type": "Catalog",
                "title": "RMH Geospatial STAC API",
                "description": "STAC catalog for geospatial raster and vector data with OAuth-based tile serving via TiTiler-pgSTAC",
                "stac_version": "1.0.0",
                "conformsTo": [
                    "https://api.stacspec.org/v1.0.0/core",
                    "https://api.stacspec.org/v1.0.0/collections",
                    "https://api.stacspec.org/v1.0.0/ogcapi-features"
                ],
                "links": [
                    {
                        "rel": "self",
                        "type": "application/json",
                        "href": f"{base_url}",
                        "title": "This catalog"
                    },
                    {
                        "rel": "root",
                        "type": "application/json",
                        "href": f"{base_url}",
                        "title": "Root catalog"
                    },
                    {
                        "rel": "conformance",
                        "type": "application/json",
                        "href": f"{base_url}/conformance",
                        "title": "STAC API conformance classes"
                    },
                    {
                        "rel": "data",
                        "type": "application/json",
                        "href": f"{base_url}/collections",
                        "title": "Collections in this catalog"
                    },
                    {
                        "rel": "search",
                        "type": "application/geo+json",
                        "href": f"{base_url}/search",
                        "method": "GET",
                        "title": "STAC search endpoint (GET)"
                    },
                    {
                        "rel": "search",
                        "type": "application/geo+json",
                        "href": f"{base_url}/search",
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
                        "href": f"{base_url}/collections/summary",
                        "title": "Custom collections summary endpoint"
                    }
                ]
            }

            logger.info("✅ STAC API landing page generated successfully")

            return func.HttpResponse(
                json.dumps(catalog, indent=2),
                mimetype="application/json",
                status_code=200
            )

        except Exception as e:
            logger.error(f"❌ Error generating STAC API landing page: {e}", exc_info=True)
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                mimetype="application/json",
                status_code=500
            )


# Create trigger instance for function_app.py registration
stac_api_landing_trigger = StacApiLandingTrigger()
