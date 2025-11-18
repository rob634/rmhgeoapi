# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - PgSTAC schema inspection and deep query endpoints
# PURPOSE: Detailed inspection of pgstac schema health, statistics, and item lookup
# LAST_REVIEWED: 2 NOV 2025
# EXPORTS: stac_inspect_trigger (StacInspectTrigger instance), StacInspectTrigger
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None (uses dict responses)
# DEPENDENCIES: http_base.BaseHttpTrigger, infrastructure.stac, util_logger
# SOURCE: HTTP GET requests to /api/stac/* inspection endpoints
# SCOPE: PgSTAC schema inspection - detailed statistics, health metrics, item lookup
# VALIDATION: Collection ID validation, item ID validation, query parameter validation
# PATTERNS: Template Method (base class), Infrastructure delegation, Read-only operations
# ENTRY_POINTS: GET /api/stac/schema/info, GET /api/stac/collections/{id}/stats, etc.
# INDEX: StacInspectTrigger:50, process_request:80, route handlers:150+
# ============================================================================

"""
STAC Inspection HTTP Trigger

Provides deep inspection endpoints for pgstac schema analysis and statistics.
All endpoints are READ-ONLY and safe to call at any time.

Endpoints:
- GET /api/stac/schema/info                      - Detailed schema structure inspection
- GET /api/stac/collections/{collection_id}/stats - Collection-level statistics
- GET /api/stac/items/{item_id}                   - Single item lookup (cross-collection)
- GET /api/stac/health                            - Overall pgstac health metrics
- GET /api/stac/collections/summary               - Quick summary of all collections

Key Features:
- Deep schema inspection (tables, indexes, sizes, row counts)
- Collection statistics (item counts, spatial/temporal extent, asset types)
- Item lookup by ID (with optional collection filtering)
- Health monitoring (status, counts, issues detection)
- Performance-friendly queries (optimized for read-only access)

Author: Robert and Geospatial Claude Legion
Date: 2 NOV 2025
"""

import azure.functions as func
from typing import Dict, Any, List

from triggers.http_base import BaseHttpTrigger
from util_logger import LoggerFactory, ComponentType
from infrastructure.pgstac_bootstrap import (
    get_schema_info,
    get_collection_stats,
    get_item_by_id,
    get_health_metrics,
    get_collections_summary
)

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "StacInspectTrigger")


class StacInspectTrigger(BaseHttpTrigger):
    """
    HTTP trigger for STAC inspection operations.

    Provides read-only endpoints for deep inspection of pgstac schema,
    collections, items, and overall health metrics.
    """

    def __init__(self):
        """Initialize the trigger."""
        super().__init__(trigger_name="stac_inspect")

    def get_allowed_methods(self) -> List[str]:
        """Return allowed HTTP methods (GET only for read-only operations)."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle STAC inspection requests.

        Routes requests to appropriate inspection handlers based on URL route.

        Supported routes:
        - /api/stac/schema/info                      → get_schema_info()
        - /api/stac/collections/{collection_id}/stats → get_collection_stats()
        - /api/stac/items/{item_id}                   → get_item_by_id()
        - /api/stac/health                            → get_health_metrics()
        - /api/stac/collections/summary               → get_collections_summary()

        Args:
            req: HTTP request with route_params

        Returns:
            Dictionary with inspection results

        Raises:
            ValueError: If route not recognized or required parameters missing
        """
        # Get route from request (will be set by function_app.py routing)
        route = req.route_params.get('route', '')

        logger.info(f"🔍 STAC Inspection request: route='{route}'")

        # Route to appropriate handler
        if route == 'schema/info':
            return self._handle_schema_info(req)
        elif route == 'collections/summary':
            return self._handle_collections_summary(req)
        elif route == 'health':
            return self._handle_health(req)
        elif 'collections' in route and 'stats' in route:
            return self._handle_collection_stats(req)
        elif route.startswith('items/'):
            return self._handle_item_lookup(req)
        else:
            raise ValueError(f"Unknown inspection route: {route}")

    # =========================================================================
    # Route Handlers
    # =========================================================================

    def _handle_schema_info(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET /api/stac/schema/info

        Returns detailed pgstac schema structure including:
        - Tables (with row counts, sizes, indexes)
        - Functions (first 20)
        - Roles
        - Total schema size

        Returns:
            Schema inspection results
        """
        logger.info("📊 Getting pgstac schema info...")
        return get_schema_info()

    def _handle_collection_stats(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET /api/stac/collections/{collection_id}/stats

        Returns detailed statistics for a specific collection:
        - Item count
        - Spatial extent (actual bbox from items)
        - Temporal extent
        - Asset types and counts
        - Recent items

        Args:
            req: HTTP request with collection_id in route_params

        Returns:
            Collection statistics

        Raises:
            ValueError: If collection_id not provided
        """
        collection_id = req.route_params.get('collection_id')

        if not collection_id:
            raise ValueError("collection_id required in route")

        logger.info(f"📊 Getting stats for collection '{collection_id}'...")
        return get_collection_stats(collection_id)

    def _handle_item_lookup(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET /api/stac/items/{item_id}

        Query parameters:
            collection_id: Optional collection ID to narrow search

        Returns:
            STAC Item JSON or error dict

        Raises:
            ValueError: If item_id not provided
        """
        item_id = req.route_params.get('item_id')

        if not item_id:
            raise ValueError("item_id required in route")

        # Optional: narrow search to specific collection
        collection_id = req.params.get('collection_id')

        logger.info(f"🔍 Looking up item '{item_id}'" +
                   (f" in collection '{collection_id}'" if collection_id else ""))

        return get_item_by_id(item_id, collection_id)

    def _handle_health(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET /api/stac/health

        Returns overall pgstac health metrics:
        - Status (healthy/warning/error)
        - Version
        - Collection/item counts
        - Database size
        - Issues detected

        Returns:
            Health metrics dict
        """
        logger.info("🏥 Checking pgstac health...")
        return get_health_metrics()

    def _handle_collections_summary(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle GET /api/stac/collections/summary

        Returns quick summary of all collections:
        - Total collections
        - Total items
        - Per-collection item counts
        - Last updated timestamps

        Returns:
            Collections summary dict
        """
        logger.info("📋 Getting collections summary...")
        return get_collections_summary()


# ============================================================================
# TRIGGER INSTANCE - For registration in function_app.py
# ============================================================================

stac_inspect_trigger = StacInspectTrigger()
