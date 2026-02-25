# Platform Status Lookup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add interactive status lookup and updated endpoint reference table to the existing platform interface page (`/api/interface/platform`).

**Architecture:** Single-file change to `web_interfaces/platform/interface.py`. Add `htmx_partial()` method with a `status-lookup` fragment that calls `GET /api/platform/status/{id}?detail=full` (or `?dataset_id&resource_id`) via internal HTTP, then renders the JSON response as styled HTML cards. Also update the static endpoint reference table.

**Tech Stack:** Python (Azure Functions), HTMX for partial updates, internal HTTP via `urllib.request`, HTML/CSS/JS rendering in Python strings.

---

### Task 1: Add `htmx_partial()` method and status lookup fragment handler

**Files:**
- Modify: `web_interfaces/platform/interface.py`

**Step 1: Add htmx_partial method to PlatformInterface**

Add after the existing `render()` method (line ~37):

```python
def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
    """Handle HTMX partial requests for platform fragments."""
    if fragment == 'status-lookup':
        return self._render_status_lookup_fragment(request)
    else:
        raise ValueError(f"Unknown fragment: {fragment}")
```

**Step 2: Add the status lookup fragment handler**

Add new method `_render_status_lookup_fragment()`. This method:
1. Reads `lookup_type` and `lookup_id` (or `dataset_id` + `resource_id`) from form POST body
2. Builds the appropriate URL:
   - For `dataset_resource`: `GET /api/platform/status?dataset_id=X&resource_id=Y`
   - For all others: `GET /api/platform/status/{id}?detail=full`
3. Calls the URL via `urllib.request` (same pattern as `web_interfaces/submit/interface.py:440-465`)
4. On success: passes JSON to `_render_status_result(data)`
5. On error (404, 500, connection): passes to `_render_status_error(message)`

```python
def _render_status_lookup_fragment(self, request: func.HttpRequest) -> str:
    """Call /api/platform/status and render result as HTML cards."""
    import json
    import urllib.request
    import urllib.error
    import os
    from urllib.parse import urlencode, quote

    # Parse form data
    body = request.get_body().decode('utf-8')
    from urllib.parse import parse_qs
    form_data = parse_qs(body)

    def get_param(key, default=None):
        values = form_data.get(key, [])
        return values[0].strip() if values and values[0].strip() else default

    lookup_type = get_param('lookup_type', 'request_id')
    lookup_id = get_param('lookup_id')
    dataset_id = get_param('dataset_id')
    resource_id = get_param('resource_id')

    # Validate input
    if lookup_type == 'dataset_resource':
        if not dataset_id or not resource_id:
            return self._render_status_error("Both dataset_id and resource_id are required")
    else:
        if not lookup_id:
            return self._render_status_error(f"Please enter a {lookup_type.replace('_', ' ')}")

    # Build URL
    website_hostname = os.environ.get('WEBSITE_HOSTNAME')
    if not website_hostname:
        return self._render_status_error("WEBSITE_HOSTNAME not set - cannot call Platform API")

    if lookup_type == 'dataset_resource':
        params = urlencode({'dataset_id': dataset_id, 'resource_id': resource_id})
        api_url = f"https://{website_hostname}/api/platform/status?{params}"
    else:
        api_url = f"https://{website_hostname}/api/platform/status/{quote(lookup_id)}?detail=full"

    # Call Platform Status API
    try:
        http_req = urllib.request.Request(api_url, method='GET')
        with urllib.request.urlopen(http_req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return self._render_status_result(data)

    except urllib.error.HTTPError as http_err:
        error_body = http_err.read().decode('utf-8')
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get('error', str(http_err))
            hint = error_json.get('hint', '')
            if hint:
                error_msg += f" ({hint})"
        except Exception:
            error_msg = error_body or str(http_err)
        return self._render_status_error(f"HTTP {http_err.code}: {error_msg}")

    except urllib.error.URLError as url_err:
        return self._render_status_error(f"Connection error: {url_err}")

    except Exception as e:
        return self._render_status_error(str(e))
```

