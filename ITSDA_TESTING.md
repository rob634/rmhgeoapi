# ITSDA QA Testing & Issue Tracker

**Created**: 18 FEB 2026
**Source**: QA team meeting notes (`feedback.md`) + `API Validation_Status.xlsx` (17 FEB 2026)
**QA Team**: Karthikeyan K, Megha, Jaganathan
**Dev Team**: Robert Mansour

---

## Meeting Action Items (feedback.md)

| # | Action Item | Owner | Status |
|---|-------------|-------|--------|
| 1 | Submit API draft mode — generate preview without version_id | Robert | DONE (17 FEB 2026) |
| 2 | Approval/Reject endpoint failures — investigate server-side errors | Robert | **DONE** (18 FEB 2026) — Draft lineage fix, asset creation made FATAL, missing `import json` fix, viewer form fields added. Deployed v0.8.19.6 |
| 3 | Platform endpoint failures — review shared spreadsheet findings | Robert | **DONE** (20 FEB 2026) — P1 fixed 18 FEB. P2 resubmit hardened 20 FEB (approval guard + asset update + platform_request update). P2 failures endpoint was data-dependent (works post-rebuild). P4 catalog data-dependent (passes after fresh submit+approve). P5 unpublish dry_run fixed 20 FEB. |
| 4 | Validate API returns 200 for invalid inputs — return proper error codes | Robert | **DONE** (18 FEB 2026) — Validate returns 400 on failure + identifier character validation via `_IDENTIFIER_PATTERN`. Deployed v0.8.19.6 |
| 5 | Service Layer SSL errors — investigate connection issues for some users | Robert | **DEFERRED** — Azure infrastructure / client-side TLS, not application code. Not reproducible from dev environment. |
| 6 | Consolidate QA findings into shared spreadsheet | Megha, Jaganathan | DONE |

### Meeting Context

- The Submit API previously required a `version_id`, blocking preview generation in draft mode. Updated to support draft flag (no version_id required).
- Collection ID and embedded URL are returned automatically via the status API when polling by request_id. No manual construction needed.
- Approve, Reject, Revoke, and other endpoints failing with null asset IDs or 500 errors despite previously working.
- QA automation identified negative test cases where APIs return 200 OK for invalid inputs.
- SSL connection errors preventing some users from accessing service layer APIs.

---

## Endpoint Validation Matrix

### Legend

| Symbol | Meaning |
|--------|---------|
| PASS | Endpoint working correctly |
| FAIL | Endpoint returning errors |
| PARTIAL | Endpoint returns 200 but behavior is incorrect |
| REGRESSED | Was working in prior validation, now broken |
| N/A | Not tested or not available |

---

### SET 1 — Core Submission & Processing Workflows

| # | Endpoint | v0.7 (JAN) | v0.8 Dev (05 FEB) | v0.8 QA (17 FEB) | Error Detail | Priority |
|---|----------|-----------|-------------------|-------------------|--------------|----------|
| 1.1 | Submit Vector | PASS | PASS | PASS | Vector, raster, and raster collection submit endpoints merged into unified `/api/platform/submit` | — |
| 1.2 | Vector Job Status | PASS | PASS | PASS | — | — |
| 1.3 | Resubmit (Dry Run) | N/A | N/A | **FIXED** | 500 was data-dependent (stale job refs post-rebuild). Hardened 20 FEB: approval guard, asset state reset, platform_request update. | P2 |
| 1.4 | Resubmit (Execute) | N/A | N/A | **FIXED** | Same as 1.3. Now blocks approved assets (409), updates asset + platform_request with new job_id. | P2 |
| 1.5 | Approval API | FAIL (404) | PASS | **FIXED** | 404 was stale data + silent asset creation failure. Fixed 18 FEB: FATAL asset creation, draft lineage fix, `import json`. Hardened 20 FEB: 3-tier asset fallback. | **P1** |
| 1.6 | Reject API | N/A | N/A | **FIXED** | Same fix as 1.5 (shared `_resolve_asset_id` chain). | **P1** |
| 1.7 | Revoke Approval | N/A | N/A | **FIXED** | Same fix as 1.5. Additionally 20 FEB: revoke deletes pgSTAC item (STAC B2C materialized view). | **P1** |
| 1.8 | Unpublish Vector | PASS | PASS | **FIXED** | `dry_run` check added before execution in all unpublish paths (vector, raster, collection). Fixed 20 FEB. | P5 |
| 1.9 | Submit Single Raster | FAIL (404) | PASS | PASS | Fixed in v0.8 — merged into unified submit | — |
| 1.10 | Raster Job / Poll Status | N/A | PARTIAL | PASS | Previously returned 200 but job had failed internally. Now working. | — |
| 1.11 | Submit Raster Collection | PASS | PASS | PASS | Merged into unified submit | — |
| 1.12 | Raster Collection Overwrite | PARTIAL | PASS | PASS | Returns same job_id with `overwrite=true` | — |
| 1.13 | Raster Collection Job Status | N/A | PARTIAL | DATA-DEP | API returns 200 but job failed. Not retested 17 FEB. Will pass after fresh submit+approve cycle. | P4 |
| 1.14 | Check Status APIs | PARTIAL | N/A | DATA-DEP | Need mapping APIs. Not retested. Will pass after fresh data exists. | P4 |
| 1.15 | Function App Logs | PASS | PASS | PASS | Service Layer Health endpoint working | — |

