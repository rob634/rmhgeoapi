# Platform Status Lookup — Design

**Date**: 25 FEB 2026
**File**: `web_interfaces/platform/interface.py`
**Scope**: Single-file enhancement to existing platform interface

## Goal

Add an interactive status lookup section to `/api/interface/platform` that calls
`GET /api/platform/status/{id}` (or `?dataset_id&resource_id`) and renders the
structured response as styled HTML cards. Also update the stale endpoint reference table.

## 1. Status Lookup Input

Dropdown selector + text input field(s) with HTMX-powered search.

**Dropdown options** (priority order):
1. Request ID
2. Job ID
3. Dataset + Resource (shows two input fields)
4. Asset ID
5. Release ID

When "Dataset + Resource" is selected, JS swaps the single input for two fields.
All other options use a single text input.

**HTMX flow**:
- `hx-post="/api/interface/platform?fragment=status-lookup"`
- Sends: `lookup_type` + `lookup_id` (or `dataset_id` + `resource_id`)
- Target: `#status-result` div

## 2. Backend Fragment Handler

New `htmx_partial()` method on `PlatformInterface` with fragment `status-lookup`.

For single-ID lookups (request, job, asset, release):
- Calls `GET /api/platform/status/{id}?detail=full` via internal HTTP

For dataset+resource lookup:
- Calls `GET /api/platform/status?dataset_id=X&resource_id=Y` via internal HTTP

Renders JSON response into HTML cards.

## 3. Result Display Cards

All cards hidden when their data block is null.

| Card | Source fields | Notes |
|------|-------------|-------|
| **Asset** | asset_id, dataset_id, resource_id, data_type, release_count | |
| **Release** | release_id, version_id, ordinal, revision, is_latest, processing_status, approval_state, clearance_state | Status badges |
| **Job** | job_status (+ job_id, job_type from detail block) | Color-coded badge |
| **Error** | code, category, message, remediation, user_fixable, detail | Only when job failed |
| **Outputs** | blob_path, table_name, stac_item_id, stac_collection_id | Monospace values |
| **Services** | preview, tiles, viewer | Clickable links |
| **Approval** | state, created_at | |
| **Versions** | Table rows per release: version_id, ordinal, approval, clearance, processing, is_latest | Compact table |

## 4. Endpoint Reference Table Update

Remove deprecated:
- `/api/platform/raster`
- `/api/platform/raster-collection`

Add all current endpoints grouped by category:
- Submit/Status, Validation, Approvals, Catalog, Operations, Diagnostics, Registry

## 5. What stays unchanged

- Platform Status banner (health, jobs 24h, success rate, pending review)
- DDH Naming Patterns section
- Valid Input Containers section
- Access Levels section
- Request ID Generation section
- DDH Application Health placeholder
