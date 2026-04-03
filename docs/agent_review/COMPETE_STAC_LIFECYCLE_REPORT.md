# COMPETE -- STAC Lifecycle Adversarial Review

**Date**: 01 APR 2026
**Pipeline**: COMPETE (Adversarial Code Review -- Alpha/Beta/Gamma/Delta)
**Version**: v0.10.9.9
**Scope**: STAC lifecycle across Epoch 4 (approval service) and Epoch 5 (DAG handlers) -- materialization, state transitions, rebuild, vector/raster/zarr paths
**Files Reviewed**: 7 primary (~3,100 lines)
- `services/stac_materialization.py` (1,113 lines) -- Core materialization engine
- `services/stac/handler_materialize_item.py` (207 lines) -- DAG atomic handler
- `services/asset_approval_service.py` (1,098 lines) -- Epoch 4 approval path
- `services/vector/handler_build_stac_item.py` (172 lines) -- Vector STAC builder
- `triggers/stac/service.py` (516 lines) -- STAC API service layer
- `workflows/vector_docker_etl.yaml` -- Vector DAG workflow
- `workflows/process_raster.yaml` -- Raster DAG workflow
- `workflows/ingest_zarr.yaml` -- Zarr DAG workflow

**Findings**: 9 unique -- 1 CRITICAL, 3 HIGH, 2 MEDIUM, 3 LOW
**Verification Passes**: 5 (confirmed working correctly)
**Reviewers**: Alpha (state boundary audit), Beta (workflow wiring + integration), Gamma (dedup + cross-cutting), Delta (final triage)

---

## 1. EXECUTIVE SUMMARY

The STAC lifecycle has one functional bug that breaks vector STAC materialization in the DAG path (C-1: handler_materialize_item only searches cog_metadata and zarr_metadata, never Release where vector items cache their stac_item_json). The Epoch 4 approval paths (single COG, tiled, zarr) all stamp approval provenance properties but omit `ddh:status='approved'`, creating items that lack the canonical status discriminator (H-1). The catalog rebuild path (`rebuild_collection_from_db`) produces degraded items missing status, provenance, and TiTiler URLs (H-2). Vector workflow wiring runs both structural and approved STAC nodes after the approval gate, making the structural insert immediately overwritten with zero preview value (H-3).

---

## 2. TOP 5 FIXES

