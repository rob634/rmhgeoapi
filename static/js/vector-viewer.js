/**
 * Vector Viewer JavaScript
 *
 * MapLibre-based viewer for vector data with MVT tiles and GeoJSON support.
 * Provides collection browsing, styling controls, feature inspection, and QA workflow.
 */

// ============================================================================
// GLOBAL STATE
// ============================================================================

let map = null;
let currentCollection = null;
let currentMode = 'mvt';  // 'mvt' or 'geojson'
let geojsonData = null;
let tileJsonData = null;

// Layer IDs
const SOURCE_ID = 'vector-source';
const GEOJSON_SOURCE_ID = 'geojson-source';
const FILL_LAYER_ID = 'vector-fill';
const LINE_LAYER_ID = 'vector-line';
const POINT_LAYER_ID = 'vector-point';
const GEOJSON_FILL_LAYER_ID = 'geojson-fill';
const GEOJSON_LINE_LAYER_ID = 'geojson-line';
const GEOJSON_POINT_LAYER_ID = 'geojson-point';

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeMap();

    if (CONFIG.collectionId) {
        loadCollectionData();
    } else {
        loadCollectionsList();
    }
});

function initializeMap() {
    map = new maplibregl.Map({
        container: 'map',
        style: {
            version: 8,
            sources: {
                'carto-light': {
                    type: 'raster',
                    tiles: [
                        'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
                        'https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png',
                        'https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png'
                    ],
                    tileSize: 256,
                    attribution: '&copy; <a href="https://carto.com/">CARTO</a>'
                }
            },
            layers: [{
                id: 'carto-light-layer',
                type: 'raster',
                source: 'carto-light',
                minzoom: 0,
                maxzoom: 22
            }]
        },
        center: [0, 20],
        zoom: 2
    });

    // Add navigation controls
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl(), 'bottom-right');

    // Update map info on move
    map.on('moveend', updateMapInfo);
    map.on('zoomend', updateMapInfo);

    // Load data when map is ready
    map.on('load', () => {
        if (CONFIG.collectionId) {
            loadVectorData();
        }
    });
}

function updateMapInfo() {
    const center = map.getCenter();
    const zoom = map.getZoom();

    document.getElementById('map-zoom').textContent = `Zoom: ${zoom.toFixed(1)}`;
    document.getElementById('map-coords').textContent =
        `${center.lat.toFixed(4)}, ${center.lng.toFixed(4)}`;
}

// ============================================================================
// COLLECTION LOADING
// ============================================================================

async function loadCollectionsList() {
    const select = document.getElementById('collection-select');
    const loading = document.getElementById('collection-loading');

    try {
        const response = await fetch('/api/vector/collections');
        const data = await response.json();

        if (data.status === 'success' && data.collections) {
            loading.classList.add('hidden');

            data.collections.forEach(col => {
                const option = document.createElement('option');
                option.value = col.id;
                option.textContent = col.title || col.id;
                if (col.feature_count) {
                    option.textContent += ` (${col.feature_count} features)`;
                }
                select.appendChild(option);
            });
        } else {
            loading.textContent = 'No collections found';
        }
    } catch (error) {
        console.error('Error loading collections:', error);
        loading.textContent = 'Error loading collections';
    }
}

function loadCollection(collectionId) {
    if (collectionId) {
        window.location.href = `/interface/vector/viewer/${collectionId}`;
    }
}

async function loadCollectionData() {
    // Build TiPG URLs
    const collectionId = CONFIG.collectionId;

    // TiPG requires schema-qualified names
    const tipgCollectionId = collectionId.includes('.') ? collectionId : `geo.${collectionId}`;

    const tipgBase = CONFIG.tipgBase || '';

    // Set API links
    const tileJsonUrl = `${tipgBase}/collections/${tipgCollectionId}/tiles/WebMercatorQuad/tilejson.json`;
    const collectionUrl = `${tipgBase}/collections/${tipgCollectionId}`;
    const itemsUrl = `${tipgBase}/collections/${tipgCollectionId}/items`;
    const tipgMapUrl = `${tipgBase}/collections/${tipgCollectionId}/tiles/WebMercatorQuad/map`;

    document.getElementById('link-tilejson').href = tileJsonUrl;
    document.getElementById('link-collection').href = collectionUrl;
    document.getElementById('link-items').href = itemsUrl + '?limit=10';
    document.getElementById('link-tipg-map').href = tipgMapUrl;

    // Store for later use
    CONFIG.tipgCollectionId = tipgCollectionId;
    CONFIG.tileJsonUrl = tileJsonUrl;
    CONFIG.collectionUrl = collectionUrl;
    CONFIG.itemsUrl = itemsUrl;

    // Load collection metadata
    await loadCollectionMetadata();
}