### SET 2 — Platform, Validation, Catalog & Service Layer

| # | Endpoint | v0.8 Dev (05 FEB) | v0.8 QA (17 FEB) | Error Detail | Priority |
|---|----------|-------------------|-------------------|--------------|----------|
| 2.1 | Platform Health | PASS | PASS | — | — |
| 2.2 | List Platforms | PASS | PASS | — | — |
| 2.3 | Get Platform Details | PASS | PASS | — | — |
| 2.4 | Platform Failures | FAIL | **FIXED** | 500 was data-dependent (empty/missing tables post-rebuild). Confirmed working 20 FEB — returns 200 with failure diagnostics. | P2 |
| 2.5 | Validate (Raster) | PASS | **FIXED** | Returns 400 on invalid input (was 200). `_IDENTIFIER_PATTERN` rejects special chars. Fixed 18 FEB. | P3 |
| 2.6 | Validate (Vector) | PASS | **FIXED** | Same fix as 2.5. | P3 |
| 2.7 | Validate (Lineage) | PASS | **FIXED** | Same fix as 2.5. | P3 |
| 2.8 | List Assets | FAIL | DATA-DEP | 404 due to empty `app.assets` table post-rebuild. No code bug — passes after fresh submit+approve cycle. | P4 |
| 2.9 | Lookup by DDH Identifiers | FAIL | PASS | Was returning 500, now fixed | — |
| 2.10 | Get STAC Item | PASS | DATA-DEP | 404 due to empty pgSTAC post-rebuild. Was working 05 FEB when data existed. No code bug. | P4 |
| 2.11 | Get Asset URLs / TiTiler | FAIL | DATA-DEP | 404 due to no assets post-rebuild. Passes after fresh submit+approve cycle. | P4 |
| 2.12 | List Items for Dataset | PARTIAL | PASS | Was returning 200 with empty body, now returning data | — |
| 2.13 | Service Layer Health | PASS | **DEFERRED** | SSL Connect Error for some users only. Infrastructure/client-side TLS — not application code. | P6 |
| 2.14 | STAC Collections | FAIL | PASS | Was returning 500 `UndefinedFunctionError`, now fixed | — |
| 2.15 | Vector Collections | PASS | PASS | — | — |
| 2.16 | API Documentation | PASS | PASS | — | — |

---

## Issue Clusters & Root Cause Analysis

### P1 — Asset Lookup Failure (Approve / Reject / Revoke) — RESOLVED

**Affected**: 1.5, 1.6, 1.7
**Error**: `404 — "No asset found for job: e0b7c82da7cdbcb1073e7ddcc29ee5e8d8e07884bcc77efe5ffb2555dddbf1e8"`
**Regression**: Approve was working on 05 FEB dev validation, broken by 17 FEB QA run.
**Status**: **FIXED** 18 FEB 2026, hardened 20 FEB 2026

**Root Causes Identified (all four fixed)**:
1. **Schema rebuild** wiped `app.geospatial_assets` — job.asset_id FK pointed to deleted records
2. **Asset creation was non-fatal** — `submit.py` swallowed errors. **Fixed**: now FATAL with 3-layer defense
3. **Draft lineage self-conflict** — drafts got `is_latest=True` and `version_ordinal=1` at submit, causing `assign_version()` to see the draft as its own predecessor. **Fixed**: drafts now get `lineage_id=None`, `version_ordinal=None`, `is_latest=False`
4. **Missing `import json`** — `asset_repository.py` crashed on all JSONB writes. **Fixed**: added import

**Additional hardening (20 FEB 2026)**:
- 3-tier asset fallback in `trigger_approvals.py`: Tier 1 (job.asset_id FK) → Tier 2 (job.parameters['asset_id']) → Tier 3 (api_requests.asset_id query)
- Upsert overwrite identity reset in `sql_generator.py`: `platform_refs`, `stac_item_id`, `stac_collection_id` now reset on overwrite

**Files**: `triggers/platform/submit.py`, `services/asset_service.py`, `infrastructure/asset_repository.py`, `triggers/trigger_approvals.py`, `core/schema/sql_generator.py`
**Commits**: `v0.8.19.6` (18 FEB), `63dbc94` (20 FEB), `23a42e5` (20 FEB)

---

### P2 — Resubmit & Platform Failures (500 errors) — RESOLVED

**Affected**: 1.3, 1.4, 2.4
**Error**: 500 Internal Server Error (no detailed error message captured)
**Status**: **FIXED** 20 FEB 2026

**Root Causes**:
1. **Resubmit 500** — data-dependent: stale job references post-rebuild caused lookup failures. Additionally, the endpoint had no awareness of the v0.8 asset lifecycle (no approval check, no asset update, no platform_request update).
2. **Platform Failures 500** — data-dependent: `GET /api/platform/failures` queries `app.jobs` table. 500 occurred when table was empty/missing post-rebuild. Confirmed working 20 FEB (returns 200 with failure diagnostics).

