# ============================================================================
# CLAUDE CONTEXT - VECTOR VIEWER INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Vector Collection QA Viewer
# PURPOSE: MapLibre/Leaflet interface for vector data QA with approve/reject
# CREATED: 07 FEB 2026 (moved from vector_viewer/)
# EXPORTS: VectorViewerInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
Vector Viewer Interface.

Interactive Leaflet map for viewing vector collections via OGC Features API.
Supports feature loading, styling, and QA workflow with approve/reject.

Features:
    - Collection metadata display
    - Feature loading with limit/bbox/simplification controls
    - Interactive map with feature popups
    - QA section with Approve/Reject buttons
    - Embed mode for iframe integration (?embed=true)

Route: /api/interface/vector-viewer?collection={collection_id}
"""

import logging
import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('vector-viewer')
class VectorViewerInterface(BaseInterface):
    """
    Vector Viewer Interface with QA workflow.

    Displays vector collections on Leaflet map via OGC Features API with
    interactive controls and approve/reject functionality.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate full-page vector viewer.

        Query Parameters:
            collection (required): Collection ID (PostGIS table name)
            embed: Set to 'true' for iframe embedding (hides navbar)

        Args:
            request: Azure Functions HTTP request

        Returns:
            Complete HTML page string
        """
        from .service import VectorViewerService

        # Get required collection parameter
        collection_id = request.params.get('collection')

        if not collection_id:
            return self._error_page("Missing required parameter: collection")

        # Optional asset_id for approve/reject workflow (09 FEB 2026)
        asset_id = request.params.get('asset_id')

        logger.info(f"Vector Viewer request: collection={collection_id}, embed={self.embed_mode}, asset_id={asset_id}")

        # Get host URL from request for absolute API paths
        host_url = None
        if hasattr(request, 'url'):
            url_parts = request.url.split('/api/')
            if len(url_parts) > 0:
                host_url = url_parts[0]
                logger.debug(f"Detected host URL: {host_url}")

        try:
            # Initialize service and generate HTML
            service = VectorViewerService()
            html = service.generate_viewer_html(
                collection_id=collection_id,
                host_url=host_url,
                embed_mode=self.embed_mode,
                asset_id=asset_id
            )

            logger.info(f"Generated viewer for {collection_id} ({len(html)} bytes)")
            return html

        except Exception as e:
            logger.error(f"Error generating vector viewer: {e}", exc_info=True)
            return self._error_page(f"Error generating viewer: {str(e)}")

    def _error_page(self, message: str) -> str:
        """Generate simple error page."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>Vector Viewer - Error</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #fee;
            padding: 40px;
            text-align: center;
        }}
        .error-box {{
            background: white;
            border: 2px solid #c33;
            border-radius: 8px;
            padding: 30px;
            max-width: 600px;
            margin: 0 auto;
        }}
        h1 {{ color: #c33; }}
    </style>
</head>
<body>
    <div class="error-box">
        <h1>Error</h1>
        <p>{message}</p>
        <p><a href="/api/interface/home">Back to Home</a></p>
    </div>
</body>
</html>"""
