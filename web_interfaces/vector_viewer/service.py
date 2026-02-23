"""
Vector viewer service layer.

HTML generation and OGC Features API integration for vector collection viewers.

Exports:
    VectorViewerService: Service for generating self-contained HTML viewer pages with Leaflet maps
"""

import json
import logging
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)


class VectorViewerService:
    """
    Service for generating vector collection viewer HTML pages.

    Simple service that fetches OGC Features collection metadata and generates
    a self-contained HTML page with Leaflet map for QA purposes.
    """

    def __init__(self, ogc_api_base_url: Optional[str] = None):
        """
        Initialize Vector Viewer Service.

        Args:
            ogc_api_base_url: Base URL for OGC Features API (e.g., "https://host/api/features")
                             If None, will use same-host relative paths
        """
        self.ogc_api_base_url = ogc_api_base_url or "/api/features"
        logger.info(f"VectorViewerService initialized with base URL: {self.ogc_api_base_url}")

    def generate_viewer_html(
        self,
        collection_id: str,
        host_url: Optional[str] = None,
        embed_mode: bool = False,
        asset_id: Optional[str] = None
    ) -> str:
        """
        Generate HTML viewer page for a vector collection.

        Args:
            collection_id: OGC Features collection ID (PostGIS table name)
            host_url: Optional host URL for absolute API paths
            embed_mode: If True, hide navbar for iframe embedding (07 FEB 2026)
            asset_id: GeospatialAsset ID for approve/reject workflow (09 FEB 2026)

        Returns:
            Complete HTML page as string

        Raises:
            ValueError: If collection_id is missing
            requests.HTTPError: If OGC Features API request fails
        """
        if not collection_id:
            raise ValueError("collection_id is required")

        logger.info(f"Generating viewer for collection={collection_id}, embed={embed_mode}, asset_id={asset_id}")

        # Fetch collection metadata
        collection_data = self._fetch_collection_metadata(collection_id, host_url)

        # Generate HTML with embedded data
        html = self._generate_html_template(collection_data, collection_id, host_url, embed_mode, asset_id)

        logger.info(f"Generated HTML viewer ({len(html)} bytes)")
        return html

    def _fetch_collection_metadata(self, collection_id: str, host_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch collection metadata from OGC Features API.

        Args:
            collection_id: Collection ID (table name)
            host_url: Optional host URL for absolute paths

        Returns:
            Collection metadata as dictionary
        """
        # Build API URL
        if host_url:
            url = f"{host_url}{self.ogc_api_base_url}/collections/{collection_id}"
        else:
            # Use relative path (same-host request)
            url = f"{self.ogc_api_base_url}/collections/{collection_id}"

        logger.debug(f"Fetching collection metadata from: {url}")

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            collection_data = response.json()
            logger.debug(f"Fetched collection: {collection_id}")
            return collection_data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch collection metadata: {e}")
            raise

    def _generate_html_template(
        self,
        collection_data: Dict[str, Any],
        collection_id: str,
        host_url: Optional[str] = None,
        embed_mode: bool = False,
        asset_id: Optional[str] = None
    ) -> str:
        """
        Generate HTML template with embedded collection data.

        Args:
            collection_data: OGC Features collection metadata
            collection_id: Collection ID for display
            host_url: Optional host URL for API calls
            embed_mode: If True, hide navbar for iframe embedding (07 FEB 2026)
            asset_id: GeospatialAsset ID for approve/reject (09 FEB 2026)

        Returns:
            Complete HTML page
        """
        # Extract metadata
        title = collection_data.get('title', collection_id)
        description = collection_data.get('description', 'No description available')
        extent = collection_data.get('extent', {})
        spatial = extent.get('spatial', {})
        bbox = spatial.get('bbox', [[0, 0, 0, 0]])[0] if spatial.get('bbox') else [0, 0, 0, 0]

        # Calculate map center from bbox
        if len(bbox) >= 4:
            center_lon = (bbox[0] + bbox[2]) / 2
            center_lat = (bbox[1] + bbox[3]) / 2
        else:
            center_lon, center_lat = 0, 0

        # Build API URLs
        if host_url:
            items_url = f"{host_url}{self.ogc_api_base_url}/collections/{collection_id}/items"
            styles_url = f"{host_url}{self.ogc_api_base_url}/collections/{collection_id}/styles"
        else:
            items_url = f"{self.ogc_api_base_url}/collections/{collection_id}/items"
            styles_url = f"{self.ogc_api_base_url}/collections/{collection_id}/styles"

        # Body class for embed mode (07 FEB 2026)
        body_class = "embed-mode" if embed_mode else ""

        # Generate HTML with 30/70 layout
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vector Viewer - {title}</title>

    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin=""/>

    <style>
        :root {{
            --ds-navy: #053657;
            --ds-blue: #0071BC;
            --ds-light-blue: #00A3DA;
            --ds-gray: #626F86;
            --ds-gray-light: #e9ecef;
            --ds-bg: #f8f9fa;
            --ds-success: #10B981;
            --ds-error: #DC2626;
            --ds-warning: #F59E0B;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: "Open Sans", -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--ds-bg);
            height: 100vh;
            overflow: hidden;
        }}

        /* Embed mode - minimize header for iframe embedding (07 FEB 2026) */
        body.embed-mode .sidebar-header {{
            padding: 12px 16px;
        }}
        body.embed-mode .sidebar-header h1 {{
            font-size: 16px;
        }}
        body.embed-mode .sidebar-header .collection-id {{
            font-size: 11px;
        }}

        /* Main Layout - 30/70 split */
        .app-container {{
            display: flex;
            height: 100vh;
        }}

        /* Right Sidebar - 30% */
        .sidebar {{
            width: 30%;
            min-width: 320px;
            max-width: 420px;
            background: white;
            border-left: 1px solid var(--ds-gray-light);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        /* Sidebar Header */
        .sidebar-header {{
            padding: 20px;
            background: linear-gradient(135deg, var(--ds-navy) 0%, #0a4a7a 100%);
            color: white;
        }}

        .sidebar-header h1 {{
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 4px;
        }}

        .sidebar-header .collection-id {{
            font-size: 12px;
            opacity: 0.8;
            font-family: 'Courier New', monospace;
        }}

        /* Sidebar Content */
        .sidebar-content {{
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }}

        /* Section Cards */
        .section-card {{
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 8px;
            margin-bottom: 16px;
            overflow: hidden;
        }}

        .section-header {{
            padding: 12px 16px;
            background: var(--ds-bg);
            border-bottom: 1px solid var(--ds-gray-light);
            font-size: 12px;
            font-weight: 600;
            color: var(--ds-navy);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .section-body {{
            padding: 16px;
        }}

        /* Feature Count Display */
        .feature-count-display {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px;
            background: linear-gradient(135deg, #F0F9FF 0%, #E0F2FE 100%);
            border: 1px solid #BAE6FD;
            border-radius: 8px;
            margin-bottom: 16px;
        }}

        .feature-count-value {{
            font-size: 28px;
            font-weight: 700;
            color: var(--ds-blue);
        }}

        .feature-count-label {{
            font-size: 11px;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .feature-count-loaded {{
            text-align: right;
        }}

        .feature-count-loaded .loaded-value {{
            font-size: 18px;
            font-weight: 600;
            color: var(--ds-success);
        }}

        .feature-count-loaded .loaded-label {{
            font-size: 10px;
            color: var(--ds-gray);
        }}

        /* Description */
        .description-text {{
            font-size: 13px;
            color: var(--ds-gray);
            line-height: 1.5;
            margin-bottom: 12px;
        }}

        /* Form Controls */
        .control-row {{
            margin-bottom: 16px;
        }}

        .control-label {{
            display: block;
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }}

        .control-hint {{
            font-size: 10px;
            color: #94a3b8;
            margin-top: 4px;
        }}

        /* Numeric Input with Buttons */
        .number-input-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .number-input {{
            flex: 1;
            padding: 10px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            font-size: 14px;
            color: var(--ds-navy);
            text-align: center;
            font-family: 'Courier New', monospace;
        }}

        .number-input:focus {{
            outline: none;
            border-color: var(--ds-blue);
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }}

        .number-btn {{
            width: 36px;
            height: 36px;
            border: 1px solid var(--ds-gray-light);
            background: white;
            border-radius: 6px;
            font-size: 18px;
            font-weight: 600;
            color: var(--ds-navy);
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .number-btn:hover {{
            background: var(--ds-bg);
            border-color: var(--ds-blue);
        }}

        .number-btn:active {{
            background: var(--ds-blue);
            color: white;
        }}

        /* Checkbox Control */
        .checkbox-control {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px;
            background: var(--ds-bg);
            border-radius: 6px;
            cursor: pointer;
        }}

        .checkbox-control input {{
            width: 18px;
            height: 18px;
            accent-color: var(--ds-blue);
        }}

        .checkbox-control span {{
            font-size: 13px;
            color: var(--ds-navy);
        }}

        /* Buttons */
        .btn {{
            padding: 12px 20px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}

        .btn-primary {{
            background: var(--ds-blue);
            color: white;
            width: 100%;
        }}

        .btn-primary:hover {{
            background: var(--ds-light-blue);
        }}

        .btn-primary:disabled {{
            background: #ccc;
            cursor: not-allowed;
        }}

        .btn-secondary {{
            background: white;
            color: var(--ds-navy);
            border: 1px solid var(--ds-gray-light);
        }}

        .btn-secondary:hover {{
            background: var(--ds-bg);
            border-color: var(--ds-blue);
        }}

        .btn-row {{
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }}

        .btn-row .btn {{
            flex: 1;
        }}

        /* Status Display */
        .status-display {{
            padding: 12px;
            background: var(--ds-bg);
            border-radius: 6px;
            text-align: center;
            margin-top: 12px;
        }}

        .status-text {{
            font-size: 13px;
            color: var(--ds-gray);
        }}

        .status-text.success {{
            color: var(--ds-success);
        }}

        .status-text.error {{
            color: var(--ds-error);
        }}

        /* QA Section */
        .qa-textarea {{
            width: 100%;
            padding: 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            font-size: 13px;
            font-family: inherit;
            resize: vertical;
            min-height: 80px;
        }}

        .qa-textarea:focus {{
            outline: none;
            border-color: var(--ds-blue);
        }}

        .qa-buttons {{
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }}

        .btn-approve {{
            flex: 1;
            background: var(--ds-success);
            color: white;
        }}

        .btn-approve:hover {{
            background: #059669;
        }}

        .btn-reject {{
            flex: 1;
            background: var(--ds-error);
            color: white;
        }}

        .btn-reject:hover {{
            background: #b91c1c;
        }}

        .btn-approve:disabled, .btn-reject:disabled, .btn-revoke:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}

        /* QA Status Display (09 FEB 2026) */
        .qa-status-display {{
            margin-bottom: 12px;
            padding: 12px;
            background: var(--ds-bg);
            border-radius: 6px;
        }}

        .qa-status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 6px;
        }}

        .qa-status-badge.approved {{
            background: #c6f6d5;
            color: #276749;
        }}

        .qa-status-badge.rejected {{
            background: #fed7d7;
            color: #c53030;
        }}

        .qa-status-badge.pending {{
            background: #feebc8;
            color: #c05621;
        }}

        .qa-status-info {{
            font-size: 11px;
            color: var(--ds-gray);
        }}

        .qa-revoke-warning {{
            background: #fff5f5;
            border: 1px solid #feb2b2;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
            font-size: 12px;
            color: #c53030;
        }}

        .btn-revoke {{
            width: 100%;
            padding: 10px;
            border: 2px solid #c53030;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            background: #fff5f5;
            color: #c53030;
        }}

        .btn-revoke:hover {{
            background: #c53030;
            color: white;
        }}

        .qa-loading {{
            text-align: center;
            padding: 20px;
            color: var(--ds-gray);
            font-style: italic;
        }}

        /* Style Dialog Placeholder */
        .style-selector {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .style-select {{
            flex: 1;
            padding: 10px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            font-size: 13px;
            color: var(--ds-navy);
            background: white;
        }}

        /* Map Container - 70% */
        .map-container {{
            flex: 1;
            position: relative;
        }}

        #map {{
            height: 100%;
            width: 100%;
        }}

        /* Map Overlay Status */
        .map-status {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: white;
            padding: 10px 16px;
            border-radius: 6px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 1000;
            font-size: 12px;
            color: var(--ds-navy);
        }}

        /* Loading Overlay */
        .loading-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.8);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1001;
        }}

        .loading-overlay.active {{
            display: flex;
        }}

        .loading-spinner {{
            text-align: center;
        }}

        .spinner-icon {{
            width: 48px;
            height: 48px;
            border: 4px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 12px;
        }}

        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}

        .loading-text {{
            font-size: 14px;
            color: var(--ds-navy);
            font-weight: 600;
        }}

        /* Popup styling */
        .leaflet-popup-content {{
            margin: 10px;
            font-size: 13px;
        }}

        .popup-title {{
            font-weight: 700;
            font-size: 14px;
            color: var(--ds-navy);
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--ds-blue);
        }}

        .popup-row {{
            padding: 4px 0;
            border-bottom: 1px solid #f0f0f0;
        }}

        .popup-row:last-child {{
            border-bottom: none;
        }}

        .popup-label {{
            font-weight: 600;
            color: var(--ds-gray);
            font-size: 11px;
            text-transform: uppercase;
        }}

        .popup-value {{
            color: var(--ds-navy);
            display: block;
            margin-top: 2px;
        }}

        /* Modal Dialog */
        .modal-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 2000;
        }}

        .modal-overlay.active {{
            display: flex;
        }}

        .modal-dialog {{
            background: white;
            border-radius: 12px;
            width: 90%;
            max-width: 500px;
            max-height: 80vh;
            overflow: hidden;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
        }}

        .modal-header {{
            padding: 20px;
            background: var(--ds-navy);
            color: white;
        }}

        .modal-header h3 {{
            font-size: 18px;
            font-weight: 700;
        }}

        .modal-body {{
            padding: 20px;
            max-height: 400px;
            overflow-y: auto;
        }}

        .modal-footer {{
            padding: 16px 20px;
            border-top: 1px solid var(--ds-gray-light);
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }}

        .style-list {{
            list-style: none;
        }}

        .style-item {{
            padding: 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .style-item:hover {{
            border-color: var(--ds-blue);
            background: #f0f7ff;
        }}

        .style-item.selected {{
            border-color: var(--ds-blue);
            background: #e0f0ff;
        }}

        .style-item-name {{
            font-weight: 600;
            color: var(--ds-navy);
        }}

        .style-item-id {{
            font-size: 11px;
            color: var(--ds-gray);
            font-family: monospace;
        }}

        .no-styles-message {{
            text-align: center;
            padding: 40px 20px;
            color: var(--ds-gray);
        }}

        /* Responsive */
        @media (max-width: 900px) {{
            .app-container {{
                flex-direction: column;
            }}
            .sidebar {{
                width: 100%;
                max-width: none;
                height: 40%;
            }}
            .map-container {{
                height: 60%;
            }}
        }}
    </style>
</head>
<body class="{body_class}">
    <div class="app-container">
        <!-- Map Container (Left - 70%) -->
        <div class="map-container">
            <div id="map"></div>

            <!-- Loading Overlay -->
            <div class="loading-overlay" id="loading-overlay">
                <div class="loading-spinner">
                    <div class="spinner-icon"></div>
                    <div class="loading-text">Loading features...</div>
                </div>
            </div>

            <!-- Map Status -->
            <div class="map-status" id="map-status">
                Zoom: <span id="zoom-level">--</span> |
                Center: <span id="map-center">--</span>
            </div>
        </div>

        <!-- Right Sidebar (30%) -->
        <div class="sidebar">
            <div class="sidebar-header">
                <h1>📍 Vector Viewer</h1>
                <div class="collection-id">{collection_id}</div>
            </div>

            <div class="sidebar-content">
                <!-- Feature Count -->
                <div class="feature-count-display">
                    <div>
                        <div class="feature-count-value" id="total-features">--</div>
                        <div class="feature-count-label">Total Features</div>
                    </div>
                    <div class="feature-count-loaded">
                        <div class="loaded-value" id="loaded-features">0</div>
                        <div class="loaded-label">Loaded</div>
                    </div>
                </div>

                <!-- Description -->
                <div class="section-card">
                    <div class="section-header">Description</div>
                    <div class="section-body">
                        <p class="description-text">{description}</p>
                    </div>
                </div>

                <!-- Load Options -->
                <div class="section-card">
                    <div class="section-header">Load Features</div>
                    <div class="section-body">
                        <div class="control-row">
                            <label class="control-label">Feature Limit</label>
                            <div class="number-input-group">
                                <button class="number-btn" onclick="adjustLimit(-100)">−</button>
                                <input type="number" class="number-input" id="limit-input"
                                       min="1" max="10000" value="100">
                                <button class="number-btn" onclick="adjustLimit(100)">+</button>
                            </div>
                            <div class="control-hint">Max: <span id="max-features">10000</span></div>
                        </div>

                        <div class="control-row">
                            <label class="control-label">Simplification (Decimal Degrees)</label>
                            <div class="number-input-group">
                                <button class="number-btn" onclick="adjustSimplify(-0.001)">−</button>
                                <input type="number" class="number-input" id="simplify-input"
                                       min="0" step="0.001" value="0">
                                <button class="number-btn" onclick="adjustSimplify(0.001)">+</button>
                            </div>
                            <div class="control-hint">0 = no simplification, 0.001 ≈ 111m at equator</div>
                        </div>

                        <div class="control-row">
                            <label class="checkbox-control">
                                <input type="checkbox" id="bbox-checkbox">
                                <span>Load visible bounding box only</span>
                            </label>
                        </div>

                        <button class="btn btn-primary" id="load-btn" onclick="loadFeatures()">
                            🔄 Load Features
                        </button>

                        <div class="btn-row">
                            <button class="btn btn-secondary" onclick="zoomToFeatures()">Zoom to Fit</button>
                            <button class="btn btn-secondary" onclick="clearFeatures()">Clear Map</button>
                        </div>

                        <div class="status-display">
                            <div class="status-text" id="status">Ready to load features</div>
                        </div>
                    </div>
                </div>

                <!-- Style Selection -->
                <div class="section-card">
                    <div class="section-header">Styling</div>
                    <div class="section-body">
                        <div class="control-row">
                            <label class="control-label">OGC Style</label>
                            <div class="style-selector">
                                <select class="style-select" id="style-select">
                                    <option value="">Default (Blue)</option>
                                </select>
                                <button class="btn btn-secondary" onclick="openStyleDialog()">Browse</button>
                            </div>
                            <div class="control-hint">Load from OGC Styles API (feature pending)</div>
                        </div>
                    </div>
                </div>

                <!-- QA Section -->
                <div class="section-card" id="qa-section">
                    <div class="section-header">Data Curator QA</div>
                    <div class="section-body">
                        <!-- Approval Status Display (09 FEB 2026) -->
                        <div id="qa-status-display" class="qa-status-display" style="display: none;">
                            <div id="qa-status-badge" class="qa-status-badge"></div>
                            <div id="qa-status-info" class="qa-status-info"></div>
                        </div>

                        <!-- Pending Approval Form (shown when not yet approved) -->
                        <div id="qa-pending-form" style="display: none;">
                            <!-- Reviewer Email (Required) -->
                            <div class="control-row">
                                <label class="control-label">Reviewer Email <span style="color: var(--ds-error);">*</span></label>
                                <input type="email" class="number-input" id="qa-reviewer"
                                       placeholder="your.email@example.org" style="text-align: left;">
                            </div>

                            <!-- Clearance Level (Required for Approve) -->
                            <div class="control-row">
                                <label class="control-label">Clearance Level <span style="color: var(--ds-error);">*</span></label>
                                <select class="style-select" id="qa-clearance">
                                    <option value="ouo" selected>OUO - Official Use Only</option>
                                    <option value="public">Public - External Access</option>
                                </select>
                            </div>

                            <!-- Version ID (required for draft assets) -->
                            <div class="control-row">
                                <label class="control-label">Version ID</label>
                                <input type="text" class="number-input" id="qa-version-id"
                                       placeholder="e.g. v1.0 (required for drafts)" style="text-align: left;">
                            </div>

                            <!-- Previous Version ID (for lineage chaining) -->
                            <div class="control-row">
                                <label class="control-label">Previous Version ID</label>
                                <input type="text" class="number-input" id="qa-previous-version-id"
                                       placeholder="e.g. v0.9 (if replacing)" style="text-align: left;">
                            </div>

                            <!-- Notes -->
                            <div class="control-row">
                                <label class="control-label">Notes <span id="notes-required" style="color: var(--ds-error); display:none;">*</span></label>
                                <textarea class="qa-textarea" id="qa-notes"
                                          placeholder="QA notes (required for rejection)..."></textarea>
                            </div>

                            <div class="qa-buttons">
                                <button class="btn btn-approve" onclick="handleApprove()">✓ Approve</button>
                                <button class="btn btn-reject" onclick="handleReject()">✗ Reject</button>
                            </div>
                        </div>

                        <!-- Revoke Section (shown when already approved) -->
                        <div id="qa-revoke-form" style="display: none;">
                            <div class="qa-revoke-warning">
                                This asset has been approved. Revoking will remove it from publication.
                            </div>
                            <button class="btn btn-revoke" onclick="handleRevoke()">Revoke Approval</button>
                        </div>

                        <!-- Loading state -->
                        <div id="qa-loading" class="qa-loading">Checking approval status...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Style Selection Modal -->
    <div class="modal-overlay" id="style-modal">
        <div class="modal-dialog">
            <div class="modal-header">
                <h3>Select OGC Style</h3>
            </div>
            <div class="modal-body" id="style-list-container">
                <div class="no-styles-message">
                    <p>Loading styles...</p>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeStyleDialog()">Cancel</button>
                <button class="btn btn-primary" onclick="applySelectedStyle()">Apply Style</button>
            </div>
        </div>
    </div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""></script>

    <script>
        // Collection metadata
        const COLLECTION_ID = '{collection_id}';
        const ITEMS_URL = '{items_url}';
        const STYLES_URL = '{styles_url}';
        const BBOX = {json.dumps(bbox)};
        const TOTAL_FEATURES = null; // Will be fetched
        const ASSET_ID = {json.dumps(asset_id)};  // For approve/reject workflow (09 FEB 2026)

        // State
        let featureLayer = null;
        let totalFeatureCount = null;
        let currentStyle = null;
        let selectedStyleId = null;

        // Initialize map
        const map = L.map('map').setView([{center_lat}, {center_lon}], 6);

        // Add OpenStreetMap base layer
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        }}).addTo(map);

        // Update map status on move
        map.on('moveend', updateMapStatus);
        map.on('zoomend', updateMapStatus);

        function updateMapStatus() {{
            const center = map.getCenter();
            document.getElementById('zoom-level').textContent = map.getZoom();
            document.getElementById('map-center').textContent =
                `${{center.lat.toFixed(4)}}, ${{center.lng.toFixed(4)}}`;
        }}

        // Fetch total feature count
        async function fetchTotalFeatureCount() {{
            try {{
                const response = await fetch(`${{ITEMS_URL}}?limit=1`);
                if (response.ok) {{
                    const data = await response.json();
                    totalFeatureCount = data.numberMatched || data.features?.length || 0;
                    document.getElementById('total-features').textContent =
                        totalFeatureCount.toLocaleString();
                    document.getElementById('max-features').textContent =
                        Math.min(totalFeatureCount, 10000).toLocaleString();

                    // Update limit input max
                    document.getElementById('limit-input').max = Math.min(totalFeatureCount, 10000);
                }}
            }} catch (error) {{
                console.error('Failed to fetch feature count:', error);
            }}
        }}

        // Adjust limit input
        function adjustLimit(delta) {{
            const input = document.getElementById('limit-input');
            const max = parseInt(input.max) || 10000;
            let newValue = parseInt(input.value || 100) + delta;
            newValue = Math.max(1, Math.min(max, newValue));
            input.value = newValue;
        }}

        // Adjust simplify input
        function adjustSimplify(delta) {{
            const input = document.getElementById('simplify-input');
            let newValue = parseFloat(input.value || 0) + delta;
            newValue = Math.max(0, parseFloat(newValue.toFixed(3)));
            input.value = newValue;
        }}

        // Show/hide loading
        function showLoading() {{
            document.getElementById('loading-overlay').classList.add('active');
        }}

        function hideLoading() {{
            document.getElementById('loading-overlay').classList.remove('active');
        }}

        // Set status
        function setStatus(message, type = '') {{
            const statusEl = document.getElementById('status');
            statusEl.textContent = message;
            statusEl.className = 'status-text' + (type ? ' ' + type : '');
        }}

        // Load features
        async function loadFeatures() {{
            const limit = parseInt(document.getElementById('limit-input').value) || 100;
            const simplify = parseFloat(document.getElementById('simplify-input').value) || 0;
            const useBbox = document.getElementById('bbox-checkbox').checked;

            showLoading();
            setStatus('Loading features...');

            try {{
                let url = `${{ITEMS_URL}}?limit=${{limit}}`;

                if (simplify > 0) {{
                    url += `&simplify=${{simplify}}`;
                }}

                if (useBbox) {{
                    const bounds = map.getBounds();
                    const bbox = `${{bounds.getWest()}},${{bounds.getSouth()}},${{bounds.getEast()}},${{bounds.getNorth()}}`;
                    url += `&bbox=${{bbox}}`;
                }}

                const response = await fetch(url);
                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                }}

                const data = await response.json();
                const features = data.features || [];

                // Update loaded count
                document.getElementById('loaded-features').textContent = features.length.toLocaleString();

                // Remove existing layer
                if (featureLayer) {{
                    map.removeLayer(featureLayer);
                }}

                // Get style
                const style = currentStyle || {{
                    color: '#0071BC',
                    weight: 2,
                    fillOpacity: 0.25,
                    fillColor: '#0071BC'
                }};

                // Add features to map
                featureLayer = L.geoJSON(data, {{
                    style: function(feature) {{
                        return style;
                    }},
                    onEachFeature: function(feature, layer) {{
                        const props = feature.properties || {{}};
                        let popupContent = '<div class="popup-title">Feature Properties</div>';

                        const keys = Object.keys(props).slice(0, 8);
                        keys.forEach(key => {{
                            const value = props[key];
                            if (value !== null && value !== undefined) {{
                                popupContent += `<div class="popup-row">
                                    <span class="popup-label">${{key}}</span>
                                    <span class="popup-value">${{value}}</span>
                                </div>`;
                            }}
                        }});

                        if (Object.keys(props).length > 8) {{
                            popupContent += `<div class="popup-row" style="color: #626F86; font-style: italic;">
                                +${{Object.keys(props).length - 8}} more properties
                            </div>`;
                        }}

                        layer.bindPopup(popupContent, {{ maxWidth: 300 }});

                        // Hover effects
                        layer.on('mouseover', function() {{
                            this.setStyle({{ weight: 3, fillOpacity: 0.4 }});
                        }});
                        layer.on('mouseout', function() {{
                            this.setStyle({{ weight: style.weight, fillOpacity: style.fillOpacity }});
                        }});
                    }}
                }}).addTo(map);

                const simplifyNote = simplify > 0 ? ` (simplified: ${{simplify}}°)` : '';
                const bboxNote = useBbox ? ' (bbox)' : '';
                setStatus(`Loaded ${{features.length}} features${{simplifyNote}}${{bboxNote}}`, 'success');

                // Zoom to features if not using bbox
                if (!useBbox && featureLayer.getBounds().isValid()) {{
                    map.fitBounds(featureLayer.getBounds(), {{ padding: [50, 50] }});
                }}

            }} catch (error) {{
                setStatus(`Error: ${{error.message}}`, 'error');
                console.error('Failed to load features:', error);
            }} finally {{
                hideLoading();
            }}
        }}

        function zoomToFeatures() {{
            if (featureLayer && featureLayer.getBounds().isValid()) {{
                map.fitBounds(featureLayer.getBounds(), {{ padding: [50, 50] }});
            }} else if (BBOX && BBOX.length >= 4) {{
                const bounds = [[BBOX[1], BBOX[0]], [BBOX[3], BBOX[2]]];
                map.fitBounds(bounds, {{ padding: [50, 50] }});
            }}
        }}

        function clearFeatures() {{
            if (featureLayer) {{
                map.removeLayer(featureLayer);
                featureLayer = null;
                document.getElementById('loaded-features').textContent = '0';
                setStatus('Map cleared');
            }}
        }}

        // Style Dialog
        function openStyleDialog() {{
            document.getElementById('style-modal').classList.add('active');
            loadStyleList();
        }}

        function closeStyleDialog() {{
            document.getElementById('style-modal').classList.remove('active');
        }}

        async function loadStyleList() {{
            const container = document.getElementById('style-list-container');

            try {{
                // Placeholder - fetch styles from OGC Styles API
                // const response = await fetch(STYLES_URL);
                // const data = await response.json();

                // For now, show placeholder
                container.innerHTML = `
                    <div class="no-styles-message">
                        <p style="font-size: 36px; margin-bottom: 16px;">🎨</p>
                        <p><strong>Style Loading Coming Soon</strong></p>
                        <p style="margin-top: 8px; font-size: 12px;">
                            OGC Styles API integration is pending.<br>
                            Styles will be loaded from:<br>
                            <code style="background: #f0f0f0; padding: 4px 8px; border-radius: 4px;">
                                ${{STYLES_URL}}
                            </code>
                        </p>
                    </div>
                `;
            }} catch (error) {{
                container.innerHTML = `
                    <div class="no-styles-message">
                        <p>Failed to load styles: ${{error.message}}</p>
                    </div>
                `;
            }}
        }}

        function applySelectedStyle() {{
            // Placeholder for applying selected style
            closeStyleDialog();
            setStatus('Style feature coming soon...');
        }}

        // Check approval status and show appropriate form (09 FEB 2026, V0.9 23 FEB 2026)
        async function checkApprovalStatus() {{
            if (!ASSET_ID) {{
                // No asset_id - show pending form by default
                document.getElementById('qa-loading').style.display = 'none';
                document.getElementById('qa-pending-form').style.display = 'block';
                return;
            }}

            try {{
                const response = await fetch(`/api/assets/${{ASSET_ID}}/approval`);
                const data = await response.json();

                document.getElementById('qa-loading').style.display = 'none';

                if (!data.success) {{
                    // Asset not found or error - show pending form
                    document.getElementById('qa-pending-form').style.display = 'block';
                    return;
                }}

                // V0.9: Read from primary_release (API nests release data)
                const release = data.primary_release || {{}};
                const state = release.approval_state || data.approval_state;
                const statusDisplay = document.getElementById('qa-status-display');
                const statusBadge = document.getElementById('qa-status-badge');
                const statusInfo = document.getElementById('qa-status-info');

                if (state === 'approved') {{
                    // Show approved status and revoke option
                    statusDisplay.style.display = 'block';
                    statusBadge.className = 'qa-status-badge approved';
                    statusBadge.textContent = 'APPROVED';

                    let infoHtml = '';
                    if (release.reviewer) infoHtml += `Reviewer: ${{release.reviewer}}<br>`;
                    if (release.reviewed_at) infoHtml += `Approved: ${{new Date(release.reviewed_at).toLocaleString()}}<br>`;
                    if (release.clearance_state) infoHtml += `Clearance: ${{release.clearance_state.toUpperCase()}}`;
                    statusInfo.innerHTML = infoHtml;

                    // Approved releases can be revoked
                    document.getElementById('qa-revoke-form').style.display = 'block';
                }} else if (state === 'rejected') {{
                    // Show rejected status
                    statusDisplay.style.display = 'block';
                    statusBadge.className = 'qa-status-badge rejected';
                    statusBadge.textContent = 'REJECTED';

                    let infoHtml = '';
                    if (release.reviewer) infoHtml += `Reviewer: ${{release.reviewer}}<br>`;
                    if (release.reviewed_at) infoHtml += `Rejected: ${{new Date(release.reviewed_at).toLocaleString()}}<br>`;
                    if (release.rejection_reason) infoHtml += `Reason: ${{release.rejection_reason}}`;
                    statusInfo.innerHTML = infoHtml;

                    // Allow re-approval for rejected releases
                    document.getElementById('qa-pending-form').style.display = 'block';
                }} else {{
                    // Pending review or other state - show approval form
                    if (state) {{
                        statusDisplay.style.display = 'block';
                        statusBadge.className = 'qa-status-badge pending';
                        statusBadge.textContent = state.toUpperCase().replace('_', ' ');
                        statusInfo.innerHTML = 'Awaiting curator review';
                    }}

                    document.getElementById('qa-pending-form').style.display = 'block';
                }}

            }} catch (error) {{
                console.error('Error checking approval status:', error);
                document.getElementById('qa-loading').style.display = 'none';
                document.getElementById('qa-pending-form').style.display = 'block';
            }}
        }}

        // Handle revoke action (09 FEB 2026)
        async function handleRevoke() {{
            if (!ASSET_ID) {{
                setStatus('⚠️ No asset_id provided for revoke', 'error');
                return;
            }}

            // Confirm revoke action
            if (!confirm('Are you sure you want to revoke approval for this asset? This will remove it from publication.')) {{
                return;
            }}

            const revokeBtn = document.querySelector('.btn-revoke');
            revokeBtn.disabled = true;
            setStatus('Revoking approval...', 'info');

            try {{
                // Prompt for revoker email
                const revoker = prompt('Enter your email address to revoke:');
                if (!revoker || !revoker.includes('@')) {{
                    setStatus('Valid email required for audit trail', 'error');
                    revokeBtn.disabled = false;
                    return;
                }}

                const revokeReason = prompt('Enter reason for revocation:');
                if (!revokeReason || !revokeReason.trim()) {{
                    setStatus('Reason required for audit trail', 'error');
                    revokeBtn.disabled = false;
                    return;
                }}

                const response = await fetch(`/api/assets/${{ASSET_ID}}/revoke`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        reason: revokeReason,
                        revoker: revoker
                    }})
                }});

                const data = await response.json();

                if (response.ok && data.success) {{
                    setStatus('Approval revoked successfully', 'success');
                    // Refresh the approval status display
                    setTimeout(() => checkApprovalStatus(), 1000);
                }} else {{
                    setStatus(`Revoke failed: ${{data.error || 'Unknown error'}}`, 'error');
                    revokeBtn.disabled = false;
                }}

            }} catch (error) {{
                setStatus(`Revoke error: ${{error.message}}`, 'error');
                revokeBtn.disabled = false;
            }}
        }}

        // QA Handlers (09 FEB 2026: Wired to platform/approve and platform/reject)
        async function handleApprove() {{
            if (!ASSET_ID) {{
                setStatus('⚠️ No asset_id - cannot approve', 'error');
                return;
            }}

            const reviewer = document.getElementById('qa-reviewer').value.trim();
            const clearance = document.getElementById('qa-clearance').value;
            const notes = document.getElementById('qa-notes').value;

            // Validate required fields
            if (!reviewer) {{
                setStatus('⚠️ Reviewer email is required', 'error');
                document.getElementById('qa-reviewer').focus();
                return;
            }}

            // Basic email validation
            if (!reviewer.includes('@')) {{
                setStatus('⚠️ Please enter a valid email address', 'error');
                document.getElementById('qa-reviewer').focus();
                return;
            }}

            setStatus('Submitting approval...', 'info');

            const versionId = document.getElementById('qa-version-id').value.trim();
            const previousVersionId = document.getElementById('qa-previous-version-id').value.trim();

            try {{
                const approvePayload = {{
                    asset_id: ASSET_ID,
                    reviewer: reviewer,
                    clearance_level: clearance,
                    notes: notes || undefined
                }};
                if (versionId) approvePayload.version_id = versionId;
                if (previousVersionId) approvePayload.previous_version_id = previousVersionId;

                const response = await fetch('/api/platform/approve', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(approvePayload)
                }});

                const result = await response.json();

                if (response.ok && result.success) {{
                    setStatus(`✓ Approved as ${{clearance.toUpperCase()}}!`, 'success');
                    // Refresh to show approved state with revoke option
                    setTimeout(() => checkApprovalStatus(), 500);
                }} else {{
                    setStatus(`✗ Approval failed: ${{result.error || 'Unknown error'}}`, 'error');
                }}
            }} catch (error) {{
                console.error('Approval error:', error);
                setStatus(`✗ Approval failed: ${{error.message}}`, 'error');
            }}
        }}

        async function handleReject() {{
            if (!ASSET_ID) {{
                setStatus('⚠️ No asset_id - cannot reject', 'error');
                return;
            }}

            const reviewer = document.getElementById('qa-reviewer').value.trim();
            const notes = document.getElementById('qa-notes').value;

            // Validate required fields
            if (!reviewer) {{
                setStatus('⚠️ Reviewer email is required', 'error');
                document.getElementById('qa-reviewer').focus();
                return;
            }}

            if (!reviewer.includes('@')) {{
                setStatus('⚠️ Please enter a valid email address', 'error');
                document.getElementById('qa-reviewer').focus();
                return;
            }}

            // Require rejection reason
            if (!notes.trim()) {{
                setStatus('⚠️ Rejection requires notes explaining why', 'error');
                document.getElementById('qa-notes').focus();
                return;
            }}

            setStatus('Submitting rejection...', 'info');

            try {{
                const response = await fetch('/api/platform/reject', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        asset_id: ASSET_ID,
                        reviewer: reviewer,
                        reason: notes
                    }})
                }});

                const result = await response.json();

                if (response.ok && result.success) {{
                    setStatus('✗ Rejected - feedback sent to submitter', 'success');
                    // Refresh to show rejected state
                    setTimeout(() => checkApprovalStatus(), 500);
                }} else {{
                    setStatus(`✗ Rejection failed: ${{result.error || 'Unknown error'}}`, 'error');
                }}
            }} catch (error) {{
                console.error('Rejection error:', error);
                setStatus(`✗ Rejection failed: ${{error.message}}`, 'error');
            }}
        }}

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            updateMapStatus();
            fetchTotalFeatureCount();

            // Zoom to bbox
            if (BBOX && BBOX.length >= 4 && BBOX[0] !== 0) {{
                const bounds = [[BBOX[1], BBOX[0]], [BBOX[3], BBOX[2]]];
                map.fitBounds(bounds, {{ padding: [50, 50] }});
            }}

            // Check approval status for QA section (09 FEB 2026)
            checkApprovalStatus();
        }});

        console.log('Vector Viewer initialized');
        console.log('Collection:', COLLECTION_ID);
        console.log('Asset ID:', ASSET_ID);
    </script>
</body>
</html>"""

        return html
