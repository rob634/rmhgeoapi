# QA Test Sequence

**Last Updated**: 21 FEB 2026
**Base URL**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`

---

## Test Runs

| Run | Version | Date | Focus | Tests | All Pass |
|-----|---------|------|-------|-------|----------|
| [Run 1](#run-1--v08198--asset-lifecycle-19-feb-2026) | 0.8.19.8 | 19 FEB 2026 | Asset lifecycle (draft, approve, revoke, lineage) | 1-7, V1-V7, D-F | Partial (E, F had pgSTAC rename gap) |
| [Run 2](#run-2--v08200--stac-b2c-materialization-20-feb-2026) | 0.8.20.0 | 20 FEB 2026 | STAC B2C materialized view, revoke-first workflow | B1-B10 | PASS |
| [Run 3](#run-3--v08201--resubmit-hardening-20-feb-2026) | 0.8.20.1 | 20 FEB 2026 | Platform resubmit pipeline hardening (raster + vector) | R1-R6, V-R1-V-R6 | PASS |

---

# Run 3 — v0.8.20.1 — Resubmit Hardening (20 FEB 2026)

**Version**: 0.8.20.1
**Environment**: Fresh schema rebuild + pgSTAC nuke. Tests the `POST /api/platform/resubmit` pipeline end-to-end after fixing 5 bugs found during flow trace analysis.

**Fixes deployed in this version**:

| Fix | Severity | Issue |
|-----|----------|-------|
| C | CRITICAL | `_drop_table()` referenced non-existent `PostgreSQLAdapter` — vector resubmit crashed with `ImportError` |
| D | Medium | New job created by `_resubmit_job()` was missing `asset_id` FK — broke job→asset linkage |
| B | Medium | `_plan_cleanup()` only checked `parameters` for `table_name`, not `result_data` — vector cleanup missed PostGIS table |
| E | Low | Deterministic `job_id` hash collision — if old job delete failed, new insert silently did nothing |
| A | Cosmetic | STAC cleanup comments updated for B2C architecture |
| — | CRITICAL | `_resolve_job_id()` used `.get()` on Pydantic `ApiRequest` model — all resubmit calls crashed |
| — | CRITICAL | `_delete_blob()` referenced non-existent `BlobStorageAdapter` — blob deletion crashed |

Also fixed same `PostgreSQLAdapter` and `BlobStorageAdapter` bugs in `triggers/jobs/delete.py`.

### Summary

| Test | Description | Result |
|------|-------------|--------|
| **RASTER RESUBMIT** | | |
| R1 | Submit raster draft | PASS |
| R2 | Job completes | PASS |
| R3 | Reject asset | PASS |
| R4 | Resubmit dry_run (cleanup preview) | PASS |
| R5 | Resubmit execute (cleanup + new job) | PASS |
| R6 | Resubmitted job completes | PASS |
| **VECTOR RESUBMIT** | | |
| V-R1 | Submit vector draft | PASS |
| V-R2 | Reject vector asset | PASS |
| V-R3 | Resubmit dry_run (table in cleanup plan — Fix B) | PASS |
| V-R4 | Resubmit execute (actual table drop — Fix C) | PASS |
| V-R5 | New job has `asset_id` (Fix D) | PASS |
| V-R6 | Resubmitted vector job completes | PASS |

---

### Pre-Requisites

```bash
# pgSTAC nuke
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"

# Schema rebuild
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"
```

---

### TEST R1: Submit Raster Draft

**Purpose**: Create a raster asset to test reject → resubmit cycle

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-resubmit-test",
    "resource_id": "dctest",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "submitted_by": "claude-qa"
  }'
```

**Result**: PASS
- `request_id`: `4f907d030ea0fa257667c6210c77d31d`
- `job_id`: `7f02693b4a8c97b277a88f70d006c446423e1f0272a58fbd9786833f5d942037`

---

### TEST R2: Job Completes

```bash
curl "${BASE_URL}/api/platform/status/4f907d030ea0fa257667c6210c77d31d"
```

**Result**: PASS
- `job_status`: `completed` (~30s)
- `asset_id`: `7a659986a89e2ffa699d8f2baf97543e`
- `approval_state`: `pending_review`

---

### TEST R3: Reject Asset

**Purpose**: Put asset into rejected state to test resubmit pathway

```bash
curl -X POST "${BASE_URL}/api/platform/reject" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "7a659986a89e2ffa699d8f2baf97543e",
    "reviewer": "claude-qa",
    "reason": "QA resubmit test"
  }'
```

**Result**: PASS
- `approval_state`: `rejected`

---

### TEST R4: Resubmit Dry Run

**Purpose**: Verify resubmit resolves identifiers correctly and plans cleanup (this was the `.get()` crash point before fix)

