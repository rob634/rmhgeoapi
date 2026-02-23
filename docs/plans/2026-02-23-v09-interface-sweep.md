# V0.9 Interface Sweep Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update all web interface pages to V0.9 Asset/Release patterns and build a new Asset Versions visualization page.

**Architecture:** Pattern-first approach — build shared V0.9 CSS + Python helpers in `base.py`, then create the new Asset Versions page, then sweep existing pages (STAC, Jobs, Home, Platform) to add V0.9 awareness. All data comes from existing `/api/platform/status/{asset_id}` and `/api/assets/*` endpoints — no new backend work.

**Tech Stack:** Python (server-side HTML), vanilla JavaScript, CSS custom properties, existing BaseInterface pattern.

**Design Doc:** `docs/plans/2026-02-23-v09-interface-sweep-design.md`

---

## Task 1: Add V0.9 Status Badge CSS to COMMON_CSS

**Files:**
- Modify: `web_interfaces/base.py:66-1005` (COMMON_CSS block)

**Step 1: Add V0.9 CSS variables and badge classes**

Insert after the existing status color variables (line 91, before the closing `}` of `:root`):

```css
/* V0.9 Approval state colors */
--ds-approval-pending-bg: #fef3c7;
--ds-approval-pending-fg: #92400e;
--ds-approval-approved-bg: #d1fae5;
--ds-approval-approved-fg: #065f46;
--ds-approval-rejected-bg: #fee2e2;
--ds-approval-rejected-fg: #991b1b;
--ds-approval-revoked-bg: #e5e7eb;
--ds-approval-revoked-fg: #6b7280;
/* V0.9 Clearance state colors */
--ds-clearance-uncleared-bg: #f3f4f6;
--ds-clearance-uncleared-fg: #6b7280;
--ds-clearance-ouo-bg: #fef3c7;
--ds-clearance-ouo-fg: #92400e;
--ds-clearance-public-bg: #d1fae5;
--ds-clearance-public-fg: #065f46;
```

Insert after the existing `.status-failed` block (after line 247, before the Stats Banner section):

```css
/* ============================================================
   V0.9 APPROVAL BADGES
   ============================================================ */
.approval-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.025em;
}
.approval-badge.approval-pending_review {
    background: var(--ds-approval-pending-bg);
    color: var(--ds-approval-pending-fg);
}
.approval-badge.approval-approved {
    background: var(--ds-approval-approved-bg);
    color: var(--ds-approval-approved-fg);
}
.approval-badge.approval-rejected {
    background: var(--ds-approval-rejected-bg);
    color: var(--ds-approval-rejected-fg);
}
.approval-badge.approval-revoked {
    background: var(--ds-approval-revoked-bg);
    color: var(--ds-approval-revoked-fg);
}

/* V0.9 CLEARANCE BADGES */
.clearance-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.025em;
}
.clearance-badge.clearance-uncleared {
    background: var(--ds-clearance-uncleared-bg);
    color: var(--ds-clearance-uncleared-fg);
}
.clearance-badge.clearance-ouo {
    background: var(--ds-clearance-ouo-bg);
    color: var(--ds-clearance-ouo-fg);
}
.clearance-badge.clearance-public {
    background: var(--ds-clearance-public-bg);
    color: var(--ds-clearance-public-fg);
}

/* V0.9 VERSION CHIP */
.version-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 700;
    font-family: monospace;
    background: var(--ds-navy);
    color: white;
}
.version-chip.version-draft {
    background: transparent;
    color: var(--ds-gray);
    border: 1.5px dashed var(--ds-gray);
    font-weight: 600;
}
.version-chip .latest-star {
    color: var(--ds-gold);
    font-size: 0.85rem;
}

/* V0.9 ASSET HEADER */
.asset-header {
    background: white;
    border-left: 4px solid var(--ds-blue-primary);
    padding: 16px 24px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.asset-header .asset-title {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--ds-navy);
    margin: 0 0 4px 0;
}
.asset-header .asset-meta {
    font-size: 0.85rem;
    color: var(--ds-gray);
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
}
.asset-header .asset-meta code {
    font-size: 0.8rem;
    background: #f1f3f5;
    padding: 1px 6px;
    border-radius: 4px;
}
```

