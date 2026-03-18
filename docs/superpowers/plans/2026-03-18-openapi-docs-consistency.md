# OpenAPI & Docs Consistency Update — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the OpenAPI spec, Swagger/ReDoc, docs landing page, and platform interface page into full consistency with the actual v0.10.x platform/* endpoint implementations.

**Architecture:** The OpenAPI spec (`openapi/platform-api-v1.json`) is the single source of truth consumed by both Swagger UI and ReDoc. Two HTML pages (`web_interfaces/docs/interface.py` and `web_interfaces/platform/interface.py`) also reference endpoints and must stay consistent. All changes are to static documentation — no runtime code changes.

**Tech Stack:** OpenAPI 3.0.1 JSON, Python (HTML template strings in interface.py files)

---

## Chunk 1: OpenAPI Spec — Header, Ghost Endpoints, and Schema Overhauls

### Task 1: Update spec info block and remove ghost endpoint

**Files:**
- Modify: `openapi/platform-api-v1.json` (lines 1-10, `/api/platform/validate` path)

- [ ] **Step 1: Update info.version and description changelog**

Change `"version": "0.9.16"` → `"version": "0.10.3.3"`.
Update the description's "What's New" section to reference v0.10.x.
Remove references to validate endpoint from description if present.

- [ ] **Step 2: Remove `/api/platform/validate` path**

Delete the entire `/api/platform/validate` path object. This endpoint was planned (F7.12) but never implemented. Its functionality is covered by `POST /api/platform/submit?dry_run=true`.

- [ ] **Step 3: Validate JSON is still parseable**

Run: `python -c "import json; json.load(open('openapi/platform-api-v1.json'))"`
Expected: No error

- [ ] **Step 4: Commit**

```bash
git add openapi/platform-api-v1.json
git commit -m "docs(openapi): bump version to 0.10.3.3, remove ghost /validate endpoint"
```

---

### Task 2: Rewrite `UnpublishRequest` schema

**Files:**
- Modify: `openapi/platform-api-v1.json` — `components.schemas.UnpublishRequest`

The current schema has 5 fields. The actual endpoint accepts 16+ fields across 6 identification options.

- [ ] **Step 1: Replace UnpublishRequest schema**

Replace with schema matching actual `_UNPUBLISH_FIELDS` from `triggers/platform/unpublish.py:28-36`:

```json
{
  "type": "object",
  "description": "Unified unpublish request. Provide ONE identification method plus options.\n\n**Identification Options:**\n- Option 1: DDH identifiers (dataset_id + resource_id + version_id)\n- Option 2: request_id from original submission\n- Option 3: job_id of the processing job\n- Option 4: release_id (V0.9 release identifier)\n- Option 5: Explicit vector (data_type=vector + table_name)\n- Option 6: Explicit raster/zarr (data_type + stac_item_id + collection_id)",
  "properties": {
    "dataset_id": {
      "type": "string",
      "description": "DDH dataset identifier (Option 1)"
    },
    "resource_id": {
      "type": "string",
      "description": "DDH resource identifier (Option 1)"
    },
    "version_id": {
      "type": "string",
      "description": "DDH version identifier (Option 1)"
    },
    "request_id": {
      "type": "string",
      "description": "Platform request ID from original submission (Option 2)"
    },
    "job_id": {
      "type": "string",
      "description": "Processing job ID (Option 3)"
    },
    "release_id": {
      "type": "string",
      "description": "V0.9 release identifier (Option 4)"
    },
    "version_ordinal": {
      "type": "integer",
      "description": "Version ordinal — used with DDH identifiers to target a specific version"
    },
    "data_type": {
      "type": "string",
      "enum": ["vector", "raster", "zarr"],
      "description": "Explicit data type override. Required for Options 5/6"
    },
    "table_name": {
      "type": "string",
      "description": "PostGIS table name for explicit vector unpublish (Option 5)"
    },
    "schema_name": {
      "type": "string",
      "default": "geo",
      "description": "PostGIS schema name (default: geo)"
    },
    "stac_item_id": {
      "type": "string",
      "description": "STAC item ID for explicit raster/zarr unpublish (Option 6)"
    },
    "collection_id": {
      "type": "string",
      "description": "STAC collection ID for explicit raster/zarr unpublish (Option 6)"
    },
    "dry_run": {
      "type": "boolean",
      "default": false,
      "description": "Preview mode — returns what would be deleted without executing. Default: false"
    },
    "force_approved": {
      "type": "boolean",
      "default": false,
      "description": "Required to unpublish data with an approved release. Revokes approval atomically"
    },
    "delete_collection": {
      "type": "boolean",
      "default": false,
      "description": "Raster only — delete all items in the STAC collection"
    },
    "delete_data_files": {
      "type": "boolean",
      "default": true,
      "description": "Zarr only — delete the Zarr store blobs from storage"
    },
    "delete_blobs": {
      "type": "boolean",
      "default": true,
      "description": "Delete associated blob storage files"
    },
    "reviewer": {
      "type": "string",
      "description": "Email of person authorizing the unpublish"
    }
  }
}
```