async function loadCollectionMetadata() {
    const metadataGrid = document.getElementById('metadata-grid');

    try {
        // Try to get collection metadata from TiPG
        const response = await fetch(CONFIG.collectionUrl);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        currentCollection = await response.json();

        // Update feature count
        const featureCount = currentCollection.numberMatched ||
                           currentCollection.context?.matched ||
                           '--';
        document.getElementById('feature-count').textContent = featureCount;

        // Build metadata display
        const extent = currentCollection.extent?.spatial?.bbox?.[0];
        const crs = currentCollection.crs?.[0] || 'EPSG:4326';
        const geomType = currentCollection.itemType || 'Feature';

        metadataGrid.innerHTML = `
            <div class="metadata-item">
                <div class="metadata-label">Geometry Type</div>
                <div class="metadata-value">${geomType}</div>
            </div>
            <div class="metadata-item">
                <div class="metadata-label">CRS</div>
                <div class="metadata-value mono">${crs}</div>
            </div>
            <div class="metadata-item full-width">
                <div class="metadata-label">Extent</div>
                <div class="metadata-value mono">${extent ? extent.map(v => v.toFixed(4)).join(', ') : '--'}</div>
            </div>
        `;

        // Load schema/attributes if available
        loadSchema();

        // Update layer info
        document.getElementById('layer-name').textContent = CONFIG.collectionId;

    } catch (error) {
        console.error('Error loading collection metadata:', error);
        metadataGrid.innerHTML = `<div class="loading-text">Error loading metadata</div>`;
    }
}

async function loadSchema() {
    const schemaContent = document.getElementById('attribute-list');

    try {
        // Get a sample feature to determine schema
        const response = await fetch(`${CONFIG.itemsUrl}?limit=1`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.features && data.features.length > 0) {
            const properties = data.features[0].properties || {};
            const attributes = Object.entries(properties);

            if (attributes.length === 0) {
                schemaContent.innerHTML = '<div class="loading-text">No attributes found</div>';
                return;
            }

            schemaContent.innerHTML = attributes.map(([key, value]) => {
                const type = getAttributeType(value);
                return `
                    <div class="attribute-item">
                        <span class="attribute-name">${key}</span>
                        <span class="attribute-type ${type}">${type}</span>
                    </div>
                `;
            }).join('');
        } else {
            schemaContent.innerHTML = '<div class="loading-text">No features to analyze</div>';
        }
    } catch (error) {
        console.error('Error loading schema:', error);
        schemaContent.innerHTML = '<div class="loading-text">Error loading schema</div>';
    }
}

function getAttributeType(value) {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    if (typeof value === 'string') return 'string';
    if (Array.isArray(value)) return 'array';
    return 'object';
}

function toggleSchema() {
    const content = document.getElementById('schema-content');
    content.classList.toggle('hidden');
}

// ============================================================================
// VECTOR DATA LOADING
// ============================================================================

async function loadVectorData() {
    showLoading(true);

    if (currentMode === 'mvt') {
        await loadMVTTiles();
    } else {
        await loadGeoJSON();
    }

    showLoading(false);
}

