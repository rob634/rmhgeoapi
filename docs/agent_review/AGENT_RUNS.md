# Agent Pipeline Run Log

All pipeline executions in chronological order.

---

## Run 1: CoreMachine Orchestration Review

| Field | Value |
|-------|-------|
| **Date** | 26 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Job pipeline orchestrator — CoreMachine, StateManager, triggers |
| **Files** | ~25 |
| **Scope Split** | Architecture vs Correctness |
| **Findings** | 18 total |
| **Fixes Applied** | 5 (1 CRITICAL, 2 HIGH, 2 MEDIUM) |
| **Commit** | `fa05cc1` (V0.9.8.1) |
| **Tests** | 352 passing |
| **Output** | `agent_docs/REVIEW_SUMMARY.md` (combined) |

---

## Run 2: Vector Workflow Review

| Field | Value |
|-------|-------|
| **Date** | 26 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Complete vector pipeline — ingestion, PostGIS, STAC, approval, unpublish |
| **Files** | ~20 |
| **Scope Split** | Architecture vs Correctness |
| **Findings** | 12 total |
| **Fixes Applied** | 10 (1 CRITICAL, 3 HIGH, 4 MEDIUM, 1 LOW, 1 pre-resolved) |
| **Commit** | `8355f7c` |
| **Tests** | 330 passing |
| **Output** | `agent_docs/REVIEW_SUMMARY.md` (combined) |

---

## Run 3: Tiled Raster Pipeline Review

| Field | Value |
|-------|-------|
| **Date** | 27 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Large file COG tiling → pgSTAC → TiTiler mosaic |
| **Files** | ~10 |
| **Scope Split** | Architecture vs Correctness |
| **Findings** | 9 total |
| **Fixes Applied** | 5+1 (1 CRITICAL, 2 HIGH, 2 MEDIUM + dead code removal) |
| **Commit** | `51e8a28` |
| **Tests** | 352 passing |
| **Output** | `agent_docs/REVIEW_SUMMARY.md` (combined) |

---

## Run 4: Approval Workflow Review

| Field | Value |
|-------|-------|
| **Date** | 27 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Approve/Reject/Revoke lifecycle across 3 trigger layers |
| **Files** | 7 |
| **Scope Split** | Architecture vs Correctness |
| **Findings** | 21 total |
| **Fixes Applied** | 5 (1 CRITICAL, 2 HIGH, 1 MEDIUM, 1 LOW) |
| **Commit** | `088aca9` |
| **Tests** | 362 passing |
| **Output** | `agent_docs/REVIEW_SUMMARY.md` (combined) |

---

## Run 5: B2B Domain Review A

| Field | Value |
|-------|-------|
| **Date** | 27 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Entity design, state machines, repositories |
| **Files** | 10 |
| **Scope Split** | Architecture vs Correctness |
| **Findings** | 13 total |
| **Fixes Applied** | 5 (2 CRITICAL, 3 HIGH) |
| **Commit** | `416124c` (V0.9.8.2, combined with Run 6 + Run 7) |
| **Tests** | Deployed + rebuilt |
| **Output** | `agent_docs/REVIEW_SUMMARY.md` (combined) |

---

## Run 6: B2B Domain Review B

| Field | Value |
|-------|-------|
| **Date** | 28 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | HTTP contracts, lifecycle integration, 3 approval layers |
| **Files** | 12 |
| **Scope Split** | Architecture vs Correctness |
| **Findings** | 37 total |
| **Fixes Applied** | 5 (1 CRITICAL, 4 HIGH) |
| **Commit** | `416124c` (V0.9.8.2, combined with Run 5 + Run 7) |
| **Tests** | Deployed + rebuilt |
| **Output** | `agent_docs/REVIEW_SUMMARY.md` (combined) |

**Note**: Runs 5 + 6 reviewed 22 files / ~15,000 lines across B2B domain. 50 unique findings after dedup, 10 fixes total.

---

## Run 7: Approval Conflict Guard (Greenfield)

| Field | Value |
|-------|-------|
| **Date** | 28 FEB 2026 |
| **Pipeline** | GREENFIELD |
| **Scope** | Version-ID conflict guard and atomic rollback for release approval |
| **Agents** | S → A+C+O → M → B → V |
| **Components Built** | `idx_releases_version_conflict` partial unique index, NOT EXISTS subquery in `approve_release_atomic()`, `rollback_approval_atomic()`, typed error responses via `ERROR_STATUS_MAP` |
| **Commit** | `416124c` (V0.9.8.2, combined with Runs 5+6) |
| **Output** | `agent_docs/MEDIATOR_RESOLUTION.md` |

