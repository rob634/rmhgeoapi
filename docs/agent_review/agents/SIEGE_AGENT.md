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
- **`profiles`**: Run profiles — `quick` or `full` (see below)

Sentinel MUST verify valid files exist before launching by calling the discovery endpoint:
```bash
curl "${BASE_URL}/api/storage/rmhazuregeobronze/blobs?zone=bronze&limit=50"
```

### Run Profiles

SIEGE supports two profiles: **quick** (~15 min) and **full** (~45-90 min).

| Profile | Max File Size | Zarr Seq 6 | Zarr Seq 19 | All Other Seqs |
|---------|---------------|------------|-------------|----------------|
| **quick** | <100 MB | `cmip6-tasmax-quick.zarr` (10 MB) | `era5-quick.zarr` (19 MB) | Default fixtures (all <26 MB) |
| **full** | No limit | `cmip6-tasmax-sample.zarr` (1.5 GB) | `era5-global-sample.zarr` (8 GB) | Default fixtures |

**Both profiles run all 25 sequences.** The only difference is data scale — sequences reference small (default) fixtures, full profile overrides to large files for stress testing.

**Sentinel selects profile at campaign start.** When building the Campaign Brief:
1. Check if the user specified `quick` or `full`
2. If `quick` or unspecified: use default fixtures (no overrides — defaults are small)
3. If `full`: apply `profiles.full.fixture_overrides` — e.g., `raster` → `raster_float32_utm` (462 MB), `vector` → `vector_geojson_large` (137 MB), `zarr_cmip6_tasmax_quick` → `zarr_cmip6_tasmax` (1.5 GB), `zarr_era5_rechunk_quick` → `zarr_era5_rechunk` (8 GB)

**Rule**: Sequences always reference the small fixture name. Profiles apply overrides. Sentinel resolves the final fixture for each sequence before handing off to Lancer.

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

**Service Layer health (TiTiler/TiPG — required for URL verification)**:

| Endpoint | Base | Probe | Expected |
|----------|------|-------|----------|
| `/livez` | `{titiler_base}` from siege_config.json | No params | 200, `{"status":"alive","app":"rmhtitiler"}` |
| `/health` | `{titiler_base}` | No params | 200, verify `app` and `role` fields present |

If the Service Layer is DOWN (non-200 from `/livez`), Cartographer MUST report `SERVICE_LAYER: DOWN` in the Health Assessment. Lancer should still run lifecycle sequences, but service URL probes will FAIL — this is expected and should be recorded as `FAIL (service layer down)`, not skipped.

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
3. **ASSERT STATUS SERVICES** (pre-approval): GET `/api/platform/status/{request_id}` → assert `services` block present:
   - `services.service_url` contains `/cog/WebMercatorQuad/tilejson.json`
   - `services.preview` contains `/cog/preview.png`
   - `services.viewer` contains `/cog/WebMercatorQuad/map.html`
   - `services.tiles` contains `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`
   - `services.stac_collection` is null (pre-approval)
   - `services.stac_item` is null (pre-approval)
   → **CHECKPOINT R1-SVC**: Record full `services` block
4. POST `/api/platform/approve` (version_id="v1") → verify STAC materialized
5. **ASSERT STATUS SERVICES** (post-approval): GET `/api/platform/status/{request_id}` → assert STAC keys populated:
   - `services.stac_collection` starts with `{titiler_base}/stac/collections/`
   - `services.stac_item` starts with `{titiler_base}/stac/collections/`
6. GET `/api/platform/catalog/item/{collection}/{item_id}` → verify exists
7. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `titiler_urls` present with keys [xyz, tilejson, preview, info, statistics]. Verify URLs contain TiTiler base hostname. → **CHECKPOINT R1-URLS**
8. **PROBE SERVICE URLS** (mandatory — this is the platform success criterion):
   - GET `{titiler_urls.info}` → expect HTTP 200, JSON with `band_metadata`
   - GET `{titiler_urls.preview}` → expect HTTP 200, Content-Type contains `image/`
   - GET `{titiler_urls.tilejson}` → expect HTTP 200, JSON with `tiles` array
   - Record each: URL, HTTP code, Content-Type, verdict (PASS/FAIL/ERROR)
   - If ANY probe fails: log the full response body (truncated to 500 chars) for diagnosis
