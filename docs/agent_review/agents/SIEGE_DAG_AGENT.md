# Pipeline 4b: SIEGE-DAG (Epoch 5 DAG Workflow Smoke Test)

**Purpose**: Verify that the Epoch 5 DAG workflow engine works end-to-end — submit, process, approve, catalog, serve — for all data types via `POST /api/platform/submit` with `workflow_engine: "dag"`.

**Best for**: Post-deployment smoke test after DAG changes. This is the **primary** SIEGE pipeline going forward (Epoch 5 only). The original SIEGE pipeline (Epoch 4 CoreMachine) is retained for regression testing during the strangler fig migration only.

**Scope**: Tests DAG routing, workflow completion, STAC materialization, catalog discovery, and service URL probes for raster, vector, zarr (NC and native), and unpublish workflows. Approval lifecycle sequences (reject, revoke, overwrite) are NOT duplicated — they test Release/Asset state machine logic which is engine-independent.

---

## Key Differences from SIEGE (Epoch 4)

| Aspect | SIEGE (Epoch 4) | SIEGE-DAG (Epoch 5) |
|--------|-----------------|---------------------|
| **Submit body** | No `workflow_engine` param | `"workflow_engine": "dag"` in every submit |
| **Namespace prefix** | `sg-` | `sg-dag-` |
| **Status values** | queued, processing, completed, failed | pending, running, completed, failed |
| **Progress block** | Stage-based (stage N/total_stages) | Task-based (tasks_done/tasks_total + tasks_by_status) |
| **Detail block** | `workflow_engine: "coremachine"`, checkpoints | `workflow_engine: "dag"`, workflow_name, DAG URLs |
| **Services block** | Identical | Identical (same Release table) |
| **Workflows tested** | CoreMachine job types | `process_raster`, `vector_docker_etl`, `ingest_zarr`, `unpublish_raster`, `unpublish_vector` |
| **Sequences** | 26 (full lifecycle + validation + edge cases) | 10 (DAG routing + workflow completion + service parity) |

---

## Endpoint Access Rules

Identical to SIEGE — all action through `/api/platform/*`, verification via admin endpoints.

**Additional DAG-specific verification endpoint**:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/dag/runs/{run_id}` | GET | DAG run detail (tasks, status, timings) |
| `/api/dag/runs/{run_id}/tasks` | GET | Individual task breakdown for a DAG run |

---

## Agent Roles

Same 5-agent structure as SIEGE: Sentinel, Cartographer, Lancer, Auditor, Scribe.

**Differences**:
- Sentinel uses `sg-dag-` namespace prefix
- Lancer adds DAG-specific assertions (progress block shape, workflow_name)
- Auditor verifies DAG tables (`workflow_runs`, `workflow_tasks`) alongside Release/Asset state
- Cartographer probes are identical (same platform endpoints)

---

## Campaign Config

Uses the same `siege_config.json` for test fixtures, service contracts, and approval payloads. No separate config file needed.

**Sentinel overrides**:
- Namespace prefix: `sg-dag-` (not `sg-`)
- All submit bodies include `"workflow_engine": "dag"`
- Test data table includes expected `workflow_name` for each fixture

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

# DAG Brain health check (CRITICAL — DAG Brain must be running)
# DAG Brain is rmhdagmaster — verify it's polling for work
curl -sf "${BASE_URL}/api/platform/health"
```

**DAG-specific prerequisite**: DAG Brain (`rmhdagmaster`) and Docker Worker (`rmhheavyapi`) must both be deployed and healthy. DAG Brain polls `workflow_runs` for pending runs; Docker Worker executes the handlers. If either is down, DAG runs will stay in `pending` state indefinitely.

---

## Step 1: Play Sentinel (No Subagent)

Sentinel defines the campaign using `sg-dag-` prefixed identifiers. Each row maps directly to a `siege_config.json → valid_files` entry.

