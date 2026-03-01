# Adversarial Live API Testing Pipelines — Design

**Date**: 28 FEB 2026
**Status**: APPROVED
**Author**: Claude + Robert Harrison

---

## Overview

Three new agent pipelines for adversarial testing of the **live deployed** Platform API. These are the 4th, 5th, and 6th pipelines in the agent review system, alongside COMPETE (code review), GREENFIELD (design-then-build), and REFLEXION (kludge hardening).

The existing pipelines analyze code statically. These pipelines **test the running system** by executing real HTTP requests against the deployed Azure endpoint and verifying state consistency.

---

## Pipeline Selection Guide

| Scenario | Pipeline | Why |
|----------|----------|-----|
| Post-deployment smoke test | SIEGE | Fast, linear, confirms basic workflows work |
| Pre-release state integrity check | WARGAME | Red attacks while Blue establishes truth |
| Full adversarial regression | TOURNAMENT | 4 specialists in 2 phases. Maximum coverage |
| After COMPETE found a bug | WARGAME | Target Red's attacks at the flagged subsystem |
| Before a QA handoff | TOURNAMENT | Maximum coverage before external testers see it |
| Quick confidence check | SIEGE | "Did that deploy break anything?" |

**Chaining**: Run SIEGE first (cheap). If issues found, fix and redeploy. Then WARGAME for focused state testing. Then TOURNAMENT for full adversarial coverage.

| Pipeline | Agents | Parallelism | Estimated Tokens | Estimated Time |
|----------|--------|-------------|-----------------|----------------|
| SIEGE | 5 sequential | None | ~200K | ~15 min |
| WARGAME | 4 (2 parallel + 2 sequential) | Red + Blue | ~350K | ~20 min |
| TOURNAMENT | 5 (4 in 2 parallel phases + 1 synthesis) | Pathfinder+Saboteur, Inspector+Provocateur | ~500K | ~30 min |

---

## Shared Infrastructure

### Target Environment

All pipelines target the live Azure endpoint:

```
BASE_URL=https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
```

### Prerequisites (Run Before Every Pipeline)

```bash
# 1. Schema rebuild (fresh slate)
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"

# 2. STAC nuke
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"

# 3. Health check
curl -sf "${BASE_URL}/api/health"
```

### Dataset Namespace Convention

Each pipeline uses a prefix to avoid cross-pipeline contamination:

| Pipeline | Prefix | Example dataset_id |
|----------|--------|--------------------|
| SIEGE | `sg-` | `sg-raster-test` |
| WARGAME | `wg-` | `wg-raster-test` |
| TOURNAMENT | `tn-` | `tn-raster-test` |

### Output Location

```
docs/agent_review/agent_docs/
  SIEGE_RUN_{N}.md
  WARGAME_RUN_{N}.md
  TOURNAMENT_RUN_{N}.md
```

All runs logged in `docs/agent_review/AGENT_RUNS.md`.

### Agent HTTP Request Log Format

Every agent that executes HTTP requests MUST log each request in this format:

```
### Step {N}: {description}
REQUEST: {method} {url}
BODY: {json body if any}
RESPONSE: HTTP {code}
BODY: {response body, truncated to 500 chars}
CAPTURED: {key}={value} (e.g., request_id=abc123)
EXPECTED: {what should happen}
ACTUAL: {what did happen}
VERDICT: PASS | FAIL | UNEXPECTED
```

### Scoring Rubric

| Severity | Definition | Examples |
|----------|------------|---------|
| CRITICAL | Data corruption or state inconsistency | Orphaned STAC items, approved release with wrong data, cross-contamination between datasets |
| HIGH | Security or integrity bypass | Attack that should fail but succeeds, missing validation on mutating endpoint |
| MEDIUM | Incorrect error handling | Wrong HTTP status code, missing error message, inconsistent error format |
| LOW | Documentation or UX issue | Misleading response field, undocumented behavior, slow response |

---

## Pipeline 1: SIEGE (Sequential Smoke Test)

**Purpose**: Fast sequential verification that the live API's core workflows function after deployment.

**Best for**: Post-deployment smoke test, quick confidence check.

### Flow

