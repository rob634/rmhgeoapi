# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - STAC collection management for data tiers
# PURPOSE: STAC collection management endpoints for Bronze/Silver/Gold tiers
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: StacCollectionsTrigger, stac_collections_trigger (singleton)
# INTERFACES: BaseHttpTrigger (inherited from http_base)
# PYDANTIC_MODELS: None - uses dict responses
# DEPENDENCIES: http_base.BaseHttpTrigger, infrastructure.stac.StacInfrastructure, util_logger
# SOURCE: HTTP POST requests with container/collection parameters
# SCOPE: STAC catalog management - collection creation for data tier organization
# VALIDATION: Container name validation, JSON request body validation, collection ID validation
# PATTERNS: Template Method (base class), Lazy initialization (STAC infrastructure), Tier-based organization
# ENTRY_POINTS: POST /api/stac/collections/bronze
# INDEX: StacCollectionsTrigger:62, process_request:92, _create_bronze:132
# ============================================================================

"""
STAC Collection Management Trigger

HTTP endpoints for creating and managing STAC collections.
Currently supports Bronze tier collections with container parameter.

Endpoints:
- POST /api/stac/collections/bronze - Create Bronze collection

Author: Robert and Geospatial Claude Legion
Date: 5 OCT 2025
Last Updated: 29 OCT 2025
"""

from typing import Dict, Any, List, Optional
import json
import azure.functions as func

from triggers.http_base import BaseHttpTrigger
from infrastructure.stac import StacInfrastructure
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
    def stac(self) -> StacInfrastructure:
        """Lazy-load STAC infrastructure (avoids config loading at import time)."""
        if self._stac is None:
            self._stac = StacInfrastructure()
        return self._stac

    def get_allowed_methods(self) -> List[str]:
        """Return allowed HTTP methods."""
        return ["POST"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Handle STAC collection requests.

        POST /api/stac/collections/{tier}  (tier: bronze, silver, gold)
        Body: {
            "container": "rmhazuregeobronze",  # Required (use config.storage.{zone}.get_container())
            "collection_id": "custom-id",      # Optional
            "title": "Custom Title",           # Optional
            "description": "Custom description"# Optional
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
            body = req.get_json()
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
                    'container': 'rmhazuregeobronze',  # Use config container name
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
