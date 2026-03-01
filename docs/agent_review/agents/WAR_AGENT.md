# Pipeline 5: WARGAME (Red vs Blue State Divergence)

**Purpose**: Focused adversarial testing of state consistency. Red attacks the system while Blue establishes ground truth on the SAME dataset namespace. Oracle catches where system state diverges from expectations.

**Best for**: Pre-release state integrity check. Chaining from COMPETE findings to verify live behavior.

---

## Endpoint Access Rules

Agents test through the **same API surface** that B2B consumers use (`/api/platform/*`).

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Action** | `/api/platform/*` | Blue, Red | Submit, approve, reject, unpublish, status, catalog. The B2B surface. |
| **Verification** | `/api/dbadmin/*`, `/api/storage/*`, `/api/health` | Oracle, Coroner | Read-only state auditing after the battle phase. |
| **Setup** | `/api/dbadmin/maintenance`, `/api/stac/nuke` | Strategist (prerequisites only) | Before agents run. Never during tests. |

**Hard rule**: Blue and Red MUST only use `/api/platform/*` endpoints. If a workflow requires an admin endpoint, that's a finding (missing B2B capability).

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Strategist | Define campaign scope, split into Red + Blue briefs | Claude (no subagent) | V0.9_TEST.md, API docs, COMPETE findings |
| Blue | Execute golden-path lifecycle sequences, record expected state | Task (parallel with Red) | Blue Brief only |
| Red | Execute adversarial attack sequences on same namespace | Task (parallel with Blue) | Red Brief only |
| Oracle | Compare Blue's expected state vs actual DB/STAC state | Task (sequential) | Blue's checkpoints + Red's attack log |
| Coroner | Root-cause analysis, reproduction scripts, pipeline chain recommendations | Task (sequential) | Oracle's findings + both logs |

**Maximum parallel agents**: 2 (Blue + Red only)

---

## Flow

```
Target: BASE_URL (Azure endpoint)
    |
    Strategist (Claude — no subagent)
        Reads V0.9_TEST.md, API docs, prior COMPETE findings
        Defines: campaign scope, shared wg- namespace
        Outputs: Blue Brief + Red Brief
    |
    ======== BATTLE PHASE ========
    |
    +--- Blue (Task) ---------+--- Red (Task) -----------+  [parallel]
    |    Golden-path executor   |    Adversarial attacker  |
    |    Runs canonical         |    Runs attack sequences |
    |    lifecycles             |    on SAME namespace     |
    |    Records expected       |    Records expected      |
    |    state checkpoints      |    rejections            |
    +---------------------------+--------------------------+
    |
    ======== JUDGMENT PHASE ========
    |
    Oracle (Task)                                           [sequential]
        Queries DB/STAC to compare actual vs Blue's expected
        Cross-references Red's attacks for contamination
        OUTPUT: Divergence Report
    |
    Coroner (Task)                                          [sequential]
        Root-cause analysis per finding
        OUTPUT: Final WARGAME Report with reproduction curls
```

---

## Campaign Config

Shared config file: `docs/agent_review/siege_config.json`

- **`valid_files`**: Used by Blue for golden-path sequences
- **`invalid_files`**: Used by Red for adversarial attacks
- **`approval_fixtures`**: Pre-built payloads for approve/reject attacks
- **`discovery`**: Endpoints for Strategist to verify files exist before launching

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

## Step 1: Play Strategist (No Subagent)

Claude plays Strategist directly. Two jobs:

### 1. Define the Campaign

1. Read V0.9_TEST.md and the Saboteur Attack Catalog (in the design doc or below).
2. Set the shared dataset namespace: `wg-` prefix.
3. Choose attack categories for Red based on context:
   - **Default**: All 5 categories (TEMPORAL, DUPLICATION, IDENTITY, RACE, LIFECYCLE)
   - **Focused** (after COMPETE): Target categories that match COMPETE findings
4. Define test data:
   - Raster: `dataset_id=wg-raster-test`, `resource_id=dctest`, `file_name=dctest.tif`
   - Vector: `dataset_id=wg-vector-test`, `resource_id=cutlines`, `file_name=cutlines.gpkg`

### 2. Write the Two Briefs

**Blue Brief** contains:
- BASE_URL and test data
- Bronze container name
- Canonical lifecycle sequences to execute (submit → poll → approve → verify, for each data type)
- State checkpoint instructions (what to record after each step)
- Blue does NOT see the attack catalog or Red's categories

**Red Brief** contains:
- BASE_URL and SAME test data (same `wg-` namespace)
- Bronze container name
- Attack categories to execute with minimum counts
- Reference to the Saboteur Attack Catalog
- Red does NOT see Blue's checkpoint map or expected state

---

## Step 2: Dispatch Blue + Red (Parallel)

Dispatch both agents simultaneously using the Agent tool. Both run in parallel.

### Blue Instructions

Execute canonical lifecycle sequences from the Blue Brief. After each step:

