# Agent V — Blind Validation Report: Dashboard Submit Panel

**Pipeline**: GREENFIELD (narrow scope — submit form)
**Date**: 02 MAR 2026
**Input**: Code ONLY — no spec, no design docs, no other agent outputs

**Files Analyzed:**
- `web_dashboard/panels/platform.py` (submit section, lines 510-889)
- `web_dashboard/__init__.py` (action proxy, lines 305-414)
- `web_dashboard/base_panel.py` (supporting methods, referenced for contract validation)

---

## INFERRED PURPOSE

This code implements a server-rendered, HTMX-driven data submission form within a dashboard panel. It provides a multi-step workflow for submitting geospatial data (raster, vector, or zarr) to a platform API: the user browses Azure Blob Storage containers, selects a file, sees auto-detected data type and type-specific processing options, fills in identifiers and metadata, and submits. The `__init__.py` action proxy translates the flat form-encoded HTMX POST into a structured JSON API call, restructuring `po_*`-prefixed form fields into a nested `processing_options` dict and stripping dashboard-only fields before forwarding to the backend `/api/platform/submit` or `/api/platform/validate` endpoint.

---

## INFERRED CONTRACTS

### `PlatformPanel._render_submit(self, request: func.HttpRequest) -> str`
- **Input:** HTTP request (unused beyond method signature conformance).
- **Output:** An HTML string containing a complete `<form id="submit-form">` with hidden inputs for file_name and detected_data_type, a container selector that loads via HTMX on page load, prefix/suffix filters, identifier fields (dataset_id, resource_id, version_id, previous_version_id), metadata fields (title, access_level, description), a placeholder div for processing options, and two action buttons (Validate and Submit).
- **Side effects:** None. Pure HTML generation. The HTMX attributes set up future client-side interactions.

### `PlatformPanel._fragment_submit_containers(self, request: func.HttpRequest) -> str`
- **Input:** HTTP request (used to forward to `/api/storage/containers?zone=bronze` via `call_api`).
- **Output:** HTML `<option>` elements for a `<select>` dropdown. On success: one "Select container..." prompt plus one option per bronze container. On failure: a single disabled error option.
- **Side effects:** Makes an internal HTTP call to the storage API.

### `PlatformPanel._fragment_submit_files(self, request: func.HttpRequest) -> str`
- **Input:** HTTP request with query params `select` (file name), `container_name`, `prefix_filter`, `suffix_filter`.
- **Output:** Operates in two modes:
  - **Mode A (no `select`):** Lists blobs in the selected container as a clickable table. Each row has `hx-get` to re-invoke this fragment in Mode B. Also emits OOB swaps to clear hidden inputs.
  - **Mode B (`select` present):** Shows a "Selected: filename" confirmation card, emits OOB swaps to set `hidden-file-name` and `hidden-detected-type`, and triggers a load of `_fragment_submit_options` into `#submit-options`.
- **Side effects:** Makes an internal HTTP call to `/api/storage/{container}/blobs`.

### `PlatformPanel._fragment_submit_options(self, request: func.HttpRequest) -> str`
- **Input:** HTTP request with query param `data_type`.
- **Output:** Type-specific form fields:
  - `raster`: CRS, NoData Value, Band Names (all prefixed `po_`).
  - `vector`: Table Name, Layer Name, Lat Column, Lon Column, WKT Column (all prefixed `po_`).
  - `zarr`: Source URL (named `source_url`, NOT prefixed `po_`).
  - Unrecognized/empty: placeholder message.
- **Side effects:** None.

### `PlatformPanel.EXTENSION_TO_TYPE` (class constant)
- **Type:** `dict[str, str]`
- **Maps:** File extensions to data type strings: `.tif/.tiff/.geotiff/.nc/.hdf/.hdf5/.h5` to `"raster"`, `.geojson/.json/.gpkg/.csv/.shp/.kml/.kmz` to `"vector"`, `.zarr` to `"zarr"`.

### `PlatformPanel.render_fragment(self, request, fragment_name) -> str` (dispatch entries)
- **Submit-related entries:** `"submit-containers"`, `"submit-files"`, `"submit-options"` map to `_fragment_submit_containers`, `_fragment_submit_files`, `_fragment_submit_options` respectively.
- **Contract:** Raises `ValueError` for unknown fragment names.