| Seq | Config Fixture Key | Container | File | Size | dataset_id | resource_id | data_type | Expected workflow_name |
|-----|-------------------|-----------|------|------|-----------|-------------|-----------|----------------------|
| D1 | `raster` | `rmhazuregeobronze` | `dctest.tif` | 26 MB | `sg-dag-raster-test` | `dctest` | (auto: raster) | `process_raster` |
| D2 | `vector` | `rmhazuregeobronze` | `0403c87a-…/cutlines.gpkg` | 6 MB | `sg-dag-vector-test` | `cutlines` | (auto: vector) | `vector_docker_etl` |
| D3 | `netcdf_climate` | `wargames` | `good-data/climatology-spei12-…-ssp370_…_2040-2059.nc` | 4 MB | `sg-dag-netcdf-test` | `spei-ssp370` | `zarr` (override) | `ingest_zarr` |
| D4 | `zarr_cmip6_tasmax_quick` | `wargames` | `good-data/cmip6-tasmax-quick.zarr` | 10 MB | `sg-dag-zarr-test` | `cmip6-tasmax-q` | `zarr` (override) | `ingest_zarr` |
| D5 | `raster_multiband` | `wargames` | `good-data/n00-n05_w005-w010_fluvial-defended_2020.tif` | 11 MB | `sg-dag-multiband-test` | `fathom-flood` | (auto: raster) | `process_raster` |
| D9 | `raster` | `rmhazuregeobronze` | `dctest.tif` | 26 MB | `sg-dag-progress-test` | `dctest` | (auto: raster) | `process_raster` |
| D10 | (invalid) | `rmhazuregeobronze` | `this_file_does_not_exist.tif` | 0 | `sg-dag-error-test` | `ghost` | (auto: raster) | `process_raster` |

**Notes**:
- `.nc` and `.zarr` extensions auto-detect `data_type=zarr` — do NOT include `data_type` in submit body (Pydantic `extra='forbid'` rejects it)
- D6 (unpublish raster), D7 (unpublish vector), and D8 (unpublish zarr) reuse outputs from D1, D2, and D3
- All submits include `"workflow_engine": "dag"` — no Epoch 4 CoreMachine paths
- All files are under 26 MB — quick profile only

---

## Step 2: Dispatch Cartographer

Identical to SIEGE — probe all platform endpoints. No changes needed for DAG.

Additionally probe DAG-specific endpoint:

| Endpoint | Method | Probe | Expected |
|----------|--------|-------|----------|
| `/api/dag/runs?limit=1` | GET | List runs | 200, JSON array |

---

## Step 3: Dispatch Lancer

### DAG-Specific Assertion Helpers

Every sequence in SIEGE-DAG uses these shared assertion patterns:

**ASSERT DAG PROGRESS** (used in every poll-until-completed step):
```
GET /api/platform/status/{request_id}?detail=full
ASSERT:
  - progress.workflow_engine == "dag"
  - progress.workflow_name == {expected_workflow_name}
  - progress.tasks_total > 0
  - progress.tasks_by_status exists (dict)
  - When completed: progress.tasks_done == progress.tasks_total
  - When completed: progress.percent_complete == 100
```

**ASSERT DAG DETAIL** (used after completion, with `?detail=full`):
```
GET /api/platform/status/{request_id}?detail=full
ASSERT:
  - detail.workflow_engine == "dag"
  - detail.workflow_name == {expected_workflow_name}
  - detail.urls.dag_run contains "/api/dag/runs/"
  - detail.task_summary exists
  - detail.started_at is not null
  - detail.completed_at is not null
```

**ASSERT TASK BREAKDOWN** (verification endpoint — Auditor uses this):
```
GET /api/dag/runs/{run_id}/tasks
ASSERT:
  - All tasks in "completed" or "skipped" status
  - No tasks in "failed" or "pending" status
  - Task count matches progress.tasks_total
```

---

### Lifecycle Sequences

**Sequence D1: Raster Lifecycle (DAG)**

