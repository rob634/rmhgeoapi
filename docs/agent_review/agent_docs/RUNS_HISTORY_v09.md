# Agent Pipeline Run History — v0.9.x Era (Runs 1-43)

Condensed from full run reports. Original detail docs archived to `docs/archive/agent_review/`.

**Date range**: 26 FEB 2026 — 15 MAR 2026
**Versions covered**: v0.9.8.1 — v0.10.2.0
**Total instrumented tokens**: ~7.5M (Runs 9-43)

---

## Pipeline Legend

| Pipeline | Purpose | Agents |
|----------|---------|--------|
| COMPETE | Adversarial code review (split-scope) | Omega → Alpha+Beta → Gamma → Delta |
| GREENFIELD | Design-build-validate new features | S → A+C+O → M → B → V |
| SIEGE | Live API regression + lifecycle testing | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| REFLEXION | Root-cause analysis + patching | R → F → P → J |
| TOURNAMENT | Full-spectrum adversarial (golden-path + attacks + audit) | Pathfinder + Saboteur + Inspector + Provocateur → Tribunal |
| ADVOCATE | B2B developer experience audit | Dispatcher → Intern → Architect → Editor |

---

## COMPETE Runs (Code Review)

| Run | Date | Version | Scope | Findings | Key Fixes | Commit |
|-----|------|---------|-------|----------|-----------|--------|
| 1 | 26 FEB | v0.9.8.1 | CoreMachine orchestration (~25 files) | 18 | 5 (1C, 2H, 2M) | `fa05cc1` |
| 2 | 26 FEB | — | Vector pipeline (~20 files) | 12 | 10 (1C, 3H, 4M) | `8355f7c` |
| 3 | 27 FEB | — | Tiled raster pipeline (~10 files) | 9 | 6 (1C, 2H, 2M) | `51e8a28` |
| 4 | 27 FEB | — | Approval workflow (7 files) | 21 | 5 (1C, 2H, 1M, 1L) | `088aca9` |
| 5 | 27 FEB | v0.9.8.2 | B2B domain A — entities, state machines (10 files) | 13 | 5 (2C, 3H) | `416124c` |
| 6 | 28 FEB | v0.9.8.2 | B2B domain B — HTTP contracts, lifecycle (12 files) | 37 | 5 (1C, 4H) | `416124c` |
| 9 | 28 FEB | — | Unpublish subsystem (5+8 files) | 22 | 2C (zero-task hang, revocation timing). 7 accepted risks | — |
| 12 | 01 MAR | — | STAC item ID naming (8+6 files) | 10 | Stale `stac_item_json`, `geoetl:*` property leak | — |
| 19 | 01 MAR | v0.9.11.0 | Web interface (6 files, ~13.7K lines) | 43 (6C, 8H) | XSS via URL params (BLIND-1), innerHTML sanitization, html shadowing | — |
| 28 | 02 MAR | — | Approval workflow (constitution rerun, 7 files) | 22 (1C, 2H) | Block approval of non-COMPLETED releases. pgSTAC silent error swallowing (11 methods) | — |
| 29 | 02 MAR | — | CoreMachine orchestration (constitution rerun, 8 files) | 26 (2C, 5H) | Re-raise transient exceptions in handlers. SB messages silently consumed on failure | — |
| 30 | 03 MAR | — | NetCDF-to-Zarr pipeline (8 files) | 23 (2C, 4H) | Unpublish looks for wrong asset key. Versioned zarr loses `zarr/` prefix | — |
| 33 | 03 MAR | v0.9.12.1 | Release audit log + ordinal revision (6 files) | 17 (1C, 6H) | **FAIL** — `get_draft()` excludes REVOKED, overwrite unreachable | — |
| 39 | 07 MAR | v0.9.14.5 | All zarr/NetCDF pipelines (28 files) | 25 (1C, 5H) | Pre-cleanup I/O in orchestrator, urlparse abfs fix, zarr_format wiring | — |
| 42 | 10 MAR | v0.10.0.2 | External environment infra (11 files) | 21 (3C, 4H) | Stack traces in HTTP responses (AAD token leak), libpq injection, silent fallback | — |

