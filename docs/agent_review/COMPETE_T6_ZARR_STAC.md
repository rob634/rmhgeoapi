# COMPETE T6 — Zarr + STAC Handler Chain

**Run**: 66
**Date**: 28 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Series**: COMPETE DAG Series — Target T6
**Version**: v0.10.9.0
**Split**: A (Design vs Runtime) + Single-Database Lens
**Files**: 12 (5 zarr handlers + 3 STAC handlers/builders + 1 materialization + 2 YAML)
**Lines**: ~2,691
**Findings**: 13 confirmed — 0 CRITICAL, 2 HIGH, 4 MEDIUM, 7 LOW/accepted
**Fixes Applied**: 4 (2 HIGH + 2 MEDIUM). 2 MEDIUM deferred to v0.10.10.
**Accepted Risks**: 5
**Run 56 Fixes Verified**: `_inject_xarray_urls` signature FIXED. `_is_vector_release` heuristic FIXED.

---

## EXECUTIVE SUMMARY

The zarr-to-STAC chain is structurally sound with genuine builder purity and idempotent pgSTAC upserts. Two high-severity bugs found: (1) `ds.coords` accessed after `ds.close()` in `handler_register.py` — crash on pyramid stores lacking coordinate arrays, and (2) Epoch 5 zarr items missing `geoetl:data_type` property, causing unpublish routing to misroute zarr as raster. Both fixed. Dry-run validation order was corrected. `cog_id` parameter renamed to `item_id` with backward-compatible alias.

---

## FIXES APPLIED

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **HIGH** | `ds.coords` accessed after `ds.close()` | Captured coord_names before close |
| 2 | **HIGH** | Epoch 5 zarr items lack `geoetl:data_type` → unpublish misroutes | Added `geoetl:data_type = "zarr"` post-build |
| 3 | MEDIUM | dry_run skips parameter validation | Moved dry_run check after validation |
| 4 | MEDIUM | `cog_id` misleading param name for zarr | Renamed to `item_id` with `cog_id` alias |

## DEFERRED TO v0.10.10

| Finding | Why Deferred |
|---------|-------------|
| Post-hoc builder mutation + account_name leak | Requires materialization architecture change |
| Temporal interval sentinel | Cosmetic, pgSTAC handles correctly |

## ACCEPTED RISKS

| Risk | Rationale |
|------|-----------|
| Non-transactional collection + item write | Upsert idempotent, retry safe |
| Connection pool pressure | Acceptable at dev scale |
| Sentinel datetime `0001-01-01` | pgSTAC handles it |
| `application/vnd+zarr` media type | Consistent across codebase, defer to STAC zarr extension standard |
| EPSG:4326 hardcoded in pyramid generation | Correct for all current datasets |

## ARCHITECTURE WINS

1. Builder purity — `build_stac_item()` is a genuine pure function (dict in, dict out)
2. Composable materialization — `stac_materialize_item` serves both raster and zarr
3. B2C sanitization — `sanitize_item_properties()` strips internal prefixes cleanly
4. xarray URL injection — rewrites `abfs://` to TiTiler discovery endpoint
5. Run 56 fixes verified — both CRITICAL and H3 properly resolved
