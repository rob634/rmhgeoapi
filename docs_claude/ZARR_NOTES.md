# Zarr ETL Notes for TiTiler Tile Serving

Reference for ETL pipelines (Zarr2Zarr rechunking, NetCDF2Zarr conversion) producing Zarr stores consumed by rmhtitiler's titiler-xarray endpoint.

**Tile server:** rmhtitiler (titiler-pgstac:2.1.0, titiler-core 1.2.x, titiler.xarray 1.2.0, zarr>=3.1)
**Storage:** Azure Blob Storage via `abfs://` scheme with OAuth (Managed Identity)
**Verified datasets:** ERA5 (0.25deg, 744 time steps), CMIP6 tasmax (2.5deg, 12 time steps)

---

## CRITICAL: Consolidated Metadata Must Be Populated (Zarr v3)

**Date:** 2026-03-08 | **Affects:** Any Zarr v3 store served by titiler-xarray

### The Problem

Zarr v3 stores include a `consolidated_metadata` block in the root `zarr.json`. When this block is **present but empty**, xarray trusts it and concludes the store has zero variables — silently returning nothing. This is worse than omitting consolidated metadata entirely (which would cause xarray to scan the store).

The ERA5 rechunk store (`abfs://silver-zarr/climate-zarr-rechunk-plat/era5-rechunk`) has this bug:

```json
{
  "zarr_format": 3,
  "node_type": "group",
  "consolidated_metadata": {
    "kind": "inline",
    "must_understand": false,
    "metadata": {}          // <-- EMPTY — causes zero variables
  }
}
```

The individual variable arrays (e.g. `air_temperature_at_2_metres/zarr.json`) have correct metadata including `dimension_names`, `shape`, `codecs`, and `attributes`. But xarray never reads them because it trusts the empty consolidated metadata.

### Symptom

```bash
curl ".../xarray/variables?url=abfs://silver-zarr/.../era5-rechunk"
# Returns: []
# No error, no warning — just empty
```

### The Fix

**ETL must run `zarr.consolidate_metadata(store)` after writing any Zarr v3 store.** This populates the `consolidated_metadata.metadata` block with references to all arrays and their metadata.

```python
import zarr

# After writing the store:
store = zarr.storage.FsspecStore.from_url(
    "abfs://silver-zarr/path/to/store",
    storage_options={"account_name": "...", "credential": token}
)
zarr.consolidate_metadata(store)
```

### Why titiler-xarray Can't Work Around This

titiler-xarray calls `xarray.open_dataset(engine="zarr")` without passing `consolidated=False`. xarray's default behavior is: if consolidated metadata exists, trust it. There is no query parameter in titiler-xarray to override this. Even if there were, the correct fix is ETL-side — consolidated metadata exists for performance (avoids N+1 metadata reads on open).

### Updated Checklist Item

Added to **Zarr2Zarr Rechunking Checklist** below: step 6 now reads "Run `zarr.consolidate_metadata(store)` — **mandatory** for Zarr v3".

---

## Chunking Requirements

### Time Dimension — Most Important

**`time=1` is mandatory for visualization.** Every tile request reads one full chunk along the time dimension. If `time=12`, rendering a single time step still downloads all 12 time steps worth of data.

```
# BAD — one chunk covers all time steps
chunks: [12, 73, 144]    # 100MB+ per chunk, entire dataset per tile request

# GOOD — one chunk per time step
chunks: [1, 73, 144]     # ~42KB per chunk for this grid size
```

### Spatial Dimensions

For low-resolution grids (< 512px per dimension), chunk the entire spatial extent:
```
# 144x73 global 2.5-degree grid — single spatial chunk is fine
chunks: [1, 73, 144]
```

For high-resolution grids (> 512px per dimension), use 256x256 or 512x512 spatial chunks:
```
# 1440x721 global 0.25-degree grid (ERA5)
chunks: [1, 256, 256]    # or [1, 512, 512]

# Very large grids (3600x1800 or bigger)
chunks: [1, 512, 512]
```

### Why This Matters

titiler-xarray serves tiles via HTTP range requests. Each tile request reads the chunks that intersect the tile's spatial extent for a single time step. Oversized chunks = wasted bandwidth and slow tile rendering. Target: each chunk should be **< 1MB compressed** for interactive map performance (0.5-1s per tile).

---

## Zarr Format

### Version

titiler.xarray 1.2.0 uses zarr>=3.1 which reads **both Zarr v2 and v3**. Zarr v3 output is fine and preferred for new stores.

### Required Metadata

titiler-xarray validates these on open:

1. **Consolidated metadata** (Zarr v3) — `zarr.consolidate_metadata(store)` **must** be run after writing. See "CRITICAL" section above. Empty consolidated metadata causes silent zero-variable discovery.

2. **`_ARRAY_DIMENSIONS` attribute** (Zarr v2) or **`dimension_names`** (Zarr v3) on each data variable — tells xarray which dims are spatial vs temporal:
   ```json
   // Zarr v2:
   {"_ARRAY_DIMENSIONS": ["time", "lat", "lon"]}
   // Zarr v3 (in array zarr.json):
   {"dimension_names": ["time", "lat", "lon"]}
   ```

3. **Recognizable coordinate names** — must use standard names:
   - Latitude: `lat`, `latitude`, `y`
   - Longitude: `lon`, `longitude`, `x`
   - Time: `time`

4. **CF conventions** — `Conventions: "CF-1.6"` (or higher) in root `.zattrs`

5. **Coordinate arrays** — `lat` and `lon` must exist as 1D coordinate arrays with their own `.zarray` and `.zattrs`

