# ============================================================================
# CLAUDE CONTEXT - STAC MAP INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web interface - STAC Collections BBox Map Viewer
# PURPOSE: Display STAC collection bounding boxes on interactive Leaflet map
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: StacMapInterface
# DEPENDENCIES: web_interfaces.base, azure.functions
# ============================================================================
"""
STAC Collections Map Interface.

Interactive Leaflet map showing bounding boxes of all STAC collections.
Clicking a collection bbox shows metadata in a popup.

Features:
    - Auto-loads all STAC collections on page load
    - Renders each collection's spatial extent as a colored rectangle
    - Click to view collection details (title, description, item count, temporal extent)
    - Color-coded by collection type or status
    - Search/filter by collection name
    - Zoom to selected collection
    - Toggle visibility of individual collections

Route: /api/interface/stac-map
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

from config import __version__


@InterfaceRegistry.register('stac-map')
class StacMapInterface(BaseInterface):
    """
    STAC Collections Map Interface.

    Displays bounding boxes of all STAC collections on an interactive
    Leaflet map with click-to-inspect functionality.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate full-page Leaflet map with STAC collection bboxes.

        Args:
            request: Azure Functions HTTP request

        Returns:
            Complete HTML page string
        """
        return self._generate_full_page()

    def _generate_full_page(self) -> str:
        """Generate complete HTML document with Leaflet map."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STAC Collections Map - Geospatial API</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        {self._generate_css()}
    </style>
</head>
<body>
    {self._generate_navbar()}

    <div id="map"></div>

    <div class="control-panel">
        <h3>STAC Collections Map</h3>
        <p class="subtitle">Spatial extents of cataloged datasets</p>

        <div class="control-group">
            <label for="search-input">Search Collections:</label>
            <input type="text" id="search-input" placeholder="Filter by name..."
                   onkeyup="filterCollections()">
        </div>

        <div class="control-group">
            <label>Collections:</label>
            <div id="collection-list" class="collection-list">
                <div class="loading-message">Loading collections...</div>
            </div>
        </div>

        <div class="button-group">
            <button onclick="showAllCollections()" class="btn-primary">
                Show All
            </button>
            <button onclick="hideAllCollections()" class="btn-secondary">
                Hide All
            </button>
            <button onclick="zoomToAll()" class="btn-secondary">
                Zoom to All
            </button>
        </div>

        <div class="stats-section">
            <div id="status" class="status-text">Loading...</div>
            <div id="stats" class="stats-text"></div>
        </div>

        <div class="legend">
            <div class="legend-title">Legend</div>
            <div class="legend-item">
                <span class="legend-color" style="background: #0071BC;"></span>
                <span>Visible Collection</span>
            </div>
            <div class="legend-item">
                <span class="legend-color" style="background: #FFC14D;"></span>
                <span>Selected/Hovered</span>
            </div>
        </div>
    </div>

    <div class="spinner" id="spinner">
        <div class="spinner-icon"></div>
        <div class="spinner-text">Loading STAC collections...</div>
    </div>

    <script>
        {self._generate_javascript()}
    </script>