1. Record the full HTTP request and response
2. Record all captured IDs (request_id, job_id, release_id, asset_id)
3. Record the **expected system state** at this checkpoint

**Sequences to execute**:

1. **Raster lifecycle**: submit → poll → approve (version_id="v1") → verify STAC
2. **Vector lifecycle**: submit → poll → approve → verify OGC
3. **Multi-version**: resubmit raster → poll → approve (version_id="v2") → verify coexistence
4. **Unpublish**: unpublish v2 → verify v1 preserved

**Polling**: Poll `/api/platform/status/{request_id}` every 10 seconds, max 30 attempts.

### Blue Checkpoint Format

```
## Checkpoint {N}: {description}
AFTER: {step description}
EXPECTED STATE:
  Jobs:
    - {job_id} → status={completed|failed|processing}
  Releases:
    - {release_id} → approval_state={pending_review|approved|rejected|revoked}
    - {release_id} → version_ordinal={n}
  STAC Items:
    - {item_id} → {exists | not exists}
  OGC Collections:
    - {collection_id} → {exists | not exists}
  Captured IDs:
    request_id={value}
    job_id={value}
    release_id={value}
    asset_id={value}
```

### Blue HTTP Log Format

```
### Step {N}: {description}
REQUEST: {method} {url}
BODY: {json}
RESPONSE: HTTP {code}
BODY: {truncated to 500 chars}
CAPTURED: {key}={value}
VERDICT: PASS | FAIL
```

---

### Red Instructions

Execute attacks from the Red Brief using the **SAME `wg-` namespace** as Blue. This is the core adversarial mechanism — Red's attacks can contaminate Blue's expected state.

**Minimum attacks**: 3 per assigned category, chosen from the Saboteur Attack Catalog.

**Key rules**:
- Red MUST use the same dataset_ids as Blue (e.g., `wg-raster-test`)
- Red should vary timing — some attacks early (before Blue approves), some late (after Blue approves)
- Red should try attacks that directly interact with Blue's lifecycle (e.g., approve Blue's release with a different version_id)

### Red Attack Log Format

```
## Attack {category}{number}: {description}
CATEGORY: TEMPORAL | DUPLICATION | IDENTITY | RACE | LIFECYCLE
REQUEST: {method} {url}
BODY: {json}
RESPONSE: HTTP {code}
BODY: {truncated to 500 chars}
EXPECTED: {succeed | fail} — {reason}
ACTUAL: {what happened}
VERDICT: EXPECTED | UNEXPECTED | INTERESTING
NOTES: {any observations}
```

---

## Saboteur Attack Catalog (Reference)

### TEMPORAL (Out-of-Order Operations)

| # | Attack | Sequence | Expected |
|---|--------|----------|----------|
| T1 | Approve before job completes | Submit → immediately approve | Reject |
| T2 | Unpublish before approval | Submit → poll → unpublish | Reject or clean draft |
| T3 | Approve after unpublish | Submit → approve → unpublish → approve | Reject |
| T4 | Reject then approve | Submit → poll → reject → approve | Reject |
| T5 | Resubmit during processing | Submit → immediately resubmit | Dedup or queue |

### DUPLICATION (Repeated Operations)

| # | Attack | Sequence | Expected |
|---|--------|----------|----------|
| D1 | Double submit | Submit twice, same params | Idempotent or 409 |
| D2 | Double approve | Approve same release twice | Second fails |
| D3 | Double unpublish | Unpublish same asset twice | Second fails |
| D4 | Double reject | Reject same release twice | Second fails |
| D5 | Same version_id conflict | Approve v1 → approve v2 as "v1" | Conflict guard rejects |

### IDENTITY (Wrong IDs)

| # | Attack | Sequence | Expected |
|---|--------|----------|----------|
| I1 | Approve nonexistent release | Random UUID | 404 |
| I2 | Cross-asset approve | Approve B's release with A's context | Fail |
| I3 | Status for missing request | Random UUID | 404 or empty |
| I4 | Unpublish nonexistent asset | Random UUID | Error, no side effects |
| I5 | Cross-dataset approve | Raster release for vector asset | Fail |

### RACE (Concurrent Operations)

| # | Attack | Sequence | Expected |
|---|--------|----------|----------|
| R1 | Simultaneous approvals | 2 approves, same release | Exactly one succeeds |
| R2 | Approve + unpublish race | Both at once | One wins, state consistent |
| R3 | Submit + unpublish race | New submit while unpublishing | Both independent |
| R4 | Simultaneous submits | 2 submits, same params | One job (idempotent) |

### LIFECYCLE (Mid-Workflow)

| # | Attack | Sequence | Expected |
|---|--------|----------|----------|
| L1 | Unpublish mid-processing | Submit → unpublish while running | Queue or reject |
| L2 | Resubmit after rejection | Submit → reject → resubmit | New release |
| L3 | Approve without version_id | Approve, omit version_id | 400 |
| L4 | Duplicate version_id | Approve v1 → v2 as "v1" | Conflict reject |
| L5 | Same version across releases | Approve "r1" → v2 as "r1" | Reject duplicate |