**Step 2: Verify CSS renders correctly**

Run: `conda activate azgeo && python -c "from web_interfaces.base import BaseInterface; b = BaseInterface(); print('CSS length:', len(b.COMMON_CSS))"`
Expected: No import errors, CSS length > 15000

**Step 3: Commit**

```bash
git add web_interfaces/base.py
git commit -m "Add V0.9 approval, clearance, version badge CSS to design system"
```

---

## Task 2: Add V0.9 Python Helper Functions to BaseInterface

**Files:**
- Modify: `web_interfaces/base.py` (after `render_status_badge` method, ~line 2139)

**Step 1: Add V0.9 render helpers**

Insert after the existing `render_status_badge` method (after line 2138):

```python
def render_approval_badge(self, state: str) -> str:
    """Render a V0.9 approval state badge."""
    if not state:
        return ''
    safe = state.lower().replace(' ', '_')
    label = safe.replace('_', ' ')
    return f'<span class="approval-badge approval-{safe}">{label}</span>'

def render_clearance_badge(self, state: str) -> str:
    """Render a V0.9 clearance state badge."""
    if not state:
        return ''
    safe = state.lower()
    return f'<span class="clearance-badge clearance-{safe}">{safe}</span>'

def render_version_chip(self, version_id: str | None, ordinal: int, is_latest: bool = False) -> str:
    """Render a V0.9 version chip (navy pill for versions, dashed for drafts)."""
    if version_id:
        star = '<span class="latest-star">&#9733;</span>' if is_latest else ''
        return f'<span class="version-chip">{version_id}{star}</span>'
    else:
        return f'<span class="version-chip version-draft">ord {ordinal}</span>'

def render_asset_header(self, asset: dict) -> str:
    """Render a V0.9 asset identity header block."""
    dataset_id = asset.get('dataset_id', '—')
    resource_id = asset.get('resource_id', '—')
    data_type = asset.get('data_type', '—')
    asset_id = asset.get('asset_id', '—')
    release_count = asset.get('release_count', 0)
    return f"""
    <div class="asset-header">
        <div class="asset-title">{dataset_id} / {resource_id}</div>
        <div class="asset-meta">
            <span>{data_type}</span>
            <span>{release_count} release{'s' if release_count != 1 else ''}</span>
            <span>asset_id: <code>{asset_id[:12]}...</code></span>
        </div>
    </div>
    """
```

**Step 2: Verify helpers work**

Run: `conda activate azgeo && python -c "from web_interfaces.base import BaseInterface; b = BaseInterface(); print(b.render_approval_badge('approved')); print(b.render_version_chip('v2', 2, True)); print(b.render_version_chip(None, 3, False))"`

Expected output:
```
<span class="approval-badge approval-approved">approved</span>
<span class="version-chip">v2<span class="latest-star">&#9733;</span></span>
<span class="version-chip version-draft">ord 3</span>
```

**Step 3: Commit**

```bash
git add web_interfaces/base.py
git commit -m "Add V0.9 render helpers: approval, clearance, version chip, asset header"
```

---

## Task 3: Create Asset Versions Interface — Module Structure

**Files:**
- Create: `web_interfaces/asset_versions/__init__.py`
- Create: `web_interfaces/asset_versions/interface.py`
- Modify: `web_interfaces/__init__.py` (add auto-import, after line ~479)

**Step 1: Create module init**

Create `web_interfaces/asset_versions/__init__.py`:

```python
from .interface import AssetVersionsInterface
```

**Step 2: Create interface skeleton**

