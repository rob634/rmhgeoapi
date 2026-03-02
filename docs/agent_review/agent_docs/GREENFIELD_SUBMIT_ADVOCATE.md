# Agent A — Advocate Design: Dashboard Submit Panel

**Pipeline**: GREENFIELD (narrow scope — submit form)
**Date**: 02 MAR 2026
**Input**: Tier 1 spec only (no Design Constraints)

---

## COMPONENT DESIGN

### Component 1: `_render_submit` (Form Shell Renderer)

- **Single Responsibility**: Render the static HTML skeleton of the submission form, including the file browser region, DDH identifier fields, processing options placeholder, action buttons, and result display area.
- **Depends on**: BasePanel utilities (`select_filter`, `status_badge`), `html` module for escaping.
- **Depended on by**: Fragment dispatch in `render_fragment()`, HTMX fragment targets within the rendered HTML.

### Component 2: `_fragment_submit_containers` (Container Loader)

- **Single Responsibility**: Fetch the list of bronze-zone containers from the storage API and render them as `<option>` elements for the container `<select>` dropdown.
- **Depends on**: `self.call_api()` for the HTTP call to `/api/storage/containers`, `self.error_block()` for failure rendering.
- **Depended on by**: The container `<select>` in the form shell (loaded via HTMX `hx-get` on page render or trigger).

### Component 3: `_fragment_submit_files` (Blob List Renderer)

- **Single Responsibility**: Fetch blobs from a specified container (with optional prefix/suffix filters) and render a clickable table of files with name, size, and modified columns.
- **Depends on**: `self.call_api()` for the HTTP call to `/api/storage/{container}/blobs`, `self.data_table()` for table rendering, `self.format_date()` for timestamps, `self.empty_block()` for empty state.
- **Depended on by**: The file browser region in the form shell (loaded via HTMX when a container is selected or prefix filter changes).

### Component 4: `_fragment_submit_options` (Type-Specific Options Renderer)

- **Single Responsibility**: Given a data type string, render the appropriate processing option fields (raster-specific or vector-specific) with the `po_` prefix on field names.
- **Depends on**: Nothing external; pure HTML generation with `html` module escaping.
- **Depended on by**: The processing options placeholder `<div>` in the form shell (loaded via HTMX when file selection changes and data type is detected).

### Component 5: Action Proxy Restructuring (in `__init__.py`)

- **Single Responsibility**: Before forwarding `submit` or `validate` actions to the API, extract all `po_`-prefixed fields from the flat form body, strip the prefix, nest them under a `processing_options` key, and remove the originals.
- **Depends on**: The existing action proxy dispatch logic.
- **Depended on by**: The submit and validate API endpoints, which expect `processing_options` as a nested object.

### Component 6: Fragment Dispatch Registration

- **Single Responsibility**: Map fragment identifiers (`submit-containers`, `submit-files`, `submit-options`) to their handler methods in the `render_fragment()` dispatch dictionary.
- **Depends on**: Components 2, 3, and 4.
- **Depended on by**: The HTMX `hx-get` attributes in the form shell HTML.

---

## INTERFACE CONTRACTS

### `_render_submit(self, request: func.HttpRequest) -> str`

```python
def _render_submit(self, request: func.HttpRequest) -> str:
    """Render the complete submit form shell.

    Returns:
        HTML string containing:
        - Container select dropdown with hx-get trigger to load containers
        - Prefix filter text input
        - File browser div (target for file list fragment)
        - Hidden input: file_name (populated by file selection)
        - Hidden input: data_type (populated by file selection)
        - Selected file display div with "Back to file browser" button
        - DDH identifier text inputs: dataset_id, resource_id, version_id, previous_version_id
        - Access level select: access_level (OUO, Public, Uncleared)
        - Processing options div (target for type-specific options fragment)
        - Validate button (hx-post to action proxy with action=validate)
        - Submit button (hx-post to action proxy with action=submit)
        - Result display div (target for action proxy response)
    """
```