### `_handle_action(req, action) -> func.HttpResponse` (in `__init__.py`)
- **Input:** Azure Functions HttpRequest with form-encoded body, plus `action` string from query params.
- **Output:** HTML fragment showing success (green result card with up to 6 key-value pairs) or failure (red result card with truncated error).
- **Side effects:** Makes an internal HTTP call to the backend API endpoint. For `submit`/`validate`, restructures `po_*` form fields into nested `processing_options` dict, strips `detected_data_type`, `prefix_filter`, `suffix_filter`. For `ensure`/`rebuild`, converts body to query params.

### `_ACTION_ENDPOINTS` (module constant in `__init__.py`)
- **Type:** `dict[str, tuple[str, str]]` mapping action name to (API path, HTTP method).
- **Entries:** `approve`, `reject`, `revoke`, `submit`, `validate` -> `/api/platform/*`; `ensure`, `rebuild` -> `/api/dbadmin/maintenance`.

---

## INFERRED INVARIANTS

**I-1: All user-sourced values are HTML-escaped before embedding in HTML output.** Every dynamic value rendered into the HTML response passes through `html_module.escape()`. Container names, file names, data types, request IDs, error messages — all are escaped. This is applied consistently across both files.

**I-2: Fragment architecture uses OOB (Out-Of-Band) swaps to maintain form state.** When the user selects a file, the `_fragment_submit_files` method returns OOB `hx-swap-oob="true"` elements that update the hidden inputs (`hidden-file-name`, `hidden-detected-type`) and the `#submit-options` div, keeping the form's hidden state synchronized without a full page reload.

**I-3: Processing option fields use the `po_` prefix convention.** All type-specific processing option form fields are named `po_{option_name}` (e.g., `po_crs`, `po_nodata_value`, `po_table_name`). The `_handle_action` code strips this prefix when restructuring into the `processing_options` dict.

**I-4: Dashboard-only fields are stripped before API forwarding.** Fields `detected_data_type`, `prefix_filter`, and `suffix_filter` are explicitly removed from the body before the API call, preventing dashboard UI state from leaking to the backend.

**I-5: The action dispatch table is a closed whitelist.** Only 7 named actions are permitted. Unknown actions receive an error block. Actions are not dynamically derived from user input beyond lookup in the `_ACTION_ENDPOINTS` dict.

**I-6: All HTTP responses return status 200 with HTML content type.** Even errors are returned as 200 with HTML error blocks, consistent with HTMX's expectation that non-2xx responses are handled differently.

**I-7: URL parameters in HTMX attributes are URL-encoded.** The code uses `urllib.parse.quote()` for values embedded in URLs within `hx-get` attributes (e.g., container names, file names in select URLs, data types in options URLs).

**I-8: Container listing is scoped to the `bronze` zone.** Both `_fragment_submit_containers` and `_fragment_submit_files` hardcode `zone=bronze`, restricting file browsing to the bronze (raw data) tier only.

**I-9: File listing is capped at 500 blobs.** The `_fragment_submit_files` method passes `limit=500` to the blob listing API.

**I-10: The `call_api` / `call_api_static` pattern uses a self-referencing loopback HTTP call.** The dashboard proxies to its own host's API endpoints, deriving the base URL from the incoming request's `Host` header.

---

## CONCERNS

**C-1: Zarr `source_url` field is NOT prefixed with `po_` — inconsistent with restructuring logic.** (MEDIUM)

The zarr processing options form names the field `source_url` rather than `po_source_url`. Since the `_handle_action` restructuring logic only collects fields starting with `po_`, this value will be sent as a top-level body field (`source_url`) rather than nested under `processing_options.source_url`. This may be intentional (if the API expects `source_url` at the top level), but it breaks the otherwise uniform `po_*` -> `processing_options` convention. If the API expects it inside `processing_options`, submissions will silently omit it.

**Suggested fix:** Verify the backend API contract. If `source_url` should be in `processing_options`, rename the field to `po_source_url`. If it belongs at the top level, add a code comment explaining the exception.

**C-2: `parse_qs` does not have `keep_blank_values=True`, so empty form fields are silently dropped.** (LOW)

At `__init__.py` line 342, `parse_qs(raw_body)` drops any field whose value is an empty string. For example, if the user leaves `version_id` blank, that key will not appear in `body` at all. This is generally fine (the API should handle missing fields), but it means the form cannot intentionally send an empty string to clear a field.

