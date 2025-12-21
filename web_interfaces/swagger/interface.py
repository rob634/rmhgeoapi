"""
Swagger UI Interface.

Serves interactive OpenAPI documentation via Swagger UI with all assets inlined.
No external dependencies - completely self-contained.

Route: /api/interface/swagger
"""

import json
import logging
import os
from pathlib import Path

import azure.functions as func
import yaml

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface

logger = logging.getLogger(__name__)

# =============================================================================
# ASSET LOADING (cached at module import time)
# =============================================================================

_ASSETS_DIR = Path(__file__).parent / "assets"
_OPENAPI_DIR = Path(__file__).parent.parent.parent / "openapi"

# Load assets once at import time
_SWAGGER_JS = ""
_SWAGGER_CSS = ""
_OPENAPI_SPEC = {}

try:
    with open(_ASSETS_DIR / "swagger-ui-bundle.js", "r", encoding="utf-8") as f:
        _SWAGGER_JS = f.read()
    logger.info(f"Loaded swagger-ui-bundle.js ({len(_SWAGGER_JS):,} bytes)")
except Exception as e:
    logger.error(f"Failed to load swagger-ui-bundle.js: {e}")

try:
    with open(_ASSETS_DIR / "swagger-ui.css", "r", encoding="utf-8") as f:
        _SWAGGER_CSS = f.read()
    logger.info(f"Loaded swagger-ui.css ({len(_SWAGGER_CSS):,} bytes)")
except Exception as e:
    logger.error(f"Failed to load swagger-ui.css: {e}")

try:
    with open(_OPENAPI_DIR / "platform-api-v1.yaml", "r", encoding="utf-8") as f:
        _OPENAPI_SPEC = yaml.safe_load(f)
    logger.info(f"Loaded OpenAPI spec: {_OPENAPI_SPEC.get('info', {}).get('title', 'Unknown')}")
except Exception as e:
    logger.error(f"Failed to load OpenAPI spec: {e}")


@InterfaceRegistry.register('swagger')
class SwaggerInterface(BaseInterface):
    """
    Swagger UI interface for interactive API documentation.

    Features:
        - Completely self-contained (no CDN dependencies)
        - Assets inlined in HTML response
        - OpenAPI spec loaded from openapi/platform-api-v1.yaml
        - Auto-detects current host for try-it-out functionality
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Swagger UI HTML page."""

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

        spec_json = json.dumps(spec, indent=2)

        return self._generate_html(spec_json, base_url)

    def _get_fallback_spec(self) -> dict:
        """Return minimal fallback spec if loading failed."""
        return {
            "openapi": "3.0.1",
            "info": {
                "title": "Geospatial Platform API",
                "version": "1.0.0",
                "description": "OpenAPI spec failed to load. Check server logs."
            },
            "paths": {}
        }

    def _generate_html(self, spec_json: str, base_url: str) -> str:
        """Generate complete HTML with inlined Swagger UI."""

        # Check if assets loaded
        if not _SWAGGER_JS or not _SWAGGER_CSS:
            return self._generate_error_html()

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation - Swagger UI</title>
    <style>
        /* Swagger UI CSS */
        {_SWAGGER_CSS}

        /* Custom overrides */
        body {{
            margin: 0;
            padding: 0;
        }}

        .swagger-ui .topbar {{
            display: none;
        }}

        .custom-header {{
            background: #053657;
            color: white;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: "Open Sans", sans-serif;
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
            font-family: "Open Sans", sans-serif;
            font-size: 13px;
            color: #626F86;
        }}

        .api-info code {{
            background: #e2e8f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }}
    </style>
</head>
<body>
    <div class="custom-header">
        <h1>Geospatial Platform API Documentation</h1>
        <div class="nav-links">
            <a href="/api/interface/home">Home</a>
            <a href="/api/interface/docs">Static Docs</a>
            <a href="/api/interface/platform">Platform</a>
            <a href="/api/health">Health Check</a>
        </div>
    </div>

    <div class="api-info">
        Base URL: <code>{base_url}</code> |
        OpenAPI Version: <code>3.0.1</code> |
        <a href="/api/openapi.json" style="color: #0071BC;">Download OpenAPI JSON</a>
    </div>

    <div id="swagger-ui"></div>

    <script>
        {_SWAGGER_JS}
    </script>

    <script>
        // OpenAPI spec (inlined)
        const spec = {spec_json};

        // Initialize Swagger UI
        window.onload = function() {{
            window.ui = SwaggerUIBundle({{
                spec: spec,
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "BaseLayout",
                defaultModelsExpandDepth: 1,
                defaultModelExpandDepth: 1,
                docExpansion: "list",
                filter: true,
                showExtensions: true,
                showCommonExtensions: true,
                tryItOutEnabled: true
            }});
        }};
    </script>
</body>
</html>"""

    def _generate_error_html(self) -> str:
        """Generate error page if assets failed to load."""
        return """<!DOCTYPE html>
<html>
<head>
    <title>Swagger UI - Error</title>
    <style>
        body {
            font-family: sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: #f8f9fa;
        }
        .error-box {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 500px;
        }
        h1 { color: #dc3545; }
        p { color: #666; }
        a { color: #0071BC; }
    </style>
</head>
<body>
    <div class="error-box">
        <h1>Failed to Load Swagger UI</h1>
        <p>The Swagger UI assets could not be loaded. This usually means the asset files are missing from the deployment.</p>
        <p>Check that these files exist:</p>
        <ul style="text-align: left;">
            <li><code>web_interfaces/swagger/assets/swagger-ui-bundle.js</code></li>
            <li><code>web_interfaces/swagger/assets/swagger-ui.css</code></li>
        </ul>
        <p><a href="/api/interface/docs">View Static Documentation Instead</a></p>
    </div>
</body>
</html>"""