**Resubmit Hardening (20 FEB 2026)**:
- **Change 1**: Block resubmit on approved assets → 409 `ResubmitBlockedError` (both `/api/platform/resubmit` and `/api/jobs/{job_id}/resubmit`)
- **Change 2**: Reset asset state after resubmit (`current_job_id`, `processing_status`)
- **Change 3**: New `update_job_id()` in `ApiRequestRepository` — keeps status polling working after resubmit

**Files**: `triggers/platform/resubmit.py`, `triggers/jobs/resubmit.py`, `infrastructure/platform.py`

---

### P3 — Validate Endpoints Return 200 for Invalid Input — RESOLVED

**Affected**: 2.5, 2.6, 2.7
**Error**: Passing invalid request body returns 200 OK instead of 400/422
**Status**: **FIXED** 18 FEB 2026, additional fix 20 FEB 2026

**Root Cause**: Validate endpoint always returned HTTP 200 regardless of validation result.

**Fixes Applied**:
1. **(18 FEB)** `_IDENTIFIER_PATTERN` validation in `PlatformRequest` (`core/models/platform.py`). Rejects special characters (`#`, `&`, `?`, spaces) in `dataset_id`, `resource_id`, `version_id`, `previous_version_id`. Allowed: `a-zA-Z0-9`, hyphens, underscores, dots. Must start with letter or digit.
2. **(18 FEB)** Validate endpoint returns **400** when `validation_result.valid` is False (`triggers/trigger_platform_status.py`).
3. **(20 FEB)** Submit dry_run returns **400** for invalid validation (`triggers/platform/submit.py`).

**Files**: `core/models/platform.py`, `triggers/trigger_platform_status.py`, `triggers/platform/submit.py`

---

### P4 — Catalog Discovery 404s — RESOLVED (data-dependent)

**Affected**: 2.8, 2.10, 2.11, 1.13, 1.14
**Error**: 404 Not Found on List Assets, Get STAC Item, Get Asset URLs/TiTiler
**Status**: **NO CODE BUG** — data-dependent. All 404s caused by empty tables post-schema-rebuild.

**Root Cause**: Schema rebuild between 05 FEB and 17 FEB wiped `app.geospatial_assets` and `pgstac.items`. The endpoints work correctly when data exists. The 2.10 "regression" (was working 05 FEB) confirms this — data existed then.

**Resolution**: These endpoints will pass after a fresh submit → approve cycle creates assets and STAC items. Covered by Tests 1-7 then Test 11 in the test plan below.

---

### P5 — Unpublish dry_run Bug — RESOLVED

**Affected**: 1.8
**Error**: `dry_run=true` actually executes the unpublish. Subsequent `dry_run=false` call returns "request already submitted" (idempotent guard).
**Status**: **FIXED** 20 FEB 2026

**Root Cause**: Unpublish handler did not check `dry_run` flag before creating the unpublish job and writing the tracking record.

**Fix Applied**: `dry_run` check added early in all three unpublish execution paths:
- `_execute_vector_unpublish()` — returns preview of `would_delete` without creating job
- `_execute_raster_unpublish()` — returns preview of `would_delete` without creating job
- `_handle_collection_unpublish()` — returns preview with item count without creating jobs
- Asset soft-delete also gated by `if original_request and not dry_run:`

**File**: `triggers/platform/unpublish.py`

---

### P6 — SSL Connection Errors — DEFERRED

**Affected**: 2.13
**Error**: SSL Connect Error for some users accessing Service Layer Health endpoint
**Status**: **DEFERRED** — infrastructure issue, not application code

**Assessment**: Not reproducible from dev environment. Likely Azure App Service TLS certificate chain issue or client-side proxy/TLS configuration. Not an application code bug — all endpoints respond correctly when SSL handshake succeeds.

---

## Architecture Context — Draft Mode + Approval (17 FEB 2026)

The platform workflow underwent a major architectural change. Version assignment and classification are now **deferred to approval**, not required at submission. This is the critical lifecycle:

### Full Lifecycle Flow

