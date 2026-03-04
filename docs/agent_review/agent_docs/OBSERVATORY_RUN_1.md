# OBSERVATORY Report -- Run 1

**Date**: 03 MAR 2026
**Target**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
**Version**: 0.9.11.10
**Pipeline**: OBSERVATORY
**Goal**: Assess diagnostic endpoint coverage -- can we diagnose and preempt problems without az CLI?

---

## Executive Summary

**Overall Score: 1.46 / 3.0 (49%) -- GAPS EXIST**

The API exposes 85 endpoints across 12 systems, with 48 of 51 probed GET endpoints returning live data. Six of twelve systems meet the target diagnostic threshold (Detection >= 2, Diagnosis >= 2), meaning **half the platform can be effectively monitored without az CLI**. The other half -- Blob Storage, OGC/TiPG, Docker Worker, App Insights, Metrics, and Auth -- have blind spots ranging from shallow to total.

Three critical operational defects were discovered during the run:

1. **`/api/system-health` reports false-negative "unhealthy"** due to broken monitoring code, making Docker Worker health invisible from the API.
2. **Janitor `task_watchdog` is failing 54% of runs** (27/50) due to a SQL bug, silently degrading stuck-job detection.
3. **`/api/dbadmin/health/utilization` is dead (404)**, removing database resource monitoring from the diagnostic surface.

Additionally, 184 dead-letter messages sit on `container-tasks` and memory utilization is at 80.9%.

The diagnostic surface is strong for database, STAC, and schema concerns but lacks depth for storage, worker, and telemetry systems. With the three P0 fixes applied, coverage would rise to approximately 1.65/3.0 and operational confidence would improve materially.

---

## Coverage Matrix

Scale: 0 = None, 1 = Minimal, 2 = Adequate, 3 = Excellent

| # | System | Detection | Diagnosis | Trending | Preemption | Overall | Status |
|---|--------|:---------:|:---------:|:--------:|:----------:|:-------:|--------|
| S1 | Database | 3 | 3 | 2 | 2 | **2.50** | PASS |
| S2 | Blob Storage | 2 | 1 | 0 | 0 | **0.75** | FAIL |
| S3 | Service Bus | 3 | 3 | 1 | 1 | **2.00** | PASS |
| S4 | STAC / pgSTAC | 3 | 3 | 2 | 2 | **2.50** | PASS |
| S5 | TiTiler | 2 | 2 | 1 | 1 | **1.50** | MARGINAL |
| S6 | TiPG / OGC | 2 | 1 | 1 | 0 | **1.00** | FAIL |
| S7 | Docker Worker | 1 | 1 | 0 | 0 | **0.50** | FAIL |
| S8 | App Insights | 2 | 2 | 0 | 0 | **1.00** | FAIL |
| S9 | Job/Task Machine | 3 | 2 | 2 | 1 | **2.00** | PASS |
| S10 | Schema / DDL | 3 | 3 | 1 | 2 | **2.25** | PASS |
| S11 | Metrics | 1 | 1 | 0 | 0 | **0.50** | FAIL |
| S12 | Auth / Identity | 2 | 2 | 0 | 0 | **1.00** | FAIL |

**Systems meeting target (Detection >= 2, Diagnosis >= 2): 6 / 12**
**Systems failing target: 6 / 12** (S2, S6, S7, S8, S11, S12)
**Weighted average: 1.46 / 3.0**

### Heatmap Legend

| Score | Meaning | Color |
|-------|---------|-------|
| 2.5 - 3.0 | Excellent -- full observability | Green |
| 2.0 - 2.4 | Good -- operationally sufficient | Light Green |
| 1.5 - 1.9 | Marginal -- gaps under stress | Yellow |
| 1.0 - 1.4 | Weak -- major blind spots | Orange |
| 0.0 - 0.9 | Critical -- effectively unmonitored | Red |

---

## Endpoint Quality Summary

### Probing Results (51 GET endpoints tested)

| Category | Count | Notes |
|----------|-------|-------|
| Live and responsive | 48 | Returning valid data |
| Dead (404) | 3 | `utilization`, `artifacts/stats`, `artifacts/history` |
| Degraded | 1 | `/api/system-health` (false-negative unhealthy) |

### Quality Scores (averaged across live endpoints)

| Dimension | Average (0-3) | Interpretation |
|-----------|:-------------:|----------------|
| Completeness | 2.31 | Good -- most endpoints return structured data |
| Actionability | 1.86 | Adequate -- data present but often requires interpretation |
| Freshness | 2.67 | Strong -- most data is real-time or near-real-time |