9. **CROSS-CHECK**: Compare `services.service_url` from status (step 5) against `titiler_urls.tilejson` from catalog (step 7) — URL paths should match (ignore encoding differences)
10. **CHECKPOINT R1**: Record all IDs, expected DB/STAC state, services block, and service URL probe results

**Sequence 2: Vector Lifecycle**
1. POST `/api/platform/submit` (vector) → capture IDs
2. Poll until completed → capture release_id
3. **ASSERT STATUS SERVICES** (pre-approval): GET `/api/platform/status/{request_id}` → assert `services` block present:
   - `services.service_url` contains `/collections/geo.`
   - `services.preview` contains `/tiles/WebMercatorQuad/map`
   - `services.viewer` contains `/tiles/WebMercatorQuad/map`
   - `services.tiles` contains `/{z}/{x}/{y}.pbf`
   - `services.stac_collection` is null (vector never has STAC)
   - `services.stac_item` is null (vector never has STAC)
   → **CHECKPOINT V1-SVC**: Record full `services` block
4. POST `/api/platform/approve` → verify OGC Features
5. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `endpoints.features` present, `tiles.tilejson` present. Verify URLs contain TiPG base path. → **CHECKPOINT V1-URLS**
6. **PROBE SERVICE URLS** (mandatory):
   - GET `{tipg_base}/collections/{schema}.{table_name}` → expect HTTP 200, JSON with collection metadata
   - GET `{tipg_base}/collections/{schema}.{table_name}/items?limit=1` → expect HTTP 200, JSON with `type: "FeatureCollection"` and `features` array
   - Record each: URL, HTTP code, Content-Type, verdict (PASS/FAIL/ERROR)
   - If ANY probe fails: log the full response body (truncated to 500 chars) for diagnosis
7. **CROSS-CHECK**: Compare `services.service_url` from status (step 3) against catalog vector collection URL (step 5) — should match exactly
8. **CHECKPOINT V1**: Record all IDs, services block, and service URL probe results

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
3. **ASSERT STATUS SERVICES** (pre-approval): GET `/api/platform/status/{request_id}` → assert `services` block present:
   - `services.service_url` contains `/xarray/WebMercatorQuad/tilejson.json`
   - `services.preview` contains `/xarray/preview.png`
   - `services.viewer` contains `/xarray/WebMercatorQuad/map.html`
   - `services.tiles` contains `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}`
   - `services.variables` contains `/xarray/variables`
   - `services.stac_collection` is null (pre-approval)
   - `services.stac_item` is null (pre-approval)
   → **CHECKPOINT Z1-SVC**: Record full `services` block
4. POST `/api/platform/approve` (version_id="v1") → verify STAC materialized (zarr items go in STAC)
5. **ASSERT STATUS SERVICES** (post-approval): GET `/api/platform/status/{request_id}` → assert STAC keys populated:
   - `services.stac_collection` starts with `{titiler_base}/stac/collections/`
   - `services.stac_item` starts with `{titiler_base}/stac/collections/`
6. GET `/api/platform/catalog/dataset/{dataset_id}` → verify catalog entry exists
7. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `xarray_urls` present with keys [variables, tiles, tilejson, preview, info, point]. Verify URLs contain TiTiler base hostname and `/xarray/` path. → **CHECKPOINT Z1-URLS**
8. **PROBE SERVICE URLS** (mandatory):
   - GET `{xarray_urls.variables}` → expect HTTP 200, JSON array of variable names
   - If variables response is 200, pick the first variable name from the array, then:
     - GET `{xarray_urls.info}&variable={first_var}` → expect HTTP 200, JSON metadata
   - Record each: URL, HTTP code, Content-Type, verdict (PASS/FAIL/ERROR)
   - If ANY probe fails: log the full response body (truncated to 500 chars) for diagnosis
9. **CROSS-CHECK**: Compare `services.service_url` from status (step 5) against `xarray_urls.tilejson` from catalog (step 7) — URL paths should match
10. **CHECKPOINT Z1**: Record all IDs, verify job_type=virtualzarr, STAC item present, services block, and service URL probe results

Note: NetCDF (.nc) routes to the VirtualiZarr pipeline, NOT the raster pipeline.
Use `data_type_override: "zarr"` from siege_config.json. Submit body must include
`"data_type": "zarr"`. Processing may take longer than raster (5-stage pipeline).