```bash
curl -X POST "${BASE_URL}/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "4f907d030ea0fa257667c6210c77d31d",
    "dry_run": true
  }'
```

**Result**: PASS
- `platform_refs` correctly resolved (dataset_id, resource_id, version_id from Pydantic model attribute access)
- `cleanup_plan`:
  - `tasks_to_delete`: 1
  - `job_to_delete`: true
  - `stac_items_to_delete`: `["qa-resubmit-test-dctest-draft"]` (B2C: no pgSTAC item exists, safe no-op)
  - `tables_to_drop`: `[]` (raster job, no PostGIS tables)
  - `blobs_to_delete`: `[]`
- Parameters include `asset_id: 7a659986...` (will be wired into new job)

---

### TEST R5: Resubmit Execute

**Purpose**: Full resubmit — cleanup old job artifacts, create new job with same parameters

```bash
curl -X POST "${BASE_URL}/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "4f907d030ea0fa257667c6210c77d31d"
  }'
```

**Result**: PASS
- `original_job_id`: `7f02693b4a8c97b277a88f70d006c446423e1f02...`
- `new_job_id`: `27084d1c7b025ffdb0e94cd585b5eed1484f528f...` (unique — Fix E confirmed)
- `cleanup_summary`:
  - `tasks_deleted`: 1
  - `job_deleted`: true
  - `stac_items_deleted`: `["qa-resubmit-test-dctest-draft"]`
  - `errors`: `[]` (clean execution)
- `monitor_url`: `/api/platform/status/4f907d030ea0fa257667c6210c77d31d` (uses request_id — monitor_url fix confirmed)

**Fix D verification** (new job has `asset_id` wired):
```bash
curl "${BASE_URL}/api/dbadmin/jobs/27084d1c7b025ffdb0e94cd585b5eed1484f528f8e8b9a13b6fcac9ee14e98f5"
```
- `asset_id`: `7a659986a89e2ffa699d8f2baf97543e` — **CONFIRMED** (previously was NULL)

---

### TEST R6: Resubmitted Job Completes

```bash
curl "${BASE_URL}/api/platform/status/4f907d030ea0fa257667c6210c77d31d"
```

**Result**: PASS
- `job_status`: `completed` (~30s)
- Resubmitted raster processed successfully with same parameters

---

### Vector Resubmit Tests (V-R1 through V-R6)

**Purpose**: Exercise vector-specific code paths — PostGIS table drop (Fix C), `table_name` from `result_data` (Fix B)

| Test | Description | Result |
|------|-------------|--------|
| V-R1 | Submit vector draft | PASS |
| V-R2 | Reject vector asset | PASS |
| V-R3 | Resubmit dry_run (verify table in cleanup plan) | PASS |
| V-R4 | Resubmit execute (actual table drop) | PASS |
| V-R5 | New job has `asset_id` | PASS |
| V-R6 | Resubmitted vector job completes | PASS |

---

### TEST V-R1: Submit Vector Draft

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "qa-vector-resubmit",
    "resource_id": "cutlines",
    "data_type": "vector",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg",
    "submitted_by": "claude-qa"
  }'
```

**Result**: PASS
- `request_id`: `24073bca43a8d9b2628a000483a8ab4f`
- `job_id`: `1612617e126de1fa3f11f07bffd345714d0966a11ecb4a521f23ed6af9dddfdf`
- `asset_id`: `be2a9e4664452af0c8782ad66440b7bd`
- Job completed instantly
- `result_data.table_name`: `qa_vector_resubmit_cutlines_draft`
- `result_data.schema`: `geo`
- `result_data.total_rows`: 1,401

---

### TEST V-R2: Reject Vector Asset

```bash
curl -X POST "${BASE_URL}/api/platform/reject" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "be2a9e4664452af0c8782ad66440b7bd",
    "reviewer": "claude-qa",
    "reason": "QA vector resubmit test"
  }'
```

**Result**: PASS
- `approval_state`: `rejected`

---

### TEST V-R3: Resubmit Dry Run (Vector)

**Purpose**: Verify `table_name` is found in cleanup plan — exercises Fix B (`result_data` fallback)

```bash
curl -X POST "${BASE_URL}/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "24073bca43a8d9b2628a000483a8ab4f",
    "dry_run": true
  }'
```

**Result**: PASS
- `cleanup_plan.tables_to_drop`: `["geo.qa_vector_resubmit_cutlines_draft"]` — **Fix B confirmed** (table_name resolved)
- `cleanup_plan.stac_items_to_delete`: `["qa-vector-resubmit-cutlines-draft"]` (B2C: no pgSTAC item exists, safe no-op)
- `cleanup_plan.tasks_to_delete`: 1

---

### TEST V-R4: Resubmit Execute (Vector)

**Purpose**: Exercises Fix C — actual `DROP TABLE` via `PostgreSQLRepository` + `sql.Identifier()`

```bash
curl -X POST "${BASE_URL}/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "24073bca43a8d9b2628a000483a8ab4f"
  }'