Tests `process_raster.yaml` — the 12-node raster DAG with conditional tiling + fan-out + fan-in + STAC.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with raster fixture + `"workflow_engine": "dag"` | 202, request_id, job_id (this is the DAG run_id) |
| 2 | **ASSERT DAG ROUTING**: Verify job_id is 64-char (DAG run_id format, not UUID) | run_id format |
| 3 | Poll `/api/platform/status/{request_id}` until completed (timeout 10 min) | processing_status=completed |
| 4 | **ASSERT DAG PROGRESS**: workflow_name=`process_raster`, all tasks done | Progress shape correct |
| 5 | **ASSERT STATUS SERVICES** (pre-approval): Same assertions as SIEGE S1 step 3 — `services.service_url` contains `/cog/WebMercatorQuad/tilejson.json`, etc. | Services block identical to Epoch 4 shape |
| 6 | POST `/api/platform/approve` (version_id="v1") | STAC materialized |
| 7 | **ASSERT STATUS SERVICES** (post-approval): `stac_collection` and `stac_item` populated | STAC URLs present |
| 8 | GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` | `raster` block with `tiles` keys present |
| 9 | **PROBE SERVICE URLS**: GET `{raster.tiles.info}` (200), `{raster.tiles.preview}` (200, image), `{raster.tiles.tilejson}` (200, JSON with `tiles` array) | Service Layer serves DAG-produced COG |
| 10 | **ASSERT DAG DETAIL**: GET `/api/platform/status/{request_id}?detail=full` → verify detail block | DAG detail shape correct |

**CHECKPOINT DR1**: DAG raster lifecycle complete. Services and catalog identical to Epoch 4.

---

**Sequence D2: Vector Lifecycle (DAG)**

Tests `vector_docker_etl.yaml` — 6-node vector DAG with conditional skip.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with vector fixture + `"workflow_engine": "dag"` | 202, request_id, run_id |
| 2 | Poll until completed (timeout 5 min) | processing_status=completed |
| 3 | **ASSERT DAG PROGRESS**: workflow_name=`vector_docker_etl`, all tasks done | Progress shape correct |
| 4 | **ASSERT STATUS SERVICES** (pre-approval): `services.service_url` contains `/collections/geo.`, `tiles` contains `/{z}/{x}/{y}.pbf` | Vector services shape |
| 5 | POST `/api/platform/approve` (version_id="v1") | OGC Features live |
| 6 | GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` | `endpoints.features` and `tiles.tilejson` present |
| 7 | **PROBE SERVICE URLS**: GET `{tipg_base}/collections/{schema}.{table_name}` (200), GET `.../items?limit=1` (200, FeatureCollection) | TiPG serves DAG-produced table |
| 8 | **ASSERT DAG DETAIL**: detail.workflow_engine == "dag", workflow_name == "vector_docker_etl" | DAG detail shape |

**CHECKPOINT DV1**: DAG vector lifecycle complete. PostGIS table + TiPG serving identical to Epoch 4.

---

**Sequence D3: NetCDF Lifecycle (DAG)**