**Sequence 6: Native Zarr Lifecycle**
1. POST `/api/platform/submit` with `data_type=zarr`, native `.zarr` store (`zarr_cmip6_tasmax_quick` from config) → capture request_id, job_id
2. Poll until completed → verify job completes (different code path from VirtualiZarr .nc)
3. **ASSERT STATUS SERVICES** (pre-approval): GET `/api/platform/status/{request_id}` → assert `services` block present:
   - `services.service_url` contains `/xarray/WebMercatorQuad/tilejson.json`
   - `services.preview` contains `/xarray/preview.png`
   - `services.viewer` contains `/xarray/WebMercatorQuad/map.html`
   - `services.tiles` contains `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}`
   - `services.variables` contains `/xarray/variables`
   - `services.stac_collection` is null (pre-approval)
   → **CHECKPOINT NZ1-SVC**: Record full `services` block
4. POST `/api/platform/approve` (version_id="v1") → verify STAC materialized
5. **ASSERT STATUS SERVICES** (post-approval): GET `/api/platform/status/{request_id}` → assert STAC keys populated:
   - `services.stac_collection` starts with `{titiler_base}/stac/collections/`
   - `services.stac_item` starts with `{titiler_base}/stac/collections/`
6. GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` → verify `xarray_urls` present → **CHECKPOINT NZ1-URLS**
7. **PROBE SERVICE URLS** (mandatory):
   - GET `{xarray_urls.variables}` → expect HTTP 200, JSON array of variable names
   - If variables response is 200, pick the first variable name from the array, then:
     - GET `{xarray_urls.info}&variable={first_var}` → expect HTTP 200, JSON metadata
   - Record each: URL, HTTP code, Content-Type, verdict (PASS/FAIL/ERROR)
   - If ANY probe fails: log the full response body (truncated to 500 chars) for diagnosis
8. **CROSS-CHECK**: Compare `services.service_url` from status (step 5) against `xarray_urls.tilejson` from catalog (step 6) — URL paths should match
9. **CHECKPOINT NZ1**: Record all IDs, verify direct zarr path (NOT virtualzarr pipeline), services block, and service URL probe results

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
| 1 | POST `/api/platform/submit` with `zarr_era5_rechunk_quick` from config (`data_type=zarr`, `processing_options: {rechunk: true}`), dataset_id `sg-zarr-rechunk-test` | request_id, job_id |
| 2 | Poll until completed | Job succeeds — `ingest_zarr_rechunk` handler fired (Stage 2 rechunk instead of blob copy) |
| 3 | **ASSERT STATUS SERVICES**: GET `/api/platform/status/{request_id}` → assert `services` block: `service_url` contains `/xarray/`, `preview` contains `/xarray/preview.png`, `variables` contains `/xarray/variables`, `stac_collection` is null (pre-approval) | Services block shape matches zarr contract from `siege_config.json → services_contract.key_assertions.zarr` |
| 4 | POST `/api/platform/approve` (version_id="v1") | STAC materialized |
| 5 | **ASSERT STATUS SERVICES** (post-approval): GET `/api/platform/status/{request_id}` → assert `stac_collection` and `stac_item` populated | STAC URLs present after approval |
| 6 | GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` | `xarray_urls` present with keys [variables, tiles, tilejson, preview, info, point] |
| 7 | **PROBE SERVICE URLS**: GET `{xarray_urls.variables}` → 200, JSON array. If 200: GET `{xarray_urls.info}&variable={first_var}` → 200 | Service Layer serves rechunked data |
| 8 | **CROSS-CHECK**: Compare `services.service_url` from status (step 5) against `xarray_urls.tilejson` from catalog (step 6) — URL paths should match | Consistency between status and catalog |
| 9 | **CHECKPOINT RCH1**: Rechunked Zarr ingested and served. Verify job_type=ingest_zarr. Record services block and service URL probe results. | |

Note: `rechunk` MUST be inside `processing_options`, same as `overwrite`. The `ingest_zarr_rechunk` handler reads source Zarr via xarray, rechunks to 256×256 spatial / time=1 / Blosc+LZ4, and writes to silver-zarr.

**Sequence 20: Vector Split Views Lifecycle (v0.10.0+)**