---

## Run 8: VirtualiZarr Pipeline (Greensight)

| Field | Value |
|-------|-------|
| **Date** | 27 FEB 2026 |
| **Pipeline** | GREENFIELD (labeled "Greensight") |
| **Scope** | VirtualiZarr NetCDF ingestion pipeline — scan, validate, combine, register STAC |
| **Agents** | S → A+C+O → M → B → V |
| **V Rating** | NEEDS MINOR WORK (5 must-fix, 6 should-fix) |
| **Components Built** | `VirtualZarrJob` (4-stage), 4 handlers (scan, validate, combine, register), DataType enum extension, approval materialization zarr branch |
| **Mediator Conflicts** | 12 resolved (numpy pin, SB 256KB limit, stage count 5→4, STAC collection builder, approval path) |
| **Deferred Decisions** | 9 (TiTiler-xarray, ETag, checkpoint/resume, datacube extension, partial cleanup, dedicated queue, numpy 2, per-file refs, non-standard calendars) |
| **Commit** | `ad3b8bd` |
| **Output** | `agent_docs/GREENSIGHT_PIPELINE.md` |

---

## Run 9: Unpublish Subsystem Review

| Field | Value |
|-------|-------|
| **Date** | 28 FEB 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Unpublish — reverse-ETL pipeline for raster, vector, and (future) zarr |
| **Files** | 5 primary + 8 supporting infrastructure |
| **Scope Split** | C (Data vs Control Flow) |
| **Findings** | 22 total |
| **Fixes Applied** | 2 CRITICAL (zero-task Stage 2 hang in CoreMachine, release revocation timing) |
| **Accepted Risks** | 7 (AR-1 through AR-7) |
| **Commit** | Applied inline during session |
| **Output** | `agent_docs/UNPUBLISH_SUBSYSTEM_REVIEW.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Omega | Scope split | ~0 | inline |
| Alpha | Data Integrity | 81,312 | 4m 36s |
| Beta | Flow Control | 114,589 | 4m 19s |
| Gamma | Contradictions | 82,310 | 3m 57s |
| Delta | Final Report | 68,445 | 3m 25s |
| **Total** | | **346,656** | **~16m 17s** |

---

## Run 10: Zarr Unpublish (Greenfield)

| Field | Value |
|-------|-------|
| **Date** | 28 FEB 2026 |
| **Pipeline** | GREENFIELD |
| **Scope** | Zarr unpublish — reverse VirtualiZarr pipeline |
| **Agents** | S → A+C+O → M → B → V → Spec Diff |
| **V Rating** | NEEDS MINOR WORK (2 integration gaps, fixed post-review) |
| **Components Built** | `UnpublishZarrJob` (3-stage), `inventory_zarr_item` handler, zarr routing in unpublish trigger, `_execute_zarr_unpublish`, `UnpublishType.ZARR` enum value |
| **Files Modified** | 8 (1 new, 7 modified) |
| **Mediator Conflicts** | 10 resolved |
| **Deferred Decisions** | 5 (failed pipeline cleanup, collection-level unpublish, concurrent guard, deep dry-run, TiTiler-xarray cache) |
| **Deployment Prereq** | `ALTER TYPE app.unpublish_type ADD VALUE 'zarr'` |
| **Output** | `agent_docs/GREENFIELD_ZARR_UNPUBLISH.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| S | Spec Writer | — | inline |
| A | Advocate (design) | 95,473 | 3m 6s |
| C | Critic (gaps) | 113,438 | 3m 24s |
| O | Operator (ops) | 112,153 | 3m 37s |
| M | Mediator (resolve) | 121,278 | 4m 31s |
| B | Builder (code) | 115,645 | 7m 47s |
| V | Validator (review) | 73,209 | 2m 30s |
| **Total** | | **631,196** | **~24m 55s** |

---

