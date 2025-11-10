# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC API Collections List
# PURPOSE: STAC API v1.0.0 collections endpoint - list all STAC collections
# LAST_REVIEWED: 10 NOV 2025
# EXPORTS: stac_api_collections_trigger (StacApiCollectionsTrigger instance)
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None (pgSTAC collection objects)
# DEPENDENCIES: http_base.BaseHttpTrigger, infrastructure.stac, util_logger
# SOURCE: HTTP GET requests to /api/stac/collections
# SCOPE: STAC API collections listing - provides navigation to all collections
# VALIDATION: None (database query)
# PATTERNS: Template Method (base class), Database query response
# ENTRY_POINTS: GET /api/stac/collections
# INDEX: StacApiCollectionsTrigger:43, process_request:56
# ============================================================================

"""
STAC API Collections List HTTP Trigger

Provides the STAC API collections list endpoint per STAC API v1.0.0 Collections specification.
Returns all collections in the catalog with metadata and navigation links.

Specification: https://api.stacspec.org/v1.0.0/collections

Endpoints:
- GET /api/stac/collections - List all STAC collections with metadata

Key Features:
- Returns array of collection objects with full metadata
- Includes spatial and temporal extents for each collection
- Provides navigation links (self, root, parent, items)
- Queries pgSTAC database for collection data

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

import azure.functions as func
import json
from typing import Dict, Any

from triggers.http_base import BaseHttpTrigger
from util_logger import LoggerFactory, ComponentType
from infrastructure.stac import get_all_collections

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "StacApiCollectionsTrigger")


class StacApiCollectionsTrigger(BaseHttpTrigger):
    """
    STAC API Collections List Trigger.

    Returns all STAC collections in the catalog with full metadata.
    """

    def process_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Process STAC API collections list request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            JSON object with collections array and links
        """
        try:
            logger.info("📚 STAC API Collections list requested")

            # Get all collections from pgSTAC
            response = get_all_collections()

            # Check for errors
            if 'error' in response:
                logger.error(f"❌ Error retrieving collections: {response['error']}")
                return func.HttpResponse(
                    json.dumps({
                        "error": response['error'],
                        "error_type": response.get('error_type', 'UnknownError')
                    }),
                    mimetype="application/json",
                    status_code=500
                )

            collections_count = len(response.get('collections', []))
            logger.info(f"✅ Returning {collections_count} STAC collections")

            return func.HttpResponse(
                json.dumps(response, indent=2),
                mimetype="application/json",
                status_code=200
            )

        except Exception as e:
            logger.error(f"❌ Error processing collections request: {e}", exc_info=True)
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                mimetype="application/json",
                status_code=500
            )


# Create trigger instance for function_app.py registration
stac_api_collections_trigger = StacApiCollectionsTrigger()