Tests `ingest_zarr.yaml` NC path — 9-node DAG with conditional NC/Zarr routing + pyramid generation.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with `netcdf_climate` fixture + `"data_type": "zarr"` + `"workflow_engine": "dag"`, container_name=`wargames` | 202, request_id, run_id |
| 2 | Poll until completed (timeout 10 min — pyramid generation is slow) | processing_status=completed |
| 3 | **ASSERT DAG PROGRESS**: workflow_name=`ingest_zarr`, all tasks done. Verify `tasks_by_status` shows `completed` and optionally `skipped` (Zarr-path nodes skip on NC input) | Progress with skipped tasks |
| 4 | **ASSERT STATUS SERVICES** (pre-approval): `services.service_url` contains `/xarray/WebMercatorQuad/tilejson.json`, `services.variables` contains `/xarray/variables`, `services.preview` contains `/xarray/preview.png` | Zarr services shape |
| 5 | POST `/api/platform/approve` (version_id="v1") | STAC materialized |
| 6 | **ASSERT STATUS SERVICES** (post-approval): `stac_collection` and `stac_item` populated | STAC URLs present |
| 7 | GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` | `xarray_urls` present with keys [variables, tiles, tilejson, preview, info, point] |
| 8 | **PROBE SERVICE URLS**: GET `{xarray_urls.variables}` (200, JSON array). If 200: GET `{xarray_urls.info}&variable={first_var}` (200, JSON metadata) | TiTiler xarray serves DAG-produced pyramid |
| 9 | **ASSERT DAG DETAIL**: workflow_name == "ingest_zarr", task_summary shows NC path nodes completed | DAG detail shape |

**CHECKPOINT DZ1**: DAG NetCDF lifecycle complete. Pyramid store in silver-zarr, STAC materialized, xarray serving.

---

**Sequence D4: Native Zarr Lifecycle (DAG)**

Tests `ingest_zarr.yaml` Zarr path — same workflow but Zarr-specific nodes fire instead of NC nodes.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with `zarr_cmip6_tasmax_quick` fixture + `"data_type": "zarr"` + `"workflow_engine": "dag"`, container_name=`wargames` | 202, request_id, run_id |
| 2 | Poll until completed (timeout 15 min — rechunk + pyramid) | processing_status=completed |
| 3 | **ASSERT DAG PROGRESS**: workflow_name=`ingest_zarr`, all tasks done. Verify `tasks_by_status` shows `completed` and optionally `skipped` (NC-path nodes skip on Zarr input) | Progress with skipped tasks |
| 4 | **ASSERT STATUS SERVICES** (pre-approval): Same zarr shape as D3 step 4 | Zarr services shape |
| 5 | POST `/api/platform/approve` (version_id="v1") | STAC materialized |
| 6 | GET `/api/platform/catalog/lookup?dataset_id={ds}&resource_id={rs}` | `xarray_urls` present |
| 7 | **PROBE SERVICE URLS**: GET `{xarray_urls.variables}` (200), GET `{xarray_urls.info}&variable={first_var}` (200) | TiTiler xarray serves DAG-produced Zarr |
| 8 | **ASSERT DAG DETAIL**: workflow_name == "ingest_zarr", Zarr-path nodes completed, NC-path nodes skipped | DAG detail shape |

**CHECKPOINT DNZ1**: DAG native Zarr lifecycle complete. Rechunk + pyramid + STAC all via DAG.

---

**Sequence D5: Multiband Raster (DAG)**

Tests `process_raster.yaml` with 8-band FATHOM flood raster — validates DAG handles complex raster inputs.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with `raster_multiband` fixture (wargames container) + `"workflow_engine": "dag"` | 202, request_id, run_id |
| 2 | Poll until completed (timeout 10 min) | processing_status=completed |
| 3 | **ASSERT DAG PROGRESS**: workflow_name=`process_raster`, all tasks done | Progress shape correct |
| 4 | **ASSERT STATUS SERVICES** (pre-approval): raster services shape | Services block correct |
| 5 | POST `/api/platform/approve` (version_id="v1") | STAC materialized |
| 6 | **PROBE SERVICE URLS**: GET `{raster.tiles.info}` (200) — verify `band_metadata` shows 8 bands | Multiband preserved through DAG |

**CHECKPOINT DMB1**: DAG handles multiband raster correctly.

---

**Sequence D6: Unpublish Raster (DAG)**

Tests `unpublish_raster.yaml` — 4-node DAG: task + fan-out + fan-in + audit.

Depends on: D1 (raster approved and served).

**Prerequisite**: `/api/platform/unpublish` must accept `workflow_engine: "dag"` and route to DAG unpublish workflow. If not yet wired, this sequence will FAIL at step 1 — record as BLOCKED and note that unpublish DAG wiring is required.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/unpublish` with D1 identifiers + `"workflow_engine": "dag"`, `dry_run=false`, `force_approved=true` | 202, unpublish run_id (64-char DAG format) |
| 2 | Poll unpublish job until completed (timeout 5 min) | processing_status=completed |
| 3 | **ASSERT DAG PROGRESS**: workflow_name=`unpublish_raster`, all tasks done | DAG unpublish completed |
| 4 | GET `/api/platform/status/{D1_request_id}` | `is_served=false`, STAC item removed |
| 5 | **PROBE BLOB POST-UNPUBLISH**: GET `{raster.tiles.info}` from D1 | Expect 4xx — blob deleted |
| 6 | **ASSERT DAG DETAIL**: detail.workflow_engine == "dag", workflow_name == "unpublish_raster" | DAG detail shape |

**CHECKPOINT DUR1**: DAG raster unpublish complete. STAC item removed, blobs deleted.

---

**Sequence D7: Unpublish Vector (DAG)**

Tests `unpublish_vector.yaml` — 3-node linear DAG.

Depends on: D2 (vector approved and served).

