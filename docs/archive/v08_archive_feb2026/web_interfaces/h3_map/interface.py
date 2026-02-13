"""
H3 Map Viewer Interface.

Interactive Leaflet map for visualizing H3 hexagonal grid cells with
zoom-dependent resolution selection.

Route: /api/interface/h3-map

Features:
    - Zoom-dependent H3 resolution (zoom out = coarser, zoom in = finer)
    - Query cells from h3.cells table within viewport
    - Render hexagons with h3-js library
    - Click to see cell details and stats
    - Resolution indicator showing current H3 level
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('h3-map')
class H3MapInterface(BaseInterface):
    """
    H3 Map Viewer with zoom-dependent resolution.

    Maps Leaflet zoom levels to H3 resolutions for appropriate detail.
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate H3 Map Viewer HTML."""
        return self._generate_full_page()

    def _generate_full_page(self) -> str:
        """Generate complete HTML page with Leaflet and h3-js dependencies."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>H3 Map Viewer</title>

    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />

    <style>
        {self._generate_css()}
    </style>
</head>
<body>
    {self._generate_navbar()}
    {self._generate_html_content()}

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <!-- h3-js for hexagon rendering -->
    <script src="https://unpkg.com/h3-js@4.1.0/dist/h3-js.umd.js"></script>

    <script>
        {self._generate_js()}
    </script>