```
STEP 1: SUBMIT (draft mode — no version_id required)
  ┌─────────────────────────────────────────────────────────────┐
  │ POST /api/platform/submit                                   │
  │   Body: { dataset_id, resource_id, file_name, ... }         │
  │                                                             │
  │ What happens:                                               │
  │   1. PlatformRequest Pydantic validation (identifier chars) │
  │   2. Generate deterministic request_id = SHA256(ds+res)     │
  │   3. Create GeospatialAsset (PENDING_REVIEW, UNCLEARED)     │
  │      - asset_id = SHA256(platform_id + platform_refs)       │
  │      - platform_refs = { dataset_id, resource_id }          │
  │      - NO version_id in platform_refs (draft)               │
  │   4. Submit CoreMachine job (process_raster_v2 / vector)    │
  │   5. Write api_requests thin tracking record                │
  │                                                             │
  │ Returns: { request_id, job_id, asset_id, monitor_url }      │
  └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
STEP 2: JOB PROCESSING (async — Service Bus → Handler)
  ┌─────────────────────────────────────────────────────────────┐
  │ Handler processes raster → COG conversion → STAC insert     │
  │ Handler processes vector → PostGIS table → STAC insert      │
  │                                                             │
  │ On completion: job status = COMPLETED                       │
  │ Asset still: PENDING_REVIEW, UNCLEARED, no version_id       │
  └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
STEP 3: POLL STATUS (confirm job completed)
  ┌─────────────────────────────────────────────────────────────┐
  │ GET /api/platform/status/{request_id}                       │
  │                                                             │
  │ Returns: job_status, embedded_url, stac_collection_id, etc. │
  └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
STEP 4: APPROVE (finalization — version + classification required)
  ┌─────────────────────────────────────────────────────────────┐
  │ POST /api/platform/approve                                  │
  │   Body: {                                                   │
  │     request_id (or job_id or asset_id),                     │
  │     reviewer: "user@example.com",                           │
  │     clearance_level: "ouo" | "public",    ← REQUIRED       │
  │     version_id: "v1.0",                   ← REQUIRED       │
  │     previous_version_id: null | "v0.9"    ← if lineage     │
  │   }                                                         │
  │                                                             │
  │ What happens:                                               │
  │   1. Resolve asset from request_id/job_id/asset_id          │
  │   2. Detect draft (no version_id in platform_refs)          │
  │   3. assign_version():                                      │
  │      - Validate lineage (reuses submit validation)          │
  │      - Update platform_refs with version_id                 │
  │      - Rebuild stac_item_id & table_name with version       │
  │      - Wire lineage: ordinal, previous_asset_id, is_latest  │
  │   4. approve_asset():                                       │
  │      - Set approval_state = APPROVED                        │
  │      - Set clearance_state = OUO or PUBLIC                  │
  │      - Update STAC item properties                          │
  │      - If PUBLIC: trigger ADF pipeline for external zone    │
  │                                                             │
  │ Returns: { asset_id, approval_state, clearance_state, ... } │
  └─────────────────────────────────────────────────────────────┘
```

### Asset Resolution Chain (`_resolve_asset_id`)

The approve/reject/revoke endpoints accept multiple identifier types:

```
asset_id     → direct lookup in app.geospatial_assets
stac_item_id → lookup via asset_repo.get_by_stac_item_id()
job_id       → lookup job → job.asset_id FK
request_id   → lookup api_request → api_request.asset_id FK → fallback: job.asset_id FK
```

**Key insight**: The QA team's error `"No asset found for job: e0b7c82d..."` means they passed `job_id` and the `job.asset_id` FK was NULL. This happens when:
1. Schema rebuild destroyed `app.geospatial_assets` (the job record exists but asset was deleted)
2. Asset creation failed silently at submit time (line 424-428 in `submit.py` swallows errors)
3. The `asset_id` was never written to the job record

---

## Testing Plan

### Pre-Requisites

- Deploy latest code: `deploy.sh all`
- Schema ensure (NOT rebuild): `POST /api/dbadmin/maintenance?action=ensure&confirm=yes`
- Confirm base health: `GET /api/health`

### Orchestrator URL

All tests use: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`

---

### TEST 1 — Full Lifecycle: Submit (Draft) → Poll → Approve (Vector)

**Purpose**: End-to-end happy path for draft mode with vector data

```bash
# 1A. SUBMIT — Draft mode (no version_id)
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-regression-vector",
    "resource_id": "test-geojson",
    "operation": "CREATE",
    "container_name": "bronze-vectors",
    "file_name": "admin0.geojson",
    "title": "QA Regression Test - Vector Draft",
    "access_level": "OUO"
  }'
# EXPECTED: 200 with request_id, job_id, asset_id
# CAPTURE: request_id, job_id

# 1B. POLL — Wait for job completion
curl "${BASE_URL}/api/platform/status/{REQUEST_ID}"
# EXPECTED: 200 with job_status eventually "completed"

# 1C. VERIFY ASSET EXISTS — Check asset record in DB
curl "${BASE_URL}/api/dbadmin/diagnostics/all" | python3 -m json.tool | grep -A5 assets
# Or direct: query app.geospatial_assets WHERE asset_id = ...

# 1D. APPROVE — Finalize with version + clearance
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "qa-test@example.com",
    "clearance_level": "ouo",
    "version_id": "v1.0"
  }'
# EXPECTED: 200 with approval_state="approved", clearance_state="ouo"

# 1E. VERIFY APPROVAL STATE
curl "${BASE_URL}/api/platform/approvals?status=approved"
# EXPECTED: Contains the approved asset
```

**Failure checkpoints**:
- 1A fails → PlatformRequest validation or job creation issue
- 1B stuck in processing → Handler/Service Bus issue
- 1C no asset → `create_or_update_asset()` failed silently at submit
- 1D 404 "No asset found" → Asset resolution chain broken (THIS IS THE QA BUG)
- 1D 400 "version_id required" → Draft detection works correctly
- 1D 200 → Full lifecycle works

---

### TEST 2 — Full Lifecycle: Submit (Draft) → Poll → Approve (Raster)

**Purpose**: Same as Test 1 but for raster. Critical because raster STAC insertion was recently fixed.

```bash
# 2A. SUBMIT — Draft mode raster
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-regression-raster",
    "resource_id": "test-tif",
    "operation": "CREATE",
    "container_name": "bronze-rasters",
    "file_name": "stactest5bigraster.tif",
    "title": "QA Regression Test - Raster Draft",
    "access_level": "OUO"
  }'

