/**
 * ============================================================================
 * UNIFIED COLLECTIONS BROWSER JAVASCRIPT
 * ============================================================================
 * Client-side logic for the Unified Collection Browser.
 * Loads and merges STAC (raster) and OGC (vector) collections.
 *
 * Dependencies:
 *   - STAC_API_URL (injected from template)
 *   - OGC_API_URL (injected from template)
 *   - TIPG_URL (injected from template)
 *   - TITILER_URL (injected from template)
 *   - common.js utilities (formatNumber, formatLabel, fetchJSON, etc.)
 * ============================================================================
 */

// ============================================================================
// STATE
// ============================================================================

let allCollections = [];
let filteredCollections = [];
let currentTypeFilter = 'all';
let currentSourceFilter = 'all';
let currentSort = 'title-asc';

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadCollections();
});

// ============================================================================
// DATA LOADING
// ============================================================================

async function loadCollections() {
    const loadingState = document.getElementById('loading-state');
    const errorState = document.getElementById('error-state');
    const emptyState = document.getElementById('empty-state');
    const grid = document.getElementById('collections-grid');
    const refreshBtn = document.getElementById('refresh-btn');

    // Show loading state
    loadingState.classList.remove('hidden');
    errorState.classList.add('hidden');
    emptyState.classList.add('hidden');
    grid.classList.add('hidden');
    refreshBtn.disabled = true;

    try {
        // Fetch STAC and OGC collections in parallel
        const [stacResult, ogcResult] = await Promise.allSettled([
            fetchStacCollections(),
            fetchOgcCollections()
        ]);

        // Process results
        const stacCollections = stacResult.status === 'fulfilled' ? stacResult.value : [];
        const ogcCollections = ogcResult.status === 'fulfilled' ? ogcResult.value : [];

        // Log any errors but continue
        if (stacResult.status === 'rejected') {
            console.warn('STAC fetch failed:', stacResult.reason);
        }
        if (ogcResult.status === 'rejected') {
            console.warn('OGC fetch failed:', ogcResult.reason);
        }

        // Merge and deduplicate
        allCollections = mergeCollections(stacCollections, ogcCollections);

        // Apply filters and render
        filterCollections();
        updateStats();

        // Hide loading, show grid
        loadingState.classList.add('hidden');

        if (allCollections.length === 0) {
            emptyState.classList.remove('hidden');
            document.getElementById('empty-message').textContent =
                'No collections found. Check that STAC and OGC APIs are available.';
        } else {
            grid.classList.remove('hidden');
        }

    } catch (error) {
        console.error('Failed to load collections:', error);
        loadingState.classList.add('hidden');
        errorState.classList.remove('hidden');
        document.getElementById('error-message').textContent = error.message;
    } finally {
        refreshBtn.disabled = false;
    }
}

async function fetchStacCollections() {
    try {
        const response = await fetch(`${STAC_API_URL}/collections`);
        if (!response.ok) throw new Error(`STAC API returned ${response.status}`);
        const data = await response.json();

        // Transform to unified format
        return (data.collections || []).map(col => transformStacCollection(col));
    } catch (error) {
        console.warn('STAC collections fetch error:', error);
        return [];
    }
}

async function fetchOgcCollections() {
    try {
        // Try TiPG first if configured
        const url = TIPG_URL ? `${TIPG_URL}/collections` : `${OGC_API_URL}/collections`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`OGC API returned ${response.status}`);
        const data = await response.json();

        // Transform to unified format
        return (data.collections || []).map(col => transformOgcCollection(col));
    } catch (error) {
        console.warn('OGC collections fetch error:', error);
        return [];
    }
}

// ============================================================================
// DATA TRANSFORMATION
// ============================================================================

function transformStacCollection(col) {
    const itemCount = col.summaries?.total_items || col.numberMatched || 0;
    const bbox = col.extent?.spatial?.bbox?.[0] || null;
    const temporal = col.extent?.temporal?.interval?.[0] || null;

    return {
        id: col.id,
        title: col.title || col.id,
        description: col.description || '',
        type: col.type || 'raster',
        source: 'stac',
        itemCount: itemCount,
        bbox: bbox,
        temporal: temporal,
        license: col.license || null,
        keywords: col.keywords || [],
        links: col.links || [],
        raw: col
    };
}

