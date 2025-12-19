# ============================================================================
# CLAUDE CONTEXT - ZARR POINT QUERY INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web interface - Interactive Zarr/CMIP6 point query map
# PURPOSE: Demo map for querying pixel values from Zarr datasets via TiTiler-xarray
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: ZarrInterface
# DEPENDENCIES: web_interfaces.base, config
# ============================================================================
"""
Zarr Point Query Interface.

Interactive Leaflet map for visualizing and querying CMIP6 Zarr data.
Uses TiTiler-xarray for tile serving and point queries.

Features:
    - Dynamic variable selection from Zarr metadata
    - XYZ tile visualization with configurable colormap
    - Click-to-query pixel values
    - Time dimension selector (if present)
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

from config import get_config


@InterfaceRegistry.register('zarr')
class ZarrInterface(BaseInterface):
    """
    Zarr Point Query Interface.

    Interactive map for querying CMIP6 climate data stored in Zarr format.
    Uses TiTiler-xarray endpoints for tile rendering and point queries.
    """

    # Zarr dataset path (relative to silver-cogs container)
    ZARR_PATH = "test-zarr/cmip6-tasmax-sample.zarr"

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Zarr Query Interface HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        config = get_config()

        # Build Zarr URL from config
        storage_account = config.storage.silver.account_name
        container = config.storage.silver.cogs
        zarr_url = f"https://{storage_account}.blob.core.windows.net/{container}/{self.ZARR_PATH}"

        # TiTiler base URL from config
        titiler_url = config.titiler_base_url.rstrip('/')

        return self._generate_full_page(zarr_url, titiler_url)

    def _generate_full_page(self, zarr_url: str, titiler_url: str) -> str:
        """Generate complete HTML page with Leaflet and TiTiler-xarray integration."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zarr Query - CMIP6 Climate Data</title>

    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin=""/>

    <style>
        {self._generate_css()}
    </style>
