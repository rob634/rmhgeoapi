# TiTiler-xarray Zarr Optimization Strategy

## Context

We operate a cloud-native geospatial platform on Azure serving CMIP6 climate data (and other raster datasets) via TiTiler-xarray reading from Zarr stores in Azure Blob Storage. We have **full control over both the ETL pipelines** that produce the Zarr files **and the TiTiler application layer** that serves them. The primary consumer is a web map frontend requesting XYZ tiles across a wide zoom range — from global views (zoom 0–4) to regional detail (zoom 10+).

Current pain point: **global and continental-scale views are extremely slow** because TiTiler must read and downsample the entire full-resolution dataset to render a single low-zoom tile.

---

## Core Principle: Apply COG Optimization Philosophy to Zarr

Cloud-Optimized GeoTIFFs (COGs) achieve fast HTTP-based tile serving through two mechanisms: internal tiling (spatial chunks aligned to tile requests) and overviews (pre-computed downsampled pyramids). Zarr can achieve the same results through analogous strategies:

| COG Concept | Zarr Equivalent |
|---|---|
| Internal tiling (256×256 or 512×512) | Spatial chunk shape aligned to tile size |
| IFD byte-range index | Each chunk is independently addressable via key/path |
| Overviews (2x, 4x, 8x…) | Multiscale pyramid as nested Zarr groups |
| Compression (DEFLATE/LZW) | Blosc + zstd/lz4 codecs |
| Consolidated header | Consolidated Zarr metadata (`.zmetadata`) |

**Key insight**: Optimizing the physical storage layout for partial HTTP range-read access does not alter the logical data model. A Zarr store optimized for tile serving remains a fully valid Zarr store usable by xarray, dask, GDAL, or any Zarr-aware client for analytical workloads.

---

## Layer 1: Zarr Storage Layout (ETL Side)

### 1.1 Spatial Chunking Strategy

Chunk shape is the single most impactful parameter for tile-serving performance. Each Zarr chunk maps to one HTTP range request, so chunk shape directly determines how much data TiTiler must fetch per tile.

**Target**: Align spatial chunk dimensions to the tile size TiTiler renders (typically 256×256 or 512×512 pixels).

**For CMIP6 data** (typical grid: ~1440×720 at 0.25°, or coarser):

- Spatial chunks of `256×256` or `512×512` are ideal for tile serving
- Time dimension should be chunked as `1` (single timestep per chunk) since tile requests always slice a single timestep
- If the spatial grid is smaller than the chunk size (e.g., a 1° model at 360×180), the entire spatial extent may fit in one chunk — this is fine and actually optimal for low-resolution models

**Chunk shape template for 3D CMIP6 variable (time, lat, lon):**

```python
chunks = {
    "time": 1,       # One timestep per chunk — tile requests always select one time
    "lat": 256,       # Aligned to tile size
    "lon": 256        # Aligned to tile size
}
```

**Tradeoffs to consider:**
- Very small chunks (64×64) → excessive HTTP request overhead, too many objects in Blob Storage
- Very large chunks (full latitude strips) → massive over-read for any single tile
- Non-square chunks → misalignment with square tile requests

> **OPEN QUESTION 1**: For coarse CMIP6 models (e.g., 2.5° grid = 144×72 pixels total), is it better to use a single spatial chunk covering the entire grid, or still chunk at 256×256 even though the grid is smaller? The single-chunk approach means one read for any tile at any zoom, but the 256×256 approach maintains consistency across the catalog. What are the indexing/metadata overhead implications of each?

### 1.2 Compression Codec Selection

For tile serving, **decompression speed matters more than compression ratio**. The bottleneck is often CPU time decompressing chunks, not network transfer.

**Recommended codecs:**
- **Blosc + LZ4**: Fastest decompression, moderate compression ratio. Best for serving.
- **Blosc + Zstd**: Slightly slower decompression, better compression ratio. Good balance.
- **Zlib/DEFLATE**: Slow decompression. Avoid for serving-optimized stores.

```python
import zarr

compressor = zarr.Blosc(cname='lz4', clevel=5, shuffle=zarr.Blosc.BITSHUFFLE)
# or
compressor = zarr.Blosc(cname='zstd', clevel=3, shuffle=zarr.Blosc.BITSHUFFLE)
```

BITSHUFFLE is generally better than SHUFFLE for floating-point climate data because it operates at the bit level, grouping similar bits together for better compression of IEEE 754 floats.