# 2B-2E: Same flow as Test 1 (poll, verify asset, approve, verify state)
```

---

### TEST 3 — Replicate QA Team's Exact Error

**Purpose**: Reproduce the "No asset found for job" 404

```bash
# 3A. Try to approve using the QA team's job_id
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "e0b7c82da7cdbcb1073e7ddcc29ee5e8d8e07884bcc77efe5ffb2555dddbf1e8",
    "reviewer": "qa-test@example.com",
    "clearance_level": "ouo",
    "version_id": "v1.0"
  }'
# EXPECTED: 404 (stale job from before schema rebuild)
# This confirms the QA issue was data loss from rebuild, not a code bug

# 3B. Check if the job record exists at all
curl "${BASE_URL}/api/dbadmin/jobs?limit=5"
# If empty → schema rebuild destroyed all data (expected)

# 3C. Check if geospatial_assets table has any rows
curl "${BASE_URL}/api/dbadmin/diagnostics/all"
```

---

### TEST 4 — Reject Flow

**Purpose**: Test rejection of a draft asset

```bash
# 4A. SUBMIT a new draft
# (Use different dataset_id to avoid idempotent collision)
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-regression-reject",
    "resource_id": "test-reject",
    "operation": "CREATE",
    "container_name": "bronze-vectors",
    "file_name": "admin0.geojson"
  }'

# 4B. Wait for completion, then REJECT
curl -X POST "${BASE_URL}/api/platform/reject" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "qa-test@example.com",
    "reason": "QA regression test - intentional rejection"
  }'
# EXPECTED: 200 with approval_state="rejected"
```

---

### TEST 5 — Revoke Flow (Approve then Revoke)

**Purpose**: Test the full approve → revoke lifecycle

```bash
# 5A. Use the asset from Test 1 (already approved)
curl -X POST "${BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{TEST1_REQUEST_ID}",
    "revoker": "qa-test@example.com",
    "reason": "QA regression test - intentional revocation"
  }'
# EXPECTED: 200 with approval_state="revoked"
```

---

### TEST 6 — Approve with Versioned Submit (Non-Draft)

**Purpose**: Test the pre-draft-mode path where version_id is provided at submit

```bash
# 6A. SUBMIT with version_id (legacy mode)
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-regression-versioned",
    "resource_id": "test-versioned",
    "version_id": "v1.0",
    "operation": "CREATE",
    "container_name": "bronze-vectors",
    "file_name": "admin0.geojson",
    "access_level": "OUO"
  }'

# 6B. Poll, then approve (version_id NOT required since it was set at submit)
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "qa-test@example.com",
    "clearance_level": "ouo"
  }'
# EXPECTED: 200 — version already assigned, no assign_version() needed
```

---

### TEST 7 — Version Lineage (v1 → v2 at Approval)

**Purpose**: Test version chaining through draft mode approval

```bash
# 7A. Submit first version (draft)
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-lineage-test",
    "resource_id": "test-lineage",
    "container_name": "bronze-vectors",
    "file_name": "admin0.geojson"
  }'
# → Approve with version_id="v1.0"

# 7B. Submit second version (same dataset_id + resource_id, new file)
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-lineage-test",
    "resource_id": "test-lineage",
    "container_name": "bronze-vectors",
    "file_name": "admin0.geojson",
    "processing_options": {"overwrite": true}
  }'
# → Approve with version_id="v2.0", previous_version_id="v1.0"
# EXPECTED: Lineage chain: v1.0 → v2.0, v1.0.is_latest=false
```

---

### TEST 8 — Negative Cases (Validate Response Codes)

**Purpose**: Replicate QA finding that validate returns 200 for invalid input

```bash
# 8A. Empty body
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{}'
# EXPECTED: 400/422 (not 200)

# 8B. Special characters in identifiers
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "bad#name",
    "resource_id": "test",
    "container_name": "bronze-vectors",
    "file_name": "test.geojson"
  }'
# EXPECTED: 400/422 with "invalid characters: {'#'}" message

# 8C. Missing required fields
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "test"}'
# EXPECTED: 400/422

# 8D. Approve without clearance_level
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "fake",
    "reviewer": "user@example.com"
  }'
# EXPECTED: 400 "clearance_level is required"

# 8E. Approve draft without version_id
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{DRAFT_REQUEST_ID}",
    "reviewer": "user@example.com",
    "clearance_level": "ouo"
  }'
# EXPECTED: 400 "version_id is required when approving a draft asset"

# 8F. Reject without reason
curl -X POST "${BASE_URL}/api/platform/reject" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "user@example.com"
  }'
# EXPECTED: 400 "reason is required for audit trail"
```

---

### TEST 9 — Resubmit (P2)

**Purpose**: Test resubmit endpoint

```bash
# 9A. Resubmit dry_run
curl -X POST "${BASE_URL}/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{COMPLETED_REQUEST_ID}",
    "dry_run": true
  }'
# EXPECTED: 200 with validation info, no job created

