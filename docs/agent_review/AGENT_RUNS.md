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

## Run 13: Platform API Smoke Test — Post-Fix Re-Run (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | SIEGE |
| **Scope** | Full Platform API surface — regression verification after SG-1 through SG-11 fixes deployed |
| **Target** | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` (v0.9.10.0) |
| **Agents** | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| **Verdict** | **CONDITIONAL PASS** — 80% pass rate (up from 54.5% in Run 11) |
| **Run 1 Regressions** | 4 fixed (SG-1, SG-2, SG-7, SG-8), 3 not fixed (SG-3, SG-5, SG-6), 1 inconclusive (SG-4) |
| **New Findings** | 6 (3 MEDIUM, 2 LOW, 1 INFO) |
| **Key Milestone** | SG-1 FIXED — raster approval, multi-version, and selective unpublish work end-to-end |
| **Output** | `agent_docs/SIEGE_RUN_2.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Sentinel | Campaign brief | — | inline |
| Cartographer | Endpoint probing | 35,060 | 1m 44s |
| Lancer | Lifecycle execution | 95,188 | 18m 23s |
| Auditor | State verification | 56,490 | 3m 19s |
| Scribe | Report synthesis | 64,600 | 3m 03s |
| **Total** | | **251,338** | **~26m 29s** |

**Regression Summary**:

| Run 1 ID | Severity | Fixed? | Notes |
|----------|----------|--------|-------|
| SG-1 | CRITICAL | **YES** | Raster approval + STAC materialization works |
| SG-2 | HIGH | **YES** | Clean error messages, no SQL leak |
| SG-3 | HIGH | NO | catalog/dataset still returns 500 |
| SG-5 | MEDIUM→HIGH | NO | Unpublish reports blobs_deleted=0 |
| SG-6 | MEDIUM | NO | Cached STAC JSON still uses -ord naming |
| SG-7 | MEDIUM | **YES** | is_latest correctly restored after unpublish |
| SG-8 | LOW | **YES** | Lineage 404 response shape consistent |

**New Finding Summary**:

| ID | Severity | Description |
|----|----------|-------------|
| SG2-1 | MEDIUM | Unpublish doesn't accept release_id or version_ordinal |
| SG2-2 | MEDIUM | Revoked release retains is_served=true |
| SG2-3 | MEDIUM | Catalog API strips required STAC 1.0.0 fields |
| SG2-4 | LOW | Status endpoint shows revoked release as primary |
| SG2-5 | LOW | outputs.stac_item_id shows processing-time name |
| SG2-6 | INFO | /resubmit semantics documentation gap |

---

## Run 14: SG-3 Root Cause Analysis and Fix (REFLEXION)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | REFLEXION |
| **Scope** | `GET /api/platform/catalog/dataset/{dataset_id}` — HTTP 500 on all requests |
| **Files** | 7 analyzed, 2 patched |
| **Agents** | R → F → P → J (sequential) |
| **Root Cause** | SQL references `r.table_name` — column removed from `asset_releases` on 26 FEB 2026, moved to `release_tables` |
| **Patches** | 2 (1 CRITICAL approved, 1 HIGH approved with modifications) |
| **Residual Faults** | 8 (F-3 through F-10, MEDIUM/LOW, deferred) |
| **Output** | `agent_docs/REFLEXION_SG3.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| R | Reverse Engineer | 41,068 | 1m 56s |
| F | Fault Injector | 91,885 | 3m 00s |
| P | Patch Author | 42,850 | 1m 52s |
| J | Judge | 56,881 | 2m 45s |
| **Total** | | **232,684** | **~9m 33s** |

**Patch Verdicts**:

| Patch | Fault | Severity | Verdict |
|-------|-------|----------|---------|
| 1 | F-1 (broken SQL) | CRITICAL | **APPROVE** |
| 2 | F-2 (opaque 500) | HIGH | **APPROVE WITH MODIFICATIONS** |

---

## Run 15: SG-5 Blob Deletion Failure (REFLEXION)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | REFLEXION |
| **Scope** | Unpublish raster pipeline — blobs not deleted, `blobs_deleted: 0` |
| **Files** | 10+ analyzed, 2 patched |
| **Agents** | R → F → P → J (sequential) |
| **Root Cause** | Three-bug cascade: `/vsiaz/` href misparse + missing return field + silent idempotent success |
| **Patches** | 3 (1 CRITICAL, 1 HIGH, 1 MEDIUM — all approved) |
| **Residual Risks** | 4 (zarr finalize gap, Bug C unpatched, no integration test, dry-run inconsistency) |
| **Output** | `agent_docs/REFLEXION_SG5.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| R | Reverse Engineer | 90,426 | 3m 08s |
| F | Fault Injector | 100,721 | 6m 27s |
| P | Patch Author | 37,444 | 2m 38s |
| J | Judge | 50,309 | 2m 46s |
| **Total** | | **278,900** | **~15m 00s** |