```
Target: BASE_URL
    |
    Sentinel (Claude — no subagent)
        Reads V0.9_TEST.md, defines test data
        Outputs: Campaign Brief
    |
    Cartographer (Task)                          [sequential]
        Probes every known endpoint
        OUTPUT: Endpoint Map
    |
    Lancer (Task)                                [sequential]
        Executes canonical lifecycle sequences
        OUTPUT: Execution Log + State Checkpoint Map
    |
    Auditor (Task)                               [sequential]
        Queries DB, STAC, status endpoints
        Compares actual vs expected state
        OUTPUT: Audit Report
    |
    Scribe (Task)                                [sequential]
        Synthesizes all outputs
        OUTPUT: Final SIEGE Report
```

### Agent Roles

| Agent | Role | Runs As | Input | Output |
|-------|------|---------|-------|--------|
| Sentinel | Define campaign | Claude (no subagent) | V0.9_TEST.md, API docs | Campaign Brief |
| Cartographer | Map API surface | Task (sequential) | Campaign Brief, endpoint list | Endpoint Map |
| Lancer | Execute workflows | Task (sequential) | Campaign Brief, test data | Execution Log + State Checkpoints |
| Auditor | Verify state | Task (sequential) | Lancer's checkpoint map | Audit Report |
| Scribe | Synthesize report | Task (sequential) | All outputs | Final Report |

### Information Asymmetry

Minimal — SIEGE is a linear sweep, not adversarial. Its value is speed and simplicity.

| Agent | Gets | Doesn't Get |
|-------|------|-------------|
| Sentinel | Full context | — |
| Cartographer | Endpoint list | Test data, lifecycle plans |
| Lancer | Campaign Brief + test data | Cartographer's findings |
| Auditor | Lancer's checkpoint map | Lancer's raw HTTP responses |
| Scribe | All outputs | — |

### Sentinel Instructions

1. Read `V0.9_TEST.md` sections A–I for the canonical test sequences.
2. Define test data using the `sg-` prefix:
   - Raster: `dataset_id=sg-raster-test`, `resource_id=dctest`, `file_name=dctest.tif`
   - Vector: `dataset_id=sg-vector-test`, `resource_id=cutlines`, `file_name=cutlines.gpkg`
3. Define the Bronze container name from environment context.
4. Output the Campaign Brief with: BASE_URL, test data, bronze container, endpoint list.

### Cartographer Instructions

For each known endpoint, send a minimal probe:

| Endpoint | Method | Probe |
|----------|--------|-------|
| `/api/health` | GET | No params |
| `/api/platform/submit` | OPTIONS or GET | Check if live |
| `/api/platform/status/{dummy}` | GET | Random UUID |
| `/api/platform/approve` | OPTIONS or GET | Check if live |
| `/api/platform/catalog/collections` | GET | No params |
| `/api/dbadmin/stats` | GET | No params |
| `/api/dbadmin/jobs` | GET | `?limit=1` |

Output: Endpoint Map table (URL → HTTP code → response shape → latency).

### Lancer Instructions

Execute these lifecycle sequences using Campaign Brief test data. Record state checkpoints after each step.

**Sequence 1: Raster lifecycle**
1. Submit raster → capture request_id, job_id
2. Poll until completed → capture release_id, asset_id
3. Approve with version_id="v1" → verify STAC materialized
4. Query STAC item → verify exists
5. **Checkpoint**: record all IDs and expected DB state

**Sequence 2: Vector lifecycle**
1. Submit vector → capture IDs
2. Poll until completed → capture release_id
3. Approve → verify OGC Features collection
4. **Checkpoint**: record all IDs

**Sequence 3: Multi-version**
1. Resubmit raster (same dataset_id) → capture v2 IDs
2. Poll → verify ordinal=2
3. Approve v2 → verify coexistence with v1
4. **Checkpoint**: both v1 and v2 state

**Sequence 4: Unpublish**
1. Unpublish v2 → poll until complete
2. **Checkpoint**: v2 removed, v1 still present

Output: Execution Log with all captured IDs + State Checkpoint Map.

### Auditor Instructions

For each checkpoint in Lancer's map, query the system and compare:

| Check | Query | Compare Against |
|-------|-------|-----------------|
| Job exists | `/api/dbadmin/jobs/{job_id}` | Expected status |
| Release state | `/api/platform/status/{request_id}` | Expected approval_state |
| STAC item | `/api/platform/catalog/item/{collection}/{item_id}` | Expected existence |
| DB stats | `/api/dbadmin/stats` | No orphaned rows |