- [ ] **Step 2: Update unpublish path examples**

Add examples for all 6 identification options (the current spec only has 2).
Add examples: by_job_id, by_release_id, explicit_vector, explicit_raster.

- [ ] **Step 3: Update unpublish path responses**

Add 202 response (job created for live runs). Current spec only has 200 and 404.

- [ ] **Step 4: Validate JSON**

Run: `python -c "import json; json.load(open('openapi/platform-api-v1.json'))"`

- [ ] **Step 5: Commit**

```bash
git add openapi/platform-api-v1.json
git commit -m "docs(openapi): rewrite UnpublishRequest schema — 16 fields, 6 ID options"
```

---

### Task 3: Rewrite `ResubmitRequest` schema

**Files:**
- Modify: `openapi/platform-api-v1.json` — `components.schemas.ResubmitRequest` and `/api/platform/resubmit` path

The current spec describes a "submit corrected file" flow (`original_request_id`, `container_name`, `file_name`). The actual endpoint is a "retry failed job" flow that resolves job_id from multiple identifier types.

- [ ] **Step 1: Replace ResubmitRequest schema**

Match actual implementation from `triggers/platform/resubmit.py:80-86,330-333`:

```json
{
  "type": "object",
  "description": "Retry a failed job. Cleans up partial artifacts and resubmits.\n\n**Identification Options (provide one):**\n- job_id: Direct job reference\n- request_id: Platform request reference\n- DDH identifiers: dataset_id + resource_id + version_id\n\n**Behavior:**\n- Deletes failed job's tasks and partial outputs\n- Creates fresh job with same parameters\n- Updates platform request with new job_id\n- Blocks on approved releases (revoke first)",
  "properties": {
    "job_id": {
      "type": "string",
      "description": "Job ID to retry (Option 1 — direct)"
    },
    "request_id": {
      "type": "string",
      "description": "Platform request ID (Option 2 — resolves to job_id)"
    },
    "dataset_id": {
      "type": "string",
      "description": "DDH dataset identifier (Option 3)"
    },
    "resource_id": {
      "type": "string",
      "description": "DDH resource identifier (Option 3)"
    },
    "version_id": {
      "type": "string",
      "description": "DDH version identifier (Option 3)"
    },
    "dry_run": {
      "type": "boolean",
      "default": false,
      "description": "Preview what would be cleaned up and resubmitted"
    },
    "delete_blobs": {
      "type": "boolean",
      "default": false,
      "description": "Delete partial blob artifacts during cleanup"
    },
    "force": {
      "type": "boolean",
      "default": false,
      "description": "Force resubmit on completed or processing jobs"
    }
  }
}
```

- [ ] **Step 2: Update resubmit path description and examples**

Replace the current description ("Resubmit a rejected request") with "Retry a failed job".
Replace the example with one using `job_id` and one using DDH identifiers.
Add 409 response for approved-release block and completed-job block.

- [ ] **Step 3: Validate JSON**

Run: `python -c "import json; json.load(open('openapi/platform-api-v1.json'))"`

- [ ] **Step 4: Commit**

```bash
git add openapi/platform-api-v1.json
git commit -m "docs(openapi): rewrite ResubmitRequest — retry-failed-job, not submit-corrected-file"
```

---

### Task 4: Update approval schemas (Approve, Reject, Revoke)

**Files:**
- Modify: `openapi/platform-api-v1.json` — 3 schemas + 3 path objects

All three approval schemas are missing: `release_id` (V0.9 primary identifier), `dataset_id`+`resource_id` (DDH resolution), `approval_id` (legacy alias), `dry_run`.

The approve schema uses `clearance_level` but the app accepts `clearance_state`, `clearance_level`, and `access_level` interchangeably.

- [ ] **Step 1: Update PlatformApproveRequest**

Add missing fields to properties:
- `release_id`: string — "Release ID (V0.9 preferred identifier)"
- `dataset_id`: string — "DDH dataset identifier (alternative lookup)"
- `resource_id`: string — "DDH resource identifier (alternative lookup)"
- `approval_id`: string — "Legacy alias for asset_id"
- `version_id`: string — "Version ID for atomic version assignment"
- `dry_run`: boolean, default false — "Preview approval without executing"

Change `clearance_level` description to note it also accepts `clearance_state` or `access_level`.

Change `required` from `["reviewer", "clearance_level"]` to `["reviewer"]` — clearance_level is required in practice but can be provided as any of the three field names.

- [ ] **Step 2: Update PlatformRejectRequest**

Add to properties: `release_id`, `dataset_id`, `resource_id`, `approval_id`, `dry_run`.

- [ ] **Step 3: Update PlatformRevokeRequest**