**Step 3: Verify the fragment routing works**

Run locally or test that `GET /api/interface/platform?fragment=status-lookup` with POST body is routed correctly through `unified_interface_handler` -> `htmx_partial` -> `_render_status_lookup_fragment`.

**Step 4: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "feat(platform): Add htmx_partial with status-lookup fragment handler"
```

---

### Task 2: Add status result renderer

**Files:**
- Modify: `web_interfaces/platform/interface.py`

**Step 1: Add `_render_status_result()` method**

This renders the full API response as styled HTML cards. Each block is conditionally shown.

```python
def _render_status_result(self, data: dict) -> str:
    """Render platform status API response as HTML cards."""
    if not data.get('success'):
        return self._render_status_error(data.get('error', 'Unknown error'))

    html_parts = []

    # --- Asset card ---
    asset = data.get('asset')
    if asset:
        html_parts.append(f'''
        <div class="result-card">
            <h3 class="result-card-title">Asset</h3>
            <div class="result-grid">
                <div class="result-field">
                    <span class="result-label">Dataset</span>
                    <span class="result-value mono">{self._esc(asset.get('dataset_id', ''))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Resource</span>
                    <span class="result-value mono">{self._esc(asset.get('resource_id', ''))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Data Type</span>
                    <span class="result-value">{self._data_type_badge(asset.get('data_type', ''))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Releases</span>
                    <span class="result-value">{asset.get('release_count', 0)}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Asset ID</span>
                    <span class="result-value mono small">{self._esc(asset.get('asset_id', ''))}</span>
                </div>
            </div>
        </div>''')

    # --- Release card ---
    release = data.get('release')
    if release:
        html_parts.append(f'''
        <div class="result-card">
            <h3 class="result-card-title">Release</h3>
            <div class="result-grid">
                <div class="result-field">
                    <span class="result-label">Version</span>
                    <span class="result-value mono">{self._esc(release.get('version_id', 'draft'))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Ordinal</span>
                    <span class="result-value">ord{release.get('version_ordinal', '?')}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Revision</span>
                    <span class="result-value">{release.get('revision', 0)}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Latest</span>
                    <span class="result-value">{'Yes' if release.get('is_latest') else 'No'}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Processing</span>
                    <span class="result-value">{self._status_badge(release.get('processing_status', ''))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Approval</span>
                    <span class="result-value">{self._approval_badge(release.get('approval_state', ''))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Clearance</span>
                    <span class="result-value">{self._clearance_badge(release.get('clearance_state', ''))}</span>
                </div>
                <div class="result-field">
                    <span class="result-label">Release ID</span>
                    <span class="result-value mono small">{self._esc(release.get('release_id', ''))}</span>
                </div>
            </div>
        </div>''')

    # --- Job Status card ---
    job_status = data.get('job_status', 'unknown')
    detail = data.get('detail') or {}
    job_id = detail.get('job_id', '')
    job_type = detail.get('job_type', '')
    html_parts.append(f'''
    <div class="result-card">
        <h3 class="result-card-title">Job</h3>
        <div class="result-grid">
            <div class="result-field">
                <span class="result-label">Status</span>
                <span class="result-value">{self._status_badge(job_status)}</span>
            </div>
            {'<div class="result-field"><span class="result-label">Job ID</span><span class="result-value mono small">' + self._esc(job_id) + '</span></div>' if job_id else ''}
            {'<div class="result-field"><span class="result-label">Type</span><span class="result-value mono">' + self._esc(job_type) + '</span></div>' if job_type else ''}
            {'<div class="result-field"><span class="result-label">Stage</span><span class="result-value">' + str(detail.get("job_stage", "")) + '</span></div>' if detail.get("job_stage") else ''}
        </div>
        {self._job_link(job_id) if job_id else ''}
    </div>''')

    # --- Error card (only for failed jobs) ---
    error = data.get('error')
    if error:
        remediation = error.get('remediation', '')
        html_parts.append(f'''
        <div class="result-card result-card-error">
            <h3 class="result-card-title">Error</h3>
            <div class="result-grid">
                {'<div class="result-field"><span class="result-label">Code</span><span class="result-value mono">' + self._esc(error.get("code", "")) + '</span></div>' if error.get("code") else ''}
                {'<div class="result-field"><span class="result-label">Category</span><span class="result-value">' + self._esc(error.get("category", "")) + '</span></div>' if error.get("category") else ''}
                <div class="result-field full-width">
                    <span class="result-label">Message</span>
                    <span class="result-value">{self._esc(error.get('message', ''))}</span>
                </div>
                {'<div class="result-field full-width"><span class="result-label">Remediation</span><span class="result-value">' + self._esc(remediation) + '</span></div>' if remediation else ''}
                {'<div class="result-field"><span class="result-label">User Fixable</span><span class="result-value">' + ("Yes" if error.get("user_fixable") else "No") + '</span></div>' if "user_fixable" in error else ''}
            </div>
        </div>''')

    # --- Outputs card ---
    outputs = data.get('outputs')
    if outputs:
        html_parts.append(f'''
        <div class="result-card">
            <h3 class="result-card-title">Outputs</h3>
            <div class="result-grid">
                {'<div class="result-field full-width"><span class="result-label">Blob Path</span><span class="result-value mono small">' + self._esc(outputs.get("blob_path", "")) + '</span></div>' if outputs.get("blob_path") else ''}
                {'<div class="result-field"><span class="result-label">Table</span><span class="result-value mono">' + self._esc(outputs.get("table_name", "")) + '</span></div>' if outputs.get("table_name") else ''}
                {'<div class="result-field"><span class="result-label">Schema</span><span class="result-value mono">' + self._esc(outputs.get("schema", "")) + '</span></div>' if outputs.get("schema") else ''}
                {'<div class="result-field"><span class="result-label">STAC Item</span><span class="result-value mono">' + self._esc(outputs.get("stac_item_id", "")) + '</span></div>' if outputs.get("stac_item_id") else ''}
                {'<div class="result-field"><span class="result-label">STAC Collection</span><span class="result-value mono">' + self._esc(outputs.get("stac_collection_id", "")) + '</span></div>' if outputs.get("stac_collection_id") else ''}
                {'<div class="result-field"><span class="result-label">Container</span><span class="result-value mono">' + self._esc(outputs.get("container", "")) + '</span></div>' if outputs.get("container") else ''}
            </div>
        </div>''')

    # --- Services card ---
    services = data.get('services')
    if services:
        links = []
        # Map service keys to display labels
        service_labels = {
            'preview': 'Preview', 'tiles': 'Tiles', 'viewer': 'Viewer',
            'collection': 'Collection', 'items': 'Items',
            'stac_collection': 'STAC Collection', 'stac_item': 'STAC Item',
        }
        for key, label in service_labels.items():
            url = services.get(key)
            if url:
                links.append(f'<a href="{self._esc(url)}" target="_blank" class="service-link">{label}</a>')

        if links:
            html_parts.append(f'''
            <div class="result-card">
                <h3 class="result-card-title">Services</h3>
                <div class="service-links">
                    {" ".join(links)}
                </div>
            </div>''')

    # --- Approval card ---
    approval = data.get('approval')
    if approval:
        html_parts.append(f'''
        <div class="result-card result-card-approval">
            <h3 class="result-card-title">Pending Approval</h3>
            <div class="result-grid">
                <div class="result-field">
                    <span class="result-label">Asset ID</span>
                    <span class="result-value mono small">{self._esc(approval.get('asset_id', ''))}</span>
                </div>
                {'<div class="result-field"><span class="result-label">Approve URL</span><span class="result-value mono small">' + self._esc(approval.get("approve_url", "")) + '</span></div>' if approval.get("approve_url") else ''}
            </div>
            {self._approval_viewer_link(approval)}
        </div>''')

    # --- Versions table ---
    versions = data.get('versions')
    if versions and len(versions) > 0:
        rows = []
        for v in versions:
            rows.append(f'''<tr>
                <td class="mono">{self._esc(v.get('version_id', 'draft'))}</td>
                <td>ord{v.get('version_ordinal', '?')}</td>
                <td>{self._status_badge(v.get('processing_status', ''))}</td>
                <td>{self._approval_badge(v.get('approval_state', ''))}</td>
                <td>{self._clearance_badge(v.get('clearance_state', ''))}</td>
                <td>{'Yes' if v.get('is_latest') else ''}</td>
                <td class="mono small">{self._esc(v.get('release_id', '')[:16]) + '...' if v.get('release_id', '') else ''}</td>
            </tr>''')

        html_parts.append(f'''
        <div class="result-card">
            <h3 class="result-card-title">Version History</h3>
            <table class="versions-table">
                <thead>
                    <tr>
                        <th>Version</th>
                        <th>Ordinal</th>
                        <th>Processing</th>
                        <th>Approval</th>
                        <th>Clearance</th>
                        <th>Latest</th>
                        <th>Release ID</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        </div>''')

    # --- Request ID (top-level) ---
    request_id = data.get('request_id')
    request_id_html = ''
    if request_id:
        request_id_html = f'<div class="request-id-bar">Request ID: <span class="mono">{self._esc(request_id)}</span></div>'

    return f'''
    <div class="status-result-container">
        {request_id_html}
        {"".join(html_parts)}
    </div>'''