Tests the P2 split views workflow — a single vector file with `split_column` parameter produces 1 base table + N PostgreSQL VIEWs, each discoverable as an independent TiPG collection.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with `vector_split_views` fixture from config (`processing_options: {split_column: "quadrant"}`) | request_id, job_id, job_type=vector_docker_etl |
| 2 | Poll until completed | job_status=completed |
| 3 | GET `/api/platform/status/{request_id}` → verify outputs contain `split_views` block | `split_views.views_created` = 4, `split_views.values` = ["NE", "NW", "SE", "SW"] |
| 4 | **ASSERT STATUS SERVICES** (pre-approval): GET `/api/platform/status/{request_id}` → assert `services` block: `service_url` contains `/collections/geo.`, `tiles` contains `/{z}/{x}/{y}.pbf` | Services shape matches vector contract |
| 5 | **PROBE BASE TABLE**: GET `{tipg_base}/collections/{schema}.{table_name}/items?limit=0` → expect 200, `numberMatched` = 3301 | Base table has all features |
| 6 | **PROBE EACH SPLIT VIEW**: For each view_name in `split_views.view_names`: GET `{tipg_base}/collections/{schema}.{view_name}/items?limit=0` → expect 200, `numberMatched` > 0 | Each view is independently discoverable |
| 7 | **COUNT VERIFICATION**: Sum of all view `numberMatched` values must equal base table `numberMatched` | No features lost or duplicated |
| 8 | POST `/api/platform/approve` (version_id="v1") → verify approval succeeds | approval_state=approved |
| 9 | **CHECKPOINT SV1**: Record all IDs, split_views block, view_names, feature counts per view, count verification result, and service URL probe results |

**CHECKPOINT SV1**: Base table + N views all live. Count sum matches. Split views block in outputs.

Note: `split_column` MUST be inside `processing_options`, same as `overwrite`. The column must exist in the uploaded data and be a categorical type (text, varchar, integer, boolean). Max 20 distinct values.

**Sequence 21: Split Views Validation (Negative Tests)**

Tests error handling for invalid split_column usage.

| # | Action | Expected | Checkpoint |
|---|--------|----------|------------|
| 21a | POST `/api/platform/submit` with `vector_split_views_invalid_column` fixture (`split_column: "nonexistent_column"`) → poll until result | Job FAILS with error mentioning column not found | SVV-1 |
| 21b | POST `/api/platform/submit` with vector file + `split_column` set to a float column (e.g., `"mean"`) → poll until result | Job FAILS with error mentioning type not allowed for split | SVV-2 |
| 21c | POST `/api/platform/submit` with vector file + `split_column: "quadrant"` but NO `overwrite` and base table still exists from Seq 20 | Job FAILS with table already exists error OR succeeds with overwrite guard | SVV-3 |

**CHECKPOINT SVV**: All 3 negative cases rejected gracefully with informative error messages (not 500s).

**Sequence 22: Approved Asset Overwrite Guard — Different File (v0.10.0+)**

Tests the core invariant: **approved assets cannot be overwritten — they must be revoked first.** Uses two different input files to prove data actually changes after revoke+overwrite, not just metadata.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (vector, `sg-ow-guard-test`, `vector_geojson_small` fixture: `roads.geojson`, 483 features) | request_id, job_id |
| 2 | Poll until completed | job_status=completed |
| 3 | POST `/api/platform/approve` (v1) | approval_state=approved |
| 4 | GET `/api/platform/status/{request_id}` | version_id="v1", is_latest=true, is_served=true |
| 5 | **BREAK ATTEMPT**: POST `/api/platform/submit` (same dataset_id+resource_id, DIFFERENT file `roads.gpkg` from `vector_gpkg` fixture, `processing_options: {overwrite: true}`) | Overwrite guard triggers — approved release NOT mutated. Expect NEW release with version_ordinal=2, NOT revision of v1 |
| 6 | Poll until completed → capture v2 IDs | New release at ordinal=2, v1 untouched |
| 7 | GET `/api/platform/status/{v1_request_id}` | v1 still approved, revision=1, is_latest=true (v2 is pending, not latest) |
| 8 | POST `/api/platform/unpublish` (v2, pending release) | v2 cleaned up — we don't want it |
| 9 | POST `/api/platform/revoke` (v1) with reason "Revoking to test overwrite with different file" | approval_state=revoked, is_latest=false, is_served=false |
| 10 | GET `/api/platform/status/{request_id}` | Confirm v1 revoked — asset now editable |
| 11 | POST `/api/platform/submit` (same dataset_id+resource_id, `roads.gpkg` from `vector_gpkg` fixture, `processing_options: {overwrite: true}`) | Overwrite succeeds — revoked release mutated |
| 12 | Poll until completed | revision=2, approval_state=pending_review |
| 13 | **PROBE DATA CHANGE**: GET `{tipg_base}/collections/{schema}.{table_name}/items?limit=1` → verify features exist (table repopulated with roads.gpkg data) | Data changed — confirms overwrite replaced content, not just metadata |
| 14 | POST `/api/platform/approve` (v1) | Re-approved at same ordinal |
| 15 | GET `/api/platform/status/{request_id}` | version_id="v1", ordinal=1, revision=2, is_latest=true, is_served=true |