Flag any divergence between expected and actual state.

### Scribe Output Format

```markdown
# SIEGE Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version from /api/health}

## Endpoint Health
| Endpoint | Status | Latency |
...

## Workflow Results
| Sequence | Steps | Pass | Fail | Unexpected |
...

## State Divergences
{from Auditor — expected vs actual}

## Findings
| # | Severity | Category | Description | Reproduction |
...

## Verdict
{PASS / FAIL / NEEDS INVESTIGATION}
```

---

## Pipeline 2: WARGAME (Red vs Blue State Divergence)

**Purpose**: Focused adversarial testing of state consistency. Red attacks the system while Blue establishes ground truth. Oracle catches where system state diverges.

**Best for**: Pre-release state integrity, chaining from COMPETE findings.

### Flow

```
Target: BASE_URL
    |
    Strategist (Claude — no subagent)
        Reads V0.9_TEST.md, API docs, any COMPETE findings
        Outputs: Red Brief + Blue Brief
    |
    ======== BATTLE PHASE ========
    |
    +--- Blue (Task) ---------+--- Red (Task) -----------+  [parallel]
    |    Golden-path executor   |    Adversarial attacker  |
    +---------------------------+--------------------------+
    |
    ======== JUDGMENT PHASE ========
    |
    Oracle (Task)                                           [sequential]
        Compares Blue expected state vs actual DB/STAC
        Finds cross-contamination from Red
    |
    Coroner (Task)                                          [sequential]
        Root-cause analysis on each finding
        Produces reproduction scripts
```

### Agent Roles

| Agent | Role | Runs As | Input | Output |
|-------|------|---------|-------|--------|
| Strategist | Define campaign | Claude (no subagent) | V0.9_TEST.md, API docs, COMPETE findings | Red Brief + Blue Brief |
| Blue | Execute golden path | Task (parallel with Red) | Blue Brief only | State Checkpoint Map + Captured IDs |
| Red | Execute attacks | Task (parallel with Blue) | Red Brief only | Attack Log + Expected Rejections |
| Oracle | Audit state | Task (sequential) | Blue's checkpoints + Red's log | Divergence Report |
| Coroner | Root-cause analysis | Task (sequential) | Oracle's findings + both logs | Final Report |

### Information Asymmetry

| Agent | Gets | Doesn't Get | What This Reveals |
|-------|------|-------------|-------------------|
| Blue | Canonical sequences | Red's attack plan | Unbiased ground truth |
| Red | Attack categories + namespace | Blue's checkpoints | Attacks without gaming the oracle |
| Oracle | Both outputs + DB queries | — | Cross-contamination and state bugs |
| Coroner | All outputs | — | Root causes |

### Strategist Instructions

1. Read V0.9_TEST.md and the attack catalog (Section: Saboteur Attack Catalog).
2. Define the shared dataset namespace: `wg-` prefix.
3. Choose which attack categories Red should focus on (based on COMPETE findings if available, otherwise all 5).
4. Write **Blue Brief**:
   - Canonical lifecycle sequences (raster submit → approve, vector submit → approve, multi-version, unpublish)
   - Test data with `wg-` prefix
   - State checkpoints to record
5. Write **Red Brief**:
   - Attack categories to execute (TEMPORAL, DUPLICATION, IDENTITY, RACE, LIFECYCLE)
   - Same `wg-` dataset namespace as Blue
   - Minimum 3 attacks per category
   - Red does NOT see Blue's checkpoint map

### Blue Instructions

Execute the sequences from Blue Brief exactly. After each step:

1. Record the HTTP request and response
2. Record all captured IDs (request_id, job_id, release_id, asset_id)
3. Record the **expected system state** at this point:
   - Which jobs should exist and in what status
   - Which releases should exist and in what approval_state
   - Which STAC items should exist
   - Which blob paths should exist

Output format:

```
## Checkpoint {N}: {description}
AFTER: {step description}
EXPECTED STATE:
  Jobs: {job_id} → {status}
  Releases: {release_id} → {approval_state}
  STAC Items: {item_id} → exists/not exists
  Captured IDs: {key=value, ...}
```

### Red Instructions

Execute attacks from the Red Brief using the SAME `wg-` dataset namespace as Blue. For each attack:

1. Record the attack category and number (e.g., T1, D2, R1)
2. Record the HTTP request and response
3. Record whether you **expected** this to succeed or fail
4. Note any surprising behavior

**Key rule**: Red MUST use the same dataset_ids as Blue (e.g., `wg-raster-test`). This is what creates contention and tests isolation.

**Minimum attacks**: 3 per assigned category, chosen from the Saboteur Attack Catalog.

Output format:

```
## Attack {category}{number}: {description}
REQUEST: {method} {url}
BODY: {json}
RESPONSE: HTTP {code}
EXPECTED: {succeed/fail + why}
ACTUAL: {what happened}
VERDICT: EXPECTED | UNEXPECTED | INTERESTING
```

### Oracle Instructions

Oracle receives Blue's State Checkpoint Map and Red's Attack Log. Oracle does NOT re-execute mutations — only queries.

**Step 1**: For each of Blue's checkpoints, query the system to verify actual state matches expected:

```bash
# Job state
curl "${BASE_URL}/api/dbadmin/jobs/{job_id}"

# Release state
curl "${BASE_URL}/api/platform/status/{request_id}"

# STAC item
curl "${BASE_URL}/api/platform/catalog/item/{collection}/{item_id}"

# Overall stats
curl "${BASE_URL}/api/dbadmin/stats"
```

**Step 2**: Cross-reference Red's attacks against Blue's expected state. Look for:
- **State divergences**: Blue expected X, actual is Y
- **Leaked attacks**: Red's attack should have failed but succeeded (HTTP 2xx instead of 4xx)
- **Cross-contamination**: Red's actions changed Blue's expected state
- **Orphaned artifacts**: DB rows, STAC items, or blob paths without valid parents

Output format:

```markdown
## State Divergences
| Checkpoint | Expected | Actual | Likely Cause |
...

## Leaked Attacks
| Attack | Expected Outcome | Actual Outcome | Risk |
...

## Cross-Contamination
| Red Attack | Blue Checkpoint Affected | How |
...

## Orphaned Artifacts
| Type | ID | Why Orphaned |
...
```

### Coroner Instructions

Receives Oracle's full output, Red's attack log, and Blue's execution log.

For each finding from Oracle:
1. Hypothesize the root cause (which code path, which function)
2. Write reproduction steps (exact curl sequence from a clean state)
3. Assign Severity × Likelihood
4. Suggest which files to feed into COMPETE or REFLEXION

Output format:

```markdown
# WARGAME Report — Run {N}

## Findings

### Finding {N}: {title}
**Severity**: CRITICAL | HIGH | MEDIUM | LOW
**Category**: State Divergence | Leaked Attack | Cross-Contamination | Orphan
**Root Cause**: {hypothesis}
**Reproduction**:
  1. {curl command}
  2. {curl command}
  ...
**Suggested Follow-Up**: Run {COMPETE|REFLEXION} on {file_path}

## Summary
| Category | Findings | Critical | High | Medium | Low |
...

## Pipeline Chain Recommendations
{Which findings to feed into code review pipelines}
```

---

## Pipeline 3: TOURNAMENT (Full-Spectrum Adversarial)

**Purpose**: Maximum-coverage adversarial testing across state consistency, edge cases, and interleaving. 4 specialists in 2 phases, synthesized by a Tribunal.

**Best for**: Full adversarial regression, pre-QA handoff.

### Flow

```
Target: BASE_URL
    |
    General (Claude — no subagent)
        Reads V0.9_TEST.md, API docs, prior findings
        Outputs: 4 Specialist Briefs
    |
    ======== PHASE 1: MUTATION ========
    |
    +--- Pathfinder (Task) ----+--- Saboteur (Task) --------+  [parallel]
    |    Happy-path executor    |    Adversarial attacker     |
    +---------------------------+----------------------------+
    |
    ======== PHASE 2: AUDIT ========
    |
    +--- Inspector (Task) -----+--- Provocateur (Task) -----+  [parallel]
    |    State auditor          |    Input validation tester  |
    +---------------------------+----------------------------+
    |
    ======== PHASE 3: JUDGMENT ========
    |
    Tribunal (Task)                                            [sequential]
        Synthesizes all findings with scoring
```

### Agent Roles