```

**Step 2: Add helper methods for badges, escaping, links**

```python
@staticmethod
def _esc(value: str) -> str:
    """HTML-escape a string."""
    import html as html_mod
    return html_mod.escape(str(value)) if value else ''

@staticmethod
def _status_badge(status: str) -> str:
    """Render a processing/job status badge."""
    colors = {
        'completed': ('badge-success', 'completed'),
        'failed': ('badge-error', 'failed'),
        'processing': ('badge-processing', 'processing'),
        'pending': ('badge-pending', 'pending'),
        'queued': ('badge-pending', 'queued'),
        'unknown': ('badge-unknown', 'unknown'),
    }
    css_class, label = colors.get(status, ('badge-unknown', status))
    return f'<span class="badge {css_class}">{label}</span>'

@staticmethod
def _approval_badge(state: str) -> str:
    """Render an approval state badge."""
    colors = {
        'approved': 'badge-success',
        'pending_review': 'badge-warning',
        'rejected': 'badge-error',
        'revoked': 'badge-error',
        'draft': 'badge-pending',
        'not_submitted': 'badge-unknown',
    }
    css_class = colors.get(state, 'badge-unknown')
    return f'<span class="badge {css_class}">{state}</span>'

@staticmethod
def _clearance_badge(state: str) -> str:
    """Render a clearance state badge."""
    colors = {
        'cleared': 'badge-success',
        'pending': 'badge-pending',
        'not_cleared': 'badge-unknown',
    }
    css_class = colors.get(state, 'badge-unknown')
    return f'<span class="badge {css_class}">{state}</span>'