| Priority | ID | WHY | WHERE | HOW | EFFORT | RISK |
|----------|----|-----|-------|-----|--------|------|
| 1 | **C-1** | Vector STAC materialization fails -- handler returns "not found" for all vector items | `services/stac/handler_materialize_item.py:144-150` | After the zarr_metadata lookup block (line 142), add a third fallback: import ReleaseRepository, call `release_repo.get_by_stac_item_id(item_id)`, extract `stac_item_json` from the release. Three lines of code. | S | Low -- additive fallback, no existing path affected |
| 2 | **H-1** | Epoch 4 items lack `ddh:status='approved'` -- the canonical status discriminator that Epoch 5 stamps at line 218 | `services/stac_materialization.py:372,403,960` | Add `props['ddh:status'] = 'approved'` in three locations: (1) single COG path after line 372, (2) tiled `approval_props` dict at line 403, (3) zarr path after line 960. One line each. | S | Very low -- additive property stamp |
| 3 | **H-2** | Catalog rebuild produces degraded items: no `ddh:status`, no `ddh:approved_by/at`, no TiTiler/xarray URLs, shallow copy risk | `services/stac_materialization.py:770-805` | Four changes in `rebuild_collection_from_db()`: (1) Stamp `props['ddh:status'] = 'approved'` alongside existing ddh props. (2) Stamp `ddh:approved_by` and `ddh:approved_at` from release fields. (3) Call `self._inject_titiler_urls()` for raster items, `self._inject_xarray_urls()` for zarr items. (4) Change `dict(stac_json)` at line 783 to `copy.deepcopy(stac_json)`. | M | Low -- rebuild is a rare manual operation |
| 4 | **H-3** | Vector structural STAC runs post-gate (zero preview value, immediately overwritten) | `workflows/vector_docker_etl.yaml:119-139` | Remove `materialize_structural` node (lines 119-128). Change `materialize_approved.depends_on` from `[materialize_structural]` to `[build_stac_item]`. Structural insert before gate has no value for vector because build_stac_item itself runs after gate. | S | Low -- YAML-only change, no code |
| 5 | **L-3** | `_is_vector_release()` returns `None` not `False` when asset is non-vector | `services/stac_materialization.py:909-924` | Add `return False` at end of function body (after the try/except block's implicit fall-through). | S | Very low -- currently benign because `None` is falsy |

---

## 3. FULL FINDING LIST

### CRITICAL

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **C-1** | CONFIRMED | `handler_materialize_item.py:114-150` | `stac_materialize_item` searches `cog_metadata` (line 122-131) then `zarr_metadata` (line 134-142) for `stac_item_json`. Vector items cache their STAC JSON on the Release record via `vector_build_stac_item` (handler_build_stac_item.py:129-134), not in either metadata table. The handler returns `"stac_item_json not found"` for every vector item. The `release_repo.get_by_stac_item_id()` method already exists (release_repository.py:574) but is never called from this handler. |

### HIGH

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **H-1** | CONFIRMED | `stac_materialization.py:372,403,960` | The Epoch 5 `materialize_approved()` method stamps `ddh:status='approved'` (line 218) as the canonical state discriminator. The three Epoch 4 paths do not: (1) `materialize_item()` single COG path stamps `ddh:approved_by/at/access_level` at lines 368-372 but not `ddh:status`. (2) `_materialize_tiled_items()` builds `approval_props` at lines 403-411 without `ddh:status`. (3) `_materialize_zarr_item()` stamps approval properties at lines 954-960 without `ddh:status`. Result: Epoch 4 items cannot be distinguished from processing items by status field alone. |
| **H-2** | CONFIRMED | `stac_materialization.py:770-805` | `rebuild_collection_from_db()` iterates approved releases and inserts items but: (1) Never stamps `ddh:status='approved'`. (2) Never stamps `ddh:approved_by` or `ddh:approved_at` despite having the release object. (3) Never calls `_inject_titiler_urls()` or `_inject_xarray_urls()`, so rebuilt items lack TiTiler visualization URLs. (4) Uses shallow `dict(stac_json)` at line 783 for tiled items instead of `copy.deepcopy()`, risking mutation of shared nested dicts across iterations. |
| **H-3** | CONFIRMED | `vector_docker_etl.yaml:119-139` | Vector workflow has `materialize_structural` (line 120) and `materialize_approved` (line 131) both AFTER `approval_gate` (line 89). Both depend on `build_stac_item` which itself depends on `register_catalog` which depends on `approval_gate`. The structural insert (state 2, `ddh:status='processing'`) is immediately overwritten by the approved insert (state 3, `ddh:status='approved'`). This is wasted computation with no preview benefit. Contrast with raster/zarr workflows where structural insert runs BEFORE the gate to enable mosaic preview. |

### MEDIUM

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **M-1** | CONFIRMED | pgSTAC search layer | pgSTAC search is not filtered by `ddh:status`. TiTiler mosaic could theoretically serve state 2 (processing) items alongside state 3 (approved) items. Accepted risk per V10_DECISIONS.md -- deferred to post-v0.11. No code change needed. |
| **M-2** | CONFIRMED | `pgstac_search_registration.py` | Python SHA256 hash never matches PostgreSQL `search_tohash(search, metadata)` due to timestamp in metadata. Dedup lookup always misses, causing duplicate INSERT on re-registration. Self-correcting: code returns `result['hash']` (PostgreSQL-generated) on all paths. Documented in V10_DECISIONS.md section Q. |

### LOW

| ID | Confidence | File:Line | Description |
|----|------------|-----------|-------------|
| **L-1** | CONFIRMED | N/A | Vector state 2 items expose TiPG URL as the primary asset. Benign -- TiPG URLs are public-facing by design. |
| **L-2** | CONFIRMED | N/A | Raster state 2 items expose `/vsiaz/` GDAL pseudo-path in the data asset href. By design -- structural items are not B2C-sanitized. Overwritten at state 3. |
| **L-3** | CONFIRMED | `stac_materialization.py:909-924` | `_is_vector_release()` has no explicit `return False` after the try/except. When asset.data_type is not `'vector'`, the function returns `None` (implicit). Currently benign because `None` is falsy and callers use `if self._is_vector_release(release):`. |

---

## 4. STATE BOUNDARY AUDIT

Traces where `ddh:status` is stamped across STAC state transitions.

| State | Transition | Path | `ddh:status` Stamped? | File:Line |
|-------|------------|------|----------------------|-----------|
| 1 -> 2 | Structural insert (processing) | Epoch 5 DAG: `materialize_structural()` | YES: `"processing"` | `stac_materialization.py:157` |
| 1 -> 2 | Structural insert (processing) | Epoch 4: `stac_collection.py` bulk insert | YES: `"processing"` | `stac_collection.py:496` |
| 2 -> 3 | Approved (B2C) | Epoch 5 DAG: `materialize_approved()` | YES: `"approved"` | `stac_materialization.py:218` |
| 2 -> 3 | Approved single COG | Epoch 4: `materialize_item()` | **NO** -- stamps `ddh:approved_by/at/access_level` only | `stac_materialization.py:367-372` |
| 2 -> 3 | Approved tiled | Epoch 4: `_materialize_tiled_items()` | **NO** -- `approval_props` dict lacks `ddh:status` | `stac_materialization.py:402-411` |
| 2 -> 3 | Approved zarr | Epoch 4: `_materialize_zarr_item()` | **NO** -- stamps provenance only | `stac_materialization.py:949-960` |
| Rebuild | Nuclear rebuild | `rebuild_collection_from_db()` | **NO** -- stamps `ddh:access_level` and `ddh:version_id` only | `stac_materialization.py:786-803` |
| 3 -> deleted | Dematerialize (unpublish) | `dematerialize_item()` | N/A (item deleted) | `stac_materialization.py:653-712` |

**Summary**: 5 out of 8 state transition paths stamp `ddh:status` correctly. The 3 Epoch 4 approval paths and the rebuild path are missing the stamp.

---

## 5. WORKFLOW WIRING VERIFICATION

Cross-reference of STAC nodes in DAG workflows.

### Raster (`process_raster.yaml`)

| Node | Handler | Depends On | When Guard | Mode | Gate Position | Verdict |
|------|---------|------------|------------|------|---------------|---------|
| `materialize_structural_single` | `stac_materialize_item` | `persist_single?` | `upload_single_cog.result.stac_item_id` | structural | BEFORE gate | CORRECT |
| `materialize_structural_tiled` | `stac_materialize_item` | `persist_tiled?` | `persist_tiled.result.cog_ids` | structural | BEFORE gate | CORRECT |
| `materialize_collection_structural` | `stac_materialize_collection` | `structural_single?, structural_tiled?` | (none) | N/A | BEFORE gate | CORRECT |
| `approval_gate` | gate | `materialize_collection_structural` | N/A | N/A | GATE | CORRECT |
| `materialize_single_item` | `stac_materialize_item` | `approval_gate` | `upload_single_cog.result.stac_item_id` | approved | AFTER gate | CORRECT |
| `materialize_tiled_items` | `stac_materialize_item` | `approval_gate, persist_tiled?` | `persist_tiled.result.cog_ids` | approved | AFTER gate | CORRECT |
| `materialize_collection` | `stac_materialize_collection` | `single_item?, tiled_items?` | (none) | N/A | AFTER gate | CORRECT |

**Verdict**: Raster workflow correctly places structural inserts before gate and approved inserts after gate. Both single COG and tiled paths are properly conditional.

### Zarr (`ingest_zarr.yaml`)

| Node | Handler | Depends On | When Guard | Mode | Gate Position | Verdict |
|------|---------|------------|------------|------|---------------|---------|
| `materialize_structural` | `stac_materialize_item` | `register` | (none) | structural | BEFORE gate | CORRECT |
| `materialize_collection_structural` | `stac_materialize_collection` | `materialize_structural` | (none) | N/A | BEFORE gate | CORRECT |
| `approval_gate` | gate | `materialize_collection_structural` | N/A | N/A | GATE | CORRECT |
| `materialize_item` | `stac_materialize_item` | `approval_gate` | (none) | approved | AFTER gate | CORRECT |
| `materialize_collection` | `stac_materialize_collection` | `materialize_item` | (none) | N/A | AFTER gate | CORRECT |

**Verdict**: Zarr workflow correctly mirrors the raster pattern. Approval gate is properly positioned between structural and approved materialization.

### Vector (`vector_docker_etl.yaml`)

| Node | Handler | Depends On | When Guard | Mode | Gate Position | Verdict |
|------|---------|------------|------------|------|---------------|---------|
| `approval_gate` | gate | `link_release_tables` | N/A | N/A | GATE | CORRECT |
| `build_stac_item` | `vector_build_stac_item` | `register_catalog` | `params.create_stac` | N/A | AFTER gate | (STAC build is post-gate -- acceptable) |
| `materialize_structural` | `stac_materialize_item` | `build_stac_item` | `params.create_stac` | structural | AFTER gate | **H-3: WASTED -- runs after gate, immediately overwritten** |
| `materialize_approved` | `stac_materialize_item` | `materialize_structural` | `params.create_stac` | approved | AFTER gate | CORRECT (but should depend on build_stac_item directly) |
| `materialize_collection` | `stac_materialize_collection` | `materialize_approved?` | `params.create_stac` | N/A | AFTER gate | CORRECT |

**Verdict**: The vector structural node is dead weight. Since `build_stac_item` runs after the gate, the structural insert provides no preview window. Fix: remove `materialize_structural`, wire `materialize_approved` directly to `build_stac_item`.

---

## 6. VERIFICATION PASSES

These areas were explicitly verified as working correctly:

| # | What | Verified By | Notes |
|---|------|-------------|-------|
| 1 | Constants mechanism (`mode: structural` / `mode: approved`) | Beta | YAML constants correctly injected into handler params by DAG engine |
| 2 | Tiled bulk `cog_ids` path | Beta | `handler_materialize_item.py:80-112` correctly iterates `cog_ids` list and materializes each item |
| 3 | Zarr approval gate wiring | Beta | `ingest_zarr.yaml` correctly sequences structural -> gate -> approved |
| 4 | Vector skip propagation | Beta | `STACMaterializer.materialize_item()` correctly returns `skipped: true` for vector releases in Epoch 4 path |
| 5 | No race condition between state 2/3 upserts | Beta | pgSTAC `upsert_item` is atomic; sequential structural -> approved inserts are safe |

---

## 7. ACCEPTED RISKS

| ID | Risk | Rationale | Revisit When |
|----|------|-----------|--------------|
| M-1 | pgSTAC search unfiltered by `ddh:status` | TiTiler mosaic may include state 2 items. Low impact: mosaic URLs are not exposed pre-approval. State 2 items are overwritten by state 3 upserts. | Post-v0.11 when STAC filtering is needed for multi-tenant |
| M-2 | pgSTAC search dedup always fails | Python hash != PostgreSQL hash due to timestamp in metadata. Creates duplicate INSERT rows. Self-correcting: code uses PostgreSQL-generated hash on return. Documented in V10_DECISIONS.md section Q. | When dedup accuracy becomes critical for performance |
| L-1 | Vector state 2 exposes TiPG URL | TiPG URLs are public-facing by design. No information leak. | N/A |
| L-2 | Raster state 2 exposes `/vsiaz/` path | GDAL pseudo-path in structural items. Overwritten at state 3 by TiTiler URL injection. Not a security risk -- path is not directly resolvable without Azure credentials. | N/A |

---

## 8. FIX IMPLEMENTATION GUIDE

### C-1: Vector STAC materialization fallback

**File**: `services/stac/handler_materialize_item.py`
**After line 142** (end of zarr_metadata lookup block), add:

```python
    # Try release table (vector items cache stac_item_json on Release)
    if stac_item_json is None:
        try:
            from infrastructure.release_repository import ReleaseRepository
            release_repo = ReleaseRepository()
            release = release_repo.get_by_stac_item_id(item_id)
            if release and release.stac_item_json:
                stac_item_json = release.stac_item_json
                metadata_source = "release"
        except Exception as exc:
            logger.warning("release lookup failed for %s: %s", item_id, exc)
```

### H-1: Epoch 4 ddh:status stamp (3 locations)

**File**: `services/stac_materialization.py`

Location 1 -- single COG (after line 372):
```python
        props['ddh:status'] = 'approved'
```

Location 2 -- tiled (add to `approval_props` dict, line 403):
```python
        approval_props = {
            'ddh:status': 'approved',
            'ddh:approved_by': reviewer,
            ...
        }
```

Location 3 -- zarr (after line 960):
```python
        props['ddh:status'] = 'approved'
```

### H-3: Vector workflow cleanup

**File**: `workflows/vector_docker_etl.yaml`

Remove the `materialize_structural` node (lines 119-128). Change `materialize_approved.depends_on` from `[materialize_structural]` to `[build_stac_item]`.