**Prerequisite**: Same as D6 — unpublish must accept `workflow_engine: "dag"`.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/unpublish` with D2 identifiers + `"workflow_engine": "dag"`, `dry_run=false`, `force_approved=true` | 202, unpublish run_id |
| 2 | Poll until completed (timeout 5 min) | processing_status=completed |
| 3 | **ASSERT DAG PROGRESS**: workflow_name=`unpublish_vector`, all tasks done | DAG unpublish completed |
| 4 | GET `{tipg_base}/collections/{schema}.{table_name}` | Expect 404 — table dropped |
| 5 | **ASSERT DAG DETAIL**: workflow_name == "unpublish_vector" | DAG detail shape |

**CHECKPOINT DUV1**: DAG vector unpublish complete. PostGIS table dropped, metadata cleaned.

---

**Sequence D8: Unpublish Zarr (DAG)**

Tests `unpublish_zarr.yaml` — unpublish a DAG-produced zarr asset (pyramid store + STAC + zarr_metadata).

Depends on: D3 (NetCDF→Zarr approved and served).

**Prerequisite**: `unpublish_zarr.yaml` workflow must exist and be wired to the unpublish endpoint. If not yet built, this sequence will FAIL — record as BLOCKED.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/unpublish` with D3 identifiers + `"workflow_engine": "dag"`, `data_type=zarr`, `dry_run=true` | 200, dry_run preview shows what would be deleted |
| 2 | Verify dry_run response includes: zarr_metadata row, STAC item, pyramid store blobs | Dry-run scope correct |
| 3 | POST `/api/platform/unpublish` with same identifiers + `dry_run=false`, `force_approved=true`, `"workflow_engine": "dag"` | 202, unpublish run_id |
| 4 | Poll until completed (timeout 5 min) | processing_status=completed |
| 5 | **ASSERT DAG PROGRESS**: workflow_name=`unpublish_zarr`, all tasks done | DAG unpublish completed |
| 6 | GET `/api/platform/catalog/lookup?dataset_id={D3_ds}&resource_id={D3_rs}` | `found: false` or stac removed |
| 7 | Verify `zarr_metadata` row deleted: query `app.zarr_metadata WHERE zarr_id = '{D3_stac_item_id}'` via dbadmin | Row gone |
| 8 | **ASSERT DAG DETAIL**: workflow_name == "unpublish_zarr" | DAG detail shape |

**CHECKPOINT DUZ1**: DAG zarr unpublish complete. Pyramid store blobs deleted, STAC item removed, zarr_metadata row cleaned.

---

**Sequence D9: DAG Progress Polling (Timing)**

Tests that progress reporting works correctly during a DAG run — polls rapidly to capture in-flight state.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with raster fixture + `"workflow_engine": "dag"` (fresh dataset_id `sg-dag-progress-test`) | 202, run_id |
| 2 | **RAPID POLL** (every 2s, max 30 iterations): GET `/api/platform/status/{request_id}` | Capture progress snapshots |
| 3 | Verify at least one snapshot shows `processing_status` in `running` state (not just `pending` → `completed`) | DAG Brain picked up the run |
| 4 | Verify progress.percent_complete increased monotonically across snapshots | Progress never goes backward |
| 5 | Verify tasks_by_status changed across snapshots (tasks moved from pending to completed) | Task progression visible |
| 6 | Final snapshot: processing_status=completed, percent_complete=100 | Run completed |

**CHECKPOINT DPROG1**: DAG progress reporting is live and monotonically increasing.

---

**Sequence D10: DAG Error Handling**

Tests that DAG runs fail gracefully with informative errors — uses invalid inputs that should cause handler failures.

| Step | Action | Verify |
|------|--------|--------|
| 1 | POST `/api/platform/submit` with `"workflow_engine": "dag"`, valid raster body but `file_name` points to nonexistent file in bronze | 202 accepted (validation is async in DAG) |
| 2 | Poll until completed or failed (timeout 5 min) | processing_status=failed |
| 3 | GET `/api/platform/status/{request_id}` | `error` field present, error_type is informative |
| 4 | **ASSERT DAG DETAIL**: detail.task_summary shows which task failed | Failed task identified |
| 5 | Verify no tasks are stuck in `running` status after run completes | Clean failure state |

**CHECKPOINT DERR1**: DAG fails gracefully. Error propagated to status. Failed task identifiable.

---

## Step 4: Dispatch Auditor