@staticmethod
def _data_type_badge(data_type: str) -> str:
    """Render a data type badge."""
    colors = {
        'raster': 'badge-raster',
        'vector': 'badge-vector',
    }
    css_class = colors.get(data_type, 'badge-unknown')
    return f'<span class="badge {css_class}">{data_type}</span>'

@staticmethod
def _job_link(job_id: str) -> str:
    """Render a link to the execution dashboard for a job."""
    if not job_id:
        return ''
    return f'<div class="result-actions"><a href="/api/interface/execution?job_id={job_id}" class="action-link">View in Execution Dashboard</a></div>'

@staticmethod
def _approval_viewer_link(approval: dict) -> str:
    """Render viewer link for pending approval."""
    viewer = approval.get('viewer_url')
    if not viewer:
        return ''
    import html as html_mod
    return f'<div class="result-actions"><a href="{html_mod.escape(viewer)}" target="_blank" class="action-link">Open Viewer for Review</a></div>'
```

**Step 3: Add `_render_status_error()` method**

```python
def _render_status_error(self, message: str) -> str:
    """Render error state for status lookup."""
    return f'''
    <div class="status-result-container">
        <div class="result-card result-card-error">
            <h3 class="result-card-title">Lookup Failed</h3>
            <p class="error-message">{self._esc(message)}</p>
        </div>
    </div>'''
