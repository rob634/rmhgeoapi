/**
 * Raster Viewer JavaScript
 * Curator interface for raster data quality review.
 * Created: 25 JAN 2026
 */

// ============================================================================
// STATE
// ============================================================================

let map = null;
let tileLayer = null;
let currentItem = null;
let currentStats = null;
let allItems = [];

// Visualization state
let currentBands = [1, 2, 3];
let currentStretch = 'auto';
let currentRescale = null;
let currentColormap = null;

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initMap();

    if (CONFIG.collectionId) {
        loadCollectionItems();
    } else {
        loadCollectionsList();
    }
});

function initMap() {
    // Initialize Leaflet map
    const defaultCenter = [0, 0];
    const defaultZoom = 2;

    map = L.map('map', {
        center: defaultCenter,
        zoom: defaultZoom,
        zoomControl: true
    });

    // Add base layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);

    // Map events
    map.on('moveend zoomend', updateMapStatus);
    map.on('click', handleMapClick);

    // Initial status
    updateMapStatus();

    // Fit to initial bbox if provided
    if (CONFIG.initialBbox) {
        const bounds = [
            [CONFIG.initialBbox[1], CONFIG.initialBbox[0]],
            [CONFIG.initialBbox[3], CONFIG.initialBbox[2]]
        ];
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}

function updateMapStatus() {
    const center = map.getCenter();
    document.getElementById('map-zoom').textContent = `Zoom: ${map.getZoom()}`;
    document.getElementById('map-coords').textContent =
        `${center.lat.toFixed(4)}, ${center.lng.toFixed(4)}`;
}

// ============================================================================
// DATA LOADING
// ============================================================================

async function loadCollectionsList() {
    const select = document.getElementById('collection-select');
    const loading = document.getElementById('collection-loading');

    try {
        const response = await fetch(`${CONFIG.stacApiBase}/collections`);
        const data = await response.json();

        const collections = data.collections || [];

        // Filter to raster collections
        const rasterCollections = collections.filter(c => {
            const itemType = c['item_type'] || '';
            return itemType.toLowerCase().includes('raster') ||
                   itemType.toLowerCase().includes('cog') ||
                   !itemType; // Include unknown types
        });

        select.innerHTML = '<option value="">-- Choose a collection --</option>';
        rasterCollections.forEach(c => {
            const option = document.createElement('option');
            option.value = c.id;
            option.textContent = `${c.id} (${c.title || 'No title'})`;
            select.appendChild(option);
        });

        loading.style.display = 'none';

    } catch (error) {
        console.error('Error loading collections:', error);
        loading.textContent = 'Error loading collections';
    }
}

function loadCollection(collectionId) {
    if (collectionId) {
        window.location.href = `/interface/raster/viewer?collection=${encodeURIComponent(collectionId)}`;
    }
}

async function loadCollectionItems() {
    const listEl = document.getElementById('items-list');
    listEl.innerHTML = '<div class="loading-text">Loading items...</div>';

    try {
        const response = await fetch(
            `${CONFIG.stacApiBase}/collections/${CONFIG.collectionId}/items?limit=100`
        );
        const data = await response.json();

        allItems = data.features || [];
        document.getElementById('item-count').textContent = data.numberMatched || allItems.length;

        renderItemsList(allItems);

        // Select first item if available
        if (allItems.length > 0) {
            selectItem(0);
        }

    } catch (error) {
        console.error('Error loading items:', error);
        listEl.innerHTML = '<div class="loading-text">Error loading items</div>';
    }
}

function renderItemsList(items) {
    const listEl = document.getElementById('items-list');

    if (items.length === 0) {
        listEl.innerHTML = '<div class="loading-text">No items found</div>';
        return;
    }

    listEl.innerHTML = items.map((item, index) => {
        const props = item.properties || {};
        const qaStatus = props['app:qa_status'] || 'pending';
        const rasterType = props['app:raster_type'] || '';
        const bandCount = props['app:band_count'] || '?';
        const datetime = props.datetime ? new Date(props.datetime).toLocaleDateString() : '';

        return `
            <div class="item-row ${qaStatus}" data-index="${index}" onclick="selectItem(${index})">
                <span class="item-icon">&#x1F5FA;</span>
                <div class="item-info">
                    <div class="item-name" title="${item.id}">${item.id}</div>
                    <div class="item-meta">${bandCount} bands ${rasterType ? '| ' + rasterType : ''} ${datetime ? '| ' + datetime : ''}</div>
                </div>
                <span class="item-status ${qaStatus}">${qaStatus}</span>
            </div>
        `;
    }).join('');
}

function filterItems(searchText) {
    const filtered = allItems.filter(item =>
        item.id.toLowerCase().includes(searchText.toLowerCase())
    );
    renderItemsList(filtered);
}

function toggleItemFilter() {
    const filter = document.getElementById('item-filter');
    filter.classList.toggle('hidden');
    if (!filter.classList.contains('hidden')) {
        document.getElementById('item-search').focus();
    }
}

// ============================================================================
// ITEM SELECTION
// ============================================================================

async function selectItem(index) {
    const items = document.querySelectorAll('.item-row');
    const targetItem = allItems.find((_, i) => {
        const row = items[i];
        return row && parseInt(row.dataset.index) === index;
    }) || allItems[index];

    if (!targetItem) return;

    currentItem = targetItem;

    // Update selection UI
    items.forEach(row => {
        row.classList.toggle('selected', parseInt(row.dataset.index) === index);
    });

    // Show sections
    document.getElementById('metadata-section').style.display = 'block';
    document.getElementById('stats-section').style.display = 'block';
    document.getElementById('viz-section').style.display = 'block';
    document.getElementById('qa-section').style.display = 'block';
    document.getElementById('query-section').style.display = 'block';
    document.getElementById('layer-info').classList.remove('hidden');

    // Update UI
    renderMetadata();
    updateBandSelectors();
    applyItemDefaults();
    updateQaStatus();
    loadTileLayer();

    // Load stats in background
    loadStats();
}

function renderMetadata() {
    const grid = document.getElementById('metadata-grid');
    const props = currentItem.properties || {};
    const assets = currentItem.assets || {};
    const dataAsset = assets.data || assets.visual || Object.values(assets)[0];

    const metadata = [
        { label: 'Item ID', value: currentItem.id, fullWidth: true },
        { label: 'Bands', value: props['app:band_count'] || '?' },
        { label: 'Type', value: props['app:raster_type'] || '--' },
        { label: 'Data Type', value: props['app:dtype'] || '--' },
        { label: 'CRS', value: props['proj:epsg'] ? `EPSG:${props['proj:epsg']}` : '--' },
    ];

    // Add dimensions if available
    if (props['app:width'] && props['app:height']) {
        metadata.push({
            label: 'Dimensions',
            value: `${props['app:width']} x ${props['app:height']}`
        });
    }

    // Add datetime
    if (props.datetime) {
        metadata.push({
            label: 'Date',
            value: new Date(props.datetime).toLocaleDateString()
        });
    }

    grid.innerHTML = metadata.map(m => `
        <div class="metadata-item ${m.fullWidth ? 'full-width' : ''}">
            <div class="metadata-label">${m.label}</div>
            <div class="metadata-value">${m.value}</div>
        </div>
    `).join('');
}

async function loadStats() {
    const content = document.getElementById('stats-content');
    content.innerHTML = '<div class="loading-text">Loading statistics...</div>';

    // Get COG URL
    const cogUrl = getCogUrl();
    if (!cogUrl) {
        content.innerHTML = '<div class="loading-text">No data asset found</div>';
        return;
    }

    try {
        const response = await fetch(`/api/raster/stats?url=${encodeURIComponent(cogUrl)}`);
        const data = await response.json();

        if (data.error) {
            content.innerHTML = `<div class="loading-text">Error: ${data.error}</div>`;
            return;
        }

        currentStats = data;
        renderStats(data);

        // If auto-stretch is selected, apply it now
        if (currentStretch === 'auto' && data.bands) {
            applyAutoStretch();
        }

    } catch (error) {
        console.error('Error loading stats:', error);
        content.innerHTML = '<div class="loading-text">Error loading statistics</div>';
    }
}

function renderStats(data) {
    const content = document.getElementById('stats-content');

    if (!data.bands || data.bands.length === 0) {
        content.innerHTML = '<div class="loading-text">No statistics available</div>';
        return;
    }

    content.innerHTML = data.bands.map((band, i) => `
        <div class="stats-band">
            <div class="stats-band-header">Band ${i + 1}</div>
            <div class="stats-row">
                <span class="stats-label">Min</span>
                <span class="stats-value">${formatNumber(band.min)}</span>
            </div>
            <div class="stats-row">
                <span class="stats-label">Max</span>
                <span class="stats-value">${formatNumber(band.max)}</span>
            </div>
            <div class="stats-row">
                <span class="stats-label">Mean</span>
                <span class="stats-value">${formatNumber(band.mean)}</span>
            </div>
            ${band.percentile_2 !== undefined ? `
            <div class="stats-row">
                <span class="stats-label">P2-P98</span>
                <span class="stats-value">${formatNumber(band.percentile_2)} - ${formatNumber(band.percentile_98)}</span>
            </div>
            ` : ''}
        </div>
    `).join('');
}

function refreshStats() {
    loadStats();
}

// ============================================================================
// VISUALIZATION
// ============================================================================

function updateBandSelectors() {
    const bandCount = currentItem?.properties?.['app:band_count'] || 3;

    ['band-r', 'band-g', 'band-b'].forEach(id => {
        const select = document.getElementById(id);
        select.innerHTML = '';
        for (let i = 1; i <= bandCount; i++) {
            const option = document.createElement('option');
            option.value = i;
            option.textContent = i;
            select.appendChild(option);
        }
    });

    // Set default values
    document.getElementById('band-r').value = Math.min(1, bandCount);
    document.getElementById('band-g').value = Math.min(2, bandCount);
    document.getElementById('band-b').value = Math.min(3, bandCount);

    // Update presets
    updateBandPresets(bandCount);

    // Update colormap visibility (only for single band)
    updateColormapVisibility();
}

function updateBandPresets(bandCount) {
    const container = document.getElementById('band-presets');
    container.innerHTML = '';

    const presets = [
        { label: 'Band 1', bands: [1], single: true }
    ];

    if (bandCount >= 3) {
        presets.push({ label: 'RGB', bands: [1, 2, 3] });
    }
    if (bandCount >= 4) {
        presets.push({ label: 'NIR', bands: [4, 3, 2] });
    }
    if (bandCount >= 8) {
        presets.push({ label: 'WV3', bands: [5, 3, 2] });
    }
    if (bandCount >= 10) {
        presets.push({ label: 'S2 RGB', bands: [4, 3, 2] });
        presets.push({ label: 'S2 NIR', bands: [8, 4, 3] });
    }

    presets.forEach((preset, i) => {
        const btn = document.createElement('button');
        btn.className = 'preset-btn' + (i === 0 ? '' : '');
        btn.textContent = preset.label;
        btn.onclick = () => applyBandPreset(preset.bands, btn);
        container.appendChild(btn);
    });
}

function applyBandPreset(bands, btn) {
    // Update buttons
    document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    currentBands = bands;

    // Update selectors
    if (bands.length >= 3) {
        document.getElementById('band-r').value = bands[0];
        document.getElementById('band-g').value = bands[1];
        document.getElementById('band-b').value = bands[2];
    } else {
        document.getElementById('band-r').value = bands[0];
        document.getElementById('band-g').value = bands[0];
        document.getElementById('band-b').value = bands[0];
    }

    updateColormapVisibility();
    loadTileLayer();
}

function applyItemDefaults() {
    const props = currentItem?.properties || {};

    // Apply saved RGB bands
    if (props['app:rgb_bands'] && Array.isArray(props['app:rgb_bands'])) {
        currentBands = props['app:rgb_bands'];
        if (currentBands.length >= 3) {
            document.getElementById('band-r').value = currentBands[0];
            document.getElementById('band-g').value = currentBands[1];
            document.getElementById('band-b').value = currentBands[2];
        }
    }

    // Apply saved rescale
    if (props['app:rescale']) {
        currentRescale = [props['app:rescale'].min, props['app:rescale'].max];
        document.getElementById('stretch-min').value = currentRescale[0];
        document.getElementById('stretch-max').value = currentRescale[1];
    } else {
        currentRescale = null;
    }

    // Apply saved colormap
    if (props['app:colormap']) {
        currentColormap = props['app:colormap'];
        document.getElementById('colormap-select').value = currentColormap;
    } else {
        currentColormap = null;
        document.getElementById('colormap-select').value = '';
    }
}

function updateVisualization() {
    // Read current band values
    currentBands = [
        parseInt(document.getElementById('band-r').value),
        parseInt(document.getElementById('band-g').value),
        parseInt(document.getElementById('band-b').value)
    ];

    // Check if single band
    const isSingleBand = currentBands[0] === currentBands[1] && currentBands[1] === currentBands[2];

    // Read colormap (only for single band)
    if (isSingleBand) {
        currentColormap = document.getElementById('colormap-select').value || null;
    } else {
        currentColormap = null;
    }

    updateColormapVisibility();
    loadTileLayer();
}

function updateColormapVisibility() {
    const isSingleBand = currentBands[0] === currentBands[1] && currentBands[1] === currentBands[2];
    const group = document.getElementById('colormap-group');
    group.style.opacity = isSingleBand ? '1' : '0.5';
    document.getElementById('colormap-select').disabled = !isSingleBand;
}

// ============================================================================
// STRETCH CONTROLS
// ============================================================================

function applyStretch(stretchType) {
    // Update button states
    document.querySelectorAll('.stretch-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.stretch === stretchType);
    });

    currentStretch = stretchType;

    // Show/hide custom inputs
    const customPanel = document.getElementById('custom-stretch');
    if (stretchType === 'custom') {
        customPanel.classList.remove('hidden');
        return; // Don't reload yet, wait for custom values
    } else {
        customPanel.classList.add('hidden');
    }

    // Calculate rescale based on stretch type and stats
    if (!currentStats || !currentStats.bands) {
        // No stats yet, just reload
        loadTileLayer();
        return;
    }

    switch (stretchType) {
        case 'auto':
            applyAutoStretch();
            break;
        case 'p2-98':
            applyPercentileStretch(2, 98);
            break;
        case 'p5-95':
            applyPercentileStretch(5, 95);
            break;
        case 'minmax':
            applyMinMaxStretch();
            break;
    }
}