Auditor receives Lancer's State Checkpoint Map and verifies:

### Standard Checks (same as SIEGE)
- Release records: approval_state, version_ordinal, is_latest, is_served
- Asset records: data_type, processing_status
- STAC items: exist where expected, absent where expected
- Blob storage: COGs/Zarr stores exist in silver containers

### DAG-Specific Checks

| Check | Query | Expected |
|-------|-------|----------|
| Workflow runs created | `SELECT * FROM app.workflow_runs WHERE run_id IN ({captured_run_ids})` | One row per DAG submission, status=completed |
| All tasks completed | `SELECT status, COUNT(*) FROM app.workflow_tasks WHERE run_id = '{id}' GROUP BY status` | Only `completed` and `skipped` (no `failed`, `pending`) |
| Task timings | `SELECT task_name, started_at, completed_at FROM app.workflow_tasks WHERE run_id = '{id}'` | All have non-null started_at and completed_at |
| Workflow timing | `SELECT started_at, completed_at, (completed_at - started_at) as duration FROM app.workflow_runs WHERE run_id = '{id}'` | Duration > 0, completed_at > started_at |
| Platform request linked | `SELECT request_id FROM app.workflow_runs WHERE run_id = '{id}'` | Matches captured request_id from submit |
| Release linked | `SELECT release_id FROM app.workflow_runs WHERE run_id = '{id}'` | Matches release from status response |
| No orphan tasks | `SELECT COUNT(*) FROM app.workflow_tasks t WHERE NOT EXISTS (SELECT 1 FROM app.workflow_runs r WHERE r.run_id = t.run_id)` | 0 |
| Zarr metadata (D3/D4) | `SELECT * FROM app.zarr_metadata WHERE zarr_id = '{stac_item_id}'` | Row exists with variables, dimensions, stac_item_json |

---

## Step 5: Dispatch Scribe

Scribe synthesizes outputs into the SIEGE-DAG report.

### Report Template

```markdown
# SIEGE-DAG Run {N} — Epoch 5 DAG Workflow Smoke Test

**Date**: {DD MMM YYYY}
**Version**: {version from /api/health}
**Profile**: quick
**Agent**: Lancer (Claude Opus 4.6)
**Duration**: ~{N} minutes

---

## Summary

| Metric | Value |
|--------|-------|
| Total Steps | {N} |
| Pass | {N} |
| Fail | {N} |
| Unexpected | {N} |
| Skip | {N} |
| **Pass Rate** | **{N}/{N} = {pct}%** |

---

## Sequence Results

| Seq | Name | Workflow | Steps | Pass | Fail | Notes |
|-----|------|----------|-------|------|------|-------|
| D1 | Raster Lifecycle | process_raster | {N} | {N} | {N} | |
| D2 | Vector Lifecycle | vector_docker_etl | {N} | {N} | {N} | |
| D3 | NetCDF Lifecycle | ingest_zarr (NC) | {N} | {N} | {N} | |
| D4 | Native Zarr Lifecycle | ingest_zarr (Zarr) | {N} | {N} | {N} | |
| D5 | Multiband Raster | process_raster | {N} | {N} | {N} | |
| D6 | Unpublish Raster | unpublish_raster | {N} | {N} | {N} | |
| D7 | Unpublish Vector | unpublish_vector | {N} | {N} | {N} | |
| D8 | DAG Progress Polling | process_raster | {N} | {N} | {N} | |
| D9 | DAG Error Handling | (failure path) | {N} | {N} | {N} | |
| D10 | DAG vs CoreMachine Parity | process_raster | {N} | {N} | {N} | |

---

## DAG-Specific Metrics

| Workflow | Avg Duration (s) | Tasks Total | Tasks Completed | Tasks Skipped |
|----------|-----------------|-------------|-----------------|---------------|
| process_raster | {N} | {N} | {N} | {N} |
| vector_docker_etl | {N} | {N} | {N} | {N} |
| ingest_zarr (NC) | {N} | {N} | {N} | {N} |
| ingest_zarr (Zarr) | {N} | {N} | {N} | {N} |
| unpublish_raster | {N} | {N} | {N} | {N} |
| unpublish_vector | {N} | {N} | {N} | {N} |

## Parity Assessment

| Aspect | Epoch 4 | Epoch 5 DAG | Parity |
|--------|---------|-------------|--------|
| Services block shape | {keys} | {keys} | MATCH / DIVERGE |
| Catalog response shape | {keys} | {keys} | MATCH / DIVERGE |
| COG/Zarr serveable | {yes/no} | {yes/no} | MATCH / DIVERGE |
| STAC materialization | {yes/no} | {yes/no} | MATCH / DIVERGE |

## Findings

{severity-categorized findings}

## Auditor State Verification

{DAG-specific checks from Step 4}
```

