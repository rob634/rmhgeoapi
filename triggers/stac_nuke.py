"""
STAC Nuclear Button HTTP Trigger.

Development/testing endpoint for clearing STAC data without dropping schema.

Exports:
    StacNukeTrigger: HTTP trigger class for STAC data clearing
    stac_nuke_trigger: Singleton instance of StacNukeTrigger
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