Create `web_interfaces/asset_versions/interface.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - ASSET VERSIONS INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - V0.9 Asset/Release version visualization
# PURPOSE: Full lifecycle view of an Asset's releases with approval actions
# LAST_REVIEWED: 23 FEB 2026
# EXPORTS: AssetVersionsInterface
# DEPENDENCIES: web_interfaces.base
# ============================================================================

import logging

from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('asset-versions')
class AssetVersionsInterface(BaseInterface):
    """V0.9 Asset version history with expandable release details and approval actions."""

    def render(self, request) -> str:
        base_url = self.get_base_url(request)
        params = self.get_query_params(request)
        asset_id = params.get('asset_id', '')
        dataset_id = params.get('dataset_id', '')
        resource_id = params.get('resource_id', '')

        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js(base_url)

        content = f"""
        <div class="av-container">
            <div id="av-loading" class="loading-state">
                <div class="spinner"></div>
                <p>Loading asset versions...</p>
            </div>
            <div id="av-error" style="display:none;"></div>
            <div id="av-content" style="display:none;">
                <div id="av-header"></div>
                <div id="av-table-wrapper"></div>
            </div>
        </div>
        <script>
            const ASSET_ID = '{asset_id}';
            const DATASET_ID = '{dataset_id}';
            const RESOURCE_ID = '{resource_id}';
        </script>
        """

        return self.wrap_html(
            title="Asset Versions",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_navbar=not self.embed_mode
        )

    def _generate_custom_css(self) -> str:
        return """
        .av-container { max-width: 1100px; margin: 0 auto; padding: 20px; }

        /* Release Table */
        .av-table { width: 100%; border-collapse: collapse; background: white;
                    border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .av-table thead th { background: var(--ds-navy); color: white; padding: 12px 16px;
                             text-align: left; font-size: 0.8rem; text-transform: uppercase;
                             letter-spacing: 0.05em; }
        .av-table tbody tr { border-bottom: 1px solid #e9ecef; cursor: pointer;
                             transition: background 0.15s; }
        .av-table tbody tr:hover { background: #f8f9fa; }
        .av-table tbody td { padding: 12px 16px; font-size: 0.9rem; }
        .av-table tbody tr.expanded { background: #eef2ff; }

        /* Expanded detail row */
        .av-detail { display: none; }
        .av-detail.open { display: table-row; }
        .av-detail td { padding: 0; }
        .av-detail-inner { padding: 16px 24px; background: #f8f9fa; border-left: 3px solid var(--ds-blue-primary); }
        .av-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 32px; margin-bottom: 12px; }
        .av-detail-label { font-size: 0.75rem; text-transform: uppercase; color: var(--ds-gray);
                           letter-spacing: 0.03em; }
        .av-detail-value { font-size: 0.85rem; color: var(--ds-navy); word-break: break-all; }
        .av-detail-value code { background: #e9ecef; padding: 1px 5px; border-radius: 3px;
                                font-size: 0.8rem; }

        /* Action buttons in detail row */
        .av-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
        .av-actions .btn { font-size: 0.8rem; padding: 6px 14px; }

        /* Expand indicator */
        .av-expand { font-size: 0.7rem; color: var(--ds-gray); transition: transform 0.2s; }
        tr.expanded .av-expand { transform: rotate(90deg); }

        /* Loading */
        .loading-state { text-align: center; padding: 60px 20px; color: var(--ds-gray); }
        .spinner { width: 32px; height: 32px; border: 3px solid #e9ecef;
                   border-top-color: var(--ds-blue-primary); border-radius: 50%;
                   animation: spin 0.8s linear infinite; margin: 0 auto 12px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        """

    def _generate_custom_js(self, base_url: str) -> str:
        return """
        async function loadAssetVersions() {
            const loading = document.getElementById('av-loading');
            const error = document.getElementById('av-error');
            const content = document.getElementById('av-content');

            try {
                let url;
                if (ASSET_ID) {
                    url = `${API_BASE_URL}/api/platform/status/${ASSET_ID}`;
                } else if (DATASET_ID && RESOURCE_ID) {
                    url = `${API_BASE_URL}/api/platform/status?dataset_id=${encodeURIComponent(DATASET_ID)}&resource_id=${encodeURIComponent(RESOURCE_ID)}`;
                } else {
                    throw new Error('asset_id or dataset_id+resource_id required');
                }

                const resp = await fetch(url);
                if (!resp.ok) throw new Error(`Status ${resp.status}: ${resp.statusText}`);
                const data = await resp.json();

                if (!data.success) throw new Error(data.error || 'Request failed');

                renderAssetHeader(data.asset);
                renderVersionsTable(data.versions || [], data.asset, data.services, data.approval);

                loading.style.display = 'none';
                content.style.display = 'block';
            } catch (e) {
                loading.style.display = 'none';
                error.style.display = 'block';
                error.innerHTML = `
                    <div style="text-align:center; padding:40px; color:#dc2626;">
                        <p style="font-size:1.1rem; font-weight:600;">Failed to load asset</p>
                        <p style="color:#6b7280;">${e.message}</p>
                        <button class="btn btn-primary" onclick="loadAssetVersions()" style="margin-top:12px;">Retry</button>
                    </div>`;
            }
        }

        function renderAssetHeader(asset) {
            if (!asset) return;
            const el = document.getElementById('av-header');
            el.innerHTML = `
                <div class="asset-header">
                    <div class="asset-title">${asset.dataset_id} / ${asset.resource_id}</div>
                    <div class="asset-meta">
                        <span>${asset.data_type}</span>
                        <span>${asset.release_count} release${asset.release_count !== 1 ? 's' : ''}</span>
                        <span>asset_id: <code>${asset.asset_id.substring(0, 12)}...</code></span>
                    </div>
                </div>`;
        }

        function renderVersionChip(v) {
            if (v.version_id) {
                const star = v.is_latest ? '<span class="latest-star">&#9733;</span>' : '';
                return `<span class="version-chip">${v.version_id}${star}</span>`;
            }
            return `<span class="version-chip version-draft">ord ${v.version_ordinal}</span>`;
        }

        function renderBadge(cls, state) {
            if (!state) return '';
            const label = state.replace(/_/g, ' ');
            return `<span class="${cls} ${cls.split('-')[0]}-${cls.split('-')[0] === 'approval' ? '' : ''}${state}">${label}</span>`;
        }

        function renderApprovalBadge(state) {
            if (!state) return '';
            return `<span class="approval-badge approval-${state}">${state.replace(/_/g, ' ')}</span>`;
        }

        function renderClearanceBadge(state) {
            if (!state) return '—';
            return `<span class="clearance-badge clearance-${state}">${state}</span>`;
        }

        function renderProcessingBadge(status) {
            if (!status) return '';
            return `<span class="status-badge status-${status}">${status}</span>`;
        }

        function renderVersionsTable(versions, asset, services, approval) {
            const wrapper = document.getElementById('av-table-wrapper');
            if (!versions || versions.length === 0) {
                wrapper.innerHTML = '<p style="text-align:center; color:#6b7280; padding:40px;">No releases found for this asset.</p>';
                return;
            }

            // Sort by version_ordinal descending (newest first)
            versions.sort((a, b) => (b.version_ordinal || 0) - (a.version_ordinal || 0));

            let rows = '';
            versions.forEach((v, i) => {
                const rowId = `row-${i}`;
                rows += `
                <tr onclick="toggleDetail('${rowId}')" id="${rowId}-header">
                    <td>${v.version_ordinal || '—'}</td>
                    <td>${renderVersionChip(v)}</td>
                    <td>${renderProcessingBadge(v.processing_status)}</td>
                    <td>${renderApprovalBadge(v.approval_state)}</td>
                    <td>${renderClearanceBadge(v.clearance_state)}</td>
                    <td>${v.revision || 1}</td>
                    <td><span class="av-expand">&#9654;</span></td>
                </tr>
                <tr class="av-detail" id="${rowId}-detail">
                    <td colspan="7">
                        <div class="av-detail-inner">
                            ${renderDetailContent(v, asset, services, approval)}
                        </div>
                    </td>
                </tr>`;
            });

            wrapper.innerHTML = `
            <table class="av-table">
                <thead>
                    <tr>
                        <th>Ord</th>
                        <th>Version</th>
                        <th>Processing</th>
                        <th>Approval</th>
                        <th>Clearance</th>
                        <th>Rev</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>`;
        }

        function renderDetailContent(v, asset, services, approval) {
            const rid = v.release_id || '—';
            const created = v.created_at ? formatDateTime(v.created_at) : '—';

            let outputsHtml = '';
            if (v.blob_path) {
                outputsHtml += `<div><div class="av-detail-label">Blob Path</div><div class="av-detail-value"><code>${v.blob_path}</code></div></div>`;
            }
            if (v.table_name) {
                outputsHtml += `<div><div class="av-detail-label">Table</div><div class="av-detail-value"><code>${v.table_name}</code></div></div>`;
            }
            if (v.stac_item_id) {
                outputsHtml += `<div><div class="av-detail-label">STAC Item</div><div class="av-detail-value">${v.stac_item_id}</div></div>`;
            }
            if (v.stac_collection_id) {
                outputsHtml += `<div><div class="av-detail-label">STAC Collection</div><div class="av-detail-value">${v.stac_collection_id}</div></div>`;
            }

            let actionsHtml = '';
            const dataType = asset?.data_type || 'raster';

            // Service links (only for completed + approved releases)
            if (v.processing_status === 'completed') {
                if (services?.viewer) {
                    actionsHtml += `<a href="${services.viewer}" target="_blank" class="btn btn-sm btn-primary">Preview</a>`;
                }
                if (services?.stac_item) {
                    actionsHtml += `<a href="${services.stac_item}" target="_blank" class="btn btn-sm btn-secondary">STAC Item</a>`;
                }
                if (v.stac_item_id && dataType === 'raster') {
                    actionsHtml += `<a href="${API_BASE_URL}/api/interface/raster-viewer?item_id=${encodeURIComponent(v.stac_item_id)}&asset_id=${asset?.asset_id || ''}" target="_blank" class="btn btn-sm btn-secondary">Raster Viewer</a>`;
                }
            }

            // Approval actions (only for pending_review + completed)
            if (v.approval_state === 'pending_review' && v.processing_status === 'completed') {
                actionsHtml += `<button class="btn btn-sm" style="background:#059669;color:white;" onclick="event.stopPropagation(); approveRelease('${asset?.asset_id}')">Approve</button>`;
                actionsHtml += `<button class="btn btn-sm" style="background:#dc2626;color:white;" onclick="event.stopPropagation(); rejectRelease('${asset?.asset_id}')">Reject</button>`;
            }

            // Revoke action (only for approved)
            if (v.approval_state === 'approved') {
                actionsHtml += `<button class="btn btn-sm" style="background:#6b7280;color:white;" onclick="event.stopPropagation(); revokeRelease('${asset?.asset_id}')">Revoke</button>`;
            }

            return `
            <div class="av-detail-grid">
                <div>
                    <div class="av-detail-label">Release ID</div>
                    <div class="av-detail-value"><code>${rid.substring(0, 16)}...</code></div>
                </div>
                <div>
                    <div class="av-detail-label">Created</div>
                    <div class="av-detail-value">${created}</div>
                </div>
                ${outputsHtml}
            </div>
            ${actionsHtml ? `<div class="av-actions">${actionsHtml}</div>` : ''}
            `;
        }

        function toggleDetail(rowId) {
            const header = document.getElementById(rowId + '-header');
            const detail = document.getElementById(rowId + '-detail');
            const isOpen = detail.classList.contains('open');

            // Close all
            document.querySelectorAll('.av-detail.open').forEach(el => el.classList.remove('open'));
            document.querySelectorAll('tr.expanded').forEach(el => el.classList.remove('expanded'));

            if (!isOpen) {
                detail.classList.add('open');
                header.classList.add('expanded');
            }
        }

        async function approveRelease(assetId) {
            const reviewer = prompt('Reviewer name:');
            if (!reviewer) return;
            const clearance = prompt('Clearance (ouo or public):', 'ouo');
            if (!clearance) return;

            try {
                const resp = await fetch(`${API_BASE_URL}/api/assets/${assetId}/approve`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({reviewer, clearance_state: clearance})
                });
                const data = await resp.json();
                if (data.success) {
                    alert('Approved successfully');
                    loadAssetVersions();
                } else {
                    alert('Error: ' + (data.error || 'Unknown'));
                }
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function rejectRelease(assetId) {
            const reviewer = prompt('Reviewer name:');
            if (!reviewer) return;
            const reason = prompt('Rejection reason:');
            if (!reason) return;

            try {
                const resp = await fetch(`${API_BASE_URL}/api/assets/${assetId}/reject`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({reviewer, reason})
                });
                const data = await resp.json();
                if (data.success) {
                    alert('Rejected');
                    loadAssetVersions();
                } else {
                    alert('Error: ' + (data.error || 'Unknown'));
                }
            } catch (e) { alert('Error: ' + e.message); }
        }

        async function revokeRelease(assetId) {
            const reviewer = prompt('Reviewer name:');
            if (!reviewer) return;
            const reason = prompt('Revocation reason:');
            if (!reason) return;

            try {
                const resp = await fetch(`${API_BASE_URL}/api/assets/${assetId}/revoke`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({reviewer, reason})
                });
                const data = await resp.json();
                if (data.success) {
                    alert('Revoked');
                    loadAssetVersions();
                } else {
                    alert('Error: ' + (data.error || 'Unknown'));
                }
            } catch (e) { alert('Error: ' + e.message); }
        }

        // Load on page ready
        document.addEventListener('DOMContentLoaded', loadAssetVersions);
        """


interface = AssetVersionsInterface()
```

