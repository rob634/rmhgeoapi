# STAC Consolidation Design

**Date**: 25 MAR 2026
**Status**: Design — Approved by Robert, pending implementation
**Goal**: Replace 3 item builders and 5 pgSTAC write paths with one canonical builder, one materialization function, and one collection builder.
**Principle**: pgSTAC is a materialized view of selected metadata fields from internal DB tables. One function builds the item, one function writes it.

---

## Problem Statement

The current STAC implementation has 3 distinct item builders producing structurally different items, 5 different pgSTAC write paths with inconsistent sanitization, and a mix of `create_item()` vs `upsert_item()` calls. Tile items are skeletal (missing proj:*, renders, raster:bands). The sentinel datetime `1999-12-31T00:00:00Z` is plausibly real. The admin rebuild path skips TiTiler URL injection. The Epoch 4 tiled path uses `pystac.Collection.to_dict()` while everything else hand-builds dicts.

### Current State (What's Broken)

| Builder | Location | Missing Fields |
|---------|----------|---------------|
| `_build_stac_item_json()` | handler_persist_app_tables.py | No geo:* attribution |
| `_build_tile_stac_item()` | handler_persist_tiled.py | No proj:*, no renders, no raster:bands, no geo:* |
| `RasterMetadata.to_stac_item()` | unified_metadata.py | Richest but Epoch 4 only |
| Zarr inline builder | handler_register.py | No stac_extensions, no proj:*, different asset key |

| Write Path | Sanitized? | TiTiler URLs? | pgSTAC fn |
|------------|-----------|--------------|-----------|
| DAG `stac_materialize_item` | Yes | Yes | `upsert_item` |
| Approval `STACMaterializer` | Yes | Yes | `upsert_item` |
| Epoch 4 tiled processing | Partial | No | `upsert_item` |
| Admin `POST /api/stac/extract` | No | No | `create_item` (fails on dup) |
| Admin bulk `extract_stac_metadata` | No | No | `create_item` (fails on dup) |
| Admin rebuild | Yes | **No (bug)** | `upsert_item` |

---

## Design Decisions

### D1: STAC item priority order

What the STAC item must answer, in order:

1. **Where is the resource and how do I access it?** TiTiler URLs (tilejson, viewer, thumbnail) ARE the access mechanism. No direct storage reading.
2. **Platform references.** DDH is the primary consumer. `ddh:dataset_id`, `ddh:resource_id`, `ddh:version_id` link back to DDH's metadata hierarchy.
3. **Spatiotemporal and attribute search.** `bbox`/`geometry` always present. `geo:iso3`/`geo:countries` enriched by pipeline when available. Temporal is limited — often unknown.

### D2: Sentinel datetime

STAC requires a non-null `datetime` field. When temporal context is unknown:
- Use `0001-01-01T00:00:00Z` (unambiguously fake — 1970 could be real for digitized imagery)
- Set internal property `geoetl:temporal_source: "unknown"` (stripped at B2C sanitization)
- Collections can eventually use a range like "2000 to now" for genuinely unknown temporal extent

### D3: Tiled collections — two-stage materialization

TiTiler needs items + search registration for mosaic preview BEFORE approval. Full B2C metadata materializes AFTER approval.

- **Stage 1 (processing time)**: Skeleton preview items + pgSTAC search registration. Minimal: geometry, bbox, datetime, asset href. Enough for TiTiler.
- **Stage 2 (approval time)**: Full `build_stac_item()` output read from `cog_metadata` cache, sanitized, stamped with approval properties, upserted over skeleton items.

Skeleton items visible in STAC API during preview are an accepted defect — aesthetically unpleasant, potentially confusing, but non-harmful. Will revisit after production launch.

**Tiled approval iteration**: At approval time, the approval flow queries `cog_metadata` for all rows matching the collection, then calls `materialize_to_pgstac()` once per tile. For a 24-tile collection this is 24 DB reads + 24 upserts — acceptable. For very large tile counts (100+), a batch variant may be needed later but is out of scope for this design.