function applyAutoStretch() {
    // Use p2-p98 as "auto"
    applyPercentileStretch(2, 98);
}

function applyPercentileStretch(low, high) {
    if (!currentStats || !currentStats.bands || currentStats.bands.length === 0) {
        loadTileLayer();
        return;
    }

    // Use first band's percentiles for now
    const band = currentStats.bands[0];
    const pLow = band[`percentile_${low}`] ?? band.min;
    const pHigh = band[`percentile_${high}`] ?? band.max;

    currentRescale = [pLow, pHigh];
    document.getElementById('stretch-min').value = formatNumber(pLow);
    document.getElementById('stretch-max').value = formatNumber(pHigh);

    loadTileLayer();
}

function applyMinMaxStretch() {
    if (!currentStats || !currentStats.bands || currentStats.bands.length === 0) {
        loadTileLayer();
        return;
    }

    const band = currentStats.bands[0];
    currentRescale = [band.min, band.max];
    document.getElementById('stretch-min').value = formatNumber(band.min);
    document.getElementById('stretch-max').value = formatNumber(band.max);

    loadTileLayer();
}

function applyCustomStretch() {
    const min = parseFloat(document.getElementById('stretch-min').value);
    const max = parseFloat(document.getElementById('stretch-max').value);

    if (isNaN(min) || isNaN(max)) {
        alert('Please enter valid min and max values');
        return;
    }

    currentRescale = [min, max];
    loadTileLayer();
}