</body>
</html>"""

    def _generate_navbar(self) -> str:
        """Generate navigation bar."""
        return """
        <nav class="map-nav">
            <a href="/api/interface/home" class="nav-brand">Geospatial API</a>
            <div class="nav-links">
                <a href="/api/interface/stac">STAC</a>
                <a href="/api/interface/map">Vector Map</a>
                <a href="/api/interface/h3">H3 Status</a>
                <a href="/api/interface/h3-map" class="active">H3 Map</a>
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
            <h3>H3 Map Viewer</h3>

            <!-- Resolution Indicator -->
            <div class="resolution-indicator">
                <div class="res-label">Current H3 Resolution</div>
                <div class="res-value" id="current-resolution">--</div>
                <div class="res-size" id="resolution-size">--</div>
            </div>

            <!-- Zoom-Resolution Mapping Info -->
            <div class="control-group">
                <label>Auto Resolution</label>
                <div class="toggle-group">
                    <input type="checkbox" id="auto-resolution" checked>
                    <span class="toggle-label">Adjust with zoom</span>
                </div>
            </div>

            <!-- Manual Resolution Override -->
            <div class="control-group" id="manual-res-group">
                <label for="manual-resolution">Manual Resolution</label>
                <select id="manual-resolution" disabled>
                    <option value="2">2 - Continental (86,745 km²)</option>
                    <option value="3">3 - Country (12,393 km²)</option>
                    <option value="4">4 - Metro (1,770 km²)</option>
                    <option value="5">5 - District (252.9 km²)</option>
                    <option value="6">6 - Neighborhood (36.1 km²)</option>
                    <option value="7">7 - Census Block (5.2 km²)</option>
                    <option value="8">8 - City Block (0.74 km²)</option>
                </select>
            </div>

            <!-- Display Options -->
            <div class="control-group">
                <label>Display Options</label>
                <div class="checkbox-group">
                    <label class="checkbox-label">
                        <input type="checkbox" id="show-grid" checked>
                        <span>Show grid overlay</span>
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" id="show-land-only">
                        <span>Land cells only</span>
                    </label>
                    <label class="checkbox-label">
                        <input type="checkbox" id="show-cell-ids">
                        <span>Show cell IDs</span>
                    </label>
                </div>
            </div>

            <!-- Status -->
            <div class="status-section">
                <div id="status" class="status-text">Initializing...</div>
                <div id="cell-count" class="cell-count"></div>
            </div>

            <!-- Legend -->
            <div class="legend">
                <div class="legend-title">Cell Types</div>
                <div class="legend-item">
                    <span class="legend-color" style="background: #0071BC;"></span>
                    <span>Database cells</span>
                </div>
                <div class="legend-item">
                    <span class="legend-color" style="background: rgba(0,113,188,0.2); border: 1px dashed #0071BC;"></span>
                    <span>Grid overlay</span>
                </div>
            </div>
        </div>

        <!-- Cell Info Panel -->
        <div class="cell-info-panel hidden" id="cell-info">
            <div class="cell-info-header">
                <span>Cell Details</span>
                <button onclick="hideCellInfo()">&times;</button>
            </div>
            <div class="cell-info-body" id="cell-info-body">
                <!-- Populated dynamically -->
            </div>
        </div>

        <!-- Loading Spinner -->
        <div class="loading-overlay hidden" id="loading">
            <div class="spinner"></div>
            <div>Loading H3 cells...</div>
        </div>
        """

    def _generate_css(self) -> str:
        """Generate CSS styles."""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Open Sans", Arial, sans-serif;
            background: #f8f9fa;
        }

        /* Navigation */
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

        .nav-brand:hover { color: #0071BC; }

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

        /* Control Panel */
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
            max-height: calc(100vh - 80px);
            overflow-y: auto;
        }

        .control-panel h3 {
            font-size: 18px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
        }

        /* Resolution Indicator */
        .resolution-indicator {
            background: linear-gradient(135deg, #EBF5FF 0%, #DBEAFE 100%);
            border: 2px solid #0071BC;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            margin-bottom: 16px;
        }

        .res-label {
            font-size: 11px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .res-value {
            font-size: 48px;
            font-weight: 700;
            color: #0071BC;
            line-height: 1.2;
        }

        .res-size {
            font-size: 12px;
            color: #053657;
            margin-top: 4px;
        }

        /* Control Groups */
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
            margin-bottom: 6px;
        }

        .control-group select {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            font-size: 13px;
            color: #053657;
            background: white;
        }

        .control-group select:disabled {
            background: #f3f4f6;
            color: #9ca3af;
        }

        .toggle-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .toggle-label {
            font-size: 13px;
            color: #053657;
        }

        .checkbox-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .checkbox-label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #053657;
            cursor: pointer;
        }

        .checkbox-label input {
            cursor: pointer;
        }

        /* Status Section */
        .status-section {
            margin-top: 16px;
            padding-top: 12px;
            border-top: 1px solid #e9ecef;
        }

        .status-text {
            font-size: 13px;
            color: #626F86;
        }

        .status-text.success { color: #10B981; }
        .status-text.error { color: #DC2626; }
        .status-text.loading { color: #0071BC; }

        .cell-count {
            font-size: 12px;
            color: #0071BC;
            font-weight: 600;
            margin-top: 4px;
        }

        /* Legend */
        .legend {
            margin-top: 16px;
            padding-top: 12px;
            border-top: 1px solid #e9ecef;
        }

        .legend-title {
            font-size: 11px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
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
            width: 20px;
            height: 14px;
            border-radius: 2px;
        }

        /* Cell Info Panel */
        .cell-info-panel {
            position: absolute;
            bottom: 20px;
            left: 10px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 1000;
            min-width: 280px;
            max-width: 350px;
            overflow: hidden;
        }

        .cell-info-panel.hidden { display: none; }

        .cell-info-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            background: #0071BC;
            color: white;
            font-weight: 600;
        }

        .cell-info-header button {
            background: none;
            border: none;
            color: white;
            font-size: 20px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
        }

        .cell-info-body {
            padding: 16px;
            max-height: 300px;
            overflow-y: auto;
        }

        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #f0f0f0;
        }

        .info-row:last-child { border-bottom: none; }

        .info-label {
            font-size: 11px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
        }

        .info-value {
            font-size: 13px;
            color: #053657;
            font-weight: 500;
            font-family: monospace;
        }

        /* Loading Overlay */
        .loading-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.9);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 2000;
            gap: 12px;
            font-size: 14px;
            color: #626F86;
        }

        .loading-overlay.hidden { display: none; }

        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid #e9ecef;
            border-top-color: #0071BC;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Leaflet Popup */
        .leaflet-popup-content {
            margin: 8px 12px;
        }

        .h3-popup-title {
            font-weight: 700;
            color: #053657;
            font-size: 12px;
            margin-bottom: 8px;
            font-family: monospace;
        }

        .h3-popup-row {
            font-size: 11px;
            color: #626F86;
            padding: 2px 0;
        }
        """

    def _generate_js(self) -> str:
        """Generate JavaScript code."""
        return """
        // H3 Resolution metadata
        const H3_RES_INFO = {
            2: { name: 'Continental', area: '86,745 km²', edge: '158 km' },
            3: { name: 'Country', area: '12,393 km²', edge: '60 km' },
            4: { name: 'Metro', area: '1,770 km²', edge: '23 km' },
            5: { name: 'District', area: '252.9 km²', edge: '8.5 km' },
            6: { name: 'Neighborhood', area: '36.1 km²', edge: '3.2 km' },
            7: { name: 'Census Block', area: '5.2 km²', edge: '1.2 km' },
            8: { name: 'City Block', area: '0.74 km²', edge: '0.46 km' }
        };

        // Zoom to H3 resolution mapping
        const ZOOM_TO_RES = {
            0: 2, 1: 2, 2: 2, 3: 2,       // Zoom 0-3 -> Res 2
            4: 3, 5: 3,                    // Zoom 4-5 -> Res 3
            6: 4, 7: 4,                    // Zoom 6-7 -> Res 4
            8: 5, 9: 5,                    // Zoom 8-9 -> Res 5
            10: 6, 11: 6,                  // Zoom 10-11 -> Res 6
            12: 7, 13: 7,                  // Zoom 12-13 -> Res 7
            14: 8, 15: 8, 16: 8, 17: 8, 18: 8  // Zoom 14+ -> Res 8
        };

        // State
        let map = null;
        let gridLayer = null;
        let dbCellsLayer = null;
        let currentResolution = 4;
        let dbCells = new Set();  // H3 indices from database
        let updateTimeout = null;

        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            initMap();
            setupEventListeners();
            loadDbCells();
        });

        function initMap() {
            map = L.map('map').setView([-1.9, 29.8], 7);  // Rwanda center

            L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; OpenStreetMap, &copy; CARTO',
                maxZoom: 18
            }).addTo(map);

            // Initialize layers
            gridLayer = L.layerGroup().addTo(map);
            dbCellsLayer = L.layerGroup().addTo(map);

            // Update on zoom/pan
            map.on('zoomend', onMapMove);
            map.on('moveend', onMapMove);

            setStatus('Map initialized', 'success');
        }

        function setupEventListeners() {
            document.getElementById('auto-resolution').addEventListener('change', function() {
                const manualSelect = document.getElementById('manual-resolution');
                manualSelect.disabled = this.checked;
                if (this.checked) {
                    updateResolution();
                } else {
                    currentResolution = parseInt(manualSelect.value);
                    updateDisplay();
                }
            });

            document.getElementById('manual-resolution').addEventListener('change', function() {
                if (!document.getElementById('auto-resolution').checked) {
                    currentResolution = parseInt(this.value);
                    updateDisplay();
                }
            });

            document.getElementById('show-grid').addEventListener('change', function() {
                if (this.checked) {
                    gridLayer.addTo(map);
                } else {
                    map.removeLayer(gridLayer);
                }
                updateDisplay();
            });

            document.getElementById('show-land-only').addEventListener('change', updateDisplay);
            document.getElementById('show-cell-ids').addEventListener('change', updateDisplay);
        }

        function onMapMove() {
            // Debounce updates
            if (updateTimeout) clearTimeout(updateTimeout);
            updateTimeout = setTimeout(() => {
                if (document.getElementById('auto-resolution').checked) {
                    updateResolution();
                }
                updateDisplay();
            }, 200);
        }

        function updateResolution() {
            const zoom = map.getZoom();
            const newRes = ZOOM_TO_RES[Math.min(zoom, 18)] || 8;

            if (newRes !== currentResolution) {
                currentResolution = newRes;
                updateResolutionIndicator();
            }
        }

        function updateResolutionIndicator() {
            const info = H3_RES_INFO[currentResolution];
            document.getElementById('current-resolution').textContent = currentResolution;
            document.getElementById('resolution-size').textContent =
                `${info.name} (~${info.area})`;
        }

        async function loadDbCells() {
            try {
                setStatus('Loading database cells...', 'loading');

                // Get cell counts per resolution
                const response = await fetch('/api/h3/stats');
                const data = await response.json();

                // For now, we'll query cells when needed
                // In a full implementation, we'd load cell IDs by viewport
                setStatus('Ready - zoom to see cells', 'success');

            } catch (error) {
                console.error('Error loading cells:', error);
                setStatus('Could not load cells', 'error');
            }
        }

        function updateDisplay() {
            updateResolutionIndicator();
            renderGrid();
        }

        function renderGrid() {
            // Clear existing
            gridLayer.clearLayers();
            dbCellsLayer.clearLayers();

            const bounds = map.getBounds();
            const showGrid = document.getElementById('show-grid').checked;
            const showIds = document.getElementById('show-cell-ids').checked;

            // Get H3 cells covering the viewport
            const polygon = [
                [bounds.getSouth(), bounds.getWest()],
                [bounds.getSouth(), bounds.getEast()],
                [bounds.getNorth(), bounds.getEast()],
                [bounds.getNorth(), bounds.getWest()],
                [bounds.getSouth(), bounds.getWest()]
            ];

            try {
                // Convert to GeoJSON polygon format for h3
                const geoJsonPoly = {
                    type: 'Polygon',
                    coordinates: [[
                        [bounds.getWest(), bounds.getSouth()],
                        [bounds.getEast(), bounds.getSouth()],
                        [bounds.getEast(), bounds.getNorth()],
                        [bounds.getWest(), bounds.getNorth()],
                        [bounds.getWest(), bounds.getSouth()]
                    ]]
                };

                // Get H3 cells that cover the viewport
                const cells = h3.polygonToCells(geoJsonPoly, currentResolution);

                // Limit to prevent browser freeze
                const maxCells = 5000;
                const displayCells = cells.slice(0, maxCells);

                let cellCount = 0;

                displayCells.forEach(h3Index => {
                    // Get cell boundary
                    const boundary = h3.cellToBoundary(h3Index, true);

                    // Create polygon (GeoJSON format is [lng, lat])
                    const latLngs = boundary.map(coord => [coord[1], coord[0]]);

                    if (showGrid) {
                        // Grid overlay - light dashed
                        const gridHex = L.polygon(latLngs, {
                            color: '#0071BC',
                            weight: 1,
                            fillOpacity: 0.05,
                            fillColor: '#0071BC',
                            dashArray: '3, 3'
                        });

                        gridHex.on('click', () => showCellInfo(h3Index));
                        gridLayer.addLayer(gridHex);
                    }

                    // Add cell ID label if enabled
                    if (showIds && map.getZoom() >= 10) {
                        const center = h3.cellToLatLng(h3Index);
                        const shortId = h3Index.slice(-6);
                        const marker = L.marker([center[0], center[1]], {
                            icon: L.divIcon({
                                className: 'h3-label',
                                html: `<div style="font-size:9px;color:#053657;white-space:nowrap;">${shortId}</div>`,
                                iconSize: [50, 12]
                            })
                        });
                        gridLayer.addLayer(marker);
                    }

                    cellCount++;
                });

                const truncated = cells.length > maxCells ? ` (showing ${maxCells} of ${cells.length})` : '';
                document.getElementById('cell-count').textContent =
                    `${cellCount.toLocaleString()} cells in view${truncated}`;

            } catch (error) {
                console.error('Error rendering grid:', error);
                setStatus('Error rendering cells', 'error');
            }
        }

        function showCellInfo(h3Index) {
            const panel = document.getElementById('cell-info');
            const body = document.getElementById('cell-info-body');

            const res = h3.getResolution(h3Index);
            const center = h3.cellToLatLng(h3Index);
            const area = h3.cellArea(h3Index, 'km2');
            const parent = res > 0 ? h3.cellToParent(h3Index, res - 1) : 'N/A';
            const children = res < 15 ? h3.cellToChildren(h3Index, res + 1).length : 'N/A';
            const isPentagon = h3.isPentagon(h3Index);

            body.innerHTML = `
                <div class="info-row">
                    <span class="info-label">H3 Index</span>
                    <span class="info-value">${h3Index}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Resolution</span>
                    <span class="info-value">${res}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Center</span>
                    <span class="info-value">${center[0].toFixed(4)}, ${center[1].toFixed(4)}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Area</span>
                    <span class="info-value">${area.toFixed(2)} km²</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Parent Cell</span>
                    <span class="info-value">${parent}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Children</span>
                    <span class="info-value">${children} cells</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Pentagon</span>
                    <span class="info-value">${isPentagon ? 'Yes' : 'No'}</span>
                </div>
            `;

            panel.classList.remove('hidden');
        }

        function hideCellInfo() {
            document.getElementById('cell-info').classList.add('hidden');
        }

        function setStatus(message, type = '') {
            const el = document.getElementById('status');
            el.textContent = message;
            el.className = 'status-text' + (type ? ' ' + type : '');
        }
        """


# Export
__all__ = ['H3MapInterface']