---

## GREENFIELD Runs (Design + Build)

| Run | Date | Scope | V Rating | Key Output |
|-----|------|-------|----------|------------|
| 7 | 28 FEB | Approval conflict guard | — | `idx_releases_version_conflict` partial unique index, `rollback_approval_atomic()` |
| 8 | 27 FEB | VirtualiZarr pipeline | NEEDS MINOR WORK | `VirtualZarrJob` (4-stage), 4 handlers, 12 mediator conflicts resolved |
| 10 | 28 FEB | Zarr unpublish | NEEDS MINOR WORK | `UnpublishZarrJob` (3-stage), `inventory_zarr_item` handler |
| 24 | 02 MAR | Dashboard submit form | GOOD | ~300 lines added. Narrow scope prevented Builder budget collapse |

---

## SIEGE Runs (Live API Testing)

| Run | SIEGE# | Date | Version | Sequences | Pass Rate | Key Result |
|-----|--------|------|---------|-----------|-----------|------------|
| 11 | 1 | 01 MAR | v0.9.9.0 | 5 | 54.5% | First SIEGE. STAC materialization ordering (SG-1 CRITICAL) |
| 13 | 2 | 01 MAR | v0.9.10.0 | 5 | 80% | SG-1 FIXED. Raster approval works E2E |
| 18 | 3 | 01 MAR | v0.9.10.1 | 5 | 100% (Lancer) | First clean Lancer sweep. SG-3, SG-5, SG2-3 FIXED |
| 20 | 4 | 01 MAR | v0.9.11.2 | 4 | 75% | LNC-1 CRITICAL — vector submit broken (non-Optional stac fields) |
| 21 | 5 | 01 MAR | v0.9.11.3 | 5 | 84% | LNC-1 FIXED — first-ever vector pass. SG5-1 found (approve allows failed) |
| 22 | 6 | 02 MAR | v0.9.11.5/6 | 5+32 invalid | 100%/81% | Provocateur added. scipy backend incompatible (SG6-L1) |
| 23 | 7 | 02 MAR | v0.9.11.7 | 6+32 invalid | 100%/95.5% | SG6-L1 FIXED — first clean NetCDF E2E. 0 new bugs |
| 25 | 8 | 02 MAR | v0.9.11.9 | 13 | 87.4% | Expanded to 13 sequences. REJ2-F1 CRITICAL (resubmit broken) |
| 26 | 9 | 02 MAR | v0.9.11.10 | 13 | 90.8% | 3 fixes verified. Zero state divergences (17/17) |
| 34 | 10 | 04 MAR | v0.9.12.2 | 18 | 98.2% | Overwrite hardening (5 new sequences). All 31 OW steps pass |
| 35 | 11 | 04 MAR | v0.9.13.1 | 18 | 94.9% | Fix verification. Native zarr rediagnosed (version_id required:true) |
| 37 | 12 | 06 MAR | v0.9.14.0 | 19 | 95.5% | ERH-1 (extra=forbid) and NZ1-F1 (native zarr) verified. Rechunk path added |
| 38 | 13 | 07 MAR | v0.9.14.4 | 19 | 94.9% | 18/19 PASS. Native zarr xarray WORKS. Rechunk codec issue (SG13-1) |
| 40 | 14 | 08 MAR | v0.9.16.0 | 19 | 98.0% | Zarr rechunk FIXED. 13/13 service URL probes pass |
| 41 | 15 | 09 MAR | v0.10.0.0 | 19 | 84.2% | GDAL 3.12.2 upgrade — zero GDAL regressions. SG15-1 (datetime=null) |
| 41b | 16 | 13 MAR | v0.10.0.3 | 25 | mixed | PostgreSQL OOM caused cascading failures. 7 findings |
| 43 | 17 | 14 MAR | v0.10.2.0 | 25 | 92.7% | PostgreSQL decomposition — zero regressions. Connection infra validated |

**SIEGE pass rate trajectory**: 54.5% → 80% → 100% → 75% → 84% → 100% → 87% → 91% → 98% → 95% → 95.5% → 95% → 98% → 84% → mixed → 93%