```

**Step 4: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "feat(platform): Add status result renderer with all response cards"
```

---

### Task 3: Add Status Lookup HTML section and input JS

**Files:**
- Modify: `web_interfaces/platform/interface.py`

**Step 1: Add Status Lookup section to `_generate_html_content()`**

Insert after the Platform Status `</div>` (line ~273) and before the DDH Naming Patterns section:

```html
<!-- Status Lookup -->
<div class="section">
    <h2>Status Lookup</h2>
    <p style="color: var(--ds-gray); margin-bottom: 16px;">
        Look up any Platform request, job, asset, or release by ID.
    </p>
    <form id="status-lookup-form" class="lookup-form"
          hx-post="/api/interface/platform?fragment=status-lookup"
          hx-target="#status-result"
          hx-indicator="#lookup-spinner">
        <div class="lookup-controls">
            <select name="lookup_type" id="lookup-type" class="lookup-select"
                    onchange="updateLookupInputs()">
                <option value="request_id">Request ID</option>
                <option value="job_id">Job ID</option>
                <option value="dataset_resource">Dataset + Resource</option>
                <option value="asset_id">Asset ID</option>
                <option value="release_id">Release ID</option>
            </select>
            <div id="lookup-inputs" class="lookup-inputs">
                <input type="text" name="lookup_id" id="lookup-id"
                       placeholder="Enter Request ID..."
                       class="lookup-input">
            </div>
            <button type="submit" class="btn btn-primary">Search</button>
            <span id="lookup-spinner" class="htmx-indicator spinner-inline"></span>
        </div>
    </form>
    <div id="status-result"></div>
</div>
```

**Step 2: Add JS for input switching to `_generate_js()`**

Add `updateLookupInputs()` function:

```javascript
function updateLookupInputs() {
    const lookupType = document.getElementById('lookup-type').value;
    const container = document.getElementById('lookup-inputs');

    const placeholders = {
        'request_id': 'Enter Request ID...',
        'job_id': 'Enter Job ID...',
        'asset_id': 'Enter Asset ID...',
        'release_id': 'Enter Release ID...',
    };

    if (lookupType === 'dataset_resource') {
        container.innerHTML = `
            <input type="text" name="dataset_id" id="lookup-dataset"
                   placeholder="dataset_id" class="lookup-input lookup-input-half">
            <input type="text" name="resource_id" id="lookup-resource"
                   placeholder="resource_id" class="lookup-input lookup-input-half">
        `;
    } else {
        container.innerHTML = `
            <input type="text" name="lookup_id" id="lookup-id"
                   placeholder="${placeholders[lookupType] || 'Enter ID...'}"
                   class="lookup-input">
        `;
    }
}
```

**Step 3: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "feat(platform): Add status lookup HTML section and input-switching JS"
```

---

### Task 4: Add CSS for status lookup and result cards

**Files:**
- Modify: `web_interfaces/platform/interface.py`

**Step 1: Add CSS to `_generate_css()`**

Append to the existing CSS string:

```css
/* Status Lookup Form */
.lookup-form { margin-bottom: 20px; }
.lookup-controls {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
}
.lookup-select {
    padding: 8px 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 14px;
    background: white;
    min-width: 180px;
}
.lookup-inputs { display: flex; gap: 8px; flex: 1; min-width: 200px; }
.lookup-input {
    padding: 8px 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 14px;
    font-family: 'Monaco', 'Consolas', monospace;
    flex: 1;
}
.lookup-input-half { flex: 1; }
.lookup-input:focus { outline: none; border-color: var(--ds-blue-primary); box-shadow: 0 0 0 2px rgba(0,113,188,0.2); }