async function loadMVTTiles() {
    try {
        // Fetch TileJSON
        const response = await fetch(CONFIG.tileJsonUrl);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        tileJsonData = await response.json();
        console.log('TileJSON loaded:', tileJsonData);

        // Remove existing layers and sources
        removeLayers();

        // Add vector tile source
        map.addSource(SOURCE_ID, {
            type: 'vector',
            tiles: tileJsonData.tiles,
            minzoom: tileJsonData.minzoom || 0,
            maxzoom: tileJsonData.maxzoom || 22,
            bounds: tileJsonData.bounds
        });

        // TiPG uses "default" as the source-layer name
        const sourceLayer = 'default';

        // Get current style settings
        const fillColor = document.getElementById('fill-color').value;
        const fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
        const strokeColor = document.getElementById('stroke-color').value;
        const strokeWidth = parseFloat(document.getElementById('stroke-width').value);
        const pointRadius = parseFloat(document.getElementById('point-radius').value);

        // Add fill layer (for polygons)
        map.addLayer({
            id: FILL_LAYER_ID,
            type: 'fill',
            source: SOURCE_ID,
            'source-layer': sourceLayer,
            filter: ['==', ['geometry-type'], 'Polygon'],
            paint: {
                'fill-color': fillColor,
                'fill-opacity': fillOpacity
            }
        });

        // Add line layer (for polygon outlines and linestrings)
        map.addLayer({
            id: LINE_LAYER_ID,
            type: 'line',
            source: SOURCE_ID,
            'source-layer': sourceLayer,
            filter: ['any',
                ['==', ['geometry-type'], 'Polygon'],
                ['==', ['geometry-type'], 'LineString'],
                ['==', ['geometry-type'], 'MultiLineString'],
                ['==', ['geometry-type'], 'MultiPolygon']
            ],
            paint: {
                'line-color': strokeColor,
                'line-width': strokeWidth
            }
        });

        // Add point layer
        map.addLayer({
            id: POINT_LAYER_ID,
            type: 'circle',
            source: SOURCE_ID,
            'source-layer': sourceLayer,
            filter: ['any',
                ['==', ['geometry-type'], 'Point'],
                ['==', ['geometry-type'], 'MultiPoint']
            ],
            paint: {
                'circle-color': fillColor,
                'circle-radius': pointRadius,
                'circle-stroke-color': strokeColor,
                'circle-stroke-width': strokeWidth
            }
        });

        // Add click handlers
        addClickHandlers([FILL_LAYER_ID, LINE_LAYER_ID, POINT_LAYER_ID]);

        // Zoom to bounds
        if (tileJsonData.bounds) {
            const [west, south, east, north] = tileJsonData.bounds;
            map.fitBounds([[west, south], [east, north]], {
                padding: 50,
                maxZoom: 14
            });
        }

        // Update UI
        document.getElementById('layer-mode').textContent = 'MVT';
        document.getElementById('visible-features').textContent = 'All';

    } catch (error) {
        console.error('Failed to load MVT tiles:', error);
        showError(`Failed to load vector tiles: ${error.message}`);
    }
}

async function loadGeoJSON() {
    try {
        const limit = document.getElementById('geojson-limit').value;
        const url = `${CONFIG.itemsUrl}?limit=${limit}`;

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        geojsonData = await response.json();
        console.log('GeoJSON loaded:', geojsonData);

        // Remove existing layers and sources
        removeLayers();

        // Add GeoJSON source
        map.addSource(GEOJSON_SOURCE_ID, {
            type: 'geojson',
            data: geojsonData
        });

        // Get current style settings
        const fillColor = document.getElementById('fill-color').value;
        const fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
        const strokeColor = document.getElementById('stroke-color').value;
        const strokeWidth = parseFloat(document.getElementById('stroke-width').value);
        const pointRadius = parseFloat(document.getElementById('point-radius').value);

        // Add fill layer
        map.addLayer({
            id: GEOJSON_FILL_LAYER_ID,
            type: 'fill',
            source: GEOJSON_SOURCE_ID,
            filter: ['==', ['geometry-type'], 'Polygon'],
            paint: {
                'fill-color': fillColor,
                'fill-opacity': fillOpacity
            }
        });

        // Add line layer
        map.addLayer({
            id: GEOJSON_LINE_LAYER_ID,
            type: 'line',
            source: GEOJSON_SOURCE_ID,
            filter: ['any',
                ['==', ['geometry-type'], 'Polygon'],
                ['==', ['geometry-type'], 'LineString'],
                ['==', ['geometry-type'], 'MultiLineString'],
                ['==', ['geometry-type'], 'MultiPolygon']
            ],
            paint: {
                'line-color': strokeColor,
                'line-width': strokeWidth
            }
        });

        // Add point layer
        map.addLayer({
            id: GEOJSON_POINT_LAYER_ID,
            type: 'circle',
            source: GEOJSON_SOURCE_ID,
            filter: ['any',
                ['==', ['geometry-type'], 'Point'],
                ['==', ['geometry-type'], 'MultiPoint']
            ],
            paint: {
                'circle-color': fillColor,
                'circle-radius': pointRadius,
                'circle-stroke-color': strokeColor,
                'circle-stroke-width': strokeWidth
            }
        });

        // Add click handlers
        addClickHandlers([GEOJSON_FILL_LAYER_ID, GEOJSON_LINE_LAYER_ID, GEOJSON_POINT_LAYER_ID]);

        // Zoom to data bounds
        if (geojsonData.features && geojsonData.features.length > 0) {
            const bounds = getBounds(geojsonData);
            if (bounds) {
                map.fitBounds(bounds, {
                    padding: 50,
                    maxZoom: 14
                });
            }
        }

        // Update UI
        const featureCount = geojsonData.features?.length || 0;
        document.getElementById('layer-mode').textContent = 'GeoJSON';
        document.getElementById('visible-features').textContent = featureCount.toLocaleString();

    } catch (error) {
        console.error('Failed to load GeoJSON:', error);
        showError(`Failed to load GeoJSON: ${error.message}`);
    }
}

