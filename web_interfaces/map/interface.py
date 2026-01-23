"""
Map interface module.

Interactive Leaflet map viewer for OGC Features collections with vector data visualization.

Updated (23 JAN 2026 - TiPG Standardization):
    - Collections and features fetched from TiPG (high-performance Docker endpoint)
    - Internal OGC Features API reserved for emergency backup only
    - Schema-qualified collection IDs (geo.{table_name}) for TiPG

Exports:
    MapInterface: Interactive map viewer with collection selection and feature display
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
from config import get_config


@InterfaceRegistry.register('map')
class MapInterface(BaseInterface):
    """
    Interactive Map Viewer interface.

    Full-page Leaflet map for visualizing OGC Features collections with:
        - Collection dropdown
        - Feature limit control
        - Simplification parameter
        - Click popups showing properties
        - Hover highlighting
        - Zoom to features
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Map Viewer HTML.

        Note: This interface uses a custom HTML structure instead of wrap_html()
        because it requires external Leaflet CSS/JS resources and full-page map layout.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        # Get TiPG base URL from config (23 JAN 2026)
        try:
            config = get_config()
            tipg_base_url = config.tipg_base_url.rstrip('/')
        except Exception:
            # Fallback for local dev
            tipg_base_url = 'https://rmhtitiler-ckdxapgkg4e2gtfp.eastus-01.azurewebsites.net/vector'

        return self._generate_full_page(tipg_base_url)

    def _generate_full_page(self, tipg_base_url: str) -> str:
        """Generate complete HTML page with Leaflet dependencies."""
        css_content = self._generate_css()
        navbar_content = self._generate_navbar()
        html_content = self._generate_html_content()
        js_content = self._generate_js(tipg_base_url)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Map Viewer - OGC Features</title>

    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin=""/>

    <style>
        {css_content}
    </style>
</head>
<body>
    {navbar_content}
    {html_content}

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""></script>

    <script>
        {js_content}
    </script>