### Tier 1 Endpoints (Excellent diagnostic value)

These endpoints provide actionable, real-time data that directly supports incident response:

| Endpoint | System | Why It Excels |
|----------|--------|---------------|
| `/api/readyz` | Core | Fast liveness check, no overhead |
| `/api/diagnostics` | Core | Cross-system summary in one call |
| `/api/dbadmin/health/performance` | S1 | Query latency, connection pool, slow queries |
| `/api/stac/health` | S4 | Collection/item counts, index health |
| `/api/cleanup/metadata-health` | S4 | Orphan detection, consistency checks |
| `/api/servicebus/health` | S3 | Queue depths, DLQ counts, subscription status |

### Problem Endpoint: `/api/health`

- Response size: **52 KB**
- Response time: **3.5 seconds**
- This endpoint aggregates too much data for a health check. It should be split into a lightweight liveness probe and a detailed diagnostics endpoint, or the existing `/api/readyz` should be promoted as the primary health check.

---

## Incident Scenario Readiness

| # | Scenario | API-Only Diagnosis? | Missing Signal | Impact |
|---|----------|:-------------------:|----------------|--------|
| 1 | Database is slow | **Yes** | No historical trending; utilization endpoint dead (404) | Can detect but not trend |
| 2 | Storage unreachable | **Partial** | No account-level health probe, no latency measurement, no per-container diagnostics | Blind to storage issues until jobs fail |
| 3 | Queue backed up | **Mostly** | No oldest-message-age metric, no depth history for trending | Can see current depth, cannot trend |
| 4 | STAC items wrong | **Yes** | Collection/item counts + metadata-health provide excellent coverage | Best-covered scenario |
| 5 | TiTiler down | **Mostly** | No error rate tracking, no render latency measurement | Can check TiTiler health but not quality |
| 6 | Worker unresponsive | **No** | `/api/system-health` broken (false-negative); no memory/CPU from worker side | Critical blind spot |
| 7 | Jobs stuck | **Partial** | `task_watchdog` SQL bug (54% failure rate); no cancel/retry API actions | Detection degraded by bug |
| 8 | Schema drifted | **Mostly** | No column-level or index-level drift detection (table-level only) | Good for table existence, weak for mutations |
| 9 | Metrics not ingesting | **No** | No App Insights health plugin; no ingestion verification endpoint | Total blind spot |
| 10 | Auth broken | **No** | No live token validation test; config endpoint shows "configured" even when credentials are invalid | Cannot distinguish configured from working |

**Scenarios fully diagnosable via API: 2 / 10** (Database slow, STAC items wrong)
**Scenarios partially diagnosable: 5 / 10**
**Scenarios NOT diagnosable: 3 / 10** (Worker unresponsive, Metrics, Auth)

---

## Gap Analysis (Priority Order)

### P0 -- Fix Immediately (Small Effort, High Impact)

These are bugs in existing code, not missing features. Each one degrades current diagnostic capability.

#### GAP-1: Fix `/api/system-health` false-negative (S7 Docker Worker)

- **Problem**: The endpoint returns `"unhealthy"` even when the worker is running. Broken monitoring code produces a false-negative, making the primary worker health signal useless.
- **Impact**: Cannot diagnose "Worker unresponsive" scenario from API. Operators must use az CLI or SSH.
- **Effort**: Small -- likely a code fix in the health aggregation logic.
- **Addresses**: Incident Scenario #6.

#### GAP-2: Fix janitor `task_watchdog` SQL bug (S9 Job/Task Machine)