```

**Result**: PASS
- `original_job_id`: `1612617e126de1fa...`
- `new_job_id`: `3c3d0061374f1ae2...` (unique — Fix E confirmed)
- `cleanup_summary`:
  - `tables_dropped`: `["geo.qa_vector_resubmit_cutlines_draft"]` — **Fix C confirmed** (PostGIS table actually dropped, 0 errors)
  - `stac_items_deleted`: `["qa-vector-resubmit-cutlines-draft"]`
  - `tasks_deleted`: 1
  - `job_deleted`: true
  - `errors`: `[]`
- `monitor_url`: `/api/platform/status/24073bca43a8d9b2628a000483a8ab4f`

---

### TEST V-R5: New Vector Job Has `asset_id`

```bash
curl "${BASE_URL}/api/dbadmin/jobs/3c3d0061374f1ae29c1b139212473ef54c49af51093bdb144fae69ed4111f568"
```

**Result**: PASS
- `asset_id`: `be2a9e4664452af0c8782ad66440b7bd` — **Fix D confirmed** (previously was NULL)

---

### TEST V-R6: Resubmitted Vector Job Completes

```bash
curl "${BASE_URL}/api/platform/status/24073bca43a8d9b2628a000483a8ab4f"
```

**Result**: PASS
- `job_status`: `completed` (instantly)
- Vector table recreated with 1,401 rows

---

### All Fixes Verified

| Fix | Raster Test | Vector Test | Status |
|-----|-------------|-------------|--------|
| `.get()` → attribute access on `ApiRequest` | R4 dry_run succeeds | V-R3 dry_run succeeds | PASS |
| `monitor_url` uses `request_id` | R5 response | V-R4 response | PASS |
| Fix C: `PostgreSQLAdapter` → `PostgreSQLRepository` | N/A (no tables for raster) | **V-R4: table actually dropped** | PASS |
| Fix D: `asset_id` wired into new job | R5: `7a659986...` | **V-R5: `be2a9e46...`** | PASS |
| Fix B: `table_name` from `result_data` | N/A (no tables for raster) | **V-R3: table found in cleanup plan** | PASS |
| Fix E: Unique `job_id` hash | R5: new differs from original | V-R4: new differs from original | PASS |
| `BlobStorageAdapter` → `BlobRepository` | Code path only (`delete_blobs` default false) | Code path only | PASS (code) |

---

# Run 2 — v0.8.20.0 — STAC B2C Materialization (20 FEB 2026)

**Version**: 0.8.20.0
**Environment**: Fresh pgSTAC nuke + schema ensure. STAC items now materialized at approval (not processing). Revoke-first workflow enforced.
**Architectural changes**: pgSTAC writes deferred to approval (`_materialize_stac`), pgSTAC items deleted on revoke (`_delete_stac`), STAC dict cached in `cog_metadata.stac_item_json` during processing.

### Summary

| Test | Description | Result |
|------|-------------|--------|
| **STAC B2C LIFECYCLE** | | |
| B1 | Submit raster draft | PASS |
| B2 | Verify pgSTAC empty (deferred to approval) | PASS |
| B3 | Approve with version_id=v1 (materializes STAC) | PASS |
| B4 | Catalog lookup by versioned ID | PASS |
| B5 | Overwrite blocked on approved asset (409) | PASS |
| B6 | Revoke (deletes pgSTAC item) | PASS |
| B7 | Overwrite after revoke | PASS |
| B8 | Re-approve with v1 (re-materializes STAC) | PASS |
| **REVOKE-FIRST WORKFLOW** | | |
| B9 | New draft blocked while approved (DraftBlockedError 409) | PASS |
| B10 | Full revoke → resubmit → approve v2 cycle | PASS |

---

### Pre-Requisites

```bash
# pgSTAC nuke (clear all STAC items)
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"

# Schema ensure
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=ensure&confirm=yes"
```

---

### TEST B1: Submit Raster Draft (no version_id)

**Purpose**: Verify draft submission caches STAC dict but does NOT write to pgSTAC

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "stac-b2c-test",
    "resource_id": "dctest",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif"
  }'
```

**Result**: PASS
- `request_id`: captured
- `asset_id`: `b711f9ff11780fa058bf7b2032530f86`
- Job completed successfully
- `cog_metadata.stac_item_json`: populated (cached STAC dict)
- Asset state: `pending_review`, `uncleared`, no version_id