### `_fragment_submit_containers(self, request: func.HttpRequest) -> str`

```python
def _fragment_submit_containers(self, request: func.HttpRequest) -> str:
    """Fetch bronze containers and render as <option> elements.

    API call:
        self.call_api(request, "/api/storage/containers", {"zone": "bronze"})
    Data extraction:
        data["zones"]["bronze"]["containers"] -> List[str]
    On failure: returns error_block HTML.
    """
```

### `_fragment_submit_files(self, request: func.HttpRequest) -> str`

```python
def _fragment_submit_files(self, request: func.HttpRequest) -> str:
    """Fetch blobs from a container and render as a clickable table.

    Params: container (required), prefix (optional), suffix (optional)

    API call:
        self.call_api(request, f"/api/storage/{container}/blobs",
                      {"zone": "bronze", "prefix": prefix, "suffix": suffix, "limit": "500"})
    Data extraction:
        data["blobs"] -> List[{"name": str, "size_mb": float, "modified": str}]

    Also handles selection mode when 'select' param is present.
    """
```

### `_fragment_submit_options(self, request: func.HttpRequest) -> str`

```python
def _fragment_submit_options(self, request: func.HttpRequest) -> str:
    """Render type-specific processing option fields.

    Params: data_type (raster, vector, or empty)

    For "raster": po_crs, po_resolution, po_resampling_method
    For "vector": po_table_name, po_srid, po_geometry_type
    For empty/unknown/zarr: empty string ""
    """
```

---

## DATA FLOW

### Flow 1: Page Load -> Container List

```
1. User navigates to Platform > Submit tab
2. _render_submit() returns form shell HTML
3. Container <select> has hx-get="/api/dashboard?tab=platform&fragment=submit-containers"
   with hx-trigger="load"
4. HTMX fires GET request on load
5. _fragment_submit_containers() calls self.call_api()
6. Returns <option> elements
7. HTMX swaps options into the <select>
```

### Flow 2: Container Selection -> File List

```
1. User selects a container from dropdown
2. <select> has hx-trigger="change", hx-target="#file-browser",
   hx-include="[name='container'],[name='prefix'],[name='suffix']"
3. _fragment_submit_files() fetches blobs, renders table via self.data_table()
4. Each row has hx-get for file selection
5. HTMX swaps table into #file-browser
```

### Flow 3: File Selection -> Form Population

```
1. User clicks a file row
2. Row's hx-get fires with select=path/file.tif
3. _fragment_submit_files() detects select param, enters selection mode
4. Determines data_type from extension:
   .tif/.tiff/.img -> "raster"
   .shp/.geojson/.gpkg/.gdb/.parquet -> "vector"
   .nc/.nc4/.hdf/.h5/.zarr -> "zarr"
5. Returns HTML with:
   a. Hidden input file_name
   b. Hidden input data_type
   c. Display div with file name + badge
   d. "Back to file browser" button
   e. #submit-options div with hx-trigger="load"
6. HTMX swaps into #file-selection-area
7. Nested hx-trigger="load" fires, loading type-specific options
```

### Flow 4: Processing Options Load

```
1. Triggered by hx-trigger="load" on #submit-options div
2. _fragment_submit_options() checks data_type param
3. Returns type-specific form fields
4. HTMX swaps into #submit-options
```

### Flow 5: Validate (Dry Run)

```
1. User clicks Validate button
2. HTMX collects all inputs within #submit-form
3. Action proxy parses form body, runs po_* restructuring
4. POSTs JSON to /api/platform/validate
5. Returns result card into #submit-result
```

### Flow 6: Submit

```
1. User clicks Submit button
2. Same flow as Validate but action=submit, endpoint=/api/platform/submit
3. Success card includes "View Request" link
```

---

## GOLDEN PATH

