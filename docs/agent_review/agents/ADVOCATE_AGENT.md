# Pipeline 7: ADVOCATE (B2B Developer Experience Audit)

**Purpose**: Evaluate the API from the perspective of developers trying to integrate. Two agents — a confused newcomer and a seasoned API architect — independently critique ergonomics, consistency, discoverability, error messages, and response shapes across the full consumer surface.

**Best for**: Pre-UAT polish. When correctness is proven (SIEGE/TOURNAMENT pass) but you need to know if the API is *pleasant* to integrate with.

---

## Endpoint Access Rules

Agents experience the API **exactly as a B2B consumer would**. No admin endpoints, no source code, no internal docs.

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/api/platform/*`, `/api/stac/*`, `/api/features/*`, TiTiler (`/cog/*`, `/xarray/*`, `/vector/*`) | Intern, Architect | The full surface a B2B developer touches end-to-end. |
| **Setup** | `/api/dbadmin/maintenance`, `/api/stac/nuke` | Dispatcher (prerequisites only) | Fresh slate before agents run. Never during tests. |
| **Synthesis** | None (reads agent outputs) | Editor | Merges findings, produces final report. No HTTP calls. |

**Hard rule**: Intern and Architect MUST NOT use admin endpoints (`/api/dbadmin/*`, `/api/health`). If they need information that isn't available through the consumer surface, that is a finding — "missing B2B capability" or "poor discoverability."

---

## Agent Roles

| Agent | Phase | Role | Persona | Runs As |
|-------|-------|------|---------|---------|
| Dispatcher | 0 | Define test data, endpoint inventory, write briefs | Campaign planner | Claude (no subagent) |
| Intern | 1 | First-impressions friction log | Junior dev, first week at DDH, no docs | Task (sequential) |
| Architect | 2 | Structured DX audit against REST best practices | Senior API architect, 10 years experience | Task (sequential) |
| Editor | 3 | Merge, deduplicate, prioritize, produce report | Technical writer | Claude (synthesis) |

**Maximum parallel agents**: 0 (strictly sequential — Architect needs Intern's output)

---

## Flow

```
Target: BASE_URL (Azure endpoint)
    |
    Dispatcher (Claude — no subagent)
        Defines adv- namespace test data
        Writes Intern Brief + Architect Brief skeleton
        Outputs: Campaign Brief
    |
    ======== PHASE 1: FIRST IMPRESSIONS ========
    |
    Intern (Task)                                    [sequential]
        Junior dev. No docs, no hints.
        Attempts full lifecycle cold: submit → poll → approve → discover → render
        Records every friction point, confusion, WTF moment.
        OUTPUT: Friction Log
    |
    ======== PHASE 2: STRUCTURED AUDIT ========
    |
    Architect (Task)                                 [sequential]
        Senior API reviewer. Gets Intern's Friction Log.
        Replays same endpoints systematically.
        Evaluates against REST best practices.
        OUTPUT: DX Audit Report
    |
    ======== PHASE 3: SYNTHESIS ========
    |
    Editor (Claude — synthesis)
        Merges both reports, deduplicates, prioritizes.
        Assigns severity, groups by theme.
        OUTPUT: Final ADVOCATE Report
```

---

## Campaign Config

Shared config file: `docs/agent_review/siege_config.json`

- **`valid_files`**: Used by Intern for lifecycle walkthrough
- **`discovery`**: Dispatcher verifies files exist before launching

---

## Prerequisites

```bash
BASE_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

# Schema rebuild (fresh slate)
curl -X POST "${BASE_URL}/api/dbadmin/maintenance?action=rebuild&confirm=yes"

# STAC nuke
curl -X POST "${BASE_URL}/api/stac/nuke?confirm=yes&mode=all"

# Health check (Dispatcher only — agents don't get this endpoint)
curl -sf "${BASE_URL}/api/platform/health"
```

---

## Step 1: Play Dispatcher (No Subagent)

Claude plays Dispatcher directly. Dispatcher's job:

1. Read `siege_config.json` for test data.
2. Verify valid files exist via discovery endpoint.
3. Define test data using `adv-` prefix:
   - Raster: `dataset_id=adv-raster-test`, `resource_id=dctest`, `file_name=dctest.tif`, `container_name=rmhazuregeobronze`
   - Vector: `dataset_id=adv-vector-test`, `resource_id=cutlines`, `file_name=0403c87a-0c6c-4767-a6ad-78a8026258db/Vivid_Standard_30_CO02_24Q2/cutlines.gpkg`, `container_name=rmhazuregeobronze`
   - NetCDF: `dataset_id=adv-netcdf-test`, `resource_id=spei-ssp370`, `file_name=good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc`, `container_name=wargames`, `data_type=zarr`
4. Write 2 specialist briefs.

---

## Step 2: Dispatch Intern (Phase 1)

### Intern Persona

```
You are a junior developer in your first week at DDH (Data Delivery Hub). You've been
asked to integrate with the geospatial data platform API. You have:

- The BASE_URL
- The test data table (dataset_ids, resource_ids, file names, containers)
- A vague understanding that the workflow is: submit data → wait for processing →
  approve it → access it via STAC/tiles/features

You do NOT have:
- API documentation
- Source code access
- Admin endpoints
- Knowledge of internal architecture
- A colleague to ask

Your job is to figure out the API by using it. Try to complete the full lifecycle for
each data type (raster, vector, NetCDF). Record every moment of confusion, frustration,
or surprise.
```

### Intern Instructions

**Task**: Complete the full lifecycle for all 3 data types using ONLY the consumer API surface. No docs. Figure it out.

**Exploration strategy**:
1. Start by hitting the obvious entry points — what can you discover?
   - `GET /api/platform/health` — is this the right base path?
   - `GET /api/platforms` — what does this return?
   - `GET /api/platform/status` — list mode, what's here?
2. Try to submit a raster. What fields are required? What errors do you get?
3. Once submitted, how do you check status? What does the response tell you?
4. When processing completes, how do you approve? What fields are needed?
5. After approval, how do you find the data? STAC? Tiles? Direct download?
6. Repeat for vector and NetCDF.

**Lifecycle to attempt** (all 3 data types):
```
Submit → Poll status → Approve → Discover in catalog → Access service URLs → Render/preview
```

**For each step, record**:

```
### Step {N}: {what I was trying to do}
TRIED: {method} {url}
SENT: {body, if any}
GOT: HTTP {code}
RESPONSE: {truncated to 500 chars}

CONFUSED BY: {what doesn't make sense}
EXPECTED: {what I thought would happen}
FRICTION: {what made this harder than it should be}
SUGGESTION: {what would have helped}
```

### Intern Friction Categories

Record every finding under one of these categories:

| Category | Code | What It Means |
|----------|------|---------------|
| **Discoverability** | DISC | "How was I supposed to know this endpoint/field exists?" |
| **Error Messages** | ERR | "This error message didn't help me fix the problem." |
| **Consistency** | CON | "This works differently from that other endpoint for no reason." |
| **Response Shape** | SHAPE | "This response has too much/too little/confusing data." |
| **Naming** | NAME | "This field/endpoint name is misleading or unclear." |
| **Workflow** | FLOW | "The steps to accomplish this task don't make sense." |
| **Missing Capability** | MISS | "I need to do X but there's no way to do it." |
| **Documentation** | DOC | "Even with docs, this would be confusing." |
| **Latency** | LAT | "This took surprisingly long." |
| **Silent Failure** | SILENT | "This appeared to succeed but actually didn't do what I expected." |

### Intern Output Format

```markdown
# Intern Friction Log — ADVOCATE Run {N}

## Overall Experience
{2-3 paragraphs: narrative of the experience. How did it feel? Where did you get
stuck? What was intuitive? What was baffling?}

## Lifecycle Walkthrough

### Raster
{Step-by-step account with friction annotations}

### Vector
{Step-by-step account}

### NetCDF / Zarr
{Step-by-step account}

## Friction Summary

| # | Category | Severity | Endpoint | Description |
|---|----------|----------|----------|-------------|
| F-1 | ERR | HIGH | /api/platform/submit | Error for missing field says "validation error" with no field name |
| F-2 | CON | MEDIUM | /api/platform/status | Status returns different shapes depending on lookup method |
...

## Top 5 "WTF Moments"
{The 5 most confusing things, ranked by how long they blocked progress}

## What Worked Well
{Things that were intuitive or pleasant — important for balance}
```

---

## Step 3: Dispatch Architect (Phase 2)

### Architect Persona

```
You are a senior API architect with 10 years of experience designing and reviewing
REST APIs. You've integrated with dozens of B2B platforms (Stripe, Twilio, AWS,
Azure, Snowflake). You know what good looks like.

You have:
- The BASE_URL
- The test data table
- The Intern's Friction Log (their first-impressions experience)
- Your own expertise in REST best practices

You do NOT have:
- Source code access
- Admin endpoints
- Internal architecture knowledge

Your job is to systematically audit the API against industry best practices. The
Intern's Friction Log tells you where the pain points are — use it as your
investigation queue, then go beyond it with your own systematic review.
```

### Architect Instructions

**Task**: Systematic DX audit of the full consumer surface. Use the Intern's Friction Log as your starting point, then evaluate holistically.

**Phase A: Replay Intern's Pain Points**

For each friction item in the Intern's log:
1. Reproduce the issue
2. Determine if it's a real problem or user error
3. If real, classify the root cause and assess severity
4. Propose the fix pattern (what should the response/behavior look like?)

**Phase B: Systematic REST Audit**

Evaluate every endpoint against these dimensions:

| Dimension | What to Check |
|-----------|---------------|
| **Naming** | Are endpoint paths RESTful? Consistent pluralization? Resource-oriented? |
| **HTTP Methods** | Correct method for each operation? POST for mutations, GET for reads? |
| **Status Codes** | Correct codes? 201 for creation? 404 vs 400? 409 for conflicts? |
| **Error Format** | Consistent error schema across all endpoints? Machine-parseable? |
| **Pagination** | Does list endpoints support pagination? Cursor vs offset? |
| **Idempotency** | Are POST operations idempotent? Can you safely retry? |
| **HATEOAS / Links** | Do responses include links to related resources? Next actions? |
| **Versioning** | API version in URL or header? Breaking change strategy? |
| **Response Bloat** | Are responses right-sized? Too many fields? Missing fields? |
| **Consistency** | Same patterns across all endpoints? Or each one different? |
| **Content Negotiation** | Accept header support? JSON only? |
| **Rate Limiting** | Headers present? Clear limits? |
| **Cacheability** | ETag/Last-Modified headers? Cache-Control? |

**Phase C: Cross-Endpoint Consistency Matrix**

Compare response shapes across related endpoints:

```
/api/platform/status (by request_id) vs /api/platform/status (by dataset_id+resource_id)
/api/platform/approvals vs /api/platform/status (versions array)
/api/platform/catalog/lookup vs /api/platform/catalog/dataset
/api/platform/approve error vs /api/platform/reject error vs /api/platform/submit error
```

For each pair: are the field names the same? Are the shapes consistent? Would a client need special handling for each?

**Phase D: Service URL Audit**

For each approved asset:
1. Extract service URLs from the status/catalog response
2. Hit each URL — does it work?
3. Are the URLs self-describing? Could a developer figure out what they do?
4. Are there standard discovery mechanisms (TileJSON, OGC capabilities)?
5. Is there a clear path from "I approved this data" to "I can see it on a map"?

Evaluate:
- Raster: TiTiler `/cog/*` endpoints (viewer, preview, tilejson, tiles, info)
- Vector: TiPG/OGC Features `/vector/collections/*` and `/features/collections/*`
- Zarr: TiTiler `/xarray/*` endpoints (variables, tiles, tilejson, preview, info, point)
- STAC: `/stac/collections/*` and `/stac/collections/*/items/*`

### Architect Severity Scale

| Severity | Definition | Example |
|----------|------------|---------|
| **CRITICAL** | Blocks integration entirely | "No way to discover service URLs after approval" |
| **HIGH** | Causes significant developer time waste | "Error messages don't identify which field failed" |
| **MEDIUM** | Inconsistency that requires workarounds | "Status response shape differs by lookup method" |
| **LOW** | Polish item, minor friction | "Field named `clearance_state` — unclear what this means" |
| **INFO** | Observation, not necessarily a problem | "No pagination on /approvals — fine for now, won't scale" |

### Architect Output Format

```markdown
# Architect DX Audit — ADVOCATE Run {N}

## Executive Summary
{3-5 sentences: overall API quality assessment. How does this compare to best-in-class
B2B APIs? What's the biggest structural issue?}

## Part A: Intern Pain Point Analysis

| # | Intern Finding | Confirmed? | Root Cause | Severity | Fix Pattern |
|---|----------------|------------|------------|----------|-------------|
| F-1 | {description} | YES/NO/PARTIAL | {why} | {sev} | {what good looks like} |
...

## Part B: REST Best Practices Audit

### Naming & URL Structure
| Endpoint | Issue | Recommendation | Severity |
...

### Error Handling
| Endpoint | Error Scenario | Current Response | Ideal Response | Severity |
...

### Response Consistency
| Pair | Issue | Severity |
...

{Continue for each dimension}

## Part C: Cross-Endpoint Consistency Matrix

| Field | /status | /approvals | /catalog/lookup | Consistent? |
|-------|---------|------------|-----------------|-------------|
| release_id | ✅ | ✅ | ✅ | YES |
| version_id | ✅ | ✅ | ❌ (missing) | NO |
...

## Part D: Service URL Audit

### Raster
| URL Type | URL | HTTP | Works? | Discoverable? | Notes |
...

### Vector
...

### Zarr
...

### STAC
...

## Findings by Theme

### Theme 1: {name}
{Description of the pattern, affected endpoints, recommended fix}

### Theme 2: {name}
...

## Prioritized Recommendations

| Priority | Finding | Effort | Impact | Recommendation |
|----------|---------|--------|--------|----------------|
| P0 | {description} | {S/M/L} | {high/med/low} | {specific change} |
| P1 | {description} | ... | ... | ... |
...
```

---

## Step 4: Play Editor (Synthesis)

Claude plays Editor directly. Editor receives both outputs and produces the final report.

### Editor Procedure

1. **Deduplicate**: Merge findings where Intern and Architect identified the same issue.
2. **Validate**: If Architect downgraded an Intern finding, note the reasoning.
3. **Theme**: Group related findings into themes (e.g., "Error handling inconsistency" covering 5 endpoints).
4. **Prioritize**: Rank by (severity × breadth). A MEDIUM that affects all endpoints outranks a HIGH that affects one.
5. **Score**: Calculate an overall DX score.

### Editor Scoring Rubric

| Category | Weight | What It Measures |
|----------|--------|------------------|
| Discoverability | 20% | Can a developer figure out the API without docs? |
| Error Quality | 20% | Do errors help the developer fix the problem? |
| Consistency | 20% | Same patterns across all endpoints? |
| Response Design | 15% | Right-sized, well-named, well-structured responses? |
| Service URL Integrity | 15% | Do rendered outputs work? Clear path to visualization? |
| Workflow Clarity | 10% | Does the lifecycle make sense? Clear state transitions? |

### Editor Output Format

```markdown
# ADVOCATE Report — Run {N}

**Date**: {date}
**Version**: {version}
**Target**: {BASE_URL}
**Pipeline**: ADVOCATE (B2B Developer Experience Audit)
**Agents**: Intern (first impressions) → Architect (structured audit)

---

## Executive Summary
{3-5 sentences: overall DX quality, biggest themes, comparison to industry standard}

---

## DX Score: {score}%

| Category | Weight | Score | Notes |
|----------|--------|-------|-------|
| Discoverability | 20% | {n}% | {brief} |
| Error Quality | 20% | {n}% | {brief} |
| Consistency | 20% | {n}% | {brief} |
| Response Design | 15% | {n}% | {brief} |
| Service URL Integrity | 15% | {n}% | {brief} |
| Workflow Clarity | 10% | {n}% | {brief} |

---

## Themes

### Theme 1: {name}
**Severity**: {CRITICAL/HIGH/MEDIUM/LOW}
**Affected endpoints**: {list}
**Intern's experience**: {what they hit}
**Architect's analysis**: {root cause}
**Recommendation**: {specific fix}
**Effort**: {S/M/L}

### Theme 2: {name}
...

---

## All Findings

| # | ID | Severity | Category | Endpoint(s) | Description | Source |
|---|-----|----------|----------|-------------|-------------|--------|
| 1 | ADV-1 | HIGH | ERR | /approve | {description} | Both |
| 2 | ADV-2 | MEDIUM | CON | /status | {description} | Architect |
...

---

## What Works Well
{List of things that are well-designed — important for team morale and to protect
good patterns from accidental regression}

---

## Prioritized Action Plan

### P0 — Fix Before UAT
| # | Finding | Effort | Change |
...

### P1 — Fix During UAT
| # | Finding | Effort | Change |
...

### P2 — Backlog
| # | Finding | Effort | Change |
...

---

## Pipeline Chain Recommendations

For each P0 finding, recommend which code-review pipeline to use:

| Finding | Pipeline | Target Files | Notes |
|---------|----------|-------------|-------|
| ADV-1 | REFLEXION | triggers/trigger_approvals.py | Single-file error format fix |
| ADV-3 | COMPETE | triggers/trigger_platform_status.py, services/platform_catalog_service.py | Cross-file consistency |
...

---

*Report generated by Editor — ADVOCATE pipeline, {date}*
*Specialists: Intern (first impressions), Architect (structured audit)*
```

### Save Output

Save to `docs/agent_review/agent_docs/ADVOCATE_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Asymmetry Summary

| Agent | Gets | Doesn't Get | Why |
|-------|------|-------------|-----|
| Dispatcher | Full context, config, prior findings | — | Sets up the campaign |
| Intern | BASE_URL, test data, nothing else | Docs, source code, admin endpoints, Architect's expertise | Simulates genuine newcomer confusion |
| Architect | BASE_URL, test data, Intern's Friction Log | Source code, admin endpoints | Intern's pain points become investigation queue |
| Editor | Both outputs | Source code | Full picture, can deduplicate and prioritize |

### Key Design Insight: Sequential Handoff

The Intern's Friction Log is the Architect's investigation queue. The Intern says *"this error message is useless"* — the Architect evaluates *why* and proposes the fix pattern. They complement rather than duplicate.

Without the Intern pass, the Architect would evaluate the API like an expert — missing the beginner friction. Without the Architect pass, the Intern's complaints would lack structural analysis and fix recommendations.

---

## Token Estimate

| Agent | Estimated Tokens | Notes |
|-------|-----------------|-------|
| Dispatcher | ~2K | Setup only |
| Intern | ~40-60K | Full lifecycle walkthrough, lots of HTTP calls |
| Architect | ~40-60K | Systematic audit + Intern replay |
| Editor | ~5-10K | Synthesis |
| **Total** | **~80-130K** | |

---

## When to Run ADVOCATE

| Scenario | Run ADVOCATE? |
|----------|---------------|
| After SIEGE/TOURNAMENT confirms correctness | **YES** — this is the sweet spot |
| Before UAT handoff | **YES** — catch DX issues before external testers see them |
| After major API refactor | **YES** — verify consistency wasn't broken |
| After adding new endpoints | **YES** — check new endpoints match existing patterns |
| During active development | **NO** — use SIEGE for functional correctness first |
| After Provocateur finds crashes | **NO** — fix crashes first, then evaluate DX |