---

## Step 3: Dispatch Oracle (Sequential, After Battle Phase)

Oracle receives Blue's State Checkpoint Map and Red's Attack Log. Oracle does NOT execute mutations — queries only.

### Oracle Procedure

**Step 1: Verify Blue's Checkpoints**

For each checkpoint in Blue's map, query using Platform API first, then admin for deep verification:

```bash
# Platform API (primary — same surface as B2B consumers)
curl "${BASE_URL}/api/platform/status/{request_id}"
curl "${BASE_URL}/api/platform/catalog/item/{collection}/{item_id}"
curl "${BASE_URL}/api/platform/catalog/dataset/{dataset_id}"
curl "${BASE_URL}/api/platform/approvals/status?stac_item_ids={ids}"
curl "${BASE_URL}/api/platform/failures"

# Admin (verification only — deeper state inspection)
curl "${BASE_URL}/api/dbadmin/jobs/{job_id}"
curl "${BASE_URL}/api/dbadmin/stats"
```

Compare actual state to Blue's expected state. Flag divergences.

**Step 2: Cross-Reference Red's Attacks**

For each of Red's attacks, check:
- Did attacks that should have failed (EXPECTED: fail) actually fail?
- Did any attacks succeed that should have been rejected? (LEAKED ATTACKS)
- Did any of Red's successful actions change Blue's expected state? (CROSS-CONTAMINATION)

**Step 3: Check for Orphans**

Query for artifacts that shouldn't exist:
- Jobs without corresponding releases
- STAC items without approved releases
- Releases in inconsistent states

### Oracle Output Format

```markdown
## State Verification

### Checkpoint {N}: {description}
| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
...

## State Divergences
| Checkpoint | Expected | Actual | Likely Cause |
...

## Leaked Attacks
| Red Attack | Expected Outcome | Actual Outcome | Risk |
...

## Cross-Contamination
| Red Attack | Blue Checkpoint Affected | How |
...

## Orphaned Artifacts
| Type | ID | Why Orphaned |
...
```

---

## Step 4: Dispatch Coroner (Sequential, After Oracle)

Coroner receives Oracle's full output, Red's attack log, and Blue's execution log.

### Coroner Procedure

For each finding from Oracle:

1. **Root-cause hypothesis**: Which code path likely failed? Reference specific files/functions if possible.
2. **Reproduction steps**: Exact curl sequence from a clean state (schema rebuild + nuke → steps to reproduce).
3. **Severity × Likelihood**: Using the shared scoring rubric.
4. **Pipeline chain**: Suggest which code-review pipeline (COMPETE or REFLEXION) to run, on which files, with what scope.

### Coroner Output Format

```markdown
# WARGAME Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version}
**Pipeline**: WARGAME

## Executive Summary
{2-3 sentences}

## Findings

### Finding {N}: {title}
**Severity**: CRITICAL | HIGH | MEDIUM | LOW
**Category**: State Divergence | Leaked Attack | Cross-Contamination | Orphan
**Root Cause**: {hypothesis — file, function, line if known}
**Reproduction**:
```bash
# From clean state:
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"
# Then:
curl -X POST ... # step 1
curl -X POST ... # step 2
# Verify:
curl ... # the failing check
```

**Suggested Follow-Up**: Run {COMPETE|REFLEXION} on `{file_path}` with scope `{scope}`

## Summary
| Category | Findings | Critical | High | Medium | Low |
...

## Pipeline Chain Recommendations
| Finding | Pipeline | Target Files | Scope |
...

## Verdict
{PASS | FAIL | NEEDS INVESTIGATION}
```

### Save Output

Save to `docs/agent_review/agent_docs/WARGAME_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Asymmetry Summary

| Agent | Gets | Doesn't Get | What This Reveals |
|-------|------|-------------|-------------------|
| Strategist | Full context | — | Defines the campaign |
| Blue | Blue Brief (canonical sequences) | Red's attack plan, attack catalog | Unbiased ground truth |
| Red | Red Brief (attacks + namespace) | Blue's checkpoint map, expected state | Attacks without gaming oracle |
| Oracle | Blue checkpoints + Red log + DB queries | — | Cross-contamination, leaked attacks |
| Coroner | Oracle findings + both logs | — | Root causes, reproduction steps |

### Why Cross-Contamination Detection Works

Red and Blue use the **SAME dataset_ids** (e.g., `wg-raster-test`). This means:

1. Blue submits and approves `wg-raster-test`
2. Red tries to double-approve, resubmit, or unpublish `wg-raster-test`
3. Oracle checks whether Blue's expected state (v1 approved, STAC item exists) still holds
4. If Red's attacks leaked through, Blue's checkpoints will show divergences

This is the core mechanism. The shared namespace creates realistic contention, and the asymmetry (Blue doesn't know about Red's attacks, Red doesn't know Blue's checkpoints) prevents either from gaming the results.