// ============================================================================
// TILE LAYER
// ============================================================================

function getCogUrl() {
    if (!currentItem) return null;
    const assets = currentItem.assets || {};
    const dataAsset = assets.data || assets.visual || Object.values(assets)[0];
    return dataAsset?.href || null;
}

function buildTileUrl() {
    const cogUrl = getCogUrl();
    if (!cogUrl || !CONFIG.titilerBase) return null;

    const params = [`url=${encodeURIComponent(cogUrl)}`];

    // Add bands
    const isSingleBand = currentBands[0] === currentBands[1] && currentBands[1] === currentBands[2];
    if (isSingleBand) {
        params.push(`bidx=${currentBands[0]}`);
    } else {
        currentBands.forEach(b => params.push(`bidx=${b}`));
    }

    // Add rescale
    if (currentRescale && currentRescale.length === 2) {
        params.push(`rescale=${currentRescale[0]},${currentRescale[1]}`);
    }

    // Add colormap (single band only)
    if (currentColormap && isSingleBand) {
        params.push(`colormap_name=${currentColormap}`);
    }

    return `${CONFIG.titilerBase}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?${params.join('&')}`;
}

function loadTileLayer() {
    if (!currentItem) return;

    showMapLoading();

    // Remove existing layer
    if (tileLayer) {
        map.removeLayer(tileLayer);
        tileLayer = null;
    }

    const tileUrl = buildTileUrl();
    if (!tileUrl) {
        hideMapLoading();
        console.error('Could not build tile URL');
        return;
    }

    try {
        tileLayer = L.tileLayer(tileUrl, {
            maxZoom: 22,
            tileSize: 256,
            attribution: 'TiTiler'
        }).addTo(map);

        tileLayer.on('load', () => {
            hideMapLoading();
            updateLayerInfo();
        });

        tileLayer.on('tileerror', (error) => {
            console.error('Tile error:', error);
        });

        // Zoom to item bounds
        if (currentItem.bbox && currentItem.bbox.length >= 4) {
            const bounds = [
                [currentItem.bbox[1], currentItem.bbox[0]],
                [currentItem.bbox[3], currentItem.bbox[2]]
            ];
            map.fitBounds(bounds, { padding: [50, 50] });
        }

    } catch (error) {
        hideMapLoading();
        console.error('Error loading tile layer:', error);
    }
}

