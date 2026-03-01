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
| `/api/platform/validate` | OPTIONS or GET | Check if live | 405 or method listing |
| `/api/platform/approvals` | GET | No params | 200 |
| `/api/platform/catalog/lookup` | GET | Missing params | 400 or empty |
| `/api/platform/failures` | GET | No params | 200 |
| `/api/platform/lineage/{random-uuid}` | GET | Random UUID | 404 or empty |
| `/api/platforms` | GET | No params | 200 |

**Verification endpoints (admin — health check only)**:

| Endpoint | Method | Probe | Expected |
|----------|--------|-------|----------|
| `/api/health` | GET | No params | 200 |
| `/api/dbadmin/stats` | GET | No params | 200 |
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
5. **CHECKPOINT R1**: Record all IDs and expected DB/STAC state

**Sequence 2: Vector Lifecycle**
1. POST `/api/platform/submit` (vector) → capture IDs
2. Poll until completed → capture release_id
3. POST `/api/platform/approve` → verify OGC Features
4. **CHECKPOINT V1**: Record all IDs

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
5. **CHECKPOINT Z1**: Record all IDs, verify job_type=virtualzarr, STAC item present

Note: NetCDF (.nc) routes to the VirtualiZarr pipeline, NOT the raster pipeline.
Use `data_type_override: "zarr"` from siege_config.json. Submit body must include
`"data_type": "zarr"`. Processing may take longer than raster (5-stage pipeline).

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
| Overall stats | `/api/dbadmin/stats` | No unexpected counts |
| Orphaned tasks | `/api/dbadmin/diagnostics/all` | Clean diagnostics |

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
```

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
| Raster Lifecycle | {n} | {n} | {n} | {n} |
| Vector Lifecycle | {n} | {n} | {n} | {n} |
| Multi-Version | {n} | {n} | {n} | {n} |
| Unpublish | {n} | {n} | {n} | {n} |
| NetCDF/VirtualiZarr | {n} | {n} | {n} | {n} |

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
| Auditor | Lancer's State Checkpoint Map, captured IDs | Lancer's raw HTTP responses |
| Scribe | All outputs from all agents | Nothing hidden |

**Note**: SIEGE has minimal information asymmetry by design. Its value is speed and completeness, not adversarial competition. For adversarial testing, use WARGAME or TOURNAMENT.
