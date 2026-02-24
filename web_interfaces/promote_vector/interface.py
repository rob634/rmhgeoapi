# ============================================================================
# CLAUDE CONTEXT - PROMOTE VECTOR INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Vector dataset promotion with style builder
# PURPOSE: Promote OGC Feature collections with integrated style creation
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: PromoteVectorInterface
# DEPENDENCIES: web_interfaces.base, InterfaceRegistry
# ============================================================================
"""
Promote Vector Interface - Vector dataset promotion with OGC Style builder.

Features:
    - OGC Features collection selector
    - Visual style builder (fill, stroke, opacity)
    - Live Leaflet map preview
    - Atomic promotion + style creation

Route: /api/interface/promote-vector
"""

import logging
from typing import Dict, Any

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('promote-vector')
class PromoteVectorInterface(BaseInterface):
    """
    Promote Vector Dashboard with integrated OGC Style builder.

    Allows users to:
    1. Select OGC Features collection
    2. Build visual style with color pickers
    3. Preview style on map
    4. Set promotion metadata
    5. Save both atomically
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Promote Vector Dashboard HTML."""
        # Include Leaflet CSS and JS in head section
        leaflet_head = """
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        """

        return self.wrap_html(
            title="Promote Vector Dataset",
            content=self._generate_html_content(),
            custom_css=self._generate_custom_css(),
            custom_js=self._generate_custom_js(),
            include_htmx=False,  # Disabled - not needed for this interface
            head_extras=leaflet_head
        )

    def _generate_custom_css(self) -> str:
        """Promote interface specific styles."""
        return """
        /* Layout Grid */
        .promote-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 20px;
        }

        @media (max-width: 1200px) {
            .promote-layout {
                grid-template-columns: 1fr;
            }
        }

        /* Panels */
        .panel {
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .panel h3 {
            font-size: 16px;
            font-weight: 600;
            color: var(--ds-navy);
            margin: 0 0 20px 0;
            padding-bottom: 12px;
            border-bottom: 2px solid var(--ds-blue-primary);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Collection Selector */
        .collection-selector {
            margin-bottom: 20px;
        }

        .selector-row {
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
        }

        .selector-row .filter-group {
            flex: 1;
            display: flex;
            flex-direction: column;
        }

        .filter-group label {
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 8px;
        }

        .filter-group .filter-select {
            width: 100%;
            padding: 10px 14px;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 14px;
            background: white;
            cursor: pointer;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .filter-group .filter-select:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
        }

        .stac-info {
            background: var(--ds-bg);
            border-radius: 8px;
            padding: 16px;
            margin-top: 12px;
        }

        .stac-info .info-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #e5e7eb;
        }

        .stac-info .info-row:last-child {
            border-bottom: none;
        }

        .stac-info .info-label {
            font-size: 12px;
            color: var(--ds-gray);
            font-weight: 600;
        }

        .stac-info .info-value {
            font-size: 13px;
            color: var(--ds-navy);
        }

        /* Style Builder */
        .style-builder {
            background: #F8FAFC;
            border-radius: 8px;
            padding: 20px;
        }

        .style-section {
            margin-bottom: 20px;
        }

        .style-section:last-child {
            margin-bottom: 0;
        }

        .style-section h4 {
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            margin: 0 0 12px 0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .style-row {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }

        .style-row:last-child {
            margin-bottom: 0;
        }

        .style-label {
            width: 100px;
            font-size: 13px;
            color: var(--ds-gray);
        }

        .style-control {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* Color Picker */
        .color-picker-wrapper {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .color-picker {
            width: 50px;
            height: 36px;
            border: 2px solid #e5e7eb;
            border-radius: 6px;
            cursor: pointer;
            padding: 2px;
        }

        .color-picker::-webkit-color-swatch-wrapper {
            padding: 0;
        }

        .color-picker::-webkit-color-swatch {
            border: none;
            border-radius: 4px;
        }

        .color-hex {
            font-family: 'Monaco', monospace;
            font-size: 12px;
            color: var(--ds-gray);
            width: 70px;
            padding: 6px 8px;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            text-transform: uppercase;
        }

        /* Slider */
        .slider-wrapper {
            display: flex;
            align-items: center;
            gap: 12px;
            flex: 1;
        }

        .slider {
            flex: 1;
            -webkit-appearance: none;
            height: 6px;
            border-radius: 3px;
            background: #e5e7eb;
            outline: none;
        }

        .slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: var(--ds-blue-primary);
            cursor: pointer;
            border: 2px solid white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }

        .slider-value {
            min-width: 45px;
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            text-align: right;
        }

        /* Map Preview */
        .map-container {
            height: 350px;
            border-radius: 8px;
            overflow: hidden;
            border: 2px solid #e5e7eb;
            margin-top: 16px;
        }

        #preview-map {
            height: 100%;
            width: 100%;
        }

        .map-controls {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }

        /* Form */
        .form-group {
            margin-bottom: 20px;
        }

        .form-group label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 8px;
        }

        .form-group .hint {
            font-size: 11px;
            color: var(--ds-gray);
            margin-top: 4px;
        }

        .form-input {
            width: 100%;
            padding: 10px 14px;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 14px;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
        }

        .form-input.short {
            width: 200px;
        }

        textarea.form-input {
            min-height: 80px;
            resize: vertical;
        }

        /* Tags Input */
        .tags-container {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            padding: 8px;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            min-height: 44px;
            align-items: center;
        }

        .tag {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            background: var(--ds-blue-primary);
            color: white;
            border-radius: 16px;
            font-size: 12px;
            font-weight: 600;
        }

        .tag-remove {
            cursor: pointer;
            opacity: 0.7;
            font-size: 14px;
        }

        .tag-remove:hover {
            opacity: 1;
        }

        .tag-input {
            border: none;
            outline: none;
            flex: 1;
            min-width: 100px;
            font-size: 14px;
        }

        /* Toggle Switch */
        .toggle-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid #e5e7eb;
        }

        .toggle-row:last-child {
            border-bottom: none;
        }

        .toggle-label {
            font-size: 14px;
            color: var(--ds-navy);
        }

        .toggle-label .hint {
            font-size: 12px;
            color: var(--ds-gray);
            display: block;
            margin-top: 2px;
        }

        .toggle-switch {
            position: relative;
            width: 48px;
            height: 26px;
        }

        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: 0.3s;
            border-radius: 26px;
        }

        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: 0.3s;
            border-radius: 50%;
        }

        input:checked + .toggle-slider {
            background-color: var(--ds-blue-primary);
        }

        input:checked + .toggle-slider:before {
            transform: translateX(22px);
        }

        /* Classification Select */
        .classification-options {
            display: flex;
            gap: 12px;
        }

        .classification-option {
            flex: 1;
            padding: 12px 16px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }

        .classification-option:hover {
            border-color: var(--ds-blue-primary);
        }

        .classification-option.selected {
            border-color: var(--ds-blue-primary);
            background: rgba(0, 113, 188, 0.05);
        }

        .classification-option input {
            display: none;
        }

        .classification-option .option-icon {
            font-size: 24px;
            margin-bottom: 4px;
        }

        .classification-option .option-label {
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
        }

        /* Submit Section */
        .submit-section {
            margin-top: 24px;
            padding-top: 24px;
            border-top: 2px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .btn-promote {
            padding: 14px 32px;
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn-promote:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }

        .btn-promote:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        /* Success Panel */
        .success-panel {
            background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%);
            border: 2px solid #10B981;
            border-radius: 12px;
            padding: 24px;
            text-align: center;
        }

        .success-panel h3 {
            color: #065F46;
            border: none;
            justify-content: center;
        }

        .success-links {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin-top: 20px;
            flex-wrap: wrap;
        }

        .success-link {
            padding: 12px 20px;
            background: white;
            border: 2px solid #10B981;
            border-radius: 8px;
            color: #065F46;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.2s;
        }

        .success-link:hover {
            background: #10B981;
            color: white;
        }

        /* Geometry Type Badge */
        .geometry-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            background: var(--ds-bg);
            border-radius: 16px;
            font-size: 12px;
            font-weight: 600;
            color: var(--ds-blue-primary);
        }

        /* Style Preview Swatch */
        .style-preview-swatch {
            width: 60px;
            height: 40px;
            border-radius: 6px;
            border: 2px solid #e5e7eb;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .swatch-polygon {
            width: 40px;
            height: 25px;
            border-radius: 3px;
        }

        .swatch-line {
            width: 40px;
            height: 4px;
            border-radius: 2px;
        }

        .swatch-point {
            width: 16px;
            height: 16px;
            border-radius: 50%;
        }
        """

    def _generate_html_content(self) -> str:
        """Generate main content HTML."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Promote Vector Dataset</h1>
                <p class="subtitle">Promote an OGC Features collection with custom styling for the gallery</p>
            </header>

            <div id="success-container" style="display: none;"></div>

            <div id="form-container" class="promote-layout">
                <!-- Left Column: Collection Selection + Style Builder -->
                <div class="left-column">
                    <!-- Collection Selector Panel -->
                    <div class="panel">
                        <h3>📦 Select Feature Collection</h3>
                        <div class="collection-selector">
                            <div class="selector-row">
                                <div class="filter-group" style="flex: 1;">
                                    <label for="collectionSelect">OGC Features Collection</label>
                                    <select id="collectionSelect" class="filter-select" onchange="onCollectionChange()">
                                        <option value="">Loading collections...</option>
                                    </select>
                                </div>
                            </div>
                            <div id="collectionInfo" class="stac-info" style="display: none;">
                                <div class="info-row">
                                    <span class="info-label">Title</span>
                                    <span class="info-value" id="infoTitle">--</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">Description</span>
                                    <span class="info-value" id="infoDescription" style="font-size: 12px;">--</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">Geometry</span>
                                    <span class="info-value"><span id="geometryBadge" class="geometry-badge">--</span></span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">Features</span>
                                    <span class="info-value" id="infoFeatures">--</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Style Builder Panel -->
                    <div class="panel" style="margin-top: 20px;">
                        <h3>🎨 Style Builder</h3>
                        <div class="style-builder">
                            <!-- Fill Section (for polygons) -->
                            <div id="fillSection" class="style-section">
                                <h4>Fill</h4>
                                <div class="style-row">
                                    <span class="style-label">Color</span>
                                    <div class="style-control">
                                        <div class="color-picker-wrapper">
                                            <input type="color" id="fillColor" class="color-picker" value="#3388ff" onchange="updateStyle()">
                                            <input type="text" id="fillColorHex" class="color-hex" value="#3388ff" onchange="syncColorFromHex('fill')">
                                        </div>
                                    </div>
                                </div>
                                <div class="style-row">
                                    <span class="style-label">Opacity</span>
                                    <div class="style-control">
                                        <div class="slider-wrapper">
                                            <input type="range" id="fillOpacity" class="slider" min="0" max="100" value="50" oninput="updateStyle()">
                                            <span class="slider-value" id="fillOpacityValue">50%</span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <!-- Stroke Section -->
                            <div id="strokeSection" class="style-section">
                                <h4>Stroke</h4>
                                <div class="style-row">
                                    <span class="style-label">Color</span>
                                    <div class="style-control">
                                        <div class="color-picker-wrapper">
                                            <input type="color" id="strokeColor" class="color-picker" value="#2255bb" onchange="updateStyle()">
                                            <input type="text" id="strokeColorHex" class="color-hex" value="#2255bb" onchange="syncColorFromHex('stroke')">
                                        </div>
                                    </div>
                                </div>
                                <div class="style-row">
                                    <span class="style-label">Width</span>
                                    <div class="style-control">
                                        <div class="slider-wrapper">
                                            <input type="range" id="strokeWidth" class="slider" min="1" max="10" value="2" oninput="updateStyle()">
                                            <span class="slider-value" id="strokeWidthValue">2px</span>
                                        </div>
                                    </div>
                                </div>
                                <div class="style-row">
                                    <span class="style-label">Opacity</span>
                                    <div class="style-control">
                                        <div class="slider-wrapper">
                                            <input type="range" id="strokeOpacity" class="slider" min="0" max="100" value="80" oninput="updateStyle()">
                                            <span class="slider-value" id="strokeOpacityValue">80%</span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <!-- Point Section (for points only) -->
                            <div id="pointSection" class="style-section" style="display: none;">
                                <h4>Marker</h4>
                                <div class="style-row">
                                    <span class="style-label">Size</span>
                                    <div class="style-control">
                                        <div class="slider-wrapper">
                                            <input type="range" id="markerSize" class="slider" min="4" max="20" value="8" oninput="updateStyle()">
                                            <span class="slider-value" id="markerSizeValue">8px</span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <!-- Style Preview Swatch -->
                            <div class="style-row" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
                                <span class="style-label">Preview</span>
                                <div class="style-control">
                                    <div id="stylePreviewSwatch" class="style-preview-swatch">
                                        <div id="swatchShape" class="swatch-polygon"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Map Preview + Form -->
                <div class="right-column">
                    <!-- Map Preview Panel -->
                    <div class="panel">
                        <h3>🗺️ Map Preview</h3>
                        <div class="map-container">
                            <div id="preview-map"></div>
                        </div>
                        <div class="map-controls">
                            <button class="btn btn-secondary btn-sm" onclick="refreshPreview()">🔄 Refresh</button>
                            <button class="btn btn-secondary btn-sm" onclick="zoomToData()">🔍 Zoom to Data</button>
                        </div>
                    </div>

                    <!-- Promotion Form Panel -->
                    <div class="panel" style="margin-top: 20px;">
                        <h3>📝 Promotion Details</h3>

                        <div class="form-group">
                            <label for="promotedId">Promoted ID *</label>
                            <input type="text" id="promotedId" class="form-input" placeholder="my-dataset-name" pattern="[a-z0-9-]+" required>
                            <div class="hint">Lowercase letters, numbers, and hyphens only</div>
                        </div>

                        <div class="form-group">
                            <label for="title">Display Title</label>
                            <input type="text" id="title" class="form-input" placeholder="Override STAC title (optional)">
                        </div>

                        <div class="form-group">
                            <label for="description">Description</label>
                            <textarea id="description" class="form-input" placeholder="Custom description for gallery display"></textarea>
                        </div>

                        <div class="form-group">
                            <label>Tags</label>
                            <div class="tags-container" onclick="document.getElementById('tagInput').focus()">
                                <span id="tagsDisplay"></span>
                                <input type="text" id="tagInput" class="tag-input" placeholder="Add tag and press Enter" onkeydown="handleTagInput(event)">
                            </div>
                        </div>

                        <div class="form-group">
                            <label>Classification</label>
                            <div class="classification-options">
                                <label class="classification-option selected" onclick="selectClassification('public', this)">
                                    <input type="radio" name="classification" value="public" checked>
                                    <div class="option-icon">🌐</div>
                                    <div class="option-label">Public</div>
                                </label>
                                <label class="classification-option" onclick="selectClassification('ouo', this)">
                                    <input type="radio" name="classification" value="ouo">
                                    <div class="option-icon">🔒</div>
                                    <div class="option-label">OUO</div>
                                </label>
                            </div>
                        </div>

                        <div class="form-group">
                            <label>Options</label>
                            <div class="toggle-row">
                                <div class="toggle-label">
                                    Add to Gallery
                                    <span class="hint">Feature in the data gallery</span>
                                </div>
                                <label class="toggle-switch">
                                    <input type="checkbox" id="inGallery" checked>
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                            <div class="toggle-row" id="galleryOrderRow">
                                <div class="toggle-label">Gallery Order</div>
                                <input type="number" id="galleryOrder" class="form-input short" value="1" min="1" max="100">
                            </div>
                        </div>

                        <div class="form-group">
                            <label>System Settings</label>
                            <div class="toggle-row">
                                <div class="toggle-label">
                                    System Reserved
                                    <span class="hint">Mark as critical system dataset (protected from demotion)</span>
                                </div>
                                <label class="toggle-switch">
                                    <input type="checkbox" id="isSystemReserved" onchange="toggleSystemRole()">
                                    <span class="toggle-slider"></span>
                                </label>
                            </div>
                            <div class="toggle-row" id="systemRoleRow" style="display: none;">
                                <div class="toggle-label">
                                    System Role
                                    <span class="hint">How this dataset is used by the platform</span>
                                </div>
                                <select id="systemRole" class="form-input short">
                                    <option value="">Select role...</option>
                                    <option value="admin0_boundaries">Admin0 Boundaries (country polygons)</option>
                                    <option value="h3_land_grid">H3 Land Grid (H3 cells over land)</option>
                                </select>
                            </div>
                        </div>

                        <div class="submit-section">
                            <button class="btn btn-secondary" onclick="resetForm()">Reset</button>
                            <button id="promoteBtn" class="btn-promote" onclick="submitPromotion()" disabled>
                                <span>🚀</span> Promote Dataset
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_js(self) -> str:
        """JavaScript for Promote interface."""
        return """
        // State
        let map = null;
        let featureLayer = null;
        let currentGeometryType = 'polygon';
        let sampleFeatures = null;
        let tags = [];
        let selectedCollection = null;
        let collectionMetadata = {};

        // Get collection from URL parameter if provided
        function getUrlParam(name) {
            const params = new URLSearchParams(window.location.search);
            return params.get(name);
        }

        // Initialize on page load
        document.addEventListener('DOMContentLoaded', () => {
            console.log('Promote UI initializing...');
            try {
                initMap();
                console.log('Map initialized');
                loadCollections();
                console.log('Collections loading started');
                updateStyle();
                console.log('Style updated');

                // Gallery toggle handler
                document.getElementById('inGallery').addEventListener('change', (e) => {
                    document.getElementById('galleryOrderRow').style.display = e.target.checked ? 'flex' : 'none';
                });
                console.log('Promote UI initialization complete');
            } catch (err) {
                console.error('Initialization error:', err);
            }
        });

        // Initialize Leaflet map
        function initMap() {
            map = L.map('preview-map').setView([20, 0], 2);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap'
            }).addTo(map);

            featureLayer = L.geoJSON(null, {
                style: getLeafletStyle,
                pointToLayer: (feature, latlng) => {
                    return L.circleMarker(latlng, getLeafletStyle(feature));
                }
            }).addTo(map);
        }

        // Load OGC Features collections
        async function loadCollections() {
            const select = document.getElementById('collectionSelect');
            select.innerHTML = '<option value="">Loading collections...</option>';
            select.disabled = true;

            try {
                console.log('Fetching collections from', API_BASE_URL + '/api/features/collections');
                const response = await fetch(`${API_BASE_URL}/api/features/collections`);
                console.log('Response status:', response.status);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();
                console.log('Loaded collections:', data);

                // Get collections array
                const collections = data.collections || [];
                console.log('Found', collections.length, 'collections');

                if (collections.length === 0) {
                    select.innerHTML = '<option value="">No collections available</option>';
                    select.disabled = true;
                    return;
                }

                // Clear and add placeholder
                select.innerHTML = '<option value="">Select a collection...</option>';

                // Add each collection
                collections.forEach(col => {
                    const option = document.createElement('option');
                    option.value = col.id;
                    option.textContent = col.title || col.id;
                    // Store metadata for later
                    collectionMetadata[col.id] = {
                        title: col.title || col.id,
                        description: col.description || '',
                        extent: col.extent
                    };
                    select.appendChild(option);
                });

                select.disabled = false;
                console.log('Collections loaded successfully:', collections.length);

                // Check for collection URL parameter and pre-select
                const urlCollection = getUrlParam('collection');
                if (urlCollection && collectionMetadata[urlCollection]) {
                    console.log('Pre-selecting collection from URL:', urlCollection);
                    select.value = urlCollection;
                    onCollectionChange();  // Trigger the selection
                }

            } catch (err) {
                console.error('Failed to load collections:', err);
                select.innerHTML = '<option value="">Error loading - Click to retry</option>';
                select.disabled = false;
                // Add click handler to retry
                select.onclick = () => {
                    select.onclick = null;
                    loadCollections();
                };
            }
        }

        // Handle collection selection
        async function onCollectionChange() {
            const collectionId = document.getElementById('collectionSelect').value;
            if (!collectionId) {
                document.getElementById('collectionInfo').style.display = 'none';
                document.getElementById('promoteBtn').disabled = true;
                featureLayer.clearLayers();
                return;
            }

            selectedCollection = collectionId;

            // Enable promote button immediately - don't wait for map preview
            document.getElementById('promoteBtn').disabled = false;

            // Show collection info with loading state
            const meta = collectionMetadata[collectionId] || {};
            document.getElementById('collectionInfo').style.display = 'block';
            document.getElementById('infoTitle').textContent = meta.title || collectionId;
            document.getElementById('infoDescription').textContent = meta.description || '--';
            document.getElementById('geometryBadge').textContent = 'Loading...';
            document.getElementById('infoFeatures').textContent = 'Loading...';

            // Load map preview in background (non-blocking)
            loadCollectionPreview(collectionId);
        }

        // Load collection preview (non-blocking, button already enabled)
        async function loadCollectionPreview(collectionId) {
            try {
                // Get features from OGC Features API
                const response = await fetch(`${API_BASE_URL}/api/features/collections/${collectionId}/items?limit=100`);
                if (!response.ok) throw new Error('Failed to load features');

                const data = await response.json();
                const meta = collectionMetadata[collectionId] || {};
                displayFeatures(data, meta.title || collectionId, meta.description);
            } catch (err) {
                console.error('Failed to load collection preview:', err);
                // Update info panel with error but keep button enabled
                document.getElementById('geometryBadge').textContent = 'Unknown';
                document.getElementById('infoFeatures').textContent = 'Preview unavailable';
                // Button stays enabled - user can still promote without preview
            }
        }

        // Display features on map
        function displayFeatures(geojson, title, description) {
            sampleFeatures = geojson;

            // Detect geometry type
            const features = geojson.features || [];
            if (features.length > 0) {
                const geomType = features[0].geometry?.type || 'Polygon';
                setGeometryType(geomType);
            }

            // Update info panel (button already enabled by onCollectionChange)
            document.getElementById('collectionInfo').style.display = 'block';
            document.getElementById('infoTitle').textContent = title;
            document.getElementById('infoDescription').textContent = description || '--';
            document.getElementById('infoFeatures').textContent = features.length.toLocaleString() + (features.length === 100 ? '+' : '');

            // Update map
            featureLayer.clearLayers();
            if (features.length > 0) {
                featureLayer.addData(geojson);
                map.fitBounds(featureLayer.getBounds(), { padding: [20, 20] });
            }
        }

        // Set geometry type and update UI
        function setGeometryType(type) {
            const normalized = type.toLowerCase().replace('multi', '');

            if (normalized.includes('polygon')) {
                currentGeometryType = 'polygon';
                document.getElementById('fillSection').style.display = 'block';
                document.getElementById('pointSection').style.display = 'none';
                document.getElementById('swatchShape').className = 'swatch-polygon';
            } else if (normalized.includes('line')) {
                currentGeometryType = 'line';
                document.getElementById('fillSection').style.display = 'none';
                document.getElementById('pointSection').style.display = 'none';
                document.getElementById('swatchShape').className = 'swatch-line';
            } else if (normalized.includes('point')) {
                currentGeometryType = 'point';
                document.getElementById('fillSection').style.display = 'block';
                document.getElementById('pointSection').style.display = 'block';
                document.getElementById('swatchShape').className = 'swatch-point';
            }

            document.getElementById('geometryBadge').textContent = type;
            updateStyle();
        }

        // Get current style values
        function getStyleValues() {
            return {
                fillColor: document.getElementById('fillColor').value,
                fillOpacity: parseInt(document.getElementById('fillOpacity').value) / 100,
                strokeColor: document.getElementById('strokeColor').value,
                strokeWidth: parseInt(document.getElementById('strokeWidth').value),
                strokeOpacity: parseInt(document.getElementById('strokeOpacity').value) / 100,
                markerSize: parseInt(document.getElementById('markerSize').value)
            };
        }

        // Get Leaflet style from current settings
        function getLeafletStyle(feature) {
            const s = getStyleValues();

            if (currentGeometryType === 'point') {
                return {
                    radius: s.markerSize,
                    fillColor: s.fillColor,
                    fillOpacity: s.fillOpacity,
                    color: s.strokeColor,
                    weight: s.strokeWidth,
                    opacity: s.strokeOpacity
                };
            } else if (currentGeometryType === 'line') {
                return {
                    color: s.strokeColor,
                    weight: s.strokeWidth,
                    opacity: s.strokeOpacity
                };
            } else {
                return {
                    fillColor: s.fillColor,
                    fillOpacity: s.fillOpacity,
                    color: s.strokeColor,
                    weight: s.strokeWidth,
                    opacity: s.strokeOpacity
                };
            }
        }

        // Update style display and map
        function updateStyle() {
            const s = getStyleValues();

            // Update value displays
            document.getElementById('fillOpacityValue').textContent = Math.round(s.fillOpacity * 100) + '%';
            document.getElementById('strokeWidthValue').textContent = s.strokeWidth + 'px';
            document.getElementById('strokeOpacityValue').textContent = Math.round(s.strokeOpacity * 100) + '%';
            document.getElementById('markerSizeValue').textContent = s.markerSize + 'px';

            // Sync color hex inputs
            document.getElementById('fillColorHex').value = s.fillColor;
            document.getElementById('strokeColorHex').value = s.strokeColor;

            // Update swatch preview
            const swatch = document.getElementById('swatchShape');
            if (currentGeometryType === 'polygon') {
                swatch.style.background = s.fillColor;
                swatch.style.opacity = s.fillOpacity;
                swatch.style.border = `${s.strokeWidth}px solid ${s.strokeColor}`;
            } else if (currentGeometryType === 'line') {
                swatch.style.background = s.strokeColor;
                swatch.style.opacity = s.strokeOpacity;
                swatch.style.height = s.strokeWidth + 'px';
            } else {
                swatch.style.background = s.fillColor;
                swatch.style.opacity = s.fillOpacity;
                swatch.style.border = `${s.strokeWidth}px solid ${s.strokeColor}`;
                swatch.style.width = s.markerSize * 2 + 'px';
                swatch.style.height = s.markerSize * 2 + 'px';
            }

            // Update map layer
            if (featureLayer) {
                featureLayer.setStyle(getLeafletStyle);
            }
        }

        // Sync color from hex input
        function syncColorFromHex(type) {
            const hexInput = document.getElementById(type + 'ColorHex');
            const colorPicker = document.getElementById(type + 'Color');
            let value = hexInput.value.trim();

            // Add # if missing
            if (!value.startsWith('#')) value = '#' + value;

            // Validate
            if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
                colorPicker.value = value;
                hexInput.value = value;
                updateStyle();
            }
        }

        // Build CartoSym-JSON style spec (OGC compliant format)
        function buildCartoSymStyle() {
            const s = getStyleValues();
            let geometryType, symbolizer;

            if (currentGeometryType === 'polygon') {
                geometryType = 'Polygon';
                symbolizer = {
                    fill: { color: s.fillColor, opacity: s.fillOpacity },
                    stroke: { color: s.strokeColor, width: s.strokeWidth, opacity: s.strokeOpacity }
                };
            } else if (currentGeometryType === 'line') {
                geometryType = 'Line';
                symbolizer = {
                    stroke: { color: s.strokeColor, width: s.strokeWidth, opacity: s.strokeOpacity }
                };
            } else {
                geometryType = 'Point';
                symbolizer = {
                    marker: {
                        fill: { color: s.fillColor, opacity: s.fillOpacity },
                        stroke: { color: s.strokeColor, width: s.strokeWidth, opacity: s.strokeOpacity },
                        size: s.markerSize
                    }
                };
            }

            return {
                stylingRules: [{
                    geometryType: geometryType,
                    symbolizer: symbolizer
                }]
            };
        }

        // Tag handling
        function handleTagInput(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                const input = event.target;
                const value = input.value.trim().toLowerCase();

                if (value && !tags.includes(value)) {
                    tags.push(value);
                    renderTags();
                }
                input.value = '';
            }
        }

        function removeTag(tag) {
            tags = tags.filter(t => t !== tag);
            renderTags();
        }

        function renderTags() {
            const container = document.getElementById('tagsDisplay');
            container.innerHTML = tags.map(tag =>
                `<span class="tag">${escapeHtml(tag)}<span class="tag-remove" onclick="removeTag('${escapeHtml(tag)}')">×</span></span>`
            ).join('');
        }

        // Classification selection
        function selectClassification(value, element) {
            document.querySelectorAll('.classification-option').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');
            element.querySelector('input').checked = true;
        }

        // Toggle system role dropdown visibility
        function toggleSystemRole() {
            const isChecked = document.getElementById('isSystemReserved').checked;
            document.getElementById('systemRoleRow').style.display = isChecked ? 'flex' : 'none';
            if (!isChecked) {
                document.getElementById('systemRole').value = '';
            }
        }

        // Refresh preview
        function refreshPreview() {
            if (sampleFeatures) {
                featureLayer.clearLayers();
                featureLayer.addData(sampleFeatures);
            }
        }

        // Zoom to data
        function zoomToData() {
            if (featureLayer.getBounds().isValid()) {
                map.fitBounds(featureLayer.getBounds(), { padding: [20, 20] });
            }
        }

        // Reset form
        function resetForm() {
            document.getElementById('promotedId').value = '';
            document.getElementById('title').value = '';
            document.getElementById('description').value = '';
            tags = [];
            renderTags();
            document.getElementById('inGallery').checked = true;
            document.getElementById('galleryOrder').value = '1';
            document.querySelectorAll('.classification-option')[0].click();
            // Reset system settings
            document.getElementById('isSystemReserved').checked = false;
            document.getElementById('systemRole').value = '';
            document.getElementById('systemRoleRow').style.display = 'none';
        }

        // Submit promotion
        async function submitPromotion() {
            const promotedId = document.getElementById('promotedId').value.trim();
            if (!promotedId) {
                alert('Please enter a Promoted ID');
                return;
            }

            if (!selectedCollection) {
                alert('Please select a collection');
                return;
            }

            const btn = document.getElementById('promoteBtn');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> Promoting...';

            try {
                // Build payload with system settings
                const isSystemReserved = document.getElementById('isSystemReserved').checked;
                const systemRole = document.getElementById('systemRole').value || null;

                const payload = {
                    promoted_id: promotedId,
                    // Use the OGC Features collection as the source
                    ogc_features_collection_id: selectedCollection,
                    title: document.getElementById('title').value || null,
                    description: document.getElementById('description').value || null,
                    tags: tags.length > 0 ? tags : null,
                    classification: document.querySelector('input[name="classification"]:checked').value,
                    gallery: document.getElementById('inGallery').checked,
                    gallery_order: document.getElementById('inGallery').checked ?
                        parseInt(document.getElementById('galleryOrder').value) : null,
                    is_system_reserved: isSystemReserved,
                    system_role: isSystemReserved ? systemRole : null,
                    style: {
                        title: promotedId + ' Style',
                        spec: buildCartoSymStyle()
                    }
                };

                const response = await fetch(`${API_BASE_URL}/api/promote`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || result.message || 'Promotion failed');
                }

                showSuccess(result);

            } catch (err) {
                alert('Error: ' + err.message);
                btn.disabled = false;
                btn.innerHTML = '<span>🚀</span> Promote Dataset';
            }
        }

        // Show success panel
        function showSuccess(result) {
            document.getElementById('form-container').style.display = 'none';

            // Build status message
            let statusMsg = `<strong>${result.promoted_id}</strong> has been promoted`;
            if (result.style_id) {
                statusMsg += ` with style <code>${result.style_id}</code>`;
            }
            if (result.is_system_reserved) {
                statusMsg += `.<br><span style="color: #0369a1;">🔒 System Reserved</span>`;
                if (result.system_role) {
                    statusMsg += ` as <code>${result.system_role}</code>`;
                }
            }
            statusMsg += '.';

            const container = document.getElementById('success-container');
            container.style.display = 'block';
            container.innerHTML = `
                <div class="panel success-panel">
                    <h3>🎉 Dataset Promoted Successfully!</h3>
                    <p style="color: #065F46; margin: 16px 0;">
                        ${statusMsg}
                    </p>
                    <div class="success-links">
                        ${result.viewer_url ? `<a href="${result.viewer_url}" target="_blank" class="success-link">🗺️ Open Viewer</a>` : ''}
                        <a href="/api/promote/${result.promoted_id}" target="_blank" class="success-link">📋 View Details</a>
                        ${result.is_system_reserved ? `<a href="/api/promote/system?role=${result.system_role}" target="_blank" class="success-link">🔍 System Query</a>` : ''}
                        <a href="/api/interface/gallery" class="success-link">🖼️ Go to Gallery</a>
                        <a href="/api/interface/promote-vector" class="success-link">➕ Promote Another</a>
                    </div>
                </div>
            `;
        }
        """