**Step 3: Register in `__init__.py`**

Add auto-import block in `web_interfaces/__init__.py` after the last existing import (near end of file):

```python
try:
    from .asset_versions import interface as _asset_versions
    logger.info("Imported Asset Versions interface module")
except ImportError as e:
    logger.warning(f"Could not import Asset Versions interface: {e}")
```

**Step 4: Verify registration**

Run: `conda activate azgeo && python -c "from web_interfaces import InterfaceRegistry; print('asset-versions' in InterfaceRegistry.list_all())"`
Expected: `True`

**Step 5: Commit**

```bash
git add web_interfaces/asset_versions/ web_interfaces/__init__.py
git commit -m "Add Asset Versions interface: table with expandable release details and approval actions"
```

---

## Task 4: Update STAC Interface — V0.9 Approval Pattern

**Files:**
- Modify: `web_interfaces/stac/interface.py`

**Step 1: Replace V0.8 approval lookup with V0.9 pattern**

Find the JavaScript that fetches approval statuses (around lines 645-657):

```javascript
// OLD V0.8 pattern - REPLACE THIS:
if (allCollections.length > 0) {
    const collectionIds = allCollections.map(c => c.id).join(',');
    try {
        const approvalData = await fetchJSON(
            `${API_BASE_URL}/api/platform/approvals/status?stac_collection_ids=${encodeURIComponent(collectionIds)}`
        );
        window.approvalStatuses = approvalData.statuses || {};
    } catch (e) {
        console.warn('Could not fetch approval statuses:', e);
        window.approvalStatuses = {};
    }
}
```