---

### TEST B2: Verify pgSTAC Empty (Deferred to Approval)

**Purpose**: Confirm no premature STAC item created during processing

```bash
# Check pgSTAC for any items in the collection
curl "${BASE_URL}/api/platform/catalog/item/stac-b2c-test/stac-b2c-test-dctest-draft"
```

**Result**: PASS
- HTTP 404 — no STAC item exists
- STAC dict is cached in `cog_metadata.stac_item_json` only
- pgSTAC is empty (as designed)

---

### TEST B3: Approve with version_id=v1 (Materializes STAC)

**Purpose**: Verify `assign_version()` renames IDs then `_materialize_stac()` creates pgSTAC item

```bash
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "robert@example.com",
    "clearance_level": "ouo",
    "version_id": "v1"
  }'
```

**Result**: PASS
- `approval_state`: `approved`
- `clearance_state`: `ouo`
- `stac_item_id`: `stac-b2c-test-dctest-v1` (renamed from draft)
- pgSTAC item created with versioned ID and approval properties (`geoetl:published=True`)

---

### TEST B4: Catalog Lookup by Versioned ID

**Purpose**: Verify the pgSTAC item is findable by the versioned ID (no more rename gap)

```bash
curl "${BASE_URL}/api/platform/catalog/item/stac-b2c-test/stac-b2c-test-dctest-v1"
```

**Result**: PASS
- HTTP 200 — STAC item found with correct versioned ID
- This was the E/F catalog test failure from Run 1 — now fixed by materializing at approval time

---

### TEST B5: Overwrite Blocked on Approved Asset (409)

**Purpose**: Verify overwrite is blocked while asset is approved

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "stac-b2c-test",
    "resource_id": "dctest",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "processing_options": {"overwrite": true}
  }'
```

**Result**: PASS (correctly rejected)
- HTTP 409
- `error_type`: `OverwriteBlockedError`
- Message: "Cannot overwrite approved asset. Version 'v1' has been approved. Revoke approval first."

---

### TEST B6: Revoke (Deletes pgSTAC Item)

**Purpose**: Verify revoke deletes the pgSTAC item (approved = visible, not approved = invisible)

```bash
curl -X POST "${BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "revoker": "robert@example.com",
    "reason": "B2C materialization test — revoke cycle"
  }'
```

**Result**: PASS
- `approval_state`: `revoked`
- pgSTAC item `stac-b2c-test-dctest-v1` deleted (confirmed: 404 on catalog lookup)
- `platform_refs.version_id` cleared
- `version_ordinal`, `lineage_id`, `is_latest` all reset

---

### TEST B7: Overwrite After Revoke

**Purpose**: After revoking, overwrite should be allowed

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "stac-b2c-test",
    "resource_id": "dctest",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "processing_options": {"overwrite": true}
  }'
```

**Result**: PASS
- New job created and processed
- Asset `stac_item_id` reset to draft placeholder
- `platform_refs`, `stac_collection_id` reset (upsert overwrite identity reset)
- `cog_metadata.stac_item_json` re-cached with fresh STAC dict

---

### TEST B8: Re-Approve with v1 (Re-materializes STAC)

**Purpose**: Verify the full revoke → overwrite → re-approve cycle materializes STAC correctly

```bash
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "robert@example.com",
    "clearance_level": "ouo",
    "version_id": "v1"
  }'
```

**Result**: PASS
- `approval_state`: `approved`
- `stac_item_id`: `stac-b2c-test-dctest-v1`
- pgSTAC item recreated with correct versioned ID
- `version_ordinal=1`, `is_latest=True`

---

### TEST B9: New Draft Blocked While Approved (DraftBlockedError)

**Purpose**: Verify revoke-first workflow — cannot submit new draft while approved version exists

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "stac-b2c-test",
    "resource_id": "dctest",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif"
  }'
```

**Result**: PASS (correctly rejected)
- HTTP 409
- `error_type`: `DraftBlockedError`
- Message: "Cannot submit new draft while version 'v1' is approved. Revoke the approved version first (POST /api/platform/revoke) then resubmit."

---

### TEST B10: Full Revoke → Resubmit → Approve v2 Cycle

**Purpose**: Complete lifecycle — revoke v1, resubmit, approve as v2. Verify only v2 in pgSTAC.

#### B10a: Revoke v1

```bash
curl -X POST "${BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "revoker": "robert@example.com",
    "reason": "Upgrading to v2"
  }'
```

**Result**: PASS — pgSTAC item `stac-b2c-test-dctest-v1` deleted

#### B10b: Resubmit After Revoke

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "stac-b2c-test",
    "resource_id": "dctest",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "processing_options": {"overwrite": true}
  }'
```

