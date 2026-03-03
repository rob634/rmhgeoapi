# Pipeline 6: TOURNAMENT (Full-Spectrum Adversarial)

**Purpose**: Maximum-coverage adversarial testing across state consistency, edge cases, and interleaving. 4 specialist agents in 2 phases, synthesized by a Tribunal. The most thorough live API testing pipeline.

**Best for**: Full adversarial regression before QA handoff. When you need confidence across all failure domains.

---

## Endpoint Access Rules

Agents test through the **same API surface** that B2B consumers use (`/api/platform/*`).

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Action** | `/api/platform/*` | Pathfinder, Saboteur, Provocateur | Submit, approve, reject, unpublish, status, catalog. The B2B surface. |
| **Verification** | `/api/dbadmin/*`, `/api/storage/*`, `/api/health` | Inspector | Read-only state auditing in Phase 2. Deep verification where Platform API is insufficient. |
| **Setup** | `/api/dbadmin/maintenance`, `/api/stac/nuke` | General (prerequisites only) | Before agents run. Never during tests. |
| **Synthesis** | None (reads other agents' outputs) | Tribunal | Correlates findings, scores, and produces final report. No HTTP calls. |

**Hard rule**: Pathfinder, Saboteur, and Provocateur MUST only use `/api/platform/*` endpoints. Inspector may use admin endpoints for deep verification. Tribunal does not make HTTP calls — it synthesizes. If a test workflow needs an admin endpoint to function, flag it as a finding — a missing B2B capability.

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| General | Define campaign, write 4 specialist briefs | Claude (no subagent) | V0.9_TEST.md, API docs, prior findings |
| Pathfinder | Execute golden-path lifecycles, record expected state | Task (Phase 1, parallel with Saboteur) | Pathfinder Brief |
| Saboteur | Execute adversarial attacks on same namespace | Task (Phase 1, parallel with Pathfinder) | Saboteur Brief |
| Inspector | Audit DB/STAC state against Pathfinder's checkpoints | Task (Phase 2, parallel with Provocateur) | Pathfinder's checkpoint map (NOT Saboteur's log) |
| Provocateur | Test input validation with boundary-value inputs | Task (Phase 2, parallel with Inspector) | Endpoint list only |
| Tribunal | Synthesize all findings, correlate, score, produce report | Task (Phase 3, sequential) | All 4 specialist outputs |

**Maximum parallel agents**: 2 (within each phase)

---

## Flow

```
Target: BASE_URL (Azure endpoint)
    |
    General (Claude — no subagent)
        Reads V0.9_TEST.md, API docs, prior findings
        Outputs: 4 Specialist Briefs
    |
    ======== PHASE 1: MUTATION ========
    |
    +--- Pathfinder (Task) ----+--- Saboteur (Task) --------+  [parallel]
    |    Happy-path executor    |    Adversarial attacker     |
    |    Runs canonical         |    Runs attack sequences    |
    |    lifecycles with tn-    |    on SAME tn- namespace   |
    |    prefix                 |                             |
    |    OUTPUT:                |    OUTPUT:                  |
    |    State Checkpoint Map   |    Attack Log per category  |
    +---------------------------+-----------------------------+
    |
    ======== PHASE 2: AUDIT ========
    |
    +--- Inspector (Task) -----+--- Provocateur (Task) -----+  [parallel]
    |    State auditor          |    Input validation tester  |
    |    Gets Pathfinder's      |    Gets endpoint list ONLY  |
    |    checkpoints            |    No campaign context      |
    |    Does NOT see Saboteur  |                             |
    |    OUTPUT:                |    OUTPUT:                  |
    |    State Audit Report     |    Error Behavior Map       |
    +---------------------------+-----------------------------+
    |
    ======== PHASE 3: JUDGMENT ========
    |
    Tribunal (Task)                                            [sequential]
        Receives ALL 4 outputs
        Correlates Inspector's divergences with Saboteur's attacks
        Scores all findings
        OUTPUT: Final TOURNAMENT Report
```

---

## Campaign Config

Shared config file: `docs/agent_review/siege_config.json`

- **`valid_files`**: Used by Pathfinder for golden-path sequences
- **`invalid_files`**: Used by Saboteur for adversarial attacks and Provocateur for input validation
- **`approval_fixtures`**: Pre-built payloads for approve/reject/conflict attacks
- **`discovery`**: Endpoints for General to verify files exist before launching

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

## Step 1: Play General (No Subagent)

Claude plays General directly. General's job:

1. Read V0.9_TEST.md (sections A–I) and the Saboteur Attack Catalog.
2. Read any prior COMPETE, WARGAME, or SIEGE findings for context.
3. Define the `tn-` namespace for all test data:
   - Raster: `dataset_id=tn-raster-test`, `resource_id=dctest`, `file_name=dctest.tif`, `container_name=rmhazuregeobronze`
   - Vector: `dataset_id=tn-vector-test`, `resource_id=cutlines`, `file_name=0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg`, `container_name=rmhazuregeobronze`
   - NetCDF: `dataset_id=tn-netcdf-test`, `resource_id=spei-ssp370`, `file_name=good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc`, `container_name=wargames`, `data_type=zarr`
4. Write 4 specialist briefs:

### Pathfinder Brief

Contains:
- BASE_URL, bronze container, test data with `tn-` prefix
- Canonical lifecycle sequences to execute
- State checkpoint instructions
- Does NOT contain any information about attacks

### Saboteur Brief

Contains:
- BASE_URL, bronze container, SAME `tn-` test data
- All 5 attack categories with minimum counts
- Reference to the Saboteur Attack Catalog
- Does NOT contain Pathfinder's checkpoint map or expected state

### Inspector Brief

Prepared but NOT dispatched until Phase 1 completes. Will contain:
- Pathfinder's State Checkpoint Map (output of Phase 1)
- Query instructions
- Does NOT contain Saboteur's attack log

### Provocateur Brief

Contains:
- BASE_URL
- Full endpoint list with methods and expected parameters
- Payload attack catalog (P1–P10)
- Does NOT contain any campaign state, test data, or other agent context

---

## Step 2: Dispatch Pathfinder + Saboteur (Phase 1, Parallel)

Dispatch both simultaneously using the Agent tool. Wait for both to complete before Phase 2.

### Pathfinder Instructions

Execute these lifecycle sequences using `tn-` prefix test data. Record state checkpoints after every mutating step.

**Sequence 1: Raster Lifecycle**
1. Submit raster → capture request_id, job_id
2. Poll until completed → capture release_id, asset_id, version_ordinal
3. Approve with version_id="v1" → verify STAC materialized
4. Verify STAC item exists
5. **CHECKPOINT P-R1**: All raster IDs and expected state

**Sequence 2: Vector Lifecycle**
1. Submit vector → capture IDs
2. Poll until completed
3. Approve → verify OGC Features
4. **CHECKPOINT P-V1**: All vector IDs and expected state

**Sequence 3: Multi-Version**
1. Resubmit raster (same dataset_id) → capture v2 IDs
2. Poll → verify ordinal=2
3. Approve v2 with version_id="v2" → verify coexistence
4. **CHECKPOINT P-MV1**: Both v1 and v2 expected state

**Sequence 4: Unpublish**
1. Unpublish v2 → poll until complete
2. **CHECKPOINT P-U1**: v2 removed, v1 preserved

**Sequence 5: NetCDF / VirtualiZarr Lifecycle**
1. Submit NetCDF: `dataset_id=tn-netcdf-test`, `resource_id=spei-ssp370`, `file_name=good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc`, `container_name=wargames`, `data_type=zarr` → capture request_id, job_id
2. Poll until completed (VirtualiZarr pipeline: scan → copy → validate → combine → register — may take longer than raster)
3. Approve with version_id="v1" → verify STAC materialized (zarr items go in STAC)
4. GET `/api/platform/catalog/dataset/{dataset_id}` → verify catalog entry exists
5. GET `/api/platform/catalog/lookup-unified?dataset_id=tn-netcdf-test&resource_id=spei-ssp370` → verify `xarray_urls` present with keys [variables, tiles, tilejson, preview, info, point]. Verify URLs contain TiTiler base hostname and `/xarray/` path. No double container prefix in URLs. → **CHECKPOINT P-Z1-URLS**
6. **CHECKPOINT P-Z1**: Record all IDs, verify job_type=virtualzarr, STAC item present

Note: NetCDF (.nc) routes to the VirtualiZarr pipeline, NOT the raster pipeline.
Submit body must include `"data_type": "zarr"`. Processing may take longer (5-stage pipeline).

**Sequence 6: Rejection Recovery**
1. Submit new raster (different resource_id: `tn-reject-test`)
2. Poll until completed
3. Reject the release
4. Resubmit same resource with `"processing_options": {"overwrite": true}` → should overwrite rejected release (revision increments)
5. Poll until completed
6. Approve
7. **CHECKPOINT P-RJ1**: Rejected release overwritten, new revision approved

CRITICAL: The `overwrite` flag MUST be inside `processing_options`, NOT at the JSON top level.
Pydantic silently ignores extra top-level fields.

**Polling**: Every 10 seconds, max 30 attempts per job.

### Pathfinder Checkpoint Format

```
## Checkpoint {ID}: {description}
AFTER: {step}
EXPECTED STATE:
  Jobs:
    - {job_id} → status={status}
  Releases:
    - {release_id} → approval_state={state}, ordinal={n}
  STAC Items:
    - {item_id} → {exists | not exists}
  Service URLs:
    - raster: titiler_urls keys={list} | MISSING
    - vector: endpoints.features={url}, tiles.tilejson={url} | MISSING
    - zarr: xarray_urls keys={list} | MISSING
  Blob Paths:
    - {path} → {should exist | should not exist}
  Captured IDs:
    request_id={value}
    job_id={value}
    release_id={value}
    asset_id={value}
```

### Pathfinder HTTP Log Format

```
### Step {N}: {description}
REQUEST: {method} {url}
BODY: {json}
RESPONSE: HTTP {code}
BODY: {truncated to 500 chars}
CAPTURED: {key}={value}
EXPECTED: {description}
ACTUAL: {description}
VERDICT: PASS | FAIL | UNEXPECTED
```

---

### Saboteur Instructions

Execute attacks from ALL 5 categories using the **SAME `tn-` namespace**. This creates realistic contention with Pathfinder's lifecycle operations.

**Minimum attacks per category**:

| Category | Min | Priority Attacks |
|----------|-----|------------------|
| TEMPORAL | 3 | T1, T2, T3 |
| DUPLICATION | 3 | D1, D2, D5 |
| IDENTITY | 3 | I1, I2, I5 |
| RACE | 2 | R1, R2 |
| LIFECYCLE | 3 | L1, L4, L5 |
| **Total** | **14** | |

**Timing strategy**: Vary timing relative to Pathfinder's expected progress:
- **Early attacks** (before Pathfinder approves): T1, T5, L1
- **Mid attacks** (while Pathfinder is approving): R1, R2, D2
- **Late attacks** (after Pathfinder approves): T3, D5, L4, L5

**Key rules**:
- MUST use `tn-raster-test`, `tn-vector-test`, and `tn-netcdf-test` as dataset_ids
- For zarr/NetCDF attacks: use `container_name=wargames`, `data_type=zarr`
- MUST record expected outcome (succeed/fail) for every attack
- MUST note any behavior that is surprising or undocumented

### Saboteur Attack Log Format

```
## Attack {CATEGORY}{NUMBER}: {description}
CATEGORY: TEMPORAL | DUPLICATION | IDENTITY | RACE | LIFECYCLE
TIMING: EARLY | MID | LATE
REQUEST: {method} {url}
BODY: {json}
RESPONSE: HTTP {code}
BODY: {truncated to 500 chars}
EXPECTED: {succeed | fail} — {reason}
ACTUAL: {what happened}
VERDICT: EXPECTED | UNEXPECTED | INTERESTING
NOTES: {observations, undocumented behavior}
```

---

## Step 3: Dispatch Inspector + Provocateur (Phase 2, Parallel)

After both Phase 1 agents complete, dispatch Phase 2 agents simultaneously.

**Critical**: Inspector receives Pathfinder's checkpoint map but NOT Saboteur's attack log. This means Saboteur's damage appears as unexplained divergences.

### Inspector Instructions

Receives Pathfinder's State Checkpoint Map and captured IDs. Does NOT know about Saboteur.

**For each checkpoint — Platform API first (B2B surface)**:

```bash
# Release/job state (primary check)
curl -s "${BASE_URL}/api/platform/status/{request_id}"

# STAC item existence
curl -s "${BASE_URL}/api/platform/catalog/item/{collection}/{item_id}"

# Dataset-level view
curl -s "${BASE_URL}/api/platform/catalog/dataset/{dataset_id}"

# Unified catalog lookup (includes service URLs: titiler_urls, xarray_urls, endpoints)
curl -s "${BASE_URL}/api/platform/catalog/lookup-unified?dataset_id={dataset_id}&resource_id={resource_id}"

# Approval status
curl -s "${BASE_URL}/api/platform/approvals/status?stac_item_ids={ids}"

# Recent failures
curl -s "${BASE_URL}/api/platform/failures"
```

**For zarr checkpoints (P-Z1) — additional verification**:
- Verify `xarray_urls` keys exist: [variables, tiles, tilejson, preview, info, point]
- Verify URLs contain TiTiler base hostname and `/xarray/` path
- Verify no double container prefix in URLs (e.g., no `silver-netcdf/silver-netcdf/`)
- Verify STAC collection exists for zarr dataset

**System-wide checks — Platform API**:

```bash
# All platform requests
curl -s "${BASE_URL}/api/platform/status?limit=100"

# All approvals
curl -s "${BASE_URL}/api/platform/approvals"

# Platform health
curl -s "${BASE_URL}/api/platform/health"
```

**Deep verification — admin endpoints (verification only)**:

```bash
# Job detail (when platform/status is insufficient)
curl -s "${BASE_URL}/api/dbadmin/jobs/{job_id}"

# Failed jobs
curl -s "${BASE_URL}/api/dbadmin/jobs?status=failed"

# System diagnostics
curl -s "${BASE_URL}/api/dbadmin/diagnostics/all"

# Database stats
curl -s "${BASE_URL}/api/dbadmin/stats"
```

**What to look for**:
- Checkpoint state matches: expected = actual? → PASS
- Unexpected jobs (not in Pathfinder's log) → flag as ANOMALY
- Unexpected STAC items → flag as ORPHAN
- Failed jobs → flag as CRASH
- Counts that don't add up → flag as DIVERGENCE

### Inspector Output Format

```markdown
## State Audit

### Checkpoint {ID}: {description}
| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Job {job_id} status | {expected} | {actual} | PASS/FAIL |
| Release {release_id} state | {expected} | {actual} | PASS/FAIL |
| STAC item {item_id} | {expected} | {actual} | PASS/FAIL |

## Unexplained Anomalies
{Items found in the system that Pathfinder's checkpoint map doesn't account for}
| Type | ID | Details | Why Unexpected |
...

## Orphaned Artifacts
| Type | ID | Why Orphaned |
...

## System Health
| Metric | Value | Assessment |
|--------|-------|------------|
| Total jobs | {n} | {expected vs actual} |
| Failed jobs | {n} | {0 expected} |
| STAC items | {n} | {expected count} |
| Diagnostics | {clean/issues} | {details} |

## Divergence Summary
| Checkpoint | Expected | Actual | Severity |
...
```

---

### Provocateur Instructions

Provocateur operates **completely independently**. It receives only the endpoint list and fires boundary-value inputs. No knowledge of campaign state, test data, or other agents.

**Execute ALL PAYLOAD attacks (P1–P10) against these endpoints**:

| Target | Method | Purpose |
|--------|--------|---------|
| `/api/platform/submit` | POST | Submission validation |
| `/api/platform/approve` | POST | Approval validation |
| `/api/platform/reject` | POST | Rejection validation |
| `/api/platform/unpublish` | POST | Unpublish validation |

### Payload Attack Catalog

| # | Attack | Payload | Expected Response |
|---|--------|---------|-------------------|
| P1 | Empty body | `{}` | 400 with required fields |
| P2 | Missing required field | `{"dataset_id": "x"}` | 400 with field name |
| P3 | SQL injection | `{"dataset_id": "'; DROP TABLE app.jobs;--", "resource_id": "x", "container_name": "c", "file_name": "f.tif"}` | 400 or safe, NOT 500 |
| P4 | Unicode identifiers | `{"dataset_id": "tn-prov", "resource_id": "émöji🚀", "container_name": "c", "file_name": "f.tif"}` | Reject or sanitize |
| P5 | Long string (10,000 chars) | `{"dataset_id": "aaa...aaa", ...}` | 400 length validation |
| P6 | Wrong Content-Type | text/plain body | 400 or 415 |
| P7 | Invalid JSON | `{not json at all` | 400 |
| P8 | Extra fields | `{...valid..., "admin": true, "role": "superuser"}` | Ignored, no escalation |
| P9 | Null values | `{"release_id": null}` | 400 |
| P10 | Path traversal | `{"file_name": "../../etc/passwd", ...}` | 400 or sanitized |

**Additional Provocateur-designed attacks**:
- Test every POST endpoint with GET (expect 405)
- Test every endpoint with empty Content-Type header
- Test approve with each field missing one at a time
- Test submit with file_name extensions that aren't supported (e.g., `.exe`, `.txt`)

### Provocateur Output Format

```markdown
## Error Behavior Map

### Endpoint: /api/platform/submit

| # | Attack | Input Summary | HTTP Code | Response Body (truncated) | Expected | Verdict |
|---|--------|---------------|-----------|---------------------------|----------|---------|
| P1 | Empty body | `{}` | {code} | {body} | 400 | PASS/FAIL |
...

### Endpoint: /api/platform/approve
...

## Crash Log (500 responses)
| # | Endpoint | Attack | Input | Response |
...

## Missing Validations
| # | Endpoint | Input | What's Missing | Severity |
...

## Inconsistent Error Formats
| Endpoint A | Error Format | Endpoint B | Error Format | Issue |
...
```

---

## Step 4: Dispatch Tribunal (Phase 3, Sequential)

Tribunal receives ALL 4 specialist outputs and General's scoring rubric.

### Tribunal Procedure

**Step 1: Correlation**

Cross-reference Inspector's unexplained anomalies and divergences with Saboteur's attack log:
- For each Inspector anomaly, check if a Saboteur attack explains it
- Anomalies explained by Saboteur attacks = INTERLEAVING DEFECTS
- Anomalies NOT explained by Saboteur = INDEPENDENT BUGS

**Step 2: Classification**

Every finding classified into one of:

| Category | Source | Meaning |
|----------|--------|---------|
| STATE DIVERGENCE | Inspector | Expected ≠ actual (cause unknown or independent) |
| LEAKED ATTACK | Saboteur | Attack should have failed but succeeded |
| INTERLEAVING DEFECT | Inspector + Saboteur correlation | Saboteur action corrupted Pathfinder state |
| INPUT VALIDATION GAP | Provocateur | Missing validation, 500, or insecure response |
| ORPHANED ARTIFACT | Inspector | DB/STAC/blob without parent entity |

**Step 3: Severity Scoring**

| Severity | Definition |
|----------|------------|
| CRITICAL | Data corruption, state inconsistency, security bypass |
| HIGH | Missing validation on mutating endpoint, leaked attack |
| MEDIUM | Wrong HTTP status code, inconsistent error format |
| LOW | Misleading response, undocumented behavior |

**Step 4: Scoreboard**

Count findings per specialist. "Unique" = only this agent's lens could catch it.

**Step 5: Pipeline Chain Recommendations**

For each HIGH or CRITICAL finding, recommend:
- Which code-review pipeline (COMPETE or REFLEXION) to run
- Which files to target
- What scope split to use (for COMPETE)

### Tribunal Output Format

```markdown
# TOURNAMENT Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version}
**Pipeline**: TOURNAMENT

## Executive Summary
{2-3 sentences: what was tested, what was found, overall verdict}

## State Divergences
| # | Checkpoint | Expected | Actual | Caused by Saboteur? | Severity |
...

## Leaked Attacks
| # | Attack | Category | Expected | Actual | Severity |
...

## Interleaving Defects
| # | Saboteur Attack | Inspector Checkpoint | How State Diverged | Severity |
...

## Input Validation Gaps
| # | Endpoint | Attack | Input | HTTP Code | Expected | Severity |
...

## Orphaned Artifacts
| # | Type | ID | Why Orphaned | Severity |
...

## Specialist Scoreboard
| Agent | Findings | Critical | High | Medium | Low | Unique |
|-------|----------|----------|------|--------|-----|--------|
| Pathfinder | (ground truth) | — | — | — | — | — |
| Saboteur | {n} | {n} | {n} | {n} | {n} | {n} |
| Inspector | {n} | {n} | {n} | {n} | {n} | {n} |
| Provocateur | {n} | {n} | {n} | {n} | {n} | {n} |
| **Tribunal** | {n} | {n} | {n} | {n} | {n} | {n} |

## Reproduction Commands
### Finding {N}: {title}
```bash
# From clean state:
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"
# Reproduce:
...
```

## Pipeline Chain Recommendations
| Finding | Severity | Pipeline | Target Files | Scope |
...

## Verdict
{PASS | FAIL | NEEDS INVESTIGATION}
Total findings: {N} ({N} critical, {N} high, {N} medium, {N} low)
```

### Save Output

Save to `docs/agent_review/agent_docs/TOURNAMENT_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Asymmetry Summary

| Agent | Gets | Doesn't Get | What This Reveals |
|-------|------|-------------|-------------------|
| General | Full context | — | Defines the campaign |
| Pathfinder | Canonical workflows only | Saboteur's attack plan | Unbiased ground truth |
| Saboteur | Attack categories + namespace | Pathfinder's checkpoints | Attacks without gaming audit |
| Inspector | Pathfinder's checkpoints only | Saboteur's attacks | Divergences without knowing cause |
| Provocateur | Endpoint list only | Everything else | Input validation in pure isolation |
| Tribunal | ALL outputs | — | Full picture with correlations |

### Key Design Insight: Inspector's Deliberate Blindness

Unlike WARGAME's Oracle (who sees both Blue and Red outputs), TOURNAMENT's Inspector sees ONLY Pathfinder's checkpoints. This means:

1. Saboteur corrupts state → Inspector sees an unexplained divergence
2. Inspector reports it as "expected X, found Y, cause unknown"
3. Tribunal correlates with Saboteur's log to find the cause
4. This two-step process catches issues that a single agent seeing everything might rationalize away

The gap between "what Inspector reports" and "what Tribunal determines" is itself a quality signal. If Inspector reports many anomalies that Tribunal can't correlate to Saboteur's attacks, those are independent bugs — the most valuable findings.