---

## REFLEXION Runs (Root Cause + Patch)

| Run | Date | Bug | Root Cause | Patches |
|-----|------|-----|------------|---------|
| 14 | 01 MAR | SG-3: catalog/dataset 500 | SQL references removed `r.table_name` column | 2 (1C, 1H) — both applied |
| 15 | 01 MAR | SG-5: blobs_deleted=0 | 3-bug cascade: `/vsiaz/` href misparse + missing return + silent success | 3 (1C, 1H, 1M) — all applied |
| 16 | 01 MAR | SG2-2: revoke retains is_served | 2 SQL paths missing `is_served = false` | 2 — both applied |
| 17 | 01 MAR | SG2-3: STAC fields stripped | pgSTAC `content` JSONB alone incomplete; reconstitution pattern existed but not propagated | 3 — all applied |
| 32 | 04 MAR | ADV-2: approval guard | Guard CANNOT be bypassed. But stale-ordinal guard inoperative (`KeyError` on `dict_row`) | 5 of 6 approved |

---

## TOURNAMENT Run

| Run | Date | Version | Score | Key Findings |
|-----|------|---------|-------|--------------|
| 27 | 02 MAR | v0.9.11.10 | 87.2% | Pathfinder 6/6 PASS. Saboteur: 16/18 blocked. PRV-1 CRITICAL (ValueError vs JSONDecodeError). LA-1 (stale approval, SG5-1 reconfirmed). PRV-2 HIGH (SSRF info leak). 0 state divergences |

---

## ADVOCATE Runs (DX Audit)

| Run | Date | Version | DX Score | Key Findings |
|-----|------|---------|----------|--------------|
| 31 | 03 MAR | v0.9.12.0 | 37% | ADV-1 CRITICAL (dead job_status_url). 5 error shapes. services/outputs always null. 18 of 25 findings fixed by v0.9.12.2 |
| 36 | 05 MAR | v0.9.13.2 | 52% (+15) | ERH-1 CRITICAL (data_type silently ignored). Raster vs vector error quality split. 19/34 tests grade A |

---

## Cumulative Statistics

| Metric | Value |
|--------|-------|
| Total runs | 43 (15 COMPETE, 4 GREENFIELD, 17 SIEGE, 5 REFLEXION, 1 TOURNAMENT, 2 ADVOCATE) |
| Instrumented tokens | ~7.5M |
| CRITICAL bugs found | ~25 |
| HIGH bugs found | ~50 |
| SIEGE pass rate (start → end) | 54.5% → 93% |
| DX score (start → end) | 37% → 52% |

---

## Cross-Cutting Findings (Patterns Across Runs)

### Most-Patched Subsystems
1. **Approval workflow** — touched in runs 4, 5, 6, 12, 14, 16, 25, 26, 27, 28, 32
2. **STAC materialization** — runs 11, 12, 13, 17, 18, 20
3. **Unpublish pipeline** — runs 9, 10, 15, 30, 39
4. **Error handling surfaces** — runs 19, 27, 31, 36

### Recurring Bugs
- **SG5-1 / LA-1**: Approve allows failed/processing releases — found in runs 21, 22, 27, 28, 31. Fixed with 4-layer guard
- **Silent exception swallowing**: Found in runs 9, 28, 29 (CoreMachine, StateManager, pgSTAC). Constitution Section 3.3
- **STAC item ID lifecycle**: Naming, caching, reconstitution issues across runs 12, 17, 18

### Key Milestones
- **Run 18 (SIEGE 3)**: First 100% Lancer pass rate
- **Run 21 (SIEGE 5)**: First-ever vector lifecycle pass (LNC-1 fixed)
- **Run 23 (SIEGE 7)**: First clean NetCDF/VirtualiZarr E2E
- **Run 34 (SIEGE 10)**: 98.2% — overwrite hardening validated
- **Run 40 (SIEGE 14)**: 98.0% — zarr rechunk working, all service URLs pass
- **Run 43 (SIEGE 17)**: PostgreSQL decomposition — zero regressions