</head>
<body>
    {self._generate_navbar()}
    {self._generate_html_content()}

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
            crossorigin=""></script>

    <script>
        // Configuration from server
        const ZARR_URL = "{zarr_url}";
        const TITILER_URL = "{titiler_url}";

        {self._generate_js()}
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
                <a href="/api/interface/map">Vector Map</a>
                <a href="/api/interface/zarr" class="active">Zarr Query</a>
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
            <h3>CMIP6 Zarr Query</h3>

            <div class="dataset-info" id="dataset-info">
                <div class="info-loading">Loading dataset info...</div>
            </div>

            <div class="control-group">
                <label for="variable-select">Variable:</label>
                <select id="variable-select" disabled>
                    <option value="">Loading...</option>
                </select>
            </div>

            <div class="control-group" id="time-control" style="display: none;">
                <label for="time-select">Time:</label>
                <select id="time-select">
                    <option value="0">First timestep</option>
                </select>
            </div>

            <div class="control-group">
                <label for="colormap-select">Colormap:</label>
                <select id="colormap-select">
                    <option value="viridis" selected>Viridis</option>
                    <option value="plasma">Plasma</option>
                    <option value="inferno">Inferno</option>
                    <option value="magma">Magma</option>
                    <option value="coolwarm">Cool-Warm</option>
                    <option value="rdbu_r">Red-Blue (diverging)</option>
                    <option value="ylgnbu">Yellow-Green-Blue</option>
                    <option value="spectral_r">Spectral</option>
                </select>
            </div>

            <div class="button-group">
                <button id="refresh-btn" onclick="loadTiles()" class="btn-primary" disabled>
                    Refresh Tiles
                </button>
                <button id="zoom-btn" onclick="zoomToData()" class="btn-secondary" disabled>
                    Zoom to Data
                </button>
            </div>

            <div class="status-section">
                <div id="status" class="status-text">Initializing...</div>
            </div>

            <div class="query-result" id="query-result" style="display: none;">
                <h4>Point Query Result</h4>
                <div id="query-content"></div>
            </div>
        </div>

        <!-- Loading Spinner -->
        <div class="spinner" id="spinner">
            <div class="spinner-icon"></div>
            <div class="spinner-text">Loading...</div>
        </div>

        <!-- Click instruction overlay -->
        <div class="click-hint" id="click-hint">
            Click anywhere on the raster to query pixel value
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
            width: 320px;
            max-height: calc(100vh - 80px);
            overflow-y: auto;
            border-left: 4px solid #00A3DA;
        }

        .control-panel h3 {
            font-size: 18px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
        }

        .dataset-info {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 16px;
            font-size: 12px;
        }

        .dataset-info .info-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #e9ecef;
        }

        .dataset-info .info-row:last-child {
            border-bottom: none;
        }

        .dataset-info .info-label {
            color: #626F86;
            font-weight: 600;
        }

        .dataset-info .info-value {
            color: #053657;
            font-family: monospace;
        }

        .info-loading {
            color: #626F86;
            font-style: italic;
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

        .control-group select:disabled {
            background: #f0f0f0;
            color: #999;
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
            background: #00A3DA;
            color: white;
        }

        .btn-primary:hover:not(:disabled) {
            background: #0071BC;
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

        /* Query Result */
        .query-result {
            margin-top: 16px;
            padding: 12px;
            background: #f0fff4;
            border: 1px solid #68d391;
            border-radius: 4px;
        }

        .query-result h4 {
            font-size: 13px;
            font-weight: 700;
            color: #2f855a;
            margin-bottom: 8px;
        }

        #query-content {
            font-size: 13px;
            color: #053657;
        }

        #query-content .query-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
        }

        #query-content .query-label {
            color: #626F86;
        }

        #query-content .query-value {
            font-weight: 600;
            font-family: monospace;
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
            border-top: 4px solid #00A3DA;
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

        /* Click hint */
        .click-hint {
            position: absolute;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 163, 218, 0.9);
            color: white;
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            z-index: 1000;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s;
        }

        .click-hint.visible {
            opacity: 1;
        }

        /* Leaflet popup customization */
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
            border-bottom: 2px solid #00A3DA;
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
            font-family: monospace;
            font-size: 14px;
        }

        .popup-value.highlight {
            font-size: 18px;
            color: #00A3DA;
            font-weight: 700;
        }
        """

    def _generate_js(self) -> str:
        """Generate JavaScript code."""
        return """
        // State
        let datasetInfo = null;
        let tileLayer = null;
        let dataBounds = null;

        // Initialize map centered on global view
        const map = L.map('map').setView([20, 0], 2);

        // Add OpenStreetMap base layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(map);

        // Status functions
        function setStatus(message, type = '') {
            const statusEl = document.getElementById('status');
            statusEl.textContent = message;
            statusEl.className = 'status-text' + (type ? ' ' + type : '');
        }

        function showSpinner(text = 'Loading...') {
            document.querySelector('.spinner-text').textContent = text;
            document.getElementById('spinner').classList.add('active');
        }

        function hideSpinner() {
            document.getElementById('spinner').classList.remove('active');
        }

        function showClickHint() {
            const hint = document.getElementById('click-hint');
            hint.classList.add('visible');
            setTimeout(() => hint.classList.remove('visible'), 4000);
        }

        // Load dataset info from TiTiler-xarray
        async function loadDatasetInfo() {
            try {
                setStatus('Loading dataset info...');
                showSpinner('Fetching Zarr metadata...');

                const infoUrl = `${TITILER_URL}/xarray/info?url=${encodeURIComponent(ZARR_URL)}`;
                console.log('Fetching info:', infoUrl);

                const response = await fetch(infoUrl);

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }

                datasetInfo = await response.json();
                console.log('Dataset info:', datasetInfo);

                // Update UI with dataset info
                updateDatasetInfoPanel();
                populateVariableDropdown();
                populateTimeDropdown();

                // Enable controls
                document.getElementById('variable-select').disabled = false;
                document.getElementById('refresh-btn').disabled = false;
                document.getElementById('zoom-btn').disabled = false;

                // Extract bounds if available
                if (datasetInfo.bounds) {
                    dataBounds = L.latLngBounds(
                        [datasetInfo.bounds[1], datasetInfo.bounds[0]],
                        [datasetInfo.bounds[3], datasetInfo.bounds[2]]
                    );
                }

                // Load initial tiles
                loadTiles();

                setStatus('Dataset loaded successfully', 'success');
                showClickHint();

            } catch (error) {
                console.error('Error loading dataset info:', error);
                setStatus(`Error: ${error.message}`, 'error');
                document.getElementById('dataset-info').innerHTML =
                    `<div class="info-loading" style="color: #DC2626;">Failed to load dataset</div>`;
            } finally {
                hideSpinner();
            }
        }

        function updateDatasetInfoPanel() {
            const panel = document.getElementById('dataset-info');

            // Extract useful info
            const dims = datasetInfo.dims || {};
            const attrs = datasetInfo.attrs || {};

            let html = '';

            // Dataset name from attrs or URL
            const name = attrs.title || ZARR_URL.split('/').pop();
            html += `<div class="info-row"><span class="info-label">Dataset:</span><span class="info-value">${name}</span></div>`;

            // Dimensions
            for (const [dim, size] of Object.entries(dims)) {
                html += `<div class="info-row"><span class="info-label">${dim}:</span><span class="info-value">${size}</span></div>`;
            }

            // Bounds if available
            if (datasetInfo.bounds) {
                const b = datasetInfo.bounds;
                html += `<div class="info-row"><span class="info-label">Bounds:</span><span class="info-value">${b[0].toFixed(1)}, ${b[1].toFixed(1)} to ${b[2].toFixed(1)}, ${b[3].toFixed(1)}</span></div>`;
            }

            panel.innerHTML = html;
        }

        function populateVariableDropdown() {
            const select = document.getElementById('variable-select');
            select.innerHTML = '';

            // Get data variables (exclude coordinate variables)
            const variables = datasetInfo.data_vars || datasetInfo.variables || [];
            const coords = datasetInfo.coords || [];

            // Filter out coordinates
            const dataVars = Array.isArray(variables)
                ? variables.filter(v => !coords.includes(v))
                : Object.keys(variables).filter(v => !coords.includes(v));

            if (dataVars.length === 0) {
                select.innerHTML = '<option value="">No variables found</option>';
                return;
            }

            dataVars.forEach((varName, idx) => {
                const option = document.createElement('option');
                option.value = varName;
                option.textContent = varName;
                if (idx === 0) option.selected = true;
                select.appendChild(option);
            });

            // Add change listener
            select.addEventListener('change', loadTiles);
        }

        function populateTimeDropdown() {
            const dims = datasetInfo.dims || {};
            const timeControl = document.getElementById('time-control');
            const timeSelect = document.getElementById('time-select');

            // Check for time dimension
            const timeDim = dims.time || dims.Time || dims.t;
            if (!timeDim || timeDim <= 1) {
                timeControl.style.display = 'none';
                return;
            }

            timeControl.style.display = 'block';
            timeSelect.innerHTML = '';

            // Add time step options (limit to avoid huge dropdown)
            const maxOptions = Math.min(timeDim, 50);
            const step = Math.max(1, Math.floor(timeDim / maxOptions));

            for (let i = 0; i < timeDim; i += step) {
                const option = document.createElement('option');
                option.value = i;
                option.textContent = `Step ${i}`;
                timeSelect.appendChild(option);
            }

            timeSelect.addEventListener('change', loadTiles);
        }

        function loadTiles() {
            const variable = document.getElementById('variable-select').value;
            const colormap = document.getElementById('colormap-select').value;
            const timeIdx = document.getElementById('time-select').value || 0;

            if (!variable) {
                setStatus('Select a variable first', 'error');
                return;
            }

            // Remove existing tile layer
            if (tileLayer) {
                map.removeLayer(tileLayer);
            }

            // Build tile URL
            // TiTiler-xarray tile endpoint: /xarray/tiles/{z}/{x}/{y}
            let tileUrl = `${TITILER_URL}/xarray/tiles/{z}/{x}/{y}`;
            tileUrl += `?url=${encodeURIComponent(ZARR_URL)}`;
            tileUrl += `&variable=${encodeURIComponent(variable)}`;
            tileUrl += `&colormap_name=${colormap}`;

            // Add time dimension if needed
            const dims = datasetInfo.dims || {};
            if (dims.time || dims.Time || dims.t) {
                tileUrl += `&time=${timeIdx}`;
            }

            console.log('Tile URL:', tileUrl);

            // Add tile layer
            tileLayer = L.tileLayer(tileUrl, {
                opacity: 0.8,
                maxZoom: 18,
                attribution: 'CMIP6 via TiTiler-xarray'
            }).addTo(map);

            setStatus(`Displaying: ${variable}`, 'success');
        }

        function zoomToData() {
            if (dataBounds && dataBounds.isValid()) {
                map.fitBounds(dataBounds, { padding: [50, 50] });
            } else {
                // Default to global view
                map.setView([20, 0], 2);
            }
        }

        // Point query on map click
        map.on('click', async function(e) {
            const { lat, lng } = e.latlng;
            const variable = document.getElementById('variable-select').value;
            const timeIdx = document.getElementById('time-select').value || 0;

            if (!variable) {
                setStatus('Select a variable to query', 'error');
                return;
            }

            try {
                setStatus('Querying point...');

                // Build point query URL
                let pointUrl = `${TITILER_URL}/xarray/point/${lng},${lat}`;
                pointUrl += `?url=${encodeURIComponent(ZARR_URL)}`;
                pointUrl += `&variable=${encodeURIComponent(variable)}`;

                // Add time if needed
                const dims = datasetInfo.dims || {};
                if (dims.time || dims.Time || dims.t) {
                    pointUrl += `&time=${timeIdx}`;
                }

                console.log('Point query URL:', pointUrl);

                const response = await fetch(pointUrl);

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }

                const result = await response.json();
                console.log('Point query result:', result);

                // Show popup on map
                const value = result.values?.[0] ?? result.value ?? 'N/A';
                const popupContent = `
                    <div class="popup-title">Point Query</div>
                    <div class="popup-row">
                        <span class="popup-label">Variable</span>
                        <span class="popup-value">${variable}</span>
                    </div>
                    <div class="popup-row">
                        <span class="popup-label">Value</span>
                        <span class="popup-value highlight">${typeof value === 'number' ? value.toFixed(4) : value}</span>
                    </div>
                    <div class="popup-row">
                        <span class="popup-label">Coordinates</span>
                        <span class="popup-value">${lat.toFixed(4)}, ${lng.toFixed(4)}</span>
                    </div>
                `;

                L.popup()
                    .setLatLng(e.latlng)
                    .setContent(popupContent)
                    .openOn(map);

                // Update side panel
                updateQueryResult(variable, value, lat, lng);

                setStatus('Query complete', 'success');

            } catch (error) {
                console.error('Point query error:', error);
                setStatus(`Query error: ${error.message}`, 'error');

                // Show error popup
                L.popup()
                    .setLatLng(e.latlng)
                    .setContent(`<div style="color: #DC2626;">Query failed: ${error.message}</div>`)
                    .openOn(map);
            }
        });

        function updateQueryResult(variable, value, lat, lng) {
            const resultDiv = document.getElementById('query-result');
            const contentDiv = document.getElementById('query-content');

            resultDiv.style.display = 'block';

            contentDiv.innerHTML = `
                <div class="query-row">
                    <span class="query-label">Variable:</span>
                    <span class="query-value">${variable}</span>
                </div>
                <div class="query-row">
                    <span class="query-label">Value:</span>
                    <span class="query-value">${typeof value === 'number' ? value.toFixed(4) : value}</span>
                </div>
                <div class="query-row">
                    <span class="query-label">Location:</span>
                    <span class="query-value">${lat.toFixed(4)}, ${lng.toFixed(4)}</span>
                </div>
            `;
        }

        // Colormap change handler
        document.getElementById('colormap-select').addEventListener('change', loadTiles);

        // Initialize on page load
        window.addEventListener('load', loadDatasetInfo);
        """
