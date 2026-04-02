# COMPETE — Zarr/NetCDF Pipeline Adversarial Review

**Date**: 01 APR 2026
**Pipeline**: COMPETE (Adversarial Code Review — Alpha/Beta/Gamma/Delta)
**Version**: v0.10.9.9
**Scope**: End-to-end zarr/netcdf ingest: PATH A (netcdf_convert_and_pyramid) and PATH B (ingest_zarr_rechunk), registration, STAC materialization, unpublish
**Files Reviewed**: 8 primary (handler_netcdf_to_zarr.py, handler_ingest_zarr.py, handler_register.py, handler_materialize_item.py, stac_materialization.py, platform_translation.py, unpublish_handlers.py, handler_generate_pyramid.py)
**Findings**: 17 unique — 3 CRITICAL, 2 HIGH, 8 MEDIUM, 4 LOW
**Reviewers**: Alpha (path analysis), Beta (integration/race conditions), Gamma (dedup + cross-cutting), Delta (final triage)

---

## 1. EXECUTIVE SUMMARY

**The zarr/netcdf pipeline has three crash-or-corrupt bugs that block all ingest runs.** PATH A (netcdf_convert_and_pyramid) crashes immediately on a NameError referencing removed variables (C-1). PATH B (ingest_zarr_rechunk) writes to a URL without `.zarr` suffix while the downstream register handler expects `.zarr`, causing every rechunk-to-register handoff to fail (C-2). Additionally, STAC materialization for zarr items never injects TiTiler xarray URLs into pgSTAC, leaving raw `abfs://` URLs in the catalog (C-3). These three bugs mean no zarr workflow can complete end-to-end until fixed. Beyond the criticals, dead pyramid code (291 lines + requirements + registrations) should be cleaned up to prevent confusion.

---

## 2. TOP 5 FIXES

| Priority | ID | WHY | WHERE | HOW | EFFORT | RISK |
|----------|----|-----|-------|-----|--------|------|
| 1 | **C-1** | PATH A crashes on every call — `NameError: pyramid_levels` | `services/handler_netcdf_to_zarr.py:984-985` | Remove `pyramid_levels` and `resampling` from the `logger.info()` format string and args (lines 983-985). These variables were deleted when pyramid generation was removed but the log line was not updated. | S | Very low — log-only change |
| 2 | **C-2** | PATH B writes to wrong URL; register reads `.zarr` suffix, rechunk omits it | `services/handler_ingest_zarr.py:879,887,959` | Three changes: (1) Line 879: `f"az://{target_container}/{target_prefix}.zarr"` (2) Line 887: `delete_blobs_by_prefix(target_container, f"{target_prefix}.zarr")` (3) Line 959: `f"abfs://{target_container}/{target_prefix}.zarr"` | S | Low — PATH A already uses `.zarr` suffix correctly |
| 3 | **C-3** | Zarr STAC items lack TiTiler xarray URLs in pgSTAC | `services/stac/handler_materialize_item.py:124-128` | When `metadata_source == "zarr_metadata"`, extract `store_prefix` from `zarr_metadata` dict and pass as `zarr_prefix` kwarg to `materializer.materialize_to_pgstac()`. The `materialize_to_pgstac` method already accepts `zarr_prefix` (line 142 of stac_materialization.py) and `_inject_xarray_urls` already exists — they are just never connected for DAG-path zarr items. | S | Low — wiring only, no new logic |
| 4 | **H-1** | PATH A missing `zarr.consolidate_metadata()` — Zarr v3 stores lack consolidated metadata | `services/handler_netcdf_to_zarr.py:1083` (after `ds.to_zarr()`) | Add `zarr.consolidate_metadata(zarr.storage.FsspecStore.from_url(target_url, storage_options=target_storage_options))` after the `ds.to_zarr()` call. PATH B (rechunk) and other handlers already do this. | S | Low — additive |
| 5 | **H-2** | PATH B pre-cleanup misses blobs after C-2 fix | `services/handler_ingest_zarr.py:887` | Change `delete_blobs_by_prefix(target_container, target_prefix)` to `delete_blobs_by_prefix(target_container, f"{target_prefix}.zarr")`. Must be applied together with C-2. | S | Low — already included in C-2 fix set |