### Recommended Attributes on Data Variables

```json
{
  "_ARRAY_DIMENSIONS": ["time", "lat", "lon"],
  "units": "K",
  "long_name": "Daily Maximum Near-Surface Air Temperature",
  "valid_min": 200.0,
  "valid_max": 340.0
}
```

The `valid_min`/`valid_max` (or `actual_range`) attributes are helpful for consumers to know the `rescale` parameter values without inspecting the data. titiler-xarray does NOT auto-scale — the `rescale` parameter is required on every tile/map request.

---

## URL Scheme

titiler-xarray uses `abfs://` (Azure Blob Filesystem) for authenticated access:

```
abfs://container-name/path/to/zarr-store

# Examples:
abfs://silver-zarr/cmip6-tasmax-sample.zarr
abfs://silver-zarr/sg-zarr-nz1-test/cmip6-tasmax
```

**Do NOT use `https://` URLs** — they route to anonymous HTTPFileSystem and will fail on private containers. The `.zarr` extension is optional; titiler-xarray detects Zarr stores by the presence of `.zgroup`/`.zmetadata` (v2) or `zarr.json` (v3) files.

---

## Tile Request Anatomy

A typical tile request:

```
GET /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png
    ?url=abfs://silver-zarr/my-dataset.zarr
    &variable=tasmax
    &bidx=1              # time step index (1-based)
    &rescale=250,320     # min,max for color scaling
    &colormap_name=viridis
```

What happens server-side:
1. Opens Zarr store via `AzureBlobFileSystem` (OAuth token from MI)
2. Selects `variable` from the xarray Dataset
3. Selects time step `bidx` (1-based index into the time dimension)
4. Reads only the spatial chunks that intersect the requested tile
5. Reprojects to WebMercatorQuad, applies rescale + colormap
6. Returns PNG tile

### Performance Expectations

| Grid Resolution | Chunk Size | Tile Latency | Notes |
|----------------|------------|-------------|-------|
| 144x73 (2.5deg) | [1, 73, 144] | ~0.5s | Single chunk read per tile |
| 1440x721 (0.25deg) | [1, 256, 256] | ~0.5-1s | 1-4 chunk reads per tile |
| 1440x721 (0.25deg) | [1, 721, 1440] | ~2-5s | Full grid read per tile (bad) |
| 1440x721 (0.25deg) | [744, 256, 256] | ~10s+ | All time steps read (very bad) |

---

## Map Viewer

titiler-core 1.2.0 includes a built-in `/map` viewer on all tiler endpoints:

```
/xarray/WebMercatorQuad/map
    ?url=abfs://silver-zarr/my-dataset.zarr
    &variable=tasmax
    &bidx=1
    &rescale=250,320
    &colormap_name=viridis
```

This renders an interactive Leaflet map — useful for quick visual QA after ETL runs.

---

## Metadata Consistency Warning

If a Zarr store is rechunked or rebuilt, **all metadata files must be regenerated**:
- `.zarray` (shape, chunks, dtype must match actual data)
- `.zmetadata` (consolidated metadata)
- `.zattrs` (coordinate metadata)

The `sg-zarr-nz1-test/cmip6-tasmax` store has stale metadata: `.zarray` claims shape=[12,73,144] with chunks=[12,73,144] (1 chunk), but there are 16 chunk files at ~100MB each. titiler-xarray reads it successfully despite this, but the inconsistency suggests the rechunker ran without updating metadata. Always verify metadata matches actual chunk layout after ETL.

---

## Zarr2Zarr Rechunking Checklist

1. Set `time=1` chunk size (mandatory)
2. Set spatial chunks to 256x256 or 512x512 for high-res grids
3. Ensure `_ARRAY_DIMENSIONS` attr on all data variables
4. Ensure `lat`/`lon` coordinate arrays exist with proper attrs
5. Set CF conventions in root `.zattrs`
6. **Run `zarr.consolidate_metadata(store)`** — MANDATORY for Zarr v3 (see CRITICAL section above). Empty consolidated metadata = silent failure.
7. Verify `.zarray` shape and chunks match actual chunk file layout
8. Document `valid_min`/`valid_max` or `actual_range` in variable attrs for rescale hints
9. Target Zarr v3 format for new stores

## NetCDF2Zarr Conversion Checklist

1. Convert all data variables and coordinates to Zarr arrays
2. Apply the chunking rules above (time=1, spatial 256x256 or 512x512)
3. Preserve CF attributes (`units`, `long_name`, `standard_name`, `_FillValue`)
4. Add `_ARRAY_DIMENSIONS` attr to each variable (xarray does this automatically if using `xr.Dataset.to_zarr()`)
5. Use compression (e.g., `numcodecs.Blosc(cname='zstd', clevel=3)`) to reduce chunk sizes
6. Write to `abfs://` destination with proper container permissions for MI read access

## Quick Verification After ETL

```bash
# 1. Check variables
curl "https://rmhtitiler-.../xarray/variables?url=abfs://container/path.zarr"

# 2. Check info (dimensions, bounds, time steps)
curl "https://rmhtitiler-.../xarray/info?url=abfs://container/path.zarr&variable=VARNAME"

# 3. Render a test tile
curl -o test.png "https://rmhtitiler-.../xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=abfs://container/path.zarr&variable=VARNAME&bidx=1&rescale=MIN,MAX&colormap_name=viridis"

# 4. Open map viewer for visual QA
# https://rmhtitiler-.../xarray/WebMercatorQuad/map?url=abfs://container/path.zarr&variable=VARNAME&bidx=1&rescale=MIN,MAX&colormap_name=viridis
```