**Result**: PASS — Job processed, STAC dict re-cached

#### B10c: Approve with v2

```bash
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "{REQUEST_ID}",
    "reviewer": "robert@example.com",
    "clearance_level": "ouo",
    "version_id": "v2"
  }'
```

**Result**: PASS
- `stac_item_id`: `stac-b2c-test-dctest-v2`
- `version_id`: `v2`
- `approval_state`: `approved`

#### B10d: pgSTAC Verification

```bash
# v2 exists
curl "${BASE_URL}/api/platform/catalog/item/stac-b2c-test/stac-b2c-test-dctest-v2"
# → HTTP 200

# v1 gone (revoked)
curl "${BASE_URL}/api/platform/catalog/item/stac-b2c-test/stac-b2c-test-dctest-v1"
# → HTTP 404

# No draft items
curl "${BASE_URL}/api/platform/catalog/item/stac-b2c-test/stac-b2c-test-dctest-draft"
# → HTTP 404
```

**Result**: PASS
- Only `stac-b2c-test-dctest-v2` exists in pgSTAC
- No v1 orphans, no draft-named items
- B2C catalog shows only approved data

---

### Architecture Guarantees Validated

| Guarantee | Test | Verified |
|-----------|------|----------|
| Processing does NOT write to pgSTAC | B2 | PASS — pgSTAC empty after processing |
| Approval materializes STAC with versioned ID | B3, B8, B10c | PASS — correct ID, approval properties |
| Catalog lookup works with versioned ID | B4 | PASS — no more rename gap (Run 1 bug E/F) |
| Revoke deletes pgSTAC item | B6, B10a | PASS — 404 after revoke |
| Overwrite resets identity fields | B7 | PASS — stac_item_id, platform_refs, stac_collection_id reset |
| No coexisting drafts (revoke-first) | B9 | PASS — DraftBlockedError 409 |
| Full v1→v2 upgrade cycle | B10 | PASS — only v2 visible in catalog |

---

### Bugs Fixed Before/During Run 2

| Bug | Discovery | Fix | Commit |
|-----|-----------|-----|--------|
| pgSTAC item rename gap (Run 1, E/F) | Run 1 TEST E | STAC materialized at approval with correct versioned ID (architectural fix) | v0.8.20.0 |
| Upsert overwrite doesn't reset identity fields | B10 (first attempt) | Added `platform_refs`, `stac_item_id`, `stac_collection_id` to overwrite SET clause in `sql_generator.py` | `63dbc94` |
| Orphaned pgSTAC item on revoke after overwrite | B10 (first attempt) | Same fix — stale `stac_item_id` caused `_delete_stac()` to target wrong item | `63dbc94` |
| Coexisting drafts impossible (asset_id collision) | B9 design | Replaced `__draft_N` with `DraftBlockedError` — revoke-first workflow | `63dbc94` |
| Revocation fields not cleared on overwrite | B7 investigation | Added `revoked_at=NULL`, `revoked_by=NULL`, `revocation_reason=NULL` to overwrite SET | `63dbc94` |

---

# Run 1 — v0.8.19.8 — Asset Lifecycle (19 FEB 2026)

**Version**: 0.8.19.8
**Environment**: Fresh schema rebuild (nullable version_ordinal, max-ordinal lineage, revoke clears version info)

### Summary

| Test | Description | Result |
|------|-------------|--------|
| **RASTER** | | |
| 1 | Draft raster submit (no version_id) | PASS |
| 2 | Approve draft with version_id=v1 | PASS |
| 3 | Overwrite blocked on approved asset | PASS (409) |
| 4 | Revoke approval (clears version info) | PASS |
| 5 | Overwrite after revoke | PASS |
| 6 | Re-approve with version_id=v1 | PASS |
| 7 | Submit v2 with previous_version_id=v1 (lineage chain) | PASS |
| **VECTOR** | | |
| V1 | Draft vector submit (no version_id) | PASS |
| V2 | Approve vector via UI embed | PASS |
| V3 | Overwrite blocked on approved vector | PASS (409) |
| V4 | Revoke vector approval (clears version info) | PASS |
| V5 | Overwrite vector after revoke | PASS |
| V6 | Re-approve vector with version_id=v1 | PASS |
| V7 | Submit vector v2 with previous_version_id=v1 | PASS |
| **CATALOG** | | |
| D | List items for dataset (QA 2.8) | PASS (QA used wrong URL) |
| E | Get STAC Item (QA 2.10) | PARTIAL — draft ID works, versioned ID 404 (pgSTAC not renamed) |
| F | Get Asset URLs / TiTiler (QA 2.11) | PARTIAL — same root cause as E |