function reloadGeoJSON() {
    if (currentMode === 'geojson') {
        loadGeoJSON();
    }
}

function removeLayers() {
    const layers = [
        FILL_LAYER_ID, LINE_LAYER_ID, POINT_LAYER_ID,
        GEOJSON_FILL_LAYER_ID, GEOJSON_LINE_LAYER_ID, GEOJSON_POINT_LAYER_ID
    ];

    layers.forEach(layerId => {
        if (map.getLayer(layerId)) {
            map.removeLayer(layerId);
        }
    });

    if (map.getSource(SOURCE_ID)) {
        map.removeSource(SOURCE_ID);
    }
    if (map.getSource(GEOJSON_SOURCE_ID)) {
        map.removeSource(GEOJSON_SOURCE_ID);
    }
}

function getBounds(geojson) {
    if (!geojson.features || geojson.features.length === 0) return null;

    let minLng = Infinity, minLat = Infinity;
    let maxLng = -Infinity, maxLat = -Infinity;

    const processCoords = (coords) => {
        if (typeof coords[0] === 'number') {
            minLng = Math.min(minLng, coords[0]);
            maxLng = Math.max(maxLng, coords[0]);
            minLat = Math.min(minLat, coords[1]);
            maxLat = Math.max(maxLat, coords[1]);
        } else {
            coords.forEach(processCoords);
        }
    };

    geojson.features.forEach(feature => {
        if (feature.geometry && feature.geometry.coordinates) {
            processCoords(feature.geometry.coordinates);
        }
    });

    if (minLng === Infinity) return null;

    return [[minLng, minLat], [maxLng, maxLat]];
}

// ============================================================================
// LAYER MODE SWITCHING
// ============================================================================

function setLayerMode(mode) {
    currentMode = mode;

    // Update button states
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Show/hide GeoJSON options
    const geojsonOptions = document.getElementById('geojson-options');
    if (mode === 'geojson') {
        geojsonOptions.classList.remove('hidden');
    } else {
        geojsonOptions.classList.add('hidden');
    }

    // Reload data with new mode
    if (map.loaded()) {
        loadVectorData();
    }
}

// ============================================================================
// STYLING
// ============================================================================

function syncColor(type) {
    const hexInput = document.getElementById(`${type}-color-hex`);
    const colorInput = document.getElementById(`${type}-color`);

    // Validate hex
    let hex = hexInput.value;
    if (!hex.startsWith('#')) {
        hex = '#' + hex;
    }

    if (/^#[0-9A-Fa-f]{6}$/.test(hex)) {
        colorInput.value = hex;
        hexInput.value = hex;
        applyStyle();
    }
}

function updateOpacity(type) {
    const slider = document.getElementById(`${type}-opacity`);
    const display = document.getElementById(`${type}-opacity-value`);
    display.textContent = slider.value;
    applyStyle();
}

function updateStrokeWidth() {
    const slider = document.getElementById('stroke-width');
    const display = document.getElementById('stroke-width-value');
    display.textContent = slider.value;
    applyStyle();
}

function updatePointRadius() {
    const slider = document.getElementById('point-radius');
    const display = document.getElementById('point-radius-value');
    display.textContent = slider.value;
    applyStyle();
}