> **OPEN QUESTION 2**: For CMIP6 float32 temperature/precipitation data, is the compression ratio difference between LZ4 and Zstd significant enough to justify the decompression speed penalty? Should we benchmark both on representative CMIP6 variables (tas, pr, psl) and pick per-variable, or standardize on one codec for operational simplicity?

### 1.3 Consolidated Metadata

Zarr v2 supports consolidated metadata (`.zmetadata` file at the store root) that contains all array and group metadata in a single JSON file. Without it, opening a Zarr store requires one HTTP request per array/group to fetch individual `.zarray` and `.zattrs` files.

```python
zarr.consolidate_metadata("az://container/dataset.zarr")
```

For a multiscale pyramid with 5 levels and multiple variables, this can eliminate dozens of metadata requests on first access.

**Always enable consolidated metadata for any Zarr store served over HTTP.**

### 1.4 Zarr Format Version

Zarr v2 is the current production standard with broad tooling support. Zarr v3 is emerging with a more formal spec and extension mechanism, but tooling support is still maturing.

> **OPEN QUESTION 3**: Should the platform standardize on Zarr v2 for now, or invest in Zarr v3 early? ndpyramid and xarray both currently default to `zarr_format=2`. What is the timeline for v3 support in titiler-xarray, fsspec, and the Azure Blob storage backend? Is there a v3 feature (e.g., codecs pipeline, sharding) that would provide meaningful serving performance improvements?

---

## Layer 2: Multiscale Pyramids (The Critical Optimization)

This is the highest-impact optimization for CMIP6 visualization. Without pyramids, every low-zoom tile request forces TiTiler to read and downsample the full-resolution grid — an O(n) operation where n is the total dataset size. With pyramids, every tile request at any zoom level reads approximately the same amount of data — O(1) relative to the full dataset.

### 2.1 What a Multiscale Zarr Pyramid Looks Like

```
cmip6_tas_pyramid.zarr/
├── .zmetadata              # Consolidated metadata for all groups
├── .zattrs                 # Root attributes including "multiscales" spec
├── 0/                      # Level 0: Full resolution (e.g., 1440×720)
│   └── tas/
│       ├── .zarray
│       └── [chunk files]
├── 1/                      # Level 1: 2x downsampled (720×360)
│   └── tas/
├── 2/                      # Level 2: 4x downsampled (360×180)
│   └── tas/
├── 3/                      # Level 3: 8x downsampled (180×90)
│   └── tas/
└── 4/                      # Level 4: 16x downsampled (90×45)
    └── tas/
```

Each level is a complete, valid Zarr group with its own arrays, coordinates, and chunk structure. The root `.zattrs` contains a `multiscales` metadata object following the emerging Zarr multiscales convention that describes the hierarchy: which paths correspond to which levels, and what scale/translation transformations relate them.

**Storage overhead**: Each level is 4x smaller than the previous (in spatial dimensions). Total storage for the pyramid is approximately 1.33x the base level. Negligible cost.

### 2.2 Generating Pyramids with ndpyramid

ndpyramid is CarbonPlan's library purpose-built for generating N-dimensional array pyramids using xarray and Zarr. It outputs `xarray.DataTree` objects that serialize directly to multi-group Zarr stores.

**Three generation methods:**

| Method | Mechanism | Best For |
|---|---|---|
| `pyramid_resample` | pyresample block interpolation, Dask-parallel | Large datasets, CMIP6. Best performance at scale. |
| `pyramid_reproject` | Reprojects to Web Mercator (EPSG:3857) while building levels | Frontends expecting Mercator tiles |
| `pyramid_coarsen` | xarray `.coarsen()` block averaging | Quick prototyping, data already in target CRS |

**Recommended approach for CMIP6 (using `pyramid_resample`):**

```python
import xarray as xr
from ndpyramid import pyramid_resample

# Open source Zarr (already chunked from ETL)
ds = xr.open_zarr("az://container/cmip6_tas.zarr")
ds = ds.rio.write_crs("EPSG:4326")

# Generate pyramid with 5 levels, bilinear resampling
pyramid = pyramid_resample(
    ds,
    x="lon",
    y="lat",
    levels=5,
    resampling="bilinear"
)

# Write as multi-group Zarr store
pyramid.to_zarr(
    "az://container/cmip6_tas_pyramid.zarr",
    zarr_format=2,
    consolidated=True,
    mode="w"
)
```