---

## Lancer Submit Body Templates

### Raster Submit (D1, D5)
```json
{
    "dataset_id": "sg-dag-raster-test",
    "resource_id": "dctest",
    "file_name": "dctest.tif",
    "container_name": "rmhazuregeobronze",
    "workflow_engine": "dag"
}
```

### Vector Submit (D2)
```json
{
    "dataset_id": "sg-dag-vector-test",
    "resource_id": "cutlines",
    "file_name": "0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg",
    "container_name": "rmhazuregeobronze",
    "workflow_engine": "dag"
}
```

### NetCDF Submit (D3)
```json
{
    "dataset_id": "sg-dag-netcdf-test",
    "resource_id": "spei-ssp370",
    "file_name": "good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc",
    "container_name": "wargames",
    "workflow_engine": "dag"
}
```
Note: `.nc` extension auto-detects `data_type=zarr`. Do NOT include `data_type` (Pydantic rejects it).

### Native Zarr Submit (D4)
```json
{
    "dataset_id": "sg-dag-zarr-test",
    "resource_id": "cmip6-tasmax-q",
    "file_name": "good-data/cmip6-tasmax-quick.zarr",
    "container_name": "wargames",
    "workflow_engine": "dag"
}
```
Note: `.zarr` extension auto-detects `data_type=zarr`.

### Multiband Raster Submit (D5)
```json
{
    "dataset_id": "sg-dag-multiband-test",
    "resource_id": "fathom-flood",
    "file_name": "good-data/n00-n05_w005-w010_fluvial-defended_2020.tif",
    "container_name": "wargames",
    "workflow_engine": "dag"
}
```

### Unpublish Submit (D6, D7, D8)
```json
{
    "dataset_id": "{from prior sequence}",
    "resource_id": "{from prior sequence}",
    "version_id": "v1",
    "data_type": "{raster|vector|zarr}",
    "dry_run": false,
    "force_approved": true,
    "workflow_engine": "dag"
}
```

### Approval Payload (all sequences)
```json
{
    "dataset_id": "{from submit}",
    "resource_id": "{from submit}",
    "reviewer": "siege-dag-qa@example.com",
    "clearance_level": "ouo",
    "version_id": "v1"
}
```

---

## Lancer Checkpoint Format

Same as SIEGE, with additional DAG fields:

```markdown
## Checkpoint {ID}: {description}
AFTER: {step description}
EXPECTED STATE:
  DAG Run:
    - run_id={value} → status={completed|failed}
    - workflow_name={expected}
    - tasks_total={N}, tasks_done={N}, tasks_skipped={N}
  Jobs:
    - (CoreMachine job may NOT exist — DAG uses workflow_runs table)
  Releases:
    - {release_id} → approval_state={state}, version_ordinal={n}
  STAC Items:
    - {item_id} → {exists | not exists}
  Services Block:
    - service_url={url}
    - preview={url}
    - stac_collection={url | null}
    - stac_item={url | null}
    - viewer={url}
    - tiles={url}
    - variables={url} (zarr only)
  Service URL Probes:
    - {probe_name}: {url} → HTTP {code}, {Content-Type} → {PASS|FAIL|ERROR}
  Captured IDs:
    - request_id={value}
    - run_id={value} (NOT job_id — DAG uses run_id)
    - release_id={value}
    - asset_id={value}
```

---

## Run Profiles

| Profile | Sequences | Est. Duration | Notes |
|---------|-----------|---------------|-------|
| **quick** | D1-D10 (all) | 20-30 min | Default fixtures (all < 26 MB) |
| **full** | D1-D10 (all) | 60-120 min | Override raster→462 MB DEM, zarr→1.5 GB CMIP6. Same fixture_overrides as SIEGE. |