function applyStyle() {
    const fillColor = document.getElementById('fill-color').value;
    const fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
    const strokeColor = document.getElementById('stroke-color').value;
    const strokeWidth = parseFloat(document.getElementById('stroke-width').value);
    const pointRadius = parseFloat(document.getElementById('point-radius').value);

    // Update hex display
    document.getElementById('fill-color-hex').value = fillColor;
    document.getElementById('stroke-color-hex').value = strokeColor;

    // Apply to MVT layers
    if (map.getLayer(FILL_LAYER_ID)) {
        map.setPaintProperty(FILL_LAYER_ID, 'fill-color', fillColor);
        map.setPaintProperty(FILL_LAYER_ID, 'fill-opacity', fillOpacity);
    }
    if (map.getLayer(LINE_LAYER_ID)) {
        map.setPaintProperty(LINE_LAYER_ID, 'line-color', strokeColor);
        map.setPaintProperty(LINE_LAYER_ID, 'line-width', strokeWidth);
    }
    if (map.getLayer(POINT_LAYER_ID)) {
        map.setPaintProperty(POINT_LAYER_ID, 'circle-color', fillColor);
        map.setPaintProperty(POINT_LAYER_ID, 'circle-radius', pointRadius);
        map.setPaintProperty(POINT_LAYER_ID, 'circle-stroke-color', strokeColor);
        map.setPaintProperty(POINT_LAYER_ID, 'circle-stroke-width', strokeWidth);
    }

    // Apply to GeoJSON layers
    if (map.getLayer(GEOJSON_FILL_LAYER_ID)) {
        map.setPaintProperty(GEOJSON_FILL_LAYER_ID, 'fill-color', fillColor);
        map.setPaintProperty(GEOJSON_FILL_LAYER_ID, 'fill-opacity', fillOpacity);
    }
    if (map.getLayer(GEOJSON_LINE_LAYER_ID)) {
        map.setPaintProperty(GEOJSON_LINE_LAYER_ID, 'line-color', strokeColor);
        map.setPaintProperty(GEOJSON_LINE_LAYER_ID, 'line-width', strokeWidth);
    }
    if (map.getLayer(GEOJSON_POINT_LAYER_ID)) {
        map.setPaintProperty(GEOJSON_POINT_LAYER_ID, 'circle-color', fillColor);
        map.setPaintProperty(GEOJSON_POINT_LAYER_ID, 'circle-radius', pointRadius);
        map.setPaintProperty(GEOJSON_POINT_LAYER_ID, 'circle-stroke-color', strokeColor);
        map.setPaintProperty(GEOJSON_POINT_LAYER_ID, 'circle-stroke-width', strokeWidth);
    }
}

// ============================================================================
// FEATURE INSPECTION
// ============================================================================

function addClickHandlers(layerIds) {
    layerIds.forEach(layerId => {
        map.on('click', layerId, handleFeatureClick);
        map.on('mouseenter', layerId, () => {
            map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', layerId, () => {
            map.getCanvas().style.cursor = '';
        });
    });
}

function handleFeatureClick(e) {
    if (!e.features || e.features.length === 0) return;

    const feature = e.features[0];
    const properties = feature.properties || {};

    // Update sidebar
    displayFeatureProperties(properties);

    // Show popup
    const coordinates = e.lngLat;
    const propEntries = Object.entries(properties);

    const popupContent = `
        <div style="max-height: 200px; overflow-y: auto;">
            <strong style="color: #053657; font-size: 13px;">Feature Properties</strong>
            <div style="margin-top: 8px; font-size: 12px;">
                ${propEntries.slice(0, 6).map(([k, v]) => `
                    <div style="padding: 3px 0; border-bottom: 1px solid #eee;">
                        <span style="color: #626F86; font-size: 10px; text-transform: uppercase;">${k}</span><br>
                        <span style="color: #053657;">${v !== null ? v : 'null'}</span>
                    </div>
                `).join('')}
                ${propEntries.length > 6 ? `<div style="color: #626F86; font-style: italic; padding-top: 4px;">+${propEntries.length - 6} more properties</div>` : ''}
            </div>
        </div>
    `;

    new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(popupContent)
        .addTo(map);
}

function displayFeatureProperties(properties) {
    const container = document.getElementById('feature-properties');
    const entries = Object.entries(properties);

    if (entries.length === 0) {
        container.innerHTML = '<div class="empty-state">No properties available</div>';
        return;
    }

    container.innerHTML = entries.map(([key, value]) => `
        <div class="property-item">
            <span class="property-key">${key}</span>
            <span class="property-value">${formatPropertyValue(value)}</span>
        </div>
    `).join('');
}

function formatPropertyValue(value) {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'object') return JSON.stringify(value);
    if (typeof value === 'number') {
        // Format numbers nicely
        if (Number.isInteger(value)) return value.toLocaleString();
        return value.toFixed(4);
    }
    return String(value);
}

// ============================================================================
// QA WORKFLOW
// ============================================================================