**CHECKPOINT OWGD1**: Full lifecycle proves:
- Step 5: Approved asset PROTECTED from overwrite (new version created instead)
- Step 9: Revocation UNLOCKS the asset for modification
- Step 11: Different file successfully replaces original data
- Step 15: Re-approval restores served state with new data

**Key difference from Seq 14**: Seq 14 uses the same file throughout. This sequence uses **different files** (GeoJSON → GPKG) to prove the overwrite actually replaced the data, not just re-ran the same pipeline.

**Sequence 23: Unpublish with Blob Preservation (v0.10.0.3+)**

Tests the `delete_blobs=false` flag — STAC item and metadata are removed but storage blobs survive. Covers the UNP-3 bug where `delete_blobs` was silently ignored and blobs were always deleted.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (raster, `sg-unp-blobkeep`, `raster` fixture: `dctest.tif`) | request_id, job_id |
| 2 | Poll until completed | job_status=completed |
| 3 | POST `/api/platform/approve` (v1) | approval_state=approved |
| 4 | GET `/api/platform/status/{request_id}` → capture `service_url` (contains blob path) | version_id="v1", is_served=true |
| 5 | **PROBE BLOB PRE-UNPUBLISH**: GET `/cog/info?url={service_url}` → expect 200 | Blob exists and is readable |
| 6 | POST `/api/platform/unpublish` with `delete_blobs=false, force_approved=true, dry_run=false` | 202 Accepted, job_type=unpublish_raster |
| 7 | Poll unpublish job until completed | job_status=completed |
| 8 | GET `/api/platform/status/{original_request_id}` | STAC item removed (stac_item=null or request not found) |
| 9 | **PROBE BLOB POST-UNPUBLISH**: GET `/cog/info?url={service_url}` (same blob URL from step 4) → expect 200 | Blob STILL exists — delete_blobs=false was honoured |
| 10 | **CLEANUP**: POST `/api/platform/unpublish` with same identifiers, `delete_blobs=true, force_approved=true` → poll until completed | Blob now deleted. GET `/cog/info?url={service_url}` → expect 4xx |

**CHECKPOINT BPRES1**: Full lifecycle proves:
- Step 7: Unpublish job completed successfully with delete_blobs=false
- Step 9: Blob survived unpublish — flag was honoured at all pipeline layers
- Step 10: Cleanup pass with delete_blobs=true removes the blob

**Key invariant**: `delete_blobs=false` must preserve storage blobs while still removing STAC metadata and audit records. This is the safety valve for clients who need to remove catalog entries without destroying source data.

**Sequence 24: Resubmit Guards (v0.10.0.3+)**

Tests the UNP-ARCH hardening — resubmit on completed jobs must be blocked (409) unless `force=true`. Also tests resubmit on processing jobs.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (raster, `sg-resubmit-guard`, `raster` fixture: `dctest.tif`) | request_id, job_id |
| 2 | Poll until completed | job_status=completed |
| 3 | **GUARD TEST**: POST `/api/platform/resubmit` with `{"job_id": "{job_id}"}` (no force flag) | HTTP 409, error_type=JobAlreadyCompleted, message mentions "force=true" |
| 4 | **DEPRECATION CHECK**: Verify response or logs contain deprecation guidance | Response mentions /api/platform/submit |
| 5 | **FORCE OVERRIDE**: POST `/api/platform/resubmit` with `{"job_id": "{job_id}", "force": true}` | HTTP 202, new_job_id returned (different from original) |
| 6 | Poll new job until completed | new job completes successfully |
| 7 | **CHECKPOINT RSUB1**: Record original_job_id, new_job_id, guard response (step 3), force response (step 5) |

**CHECKPOINT RSUB1**: Resubmit guards prove:
- Step 3: Completed jobs are PROTECTED — 409 returned without force flag
- Step 5: Force override works when explicitly requested
- Step 6: Forced resubmit produces a working new job

