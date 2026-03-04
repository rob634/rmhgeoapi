# Pipeline 8: OBSERVATORY (Infrastructure Diagnostic Coverage Assessment)

**Purpose**: Assess whether the API's diagnostic endpoints provide sufficient observability to diagnose and preempt problems without `az cli` access. Two-phase pipeline: static code analysis to map systems and their diagnostic surface, then live probing to grade response quality and coverage.

**Best for**: Periodic observability audit, pre-release diagnostic readiness check, "can I diagnose X without az cli?" assessment.

**Derived from**: SIEGE (Pipeline 4) — same sequential structure, same endpoint probing discipline, repurposed from workflow verification to diagnostic coverage grading.

---

## Goal

Produce a **Coverage Matrix** that grades every infrastructure subsystem on four diagnostic dimensions:

| Dimension | Question | Grade Scale |
|-----------|----------|-------------|
| **Detection** | Can I tell *that* something is wrong? | 0 = no signal, 1 = binary up/down, 2 = specific error, 3 = error + context |
| **Diagnosis** | Can I tell *what* is wrong? | 0 = no info, 1 = error category, 2 = root cause hint, 3 = actionable fix |
| **Trending** | Can I see it getting worse *before* it breaks? | 0 = no history, 1 = point-in-time, 2 = recent window, 3 = trend data |
| **Preemption** | Can I act before users notice? | 0 = no action, 1 = manual fix path, 2 = guided remediation, 3 = self-healing/auto-alert |

**Target**: Every subsystem should score >= 2 on Detection and Diagnosis. Trending and Preemption are stretch goals.

---

## Infrastructure Systems Inventory

These are the systems OBSERVATORY assesses. Sentinel confirms this list during setup.

| # | System | Code Location | Current az CLI Dependency |
|---|--------|---------------|--------------------------|
| S1 | **PostgreSQL Database** | `infrastructure/db_repository.py`, `infrastructure/release_repository.py` | `az postgres flexible-server ...` for connectivity, slow queries, locks |
| S2 | **Azure Blob Storage** | `infrastructure/blob_repository.py`, `services/handler_*.py` | `az storage blob ...` for existence checks, account health, metrics |
| S3 | **Service Bus Queues** | `infrastructure/queue_service.py`, `triggers/service_bus/` | `az servicebus queue ...` for depth, DLQ, consumer health |
| S4 | **STAC / pgSTAC** | `infrastructure/stac_repository.py`, `triggers/stac/` | `az postgres ...` + direct SQL for collection/item integrity |
| S5 | **TiTiler (Raster)** | External service, referenced in `services/platform_translation.py` | Direct HTTP probes (no az CLI, but no dedicated diagnostic endpoint) |
| S6 | **TiPG (Vector/OGC)** | External service, referenced in `triggers/features/` | Direct HTTP probes |
| S7 | **Docker Worker** | `triggers/worker/`, Dockerfile | `az webapp log ...`, `az webapp show ...` for status, restarts, resource usage |
| S8 | **Application Insights** | `triggers/probes.py` (query/export endpoints) | `az monitor app-insights query ...` for log queries |
| S9 | **Job/Task State Machine** | `core/machine.py`, `jobs/`, `services/` | `/api/dbadmin/jobs` exists, but stuck-job detection requires manual queries |
| S10 | **Schema/DDL** | `core/models/`, `triggers/admin/admin_db.py` | Schema drift detection requires manual `\d+` comparisons |
| S11 | **Metrics/Telemetry** | `services/metrics_logger.py`, `triggers/probes.py` | Flush status exists, but ingestion health requires Azure Portal |
| S12 | **Authentication/Identity** | `config/`, managed identity | `az ad ...`, `az role assignment ...` for RBAC verification |

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Sentinel | Define systems inventory, verify API is live | Claude (no subagent) | This document, codebase |
| Surveyor | Static code analysis — map diagnostic surface per system | Task (sequential) | Systems Inventory + codebase file list |
| Cartographer | Live probe every diagnostic endpoint | Task (sequential) | Surveyor's Endpoint Registry |
| Assessor | Grade coverage per system, identify gaps | Task (sequential) | Surveyor's System Registry + Cartographer's Probe Results |
| Scribe | Final report with coverage matrix and recommendations | Task (sequential) | All previous outputs |