function transformOgcCollection(col) {
    // OGC collections from TiPG have id like "geo.table_name"
    const id = col.id || col.name || 'unknown';
    const displayId = id.replace('geo.', '');

    // Extract feature count from description or itemCount
    let featureCount = 0;
    if (col.itemCount !== undefined) {
        featureCount = col.itemCount;
    } else if (col.numberMatched !== undefined) {
        featureCount = col.numberMatched;
    } else if (col.description) {
        const match = col.description.match(/(\d+)\s*features?/i);
        if (match) featureCount = parseInt(match[1]);
    }

    const bbox = col.extent?.spatial?.bbox?.[0] || null;
    const temporal = col.extent?.temporal?.interval?.[0] || null;

    return {
        id: id,
        displayId: displayId,
        title: col.title || displayId,
        description: col.description || '',
        type: 'vector',
        source: 'ogc',
        itemCount: featureCount,
        bbox: bbox,
        temporal: temporal,
        license: col.properties?.license || null,
        keywords: col.properties?.keywords || [],
        links: col.links || [],
        crs: col.crs || [],
        storageCrs: col.storageCrs || null,
        raw: col
    };
}

function mergeCollections(stacCollections, ogcCollections) {
    // Create map by ID for deduplication
    const collectionsMap = new Map();

    // Add STAC collections first
    stacCollections.forEach(col => {
        collectionsMap.set(`stac:${col.id}`, col);
    });

    // Add OGC collections, marking potential duplicates
    ogcCollections.forEach(col => {
        const key = `ogc:${col.id}`;
        // Check if this OGC collection is also in STAC (vector items cataloged in STAC)
        const matchingStac = stacCollections.find(s =>
            s.id === col.displayId ||
            s.id === col.id ||
            s.title?.toLowerCase() === col.title?.toLowerCase()
        );

        if (matchingStac) {
            // Mark as having both sources
            col.stacId = matchingStac.id;
            col.hasBothSources = true;
        }

        collectionsMap.set(key, col);
    });

    return Array.from(collectionsMap.values());
}

// ============================================================================
// FILTERING & SORTING
// ============================================================================

function filterCollections() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();

    filteredCollections = allCollections.filter(col => {
        // Type filter
        if (currentTypeFilter !== 'all' && col.type !== currentTypeFilter) {
            return false;
        }

        // Source filter
        if (currentSourceFilter !== 'all' && col.source !== currentSourceFilter) {
            return false;
        }

        // Search filter
        if (searchTerm) {
            const searchableText = [
                col.id,
                col.title,
                col.description,
                ...(col.keywords || [])
            ].join(' ').toLowerCase();

            if (!searchableText.includes(searchTerm)) {
                return false;
            }
        }

        return true;
    });

    // Apply sorting
    sortCollections();
}

function sortCollections() {
    currentSort = document.getElementById('sort-select').value;

    filteredCollections.sort((a, b) => {
        switch (currentSort) {
            case 'title-asc':
                return (a.title || a.id).localeCompare(b.title || b.id);
            case 'title-desc':
                return (b.title || b.id).localeCompare(a.title || a.id);
            case 'items-desc':
                return (b.itemCount || 0) - (a.itemCount || 0);
            case 'items-asc':
                return (a.itemCount || 0) - (b.itemCount || 0);
            case 'type':
                const typeOrder = { raster: 0, vector: 1 };
                return (typeOrder[a.type] || 2) - (typeOrder[b.type] || 2);
            default:
                return 0;
        }
    });

    renderCollections();
    updateFilterCounts();
}

function setTypeFilter(type) {
    currentTypeFilter = type;

    // Update active state
    document.querySelectorAll('#type-filter .filter-pill').forEach(pill => {
        pill.classList.toggle('active', pill.dataset.type === type);
    });

    filterCollections();
}

function setSourceFilter(source) {
    currentSourceFilter = source;

    // Update active state
    document.querySelectorAll('#source-filter .filter-pill').forEach(pill => {
        pill.classList.toggle('active', pill.dataset.source === source);
    });

    filterCollections();
}

// ============================================================================
// RENDERING
// ============================================================================

function renderCollections() {
    const grid = document.getElementById('collections-grid');
    const emptyState = document.getElementById('empty-state');

    if (filteredCollections.length === 0) {
        grid.classList.add('hidden');
        emptyState.classList.remove('hidden');
        document.getElementById('empty-message').textContent =
            currentTypeFilter !== 'all' || currentSourceFilter !== 'all' || document.getElementById('search-input').value
                ? 'No collections match your current filters.'
                : 'No collections found.';
        return;
    }

    emptyState.classList.add('hidden');
    grid.classList.remove('hidden');

    grid.innerHTML = filteredCollections.map(col => renderCollectionCard(col)).join('');
}