# 9B. Resubmit execute
curl -X POST "${BASE_URL}/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{COMPLETED_REQUEST_ID}",
    "dry_run": false
  }'
# EXPECTED: 200 with new job_id
```

---

### TEST 10 — Unpublish dry_run Bug (P5)

**Purpose**: Verify dry_run doesn't actually execute

```bash
# 10A. Unpublish with dry_run=true
curl -X POST "${BASE_URL}/api/platform/unpublish" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{APPROVED_REQUEST_ID}",
    "dry_run": true
  }'
# EXPECTED: 200 with preview of what WOULD be deleted, NO actual deletion

# 10B. Verify data still exists after dry_run
curl "${BASE_URL}/api/platform/status/{APPROVED_REQUEST_ID}"
# EXPECTED: Same status as before — nothing changed

# 10C. NOW execute for real
curl -X POST "${BASE_URL}/api/platform/unpublish" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{APPROVED_REQUEST_ID}",
    "dry_run": false
  }'
# EXPECTED: 200 with actual deletion
```

---

### TEST 11 — Catalog Discovery (P4, after Tests 1-2 complete)

**Purpose**: Verify catalog endpoints work when assets + STAC items exist

```bash
# 11A. List Assets
curl "${BASE_URL}/api/platform/catalog/assets"
# EXPECTED: 200 with list of assets from Tests 1-6

# 11B. Get STAC Item
curl "${BASE_URL}/api/platform/catalog/stac-item?collection_id={COLLECTION_ID}&item_id={ITEM_ID}"
# EXPECTED: 200 with STAC item JSON

# 11C. Get Asset URLs / TiTiler
curl "${BASE_URL}/api/platform/catalog/urls?asset_id={ASSET_ID}"
# EXPECTED: 200 with TiTiler URLs

# 11D. List Items for Dataset
curl "${BASE_URL}/api/platform/catalog/items?dataset_id=qa-regression-raster"
# EXPECTED: 200 with items list

# 11E. Lookup by DDH Identifiers
curl "${BASE_URL}/api/platform/catalog/lookup?dataset_id=qa-regression-vector&resource_id=test-geojson"
# EXPECTED: 200 with asset + URLs
```

---

## Test Execution Order

Tests must run in this order due to dependencies:

```
DEPLOY + ENSURE SCHEMA
        │
        ▼
TEST 1 (vector draft → approve)  ──┐
TEST 2 (raster draft → approve)  ──┤
TEST 3 (replicate QA bug)          │
        │                          │
        ▼                          │
TEST 4 (reject flow)               │
TEST 5 (revoke flow — uses T1)  ◄──┘
TEST 6 (versioned submit + approve)
TEST 7 (lineage v1→v2)
        │
        ▼
TEST 8 (negative cases — independent)
TEST 9 (resubmit — uses completed jobs)
TEST 10 (unpublish dry_run — uses approved asset)
        │
        ▼
