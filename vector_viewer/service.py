# ============================================================================
# CLAUDE CONTEXT - VECTOR VIEWER SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service Layer - HTML generation and OGC Features API integration
# PURPOSE: Generate dynamic HTML viewer pages for PostGIS vector collections
# LAST_REVIEWED: 13 NOV 2025
# EXPORTS: VectorViewerService
# INTERFACES: Standalone service class
# PYDANTIC_MODELS: None (works with raw JSON)
# DEPENDENCIES: requests, json, typing
# SOURCE: OGC Features API endpoints for collection data
# SCOPE: HTML generation for vector geometry visualization
# VALIDATION: Basic parameter validation
# PATTERNS: Service Layer, Template Pattern
# ENTRY_POINTS: VectorViewerService.generate_viewer_html()
# INDEX: VectorViewerService:40, generate_viewer_html:80, _generate_html_template:150
# ============================================================================

"""
Vector Viewer Service - HTML Generation and OGC Features Data Fetching

Responsible for:
1. Fetching vector collection metadata from OGC Features API
2. Generating self-contained HTML viewer pages
3. Embedding collection info and feature query endpoints

Author: Robert and Geospatial Claude Legion
Date: 13 NOV 2025
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

    def generate_viewer_html(self, collection_id: str, host_url: Optional[str] = None) -> str:
        """
        Generate HTML viewer page for a vector collection.

        Args:
            collection_id: OGC Features collection ID (PostGIS table name)
            host_url: Optional host URL for absolute API paths

        Returns:
            Complete HTML page as string

        Raises:
            ValueError: If collection_id is missing
            requests.HTTPError: If OGC Features API request fails
        """
        if not collection_id:
            raise ValueError("collection_id is required")

        logger.info(f"Generating viewer for collection={collection_id}")

        # Fetch collection metadata
        collection_data = self._fetch_collection_metadata(collection_id, host_url)

        # Generate HTML with embedded data
        html = self._generate_html_template(collection_data, collection_id, host_url)

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

    def _generate_html_template(self, collection_data: Dict[str, Any], collection_id: str, host_url: Optional[str] = None) -> str:
        """
        Generate HTML template with embedded collection data.

        Args:
            collection_data: OGC Features collection metadata
            collection_id: Collection ID for display
            host_url: Optional host URL for API calls

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

        # Build items API URL
        if host_url:
            items_url = f"{host_url}{self.ogc_api_base_url}/collections/{collection_id}/items"
        else:
            items_url = f"{self.ogc_api_base_url}/collections/{collection_id}/items"

        # Generate HTML
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
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
        }}

        #map {{
            height: 100vh;
            width: 100%;
        }}

        /* Metadata Panel */
        .metadata-panel {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 1000;
            max-width: 350px;
            max-height: 90vh;
            overflow-y: auto;
        }}

        .metadata-panel h3 {{
            margin: 0 0 10px 0;
            font-size: 16px;
            color: #333;
            border-bottom: 2px solid #3388ff;
            padding-bottom: 5px;
        }}

        .metadata-row {{
            margin-bottom: 8px;
            font-size: 13px;
        }}

        .metadata-label {{
            font-weight: 600;
            color: #555;
            display: inline-block;
            width: 100px;
        }}

        .metadata-value {{
            color: #333;
            word-break: break-word;
        }}

        .bbox-display {{
            font-family: monospace;
            font-size: 11px;
            background: #f0f0f0;
            padding: 5px;
            border-radius: 4px;
            margin-top: 5px;
        }}

        .info-badge {{
            display: inline-block;
            padding: 3px 8px;
            background: #3388ff;
            color: white;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
        }}

        .load-button {{
            width: 100%;
            padding: 8px;
            background: #3388ff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            margin-top: 10px;
        }}

        .load-button:hover {{
            background: #2266dd;
        }}

        .load-button:disabled {{
            background: #ccc;
            cursor: not-allowed;
        }}

        .status-text {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <!-- Map Container -->
    <div id="map"></div>

    <!-- Metadata Panel -->
    <div class="metadata-panel">
        <h3>📍 Vector Viewer</h3>

        <div class="metadata-row">
            <span class="metadata-label">Collection:</span>
            <span class="metadata-value">{collection_id}</span>
        </div>

        <div class="metadata-row">
            <span class="metadata-label">Title:</span>
            <span class="metadata-value">{title}</span>
        </div>

        <div class="metadata-row">
            <span class="metadata-label">Description:</span>
            <span class="metadata-value">{description}</span>
        </div>

        <div class="metadata-row">
            <span class="metadata-label">Bounding Box:</span>
            <div class="bbox-display">
                min: [{bbox[0]:.6f}, {bbox[1]:.6f}]<br>
                max: [{bbox[2]:.6f}, {bbox[3]:.6f}]
            </div>
        </div>

        <button class="load-button" onclick="loadFeatures(100)">Load 100 Features</button>
        <button class="load-button" onclick="loadFeatures(500)">Load 500 Features</button>
        <div class="status-text" id="status">Ready to load features</div>

        <div class="metadata-row" style="margin-top: 10px;">
            <span class="info-badge">Vector Data QA</span>
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
        const BBOX = {json.dumps(bbox)};

        // Initialize map
        const map = L.map('map').setView([{center_lat}, {center_lon}], 6);

        // Add OpenStreetMap base layer
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        }}).addTo(map);

        // GeoJSON layer for features
        let featureLayer = null;

        // Load features from OGC Features API
        async function loadFeatures(limit) {{
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = `Loading ${{limit}} features...`;

            try {{
                const response = await fetch(`${{ITEMS_URL}}?limit=${{limit}}`);
                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                }}

                const data = await response.json();
                const features = data.features || [];

                statusDiv.textContent = `Loaded ${{features.length}} features`;

                // Remove existing layer
                if (featureLayer) {{
                    map.removeLayer(featureLayer);
                }}

                // Add features to map
                featureLayer = L.geoJSON(data, {{
                    style: function(feature) {{
                        return {{
                            color: '#3388ff',
                            weight: 2,
                            fillOpacity: 0.3,
                            fillColor: '#3388ff'
                        }};
                    }},
                    onEachFeature: function(feature, layer) {{
                        // Create popup with properties
                        const props = feature.properties || {{}};
                        let popupContent = '<div style="font-size: 13px; max-width: 250px;"><b>Properties</b><br>';

                        // Show first 5 properties
                        const keys = Object.keys(props).slice(0, 5);
                        keys.forEach(key => {{
                            const value = props[key];
                            if (value !== null && value !== undefined) {{
                                popupContent += `<b>${{key}}:</b> ${{value}}<br>`;
                            }}
                        }});

                        if (Object.keys(props).length > 5) {{
                            popupContent += `<i>...and ${{Object.keys(props).length - 5}} more</i>`;
                        }}
                        popupContent += '</div>';

                        layer.bindPopup(popupContent);
                    }}
                }}).addTo(map);

                // Zoom to features
                if (featureLayer.getBounds().isValid()) {{
                    map.fitBounds(featureLayer.getBounds(), {{ padding: [50, 50] }});
                }} else if (BBOX && BBOX.length >= 4) {{
                    // Fallback to collection bbox
                    const bounds = [
                        [BBOX[1], BBOX[0]],
                        [BBOX[3], BBOX[2]]
                    ];
                    map.fitBounds(bounds, {{ padding: [50, 50] }});
                }}

                console.log(`Loaded ${{features.length}} features from ${{COLLECTION_ID}}`);
            }} catch (error) {{
                statusDiv.textContent = `Error: ${{error.message}}`;
                console.error('Failed to load features:', error);
            }}
        }}

        console.log('Vector Viewer initialized');
        console.log('Collection:', COLLECTION_ID);
        console.log('Items URL:', ITEMS_URL);
    </script>
</body>
</html>"""

        return html