Add to properties: `release_id`, `dataset_id`, `resource_id`, `approval_id`, `dry_run`.
Note that the app accepts `reviewer` OR `revoker` (line 721: `req_body.get('reviewer') or req_body.get('revoker')`).

- [ ] **Step 4: Update path descriptions for all three approval endpoints**

Update descriptions to mention V0.9 Release-based approval (not Asset-based).
Add `release_id` to examples as the preferred identifier.

- [ ] **Step 5: Validate JSON**

Run: `python -c "import json; json.load(open('openapi/platform-api-v1.json'))"`

- [ ] **Step 6: Commit**

```bash
git add openapi/platform-api-v1.json
git commit -m "docs(openapi): update approval schemas — add release_id, dry_run, DDH lookups"
```

---

## Chunk 2: HTML Documentation Pages

### Task 5: Fix docs landing page (`web_interfaces/docs/interface.py`)

**Files:**
- Modify: `web_interfaces/docs/interface.py` (522 lines)

- [ ] **Step 1: Remove `/api/platform/validate` references (3 locations)**

Line 412: Remove workflow step 0 ("Validate" / `POST /api/platform/validate`)
  — Renumber remaining steps: Submit=1→0, Poll=2→1, Review=3→2, Approve=4→3
  OR keep numbering and replace validate with a note that dry_run on submit serves this purpose.

Line 446: Remove `<li>POST /api/platform/validate</li>` from Submission Endpoints card.

Lines 500-502: Remove the "Pre-flight Validation" concept card that references validate endpoint.

- [ ] **Step 2: Remove `/api/platform/lineage/{request_id}` reference**

Line 459: Remove `<li>GET /api/platform/lineage/{{request_id}}</li>` from Status & Monitoring card. This endpoint does not exist.

- [ ] **Step 3: Update "Key Concepts" from v0.8 to v0.9**

Line 490: Change `"Key Concepts (v0.8)"` → `"Key Concepts (v0.9)"`

Line 493-494: Update "Three-State Entity Model" to describe Asset+Release:
  Old: "Each dataset has three independent states: processing_status, approval_state, clearance_state"
  New: "Two-entity model: Asset (stable identity across versions) + Release (versioned artifact with approval_state and clearance_state). Each submission creates a Release under its Asset."

- [ ] **Step 4: Add missing endpoint to Catalog card**

After line 481 (`catalog/lookup`), add:
  `<li><code>GET /api/platform/catalog/asset/{{asset_id}}</code> - Asset by ID</li>`

- [ ] **Step 5: Validate Python syntax**

Run: `python -c "import ast; ast.parse(open('web_interfaces/docs/interface.py').read()); print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add web_interfaces/docs/interface.py
git commit -m "docs(landing): remove ghost endpoints, update to v0.9 entity model"
```

---

### Task 6: Fix platform interface page (`web_interfaces/platform/interface.py`)

**Files:**
- Modify: `web_interfaces/platform/interface.py` (1182 lines)

- [ ] **Step 1: Remove `/api/platform/validate` reference**

Line 935: Remove or replace the table row referencing `/api/platform/validate`.
Replace with a note that `POST /api/platform/submit?dry_run=true` serves this purpose.

- [ ] **Step 2: Remove `/api/platform/lineage/{id}` reference**

Line 1003: Remove or replace the table row referencing `/api/platform/lineage/{id}`.

- [ ] **Step 3: Validate Python syntax**

Run: `python -c "import ast; ast.parse(open('web_interfaces/platform/interface.py').read()); print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add web_interfaces/platform/interface.py
git commit -m "docs(platform-ui): remove ghost validate and lineage endpoint references"
```

---

### Task 7: Final validation

**Files:**
- Read: `openapi/platform-api-v1.json`, `web_interfaces/docs/interface.py`, `web_interfaces/platform/interface.py`

- [ ] **Step 1: Full JSON parse + path count**

```bash
python -c "
import json
with open('openapi/platform-api-v1.json') as f:
    spec = json.load(f)
print(f'Version: {spec[\"info\"][\"version\"]}')
print(f'Paths: {len(spec[\"paths\"])}')
print(f'Schemas: {len(spec[\"components\"][\"schemas\"])}')
for p in sorted(spec['paths']): print(f'  {p}')
"
```

Expected: 20 paths (was 21, minus /validate), version 0.10.3.3

- [ ] **Step 2: Grep for ghost endpoints across codebase**

```bash
grep -rn "platform/validate\|platform/lineage" web_interfaces/ --include="*.py"
```

Expected: No matches

- [ ] **Step 3: Grep for stale version references**

```bash
grep -n "0.9.16" openapi/platform-api-v1.json
```

Expected: No matches (all updated to 0.10.3.3)

- [ ] **Step 4: Commit (if any final fixes needed)**

```bash
git add -A
git commit -m "docs: final consistency validation pass"
```