### D4: No pystac for building

`pystac.Collection.to_dict()` produces a different dict shape than the hand-built path. Since pgSTAC expects a plain JSON dict via SQL, using a library to build a dictionary adds complexity for no benefit. All builders produce plain dicts. pystac stays as a dependency for other uses (reading, validation) but not for construction.

### D5: Epoch 4 and Epoch 5 compatibility

The builder is a pure function — no I/O, no framework dependency. Both epochs call `build_stac_item(**fields)` and get the same dict. Epoch 4 extracts fields from `RasterMetadata`; Epoch 5 DAG handlers pass fields from handler context. The function doesn't know or care which epoch called it.

---

## Architecture

### New Files

| File | Purpose | Type |
|------|---------|------|
| `services/stac/stac_item_builder.py` | `build_stac_item()` — canonical item builder | Pure function |
| `services/stac/stac_collection_builder.py` | `build_stac_collection()` — canonical collection builder | Pure function |
| `services/stac/stac_preview.py` | `build_preview_item()` — skeleton for TiTiler tiled preview | Pure function |

### Data Flow

```
Processing Time:
  handler extracts fields from blob/metadata
    |
    v
  build_stac_item(**fields) --> stac_item_json cached to cog_metadata/zarr_metadata
    |
    v (tiled only)
  build_preview_item() --> skeleton items to pgSTAC
  PgSTACSearchRegistration.register_collection_search() --> pgSTAC search
    |
    v
  TiTiler mosaic preview works immediately

Approval Time (or DAG materialize node for non-approval paths):
  read cached stac_item_json from cog_metadata/zarr_metadata
    |
    v
  STACMaterializer.materialize_to_pgstac(item, approval_stamps?)
    1. Copy (no mutation of cache)
    2. Sanitize (strip geoetl:*, processing:*)
    3. Stamp ddh:approved_by/at/access_level (if approval)
    4. Inject TiTiler URLs (COG or zarr)
    5. Ensure collection exists
    6. pgstac.upsert_item()
    |
    v
  handler_materialize_collection:
    build_stac_collection() + extent recalc --> pgSTAC collection
    register pgSTAC search (if tiled, item_count > 1) --> pgSTAC search
```

**Search registration ownership**: pgSTAC search registration is a collection-level concern, owned by `handler_materialize_collection` — NOT by `materialize_to_pgstac()` (which is per-item).

### `build_stac_item()` Signature

```python
def build_stac_item(
    # === Identity (required) ===
    item_id: str,
    collection_id: str,

    # === Spatial (required) ===
    bbox: list[float],              # [minx, miny, maxx, maxy] WGS84

    # === Access (required) ===
    asset_href: str,                # /vsiaz/... for COG, abfs://... for zarr
    asset_type: str,                # MIME type
    asset_roles: list[str] = ["data"],
    asset_key: str = "data",        # "data" for COG, "zarr-store" for zarr

    # === Temporal (optional) ===
    datetime: str | None = None,    # ISO8601 or None -> sentinel
    start_datetime: str | None = None,
    end_datetime: str | None = None,

    # === Projection (optional) ===
    crs: str | None = None,         # "EPSG:4326" or WKT
    transform: list | None = None,  # Affine [a,b,c,d,e,f]

    # === Raster metadata (optional) ===
    raster_bands: list | None = None,
    detected_type: str | None = None,
    band_count: int | None = None,
    data_type: str | None = None,

    # === Platform refs (optional) ===
    dataset_id: str | None = None,
    resource_id: str | None = None,
    version_id: str | None = None,

    # === Geographic attribution (optional) ===
    iso3_codes: list[str] | None = None,
    primary_iso3: str | None = None,
    country_names: list[str] | None = None,

    # === Zarr-specific (optional) ===
    zarr_variables: list[str] | None = None,
    zarr_dimensions: dict | None = None,

    # === Display (optional) ===
    title: str | None = None,

    # === Provenance (internal, stripped at materialization) ===
    job_id: str | None = None,
    epoch: int = 5,
) -> dict:
```

