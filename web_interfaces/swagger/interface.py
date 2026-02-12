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

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface
from config import __version__

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
    with open(_OPENAPI_DIR / "platform-api-v1.json", "r", encoding="utf-8") as f:
        _OPENAPI_SPEC = json.load(f)
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
        base_url = self.get_base_url(request)

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
                "title": "Geospatial APIs",
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

        /* Custom overrides for readable, consistent typography */
        body {{
            margin: 0;
            padding: 0;
            font-size: 15px;
        }}

        .swagger-ui .topbar {{
            display: none;
        }}

        /* Base font sizing - make everything more readable */
        .swagger-ui {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 15px;
            line-height: 1.6;
        }}

        /* Operation blocks - endpoint titles */
        .swagger-ui .opblock-summary-method {{
            font-size: 14px;
            font-weight: 700;
            min-width: 70px;
        }}

        .swagger-ui .opblock-summary-path {{
            font-size: 15px;
            font-weight: 600;
        }}

        .swagger-ui .opblock-summary-description {{
            font-size: 14px;
            color: #555;
        }}

        /* Parameter names and descriptions - FIX SIZE MISMATCH */
        .swagger-ui .parameters-col_name {{
            font-size: 14px;
            font-weight: 600;
            color: #333;
        }}

        .swagger-ui .parameters-col_description {{
            font-size: 14px;
            line-height: 1.5;
        }}

        .swagger-ui .parameters-col_description p {{
            font-size: 14px;
            margin: 4px 0;
        }}

        .swagger-ui .parameter__name {{
            font-size: 14px;
            font-weight: 600;
        }}

        .swagger-ui .parameter__type {{
            font-size: 13px;
            color: #666;
        }}

        .swagger-ui .parameter__in {{
            font-size: 12px;
            color: #888;
        }}

        /* Schema/Model properties */
        .swagger-ui .model-box {{
            font-size: 14px;
        }}

        .swagger-ui .model {{
            font-size: 14px;
        }}

        .swagger-ui .model-title {{
            font-size: 15px;
            font-weight: 600;
        }}

        .swagger-ui .prop-name {{
            font-size: 14px;
            font-weight: 600;
        }}

        .swagger-ui .prop-type {{
            font-size: 13px;
        }}

        /* Request/Response body */
        .swagger-ui .body-param__text {{
            font-size: 14px;
        }}

        .swagger-ui .response-col_status {{
            font-size: 14px;
            font-weight: 600;
        }}

        .swagger-ui .response-col_description {{
            font-size: 14px;
        }}

        /* Code blocks and examples */
        .swagger-ui .highlight-code {{
            font-size: 13px;
        }}

        .swagger-ui pre {{
            font-size: 13px;
            line-height: 1.5;
        }}

        .swagger-ui code {{
            font-size: 13px;
        }}

        /* INLINE CODE in descriptions - tone down the jarring purple */
        .swagger-ui .markdown code,
        .swagger-ui .renderedMarkdown code,
        .swagger-ui .info .description code,
        .swagger-ui .opblock-description code,
        .swagger-ui .opblock-description-wrapper code,
        .swagger-ui p code {{
            font-size: 13px;
            font-weight: 500;
            color: #1a5276;
            background: #eaf2f8;
            padding: 1px 5px;
            border-radius: 3px;
            font-family: "SF Mono", Monaco, Consolas, monospace;
        }}

        /* Ensure inline code doesn't look bigger than surrounding text */
        .swagger-ui .info .description p code {{
            font-size: 14px;
        }}

        .swagger-ui .opblock-body .opblock-description code {{
            font-size: 13px;
        }}

        /* Info section at top */
        .swagger-ui .info {{
            margin: 20px 0;
        }}

        .swagger-ui .info .title {{
            font-size: 28px;
            font-weight: 700;
        }}

        .swagger-ui .info .description {{
            font-size: 15px;
            line-height: 1.6;
        }}

        .swagger-ui .info .description p {{
            font-size: 15px;
            margin: 12px 0;
        }}

        .swagger-ui .info .description h2 {{
            font-size: 20px;
            margin-top: 24px;
        }}

        .swagger-ui .info .description h3 {{
            font-size: 17px;
            margin-top: 20px;
        }}

        .swagger-ui .info .description li {{
            font-size: 15px;
            margin: 6px 0;
        }}

        /* Tag sections */
        .swagger-ui .opblock-tag {{
            font-size: 18px;
            font-weight: 600;
            border-bottom: 2px solid #eee;
            padding: 16px 0;
        }}

        .swagger-ui .opblock-tag small {{
            font-size: 14px;
            color: #666;
        }}

        /* Input fields */
        .swagger-ui input[type=text],
        .swagger-ui textarea {{
            font-size: 14px;
        }}

        .swagger-ui select {{
            font-size: 14px;
        }}

        /* Buttons */
        .swagger-ui .btn {{
            font-size: 14px;
        }}

        /* Table headers */
        .swagger-ui table thead tr th {{
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            color: #666;
        }}

        /* Standard navbar - matches all other interfaces */
        .site-navbar {{
            background: white;
            padding: 15px 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 3px solid #0071BC;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        }}

        .site-navbar .navbar-brand {{
            font-size: 20px;
            font-weight: 700;
            color: #053657;
            text-decoration: none;
            transition: color 0.2s;
        }}

        .site-navbar .navbar-brand:hover {{
            color: #0071BC;
        }}

        .site-navbar .navbar-links {{
            display: flex;
            gap: 20px;
        }}

        .site-navbar .navbar-links a {{
            color: #0071BC;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            transition: color 0.2s;
        }}

        .site-navbar .navbar-links a:hover {{
            color: #00A3DA;
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
    <nav class="site-navbar">
        <a href="/api/interface/home" class="navbar-brand">Geospatial API v{__version__}</a>
        <div class="navbar-links">
            <a href="/api/interface/health">System</a>
            <a href="/api/interface/pipeline">Pipelines</a>
            <a href="/api/interface/stac">STAC</a>
            <a href="/api/interface/vector">OGC Features</a>
            <a href="/api/interface/docs">API Docs</a>
        </div>
    </nav>

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