**Lineage verified after all tests:**
- v1: `ordinal=1`, `is_latest=False`, `previous_asset_id=None`, `approved`
- v2: `ordinal=2`, `is_latest=True`, `previous_asset_id=794bf63f...` (v1), `pending_review`

**Note**: Tests E and F failures (pgSTAC rename gap) were resolved in Run 2 by the STAC B2C materialization architecture — pgSTAC items are now created at approval time with the correct versioned ID.

---

### Pre-Requisites

```bash
# Schema rebuild (fresh slate)
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"
# Result: 21 app tables, 22 pgSTAC tables, all clean
```

---

### TEST 1: Draft Raster Submit (no version_id)

**Purpose**: Verify draft submission creates asset with no lineage wiring

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "approvemedaddy0300103212112",
    "resource_id": "v8-testing",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/raster_tiles/0300103212112.tif",
    "processing_options": {
      "processing_mode": "docker"
    }
  }'
```

**Result**: PASS
- `request_id`: `823ff40a73f8f29b3ab15e90d0cb402e`
- `job_id`: `e57dd19ec160da0f2d9b3d766a1d5771cf0f20460f7d54223bd5bb7901a9b5d7`
- `asset_id`: `794bf63fa2d3653f3cc28de87ba7fca3`
- Job completed in ~75s
- 4-band NIR raster, EPSG:4326, 369MB COG, deflate compression
- STAC item: `approvemedaddy0300103212112-v8-testing-draft`
- Asset state: `pending_review`, `uncleared`, `version_ordinal=NULL`, `lineage_id=NULL`

---

### TEST 2: Approve Draft with version_id=v1

**Purpose**: Verify assign_version() wires lineage at approval time

```bash
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "823ff40a73f8f29b3ab15e90d0cb402e",
    "reviewer": "robert@example.com",
    "clearance_level": "ouo",
    "version_id": "v1"
  }'
```

**Result**: PASS
- `"approval_state": "approved"`
- `"clearance_state": "ouo"`
- `"stac_item_id": "approvemedaddy0300103212112-v8-testing-v1"` (rebuilt from `-draft` to `-v1`)
- Asset state after: `version_ordinal=1`, `lineage_id=794bf63f...`, `is_latest=True`, `previous_asset_id=None`

---

### TEST 3: Overwrite Approved Asset (should be rejected)

**Purpose**: Verify overwrite is blocked when asset is approved — must revoke first

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "approvemedaddy0300103212112",
    "resource_id": "v8-testing",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/raster_tiles/0300103212112.tif",
    "processing_options": {
      "processing_mode": "docker",
      "overwrite": true
    }
  }'
```

**Result**: PASS (correctly rejected)
- HTTP 409
- `"error": "Cannot overwrite approved asset. Version 'v1' has been approved. Revoke approval first (POST /api/platform/revoke) or submit with a new version_id."`
- `"error_type": "OverwriteBlockedError"`

---

### TEST 4: Revoke Approval

**Purpose**: Verify revoke clears version info (asset returns to draft state)

```bash
curl -X POST "${BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "823ff40a73f8f29b3ab15e90d0cb402e",
    "revoker": "robert@example.com",
    "reason": "QA testing — overwrite resubmit test"
  }'
```

**Result**: PASS
- `"approval_state": "revoked"`
- `"warning": "Approved asset has been revoked and version info cleared. Re-approval will require version assignment."`
- Asset state after: `version_ordinal=NULL`, `lineage_id=NULL`, `is_latest=False`, `version_id` removed from `platform_refs`

---

### TEST 5: Overwrite After Revoke (should succeed)

**Purpose**: After revoking, overwrite=true should be allowed (asset is now draft again)

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "approvemedaddy0300103212112",
    "resource_id": "v8-testing",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/raster_tiles/0300103212112.tif",
    "processing_options": {
      "processing_mode": "docker",
      "overwrite": true
    }
  }'
```

**Result**: PASS
- Same `request_id`: `823ff40a73f8f29b3ab15e90d0cb402e`
- New `job_id`: `7e875af5fffb9a43113658a1e8483a93de725a5102934c9ed1c58b00ae5414c2`
- Asset reused, new job created for reprocessing
- Job completed in ~60s

---

### TEST 6: Re-Approve with version_id=v1 (after revoke + overwrite)

**Purpose**: Verify the full revoke → overwrite → re-approve cycle wires lineage correctly

```bash
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "823ff40a73f8f29b3ab15e90d0cb402e",
    "reviewer": "robert@example.com",
    "clearance_level": "ouo",
    "version_id": "v1"
  }'
