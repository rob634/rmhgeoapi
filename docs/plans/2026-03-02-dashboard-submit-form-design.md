# GREENFIELD Spec: Dashboard Submit Form

**Date**: 02 MAR 2026
**Pipeline**: GREENFIELD (narrowly scoped — single method replacement)
**Goal**: Test narrow-scope GREENFIELD pipeline AND produce a deployable submit form

---

## Tier 1: System Context

### PURPOSE

Replace the stub `_render_submit()` method in `PlatformPanel` with a complete data submission form. The form lets operators browse files in blob storage, configure DDH identifiers and processing options, validate via dry run, and submit a CoreMachine job — all within the existing dashboard HTMX framework.

This is the primary "write" interface in the dashboard. Without it, operators must use cURL or the legacy `/api/interface/submit` page.

### BOUNDARIES

**In scope**:
- Container dropdown populated via HTMX fragment from storage API
- Blob list with metadata (name, size, modified) populated via HTMX fragment
- Single-file click-to-select (raster, vector, zarr/netcdf)
- All DDH identifier fields: dataset_id, resource_id, version_id, previous_version_id
- Data type auto-detected from file extension, displayed as badge
- Type-specific processing options (raster fields vs vector fields)
- Access level selector (OUO, Public, Uncleared)
- Validate (dry run) with inline result display showing warnings and lineage state
- Submit with structured result card (request_id, job_id, job_type, monitor links)
- "View Request" link in success result navigating to Platform/Requests tab

**Out of scope**:
- Multi-file selection for raster collections (future enhancement)
- Live cURL command generation
- Client-side form validation (server validates via dry_run)
- Zarr-specific source_url input (Zarr submits via source_url, not file browser — handle as text input fallback)
- File upload (files are already in blob storage)
- Changes to `base_panel.py` (use existing utilities as-is)
- Changes to any other panel or module

### CONTRACTS

#### Methods to implement (all in `web_dashboard/panels/platform.py`)

**`_render_submit(request) -> str`**
- Input: `func.HttpRequest` with no required params
- Output: Complete HTML form with file browser, DDH fields, processing options, action buttons, result div
- Promises: All user data HTML-escaped. Form posts through dashboard action proxy.

**`_fragment_submit_containers(request) -> str`**
- Input: `func.HttpRequest` (no params required)
- Output: HTML `<option>` elements for container `<select>` dropdown
- Calls: `GET /api/storage/containers?zone=bronze`
- Promises: Returns options for all containers in bronze zone. Returns error block on failure.

**`_fragment_submit_files(request) -> str`**
- Input: `func.HttpRequest` with `container` param (required), optional `prefix` and `suffix` params
- Output: HTML table of blobs with click-to-select rows
- Calls: `GET /api/storage/{container}/blobs?zone=bronze&prefix=X&suffix=Y&limit=500`
- Promises: Each row click populates the file_name hidden input and shows selected file. Returns empty block if no files match.

**`_fragment_submit_options(request) -> str`**
- Input: `func.HttpRequest` with `data_type` param (raster, vector, or empty)
- Output: HTML form fields specific to the detected data type. Returns empty string if type is unknown or zarr (no options needed).
- Promises: Field names use `po_` prefix (e.g., `po_table_name`). All within the `#submit-form` so `hx-include` captures them.

**`_fragment_submit_validate(request) -> str`**
- Input: `func.HttpRequest` with form data (via action proxy)
- Output: HTML result card showing validation outcome
- Note: This is handled by the existing action proxy returning a result card. No separate fragment needed — the validate button posts to `/api/dashboard?action=validate` and the proxy returns the result HTML. Builder should format the `#submit-result` div to show validation-specific details (valid/invalid, warnings, lineage state, suggested params).

#### Fragment dispatch additions

Add to `render_fragment()` dispatch dict:
```
"submit-containers": self._fragment_submit_containers,
"submit-files": self._fragment_submit_files,
"submit-options": self._fragment_submit_options,
```

#### Action proxy change (in `__init__.py`)

Add `po_*` field restructuring before the API call for `submit` and `validate` actions:
```python
# Collect po_* fields into processing_options dict
if action in ("submit", "validate"):
    po_fields = {k[3:]: v for k, v in body.items() if k.startswith("po_") and v}
    for k in list(body):
        if k.startswith("po_"):
            del body[k]
    if po_fields:
        body["processing_options"] = po_fields
```

### INVARIANTS

1. Form field `name` attributes MUST match PlatformRequest DTO field names exactly (the action proxy passes them through as-is to the API).
2. Data type is never user-selected — it is detected from file extension by the API. The form may display the detected type as informational only.
3. File browser always queries bronze zone (source data zone).
4. Selected file state lives in a hidden input, not in JavaScript variables.

