# Agent M — Mediator Resolution: Dashboard Submit Panel

**Pipeline**: GREENFIELD (narrow scope — submit form)
**Date**: 02 MAR 2026
**Input**: Tier 1 + Tier 2 + A + C + O outputs

---

## CONFLICTS FOUND

### C1: A overloads _fragment_submit_files for listing + selection vs. C's UX concerns (E-8, G-3)

**A proposed**: _fragment_submit_files serves double duty via `select` parameter.
**C raised**: No spec for selection UX, container change leaves stale state (E-8).
**Resolution**: Accept A's fragment overloading — only HTMX-pure way. Container change naturally clears selection (fragment is fully replaced). Deselect via "Back to file browser" button. Mode A must OOB-reset hidden inputs to prevent stale state.

### C2: C's contradiction C-1 (__init__.py modification) vs. Design Constraints

**C flags**: Spec says "do not modify other panels" but requires __init__.py changes.
**Resolution**: Constraint says "any other **panel**". __init__.py is the entry point, not a panel. Spec explicitly lists it as secondary file. Not a contradiction.

### C3: A's data type detection vs. C's ambiguity A-1

**A proposed**: Server-side EXTENSION_TO_TYPE dict in _fragment_submit_files.
**C asks**: Client-side or server-side?
**Resolution**: Server-side, inside _fragment_submit_files when `select` is present. Aligns with Invariant 2 and No JavaScript constraint.

### C4: O's cold start reality vs. NFR performance targets

**O notes**: 5-15s cold starts violate <1s/<3s NFRs.
**Resolution**: NFR targets are "warm instance" targets. Mitigate with hx-indicator loading spinners.

### C5: O's FM-3 (po_* restructuring risk) — A doesn't address

**O flags**: Modifying shared _handle_action risks breaking other actions.
**Resolution**: Triple-qualified guard: `action in ('submit', 'validate') and tab == 'platform'` plus po_* key presence. Existing actions unaffected.

### C6: C's E-7/E-9 (XSS and URL-unsafe chars) — A doesn't address

**Resolution**: Double-escape for hx-get URL values: urllib.parse.quote() then html_module.escape(). Container and blob names both need this treatment.

---

## DESIGN TENSIONS

### T1: A's hx-trigger="load" for containers — No tension (valid HTMX).
### T2: A's hx-trigger="keyup changed delay:500ms" — No tension (valid HTMX).
### T3: C's client-side validation vs. No JavaScript constraint — Constraint enforced. UX slightly less responsive (server round-trips for all interactions).
### T4: O's correlation IDs vs. Scope — Constraint enforced (would require base_panel.py changes). Deferred.
### T5: C's pagination vs. Spec boundary (limit=500) — Spec enforced for v1. Prefix/suffix filters as workaround.

---

## RESOLVED SPEC

### 0. Constants and Imports

```python
import urllib.parse
import os

EXTENSION_TO_TYPE = {
    '.tif': 'raster', '.tiff': 'raster', '.geotiff': 'raster',
    '.nc': 'raster', '.hdf': 'raster', '.hdf5': 'raster', '.h5': 'raster',
    '.geojson': 'vector', '.json': 'vector', '.gpkg': 'vector',
    '.csv': 'vector', '.shp': 'vector', '.kml': 'vector', '.kmz': 'vector',
    '.zarr': 'zarr',
}
```

### 1. _render_submit(request) -> str

Returns complete form HTML with:
- File browser (container select + prefix/suffix filters + #file-selection-area)
- DDH identifiers (dataset_id, resource_id, version_id, previous_version_id)
- Metadata (title, access_level, description)
- Processing options placeholder (#submit-options)
- Hidden inputs (file_name, detected_data_type)
- Action buttons (Validate, Submit)
- Result display (#submit-result)
- Loading indicators (hx-indicator)

Container select auto-loads via hidden div with hx-trigger="load".
All interactivity via HTMX attributes. No JavaScript.

### 2. _fragment_submit_containers(request) -> str

API: GET /api/storage/containers?zone=bronze
Returns: <option> elements for container dropdown
Error: Single disabled option "Failed to load containers"
Empty: Single disabled option "No bronze containers found"

### 3. _fragment_submit_files(request) -> str

**Mode A (listing)**: When no `select` param.
API: GET /api/storage/{container}/blobs?zone=bronze&prefix=X&suffix=Y&limit=500
Returns: Table with clickable rows (Name, Size MB, Modified)
Each row: hx-get with select={blob_name}&container_name={container}
Count indicator with "limit: 500" warning if at limit.
**Must OOB-reset hidden inputs to empty** when rendering blob list.

**Mode B (selection)**: When `select` param present.
Returns: Selection display with file name, data type badge, "Back to browser" button.
Updates hidden inputs via hx-swap-oob="true".
Auto-loads processing options via nested hx-trigger="load" div.

**Data type detection**: os.path.splitext(filename) -> EXTENSION_TO_TYPE lookup.

**Double-escape for URLs**: urllib.parse.quote() then html_module.escape() for all dynamic values in hx-get attributes.

### 4. _fragment_submit_options(request) -> str

data_type=raster: po_crs, po_nodata_value, po_band_names
data_type=vector: po_table_name, po_layer_name, po_lat_column, po_lon_column, po_wkt_column
data_type=zarr: source_url text input (minimal fallback)
data_type=empty/unknown: "Select a file to see processing options"

### 5. Fragment Dispatch (3 entries)

submit-containers, submit-files, submit-options

### 6. po_* Restructuring in __init__.py

Guard: action in ('submit', 'validate')
Collect po_* keys, strip prefix, nest under processing_options.
Remove informational fields: detected_data_type, prefix_filter, suffix_filter.

### 7. Result Rendering

Submit success: Green card with request_id, job_id, job_type, "View Request" link.
Validate success: Blue card with would_create_job_type, lineage_state, suggested_params.
Both: Warnings rendering (amber ⚠ items).
Error: Red error block.

---

## DEFERRED DECISIONS

1. Blob list pagination (v1: limit=500 + prefix filter)
2. Zarr file browser (v1: text input fallback)
3. Multi-file selection (out of scope)
4. Correlation IDs (requires base_panel.py changes)
5. Auto-populate previous_version_id from suggested_params (requires JS or complex OOB)
6. Validate-before-submit enforcement (v1: operator discipline)
7. Access level enum verification (Builder should check PlatformRequest)
8. File size display units (v1: show size_mb as-is from API)

---

## RISK REGISTER

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | hx-swap-oob browser compatibility | Low | High | Test with exact HTMX version; fallback to visible readonly fields |
| R2 | po_* restructuring breaks existing actions | Low | High | Triple-qualified guard; test with approve/revoke actions |
| R3 | Blob names with special characters | Medium | Medium | Double-escape: urllib.parse.quote() then html_module.escape() |
| R4 | Large container timeout | Medium | Low | limit=500 cap + prefix filter + loading indicator |
| R5 | CDN outage breaks entire dashboard | Low | High | Inherited risk; future: vendor HTMX locally |
| R6 | Stale container_name after selection | Medium | Medium | Mode A OOB-resets hidden inputs to empty |
