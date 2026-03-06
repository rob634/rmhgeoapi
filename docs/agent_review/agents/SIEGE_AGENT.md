# Pipeline 4: SIEGE (Sequential Smoke Test)

**Purpose**: Fast sequential verification that the live API's core workflows function correctly after deployment. No information asymmetry — this is a linear sweep for speed and simplicity.

**Best for**: Post-deployment smoke test, quick confidence check ("did that deploy break anything?").

---

## Endpoint Access Rules

Agents test through the **same API surface** that B2B consumers use (`/api/platform/*`). This ensures tests reflect real-world access patterns.

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Action** | `/api/platform/*` | Cartographer (probes), Lancer | Submit, approve, reject, unpublish, query status, browse catalog. The B2B surface. |
| **Verification** | `/api/dbadmin/*`, `/api/storage/*`, `/api/health` | Cartographer (health only), Auditor | Read-only state auditing. Confirm DB/STAC/blob state matches expectations. |
| **Setup** | `/api/dbadmin/maintenance`, `/api/stac/nuke` | Sentinel (prerequisites only) | Schema rebuild and STAC nuke BEFORE agents run. Never during tests. |
| **Synthesis** | None (reads other agents' outputs) | Scribe | Produces final report from other agents' data. No HTTP calls. |

**Hard rule**: Lancer MUST only use `/api/platform/*` endpoints. Auditor may use admin endpoints for deep verification. If a workflow needs an admin endpoint to function, flag it as a finding — a missing B2B capability.

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Sentinel | Define campaign (test data, endpoints, bronze container) | Claude (no subagent) | V0.9_TEST.md, API docs |
| Cartographer | Probe every endpoint, map API surface | Task (sequential) | Campaign Brief |
| Lancer | Execute canonical lifecycle sequences | Task (sequential) | Campaign Brief + test data |
| Auditor | Query DB/STAC/status, compare actual vs expected | Task (sequential) | Lancer's State Checkpoint Map |
| Scribe | Synthesize all outputs into final report | Task (sequential) | All previous outputs |

**Maximum parallel agents**: 0 (all sequential)

---

## Flow

```
Target: BASE_URL (Azure endpoint)
    |
    Sentinel (Claude — no subagent)
        Reads V0.9_TEST.md, defines test data with sg- prefix
        Outputs: Campaign Brief
    |
    Cartographer (Task)                          [sequential]
        Probes every known endpoint
        OUTPUT: Endpoint Map (URL → HTTP code → response schema → latency)
    |
    Lancer (Task)                                [sequential]
        Executes canonical lifecycle sequences
        OUTPUT: Execution Log + State Checkpoint Map
    |
    Auditor (Task)                               [sequential]
        Queries DB, STAC, status endpoints
        Compares actual vs expected state
        OUTPUT: Audit Report (matches, divergences, orphans)
    |
    Scribe (Task)                                [sequential]
        Synthesizes all outputs
        OUTPUT: Final SIEGE Report
```

---

## Prerequisites

```bash
BASE_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

# Schema rebuild (fresh slate)
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"

# STAC nuke
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"

# Health check
curl -sf "${BASE_URL}/api/health"
```

---

## Campaign Config

All pipelines share a config file: `docs/agent_review/siege_config.json`

The config contains:
- **`valid_files`**: Files that MUST exist in bronze storage — used by Pathfinder/Blue/Lancer
- **`invalid_files`**: Deliberately bad inputs — used by Saboteur/Red/Provocateur
- **`approval_fixtures`**: Pre-built payloads for approve/reject testing
- **`discovery`**: Endpoint templates for verifying files exist before testing
- **`prerequisites`**: Setup commands (rebuild, nuke, health check)

Sentinel MUST verify valid files exist before launching by calling the discovery endpoint:
```bash
curl "${BASE_URL}/api/storage/rmhazuregeobronze/blobs?zone=bronze&limit=50"
```

---

## Step 1: Play Sentinel (No Subagent)

Claude plays Sentinel directly. Sentinel's job:

1. Read `siege_config.json` for test data and `V0.9_TEST.md` sections A–I for canonical test sequences.
2. Verify valid files exist via discovery endpoint.
3. Define test data using `sg-` prefix:
   - Raster: `dataset_id=sg-raster-test`, `resource_id=dctest`, `file_name=dctest.tif`
   - Vector: `dataset_id=sg-vector-test`, `resource_id=cutlines`, `file_name=cutlines.gpkg`
   - NetCDF: `dataset_id=sg-netcdf-test`, `resource_id=spei-ssp370`, `file_name=good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc`, `container_name=wargames`, `data_type=zarr`
3. Identify the bronze container name from environment context.
4. Output the Campaign Brief:
   - BASE_URL
   - Test data table
   - Bronze container
   - Full endpoint list for Cartographer
   - Lifecycle sequences for Lancer

---

## Step 2: Dispatch Cartographer

Cartographer probes every known endpoint with a minimal request to verify liveness.

### Cartographer Probe Table

**Platform API surface (B2B — primary focus)**:

| Endpoint | Method | Probe | Expected |
|----------|--------|-------|----------|
| `/api/platform/health` | GET | No params | 200 |
| `/api/platform/submit` | OPTIONS or GET | Check if live | 405 or method listing |
| `/api/platform/status` | GET | No params, list mode | 200 |
| `/api/platform/status/{random-uuid}` | GET | Random UUID | 404 or empty |
| `/api/platform/approve` | OPTIONS or GET | Check if live | 405 or method listing |
| `/api/platform/reject` | OPTIONS or GET | Check if live | 405 or method listing |
| `/api/platform/unpublish` | OPTIONS or GET | Check if live | 405 or method listing |
| `/api/platform/resubmit` | OPTIONS or GET | Check if live | 405 or method listing |
| `/api/platform/approvals` | GET | No params | 200 |
| `/api/platform/catalog/lookup` | GET | Missing params | 400 or empty |
| `/api/platform/failures` | GET | No params | 200 |
| `/api/platforms` | GET | No params | 200 |

**Verification endpoints (admin — health check only)**:

| Endpoint | Method | Probe | Expected |
|----------|--------|-------|----------|
| `/api/health` | GET | No params | 200 |
| `/api/dbadmin/diagnostics?type=stats` | GET | No params | 200 |
| `/api/dbadmin/jobs` | GET | `?limit=1` | 200 |

### Cartographer Output Format

```markdown
## Endpoint Map

| # | Endpoint | Method | HTTP Code | Latency (ms) | Response Shape | Notes |
|---|----------|--------|-----------|-------------|----------------|-------|
...

## Health Assessment
{HEALTHY | DEGRADED | DOWN}
{Any endpoints that returned unexpected codes}
```

---

## Step 3: Dispatch Lancer

Lancer executes canonical lifecycle sequences and records state checkpoints.

### Lifecycle Sequences

**Sequence 1: Raster Lifecycle**
1. POST `/api/platform/submit` (raster) → capture request_id, job_id
2. GET `/api/platform/status/{request_id}` (poll until completed) → capture release_id, asset_id
3. POST `/api/platform/approve` (version_id="v1") → verify STAC materialized
4. GET `/api/platform/catalog/item/{collection}/{item_id}` → verify exists
5. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `titiler_urls` present with keys [xyz, tilejson, preview, info, statistics]. Verify URLs contain TiTiler base hostname. → **CHECKPOINT R1-URLS**
6. **CHECKPOINT R1**: Record all IDs and expected DB/STAC state

**Sequence 2: Vector Lifecycle**
1. POST `/api/platform/submit` (vector) → capture IDs
2. Poll until completed → capture release_id
3. POST `/api/platform/approve` → verify OGC Features
4. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `endpoints.features` present, `tiles.tilejson` present. Verify URLs contain TiPG base path. → **CHECKPOINT V1-URLS**
5. **CHECKPOINT V1**: Record all IDs

**Sequence 3: Multi-Version**
1. POST `/api/platform/submit` (resubmit raster, same dataset_id) → capture v2 IDs
2. Poll → verify ordinal=2
3. POST `/api/platform/approve` (version_id="v2") → verify coexistence with v1
4. **CHECKPOINT MV1**: Both v1 and v2 state

**Sequence 4: Unpublish**
1. POST `/api/platform/unpublish` (v2) → poll until complete
2. **CHECKPOINT U1**: v2 removed, v1 preserved

**Sequence 5: NetCDF / VirtualiZarr Lifecycle**
1. POST `/api/platform/submit` with `data_type=zarr`, NetCDF file from wargames container → capture request_id, job_id
2. Poll until completed (VirtualiZarr pipeline: scan → copy → validate → combine → register)
3. POST `/api/platform/approve` (version_id="v1") → verify STAC materialized (zarr items go in STAC)
4. GET `/api/platform/catalog/dataset/{dataset_id}` → verify catalog entry exists
5. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `xarray_urls` present with keys [variables, tiles, tilejson, preview, info, point]. Verify URLs contain TiTiler base hostname and `/xarray/` path. → **CHECKPOINT Z1-URLS**
6. **CHECKPOINT Z1**: Record all IDs, verify job_type=virtualzarr, STAC item present

Note: NetCDF (.nc) routes to the VirtualiZarr pipeline, NOT the raster pipeline.
Use `data_type_override: "zarr"` from siege_config.json. Submit body must include
`"data_type": "zarr"`. Processing may take longer than raster (5-stage pipeline).

**Sequence 6: Native Zarr Lifecycle**
1. POST `/api/platform/submit` with `data_type=zarr`, native `.zarr` store (`zarr_cmip6_tasmax` from config) → capture request_id, job_id
2. Poll until completed → verify job completes (different code path from VirtualiZarr .nc)
3. POST `/api/platform/approve` (version_id="v1") → verify STAC materialized
4. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `xarray_urls` present → **CHECKPOINT NZ1-URLS**
5. **CHECKPOINT NZ1**: Record all IDs, verify direct zarr path (NOT virtualzarr pipeline)

**Sequence 7: Rejection Path**
1. POST `/api/platform/submit` (raster, new dataset_id `sg-reject-test`) → capture request_id
2. Poll until completed → capture release_id
3. POST `/api/platform/reject` with `reviewer`, `reason` → expect 200, approval_state=rejected
4. GET `/api/platform/status/{request_id}` → verify approval_state=rejected, reason preserved
5. **CHECKPOINT REJ1**: Release rejected, reason in audit trail

**Sequence 8: Reject → Resubmit → Approve**
1. POST `/api/platform/submit` (same dataset_id + resource_id as Seq 7, `"processing_options": {"overwrite": true}`) → expect new job_id created
   **CRITICAL**: `overwrite` MUST be inside `processing_options`, NOT at the top level. Top-level `overwrite` is silently ignored by Pydantic.
2. Poll until completed → verify revision counter incremented (revision=2), approval_state=pending_review
3. POST `/api/platform/approve` (version_id="v1") → expect success
4. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify catalog entry
5. **CHECKPOINT REJ2**: Recovered from rejection, release approved after resubmit

**Sequence 9: Revocation + is_latest Cascade**
1. Use raster from Seq 1 (has v1 approved + v1 preserved after Seq 4 unpublished v2)
2. POST `/api/platform/submit` (same dataset_id as Seq 1, new file) → poll → capture v3 IDs
3. POST `/api/platform/approve` (version_id="v3") → v3 is now is_latest=true
4. POST `/api/platform/revoke` with `reviewer`, `reason` (revoke v3) → expect 200, approval_state=revoked
5. GET `/api/platform/status/{request_id}` → verify v3 revoked, v1 promoted back to is_latest=true
6. **CHECKPOINT REV1**: v3 revoked, v1 is_latest restored, STAC item for v3 deleted

**Sequence 10: Overwrite Draft**
1. POST `/api/platform/submit` (new dataset_id `sg-overwrite-test`) → capture request_id_1
2. POST `/api/platform/submit` (same dataset_id + resource_id, NO overwrite) → expect idempotent response (same request_id returned) or 409 if job exists
3. POST `/api/platform/submit` (same dataset_id + resource_id, `"processing_options": {"overwrite": true}`) → expect same request_id, revision counter incremented
   **CRITICAL**: `overwrite` MUST be inside `processing_options`, NOT at the top level.
4. Poll new request until completed
5. **CHECKPOINT OW1**: Old draft replaced, new release active

### Invalid Transition Sequences

These sequences verify that the state machine rejects illegal transitions with correct error codes. Each step expects a specific HTTP error — a 200 or 500 is a **FAIL**.

**Sequence 11: Invalid State Transitions**

Uses releases created in previous sequences. Each step is independent.

| # | Action | Target State | Expected | Checkpoint |
|---|--------|-------------|----------|------------|
| 11a | POST `/api/platform/approve` (release from Seq 1, already approved) | approved→approved | HTTP 400 `"expected 'pending_review'"` | IST-1 |
| 11b | POST `/api/platform/reject` (release from Seq 1, already approved) | approved→rejected | HTTP 400 `"expected 'pending_review'"` | IST-2 |
| 11c | POST `/api/platform/approve` (release from Seq 7, rejected, before resubmit) | rejected→approved | HTTP 400 `"expected 'pending_review'"` | IST-3 |
| 11d | POST `/api/platform/reject` (release from Seq 7, already rejected) | rejected→rejected | HTTP 400 `"expected 'pending_review'"` | IST-4 |
| 11e | POST `/api/platform/approve` (v3 from Seq 9, revoked) | revoked→approved | HTTP 400 `"expected 'pending_review'"` | IST-5 |
| 11f | POST `/api/platform/revoke` (v3 from Seq 9, already revoked) | revoked→revoked | HTTP 400 `"expected 'approved'"` | IST-6 |
| 11g | POST `/api/platform/revoke` (pending_review release) | pending→revoked | HTTP 400 `"expected 'approved'"` | IST-7 |
| 11h | POST `/api/platform/approve` on pending_review release with processing_status != completed | pending+processing | HTTP 400 (processing guard) | IST-8 |
| 11i | POST `/api/platform/submit` with overwrite on APPROVED release | approved+overwrite | New version created (not overwrite) — verify ordinal incremented | IST-9 |

**CHECKPOINT IST**: All 9 checks returned expected results (400 for 11a-11h, new version for 11i — not 200 or 500 where errors expected). Record each HTTP code and error message.

**Sequence 12: Missing Required Fields**

Fresh requests — no prior state needed. Each step expects HTTP 400.

| # | Action | Missing Field | Expected |
|---|--------|---------------|----------|
| 12a | POST `/api/platform/submit` with empty body `{}` | all fields | HTTP 400 |
| 12b | POST `/api/platform/submit` without `dataset_id` | dataset_id | HTTP 400 |
| 12c | POST `/api/platform/submit` without `file_name` and without `source_url` | file_name | HTTP 400 |
| 12d | POST `/api/platform/approve` without `reviewer` | reviewer | HTTP 400 |
| 12e | POST `/api/platform/approve` without `clearance_level` | clearance_level | HTTP 400 |
| 12f | POST `/api/platform/approve` without any release identifier | release lookup | HTTP 400 |
| 12g | POST `/api/platform/reject` without `reason` | reason | HTTP 400 |
| 12h | POST `/api/platform/reject` with `reason=""` (empty string) | reason (blank) | HTTP 400 |
| 12i | POST `/api/platform/revoke` without `reason` | reason | HTTP 400 |
| 12j | POST `/api/platform/approve` for nonexistent release_id (UUID zeros) | valid structure, no target | HTTP 404 |
| 12k | POST `/api/platform/submit` with valid raster body + unknown field `"bogus_field": "test"` | unknown top-level field (ERH-1 extra='forbid') | HTTP 400 |
| 12l | POST `/api/platform/submit` with valid body + `"processing_options": {"overwrite": true, "fake_option": 99}` | unknown processing_options field (ERH-1 extra='forbid') | HTTP 400 |
| 12m | POST `/api/platform/approve` with valid approval + `"extra_junk": true` | unknown approval field (ERH-1 extra='forbid') | HTTP 400 |

**CHECKPOINT MRF**: All 13 requests returned 400/404 (not 200 or 500). Record each HTTP code and error body.

**Sequence 13: Version Conflict**
1. POST `/api/platform/submit` (new dataset_id `sg-conflict-test`) → poll until completed
2. POST `/api/platform/approve` (version_id="v1") → expect 200 (first approval)
3. POST `/api/platform/submit` (same dataset_id, new resource or overwrite) → poll until completed
4. POST `/api/platform/approve` (version_id="v1" AGAIN, same version_id) → expect HTTP 409 `VersionConflict`
5. **CHECKPOINT VC1**: Second approval rejected with 409, first v1 unaffected

**Sequence 14: Revoke → Overwrite → Reapprove (Golden Path)**

The core flow that was previously dead code (BS-1). Tests `get_overwrite_candidate()` finding a REVOKED release.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (raster, `sg-revoke-ow-test`) | request_id, job_id |
| 2 | Poll until completed | release_id, asset_id |
| 3 | POST `/api/platform/approve` (v1) | approved |
| 4 | GET `/api/platform/status` | version_id="v1", ordinal=1, revision=1, is_latest=true |
| 5 | POST `/api/platform/revoke` | revoked |
| 6 | GET `/api/platform/status` | approval_state=revoked, is_latest=false, is_served=false |
| 7 | POST `/api/platform/submit` (same, `processing_options: {overwrite: true}`) | new job created |
| 8 | Poll until completed | revision=2, approval_state=pending_review, version_id=null |
| 9 | POST `/api/platform/approve` (v1) | re-approved at same ordinal |
| 10 | GET `/api/platform/status` | version_id="v1", ordinal=1, revision=2, is_latest=true, is_served=true |

**CHECKPOINT RVOW1**: Full round-trip. Ordinal preserved, revision incremented, version_id restored.

**Sequence 15: Overwrite APPROVED Release (Should Create New Version)**

Ensures `get_overwrite_candidate()` correctly excludes APPROVED releases — overwrite flag on an approved release creates a new version instead.

| Step | Action | Verify |
|------|--------|--------|
| 1 | (Use approved raster from Seq 14) | v1 re-approved, revision=2 |
| 2 | POST `/api/platform/submit` (same, `processing_options: {overwrite: true}`) | new release created |
| 3 | Poll until completed | NEW release with version_ordinal=2, NOT a mutation of v1 |

**CHECKPOINT RVOW2**: Overwrite flag on approved release creates new version, does not corrupt existing.

**Sequence 16: Triple Revision (Reject → Overwrite → Reject → Overwrite → Approve)**

Stress-test revision counter and repeated overwrite.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (`sg-triple-rev-test`) → poll | completed, revision=1 |
| 2 | POST `/api/platform/reject` | rejected |
| 3 | POST `/api/platform/submit` (same, `processing_options: {overwrite: true}`) → poll | completed, revision=2 |
| 4 | POST `/api/platform/reject` | rejected again |
| 5 | POST `/api/platform/submit` (same, `processing_options: {overwrite: true}`) → poll | completed, revision=3 |
| 6 | POST `/api/platform/approve` (v1) | approved |
| 7 | GET `/api/platform/status` | revision=3, version_id="v1", approved |

**CHECKPOINT TREV1**: Three revisions tracked correctly, final approval succeeds.

**Sequence 17: Overwrite Race Guard (Overwrite While PROCESSING)**

Verify the `processing_status != 'processing'` guard prevents overwrite of an in-flight release.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (`sg-race-test`) | request_id (do NOT poll) |
| 2 | Immediately POST `/api/platform/submit` (same, `processing_options: {overwrite: true}`) | idempotent response OR error |

**CHECKPOINT RACE1**: Guard prevented overwrite of processing release. No data corruption.

Note: Timing-dependent — if first completes before second arrives, overwrite succeeds (correct behavior). Lancer records whichever outcome; Auditor verifies consistency regardless.

**Sequence 18: Multi-Revoke Overwrite Target (Pick Most Recent)**

Tests `get_overwrite_candidate()` ORDER BY behavior — must select the most recently created revoked release.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (`sg-multi-revoke-test`) → poll | completed |
| 2 | POST `/api/platform/approve` (v1) | approved |
| 3 | POST `/api/platform/submit` (same, new version) → poll | completed, capture v2 release_id |
| 4 | POST `/api/platform/approve` (v2) | approved |
| 5 | POST `/api/platform/revoke` (v2) | revoked |
| 6 | POST `/api/platform/revoke` (v1) | revoked |
| 7 | POST `/api/platform/submit` (same, `processing_options: {overwrite: true}`) → poll | overwritten release = v2's release_id |

**CHECKPOINT MREV1**: Most recent revoked release selected. v1's revoked release untouched.

**Sequence 19: Zarr Rechunk Path (v0.9.14.0)**

Tests the `ingest_zarr_rechunk` handler — submitting a native Zarr with `rechunk=True` processing option. Uses a different Zarr fixture than Seq 6 to avoid dataset_id collision.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with `zarr_era5_global` from config (`data_type=zarr`, `processing_options: {rechunk: true}`), dataset_id `sg-zarr-rechunk-test` | request_id, job_id |
| 2 | Poll until completed | Job succeeds — `ingest_zarr_rechunk` handler fired (Stage 2 rechunk instead of blob copy) |
| 3 | POST `/api/platform/approve` (version_id="v1") | STAC materialized |
| 4 | GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` | `xarray_urls` present with keys [variables, tiles, tilejson, preview, info, point] |
| 5 | **CHECKPOINT RCH1**: Rechunked Zarr ingested and served. Verify job_type=ingest_zarr. |

Note: `rechunk` MUST be inside `processing_options`, same as `overwrite`. The `ingest_zarr_rechunk` handler reads source Zarr via xarray, rechunks to 256×256 spatial / time=1 / Blosc+LZ4, and writes to silver-zarr.

### Lancer Checkpoint Format

```markdown
## Checkpoint {ID}: {description}
AFTER: {step description}
EXPECTED STATE:
  Jobs:
    - {job_id} → status={status}
  Releases:
    - {release_id} → approval_state={state}, version_ordinal={n}
  STAC Items:
    - {item_id} → {exists | not exists}
  Service URLs:
    - raster: titiler_urls keys={list} | MISSING
    - vector: endpoints.features={url}, tiles.tilejson={url} | MISSING
    - zarr: xarray_urls keys={list} | MISSING
  Captured IDs:
    - request_id={value}
    - job_id={value}
    - release_id={value}
    - asset_id={value}
```

### Lancer HTTP Log Format

```
### Step {N}: {description}
REQUEST: {method} {url}
BODY: {json body if any}
RESPONSE: HTTP {code}
BODY: {response body, truncated to 500 chars}
CAPTURED: {key}={value}
EXPECTED: {what should happen}
ACTUAL: {what did happen}
VERDICT: PASS | FAIL | UNEXPECTED
```

---

## Step 4: Dispatch Auditor

Auditor receives Lancer's State Checkpoint Map and verifies actual system state.

### Audit Queries

For each checkpoint, prefer Platform API endpoints. Use admin endpoints only for deeper verification.

**Primary checks (Platform API)**:

| Check | Query | Compare Against |
|-------|-------|-----------------|
| Job/release state | `/api/platform/status/{request_id}` | Expected job_status, approval_state |
| STAC item existence | `/api/platform/catalog/item/{collection}/{item_id}` | Expected 200 or 404 |
| Dataset items | `/api/platform/catalog/dataset/{dataset_id}` | Expected item count |
| Approval state | `/api/platform/approvals/status?stac_item_ids={ids}` | Expected approval records |
| Recent failures | `/api/platform/failures` | No unexpected failures |

**Deep verification (admin — verification only)**:

| Check | Query | Compare Against |
|-------|-------|-----------------|
| Job detail | `/api/dbadmin/jobs/{job_id}` | Expected status, result_data |
| Overall stats | `/api/dbadmin/diagnostics?type=stats` | No unexpected counts |
| Orphaned tasks | `/api/dbadmin/diagnostics?type=all` | Clean diagnostics |

### Overwrite-Specific Audit Checks

For each overwrite checkpoint, Auditor MUST verify these fields via `/api/platform/status/{request_id}`:

| Checkpoint | Key Assertions |
|------------|---------------|
| **RVOW1** (Seq 14) | revision=2, version_ordinal=1, version_id="v1", is_latest=true, is_served=true. Versions array shows single release with revision=2. |
| **RVOW2** (Seq 15) | New release_id (not same as v1's release_id), version_ordinal=2. Original v1 release unchanged. |
| **TREV1** (Seq 16) | revision=3, version_id="v1", approval_state=approved. Versions array shows revision=3. |
| **RACE1** (Seq 17) | No corrupted state regardless of timing outcome. If overwrite succeeded: revision=2. If guard blocked: original release intact at revision=1. |
| **MREV1** (Seq 18) | Overwritten release_id matches v2's original release_id. v1's revoked release untouched (still revoked, same revision). |
| **IST-8** (Seq 11h) | Release still in pending_review + processing. No state mutation occurred. |
| **IST-9** (Seq 11i) | New release created with version_ordinal incremented. Original approved release unchanged. |

### Auditor Output Format

```markdown
## State Audit

### Checkpoint {ID}: {description}
| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Job {job_id} status | completed | {actual} | PASS/FAIL |
| Release {release_id} state | approved | {actual} | PASS/FAIL |
| STAC item {item_id} | exists | {actual} | PASS/FAIL |

### Orphaned Artifacts
| Type | ID | Why Orphaned |
...

### Divergences
| Checkpoint | Expected | Actual | Severity |
...

### Service URL Integrity
| Data Type | Probe | URL | HTTP | Content-Type | Verdict |
|-----------|-------|-----|------|-------------|---------|
...
```

### Service URL Integrity

For each approved release in the checkpoint map:

1. **TiTiler Liveness**: GET `{titiler_base}/livez` → expect HTTP 200 with `{"status":"alive"}`
2. **Per data type probes** (using URLs from Lancer's catalog response):

| Data Type | Probe | Expected |
|-----------|-------|----------|
| Raster | GET `{titiler_urls.info}` | HTTP 200, JSON with `band_metadata` |
| Raster | GET `{titiler_urls.preview}` | HTTP 200, Content-Type: image/png |
| Raster | GET `{titiler_urls.tilejson}` | HTTP 200, JSON with `tiles` array |
| Vector | GET `{tipg_base}/collections/{table}` | HTTP 200, collection metadata |
| Vector | GET `{tipg_base}/collections/{table}/items?limit=1` | HTTP 200, GeoJSON FeatureCollection |
| Zarr | GET `{xarray_urls.variables}` | HTTP 200, JSON array of variable names |
| Zarr | GET `{xarray_urls.info}&variable={first_var}` | HTTP 200, JSON metadata |

---

## Step 5: Dispatch Scribe

Scribe receives all outputs and produces the final report.

### Scribe Output Format

```markdown
# SIEGE Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version from /api/health}
**Pipeline**: SIEGE

## Endpoint Health
| Endpoint | Status | Latency |
...
Assessment: {HEALTHY | DEGRADED | DOWN}

## Workflow Results
| Sequence | Steps | Pass | Fail | Unexpected |
|----------|-------|------|------|------------|
| 1. Raster Lifecycle | {n} | {n} | {n} | {n} |
| 2. Vector Lifecycle | {n} | {n} | {n} | {n} |
| 3. Multi-Version | {n} | {n} | {n} | {n} |
| 4. Unpublish | {n} | {n} | {n} | {n} |
| 5. NetCDF/VirtualiZarr | {n} | {n} | {n} | {n} |
| 6. Native Zarr | {n} | {n} | {n} | {n} |
| 7. Rejection | {n} | {n} | {n} | {n} |
| 8. Reject→Resubmit→Approve | {n} | {n} | {n} | {n} |
| 9. Revoke + is_latest Cascade | {n} | {n} | {n} | {n} |
| 10. Overwrite Draft | {n} | {n} | {n} | {n} |
| 11. Invalid State Transitions (9) | {n} | {n} | {n} | {n} |
| 12. Missing Required Fields (13) | {n} | {n} | {n} | {n} |
| 13. Version Conflict | {n} | {n} | {n} | {n} |
| 14. Revoke→Overwrite→Reapprove | {n} | {n} | {n} | {n} |
| 15. Overwrite Approved (→New Version) | {n} | {n} | {n} | {n} |
| 16. Triple Revision | {n} | {n} | {n} | {n} |
| 17. Overwrite Race Guard | {n} | {n} | {n} | {n} |
| 18. Multi-Revoke Overwrite Target | {n} | {n} | {n} | {n} |
| 19. Zarr Rechunk Path | {n} | {n} | {n} | {n} |

## Service URL Verification
| Data Type | Probe | HTTP | Verdict |
|-----------|-------|------|---------|
| TiTiler liveness | /livez | {code} | PASS/FAIL |
| Raster info | /cog/info | {code} | PASS/FAIL |
| Raster preview | /cog/preview | {code} | PASS/FAIL |
| Vector collection | /vector/collections/{table} | {code} | PASS/FAIL |
| Vector items | /vector/collections/{table}/items | {code} | PASS/FAIL |
| Zarr variables | /xarray/variables | {code} | PASS/FAIL |
| Zarr info | /xarray/info | {code} | PASS/FAIL |

Assessment: {ALL PASS | DEGRADED | UNAVAILABLE}

## State Divergences
{from Auditor — expected vs actual for each failing checkpoint}

## Findings
| # | Severity | Category | Description | Reproduction |
...

## Verdict
{PASS | FAIL | NEEDS INVESTIGATION}
```

### Save Output

Save to `docs/agent_review/agent_docs/SIEGE_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Flow Summary

| Agent | Gets | Doesn't Get |
|-------|------|-------------|
| Sentinel | V0.9_TEST.md, API docs | Nothing (defines everything) |
| Cartographer | Campaign Brief, endpoint list | Test data, lifecycle sequences |
| Lancer | Campaign Brief, test data, sequences | Cartographer's findings |
| Auditor | Lancer's State Checkpoint Map, captured IDs, service URLs from checkpoints. Also probes external TiTiler/TiPG endpoints. | Lancer's raw HTTP responses |
| Scribe | All outputs from all agents | Nothing hidden |

**Note**: SIEGE has minimal information asymmetry by design. Its value is speed and completeness, not adversarial competition. For adversarial testing, use WARGAME or TOURNAMENT.