**Behavioral rules:**
- `geometry` always computed as Polygon from `bbox`. One source of truth.
- If no `datetime` and no `start_datetime` → `"0001-01-01T00:00:00Z"` + `geoetl:temporal_source: "unknown"`
- If `start_datetime`/`end_datetime` provided → `datetime` set to `start_datetime`, both range fields included
- `stac_extensions` computed from what's present (crs → projection, raster_bands → raster, renders → render)
- `renders` computed from `detected_type` + `band_count` + `data_type` + `raster_bands` via `stac_renders.build_renders()`. `data_type` is consumed only for render computation — it is NOT persisted as a property. Renders are immutable once built and cached in `stac_item_json`.
- `links: []` — pgSTAC auto-generates links; the builder does not add collection/self links
- `geoetl:*` properties always included in cached JSON (stripped at materialization)
- `ddh:*` properties included when platform refs provided
- `geo:*` properties included when attribution provided
- Returns a complete, valid STAC 1.0.0 Item dict

### `build_stac_collection()` Signature

```python
def build_stac_collection(
    collection_id: str,
    bbox: list[float] = [-180, -90, 180, 90],
    temporal_start: str | None = None,
    temporal_end: str | None = None,
    description: str | None = None,
    license: str = "proprietary",
    iso3_codes: list[str] | None = None,
    primary_iso3: str | None = None,
    country_names: list[str] | None = None,
) -> dict:
```

Returns a plain dict. Always the same shape. No pystac.

### `build_preview_item()` Signature

```python
def build_preview_item(
    item_id: str,
    collection_id: str,
    bbox: list[float],
    asset_href: str,
    asset_type: str = "image/tiff; application=geotiff; profile=cloud-optimized",
) -> dict:
```

Minimal: type, stac_version, stac_extensions (empty list), id, collection, geometry, bbox, datetime (sentinel), one asset. No properties beyond datetime. ~15 lines.

### `materialize_to_pgstac()` Signature

```python
def materialize_to_pgstac(
    self,
    stac_item_json: dict,
    collection_id: str,
    blob_path: str | None = None,       # COG: triggers TiTiler URL injection
    zarr_prefix: str | None = None,     # Zarr: triggers xarray URL injection
    approved_by: str | None = None,
    approved_at: str | None = None,
    access_level: str | None = None,
    version_id: str | None = None,
) -> dict:
```

Steps (always in this order):
1. Copy item dict
2. Sanitize (strip `geoetl:*`, `processing:*`)
3. Stamp `ddh:approved_*` if approval params provided
4. Inject TiTiler URLs if `blob_path` or `zarr_prefix` provided
5. Ensure collection exists (auto-create from item bbox if missing)
6. `pgstac.upsert_item()` — always upsert, never create

---

## Code Changes

### Deletions

| Code | Location | Replaced By |
|------|----------|------------|
| `_build_stac_item_json()` | services/raster/handler_persist_app_tables.py | `build_stac_item()` |
| `_build_tile_stac_item()` | services/raster/handler_persist_tiled.py | `build_stac_item()` |
| Zarr inline item builder | services/zarr/handler_register.py | `build_stac_item()` |
| `RasterMetadata.to_stac_item()` | core/models/unified_metadata.py | `build_stac_item()` with fields from RasterMetadata |
| `build_raster_stac_collection()` | services/stac_collection.py | `build_stac_collection()` |
| `pystac.Collection` usage | services/stac_collection.py | `build_stac_collection()` |
| `PgStacBootstrap.insert_item()` | triggers/stac_extract.py, services/stac_catalog.py | `upsert_item()` |
| `STACMaterializer._materialize_zarr_item()` | services/stac_materialization.py | `materialize_to_pgstac()` with zarr_prefix |

### Modifications