</body>
</html>"""

    def _generate_navbar(self) -> str:
        """Generate navigation bar matching web_interfaces style."""
        return """
        <nav class="map-nav">
            <a href="/api/interface/home" class="nav-brand">Geospatial API</a>
            <div class="nav-links">
                <a href="/api/interface/stac">STAC</a>
                <a href="/api/interface/vector">OGC Features</a>
                <a href="/api/interface/pipeline">Storage</a>
                <a href="/api/interface/jobs">Jobs</a>
                <a href="/api/interface/map" class="active">Map</a>
                <a href="/api/interface/health">Health</a>
            </div>
        </nav>
        """

    def _generate_html_content(self) -> str:
        """Generate HTML content structure."""
        return """
        <!-- Map Container -->
        <div id="map"></div>

        <!-- Control Panel -->
        <div class="control-panel">
            <h3>Map Viewer</h3>

            <div class="control-group">
                <label for="collection-select">Collection:</label>
                <select id="collection-select">
                    <option value="">Loading collections...</option>
                </select>
            </div>

            <div class="control-group">
                <label for="limit-select">Features:</label>
                <select id="limit-select">
                    <option value="50">50</option>
                    <option value="100" selected>100</option>
                    <option value="250">250</option>
                    <option value="500">500</option>
                    <option value="1000">1000</option>
                </select>
            </div>

            <div class="control-group">
                <label for="simplify-input">Simplify (m):</label>
                <input type="number" id="simplify-input" min="0" step="0.1" value="0"
                       placeholder="0 = none">
            </div>

            <div class="button-group">
                <button id="load-btn" onclick="loadFeatures()" class="btn-primary">
                    Load Features
                </button>
                <button id="zoom-btn" onclick="zoomToFeatures()" class="btn-secondary" disabled>
                    Zoom to Fit
                </button>
                <button id="clear-btn" onclick="clearFeatures()" class="btn-secondary">
                    Clear Map
                </button>
            </div>

            <div class="status-section">
                <div id="status" class="status-text">Ready</div>
                <div id="feature-count" class="feature-count"></div>
            </div>
        </div>

        <!-- Loading Spinner -->
        <div class="spinner" id="spinner">
            <div class="spinner-icon"></div>
            <div class="spinner-text">Loading features...</div>
        </div>
        """

    def _generate_css(self) -> str:
        """Generate CSS styles."""
        return """
        /* Reset */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Open Sans", Arial, sans-serif;
            background: #f8f9fa;
        }

        /* Navigation - Design System style */
        .map-nav {
            background: white;
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 3px solid #0071BC;
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1001;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .nav-brand {
            font-size: 18px;
            font-weight: 700;
            color: #053657;
            text-decoration: none;
        }

        .nav-brand:hover {
            color: #0071BC;
        }

        .nav-links {
            display: flex;
            gap: 20px;
        }

        .nav-links a {
            color: #0071BC;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            padding: 6px 12px;
            border-radius: 4px;
            transition: all 0.2s;
        }

        .nav-links a:hover {
            background: #f0f7ff;
            color: #00A3DA;
        }

        .nav-links a.active {
            background: #0071BC;
            color: white;
        }

        /* Map */
        #map {
            position: absolute;
            top: 52px;
            bottom: 0;
            left: 0;
            right: 0;
        }

        /* Control Panel - Design System style */
        .control-panel {
            position: absolute;
            top: 62px;
            right: 10px;
            background: white;
            padding: 20px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 1000;
            width: 280px;
            border-left: 4px solid #0071BC;
        }

        .control-panel h3 {
            font-size: 18px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
        }

        .control-group {
            margin-bottom: 12px;
        }

        .control-group label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }

        .control-group select,
        .control-group input {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            font-size: 14px;
            color: #053657;
            background: white;
        }

        .control-group select:focus,
        .control-group input:focus {
            outline: none;
            border-color: #0071BC;
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }

        .button-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 16px;
        }

        .btn-primary, .btn-secondary {
            width: 100%;
            padding: 10px 16px;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: #0071BC;
            color: white;
        }

        .btn-primary:hover {
            background: #00A3DA;
        }

        .btn-secondary {
            background: #f8f9fa;
            color: #053657;
            border: 1px solid #e9ecef;
        }

        .btn-secondary:hover:not(:disabled) {
            background: #e9ecef;
        }

        .btn-primary:disabled,
        .btn-secondary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .status-section {
            margin-top: 16px;
            padding-top: 12px;
            border-top: 1px solid #e9ecef;
        }

        .status-text {
            font-size: 13px;
            color: #626F86;
        }

        .status-text.error {
            color: #DC2626;
        }

        .status-text.success {
            color: #10B981;
        }

        .feature-count {
            font-size: 12px;
            color: #0071BC;
            font-weight: 600;
            margin-top: 4px;
        }

        /* Spinner */
        .spinner {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 2000;
            background: white;
            padding: 30px 40px;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.2);
            display: none;
            text-align: center;
        }

        .spinner.active {
            display: block;
        }

        .spinner-icon {
            border: 4px solid #e9ecef;
            border-top: 4px solid #0071BC;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 12px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .spinner-text {
            color: #053657;
            font-size: 14px;
            font-weight: 600;
        }

        /* Popup styling */
        .leaflet-popup-content {
            margin: 10px;
            font-size: 13px;
        }

        .popup-title {
            font-weight: 700;
            font-size: 14px;
            color: #053657;
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 2px solid #0071BC;
        }

        .popup-row {
            padding: 4px 0;
            border-bottom: 1px solid #f0f0f0;
        }

        .popup-row:last-child {
            border-bottom: none;
        }

        .popup-label {
            font-weight: 600;
            color: #626F86;
            font-size: 11px;
            text-transform: uppercase;
        }

        .popup-value {
            color: #053657;
            display: block;
            margin-top: 2px;
        }
        """

    def _generate_js(self, tipg_base_url: str) -> str:
        """Generate JavaScript code.

        Updated 23 JAN 2026: Use TiPG as primary endpoint for collections and features.

        Args:
            tipg_base_url: TiPG base URL for OGC Features (e.g., https://titiler.../vector)
        """
        return """
        // API Configuration
        const API_BASE_URL = window.location.origin;
        // TiPG endpoint for high-performance OGC Features (23 JAN 2026)
        const TIPG_BASE_URL = '""" + tipg_base_url + """';

        // Helper: Extract table name from schema-qualified ID (geo.table -> table)
        const getTableName = (id) => id.includes('.') ? id.split('.').pop() : id;

        // Initialize map centered on global view
        const map = L.map('map').setView([20, 0], 2);

        // Add OpenStreetMap base layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(map);

        // State
        let currentLayer = null;
        let collections = [];

        // Status functions
        function setStatus(message, type = '') {
            const statusEl = document.getElementById('status');
            statusEl.textContent = message;
            statusEl.className = 'status-text' + (type ? ' ' + type : '');
        }

        function showSpinner() {
            document.getElementById('spinner').classList.add('active');
        }

        function hideSpinner() {
            document.getElementById('spinner').classList.remove('active');
        }

        // Load collections from TiPG (23 JAN 2026 - standardized to TiPG)
        async function loadCollections() {
            try {
                setStatus('Loading collections...');
                const response = await fetch(`${TIPG_BASE_URL}/collections`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                collections = data.collections || [];

                const select = document.getElementById('collection-select');
                select.innerHTML = '';

                if (collections.length === 0) {
                    select.innerHTML = '<option value="">No collections found</option>';
                    setStatus('No collections available', 'error');
                    return;
                }

                collections.forEach(collection => {
                    const option = document.createElement('option');
                    // Store full TiPG ID as value, display table name
                    option.value = collection.id;
                    option.textContent = getTableName(collection.id);
                    select.appendChild(option);
                });

                setStatus(`${collections.length} collections available`);
                document.getElementById('load-btn').disabled = false;

            } catch (error) {
                console.error('Error loading collections:', error);
                setStatus(`Error: ${error.message}`, 'error');
            }
        }

        // Load features from TiPG (23 JAN 2026 - standardized to TiPG)
        async function loadFeatures() {
            const collectionId = document.getElementById('collection-select').value;
            const limit = document.getElementById('limit-select').value;
            const simplify = document.getElementById('simplify-input').value;

            if (!collectionId) {
                setStatus('Select a collection first', 'error');
                return;
            }

            try {
                showSpinner();
                setStatus('Loading features...');
                document.getElementById('load-btn').disabled = true;

                // Use TiPG for features (schema-qualified ID)
                let url = `${TIPG_BASE_URL}/collections/${collectionId}/items?limit=${limit}`;
                if (simplify && parseFloat(simplify) > 0) {
                    url += `&simplify=${simplify}`;
                }

                const response = await fetch(url);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const geojson = await response.json();

                if (!geojson.features || geojson.features.length === 0) {
                    setStatus('No features found', 'error');
                    hideSpinner();
                    document.getElementById('load-btn').disabled = false;
                    return;
                }

                // Clear existing layer
                if (currentLayer) {
                    map.removeLayer(currentLayer);
                }

                // Add features with Design System blue styling
                currentLayer = L.geoJSON(geojson, {
                    style: function(feature) {
                        return {
                            color: '#0071BC',
                            weight: 2,
                            fillOpacity: 0.25,
                            fillColor: '#0071BC'
                        };
                    },
                    onEachFeature: function(feature, layer) {
                        const props = feature.properties || {};
                        let popupContent = '<div class="popup-title">Feature Properties</div>';

                        const keys = Object.keys(props).slice(0, 8);
                        keys.forEach(key => {
                            const value = props[key];
                            if (value !== null && value !== undefined) {
                                popupContent += `<div class="popup-row">
                                    <span class="popup-label">${key}</span>
                                    <span class="popup-value">${value}</span>
                                </div>`;
                            }
                        });

                        if (Object.keys(props).length > 8) {
                            popupContent += `<div class="popup-row" style="color: #626F86; font-style: italic;">
                                +${Object.keys(props).length - 8} more properties
                            </div>`;
                        }

                        layer.bindPopup(popupContent, { maxWidth: 300 });

                        // Hover effects
                        layer.on('mouseover', function() {
                            this.setStyle({ weight: 3, fillOpacity: 0.4 });
                        });
                        layer.on('mouseout', function() {
                            this.setStyle({ weight: 2, fillOpacity: 0.25 });
                        });
                    }
                }).addTo(map);

                // Update UI
                const count = geojson.features.length;
                const total = geojson.numberMatched || count;
                setStatus('Features loaded successfully', 'success');
                document.getElementById('feature-count').textContent =
                    `Showing ${count} of ${total} features`;
                document.getElementById('zoom-btn').disabled = false;

                zoomToFeatures();

            } catch (error) {
                console.error('Error:', error);
                setStatus(`Error: ${error.message}`, 'error');
            } finally {
                hideSpinner();
                document.getElementById('load-btn').disabled = false;
            }
        }

        function zoomToFeatures() {
            if (currentLayer) {
                const bounds = currentLayer.getBounds();
                if (bounds.isValid()) {
                    map.fitBounds(bounds, { padding: [50, 50] });
                }
            }
        }

        function clearFeatures() {
            if (currentLayer) {
                map.removeLayer(currentLayer);
                currentLayer = null;
                document.getElementById('feature-count').textContent = '';
                document.getElementById('zoom-btn').disabled = true;
                setStatus('Map cleared');
            }
        }

        // Initialize
        window.addEventListener('load', loadCollections);

        // Enter key support
        document.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !document.getElementById('load-btn').disabled) {
                loadFeatures();
            }
        });
        """