**Maximum parallel agents**: 0 (all sequential)

---

## Flow

```
Target: BASE_URL (Azure endpoint) + codebase (local)
    |
    Sentinel (Claude — no subagent)
        Verifies /api/health responds
        Confirms Systems Inventory (S1–S12)
        Outputs: Campaign Brief
    |
    Surveyor (Task)                              [sequential]
        Reads infrastructure code (NO HTTP calls)
        Maps: system → internal state → diagnostic endpoints → az CLI gaps
        OUTPUT: System Registry + Endpoint Registry
    |
    Cartographer (Task)                          [sequential]
        Probes every endpoint from Endpoint Registry
        Grades response quality (shape, latency, actionability)
        OUTPUT: Probe Results
    |
    Assessor (Task)                              [sequential]
        Cross-references System Registry vs Probe Results
        Grades each system on 4 dimensions
        OUTPUT: Coverage Matrix + Gap Analysis
    |
    Scribe (Task)                                [sequential]
        Synthesizes final report
        OUTPUT: OBSERVATORY Report
```

---

## Prerequisites

```bash
BASE_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

# Health check (confirms API is live — NO destructive operations)
curl -sf "${BASE_URL}/api/health"

# OBSERVATORY is read-only. No schema rebuild. No STAC nuke.
# It only GETs diagnostic endpoints — never mutates state.
```

**Hard rule**: OBSERVATORY is 100% non-destructive. No POSTs to action endpoints. No maintenance operations. Read-only diagnostic probing only.

---

## Step 1: Play Sentinel (No Subagent)

Claude plays Sentinel directly. Sentinel's job:

1. Verify `/api/health` returns 200.
2. Confirm the Systems Inventory (S1–S12) is current by checking codebase structure:
   - `ls infrastructure/` — verify repository files exist
   - `ls triggers/admin/` — verify admin endpoint files exist
   - `ls triggers/stac/` — verify STAC endpoints exist
3. Note the deployed version from `/api/health` response.
4. Output the Campaign Brief:
   - BASE_URL
   - Deployed version
   - Confirmed Systems Inventory (add/remove systems if codebase has changed)
   - File list for Surveyor to read

---

## Step 2: Dispatch Surveyor

Surveyor performs **static code analysis only** — no HTTP calls. Its job is to map what diagnostic surface exists per system by reading the code.

### Surveyor Instructions

For each system S1–S12, read the relevant code files and produce:

1. **Internal State Tracked**: What state does this system maintain? (tables, queues, blobs, connections, caches)
2. **Diagnostic Endpoints**: Which HTTP endpoints expose this system's state? (URL, method, what it returns)
3. **Health Check Coverage**: Is this system included in `/api/health`? What does the health plugin check?
4. **az CLI Currently Required For**: What operations currently require `az cli` that the API doesn't expose?
5. **Error Signals**: When this system fails, how does the API report it? (HTTP codes, error messages, log patterns)

### Surveyor File Reading Guide

| System | Read These Files |
|--------|-----------------|
| S1 Database | `infrastructure/db_repository.py`, `triggers/admin/admin_db.py`, `triggers/health.py` |
| S2 Blob Storage | `infrastructure/blob_repository.py`, `triggers/list_storage_containers.py`, `triggers/health.py` |
| S3 Service Bus | `infrastructure/queue_service.py`, `triggers/admin/admin_servicebus.py`, `triggers/health.py` |
| S4 STAC/pgSTAC | `infrastructure/stac_repository.py`, `triggers/stac/stac_bp.py`, `triggers/health.py` |
| S5 TiTiler | `services/platform_translation.py`, `triggers/health.py` |
| S6 TiPG/OGC | `triggers/features/`, `triggers/health.py` |
| S7 Docker Worker | `triggers/worker/`, `triggers/system_health.py`, `triggers/health.py` |
| S8 App Insights | `triggers/probes.py` (appinsights endpoints) |
| S9 Job/Task Machine | `core/machine.py`, `triggers/get_job_status.py`, `triggers/admin/admin_db.py` |
| S10 Schema/DDL | `core/models/`, `triggers/admin/admin_db.py` (maintenance endpoint) |
| S11 Metrics | `services/metrics_logger.py`, `triggers/probes.py` (metrics endpoints) |
| S12 Auth/Identity | `config/__init__.py`, `infrastructure/blob_repository.py` (credential handling) |