## Run 11: Platform API Smoke Test (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | SIEGE |
| **Scope** | Full Platform API surface — endpoint health, raster/vector lifecycles, multi-version, unpublish |
| **Target** | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` (v0.9.9.0) |
| **Agents** | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| **Verdict** | **FAIL** — 6/11 workflow steps passed (54.5%) |
| **Findings** | 11 total: 1 CRITICAL, 2 HIGH, 4 MEDIUM, 4 LOW |
| **Key Bugs** | STAC materialization ordering (blocks raster approval), SQL error leak on approvals/status, catalog/dataset returns 500 |
| **Fixes Applied** | None (report only) |
| **Output** | `agent_docs/SIEGE_RUN_1.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Sentinel | Campaign brief | — | inline |
| Cartographer | Endpoint probing | 34,172 | 1m 48s |
| Lancer | Lifecycle execution | 69,735 | 7m 34s |
| Auditor | State verification | 45,628 | 2m 42s |
| Scribe | Report synthesis | 29,258 | 1m 20s |
| **Total** | | **178,793** | **~13m 24s** |

**Finding Summary**:

| ID | Severity | Description |
|----|----------|-------------|
| SG-1 | CRITICAL | STAC materialization calls item insert before collection create |
| SG-2 | HIGH | SQL error message leaked to B2B callers on approvals/status |
| SG-3 | HIGH | /api/platform/catalog/dataset/{id} returns 500 instead of 404 |
| SG-4 | MEDIUM | Approval rollbacks not surfaced on /api/platform/failures |
| SG-5 | MEDIUM | Orphaned 127 MB COG blob with no catalog reference |
| SG-6 | MEDIUM | stac_item_id mismatch: release says -v1, cached JSON says -ord1 |
| SG-7 | MEDIUM | is_latest not restored after approval rollback |
| SG-8 | LOW | Inconsistent 404 response shape on lineage endpoint |
| SG-9 | LOW | /api/dbadmin/stats and diagnostics/all return 404 |
| SG-10 | LOW | /api/health takes 3.9s (too slow for health probes) |
| SG-11 | LOW | Resubmit bumps revision, not version — may surprise callers |

---

## Run 12: SG-6 STAC Item ID Naming Convention

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | COMPETE |
| **Scope** | STAC item ID naming lifecycle — `-ord{N}` vs `-v{version_id}` mismatch |
| **Files** | 8 primary + 6 supporting |
| **Scope Split** | B (Internal vs External) |
| **Findings** | 10 total (2 HIGH, 4 MEDIUM, 4 LOW) |
| **Fixes Proposed** | 5 (2 HIGH, 1 LOW, 1 LOW, 1 MEDIUM) |
| **Accepted Risks** | 4 (identity change on approval, 5 mutation points, orphaned pgSTAC, race condition) |
| **Key Insight** | Naming convention is sound; lifecycle hygiene is incomplete — stale `stac_item_json` blob and `geoetl:*` property leak |
| **Output** | `agent_docs/COMPETE_SG6_STAC_NAMING.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Omega | Scope split | — | inline |
| Alpha | Internal Logic | 69,784 | 5m 51s |
| Beta | External Interfaces | 91,176 | 4m 31s |
| Alpha+Beta | (parallel wall clock) | 160,960 | 6m 17s |
| Gamma | Contradictions | 112,503 | 5m 08s |
| Delta | Final Report | 64,098 | 3m 13s |
| **Total** | | **337,561** | **~16m 40s** |

**Finding Summary**:

| Rank | Finding | Severity | Confidence |
|------|---------|----------|------------|
| 1 | Raw `stac_item_json` with `geoetl:*` exposed via `to_dict()` | HIGH | CONFIRMED |
| 2 | Stale `stac_item_json['id']` in DB after approval | HIGH | CONFIRMED |
| 3 | `stac_item_id` identity change breaks approvals/status lookup | MEDIUM | CONFIRMED |
| 4 | Five mutation points for `stac_item_id` | MEDIUM | CONFIRMED |
| 5 | `cog_metadata.stac_item_id` stale after approval | MEDIUM | PROBABLE |
| 6 | `version_ordinal=0` accepted silently | LOW | CONFIRMED |
| 7 | No catch-all in submit ordinal finalization | LOW | CONFIRMED |
| 8 | Orphaned pgSTAC items after failed revocation | MEDIUM | PROBABLE |

---

## Cumulative Token Usage

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12 | 684,217 (Run 9: 346,656 + Run 12: 337,561; Runs 1-6 predated instrumentation) |
| GREENFIELD | Runs 7, 8, 10 | 631,196 (Run 10 only; Runs 7-8 predated instrumentation) |
| SIEGE | Run 11 | 178,793 |
| **Instrumented Total** | Runs 9-12 | **1,494,206** |

**Note**: Runs 1-8 predated the token instrumentation described in `agents/AGENT_METRICS.md`. Per-agent token breakdowns are available for Runs 9-12.