**Scenario**: Operator submits a GeoTIFF raster file for processing.

1. Operator navigates to Platform > Submit tab. Form shell renders. Container select loads via hx-trigger="load".
2. Container list loads from storage API (source-rasters, source-vectors, source-netcdf).
3. Operator selects "source-rasters". File list loads via hx-trigger="change".
4. 15 blobs render in table. Operator types "elevation" in prefix filter. List narrows to 3 files.
5. Operator clicks "elevation/dem_30m.tif". Selection fragment replaces file browser with hidden inputs + badge + "Back" button. Processing options load automatically.
6. Raster options appear: Target CRS, Resolution, Resampling Method.
7. Operator fills form: dataset_id="elevation-data", resource_id="dem-30m", version_id="1.0", access_level="OUO", po_crs="EPSG:4326", po_resampling_method="bilinear".
8. Operator clicks "Validate". Action proxy restructures po_* fields, POSTs to /api/platform/validate. Result card shows "valid: true, would_create_job_type: process_raster_docker".
9. Operator clicks "Submit". Same flow, success card shows request_id, job_id, "View Request" link.
10. Operator clicks "View Request" — navigates to Platform/Requests tab.

---

## STATE MANAGEMENT

| State | Location | Writer | Reader |
|-------|----------|--------|--------|
| Selected container | `<select name="container">` | User | HTMX hx-include |
| Prefix filter | `<input name="prefix">` | User | HTMX hx-include |
| Selected file | `<input type="hidden" name="file_name">` | Server (fragment) | HTMX hx-include |
| Detected data type | `<input type="hidden" name="data_type">` | Server (fragment) | Options fragment trigger |
| DDH fields | `<input name="dataset_id">` etc. | User | HTMX hx-include |
| Access level | `<select name="access_level">` | User | HTMX hx-include |
| Processing options | `<input name="po_*">` | User | HTMX hx-include |
| Result | `#submit-result` div | Action proxy | User (visual) |

All state is DOM-only. No server-side session. Page refresh resets all state.

---

## EXTENSION POINTS

1. **New data types**: Add to EXTENSION_TO_TYPE dict + new branch in _fragment_submit_options()
2. **New processing option fields**: Add new `<input name="po_X">` to options fragment. Auto-captured by po_* restructuring.
3. **New action buttons**: Add button with hx-post, register action in proxy.
4. **Multi-file selection** (future): Change hidden input to multiple inputs or checkboxes.
5. **Additional filter controls**: Add to file browser, include in hx-include selector.

---

## DESIGN RATIONALE

1. **File selection via server-rendered fragment swap** (not JavaScript): Spec mandates no JS. Server fragment swap keeps state in DOM via hidden inputs.

2. **Single #file-selection-area that alternates between browser and selection**: HTMX's hx-swap="innerHTML" naturally replaces content. No show/hide toggling needed.

3. **Overloading _fragment_submit_files for listing and selection**: Single method with mode branch (select param present or not) is simpler than separate fragment endpoint.

4. **Processing options via nested hx-trigger="load"**: Separates file selection from options rendering. Changing option fields doesn't touch file selection logic. Cost: one extra HTTP request.

5. **po_ prefix convention**: HTMX collects flat key-value pairs. po_ prefix identifies fields for nesting. 4 lines of code in proxy.

6. **Containers loaded on page load via hx-trigger="load"**: Keeps _render_submit() fast (pure HTML template, no API calls).

7. **Prefix filter with debounced HTMX trigger**: hx-trigger="keyup changed delay:500ms" auto-refreshes file list. Standard HTMX pattern.

8. **Data type detection by file extension on server**: Simple dict lookup. Informational only — API does authoritative detection at submission.

9. **Single form with hx-include="#submit-form"**: All inputs in one form element. Dynamically loaded inputs automatically included in submissions.

10. **"View Request" as HTMX navigation**: Stays in SPA framework. Consistent with dashboard architecture.
