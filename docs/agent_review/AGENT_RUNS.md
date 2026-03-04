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
| **Patches Applied** | **YES** — both patches verified in codebase (v0.9.10.1) |
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
| **Patches Applied** | **YES** — all 3 patches verified in codebase (v0.9.10.1) |
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
| **Patches Applied** | **YES** — both patches verified in codebase (v0.9.10.1) |
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
| **Patches Applied** | **YES** — all 3 patches verified in codebase (v0.9.10.1) |
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

## Run 18: Platform API Regression Verification (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | SIEGE |
| **Scope** | Full Platform API surface -- regression verification after REFLEXION Runs 14-17 (SG-3, SG-5, SG2-2, SG2-3 fixes) |
| **Target** | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` (v0.9.10.1) |
| **Agents** | Sentinel -> Cartographer -> Lancer -> Auditor -> Scribe |
| **Verdict** | **CONDITIONAL PASS** -- Lancer 100% pass rate (first clean sweep), 3 of 4 targeted regressions FIXED |
| **Regressions Verified** | SG-3 FIXED, SG-5 FIXED, SG2-3 FIXED, SG2-2 INCONCLUSIVE (not exposed in API) |
| **New Findings** | 5 (1 HIGH, 1 MEDIUM, 2 LOW, 1 INFO) |
| **Key Discovery** | SG3-1: Vector STAC materialization writes 0 items -- vector equivalent of SG-1 |
| **Output** | `agent_docs/SIEGE_RUN_3.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Sentinel | Campaign brief | -- | inline |
| Cartographer | Endpoint probing | 33,062 | 1m 31s |
| Lancer | Lifecycle execution | 71,479 | 19m 37s |
| Auditor | State verification | 59,679 | 3m 04s |
| Scribe | Report synthesis | ~65,000 | ~3m 00s |
| **Total** | | **~229,220** | **~27m 12s** |

**Regression Summary**:

| Run 2 ID | Severity | Fixed in Run 3? | Notes |
|----------|----------|-----------------|-------|
| SG-3 | HIGH | **YES** | Returns 404 instead of 500 (REFLEXION Run 14) |
| SG-5 | HIGH | **YES** | blobs_deleted=1, COG absent from storage (REFLEXION Run 15) |
| SG2-2 | MEDIUM | **INCONCLUSIVE** | Code fix applied but is_served not exposed in API |
| SG2-3 | MEDIUM | **YES** | All 5 STAC 1.0.0 fields present (REFLEXION Run 17) |

**New Finding Summary**:

| ID | Severity | Description |
|----|----------|-------------|
| SG3-1 | HIGH | Vector STAC materialization creates pgSTAC collection but writes 0 items -- vector datasets invisible in catalog |
| SG3-2 | MEDIUM | Approve endpoint targets wrong release when request_id shared across versions (hash collision) |
| SG3-3 | LOW | is_served not exposed in platform status versions array |
| SG3-4 | LOW | Vector STAC collection description says "Raster collection" |
| SG3-5 | INFO | Unpublish defaults to dry_run=true (safe but undocumented) |

---

## Run 19: Web Interface Core Workflow (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | COMPETE |
| **Scope** | Web interface core workflow — pipeline → submit → status → platform (+ base infrastructure) |
| **Files** | 6 (~13,700 lines) |
| **Scope Split** | B: Internal vs External |
| **Findings** | 43 valid (6 CRITICAL, 8 HIGH, 18 MEDIUM, 11 LOW) + 1 invalidated |
| **Fixes Proposed** | 5 (Top 5 from Delta) |
| **Fixes Applied** | **YES** — all 5 Top Fixes implemented (v0.9.11.0) |
| **Key Discovery** | BLIND-1: Reflected XSS via URL params in JS string literals (tasks/interface.py) — trivially exploitable, no auth required |
| **Systemic Pattern** | Zero HTML escaping in 5 of 6 files; platform/interface.py is the only safe reference |
| **Output** | `agent_docs/COMPETE_RUN18_WEB_INTERFACE.md` |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Alpha | Internal logic & invariants | 100,244 | 4m 48s |
| Beta | External interfaces & security | 78,856 | 5m 02s |
| Gamma | Contradictions & blind spots | 161,814 | 3m 35s |
| Delta | Final report | 46,808 | 2m 28s |
| **Total** | | **387,722** | **~15m 53s** |

**Gamma Corrections**:

| Original | Correction |
|----------|-----------|
| Alpha C2 HIGH ("dead execution link") | **INVALIDATED** — execution interface IS registered |
| Alpha C9 MEDIUM (html shadowing) | **UPGRADED to HIGH** — causes UnboundLocalError crash in error handler |

**Top 5 Fixes**:

| Fix | Target | Severity | Effort |
|-----|--------|----------|--------|
| 1 | JS string injection in tasks `_generate_custom_js` | CRITICAL | Small |
| 2 | Blob/container/zone escaping in submit | CRITICAL | Small |
| 3 | `html` variable shadowing in `__init__.py` | HIGH | Small |
| 4 | innerHTML sanitization across pipeline + tasks JS | HIGH | Medium |
| 5 | Error message + warning escaping in submit | HIGH | Small |

---