**Suggested fix:** If the API needs to distinguish between "field not sent" and "field sent as empty," use `parse_qs(raw_body, keep_blank_values=True)`. Otherwise, document this as intentional behavior.

**C-3: `.json` extension maps to `vector` in `EXTENSION_TO_TYPE`, which is overly broad.** (LOW)

The `.json` extension is mapped to `vector` data type. However, `.json` files could be arbitrary JSON (config files, STAC manifests, etc.), not GeoJSON. A user browsing a container with generic `.json` files would get incorrect auto-detection. Mitigated by the fact that it only controls default processing options shown.

**Suggested fix:** Consider removing `.json` from the mapping or mapping it to a more cautious default.

**C-4: No CSRF protection on POST actions.** (MEDIUM)

The action proxy accepts any POST with `?action=submit` and processes it. There is no CSRF token verification. Since the form uses HTMX, the `HX-Request` header provides some implicit protection (custom headers cannot be set by simple cross-origin requests), but the `_handle_action` code does not check for the `HX-Request` header. The `__init__.py` module-level docstring notes "No authentication enforced."

**Suggested fix:** At minimum, verify `HX-Request: true` header in `_handle_action`. For production readiness, add CSRF tokens.

**C-5: Error block in `_fragment_submit_files` retry URL uses `html_module.escape` instead of `urllib.parse.quote` for container name in URL.** (VERY LOW)

The retry URL uses `html_module.escape(str(container))` inside a URL path. HTML escaping is appropriate for the HTML attribute context but not for URL encoding. In practice, Azure container names are restricted to lowercase alphanumeric and hyphens, so this is unlikely to trigger.

**Suggested fix:** Use `urllib.parse.quote(str(container))` for the URL component, then `html_module.escape()` for the HTML attribute.

**C-6: Success response renders dict values with `str(val)[:100]` truncation.** (VERY LOW)

At `__init__.py` line 384, `str(val)[:100]` slicing is applied before `html_module.escape()`. For Python 3 strings, this operates on Unicode code points, so this is safe. Non-issue in practice.

**Suggested fix:** None needed.

**C-7: No client-side form validation; reliance on server-side API validation only.** (LOW)

The submit form has no `required` attributes on critical fields like `dataset_id`, `resource_id`, `file_name`, or `container_name`. A user can click "Submit Request" with an empty form.

**Suggested fix:** Add `required` attribute to `dataset_id` and `resource_id` inputs.

**C-8: The `_handle_action` body dict preserves list values for multi-valued form fields.** (VERY LOW)

At line 344, `parse_qs` returns lists for each key. The comprehension converts single-element lists to scalars but keeps multi-element lists as-is. Standard and correct behavior.

**Suggested fix:** None needed.

**C-9: `call_api_static` derives scheme from Host header, which could be spoofed.** (LOW)

The scheme (http vs https) is derived from the request's `Host` header, with fallback to `X-Forwarded-Proto`. In Azure Functions behind a load balancer, this is standard. Blast radius is limited since this is an internal loopback call.

**Suggested fix:** Consider hardcoding the loopback URL or validating the Host header against a known allowlist.

**C-10: The `hx-confirm` dialogs embed escaped identifiers that appear as literal HTML entities.** (VERY LOW)

Since `hx-confirm` values are treated as plain text by HTMX (displayed via browser's native `confirm()` dialog), HTML entities like `&amp;` would appear literally. Given that release IDs are UUIDs (alphanumeric + hyphens), this is a non-issue in practice.

**Suggested fix:** None needed for current data patterns.

---

## QUALITY ASSESSMENT

**GOOD**

The code demonstrates a well-structured, methodical approach to building a server-rendered HTMX form with proper separation between UI generation (platform.py) and action proxying (__init__.py). HTML escaping is applied comprehensively and consistently across both files. The `po_*` restructuring pattern is a clean solution for translating flat HTML form fields into a nested API payload. The OOB swap pattern for maintaining hidden form state during fragment updates is correctly implemented. The primary concern is the `source_url` naming inconsistency for zarr (C-1), which may indicate either a deliberate design choice or a gap in the `po_*` convention. No critical security issues were found; the medium-severity items (C-1, C-4) are worth addressing but do not represent exploitable vulnerabilities in the current deployment context (internal dev tool with no authentication).