| Agent | Role | Runs As | Input | Output |
|-------|------|---------|-------|--------|
| General | Define campaign | Claude (no subagent) | V0.9_TEST.md, API docs, prior findings | 4 Specialist Briefs |
| Pathfinder | Execute golden path | Task (Phase 1, parallel) | Pathfinder Brief | State Checkpoint Map |
| Saboteur | Execute attacks | Task (Phase 1, parallel) | Saboteur Brief | Attack Log |
| Inspector | Audit state | Task (Phase 2, parallel) | Pathfinder's checkpoints | State Audit Report |
| Provocateur | Test input validation | Task (Phase 2, parallel) | Endpoint list only | Error Behavior Map |
| Tribunal | Synthesize findings | Task (Phase 3, sequential) | All 4 outputs | Final Tournament Report |

### Information Asymmetry

| Agent | Gets | Doesn't Get | What This Reveals |
|-------|------|-------------|-------------------|
| Pathfinder | Canonical workflows | Saboteur's attack plan | Unbiased ground truth |
| Saboteur | Attack categories + namespace | Pathfinder's checkpoints | Attacks without gaming audit |
| Inspector | Pathfinder's checkpoint map | Saboteur's attacks | Divergences without knowing cause |
| Provocateur | Endpoint list only | Everything else | Input validation in pure isolation |
| Tribunal | ALL outputs | — | Full picture with scoring |

### General Instructions

1. Read V0.9_TEST.md (sections A–I) and the Saboteur Attack Catalog.
2. Define the `tn-` namespace for all test data.
3. Prepare 4 specialist briefs:

**Pathfinder Brief**:
- Canonical lifecycle sequences (same as SIEGE Lancer but with `tn-` prefix)
- Must execute: raster lifecycle, vector lifecycle, multi-version, unpublish
- Record state checkpoints after every step

**Saboteur Brief**:
- All 5 attack categories: TEMPORAL, DUPLICATION, IDENTITY, RACE, LIFECYCLE
- Same `tn-` namespace as Pathfinder
- Minimum 3 attacks per category (15 total minimum)
- Choose specific attacks from the catalog or design new ones

**Inspector Brief**:
- Will receive Pathfinder's output after Phase 1
- Query endpoints to verify state
- Does NOT see Saboteur's attacks

**Provocateur Brief**:
- Endpoint list with methods and expected parameters
- All PAYLOAD category attacks (P1–P10 minimum)
- May design additional input validation attacks

### Pathfinder Instructions

Same as WARGAME Blue, but with `tn-` prefix and these additional sequences:

**Sequence 1: Raster lifecycle** (submit → poll → approve → verify STAC)
**Sequence 2: Vector lifecycle** (submit → poll → approve → verify OGC)
**Sequence 3: Multi-version** (resubmit raster → poll → approve v2 → verify coexistence)
**Sequence 4: Unpublish** (unpublish v2 → verify v1 preserved)
**Sequence 5: Rejection recovery** (submit → poll → reject → resubmit → approve)

Output: State Checkpoint Map with all captured IDs.

### Saboteur Instructions

Same as WARGAME Red, but with `tn-` prefix and ALL 5 attack categories.

Minimum attack execution:

| Category | Min Attacks | Focus |
|----------|-------------|-------|
| TEMPORAL | 3 | T1, T2, T3 |
| DUPLICATION | 3 | D1, D2, D5 |
| IDENTITY | 3 | I1, I2, I5 |
| RACE | 2 | R1, R2 |
| LIFECYCLE | 3 | L1, L4, L5 |

**Key rule**: Use same `tn-` dataset_ids as Pathfinder.

Output: Attack Log per category with expected vs actual outcomes.

### Inspector Instructions

Same as WARGAME Oracle (state verification), but:
- Inspector does NOT see Saboteur's attacks (unlike Oracle who sees Red's log)
- Inspector only receives Pathfinder's checkpoint map
- Divergences caused by Saboteur appear as **unexplained anomalies**

This is the key difference from WARGAME — Inspector must report divergences without knowing the cause, forcing Tribunal to correlate.

Additional checks Inspector MUST perform:

| Check | Query | Purpose |
|-------|-------|---------|
| Job count | `/api/dbadmin/jobs?limit=100` | Are there unexpected jobs? |
| Failed jobs | `/api/dbadmin/jobs?status=failed` | Any crashes? |
| Task orphans | `/api/dbadmin/diagnostics/all` | Orphaned tasks? |
| STAC collections | `/api/platform/catalog/collections` | Unexpected collections? |