**Requirements / constraints for `pyramid_resample`:**
- Longitude values must be in range [-180, 180]
- Dimension order must be `(time, y, x)` for 3D or `(y, x)` for 2D
- Chunked Zarr input is preferred to avoid complicated Dask task graphs from rechunking
- CRS must be assigned via rioxarray before pyramid generation

### 2.3 How Many Pyramid Levels?

The number of levels depends on the base resolution and the minimum zoom level you need to serve efficiently.

**Rule of thumb**: Add levels until the coarsest level fits in ≤ 1–2 spatial chunks.

For a 0.25° CMIP6 grid (1440×720):
- Level 0: 1440×720 (full res)
- Level 1: 720×360
- Level 2: 360×180
- Level 3: 180×90 → fits in single 256×256 chunk
- Level 4: 90×45 → comfortably fits in single chunk

**4–5 levels is sufficient for most CMIP6 data.** Beyond that, the data is already tiny.

For higher-resolution datasets (downscaled CMIP6 at 0.05°, FATHOM flood data), you may need 7–8 levels.

> **OPEN QUESTION 4**: Should the number of pyramid levels be dynamically calculated per dataset based on its native resolution, or should the platform enforce a fixed number of levels (e.g., always 5) for consistency? Dynamic levels optimize storage, but fixed levels simplify the TiTiler reader logic and API contract. How does this interact with the zoom-level-to-pyramid-level mapping on the serving side?

### 2.4 Resampling Method Selection

The resampling algorithm affects both visual quality and scientific validity of the downsampled data.

- **Nearest neighbor**: Fastest. Preserves exact values. Good for categorical data or when speed is paramount. Can look pixelated.
- **Bilinear**: Good balance of quality and speed. Smooth interpolation. Appropriate for continuous fields like temperature.
- **Conservative**: Preserves area-weighted means. Best for flux variables (precipitation, radiation) where spatial aggregation should conserve totals. Not natively available in ndpyramid but can be implemented with xesmf.

> **OPEN QUESTION 5**: For a multi-variable CMIP6 catalog, should the resampling method vary by variable type? E.g., bilinear for temperature/pressure (intensive properties), conservative for precipitation/radiation (extensive properties), nearest for land-use masks (categorical)? Or is bilinear acceptable across the board for visualization purposes given that the pyramid is only used for rendering tiles, not for analysis?

### 2.5 Web Mercator Reprojection: At Pyramid Time or Tile Time?

COG-based tile servers typically serve data that's already in Web Mercator (EPSG:3857), because the COG's internal tiling aligns 1:1 with XYZ tile grids. For Zarr, there are two approaches:

**Option A: Store pyramids in EPSG:4326, reproject at tile time**
- ETL is simpler (no reprojection step)
- TiTiler handles reprojection on the fly
- Data remains in its native CRS for analytical use
- Slight performance cost per tile request for the reprojection

**Option B: Store pyramids in EPSG:3857, serve directly**
- Use `pyramid_reproject` instead of `pyramid_resample`
- Tile requests align perfectly with stored chunks — no reprojection needed
- Fastest possible tile serving
- Data is distorted at high latitudes (Mercator projection) — not ideal for analysis
- Duplicates data if you also need 4326 for non-tile use cases

> **OPEN QUESTION 6**: Given that TiTiler already reprojects on the fly efficiently, is the performance gain of pre-reprojecting to 3857 worth the added ETL complexity and storage duplication? For CMIP6 data where users also run analytics in 4326, Option A seems pragmatic — but does the per-tile reprojection cost become significant at scale (hundreds of concurrent tile requests)?

---

## Layer 3: TiTiler Application Layer

### 3.1 Zoom-Level-Aware Pyramid Reading

Out of the box, `titiler.xarray.Reader` opens a flat Zarr store and doesn't understand multiscale pyramid hierarchies. To serve from pyramids, the application needs custom logic to route tile requests to the appropriate pyramid level.

**Approach A: Custom Reader with zoom-level mapping**

Extend the TiTiler reader to inspect the requested zoom level and open the corresponding Zarr group:

```python
import attr
from titiler.xarray.io import Reader

@attr.s
class PyramidReader(Reader):
    """Reader that selects pyramid level based on tile zoom."""

    def _get_pyramid_level(self, zoom: int) -> str:
        """Map tile zoom to pyramid level path."""
        # Example mapping for 5-level pyramid
        # Adjust thresholds based on native resolution and pyramid levels
        level_map = {
            range(0, 3): "4",    # Zoom 0-2 → coarsest level
            range(3, 5): "3",    # Zoom 3-4
            range(5, 7): "2",    # Zoom 5-6
            range(7, 9): "1",    # Zoom 7-8
            range(9, 20): "0",   # Zoom 9+ → full resolution
        }
        for zoom_range, level in level_map.items():
            if zoom in zoom_range:
                return level
        return "0"
```

**Approach B: URL-level routing / middleware**

The API layer rewrites the Zarr URL before it reaches the reader:

```
Request: /tiles/{z}/{x}/{y}?url=az://data/cmip6_tas_pyramid.zarr&variable=tas

Middleware maps z → level:
  z=2 → url becomes az://data/cmip6_tas_pyramid.zarr/4
  z=8 → url becomes az://data/cmip6_tas_pyramid.zarr/0
```

This avoids modifying the reader internals but requires external routing logic.

> **OPEN QUESTION 7**: Which approach is more maintainable — a custom PyramidReader that encapsulates the zoom-to-level logic, or a middleware/routing layer? The custom reader is self-contained but couples pyramid awareness into the data reader. The middleware is more flexible but adds a layer of indirection. How should the zoom-to-level mapping be configured — hardcoded per dataset, derived from `multiscales` metadata, or dynamically computed from the dataset's native resolution?

### 3.2 Dataset Object Caching