**Sequence 25: Unpublish DDH-Only Resolution (v0.10.0.3+)**

Tests the UNP-1 fallback — unpublish resolves data_type from Asset entity when no `platform_requests` record matches the DDH identifiers. Uses explicit `data_type` + DDH identifiers (Option 4 path) to verify the system doesn't return 400.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` (vector, `sg-unp-ddh-resolve`, `vector` fixture) | request_id, job_id, dataset_id, resource_id |
| 2 | Poll until completed | job_status=completed |
| 3 | GET `/api/platform/status/{request_id}` → capture table_name from outputs | table_name recorded |
| 4 | **DIRECT DDH UNPUBLISH**: POST `/api/platform/unpublish` with `{"data_type": "vector", "dataset_id": "{dataset_id}", "resource_id": "{resource_id}", "version_id": "v1", "dry_run": true}` | HTTP 200 (dry_run preview), data_type=vector, would_delete.table matches expected |
| 5 | **LIVE DDH UNPUBLISH**: POST `/api/platform/unpublish` with same DDH identifiers + `"dry_run": false` | HTTP 202, job_type=unpublish_vector |
| 6 | Poll unpublish job until completed | job_status=completed, table dropped |
| 7 | **VERIFY GONE**: GET `{tipg_base}/collections/geo.{table_name}` → expect 404 | Table no longer discoverable |

**CHECKPOINT DDHR1**: DDH resolution proves:
- Step 4: Dry-run resolves data_type from explicit parameter + DDH identifiers (no 400)
- Step 5: Live unpublish executes correctly from DDH-resolved parameters
- Step 7: Data actually removed — not just a metadata update

**Key difference from Seq 5**: Seq 5 unpublishes using request_id (always resolves via platform_requests). This sequence tests resolution via explicit data_type + DDH identifiers, which exercises the UNP-1 fallback path.

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
  Services Block (from /api/platform/status — *-SVC checkpoints):
    - service_url={url}
    - preview={url}
    - stac_collection={url | null}
    - stac_item={url | null}
    - viewer={url}
    - tiles={url}
    - variables={url} (zarr only)
  Service URLs (from catalog response — *-URLS checkpoints):
    - raster: titiler_urls keys={list} | MISSING
    - vector: endpoints.features={url}, tiles.tilejson={url} | MISSING
    - zarr: xarray_urls keys={list} | MISSING
  Status ↔ Catalog Cross-Check:
    - services.service_url vs catalog URL → {MATCH | DIVERGENCE}
  Service URL Probes (Lancer actually hit these — PASS/FAIL/SKIP):
    - {probe_name}: {url} → HTTP {code}, {Content-Type} → {PASS|FAIL|ERROR}
    - {probe_name}: {url} → HTTP {code}, {Content-Type} → {PASS|FAIL|ERROR}
    - (if FAIL: response body excerpt for diagnosis)
  Captured IDs:
    - request_id={value}
    - job_id={value}
    - release_id={value}
    - asset_id={value}
```

**Service URL probe rules**:
- Probes are mandatory for all `*-URLS` checkpoints (R1, V1, Z1, NZ1, RCH1)
- Use `{titiler_base}` from `siege_config.json → target.service_urls.titiler_base`
- Use probe URL templates from `siege_config.json → target.service_urls.{raster,vector,zarr}_probes`
- Substitute `{encoded_url}` with the actual URL-encoded blob path from the catalog response
- Substitute `{schema}` and `{table_name}` from the catalog vector response
- Substitute `{variable}` with the first variable from `/xarray/variables` response
- If the Service Layer is unreachable, record `FAIL (service layer down)` — do NOT skip

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
| **OWGD1** (Seq 22) | Step 5 created new version (ordinal=2), NOT mutation of v1. After revoke: revision=2, ordinal=1, file changed from .geojson to .gpkg. v1 re-approved with new data. |
| **BPRES1** (Seq 23) | Unpublish with delete_blobs=false: STAC removed, blob still accessible via TiTiler. Cleanup pass with delete_blobs=true deletes blob. |
| **RSUB1** (Seq 24) | Resubmit on completed job returns 409 (JobAlreadyCompleted). Resubmit with force=true returns 202 and produces working job. |
| **DDHR1** (Seq 25) | DDH-only unpublish resolves data_type via explicit parameter. Dry-run returns 200 preview. Live unpublish completes and removes data. |

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

### Service URL Integrity (Re-verification of Lancer probes)
| Data Type | Probe | Lancer Result | Auditor Re-probe | Verdict |
|-----------|-------|---------------|------------------|---------|
...
```