- **Problem**: 27 of 50 janitor runs are failing due to a SQL bug in the `task_watchdog` function. Stuck tasks are not being detected or escalated.
- **Impact**: Jobs can silently stall without alerting. The "Jobs stuck" scenario (#7) is partially blind.
- **Effort**: Small -- SQL query fix in the janitor/watchdog code.
- **Addresses**: Incident Scenario #7.

#### GAP-3: Fix `/api/dbadmin/health/utilization` dead endpoint (S1 Database)

- **Problem**: Returns 404. The route is registered but the handler is missing or broken.
- **Impact**: Database resource utilization (connections, memory, disk) cannot be checked from the API.
- **Effort**: Small -- implement or reconnect the handler.
- **Addresses**: Incident Scenario #1 (trending gap).

### P1 -- Next Sprint (Medium Effort, Significant Impact)

#### GAP-4: Add blob storage health depth (S2)

- **Problem**: No account-level health probe, no latency measurement, no per-container diagnostics. Storage issues are invisible until jobs fail.
- **Missing endpoints**:
  - `GET /api/storage/health` -- account connectivity + latency probe
  - `GET /api/storage/{zone}/health` -- per-zone (bronze/silver/gold) health
- **Impact**: Incident Scenario #2 is only partially diagnosable.
- **Effort**: Medium -- requires BlobRepository health methods + new trigger.

#### GAP-5: Add queue trending and oldest-message-age (S3)

- **Problem**: Service Bus health shows current depths and DLQ counts but no historical trending or message age. Cannot distinguish "briefly spiked" from "steadily growing."
- **Missing signals**: Oldest message age per queue, depth snapshots over time.
- **Effort**: Medium -- add age query to Service Bus health, optionally store snapshots.
- **Addresses**: Incident Scenario #3.

#### GAP-6: Add TiTiler error rate and latency tracking (S5)

- **Problem**: TiTiler health check confirms the service is reachable but does not measure render quality, error rates, or latency.
- **Missing signals**: Error rate per tile request type, P95 render latency, failed tile count.
- **Effort**: Medium -- instrument the TiTiler proxy layer.
- **Addresses**: Incident Scenario #5.

### P2 -- Backlog (Small-to-Medium Effort, Completeness)

#### GAP-7: Add App Insights health plugin (S8)

- **Problem**: App Insights has no health plugin in the health aggregation system. Cannot verify that telemetry is flowing without az CLI.
- **Effort**: Small -- add a health plugin that queries AI for recent trace count.
- **Addresses**: Incident Scenario #9.

#### GAP-8: Add Metrics health plugin (S11)

- **Problem**: Metrics system has no health plugin. Cannot verify metric ingestion is working.
- **Effort**: Small -- add a health plugin that checks for recent metric writes.
- **Addresses**: Incident Scenario #9.

#### GAP-9: Add auth live-token test (S12)

- **Problem**: Auth config endpoint shows "configured" status but does not validate that credentials actually work. A rotated secret or expired certificate appears healthy.
- **Effort**: Small -- add a lightweight token acquisition test (acquire + discard).
- **Addresses**: Incident Scenario #10.

#### GAP-10: Add OGC Features / TiPG diagnostic depth (S6)

- **Problem**: Only basic collection listing is available. No query performance metrics, no feature count validation, no spatial index health.
- **Effort**: Medium -- add PostGIS-backed diagnostics for OGC collections.
- **Addresses**: General observability completeness.

#### GAP-11: Slim down `/api/health` response

- **Problem**: 52 KB / 3.5s is too heavy for a health check. Monitoring tools and load balancers expect fast, lightweight probes.
- **Recommendation**: Promote `/api/readyz` as the primary health check. Retain `/api/health` as a detailed diagnostics endpoint, or split into `/api/health` (lightweight) and `/api/health/full` (detailed).
- **Effort**: Small -- routing/documentation change.

---

## What Works Well

The diagnostic surface is not starting from zero. Several areas demonstrate strong engineering:

1. **Database diagnostics (S1) are excellent.** `/api/dbadmin/health/performance` provides query latency, connection pool stats, and slow query detection. Combined with `/api/dbadmin/stats` and `/api/dbadmin/diagnostics/all`, database issues can be diagnosed entirely from the API.

2. **STAC/pgSTAC observability (S4) is best-in-class.** `/api/stac/health` provides collection and item counts, index health, and consistency checks. `/api/cleanup/metadata-health` detects orphans and stale records. This is the gold standard for the platform.

3. **Service Bus monitoring (S3) is operationally useful.** Queue depths, DLQ counts, subscription status, and message peek are all available. The 184 DLQ messages on `container-tasks` were discovered entirely through API endpoints.

4. **Schema management (S10) is mature.** The `ensure` vs `rebuild` pattern with `/api/dbadmin/maintenance` provides safe, idempotent schema evolution. Table-level drift detection is solid.

5. **Job/Task machine (S9) has good detection.** Job status, task breakdowns, stage progression, and failure details are all queryable. The janitor system (when working) provides automated cleanup and watchdog functions.

6. **`/api/readyz` is an ideal liveness probe.** Fast, lightweight, and reliable. This should be the primary health check for load balancers and monitoring systems.

7. **Structured error responses.** Most diagnostic endpoints return consistent JSON with clear field names, making automated monitoring feasible.

---

## Recommendations

### Quick Wins (1-2 days total)

| # | Action | Systems | Effort |
|---|--------|---------|--------|
| QW-1 | Fix `/api/system-health` false-negative | S7 | Hours |
| QW-2 | Fix `task_watchdog` SQL bug | S9 | Hours |
| QW-3 | Fix or remove `/api/dbadmin/health/utilization` | S1 | Hours |
| QW-4 | Add App Insights health plugin | S8 | Hours |
| QW-5 | Add Metrics health plugin | S11 | Hours |
| QW-6 | Promote `/api/readyz` as primary health check | All | Documentation |

### Medium Effort (3-5 days total)

| # | Action | Systems | Effort |
|---|--------|---------|--------|
| ME-1 | Implement blob storage health probes | S2 | 1-2 days |
| ME-2 | Add queue message age + depth trending | S3 | 1 day |
| ME-3 | Add auth live-token validation | S12 | Half day |
| ME-4 | Add TiTiler error/latency instrumentation | S5 | 1 day |

### Architectural (Future sprint)

| # | Action | Systems | Effort |
|---|--------|---------|--------|
| AR-1 | Implement time-series diagnostic snapshots (store health data for trending) | All | 3-5 days |
| AR-2 | Add OGC/TiPG diagnostic depth (spatial index health, query perf) | S6 | 2-3 days |
| AR-3 | Build a `/api/diagnostics/dashboard` summary endpoint optimized for the web dashboard | All | 1-2 days |
| AR-4 | Implement worker-side health reporting (memory, CPU, active tasks) pushed to orchestrator | S7 | 2-3 days |

---

## Pipeline Chain Recommendations

For each major gap, the recommended agent review pipeline to validate the fix:

| Gap | Fix Type | Recommended Pipeline | Rationale |
|-----|----------|---------------------|-----------|
| GAP-1 (system-health) | Bug fix | **REFLEXION** | Code review of health aggregation logic |
| GAP-2 (task_watchdog) | Bug fix | **REFLEXION** then **SIEGE** | Code review + live verification |
| GAP-3 (utilization) | Bug fix / new endpoint | **SIEGE** | Live endpoint testing |
| GAP-4 (blob storage) | New feature | **COMPETE** then **SIEGE** | Design review + live testing |
| GAP-5 (queue trending) | Enhancement | **COMPETE** | Design review for data model |
| GAP-6 (TiTiler) | New feature | **COMPETE** then **SIEGE** | Design + live testing |
| GAP-7/8 (health plugins) | Small feature | **SIEGE** | Live verification sufficient |
| GAP-9 (auth test) | New feature | **TOURNAMENT** | Security-sensitive, adversarial testing |
| Full re-assessment | Validation | **OBSERVATORY Run 2** | Re-run after fixes applied |

---

## Token Usage

| Agent | Tokens | Duration | Purpose |
|-------|-------:|:--------:|---------|
| Sentinel | ~2,000 | <30s | Health check + system enumeration |
| Surveyor | 174,009 | 4m 17s | Endpoint mapping across 12 systems |
| Cartographer | 53,786 | 4m 40s | Live endpoint probing (51 endpoints) |
| Assessor | 91,248 | 3m 32s | Coverage scoring + gap analysis |
| Scribe | ~12,000 | ~2m | Report synthesis (this document) |
| **Total** | **~333,043** | **~15m** | Full pipeline |

---

## Verdict

### GAPS EXIST

The API diagnostic surface covers **6 of 12 systems** at an operationally sufficient level. Database, STAC, Service Bus, Job/Task, and Schema systems can be diagnosed without az CLI. However, **three active bugs** (false-negative system-health, task_watchdog SQL failure, dead utilization endpoint) degrade even the covered systems, and six systems (Blob Storage, OGC, Docker Worker, App Insights, Metrics, Auth) have blind spots ranging from shallow to total.

**The platform cannot yet replace az CLI for full operational diagnosis**, but it is closer than expected. Applying the three P0 fixes would raise the weighted average from 1.46 to approximately 1.65/3.0 and restore confidence in the systems that are already instrumented. The P1 blob storage and queue trending work would address the two most operationally dangerous blind spots.

**Recommended next action**: Fix GAP-1, GAP-2, and GAP-3 (estimated: 1 day), then schedule OBSERVATORY Run 2 to re-assess.

---

*Report generated by OBSERVATORY pipeline (Sentinel -> Surveyor -> Cartographer -> Assessor -> Scribe)*
*03 MAR 2026 | v0.9.11.10 | ~333,043 tokens | ~15 minutes*
