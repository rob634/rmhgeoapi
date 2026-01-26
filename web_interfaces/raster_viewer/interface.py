# ============================================================================
# CLAUDE CONTEXT - TITILER RASTER VIEWER INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - COG Preview with Band Selection
# PURPOSE: Leaflet interface for TiTiler COG viewing with RGB band controls
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: RasterViewerInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
TiTiler Raster Viewer Interface.

Interactive Leaflet map for viewing Cloud Optimized GeoTIFFs (COGs) via TiTiler.
Supports RGB band selection, rescaling, colormaps, and point queries.

Features:
    - COG URL input or file browser
    - Auto-fetch band info from TiTiler /cog/info
    - RGB band selector (assign bands to R, G, B channels)
    - Single-band mode with colormap selection
    - Rescale controls (auto from statistics or manual)
    - Point query on map click (all band values)
    - QA section with Approve/Reject buttons

Route: /api/interface/raster-viewer
"""

import os
import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

from config import __version__


@InterfaceRegistry.register('raster-viewer')
class RasterViewerInterface(BaseInterface):
    """
    TiTiler Raster Viewer Interface.

    Displays COGs on Leaflet map via TiTiler XYZ tiles with
    interactive band selection and visualization controls.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate full-page raster viewer.

        Query Parameters:
            url: Optional COG URL to load on page open

        Args:
            request: Azure Functions HTTP request

        Returns:
            Complete HTML page string
        """
        # Get optional COG URL from query params
        cog_url = request.params.get('url', '')

        return self._generate_full_page(cog_url)

    def _generate_full_page(self, initial_url: str = '') -> str:
        """Generate complete HTML document with Leaflet map and controls."""
        titiler_url = os.getenv('TITILER_BASE_URL', 'https://titiler.xyz')

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raster Viewer - Geospatial API</title>
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
        <h3>Raster Viewer</h3>
        <p class="subtitle">TiTiler COG Visualization</p>

        <!-- COG URL Input -->
        <div class="control-group">
            <label for="cog-url">COG URL:</label>
            <input type="text" id="cog-url" placeholder="https://storage.blob.../file.tif"
                   value="{initial_url}">
            <button onclick="loadCogInfo()" class="btn-primary btn-small" style="margin-top: 8px;">
                Load COG
            </button>
        </div>

        <!-- COG Info Section (hidden until loaded) -->
        <div id="cog-info-section" class="info-section" style="display: none;">
            <div class="section-header">COG Info</div>
            <div id="cog-info-content"></div>
            <button onclick="zoomToExtent()" class="btn-zoom-extent" style="margin-top: 10px;">
                Zoom to Data Extent
            </button>
        </div>

        <!-- Band Selection (hidden until loaded) -->
        <div id="band-section" class="control-group" style="display: none;">
            <label>RGB Band Selection:</label>
            <div class="band-selector">
                <div class="band-row">
                    <span class="band-label" style="color: #e53935;">R:</span>
                    <select id="band-r" onchange="updateTileLayer()"></select>
                </div>
                <div class="band-row">
                    <span class="band-label" style="color: #43a047;">G:</span>
                    <select id="band-g" onchange="updateTileLayer()"></select>
                </div>
                <div class="band-row">
                    <span class="band-label" style="color: #1e88e5;">B:</span>
                    <select id="band-b" onchange="updateTileLayer()"></select>
                </div>
            </div>

            <!-- Quick Presets -->
            <div class="preset-buttons">
                <button onclick="setPreset('rgb')" class="btn-preset">RGB (1,2,3)</button>
                <button onclick="setPreset('nir')" class="btn-preset">NIR (4,3,2)</button>
                <button onclick="setPreset('gray')" class="btn-preset">Gray (1)</button>
            </div>
        </div>

        <!-- Rescale Controls -->
        <div id="rescale-section" class="control-group" style="display: none;">
            <label>Rescale:</label>
            <div class="rescale-controls">
                <label class="radio-label">
                    <input type="radio" name="rescale-mode" value="auto" checked
                           onchange="updateTileLayer()"> Auto
                </label>
                <label class="radio-label">
                    <input type="radio" name="rescale-mode" value="manual"
                           onchange="updateTileLayer()"> Manual
                </label>
            </div>
            <div id="manual-rescale" class="manual-rescale" style="display: none;">
                <div class="rescale-row">
                    <label>Min:</label>
                    <input type="number" id="rescale-min" value="0" onchange="updateTileLayer()">
                </div>
                <div class="rescale-row">
                    <label>Max:</label>
                    <input type="number" id="rescale-max" value="255" onchange="updateTileLayer()">
                </div>
            </div>
        </div>

        <!-- Colormap (for single-band) -->
        <div id="colormap-section" class="control-group" style="display: none;">
            <label for="colormap">Colormap (single-band):</label>
            <select id="colormap" onchange="updateTileLayer()">
                <option value="">None (grayscale)</option>
                <option value="viridis">Viridis</option>
                <option value="plasma">Plasma</option>
                <option value="inferno">Inferno</option>
                <option value="magma">Magma</option>
                <option value="terrain">Terrain</option>
                <option value="blues">Blues</option>
                <option value="reds">Reds</option>
                <option value="greens">Greens</option>
                <option value="ylgn">Yellow-Green</option>
                <option value="rdylgn">Red-Yellow-Green</option>
                <option value="spectral">Spectral</option>
                <option value="coolwarm">Cool-Warm</option>
            </select>
        </div>

        <!-- Point Query Display -->
        <div id="point-section" class="info-section" style="display: none;">
            <div class="section-header">Point Query</div>
            <div id="point-info-content">Click map to query values</div>
        </div>

        <!-- Status -->
        <div class="stats-section">
            <div id="status" class="status-text">Enter a COG URL to begin</div>
        </div>

        <!-- QA Section -->
        <div id="qa-section" class="qa-section" style="display: none;">
            <div class="section-header">Data Curator QA</div>
            <textarea class="qa-input" id="qa-notes" placeholder="QA notes (optional)..." rows="3"></textarea>
            <div class="qa-buttons">
                <button class="approve-button" onclick="handleApprove()">Approve</button>
                <button class="reject-button" onclick="handleReject()">Reject</button>
            </div>
        </div>
    </div>

    <!-- Spinner -->
    <div class="spinner" id="spinner">
        <div class="spinner-icon"></div>
        <div class="spinner-text">Loading COG info...</div>
    </div>

    <script>
        {self._generate_javascript(titiler_url)}
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
                <a href="/api/interface/stac">STAC</a>
                <a href="/api/interface/map">Vector Map</a>
                <a href="/api/interface/stac-map">STAC Map</a>
                <a href="/api/interface/gallery">Gallery</a>
            </div>
        </nav>"""

    def _generate_css(self) -> str:
        """Generate CSS styles."""
        return """
        /* Reset and base */
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: "Open Sans", Arial, sans-serif;
            font-size: 14px;
        }

        /* Navbar */
        .navbar {
            position: absolute;
            top: 0; left: 0; right: 0;
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

        .nav-brand:hover { color: #0071BC; }

        .nav-links { display: flex; gap: 24px; }

        .nav-links a {
            color: #0071BC;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
        }

        .nav-links a:hover { color: #00A3DA; }

        /* Map */
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

        .control-group input[type="text"],
        .control-group input[type="number"],
        .control-group select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            font-size: 14px;
        }

        .control-group input:focus,
        .control-group select:focus {
            outline: none;
            border-color: #0071BC;
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }

        /* Band selector */
        .band-selector {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 4px;
        }

        .band-row {
            display: flex;
            align-items: center;
            margin-bottom: 8px;
        }

        .band-row:last-child { margin-bottom: 0; }

        .band-label {
            font-weight: 700;
            font-size: 14px;
            width: 24px;
        }

        .band-row select {
            flex: 1;
            padding: 6px 10px;
            font-size: 13px;
        }

        .preset-buttons {
            display: flex;
            gap: 6px;
            margin-top: 10px;
        }

        .btn-preset {
            flex: 1;
            padding: 6px 8px;
            font-size: 11px;
            background: #e9ecef;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            color: #053657;
        }

        .btn-preset:hover {
            background: #dee2e6;
        }

        /* Rescale controls */
        .rescale-controls {
            display: flex;
            gap: 16px;
            margin-bottom: 8px;
        }

        .radio-label {
            display: flex;
            align-items: center;
            gap: 4px;
            font-size: 13px;
            cursor: pointer;
        }

        .manual-rescale {
            display: flex;
            gap: 12px;
        }

        .rescale-row {
            flex: 1;
        }

        .rescale-row label {
            font-size: 11px;
            margin-bottom: 4px;
        }

        .rescale-row input {
            width: 100%;
            padding: 6px 8px;
        }

        /* Info sections */
        .info-section {
            background: #f8f9fa;
            border-radius: 4px;
            padding: 12px;
            margin-bottom: 16px;
        }

        .section-header {
            font-size: 12px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid #e9ecef;
        }

        .info-row {
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            margin-bottom: 4px;
        }

        .info-label { color: #626F86; }
        .info-value { color: #053657; font-weight: 500; }
        .info-value.mono {
            font-family: monospace;
            font-size: 11px;
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

        .status-text.error { color: #c53030; }
        .status-text.success { color: #2f855a; }

        /* QA section */
        .qa-section {
            border-top: 1px solid #e9ecef;
            padding-top: 16px;
        }

        .qa-input {
            width: 100%;
            padding: 10px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            font-size: 13px;
            font-family: inherit;
            resize: vertical;
            margin-bottom: 10px;
        }

        .qa-buttons {
            display: flex;
            gap: 8px;
        }

        .approve-button, .reject-button {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
        }

        .approve-button {
            background: #48bb78;
            color: white;
        }

        .approve-button:hover { background: #38a169; }

        .reject-button {
            background: #f56565;
            color: white;
        }

        .reject-button:hover { background: #e53e3e; }

        /* Buttons */
        .btn-primary {
            background: #0071BC;
            color: white;
            padding: 10px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            width: 100%;
        }

        .btn-primary:hover { background: #00A3DA; }

        .btn-small {
            padding: 8px 12px;
            font-size: 12px;
        }

        .btn-zoom-extent {
            width: 100%;
            padding: 8px 12px;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
        }

        .btn-zoom-extent:hover {
            background: #38a169;
        }

        /* Spinner */
        .spinner {
            position: fixed;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            z-index: 2000;
            background: white;
            padding: 30px 40px;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.2);
            display: none;
            text-align: center;
        }

        .spinner.active { display: block; }

        .spinner-icon {
            border: 4px solid #e9ecef;
            border-top: 4px solid #0071BC;
            border-radius: 50%;
            width: 40px; height: 40px;
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

        /* Point info */
        .point-coords {
            font-family: monospace;
            font-size: 12px;
            background: #e9ecef;
            padding: 4px 8px;
            border-radius: 3px;
            margin-bottom: 8px;
        }

        .band-values {
            font-size: 12px;
        }

        .band-value-row {
            display: flex;
            justify-content: space-between;
            padding: 3px 0;
            border-bottom: 1px solid #e9ecef;
        }

        .band-value-row:last-child { border-bottom: none; }

        /* Leaflet popup */
        .leaflet-popup-content-wrapper {
            border-radius: 4px;
        }

        .leaflet-popup-content {
            margin: 10px 14px;
            font-family: "Open Sans", Arial, sans-serif;
        }
        """

    def _generate_javascript(self, titiler_url: str) -> str:
        """Generate JavaScript for map interaction."""
        return f"""
        // Configuration
        const TITILER_URL = '{titiler_url}';
        const API_BASE = window.location.origin;

        // State
        let map = null;
        let tileLayer = null;
        let cogInfo = null;
        let cogStats = null;
        let currentCogUrl = '';

        // Initialize map
        function initMap() {{
            map = L.map('map').setView([20, 0], 2);

            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 19
            }}).addTo(map);

            // Click handler for point query
            map.on('click', handleMapClick);
        }}

        // Show/hide spinner
        function showSpinner(text) {{
            document.querySelector('.spinner-text').textContent = text || 'Loading...';
            document.getElementById('spinner').classList.add('active');
        }}

        function hideSpinner() {{
            document.getElementById('spinner').classList.remove('active');
        }}

        // Set status
        function setStatus(message, type = '') {{
            const el = document.getElementById('status');
            el.textContent = message;
            el.className = 'status-text' + (type ? ' ' + type : '');
        }}

        // Load COG info from TiTiler
        async function loadCogInfo() {{
            const urlInput = document.getElementById('cog-url');
            const cogUrl = urlInput.value.trim();

            if (!cogUrl) {{
                setStatus('Please enter a COG URL', 'error');
                return;
            }}

            currentCogUrl = cogUrl;
            showSpinner('Loading COG info...');

            try {{
                // Fetch COG info
                const infoUrl = `${{TITILER_URL}}/cog/info?url=${{encodeURIComponent(cogUrl)}}`;
                const infoResp = await fetch(infoUrl);

                if (!infoResp.ok) {{
                    throw new Error(`TiTiler error: ${{infoResp.status}} ${{infoResp.statusText}}`);
                }}

                cogInfo = await infoResp.json();
                console.log('COG Info:', cogInfo);

                // Fetch statistics
                try {{
                    const statsUrl = `${{TITILER_URL}}/cog/statistics?url=${{encodeURIComponent(cogUrl)}}`;
                    const statsResp = await fetch(statsUrl);
                    if (statsResp.ok) {{
                        cogStats = await statsResp.json();
                        console.log('COG Stats:', cogStats);
                    }}
                }} catch (e) {{
                    console.warn('Could not fetch statistics:', e);
                    cogStats = null;
                }}

                // Fetch TileJSON for WGS84 bounds (cogInfo.bounds may be in projected CRS)
                let wgs84Bounds = null;
                try {{
                    const tileJsonUrl = `${{TITILER_URL}}/cog/WebMercatorQuad/tilejson.json?url=${{encodeURIComponent(cogUrl)}}`;
                    const tileJsonResp = await fetch(tileJsonUrl);
                    if (tileJsonResp.ok) {{
                        const tileJson = await tileJsonResp.json();
                        wgs84Bounds = tileJson.bounds;
                        console.log('TileJSON WGS84 bounds:', wgs84Bounds);
                    }}
                }} catch (e) {{
                    console.warn('Could not fetch TileJSON bounds:', e);
                }}

                hideSpinner();

                // Display COG info
                displayCogInfo();

                // Populate band selectors
                populateBandSelectors();

                // Show controls
                document.getElementById('cog-info-section').style.display = 'block';
                document.getElementById('band-section').style.display = 'block';
                document.getElementById('rescale-section').style.display = 'block';
                document.getElementById('colormap-section').style.display = 'block';
                document.getElementById('point-section').style.display = 'block';
                document.getElementById('qa-section').style.display = 'block';

                // Add tile layer
                updateTileLayer();

                // Zoom to bounds (use WGS84 bounds from TileJSON, not native CRS from cogInfo)
                if (wgs84Bounds && wgs84Bounds.length === 4) {{
                    const bounds = [
                        [wgs84Bounds[1], wgs84Bounds[0]],  // [south, west] = [miny, minx]
                        [wgs84Bounds[3], wgs84Bounds[2]]   // [north, east] = [maxy, maxx]
                    ];
                    console.log('WGS84 bounds:', wgs84Bounds);
                    console.log('Leaflet bounds:', bounds);

                    // Use maxZoom to ensure small rasters zoom in properly
                    // animate: false ensures immediate zoom without animation glitches
                    map.fitBounds(bounds, {{
                        padding: [50, 50],
                        maxZoom: 18,
                        animate: false
                    }});
                }} else {{
                    console.warn('No WGS84 bounds available, cogInfo.bounds:', cogInfo.bounds);
                    setStatus('COG loaded (could not determine map extent)', 'success');
                }}

                setStatus('COG loaded successfully', 'success');

            }} catch (error) {{
                hideSpinner();
                console.error('Error loading COG:', error);
                setStatus(`Error: ${{error.message}}`, 'error');
            }}
        }}

        // Zoom to data extent (manual button)
        function zoomToExtent() {{
            if (!currentCogUrl) {{
                setStatus('No COG loaded', 'error');
                return;
            }}

            // Fetch WGS84 bounds from TileJSON (cogInfo.bounds may be in projected CRS)
            const tileJsonUrl = `${{TITILER_URL}}/cog/WebMercatorQuad/tilejson.json?url=${{encodeURIComponent(currentCogUrl)}}`;
            fetch(tileJsonUrl)
                .then(resp => resp.json())
                .then(data => {{
                    if (data.bounds && data.bounds.length === 4) {{
                        const bounds = [
                            [data.bounds[1], data.bounds[0]],
                            [data.bounds[3], data.bounds[2]]
                        ];
                        console.log('Zooming to TileJSON bounds:', bounds);
                        map.fitBounds(bounds, {{
                            padding: [50, 50],
                            maxZoom: 18,
                            animate: true
                        }});
                        setStatus('Zoomed to data extent', 'success');
                    }} else {{
                        setStatus('No bounds available for this COG', 'error');
                    }}
                }})
                .catch(err => {{
                    console.error('Failed to get bounds from TileJSON:', err);
                    setStatus('Could not determine data extent', 'error');
                }});
        }}

        // Display COG info
        function displayCogInfo() {{
            const container = document.getElementById('cog-info-content');

            const bandCount = cogInfo.band_metadata ? cogInfo.band_metadata.length : (cogInfo.count || '?');
            const dtype = cogInfo.dtype || '?';
            const width = cogInfo.width || '?';
            const height = cogInfo.height || '?';
            const crs = cogInfo.crs || cogInfo.crs_wkt?.match(/GEOGCS\\["([^"]+)"/)?.[1] || 'Unknown';

            let html = `
                <div class="info-row">
                    <span class="info-label">Size:</span>
                    <span class="info-value">${{width}} x ${{height}}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Bands:</span>
                    <span class="info-value">${{bandCount}}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Data Type:</span>
                    <span class="info-value">${{dtype}}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">CRS:</span>
                    <span class="info-value mono">${{crs}}</span>
                </div>
            `;

            if (cogInfo.nodata !== undefined && cogInfo.nodata !== null) {{
                html += `
                <div class="info-row">
                    <span class="info-label">NoData:</span>
                    <span class="info-value">${{cogInfo.nodata}}</span>
                </div>
                `;
            }}

            container.innerHTML = html;
        }}

        // Populate band selector dropdowns
        function populateBandSelectors() {{
            const bandCount = cogInfo.band_metadata ? cogInfo.band_metadata.length : (cogInfo.count || 1);
            const bandDescriptions = cogInfo.band_descriptions || [];

            const selectors = ['band-r', 'band-g', 'band-b'];
            const defaults = [1, Math.min(2, bandCount), Math.min(3, bandCount)];

            selectors.forEach((id, idx) => {{
                const select = document.getElementById(id);
                select.innerHTML = '';

                // Add "None" option for G and B (allows single-band mode)
                if (idx > 0) {{
                    const noneOpt = document.createElement('option');
                    noneOpt.value = '';
                    noneOpt.textContent = '-- None --';
                    select.appendChild(noneOpt);
                }}

                for (let i = 1; i <= bandCount; i++) {{
                    const opt = document.createElement('option');
                    opt.value = i;

                    // Get band name if available
                    let bandName = `Band ${{i}}`;
                    if (bandDescriptions[i-1] && bandDescriptions[i-1][1]) {{
                        bandName = `${{i}}: ${{bandDescriptions[i-1][1]}}`;
                    }} else if (cogInfo.band_metadata && cogInfo.band_metadata[i-1]) {{
                        const meta = cogInfo.band_metadata[i-1];
                        if (meta.DESCRIPTION || meta.description) {{
                            bandName = `${{i}}: ${{meta.DESCRIPTION || meta.description}}`;
                        }}
                    }}

                    opt.textContent = bandName;
                    select.appendChild(opt);
                }}

                // Set default
                if (bandCount >= defaults[idx]) {{
                    select.value = defaults[idx];
                }} else if (idx === 0) {{
                    select.value = 1;
                }}
            }});
        }}

        // Set band preset
        function setPreset(preset) {{
            const bandCount = cogInfo?.count || cogInfo?.band_metadata?.length || 1;

            if (preset === 'rgb') {{
                document.getElementById('band-r').value = 1;
                document.getElementById('band-g').value = bandCount >= 2 ? 2 : '';
                document.getElementById('band-b').value = bandCount >= 3 ? 3 : '';
            }} else if (preset === 'nir') {{
                document.getElementById('band-r').value = bandCount >= 4 ? 4 : 1;
                document.getElementById('band-g').value = bandCount >= 3 ? 3 : '';
                document.getElementById('band-b').value = bandCount >= 2 ? 2 : '';
            }} else if (preset === 'gray') {{
                document.getElementById('band-r').value = 1;
                document.getElementById('band-g').value = '';
                document.getElementById('band-b').value = '';
            }}

            updateTileLayer();
        }}

        // Update TiTiler tile layer
        function updateTileLayer() {{
            if (!currentCogUrl || !cogInfo) return;

            // Remove existing tile layer
            if (tileLayer) {{
                map.removeLayer(tileLayer);
            }}

            // Get selected bands
            const bandR = document.getElementById('band-r').value;
            const bandG = document.getElementById('band-g').value;
            const bandB = document.getElementById('band-b').value;

            // Build bidx parameter
            const bands = [bandR, bandG, bandB].filter(b => b);
            const isSingleBand = bands.length === 1;

            // Build URL parameters
            let params = new URLSearchParams();
            params.append('url', currentCogUrl);

            bands.forEach(b => params.append('bidx', b));

            // Rescale
            const rescaleMode = document.querySelector('input[name="rescale-mode"]:checked').value;
            const manualRescaleDiv = document.getElementById('manual-rescale');

            if (rescaleMode === 'auto' && cogStats) {{
                // Use statistics for rescale
                manualRescaleDiv.style.display = 'none';

                // Get min/max from first selected band stats
                const firstBand = bands[0];
                const bandKey = `b${{firstBand}}`;
                if (cogStats[bandKey]) {{
                    const min = cogStats[bandKey].min || cogStats[bandKey].percentile_2 || 0;
                    const max = cogStats[bandKey].max || cogStats[bandKey].percentile_98 || 255;
                    params.append('rescale', `${{min}},${{max}}`);

                    // Update manual inputs for reference
                    document.getElementById('rescale-min').value = Math.floor(min);
                    document.getElementById('rescale-max').value = Math.ceil(max);
                }}
            }} else {{
                // Manual rescale
                manualRescaleDiv.style.display = 'flex';
                const min = document.getElementById('rescale-min').value || 0;
                const max = document.getElementById('rescale-max').value || 255;
                params.append('rescale', `${{min}},${{max}}`);
            }}

            // Colormap (only for single band)
            if (isSingleBand) {{
                document.getElementById('colormap-section').style.display = 'block';
                const colormap = document.getElementById('colormap').value;
                if (colormap) {{
                    params.append('colormap_name', colormap);
                }}
            }} else {{
                document.getElementById('colormap-section').style.display = 'none';
            }}

            // Build tile URL
            const tileUrl = `${{TITILER_URL}}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}@2x.png?${{params.toString()}}`;

            console.log('Tile URL template:', tileUrl);

            // Add new tile layer
            // minNativeZoom: 0 prevents negative zoom requests when zoomed out far
            // (tileSize: 512 + zoomOffset: -1 can calculate z=-1 at low view zooms)
            tileLayer = L.tileLayer(tileUrl, {{
                tileSize: 512,
                zoomOffset: -1,
                minNativeZoom: 0,
                maxNativeZoom: 22,
                maxZoom: 24,
                attribution: 'TiTiler'
            }}).addTo(map);

            setStatus(`Displaying bands: ${{bands.join(', ')}}`, 'success');
        }}

        // Handle map click for point query
        async function handleMapClick(e) {{
            if (!currentCogUrl) return;

            const lat = e.latlng.lat;
            const lon = e.latlng.lng;

            const pointSection = document.getElementById('point-section');
            const pointContent = document.getElementById('point-info-content');

            pointContent.innerHTML = `<div class="point-coords">Querying ${{lat.toFixed(6)}}, ${{lon.toFixed(6)}}...</div>`;

            try {{
                const pointUrl = `${{TITILER_URL}}/cog/point/${{lon}},${{lat}}?url=${{encodeURIComponent(currentCogUrl)}}`;
                const resp = await fetch(pointUrl);

                if (!resp.ok) {{
                    throw new Error(`Point query failed: ${{resp.status}}`);
                }}

                const data = await resp.json();
                console.log('Point data:', data);

                let html = `<div class="point-coords">${{lat.toFixed(6)}}, ${{lon.toFixed(6)}}</div>`;
                html += '<div class="band-values">';

                if (data.values && Array.isArray(data.values)) {{
                    data.values.forEach((val, idx) => {{
                        const bandNum = idx + 1;
                        const displayVal = val !== null ? val.toFixed(4) : 'NoData';
                        html += `
                            <div class="band-value-row">
                                <span>Band ${{bandNum}}:</span>
                                <span>${{displayVal}}</span>
                            </div>
                        `;
                    }});
                }} else {{
                    html += '<div>No values returned</div>';
                }}

                html += '</div>';
                pointContent.innerHTML = html;

                // Show popup on map
                L.popup()
                    .setLatLng(e.latlng)
                    .setContent(`<b>Point Values</b><br>${{data.values ? data.values.map((v, i) => `B${{i+1}}: ${{v !== null ? v.toFixed(2) : 'NoData'}}`).join('<br>') : 'No data'}}`)
                    .openOn(map);

            }} catch (error) {{
                console.error('Point query error:', error);
                pointContent.innerHTML = `<div class="point-coords">Error: ${{error.message}}</div>`;
            }}
        }}

        // QA handlers
        function handleApprove() {{
            const notes = document.getElementById('qa-notes').value;
            console.log('APPROVE:', currentCogUrl, notes);
            setStatus('Approved! (Feature coming soon)', 'success');
            setTimeout(() => setStatus('COG loaded successfully', 'success'), 3000);
        }}

        function handleReject() {{
            const notes = document.getElementById('qa-notes').value;
            console.log('REJECT:', currentCogUrl, notes);
            setStatus('Rejected! (Feature coming soon)', 'error');
            setTimeout(() => setStatus('COG loaded successfully', 'success'), 3000);
        }}

        // Initialize on page load
        window.onload = function() {{
            initMap();

            // Check for URL parameter
            const urlInput = document.getElementById('cog-url');
            if (urlInput.value) {{
                loadCogInfo();
            }}
        }};
        """
