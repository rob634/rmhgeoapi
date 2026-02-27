# Adversarial Review: Tiled Raster Output Pipeline

**Date**: 26 FEB 2026
**Scope**: Tiled raster workflow — large file COG tiling → pgSTAC registration → TiTiler mosaic
**Pipeline**: Omega → Alpha + Beta (parallel) → Gamma → Delta
**Implementation Status**: 3 of 5 actionable findings RESOLVED (26 FEB 2026, commit `51e8a28`). 2 remaining.

---

## EXECUTIVE SUMMARY

The tiled raster pipeline has **two confirmed crash bugs** that block production workloads: a stale config attribute reference in `raster_cog.py` that crashes all single-COG Docker processing (C-1), and an unbound variable in the VSI checkpoint resume path that causes `NameError` when Phase 4 runs after a Phase 3 skip (C-2). Beyond these blockers, the two parallel tiled workflow implementations (`_process_raster_tiled` and `_process_raster_tiled_mount`) have divergent tiling behavior — the mount workflow produces zero-overlap tiles causing visible seams in TiTiler mosaics, while the VSI workflow uses 512px overlap. The architecture is fundamentally sound: the checkpoint system, handler registry, and pgSTAC write patterns are well-designed. The immediate priority is fixing the two crashers, then addressing the overlap gap and consolidating the duplicate workflows.

---

## REMAINING FIXES

> Fixes 1-3 completed in commit `51e8a28` (26 FEB 2026). See `ADVERSARIAL_ANALYSIS_HISTORY.md` for details.

### FIX 4: `_calculate_spatial_extent_from_tiles` opens every tile via HTTP [MEDIUM — CONFIRMED]

**What**: Opens every COG tile via `/vsiaz/` to read bounds. For 200 tiles = ~200 HTTP GETs = ~100 seconds. The tile bounds are already known from the tiling scheme output.

**Why**: Pure wasted I/O — the tiling scheme already has the bounds.

**Where**:
- `services/stac_collection.py`
- Function: `_calculate_spatial_extent_from_tiles()`, lines 618-698

**How**: Accept optional `tiling_result` parameter; compute union bbox from tiling scheme when available, fall back to per-tile HTTP approach otherwise.

**Effort**: 30 minutes
**Risk**: Low — per-tile approach remains as fallback

---

### FIX 5: `AZURE_STORAGE_KEY` unguarded env access bypasses Managed Identity [MEDIUM — CONFIRMED]

**What**: `stac_collection.py` line 651 reads `os.environ.get("AZURE_STORAGE_KEY")` with no None guard. Passed to `rasterio.Env()` — undefined behavior when `None` in production (which uses Managed Identity).

**Why**: In production `AZURE_STORAGE_KEY` is absent. GDAL's behavior with `AZURE_STORAGE_ACCESS_KEY=None` varies by version.

**Where**:
- `services/stac_collection.py`, line 651

**How**: Use credential chain — check for key, fall back to Azure AD auth:
```python
storage_key = os.environ.get("AZURE_STORAGE_KEY")
rasterio_env = {"AZURE_STORAGE_ACCOUNT": storage_account}
if storage_key:
    rasterio_env["AZURE_STORAGE_ACCESS_KEY"] = storage_key
else:
    rasterio_env["AZURE_STORAGE_AUTH_TYPE"] = "AZURE_AD"
```

**Effort**: 20 minutes
**Risk**: Low — largely mooted if Fix 4 is implemented (this code path becomes fallback-only)

---

## ACCEPTED RISKS

| ID | Finding | Rationale |
|----|---------|-----------|
| **H-1** | VSI workflow has no per-tile Phase 3 checkpoint (~50 min lost on failure) | Mount workflow (production path) has per-tile resume. VSI is fallback only. Track as tech debt. |
| **H-2** | Two duplicate ~500-line tiled workflows | Real maintenance hazard, but consolidation is multi-day Feature-level refactor. Both are stable. |
| **H-4** | `_process_raster_tiled_mount` is ~645 lines | Readability concern, not a bug. Sequential, well-commented. Refactor during H-2 consolidation. |
| **M-1** | Python hash vs pgSTAC GENERATED column hash divergence | Theoretical. Consistent `json.dumps(sort_keys=True)` serialization. Monitor, don't fix preemptively. |
| **M-4** | Partial `cog_metadata` state on extraction failure | Recoverable via upsert on retry. Existing retry mechanism handles this. |
| **M-5** | `TiTilerSearchService` is dead code | No runtime impact. Delete when convenient. |
| **M-6** | Fan-in mode in `stac_collection.py` is legacy | Functions correctly. Remove during H-2 consolidation. |
| **M-7** | Untyped inter-phase dict contracts | Real debt but changing requires touching all 4 phases. Do during H-2 refactor. |
| **M-8** | Direct infrastructure imports in `stac_collection.py` | Stable. Fix during service layer refactoring. |
| **L-1** | Inconsistent `total_phases` in progress reporting | Cosmetic only. |

---

## ARCHITECTURE WINS (Preserve These)

**CheckpointManager design** — Clean phase tracking with artifact validation and shutdown awareness. The mount workflow's blob-existence resume mechanism (`_get_completed_cog_indices`) is elegant and survives container restarts.

**ETL-owned pgSTAC write pattern** — TiTiler stays read-only; ETL owns all writes to collections, items, and searches tables. Correct security boundary. Do not introduce TiTiler writes.

**Non-fatal STAC with degraded mode** — STAC registration failure returns `"degraded": True` rather than failing the job. COG tiles are already uploaded — failing would lose that work. Right tradeoff.

**Handler registry with import-time validation** — `services/__init__.py` catches misconfigured handlers at import, not at job submission. Correct fail-fast.

**Disaster recovery via `metadata.json` sidecar** — Comprehensive metadata written alongside COGs in blob storage. Allows manual STAC catalog reconstruction without database access.

**Typed Pydantic result models** — `COGCreationResult`, `RasterValidationResult`, `STACCreationResult` give structured contracts for individual services. Extend to inter-phase contracts during consolidation.

---

## REVIEW PIPELINE TRACEABILITY

| Agent | Role | Key Findings |
|-------|------|-------------|
| **Omega** | Scope partition | Split into Architecture (Alpha) vs Correctness (Beta); identified priority files for Gamma |
| **Alpha** | Architecture lens | 7 strengths, 9 concerns (3 HIGH), 5 assumptions, 7 recommendations |
| **Beta** | Correctness lens | 7 verified-safe patterns, 7 bugs (1 CRITICAL, 3 HIGH), 4 risks, 6 edge cases |
| **Gamma** | Contradiction finder | 3 contradictions resolved, 2 agreements reinforced, 5 blind spots found, full severity recalibration |
| **Delta** | Final arbiter | Top 5 surgical fixes, 10 accepted risks, 6 architecture wins |