function renderCollectionCard(col) {
    const typeClass = col.type === 'raster' ? 'type-raster' : 'type-vector';
    const typeIcon = col.type === 'raster' ? '&#x1F5BC;' : '&#x1F4CD;';
    const typeBadgeClass = col.type === 'raster' ? 'raster' : 'vector';

    const description = col.description
        ? escapeHtml(col.description.slice(0, 150) + (col.description.length > 150 ? '...' : ''))
        : 'No description available';

    const bboxDisplay = col.bbox
        ? `${col.bbox[0].toFixed(2)}, ${col.bbox[1].toFixed(2)} → ${col.bbox[2].toFixed(2)}, ${col.bbox[3].toFixed(2)}`
        : 'N/A';

    return `
        <div class="collection-card ${typeClass}" onclick="showCollectionDetail('${escapeHtml(col.id)}', '${col.source}')">
            <div class="card-header">
                <div class="card-title-row">
                    <h3 class="card-title">${escapeHtml(col.title)}</h3>
                    <div class="card-badges">
                        <span class="type-badge ${typeBadgeClass}">${typeIcon} ${col.type}</span>
                        <span class="source-badge">${col.source.toUpperCase()}</span>
                    </div>
                </div>
                <div class="card-id">${escapeHtml(col.displayId || col.id)}</div>
                <p class="card-description">${description}</p>
            </div>
            <div class="card-body">
                <div class="card-stats">
                    <div class="card-stat">
                        <div class="stat-value">${formatNumber(col.itemCount)}</div>
                        <div class="stat-label">${col.type === 'raster' ? 'Items' : 'Features'}</div>
                    </div>
                    <div class="card-stat">
                        <div class="stat-value">${col.keywords?.length || 0}</div>
                        <div class="stat-label">Keywords</div>
                    </div>
                </div>
                <div class="extent-display">
                    <div class="extent-label">Spatial Extent</div>
                    <div class="extent-value">${bboxDisplay}</div>
                </div>
            </div>
            <div class="card-footer" onclick="event.stopPropagation()">
                ${col.source === 'stac' ? `
                    <a href="/api/stac/collections/${encodeURIComponent(col.id)}/items" class="btn btn-secondary" target="_blank">
                        Items
                    </a>
                    ${TITILER_URL ? `
                    <a href="${TITILER_URL}/collections/${encodeURIComponent(col.id)}/map" class="btn btn-secondary" target="_blank">
                        Map
                    </a>
                    ` : ''}
                ` : `
                    <a href="/api/features/collections/${encodeURIComponent(col.id)}/items?limit=10" class="btn btn-secondary" target="_blank">
                        Features
                    </a>
                    ${TIPG_URL ? `
                    <a href="${TIPG_URL}/collections/${encodeURIComponent(col.id)}/map" class="btn btn-secondary" target="_blank">
                        Map
                    </a>
                    ` : ''}
                `}
                <button class="btn btn-primary" onclick="event.stopPropagation(); showCollectionDetail('${escapeHtml(col.id)}', '${col.source}')">
                    Details
                </button>
            </div>
        </div>
    `;
}

function updateStats() {
    const rasterCount = allCollections.filter(c => c.type === 'raster').length;
    const vectorCount = allCollections.filter(c => c.type === 'vector').length;
    const totalItems = allCollections.reduce((sum, c) => sum + (c.itemCount || 0), 0);

    document.getElementById('stat-total').textContent = formatNumber(allCollections.length);
    document.getElementById('stat-raster').textContent = formatNumber(rasterCount);
    document.getElementById('stat-vector').textContent = formatNumber(vectorCount);
    document.getElementById('stat-items').textContent = formatNumber(totalItems);
}

function updateFilterCounts() {
    const allCount = allCollections.length;
    const rasterCount = allCollections.filter(c => c.type === 'raster').length;
    const vectorCount = allCollections.filter(c => c.type === 'vector').length;

    document.getElementById('count-all').textContent = allCount;
    document.getElementById('count-raster').textContent = rasterCount;
    document.getElementById('count-vector').textContent = vectorCount;
}

// ============================================================================
// MODAL / DETAIL VIEW
// ============================================================================