## Run 20: Platform API Regression + Vector STAC Exclusion (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | SIEGE |
| **Scope** | Full Platform API surface — regression verification + vector STAC exclusion validation + expanded test fixtures |
| **Target** | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` (v0.9.11.2) |
| **Agents** | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| **Verdict** | **CONDITIONAL PASS** — 3/4 Lancer sequences pass, vector blocked by CRITICAL |
| **Regressions Verified** | SG-5, SG2-2, SG3-3 confirmed fixed. 0 regressions introduced. |
| **New Findings** | 6 total: 1 CRITICAL, 1 MEDIUM, 2 LOW, 2 INFO |
| **Key Discovery** | LNC-1: Vector submit completely broken — AssetRelease model requires stac_item_id/stac_collection_id as non-Optional, but vector exclusion passes None |
| **Output** | `agent_docs/SIEGE_RUN_4.md` |

**Regression Summary**:

| Prior ID | Severity | Run 4 Status |
|----------|----------|-------------|
| SG-1 | CRITICAL | Still fixed |
| SG-2 | HIGH | Still fixed |
| SG-3 | HIGH | Still fixed |
| SG-5 | HIGH | **Confirmed fixed** (blobs_deleted=1) |
| SG-7 | MEDIUM | Still fixed |
| SG2-2 | MEDIUM | **Confirmed fixed** (is_served=false) |
| SG3-3 | LOW | **Confirmed fixed** (is_served in versions) |

**New Finding Summary**:

| ID | Severity | Description |
|----|----------|-------------|
| LNC-1 | CRITICAL | Vector submit broken — stac_item_id/stac_collection_id non-Optional in AssetRelease model |
| AUD-R1-1 | MEDIUM | /api/platform/approvals/status returns lookup_error for valid STAC item IDs |
| F-CART-1 | LOW | POST-only endpoints return 404 instead of 405 |
| F-CART-2 | LOW | /api/dbadmin/stats returns 404 (SG-9 reconfirmed) |
| F-CART-3 | INFO | /api/health JSON contains control character |
| F-CART-4 | INFO | /api/health latency 3.7s |

---

## Run 21: LNC-1 Fix Verification + NetCDF Lifecycle (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 01 MAR 2026 |
| **Pipeline** | SIEGE |
| **Scope** | 5 lifecycle sequences (raster, vector, multi-version, unpublish, NetCDF/VirtualiZarr) — LNC-1 fix verification + first NetCDF test |
| **Target** | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` (v0.9.11.3) |
| **Agents** | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| **Verdict** | **CONDITIONAL PASS** — 4/5 sequences pass (first-ever vector pass), NetCDF blocked by infra gap |
| **Key Milestone** | LNC-1 FIXED — vector lifecycle passes for the first time |
| **Regressions Verified** | All prior fixes hold (SG-1, SG-5, SG2-2, SG3-3) |
| **New Findings** | 3 total: 1 CRITICAL, 1 MEDIUM, 1 LOW |
| **Output** | `agent_docs/SIEGE_RUN_5.md` |

**Sequence Results**:

| Sequence | Steps | Result |
|----------|-------|--------|
| 1. Raster Lifecycle | 4/4 | PASS |
| 2. Vector Lifecycle | 4/4 | **PASS (LNC-1 FIXED)** |
| 3. Multi-Version | 4/4 | PASS |
| 4. Unpublish | 3/3 | PASS |
| 5. NetCDF/VirtualiZarr | 1/4 | FAIL (SG5-1, SG5-3) |

**New Finding Summary**:

| ID | Severity | Description |
|----|----------|-------------|
| SG5-1 | CRITICAL | Approval endpoint approved release with processing_status=failed — no guard. Phantom STAC entry with is_served=true. |
| SG5-2 | MEDIUM | Orphaned release on validation failure — requires overwrite=true on retry |
| SG5-3 | LOW | silver-netcdf container not provisioned — VirtualiZarr fails at Stage 1 |

---

## Run 22: NetCDF Pipeline Gaps + Full Invalid Data Sweep (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 02 MAR 2026 |
| **Pipeline** | SIEGE (expanded with Provocateur) |
| **Scope** | 5 lifecycle sequences + 32 invalid/bad data scenarios (all valid_files + all invalid_files from siege_config.json) |
| **Target** | Orchestrator v0.9.11.5 / Docker Worker v0.9.11.6 |
| **Agents** | Sentinel -> Cartographer -> Lancer -> Provocateur -> Scribe |
| **Verdict** | **CONDITIONAL PASS** -- Seq 1-4 pass (100%), Seq 5 blocked by scipy backend, invalid data 26/32 graceful |
| **Key Milestone** | SG5-3 FIXED (silver-netcdf container now exists), GAP-1/2/7 code deployed |
| **New Findings** | 9 total: 2 HIGH, 3 MEDIUM, 2 LOW, 2 INFO |
| **Output** | `agent_docs/SIEGE_RUN_6.md` |

**Sequence Results**:

| Sequence | Steps | Result |
|----------|-------|--------|
| 1. Raster Lifecycle | 4/4 | PASS |
| 2. Vector Lifecycle | 4/4 | PASS |
| 3. Multi-Version | 4/4 | PASS |
| 4. Unpublish | 3/3 | PASS |
| 5. NetCDF/VirtualiZarr | 1/4 | FAIL (SG6-L1: scipy backend incompatible) |

**Invalid Data Sweep (32 tests)**:

| Category | Count |
|----------|-------|
| Rejected at submit (4xx) | 12 |
| Accepted then failed in pipeline | 15 |
| 500 errors | **0** |
| Unexpected successes | 3 |
| Inconclusive | 1 |