Re-opening a Zarr store on every tile request is expensive due to metadata fetches (even with consolidated metadata, there's still an HTTP round-trip). Caching the opened `xarray.Dataset` or the `fsspec` filesystem/mapper object across requests eliminates repeated metadata reads.

```python
from cachetools import TTLCache

# Cache opened datasets with 5-minute TTL
_dataset_cache = TTLCache(maxsize=100, ttl=300)

def get_dataset(url: str, **kwargs):
    if url not in _dataset_cache:
        _dataset_cache[url] = xr.open_zarr(url, consolidated=True, **kwargs)
    return _dataset_cache[url]
```

Considerations:
- Memory usage grows with cache size — each Dataset object holds coordinate arrays and metadata in memory
- TTL should balance freshness vs. performance (5–15 minutes for data that changes rarely)
- Thread safety: `TTLCache` is not thread-safe by default — use `cachetools.cached` with a lock, or a concurrent-safe alternative

> **OPEN QUESTION 8**: What is the memory footprint of a cached xarray.Dataset opened lazily from Zarr (i.e., data not loaded, just metadata and coordinates)? For a CMIP6 catalog with hundreds of variables × scenarios × models, how many datasets can reasonably be cached in the memory available to an Azure Web App (e.g., B2 or P1v2 plan)? Is there a lighter-weight object to cache — e.g., just the fsspec mapper — that avoids holding coordinate arrays in memory?

### 3.3 Tile Response Caching

TiTiler generates tiles dynamically on every request. For climate data that doesn't change after ETL, tile responses can be aggressively cached.

**Caching layers (innermost to outermost):**

1. **In-memory LRU cache** on the TiTiler process — fastest, limited by worker memory
2. **Redis/shared cache** — shared across workers, survives restarts, adds network hop
3. **CDN/Cloudflare cache** — closest to the user, longest TTL, requires proper cache headers

For the DDHGeo platform with Cloudflare already in the externalization architecture, the CDN layer is the highest-leverage cache:

```python
from fastapi import Response

@app.get("/tiles/{z}/{x}/{y}.png")
async def tile(z: int, x: int, y: int, ...):
    tile_data = render_tile(z, x, y, ...)
    return Response(
        content=tile_data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",  # 24 hours
            "CDN-Cache-Control": "max-age=604800",       # 7 days at CDN
        }
    )
```

> **OPEN QUESTION 9**: What's the right cache invalidation strategy when a dataset is re-processed through the ETL pipeline? Options include versioned URLs (e.g., `/v2/tiles/...`), Cloudflare cache purge API on ETL completion, or ETL-generated cache-busting query parameters. How does this interact with STAC catalog versioning if the platform evolves to use STAC for dataset discovery?

### 3.4 Concurrency and Worker Configuration

TiTiler is an async FastAPI application, but the actual data reads (xarray/rasterio) are blocking I/O operations. Configuration matters:

- **Uvicorn workers**: Match to available CPU cores (typically 2–4 per Web App SKU)
- **Thread pool**: FastAPI offloads sync operations to a thread pool. Default size may be insufficient for high-concurrency tile serving.
- **Dask scheduler**: For tile serving, use the synchronous scheduler (`dask.config.set(scheduler="synchronous")`) to avoid Dask overhead on small reads. The distributed scheduler is for ETL, not serving.

```python
import dask
dask.config.set(scheduler="synchronous")
```

> **OPEN QUESTION 10**: Should the TiTiler deployment use multiple small workers (e.g., 4 workers × 1 thread) or fewer workers with larger thread pools (e.g., 2 workers × 4 threads)? The former isolates memory better but increases process overhead. The latter shares the dataset cache across threads but risks GIL contention during numpy/decompression operations. What does profiling suggest for the typical CMIP6 tile workload?

---

## Layer 4: Infrastructure and Network Path

### 4.1 Storage-to-Compute Proximity

The Zarr stores in Azure Blob Storage and the TiTiler Web App must be in the same Azure region. Cross-region data reads add 50–200ms of latency per chunk fetch, which is devastating when a single tile request may read multiple chunks.

### 4.2 Authentication Overhead

Each chunk read from Azure Blob Storage requires authentication. Options:

- **SAS tokens**: Per-request URL signing overhead. For high-throughput tile serving, this adds up.
- **Managed Identity**: Token cached and reused. Lower per-request overhead. Already configured for the platform's managed identities (migeoetldbadminqa, migeoeextdbreaderqa).

**Use managed identity for the TiTiler Web App's storage access.**

### 4.3 Private Endpoints

If the Blob Storage account uses private endpoints (likely, given the platform's architecture), ensure the TiTiler Web App has VNet integration to access storage over the private network. This avoids public internet round-trips and reduces latency.

### 4.4 fsspec Configuration for Azure

The fsspec library (used by xarray to read Zarr from remote storage) has tunable parameters:

```python
import fsspec

fs = fsspec.filesystem(
    "az",
    account_name="storageaccount",
    connection_string="...",  # or use managed identity
    default_fill_cache=True,   # Cache directory listings
    default_cache_type="readahead",  # Prefetch adjacent chunks
)
```

Connection pooling, retry policies, and timeout settings on the underlying `aiohttp` or `requests` session can also impact serving performance.

---

## Layer 5: ETL Pipeline Integration

### 5.1 Proposed ETL Flow

```
Source Data (NetCDF/GRIB from CMIP6 archive)
    │
    ▼
[Azure Function: Ingest]
    - Download from source
    - Convert to Zarr with optimized chunking (256×256 spatial, 1 time)
    - Blosc/LZ4 compression
    - Write base Zarr to Azure Blob
    │
    ▼
[Azure Function: Pyramid Generation]
    - Open base Zarr
    - Run ndpyramid.pyramid_resample (Dask-parallelized)
    - Write multi-group pyramid Zarr to Azure Blob
    - Consolidate metadata
    │
    ▼
[Azure Function: Register]
    - Update STAC catalog / pgstac with pyramid Zarr URL
    - Record pyramid metadata (levels, CRS, resampling method)
    - Trigger Cloudflare cache purge if replacing existing dataset
    │
    ▼
[TiTiler Web App]
    - Reads from pyramid Zarr store
    - Serves tiles at all zoom levels with consistent performance
```

### 5.2 Rechunking Existing Zarr Stores

For Zarr stores already produced by the ETL pipeline with suboptimal chunking, use `rechunker` to reshape without full reprocessing:

```python
from rechunker import rechunk

target_chunks = {"time": 1, "lat": 256, "lon": 256}
rechunk_plan = rechunk(
    source=source_zarr,
    target_chunks=target_chunks,
    target_store="az://container/rechunked.zarr",
    temp_store="az://container/temp_rechunk/",
    max_mem="2GB"
)
rechunk_plan.execute()
```

> **OPEN QUESTION 11**: Should the ETL pipeline always produce both a flat (analysis-optimized) Zarr and a pyramid (serving-optimized) Zarr, or should the pyramid be the canonical store with the full-resolution level (level 0) serving double duty for both analysis and tile serving? The dual-store approach is cleaner conceptually but doubles write time. The single-pyramid approach is more efficient but requires all consumers to understand the group hierarchy.

---

## Layer 6: Monitoring and Profiling

### 6.1 What to Measure

Before optimizing, profile where time is actually spent in a tile request. The breakdown is typically:

1. **Metadata lookup**: Time to open the Zarr store and resolve chunk locations
2. **Chunk fetch**: HTTP range request(s) to read the required chunk(s) from Blob Storage
3. **Decompression**: CPU time to decompress the chunk data
4. **Computation**: Reprojection, resampling, colormap application
5. **Encoding**: Rendering the output tile to PNG/JPEG

For an unoptimized CMIP6 tile at zoom level 2, step 2 dominates (reading hundreds of chunks). With pyramids, step 2 becomes one or two chunk reads, and the remaining steps are fast.

### 6.2 Profiling Tools

- **TiTiler timing middleware**: Add request duration logging to the FastAPI app
- **fsspec request logging**: Monitor the number and size of HTTP requests per tile
- **Application Insights**: Azure-native APM for the Web App, tracking latency distributions and dependency calls
- **Development Seed tile-benchmarking**: Open-source benchmark suite used to compare raw Zarr vs. pyramid tile generation times on CMIP6 data

> **OPEN QUESTION 12**: What target latency should we set for tile requests? Sub-200ms p95 is typical for production tile servers. Is this achievable with pyramids + caching on the current Azure Web App SKU, or does the platform need to scale up compute? What does the latency distribution look like for cold-start (first request, no cache) vs. warm (dataset cached, tile cached at CDN)?

---

## Summary: Priority-Ordered Optimization Roadmap

1. **Multiscale pyramids via ndpyramid** (Layer 2) — Highest impact. Eliminates the fundamental O(n) problem for low-zoom tiles. Implement first.
2. **Spatial chunk alignment** (Layer 1.1) — Ensure base Zarr uses 256×256 spatial chunks with single-timestep time chunks. May already be partially done.
3. **Consolidated metadata** (Layer 1.3) — Quick win. Single flag in the ETL write step.
4. **CDN tile caching via Cloudflare** (Layer 3.3) — Eliminates repeat computation for popular tiles. Leverages existing architecture.
5. **Dataset object caching** (Layer 3.2) — Reduces per-request metadata overhead.
6. **Compression codec optimization** (Layer 1.2) — Switch to Blosc/LZ4 if not already using it.
7. **TiTiler worker/thread tuning** (Layer 3.4) — Profile-driven, do after baseline measurements.
8. **Web Mercator pre-reprojection** (Layer 2.5) — Only if profiling shows reprojection is a significant bottleneck.

---

## Open Questions Index

| # | Question | Layers Affected | Key Tension |
|---|---|---|---|
| 1 | Chunk strategy for coarse-resolution models | L1 | Consistency vs. per-dataset optimization |
| 2 | LZ4 vs. Zstd codec selection | L1 | Decompression speed vs. compression ratio |
| 3 | Zarr v2 vs. v3 format | L1, L2 | Stability vs. future-proofing |
| 4 | Fixed vs. dynamic pyramid level count | L2, L3 | Simplicity vs. storage efficiency |
| 5 | Per-variable resampling method | L2 | Scientific accuracy vs. operational simplicity |
| 6 | CRS: 4326 storage + runtime reproject vs. 3857 pre-reproject | L2, L5 | Simplicity vs. tile serving speed |
| 7 | Custom PyramidReader vs. middleware routing | L3 | Encapsulation vs. flexibility |
| 8 | Dataset cache sizing and memory footprint | L3 | Cache hit rate vs. memory budget |
| 9 | Cache invalidation strategy | L3, L5 | Freshness vs. complexity |
| 10 | Worker × thread configuration | L3 | Isolation vs. resource sharing |
| 11 | Dual-store vs. single-pyramid canonical store | L5 | Clarity vs. efficiency |
| 12 | Target tile latency and SKU requirements | L4, L6 | Performance vs. cost |

---

## Key Dependencies and Links

- **ndpyramid**: https://github.com/carbonplan/ndpyramid — Pyramid generation library
- **titiler-xarray**: https://github.com/developmentseed/titiler — Tile server
- **Zarr multiscales convention**: https://github.com/zarr-conventions/multiscales — Emerging standard for pyramid metadata
- **xarray DataTree**: https://xarray.dev/blog/datatree — Hierarchical data structure for multi-group Zarr
- **rechunker**: https://rechunker.readthedocs.io — Zarr rechunking utility
- **Development Seed tile benchmarks**: https://developmentseed.org/tile-benchmarking — CMIP6 pyramid vs. raw Zarr benchmarks