---

## 3. FULL FINDING LIST

### CRITICAL

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **C-1** | CONFIRMED | `handler_netcdf_to_zarr.py:984-985` | `logger.info` references `pyramid_levels` and `resampling` — both removed from param extraction at line 960-966. Every PATH A call raises `NameError` and fails. |
| **C-2** | CONFIRMED | `handler_ingest_zarr.py:879,887,959` | Rechunk writes to `az://{container}/{prefix}` (no `.zarr`). Register reads from `abfs://{container}/{prefix}.zarr`. URL mismatch causes "store not found" for every rechunk run. When rechunk is skipped (already correct chunking), nothing is written to silver at all, and register still tries `.zarr` — also fails. |
| **C-3** | CONFIRMED | `handler_materialize_item.py:124` + `stac_materialization.py:182` | `stac_materialize_item` calls `materialize_to_pgstac(stac_item_json, collection_id, blob_path=effective_blob_path)` without `zarr_prefix`. In `materialize_to_pgstac`, xarray URL injection is gated by `elif zarr_prefix:` (line 182) which is never truthy. All zarr items in pgSTAC retain raw `abfs://` URLs instead of TiTiler service URLs. |

### HIGH

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **H-1** | CONFIRMED | `handler_netcdf_to_zarr.py:1083` | After `ds.to_zarr()`, no `zarr.consolidate_metadata()` call. PATH B (rechunk handler at ~line 940), `netcdf_convert` handler, and `handler_register.py` all expect consolidated metadata. Zarr v3 stores from PATH A will fail `consolidated=True` open attempts, falling through to unconsolidated and potentially to the pyramid `group="0"` fallback. |
| **H-2** | CONFIRMED | `handler_ingest_zarr.py:887` | Pre-cleanup `delete_blobs_by_prefix(target_container, target_prefix)` uses raw prefix. After C-2 fix, blobs will live at `{target_prefix}.zarr/...`. Pre-cleanup on re-runs will miss them, leaving orphan blobs that corrupt subsequent writes. Must be fixed together with C-2. |

### MEDIUM

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **M-1** | CONFIRMED | `handler_register.py:125-126` | `group="0"` fallback for legacy pyramid stores. Violates Constitution zero-tolerance policy. If a store fails to open, this fallback masks the real error with a misleading "opened pyramid store" success that will fail downstream. |
| **M-2** | CONFIRMED | `handler_netcdf_to_zarr.py:1076` | PATH A does not call `ds[var].encoding.clear()` before `to_zarr()`. PATH B does (line 852). Inherited NetCDF4 encodings (e.g. `_FillValue`, `scale_factor`, `add_offset`) may conflict with Zarr v3 codecs, causing silent data corruption or write failures for specific datasets. Partially mitigated by explicit `encoding` param. |
| **M-3** | CONFIRMED | `handler_netcdf_to_zarr.py:1054` | CRS unconditionally stamped as `EPSG:4326` without checking source CRS. Correct for all current datasets but will silently produce wrong georeference if non-4326 data is ever ingested. PATH B does not write CRS at all. |
| **M-4** | CONFIRMED | Multiple files | Dead pyramid code: `handler_generate_pyramid.py` (291 lines), `ALL_HANDLERS` registration in `services/__init__.py:201`, `DOCKER_TASKS` timeout profile in `docker_service.py:442`, `ndpyramid`/`pyresample` in `requirements-docker.txt:75,77`. All dead weight since pyramid generation was replaced with flat zarr. |
| **M-5** | CONFIRMED | `handler_netcdf_to_zarr.py:1049` | PATH A imports `_detect_spatial_dims` from `handler_generate_pyramid.py`. If M-4 cleanup archives that file, PATH A breaks. Function must be moved to a shared module first. |
| **M-6** | PROBABLE | `handler_ingest_zarr.py` | No advisory lock on `target_prefix`. Two concurrent runs targeting the same prefix can interleave blob writes, producing a corrupt zarr store. Low probability in current single-user dev environment but will be a problem at scale. |
| **M-7** | CONFIRMED | `unpublish_handlers.py:1317-1325` | Zarr metadata deletion is outside the main DB transaction (try/except continues on failure). If blob deletion succeeds but metadata deletion fails, orphan `zarr_metadata` rows remain pointing at deleted blobs. |
| **M-8** | CONFIRMED | `platform_translation.py:695-725` | `_reshape_zarr_params` silently drops user-provided `time_chunk_size`, `compressor`, `compression_level`, `concat_dim`, `file_pattern`, and `max_files`. These params are accepted by the translate layer but never forwarded to the workflow, causing silent default-fallback behavior. |

