# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC API Conformance Classes
# PURPOSE: STAC API v1.0.0 conformance endpoint - declares supported standards
# LAST_REVIEWED: 10 NOV 2025
# EXPORTS: stac_api_conformance_trigger (StacApiConformanceTrigger instance)
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None (static JSON array)
# DEPENDENCIES: http_base.BaseHttpTrigger, util_logger
# SOURCE: HTTP GET requests to /api/stac/conformance
# SCOPE: STAC API conformance declaration - lists implemented specification classes
# VALIDATION: None (static response)
# PATTERNS: Template Method (base class), Static JSON response
# ENTRY_POINTS: GET /api/stac/conformance
# INDEX: StacApiConformanceTrigger:40, process_request:55
# ============================================================================

"""
STAC API Conformance HTTP Trigger

Provides the STAC API conformance classes endpoint per STAC API v1.0.0 specification.
Declares which STAC API conformance classes this implementation supports.

Specification: https://api.stacspec.org/v1.0.0/core

Endpoints:
- GET /api/stac/conformance - List of conformance class URIs

Key Features:
- Returns array of conformance class URIs
- Declares support for STAC API Core, Collections, OGC API - Features
- Static response (no database queries)

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

import azure.functions as func
import json
from typing import Dict, Any, List

from triggers.http_base import BaseHttpTrigger
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "StacApiConformanceTrigger")


class StacApiConformanceTrigger(BaseHttpTrigger):
    """
    STAC API Conformance Trigger.

    Returns the list of STAC API conformance classes that this implementation supports.
    """

    def process_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Process STAC API conformance request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            JSON object with conformsTo array
        """
        try:
            logger.info("📋 STAC API Conformance requested")

            # STAC API conformance classes we support
            conformance = {
                "conformsTo": [
                    # STAC API Core (required)
                    "https://api.stacspec.org/v1.0.0/core",

                    # STAC API Collections (required for /collections endpoints)
                    "https://api.stacspec.org/v1.0.0/collections",

                    # OGC API - Features Core (collection items endpoints)
                    "https://api.stacspec.org/v1.0.0/ogcapi-features",

                    # STAC API Item Search (POST /search endpoint)
                    # Note: Commented out until search endpoint implemented
                    # "https://api.stacspec.org/v1.0.0/item-search",

                    # OGC API - Features Part 1: Core
                    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",

                    # OGC API - Features Part 1: GeoJSON
                    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
                ]
            }

            logger.info(f"✅ Returning {len(conformance['conformsTo'])} conformance classes")

            return func.HttpResponse(
                json.dumps(conformance, indent=2),
                mimetype="application/json",
                status_code=200
            )

        except Exception as e:
            logger.error(f"❌ Error generating conformance response: {e}", exc_info=True)
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                mimetype="application/json",
                status_code=500
            )


# Create trigger instance for function_app.py registration
stac_api_conformance_trigger = StacApiConformanceTrigger()
