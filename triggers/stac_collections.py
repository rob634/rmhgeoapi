# ============================================================================
# STAC COLLECTION MANAGEMENT TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET/POST /api/stac/collections
# PURPOSE: Create and manage STAC collections mapped to Azure Storage containers
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: StacCollectionsTrigger, stac_collections_trigger
# DEPENDENCIES: infrastructure.pgstac_bootstrap
# ============================================================================
"""
STAC Collection Management Trigger.

HTTP endpoints for creating and managing STAC collections.

Exports:
    StacCollectionsTrigger: HTTP trigger class for STAC collection management
    stac_collections_trigger: Singleton instance of StacCollectionsTrigger
"""

from typing import Dict, Any, List, Optional
import json
import azure.functions as func

from triggers.http_base import BaseHttpTrigger, parse_request_json
from infrastructure.pgstac_bootstrap import PgStacBootstrap
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "StacCollectionsTrigger")


class StacCollectionsTrigger(BaseHttpTrigger):
    """
    STAC collection management trigger.

    Provides endpoints for creating and managing STAC collections
    mapped to Azure Storage containers.
    """

    def __init__(self):
        """Initialize the trigger."""
        super().__init__(trigger_name="stac_collections")
        self._stac = None  # Lazy-loaded to avoid config issues at import time

    @property
    def stac(self) -> PgStacBootstrap:
        """Lazy-load STAC infrastructure (avoids config loading at import time)."""
        if self._stac is None:
            self._stac = PgStacBootstrap()
        return self._stac

    def get_allowed_methods(self) -> List[str]:
        """Return allowed HTTP methods."""
        return ["POST"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle STAC collection requests.

        POST /api/stac/collections/{tier}  (tier: bronze, silver, gold)
        Body: {
            "container": "<bronze-container>",  # Required (use config.storage.{zone})
            "collection_id": "custom-id",       # Optional
            "title": "Custom Title",            # Optional
            "description": "Custom description" # Optional
        }

        Returns:
            Dict with collection creation results
        """
        method = req.method

        if method == "POST":
            # Extract tier from route parameters
            tier = req.route_params.get('tier')
            return self._create_collection(req, tier)

        return {
            'error': f'Method {method} not allowed',
            'allowed_methods': self.get_allowed_methods()
        }

    def _create_collection(self, req: func.HttpRequest, tier: Optional[str] = None) -> Dict[str, Any]:
        """
        Create STAC collection for any tier.

        Args:
            req: HTTP request with JSON body
            tier: Collection tier (bronze, silver, gold) - from route param

        Returns:
            Collection creation result
        """
        # Validate tier
        if not tier:
            logger.error("Missing tier in route parameters")
            return {
                'success': False,
                'error': 'Missing tier parameter - use /api/stac/collections/{tier}',
                'valid_tiers': ['bronze', 'silver', 'gold']
            }

        logger.info(f"📦 {tier.upper()} collection creation request")

        # Parse request body
        try:
            body = parse_request_json(req)
        except ValueError as e:
            logger.error(f"Invalid JSON in request body: {e}")
            return {
                'success': False,
                'error': 'Invalid JSON in request body',
                'details': str(e)
            }

        # Validate required parameters
        container = body.get('container')
        if not container:
            logger.error("Missing required parameter: container")
            return {
                'success': False,
                'error': 'Missing required parameter: container',
                'example': {
                    'container': '<bronze-container>',  # Use config.storage.bronze
                    'collection_id': f'{tier}-custom (optional)',
                    'title': 'Custom Title (optional)',
                    'description': 'Custom description (optional)'
                }
            }

        # Extract optional parameters
        collection_id = body.get('collection_id')
        title = body.get('title')
        description = body.get('description')
        summaries = body.get('summaries')

        logger.info(f"Creating {tier.upper()} collection for container: {container}")
        logger.debug(f"  collection_id: {collection_id or '(auto-generated)'}")
        logger.debug(f"  title: {title or '(auto-generated)'}")

        # Create collection
        try:
            result = self.stac.create_collection(
                container=container,
                tier=tier,
                collection_id=collection_id,
                title=title,
                description=description,
                summaries=summaries
            )

            if result.get('success'):
                logger.info(f"✅ {tier.upper()} collection created: {result.get('collection_id')}")
            else:
                logger.warning(f"⚠️ Collection creation returned success=False: {result.get('error')}")

            return result

        except Exception as e:
            logger.error(f"❌ Unexpected error creating {tier} collection: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': f'Unexpected error during {tier} collection creation',
                'details': str(e),
                'error_type': type(e).__name__
            }


# ============================================================================
# TRIGGER INSTANCE - For registration in function_app.py
# ============================================================================

stac_collections_trigger = StacCollectionsTrigger()