### Surveyor Output Format

```markdown
## System Registry

### S{N}: {System Name}

**Internal State**:
- {state item 1}
- {state item 2}

**Diagnostic Endpoints**:
| Endpoint | Method | Returns | Actionability |
|----------|--------|---------|---------------|
| `/api/...` | GET | {description} | {high/medium/low} |

**Health Plugin**: {yes/no — what it checks}

**az CLI Still Required For**:
- {operation 1}: `az {command}` — {why API can't do this}
- {operation 2}: ...

**Error Signals**:
- {failure mode} → {how API reports it}

---

## Endpoint Registry

(Flat list of ALL diagnostic endpoints for Cartographer to probe)

| # | Endpoint | Method | System | Purpose |
|---|----------|--------|--------|---------|
| 1 | `/api/health` | GET | All | Aggregate health |
| 2 | `/api/diagnostics` | GET | All | Deep connectivity |
...
```

---

## Step 3: Dispatch Cartographer

Cartographer probes every endpoint from Surveyor's Endpoint Registry. Unlike SIEGE's Cartographer (which checks liveness), OBSERVATORY's Cartographer grades **diagnostic quality**.

### Cartographer Probe Protocol

For each endpoint in the Endpoint Registry:

1. **Call it** with default parameters (no auth required — these are admin endpoints on internal network)
2. **Record**: HTTP code, latency, response size, content-type
3. **Grade response quality** on 3 axes:

| Axis | Question | Score |
|------|----------|-------|
| **Completeness** | Does it return all relevant data for its system? | 0-3 |
| **Actionability** | Can I act on this information without additional tools? | 0-3 |
| **Freshness** | Is this real-time, cached, or stale? | 0-3 |

Scoring guide:
- **0**: Empty, error, or useless response
- **1**: Basic info, needs other tools to interpret
- **2**: Good info, actionable with domain knowledge
- **3**: Excellent — tells you exactly what's wrong and suggests next steps

### Cartographer Probe Table

**Core Health & Probes**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/livez` | GET | none | 200 | Liveness only — should respond even if dependencies are down |
| `/api/readyz` | GET | none | 200/503 | Startup validation check |
| `/api/readyz?deep=true` | GET | deep=true | 200 | Lightweight diagnostics mode |
| `/api/health` | GET | none | 200 | Full 20-plugin health check — grade each plugin's output |
| `/api/diagnostics` | GET | none | 200 | Connectivity, DNS, pools — grade depth of each section |
| `/api/diagnostics?timeout=5` | GET | timeout=5 | 200 | Verify timeout parameter works |

**Database Diagnostics**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/dbadmin/health` | GET | none | 200 | DB connection health |
| `/api/dbadmin/health/performance` | GET | none | 200 | Performance metrics — grade: latency numbers? slow query list? |
| `/api/dbadmin/activity?type=running` | GET | type=running | 200 | Running queries — can I see long-running queries? |
| `/api/dbadmin/activity?type=slow` | GET | type=slow | 200 | Slow query history |
| `/api/dbadmin/activity?type=locks` | GET | type=locks | 200 | Lock contention — can I see deadlocks? |
| `/api/dbadmin/activity?type=connections` | GET | type=connections | 200 | Connection pool usage |
| `/api/dbadmin/diagnostics?type=stats` | GET | type=stats | 200 | Aggregate DB stats |
| `/api/dbadmin/diagnostics?type=enums` | GET | type=enums | 200 | Enum types in DB |
| `/api/dbadmin/diagnostics?type=config` | GET | type=config | 200 | DB configuration |
| `/api/dbadmin/diagnostics?type=errors` | GET | type=errors | 200 | Recent DB errors |
| `/api/dbadmin/diagnostics?type=geo_integrity` | GET | type=geo_integrity | 200 | Geo data integrity |
| `/api/dbadmin/diagnostics?type=user_privileges` | GET | type=user_privileges | 200 | Permission check |
| `/api/dbadmin/diagnostics?type=all` | GET | type=all | 200 | Everything at once |
| `/api/dbadmin/schemas` | GET | none | 200 | Schema inventory |
| `/api/dbadmin/jobs?limit=5&status=failed` | GET | limit, status | 200 | Failed jobs — grade: error details? stack traces? |
| `/api/dbadmin/jobs?limit=5&status=processing` | GET | limit, status | 200 | Stuck jobs — can I detect them? |

