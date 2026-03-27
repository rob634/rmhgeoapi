# Unified Zarr Ingest Workflow — Design Spec

**Created**: 27 MAR 2026
**Status**: DRAFT
**Version**: v0.10.9
**Author**: Claude + Robert Harrison
**Relates to**: V10_MIGRATION.md Phase 7 (v0.10.9), ZARR_MAGIC.md

---

## Summary

A single unified DAG workflow (`ingest_zarr.yaml`) that accepts either NetCDF or native Zarr inputs, rechunks to 256x256 spatial tiles optimized for TiTiler-xarray, generates multiscale pyramids via ndpyramid, and registers the output with STAC. Replaces the two existing separate workflows (`ingest_zarr.yaml` + `netcdf_to_zarr.yaml`).

**Scope**: 1 unified YAML workflow, 2 new handlers (`zarr_validate_source`, `zarr_generate_pyramid`), 1 modified handler (`netcdf_convert` → `netcdf_convert_and_pyramid`), new dependencies (`ndpyramid`, `rioxarray`).

**Out of scope**: VirtualiZarr workflows, unpublish_zarr (uses existing handlers like unpublish_raster pattern), TiTiler PyramidReader (Layer 3 in ZARR_MAGIC — separate story).

---

## Design Decisions

### D1: Unified workflow replaces two separate YAMLs

The existing `ingest_zarr.yaml` and `netcdf_to_zarr.yaml` share an identical tail (register → STAC materialize). A conditional node routes based on input type, both paths converge on shared registration and STAC nodes. This is the same pattern as `process_raster.yaml` routing between single COG and tiled COG paths.

The existing separate YAML files will be superseded (not deleted until E2E verified).

### D2: Single-pass for NetCDF, two-step for Zarr

**NetCDF path**: `open_mfdataset()` → `chunk(256×256)` → `pyramid_resample()` → `pyramid.to_zarr()`. The Dataset is a Dask graph in memory — no intermediate flat store is written. One execution, one write pass. This is analogous to how GDAL combines reprojection + COG translate in one pass.

**Zarr path**: `rechunk` (writes flat store or skips if already 256/512) → `generate_pyramid` (reads flat store, writes pyramid store). Two nodes because the source store already exists on disk — no point loading it into a Dask graph just to combine with pyramid generation.

### D3: Rechunk bypass for 256×256 or 512×512

The `ingest_zarr_rechunk` handler checks spatial chunk sizes before rechunking. If chunks are already 256×256 or 512×512, it skips the rechunk and passes through the existing store URL. The bypass lives inside the handler (not as a DAG conditional) because:
- The handler must open the store anyway — the check is free
- Avoids DAG conditional + skip propagation complexity
- Downstream `generate_pyramid` doesn't care whether rechunking occurred

Returns `{rechunked: true/false, zarr_store_url: "..."}` for transparency.

### D4: Multiscale pyramids via ndpyramid (ZARR_MAGIC Layer 2)

