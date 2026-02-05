"""
MapLibre Vector Tiles Viewer Interface.

Web interface for viewing PostGIS vector data using MapLibre GL JS with
MVT (Mapbox Vector Tiles) from TiPG.

Route: /api/interface/vector-tiles?collection={collection_id}

Features (13 JAN 2026):
    - MapLibre GL JS for high-performance vector tile rendering
    - MVT tiles from TiPG (rmhtitiler) instead of GeoJSON
    - Handles large datasets efficiently (tiles only load what's visible)
    - Dynamic styling with MapLibre GL expressions
    - Feature inspection on click via OGC Features API
    - Zoom-dependent styling

Why MapLibre over Leaflet:
    - Native vector tile support (MVT/PBF format)
    - WebGL rendering for smooth pan/zoom
    - Handles millions of features without performance degradation
    - Rich styling language (expressions, zoom interpolation)

Exports:
    VectorTilesInterface: MapLibre-based vector tile viewer
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
from config import get_config


@InterfaceRegistry.register('vector-tiles')
class VectorTilesInterface(BaseInterface):
    """
    MapLibre GL Vector Tiles Viewer.

    High-performance viewer for PostGIS vector data using MVT tiles
    from TiPG (served by rmhtitiler).
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate MapLibre vector tiles viewer HTML.

        Query Parameters:
            collection: Collection ID / table name (required)

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        collection_id = request.params.get('collection', '')

        # Get TiTiler base URL for TiPG endpoints
        config = get_config()
        titiler_base_url = config.titiler_base_url.rstrip('/')

        content = self._generate_html_content(collection_id, titiler_base_url)

        title = f"Vector Tiles: {collection_id}" if collection_id else "Vector Tiles Viewer"

        # Return complete HTML (not using wrap_html since we need full control)
        return content

    def _generate_html_content(self, collection_id: str, titiler_base_url: str) -> str:
        """Generate complete HTML page with MapLibre GL JS."""

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vector Tiles - {collection_id or 'Viewer'}</title>

    <!-- MapLibre GL JS -->
    <script src="https://unpkg.com/maplibre-gl@4.1.2/dist/maplibre-gl.js"></script>
    <link href="https://unpkg.com/maplibre-gl@4.1.2/dist/maplibre-gl.css" rel="stylesheet" />

    <style>
        :root {{
            --ds-navy: #053657;
            --ds-blue: #0071BC;
            --ds-light-blue: #00A3DA;
            --ds-gray: #626F86;
            --ds-gray-light: #e9ecef;
            --ds-gray-dark: #374151;
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

        /* Main Layout */
        .app-container {{
            display: flex;
            height: 100vh;
        }}

        /* Map Container */
        .map-container {{
            flex: 1;
            position: relative;
        }}

        #map {{
            height: 100%;
            width: 100%;
        }}

        /* Right Sidebar */
        .sidebar {{
            width: 340px;
            background: white;
            border-left: 1px solid var(--ds-gray-light);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        .sidebar-header {{
            padding: 20px;
            background: linear-gradient(135deg, var(--ds-navy) 0%, #0a4a7a 100%);
            color: white;
        }}

        .sidebar-header h1 {{
            font-size: 16px;
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
            word-break: break-all;
        }}

        .maplibre-badge {{
            background: rgba(255,255,255,0.2);
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
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
            padding: 10px 14px;
            background: var(--ds-bg);
            border-bottom: 1px solid var(--ds-gray-light);
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-navy);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .section-body {{
            padding: 14px;
        }}

        /* Status Display */
        .status-display {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px;
            background: linear-gradient(135deg, #F0F9FF 0%, #E0F2FE 100%);
            border: 1px solid #BAE6FD;
            border-radius: 8px;
            margin-bottom: 16px;
        }}

        .status-icon {{
            font-size: 24px;
        }}

        .status-text {{
            flex: 1;
        }}

        .status-label {{
            font-size: 10px;
            color: var(--ds-gray);
            text-transform: uppercase;
        }}

        .status-value {{
            font-size: 14px;
            font-weight: 600;
            color: var(--ds-navy);
        }}

        .status-value.loading {{
            color: var(--ds-warning);
        }}

        .status-value.error {{
            color: var(--ds-error);
        }}

        .status-value.success {{
            color: var(--ds-success);
        }}

        /* Style Controls */
        .style-control {{
            margin-bottom: 14px;
        }}

        .style-control label {{
            display: block;
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            margin-bottom: 6px;
        }}

        .color-row {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}

        .color-input {{
            width: 40px;
            height: 32px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            cursor: pointer;
            padding: 2px;
        }}

        .color-hex {{
            flex: 1;
            padding: 8px 10px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
        }}

        .slider-row {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}

        .slider-input {{
            flex: 1;
            height: 6px;
            -webkit-appearance: none;
            background: var(--ds-gray-light);
            border-radius: 3px;
            outline: none;
        }}

        .slider-input::-webkit-slider-thumb {{
            -webkit-appearance: none;
            width: 16px;
            height: 16px;
            background: var(--ds-blue);
            border-radius: 50%;
            cursor: pointer;
        }}

        .slider-value {{
            width: 40px;
            text-align: right;
            font-size: 12px;
            font-family: monospace;
            color: var(--ds-gray-dark);
        }}

        /* Buttons */
        .btn {{
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }}

        .btn-primary {{
            background: var(--ds-blue);
            color: white;
            width: 100%;
        }}

        .btn-primary:hover {{
            background: var(--ds-light-blue);
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

        /* Feature Info Panel */
        .feature-info {{
            background: var(--ds-bg);
            border-radius: 6px;
            padding: 12px;
            max-height: 200px;
            overflow-y: auto;
        }}

        .feature-info-empty {{
            color: var(--ds-gray);
            font-size: 12px;
            text-align: center;
            padding: 20px;
        }}

        .feature-prop {{
            padding: 6px 0;
            border-bottom: 1px solid var(--ds-gray-light);
            font-size: 12px;
        }}

        .feature-prop:last-child {{
            border-bottom: none;
        }}

        .feature-prop-key {{
            color: var(--ds-gray);
            font-size: 10px;
            text-transform: uppercase;
        }}

        .feature-prop-value {{
            color: var(--ds-navy);
            font-weight: 500;
            word-break: break-word;
        }}

        /* Map Controls Overlay */
        .map-info {{
            position: absolute;
            bottom: 30px;
            left: 10px;
            background: white;
            padding: 8px 14px;
            border-radius: 6px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            font-size: 11px;
            color: var(--ds-gray-dark);
            z-index: 1;
        }}

        .map-info span {{
            margin-right: 12px;
        }}

        /* Error state */
        .error-banner {{
            background: #FEF2F2;
            border: 1px solid #FECACA;
            color: #991B1B;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 16px;
            font-size: 12px;
        }}

        .error-banner strong {{
            display: block;
            margin-bottom: 4px;
        }}

        /* Links */
        .api-links {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 12px;
        }}

        .api-link {{
            font-size: 11px;
            padding: 4px 10px;
            background: var(--ds-gray-light);
            color: var(--ds-gray-dark);
            text-decoration: none;
            border-radius: 4px;
        }}

        .api-link:hover {{
            background: var(--ds-blue);
            color: white;
        }}

        /* Responsive */
        @media (max-width: 900px) {{
            .app-container {{
                flex-direction: column;
            }}
            .sidebar {{
                width: 100%;
                height: 40%;
            }}
            .map-container {{
                height: 60%;
            }}
        }}

        /* MapLibre popup override */
        .maplibregl-popup-content {{
            padding: 12px 16px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}

        .maplibregl-popup-close-button {{
            font-size: 18px;
            padding: 4px 8px;
        }}
    </style>
</head>
<body>
    <div class="app-container">
        <!-- Map Container -->
        <div class="map-container">
            <div id="map"></div>
            <div class="map-info">
                <span>Zoom: <strong id="zoom-level">--</strong></span>
                <span>Tiles: <strong id="tile-count">--</strong></span>
            </div>
        </div>

        <!-- Sidebar -->
        <div class="sidebar">
            <div class="sidebar-header">
                <h1>
                    <span>🗺️ Vector Tiles</span>
                    <span class="maplibre-badge">MapLibre GL</span>
                </h1>
                <div class="collection-id" id="collection-display">{collection_id or 'No collection specified'}</div>
            </div>

            <div class="sidebar-content">
                <!-- Status -->
                <div class="status-display">
                    <div class="status-icon" id="status-icon">⏳</div>
                    <div class="status-text">
                        <div class="status-label">Source Status</div>
                        <div class="status-value loading" id="status-value">Loading...</div>
                    </div>
                </div>

                <!-- Error Banner (hidden by default) -->
                <div class="error-banner" id="error-banner" style="display: none;">
                    <strong>Error Loading Tiles</strong>
                    <span id="error-message"></span>
                </div>

                <!-- Styling -->
                <div class="section-card">
                    <div class="section-header">Layer Styling</div>
                    <div class="section-body">
                        <div class="style-control">
                            <label>Fill Color</label>
                            <div class="color-row">
                                <input type="color" class="color-input" id="fill-color" value="#0071BC">
                                <input type="text" class="color-hex" id="fill-color-hex" value="#0071BC" readonly>
                            </div>
                        </div>

                        <div class="style-control">
                            <label>Fill Opacity</label>
                            <div class="slider-row">
                                <input type="range" class="slider-input" id="fill-opacity"
                                       min="0" max="1" step="0.05" value="0.4">
                                <span class="slider-value" id="fill-opacity-value">0.4</span>
                            </div>
                        </div>

                        <div class="style-control">
                            <label>Stroke Color</label>
                            <div class="color-row">
                                <input type="color" class="color-input" id="stroke-color" value="#053657">
                                <input type="text" class="color-hex" id="stroke-color-hex" value="#053657" readonly>
                            </div>
                        </div>

                        <div class="style-control">
                            <label>Stroke Width</label>
                            <div class="slider-row">
                                <input type="range" class="slider-input" id="stroke-width"
                                       min="0" max="5" step="0.5" value="1">
                                <span class="slider-value" id="stroke-width-value">1</span>
                            </div>
                        </div>

                        <button class="btn btn-primary" onclick="applyStyle()">
                            🎨 Apply Style
                        </button>
                    </div>
                </div>

                <!-- Navigation -->
                <div class="section-card">
                    <div class="section-header">Navigation</div>
                    <div class="section-body">
                        <div class="btn-row">
                            <button class="btn btn-secondary" onclick="zoomToExtent()">
                                📍 Zoom to Extent
                            </button>
                            <button class="btn btn-secondary" onclick="resetView()">
                                🌍 World View
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Feature Info -->
                <div class="section-card">
                    <div class="section-header">Feature Inspector</div>
                    <div class="section-body">
                        <div class="feature-info" id="feature-info">
                            <div class="feature-info-empty">
                                Click a feature on the map to inspect its properties
                            </div>
                        </div>
                    </div>
                </div>

                <!-- API Links -->
                <div class="section-card">
                    <div class="section-header">API Endpoints</div>
                    <div class="section-body">
                        <div class="api-links">
                            <a class="api-link" id="link-tilejson" href="#" target="_blank">TileJSON</a>
                            <a class="api-link" id="link-collection" href="#" target="_blank">Collection</a>
                            <a class="api-link" id="link-items" href="#" target="_blank">Items (GeoJSON)</a>
                            <a class="api-link" id="link-tipg-map" href="#" target="_blank">TiPG Viewer</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Configuration
        const COLLECTION_ID_RAW = '{collection_id}';
        const TITILER_BASE_URL = '{titiler_base_url}';
        const TIPG_BASE_URL = `${{TITILER_BASE_URL}}/vector`;

        // TiPG requires schema prefix (e.g., "geo.tablename")
        // Auto-prepend "geo." if collection doesn't already have a schema prefix
        const COLLECTION_ID = COLLECTION_ID_RAW.includes('.') ? COLLECTION_ID_RAW : `geo.${{COLLECTION_ID_RAW}}`;

        // TiPG endpoints with TileMatrixSet in path
        const TILEJSON_URL = `${{TIPG_BASE_URL}}/collections/${{COLLECTION_ID}}/tiles/WebMercatorQuad/tilejson.json`;
        const COLLECTION_URL = `${{TIPG_BASE_URL}}/collections/${{COLLECTION_ID}}`;
        const ITEMS_URL = `${{TIPG_BASE_URL}}/collections/${{COLLECTION_ID}}/items`;
        const TIPG_MAP_URL = `${{TIPG_BASE_URL}}/collections/${{COLLECTION_ID}}/tiles/WebMercatorQuad/map`;

        // Layer names
        const SOURCE_ID = 'vector-source';
        const FILL_LAYER_ID = 'vector-fill';
        const LINE_LAYER_ID = 'vector-line';
        const POINT_LAYER_ID = 'vector-point';

        // State
        let map = null;
        let tileJsonData = null;

        // Initialize map
        function initMap() {{
            map = new maplibregl.Map({{
                container: 'map',
                style: {{
                    version: 8,
                    sources: {{
                        'carto-light': {{
                            type: 'raster',
                            tiles: [
                                'https://a.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}@2x.png',
                                'https://b.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}@2x.png',
                                'https://c.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}@2x.png'
                            ],
                            tileSize: 256,
                            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
                        }}
                    }},
                    layers: [{{
                        id: 'carto-light-layer',
                        type: 'raster',
                        source: 'carto-light',
                        minzoom: 0,
                        maxzoom: 22
                    }}]
                }},
                center: [0, 20],
                zoom: 2
            }});

            // Add navigation controls
            map.addControl(new maplibregl.NavigationControl(), 'top-right');
            map.addControl(new maplibregl.ScaleControl(), 'bottom-right');

            // Update zoom display
            map.on('moveend', updateMapInfo);
            map.on('zoomend', updateMapInfo);

            // Wait for map to load, then add vector tiles
            map.on('load', () => {{
                if (COLLECTION_ID) {{
                    loadVectorTiles();
                }} else {{
                    setStatus('error', '❌', 'No collection specified');
                }}
            }});

            // Set up API links
            document.getElementById('link-tilejson').href = TILEJSON_URL;
            document.getElementById('link-collection').href = COLLECTION_URL;
            document.getElementById('link-items').href = ITEMS_URL + '?limit=10';
            document.getElementById('link-tipg-map').href = TIPG_MAP_URL;
        }}

        // Load vector tiles from TiPG
        async function loadVectorTiles() {{
            setStatus('loading', '⏳', 'Fetching TileJSON...');

            try {{
                // Fetch TileJSON
                const response = await fetch(TILEJSON_URL);
                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                }}

                tileJsonData = await response.json();
                console.log('TileJSON loaded:', tileJsonData);

                // Add vector tile source
                map.addSource(SOURCE_ID, {{
                    type: 'vector',
                    tiles: tileJsonData.tiles,
                    minzoom: tileJsonData.minzoom || 0,
                    maxzoom: tileJsonData.maxzoom || 22,
                    bounds: tileJsonData.bounds
                }});

                // TiPG uses "default" as the source-layer name for all collections
                const sourceLayer = 'default';

                // Add fill layer (for polygons)
                map.addLayer({{
                    id: FILL_LAYER_ID,
                    type: 'fill',
                    source: SOURCE_ID,
                    'source-layer': sourceLayer,
                    filter: ['==', ['geometry-type'], 'Polygon'],
                    paint: {{
                        'fill-color': '#0071BC',
                        'fill-opacity': 0.4
                    }}
                }});

                // Add line layer (for polygons outline and linestrings)
                map.addLayer({{
                    id: LINE_LAYER_ID,
                    type: 'line',
                    source: SOURCE_ID,
                    'source-layer': sourceLayer,
                    filter: ['any',
                        ['==', ['geometry-type'], 'Polygon'],
                        ['==', ['geometry-type'], 'LineString']
                    ],
                    paint: {{
                        'line-color': '#053657',
                        'line-width': 1
                    }}
                }});

                // Add point layer
                map.addLayer({{
                    id: POINT_LAYER_ID,
                    type: 'circle',
                    source: SOURCE_ID,
                    'source-layer': sourceLayer,
                    filter: ['==', ['geometry-type'], 'Point'],
                    paint: {{
                        'circle-color': '#0071BC',
                        'circle-radius': 6,
                        'circle-stroke-color': '#053657',
                        'circle-stroke-width': 1
                    }}
                }});

                // Add click handlers for feature inspection
                [FILL_LAYER_ID, LINE_LAYER_ID, POINT_LAYER_ID].forEach(layerId => {{
                    map.on('click', layerId, handleFeatureClick);
                    map.on('mouseenter', layerId, () => {{
                        map.getCanvas().style.cursor = 'pointer';
                    }});
                    map.on('mouseleave', layerId, () => {{
                        map.getCanvas().style.cursor = '';
                    }});
                }});

                // Zoom to bounds
                if (tileJsonData.bounds) {{
                    const [west, south, east, north] = tileJsonData.bounds;
                    map.fitBounds([[west, south], [east, north]], {{
                        padding: 50,
                        maxZoom: 14
                    }});
                }}

                setStatus('success', '✅', 'Vector tiles loaded');

            }} catch (error) {{
                console.error('Failed to load vector tiles:', error);
                setStatus('error', '❌', 'Failed to load');
                showError(error.message);
            }}
        }}

        // Handle feature click
        function handleFeatureClick(e) {{
            if (!e.features || e.features.length === 0) return;

            const feature = e.features[0];
            const properties = feature.properties || {{}};

            // Update sidebar
            const container = document.getElementById('feature-info');

            const propEntries = Object.entries(properties);
            if (propEntries.length === 0) {{
                container.innerHTML = '<div class="feature-info-empty">No properties available</div>';
                return;
            }}

            container.innerHTML = propEntries.map(([key, value]) => `
                <div class="feature-prop">
                    <div class="feature-prop-key">${{key}}</div>
                    <div class="feature-prop-value">${{value !== null ? value : 'null'}}</div>
                </div>
            `).join('');

            // Show popup on map
            const coordinates = e.lngLat;
            const popupContent = `
                <div style="max-height: 200px; overflow-y: auto;">
                    <strong style="color: #053657; font-size: 13px;">Feature Properties</strong>
                    <div style="margin-top: 8px; font-size: 12px;">
                        ${{propEntries.slice(0, 6).map(([k, v]) => `
                            <div style="padding: 3px 0; border-bottom: 1px solid #eee;">
                                <span style="color: #626F86; font-size: 10px; text-transform: uppercase;">${{k}}</span><br>
                                <span style="color: #053657;">${{v !== null ? v : 'null'}}</span>
                            </div>
                        `).join('')}}
                        ${{propEntries.length > 6 ? `<div style="color: #626F86; font-style: italic; padding-top: 4px;">+${{propEntries.length - 6}} more properties</div>` : ''}}
                    </div>
                </div>
            `;

            new maplibregl.Popup()
                .setLngLat(coordinates)
                .setHTML(popupContent)
                .addTo(map);
        }}

        // Apply style changes
        function applyStyle() {{
            if (!map.getLayer(FILL_LAYER_ID)) return;

            const fillColor = document.getElementById('fill-color').value;
            const fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
            const strokeColor = document.getElementById('stroke-color').value;
            const strokeWidth = parseFloat(document.getElementById('stroke-width').value);

            // Update fill layer
            map.setPaintProperty(FILL_LAYER_ID, 'fill-color', fillColor);
            map.setPaintProperty(FILL_LAYER_ID, 'fill-opacity', fillOpacity);

            // Update line layer
            map.setPaintProperty(LINE_LAYER_ID, 'line-color', strokeColor);
            map.setPaintProperty(LINE_LAYER_ID, 'line-width', strokeWidth);

            // Update point layer
            map.setPaintProperty(POINT_LAYER_ID, 'circle-color', fillColor);
            map.setPaintProperty(POINT_LAYER_ID, 'circle-stroke-color', strokeColor);
            map.setPaintProperty(POINT_LAYER_ID, 'circle-stroke-width', strokeWidth);
        }}

        // Zoom to layer extent
        function zoomToExtent() {{
            if (tileJsonData && tileJsonData.bounds) {{
                const [west, south, east, north] = tileJsonData.bounds;
                map.fitBounds([[west, south], [east, north]], {{
                    padding: 50,
                    maxZoom: 14
                }});
            }}
        }}

        // Reset to world view
        function resetView() {{
            map.flyTo({{
                center: [0, 20],
                zoom: 2
            }});
        }}

        // Update map info display
        function updateMapInfo() {{
            document.getElementById('zoom-level').textContent = map.getZoom().toFixed(1);

            // Count visible tiles (approximate)
            const zoom = Math.floor(map.getZoom());
            const bounds = map.getBounds();
            const tileCount = estimateTileCount(bounds, zoom);
            document.getElementById('tile-count').textContent = tileCount;
        }}

        // Estimate visible tile count
        function estimateTileCount(bounds, zoom) {{
            const n = Math.pow(2, zoom);
            const west = ((bounds.getWest() + 180) / 360) * n;
            const east = ((bounds.getEast() + 180) / 360) * n;
            const north = (1 - Math.log(Math.tan(bounds.getNorth() * Math.PI / 180) + 1 / Math.cos(bounds.getNorth() * Math.PI / 180)) / Math.PI) / 2 * n;
            const south = (1 - Math.log(Math.tan(bounds.getSouth() * Math.PI / 180) + 1 / Math.cos(bounds.getSouth() * Math.PI / 180)) / Math.PI) / 2 * n;

            const xTiles = Math.ceil(east) - Math.floor(west);
            const yTiles = Math.ceil(south) - Math.floor(north);
            return Math.max(1, xTiles * yTiles);
        }}

        // Set status display
        function setStatus(type, icon, message) {{
            const iconEl = document.getElementById('status-icon');
            const valueEl = document.getElementById('status-value');

            iconEl.textContent = icon;
            valueEl.textContent = message;
            valueEl.className = 'status-value ' + type;
        }}

        // Show error banner
        function showError(message) {{
            const banner = document.getElementById('error-banner');
            document.getElementById('error-message').textContent = message;
            banner.style.display = 'block';
        }}

        // Sync color inputs
        document.getElementById('fill-color').addEventListener('input', (e) => {{
            document.getElementById('fill-color-hex').value = e.target.value;
        }});
        document.getElementById('stroke-color').addEventListener('input', (e) => {{
            document.getElementById('stroke-color-hex').value = e.target.value;
        }});

        // Sync slider values
        document.getElementById('fill-opacity').addEventListener('input', (e) => {{
            document.getElementById('fill-opacity-value').textContent = e.target.value;
        }});
        document.getElementById('stroke-width').addEventListener('input', (e) => {{
            document.getElementById('stroke-width-value').textContent = e.target.value;
        }});

        // Initialize on load
        document.addEventListener('DOMContentLoaded', () => {{
            // Update collection display if prefix was added
            if (COLLECTION_ID !== COLLECTION_ID_RAW) {{
                document.getElementById('collection-display').textContent = COLLECTION_ID;
            }}
            initMap();
        }});

        console.log('MapLibre Vector Tiles Viewer initialized');
        console.log('Collection:', COLLECTION_ID);
        console.log('TiPG Base URL:', TIPG_BASE_URL);
    </script>
</body>
</html>'''


# Export for testing
__all__ = ['VectorTilesInterface']