function showCollectionDetail(id, source) {
    const col = allCollections.find(c => c.id === id && c.source === source);
    if (!col) return;

    const modal = document.getElementById('collection-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');

    modalTitle.textContent = col.title || col.id;
    modalBody.innerHTML = renderCollectionDetail(col);

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeCollectionModal() {
    const modal = document.getElementById('collection-modal');
    modal.classList.add('hidden');
    document.body.style.overflow = '';
}

function closeModal(event) {
    if (event.target.classList.contains('modal-overlay')) {
        closeCollectionModal();
    }
}

function renderCollectionDetail(col) {
    const typeIcon = col.type === 'raster' ? '&#x1F5BC;' : '&#x1F4CD;';

    // Format bbox
    const bboxDisplay = col.bbox
        ? `[${col.bbox.map(v => v.toFixed(4)).join(', ')}]`
        : 'Not specified';

    // Format temporal extent
    const temporalDisplay = col.temporal
        ? `${col.temporal[0] || 'unbounded'} → ${col.temporal[1] || 'unbounded'}`
        : 'Not specified';

    // Build links section
    const linksHtml = (col.links || []).slice(0, 10).map(link => `
        <a href="${escapeHtml(link.href)}" class="link-item" target="_blank" rel="noopener">
            <span class="link-rel">${escapeHtml(link.rel)}</span>
            <span class="link-href">${escapeHtml(link.href)}</span>
        </a>
    `).join('');

    return `
        <div class="detail-section">
            <h3>Overview</h3>
            <div class="detail-grid">
                <div class="detail-item">
                    <div class="label">Collection ID</div>
                    <div class="value mono">${escapeHtml(col.id)}</div>
                </div>
                <div class="detail-item">
                    <div class="label">Type</div>
                    <div class="value">${typeIcon} ${col.type.charAt(0).toUpperCase() + col.type.slice(1)}</div>
                </div>
                <div class="detail-item">
                    <div class="label">Source</div>
                    <div class="value">${col.source.toUpperCase()}</div>
                </div>
                <div class="detail-item">
                    <div class="label">${col.type === 'raster' ? 'Items' : 'Features'}</div>
                    <div class="value">${formatNumber(col.itemCount)}</div>
                </div>
                ${col.license ? `
                <div class="detail-item">
                    <div class="label">License</div>
                    <div class="value">${escapeHtml(col.license)}</div>
                </div>
                ` : ''}
                ${col.keywords?.length ? `
                <div class="detail-item">
                    <div class="label">Keywords</div>
                    <div class="value">${col.keywords.map(k => escapeHtml(k)).join(', ')}</div>
                </div>
                ` : ''}
                <div class="detail-item full-width">
                    <div class="label">Description</div>
                    <div class="value">${escapeHtml(col.description) || 'No description'}</div>
                </div>
            </div>
        </div>

        <div class="detail-section">
            <h3>Extent</h3>
            <div class="detail-grid">
                <div class="detail-item">
                    <div class="label">Spatial (BBOX)</div>
                    <div class="value mono">${bboxDisplay}</div>
                </div>
                <div class="detail-item">
                    <div class="label">Temporal</div>
                    <div class="value mono">${temporalDisplay}</div>
                </div>
            </div>
        </div>

        ${linksHtml ? `
        <div class="detail-section">
            <h3>Links</h3>
            <div class="links-list">
                ${linksHtml}
            </div>
        </div>
        ` : ''}

        <div class="detail-section">
            <h3>Raw Metadata</h3>
            <div class="json-preview">${JSON.stringify(col.raw, null, 2)}</div>
        </div>

        <div class="modal-actions">
            ${col.source === 'stac' ? `
                <a href="/api/stac/collections/${encodeURIComponent(col.id)}" class="btn btn-secondary" target="_blank">
                    View STAC Collection
                </a>
                <a href="/api/stac/collections/${encodeURIComponent(col.id)}/items" class="btn btn-secondary" target="_blank">
                    View Items
                </a>
                ${TITILER_URL ? `
                <a href="${TITILER_URL}/collections/${encodeURIComponent(col.id)}/map" class="btn btn-primary" target="_blank">
                    Open Map Viewer
                </a>
                ` : ''}
            ` : `
                <a href="/api/features/collections/${encodeURIComponent(col.id)}" class="btn btn-secondary" target="_blank">
                    View OGC Collection
                </a>
                <a href="/api/features/collections/${encodeURIComponent(col.id)}/items?limit=10" class="btn btn-secondary" target="_blank">
                    View Features
                </a>
                ${TIPG_URL ? `
                <a href="${TIPG_URL}/collections/${encodeURIComponent(col.id)}/map" class="btn btn-primary" target="_blank">
                    Open Map Viewer
                </a>
                ` : ''}
            `}
        </div>
    `;
}

// ============================================================================
// UTILITIES
// ============================================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Keyboard handler for modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeCollectionModal();
    }
});