**Patch Verdicts**:

| Patch | Fault | Severity | Verdict |
|-------|-------|----------|---------|
| 1 | Bug A (/vsiaz/ href misparse) | CRITICAL | **APPROVE** |
| 2 | Bug B (missing blobs_deleted return) | HIGH | **APPROVE** |
| 3 | Bug B+C (accurate blob count) | MEDIUM | **APPROVE** |

---

## Run 16: SG2-2 Revoked Release Retains is_served=true (REFLEXION)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | REFLEXION |
| **Scope** | Release revocation — `is_served` not set to `false` on revoke |
| **Files** | 5 analyzed, 2 patched |
| **Agents** | R → F → P → J (combined run) |
| **Root Cause** | 2 independent revocation SQL paths both missing `is_served = false` |
| **Patches** | 2 (both ACCEPTED) |
| **Output** | `agent_docs/REFLEXION_SG22.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| R+F+P+J | Combined | 50,775 | 3m 49s |
| **Total** | | **50,775** | **~3m 49s** |

**Patch Verdicts**:

| Patch | Location | Change | Verdict |
|-------|----------|--------|---------|
| 1 | `release_repository.py:745` | Added `is_served = false` to `update_revocation()` SQL | **ACCEPT** |
| 2 | `unpublish_handlers.py:1095` | Extended inline SQL: `+is_served=false, is_latest=false, revoked_at=NOW()` | **ACCEPT** |

---

## Run 17: SG2-3 Catalog API Strips STAC 1.0.0 Fields (REFLEXION)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | REFLEXION |
| **Scope** | pgSTAC item denormalization — `get_item()` returns incomplete STAC items |
| **Files** | 1 analyzed, 1 patched (3 methods) |
| **Agents** | R → F → P → J (combined run) |
| **Root Cause** | pgSTAC stores `id`, `collection`, `geometry` in separate columns; `content` JSONB alone is not a valid STAC item. Correct reconstitution pattern existed in `pgstac_bootstrap.py` since 13 NOV 2025 but was not propagated to `PgStacRepository`. |
| **Patches** | 3 (all ACCEPTED) |
| **Output** | `agent_docs/REFLEXION_SG23.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| R+F+P+J | Combined | 69,607 | 2m 47s |
| **Total** | | **69,607** | **~2m 47s** |

**Patch Verdicts**:

| Patch | Location | Change | Verdict |
|-------|----------|--------|---------|
| 1 | `pgstac_repository.py:374-393` | `get_item()`: `SELECT content` → `content \|\| jsonb_build_object(...)` | **ACCEPT** |
| 2 | `pgstac_repository.py:612-640` | `search_by_platform_ids()`: Same reconstitution pattern | **ACCEPT** |
| 3 | `pgstac_repository.py:672-692` | `get_items_by_platform_dataset()`: SQL reconstitution replaces Python merge | **ACCEPT** |

---

## Cumulative Token Usage

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12 | 684,217 (Run 9: 346,656 + Run 12: 337,561; Runs 1-6 predated instrumentation) |
| GREENFIELD | Runs 7, 8, 10 | 631,196 (Run 10 only; Runs 7-8 predated instrumentation) |
| SIEGE | Runs 11, 13 | 430,131 (Run 11: 178,793 + Run 13: 251,338) |
| REFLEXION | Runs 14, 15, 16, 17 | 631,966 (Run 14: 232,684 + Run 15: 278,900 + Run 16: 50,775 + Run 17: 69,607) |
| **Instrumented Total** | Runs 9-17 | **2,377,510** |

**Note**: Runs 1-8 predated the token instrumentation described in `agents/AGENT_METRICS.md`. Per-agent token breakdowns are available for Runs 9-17.