Output: State Audit Report with matches, divergences, orphaned artifacts, unexplained anomalies.

### Provocateur Instructions

Provocateur operates **completely independently** from the other agents. It receives only the endpoint list and fires boundary-value inputs.

Execute ALL attacks from the PAYLOAD category (P1–P10) against these endpoints:

| Target Endpoint | Method |
|-----------------|--------|
| `/api/platform/submit` | POST |
| `/api/platform/approve` | POST |
| `/api/platform/reject` | POST |
| `/api/platform/unpublish` | POST |

For each attack, record:

```
## P{N}: {description}
ENDPOINT: {path}
REQUEST: {method} {url}
BODY: {payload}
RESPONSE: HTTP {code}
BODY: {response body}
EXPECTED: {what should happen — 400, 415, etc.}
ACTUAL: {what happened}
VERDICT: PASS | FAIL
NOTES: {any observations about error format, missing details, etc.}
```

Additional Provocateur-designed attacks (beyond catalog):
- Test every endpoint with GET when it expects POST
- Test every endpoint with no Authorization header (if auth is enabled)
- Test approve with every possible field missing one at a time

Output: Error Behavior Map (endpoint × input → HTTP code → response body) + Crash Log (any 500s).

### Tribunal Instructions

Tribunal receives ALL 4 specialist outputs and produces the final report.

**Step 1: Correlation**
Cross-reference Inspector's unexplained divergences with Saboteur's attack log to identify interleaving defects.

**Step 2: Classification**
Classify every finding into one of:

| Category | Source | Meaning |
|----------|--------|---------|
| STATE DIVERGENCE | Inspector | Expected ≠ actual (may or may not be Saboteur's fault) |
| LEAKED ATTACK | Saboteur | Attack that should have failed but succeeded |
| INTERLEAVING DEFECT | Inspector + Saboteur correlation | Saboteur's action corrupted Pathfinder's state |
| INPUT VALIDATION GAP | Provocateur | Missing validation, 500 crash, or insecure response |
| ORPHANED ARTIFACT | Inspector | DB/STAC/blob without parent entity |

**Step 3: Scoring**
For each finding, assign Severity × Likelihood from the shared rubric.

**Step 4: Scoreboard**

```
## Specialist Scoreboard
| Agent | Findings | Critical | High | Medium | Low | Unique |
|-------|----------|----------|------|--------|-----|--------|
| Pathfinder | (ground truth — not scored) | — | — | — | — | — |
| Saboteur | {n} | {n} | {n} | {n} | {n} | {n} |
| Inspector | {n} | {n} | {n} | {n} | {n} | {n} |
| Provocateur | {n} | {n} | {n} | {n} | {n} | {n} |
| **Tribunal (correlated)** | {n} | {n} | {n} | {n} | {n} | {n} |
```

"Unique" = findings that only this agent's lens could catch.

**Step 5: Pipeline Chain Recommendations**
For each HIGH or CRITICAL finding, recommend:
- Which code-review pipeline to run (COMPETE or REFLEXION)
- Which files to target
- What scope split to use

### Tribunal Output Format

```markdown
# TOURNAMENT Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version}

## Executive Summary
{2-3 sentences: what was tested, what was found, overall verdict}

## State Divergences
| # | Checkpoint | Expected | Actual | Saboteur Correlated? | Severity |
...

## Leaked Attacks
| # | Attack | Expected | Actual | Severity |
...

## Interleaving Defects
| # | Saboteur Attack | Pathfinder Checkpoint Affected | How | Severity |
...

## Input Validation Gaps
| # | Endpoint | Input | HTTP Code | Expected | Severity |
...

## Orphaned Artifacts
| # | Type | ID | Why Orphaned | Severity |
...

## Specialist Scoreboard
{table as above}

## Reproduction Commands
{Exact curl sequences for every HIGH+ finding}

## Pipeline Chain Recommendations
| Finding | Pipeline | Target Files | Scope |
...

## Verdict
{PASS / FAIL / NEEDS INVESTIGATION}
{Total findings: X (Y critical, Z high, ...)}
```

---

## Saboteur Attack Catalog

Reference catalog of attacks for Red (WARGAME) and Saboteur (TOURNAMENT).

### Category 1: TEMPORAL (Out-of-Order Operations)

| # | Attack | Sequence | Expected Behavior | Tests |
|---|--------|----------|-------------------|-------|
| T1 | Approve before job completes | Submit → immediately approve | Reject: release not ready | Pre-completion approval guard |
| T2 | Unpublish before approval | Submit → poll → unpublish (skip approve) | Reject or clean draft artifacts | Unapproved release handling |
| T3 | Approve after unpublish | Submit → approve → unpublish → approve again | Reject: release revoked | State finality after unpublish |
| T4 | Reject then approve | Submit → poll → reject → approve | Reject: release rejected | Rejection finality |
| T5 | Resubmit during processing | Submit → immediately resubmit (same params) | Dedup or queue | Concurrent submission handling |

### Category 2: DUPLICATION (Repeated Operations)

| # | Attack | Sequence | Expected Behavior | Tests |
|---|--------|----------|-------------------|-------|
| D1 | Double submit | Submit twice, identical params | Same job_id (idempotent) or 409 | Job ID determinism |
| D2 | Double approve | Approve same release_id twice | Second fails or idempotent | Approval conflict guard |
| D3 | Double unpublish | Unpublish same asset twice | Second fails gracefully | Unpublish idempotency |
| D4 | Double reject | Reject same release_id twice | Second fails gracefully | Rejection idempotency |
| D5 | Same version_id for two releases | Approve v1 as "v1" → approve v2 as "v1" | Conflict guard rejects | Partial unique index |

### Category 3: IDENTITY (Wrong/Mismatched IDs)

| # | Attack | Sequence | Expected Behavior | Tests |
|---|--------|----------|-------------------|-------|
| I1 | Approve nonexistent release | Random UUID as release_id | 404 or clear error | Release existence check |
| I2 | Cross-asset approve | Approve B's release with A's context | Fail or scoped to B only | Release-asset scoping |
| I3 | Status for nonexistent request | Random UUID as request_id | 404 or empty | Missing request handling |
| I4 | Unpublish nonexistent asset | Random UUID as asset_id | Clear error, no side effects | Asset existence check |
| I5 | Cross-dataset approve | Approve raster release for vector asset | Fail | Entity type enforcement |

### Category 4: RACE (Concurrent Operations)

| # | Attack | Sequence | Expected Behavior | Tests |
|---|--------|----------|-------------------|-------|
| R1 | Simultaneous approvals | 2 approve requests, same release_id, at once | Exactly one succeeds | `approve_release_atomic()` atomicity |
| R2 | Approve + unpublish race | Approve and unpublish simultaneously | One wins, state consistent | Concurrent lifecycle safety |
| R3 | Submit + unpublish race | New submit while unpublishing same dataset | Both complete independently | Cross-version isolation |
| R4 | Simultaneous submits | 2 submits, identical params, at once | One job (idempotent) | Job dedup under concurrency |

### Category 5: LIFECYCLE (Mid-Workflow Interruption)

| # | Attack | Sequence | Expected Behavior | Tests |
|---|--------|----------|-------------------|-------|
| L1 | Unpublish mid-processing | Submit → unpublish while job runs | Queue or reject | Running job protection |
| L2 | Resubmit after rejection | Submit → reject → resubmit | New release created | Recovery from rejection |
| L3 | Approve without version_id | Submit → poll → approve (no version_id) | 400 validation error | Required field enforcement |
| L4 | Duplicate version_id | Approve v1 as "v1" → submit v2 → approve as "v1" | Conflict guard rejects | Version uniqueness |
| L5 | Same version across releases | Approve as "r1" → submit v2 → approve as "r1" | Reject duplicate | Cross-release version uniqueness |

### Category 6: PAYLOAD (Input Validation)

Used by Provocateur (TOURNAMENT). Optional for Red (WARGAME).

| # | Attack | Target | Payload | Expected |
|---|--------|--------|---------|----------|
| P1 | Empty body | /api/platform/submit | `{}` | 400 with required fields list |
| P2 | Missing field | /api/platform/submit | `{"dataset_id": "x"}` | 400 with missing field name |
| P3 | SQL injection | /api/platform/submit | `{"dataset_id": "'; DROP TABLE app.jobs;--"}` | 400 or safe processing |
| P4 | Unicode | /api/platform/submit | `{"resource_id": "émöji🚀"}` | Reject or sanitize |
| P5 | Long string | /api/platform/submit | `{"dataset_id": "a" × 10000}` | 400 length validation |
| P6 | Wrong Content-Type | /api/platform/submit | text/plain body | 400 or 415 |
| P7 | Invalid JSON | /api/platform/submit | `{not json` | 400 |
| P8 | Extra fields | /api/platform/submit | Valid + `"admin": true` | Ignored, no escalation |
| P9 | Null values | /api/platform/approve | `{"release_id": null}` | 400 |
| P10 | Path traversal | /api/platform/submit | `{"file_name": "../../etc/passwd"}` | 400 or sanitized |

### Attack Priority by Pipeline

| Category | SIEGE | WARGAME (Red) | TOURNAMENT (Saboteur) | TOURNAMENT (Provocateur) |
|----------|-------|---------------|----------------------|--------------------------|
| TEMPORAL | — | 3+ | 3+ | — |
| DUPLICATION | — | 3+ | 3+ | — |
| IDENTITY | — | 2+ | 3+ | — |
| RACE | — | 2+ | 2+ | — |
| LIFECYCLE | — | 3+ | 3+ | — |
| PAYLOAD | — | Optional | — | 10+ |

---

## Metrics & Instrumentation

### Per-Run Captured (in AGENT_RUNS.md)

| Field | Description |
|-------|-------------|
| Pipeline | SIEGE, WARGAME, or TOURNAMENT |
| Date | Run date |
| Target | BASE_URL |
| Version | Deployed version from /api/health |
| Per-agent tokens | input, output, cache_read, total |
| Per-agent duration | Wall clock time |
| HTTP requests fired | Total across all agents |
| Findings | Count by severity |
| Verdict | PASS / FAIL / NEEDS INVESTIGATION |

### Quality Signals

| Signal | What It Means |
|--------|---------------|
| Inspector finds 0 divergences | Either system is perfect OR Pathfinder's checkpoints are wrong |
| Saboteur finds 0 leaked attacks | Either security is tight OR attacks are too weak |
| Provocateur finds 0 crashes | Input validation is solid |
| Cross-contamination > 0 | State isolation is broken — CRITICAL |
| Tribunal correlated findings > individual | Information asymmetry is working — agents found more together than alone |

---

## Implementation Notes

### How Agents Execute HTTP Requests

Agents use `curl` via the Bash tool. Each agent receives the BASE_URL and constructs curl commands based on their brief.

Example agent execution:

```bash
# Submit
curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "${BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "tn-raster-test", "resource_id": "dctest", "container_name": "bronze-netcdf", "file_name": "dctest.tif"}'

# Poll (with retry)
for i in {1..30}; do
  RESPONSE=$(curl -s "${BASE_URL}/api/platform/status/${REQUEST_ID}")
  STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('job_status','unknown'))")
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 10
done
```

### Phase Sequencing

- **SIEGE**: All agents sequential (no parallelism)
- **WARGAME**: Blue + Red parallel → Oracle sequential → Coroner sequential
- **TOURNAMENT**: Pathfinder + Saboteur parallel → Inspector + Provocateur parallel → Tribunal sequential

Phase 2 agents MUST NOT start until Phase 1 agents complete. This is enforced by the orchestrator (Claude playing General/Strategist) waiting for both Phase 1 agent results before dispatching Phase 2.

### Agent Tool Configuration

All testing agents are dispatched as subagents via the Agent tool with `subagent_type: "general-purpose"`. Each agent receives its brief as the prompt, including:
- BASE_URL
- Test data (dataset namespace)
- Their specific instructions
- Output format requirements

---

## Future Extensions

| Extension | Description | When |
|-----------|-------------|------|
| Newman integration | Export attack catalog as Postman/Newman collection for CI | When CI pipeline exists |
| REFLEXION chain | Auto-trigger REFLEXION on files identified by TOURNAMENT findings | After TOURNAMENT is proven |
| Concurrency harness | Python script that fires truly concurrent requests (asyncio/aiohttp) instead of sequential curl | When RACE category needs true concurrency |
| Regression baseline | Store passing state checkpoint maps as baselines for future runs | After 3+ clean TOURNAMENT runs |
| ITSDA handoff | Generate QA team test matrix from TOURNAMENT findings | Before next QA sprint |
