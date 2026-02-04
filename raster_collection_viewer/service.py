"""
Raster Collection Viewer Service - STAC-Integrated Raster Map Viewer.

Provides interactive Leaflet-based viewer for browsing STAC raster collections
with smart TiTiler URL generation based on raster metadata.

Feature: F2.9 (30 DEC 2025)
Reference: TITILER-URL-GUIDE.md

Exports:
    RasterCollectionViewerService: Service for generating self-contained HTML viewer pages
"""

import json
import logging
import urllib.parse
from typing import Optional, Dict, Any, List
import requests

logger = logging.getLogger(__name__)


class RasterCollectionViewerService:
    """
    Service for generating raster collection viewer HTML pages.

    Integrates with STAC API and TiTiler to provide interactive visualization
    of raster collections with band selection, rescale, and colormap controls.
    """

    def __init__(
        self,
        stac_api_base_url: Optional[str] = None,
        titiler_base_url: Optional[str] = None
    ):
        """
        Initialize Raster Collection Viewer Service.

        Args:
            stac_api_base_url: Base URL for STAC API (e.g., "/api/stac")
            titiler_base_url: Base URL for TiTiler (e.g., "https://titiler.example.com")
        """
        self.stac_api_base_url = stac_api_base_url or "/api/stac"
        self.titiler_base_url = titiler_base_url

        # Load from config if not provided
        if not self.titiler_base_url:
            try:
                from config import get_config
                config = get_config()
                self.titiler_base_url = config.titiler_base_url
            except Exception:
                self.titiler_base_url = ""

        logger.info(f"RasterCollectionViewerService initialized")
        logger.info(f"  STAC API: {self.stac_api_base_url}")
        logger.info(f"  TiTiler: {self.titiler_base_url}")

    def generate_viewer_html(
        self,
        collection_id: str,
        host_url: Optional[str] = None
    ) -> str:
        """
        Generate HTML viewer page for a raster collection.

        Args:
            collection_id: STAC collection ID
            host_url: Optional host URL for absolute API paths

        Returns:
            Complete HTML page as string

        Raises:
            ValueError: If collection_id is missing
        """
        if not collection_id:
            raise ValueError("collection_id is required")

        logger.info(f"Generating raster viewer for collection={collection_id}")

        # Fetch collection metadata
        collection_data = self._fetch_collection_metadata(collection_id, host_url)

        # Fetch first batch of items for sidebar
        items_data = self._fetch_collection_items(collection_id, host_url, limit=50)

        # Generate HTML with embedded data
        html = self._generate_html_template(
            collection_data,
            items_data,
            collection_id,
            host_url
        )

        logger.info(f"Generated raster viewer HTML ({len(html)} bytes)")
        return html

    def _fetch_collection_metadata(
        self,
        collection_id: str,
        host_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch collection metadata from STAC API."""
        if host_url:
            url = f"{host_url}{self.stac_api_base_url}/collections/{collection_id}"
        else:
            url = f"{self.stac_api_base_url}/collections/{collection_id}"

        logger.debug(f"Fetching collection metadata from: {url}")

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch collection metadata: {e}")
            raise

    def _fetch_collection_items(
        self,
        collection_id: str,
        host_url: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Fetch items from STAC collection."""
        if host_url:
            url = f"{host_url}{self.stac_api_base_url}/collections/{collection_id}/items?limit={limit}"
        else:
            url = f"{self.stac_api_base_url}/collections/{collection_id}/items?limit={limit}"

        logger.debug(f"Fetching collection items from: {url}")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch collection items: {e}")
            return {"features": [], "numberMatched": 0}

    def _generate_html_template(
        self,
        collection_data: Dict[str, Any],
        items_data: Dict[str, Any],
        collection_id: str,
        host_url: Optional[str] = None
    ) -> str:
        """Generate HTML template with embedded collection and items data."""
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
            items_url = f"{host_url}{self.stac_api_base_url}/collections/{collection_id}/items"
        else:
            items_url = f"{self.stac_api_base_url}/collections/{collection_id}/items"

        titiler_base = self.titiler_base_url.rstrip('/') if self.titiler_base_url else ""

        # Extract items for initial load
        items = items_data.get('features', [])
        total_items = items_data.get('numberMatched', len(items))

        # Serialize items for JavaScript
        items_json = json.dumps(items)

        # Generate HTML with 30/70 layout
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raster Viewer - {title}</title>

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

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: "Open Sans", -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--ds-bg);
            height: 100vh;
            overflow: hidden;
        }}

        .app-container {{ display: flex; height: 100vh; }}

        /* Right Sidebar - 30% */
        .sidebar {{
            width: 30%;
            min-width: 340px;
            max-width: 440px;
            background: white;
            border-left: 1px solid var(--ds-gray-light);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            order: 2;
        }}

        .sidebar-header {{
            padding: 20px;
            background: linear-gradient(135deg, #1a3a52 0%, #2d5a7b 100%);
            color: white;
        }}

        .sidebar-header h1 {{
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .sidebar-header .collection-id {{
            font-size: 12px;
            opacity: 0.8;
            font-family: 'Courier New', monospace;
        }}

        .sidebar-content {{
            flex: 1;
            overflow-y: auto;
            padding: 16px;
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

        .section-body {{ padding: 16px; }}

        /* Item Stats */
        .item-stats {{
            display: flex;
            gap: 16px;
            padding: 16px;
            background: linear-gradient(135deg, #FFF7ED 0%, #FFEDD5 100%);
            border: 1px solid #FED7AA;
            border-radius: 8px;
            margin-bottom: 16px;
        }}

        .stat-block {{ text-align: center; }}
        .stat-value {{ font-size: 24px; font-weight: 700; color: #EA580C; }}
        .stat-label {{ font-size: 10px; color: var(--ds-gray); text-transform: uppercase; }}

        /* Items List */
        .items-list {{
            max-height: 250px;
            overflow-y: auto;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
        }}

        .item-row {{
            padding: 12px;
            border-bottom: 1px solid var(--ds-gray-light);
            cursor: pointer;
            transition: background 0.15s;
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .item-row:last-child {{ border-bottom: none; }}
        .item-row:hover {{ background: #f0f7ff; }}
        .item-row.selected {{ background: #e0f0ff; border-left: 3px solid var(--ds-blue); }}

        .item-thumb {{
            width: 48px;
            height: 48px;
            border-radius: 4px;
            background: #ddd;
            flex-shrink: 0;
            object-fit: cover;
        }}

        .item-info {{ flex: 1; min-width: 0; }}
        .item-name {{
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .item-meta {{
            font-size: 11px;
            color: var(--ds-gray);
            margin-top: 2px;
        }}

        .item-delete {{
            padding: 6px 10px;
            background: transparent;
            border: 1px solid #dc2626;
            color: #dc2626;
            border-radius: 4px;
            font-size: 11px;
            cursor: pointer;
            flex-shrink: 0;
            transition: all 0.15s;
        }}

        .item-delete:hover {{
            background: #dc2626;
            color: white;
        }}

        /* Modal */
        .modal-overlay {{
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
        }}

        .modal-content {{
            background: white;
            padding: 24px;
            border-radius: 8px;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }}

        .modal-title {{
            font-size: 18px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 12px;
        }}

        .modal-body {{
            font-size: 14px;
            color: var(--ds-gray);
            margin-bottom: 20px;
            line-height: 1.5;
        }}

        .modal-buttons {{
            display: flex;
            gap: 12px;
            justify-content: flex-end;
        }}

        .btn-danger {{
            background: #dc2626;
            color: white;
        }}

        .btn-danger:hover {{
            background: #b91c1c;
        }}

        .btn-cancel {{
            background: var(--ds-gray-light);
            color: var(--ds-navy);
        }}

        .btn-cancel:hover {{
            background: #e5e7eb;
        }}

        /* Band Controls */
        .band-controls {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }}

        .band-select-group {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}

        .band-select-group label {{
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
        }}

        .band-select {{
            padding: 8px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-size: 13px;
        }}

        .preset-buttons {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }}

        .preset-btn {{
            padding: 6px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            background: white;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .preset-btn:hover {{ border-color: var(--ds-blue); background: #f0f7ff; }}
        .preset-btn.active {{ background: var(--ds-blue); color: white; border-color: var(--ds-blue); }}

        /* Rescale Controls */
        .rescale-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }}

        .rescale-input {{
            width: 80px;
            padding: 8px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-size: 13px;
            text-align: center;
        }}

        .colormap-select {{
            width: 100%;
            padding: 10px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            font-size: 13px;
        }}

        /* Status */
        .status-bar {{
            padding: 12px;
            background: var(--ds-bg);
            border-radius: 6px;
            text-align: center;
            font-size: 12px;
            color: var(--ds-gray);
            margin-top: 12px;
        }}

        .status-bar.success {{ background: #D1FAE5; color: #065F46; }}
        .status-bar.error {{ background: #FEE2E2; color: #991B1B; }}

        /* Map Container - 70% (left side) */
        .map-container {{
            flex: 1;
            position: relative;
            order: 1;
        }}

        #map {{ height: 100%; width: 100%; }}

        .map-overlay {{
            position: absolute;
            background: white;
            padding: 10px 16px;
            border-radius: 6px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 1000;
            font-size: 12px;
        }}

        .map-status {{ bottom: 20px; left: 20px; }}
        .layer-info {{ top: 20px; right: 20px; max-width: 300px; }}

        .layer-info-title {{
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--ds-blue);
        }}

        .layer-info-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 11px;
        }}

        .layer-info-label {{ color: var(--ds-gray); }}
        .layer-info-value {{ font-weight: 600; color: var(--ds-navy); }}

        /* Point Query Popup */
        .point-query-popup {{
            min-width: 200px;
        }}

        .point-query-popup .popup-title {{
            font-weight: 600;
            font-size: 13px;
            color: var(--ds-navy);
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 2px solid var(--ds-blue);
        }}

        .point-query-popup .popup-coords {{
            font-size: 11px;
            color: var(--ds-gray);
            margin-bottom: 8px;
            font-family: 'Courier New', monospace;
        }}

        .point-query-popup .band-values {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 12px;
        }}

        .point-query-popup .band-row {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            padding: 2px 0;
        }}

        .point-query-popup .band-label {{
            color: var(--ds-gray);
        }}

        .point-query-popup .band-value {{
            font-weight: 600;
            color: var(--ds-navy);
            font-family: 'Courier New', monospace;
        }}

        .point-query-popup .loading {{
            text-align: center;
            padding: 10px;
            color: var(--ds-gray);
        }}

        /* QA Status */
        .qa-section {{
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }}

        .qa-btn {{
            flex: 1;
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .qa-btn.approve {{
            background: #10B981;
            color: white;
        }}

        .qa-btn.approve:hover {{
            background: #059669;
        }}

        .qa-btn.reject {{
            background: #DC2626;
            color: white;
        }}

        .qa-btn.reject:hover {{
            background: #B91C1C;
        }}

        .qa-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}

        .qa-status-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .qa-status-badge.pending {{
            background: #FEF3C7;
            color: #92400E;
        }}

        .qa-status-badge.approved {{
            background: #D1FAE5;
            color: #065F46;
        }}

        .qa-status-badge.rejected {{
            background: #FEE2E2;
            color: #991B1B;
        }}

        /* Loading Overlay */
        .loading-overlay {{
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.85);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1001;
        }}

        .loading-overlay.active {{ display: flex; }}

        .spinner {{
            width: 48px;
            height: 48px;
            border: 4px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }}

        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

        /* Buttons */
        .btn {{
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .btn-primary {{
            background: var(--ds-blue);
            color: white;
            width: 100%;
        }}

        .btn-primary:hover {{ background: var(--ds-light-blue); }}

        .btn-secondary {{
            background: white;
            color: var(--ds-navy);
            border: 1px solid var(--ds-gray-light);
        }}

        .btn-secondary:hover {{ background: var(--ds-bg); }}

        /* Responsive */
        @media (max-width: 900px) {{
            .app-container {{ flex-direction: column; }}
            .sidebar {{ width: 100%; max-width: none; height: 45%; order: 2; }}
            .map-container {{ height: 55%; order: 1; }}
        }}
    </style>
</head>
<body>
    <div class="app-container">
        <!-- Right Sidebar (appears on right due to CSS order) -->
        <div class="sidebar">
            <div class="sidebar-header">
                <h1>Raster Collection Viewer</h1>
                <div class="collection-id">{collection_id}</div>
            </div>

            <div class="sidebar-content">
                <!-- Item Stats -->
                <div class="item-stats">
                    <div class="stat-block">
                        <div class="stat-value" id="total-items">{total_items}</div>
                        <div class="stat-label">Total Items</div>
                    </div>
                    <div class="stat-block">
                        <div class="stat-value" id="loaded-items">{len(items)}</div>
                        <div class="stat-label">Loaded</div>
                    </div>
                </div>

                <!-- Items List -->
                <div class="section-card">
                    <div class="section-header">Collection Items</div>
                    <div class="section-body">
                        <div class="items-list" id="items-list">
                            <!-- Items populated by JavaScript -->
                        </div>
                    </div>
                </div>

                <!-- Band Selection -->
                <div class="section-card" id="band-section">
                    <div class="section-header">Band Selection</div>
                    <div class="section-body">
                        <div class="band-controls">
                            <div class="band-select-group">
                                <label>R</label>
                                <select class="band-select" id="band-r">
                                    <option value="1">Band 1</option>
                                </select>
                            </div>
                            <div class="band-select-group">
                                <label>G</label>
                                <select class="band-select" id="band-g">
                                    <option value="2">Band 2</option>
                                </select>
                            </div>
                            <div class="band-select-group">
                                <label>B</label>
                                <select class="band-select" id="band-b">
                                    <option value="3">Band 3</option>
                                </select>
                            </div>
                        </div>
                        <div class="preset-buttons" id="preset-buttons">
                            <button class="preset-btn active" data-bands="1,2,3">RGB</button>
                            <button class="preset-btn" data-bands="4,3,2">NIR</button>
                            <button class="preset-btn" data-bands="1">Band 1</button>
                        </div>
                        <button class="btn btn-primary" style="margin-top: 12px;" onclick="applyBandSelection()">
                            Apply Bands
                        </button>
                    </div>
                </div>

                <!-- Rescale & Colormap -->
                <div class="section-card" id="rescale-section">
                    <div class="section-header">Rescale & Colormap</div>
                    <div class="section-body">
                        <div class="rescale-row">
                            <span style="font-size: 12px; width: 60px;">Rescale:</span>
                            <input type="number" class="rescale-input" id="rescale-min" placeholder="Min">
                            <span>to</span>
                            <input type="number" class="rescale-input" id="rescale-max" placeholder="Max">
                        </div>
                        <div style="margin-top: 12px;">
                            <label style="font-size: 11px; font-weight: 600; color: var(--ds-gray); display: block; margin-bottom: 6px;">Colormap (Single Band)</label>
                            <select class="colormap-select" id="colormap-select">
                                <option value="">None (Grayscale)</option>
                                <option value="terrain">Terrain (DEM)</option>
                                <option value="viridis">Viridis</option>
                                <option value="rdylgn">RdYlGn (Vegetation)</option>
                                <option value="blues">Blues</option>
                                <option value="plasma">Plasma</option>
                                <option value="magma">Magma</option>
                                <option value="inferno">Inferno</option>
                            </select>
                        </div>
                        <button class="btn btn-primary" style="margin-top: 12px;" onclick="applyRescale()">
                            Apply Rescale
                        </button>
                    </div>
                </div>

                <!-- QA Actions -->
                <div class="section-card" id="qa-section" style="display: none;">
                    <div class="section-header">QA Review</div>
                    <div class="section-body">
                        <div style="margin-bottom: 12px; font-size: 13px;">
                            Current status: <span id="qa-current-status" class="qa-status-badge pending">pending</span>
                        </div>
                        <div class="qa-section">
                            <button class="qa-btn approve" onclick="setQaStatus('approved')">✓ Approve</button>
                            <button class="qa-btn reject" onclick="setQaStatus('rejected')">✗ Reject</button>
                        </div>
                    </div>
                </div>

                <!-- Status -->
                <div class="status-bar" id="status">
                    Select an item to view. Click on map for band values.
                </div>
            </div>
        </div>

        <!-- Map Container (appears on left due to CSS order) -->
        <div class="map-container">
            <div id="map"></div>

            <div class="loading-overlay" id="loading">
                <div class="spinner"></div>
            </div>

            <div class="map-overlay map-status">
                Zoom: <span id="zoom-level">--</span> |
                Center: <span id="map-center">--</span>
            </div>

            <div class="map-overlay layer-info" id="layer-info" style="display: none;">
                <div class="layer-info-title" id="layer-title">No Layer</div>
                <div class="layer-info-row">
                    <span class="layer-info-label">Type:</span>
                    <span class="layer-info-value" id="layer-type">--</span>
                </div>
                <div class="layer-info-row">
                    <span class="layer-info-label">Bands:</span>
                    <span class="layer-info-value" id="layer-bands">--</span>
                </div>
                <div class="layer-info-row">
                    <span class="layer-info-label">Rescale:</span>
                    <span class="layer-info-value" id="layer-rescale">--</span>
                </div>
            </div>
        </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div class="modal-overlay" id="delete-modal" style="display: none;">
        <div class="modal-content">
            <div class="modal-title">Delete STAC Item</div>
            <div class="modal-body">
                Are you sure you want to delete item <strong id="delete-item-id"></strong>?
                <br><br>
                This will remove the item from the STAC catalog and delete associated files. This action cannot be undone.
            </div>
            <div class="modal-buttons">
                <button class="btn btn-cancel" onclick="closeDeleteModal()">Cancel</button>
                <button class="btn btn-danger" onclick="confirmDelete()">Delete</button>
            </div>
        </div>
    </div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""></script>

    <script>
        // Configuration
        const COLLECTION_ID = '{collection_id}';
        const ITEMS_URL = '{items_url}';
        const TITILER_BASE = '{titiler_base}';
        const BBOX = {json.dumps(bbox)};
        const INITIAL_ITEMS = {items_json};

        // State
        let currentItem = null;
        let tileLayer = null;
        let currentBands = [1, 2, 3];
        let currentRescale = null;
        let currentColormap = null;

        // Initialize map
        const map = L.map('map').setView([{center_lat}, {center_lon}], 6);

        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
        }}).addTo(map);

        // Update map status
        map.on('moveend zoomend', () => {{
            const center = map.getCenter();
            document.getElementById('zoom-level').textContent = map.getZoom();
            document.getElementById('map-center').textContent =
                `${{center.lat.toFixed(4)}}, ${{center.lng.toFixed(4)}}`;
        }});

        // Populate items list
        function populateItemsList() {{
            const listEl = document.getElementById('items-list');
            listEl.innerHTML = '';

            INITIAL_ITEMS.forEach((item, index) => {{
                const props = item.properties || {{}};
                const itemId = item.id || `item-${{index}}`;

                // Get thumbnail URL if available
                const thumbUrl = item.assets?.thumbnail?.href || '';

                // Get raster metadata
                const rasterType = props['app:raster_type'] || 'unknown';
                const bandCount = props['app:band_count'] || '?';
                const datetime = props.datetime ? new Date(props.datetime).toLocaleDateString() : '';

                const row = document.createElement('div');
                row.className = 'item-row';
                row.dataset.index = index;

                row.innerHTML = `
                    ${{thumbUrl ? `<img class="item-thumb" src="${{thumbUrl}}" onerror="this.style.display='none'">` : ''}}
                    <div class="item-info" onclick="selectItem(${{index}})">
                        <div class="item-name">${{itemId}}</div>
                        <div class="item-meta">${{rasterType}} | ${{bandCount}} bands ${{datetime ? '| ' + datetime : ''}}</div>
                    </div>
                    <button class="item-delete" onclick="showDeleteModal('${{itemId}}', event)" title="Delete item">🗑️</button>
                `;

                // Click on row (but not delete button) selects item
                row.onclick = (e) => {{ if (!e.target.classList.contains('item-delete')) selectItem(index); }};
                listEl.appendChild(row);
            }});
        }}

        // Select an item
        function selectItem(index) {{
            currentItem = INITIAL_ITEMS[index];

            // Update selection UI
            document.querySelectorAll('.item-row').forEach(row => {{
                row.classList.toggle('selected', parseInt(row.dataset.index) === index);
            }});

            // Update band selectors based on item metadata
            updateBandSelectors();

            // Apply item's app:* metadata if available
            applyItemMetadata();

            // Show QA section and update status
            updateQaSection();

            // Load tile layer
            loadTileLayer();
        }}

        // Update band selectors based on current item
        function updateBandSelectors() {{
            const bandCount = currentItem?.properties?.['app:band_count'] || 3;

            ['band-r', 'band-g', 'band-b'].forEach(id => {{
                const select = document.getElementById(id);
                select.innerHTML = '';
                for (let i = 1; i <= bandCount; i++) {{
                    const option = document.createElement('option');
                    option.value = i;
                    option.textContent = `Band ${{i}}`;
                    select.appendChild(option);
                }}
            }});

            // Set default RGB
            document.getElementById('band-r').value = Math.min(1, bandCount);
            document.getElementById('band-g').value = Math.min(2, bandCount);
            document.getElementById('band-b').value = Math.min(3, bandCount);

            // Update presets based on band count
            updatePresetButtons(bandCount);
        }}

        // Update preset buttons based on band count
        function updatePresetButtons(bandCount) {{
            const container = document.getElementById('preset-buttons');
            container.innerHTML = '';

            // Always add first band
            addPreset(container, 'Band 1', '1');

            if (bandCount >= 3) {{
                addPreset(container, 'RGB', '1,2,3', true);
            }}

            if (bandCount >= 4) {{
                addPreset(container, 'RGB (1-3)', '1,2,3');
                addPreset(container, 'NIR', '4,3,2');
            }}

            if (bandCount === 8) {{
                // WorldView-3 presets
                addPreset(container, 'WV3 RGB', '5,3,2');
                addPreset(container, 'WV3 NIR', '7,5,3');
            }}

            if (bandCount >= 10) {{
                // Sentinel-2/Landsat presets
                addPreset(container, 'S2 RGB', '4,3,2');
                addPreset(container, 'S2 NIR', '8,4,3');
            }}
        }}

        function addPreset(container, label, bands, active = false) {{
            const btn = document.createElement('button');
            btn.className = 'preset-btn' + (active ? ' active' : '');
            btn.dataset.bands = bands;
            btn.textContent = label;
            btn.onclick = () => selectPreset(btn, bands);
            container.appendChild(btn);
        }}

        function selectPreset(btn, bandsStr) {{
            // Update button states
            document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Parse bands
            const bands = bandsStr.split(',').map(b => parseInt(b.trim()));
            currentBands = bands;

            // Update selectors
            if (bands.length >= 1) document.getElementById('band-r').value = bands[0];
            if (bands.length >= 2) document.getElementById('band-g').value = bands[1];
            if (bands.length >= 3) document.getElementById('band-b').value = bands[2];

            // Reload layer
            if (currentItem) loadTileLayer();
        }}

        // Apply item's app:* metadata
        function applyItemMetadata() {{
            const props = currentItem?.properties || {{}};

            // Apply rgb_bands if available
            const rgbBands = props['app:rgb_bands'];
            if (rgbBands && Array.isArray(rgbBands)) {{
                currentBands = rgbBands;
                if (rgbBands.length >= 1) document.getElementById('band-r').value = rgbBands[0];
                if (rgbBands.length >= 2) document.getElementById('band-g').value = rgbBands[1];
                if (rgbBands.length >= 3) document.getElementById('band-b').value = rgbBands[2];
            }}

            // Apply rescale if available
            const rescale = props['app:rescale'];
            if (rescale && rescale.min !== undefined && rescale.max !== undefined) {{
                currentRescale = [rescale.min, rescale.max];
                document.getElementById('rescale-min').value = rescale.min;
                document.getElementById('rescale-max').value = rescale.max;
            }} else {{
                currentRescale = null;
                document.getElementById('rescale-min').value = '';
                document.getElementById('rescale-max').value = '';
            }}

            // Apply colormap if available
            const colormap = props['app:colormap'];
            if (colormap) {{
                currentColormap = colormap;
                document.getElementById('colormap-select').value = colormap;
            }} else {{
                currentColormap = null;
                document.getElementById('colormap-select').value = '';
            }}
        }}

        // Build TiTiler tile URL
        function buildTileUrl() {{
            if (!currentItem) return null;

            // Get COG URL from data asset
            const dataAsset = currentItem.assets?.data || currentItem.assets?.visual || Object.values(currentItem.assets || {{}})[0];
            if (!dataAsset?.href) {{
                setStatus('No data asset found in item', 'error');
                return null;
            }}

            const cogUrl = dataAsset.href;
            const encodedUrl = encodeURIComponent(cogUrl);

            // Build params
            const params = [`url=${{encodedUrl}}`];

            // Add band indices
            if (currentBands.length > 1) {{
                currentBands.forEach(b => params.push(`bidx=${{b}}`));
            }} else if (currentBands.length === 1) {{
                params.push(`bidx=${{currentBands[0]}}`);
            }}

            // Add rescale
            if (currentRescale && currentRescale.length === 2) {{
                params.push(`rescale=${{currentRescale[0]}},${{currentRescale[1]}}`);
            }}

            // Add colormap (only for single band)
            if (currentColormap && currentBands.length === 1) {{
                params.push(`colormap_name=${{currentColormap}}`);
            }}

            const paramStr = params.join('&');
            return `${{TITILER_BASE}}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?${{paramStr}}`;
        }}

        // Load tile layer
        async function loadTileLayer() {{
            if (!currentItem) return;

            showLoading();

            // Remove existing layer
            if (tileLayer) {{
                map.removeLayer(tileLayer);
            }}

            const tileUrl = buildTileUrl();
            if (!tileUrl) {{
                hideLoading();
                return;
            }}

            try {{
                // Fetch TileJSON to get actual minzoom for this COG
                // (03 FEB 2026: fixes issue where tiles don't appear if viewer zoom < COG minzoom)
                const dataAsset = currentItem.assets?.data || currentItem.assets?.visual || Object.values(currentItem.assets || {{}})[0];
                const cogUrl = dataAsset?.href;
                let minZoom = 10;  // Default fallback

                if (cogUrl) {{
                    try {{
                        const tileJsonUrl = `${{TITILER_BASE}}/cog/WebMercatorQuad/tilejson.json?url=${{encodeURIComponent(cogUrl)}}`;
                        const tjResp = await fetch(tileJsonUrl);
                        if (tjResp.ok) {{
                            const tj = await tjResp.json();
                            minZoom = tj.minzoom || 10;
                            console.log(`COG minzoom from tilejson: ${{minZoom}}`);
                        }}
                    }} catch (e) {{
                        console.warn('Could not fetch tilejson for minzoom:', e);
                    }}
                }}

                tileLayer = L.tileLayer(tileUrl, {{
                    maxZoom: 22,
                    minNativeZoom: minZoom,  // Prevent tile requests below this zoom
                    tileSize: 256,
                    attribution: 'TiTiler'
                }}).addTo(map);

                tileLayer.on('load', () => {{
                    hideLoading();
                    setStatus(`Loaded: ${{currentItem.id}}`, 'success');
                    updateLayerInfo();
                }});

                tileLayer.on('tileerror', (error) => {{
                    console.error('Tile error:', error);
                }});

                // Zoom to item bbox
                const itemBbox = currentItem.bbox;
                if (itemBbox && itemBbox.length >= 4) {{
                    const bounds = [[itemBbox[1], itemBbox[0]], [itemBbox[3], itemBbox[2]]];
                    map.fitBounds(bounds, {{ padding: [50, 50], maxZoom: 18 }});

                    // Ensure we're zoomed in enough to see tiles
                    // (minZoom from tilejson tells us the lowest zoom with valid tiles)
                    setTimeout(() => {{
                        if (map.getZoom() < minZoom) {{
                            console.log(`Zoom ${{map.getZoom()}} < minzoom ${{minZoom}}, zooming in`);
                            map.setZoom(minZoom);
                        }}
                    }}, 100);
                }}

            }} catch (error) {{
                hideLoading();
                setStatus(`Error: ${{error.message}}`, 'error');
            }}
        }}

        // Update layer info panel
        function updateLayerInfo() {{
            const panel = document.getElementById('layer-info');
            panel.style.display = 'block';

            document.getElementById('layer-title').textContent = currentItem?.id || 'Unknown';
            document.getElementById('layer-type').textContent = currentItem?.properties?.['app:raster_type'] || 'unknown';
            document.getElementById('layer-bands').textContent = currentBands.join(', ');
            document.getElementById('layer-rescale').textContent = currentRescale ? `${{currentRescale[0]}} - ${{currentRescale[1]}}` : 'auto';
        }}

        // Apply band selection
        function applyBandSelection() {{
            currentBands = [
                parseInt(document.getElementById('band-r').value),
                parseInt(document.getElementById('band-g').value),
                parseInt(document.getElementById('band-b').value)
            ];

            // Clear preset selection
            document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));

            if (currentItem) loadTileLayer();
        }}

        // Apply rescale
        function applyRescale() {{
            const min = parseFloat(document.getElementById('rescale-min').value);
            const max = parseFloat(document.getElementById('rescale-max').value);

            if (!isNaN(min) && !isNaN(max)) {{
                currentRescale = [min, max];
            }} else {{
                currentRescale = null;
            }}

            currentColormap = document.getElementById('colormap-select').value || null;

            if (currentItem) loadTileLayer();
        }}

        // UI helpers
        function showLoading() {{ document.getElementById('loading').classList.add('active'); }}
        function hideLoading() {{ document.getElementById('loading').classList.remove('active'); }}

        function setStatus(message, type = '') {{
            const el = document.getElementById('status');
            el.textContent = message;
            el.className = 'status-bar' + (type ? ' ' + type : '');
        }}

        // Delete item functionality
        let pendingDeleteItemId = null;

        function showDeleteModal(itemId, event) {{
            event.stopPropagation();
            pendingDeleteItemId = itemId;
            document.getElementById('delete-item-id').textContent = itemId;
            document.getElementById('delete-modal').style.display = 'flex';
        }}

        function closeDeleteModal() {{
            document.getElementById('delete-modal').style.display = 'none';
            pendingDeleteItemId = null;
        }}

        async function confirmDelete() {{
            if (!pendingDeleteItemId) return;

            const itemId = pendingDeleteItemId;
            closeDeleteModal();
            showLoading();
            setStatus(`Deleting item ${{itemId}}...`);

            try {{
                const response = await fetch('/api/platform/unpublish/raster', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        stac_item_id: itemId,
                        collection_id: COLLECTION_ID,
                        dry_run: false
                    }})
                }});

                const result = await response.json();

                if (response.ok && result.success) {{
                    setStatus(`Deleted: ${{itemId}}`, 'success');

                    // Remove item from list and refresh
                    const idx = INITIAL_ITEMS.findIndex(item => item.id === itemId);
                    if (idx !== -1) {{
                        INITIAL_ITEMS.splice(idx, 1);
                        populateItemsList();

                        // Update counts
                        document.getElementById('total-items').textContent = INITIAL_ITEMS.length;
                        document.getElementById('loaded-items').textContent = INITIAL_ITEMS.length;

                        // If deleted item was selected, select first available
                        if (currentItem && currentItem.id === itemId) {{
                            currentItem = null;
                            if (tileLayer) {{
                                map.removeLayer(tileLayer);
                                tileLayer = null;
                            }}
                            if (INITIAL_ITEMS.length > 0) {{
                                selectItem(0);
                            }}
                        }}
                    }}
                }} else {{
                    const errMsg = result.error || result.message || 'Unknown error';
                    setStatus(`Delete failed: ${{errMsg}}`, 'error');
                }}
            }} catch (error) {{
                console.error('Delete error:', error);
                setStatus(`Delete error: ${{error.message}}`, 'error');
            }} finally {{
                hideLoading();
            }}
        }}

        // QA Section Management
        function updateQaSection() {{
            if (!currentItem) {{
                document.getElementById('qa-section').style.display = 'none';
                return;
            }}

            // Show QA section
            document.getElementById('qa-section').style.display = 'block';

            // Get current QA status
            const qaStatus = currentItem.properties?.['app:qa_status'] || 'pending';
            updateQaStatusBadge(qaStatus);
        }}

        function updateQaStatusBadge(status) {{
            const badge = document.getElementById('qa-current-status');
            badge.textContent = status;
            badge.className = 'qa-status-badge ' + status;
        }}

        async function setQaStatus(status) {{
            if (!currentItem) return;

            const itemId = currentItem.id;
            showLoading();
            setStatus(`Setting QA status to '${{status}}'...`);

            try {{
                const response = await fetch('/api/raster/qa', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        item_id: itemId,
                        collection_id: COLLECTION_ID,
                        status: status
                    }})
                }});

                const result = await response.json();

                if (response.ok && result.success) {{
                    // Update local item properties
                    currentItem.properties = currentItem.properties || {{}};
                    currentItem.properties['app:qa_status'] = status;

                    // Update UI
                    updateQaStatusBadge(status);
                    setStatus(`QA status set to '${{status}}'`, 'success');
                }} else {{
                    const errMsg = result.error || 'Unknown error';
                    setStatus(`QA update failed: ${{errMsg}}`, 'error');
                }}
            }} catch (error) {{
                console.error('QA status error:', error);
                setStatus(`QA update error: ${{error.message}}`, 'error');
            }} finally {{
                hideLoading();
            }}
        }}

        // Close modal on overlay click
        document.getElementById('delete-modal')?.addEventListener('click', (e) => {{
            if (e.target.classList.contains('modal-overlay')) closeDeleteModal();
        }});

        // Point Query on Map Click
        let pointQueryPopup = null;

        map.on('click', async (e) => {{
            if (!currentItem) return;

            const {{ lat, lng }} = e.latlng;

            // Get COG URL from data asset
            const dataAsset = currentItem.assets?.data || currentItem.assets?.visual || Object.values(currentItem.assets || {{}})[0];
            if (!dataAsset?.href) return;

            // Show loading popup
            if (pointQueryPopup) {{
                map.closePopup(pointQueryPopup);
            }}

            pointQueryPopup = L.popup()
                .setLatLng(e.latlng)
                .setContent(`
                    <div class="point-query-popup">
                        <div class="popup-title">Point Query</div>
                        <div class="popup-coords">${{lat.toFixed(6)}}, ${{lng.toFixed(6)}}</div>
                        <div class="loading">Loading band values...</div>
                    </div>
                `)
                .openOn(map);

            // Query TiTiler point endpoint
            try {{
                const cogUrl = dataAsset.href;
                const encodedUrl = encodeURIComponent(cogUrl);
                const pointUrl = `${{TITILER_BASE}}/cog/point/${{lng}},${{lat}}?url=${{encodedUrl}}`;

                const response = await fetch(pointUrl);
                const result = await response.json();

                if (response.ok && result.values) {{
                    // Build band values HTML
                    const bandCount = result.values.length;
                    let bandHtml = '<div class="band-values">';

                    result.values.forEach((val, idx) => {{
                        const bandNum = idx + 1;
                        const displayVal = val === null || val === undefined ? 'NoData' :
                            (typeof val === 'number' ? val.toFixed(4) : val);
                        bandHtml += `
                            <div class="band-row">
                                <span class="band-label">Band ${{bandNum}}:</span>
                                <span class="band-value">${{displayVal}}</span>
                            </div>
                        `;
                    }});
                    bandHtml += '</div>';

                    pointQueryPopup.setContent(`
                        <div class="point-query-popup">
                            <div class="popup-title">Band Values</div>
                            <div class="popup-coords">${{lat.toFixed(6)}}, ${{lng.toFixed(6)}}</div>
                            ${{bandHtml}}
                        </div>
                    `);
                }} else {{
                    // No data at location or error
                    const errMsg = result.detail || 'No data at this location';
                    pointQueryPopup.setContent(`
                        <div class="point-query-popup">
                            <div class="popup-title">Point Query</div>
                            <div class="popup-coords">${{lat.toFixed(6)}}, ${{lng.toFixed(6)}}</div>
                            <div style="color: #999; font-style: italic;">No data available</div>
                        </div>
                    `);
                }}
            }} catch (error) {{
                console.error('Point query error:', error);
                pointQueryPopup.setContent(`
                    <div class="point-query-popup">
                        <div class="popup-title">Point Query</div>
                        <div class="popup-coords">${{lat.toFixed(6)}}, ${{lng.toFixed(6)}}</div>
                        <div style="color: #dc2626;">Error: ${{error.message}}</div>
                    </div>
                `);
            }}
        }});

        // Parse URL parameters
        function getUrlParams() {{
            const params = new URLSearchParams(window.location.search);
            return {{
                item: params.get('item'),
                collection: params.get('collection')
            }};
        }}

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            populateItemsList();

            // Zoom to collection bbox
            if (BBOX && BBOX.length >= 4 && BBOX[0] !== 0) {{
                const bounds = [[BBOX[1], BBOX[0]], [BBOX[3], BBOX[2]]];
                map.fitBounds(bounds, {{ padding: [50, 50] }});
            }}

            // Check for item URL parameter
            const urlParams = getUrlParams();
            if (urlParams.item) {{
                // Find and select the item by ID
                const itemIndex = INITIAL_ITEMS.findIndex(item => item.id === urlParams.item);
                if (itemIndex !== -1) {{
                    selectItem(itemIndex);
                    setStatus(`Loaded item from URL: ${{urlParams.item}}`, 'success');
                }} else {{
                    setStatus(`Item not found: ${{urlParams.item}}`, 'error');
                    // Still select first item as fallback
                    if (INITIAL_ITEMS.length > 0) {{
                        selectItem(0);
                    }}
                }}
            }} else {{
                // Auto-select first item if available
                if (INITIAL_ITEMS.length > 0) {{
                    selectItem(0);
                }}
            }}
        }});

        console.log('Raster Collection Viewer initialized');
        console.log('Collection:', COLLECTION_ID);
        console.log('TiTiler:', TITILER_BASE);
    </script>
</body>
</html>"""

        return html
