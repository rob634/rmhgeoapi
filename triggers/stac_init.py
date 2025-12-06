"""
STAC Initialization Trigger.

HTTP endpoint to initialize STAC production collections for Bronze/Silver/Gold tiers.

Exports:
    handle_request: HTTP trigger function for POST /api/stac/init
"""

import azure.functions as func
from typing import Dict, Any
import json
import logging

from infrastructure.pgstac_bootstrap import PgStacBootstrap
from config.defaults import STACDefaults

logger = logging.getLogger(__name__)


def handle_request(req: func.HttpRequest) -> func.HttpResponse:
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
    try:
        # Parse request
        body = req.get_json() if req.get_body() else {}
        collections_to_create = body.get('collections', STACDefaults.VALID_USER_COLLECTIONS)

        stac = PgStacBootstrap()
        results = {}

        for collection_type in collections_to_create:
            logger.info(f"Creating collection: {collection_type}")
            result = stac.create_production_collection(collection_type)
            results[collection_type] = result

        # Check if all succeeded
        all_success = all(r.get('success', False) for r in results.values())

        response = {
            'success': all_success,
            'collections_created': [k for k, v in results.items() if v.get('success')],
            'collections_failed': [k for k, v in results.items() if not v.get('success')],
            'results': results
        }

        return func.HttpResponse(
            json.dumps(response, indent=2),
            mimetype="application/json",
            status_code=200 if all_success else 207  # 207 Multi-Status if partial success
        )

    except Exception as e:
        logger.error(f"STAC init failed: {e}")
        return func.HttpResponse(
            json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }, indent=2),
            mimetype="application/json",
            status_code=500
        )


# Create trigger instance
stac_init_trigger = type('StacInitTrigger', (), {'handle_request': staticmethod(handle_request)})()