function updateLayerInfo() {
    document.getElementById('layer-name').textContent = currentItem?.id || '--';

    const isSingleBand = currentBands[0] === currentBands[1] && currentBands[1] === currentBands[2];
    document.getElementById('layer-bands').textContent = isSingleBand
        ? `Band ${currentBands[0]}`
        : currentBands.join(', ');

    document.getElementById('layer-stretch').textContent = currentRescale
        ? `${formatNumber(currentRescale[0])} - ${formatNumber(currentRescale[1])}`
        : 'Auto';
}

function showMapLoading() {
    document.getElementById('map-loading').classList.remove('hidden');
}

function hideMapLoading() {
    document.getElementById('map-loading').classList.add('hidden');
}

// ============================================================================
// POINT QUERY
// ============================================================================

async function handleMapClick(e) {
    if (!currentItem) return;

    const { lat, lng } = e.latlng;
    const cogUrl = getCogUrl();
    if (!cogUrl) return;

    // Show loading in query section
    document.getElementById('query-coords').textContent = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    document.getElementById('query-values').innerHTML = '<div class="loading-text">Querying...</div>';

    try {
        const pointUrl = `${CONFIG.titilerBase}/cog/point/${lng},${lat}?url=${encodeURIComponent(cogUrl)}`;
        const response = await fetch(pointUrl);
        const result = await response.json();

        if (response.ok && result.values) {
            const html = result.values.map((val, i) => {
                const displayVal = val === null || val === undefined
                    ? 'NoData'
                    : formatNumber(val);
                return `
                    <div class="query-band">
                        <span class="query-band-label">Band ${i + 1}</span>
                        <span class="query-band-value">${displayVal}</span>
                    </div>
                `;
            }).join('');
            document.getElementById('query-values').innerHTML = html;
        } else {
            document.getElementById('query-values').innerHTML =
                '<div class="loading-text">No data at this location</div>';
        }

    } catch (error) {
        console.error('Point query error:', error);
        document.getElementById('query-values').innerHTML =
            '<div class="loading-text">Query failed</div>';
    }
}