**New Finding Summary**:

| ID | Severity | Description |
|----|----------|-------------|
| SG6-L1 | HIGH | scipy engine does not support storage_options -- validate handler fails on all NetCDF files |
| SG6-L2 | HIGH | Approval allows failed releases (reconfirms SG5-1) |
| SG6-L3 | MEDIUM | Zarr submit with file_name creates orphaned release |
| SG6-P1 | MEDIUM | Raster without CRS silently processed into COG |
| SG6-P2 | MEDIUM | Raster without geotransform silently processed |
| SG6-P3 | LOW | Empty/garbage rasters produce misleading "transient network" error |
| SG6-P4 | LOW | Vector null geometries silently accepted |
| SG6-P5 | INFO | No timeout guard on huge polygon processing |
| SG6-P6 | INFO | File/container not found returns 409 instead of 404 |

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Sentinel | Campaign brief | -- | inline |
| Cartographer | Endpoint probing | 26,352 | 58s |
| Lancer | Lifecycle execution | 67,021 | 11m 22s |
| Provocateur | Invalid data sweep | 55,214 | 10m 45s |
| **Total** | | **~148,587** | **~23m 05s** |

---

## Run 23: Full SIEGE with NetCDF Fix Verification

| Field | Value |
|-------|-------|
| **Date** | 02 MAR 2026 |
| **Pipeline** | SIEGE (full lifecycle + Provocateur) |
| **Scope** | 6 lifecycle sequences (incl. CSV/SHP/KML) + 32 invalid data scenarios |
| **Target** | Docker Worker v0.9.11.7 (netCDF4 + scipy + fsspec temp file + abfs:// fix) |
| **Agents** | Cartographer -> Lancer -> Provocateur |
| **Verdict** | **PASS** — All 6 sequences pass (28/28 steps), 0 new bugs, 0 server 500s |
| **Key Milestone** | SG6-L1 FIXED — first clean NetCDF/VirtualiZarr end-to-end run |
| **New Findings** | 0 |
| **Output** | `agent_docs/SIEGE_RUN_7.md` |

**Sequence Results**:

| Sequence | Steps | Result |
|----------|-------|--------|
| 1. Raster Lifecycle | 4/4 | PASS |
| 2. Vector Lifecycle | 4/4 | PASS |
| 3. Multi-Version | 7/7 | PASS |
| 4. Unpublish | 6/6 | PASS |
| 5. NetCDF/VirtualiZarr | 4/4 | **PASS** (previously FAIL) |
| 6. Additional Formats (CSV/SHP/KML) | 3/3 | PASS |

**Invalid Data Sweep (32 tests)**:

| Category | Count |
|----------|-------|
| Rejected at submit (4xx) | 11 |
| Accepted then failed in pipeline | 17 |
| 500 errors | **0** |
| Unexpected successes | 2 (SG6-P1/P2 — known) |
| Inconclusive | 1 |

**Score**: 84/88 (95.5%) — up from 88.75% in Run 22

**Token Usage**:

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| Cartographer | Endpoint probing | ~30,000 | ~57s |
| Lancer | Lifecycle execution | ~64,000 | ~8m |
| Provocateur | Invalid data sweep | ~59,000 | ~9.5m |
| **Total** | | **~153,000** | **~18m** |

---

## Run 24: Dashboard Submit Form (GREENFIELD — Narrow Scope)

| Field | Value |
|-------|-------|
| **Date** | 02 MAR 2026 |
| **Pipeline** | GREENFIELD (S→A→C→O→M→B→V) |
| **Scope** | Narrow — replace `_render_submit()` stub with complete file browser form |
| **Execution** | Subagent-driven development (fresh subagent per stage) |
| **Files Modified** | 2 (`platform.py`, `__init__.py`) |
| **Lines Added** | ~300 |
| **V Rating** | **GOOD** (0 CRITICAL, 2 MEDIUM, 4 LOW, 4 VERY LOW) |
| **Spec Diff** | 100% contract alignment, 100% invariant alignment, 6/8 success criteria fully met |
| **Gaps Found by V** | 2 real (required attrs, error URL escaping) — both spec-aligned, B missed them |
| **Gaps Fixed** | 3 of 4 (V1 required attrs, V2 URL escaping, V4 code comment; V3 result formatting deferred) |
| **Builder Budget Collapse** | **NO** — narrow scope (~370 line spec → ~300 line output) worked |
| **Key Learning** | Narrow scope prevents Builder budget collapse (confirmed). V catches spec-to-code drift, not new design issues. |
| **Commits** | `63182c6`, `bcc9b0e`, `fcefefb`, `54b9308`, `c0fd2f3` |
| **Output** | `agent_docs/GREENFIELD_SUBMIT_RUN_REPORT.md` |

**Agent Outputs**:

| Agent | Output File |
|-------|-------------|
| A (Advocate) | `agent_docs/GREENFIELD_SUBMIT_ADVOCATE.md` |
| C (Critic) | `agent_docs/GREENFIELD_SUBMIT_CRITIC.md` |
| O (Operator) | `agent_docs/GREENFIELD_SUBMIT_OPERATOR.md` |
| M (Mediator) | `agent_docs/GREENFIELD_SUBMIT_MEDIATOR.md` |
| B (Builder) | Direct code changes (committed) |
| V (Validator) | `agent_docs/GREENFIELD_SUBMIT_VALIDATOR.md` |
| Spec Diff | `agent_docs/GREENFIELD_SUBMIT_SPEC_DIFF.md` |

**Token Usage**:

| Agent | Role | Tokens |
|-------|------|--------|
| A | Optimistic design | ~40,000 |
| C | Gap analysis | ~35,000 |
| O | Infrastructure assessment | ~35,000 |
| M | Conflict resolution | ~50,000 |
| B | Code generation | ~55,000 |
| V | Blind code review | ~58,000 |
| Controller | Orchestration + fixes | ~40,000 |
| **Total** | | **~313,000** |

---

## Run 25: SIEGE Run 8 — Full State Machine + Service URL Testing

| Field | Value |
|-------|-------|
| **Pipeline** | SIEGE |
| **Date** | 02 MAR 2026 |
| **Version** | 0.9.11.9 |
| **Focus** | Full lifecycle state machine (13 sequences), invalid transition guards, service URL probes |
| **Output** | `agent_docs/SIEGE_RUN_8.md` |

**Sequences Tested**: 13 (up from 5 in prior SIEGE runs)

| Category | Sequences | Steps | Pass | Fail |
|----------|-----------|-------|------|------|
| Happy-path lifecycles (1-6) | Raster, Vector, Multi-Version, Unpublish, NetCDF/Zarr, Native Zarr | 23 | 22 | 1 |
| Extended lifecycle (7-10) | Rejection, Reject→Resubmit→Approve, Revoke+Cascade, Overwrite | 16 | 14 | 2 |
| Invalid transitions (11-13) | 7 state guards + 10 field validations + version conflict | 22 | 22 | 0 |
| **Total** | | **61** | **58** | **3** |

**Score**: 87.4% — NEEDS INVESTIGATION

**New Findings**:

| ID | Severity | Description |
|----|----------|-------------|
| REJ2-F1 | **CRITICAL** | Resubmit after rejection broken — release deleted but not recreated, approve returns 404 |
| SVC-F1 | HIGH | STAC URLs in /status use wrong prefix (`/api/collections/` → 404, should be `/api/stac/collections/`) |
| NZ1-F1 | MEDIUM | No native .zarr ingest path — VirtualiZarr only scans for *.nc |
| OW1-F1 | MEDIUM | `is_served=true` set on pending_review releases (before approval) |
| SVC-F2 | MEDIUM | TiTiler xarray endpoints return 500 — zarr package not installed |
| SVC-F3 | MEDIUM | Double path in zarr xarray URLs (container name duplicated) |
| REJ1-F1 | LOW | Rejection reason not surfaced in /status response |

**Reconfirmed**: SG-9 (stats 404), SG5-1 (approve allows failed releases), SG6-L3 (orphaned release from file_name zarr submit)

**Token Usage**:

| Agent | Tokens |
|-------|--------|
| Cartographer | ~29,000 |
| Lancer Seq 1-5 | ~55,000 |
| Lancer Seq 6-10 | ~57,000 |
| Lancer Seq 11-13 | ~45,000 |
| Auditor | ~57,000 |
| **Total** | **~243,000** |

---

## Run 26: SIEGE Run 9 — Fix Verification (OW1-F1, SVC-F3, REJ1-F1)

| Field | Value |
|-------|-------|
| **Pipeline** | SIEGE |
| **Date** | 02 MAR 2026 |
| **Version** | 0.9.11.10 |
| **Focus** | Verify 3 ad hoc fixes from Run 8 + regression test |
| **Output** | `agent_docs/SIEGE_RUN_9.md` |

**Sequences Tested**: 13

| Category | Steps | Pass | Fail |
|----------|-------|------|------|
| Happy-path (1-6) | 19 | 19 | 0 |
| Extended lifecycle (7-10) | 13 | 11 | 2 |
| Invalid transitions (11-13) | 22 | 22 | 0 |
| **Total** | **54** | **52** | **2** |

**Score**: 90.8% — up from 87.4% in Run 8 (+3.4%)

**Fixes Verified**:

| Fix | Status | Evidence |
|-----|--------|----------|
| OW1-F1 (is_served premature) | **FIXED** | OW1+VC1: `is_served=false` on pending_review |
| SVC-F3 (double container) | **FIXED** | No `silver-netcdf/silver-netcdf` in xarray URLs |
| REJ1-F1 (rejection reason) | **FIXED** | `rejection_reason` visible in `/status` |
| SVC-F1 (STAC wrong app) | **Confirmed** | STAC URLs → Service Layer, HTTP 200 |

**State Audit**: 17/17 — **ZERO DIVERGENCES** (was 55/57 in Run 8)

**Still Open**: REJ2-F1 (CRITICAL: resubmit broken), SVC-F2 (zarr viz), NZ1-F1 (native zarr), SG-9 (stats 404)

**Token Usage**:

| Agent | Tokens |
|-------|--------|
| Cartographer | ~25,000 |
| Lancer Seq 1-5 | ~48,000 |
| Lancer Seq 6-13 | ~65,000 |
| Auditor | ~40,000 |
| Scribe | ~35,000 |
| **Total** | **~213,000** |

---

## Cumulative Token Usage

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19 | 1,071,939 (Run 9: 346,656 + Run 12: 337,561 + Run 19: 387,722; Runs 1-6 predated instrumentation) |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944,196 (Run 10: 631,196 + Run 24: ~313,000; Runs 7-8 predated instrumentation) |
| SIEGE | Runs 11, 13, 18, 20, 21, 22, 23, 25, 26 | ~1,817,587 |
| REFLEXION | Runs 14, 15, 16, 17 | 631,966 (Run 14: 232,684 + Run 15: 278,900 + Run 16: 50,775 + Run 17: 69,607) |
| **Instrumented Total** | Runs 9-26 | **~4,465,688** |

---

## Run 27: TOURNAMENT Run 1 — Full-Spectrum Adversarial (First TOURNAMENT)

| Field | Value |
|-------|-------|
| **Pipeline** | TOURNAMENT |
| **Date** | 02 MAR 2026 |
| **Version** | 0.9.11.10 |
| **Focus** | Full-spectrum adversarial testing: golden-path + attacks + blind audit + boundary-value |
| **Output** | `agent_docs/TOURNAMENT_RUN_27.md` |

**Phase 1: MUTATION (Parallel)**

| Agent | Scope | Result |
|-------|-------|--------|
| Pathfinder | 6 sequences (raster, vector, multi-version, unpublish, NetCDF/VirtualiZarr, rejection recovery) | 6/6 PASS, 25/25 steps |
| Saboteur | 18 adversarial attacks (TEMPORAL, DUPLICATION, IDENTITY, RACE, LIFECYCLE) | 16 EXPECTED, 2 INTERESTING, 0 UNEXPECTED |

**Phase 2: AUDIT (Parallel)**

| Agent | Scope | Result |
|-------|-------|--------|
| Inspector | 6 checkpoints, system-wide anomaly scan | 6/6 PASS, 7 anomalies (all correlated to Saboteur) |
| Provocateur | 68 boundary-value attacks across 4 endpoints | 8 crashes (500s), 1 CRITICAL exception bug, 1 HIGH SSRF |

**Phase 3: JUDGMENT**

| Agent | Scope | Result |
|-------|-------|--------|
| Tribunal | Correlation of all 4 outputs | 0 state divergences, 11 findings classified |

**Score**: **87.2%** (91.2% raw, -4 for 2 CRITICALs)

**Findings**:

| ID | Severity | Source | Description |
|----|----------|--------|-------------|
| PRV-1 | CRITICAL | Provocateur | `/approve`, `/reject`, `/revoke` return 500 on malformed JSON — `ValueError` vs `JSONDecodeError` mismatch |
| LA-1/SG5-1 | CRITICAL | Saboteur | Stale release approved during active processing (reconfirmed from SIEGE Run 25) |
| PRV-2 | HIGH | Provocateur | SSRF info leak — URL in container_name leaks Azure Storage internal errors |
| LA-2 | MEDIUM | Saboteur | Unpublish dry_run accepts non-approved releases |
| ID-1 | MEDIUM | Inspector+Saboteur | No authorization model on approvals — any caller can approve |
| PRV-3 | MEDIUM | Provocateur | No length limits on approve/reject free-text fields |
| PRV-7 | MEDIUM | Provocateur | Unpublish broken for DDH identifier-based lookups |
| PRV-10 | MEDIUM | Provocateur | Inconsistent error format between /submit and /approve |
| ID-2 | LOW | Inspector+Saboteur | Race condition resolved correctly (approve wins) |
| PRV-8 | LOW | Provocateur | XSS payloads accepted in stored fields |
| PRV-9 | LOW | Provocateur | 404 vs 405 for wrong HTTP methods |

**Token Usage**:

| Agent | Tokens | Duration |
|-------|--------|----------|
| Pathfinder | ~58,000 | 19 min |
| Saboteur | ~42,000 | 7.5 min |
| Inspector | ~63,000 | 5.5 min |
| Provocateur | ~76,000 | 7.8 min |
| Tribunal | ~39,000 | 2.6 min |
| **Total** | **~278,000** | **~42 min** |

---

## Cumulative Token Usage

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19 | 1,071,939 (Run 9: 346,656 + Run 12: 337,561 + Run 19: 387,722; Runs 1-6 predated instrumentation) |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944,196 (Run 10: 631,196 + Run 24: ~313,000; Runs 7-8 predated instrumentation) |
| SIEGE | Runs 11, 13, 18, 20, 21, 22, 23, 25, 26 | ~1,817,587 |
| REFLEXION | Runs 14, 15, 16, 17 | 631,966 (Run 14: 232,684 + Run 15: 278,900 + Run 16: 50,775 + Run 17: 69,607) |
| TOURNAMENT | Run 27 | ~278,000 |
| **Instrumented Total** | Runs 9-27 | **~4,743,688** |

**Note**: Runs 1-8 predated the token instrumentation described in `agents/AGENT_METRICS.md`. Per-agent token breakdowns are available for Runs 9-27.

---

## Run 28: COMPETE — Approval Workflow (Constitution Rerun)

**Date**: 02 MAR 2026
**Pipeline**: COMPETE (Adversarial Review) with Constitution Enforcement
**Scope**: Approval Workflow — approve/reject/revoke lifecycle (7 files, ~7,000 lines)
**Split**: B (Internal vs External)
**Pattern**: A (Recurring Review)
**Output**: `agent_docs/COMPETE_CONSTITUTION_RERUNS.md`

| Agent | Scope | Tokens | Tool Uses | Duration |
|-------|-------|--------|-----------|----------|
| Alpha | Internal Logic (asset_approval_service.py, release_repository.py, asset.py, stac_materialization.py) | 91,682 | 20 | 163s |
| Beta | External Interfaces (trigger_approvals.py, platform.py, pgstac_repository.py, release_repository.py) | 108,344 | 26 | 159s |
| Gamma | Contradiction + Blind Spot Finder | 96,506 | 20 | 169s |
| Delta | Final Report | 52,640 | 30 | 177s |
| **Total** | | **349,172** | **96** | **668s** |

**Key Findings**: 1 CRITICAL, 2 HIGH, 16 MEDIUM, 3 LOW. 5 Constitution violations (Sections 1.1, 1.2, 3.3).
**Top Fix**: Block approval of non-COMPLETED releases (SG5-1/LA-1 reconfirmed — CRITICAL).
**Gamma Discovery**: pgSTAC repository systematic error swallowing (11 methods, Section 3.3) — cascading silent failures.

---

## Run 29: COMPETE — CoreMachine Orchestration (Constitution Rerun)

**Date**: 02 MAR 2026
**Pipeline**: COMPETE (Adversarial Review) with Constitution Enforcement
**Scope**: CoreMachine Orchestration — Job→Stage→Task pattern (8 files, ~5,600 lines)
**Split**: A (Design vs Runtime)
**Pattern**: B (Recurring Review)
**Output**: `agent_docs/COMPETE_CONSTITUTION_RERUNS.md`

| Agent | Scope | Tokens | Tool Uses | Duration |
|-------|-------|--------|-----------|----------|
| Alpha | Architecture/Design (machine.py, state_manager.py, base.py, mixins.py, services/__init__.py) | 104,474 | 36 | 191s |
| Beta | Correctness/Runtime (machine.py, state_manager.py, transitions.py, task_handler.py, job_handler.py) | 106,028 | 37 | 446s |
| Gamma | Contradiction + Blind Spot Finder | 114,550 | 32 | 231s |
| Delta | Final Report | 57,341 | 29 | 148s |
| **Total** | | **382,393** | **134** | **1,016s** |

**Key Findings**: 2 CRITICAL, 5 HIGH, 12 MEDIUM, 7 LOW. 5 Constitution violations (Sections 1.1, 3.3).
**Top Fix**: Re-raise transient exceptions in job/task handlers (Section 3.3 — CRITICAL). Service Bus messages silently consumed on failure.
**Gamma Discovery**: Job/task handlers swallow ALL exceptions, preventing Service Bus retry delivery. If DB is also down, messages are permanently lost.

---

## Run 30: COMPETE — NetCDF-to-Zarr Pipeline

**Date**: 03 MAR 2026
**Pipeline**: COMPETE (Adversarial Review)
**Scope**: `netcdf_to_zarr` 5-stage pipeline + platform routing + unpublish integration (8 files, ~2,800 lines)
**Split**: C (Data vs Control Flow)
**Pattern**: New Implementation Review
**Output**: `agent_docs/COMPETE_NETCDF_TO_ZARR.md`

| Agent | Scope | Tokens | Tool Uses | Duration |
|-------|-------|--------|-----------|----------|
| Alpha | Data integrity (handler_netcdf_to_zarr.py, netcdf_to_zarr.py, handler_ingest_zarr.py) | ~95,000 | ~30 | ~180s |
| Beta | Control flow (submit.py, platform_translation.py, unpublish_zarr.py, unpublish_handlers.py) | ~98,000 | ~32 | ~200s |
| Gamma | Contradiction + Blind Spot Finder | ~105,000 | ~28 | ~210s |
| Delta | Final Report | ~52,000 | ~24 | ~140s |
| **Total** | | **~350,000** | **~114** | **~730s** |

**Key Findings**: 2 CRITICAL, 4 HIGH, 10 MEDIUM, 7 LOW. 6 Accepted Risks documented.
**Top Fix**: Unpublish `inventory_zarr_item` broken for native Zarr pipelines — looks for `"reference"` asset key, but `netcdf_to_zarr` and `ingest_zarr` produce `"zarr-store"` (BS-1 — CRITICAL).
**Gamma Discovery**: Versioned zarr submissions lose `zarr/` prefix — Step 6 in submit.py uses raster path generator for all data types (C-1 — CRITICAL).

---

## Run 31: ADVOCATE Run 1 — B2B Developer Experience Audit (First ADVOCATE)

| Field | Value |
|-------|-------|
| **Pipeline** | ADVOCATE (B2B Developer Experience Audit) |
| **Date** | 03 MAR 2026 |
| **Version** | 0.9.12.0 |
| **Focus** | Full consumer API surface — DX quality, consistency, discoverability |
| **Prerequisites** | Schema rebuild + STAC nuke |
| **Output** | `agent_docs/ADVOCATE_RUN_1.md` |

**DX Score**: **37%** (pre-beta integration quality)

| Category | Weight | Score |
|----------|--------|-------|
| Discoverability | 20% | 40% |
| Error Quality | 20% | 25% |
| Consistency | 20% | 30% |
| Response Design | 15% | 45% |
| Service URL Integrity | 15% | 40% |
| Workflow Clarity | 10% | 50% |

**Phase Execution**:

| Phase | Agent | Role | HTTP Calls |
|-------|-------|------|------------|
| 0 | Dispatcher | Setup + prerequisites | N/A |
| 1 | Intern | First-impressions friction log | ~45 |
| 2 | Architect | Structured REST audit (12 dimensions) | 65 |
| 3 | Editor | Synthesis + scoring | N/A |

**Findings**: 25 total (2 CRITICAL, 7 HIGH, 10 MEDIUM, 5 LOW, 1 INFO)

| ID | Severity | Description |
|----|----------|-------------|
| ADV-1 | **CRITICAL** | `job_status_url` permanently broken (404) — first-contact failure for every integration |
| ADV-2 | **CRITICAL** | Approval allows failed/unprocessed releases — `is_served=true` on non-existent data (SG5-1/LA-1 reconfirmed) |
| ADV-3 | HIGH | 5 distinct error response shapes — unified error handler impossible |
| ADV-4 | HIGH | `services`/`outputs` always null — write-only API, no path from approved to consumable |
| ADV-5 | HIGH | Silent parameter ignoring on `/status` list — pagination and filters have no effect |
| ADV-6 | HIGH | No API discovery page — OpenAPI exists but not linked from anywhere |
| ADV-7 | HIGH | TiTiler not cross-linked from platform responses |
| ADV-8 | HIGH | `error: null` on failed jobs, `error_summary: "Unknown error"` |
| ADV-9 | HIGH | Malformed JSON on `/approve`/`/reject`/`/revoke` returns 500 (fixed in v0.9.11.11) |

**REST Dimension Grades**: A- (Idempotency), B+ (HTTP Methods), B (Status Codes), C/C- (HATEOAS, Response Bloat, Naming), D/D+ (Pagination, Versioning, Consistency), F (Error Format, Content Negotiation, Cacheability)

**8 Themes**: Dead URLs, State Machine Integrity, Five Error Shapes, Services/Outputs Gap, Silent Parameter Ignoring, Discoverability Gap, Response Shape Inconsistency, Broken Catalog

**New findings** (not previously identified):
- ADV-1 (`job_status_url` broken) — new, first found by ADVOCATE
- ADV-5 (silent param ignoring) — new, first found by ADVOCATE
- ADV-4 (services/outputs gap) — known gap, first formally documented
- ADV-6/ADV-7 (discoverability) — new DX findings

**Token Usage**:

| Agent | Tokens (est) |
|-------|-------------|
| Dispatcher | ~2,000 |
| Intern | ~50,000 |
| Architect | ~55,000 |
| Editor | ~8,000 |
| **Total** | **~115,000** |

### Run 32 — REFLEXION: ADV-2 Approval Guard (04 MAR 2026)

**Pipeline**: REFLEXION | **Target**: ADV-2 approval guard bypass concern | **Version**: v0.9.12.1

**Scope**: `services/asset_approval_service.py`, `triggers/trigger_approvals.py`, `infrastructure/release_repository.py` (3 files, ~3,886 lines)

**ADV-2 Verdict**: The approval guard **CANNOT be bypassed**. Both the Python guard (line 155) and SQL WHERE clause (`processing_status = 'completed'`) work correctly. The live test was explained by Docker worker completing processing between status check and approval call.

**Critical Discovery**: The stale-ordinal guard (SG5-1/LA-1) has been **completely inoperative** since implementation — `has_newer_active_ordinal()` used positional row indexing (`row[0]`-`row[3]`) that crashes with `KeyError` on `dict_row` cursors, silently caught upstream.

**Faults Found**: 18 total (1 CRITICAL, 6 HIGH, 7 MEDIUM, 4 LOW)

**Patches Applied**: 5 of 6 approved

| Patch | Fault | Description | Verdict |
|-------|-------|-------------|---------|
| P1 | F-02 | Fix positional row indexing in `has_newer_active_ordinal()` | **APPROVE (P0)** |
| P2 | F-06 | Fix version_ordinal coercion to 0 | **REJECT** (by design) |
| P3 | F-16 | Parameterize `'completed'` string in SQL | **APPROVE** |
| P4 | F-08 | Null guard after atomic commit re-read | **APPROVE** |
| P5 | F-04 | Add `is_served = false` to rollback | **APPROVE** (modified: keep version_ordinal) |
| P6 | F-05 | Improve rejection error message | **APPROVE** |

**Residual Risks**: F-01 (approve+revoke race), F-03 (STAC partial failure orphans), F-07 (no DB retry)

**Report**: `docs/agent_review/agent_docs/REFLEXION_ADV2_APPROVAL_GUARD.md`

**Token Usage**:

| Agent | Tokens (est) |
|-------|-------------|
| R (Reverse Engineer) | ~85,000 |
| F (Fault Injector) | ~91,000 |
| P (Patch Author) | ~85,000 |
| J (Judge) | ~82,000 |
| **Total** | **~343,000** |

---

### Run 33 — COMPETE: Release Audit Log & In-Place Ordinal Revision (03 MAR 2026)

**Pipeline**: COMPETE | **Split**: A (Design vs Runtime) | **Version**: v0.9.12.1

**Scope**: Release audit log subsystem + in-place ordinal revision enablement (6 files reviewed, 3 priority files added by Gamma)

**Files**: `core/models/release_audit.py` (NEW), `infrastructure/release_audit_repository.py` (NEW), `infrastructure/release_repository.py`, `core/models/asset.py`, `services/asset_approval_service.py`, `core/schema/sql_generator.py`

**Verdict**: **FAIL** — 1 CRITICAL, 6 HIGH. Primary spec feature (overwrite of revoked ordinals) is unreachable.

**Findings**: 17 total (1 CRITICAL, 6 HIGH, 4 MEDIUM, 6 LOW)

| ID | Severity | Description |
|----|----------|-------------|
| BS-1 | **CRITICAL** | `get_draft()` excludes REVOKED releases — in-place ordinal revision unreachable |
| F-2 | **HIGH** | All audit read methods produce garbage via `dict(zip(columns, dict_row))` |
| BS-4 | **HIGH** | Audit and mutation in separate transactions — phantom events |
| AR-3 | **HIGH** | `update_overwrite()` no state guard in WHERE — TOCTOU race |
| F-4 | **HIGH** | `INTERVAL '%s hours'` broken with psycopg3 |
| AR-1 | **HIGH** | `ReleaseAuditRepository` not in `infrastructure/__init__.py` |
| AR-2 | **HIGH** | 3 identical audit blocks — DRY violation + overbroad `except Exception` |

**Key Blind Spot (Gamma)**: Neither Alpha nor Beta reviewed the caller chain — `asset_service.py:create_or_get_draft()` calls `get_draft()` which has `version_id IS NULL AND approval_state != REVOKED`. Revoked releases have `version_id`, so they're excluded by BOTH conditions. The `can_overwrite()` change to accept REVOKED is dead code.

**Report**: `agent_docs/COMPETE_RELEASE_AUDIT.md`

**Token Usage**:

| Agent | Tokens (est) |
|-------|-------------|
| Omega | -- (inline) |
| Alpha | ~64,900 |
| Beta | ~79,900 |
| Gamma | ~83,300 |
| Delta | ~53,300 |
| **Total** | **~281,400** |

---

## Cumulative Token Usage

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19, 28, 29, 30, 33 | ~2,434,904 (prior 2,153,504 + Run 33: ~281,400) |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944,196 (Run 10: 631,196 + Run 24: ~313,000; Runs 7-8 predated instrumentation) |
| SIEGE | Runs 11, 13, 18, 20, 21, 22, 23, 25, 26 | ~1,817,587 |
| REFLEXION | Runs 14, 15, 16, 17, 32 | ~974,966 (prior 631,966 + Run 32: ~343,000) |
| TOURNAMENT | Run 27 | ~278,000 |
| ADVOCATE | Run 31 | ~115,000 |
| **Instrumented Total** | Runs 9-33 | **~6,564,653** |

**Note**: Runs 1-8 predated the token instrumentation described in `agents/AGENT_METRICS.md`. Per-agent token breakdowns are available for Runs 9-31.

---

## Recurring Review Patterns

Two subsystems are designated for **regular re-review** using the COMPETE pipeline with full constitution enforcement. These are the highest-churn, highest-risk areas of the codebase — each has been the source of multiple SIEGE/TOURNAMENT findings across runs.

### Pattern A: Approval Workflow Review

**Original**: Run 4 (27 FEB 2026) — pre-constitution, 21 findings, 5 fixes
**Why recurring**: The approval lifecycle is the most-patched subsystem. Runs 4, 5, 6, 12, 14, 16, 25, 26, 27 all found or fixed approval-related issues. Every fix is a potential constitution violation introduction point.

**Scope** (7 files, ~7,000 lines):
- `triggers/trigger_approvals.py` — approve/reject/revoke endpoints
- `services/asset_approval_service.py` — approval business logic
- `infrastructure/release_repository.py` — release persistence + atomic state transitions
- `core/models/asset.py` — AssetRelease model + state machine
- `core/models/platform.py` — PlatformRequest validation
- `services/stac_materialization.py` — STAC writes at approval time
- `infrastructure/pgstac_repository.py` — pgSTAC operations

**Constitution focus**: Sections 1 (zero-tolerance), 2 (config access), 3 (error handling), 5 (platform boundaries), 6 (database patterns)

**Recommended split**: B (Internal vs External) — Internal logic/invariants vs boundary contracts/error surfaces

**Cadence**: After every deployment that touches approval files, or monthly.

### Pattern B: CoreMachine Orchestration Review

**Original**: Run 1 (26 FEB 2026) — pre-constitution, 18 findings, 5 fixes
**Why recurring**: CoreMachine is the heart of all job processing. The zero-task stage guard (added post-Run 9) and various error handling changes make this a constitution compliance hotspot. Exception swallowing patterns (accepted risk BLIND-2) should be re-evaluated against Section 3.3.

**Scope** (8 files, ~5,600 lines):
- `core/machine.py` — orchestration engine
- `core/state_manager.py` — job/task state persistence
- `core/logic/transitions.py` — state machine rules
- `jobs/base.py` — abstract job interface
- `jobs/mixins.py` — JobBaseMixin (77% boilerplate reduction)
- `services/__init__.py` — handler registry
- `triggers/service_bus/task_handler.py` — task message processing
- `triggers/service_bus/job_handler.py` — job message processing

**Constitution focus**: Sections 1 (zero-tolerance, especially 1.3 ContractViolationError, 1.4 repository pattern), 3 (error handling categories), 4 (import hierarchy), 9 (job/task patterns)

**Recommended split**: A (Design vs Runtime) — Architecture/contracts vs correctness/reliability

**Cadence**: After major CoreMachine changes, or bi-monthly.
