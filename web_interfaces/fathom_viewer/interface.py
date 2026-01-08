"""
FATHOM Flood Viewer Interface.

Interactive viewer for exploring FATHOM flood hazard data with
cascading selectors for flood type, defense status, year, climate
scenario, and return period.

Route: /api/interface/fathom-viewer?collection=<collection_id>

Features:
    - Cascading dropdown selectors
    - Dynamic filtering based on available data
    - TiTiler-based map rendering
    - Click-to-query flood depth values
    - Flood-appropriate color scale
"""

import os
import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
from config import get_config


@InterfaceRegistry.register('fathom-viewer')
class FathomViewerInterface(BaseInterface):
    """
    FATHOM Flood Hazard Viewer.

    Interactive map viewer with scenario selection for FATHOM
    multi-band flood COGs.
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate FATHOM viewer HTML."""
        collection_id = request.params.get('collection', 'fathom-flood-rwa')
        config = get_config()
        titiler_url = config.titiler_base_url.rstrip('/')

        content = self._generate_content(collection_id, titiler_url)
        custom_css = self._generate_css()
        custom_js = self._generate_js(collection_id, titiler_url)

        # Leaflet CSS and JS
        head_extras = """
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        """

        return self.wrap_html(
            title=f"FATHOM Flood Viewer - {collection_id}",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=False,
            head_extras=head_extras
        )

    def _generate_content(self, collection_id: str, titiler_url: str) -> str:
        """Generate HTML content."""
        return f"""
        <div class="viewer-container">
            <!-- Header -->
            <header class="viewer-header">
                <div class="header-left">
                    <a href="/api/interface/stac" class="back-link">← STAC</a>
                    <h1>FATHOM Flood Viewer</h1>
                    <span class="collection-badge">{collection_id}</span>
                </div>
                <div class="header-right">
                    <span class="data-info" id="data-info">Loading...</span>
                </div>
            </header>

            <!-- Control Panel -->
            <div class="control-panel">
                <div class="selector-row">
                    <!-- 1. Flood Type -->
                    <div class="selector-group skeleton-group" id="group-flood-type">
                        <label for="flood-type">1. Flood Type</label>
                        <select id="flood-type" onchange="onFloodTypeChange()" class="skeleton-select" disabled>
                            <option value="">Loading scenarios...</option>
                        </select>
                    </div>

                    <!-- 2. Defense Status -->
                    <div class="selector-group" id="group-defense">
                        <label for="defense-status">2. Defense Status</label>
                        <select id="defense-status" onchange="onDefenseChange()" disabled>
                            <option value="">--</option>
                        </select>
                    </div>

                    <!-- 3. Year -->
                    <div class="selector-group" id="group-year">
                        <label for="year">3. Projection Year</label>
                        <select id="year" onchange="onYearChange()" disabled>
                            <option value="">--</option>
                        </select>
                    </div>

                    <!-- 4. Climate Scenario -->
                    <div class="selector-group" id="group-scenario">
                        <label for="scenario">4. Climate Scenario</label>
                        <select id="scenario" onchange="onScenarioChange()" disabled>
                            <option value="">--</option>
                        </select>
                    </div>

                    <!-- 5. Return Period -->
                    <div class="selector-group" id="group-return">
                        <label for="return-period">5. Return Period</label>
                        <select id="return-period" onchange="onReturnPeriodChange()">
                            <option value="1">1-in-5 year</option>
                            <option value="2">1-in-10 year</option>
                            <option value="3">1-in-20 year</option>
                            <option value="4">1-in-50 year</option>
                            <option value="5" selected>1-in-100 year</option>
                            <option value="6">1-in-200 year</option>
                            <option value="7">1-in-500 year</option>
                            <option value="8">1-in-1000 year</option>
                        </select>
                    </div>
                </div>

                <!-- Current Selection Summary -->
                <div class="selection-summary skeleton-summary" id="selection-summary">
                    <span class="summary-label">Loading flood scenarios...</span>
                </div>
            </div>

            <!-- Map Container -->
            <div id="map-container">
                <div id="map"></div>

                <!-- Legend -->
                <div class="map-legend" id="map-legend">
                    <div class="legend-title">Flood Depth (cm)</div>
                    <div class="legend-scale">
                        <div class="legend-bar"></div>
                        <div class="legend-labels">
                            <span>0</span>
                            <span>150</span>
                            <span>300+</span>
                        </div>
                    </div>
                </div>

                <!-- Click Info Panel -->
                <div class="click-info hidden" id="click-info">
                    <div class="click-info-header">
                        <span>Flood Depth</span>
                        <button onclick="hideClickInfo()">&times;</button>
                    </div>
                    <div class="click-info-body">
                        <div class="depth-value" id="depth-value">--</div>
                        <div class="depth-unit">centimeters</div>
                        <div class="click-coords" id="click-coords">--</div>
                    </div>
                </div>

                <!-- Loading Overlay -->
                <div class="map-loading hidden" id="map-loading">
                    <div class="spinner"></div>
                    <div>Loading flood data...</div>
                </div>
            </div>
        </div>
        """

    def _generate_css(self) -> str:
        """Generate custom CSS."""
        return """
        /* Full viewport layout */
        .viewer-container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        /* Header */
        .viewer-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 20px;
            background: linear-gradient(135deg, #053657 0%, #0071BC 100%);
            color: white;
            flex-shrink: 0;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .back-link {
            color: rgba(255,255,255,0.8);
            text-decoration: none;
            font-size: 13px;
            padding: 6px 12px;
            background: rgba(255,255,255,0.1);
            border-radius: 4px;
            transition: all 0.2s;
        }

        .back-link:hover {
            background: rgba(255,255,255,0.2);
            color: white;
        }

        .viewer-header h1 {
            font-size: 20px;
            font-weight: 600;
            margin: 0;
        }

        .collection-badge {
            background: rgba(255,255,255,0.2);
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-family: monospace;
        }

        .data-info {
            font-size: 13px;
            opacity: 0.9;
        }

        /* Control Panel */
        .control-panel {
            background: white;
            border-bottom: 1px solid #E5E7EB;
            padding: 16px 20px;
            flex-shrink: 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }

        .selector-row {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
        }

        .selector-group {
            flex: 1;
            min-width: 160px;
            max-width: 220px;
        }

        .selector-group label {
            display: block;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            color: #6B7280;
            margin-bottom: 6px;
            letter-spacing: 0.5px;
        }

        .selector-group select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #D1D5DB;
            border-radius: 6px;
            font-size: 14px;
            background: white;
            cursor: pointer;
            transition: all 0.2s;
        }

        .selector-group select:hover {
            border-color: #0071BC;
        }

        .selector-group select:focus {
            outline: none;
            border-color: #0071BC;
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }

        .selector-group select:disabled {
            background: #F3F4F6;
            cursor: not-allowed;
            opacity: 0.7;
        }

        /* Selection Summary */
        .selection-summary {
            margin-top: 12px;
            padding: 10px 14px;
            background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
            border: 1px solid #BFDBFE;
            border-radius: 6px;
            font-size: 13px;
        }

        .selection-summary.active {
            background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%);
            border-color: #6EE7B7;
        }

        .selection-summary.no-data {
            background: linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%);
            border-color: #FCD34D;
        }

        .summary-label {
            font-weight: 500;
            color: #1E40AF;
        }

        .selection-summary.active .summary-label {
            color: #065F46;
        }

        .selection-summary.no-data .summary-label {
            color: #92400E;
        }

        /* Map Container */
        #map-container {
            flex: 1;
            position: relative;
            min-height: 0;
        }

        #map {
            width: 100%;
            height: 100%;
        }

        /* Legend */
        .map-legend {
            position: absolute;
            bottom: 30px;
            left: 10px;
            background: white;
            padding: 12px 16px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 1000;
            min-width: 120px;
        }

        .legend-title {
            font-size: 12px;
            font-weight: 600;
            color: #374151;
            margin-bottom: 8px;
        }

        .legend-bar {
            height: 12px;
            border-radius: 2px;
            background: linear-gradient(to right,
                #f7fbff 0%,
                #deebf7 12.5%,
                #c6dbef 25%,
                #9ecae1 37.5%,
                #6baed6 50%,
                #4292c6 62.5%,
                #2171b5 75%,
                #08519c 87.5%,
                #08306b 100%
            );
            margin-bottom: 4px;
        }

        .legend-labels {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: #6B7280;
        }

        /* Click Info Panel */
        .click-info {
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 1000;
            min-width: 160px;
            overflow: hidden;
        }

        .click-info.hidden {
            display: none;
        }

        .click-info-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            background: #0071BC;
            color: white;
            font-size: 13px;
            font-weight: 600;
        }

        .click-info-header button {
            background: none;
            border: none;
            color: white;
            font-size: 18px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
        }

        .click-info-body {
            padding: 16px;
            text-align: center;
        }

        .depth-value {
            font-size: 36px;
            font-weight: 700;
            color: #0071BC;
            line-height: 1;
        }

        .depth-value.no-flood {
            color: #10B981;
            font-size: 18px;
        }

        .depth-unit {
            font-size: 12px;
            color: #6B7280;
            margin-top: 4px;
        }

        .click-coords {
            font-size: 10px;
            color: #9CA3AF;
            margin-top: 8px;
            font-family: monospace;
        }

        /* Loading Overlay */
        .map-loading {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.9);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 1001;
            gap: 12px;
            font-size: 14px;
            color: #6B7280;
        }

        .map-loading.hidden {
            display: none;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid #E5E7EB;
            border-top-color: #0071BC;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Skeleton Loading Animation */
        @keyframes skeleton-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .skeleton-group .skeleton-select {
            background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
            background-size: 200% 100%;
            animation: skeleton-pulse 1.5s ease-in-out infinite;
        }

        .skeleton-summary {
            animation: skeleton-pulse 1.5s ease-in-out infinite;
        }

        /* Responsive */
        @media (max-width: 900px) {
            .selector-group {
                min-width: 140px;
                max-width: none;
            }
        }

        @media (max-width: 600px) {
            .selector-row {
                flex-direction: column;
            }
            .selector-group {
                max-width: none;
            }
        }
        """

    def _generate_js(self, collection_id: str, titiler_url: str) -> str:
        """Generate JavaScript."""
        return f"""
        // Configuration
        const COLLECTION_ID = '{collection_id}';
        const TITILER_URL = '{titiler_url}';

        // State
        let allItems = [];
        let currentItem = null;
        let map = null;
        let tileLayer = null;
        let countryLayer = null;

        // Return period band mapping
        const RETURN_PERIODS = {{
            1: '1-in-5 year',
            2: '1-in-10 year',
            3: '1-in-20 year',
            4: '1-in-50 year',
            5: '1-in-100 year',
            6: '1-in-200 year',
            7: '1-in-500 year',
            8: '1-in-1000 year'
        }};

        // Initialize map IMMEDIATELY (don't wait for data)
        document.addEventListener('DOMContentLoaded', function() {{
            initMap();
            // Load country boundary and data in parallel
            loadCountryBoundary();
            loadItems();
        }});

        // Initialize Leaflet map
        function initMap() {{
            map = L.map('map').setView([-1.9, 29.8], 8);

            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                attribution: '&copy; OpenStreetMap, &copy; CARTO',
                maxZoom: 18
            }}).addTo(map);

            // Click handler
            map.on('click', onMapClick);

            console.log('Map initialized');
        }}

        // Load country boundary from system admin0 table
        async function loadCountryBoundary() {{
            try {{
                // First check if admin0 table exists via promoted datasets
                const promotedResp = await fetch('/api/promoted');
                const promotedData = await promotedResp.json();

                // Find system-reserved admin0 dataset
                const admin0Dataset = promotedData.datasets?.find(d =>
                    d.is_system_reserved && d.system_role === 'admin0_boundaries'
                );

                if (!admin0Dataset) {{
                    console.log('No admin0 boundaries dataset found');
                    return;
                }}

                const tableName = admin0Dataset.table_name;
                console.log('Found admin0 table:', tableName);

                // Fetch Rwanda boundary from OGC Features API
                const featuresResp = await fetch(
                    `/api/features/collections/${{tableName}}/items?iso3=RWA&limit=1`
                );
                const featuresData = await featuresResp.json();

                if (featuresData.features && featuresData.features.length > 0) {{
                    // Add country outline to map
                    countryLayer = L.geoJSON(featuresData.features, {{
                        style: {{
                            color: '#053657',
                            weight: 2,
                            fillOpacity: 0,
                            dashArray: '5, 5'
                        }}
                    }}).addTo(map);

                    console.log('Added Rwanda boundary');
                }}
            }} catch (error) {{
                console.log('Could not load country boundary:', error.message);
                // Non-critical - continue without boundary
            }}
        }}

        // Load items from STAC collection
        async function loadItems() {{
            try {{
                console.log('Fetching STAC items...');
                const resp = await fetch(`/api/stac/collections/${{COLLECTION_ID}}/items?limit=1000`);
                const data = await resp.json();
                allItems = data.features || [];

                console.log(`Loaded ${{allItems.length}} items`);
                document.getElementById('data-info').textContent = `${{allItems.length}} scenarios available`;

                // Remove skeleton loading state
                document.getElementById('group-flood-type').classList.remove('skeleton-group');
                document.getElementById('flood-type').classList.remove('skeleton-select');
                document.getElementById('selection-summary').classList.remove('skeleton-summary');

                populateFloodTypes();
            }} catch (error) {{
                console.error('Error loading items:', error);
                document.getElementById('data-info').textContent = 'Error loading data';
                document.getElementById('flood-type').innerHTML = '<option value="">Error loading</option>';
                // Remove skeleton on error too
                document.getElementById('group-flood-type').classList.remove('skeleton-group');
                document.getElementById('flood-type').classList.remove('skeleton-select');
            }}
        }}

        // Get unique values for a property, optionally filtered
        function getUniqueValues(prop, filters = {{}}) {{
            const values = new Set();
            allItems.forEach(item => {{
                const props = item.properties || {{}};

                // Apply filters
                let match = true;
                for (const [key, val] of Object.entries(filters)) {{
                    if (props[key] !== val) {{
                        match = false;
                        break;
                    }}
                }}

                if (match && props[prop] !== undefined && props[prop] !== null) {{
                    values.add(props[prop]);
                }}
            }});
            return Array.from(values).sort();
        }}

        // Find matching item
        function findItem(filters) {{
            return allItems.find(item => {{
                const props = item.properties || {{}};
                for (const [key, val] of Object.entries(filters)) {{
                    if (props[key] !== val) return false;
                }}
                return true;
            }});
        }}

        // Populate flood type dropdown
        function populateFloodTypes() {{
            const select = document.getElementById('flood-type');
            const types = getUniqueValues('fathom:flood_type');

            console.log('Flood types found:', types);

            if (types.length === 0) {{
                select.innerHTML = '<option value="">No flood types found</option>';
                return;
            }}

            select.innerHTML = types.map(t =>
                `<option value="${{t}}">${{formatLabel(t)}}</option>`
            ).join('');

            // Enable the dropdown
            select.disabled = false;

            // Trigger cascade
            onFloodTypeChange();
        }}

        // 1. Flood Type changed
        function onFloodTypeChange() {{
            const floodType = document.getElementById('flood-type').value;
            const defenseSelect = document.getElementById('defense-status');

            if (!floodType) {{
                defenseSelect.innerHTML = '<option value="">Select flood type first</option>';
                defenseSelect.disabled = true;
                resetDownstream('defense');
                return;
            }}

            const defenses = getUniqueValues('fathom:defense_status', {{
                'fathom:flood_type': floodType
            }});

            defenseSelect.innerHTML = defenses.map(d =>
                `<option value="${{d}}">${{formatLabel(d)}}</option>`
            ).join('');
            defenseSelect.disabled = false;

            onDefenseChange();
        }}

        // 2. Defense Status changed
        function onDefenseChange() {{
            const floodType = document.getElementById('flood-type').value;
            const defense = document.getElementById('defense-status').value;
            const yearSelect = document.getElementById('year');

            if (!defense) {{
                yearSelect.innerHTML = '<option value="">Select defense first</option>';
                yearSelect.disabled = true;
                resetDownstream('year');
                return;
            }}

            const years = getUniqueValues('fathom:year', {{
                'fathom:flood_type': floodType,
                'fathom:defense_status': defense
            }});

            yearSelect.innerHTML = years.map(y =>
                `<option value="${{y}}">${{y}}</option>`
            ).join('');
            yearSelect.disabled = false;

            onYearChange();
        }}

        // 3. Year changed
        function onYearChange() {{
            const floodType = document.getElementById('flood-type').value;
            const defense = document.getElementById('defense-status').value;
            const year = parseInt(document.getElementById('year').value);
            const scenarioSelect = document.getElementById('scenario');

            if (!year) {{
                scenarioSelect.innerHTML = '<option value="">Select year first</option>';
                scenarioSelect.disabled = true;
                resetDownstream('scenario');
                return;
            }}

            // 2020 is baseline - no SSP scenarios
            if (year === 2020) {{
                scenarioSelect.innerHTML = '<option value="baseline">Baseline (Historical)</option>';
                scenarioSelect.disabled = true;  // Only one option, no need to select
                onScenarioChange();
                return;
            }}

            const scenarios = getUniqueValues('fathom:ssp_scenario', {{
                'fathom:flood_type': floodType,
                'fathom:defense_status': defense,
                'fathom:year': year
            }});

            // Handle SSP scenarios for future years
            if (scenarios.length === 0) {{
                scenarioSelect.innerHTML = '<option value="">No scenarios available</option>';
                scenarioSelect.disabled = true;
                return;
            }}

            scenarioSelect.innerHTML = scenarios.map(s =>
                `<option value="${{s}}">${{formatScenario(s)}}</option>`
            ).join('');
            scenarioSelect.disabled = false;

            onScenarioChange();
        }}

        // 4. Scenario changed
        function onScenarioChange() {{
            const floodType = document.getElementById('flood-type').value;
            const defense = document.getElementById('defense-status').value;
            const year = parseInt(document.getElementById('year').value);
            const scenario = document.getElementById('scenario').value;

            if (!scenario) {{
                updateSummary(null);
                return;
            }}

            // Find matching item - baseline (2020) has no ssp_scenario field
            if (year === 2020 || scenario === 'baseline') {{
                // For 2020/baseline, find item without ssp_scenario filter
                currentItem = allItems.find(item => {{
                    const props = item.properties || {{}};
                    return props['fathom:flood_type'] === floodType &&
                           props['fathom:defense_status'] === defense &&
                           props['fathom:year'] === 2020;
                }});
            }} else {{
                // For future years, include ssp_scenario in filter
                currentItem = findItem({{
                    'fathom:flood_type': floodType,
                    'fathom:defense_status': defense,
                    'fathom:year': year,
                    'fathom:ssp_scenario': scenario
                }});
            }}

            if (currentItem) {{
                console.log('Found item:', currentItem.id);
                updateSummary(currentItem);
                updateMap();
            }} else {{
                console.log('No matching item found for:', {{ floodType, defense, year, scenario }});
                updateSummary(null);
            }}
        }}

        // 5. Return period changed
        function onReturnPeriodChange() {{
            if (currentItem) {{
                updateMap();
            }}
        }}

        // Reset downstream selectors
        function resetDownstream(from) {{
            const order = ['defense', 'year', 'scenario'];
            const startIdx = order.indexOf(from);

            if (startIdx >= 0) {{
                for (let i = startIdx; i < order.length; i++) {{
                    const id = order[i] === 'defense' ? 'defense-status' : order[i];
                    const select = document.getElementById(id);
                    select.innerHTML = `<option value="">Select previous first</option>`;
                    select.disabled = true;
                }}
            }}

            updateSummary(null);
            clearMap();
        }}

        // Update selection summary
        function updateSummary(item) {{
            const summary = document.getElementById('selection-summary');

            if (!item) {{
                summary.className = 'selection-summary no-data';
                summary.innerHTML = '<span class="summary-label">No matching scenario found</span>';
                return;
            }}

            const props = item.properties;
            const band = document.getElementById('return-period').value;
            const returnPeriod = RETURN_PERIODS[band];

            summary.className = 'selection-summary active';
            summary.innerHTML = `
                <span class="summary-label">
                    ${{formatLabel(props['fathom:flood_type'])}} flooding,
                    ${{formatLabel(props['fathom:defense_status'])}},
                    ${{props['fathom:year']}},
                    ${{formatScenario(props['fathom:ssp_scenario'])}},
                    ${{returnPeriod}}
                </span>
            `;
        }}

        // Update map with selected COG/band
        function updateMap() {{
            if (!currentItem) return;

            const band = document.getElementById('return-period').value;
            const cogUrl = currentItem.assets?.data?.href;

            if (!cogUrl) {{
                console.error('No COG URL found');
                return;
            }}

            showLoading(true);

            // Remove existing tile layer
            if (tileLayer) {{
                map.removeLayer(tileLayer);
            }}

            // Build TiTiler tile URL
            // Use expression to mask 0 values (no flood) - only show flood risk areas
            const params = new URLSearchParams({{
                url: cogUrl,
                bidx: band,
                rescale: '1,300',
                colormap_name: 'blues',
                nodata: '0'
            }});

            const tileUrl = `${{TITILER_URL}}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}@2x.png?${{params.toString()}}`;

            tileLayer = L.tileLayer(tileUrl, {{
                maxZoom: 18,
                opacity: 0.8,
                attribution: 'FATHOM Global'
            }});

            tileLayer.on('load', () => showLoading(false));
            tileLayer.on('tileerror', () => showLoading(false));

            tileLayer.addTo(map);

            // Fit to bounds if first load
            if (currentItem.bbox) {{
                const bounds = [
                    [currentItem.bbox[1], currentItem.bbox[0]],
                    [currentItem.bbox[3], currentItem.bbox[2]]
                ];
                map.fitBounds(bounds, {{ padding: [20, 20] }});
            }}

            // Update summary with current return period
            updateSummary(currentItem);

            // Hide loading after timeout
            setTimeout(() => showLoading(false), 3000);
        }}

        // Clear map layer
        function clearMap() {{
            if (tileLayer) {{
                map.removeLayer(tileLayer);
                tileLayer = null;
            }}
        }}

        // Map click handler
        async function onMapClick(e) {{
            if (!currentItem) return;

            const {{ lat, lng }} = e.latlng;
            const band = document.getElementById('return-period').value;
            const cogUrl = currentItem.assets?.data?.href;

            if (!cogUrl) return;

            try {{
                const pointUrl = `${{TITILER_URL}}/cog/point/${{lng}},${{lat}}?url=${{encodeURIComponent(cogUrl)}}`;
                const resp = await fetch(pointUrl);
                const data = await resp.json();

                // Get value for selected band (1-indexed)
                const values = data.values || [];
                const bandIdx = parseInt(band) - 1;
                const depth = values[bandIdx];

                showClickInfo(depth, lat, lng);
            }} catch (error) {{
                console.error('Error querying point:', error);
            }}
        }}

        // Show click info panel
        function showClickInfo(depth, lat, lng) {{
            const panel = document.getElementById('click-info');
            const depthEl = document.getElementById('depth-value');
            const coordsEl = document.getElementById('click-coords');

            panel.classList.remove('hidden');

            if (depth === null || depth === undefined || depth === -32768 || depth <= 0) {{
                depthEl.textContent = 'No Flood';
                depthEl.className = 'depth-value no-flood';
            }} else {{
                depthEl.textContent = Math.round(depth);
                depthEl.className = 'depth-value';
            }}

            coordsEl.textContent = `${{lat.toFixed(4)}}, ${{lng.toFixed(4)}}`;
        }}

        function hideClickInfo() {{
            document.getElementById('click-info').classList.add('hidden');
        }}

        // Show/hide loading overlay
        function showLoading(show) {{
            document.getElementById('map-loading').classList.toggle('hidden', !show);
        }}

        // Format labels
        function formatLabel(value) {{
            if (!value) return 'Unknown';
            return value.charAt(0).toUpperCase() + value.slice(1);
        }}

        function formatScenario(value) {{
            if (!value || value === 'baseline') return 'Baseline (Historical)';
            const labels = {{
                'ssp126': 'SSP1-2.6 (Low)',
                'ssp245': 'SSP2-4.5 (Medium)',
                'ssp370': 'SSP3-7.0 (High)',
                'ssp585': 'SSP5-8.5 (Very High)'
            }};
            return labels[value] || value.toUpperCase();
        }}
        """


# Export
__all__ = ['FathomViewerInterface']
