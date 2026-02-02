# ============================================================================
# CLAUDE CONTEXT - REDOC INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - ReDoc API documentation
# PURPOSE: Serve ReDoc documentation viewer for OpenAPI spec
# LAST_REVIEWED: 02 FEB 2026
# EXPORTS: ReDocInterface
# INTERFACES: BaseInterface (base.py), InterfaceRegistry (__init__.py)
# DEPENDENCIES: azure.functions, json, pathlib
# PATTERNS: InterfaceRegistry decorator, CDN-loaded ReDoc, inlined spec
# ENTRY_POINTS: /api/interface/redoc
# FEATURE: F12.8 API Documentation Hub
# ============================================================================
"""
ReDoc Interface.

Serves ReDoc documentation viewer with the OpenAPI specification inlined.
ReDoc JS loaded from CDN, spec embedded in page for correct server URL.

Route: /api/interface/redoc
Updated: 02 FEB 2026 - Inline spec instead of fetching from endpoint
"""

import json
import logging
from pathlib import Path

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface

logger = logging.getLogger(__name__)

# =============================================================================
# ASSET LOADING (cached at module import time)
# =============================================================================

_OPENAPI_DIR = Path(__file__).parent.parent.parent / "openapi"
_OPENAPI_SPEC = {}

try:
    with open(_OPENAPI_DIR / "platform-api-v1.json", "r", encoding="utf-8") as f:
        _OPENAPI_SPEC = json.load(f)
    logger.info(f"Loaded OpenAPI spec for ReDoc: {_OPENAPI_SPEC.get('info', {}).get('title', 'Unknown')}")
except Exception as e:
    logger.error(f"Failed to load OpenAPI spec for ReDoc: {e}")


@InterfaceRegistry.register('redoc')
class ReDocInterface(BaseInterface):
    """
    ReDoc interface for API documentation.

    Features:
        - Clean, three-panel documentation layout
        - ReDoc JS loaded from CDN (lightweight)
        - OpenAPI spec inlined in page (correct server URL, no extra request)
        - Displays API version from spec
        - Navigation links to other interfaces
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate ReDoc HTML page."""

        # Get current host for API calls
        host = request.headers.get('Host', 'localhost')
        scheme = 'https' if 'azurewebsites.net' in host else 'http'
        base_url = f"{scheme}://{host}"

        # Update spec with current server URL
        spec = _OPENAPI_SPEC.copy() if _OPENAPI_SPEC else self._get_fallback_spec()
        spec['servers'] = [
            {
                'url': base_url,
                'description': 'Current deployment'
            }
        ]

        # Extract API version for display
        api_version = spec.get('info', {}).get('version', '0.8')

        spec_json = json.dumps(spec, indent=2)

        return self._generate_html(spec_json, base_url, api_version)

    def _get_fallback_spec(self) -> dict:
        """Return minimal fallback spec if loading failed."""
        return {
            "openapi": "3.0.1",
            "info": {
                "title": "Geospatial APIs",
                "version": "1.0.0",
                "description": "OpenAPI spec failed to load. Check server logs."
            },
            "paths": {}
        }

    def _generate_html(self, spec_json: str, base_url: str, api_version: str) -> str:
        """Generate complete HTML with ReDoc and inlined spec."""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation - ReDoc</title>
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>
        body {{
            margin: 0;
            padding: 0;
        }}

        .custom-header {{
            background: #053657;
            color: white;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: "Montserrat", sans-serif;
            position: sticky;
            top: 0;
            z-index: 1000;
        }}

        .custom-header h1 {{
            margin: 0;
            font-size: 20px;
            font-weight: 600;
        }}

        .custom-header .nav-links {{
            display: flex;
            gap: 20px;
        }}

        .custom-header a {{
            color: #00A3DA;
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
        }}

        .custom-header a:hover {{
            color: #FFC14D;
        }}

        .api-info {{
            background: #f0f4f8;
            padding: 12px 24px;
            border-bottom: 1px solid #ddd;
            font-family: "Roboto", sans-serif;
            font-size: 13px;
            color: #626F86;
        }}

        .api-info code {{
            background: #e2e8f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }}

        .api-info a {{
            color: #0071BC;
            text-decoration: none;
        }}

        .api-info a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="custom-header">
        <h1>Geospatial Platform API</h1>
        <div class="nav-links">
            <a href="/api/interface/home">Home</a>
            <a href="/api/interface/swagger">Swagger UI</a>
            <a href="/api/interface/docs">Platform Docs</a>
            <a href="/api/health">Health Check</a>
        </div>
    </div>

    <div class="api-info">
        Base URL: <code>{base_url}</code> |
        API Version: <code>{api_version}</code> |
        <a href="/api/openapi.json">Download OpenAPI JSON</a> |
        <a href="/api/interface/swagger">Try Interactive Swagger UI</a>
    </div>

    <div id="redoc-container"></div>

    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
    <script>
        // OpenAPI spec (inlined with current server URL)
        const spec = {spec_json};

        // Initialize ReDoc with inlined spec
        Redoc.init(spec, {{
            scrollYOffset: 100,
            hideDownloadButton: false,
            expandResponses: "200,201,202"
        }}, document.getElementById('redoc-container'));
    </script>
</body>
</html>"""
