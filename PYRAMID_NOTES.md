# Zarr Pyramids and titiler-xarray — Compatibility Notes

## Problem

The ETL pipeline produces pyramidal Zarr stores (via `ndpyramid` / `pyramid_coarsen`) to improve tile serving performance. These stores have a `multiscales` metadata structure:

```
ssp370-2040-2059_pyramid.zarr/
├── zarr.json          ← root: multiscales metadata only, no data variables
├── 0/                 ← full resolution
├── 1/                 ← 2x coarsened
└── 2/                 ← 4x coarsened
```

**titiler-xarray does not support this format.** It opens the root as a flat xarray Dataset, finds `data_vars: {}`, and returns "No variable named '...'. Variables on the dataset include []".

## Why Pyramids Don't Help Here

The `multiscales` convention is designed for clients that select the appropriate resolution level themselves (e.g., `carbonplan/maps`, custom deck.gl viewers). These clients read the `multiscales` metadata, pick level `0` at high zoom and level `2` at low zoom.

titiler-xarray works differently — it expects a single flat Dataset and handles zoom-level performance by:

1. Reading only the chunks intersecting the requested tile
2. Relying on good chunk layout to minimize I/O
3. Letting GDAL/rasterio handle resampling at the tile boundary

The pyramid adds complexity that titiler-xarray can't use, and the extra storage/processing in the ETL is wasted.

## What to Produce Instead

A flat (non-pyramid) Zarr store with optimized chunking:

| Dimension | Recommended Chunk Size | Why |
|-----------|----------------------|-----|
| `time` | **1** | Most important. Ensures a tile request for one time step reads one chunk, not an entire time series |
| `y` (lat) | 256 or 512 | Matches common tile sizes. 256 for datasets <1000px spatial, 512 for larger |
| `x` (lon) | 256 or 512 | Same as y |

### Format Requirements

- **Zarr v3** — required by the current stack (titiler-xarray 1.2.x + zarr 3.1.x). Zarr v2 (`.zgroup` / `.zarray`) is not supported.
- **Consolidated metadata** not required for v3 (zarr 3.x reads `zarr.json` natively)

### Reference: Working Store

The CMIP6 `tasmax` store in `silver-zarr` is confirmed working with this stack. It uses flat layout, `time=1` chunking, Zarr v3 format.

## ETL Action

1. **Remove the pyramid step** from Zarr post-processing
2. **Ensure chunking** is set correctly during write: `ds.chunk({"time": 1, "y": 256, "x": 256}).to_zarr(..., zarr_format=3)`
3. **Re-process `spei12-test/ssp370-2040-2059`** as a flat Zarr to verify

## Serving URL Pattern

Once the flat Zarr is in blob storage, the viewer URL is:

```
/viewer/zarr?url=abfs://silver-zarr/zarr/spei12-test/ssp370-2040-2059.zarr&variable=spei12
```

The `abfs://` scheme uses the storage account from `AZURE_STORAGE_ACCOUNT_NAME`. Authentication is handled by Managed Identity (obstore backend).