async function approveCollection() {
    const btn = document.getElementById('btn-approve');
    btn.disabled = true;
    btn.textContent = 'Approving...';

    try {
        // Try approval workflow via Function App proxy
        const approvalResponse = await fetch(
            `/api/proxy/fa/approvals?status=pending&limit=100`
        );

        if (approvalResponse.status === 404) {
            alert('Approval workflow not configured.\n\nData review is complete - record this collection as reviewed manually.');
            updateQaStatus('reviewed');
            return;
        }

        if (!approvalResponse.ok) {
            throw new Error(`Approval service unavailable: ${approvalResponse.status}`);
        }

        const approvals = await approvalResponse.json();

        // Find approval for this collection
        const approval = (approvals.approvals || []).find(a =>
            a.collection_id === CONFIG.collectionId ||
            a.stac_collection_id === CONFIG.collectionId
        );

        if (approval) {
            const response = await fetch(`/api/proxy/fa/approvals/${approval.id}/approve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reviewer: 'docker-curator',
                    notes: 'Approved via Vector Curator UI'
                })
            });

            if (response.ok) {
                updateQaStatus('approved');
            } else {
                const error = await response.json();
                alert(`Approval failed: ${error.error || 'Unknown error'}`);
            }
        } else {
            alert('No pending approval record found for this collection.\n\nData review is complete - record as reviewed manually.');
            updateQaStatus('reviewed');
        }

    } catch (error) {
        console.error('Approval error:', error);
        if (error.message.includes('fetch') || error.message.includes('network')) {
            alert('Could not connect to approval service.\n\nData review is complete - record as reviewed manually.');
            updateQaStatus('reviewed');
        } else {
            alert(`Error: ${error.message}`);
        }
    } finally {
        btn.disabled = false;
        btn.textContent = 'Approve';
    }
}

function showRejectModal() {
    document.getElementById('reject-modal').classList.remove('hidden');
    document.getElementById('reject-reason').value = '';
    document.getElementById('reject-reason').focus();
}

function closeRejectModal() {
    document.getElementById('reject-modal').classList.add('hidden');
}

async function confirmReject() {
    const reason = document.getElementById('reject-reason').value.trim();
    if (!reason) {
        alert('Please provide a rejection reason');
        return;
    }

    closeRejectModal();

    const btn = document.getElementById('btn-reject');
    btn.disabled = true;
    btn.textContent = 'Rejecting...';

    try {
        const approvalResponse = await fetch(
            `/api/proxy/fa/approvals?status=pending&limit=100`
        );

        if (approvalResponse.status === 404) {
            alert(`Rejection reason recorded locally:\n\n"${reason}"\n\nApproval workflow not configured - please record this rejection manually.`);
            updateQaStatus('rejected');
            return;
        }

        if (!approvalResponse.ok) {
            throw new Error(`Approval service unavailable: ${approvalResponse.status}`);
        }

        const approvals = await approvalResponse.json();

        const approval = (approvals.approvals || []).find(a =>
            a.collection_id === CONFIG.collectionId ||
            a.stac_collection_id === CONFIG.collectionId
        );

        if (approval) {
            const response = await fetch(`/api/proxy/fa/approvals/${approval.id}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reviewer: 'docker-curator',
                    rejection_reason: reason
                })
            });

            if (response.ok) {
                updateQaStatus('rejected');
            } else {
                const error = await response.json();
                alert(`Rejection failed: ${error.error || 'Unknown error'}`);
            }
        } else {
            alert(`Rejection reason recorded:\n\n"${reason}"\n\nNo pending approval record found - please record this rejection manually.`);
            updateQaStatus('rejected');
        }

    } catch (error) {
        console.error('Rejection error:', error);
        if (error.message.includes('fetch') || error.message.includes('network')) {
            alert(`Rejection reason recorded:\n\n"${reason}"\n\nCould not connect to approval service - please record this rejection manually.`);
            updateQaStatus('rejected');
        } else {
            alert(`Error: ${error.message}`);
        }
    } finally {
        btn.disabled = false;
        btn.textContent = 'Reject';
    }
}

function updateQaStatus(status) {
    const badge = document.getElementById('qa-status-badge');
    badge.className = `qa-badge ${status}`;
    badge.textContent = status;
}

// ============================================================================
// UTILITIES
// ============================================================================

function showLoading(show) {
    const overlay = document.getElementById('map-loading');
    if (show) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}

function showError(message) {
    // Simple error display
    console.error(message);

    // Could add a toast notification here
    const layerInfo = document.getElementById('layer-info');
    layerInfo.innerHTML = `
        <div class="layer-name" style="color: var(--ds-error);">Error</div>
        <div class="layer-details">${message}</div>
    `;
}