</body>
</html>"""

    def _generate_navbar(self) -> str:
        """Generate top navigation bar."""
        return f"""
        <nav class="navbar">
            <a href="/api/interface/home" class="nav-brand">
                Geospatial API v{__version__}
            </a>
            <div class="nav-links">
                <a href="/api/interface/stac">STAC Browser</a>
                <a href="/api/interface/map">OGC Map</a>
                <a href="/api/interface/docs">API Docs</a>
            </div>
        </nav>"""

    def _generate_css(self) -> str:
        """Generate CSS styles."""
        return """
        /* Reset and base styles */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Open Sans", Arial, sans-serif;
            font-size: 14px;
        }

        /* Navbar */
        .navbar {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 52px;
            background: white;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            border-bottom: 3px solid #0071BC;
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
            gap: 24px;
        }

        .nav-links a {
            color: #0071BC;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
        }

        .nav-links a:hover {
            color: #00A3DA;
        }

        /* Map container */
        #map {
            position: absolute;
            top: 52px;
            bottom: 0;
            left: 0;
            right: 0;
        }

        /* Control panel */
        .control-panel {
            position: absolute;
            top: 62px;
            right: 10px;
            background: white;
            padding: 20px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 1000;
            width: 320px;
            max-height: calc(100vh - 80px);
            overflow-y: auto;
            border-left: 4px solid #0071BC;
        }

        .control-panel h3 {
            color: #053657;
            margin-bottom: 4px;
            font-size: 18px;
        }

        .control-panel .subtitle {
            color: #626F86;
            font-size: 12px;
            margin-bottom: 16px;
        }

        .control-group {
            margin-bottom: 16px;
        }

        .control-group label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .control-group input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            font-size: 14px;
        }

        .control-group input:focus {
            outline: none;
            border-color: #0071BC;
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }

        /* Collection list */
        .collection-list {
            max-height: 280px;
            overflow-y: auto;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            background: #f8f9fa;
        }

        .collection-item {
            display: flex;
            align-items: center;
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
            cursor: pointer;
            transition: background 0.2s;
        }

        .collection-item:last-child {
            border-bottom: none;
        }

        .collection-item:hover {
            background: #e9ecef;
        }

        .collection-item.hidden-layer {
            opacity: 0.5;
        }

        .collection-item input[type="checkbox"] {
            margin-right: 10px;
            width: 16px;
            height: 16px;
            cursor: pointer;
        }

        .collection-item .collection-name {
            flex: 1;
            font-size: 13px;
            color: #053657;
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .collection-item .collection-count {
            font-size: 11px;
            color: #626F86;
            background: #e9ecef;
            padding: 2px 8px;
            border-radius: 10px;
            margin-left: 8px;
        }

        .collection-item .zoom-btn {
            margin-left: 8px;
            padding: 4px 8px;
            background: transparent;
            border: 1px solid #0071BC;
            color: #0071BC;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
            opacity: 0;
            transition: opacity 0.2s;
        }

        .collection-item:hover .zoom-btn {
            opacity: 1;
        }

        .collection-item .zoom-btn:hover {
            background: #0071BC;
            color: white;
        }

        .loading-message, .empty-message {
            padding: 20px;
            text-align: center;
            color: #626F86;
            font-size: 13px;
        }

        /* Buttons */
        .button-group {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
        }

        .btn-primary, .btn-secondary {
            flex: 1;
            padding: 10px 12px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            border: none;
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

        .btn-secondary:hover {
            background: #e9ecef;
        }

        /* Stats section */
        .stats-section {
            padding: 12px;
            background: #f8f9fa;
            border-radius: 4px;
            margin-bottom: 16px;
        }

        .status-text {
            font-size: 13px;
            color: #053657;
            font-weight: 500;
        }

        .status-text.error {
            color: #c53030;
        }

        .stats-text {
            font-size: 12px;
            color: #626F86;
            margin-top: 4px;
        }

        /* Legend */
        .legend {
            border-top: 1px solid #e9ecef;
            padding-top: 12px;
        }

        .legend-title {
            font-size: 11px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: #053657;
            margin-bottom: 4px;
        }

        .legend-color {
            width: 16px;
            height: 16px;
            border-radius: 3px;
            border: 1px solid rgba(0,0,0,0.2);
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
            font-size: 14px;
            color: #053657;
        }

        /* Leaflet popup customization */
        .leaflet-popup-content-wrapper {
            border-radius: 4px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        }

        .leaflet-popup-content {
            margin: 12px 16px;
            font-family: "Open Sans", Arial, sans-serif;
            min-width: 280px;
        }

        .popup-header {
            font-weight: 700;
            font-size: 16px;
            color: #053657;
            padding-bottom: 10px;
            margin-bottom: 10px;
            border-bottom: 2px solid #0071BC;
        }

        .popup-section {
            margin-bottom: 10px;
        }

        .popup-label {
            font-size: 11px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            margin-bottom: 2px;
        }

        .popup-value {
            font-size: 13px;
            color: #053657;
            line-height: 1.4;
        }

        .popup-value.mono {
            font-family: monospace;
            font-size: 11px;
            background: #f8f9fa;
            padding: 4px 6px;
            border-radius: 3px;
        }

        .popup-description {
            font-size: 12px;
            color: #626F86;
            line-height: 1.5;
            max-height: 60px;
            overflow-y: auto;
        }

        .popup-links {
            margin-top: 12px;
            padding-top: 10px;
            border-top: 1px solid #e9ecef;
            display: flex;
            gap: 10px;
        }

        .popup-links a {
            font-size: 12px;
            color: #0071BC;
            text-decoration: none;
            font-weight: 600;
        }

        .popup-links a:hover {
            color: #00A3DA;
            text-decoration: underline;
        }

        /* Badge styles */
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }

        .badge.items {
            background: #e3f2fd;
            color: #1565c0;
        }

        .badge.no-items {
            background: #fff3e0;
            color: #ef6c00;
        }
        """

    def _generate_javascript(self) -> str:
        """Generate JavaScript for map interaction."""
        return """
        // State
        const API_BASE_URL = window.location.origin;
        let map = null;
        let allCollections = [];
        let collectionLayers = {};  // { collectionId: L.rectangle }
        let allBounds = null;

        // Color palette for collections
        const COLORS = [
            '#0071BC', '#00A3DA', '#245AAD', '#0891b2',
            '#059669', '#7c3aed', '#db2777', '#ea580c'
        ];

        // Initialize map
        function initMap() {
            map = L.map('map').setView([20, 0], 2);

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 19
            }).addTo(map);
        }

        // Show/hide spinner
        function showSpinner() {
            document.getElementById('spinner').classList.add('active');
        }

        function hideSpinner() {
            document.getElementById('spinner').classList.remove('active');
        }

        // Set status message
        function setStatus(message, isError = false) {
            const el = document.getElementById('status');
            el.textContent = message;
            el.className = 'status-text' + (isError ? ' error' : '');
        }

        // Load collections from API
        async function loadCollections() {
            showSpinner();
            setStatus('Loading collections...');

            try {
                const response = await fetch(`${API_BASE_URL}/api/stac/collections`);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();
                allCollections = data.collections || [];

                // Filter to collections with valid bbox
                const collectionsWithBbox = allCollections.filter(c =>
                    c.extent?.spatial?.bbox &&
                    c.extent.spatial.bbox[0] &&
                    c.extent.spatial.bbox[0].length === 4
                );

                hideSpinner();

                if (collectionsWithBbox.length === 0) {
                    setStatus('No collections with spatial extent found');
                    renderCollectionList([]);
                    return;
                }

                setStatus(`${collectionsWithBbox.length} collections loaded`);
                document.getElementById('stats').textContent =
                    `${allCollections.length} total, ${collectionsWithBbox.length} with bbox`;

                // Render collection bboxes on map
                renderCollectionBboxes(collectionsWithBbox);

                // Render collection list in sidebar
                renderCollectionList(collectionsWithBbox);

                // Zoom to all collections
                if (allBounds) {
                    map.fitBounds(allBounds, { padding: [50, 50] });
                }

            } catch (error) {
                hideSpinner();
                console.error('Error loading collections:', error);
                setStatus(`Error: ${error.message}`, true);
                renderCollectionList([]);
            }
        }

        // Render collection bboxes on map
        function renderCollectionBboxes(collections) {
            // Clear existing layers
            Object.values(collectionLayers).forEach(layer => {
                map.removeLayer(layer);
            });
            collectionLayers = {};
            allBounds = null;

            collections.forEach((collection, index) => {
                const bbox = collection.extent.spatial.bbox[0];
                // bbox format: [min_lon, min_lat, max_lon, max_lat]
                const bounds = L.latLngBounds(
                    [bbox[1], bbox[0]],  // southwest [lat, lon]
                    [bbox[3], bbox[2]]   // northeast [lat, lon]
                );

                // Expand allBounds
                if (!allBounds) {
                    allBounds = bounds;
                } else {
                    allBounds.extend(bounds);
                }

                // Create rectangle with color from palette
                const color = COLORS[index % COLORS.length];
                const rectangle = L.rectangle(bounds, {
                    color: color,
                    weight: 2,
                    fillOpacity: 0.15,
                    fillColor: color
                });

                // Bind popup
                rectangle.bindPopup(createPopupContent(collection, bbox), {
                    maxWidth: 350
                });

                // Hover effects
                rectangle.on('mouseover', function() {
                    this.setStyle({
                        weight: 3,
                        fillOpacity: 0.35,
                        color: '#FFC14D'
                    });
                    this.bringToFront();
                });

                rectangle.on('mouseout', function() {
                    this.setStyle({
                        weight: 2,
                        fillOpacity: 0.15,
                        color: color
                    });
                });

                rectangle.addTo(map);
                collectionLayers[collection.id] = rectangle;
            });
        }

        // Create popup HTML content
        function createPopupContent(collection, bbox) {
            const title = collection.title || collection.id;
            const description = collection.description || 'No description';
            const itemCount = collection.summaries?.total_items ||
                             collection.item_count ||
                             '?';

            // Format temporal extent
            let temporalStr = 'Not specified';
            if (collection.extent?.temporal?.interval) {
                const interval = collection.extent.temporal.interval[0];
                const start = interval[0] ? interval[0].split('T')[0] : 'open';
                const end = interval[1] ? interval[1].split('T')[0] : 'present';
                temporalStr = `${start} to ${end}`;
            }

            // Format bbox
            const bboxStr = `[${bbox.map(v => v.toFixed(4)).join(', ')}]`;

            return `
                <div class="popup-header">${title}</div>

                <div class="popup-section">
                    <div class="popup-label">Collection ID</div>
                    <div class="popup-value mono">${collection.id}</div>
                </div>

                <div class="popup-section">
                    <div class="popup-label">Description</div>
                    <div class="popup-description">${description}</div>
                </div>

                <div class="popup-section">
                    <div class="popup-label">Items</div>
                    <div class="popup-value">${itemCount.toLocaleString()} items</div>
                </div>

                <div class="popup-section">
                    <div class="popup-label">Temporal Extent</div>
                    <div class="popup-value">${temporalStr}</div>
                </div>

                <div class="popup-section">
                    <div class="popup-label">Bounding Box</div>
                    <div class="popup-value mono">${bboxStr}</div>
                </div>

                <div class="popup-links">
                    <a href="/api/interface/stac?collection=${collection.id}">View in STAC Browser</a>
                    <a href="/api/stac/collections/${collection.id}" target="_blank">JSON</a>
                </div>
            `;
        }

        // Render collection list in sidebar
        function renderCollectionList(collections) {
            const listEl = document.getElementById('collection-list');

            if (collections.length === 0) {
                listEl.innerHTML = '<div class="empty-message">No collections found</div>';
                return;
            }

            listEl.innerHTML = collections.map(collection => {
                const itemCount = collection.summaries?.total_items ||
                                 collection.item_count || 0;
                const name = collection.title || collection.id;

                return `
                    <div class="collection-item" data-id="${collection.id}">
                        <input type="checkbox" checked
                               onchange="toggleCollection('${collection.id}', this.checked)">
                        <span class="collection-name" title="${collection.id}">${name}</span>
                        <span class="collection-count">${itemCount}</span>
                        <button class="zoom-btn" onclick="zoomToCollection('${collection.id}', event)">
                            Zoom
                        </button>
                    </div>
                `;
            }).join('');
        }

        // Filter collections by search term
        function filterCollections() {
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            const items = document.querySelectorAll('.collection-item');

            items.forEach(item => {
                const name = item.querySelector('.collection-name').textContent.toLowerCase();
                const id = item.dataset.id.toLowerCase();
                const matches = name.includes(searchTerm) || id.includes(searchTerm);
                item.style.display = matches ? 'flex' : 'none';
            });
        }

        // Toggle collection visibility
        function toggleCollection(collectionId, visible) {
            const layer = collectionLayers[collectionId];
            if (!layer) return;

            if (visible) {
                layer.addTo(map);
            } else {
                map.removeLayer(layer);
            }

            // Update item styling
            const item = document.querySelector(`.collection-item[data-id="${collectionId}"]`);
            if (item) {
                item.classList.toggle('hidden-layer', !visible);
            }
        }

        // Zoom to specific collection
        function zoomToCollection(collectionId, event) {
            if (event) event.stopPropagation();

            const layer = collectionLayers[collectionId];
            if (layer) {
                map.fitBounds(layer.getBounds(), { padding: [50, 50] });
                layer.openPopup();
            }
        }

        // Show all collections
        function showAllCollections() {
            Object.entries(collectionLayers).forEach(([id, layer]) => {
                layer.addTo(map);
            });

            // Check all checkboxes
            document.querySelectorAll('.collection-item input[type="checkbox"]').forEach(cb => {
                cb.checked = true;
            });
            document.querySelectorAll('.collection-item').forEach(item => {
                item.classList.remove('hidden-layer');
            });
        }

        // Hide all collections
        function hideAllCollections() {
            Object.entries(collectionLayers).forEach(([id, layer]) => {
                map.removeLayer(layer);
            });

            // Uncheck all checkboxes
            document.querySelectorAll('.collection-item input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
            });
            document.querySelectorAll('.collection-item').forEach(item => {
                item.classList.add('hidden-layer');
            });
        }

        // Zoom to all collections
        function zoomToAll() {
            if (allBounds) {
                map.fitBounds(allBounds, { padding: [50, 50] });
            }
        }

        // Initialize on page load
        window.onload = function() {
            initMap();
            loadCollections();
        };
        """
