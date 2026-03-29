# COMPETE T4 — Raster Handler Chain

**Run**: 64
**Date**: 28 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Series**: COMPETE DAG Series — Target T4
**Version**: v0.10.9.0
**Split**: B (Internal vs External) + Single-Database Lens
**Files**: 10 (9 handlers + 1 YAML)
**Lines**: ~2,939
**Findings**: 10 confirmed — 1 CRITICAL, 2 HIGH, 2 MEDIUM, 5 rejected/downgraded
**Fixes Applied**: 5 (1 CRIT + 2 HIGH + 2 MEDIUM). LOWs/accepted left in place.
**Accepted Risks**: 3

---

## EXECUTIVE SUMMARY

The raster handler chain has one critical workflow gap: the tiled path had no STAC materialization node — `materialize_single_item` referenced outputs from `upload_single_cog` which is SKIPPED in the tiled branch. Every large raster (>2GB) failed at materialization. Additionally, NaN nodata was not filtered correctly in band statistics, and the tile handler's cleanup couldn't find the COG temp file due to a missing result key. All MEDIUM+ issues fixed.

---

## FIXES APPLIED

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **CRITICAL** | Tiled path has no STAC materialization | Added `materialize_tiled_items` node + `when` clause on `materialize_single_item` |
| 2 | **HIGH** | NaN nodata breaks statistics filtering | Added `np.isnan` check before comparison |
| 3 | **HIGH** | Tile cleanup references non-existent `cog_path` key | Derive local COG path from naming convention |
| 4 | MEDIUM | persist_tiled returns failure on partial success | Changed to `success: len(persisted_ids) > 0` |
| 5 | MEDIUM | processing_options silently dropped in single-COG path | Added fallback extraction from processing_options dict |

## ACCEPTED RISKS

| Risk | Rationale | Revisit |
|------|-----------|---------|
| CRS string equality comparison | Both strings are EPSG format from rasterio. Full CRS equivalence adds complexity for theoretical edge case. | Non-EPSG CRS sources |
| No dry_run in raster handlers | Handlers write to mount/blob; dry_run semantics unclear for COG creation. STAC handlers support it. | When dry_run spec is defined for ETL |
| Upload deletes source before downstream | No current downstream needs source after upload | Workflow extension with derived products |

## ARCHITECTURE WINS

1. Optional dependency pattern (`persist_single?`/`persist_tiled?`) correctly handles mutual-exclusion routing
2. WarpedVRT windowed reads for memory-efficient tile extraction
3. Block-window statistics keep memory at O(block_size)
4. Deterministic identifiers via shared `derive_stac_item_id`
5. Fan-in collect aggregation for tile results
