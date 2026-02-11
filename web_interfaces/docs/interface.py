"""
Platform API Documentation Hub.

Landing page with links to interactive documentation (Swagger UI, ReDoc).
Endpoint details are maintained in the OpenAPI spec - this page provides
overview, workflow guidance, and links to the auto-generated docs.

Route: /api/interface/docs
Updated: 02 FEB 2026 - Simplified to landing page, endpoint docs via OpenAPI
"""

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface
from config import __version__


@InterfaceRegistry.register('docs')
class DocsInterface(BaseInterface):
    """
    Platform API documentation landing page.

    Provides:
        - Overview of the Platform API
        - Workflow diagram (submit → poll → approve)
        - Links to Swagger UI and ReDoc
        - Key concepts (three-state model, version lineage)

    For endpoint details, see:
        - /api/interface/swagger - Interactive testing
        - /api/interface/redoc - Read-only documentation
        - /api/openapi.json - Raw OpenAPI spec
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate documentation landing page."""
        host = request.headers.get('Host', 'localhost')
        scheme = 'https' if 'azurewebsites.net' in host else 'http'
        base_url = f"{scheme}://{host}"

        return self._generate_html(base_url)

    def _generate_html(self, base_url: str) -> str:
        """Generate the landing page HTML."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Platform API Documentation</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }}

        /* Standard navbar - matches all other interfaces */
        .site-navbar {{
            background: white;
            padding: 15px 30px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 3px solid #0071BC;
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

        .container {{
            max-width: 1100px;
            margin: 0 auto;
            padding: 40px 20px;
        }}

        .hero {{
            background: white;
            border-radius: 12px;
            padding: 40px;
            margin-bottom: 30px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            text-align: center;
        }}

        .hero h2 {{
            font-size: 28px;
            color: #053657;
            margin-bottom: 12px;
        }}

        .hero p {{
            color: #626F86;
            font-size: 16px;
            margin-bottom: 24px;
        }}

        .version-badge {{
            display: inline-block;
            background: #e7f3ff;
            color: #0071BC;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            margin-bottom: 20px;
        }}

        .doc-buttons {{
            display: flex;
            gap: 16px;
            justify-content: center;
            flex-wrap: wrap;
        }}

        .doc-btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 14px 28px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            font-size: 15px;
            transition: all 0.2s;
        }}

        .doc-btn-primary {{
            background: #0071BC;
            color: white;
        }}

        .doc-btn-primary:hover {{
            background: #005a96;
        }}

        .doc-btn-secondary {{
            background: #f0f4f8;
            color: #053657;
            border: 1px solid #ddd;
        }}

        .doc-btn-secondary:hover {{
            background: #e2e8f0;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 24px;
            margin-bottom: 30px;
        }}

        .card {{
            background: white;
            border-radius: 10px;
            padding: 28px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}

        .card h3 {{
            color: #053657;
            font-size: 18px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .card h3 .icon {{
            font-size: 22px;
        }}

        .card p {{
            color: #626F86;
            font-size: 14px;
            margin-bottom: 16px;
        }}

        .card ul {{
            list-style: none;
            padding: 0;
        }}

        .card li {{
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
            font-size: 14px;
            color: #444;
        }}

        .card li:last-child {{
            border-bottom: none;
        }}

        .workflow {{
            background: white;
            border-radius: 10px;
            padding: 32px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 30px;
        }}

        .workflow h3 {{
            color: #053657;
            font-size: 18px;
            margin-bottom: 24px;
            text-align: center;
        }}

        .workflow-steps {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 16px;
        }}

        .workflow-step {{
            flex: 1;
            min-width: 140px;
            text-align: center;
            position: relative;
        }}

        .workflow-step:not(:last-child)::after {{
            content: "→";
            position: absolute;
            right: -20px;
            top: 20px;
            color: #ccc;
            font-size: 20px;
        }}

        .step-number {{
            width: 44px;
            height: 44px;
            background: #0071BC;
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 12px;
            font-weight: 600;
            font-size: 16px;
        }}

        .step-title {{
            font-weight: 600;
            color: #053657;
            margin-bottom: 4px;
            font-size: 14px;
        }}

        .step-desc {{
            color: #626F86;
            font-size: 12px;
        }}

        .step-endpoint {{
            font-family: monospace;
            font-size: 11px;
            color: #0071BC;
            background: #f0f7ff;
            padding: 2px 6px;
            border-radius: 4px;
            margin-top: 6px;
            display: inline-block;
        }}

        .concepts {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 28px;
        }}

        .concepts h3 {{
            color: #053657;
            font-size: 16px;
            margin-bottom: 16px;
        }}

        .concept-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }}

        .concept {{
            background: white;
            padding: 16px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}

        .concept h4 {{
            color: #053657;
            font-size: 14px;
            margin-bottom: 8px;
        }}

        .concept p {{
            color: #626F86;
            font-size: 13px;
            margin: 0;
        }}

        code {{
            background: #f0f4f8;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: "SF Mono", Monaco, monospace;
            font-size: 12px;
        }}

        .footer {{
            text-align: center;
            padding: 30px;
            color: #626F86;
            font-size: 13px;
        }}

        .footer a {{
            color: #0071BC;
            text-decoration: none;
        }}

        @media (max-width: 768px) {{
            .workflow-step:not(:last-child)::after {{
                display: none;
            }}
            .header {{
                flex-direction: column;
                gap: 16px;
                text-align: center;
            }}
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

    <div class="container">
        <div class="hero">
            <span class="version-badge">API Version 0.8 · App Version {__version__}</span>
            <h2>Platform API Documentation</h2>
            <p>B2B integration API for data onboarding, processing, and catalog management</p>
            <div class="doc-buttons">
                <a href="/api/interface/swagger" class="doc-btn doc-btn-primary">
                    <span>⚡</span> Swagger UI - Interactive Testing
                </a>
                <a href="/api/interface/redoc" class="doc-btn doc-btn-secondary">
                    <span>📖</span> ReDoc - Read Documentation
                </a>
                <a href="/api/openapi.json" class="doc-btn doc-btn-secondary">
                    <span>&#123; &#125;</span> OpenAPI Spec
                </a>
            </div>
        </div>

        <div class="workflow">
            <h3>Standard Workflow</h3>
            <div class="workflow-steps">
                <div class="workflow-step">
                    <div class="step-number">0</div>
                    <div class="step-title">Validate</div>
                    <div class="step-desc">Pre-flight check</div>
                    <div class="step-endpoint">POST /api/platform/validate</div>
                </div>
                <div class="workflow-step">
                    <div class="step-number">1</div>
                    <div class="step-title">Submit</div>
                    <div class="step-desc">Create processing job</div>
                    <div class="step-endpoint">POST /api/platform/submit</div>
                </div>
                <div class="workflow-step">
                    <div class="step-number">2</div>
                    <div class="step-title">Poll</div>
                    <div class="step-desc">Monitor progress</div>
                    <div class="step-endpoint">GET /api/platform/status/{{request_id}}</div>
                </div>
                <div class="workflow-step">
                    <div class="step-number">3</div>
                    <div class="step-title">Review</div>
                    <div class="step-desc">QA verification</div>
                    <div class="step-endpoint">GET /api/platform/approvals</div>
                </div>
                <div class="workflow-step">
                    <div class="step-number">4</div>
                    <div class="step-title">Approve</div>
                    <div class="step-desc">Publish dataset</div>
                    <div class="step-endpoint">POST /api/platform/approve</div>
                </div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h3><span class="icon">📤</span> Submission Endpoints</h3>
                <p>Submit data for processing with automatic type detection</p>
                <ul>
                    <li><code>POST /api/platform/validate</code> - Pre-flight validation</li>
                    <li><code>POST /api/platform/submit</code> - Create processing job</li>
                    <li><code>POST /api/platform/resubmit</code> - Resubmit after failure</li>
                </ul>
            </div>

            <div class="card">
                <h3><span class="icon">📊</span> Status & Monitoring</h3>
                <p>Track processing progress and system health</p>
                <ul>
                    <li><code>GET /api/platform/status/{{request_id}}</code> - Request status</li>
                    <li><code>GET /api/platform/status</code> - List all requests</li>
                    <li><code>GET /api/platform/failures</code> - List failed requests</li>
                    <li><code>GET /api/platform/lineage/{{request_id}}</code> - Version history</li>
                    <li><code>GET /api/platform/health</code> - System health</li>
                </ul>
            </div>

            <div class="card">
                <h3><span class="icon">✅</span> Approval Workflow</h3>
                <p>QA review and publication control</p>
                <ul>
                    <li><code>GET /api/platform/approvals</code> - List pending reviews</li>
                    <li><code>POST /api/platform/approve</code> - Approve with clearance</li>
                    <li><code>POST /api/platform/reject</code> - Reject with reason</li>
                    <li><code>POST /api/platform/revoke</code> - Revoke approval</li>
                    <li><code>GET /api/platform/approvals/status</code> - Batch status lookup</li>
                    <li><code>POST /api/platform/unpublish</code> - Unpublish asset</li>
                </ul>
            </div>

            <div class="card">
                <h3><span class="icon">🔍</span> Catalog Discovery</h3>
                <p>Find and access processed data</p>
                <ul>
                    <li><code>GET /api/platform/catalog/lookup</code> - Find by DDH IDs</li>
                    <li><code>GET /api/platform/catalog/item/{{c}}/{{i}}</code> - STAC item</li>
                    <li><code>GET /api/platform/catalog/dataset/{{dataset_id}}</code> - Dataset info</li>
                    <li><code>GET /api/platform/catalog/assets/{{c}}/{{i}}</code> - Asset URLs</li>
                </ul>
            </div>
        </div>

        <div class="concepts">
            <h3>Key Concepts (v0.8)</h3>
            <div class="concept-grid">
                <div class="concept">
                    <h4>Three-State Entity Model</h4>
                    <p>Each dataset has three independent states: <code>processing_status</code> (job progress), <code>approval_state</code> (QA status), and <code>clearance_state</code> (access level).</p>
                </div>
                <div class="concept">
                    <h4>Version Lineage</h4>
                    <p>Track data versions with <code>previous_version_id</code>. The system maintains a complete version chain for audit and rollback capabilities.</p>
                </div>
                <div class="concept">
                    <h4>Pre-flight Validation</h4>
                    <p>Use <code>POST /api/platform/validate</code> to validate requests without creating jobs. Returns <code>lineage_state</code> and <code>suggested_params</code>.</p>
                </div>
                <div class="concept">
                    <h4>Idempotent Request IDs</h4>
                    <p>Request ID = SHA256(dataset_id + resource_id + version_id). Resubmitting the same request returns the existing job.</p>
                </div>
            </div>
        </div>
    </div>

    <div class="footer">
        <p>
            <a href="/api/interface/swagger">Swagger UI</a> ·
            <a href="/api/interface/redoc">ReDoc</a> ·
            <a href="/api/openapi.json">OpenAPI Spec</a> ·
            <a href="/api/health">Health Check</a>
        </p>
        <p style="margin-top: 8px;">Base URL: <code>{base_url}</code></p>
    </div>
</body>
</html>"""