### NON-FUNCTIONAL REQUIREMENTS

- **Performance**: Container list fragment <1s. Blob list fragment <3s (may have hundreds of files). Form submission <5s.
- **Security**: All dynamic content escaped with `html_module.escape()`. No inline JavaScript. No `onclick` handlers. All interactivity via HTMX attributes.
- **Accessibility**: All form inputs have associated `<label>` elements. Required fields marked with `required` attribute.

### INFRASTRUCTURE CONTEXT

- Azure Functions consumption plan, Python 3.12
- Dashboard served from `/api/dashboard` on the Orchestrator app (rmhazuregeoapi)
- HTMX 1.9.12 loaded in dashboard shell
- Fragment responses target specific `<div>` elements via `hx-target`
- Action proxy at `/api/dashboard?action=submit|validate` translates form-encoded → JSON → API call → HTML result card

### EXISTING SYSTEM CONTEXT

**BasePanel utilities available** (do not reimplement):
- `self.call_api(request, path, params)` — HTTP client returning `(ok, data)` tuple
- `self.data_table(headers, rows, row_attrs)` — renders `<table>` with optional HTMX attributes per row
- `self.select_filter(name, label, options, selected)` — renders labeled `<select>`
- `self.error_block(message, retry_url)` — renders error div with optional retry
- `self.empty_block(message)` — renders empty state
- `self.status_badge(status)`, `self.data_type_badge(data_type)` — colored badges
- `self.format_date(iso_str)` — military date format
- `self.truncate_id(full_id, length)` — truncated ID with hover title

**Action proxy** (in `__init__.py`, do not modify):
- `submit` action → `POST /api/platform/submit` with JSON body
- `validate` action → `POST /api/platform/validate` with JSON body
- Returns HTML result card (`<div class="result-card success|failure">`)

**API response schemas** (for formatting result displays):

Submit success (202):
```json
{
  "success": true,
  "request_id": "abc123...",
  "job_id": "def456...",
  "job_type": "process_raster_docker",
  "message": "Platform request submitted...",
  "monitor_url": "/api/platform/status/abc123...",
  "warnings": [{"type": "...", "message": "..."}]
}
```

Validate success (200):
```json
{
  "valid": true,
  "dry_run": true,
  "request_id": "abc123...",
  "would_create_job_type": "process_raster_docker",
  "lineage_state": {"lineage_exists": true, "current_latest": {...}},
  "warnings": [],
  "suggested_params": {"previous_version_id": "v1.0"}
}
```

Containers response (200):
```json
{
  "zones": {
    "bronze": {
      "account": "rmhazuregeobronze",
      "containers": ["source-rasters", "source-vectors", ...],
      "container_count": 3
    }
  }
}
```

Blobs response (200):
```json
{
  "blobs": [
    {"name": "path/file.tif", "size_mb": 1000.0, "modified": "2026-02-15T10:30:00Z"}
  ],
  "count": 42
}
```

### OPEN QUESTIONS

1. Should the file browser support prefix filtering (typing a path to narrow results)? The blob API supports a `prefix` param. **Recommendation**: Yes — containers can have hundreds of files. A prefix input is low effort and high value.
2. Should the form show a "Back to file browser" button after selecting a file, allowing re-selection? **Recommendation**: Yes — use an HTMX swap to toggle between file browser and form states.
3. Should processing_options fields be in a collapsible section or always visible? **Recommendation**: Always visible when relevant type is detected. They're only 2-3 fields per type.

---

## Tier 2: Design Constraints

*These go to M and B only. A, C, and O do not see this section.*

### Settled Architectural Patterns

- All HTML is returned as Python f-strings from panel methods
- HTMX fragments use `hx-get="/api/dashboard?tab=platform&fragment=X"` with dispatch through `render_fragment()`
- Form actions use `hx-post="/api/dashboard?action=submit|validate"` with `hx-include="#submit-form"` to send all form fields
- XSS prevention: `html_module.escape()` for all dynamic content in HTML context
- No JavaScript. Zero. All interactivity via HTMX attributes only.

### Integration Rules

- **Primary file**: `web_dashboard/panels/platform.py`
  - Replace: `_render_submit()` (currently lines 511-582)
  - Add: `_fragment_submit_containers()`, `_fragment_submit_files()`, `_fragment_submit_options()`
  - Update: `render_fragment()` dispatch dict (add 3 entries)
- **Secondary file**: `web_dashboard/__init__.py`
  - Add: `po_*` field restructuring in `_handle_action()` for submit/validate actions (~10 lines)
- **Do NOT modify**: `base_panel.py`, `shell.py`, `registry.py`, any other panel

### Anti-Patterns