Pyramids are the highest-impact optimization for TiTiler-xarray serving (ZARR_MAGIC.md priority #1). Without pyramids, low-zoom tile requests read the entire dataset — O(n). With pyramids, every tile at every zoom reads ~1-2 chunks — O(1).

**Auto-detect levels**: Compute from spatial dimensions. Add levels until the coarsest level fits in ≤1 chunk (256 pixels). For 1440×720 (0.25° CMIP6): 4 levels. For 360×180 (1° model): 2 levels.

**Resampling default**: `bilinear` — good for continuous fields (temperature, precipitation). Configurable per submission.

**Storage overhead**: ~33% above base level (each level is 4× smaller). Negligible.

**Analytics impact**: Zero. Level 0 IS the full-resolution analytical data. Pyramid levels are additional pre-computed summaries alongside it. `xr.open_zarr("store/0")` returns the exact same data as a flat store.

### D5: Single pyramid store is canonical (ZARR_MAGIC Q11 resolved)

No dual stores. The pyramid Zarr IS the canonical store — level 0 = full resolution for analytics, levels 1-N = downsampled for tile serving. One URL, one store, one STAC item.

### D6: Zarr v3 output, Blosc/LZ4/BITSHUFFLE compression

All output is Zarr v3 format with:
- Spatial chunks: 256×256 (configurable)
- Time chunks: 1 (mandatory for tile serving — slice single timestep per request)
- Codec: `zarr.codecs.BloscCodec(cname="lz4", clevel=5, shuffle="bitshuffle")`
- Consolidated metadata: mandatory `zarr.consolidate_metadata()` after write (CRITICAL for v3)

### D7: `dry_run: true` default

Per project standard (26 MAR 2026). Validate and detect run normally, convert/rechunk/pyramid skip the actual write.

### D8: New dependencies

| Package | Purpose | Added to |
|---------|---------|----------|
| `ndpyramid` | Multiscale pyramid generation (`pyramid_resample`) | `requirements-docker.txt` |
| `rioxarray` | CRS assignment (`ds.rio.write_crs()`) required by ndpyramid | `requirements-docker.txt` |

Both are well-maintained (ndpyramid by CarbonPlan, rioxarray by Corteva). ndpyramid pulls in `pyresample` for spatial resampling.

---

## Workflow Definition

### `workflows/ingest_zarr.yaml` (unified, replaces both existing)

**DAG shape**: validate → conditional → [NC: convert_and_pyramid | Zarr: rechunk → pyramid] → register → STAC

```yaml
workflow: ingest_zarr
description: "Unified Zarr ingest: NetCDF or Zarr → rechunk 256x256 → multiscale pyramid → STAC"
version: 2
reverses: [unpublish_zarr]

parameters:
  source_url: {type: str, required: true}
  source_account: {type: str, required: true}
  collection_id: {type: str, required: true}
  stac_item_id: {type: str, required: true}
  dataset_id: {type: str, required: true}
  resource_id: {type: str, required: true}
  access_level: {type: str, default: "internal"}
  target_container: {type: str, default: "silver-zarr"}
  target_prefix: {type: str, required: true}
  pyramid_levels: {type: int, default: 0}
  resampling: {type: str, default: "bilinear"}
  spatial_chunk_size: {type: int, default: 256}
  zarr_format: {type: int, default: 3}
  dry_run: {type: bool, default: true}

nodes:
  # ── Validate source and detect input type ──────────────────────
  validate:
    type: task
    handler: zarr_validate_source
    params: [source_url, source_account, dataset_id, resource_id]

  # ── Route: NetCDF or Zarr ──────────────────────────────────────
  detect_type:
    type: conditional
    depends_on: [validate]
    condition: "validate.input_type"
    branches:
      - name: netcdf_path
        condition: "eq netcdf"
        next: [convert_and_pyramid]
      - name: zarr_path
        default: true
        next: [rechunk]

  # ── PATH A: NetCDF → convert + chunk + pyramid (single pass) ───
  convert_and_pyramid:
    type: task
    handler: netcdf_convert_and_pyramid
    params: [source_url, source_account, target_container, target_prefix,
             spatial_chunk_size, zarr_format, pyramid_levels, resampling, dry_run]
    receives:
      file_list: "validate.file_list"
      dimensions: "validate.dimensions"

  # ── PATH B: Zarr → rechunk (skip if 256/512) ──────────────────
  rechunk:
    type: task
    handler: ingest_zarr_rechunk
    params: [source_url, source_account, target_container, target_prefix,
             spatial_chunk_size, zarr_format, dry_run]
    receives:
      current_chunks: "validate.current_chunks"
      dimensions: "validate.dimensions"

  # ── PATH B continued: generate pyramid from rechunked store ────
  generate_pyramid:
    type: task
    handler: zarr_generate_pyramid
    depends_on: [rechunk]
    params: [target_container, pyramid_levels, resampling, zarr_format, dry_run]
    receives:
      zarr_store_url: "rechunk.zarr_store_url"
      dimensions: "validate.dimensions"

  # ── Register metadata (both paths converge) ────────────────────
  register:
    type: task
    handler: zarr_register_metadata
    depends_on:
      - "convert_and_pyramid?"
      - "generate_pyramid?"
    params: [stac_item_id, collection_id, dataset_id, resource_id, access_level,
             target_container, target_prefix]

  # ── STAC materialization ───────────────────────────────────────
  materialize_item:
    type: task
    handler: stac_materialize_item
    depends_on: [register]
    params: [collection_id]
    receives:
      cog_id: "register.zarr_id"

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_item]
    params: [collection_id]
```

**Note on `receives:` convergence**: The `register` node needs `pyramid_url` from whichever path ran. The `?` optional dependency syntax handles skip propagation. The exact resolution syntax (`convert_and_pyramid?.pyramid_url || generate_pyramid?.pyramid_url`) needs verification against the param resolver — may need to use a simpler pattern where register reads from both and the handler takes whichever is non-null. See Implementation Consideration IC1 below.

---

## Handler Specifications

### New: `zarr_validate_source` (services/zarr/handler_validate_source.py)

**Purpose**: Detect input type (NC vs Zarr), validate structure, report dimensions and current chunks.

**Params**: `source_url`, `source_account`, `dataset_id`, `resource_id`

**Returns**:
```python
{
    "success": True,
    "input_type": "netcdf" | "zarr",
    "file_list": ["file1.nc", ...],       # NC path: list of NC files found
    "dimensions": {"time": 12, "lat": 720, "lon": 1440},
    "current_chunks": {"time": 1, "lat": 720, "lon": 1440},  # Zarr path only
    "needs_rechunk": True,                  # True if chunks not in {256, 512}
    "variable_count": 3,
    "total_size_bytes": 52428800
}
```

**Detection logic**: Inspect source URL/blob listing. If `.nc` files found → netcdf. If `.zmetadata` or `zarr.json` found → zarr.

### New: `zarr_generate_pyramid` (services/zarr/handler_generate_pyramid.py)

**Purpose**: Generate multiscale pyramid from a flat/rechunked Zarr store.

**Params**: `zarr_store_url`, `target_container`, `pyramid_levels`, `resampling`, `zarr_format`, `dry_run`, `dimensions`

**Returns**:
```python
{
    "success": True,
    "pyramid_url": "abfs://silver-zarr/prefix_pyramid.zarr",
    "levels_generated": 4,
    "resampling": "bilinear",
    "level_sizes": {"0": "1440x720", "1": "720x360", "2": "360x180", "3": "180x90"},
    "storage_bytes": 68157440
}
```

**Auto-detect levels** (when `pyramid_levels=0`):
```python
max_dim = max(spatial_dims)
levels = 0
while max_dim > spatial_chunk_size:
    max_dim //= 2
    levels += 1
return max(levels, 1)  # at least 1 level
```

**Core logic**:
```python
ds = xr.open_zarr(zarr_store_url, consolidated=True)
ds = ds.rio.write_crs("EPSG:4326")

pyramid = pyramid_resample(ds, x=lon_dim, y=lat_dim, levels=levels, resampling=resampling)
pyramid.to_zarr(target_url, zarr_format=zarr_format, consolidated=True, mode="w")

if zarr_format == 3:
    zarr.consolidate_metadata(store)
```

### Modified: `netcdf_convert` → `netcdf_convert_and_pyramid`

**Location**: `services/handler_netcdf_to_zarr.py`

**Change**: After the existing `ds.chunk(target_chunks)` step, add pyramid generation before writing:

```python
# Existing: ds = xr.open_mfdataset(nc_files) → ds.chunk(target_chunks)

# New: add CRS + pyramid
ds = ds.rio.write_crs("EPSG:4326")
pyramid = pyramid_resample(ds, x=lon_dim, y=lat_dim, levels=levels, resampling=resampling)
pyramid.to_zarr(target_url, zarr_format=zarr_format, consolidated=True, mode="w")

# Existing: zarr.consolidate_metadata(store) for v3
```

The handler name changes in `ALL_HANDLERS` registration. The old `netcdf_convert` key is kept as an alias for backward compat with any Epoch 4 references.

### Modified: `ingest_zarr_rechunk`

**Location**: `services/handler_ingest_zarr.py`

**Change**: Add bypass logic at the top:

```python
current_spatial = (current_chunks.get(lat_dim), current_chunks.get(lon_dim))
acceptable = {256, 512}

if current_spatial[0] in acceptable and current_spatial[1] in acceptable:
    logger.info("Spatial chunks %s already optimal, skipping rechunk", current_spatial)
    return {"success": True, "rechunked": False, "zarr_store_url": source_url}
```

Also add `current_chunks` to the params the handler reads from (passed via `receives:` from validate).

---

## Implementation Considerations

### IC1: Parameter convergence at register node

The DAG param resolver does not support `||` fallback syntax in `receives:`. The register handler must resolve the pyramid URL itself. Two approaches:

**Approach A (recommended)**: Both `convert_and_pyramid` and `generate_pyramid` write their output URL to a known location (e.g., `target_container/target_prefix_pyramid.zarr`). The register handler constructs the URL from its `target_container` + `target_prefix` params — it doesn't need `receives:` from upstream at all.

**Approach B**: The register handler reads `workflow_tasks` result_data for its predecessors and picks the non-null one. More complex, tighter coupling to the DAG infrastructure.

Approach A is simpler and follows the "convention over configuration" principle — all upstream handlers write to the same predictable path.

### IC2: Dimension name detection

NetCDF and Zarr stores use inconsistent dimension names (`lat`/`latitude`/`y`, `lon`/`longitude`/`x`, `time`/`t`). The existing `_build_zarr_encoding()` helper already handles this with lookup sets:

```python
spatial_names = {"lat", "latitude", "y"}
time_names = {"time", "t"}
```

The new handlers should use the same convention. The validate handler normalizes dimension names in its output so downstream handlers don't need to repeat the detection.

### IC3: CRS handling

`ndpyramid.pyramid_resample()` requires CRS metadata on the Dataset. Climate data (CMIP6, ERA5) is always EPSG:4326 but rarely has CRS metadata embedded. `ds.rio.write_crs("EPSG:4326")` sets it. For non-4326 data, the CRS should be detected from the source or passed as a parameter. For v1 of this workflow, assume EPSG:4326 (covers all current use cases).

### IC4: ndpyramid output structure

`pyramid_resample` returns an `xarray.DataTree`. When written with `.to_zarr()`, the output is a multi-group Zarr store with groups named `"0"`, `"1"`, `"2"`, etc. Root `.zattrs` contains the `multiscales` metadata convention. This is the structure TiTiler's PyramidReader (future) will consume.

---

## Validation Plan

### E2E test sequence

1. **NetCDF dry run**: Submit with `.nc` source, `dry_run: true` → validate completes, routes to NC path, no write
2. **NetCDF live**: Submit with `dry_run: false` → pyramid Zarr v3 written, registered, STAC materialized
3. **Zarr (needs rechunk) dry run**: Submit Zarr store with striped chunks, `dry_run: true` → validates, detects needs_rechunk
4. **Zarr (needs rechunk) live**: Submit with `dry_run: false` → rechunked + pyramid generated + registered
5. **Zarr (already 256×256)**: Submit optimized store → rechunk bypassed, pyramid generated from existing store
6. **Verify pyramid structure**: Open output with `xr.open_datatree()`, confirm levels, check consolidated metadata
7. **Verify analytics access**: `xr.open_zarr("store/0")` returns full-resolution data identical to input

### Test data (from SIEGE config)

- **NetCDF**: `wargames/good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc` (4 MB)
- **Zarr (quick)**: `wargames/good-data/cmip6-tasmax-quick.zarr` (10 MB)

---

## Files Changed

| File | Change | New? |
|------|--------|------|
| `workflows/ingest_zarr.yaml` | Replace with unified workflow (version 2) | Overwrite |
| `services/zarr/handler_validate_source.py` | New unified validate handler | Yes |
| `services/zarr/handler_generate_pyramid.py` | New pyramid generation handler | Yes |
| `services/handler_netcdf_to_zarr.py` | Modify `netcdf_convert` to add pyramid pass | No |
| `services/handler_ingest_zarr.py` | Add rechunk bypass for 256/512 chunks | No |
| `services/__init__.py` | Register new handlers in ALL_HANDLERS | No |
| `requirements-docker.txt` | Add `ndpyramid`, `rioxarray` | No |
| `workflows/netcdf_to_zarr.yaml` | Mark as superseded (keep until verified) | No |

---

## Impact on V10_MIGRATION.md

- v0.10.9 remaining: `ingest_zarr.yaml` and `netcdf_to_zarr.yaml` replaced by unified workflow
- Workflow count: 11 → 11 (unified replaces two, net +0 after `netcdf_to_zarr.yaml` removed)
- Handler count: 57 → 59 (two new: `zarr_validate_source`, `zarr_generate_pyramid`)
- ZARR_MAGIC.md: Open Questions 3 (v3), 5 (resampling), 11 (single vs dual store) answered by this design

---

*Spec: docs/superpowers/specs/2026-03-27-unified-zarr-ingest-design.md*
*Related: V10_MIGRATION.md Phase 7 (v0.10.9), ZARR_MAGIC.md*