**Service Bus**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/servicebus?type=queues` | GET | type=queues | 200 | Queue inventory — active count, DLQ count? |
| `/api/servicebus?type=health` | GET | type=health | 200 | Queue health assessment |

**Storage**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/storage/containers` | GET | none | 200 | Container listing — zone grouping? |
| `/api/storage/containers?zone=bronze` | GET | zone=bronze | 200 | Zone-filtered listing |

**STAC**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/stac/health` | GET | none | 200 | pgSTAC health metrics |
| `/stac/schema/info` | GET | none | 200 | Schema integrity |
| `/stac/collections/summary` | GET | none | 200 | Quick collection overview |
| `/stac/collections` | GET | none | 200 | Full collection list |

**System & Infrastructure**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/system-health` | GET | none | 200 | Cross-app health aggregation |
| `/api/system/stats` | GET | none | 200 | Memory, CPU, job stats |
| `/api/system/snapshot` | GET | none | 200 | Latest config snapshot |
| `/api/system/snapshot/drift` | GET | none | 200 | Config drift history |

**Metrics & Observability**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/metrics/stats` | GET | none | 200 | Metrics buffer status |
| `/api/appinsights/templates` | GET | none | 200 | Available log query templates |

**Cleanup & Maintenance**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/cleanup/status` | GET | none | 200 | Janitor config and status |
| `/api/cleanup/metadata-health` | GET | none | 200 | Cross-reference integrity |
| `/api/cleanup/history?hours=24` | GET | hours=24 | 200 | Recent cleanup runs |

**Artifacts**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/admin/artifacts/stats` | GET | none | 200 | Artifact statistics |
| `/api/admin/artifacts/history` | GET | none | 200 | Recent artifact activity |

**External Services**:

| Endpoint | Method | Params | Expected | Notes |
|----------|--------|--------|----------|-------|
| `/api/jobs/services` | GET | none | 200 | Registered external services |
| `/api/jobs/services/stats` | GET | none | 200 | Service usage stats |

### Cartographer Output Format

```markdown
## Probe Results

### Category: {category name}

| # | Endpoint | HTTP | Latency (ms) | Size | Completeness | Actionability | Freshness | Notes |
|---|----------|------|-------------|------|-------------|---------------|-----------|-------|
| 1 | `/api/health` | 200 | 450 | 2.1KB | 3 | 3 | 3 | 20 plugins, each with status + detail |
| 2 | `/api/dbadmin/health` | 200 | 120 | 340B | 2 | 1 | 3 | Says "connected" but no latency numbers |
...

### Probe Summary

| Category | Endpoints | Live | Error | Avg Completeness | Avg Actionability | Avg Freshness |
|----------|-----------|------|-------|-----------------|-------------------|---------------|
| Core Health | 6 | 6 | 0 | 2.8 | 2.5 | 3.0 |
| Database | 16 | 15 | 1 | 2.1 | 1.8 | 2.5 |
...
```

---

## Step 4: Dispatch Assessor

Assessor cross-references Surveyor's System Registry against Cartographer's Probe Results to produce the Coverage Matrix.

### Assessor Procedure

For each system S1–S12:

1. **List all internal state** (from Surveyor)
2. **List all diagnostic endpoints** that cover this system (from Surveyor + Cartographer)
3. **Grade Detection**: Can I tell something is wrong?
   - Check: Does `/api/health` include this system? Do dedicated endpoints exist? Do they return error states clearly?
4. **Grade Diagnosis**: Can I tell *what* is wrong?
   - Check: Do endpoints return specific error messages? Stack traces? Affected resources? Suggested fixes?
5. **Grade Trending**: Can I see degradation over time?
   - Check: Is there historical data? Point-in-time snapshots? Drift detection? Comparison windows?
6. **Grade Preemption**: Can I act before users notice?
   - Check: Are there threshold alerts? Auto-remediation? Guided cleanup? Watchdog jobs?
7. **Identify az CLI gaps**: For each operation that still requires az CLI (from Surveyor), assess:
   - How critical is this operation? (daily / weekly / incident-only)
   - How hard is it to add an API endpoint for this?
   - Priority: P0 (daily ops), P1 (weekly ops), P2 (incident-only), P3 (nice-to-have)

### Assessor Scenario Grading

For each system, grade against these **incident scenarios**:

| Scenario | What You Need to Know | Current Source |
|----------|----------------------|----------------|
| "Database is slow" | Slow queries, lock contention, connection count | API or az CLI? |
| "Storage is full/unreachable" | Account health, capacity, connectivity | API or az CLI? |
| "Queue is backed up" | Depth, consumer count, DLQ items, oldest message age | API or az CLI? |
| "STAC items are wrong" | Collection/item count, integrity, orphans | API or az CLI? |
| "TiTiler is down" | Liveness, error rate, last successful render | API or az CLI? |
| "Worker is unresponsive" | Container status, restart count, memory/CPU | API or az CLI? |
| "Jobs are stuck" | Stuck job count, last progress, task breakdown | API or az CLI? |
| "Schema drifted" | Expected vs actual tables/columns/indexes | API or az CLI? |
| "Metrics aren't ingesting" | Buffer size, last flush, AI ingestion status | API or az CLI? |
| "Auth is broken" | Token validity, RBAC roles, managed identity status | API or az CLI? |

### Assessor Output Format

```markdown
## Coverage Matrix