### Service URL Integrity (Re-verification)

Lancer performs the primary service URL probes during lifecycle sequences.
Auditor cross-checks Lancer's probe results and re-verifies any that failed.

1. **Check Lancer's probe results**: For each `*-URLS` checkpoint, verify Lancer recorded PASS/FAIL/ERROR for all expected probes. If any probe is missing from the checkpoint, flag as `AUDIT_GAP`.
2. **Re-probe failures**: For any probe that Lancer recorded as FAIL, re-run the same GET request. If it now passes, record `FLAKY`. If it still fails, record `CONFIRMED_FAIL`.
3. **TiTiler health cross-check**: GET `{titiler_base}/health` → verify response contains `"app": "rmhtitiler"` and `"status"` field. This confirms the Service Layer is identity-aware (platform contract alignment).

### Status ↔ Catalog URL Cross-Check

For each completed & approved lifecycle checkpoint that has both a `*-SVC` and `*-URLS` checkpoint, compare the status `services` block against the catalog lookup response:

| Data Type | Status Key | Catalog Key | Should Match |
|-----------|-----------|-------------|--------------|
| Raster | `services.service_url` | `titiler_urls.tilejson` | URL path match (ignore encoding diffs) |
| Vector | `services.service_url` | `vector.collection` (from catalog) | Exact match |
| Zarr | `services.service_url` | `xarray_urls.tilejson` | URL path match |

Any divergence = FINDING (MEDIUM severity — consumers see different URLs from different endpoints).

### Services Block Shape Validation

For each `*-SVC` checkpoint, validate against the contract defined in `siege_config.json → services_contract`:

1. Assert all 6 guaranteed keys present: `service_url`, `preview`, `stac_collection`, `stac_item`, `viewer`, `tiles`
2. For zarr checkpoints: assert `variables` key also present
3. Assert `service_url` is not null (primary success criterion)
4. Assert key values match the `key_assertions` patterns for the data type (e.g., raster `service_url` contains `/cog/WebMercatorQuad/tilejson.json`)
5. Missing keys or null `service_url` = FINDING (HIGH severity — service contract violation)

| Data Type | Probe | Expected |
|-----------|-------|----------|
| Raster | GET `{titiler_urls.info}` | HTTP 200, JSON with `band_metadata` |
| Raster | GET `{titiler_urls.preview}` | HTTP 200, Content-Type contains `image/` |
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
| 20. Vector Split Views | {n} | {n} | {n} | {n} |
| 21. Split Views Validation (3) | {n} | {n} | {n} | {n} |
| 22. Approved Overwrite Guard (Diff File) | {n} | {n} | {n} | {n} |
| 23. Unpublish Blob Preservation | {n} | {n} | {n} | {n} |
| 24. Resubmit Guards | {n} | {n} | {n} | {n} |
| 25. Unpublish DDH-Only Resolution | {n} | {n} | {n} | {n} |

## Services Block Contract (Status Endpoint)

**Validates that `/api/platform/status` returns a consistent `services` shape after job completion.**
Uses expected shapes from `siege_config.json → services_contract`.

| Seq | Data Type | Checkpoint | 6 Keys Present | service_url Not Null | Type-Specific Keys | Verdict |
|-----|-----------|------------|----------------|---------------------|--------------------|---------|
| 1 | Raster | R1-SVC | {Y/N} | {Y/N} | — | PASS/FAIL |
| 2 | Vector | V1-SVC | {Y/N} | {Y/N} | — | PASS/FAIL |
| 5 | Zarr (VirtualiZarr) | Z1-SVC | {Y/N} | {Y/N} | variables: {Y/N} | PASS/FAIL |
| 6 | Zarr (native) | NZ1-SVC | {Y/N} | {Y/N} | variables: {Y/N} | PASS/FAIL |
| 19 | Zarr (rechunk) | RCH1-SVC | {Y/N} | {Y/N} | variables: {Y/N} | PASS/FAIL |

## Status ↔ Catalog URL Cross-Check