// ============================================================================
// QA ACTIONS
// ============================================================================

function updateQaStatus() {
    const status = currentItem?.properties?.['app:qa_status'] || 'pending';
    const badge = document.getElementById('qa-status-badge');
    badge.textContent = status;
    badge.className = `qa-badge ${status}`;
}

async function approveItem() {
    if (!currentItem) return;

    const btn = document.getElementById('btn-approve');
    btn.disabled = true;
    btn.textContent = 'Approving...';

    try {
        // Try approval workflow via Function App proxy
        const approvalResponse = await fetch(
            `/api/proxy/fa/approvals?status=pending&limit=100`
        );

        if (approvalResponse.status === 404) {
            // Approval endpoint not configured - show info message
            alert('Approval workflow not configured.\n\nData review is complete - record this item as reviewed manually.');
            updateItemStatus('reviewed');
            return;
        }

        if (!approvalResponse.ok) {
            throw new Error(`Approval service unavailable: ${approvalResponse.status}`);
        }

        const approvals = await approvalResponse.json();

        // Find approval for this item (by job_id in STAC properties or item_id)
        const approval = (approvals.approvals || []).find(a =>
            a.stac_item_id === currentItem.id ||
            a.job_id === currentItem.properties?.['app:job_id']
        );

        if (approval) {
            // Use approval workflow
            const response = await fetch(`/api/proxy/fa/approvals/${approval.id}/approve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reviewer: 'docker-curator',
                    notes: 'Approved via Raster Curator UI'
                })
            });

            if (response.ok) {
                updateItemStatus('approved');
            } else {
                const error = await response.json();
                alert(`Approval failed: ${error.error || 'Unknown error'}`);
            }
        } else {
            // No pending approval found for this item
            alert('No pending approval record found for this item.\n\nThe item may have already been approved or was not created through the approval workflow.');
            updateItemStatus('reviewed');
        }

    } catch (error) {
        console.error('Approval error:', error);
        // Show user-friendly message for network/connection errors
        if (error.message.includes('fetch') || error.message.includes('network')) {
            alert('Could not connect to approval service.\n\nData review is complete - record this item as reviewed manually.');
            updateItemStatus('reviewed');
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
        // Try approval workflow via Function App proxy
        const approvalResponse = await fetch(
            `/api/proxy/fa/approvals?status=pending&limit=100`
        );

        if (approvalResponse.status === 404) {
            // Approval endpoint not configured
            alert(`Rejection reason recorded locally:\n\n"${reason}"\n\nApproval workflow not configured - please record this rejection manually.`);
            updateItemStatus('rejected');
            return;
        }

        if (!approvalResponse.ok) {
            throw new Error(`Approval service unavailable: ${approvalResponse.status}`);
        }

        const approvals = await approvalResponse.json();

        const approval = (approvals.approvals || []).find(a =>
            a.stac_item_id === currentItem.id ||
            a.job_id === currentItem.properties?.['app:job_id']
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
                updateItemStatus('rejected');
            } else {
                const error = await response.json();
                alert(`Rejection failed: ${error.error || 'Unknown error'}`);
            }
        } else {
            // No pending approval found
            alert(`Rejection reason recorded:\n\n"${reason}"\n\nNo pending approval record found - please record this rejection manually.`);
            updateItemStatus('rejected');
        }

    } catch (error) {
        console.error('Rejection error:', error);
        // Show user-friendly message for network/connection errors
        if (error.message.includes('fetch') || error.message.includes('network')) {
            alert(`Rejection reason recorded:\n\n"${reason}"\n\nCould not connect to approval service - please record this rejection manually.`);
            updateItemStatus('rejected');
        } else {
            alert(`Error: ${error.message}`);
        }
    } finally {
        btn.disabled = false;
        btn.textContent = 'Reject';
    }
}

function updateItemStatus(status) {
    // Update current item
    if (currentItem && currentItem.properties) {
        currentItem.properties['app:qa_status'] = status;
    }

    // Update badge
    updateQaStatus();

    // Update item in list
    const index = allItems.findIndex(item => item.id === currentItem.id);
    if (index >= 0) {
        const row = document.querySelector(`.item-row[data-index="${index}"]`);
        if (row) {
            row.classList.remove('pending', 'approved', 'rejected');
            row.classList.add(status);
            const statusBadge = row.querySelector('.item-status');
            if (statusBadge) {
                statusBadge.textContent = status;
                statusBadge.className = `item-status ${status}`;
            }
        }
    }
}

// ============================================================================
// UTILITIES
// ============================================================================

function formatNumber(num) {
    if (num === null || num === undefined) return '--';
    if (Number.isInteger(num)) return num.toString();
    if (Math.abs(num) < 0.01 || Math.abs(num) >= 10000) {
        return num.toExponential(2);
    }
    return num.toFixed(2);
}