/* Result Cards */
.status-result-container { margin-top: 16px; }
.request-id-bar {
    padding: 8px 12px;
    background: #f0f4f8;
    border-radius: 4px;
    font-size: 13px;
    color: #626F86;
    margin-bottom: 12px;
}
.result-card {
    background: #f8f9fa;
    border: 1px solid #e1e4e8;
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 12px;
}
.result-card-error {
    background: #fef2f2;
    border-color: #fecaca;
}
.result-card-approval {
    background: #fffbeb;
    border-color: #fde68a;
}
.result-card-title {
    color: var(--ds-blue-primary);
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #e1e4e8;
}
.result-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
}
.result-field { display: flex; flex-direction: column; gap: 2px; }
.result-field.full-width { grid-column: 1 / -1; }
.result-label { font-size: 11px; color: #626F86; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
.result-value { font-size: 14px; color: #1a1a2e; }
.result-value.mono { font-family: 'Monaco', 'Consolas', monospace; font-size: 13px; }
.result-value.small, .mono.small { font-size: 11px; word-break: break-all; }
.error-message { color: #991b1b; font-size: 14px; margin: 0; }

/* Badges */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
}
.badge-success { background: #d1fae5; color: #065f46; }
.badge-error { background: #fee2e2; color: #991b1b; }
.badge-processing { background: #dbeafe; color: #1e40af; }
.badge-pending { background: #e0e7ff; color: #3730a3; }
.badge-warning { background: #fef3c7; color: #92400e; }
.badge-unknown { background: #f3f4f6; color: #6b7280; }
.badge-raster { background: #dbeafe; color: #1e40af; }
.badge-vector { background: #d1fae5; color: #065f46; }

/* Service Links */
.service-links { display: flex; gap: 8px; flex-wrap: wrap; }
.service-link {
    display: inline-block;
    padding: 6px 14px;
    background: var(--ds-blue-primary);
    color: white;
    text-decoration: none;
    border-radius: 4px;
    font-size: 13px;
    font-weight: 600;
}
.service-link:hover { opacity: 0.85; }

/* Action Links */
.result-actions { margin-top: 12px; padding-top: 8px; border-top: 1px solid #e1e4e8; }
.action-link {
    color: var(--ds-blue-primary);
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
}
.action-link:hover { text-decoration: underline; }

/* Versions Table */
.versions-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.versions-table th, .versions-table td {
    padding: 8px 10px;
    text-align: left;
    border-bottom: 1px solid #e1e4e8;
}
.versions-table th {
    background: #f0f4f8;
    font-weight: 600;
    color: var(--ds-navy);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Spinner for HTMX */
.spinner-inline { display: none; width: 20px; height: 20px; }
.htmx-indicator.spinner-inline { display: inline-block; }
```

**Step 2: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "feat(platform): Add CSS for status lookup form, result cards, and badges"
```

---

### Task 5: Update the endpoint reference table

**Files:**
- Modify: `web_interfaces/platform/interface.py`

**Step 1: Replace the endpoint table HTML in `_generate_html_content()`**

Replace the existing `<tbody>` content (lines ~350-391) with the current endpoint set, grouped by category:

```html
<tbody>
    <!-- Submit/Status -->
    <tr><td colspan="3" class="endpoint-group">Submit / Status</td></tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/submit</code></td>
        <td>Submit DDH request (auto-detects raster/vector). <code>?dry_run=true</code> for validation.</td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/status/{id}</code></td>
        <td>Lookup by any ID (request, job, asset, release — auto-detected). <code>?detail=full</code></td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/status</code></td>
        <td>List requests. Filter: <code>?dataset_id=X&amp;resource_id=Y</code> or <code>?limit=N</code></td>
    </tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/validate</code></td>
        <td>Pre-flight validation (same body as submit)</td>
    </tr>
    <!-- Approvals -->
    <tr><td colspan="3" class="endpoint-group">Approvals</td></tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/approve</code></td>
        <td>Approve pending dataset for publication</td>
    </tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/reject</code></td>
        <td>Reject pending dataset (reason required)</td>
    </tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/revoke</code></td>
        <td>Revoke approved dataset (reason required)</td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/approvals</code></td>
        <td>List approvals. Filter: <code>?status=&amp;classification=&amp;limit=</code></td>
    </tr>
    <!-- Catalog -->
    <tr><td colspan="3" class="endpoint-group">Catalog</td></tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/catalog/lookup</code></td>
        <td>Unified lookup by DDH IDs: <code>?dataset_id=&amp;resource_id=&amp;version_id=</code></td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/catalog/asset/{id}</code></td>
        <td>Asset details + service URLs</td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/catalog/dataset/{id}</code></td>
        <td>All assets (raster + vector) for a DDH dataset</td>
    </tr>
    <!-- Operations -->
    <tr><td colspan="3" class="endpoint-group">Operations</td></tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/unpublish</code></td>
        <td>Unpublish by DDH IDs, request_id, or job_id. <code>?dry_run=true</code> (default)</td>
    </tr>
    <tr>
        <td><span class="method post">POST</span></td>
        <td><code class="endpoint-path">/api/platform/resubmit</code></td>
        <td>Resubmit failed job with cleanup</td>
    </tr>
    <!-- Diagnostics -->
    <tr><td colspan="3" class="endpoint-group">Diagnostics</td></tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/health</code></td>
        <td>System readiness check (simplified for external apps)</td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/failures</code></td>
        <td>Recent failures with sanitized errors. <code>?hours=&amp;limit=</code></td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platform/lineage/{id}</code></td>
        <td>Data lineage trace by request ID</td>
    </tr>
    <!-- Registry -->
    <tr><td colspan="3" class="endpoint-group">Platform Registry</td></tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platforms</code></td>
        <td>List supported B2B platforms</td>
    </tr>
    <tr>
        <td><span class="method get">GET</span></td>
        <td><code class="endpoint-path">/api/platforms/{id}</code></td>
        <td>Platform details with required/optional refs</td>
    </tr>
</tbody>
```

**Step 2: Add CSS for endpoint group rows**

Add to `_generate_css()`:

```css
.endpoint-group {
    background: #f0f4f8;
    font-weight: 700;
    color: var(--ds-navy);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 12px;
}
```

**Step 3: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "feat(platform): Update endpoint reference table — remove deprecated, add all current"
```

---

### Task 6: Smoke test and final commit

**Step 1: Syntax check**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "from web_interfaces.platform.interface import PlatformInterface; print('Import OK')"
```

Expected: `Import OK`

**Step 2: Verify interface registration**

```bash
python -c "from web_interfaces import InterfaceRegistry; print('platform' in InterfaceRegistry.list_all())"
```

Expected: `True`

**Step 3: Verify htmx_partial is callable**

```bash
python -c "
from web_interfaces.platform.interface import PlatformInterface
p = PlatformInterface()
assert hasattr(p, 'htmx_partial'), 'htmx_partial missing'
print('htmx_partial method present')
"
```

Expected: `htmx_partial method present`

**Step 4: Final commit with updated header**

Update the file header `LAST_REVIEWED` to `25 FEB 2026` and docstring to reflect new capabilities.

```bash
git add web_interfaces/platform/interface.py
git commit -m "feat(platform): Status lookup + endpoint table update — complete

V0.9.6: Platform interface enhanced with:
- Interactive status lookup (request, job, dataset+resource, asset, release)
- HTMX-powered result cards showing full API response
- Updated endpoint reference table (removed deprecated, added all current)"
```