### LOW

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **L-1** | CONFIRMED | STAC builder | STAC items with temporal ranges set `datetime` to a sentinel value instead of `null` as required by STAC spec. pgSTAC handles it correctly. Cosmetic. |
| **L-2** | CONFIRMED | `handler_netcdf_to_zarr.py` | Function name `netcdf_convert_and_pyramid` and docstring still reference pyramid generation. Misleading but harmless. |
| **L-3** | CONFIRMED | `handler_ingest_zarr.py` | `validate` sub-handler does not respect `dry_run` flag — always performs full validation including blob reads. Correct behavior (validation should always run) but violates dry_run contract. |
| **L-4** | PROBABLE | `unpublish_handlers.py` | Unpublish reads STAC item href from pgSTAC to derive blob path for deletion. If materialization rewrote the href (TiTiler URL injection), the derived blob path may be wrong. Depends on whether href is rewritten or only links are added. |

---

## 4. PYRAMID ORPHAN AUDIT

All surviving references to the removed pyramid generation feature:

| Location | Type | Line(s) | What |
|----------|------|---------|------|
| `services/zarr/handler_generate_pyramid.py` | **Entire file** | 1-291 | Dead handler: `zarr_generate_pyramid()` + helper `_detect_spatial_dims()` |
| `services/__init__.py` | Import + registration | 123, 201 | `from .zarr.handler_generate_pyramid import zarr_generate_pyramid` and `ALL_HANDLERS["zarr_generate_pyramid"]` |
| `docker_service.py` | Timeout profile | 442 | `'generate_pyramid': (60, 5, 3600)` in `DOCKER_TASKS` |
| `requirements-docker.txt` | Dependencies | 75, 77 | `ndpyramid>=0.3.0` and `pyresample>=1.28.0` |
| `handler_netcdf_to_zarr.py` | Import | 1049 | `from services.zarr.handler_generate_pyramid import _detect_spatial_dims` |
| `handler_netcdf_to_zarr.py` | Function name | 927 | Function still named `netcdf_convert_and_pyramid` |
| `handler_netcdf_to_zarr.py` | Docstring | 928-952 | Docstring references `pyramid_levels` and `resampling` params |
| `handler_netcdf_to_zarr.py` | Log messages | 982, 994, 1068, 1074, 1087 | Multiple log messages use "netcdf_convert_and_pyramid" prefix |
| `handler_register.py` | Fallback | 125-126 | `group="0"` fallback for legacy pyramid stores |

**Cleanup order** (dependency-aware):
1. Move `_detect_spatial_dims` to `services/zarr/helpers.py` or similar shared module
2. Update import in `handler_netcdf_to_zarr.py` to use new location
3. Remove `handler_generate_pyramid.py`
4. Remove `ALL_HANDLERS` entry and import in `services/__init__.py`
5. Remove `DOCKER_TASKS` timeout profile in `docker_service.py`
6. Remove `ndpyramid` and `pyresample` from `requirements-docker.txt`
7. Remove `group="0"` fallback in `handler_register.py`
8. Rename function and update log messages (optional, low priority)