| Seq | Data Type | Status service_url | Catalog URL | Match? |
|-----|-----------|-------------------|-------------|--------|
| 1 | Raster | {url} | titiler_urls.tilejson | {MATCH/DIVERGE} |
| 2 | Vector | {url} | catalog vector URL | {MATCH/DIVERGE} |
| 5 | Zarr (VirtualiZarr) | {url} | xarray_urls.tilejson | {MATCH/DIVERGE} |
| 6 | Zarr (native) | {url} | xarray_urls.tilejson | {MATCH/DIVERGE} |
| 19 | Zarr (rechunk) | {url} | xarray_urls.tilejson | {MATCH/DIVERGE} |

## Service URL Verification (Platform Success Criterion)

**This is the primary measure of platform health.** ETL pipelines are only successful
if the Service Layer can serve the data they produced. URLs are probed by Lancer
during lifecycle sequences and re-verified by Auditor for any failures.

| Seq | Data Type | Probe | URL | HTTP | Verdict |
|-----|-----------|-------|-----|------|---------|
| 1 | TiTiler liveness | /livez | {url} | {code} | PASS/FAIL |
| 1 | Raster info | /cog/info | {url} | {code} | PASS/FAIL |
| 1 | Raster preview | /cog/preview | {url} | {code} | PASS/FAIL |
| 1 | Raster tilejson | /cog/tilejson | {url} | {code} | PASS/FAIL |
| 2 | Vector collection | /vector/collections/{table} | {url} | {code} | PASS/FAIL |
| 2 | Vector items | /vector/collections/{table}/items | {url} | {code} | PASS/FAIL |
| 5 | Zarr variables (VirtualiZarr) | /xarray/variables | {url} | {code} | PASS/FAIL |
| 5 | Zarr info (VirtualiZarr) | /xarray/info | {url} | {code} | PASS/FAIL |
| 6 | Zarr variables (native) | /xarray/variables | {url} | {code} | PASS/FAIL |
| 6 | Zarr info (native) | /xarray/info | {url} | {code} | PASS/FAIL |
| 19 | Zarr variables (rechunk) | /xarray/variables | {url} | {code} | PASS/FAIL |
| 19 | Zarr info (rechunk) | /xarray/info | {url} | {code} | PASS/FAIL |
| 20 | Split views base table | /vector/collections/{table} | {url} | {code} | PASS/FAIL |
| 20 | Split views base items | /vector/collections/{table}/items | {url} | {code} | PASS/FAIL |
| 20 | Split view NE | /vector/collections/{table}_quadrant_ne/items | {url} | {code} | PASS/FAIL |
| 20 | Split view NW | /vector/collections/{table}_quadrant_nw/items | {url} | {code} | PASS/FAIL |
| 20 | Split view SE | /vector/collections/{table}_quadrant_se/items | {url} | {code} | PASS/FAIL |
| 20 | Split view SW | /vector/collections/{table}_quadrant_sw/items | {url} | {code} | PASS/FAIL |
| 20 | Split views count sum | sum(views) == base | -- | -- | PASS/FAIL |
| 22 | Overwrite guard vector (post-revoke) | /vector/collections/{table}/items | {url} | {code} | PASS/FAIL |
| 23 | Blob preserved (post-unpublish) | /cog/info?url={blob_url} | {url} | {code} | PASS/FAIL |
| 23 | Blob deleted (post-cleanup) | /cog/info?url={blob_url} | {url} | {code} | PASS/FAIL |
| 25 | DDH unpublish vector gone | /vector/collections/{table} | {url} | 404 | PASS/FAIL |

Assessment: {ALL PASS | DEGRADED | UNAVAILABLE}
- **ALL PASS**: Platform is fully operational — ETL data is discoverable and servable
- **DEGRADED**: Some data types not served (e.g. zarr 500 but raster OK)
- **UNAVAILABLE**: Service Layer down or all probes failing

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
| Cartographer | Campaign Brief, endpoint list, `siege_config.json` service URLs | Test data, lifecycle sequences |
| Lancer | Campaign Brief, test data, sequences, `siege_config.json` service URL templates | Cartographer's findings |
| Auditor | Lancer's State Checkpoint Map (incl. service URL probe results). Re-probes TiTiler/TiPG for failures. | Lancer's raw HTTP responses |
| Scribe | All outputs from all agents | Nothing hidden |

**Note**: SIEGE has minimal information asymmetry by design. Its value is speed and completeness, not adversarial competition. For adversarial testing, use WARGAME or TOURNAMENT.