| System | Detection | Diagnosis | Trending | Preemption | az CLI Gaps | Priority |
|--------|-----------|-----------|----------|------------|-------------|----------|
| S1 Database | {0-3} | {0-3} | {0-3} | {0-3} | {count} | {P0-P3} |
| S2 Blob Storage | {0-3} | {0-3} | {0-3} | {0-3} | {count} | {P0-P3} |
...

## Gap Analysis

### S{N}: {System Name} — Score: {avg}/3.0

**What Works**:
- {endpoint} provides {capability}

**What's Missing**:
- {gap}: Currently requires `az {command}` — {frequency of need}
- {gap}: No endpoint exists — {impact}

**Recommendation**: {specific endpoint or enhancement to add}
**Effort**: {small/medium/large}
**Priority**: {P0/P1/P2/P3}

---

## Incident Scenario Coverage

| Scenario | Can Diagnose via API? | Missing Signal | Priority |
|----------|----------------------|----------------|----------|
| "Database is slow" | {YES/PARTIAL/NO} | {what's missing} | {P0-P3} |
...
```

---

## Step 5: Dispatch Scribe

Scribe receives all outputs and produces the final OBSERVATORY report.

### Scribe Output Format

```markdown
# OBSERVATORY Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version}
**Pipeline**: OBSERVATORY
**Goal**: Assess diagnostic endpoint coverage — can we diagnose and preempt problems without az CLI?

## Executive Summary

**Overall Diagnostic Readiness**: {score}% ({X}/{Y} systems at target coverage)
**az CLI Dependencies Remaining**: {count} operations across {N} systems
**Critical Gaps**: {count} — systems where failure would require az CLI to diagnose

## Coverage Matrix

| System | Detection | Diagnosis | Trending | Preemption | Overall | az CLI Gaps | Priority |
|--------|-----------|-----------|----------|------------|---------|-------------|----------|
| S1 Database | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S2 Blob Storage | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S3 Service Bus | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S4 STAC/pgSTAC | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S5 TiTiler | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S6 TiPG/OGC | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S7 Docker Worker | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S8 App Insights | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S9 Job/Task Machine | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S10 Schema/DDL | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S11 Metrics | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |
| S12 Auth/Identity | {0-3} | {0-3} | {0-3} | {0-3} | {avg} | {count} | {P0-P3} |

### Coverage Heatmap

(Visual representation — systems along Y axis, dimensions along X axis)

```
              Detection  Diagnosis  Trending  Preemption
S1  Database  [███████]  [███████]  [█████░░]  [███░░░░]
S2  Storage   [█████░░]  [███░░░░]  [░░░░░░░]  [░░░░░░░]
S3  Queues    [███████]  [█████░░]  [█████░░]  [███░░░░]
...
```

Legend: █ = covered (score 2-3), ░ = gap (score 0-1)

## Endpoint Quality Summary

| Category | Endpoints Probed | Avg Completeness | Avg Actionability | Avg Freshness |
|----------|-----------------|-----------------|-------------------|---------------|
| Core Health | {n} | {0-3} | {0-3} | {0-3} |
| Database | {n} | {0-3} | {0-3} | {0-3} |
| Service Bus | {n} | {0-3} | {0-3} | {0-3} |
| Storage | {n} | {0-3} | {0-3} | {0-3} |
| STAC | {n} | {0-3} | {0-3} | {0-3} |
| System | {n} | {0-3} | {0-3} | {0-3} |
| Metrics | {n} | {0-3} | {0-3} | {0-3} |
| Cleanup | {n} | {0-3} | {0-3} | {0-3} |

## Incident Scenario Readiness

| Scenario | API-Only? | Missing Signal | Workaround | Priority |
|----------|-----------|----------------|------------|----------|
| "Database is slow" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Storage unreachable" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Queue backed up" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "STAC items wrong" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "TiTiler down" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Worker unresponsive" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Jobs stuck" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Schema drifted" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Metrics broken" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |
| "Auth broken" | {YES/PARTIAL/NO} | {gap} | {az cli command} | {P0-P3} |

## Gap Analysis (Priority Order)

### P0 — Daily Operations (must fix)

**{Gap Title}**
- System: S{N} {name}
- Current state: {what's missing}
- Impact: {what happens during incident}
- az CLI workaround: `az {command}`
- Recommended endpoint: `{method} /api/{path}` returning `{shape}`
- Effort: {small/medium/large}

### P1 — Weekly Operations (should fix)
...

### P2 — Incident-Only (nice to have)
...

## What Works Well

(Highlight systems with strong diagnostic coverage — acknowledge good design)

1. {system}: {why it's well-covered}
2. ...

## Recommendations

### Quick Wins (< 1 day each)
1. {recommendation}
2. ...

### Medium Effort (1-3 days each)
1. {recommendation}
2. ...

### Architectural (requires design)
1. {recommendation}
2. ...

## Pipeline Chain Recommendations

For each P0/P1 gap, recommend which agent pipeline to use for implementation:

| Gap | Pipeline | Scope | Rationale |
|-----|----------|-------|-----------|
| {gap} | GREENFIELD | New endpoint | New diagnostic endpoint from scratch |
| {gap} | REFLEXION | Existing endpoint | Harden existing endpoint to return more data |
| {gap} | COMPETE | Infrastructure code | Review infrastructure layer for hidden diagnostic opportunities |

## Verdict

{SUFFICIENT | GAPS EXIST | INSUFFICIENT}

**Can diagnose without az CLI**: {X}/{10} incident scenarios
**Remaining az CLI dependencies**: {list}
```

### Save Output

Save to `docs/agent_review/agent_docs/OBSERVATORY_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Flow Summary

| Agent | Gets | Doesn't Get |
|-------|------|-------------|
| Sentinel | This document, codebase access | Nothing (defines everything) |
| Surveyor | Campaign Brief, codebase file list | Live endpoint responses |
| Cartographer | Surveyor's Endpoint Registry | Surveyor's gap analysis (avoids bias) |
| Assessor | Surveyor's System Registry + Cartographer's Probe Results | Surveyor's recommendations (forms own conclusions) |
| Scribe | All outputs from all agents | Nothing hidden |

**Note**: Cartographer does NOT see Surveyor's gap analysis — this prevents confirmation bias. Cartographer grades response quality purely on what the endpoint returns. Assessor then combines both perspectives.

**Note**: Assessor does NOT see Surveyor's recommendations — Assessor forms independent conclusions about gaps and priorities, then Scribe reconciles.

---

## Differences from SIEGE

| Aspect | SIEGE | OBSERVATORY |
|--------|-------|-------------|
| **Purpose** | Verify workflows work | Assess diagnostic coverage |
| **Mutates state** | Yes (submits, approves, etc.) | No (read-only probing) |
| **Endpoints probed** | Platform API (B2B surface) | Admin/diagnostic endpoints |
| **Includes static analysis** | No | Yes (Surveyor reads code) |
| **Output** | Pass/fail per workflow | Coverage matrix per system |
| **Destructive prerequisites** | Schema rebuild + STAC nuke | None (health check only) |
| **When to run** | After deployment | Before deployment or periodically |
