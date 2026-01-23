# ============================================================================
# SERVICE PREVIEW INTERFACE
# ============================================================================
# STATUS: Web Interface - Map preview for external geospatial services
# PURPOSE: Display external services (ArcGIS, WMS, etc.) on a Leaflet map
# CREATED: 23 JAN 2026
# ============================================================================
"""
Service Preview Interface - Full-page map for external service preview.

Displays registered external services on an interactive Leaflet map.
Supports ArcGIS (MapServer, FeatureServer, ImageServer), WMS, WMTS, XYZ tiles.

URL: /api/interface/service-preview?service_id={id}
     /api/interface/service-preview?type={type}&url={url}&name={name}
"""

import json
from urllib.parse import unquote
import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface


@InterfaceRegistry.register('service-preview')
class ServicePreviewInterface(BaseInterface):
    """
    Full-page map interface for previewing external geospatial services.

    Loads service from database by ID or accepts direct URL parameters.
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate the full page HTML with Leaflet map."""
        # Get service info either from database or URL params
        service_info = self._get_service_info(request)

        if service_info.get('error'):
            return self._render_error(service_info['error'])

        return self._render_map_page(service_info)

    def _get_service_info(self, request: func.HttpRequest) -> dict:
        """Get service information from database or URL parameters."""
        service_id = request.params.get('service_id')

        if service_id:
            # Load from database
            try:
                from infrastructure.external_service_repository import ExternalServiceRepository
                repository = ExternalServiceRepository()
                svc = repository.get_by_id(service_id)

                if not svc:
                    return {'error': f'Service not found: {service_id}'}

                service_type = svc.service_type.value if hasattr(svc.service_type, 'value') else svc.service_type

                return {
                    'service_id': svc.service_id,
                    'name': svc.name,
                    'url': svc.url,
                    'type': service_type,
                    'description': svc.description,
                    'capabilities': svc.detected_capabilities or {},
                    'status': svc.status.value if hasattr(svc.status, 'value') else svc.status
                }
            except Exception as e:
                return {'error': f'Error loading service: {str(e)}'}
        else:
            # Use URL parameters directly
            url = request.params.get('url')
            service_type = request.params.get('type', 'unknown')
            name = request.params.get('name', 'External Service')

            if not url:
                return {'error': 'Either service_id or url parameter is required'}

            return {
                'service_id': None,
                'name': unquote(name),
                'url': unquote(url),
                'type': service_type,
                'description': None,
                'capabilities': {},
                'status': 'unknown'
            }

    def _render_error(self, error_message: str) -> str:
        """Render an error page."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Service Preview - Error</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f5;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                }}
                .error-box {{
                    background: white;
                    padding: 40px;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    text-align: center;
                    max-width: 500px;
                }}
                h1 {{ color: #dc2626; margin-bottom: 20px; }}
                p {{ color: #666; margin-bottom: 20px; }}
                a {{ color: #0071bc; }}
            </style>
        </head>
        <body>
            <div class="error-box">
                <h1>Preview Error</h1>
                <p>{error_message}</p>
                <a href="/api/interface/external-services">Back to Service Registry</a>
            </div>
        </body>
        </html>
        """

    def _render_map_page(self, service_info: dict) -> str:
        """Render the full-page map interface."""
        service_type = service_info['type']
        service_url = service_info['url']
        service_name = service_info['name']
        capabilities = service_info.get('capabilities', {})

        # Determine which libraries to load
        needs_esri = service_type in ['arcgis_mapserver', 'arcgis_featureserver', 'arcgis_imageserver']

        # Get layer info for ArcGIS services
        layers_info = self._get_layers_info(service_type, capabilities)

        # Generate the JavaScript for loading the service
        layer_js = self._generate_layer_js(service_type, service_url, capabilities)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Preview: {service_name}</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">

            <!-- Leaflet CSS -->
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
                  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />

            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}

                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }}

                /* Header bar */
                .header {{
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    height: 60px;
                    background: #1a365d;
                    color: white;
                    display: flex;
                    align-items: center;
                    padding: 0 20px;
                    z-index: 1000;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                }}

                .header-back {{
                    color: white;
                    text-decoration: none;
                    font-size: 24px;
                    margin-right: 20px;
                    opacity: 0.8;
                }}

                .header-back:hover {{
                    opacity: 1;
                }}

                .header-title {{
                    flex: 1;
                }}

                .header-title h1 {{
                    font-size: 18px;
                    font-weight: 600;
                    margin-bottom: 2px;
                }}

                .header-title .subtitle {{
                    font-size: 12px;
                    opacity: 0.7;
                }}

                .header-badge {{
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                    margin-left: 15px;
                }}

                .badge-arcgis {{ background: #0369a1; }}
                .badge-wms {{ background: #b45309; }}
                .badge-wmts {{ background: #b45309; }}
                .badge-xyz {{ background: #be185d; }}
                .badge-wfs {{ background: #047857; }}
                .badge-stac {{ background: #6d28d9; }}
                .badge-unknown {{ background: #6b7280; }}

                .header-actions {{
                    display: flex;
                    gap: 10px;
                }}

                .header-btn {{
                    padding: 8px 16px;
                    border: 1px solid rgba(255,255,255,0.3);
                    background: transparent;
                    color: white;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 13px;
                    transition: all 0.2s;
                }}

                .header-btn:hover {{
                    background: rgba(255,255,255,0.1);
                    border-color: rgba(255,255,255,0.5);
                }}

                /* Map container */
                #map {{
                    position: fixed;
                    top: 60px;
                    left: 0;
                    right: 0;
                    bottom: 0;
                }}

                /* Layer control panel */
                .layer-panel {{
                    position: fixed;
                    top: 80px;
                    right: 20px;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.15);
                    z-index: 1000;
                    max-width: 300px;
                    max-height: calc(100vh - 120px);
                    overflow-y: auto;
                }}

                .layer-panel.collapsed {{
                    max-height: 40px;
                    overflow: hidden;
                }}

                .layer-panel-header {{
                    padding: 12px 15px;
                    background: #f8fafc;
                    border-bottom: 1px solid #e2e8f0;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    cursor: pointer;
                    border-radius: 8px 8px 0 0;
                }}

                .layer-panel.collapsed .layer-panel-header {{
                    border-bottom: none;
                    border-radius: 8px;
                }}

                .layer-panel-header h3 {{
                    font-size: 13px;
                    font-weight: 600;
                    color: #1a365d;
                    margin: 0;
                }}

                .layer-panel-toggle {{
                    font-size: 12px;
                    color: #64748b;
                }}

                .layer-panel-body {{
                    padding: 15px;
                }}

                .layer-item {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 8px 0;
                    border-bottom: 1px solid #f1f5f9;
                }}

                .layer-item:last-child {{
                    border-bottom: none;
                }}

                .layer-item input {{
                    cursor: pointer;
                }}

                .layer-item label {{
                    font-size: 13px;
                    color: #334155;
                    cursor: pointer;
                    flex: 1;
                }}

                /* Info panel */
                .info-panel {{
                    position: fixed;
                    bottom: 20px;
                    left: 20px;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.15);
                    padding: 15px;
                    z-index: 1000;
                    max-width: 350px;
                    font-size: 12px;
                }}

                .info-panel h4 {{
                    font-size: 13px;
                    color: #1a365d;
                    margin: 0 0 10px 0;
                }}

                .info-row {{
                    display: flex;
                    margin-bottom: 6px;
                }}

                .info-row label {{
                    width: 80px;
                    color: #64748b;
                    flex-shrink: 0;
                }}

                .info-row span {{
                    color: #334155;
                    word-break: break-all;
                }}

                .info-url {{
                    font-family: monospace;
                    font-size: 10px;
                    background: #f1f5f9;
                    padding: 2px 4px;
                    border-radius: 3px;
                }}

                /* Loading overlay */
                .loading-overlay {{
                    position: fixed;
                    top: 60px;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: rgba(255,255,255,0.9);
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    z-index: 999;
                }}

                .loading-overlay.hidden {{
                    display: none;
                }}

                .spinner {{
                    width: 40px;
                    height: 40px;
                    border: 3px solid #e2e8f0;
                    border-top-color: #0071bc;
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                }}

                @keyframes spin {{
                    to {{ transform: rotate(360deg); }}
                }}

                .loading-text {{
                    margin-top: 15px;
                    color: #64748b;
                    font-size: 14px;
                }}

                /* Error message */
                .map-error {{
                    position: fixed;
                    top: 80px;
                    left: 50%;
                    transform: translateX(-50%);
                    background: #fee2e2;
                    color: #b91c1c;
                    padding: 12px 20px;
                    border-radius: 6px;
                    z-index: 1001;
                    font-size: 14px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}

                .map-error.hidden {{
                    display: none;
                }}
            </style>
        </head>
        <body>
            <!-- Header -->
            <header class="header">
                <a href="/api/interface/external-services" class="header-back" title="Back to registry">&larr;</a>
                <div class="header-title">
                    <h1>{service_name}</h1>
                    <span class="subtitle">{self._truncate_url(service_url, 60)}</span>
                </div>
                <span class="header-badge badge-{self._get_badge_class(service_type)}">{self._format_type(service_type)}</span>
                <div class="header-actions">
                    <button class="header-btn" onclick="resetView()">Reset View</button>
                    <button class="header-btn" onclick="window.open('{service_url}', '_blank')">Open URL</button>
                </div>
            </header>

            <!-- Map -->
            <div id="map"></div>

            <!-- Loading overlay -->
            <div id="loading" class="loading-overlay">
                <div class="spinner"></div>
                <div class="loading-text">Loading service...</div>
            </div>

            <!-- Error message -->
            <div id="map-error" class="map-error hidden"></div>

            <!-- Layer panel (for services with multiple layers) -->
            {self._render_layer_panel(service_type, capabilities)}

            <!-- Info panel -->
            <div class="info-panel">
                <h4>Service Info</h4>
                <div class="info-row">
                    <label>Type:</label>
                    <span>{self._format_type(service_type)}</span>
                </div>
                <div class="info-row">
                    <label>URL:</label>
                    <span class="info-url">{self._truncate_url(service_url, 40)}</span>
                </div>
                {f'<div class="info-row"><label>Layers:</label><span>{len(layers_info)} available</span></div>' if layers_info else ''}
            </div>

            <!-- Leaflet JS -->
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
                    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>

            <!-- Esri Leaflet (for ArcGIS services) -->
            {'<script src="https://unpkg.com/esri-leaflet@3.0.12/dist/esri-leaflet.js"></script>' if needs_esri else ''}

            <script>
                // Initialize map
                const map = L.map('map').setView([20, 0], 2);

                // Add base layer
                L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                    subdomains: 'abcd',
                    maxZoom: 20
                }}).addTo(map);

                // Service layer variable
                let serviceLayer = null;
                let serviceLayers = {{}};

                // Service info
                const serviceUrl = "{service_url}";
                const serviceType = "{service_type}";

                // Hide loading
                function hideLoading() {{
                    document.getElementById('loading').classList.add('hidden');
                }}

                // Show error
                function showError(message) {{
                    const errorEl = document.getElementById('map-error');
                    errorEl.textContent = message;
                    errorEl.classList.remove('hidden');
                    hideLoading();
                }}

                // Reset view
                function resetView() {{
                    map.setView([20, 0], 2);
                }}

                // Toggle layer panel
                function toggleLayerPanel() {{
                    document.querySelector('.layer-panel')?.classList.toggle('collapsed');
                }}

                // Toggle individual layer
                function toggleLayer(layerId, checkbox) {{
                    if (checkbox.checked) {{
                        if (serviceLayers[layerId]) {{
                            serviceLayers[layerId].addTo(map);
                        }}
                    }} else {{
                        if (serviceLayers[layerId]) {{
                            map.removeLayer(serviceLayers[layerId]);
                        }}
                    }}
                }}

                // Load the service layer
                {layer_js}
            </script>
        </body>
        </html>
        """

    def _generate_layer_js(self, service_type: str, url: str, capabilities: dict) -> str:
        """Generate JavaScript code to load the service layer."""

        if service_type == 'arcgis_mapserver':
            return f"""
                try {{
                    serviceLayer = L.esri.dynamicMapLayer({{
                        url: serviceUrl,
                        opacity: 0.8
                    }}).addTo(map);

                    serviceLayer.on('load', function() {{
                        hideLoading();
                    }});

                    serviceLayer.on('error', function(e) {{
                        showError('Error loading MapServer: ' + (e.error?.message || 'Unknown error'));
                    }});

                    // Try to get metadata for bounds
                    serviceLayer.metadata(function(error, metadata) {{
                        if (!error && metadata && metadata.fullExtent) {{
                            const ext = metadata.fullExtent;
                            if (ext.xmin && ext.ymin && ext.xmax && ext.ymax) {{
                                map.fitBounds([[ext.ymin, ext.xmin], [ext.ymax, ext.xmax]]);
                            }}
                        }}
                    }});
                }} catch (e) {{
                    showError('Error initializing MapServer layer: ' + e.message);
                }}
            """

        elif service_type == 'arcgis_featureserver':
            # For FeatureServer, we typically need to add /0 or specific layer index
            layers = capabilities.get('layers', [])
            if layers:
                # Load each layer
                layer_code = []
                for i, layer in enumerate(layers[:5]):  # Limit to first 5 layers
                    layer_name = layer.get('name', f'Layer {i}') if isinstance(layer, dict) else str(layer)
                    layer_id = layer.get('id', i) if isinstance(layer, dict) else i
                    layer_code.append(f"""
                    try {{
                        serviceLayers['{layer_id}'] = L.esri.featureLayer({{
                            url: serviceUrl + '/{layer_id}',
                            style: function() {{
                                return {{ color: '#{self._get_layer_color(i)}', weight: 2, fillOpacity: 0.3 }};
                            }}
                        }});
                        {'serviceLayers[\\''+str(layer_id)+'\\'].addTo(map);' if i == 0 else ''}

                        serviceLayers['{layer_id}'].on('load', function() {{
                            hideLoading();
                        }});
                    }} catch (e) {{
                        console.error('Error loading layer {layer_id}:', e);
                    }}
                    """)
                return '\n'.join(layer_code) + """

                    // Fit to first layer bounds after a delay
                    setTimeout(function() {
                        const firstLayer = Object.values(serviceLayers)[0];
                        if (firstLayer && firstLayer.getBounds) {
                            try {
                                const bounds = firstLayer.getBounds();
                                if (bounds.isValid()) {
                                    map.fitBounds(bounds);
                                }
                            } catch(e) {}
                        }
                        hideLoading();
                    }, 2000);
                """
            else:
                # Try loading as single layer (append /0)
                return """
                try {
                    serviceLayer = L.esri.featureLayer({
                        url: serviceUrl + '/0',
                        style: function() {
                            return { color: '#0071bc', weight: 2, fillOpacity: 0.3 };
                        }
                    }).addTo(map);

                    serviceLayer.on('load', function() {
                        hideLoading();
                        try {
                            const bounds = serviceLayer.getBounds();
                            if (bounds.isValid()) {
                                map.fitBounds(bounds);
                            }
                        } catch(e) {}
                    });

                    serviceLayer.on('error', function(e) {
                        showError('Error loading FeatureServer: ' + (e.error?.message || 'Unknown error'));
                    });
                } catch (e) {
                    showError('Error initializing FeatureServer layer: ' + e.message);
                }
                """

        elif service_type == 'arcgis_imageserver':
            return """
                try {
                    serviceLayer = L.esri.imageMapLayer({
                        url: serviceUrl,
                        opacity: 0.8
                    }).addTo(map);

                    serviceLayer.on('load', function() {
                        hideLoading();
                    });

                    serviceLayer.on('error', function(e) {
                        showError('Error loading ImageServer: ' + (e.error?.message || 'Unknown error'));
                    });

                    // Try to get metadata for bounds
                    serviceLayer.metadata(function(error, metadata) {
                        if (!error && metadata && metadata.extent) {
                            const ext = metadata.extent;
                            if (ext.xmin && ext.ymin && ext.xmax && ext.ymax) {
                                map.fitBounds([[ext.ymin, ext.xmin], [ext.ymax, ext.xmax]]);
                            }
                        }
                    });
                } catch (e) {
                    showError('Error initializing ImageServer layer: ' + e.message);
                }
            """

        elif service_type == 'wms':
            # Get layer name from capabilities or use first available
            layers = capabilities.get('layers', ['0'])
            layer_name = layers[0] if layers else '0'
            if isinstance(layer_name, dict):
                layer_name = layer_name.get('name', '0')

            return f"""
                try {{
                    serviceLayer = L.tileLayer.wms(serviceUrl, {{
                        layers: '{layer_name}',
                        format: 'image/png',
                        transparent: true,
                        attribution: 'WMS Service'
                    }}).addTo(map);

                    hideLoading();
                }} catch (e) {{
                    showError('Error loading WMS layer: ' + e.message);
                }}
            """

        elif service_type == 'wmts':
            return """
                try {
                    // WMTS typically needs specific layer/matrix configuration
                    // This is a simplified approach using tile URL pattern
                    serviceLayer = L.tileLayer(serviceUrl + '/{z}/{x}/{y}.png', {
                        attribution: 'WMTS Service'
                    }).addTo(map);

                    hideLoading();
                } catch (e) {
                    showError('Error loading WMTS layer: ' + e.message);
                }
            """

        elif service_type in ['xyz_tiles', 'tms_tiles']:
            return """
                try {
                    serviceLayer = L.tileLayer(serviceUrl, {
                        attribution: 'Tile Service'
                    }).addTo(map);

                    hideLoading();
                } catch (e) {
                    showError('Error loading tile layer: ' + e.message);
                }
            """

        elif service_type == 'wfs':
            return """
                try {
                    // WFS - fetch GeoJSON and display
                    const wfsUrl = serviceUrl + '?service=WFS&version=1.1.0&request=GetFeature&outputFormat=application/json&srsname=EPSG:4326';

                    fetch(wfsUrl)
                        .then(response => {
                            if (!response.ok) throw new Error('WFS request failed');
                            return response.json();
                        })
                        .then(geojson => {
                            serviceLayer = L.geoJSON(geojson, {
                                style: { color: '#0071bc', weight: 2, fillOpacity: 0.3 }
                            }).addTo(map);

                            if (serviceLayer.getBounds().isValid()) {
                                map.fitBounds(serviceLayer.getBounds());
                            }
                            hideLoading();
                        })
                        .catch(e => {
                            showError('Error loading WFS: ' + e.message);
                        });
                } catch (e) {
                    showError('Error initializing WFS layer: ' + e.message);
                }
            """

        elif service_type == 'ogc_api_features':
            return """
                try {
                    // OGC API Features - fetch items as GeoJSON
                    const itemsUrl = serviceUrl + '/items?f=json&limit=1000';

                    fetch(itemsUrl)
                        .then(response => {
                            if (!response.ok) throw new Error('OGC API request failed');
                            return response.json();
                        })
                        .then(geojson => {
                            serviceLayer = L.geoJSON(geojson, {
                                style: { color: '#047857', weight: 2, fillOpacity: 0.3 }
                            }).addTo(map);

                            if (serviceLayer.getBounds().isValid()) {
                                map.fitBounds(serviceLayer.getBounds());
                            }
                            hideLoading();
                        })
                        .catch(e => {
                            showError('Error loading OGC API Features: ' + e.message);
                        });
                } catch (e) {
                    showError('Error initializing OGC API layer: ' + e.message);
                }
            """

        elif service_type == 'stac_api':
            return """
                try {
                    // STAC API - show collection footprints
                    fetch(serviceUrl + '/collections')
                        .then(response => response.json())
                        .then(data => {
                            const collections = data.collections || [];
                            const features = collections
                                .filter(c => c.extent?.spatial?.bbox)
                                .map(c => {
                                    const bbox = c.extent.spatial.bbox[0];
                                    return {
                                        type: 'Feature',
                                        properties: { title: c.title || c.id },
                                        geometry: {
                                            type: 'Polygon',
                                            coordinates: [[
                                                [bbox[0], bbox[1]],
                                                [bbox[2], bbox[1]],
                                                [bbox[2], bbox[3]],
                                                [bbox[0], bbox[3]],
                                                [bbox[0], bbox[1]]
                                            ]]
                                        }
                                    };
                                });

                            if (features.length > 0) {
                                serviceLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
                                    style: { color: '#6d28d9', weight: 2, fillOpacity: 0.2 },
                                    onEachFeature: function(feature, layer) {
                                        layer.bindPopup('<strong>' + feature.properties.title + '</strong>');
                                    }
                                }).addTo(map);

                                map.fitBounds(serviceLayer.getBounds());
                            }
                            hideLoading();
                        })
                        .catch(e => {
                            showError('Error loading STAC API: ' + e.message);
                        });
                } catch (e) {
                    showError('Error initializing STAC layer: ' + e.message);
                }
            """

        else:
            return """
                showError('Preview not supported for service type: """ + service_type + """');
            """

    def _render_layer_panel(self, service_type: str, capabilities: dict) -> str:
        """Render the layer selection panel for multi-layer services."""
        layers = capabilities.get('layers', [])

        if not layers or service_type not in ['arcgis_featureserver', 'arcgis_mapserver', 'wms']:
            return ''

        layer_items = []
        for i, layer in enumerate(layers[:10]):  # Limit to 10 layers
            if isinstance(layer, dict):
                layer_name = layer.get('name', f'Layer {i}')
                layer_id = layer.get('id', i)
            else:
                layer_name = str(layer)
                layer_id = i

            checked = 'checked' if i == 0 else ''
            layer_items.append(f'''
                <div class="layer-item">
                    <input type="checkbox" id="layer-{layer_id}" {checked}
                           onchange="toggleLayer('{layer_id}', this)">
                    <label for="layer-{layer_id}">{layer_name}</label>
                </div>
            ''')

        return f'''
            <div class="layer-panel">
                <div class="layer-panel-header" onclick="toggleLayerPanel()">
                    <h3>Layers ({len(layers)})</h3>
                    <span class="layer-panel-toggle">&#9660;</span>
                </div>
                <div class="layer-panel-body">
                    {''.join(layer_items)}
                </div>
            </div>
        '''

    def _get_layers_info(self, service_type: str, capabilities: dict) -> list:
        """Extract layer information from capabilities."""
        return capabilities.get('layers', [])

    def _get_badge_class(self, service_type: str) -> str:
        """Get CSS badge class for service type."""
        if service_type.startswith('arcgis'):
            return 'arcgis'
        elif service_type in ['wms', 'wmts', 'wfs']:
            return service_type
        elif service_type in ['xyz_tiles', 'tms_tiles']:
            return 'xyz'
        elif service_type == 'stac_api':
            return 'stac'
        return 'unknown'

    def _format_type(self, service_type: str) -> str:
        """Format service type for display."""
        type_labels = {
            'arcgis_mapserver': 'ArcGIS Map',
            'arcgis_featureserver': 'ArcGIS Feature',
            'arcgis_imageserver': 'ArcGIS Image',
            'wms': 'WMS',
            'wfs': 'WFS',
            'wmts': 'WMTS',
            'ogc_api_features': 'OGC Features',
            'ogc_api_tiles': 'OGC Tiles',
            'stac_api': 'STAC',
            'xyz_tiles': 'XYZ Tiles',
            'tms_tiles': 'TMS Tiles',
            'cog_endpoint': 'COG',
            'generic_rest': 'REST',
            'unknown': 'Unknown'
        }
        return type_labels.get(service_type, service_type)

    def _truncate_url(self, url: str, max_length: int = 50) -> str:
        """Truncate URL for display."""
        if len(url) <= max_length:
            return url
        return url[:max_length - 3] + '...'

    def _get_layer_color(self, index: int) -> str:
        """Get a color for a layer based on index."""
        colors = ['0071bc', '059669', 'd97706', '7c3aed', 'dc2626', '0891b2', 'be185d', '4f46e5']
        return colors[index % len(colors)]