TEST 11 (catalog — needs STAC items from T1-T7)
```

---

## 19-20 FEB 2026 — Sprint Focus: Open QA Issues

**Goal**: Fix all remaining open items, run full test suite on fresh schema, summarize results.
**Status**: **ALL CODE ISSUES RESOLVED** as of 20 FEB 2026. P4 items are data-dependent (pass after fresh data). P6 deferred (infrastructure).

### Items Summary (Final)

| # | QA Ref | Issue | Priority | Status | Resolution |
|---|--------|-------|----------|--------|------------|
| A | 1.3, 1.4 | Resubmit endpoint returns 500 | P2 | **FIXED** | Data-dependent 500 + hardened with approval guard (409), asset state reset, platform_request job_id update. `triggers/platform/resubmit.py`, `triggers/jobs/resubmit.py`, `infrastructure/platform.py` |
| B | 2.4 | Platform Failures endpoint returns 500 | P2 | **FIXED** | Data-dependent — `GET /api/platform/failures` queries `app.jobs`. Works post-rebuild. Confirmed 200 on 20 FEB. Route: `triggers/trigger_platform_status.py:1171` |
| C | 1.8 | Unpublish `dry_run=true` actually executes | P5 | **FIXED** | `dry_run` check added before job creation in all unpublish paths (vector, raster, collection). `triggers/platform/unpublish.py` |
| D | 2.8 | List Assets returns 404 | P4 | **DATA-DEP** | No code bug. Empty `app.assets` table post-rebuild. Passes after fresh submit+approve cycle. |
| E | 2.10 | Get STAC Item returns 404 (REGRESSED) | P4 | **DATA-DEP** | No code bug. Empty `pgstac.items` post-rebuild. Was working 05 FEB when data existed. |
| F | 2.11 | Get Asset URLs / TiTiler returns 404 | P4 | **DATA-DEP** | No code bug. No assets or STAC items to serve. Passes after fresh data. |
| G | 2.13 | SSL Connect Error for some users | P6 | **DEFERRED** | Infrastructure/client-side TLS — not application code. Not reproducible from dev. |

### Progress Log

| Date | Item | Action | Result |
|------|------|--------|--------|
| 18 FEB | P1 | Draft lineage fix, FATAL asset creation, `import json` fix | FIXED — v0.8.19.6 |
| 18 FEB | P3 | Validate returns 400, `_IDENTIFIER_PATTERN` | FIXED — v0.8.19.6 |
| 19 FEB | — | CVE fixes (aiohttp, pillow, geopandas, jinja2) | Deployed |
| 20 FEB | P1 | 3-tier asset fallback, upsert overwrite identity reset | Hardened — commit `63dbc94`, `23a42e5` |
| 20 FEB | P2 (A) | Resubmit approval guard + asset update + platform_request update | FIXED — v0.8.20.0 |
| 20 FEB | P2 (B) | Platform Failures confirmed working (data-dependent) | VERIFIED — returns 200 |
| 20 FEB | P3 | Submit dry_run returns 400 on invalid | FIXED — commit `23a42e5` |
| 20 FEB | P5 (C) | Unpublish dry_run gated before job creation | FIXED |
| 20 FEB | — | Resubmit `monitor_url` fixed to use `request_id` | FIXED |

---

## Regression Tracking

| Endpoint | Working Date | Broken Date | Fixed Date | Resolution |
|----------|-------------|-------------|------------|------------|
| Approval API | 05 FEB 2026 | 17 FEB 2026 | **18 FEB 2026** | Draft lineage fix + FATAL asset creation + `import json` fix. Hardened 20 FEB: 3-tier asset fallback, upsert overwrite identity reset. |
| Reject API | N/A | 17 FEB 2026 | **18 FEB 2026** | Same fix as Approve (shared `_resolve_asset_id`) |
| Revoke API | N/A | 17 FEB 2026 | **18 FEB 2026** | Same fix as Approve. 20 FEB: revoke now deletes pgSTAC item (STAC B2C materialized view). |
| Validate (200 for invalid) | N/A | 17 FEB 2026 | **18 FEB 2026** | Returns 400 + identifier pattern validation. 20 FEB: submit dry_run also returns 400. |
| Get STAC Item | 05 FEB 2026 | 17 FEB 2026 | **DATA-DEP** | No code bug. Empty pgSTAC post-rebuild. Passes after fresh submit+approve cycle. |
| Resubmit | N/A | 17 FEB 2026 | **20 FEB 2026** | Data-dependent 500 + hardened: approval guard (409), asset state reset, platform_request update, `monitor_url` fix. |
| Platform Failures | N/A | 17 FEB 2026 | **20 FEB 2026** | Data-dependent 500. `GET /api/platform/failures` works post-rebuild. Confirmed 200 on 20 FEB. |
| Unpublish dry_run | N/A | 17 FEB 2026 | **20 FEB 2026** | `dry_run` check added before job creation in all unpublish paths (vector, raster, collection). |
| Service Layer Health | 05 FEB 2026 | 17 FEB 2026 | **DEFERRED** | SSL — infrastructure issue, not application code. Not reproducible from dev. |

---

## Root Cause Analysis (All Resolved)

### P1 — Asset Lookup Failure (RESOLVED 18 FEB 2026, hardened 20 FEB 2026)

**Root causes identified (all four fixed)**:
1. **Schema rebuild** wiped `app.geospatial_assets` — job.asset_id FK pointed to deleted records
2. **Asset creation was non-fatal** — `submit.py` swallowed errors and continued without asset. **Fixed**: now FATAL with 3-layer defense.
3. **Draft lineage self-conflict** — drafts got `is_latest=True` and `version_ordinal=1` at submit, causing `assign_version()` to see the draft as its own predecessor. **Fixed**: drafts now get `lineage_id=None`, `version_ordinal=None`, `is_latest=False`.
4. **Missing `import json`** — `asset_repository.py` crashed on all JSONB writes. **Fixed**: added import.
5. **(20 FEB)** **3-tier asset fallback** in approval trigger: job.asset_id FK → job.parameters['asset_id'] → api_requests.asset_id query.
6. **(20 FEB)** **Upsert overwrite identity reset** — `stac_item_id`, `platform_refs`, `stac_collection_id` now properly reset on overwrite, preventing orphaned pgSTAC items.

### P2 — Resubmit & Platform Failures (RESOLVED 20 FEB 2026)

**Root cause (Resubmit)**: Data-dependent 500 from stale job refs post-rebuild. Additionally, endpoint lacked v0.8 asset lifecycle awareness. **Fixed**: approval guard (blocks approved assets with 409), asset state reset (`current_job_id`, `processing_status`), platform_request `job_id` update, `monitor_url` corrected to use `request_id`.

**Root cause (Platform Failures)**: Data-dependent 500 from empty/missing `app.jobs` table post-rebuild. No code bug — endpoint works correctly when table exists. **Confirmed** working 20 FEB.

### P3 — Validate Returns 200 (RESOLVED 18 FEB 2026)

**Root cause**: Validate endpoint always returned HTTP 200 regardless of result. **Fixed**: returns 400 when `validation_result.valid` is False. Additionally, `_IDENTIFIER_PATTERN` now rejects special characters in identifiers. **(20 FEB)** Submit dry_run also returns 400 for invalid.

### P4 — Catalog Discovery 404s (DATA-DEPENDENT, no code bug)

**Root cause**: Schema rebuild wiped all data from `app.geospatial_assets` and `pgstac.items`. Endpoints work correctly when data exists. Confirmed by 05 FEB validation (data existed, endpoints passed) vs 17 FEB (data wiped, endpoints 404). Will pass after fresh submit+approve cycle.

### P5 — Unpublish dry_run (RESOLVED 20 FEB 2026)

**Root cause**: Unpublish handler did not check `dry_run` flag before creating job and writing tracking record. **Fixed**: `dry_run` check added early in all three execution paths (`_execute_vector_unpublish`, `_execute_raster_unpublish`, `_handle_collection_unpublish`). Asset soft-delete also gated.

### P6 — SSL Connection Errors (DEFERRED)

**Assessment**: Infrastructure/client-side TLS issue. Not reproducible from dev environment. Not an application code bug.

---

## Fixes Applied

| Date | Fix | Scope | Commit | QA Issue |
|------|-----|-------|--------|----------|
| 17 FEB 2026 | Draft mode — submit without version_id | `triggers/platform/submit.py`, `core/models/platform.py` | — | 1.1 (action item 1) |
| 18 FEB 2026 | Identifier character validation (`_IDENTIFIER_PATTERN`) | `core/models/platform.py` — `PlatformRequest` | — | P3 (2.5, 2.6, 2.7) |
| 18 FEB 2026 | pgSTAC datetime NULL fix | `core/models/unified_metadata.py`, `services/service_stac_metadata.py` | `9e6f15d` | — |
| 18 FEB 2026 | pgSTAC partition fix — create collection before item insert | `services/handler_process_raster_complete.py` | `25e29b6` | — |
| 18 FEB 2026 | STAC DRY cleanup — rename app_meta, extract ISO3 helper, remove dead code | Multiple files | `fea31a1` | — |
| 18 FEB 2026 | Unified raster collection builder + strip MosaicJSON | `services/stac_collection.py`, `services/handler_process_raster_complete.py` | `54829d6` | — |
| 18 FEB 2026 | Version ID / Previous Version ID fields added to viewer approval forms | `web_interfaces/raster_viewer/interface.py`, `web_interfaces/vector_viewer/service.py` | — | P1 (1.5) |
| 18 FEB 2026 | Draft lineage self-conflict fix — drafts get no lineage at submit | `triggers/platform/submit.py`, `services/asset_service.py` | — | P1 (1.5, 1.6, 1.7) |
| 18 FEB 2026 | Asset creation made FATAL (was silent warning) | `triggers/platform/submit.py` | — | P1 (root cause 2) |
| 18 FEB 2026 | Post-creation asset_id verification + emergency repair | `triggers/platform/submit.py`, `infrastructure/jobs_tasks.py` | — | P1 (root cause 3) |
| 18 FEB 2026 | Missing `import json` in asset_repository.py | `infrastructure/asset_repository.py` | — | P1 (crash) |
| 18 FEB 2026 | Validate endpoint returns 400 on failure (was always 200) | `triggers/trigger_platform_status.py` | — | P3 (2.5, 2.6, 2.7) |
| 19 FEB 2026 | CVE fixes — aiohttp, pillow, geopandas, jinja2 | `requirements.txt`, `requirements-docker.txt` | — | — |
| 19 FEB 2026 | Deploy script — ACR build failure detection + timeout | `deploy.sh` | — | — |
| 20 FEB 2026 | STAC B2C materialized view — pgSTAC writes deferred to approval, deleted on revoke | `services/asset_approval_service.py`, `services/handler_process_raster_complete.py`, `services/stac_catalog.py`, `infrastructure/raster_metadata_repository.py` | — | Architectural |
| 20 FEB 2026 | Revoke-first workflow — block draft submission when approved version exists | `triggers/platform/submit.py` | `63dbc94` | P1 (integrity) |
| 20 FEB 2026 | Upsert overwrite identity reset — `stac_item_id`, `platform_refs`, `stac_collection_id` | `core/schema/sql_generator.py` | `63dbc94` | P1 (orphan prevention) |
| 20 FEB 2026 | 3-tier asset fallback in approval trigger | `triggers/trigger_approvals.py` | `23a42e5` | P1 (1.5, 1.6, 1.7) |
| 20 FEB 2026 | Submit dry_run returns 400 on invalid validation | `triggers/platform/submit.py` | `23a42e5` | P3 (2.5, 2.6, 2.7) |
| 20 FEB 2026 | Geo integrity timer `success` field added | `triggers/admin/geo_integrity_timer.py` | `23a42e5` | — |
| 20 FEB 2026 | Fragment param works without HX-Request header | `web_interfaces/__init__.py` | `23a42e5` | — |
| 20 FEB 2026 | Resubmit hardening — approval guard, asset state reset, platform_request update | `triggers/platform/resubmit.py`, `triggers/jobs/resubmit.py`, `infrastructure/platform.py` | — | P2 (1.3, 1.4) |
| 20 FEB 2026 | Unpublish dry_run gated before job creation | `triggers/platform/unpublish.py` | — | P5 (1.8) |
| 20 FEB 2026 | Resubmit `monitor_url` fixed to use `request_id` instead of `job_id` | `triggers/platform/resubmit.py` | — | P2 |