```

**Result**: PASS
- `"approval_state": "approved"`
- `"clearance_state": "ouo"`
- `"stac_item_id": "approvemedaddy0300103212112-v8-testing-v1"`
- Asset state after: `version_ordinal=1`, `lineage_id=794bf63f...`, `is_latest=True`, `previous_asset_id=None`

---

### TEST 7: Submit v2 with Version Lineage (previous_version_id=v1)

**Purpose**: Verify version chaining — v2 references approved v1 as predecessor

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "approvemedaddy0300103212112",
    "resource_id": "v8-testing",
    "version_id": "v2",
    "previous_version_id": "v1",
    "data_type": "raster",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/raster_tiles/0300103212112.tif",
    "processing_options": {
      "processing_mode": "docker"
    }
  }'
```

**Result**: PASS
- New `request_id`: `5c36d71e1a69aced3390af72f486320c`
- New `job_id`: `fbf210cd45010a4715d3a0ffb0e8a26b54cb3dd6d10cc277256fd1eefafe86ee`
- Job completed in ~60s
- New asset created for v2 (separate from v1 asset)

**Lineage state verified:**

| Version | ordinal | is_latest | previous_asset_id | approval_state |
|---------|---------|-----------|-------------------|----------------|
| v1 | 1 | False | None | approved |
| v2 | 2 | True | `794bf63fa2d3653f3cc28de87ba7fca3` (v1) | pending_review |

---

## VECTOR TESTS (Run 1)

### TEST V1: Draft Vector Submit (no version_id)

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "versionthefuckoutofcutlines",
    "resource_id": "v8-testing",
    "data_type": "vector",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg",
    "processing_options": {"processing_mode": "docker"}
  }'
```

**Result**: PASS
- `request_id`: `d965c0d11471ab5d6fdc9a876413c872`
- `asset_id`: `5eb6023c57b8bdbdb27fe80e77b9cda1`
- Job completed

---

### TEST V2: Approve Vector via UI Embed

**Embed URL**:
```
${BASE_URL}/api/interface/vector-viewer?collection=versionthefuckoutofcutlines_v8_testing_draft&asset_id=5eb6023c57b8bdbdb27fe80e77b9cda1&embed=true
```

**Result**: PASS
- `approval_state`: `approved`, `clearance_state`: `ouo`

---

### TEST V3: Overwrite Approved Vector (should be rejected)

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "versionthefuckoutofcutlines",
    "resource_id": "v8-testing",
    "data_type": "vector",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg",
    "processing_options": {"processing_mode": "docker", "overwrite": true}
  }'
```

**Result**: PASS (correctly rejected)
- HTTP 409
- `"error_type": "OverwriteBlockedError"`

---

### TEST V4: Revoke Vector Approval

```bash
curl -X POST "${BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "d965c0d11471ab5d6fdc9a876413c872",
    "revoker": "robert@example.com",
    "reason": "QA testing — vector overwrite resubmit test"
  }'
```

**Result**: PASS
- `"approval_state": "revoked"`

---

### TEST V5: Overwrite Vector After Revoke

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "versionthefuckoutofcutlines",
    "resource_id": "v8-testing",
    "data_type": "vector",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg",
    "processing_options": {"processing_mode": "docker", "overwrite": true}
  }'
```

**Result**: PASS
- Same `request_id`: `d965c0d11471ab5d6fdc9a876413c872`
- New job created, completed instantly

---

### TEST V6: Re-Approve Vector with version_id=v1

```bash
curl -X POST "${BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "d965c0d11471ab5d6fdc9a876413c872",
    "reviewer": "robert@example.com",
    "clearance_level": "ouo",
    "version_id": "v1"
  }'
```

**Result**: PASS
- `"approval_state": "approved"`
- `"stac_item_id": "versionthefuckoutofcutlines-v8-testing-v1"`
- Asset state: `version_ordinal=1`, `is_latest=True`

---

### TEST V7: Submit Vector v2 with Lineage (previous_version_id=v1)

```bash
curl -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "versionthefuckoutofcutlines",
    "resource_id": "v8-testing",
    "version_id": "v2",
    "previous_version_id": "v1",
    "data_type": "vector",
    "container_name": "rmhazuregeobronze",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg",
    "processing_options": {"processing_mode": "docker"}
  }'