Replace with:

```javascript
// V0.9 approval stats
try {
    const approvalResp = await fetch(`${API_BASE_URL}/api/assets/approval-stats`);
    if (approvalResp.ok) {
        window.approvalStats = await approvalResp.json();
    }
} catch (e) {
    console.warn('Could not fetch approval stats:', e);
    window.approvalStats = {};
}
```

**Step 2: Update collection card approval badge rendering**

Find the approval badge rendering (around lines 694-728). Update the badge logic to use the V0.9 approval badge CSS class pattern. The exact lines will depend on what the current code looks like — look for references to `approvalStatuses` and `is_approved`.

Replace references like:
```javascript
const isApproved = approvalStatus.is_approved === true;
```

With V0.9 badge rendering (if collection-level approval data isn't available, show a "Versions" link instead):

```javascript
// Add Versions link to collection card action buttons
actionButtons += `<a href="/api/interface/asset-versions?dataset_id=${encodeURIComponent(c.id)}" class="btn btn-sm btn-secondary">Versions</a>`;
```

**Step 3: Add version_ordinal to items table**

In the items table rendering (around lines 1237-1257), verify columns match V0.9 patterns. The items themselves come from pgSTAC and may not change, but add a "Versions" link in the collection detail view.

**Step 4: Verify no import errors**

Run: `conda activate azgeo && python -c "from web_interfaces.stac.interface import StacInterface; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add web_interfaces/stac/interface.py
git commit -m "Update STAC interface to V0.9 approval patterns, add Versions link"
```

---

## Task 5: Update Jobs Interface — Release Association

**Files:**
- Modify: `web_interfaces/jobs/interface.py`

**Step 1: Add Asset/Version columns to the jobs table header**

Find the table header (around lines 359-368):

```html
<thead>
    <tr>
        <th>Job ID</th>
        <th>Job Type</th>
        <th>Status</th>
        <th>Stage</th>
        <th>Tasks</th>
        <th>Created</th>
        <th>Actions</th>
    </tr>
</thead>
```

Add `Asset` column after `Job Type`:

```html
<thead>
    <tr>
        <th>Job ID</th>
        <th>Job Type</th>
        <th>Asset</th>
        <th>Status</th>
        <th>Stage</th>
        <th>Tasks</th>
        <th>Created</th>
        <th>Actions</th>
    </tr>
</thead>
```

**Step 2: Add asset cell to job row rendering**

Find the row rendering code (around lines 135-146). Add asset column cell. Since jobs don't natively carry asset info, display dataset_id from the job parameters if available:

```python
# Extract dataset context from job parameters (if available)
job_params = job.get('parameters', {}) or {}
dataset_id = job_params.get('dataset_id', '')
resource_id = job_params.get('resource_id', '')
if dataset_id:
    asset_link = f'<a href="/api/interface/asset-versions?dataset_id={dataset_id}&resource_id={resource_id}" title="{dataset_id}/{resource_id}">{dataset_id[:15]}</a>'
else:
    asset_link = '—'
```

Then insert the cell into the row HTML after the job_type cell:

```html
<td>{asset_link}</td>
```

**Step 3: Verify no import errors**

Run: `conda activate azgeo && python -c "from web_interfaces.jobs.interface import JobsInterface; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add web_interfaces/jobs/interface.py
git commit -m "Add asset column to Jobs interface linking to Asset Versions page"
```

---

## Task 6: Update Home Interface — Approval Queue Card + Asset Versions Link

**Files:**
- Modify: `web_interfaces/home/interface.py`

**Step 1: Add Asset Versions card to Browse Data section**

Find the Browse Data section (lines 82-107). Insert a new card after the Map Viewer card (after line 105, before the closing `</div>` on line 106):

```html
<a href="/api/interface/asset-versions" class="card">
    <div class="card-icon">&#128209;</div>
    <h3 class="card-title">Asset Versions</h3>
    <p class="card-description">Browse asset release history and approval workflow</p>
    <div class="card-footer">View Assets</div>
</a>
```

**Step 2: Add Approval Queue card to System section**

Find the System section cards grid (lines 112-168). Insert after the Job Monitor card (after line 125):

```html
<a href="/api/interface/asset-versions" class="card">
    <div class="card-icon">&#9989;</div>
    <h3 class="card-title">Approval Queue</h3>
    <p class="card-description">Review and approve pending dataset releases</p>
    <div class="card-footer">Review Queue</div>
</a>
```

**Step 3: Verify rendering**

Run: `conda activate azgeo && python -c "from web_interfaces.home.interface import HomeInterface; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add web_interfaces/home/interface.py
git commit -m "Add Asset Versions and Approval Queue cards to Home interface"
```

---

## Task 7: Update Platform Interface — Version Summary

**Files:**
- Modify: `web_interfaces/platform/interface.py`

**Step 1: Add approval stats to platform status section**

Find the Platform Status section (around lines 246-265). Add an approval summary display after the existing "Success Rate" span (around line 263):

```html
<div>
    <strong>Pending Review:</strong>
    <span id="pending-review-count">--</span>
</div>
<div>
    <a href="/api/interface/asset-versions" style="color: var(--ds-blue-primary); text-decoration: none; font-weight: 600;">
        Asset Versions &rarr;
    </a>
</div>
```

**Step 2: Add JS to fetch approval stats**

In the JavaScript section, find the `loadPlatformHealth()` function (around lines 422-456). Add approval stats fetch:

```javascript
// Fetch V0.9 approval stats
try {
    const approvalResp = await fetch(`${API_BASE_URL}/api/assets/approval-stats`);
    if (approvalResp.ok) {
        const stats = await approvalResp.json();
        const pendingEl = document.getElementById('pending-review-count');
        if (pendingEl && stats.pending_review !== undefined) {
            pendingEl.textContent = stats.pending_review;
            if (stats.pending_review > 0) {
                pendingEl.style.color = '#d97706';
                pendingEl.style.fontWeight = '700';
            }
        }
    }
} catch (e) {
    console.warn('Could not fetch approval stats:', e);
}
```

**Step 3: Verify rendering**

Run: `conda activate azgeo && python -c "from web_interfaces.platform.interface import PlatformInterface; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "Add approval stats and Asset Versions link to Platform interface"
```

---

## Task 8: Update Navbar — Add Asset Versions Link

**Files:**
- Modify: `web_interfaces/base.py:2006-2074` (navbar rendering)

**Step 1: Add Asset Versions nav link**

Find the `_render_navbar()` method (around line 2006). Add a new navigation link in the nav items. Insert after the "Pipelines" link and before the "STAC" link:

```html
<a href="/api/interface/asset-versions" class="nav-link">Assets</a>
```

**Step 2: Verify navbar renders**

Run: `conda activate azgeo && python -c "from web_interfaces.base import BaseInterface; b = BaseInterface(); html = b._render_navbar(); assert 'asset-versions' in html; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add web_interfaces/base.py
git commit -m "Add Assets link to navbar for V0.9 version management"
```

---

## Task 9: Extend Status Endpoint Versions Array — Include Physical Outputs

**Files:**
- Modify: `triggers/trigger_platform_status.py:716-745` (`_build_version_summary`)

**Context:** The Asset Versions page needs `blob_path`, `table_name`, `stac_item_id`, `stac_collection_id` in each version entry for the expanded detail row. Currently the `_build_version_summary` only includes identity and state fields.

**Step 1: Check current version summary fields**

Read `triggers/trigger_platform_status.py` around lines 716-745 to confirm what `_build_version_summary` returns. Then add the physical output fields.

Add to the version summary dict (inside `_build_version_summary`):

```python
"blob_path": getattr(release, 'blob_path', None),
"table_name": getattr(release, 'table_name', None),
"stac_item_id": getattr(release, 'stac_item_id', None),
"stac_collection_id": getattr(release, 'stac_collection_id', None),
```

**Step 2: Verify response shape**

Run: `conda activate azgeo && python -c "from triggers.trigger_platform_status import _build_version_summary; print('OK')"`
Expected: No import errors

**Step 3: Commit**

```bash
git add triggers/trigger_platform_status.py
git commit -m "Add physical outputs to version summary for Asset Versions UI"
```

---

## Task 10: Final Verification and Cleanup

**Step 1: Verify all interfaces import cleanly**

Run:
```bash
conda activate azgeo && python -c "
from web_interfaces import InterfaceRegistry
interfaces = InterfaceRegistry.list_all()
print(f'{len(interfaces)} interfaces registered')
assert 'asset-versions' in interfaces, 'asset-versions missing!'
print('All imports OK')
for name in sorted(interfaces):
    print(f'  - {name}')
"
```

Expected: All interfaces listed including `asset-versions`, no import errors.

**Step 2: Verify CSS/JS helpers work end-to-end**

Run:
```bash
conda activate azgeo && python -c "
from web_interfaces.base import BaseInterface
b = BaseInterface()
# Test all V0.9 helpers
print(b.render_approval_badge('approved'))
print(b.render_approval_badge('pending_review'))
print(b.render_clearance_badge('public'))
print(b.render_clearance_badge('ouo'))
print(b.render_version_chip('v2', 2, True))
print(b.render_version_chip(None, 3, False))
print(b.render_asset_header({'dataset_id': 'test', 'resource_id': 'res', 'data_type': 'raster', 'asset_id': 'abc123def456', 'release_count': 3}))
print('All helpers OK')
"
```

Expected: All badge/chip/header HTML renders without errors.

**Step 3: Commit any remaining changes**

```bash
git add -A && git status
# Only commit if there are changes
git commit -m "V0.9 interface sweep: final cleanup"
```

---

## Summary of Changes

| Task | File(s) | What |
|------|---------|------|
| 1 | `base.py` CSS | V0.9 approval, clearance, version badge styles |
| 2 | `base.py` methods | Python render helpers |
| 3 | `asset_versions/` + `__init__.py` | New Asset Versions page |
| 4 | `stac/interface.py` | V0.9 approval pattern + Versions link |
| 5 | `jobs/interface.py` | Asset column linking to versions |
| 6 | `home/interface.py` | Asset Versions + Approval Queue cards |
| 7 | `platform/interface.py` | Approval stats + version link |
| 8 | `base.py` navbar | Assets nav link |
| 9 | `trigger_platform_status.py` | Physical outputs in version summary |
| 10 | All | Final verification |
