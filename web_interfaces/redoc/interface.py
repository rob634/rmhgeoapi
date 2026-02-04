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
from config import __version__

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
            position: sticky;
            top: 0;
            z-index: 1000;
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

        /* ReDoc typography overrides for consistent, readable text */

        /* Main content area */
        [data-role="redoc"] {{
            font-size: 15px;
        }}

        /* API description text */
        .api-content {{
            font-size: 15px;
            line-height: 1.7;
        }}

        /* Endpoint paths */
        .http-verb {{
            font-size: 13px !important;
            font-weight: 700;
        }}

        /* Parameter names - fix size mismatch */
        td[kind="field"] {{
            font-size: 14px;
        }}

        /* Schema property names */
        .property-name {{
            font-size: 14px;
            font-weight: 600;
        }}

        /* Type labels */
        .property-type {{
            font-size: 13px;
        }}

        /* Description text */
        .property-description {{
            font-size: 14px;
            line-height: 1.6;
        }}

        /* Response status codes */
        .response-status {{
            font-size: 14px;
            font-weight: 600;
        }}

        /* Code samples */
        pre, code {{
            font-size: 13px !important;
            line-height: 1.5;
        }}

        /* Menu items in left sidebar */
        .menu-item {{
            font-size: 14px;
        }}

        /* Section headers */
        h1 {{
            font-size: 28px;
        }}

        h2 {{
            font-size: 22px;
        }}

        h3 {{
            font-size: 18px;
        }}

        h5 {{
            font-size: 14px;
        }}

        /* Table of parameters */
        table {{
            font-size: 14px;
        }}

        th {{
            font-size: 13px;
            font-weight: 600;
        }}

        td {{
            font-size: 14px;
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
            <a href="/api/interface/gallery">Gallery</a>
            <a href="/api/interface/docs">API Docs</a>
        </div>
    </nav>

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

        // Initialize ReDoc with inlined spec and custom theme
        Redoc.init(spec, {{
            scrollYOffset: 100,
            hideDownloadButton: false,
            expandResponses: "200,201,202",
            theme: {{
                typography: {{
                    fontSize: '15px',
                    lineHeight: '1.6',
                    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
                    headings: {{
                        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
                        fontWeight: '600'
                    }},
                    code: {{
                        fontSize: '13px',
                        fontFamily: '"SF Mono", Monaco, "Cascadia Code", Consolas, monospace',
                        lineHeight: '1.5'
                    }}
                }},
                sidebar: {{
                    width: '280px',
                    textColor: '#333',
                    backgroundColor: '#fafafa'
                }},
                rightPanel: {{
                    backgroundColor: '#1e2430'
                }},
                colors: {{
                    primary: {{
                        main: '#0071BC'
                    }},
                    text: {{
                        primary: '#333',
                        secondary: '#666'
                    }},
                    http: {{
                        get: '#28a745',
                        post: '#0071BC',
                        put: '#fd7e14',
                        delete: '#dc3545'
                    }}
                }}
            }}
        }}, document.getElementById('redoc-container'));
    </script>
</body>
</html>"""