- No `<script>` tags. No inline `onclick`. No `addEventListener`. HTMX only.
- No conditional show/hide via CSS class toggling from JavaScript. Use separate HTMX fragment loads to show different form sections.
- No client-side form building. All HTML rendered server-side in Python.
- No `localStorage`, `sessionStorage`, or cookies.
- No backward compatibility shims. If the old stub breaks, that's fine.

### Form Field Names (MUST match API exactly)

```
dataset_id          → PlatformRequest.dataset_id (required)
resource_id         → PlatformRequest.resource_id (required)
version_id          → PlatformRequest.version_id (optional)
previous_version_id → PlatformRequest.previous_version_id (optional)
container_name      → PlatformRequest.container_name (required)
file_name           → PlatformRequest.file_name (required for raster/vector)
source_url          → PlatformRequest.source_url (required for zarr via abfs://)
title               → PlatformRequest.title (optional)
access_level        → PlatformRequest.access_level (optional, default OUO)
description         → PlatformRequest.description (optional)
```

Processing options must be nested under `processing_options` key. Since the action proxy flattens form data, processing option fields should use a prefix convention. Fields named `po_table_name`, `po_lat_column`, etc. get restructured into `processing_options: {table_name: ..., lat_column: ...}` by a small helper in the action proxy before calling the API. **The form MUST show type-specific fields as proper labeled inputs** — not a JSON textarea. Operators should not need to know JSON syntax.

**Raster processing fields** (shown when file extension is .tif/.tiff/.geotiff/.nc/.hdf/.hdf5):
- `po_crs` — Input CRS (text, placeholder: "e.g., EPSG:32618")
- `po_nodata_value` — NoData value (text, placeholder: "e.g., -9999")
- `po_band_names` — Band names (text, placeholder: "e.g., red,green,blue")

**Vector processing fields** (shown when file extension is .geojson/.json/.gpkg/.csv/.shp/.kml/.kmz):
- `po_table_name` — Target table name (text, placeholder: "Auto-generated if blank")
- `po_layer_name` — GeoPackage layer (text, placeholder: "For .gpkg with multiple layers")
- `po_lat_column` — Latitude column (text, placeholder: "e.g., lat, latitude, y")
- `po_lon_column` — Longitude column (text, placeholder: "e.g., lon, longitude, x")
- `po_wkt_column` — WKT geometry column (text, placeholder: "e.g., geometry, geom")

**Type-specific sections**: The file browser fragment detects data type from the selected file extension and returns a `data-type` attribute. The form uses a second HTMX fragment (`_fragment_submit_options`) that renders the appropriate fields based on the detected type. When no file is selected, no processing options are shown.

**Action proxy restructuring**: A small helper in `_handle_action` (or in the submit form's fragment handler) must collect `po_*` fields from the form body, strip the prefix, and nest them under `processing_options` before calling the API. This is ~10 lines of code in `__init__.py`.

### CSS Classes Available (from shell.py design system)

```
.form-control      — text inputs, textareas, selects (full width)
.filter-select     — smaller select elements
.filter-input      — smaller text inputs
.filter-label      — labels above filter elements
.btn .btn-primary  — blue primary button
.btn .btn-secondary — gray secondary button
.btn .btn-sm       — smaller button variant
.detail-panel      — card with border, padding, background
.detail-grid       — grid layout for label/value pairs
.detail-item       — single label/value pair
.detail-label      — gray label text
.detail-value      — value text (or .mono for monospace)
.data-table        — styled table
.stat-strip        — horizontal stat cards
.error-block       — red error display with retry
.empty-state       — centered placeholder
.clickable         — cursor:pointer on table rows
```

---

## Estimated Builder Output

- `_render_submit()`: ~180 lines (form HTML with all fields, file browser area, result div)
- `_fragment_submit_containers()`: ~40 lines (fetch + render options)
- `_fragment_submit_files()`: ~80 lines (fetch + render table with click-to-select)
- `_fragment_submit_options()`: ~60 lines (type-specific processing fields)
- Fragment dispatch additions: ~3 lines
- Action proxy `po_*` restructuring in `__init__.py`: ~10 lines
- **Total**: ~370 lines — well within the 2,000-3,000 line safe zone

---

## Success Criteria

1. Operator can select a container from dropdown (HTMX-populated)
2. Operator can browse and select a file from blob list (click-to-select)
3. Form shows all DDH identifier fields with correct `name` attributes
4. Validate button returns inline result with valid/invalid status and warnings
5. Submit button creates job and shows result card with request_id, job_id, and "View Request" link
6. All dynamic content HTML-escaped
7. No JavaScript — HTMX only
8. Works on both localhost:7071 (dev) and Azure deployment