---

## Known Issues and Required Fixes (28 MAR 2026)

Identified via SIEGE-DAG Run 1. Root causes investigated, fixes proposed.

### F-1: Status `services` block null for DAG runs (MEDIUM)

**Root cause**: `trigger_platform_status.py` resolves the top-level `release` via `ReleaseRepository().get_by_job_id(platform_request.job_id)`. For DAG runs, `job_id` is a 64-char `run_id` that exists in `workflow_runs`, not `jobs`. The query finds nothing, so `release=None` → `services=None`.

**Data is correct**: `versions[]` array builds via `list_by_asset(asset_id)` which works fine.

**Fix**: After `dag_run = WorkflowRunRepository().get_by_run_id(job_id)` succeeds (line ~510), add:
```python
if not release and dag_run.release_id:
    release = ReleaseRepository().get_by_id(dag_run.release_id)
```
**File**: `triggers/trigger_platform_status.py` ~line 510
**Impact**: 3 lines. Services block will populate for DAG runs.

### F-3: Catalog `xarray_urls` empty for zarr assets (MEDIUM)

**Root cause**: `platform_catalog_service.py` builds xarray URLs from `release.stac_item_json`. The Epoch 5 `zarr_register_metadata` handler (in `services/zarr/handler_register.py`) writes `stac_item_json` to the `zarr_metadata` table but does NOT update `asset_releases.stac_item_json`. The Epoch 4 `ingest_zarr_register` handler (in `services/handler_ingest_zarr.py` line 649) correctly calls `release_repo.update_stac_item_json(release_id, stac_item)`.

**Fix**: In `services/zarr/handler_register.py`, after the `zarr_repo.upsert()` call (~line 240), add:
```python
release_id = params.get('release_id')
if release_id:
    from infrastructure.release_repository import ReleaseRepository
    ReleaseRepository().update_stac_item_json(release_id, stac_item_json)
```
**File**: `services/zarr/handler_register.py` ~line 240
**Impact**: 4 lines. Catalog xarray_urls will populate.

### F-4: `download_to_mount` fails for native Zarr stores (HIGH)

**Root cause**: `infrastructure/etl_mount.py` `download_prefix_to_mount()` detects file vs directory by checking if the last path segment contains a dot. `store.zarr` contains a dot, so it's misclassified as a single file. The download logic then corrupts the Zarr directory structure.

**Epoch 4 approach**: Epoch 4's `ingest_zarr_validate` reads Zarr directly from cloud storage via `xr.open_zarr("az://...", storage_options=...)` — no local download needed.

**Fix (Option A — recommended)**: Skip download for `.zarr` inputs. Modify `zarr_download_to_mount` handler to detect `.zarr` suffix and return the cloud URL as-is. Modify downstream handlers (`validate_source`, `rechunk`, `generate_pyramid`) to accept cloud URLs via `az://` + `storage_options`.

**Fix (Option B — quick)**: Add `.zarr` exception to `download_prefix_to_mount()`:
```python
if prefix.rstrip("/").endswith(".zarr"):
    strip_prefix = prefix.rsplit("/", 1)[0] + "/" if "/" in prefix else ""
```
**Disadvantage**: Downloads entire store to mount (slow, storage-limited).

### F-5: Unpublish endpoint rejects `workflow_engine: "dag"` (MEDIUM)

**Root cause**: `/api/platform/unpublish` handler validates params against a whitelist that doesn't include `workflow_engine`. No DAG routing code exists in the unpublish handler.

**Fix**: Same pattern as the submit handler — pop `workflow_engine` before validation, then route to `create_and_submit_dag_run()` with `unpublish_raster` / `unpublish_vector` / `unpublish_zarr` workflow.

**Prerequisite**: `unpublish_zarr.yaml` workflow must be created first.

### Other Known Issues

- **`asset_releases.job_id` FK violation**: DAG `run_id` not in `jobs` table. Non-blocking, logged as CRITICAL. Auditor should note as KNOWN.
- **Spatial extent fallback**: Pyramid stores use global bbox `[-180, -90, 180, 90]`. Zarr STAC items may show global bbox.
- **TiPG cache delay**: New PostGIS tables take time to appear in TiPG collection list. Pre-existing, not DAG-specific.