---

## 5. PATH PARITY CHECK

Comparison of PATH A (`netcdf_convert_and_pyramid` in `handler_netcdf_to_zarr.py`) vs PATH B (`ingest_zarr_rechunk` in `handler_ingest_zarr.py`):

| Capability | PATH A (NC to Zarr) | PATH B (Zarr Rechunk) | Parity? |
|------------|--------------------|-----------------------|---------|
| **Output URL suffix** | `.zarr` (line 1028) | No `.zarr` (line 879, 959) | NO — C-2 |
| **Pre-cleanup prefix** | `.zarr` suffix (line 1064) | No `.zarr` suffix (line 887) | NO — H-2 |
| **Encoding clear** | Missing | `ds[var].encoding.clear()` (line 852-853) | NO — M-2 |
| **Consolidated metadata** | Missing after write | Present (implicit in xr.to_zarr) | NO — H-1 |
| **CRS assignment** | `rio.write_crs("EPSG:4326")` (line 1054) | Not performed | NO — M-3 |
| **Spatial dim rename** | Yes (x/y normalization, line 1048-1053) | Not performed | Intentional — rechunk preserves source dims |
| **Dry-run gate** | After validation (correct) | After validation (correct) | YES |
| **Target container default** | `silver-zarr` | `silver-zarr` | YES |
| **Chunk encoding** | `_build_zarr_encoding()` | `_build_zarr_encoding()` | YES |
| **Error return shape** | `{success, error, error_type}` | `{success, error, error_type}` | YES |
| **Result zarr_store_url** | `abfs://{container}/{prefix}.zarr` | `abfs://{container}/{prefix}` (no .zarr) | NO — C-2 |

**Verdict**: PATH B has 4 parity gaps vs PATH A: output URL suffix (C-2), pre-cleanup prefix (H-2), and the result URL returned to downstream handlers. PATH A has 2 gaps vs PATH B: missing encoding clear (M-2) and missing consolidate_metadata (H-1). These should converge.

---

## 6. ACCEPTED RISKS

| Finding | Risk | Rationale | Revisit When |
|---------|------|-----------|--------------|
| **M-3**: CRS hardcoded as EPSG:4326 | Incorrect georeference for non-4326 data | All current datasets are EPSG:4326. Document as a known constraint. | Non-4326 data source is onboarded |
| **M-6**: No advisory lock on target_prefix | Corrupt zarr store on concurrent writes | Single-user dev environment; job deduplication by SHA256 prevents most duplicates | Multi-user or parallel ingest is needed |
| **L-1**: Sentinel datetime for ranges | Non-compliant STAC spec | pgSTAC handles correctly; cosmetic only | STAC validator is added to CI |
| **L-3**: validate ignores dry_run | Validation always runs | Correct behavior — validation should always execute; dry_run gates destructive writes only | dry_run contract is formalized |
| **L-4**: Unpublish href derivation | Possible wrong blob path | Depends on TiTiler URL injection implementation; needs E2E test to confirm | Unpublish E2E test is added to SIEGE |

---

## 7. FIX DEPENDENCY GRAPH

```
C-1 (standalone)  ──────────────────────────── can fix immediately

C-2 ──┬── H-2 (must fix together)  ────────── can fix immediately
      │
      └── affects register handler (no code change needed — register already correct)

C-3 (standalone)  ──────────────────────────── can fix immediately

H-1 (standalone)  ──────────────────────────── can fix immediately

M-5 ──── M-4 (must move _detect_spatial_dims before archiving pyramid handler)

M-1, M-2, M-7, M-8 ────────────────────────── independent, can fix in any order
```

**Recommended fix order**: C-1 -> C-2+H-2 -> C-3 -> H-1 -> M-5+M-4 -> remaining MEDIUMs

---

*Generated by COMPETE pipeline (Alpha/Beta/Gamma/Delta) on 01 APR 2026*
*Reviewed files at v0.10.9.9*