| File | Change |
|------|--------|
| `services/stac/handler_materialize_item.py` | Calls `materialize_to_pgstac()` |
| `services/stac/handler_materialize_collection.py` | Also registers pgSTAC search for tiled collections |
| `services/stac_materialization.py` | New `materialize_to_pgstac()`. Approval flow calls it. Rebuild fixed. |
| `services/raster/handler_persist_app_tables.py` | Calls `build_stac_item()` |
| `services/raster/handler_persist_tiled.py` | Calls `build_stac_item()` for cache, `build_preview_item()` for pgSTAC |
| `services/zarr/handler_register.py` | Calls `build_stac_item()` with zarr params |
| `services/handler_process_raster_complete.py` | Epoch 4: extract fields from RasterMetadata, call `build_stac_item()` |
| `services/stac_catalog.py` | Use `upsert_item()` instead of `create_item()` |
| `triggers/stac_extract.py` | Use `upsert_item()` instead of `create_item()` |

### Unchanged

| Code | Why |
|------|-----|
| `PgSTACSearchRegistration` | Clean service, just called from new location |
| `PgStacRepository` | pgSTAC SQL operations unchanged |
| `stac_renders.build_renders()` | Render logic solid, called by `build_stac_item()` |
| `sanitize_item_properties()` | Stays in STACMaterializer, called by `materialize_to_pgstac()` |
| `_inject_titiler_urls()` / `_inject_xarray_urls()` | TiTiler injection stays, called by `materialize_to_pgstac()` |

---

## Bugs Fixed by This Design

1. **Admin rebuild skips TiTiler URLs** — `rebuild_from_db()` now calls `materialize_to_pgstac()` which always injects URLs
2. **`create_item()` fails on duplicates** — all paths use `upsert_item()`
3. **Tile items missing proj:/renders/raster:bands** — all items built by same function with same fields
4. **Sentinel datetime `1999-12-31` is plausibly real** — changed to `0001-01-01T00:00:00Z`
5. **Collection shape inconsistency** (pystac vs hand-built) — one builder, one shape

---

## Existing Items in pgSTAC

Items already materialized under old builders (with `1999-12-31` sentinel, missing fields, inconsistent structure) are left as-is. The fixed admin rebuild path (`rebuild_all_from_db()`) serves as the migration mechanism — running it after deployment will re-materialize all items through the new canonical builder + `materialize_to_pgstac()`, producing consistent structure across the entire catalog. This is an on-demand operation, not an automatic migration.

---

## Testing Strategy

### Unit Tests for Pure Functions

- `test_build_stac_item_raster_single` — all raster fields provided, verify complete item
- `test_build_stac_item_raster_minimal` — only required fields, verify sentinel datetime + unknown flag
- `test_build_stac_item_zarr` — zarr params, verify asset key and zarr properties
- `test_build_stac_item_with_platform_refs` — ddh:* properties present
- `test_build_stac_item_with_temporal_range` — start/end datetime handling
- `test_build_stac_item_extensions_computed` — stac_extensions list matches provided fields
- `test_build_stac_collection_defaults` — verify shape with minimal params
- `test_build_preview_item` — verify skeleton structure

### Integration Tests

- `test_materialize_to_pgstac_sanitizes` — geoetl:* stripped, ddh:* preserved
- `test_materialize_to_pgstac_injects_titiler` — TiTiler URLs present after materialization
- `test_materialize_to_pgstac_approval_stamps` — ddh:approved_* present when provided
- `test_materialize_upsert_over_preview` — preview skeleton replaced by full item

---

## Scope and Sequencing

This work fits within the v0.10.x series. Suggested version: **v0.10.6** (Composable STAC was already started at v0.10.6).

### Phase 1: New builders + materialize function
Create the 3 new files, write tests. No existing code changes yet.

### Phase 2: Wire up DAG handlers (Epoch 5)
Replace inline builders in handler_persist_app_tables, handler_persist_tiled, handler_register. Wire stac_materialize_item to use materialize_to_pgstac().

### Phase 3: Wire up Epoch 4 paths
Replace RasterMetadata.to_stac_item() callers. Fix admin paths to use upsert_item().

### Phase 4: Delete dead code
Remove old builders, pystac collection usage, _materialize_zarr_item().
