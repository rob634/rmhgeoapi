# ============================================================================
# STAC ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for STAC administration routes
# PURPOSE: STAC initialization, data clearing, and repair endpoints
# CREATED: 12 JAN 2026 (Consolidated from function_app.py)
# UPDATED: 12 JAN 2026 (Removed stac/setup - use dbadmin/maintenance instead)
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
STAC Admin Blueprint - STAC administration routes.

Routes (6 total):
    Init & Data (3):
        POST /api/stac/init               - Initialize production collections
        POST /api/stac/collections/{tier} - Create tier collection (bronze/silver/gold)
        POST /api/stac/nuke               - Clear STAC data (DEV/TEST ONLY)

    Repair (3):
        GET  /api/stac/repair/test         - Test repair handler availability
        POST /api/stac/repair/inventory    - Generate STAC health inventory
        POST /api/stac/repair/item         - Repair specific STAC item

NOTE: PgSTAC schema rebuild is handled by /api/dbadmin/maintenance?action=rebuild
"""

import azure.functions as func
from azure.functions import Blueprint

bp = Blueprint()


# ============================================================================
# STAC INITIALIZATION & DATA (3 routes)
# ============================================================================
# NOTE: stac/setup REMOVED (12 JAN 2026) - Use /api/dbadmin/maintenance?action=rebuild instead

@bp.route(route="stac/init", methods=["POST"])
def stac_init(req: func.HttpRequest) -> func.HttpResponse:
    """
    Initialize STAC production collections.

    POST /api/stac/init

    Body (optional):
        {
            "collections": ["dev", "cogs", "vectors", "geoparquet"]  // Default: all
        }

    Returns:
        Results for each collection creation
    """
    from triggers.stac_init import stac_init_trigger
    return stac_init_trigger.handle_request(req)


@bp.route(route="stac/collections/{tier}", methods=["POST"])
def stac_collections(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC collection management for Bronze/Silver/Gold tiers.

    POST /api/stac/collections/{tier} where tier is: bronze, silver, or gold

    Body:
        {
            "container": "<bronze-container>",  // Required (use config.storage.bronze)
            "collection_id": "custom-id",       // Optional
            "title": "Custom Title",            // Optional
            "description": "Custom description" // Optional
        }

    Returns:
        Collection creation result with collection_id
    """
    from triggers.stac_collections import stac_collections_trigger
    return stac_collections_trigger.handle_request(req)


@bp.route(route="stac/nuke", methods=["POST"])
def nuke_stac_data(req: func.HttpRequest) -> func.HttpResponse:
    """
    NUCLEAR: Clear STAC items/collections (DEV/TEST ONLY)

    POST /api/stac/nuke?confirm=yes&mode=all

    Query Parameters:
        confirm: Must be "yes" (required)
        mode: Clearing mode (default: "all")
              - "items": Delete only items (preserve collections)
              - "collections": Delete collections (CASCADE deletes items)
              - "all": Delete both collections and items

    Returns:
        Deletion results with counts and execution time

    WARNING: This clears STAC data but preserves pgstac schema (functions, indexes, partitions)
    Much faster than full schema drop/recreate cycle
    """
    from triggers.stac_nuke import stac_nuke_trigger
    return stac_nuke_trigger.handle_request(req)


# ============================================================================
# STAC REPAIR (3 routes)
# ============================================================================

@bp.route(route="stac/repair/test", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_repair_test(req: func.HttpRequest) -> func.HttpResponse:
    """
    Test STAC repair handler configuration.

    GET /api/stac/repair/test

    Returns handler availability and configuration status.
    """
    from triggers.admin.stac_repair import stac_repair_test_handler
    return stac_repair_test_handler(req)


@bp.route(route="stac/repair/inventory", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_repair_inventory_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    Run STAC repair inventory directly (bypass job orchestration).

    POST /api/stac/repair/inventory?collection_id=xxx&limit=100

    Query Parameters:
        collection_id: Optional - limit to specific collection
        limit: Maximum items to scan (default: 100)
        prioritize_promoted: If true, return promoted items first (default: true)
    """
    from triggers.admin.stac_repair import stac_repair_inventory_handler
    return stac_repair_inventory_handler(req)


@bp.route(route="stac/repair/item", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_repair_item_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    Repair a single STAC item directly (bypass job orchestration).

    POST /api/stac/repair/item?item_id=xxx&collection_id=yyy

    Query Parameters:
        item_id: STAC item ID to repair (required)
        collection_id: Collection the item belongs to (required)
        fix_version: Repair STAC version (default: true)
        fix_datetime: Add datetime if missing (default: true)
        fix_geometry: Derive geometry from bbox (default: true)
    """
    from triggers.admin.stac_repair import stac_repair_item_handler
    return stac_repair_item_handler(req)