```

**Result**: PASS
- New `request_id`: `cb4019925c262c2a79d858f6ab7e2100`
- Job completed instantly

**Vector lineage verified:**

| Version | ordinal | is_latest | previous_asset_id | approval_state |
|---------|---------|-----------|-------------------|----------------|
| v1 | 1 | False | None | approved |
| v2 | 2 | True | `5eb6023c57b8bdbdb27fe80e77b9cda1` (v1) | pending_review |

---

## CATALOG ENDPOINT RETESTS (Run 1 — ITSDA Items D, E, F)

**Context**: QA reported 404s on catalog endpoints (2.8, 2.10, 2.11). Retested with fresh approved assets.

### TEST D: List Items for Dataset (QA ref 2.8)

**QA reported URL**: `/api/platform/catalog/assets` — **this route does not exist**.
**Correct route**: `/api/platform/catalog/dataset/{dataset_id}`

```bash
curl "${BASE_URL}/api/platform/catalog/dataset/approvemedaddy0300103212112"
curl "${BASE_URL}/api/platform/catalog/dataset/versionthefuckoutofcutlines"
```

**Result**: PASS — QA team used wrong URL

---

### TEST E: Get STAC Item (QA ref 2.10)

```bash
# Versioned ID → 404 (pgSTAC item not renamed at approval time)
curl "${BASE_URL}/api/platform/catalog/item/approvemedaddy0300103212112/approvemedaddy0300103212112-v8-testing-v1"

# Draft ID → 200 (pgSTAC still has original draft name)
curl "${BASE_URL}/api/platform/catalog/item/approvemedaddy0300103212112/approvemedaddy0300103212112-v8-testing-draft"
```

**Result**: PARTIAL — pgSTAC item ID rename gap. **Fixed in Run 2** by STAC B2C materialization (pgSTAC items now created at approval with correct versioned ID).

---

### TEST F: Get Asset URLs / TiTiler (QA ref 2.11)

**Result**: PARTIAL — same root cause as TEST E. **Fixed in Run 2**.

---

## Bugs Found & Fixed During Run 1

| Bug | Discovery | Fix | Version |
|-----|-----------|-----|---------|
| `lineage_id[:16]` on None crashes draft submit | TEST 1 (first run, v0.8.19.6) | None-safety guard in log line | 0.8.19.7 |
| `validation_result.suggested_params` on None crashes draft submit | TEST 1 (first run, v0.8.19.6) | None-check before access | 0.8.19.7 |
| `version_ordinal NOT NULL` blocks revoke (can't set NULL) | TEST 4 (second run, v0.8.19.8) | Changed `version_ordinal: int` → `Optional[int]` in asset model, removed `COALESCE(..., 1)` from upsert | 0.8.19.8 |
| `is_latest` flag drift after revoke → overwrite → re-approve | TEST 6 (second run) | `get_latest_in_lineage` now uses `ORDER BY version_ordinal DESC` instead of `WHERE is_latest = TRUE` | 0.8.19.8 |
| Revoke doesn't clear version info — asset stays "versioned" | TEST 7 (first attempt failed) | `update_revocation` now clears `version_ordinal`, `lineage_id`, `is_latest`, removes `version_id` from `platform_refs` | 0.8.19.8 |

---

## Files Modified Across All Runs

| File | Run 1 Changes | Run 2 Changes | Run 3 Changes |
|------|---------------|---------------|---------------|
| `triggers/platform/submit.py` | None-safety for draft path | DraftBlockedError (revoke-first), dry_run returns 400 | — |
| `core/models/asset.py` | `version_ordinal` → `Optional[int]` | — | — |
| `core/schema/sql_generator.py` | Removed `COALESCE(p_version_ordinal, 1)` | Upsert overwrite identity reset + revocation field clearing | — |
| `infrastructure/asset_repository.py` | `get_latest_in_lineage` max-ordinal, `update_revocation` clears version info | — | — |
| `services/asset_approval_service.py` | Revoke audit log | `_materialize_stac`, `_delete_stac` (replace pgSTAC insert/update) | — |
| `services/handler_process_raster_complete.py` | — | Cache STAC dict, remove pgSTAC inserts | — |
| `services/stac_catalog.py` | — | Remove pgSTAC inserts, cache instead | — |
| `infrastructure/raster_metadata_repository.py` | — | `stac_item_json` column, upsert + read method | — |
| `triggers/trigger_approvals.py` | — | 3-tier asset fallback | — |
| `triggers/platform/resubmit.py` | — | Approval guard, asset update, platform_request update | `.get()` → attribute access, `monitor_url` fix, `asset_id` pass-through |
| `triggers/jobs/resubmit.py` | — | Approval guard, asset update | Fix C (`_drop_table`), Fix B (`result_data` lookup), Fix D (`asset_id`), Fix E (unique hash), Fix A (B2C comments), `_delete_blob` fix |
| `triggers/jobs/delete.py` | — | — | Same `_drop_table` and `_delete_blob` fixes as resubmit.py |
| `triggers/platform/platform_bp.py` | — | — | Docstring `monitor_url` example fix |
| `infrastructure/platform.py` | — | `update_job_id()` method | — |
| `triggers/platform/unpublish.py` | — | dry_run gated before job creation | — |
