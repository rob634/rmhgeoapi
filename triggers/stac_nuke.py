# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC data clearing endpoint (DEV/TEST ONLY)
# PURPOSE: Nuclear button endpoint for clearing STAC items and collections without dropping schema
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: StacNukeTrigger, stac_nuke_trigger (instance)
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None - uses dict for responses
# DEPENDENCIES: triggers.http_base, infrastructure.stac, azure.functions, typing, json
# SOURCE: HTTP POST requests with query parameters (confirm, mode)
# SCOPE: DEV/TEST ONLY - Nuclear button for clearing STAC data without schema drop
# VALIDATION: Requires confirm=yes query parameter, validates mode parameter
# PATTERNS: Nuclear Button pattern (follows db_query.py SchemaNukeQueryTrigger)
# ENTRY_POINTS: POST /api/stac/nuke?confirm=yes&mode=all|items|collections
# INDEX: StacNukeTrigger:60, process_request:90
# ============================================================================

"""
STAC Nuclear Button HTTP Trigger - Clear Items and Collections

⚠️ DEVELOPMENT/TESTING ONLY - NOT FOR PRODUCTION USE

Provides HTTP endpoint for clearing STAC data from pgstac tables without
dropping the entire schema. This is much faster than full schema drop/recreate
and preserves all functions, indexes, and partitions.

Endpoint:
    POST /api/stac/nuke?confirm=yes&mode=all

Query Parameters:
    confirm: Must be "yes" (400 error if missing or wrong value)
    mode: Clearing mode (default: "all")
          - "items": Delete only items (preserve collections)
          - "collections": Delete collections (CASCADE deletes items)
          - "all": Delete both collections and items

Response:
    {
        "success": true,
        "mode": "all",
        "deleted": {
            "items": 1234,
            "collections": 5
        },
        "counts_before": {
            "items": 1234,
            "collections": 5
        },
        "execution_time_ms": 456.78,
        "warning": "⚠️ DEV/TEST ONLY - STAC data cleared (schema preserved)"
    }

Key Features:
- Preserves pgstac schema structure (functions, indexes, partitions)
- CASCADE automatically handles foreign key relationships
- Reports counts before and after deletion
- Execution time tracking
- Safety confirmation required

Use Cases:
- Development testing with fresh STAC state
- Integration test cleanup
- Demo resets without full schema rebuild
- Faster than full drop/recreate cycle

Comparison to Full Schema Drop:
- Nuclear Button: DELETE data, keep schema (fast, preserves structure)
- Schema Drop: DROP schema, reinstall pgstac (slow, full reset)

"""

from typing import Dict, Any, List
import json

import azure.functions as func

from triggers.http_base import BaseHttpTrigger
from infrastructure.pgstac_bootstrap import clear_stac_data
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "StacNuke")


class StacNukeTrigger(BaseHttpTrigger):
    """
    STAC Nuclear Button HTTP Trigger.

    ⚠️ DEV/TEST ONLY - Clears STAC items/collections without dropping schema.
    """

    def __init__(self):
        super().__init__("stac_nuke")

    def get_allowed_methods(self) -> List[str]:
        """Only POST allowed for nuclear button."""
        return ["POST"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process STAC nuclear button request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            Response dict with deletion results
        """
        # Get query parameters
        confirm = req.params.get('confirm', '').lower()
        mode = req.params.get('mode', 'all').lower()

        # Require explicit confirmation
        if confirm != 'yes':
            return {
                'success': False,
                'error': 'Confirmation required: add ?confirm=yes query parameter',
                'status_code': 400
            }

        # Validate mode
        valid_modes = ['all', 'items', 'collections']
        if mode not in valid_modes:
            return {
                'success': False,
                'error': f'Invalid mode: {mode}. Must be one of: {", ".join(valid_modes)}',
                'valid_modes': valid_modes,
                'status_code': 400
            }

        logger.warning(f"🚨 STAC NUCLEAR BUTTON ACTIVATED - Mode: {mode}")
        logger.warning("⚠️ This will DELETE STAC data (schema preserved)")

        # Execute nuclear button
        result = clear_stac_data(mode=mode)

        if not result.get('success'):
            logger.error(f"STAC nuke failed: {result.get('error')}")
            return {
                **result,
                'status_code': 500
            }

        logger.info(f"✅ STAC nuke completed successfully")
        logger.info(f"   Mode: {result['mode']}")
        logger.info(f"   Deleted items: {result['deleted']['items']}")
        logger.info(f"   Deleted collections: {result['deleted']['collections']}")
        logger.info(f"   Execution time: {result['execution_time_ms']}ms")

        return {
            **result,
            'status_code': 200
        }


# Create trigger instance for registration
stac_nuke_trigger = StacNukeTrigger()
