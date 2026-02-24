# ============================================================================
# CLAUDE CONTEXT - PROMOTED DATASET VIEWER INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Styled map viewer for promoted datasets
# PURPOSE: Display promoted vector datasets with OGC Styles applied
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: PromotedViewerInterface
# DEPENDENCIES: web_interfaces.base, infrastructure.promoted_repository
# ============================================================================
"""
Promoted Dataset Viewer Interface.

Full-featured Leaflet map viewer for promoted datasets:
- Fetches promoted metadata (title, description, tags)
- Fetches OGC Style in Leaflet format
- Renders styled features with controls (limit, simplify)
- Click popups, zoom-to-fit, status panel

Route: /api/interface/promoted-viewer?id={promoted_id}
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('promoted-viewer')
class PromotedViewerInterface(BaseInterface):
    """
    Promoted Dataset Viewer Interface.

    Displays promoted vector datasets with their associated OGC Style.
    Full-featured viewer with limit/simplify controls.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Render the promoted dataset viewer page.

        Args:
            request: Azure Functions HttpRequest object
                Query params:
                    - id: Required. The promoted_id to view

        Returns:
            Complete HTML document string
        """
        # Get promoted_id from query params
        promoted_id = request.params.get('id')

        if not promoted_id:
            return self._render_error_page(
                "Missing 'id' parameter",
                "Usage: /api/interface/promoted-viewer?id={promoted_id}"
            )

        # Generate HTML - data will be fetched client-side
        content = self._generate_html_content(promoted_id)
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js(promoted_id)

        # Include Leaflet in head
        leaflet_head = """
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        """

        return self.wrap_html(
            title="Dataset Viewer",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=False,
            include_navbar=False,  # Full-screen map
            head_extras=leaflet_head
        )

    def _render_error_page(self, title: str, message: str) -> str:
        """Render error page for missing parameters."""
        content = f"""
        <div class="container">
            <div class="error-box">
                <h2>{title}</h2>
                <p>{message}</p>
                <p><a href="/api/interface/gallery">Back to Gallery</a></p>
            </div>
        </div>
        """
        return self.wrap_html(
            title="Error - Promoted Viewer",
            content=content,
            custom_css="""
            .error-box {
                background: white;
                padding: 40px;
                border-radius: 8px;
                text-align: center;
                max-width: 500px;
                margin: 100px auto;
                box-shadow: 0 2px 12px rgba(0,0,0,0.1);
            }
            .error-box h2 { color: #dc2626; margin-bottom: 16px; }
            .error-box a { color: var(--ds-blue-primary); }
            """
        )

    def _generate_html_content(self, promoted_id: str) -> str:
        """Generate HTML structure for the viewer."""
        return f"""
        <!-- Full-screen map container -->
        <div id="map"></div>

        <!-- Metadata Panel (top-right) -->
        <div class="metadata-panel" id="metadata-panel">
            <div class="panel-header">
                <h3 id="dataset-title">Loading...</h3>
                <button class="close-btn" onclick="togglePanel()">&times;</button>
            </div>

            <div id="dataset-description" class="description">Loading dataset information...</div>

            <div id="tags-container" class="tags-container"></div>

            <div class="controls-section">
                <h4>Display Options</h4>

                <div class="control-row">
                    <label>Feature Limit:</label>
                    <select id="limit-select" onchange="loadFeatures()">
                        <option value="50">50</option>
                        <option value="100" selected>100</option>
                        <option value="250">250</option>
                        <option value="500">500</option>
                        <option value="1000">1000</option>
                        <option value="5000">5000 (slow)</option>
                    </select>
                </div>

                <div class="control-row">
                    <label>Simplify (meters):</label>
                    <input type="number" id="simplify-input" value="0" min="0" step="1"
                           onchange="loadFeatures()" placeholder="0 = none">
                </div>

                <div class="button-row">
                    <button class="btn btn-primary" onclick="loadFeatures()">Reload</button>
                    <button class="btn btn-secondary" onclick="zoomToFeatures()">Zoom to Fit</button>
                </div>
            </div>

            <div class="status-section">
                <div id="status-text" class="status-text">Initializing...</div>
                <div id="style-info" class="style-info"></div>
            </div>

            <div class="footer-links">
                <a href="/api/interface/gallery">Back to Gallery</a>
            </div>
        </div>

        <!-- Panel toggle button (when panel is hidden) -->
        <button class="panel-toggle hidden" id="panel-toggle" onclick="togglePanel()">
            Info
        </button>

        <!-- Loading overlay -->
        <div id="loading-overlay" class="loading-overlay">
            <div class="spinner"></div>
            <div>Loading dataset...</div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate CSS for the promoted viewer."""
        return """
        /* Full-screen map */
        body {
            margin: 0;
            padding: 0;
            overflow: hidden;
        }

        #map {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 1;
        }

        /* Metadata Panel */
        .metadata-panel {
            position: absolute;
            top: 10px;
            right: 10px;
            width: 320px;
            max-height: calc(100vh - 20px);
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            z-index: 1000;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding: 16px;
            border-bottom: 1px solid #e9ecef;
            background: linear-gradient(135deg, var(--ds-blue-primary) 0%, var(--ds-navy) 100%);
            color: white;
            border-radius: 8px 8px 0 0;
        }

        .panel-header h3 {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
            line-height: 1.3;
        }

        .close-btn {
            background: transparent;
            border: none;
            color: white;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
            opacity: 0.8;
        }

        .close-btn:hover {
            opacity: 1;
        }

        .description {
            padding: 12px 16px;
            font-size: 13px;
            color: var(--ds-gray);
            border-bottom: 1px solid #e9ecef;
        }

        .tags-container {
            padding: 12px 16px;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            border-bottom: 1px solid #e9ecef;
        }

        .tag {
            display: inline-block;
            padding: 4px 10px;
            background: var(--ds-bg);
            color: var(--ds-navy);
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }

        .controls-section {
            padding: 16px;
            border-bottom: 1px solid #e9ecef;
        }

        .controls-section h4 {
            margin: 0 0 12px 0;
            font-size: 13px;
            color: var(--ds-navy);
            font-weight: 600;
        }

        .control-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 10px;
        }

        .control-row label {
            font-size: 12px;
            color: var(--ds-gray);
        }

        .control-row select,
        .control-row input {
            width: 120px;
            padding: 6px 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 12px;
        }

        .button-row {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }

        .btn {
            flex: 1;
            padding: 8px 12px;
            border: none;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--ds-blue-primary);
            color: white;
        }

        .btn-primary:hover {
            background: var(--ds-cyan);
        }

        .btn-secondary {
            background: #e9ecef;
            color: var(--ds-navy);
        }

        .btn-secondary:hover {
            background: #ddd;
        }

        .status-section {
            padding: 12px 16px;
            background: var(--ds-bg);
        }

        .status-text {
            font-size: 12px;
            color: var(--ds-gray);
            text-align: center;
        }

        .status-text.success { color: #059669; }
        .status-text.error { color: #dc2626; }

        .style-info {
            font-size: 11px;
            color: var(--ds-gray);
            text-align: center;
            margin-top: 6px;
        }

        .footer-links {
            padding: 12px 16px;
            text-align: center;
            border-top: 1px solid #e9ecef;
        }

        .footer-links a {
            font-size: 12px;
            color: var(--ds-blue-primary);
            text-decoration: none;
        }

        .footer-links a:hover {
            text-decoration: underline;
        }

        /* Panel toggle button */
        .panel-toggle {
            position: absolute;
            top: 10px;
            right: 10px;
            z-index: 1000;
            padding: 10px 16px;
            background: white;
            border: none;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
        }

        .panel-toggle:hover {
            background: #f0f0f0;
        }

        /* Loading overlay */
        .loading-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.9);
            z-index: 2000;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 16px;
            font-size: 16px;
            color: var(--ds-gray);
        }

        .loading-overlay.hidden {
            display: none;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid #e9ecef;
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .hidden {
            display: none !important;
        }

        /* Responsive */
        @media (max-width: 600px) {
            .metadata-panel {
                width: calc(100% - 20px);
                max-height: 50vh;
            }
        }
        """

    def _generate_custom_js(self, promoted_id: str) -> str:
        """Generate JavaScript for the promoted viewer."""
        return f"""
        // Configuration
        const PROMOTED_ID = '{promoted_id}';
        const API_BASE = window.location.origin;

        // State
        let map = null;
        let featureLayer = null;
        let promotedData = null;
        let styleData = null;

        // Initialize on load
        document.addEventListener('DOMContentLoaded', init);

        async function init() {{
            console.log('Initializing promoted viewer for:', PROMOTED_ID);

            try {{
                // Step 1: Fetch promoted dataset metadata
                updateStatus('Fetching dataset info...');
                promotedData = await fetchPromotedDataset();

                if (!promotedData) {{
                    throw new Error('Dataset not found');
                }}

                // Update UI with metadata
                updateMetadataPanel(promotedData);

                // Step 2: Initialize map
                updateStatus('Initializing map...');
                initMap();

                // Step 3: Fetch style if available
                if (promotedData.style_id && promotedData.stac_collection_id) {{
                    updateStatus('Fetching style...');
                    styleData = await fetchStyle(promotedData.stac_collection_id, promotedData.style_id);
                    if (styleData) {{
                        document.getElementById('style-info').textContent = `Style: ${{promotedData.style_id}}`;
                    }}
                }}

                // Step 4: Load features
                await loadFeatures();

                // Hide loading overlay
                document.getElementById('loading-overlay').classList.add('hidden');

            }} catch (error) {{
                console.error('Initialization error:', error);
                updateStatus(`Error: ${{error.message}}`, 'error');
                document.getElementById('loading-overlay').innerHTML = `
                    <div style="color: #dc2626; text-align: center;">
                        <h3>Failed to load dataset</h3>
                        <p>${{error.message}}</p>
                        <a href="/api/interface/gallery" style="color: var(--ds-blue-primary);">Back to Gallery</a>
                    </div>
                `;
            }}
        }}

        async function fetchPromotedDataset() {{
            const response = await fetch(`${{API_BASE}}/api/promote/${{PROMOTED_ID}}`);
            if (!response.ok) {{
                throw new Error(`Dataset not found: ${{PROMOTED_ID}}`);
            }}
            const result = await response.json();
            if (!result.success) {{
                throw new Error(result.error || 'Failed to fetch dataset');
            }}
            return result.data;
        }}

        async function fetchStyle(collectionId, styleId) {{
            try {{
                const url = `${{API_BASE}}/api/features/collections/${{collectionId}}/styles/${{styleId}}?f=leaflet`;
                const response = await fetch(url);
                if (!response.ok) {{
                    console.warn('Style not found, using default');
                    return null;
                }}
                return await response.json();
            }} catch (error) {{
                console.warn('Failed to fetch style:', error);
                return null;
            }}
        }}

        function updateMetadataPanel(data) {{
            // Title
            document.getElementById('dataset-title').textContent = data.title || data.promoted_id;
            document.title = `${{data.title || data.promoted_id}} - Dataset Viewer`;

            // Description
            document.getElementById('dataset-description').textContent =
                data.description || 'No description available';

            // Tags
            const tagsContainer = document.getElementById('tags-container');
            const tags = data.tags || [];
            if (tags.length > 0) {{
                tagsContainer.innerHTML = tags.map(tag =>
                    `<span class="tag">${{escapeHtml(tag)}}</span>`
                ).join('');
            }} else {{
                tagsContainer.innerHTML = '<span class="tag">vector</span>';
            }}
        }}

        function initMap() {{
            map = L.map('map').setView([0, 0], 2);

            // Add OpenStreetMap base layer
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 19
            }}).addTo(map);

            console.log('Map initialized');
        }}

        async function loadFeatures() {{
            if (!promotedData || !promotedData.stac_collection_id) {{
                updateStatus('No collection ID available', 'error');
                return;
            }}

            const limit = document.getElementById('limit-select').value;
            const simplify = document.getElementById('simplify-input').value;

            updateStatus(`Loading ${{limit}} features...`);

            try {{
                // Build URL
                let url = `${{API_BASE}}/api/features/collections/${{promotedData.stac_collection_id}}/items?limit=${{limit}}`;
                if (simplify && parseFloat(simplify) > 0) {{
                    url += `&simplify=${{simplify}}`;
                }}

                const response = await fetch(url);
                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}`);
                }}

                const data = await response.json();
                const features = data.features || [];

                // Remove existing layer
                if (featureLayer) {{
                    map.removeLayer(featureLayer);
                }}

                // Determine style to apply
                const leafletStyle = getLeafletStyle();

                // Add features to map
                featureLayer = L.geoJSON(data, {{
                    style: function(feature) {{
                        return leafletStyle;
                    }},
                    pointToLayer: function(feature, latlng) {{
                        return L.circleMarker(latlng, {{
                            radius: 6,
                            ...leafletStyle
                        }});
                    }},
                    onEachFeature: function(feature, layer) {{
                        // Create popup with properties
                        const props = feature.properties || {{}};
                        let popupContent = '<div style="font-size: 13px; max-width: 280px;">';
                        popupContent += `<b style="color: var(--ds-navy);">${{promotedData.title || 'Feature'}}</b><br><hr style="margin: 8px 0;">`;

                        // Show first 8 properties
                        const keys = Object.keys(props).slice(0, 8);
                        keys.forEach(key => {{
                            const value = props[key];
                            if (value !== null && value !== undefined) {{
                                popupContent += `<b>${{key}}:</b> ${{value}}<br>`;
                            }}
                        }});

                        if (Object.keys(props).length > 8) {{
                            popupContent += `<i style="color: #888;">...and ${{Object.keys(props).length - 8}} more properties</i>`;
                        }}
                        popupContent += '</div>';

                        layer.bindPopup(popupContent);

                        // Hover effect
                        layer.on('mouseover', function() {{
                            this.setStyle({{ fillOpacity: 0.8 }});
                        }});
                        layer.on('mouseout', function() {{
                            this.setStyle({{ fillOpacity: leafletStyle.fillOpacity || 0.5 }});
                        }});
                    }}
                }}).addTo(map);

                // Zoom to features
                zoomToFeatures();

                const simplifyNote = simplify && parseFloat(simplify) > 0 ? ` (simplified: ${{simplify}}m)` : '';
                updateStatus(`Loaded ${{features.length}} features${{simplifyNote}}`, 'success');

            }} catch (error) {{
                console.error('Failed to load features:', error);
                updateStatus(`Error loading features: ${{error.message}}`, 'error');
            }}
        }}

        function getLeafletStyle() {{
            // If we have style data from OGC Styles API, use it
            if (styleData && styleData.style) {{
                return styleData.style;
            }}

            // Default style (Design System blue)
            return {{
                color: '#0071BC',
                weight: 2,
                opacity: 0.8,
                fillColor: '#0071BC',
                fillOpacity: 0.4
            }};
        }}

        function zoomToFeatures() {{
            if (featureLayer && featureLayer.getBounds().isValid()) {{
                map.fitBounds(featureLayer.getBounds(), {{ padding: [50, 50] }});
            }}
        }}

        function togglePanel() {{
            const panel = document.getElementById('metadata-panel');
            const toggle = document.getElementById('panel-toggle');

            if (panel.classList.contains('hidden')) {{
                panel.classList.remove('hidden');
                toggle.classList.add('hidden');
            }} else {{
                panel.classList.add('hidden');
                toggle.classList.remove('hidden');
            }}
        }}

        function updateStatus(message, type = '') {{
            const statusEl = document.getElementById('status-text');
            statusEl.textContent = message;
            statusEl.className = 'status-text' + (type ? ' ' + type : '');
        }}
        """
