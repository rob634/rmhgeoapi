# ============================================================================
# CLAUDE CONTEXT - STAC REPAIR ADMIN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Admin trigger - Direct STAC repair testing
# PURPOSE: HTTP endpoint to test STAC repair handlers without job orchestration
# LAST_REVIEWED: 23 DEC 2025
# EXPORTS: stac_repair_inventory_handler, stac_repair_test_handler
# DEPENDENCIES: services.stac_repair_handlers
# ============================================================================
"""
STAC Repair Admin Triggers.

Direct HTTP endpoints to test STAC repair functionality without going through
the Service Bus job orchestration. Useful for debugging and manual repairs.

Endpoints:
    GET  /api/admin/stac/repair/test - Test handler import and configuration
    POST /api/admin/stac/repair/inventory - Run inventory scan directly
    POST /api/admin/stac/repair/item - Repair a single item directly
"""

import azure.functions as func
import json
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "STACRepairAdmin")


def stac_repair_test_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Test that STAC repair handlers are properly configured.

    GET /api/admin/stac/repair/test

    Returns handler availability and configuration status.
    """
    logger.info("Testing STAC repair handler configuration")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": []
    }

    # Test 1: Import handlers
    try:
        from services.stac_repair_handlers import stac_repair_inventory, stac_repair_item
        results["tests"].append({
            "name": "import_handlers",
            "status": "success",
            "message": "Handlers imported successfully"
        })
    except Exception as e:
        results["tests"].append({
            "name": "import_handlers",
            "status": "failed",
            "error": str(e)
        })
        return func.HttpResponse(
            json.dumps(results, default=str),
            status_code=500,
            mimetype="application/json"
        )

    # Test 2: Check handler registration
    try:
        from services import ALL_HANDLERS
        inventory_registered = "stac_repair_inventory" in ALL_HANDLERS
        item_registered = "stac_repair_item" in ALL_HANDLERS
        results["tests"].append({
            "name": "handler_registration",
            "status": "success" if (inventory_registered and item_registered) else "warning",
            "stac_repair_inventory": inventory_registered,
            "stac_repair_item": item_registered
        })
    except Exception as e:
        results["tests"].append({
            "name": "handler_registration",
            "status": "failed",
            "error": str(e)
        })

    # Test 3: Check validation module
    try:
        from services.stac_validation import STACValidator, STACRepair, ValidationResult
        results["tests"].append({
            "name": "validation_module",
            "status": "success",
            "message": "STACValidator and STACRepair available"
        })
    except Exception as e:
        results["tests"].append({
            "name": "validation_module",
            "status": "failed",
            "error": str(e)
        })

    # Test 4: Check STAC models
    try:
        from core.models.stac import STAC_VERSION, STACItemCore
        results["tests"].append({
            "name": "stac_models",
            "status": "success",
            "stac_version": STAC_VERSION
        })
    except Exception as e:
        results["tests"].append({
            "name": "stac_models",
            "status": "failed",
            "error": str(e)
        })

    # Summary
    all_success = all(t.get("status") == "success" for t in results["tests"])
    results["overall_status"] = "ready" if all_success else "issues_found"

    return func.HttpResponse(
        json.dumps(results, default=str),
        status_code=200 if all_success else 500,
        mimetype="application/json"
    )


def stac_repair_inventory_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Run STAC repair inventory directly (bypass job orchestration).

    POST /api/admin/stac/repair/inventory

    Query Parameters:
        collection_id: Optional - limit to specific collection
        limit: Maximum items to scan (default: 100)
        prioritize_promoted: If true, return promoted items first (default: true)

    Returns:
        Inventory results with items that have issues
    """
    logger.info("Running STAC repair inventory directly")

    # Parse parameters
    collection_id = req.params.get('collection_id')
    limit = int(req.params.get('limit', '100'))
    prioritize_promoted = req.params.get('prioritize_promoted', 'true').lower() == 'true'

    params = {
        'collection_id': collection_id,
        'limit': limit,
        'prioritize_promoted': prioritize_promoted
    }

    logger.info(f"Inventory params: {params}")

    try:
        from services.stac_repair_handlers import stac_repair_inventory

        # Run handler directly
        result = stac_repair_inventory(params)

        logger.info(f"Inventory complete: {result.get('total_scanned', 0)} scanned, {len(result.get('items_with_issues', []))} with issues")

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "parameters": params,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Inventory failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "parameters": params,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, default=str),
            status_code=500,
            mimetype="application/json"
        )


def stac_repair_item_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Repair a single STAC item directly (bypass job orchestration).

    POST /api/admin/stac/repair/item?item_id=xxx&collection_id=yyy

    Query Parameters:
        item_id: STAC item ID to repair (required)
        collection_id: Collection the item belongs to (required)
        fix_version: Repair STAC version (default: true)
        fix_datetime: Add datetime if missing (default: true)
        fix_geometry: Derive geometry from bbox (default: true)

    Returns:
        Repair results
    """
    item_id = req.params.get('item_id')
    collection_id = req.params.get('collection_id')

    if not item_id or not collection_id:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": "Missing required parameters: item_id and collection_id",
                "usage": "POST /api/admin/stac/repair/item?item_id=xxx&collection_id=yyy"
            }),
            status_code=400,
            mimetype="application/json"
        )

    fix_version = req.params.get('fix_version', 'true').lower() == 'true'
    fix_datetime = req.params.get('fix_datetime', 'true').lower() == 'true'
    fix_geometry = req.params.get('fix_geometry', 'true').lower() == 'true'

    params = {
        'item_id': item_id,
        'collection_id': collection_id,
        'fix_version': fix_version,
        'fix_datetime': fix_datetime,
        'fix_geometry': fix_geometry
    }

    logger.info(f"Repairing STAC item: {item_id} in {collection_id}")

    try:
        from services.stac_repair_handlers import stac_repair_item

        # Run handler directly
        result = stac_repair_item(params)

        logger.info(f"Repair complete for {item_id}: repaired={result.get('repaired', False)}")

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "parameters": params,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Repair failed for {item_id}: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "parameters": params,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, default=str),
            status_code=500,
            mimetype="application/json"
        )


__all__ = [
    'stac_repair_test_handler',
    'stac_repair_inventory_handler',
    'stac_repair_item_handler'
]
