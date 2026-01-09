# Service Layer API Documentation

**Purpose:** Comprehensive documentation for the data access APIs that serve finished geospatial products.

**Last Updated:** 09 JAN 2026

---

## Overview

The Service Layer provides read-only query access to processed geospatial data through standardized APIs. These APIs are **completely independent from the ETL layer** (CoreMachine, jobs, Service Bus) and can be deployed as standalone Function Apps.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Service Layer (Read-Only Query APIs)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  /api/stac  │  │/api/features│  │ /api/raster │  │ /api/xarray │        │
│  │  (Catalog)  │  │  (Vectors)  │  │  (Queries)  │  │  (Queries)  │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
└─────────┼────────────────┼────────────────┼────────────────┼───────────────┘
          │                │                │                │
          ▼                ▼                ▼                ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
    │  pgSTAC  │     │ PostGIS  │     │   COGs   │     │   Zarr   │
    │(metadata)│     │ (vector) │     │ (Blob)   │     │  (Blob)  │
    └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

### API Categories

| Category | APIs | Response Time | Deployment |
|----------|------|---------------|------------|
| **Catalog** | STAC API | < 1s | Azure Functions |
| **Vector** | OGC Features | < 5s | Azure Functions |
| **Raster Tiles** | TiTiler (COG/Zarr) | < 1s | Docker (always separate) |
| **Raster Queries** | Pixel math, zonal stats | < 60s | Azure Functions |
| **Xarray Queries** | Time-series, aggregations | < 60s | Azure Functions |

**Synchronous Query Definition**: Any operation completing in < 60 seconds. This generous timeout accommodates complex multi-band raster calculations and time-series aggregations while staying well within Azure Functions limits.

### Component Summary

| Component | Purpose | Backend | Deployment |
|-----------|---------|---------|------------|
| **STAC API** | Raster metadata catalog | pgSTAC (PostgreSQL) | Azure Functions |
| **OGC Features** | Vector data access | PostGIS | Azure Functions |
| **Raster Tiles** | Dynamic tile serving | TiTiler (Docker) | Docker / App Service |
| **Raster Queries** | Pixel math, zonal stats | COGs via rasterio | Azure Functions |
| **Xarray Queries** | Time-series, aggregations | Zarr via xarray | Azure Functions |

---

## Standalone Deployment Architecture

### Current State: Development Monolith

Currently, all APIs are developed in a single codebase (`rmhgeoapi`) for convenience:

```
rmhazuregeoapi (Single Function App)
├── ETL LAYER (CoreMachine, Jobs, Service Bus)
│   ├── jobs/                    # Job definitions
│   ├── services/                # Task handlers
│   ├── core/machine.py          # CoreMachine orchestrator
│   └── triggers/                # Service Bus triggers
│
└── SERVICE LAYER (Read-Only APIs) ← Can be extracted
    ├── stac_api/                # STAC API
    ├── ogc_features/            # OGC Features API
    ├── raster_api/              # Raster queries (future)
    └── xarray_api/              # Xarray queries (future)
```

### Future State: Standalone Service Layer App

The Service Layer can be deployed as a **completely separate Function App** for:
- **Independent scaling**: Scale read APIs separately from ETL workloads
- **Isolated deployments**: Deploy API fixes without touching ETL
- **Security boundaries**: Different auth policies for public vs internal APIs
- **Cost optimization**: Right-size each app for its workload

```
Azure API Management (geospatial.rmh.org)
├─→ rmh-service-layer (Standalone Function App)
│   ├── /api/stac/*       → STAC API
│   ├── /api/features/*   → OGC Features API
│   ├── /api/raster/*     → Raster Queries
│   └── /api/xarray/*     → Xarray Queries
│
├─→ rmh-titiler (Docker Container App)
│   └── /cog/*, /xarray/* → TiTiler tile serving
│
└─→ rmhazuregeoapi (ETL Function App)
    ├── /api/platform/*   → Platform API (DDH integration)
    └── /api/jobs/*       → Job submission/status

All connect to: PostgreSQL (shared database, read-only for Service Layer)
```

### File Mapping: Standalone Service Layer App

When extracting the Service Layer to a standalone Function App, copy these files:

```
rmh-service-layer/                    # New standalone Function App
├── function_app.py                   # NEW: Azure Functions entry point
├── host.json                         # NEW: Function App config
├── requirements.txt                  # NEW: Subset of dependencies
│
├── stac_api/                         # COPY: Entire module
│   ├── __init__.py
│   ├── triggers.py                   # HTTP endpoints
│   ├── service.py                    # Business logic
│   └── infrastructure.py             # pgSTAC queries
│
├── ogc_features/                     # COPY: Entire module (~2,600 lines)
│   ├── __init__.py
│   ├── config.py                     # OGC-specific config
│   ├── models.py                     # Pydantic models
│   ├── repository.py                 # PostGIS queries
│   ├── service.py                    # Business logic
│   └── triggers.py                   # HTTP endpoints
│
├── raster_api/                       # COPY: When implemented
│   └── ...
│
├── xarray_api/                       # COPY: When implemented
│   └── ...
│
├── core/                             # COPY: Shared models only
│   └── models/
│       ├── __init__.py
│       ├── unified_metadata.py       # VectorMetadata model (F7.8)
│       └── external_refs.py          # DatasetRef model (F7.8)
│
├── config/                           # COPY: Database config only
│   ├── __init__.py
│   └── database.py                   # Connection string builder
│
└── web_interfaces/                   # OPTIONAL: Interactive viewers
    └── ...
```

### Files NOT Needed in Service Layer App

These are ETL-only and should NOT be copied:

```
DO NOT COPY:
├── jobs/                    # Job definitions (ETL only)
├── services/                # Task handlers (ETL only)
├── core/machine.py          # CoreMachine (ETL only)
├── core/state_manager.py    # Job state management (ETL only)
├── triggers/trigger_*.py    # Service Bus triggers (ETL only)
├── platform/                # Platform API (ETL only)
└── docker/                  # GDAL worker (ETL only)
```

### Database Access Pattern

The Service Layer is **read-only** and accesses only these schemas:

| Schema | Tables | Access |
|--------|--------|--------|
| `geo` | `table_metadata`, vector tables | SELECT only |
| `pgstac` | `collections`, `items`, `searches` | SELECT only |
| `h3` | H3 grid tables | SELECT only |

The Service Layer does **NOT** access:
- `app` schema (jobs, tasks) - ETL only
- Service Bus queues - ETL only
- Bronze storage account - ETL only

### Shared Model: VectorMetadata (F7.8)

The `VectorMetadata` model (`core/models/unified_metadata.py`) provides a single source of truth for dataset metadata with conversion methods:

```python
from core.models.unified_metadata import VectorMetadata

# Repository returns VectorMetadata model
metadata = repo.get_vector_metadata("admin_boundaries")

# Convert to OGC Features response
ogc_collection = metadata.to_ogc_collection(base_url="/api/features")

# Convert to STAC response
stac_collection = metadata.to_stac_collection(base_url="/api/stac")
```

This model is used by both OGC Features and STAC APIs, ensuring consistent metadata across both standards.

---

## 1. STAC API (`/api/stac/...`)

### Overview

Implements **STAC API v1.0.0** specification for managing raster metadata and asset discovery. Uses pgSTAC as the backend for efficient spatial-temporal queries.

### Architecture

```
HTTP Request → STAC Triggers → Service Layer → pgSTAC
                                     ↓
                              Pure STAC JSON Response
```

The implementation follows a three-layer design:
- **Triggers Layer** (`stac_api/triggers.py`): HTTP endpoints, parameter extraction
- **Service Layer** (`stac_api/service.py`): Business logic, response formatting
- **Infrastructure Layer** (`stac_api/infrastructure.py`): pgSTAC SQL queries

### Core Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/stac` | Landing page with API links |
| `GET /api/stac/conformance` | Supported conformance classes |
| `GET /api/stac/collections` | List all collections |
| `GET /api/stac/collections/{id}` | Collection metadata |
| `GET /api/stac/collections/{id}/items` | List items in collection |
| `GET /api/stac/collections/{id}/items/{item_id}` | Single item metadata |
| `POST /api/stac/search` | Cross-collection search |

### Query Parameters

```bash
# Search items by bbox
curl "/api/stac/collections/my-cogs/items?bbox=-70.7,-56.3,-70.6,-56.2"

# Search by datetime
curl "/api/stac/collections/my-cogs/items?datetime=2024-01-01/2024-12-31"

# Full-text search
curl -X POST "/api/stac/search" \
  -H "Content-Type: application/json" \
  -d '{"collections": ["my-cogs"], "bbox": [-180,-90,180,90], "limit": 10}'
```

### Key Features

- **Pure STAC JSON**: No extra fields - compliant with standard STAC clients
- **pgSTAC Backend**: Efficient PostGIS-based queries for millions of items
- **Cross-Collection Search**: Single query across multiple collections
- **Pagination**: Standard `limit` and `next` token support

### STAC Nuclear Button (Dev/Test Only)

```bash
# Clear all STAC items and collections
curl -X POST "/api/stac/nuke?confirm=yes&mode=all"
```

---

## 2. OGC Features API (`/api/features/...`)

### Overview

Implements **OGC API - Features Core 1.0** for serving vector data from PostGIS. The implementation is ~2,600 lines and can be deployed as a standalone module.

### Architecture

```
HTTP Request → Features Triggers → Service Layer → Repository Layer → PostGIS
                                          ↓
                                    GeoJSON Response
```

Three-layer design:
- **Triggers Layer** (`ogc_features/triggers.py`): HTTP endpoints
- **Service Layer** (`ogc_features/service.py`): Query building, response formatting
- **Repository Layer** (`ogc_features/repository.py`): SQL generation, geometry handling

### Core Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/features` | Landing page |
| `GET /api/features/conformance` | Conformance declaration |
| `GET /api/features/collections` | List all collections |
| `GET /api/features/collections/{id}` | Collection metadata |
| `GET /api/features/collections/{id}/items` | Query features |
| `GET /api/features/collections/{id}/items/{fid}` | Single feature |

### Query Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `bbox` | Bounding box filter | `bbox=-70.7,-56.3,-70.6,-56.2` |
| `datetime` | Temporal filter | `datetime=2024-01-01/2024-12-31` |
| `limit` | Max features returned | `limit=100` |
| `offset` | Pagination offset | `offset=100` |
| `sortby` | Sort field (+/- prefix) | `sortby=-created` |
| `simplify` | Geometry simplification (m) | `simplify=100` |
| `properties` | Attribute filter | `properties=status:active` |

### Examples

```bash
# Query by bounding box
curl "/api/features/collections/buildings/items?bbox=-70.7,-56.3,-70.6,-56.2&limit=5"

# Temporal filter
curl "/api/features/collections/observations/items?datetime=2024-06-01/2024-06-30"

# Attribute filter with sorting
curl "/api/features/collections/parcels/items?properties=type:residential&sortby=-area&limit=10"

# Geometry simplification (reduce data size)
curl "/api/features/collections/boundaries/items?simplify=500"
```

### Key Features

- **Spatial Filtering**: Efficient bbox queries via PostGIS indexes
- **Temporal Queries**: Date range filtering on temporal columns
- **Attribute Filtering**: Filter by any property field
- **Geometry Optimization**: Server-side simplification reduces transfer size
- **Sorting**: Ascending (+) or descending (-) on any field
- **Pagination**: Standard limit/offset with next links

### Interactive Map

Access the web viewer at: `/api/interface/map`

---

## 3. Raster APIs

The raster stack has two components:
1. **TiTiler** (Docker) - Dynamic tile serving for maps
2. **Raster Queries** (Azure Functions) - Synchronous pixel math and zonal statistics

### 3a. TiTiler - Dynamic Tile Serving (`/cog/...`, `/xarray/...`)

TiTiler provides dynamic raster tile serving for Cloud Optimized GeoTIFFs (COGs) and Zarr datasets. It runs as a **Docker container** and cannot be deployed as Azure Functions.

### Deployment Options

| Option | URL | Use Case |
|--------|-----|----------|
| Azure App Service | `https://yourapp.azurewebsites.net` | Production |
| Azure Container Instances | Dynamic | Testing |
| Local Docker | `http://localhost:8000` | Development |

### Docker Setup

```bash
# Development environment
docker run -p 8000:8000 \
  -e TITILER_API_CACHECONTROL="public, max-age=3600" \
  ghcr.io/developmentseed/titiler-pgstac:latest

# With pgSTAC connection
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql://user:pass@host:5432/db" \
  -e TITILER_API_CACHECONTROL="public, max-age=3600" \
  ghcr.io/developmentseed/titiler-pgstac:latest
```

### COG Endpoints (TiTiler-pgSTAC)

| Endpoint | Purpose |
|----------|---------|
| `/cog/tiles/{z}/{x}/{y}.png` | Get map tiles |
| `/cog/tilejson.json` | TileJSON metadata |
| `/cog/info` | COG metadata |
| `/cog/statistics` | Band statistics |
| `/cog/preview.png` | Quick preview image |
| `/cog/point/{lon},{lat}` | Point value query |
| `/cog/bbox/{minx},{miny},{maxx},{maxy}.tif` | Extract bbox |

### COG Examples

```bash
# Get tile
curl "https://titiler/cog/tiles/10/512/384.png?url=https://storage.blob.core.windows.net/cogs/my-image.tif"

# Get info
curl "https://titiler/cog/info?url=https://storage.blob.core.windows.net/cogs/my-image.tif"

# Point query
curl "https://titiler/cog/point/-77.0,38.9?url=https://storage.blob.core.windows.net/cogs/my-image.tif"
```

### Zarr Endpoints (TiTiler-xarray)

| Endpoint | Purpose |
|----------|---------|
| `/xarray/variables` | List Zarr variables |
| `/xarray/info` | Variable metadata |
| `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png` | Map tiles |
| `/xarray/point/{lon},{lat}` | Point query |
| `/xarray/WebMercatorQuad/map.html` | Interactive viewer |

### Zarr Examples

```bash
# List variables
curl "https://titiler/xarray/variables?url=https://storage.blob.core.windows.net/zarr/era5.zarr&decode_times=false"

# Get info for variable
curl "https://titiler/xarray/info?url=https://storage.blob.core.windows.net/zarr/era5.zarr&variable=air_temperature_at_2_metres&decode_times=false"

# Get tile (temperature visualization)
curl "https://titiler/xarray/tiles/WebMercatorQuad/3/4/2@1x.png\
?url=https://storage.blob.core.windows.net/zarr/era5.zarr\
&variable=air_temperature_at_2_metres\
&decode_times=false\
&bidx=1\
&colormap_name=viridis\
&rescale=250,320"

# Point query
curl "https://titiler/xarray/point/-77.0,38.9\
?url=https://storage.blob.core.windows.net/zarr/era5.zarr\
&variable=air_temperature_at_2_metres\
&decode_times=false\
&bidx=1"

# Interactive map
open "https://titiler/xarray/WebMercatorQuad/map.html\
?url=https://storage.blob.core.windows.net/zarr/era5.zarr\
&variable=air_temperature_at_2_metres\
&decode_times=false\
&bidx=1\
&colormap_name=viridis\
&rescale=250,320"
```

### Critical TiTiler-xarray Parameters

| Parameter | Purpose | Required |
|-----------|---------|----------|
| `url` | Zarr store URL | Yes |
| `variable` | Data variable name | Yes (for /info, /tiles, /point) |
| `decode_times=false` | Handle non-standard calendars | Yes (for climate data) |
| `bidx=N` | Band/time index (1-based) | Yes (for temporal data) |
| `colormap_name` | Color palette | Optional |
| `rescale=min,max` | Value range for colormap | Recommended |

---

### 3b. Raster Queries API (`/api/raster/...`)

**Status**: Under Consideration

Synchronous raster query operations that complete within 60 seconds. Unlike TiTiler (which serves tiles for maps), the Raster Queries API performs **analytical operations** on COG data.

### Use Cases

| Operation | Description | Example |
|-----------|-------------|---------|
| **Point Query** | Get pixel value(s) at coordinates | "What's the elevation at this point?" |
| **Zonal Statistics** | Stats within a polygon | "Average flood depth in this district" |
| **Band Math** | Calculate derived indices | "NDVI = (NIR - Red) / (NIR + Red)" |
| **Transect** | Values along a line | "Elevation profile along this route" |
| **Multi-Band Extract** | Extract all bands at location | "Get all 12 FATHOM scenarios at this point" |

### Proposed Endpoints

```bash
# Point query - single location, all bands
GET /api/raster/point/{collection}/{item}
    ?lon=-77.0&lat=38.9
    &bands=1,2,3           # Optional: specific bands

# Zonal statistics - stats within polygon
POST /api/raster/zonal/{collection}/{item}
    Content-Type: application/json
    {
      "geometry": {"type": "Polygon", "coordinates": [...]},
      "stats": ["min", "max", "mean", "std", "count"]
    }

# Band math - calculated index
GET /api/raster/bandmath/{collection}/{item}
    ?expression=(b4-b3)/(b4+b3)    # NDVI formula
    &bbox=-77.1,38.8,-76.9,39.0
    &format=tif|png

# Transect - values along a line
POST /api/raster/transect/{collection}/{item}
    Content-Type: application/json
    {
      "geometry": {"type": "LineString", "coordinates": [...]},
      "resolution": 30,     # Sample every 30m
      "bands": [1]
    }
```

### Response Format

```json
{
  "collection": "fathom-flood",
  "item": "rwanda-pluvial-100yr",
  "operation": "point",
  "location": [-77.0, 38.9],
  "crs": "EPSG:4326",
  "values": {
    "band_1": 2.34,
    "band_2": 1.89,
    "band_3": 0.45
  },
  "unit": "meters",
  "processing_time_ms": 145
}
```

### Performance Constraints

- **Timeout**: 60 seconds max (Azure Functions limit)
- **Area limit**: ~10,000 km² for zonal stats (adjustable)
- **Concurrent requests**: Scales with Function App instances
- **COG requirement**: Data must be Cloud Optimized GeoTIFF

### Architecture

```
HTTP Request → Raster Triggers → Raster Service → COG Reader (rasterio)
                                        ↓
                                 JSON/GeoTIFF Response
```

The Raster Queries API uses `rasterio` with HTTP range requests to read only the required pixels from COGs in blob storage - no full file download required.

---

## 4. Xarray Queries API (`/api/xarray/...`)

**Status**: Under Consideration

### Overview

Synchronous Zarr access via xarray for time-series analysis and temporal aggregations. Operations complete within 60 seconds. More efficient than multiple TiTiler requests when querying many timesteps or performing aggregations.

### When to Use xarray vs TiTiler

| Use Case | Recommended API |
|----------|-----------------|
| Single tile/image | TiTiler `/xarray/tiles` |
| Single point, single time | TiTiler `/xarray/point` |
| Point time-series (many times) | xarray `/api/xarray/point` |
| Temporal aggregation (mean, max) | xarray `/api/xarray/aggregate` |
| Regional statistics over time | xarray `/api/xarray/statistics` |

### Proposed Endpoints

```
GET /api/xarray/point/{collection}/{item}
    ?location={lon},{lat}
    &start_time={iso_date}
    &end_time={iso_date}
    &aggregation=none|daily|monthly|yearly

GET /api/xarray/statistics/{collection}/{item}
    ?bbox={minx},{miny},{maxx},{maxy}
    &start_time={iso_date}
    &end_time={iso_date}
    &stat=mean|max|min|sum

GET /api/xarray/aggregate/{collection}/{item}
    ?bbox={minx},{miny},{maxx},{maxy}
    &start_time={iso_date}
    &end_time={iso_date}
    &temporal_agg=mean|max|min
    &format=tif|png
```

### Example: Point Time-Series

```bash
# Get daily temperature for 2015 at Washington DC
curl "https://api.../xarray/point/era5/temperature\
?location=-77.0,38.9\
&start_time=2020-01-01\
&end_time=2020-01-31"
```

Response:
```json
{
  "location": [-77.0, 38.9],
  "item_id": "temperature",
  "variable": "air_temperature_at_2_metres",
  "unit": "K",
  "time_series": [
    {"time": "2020-01-01", "value": 279.8},
    {"time": "2020-01-02", "value": 281.2},
    ...
  ],
  "statistics": {
    "min": 265.2,
    "max": 285.4,
    "mean": 275.1
  }
}
```

### Service Implementation

The xarray API uses the `XArrayReaderService` in `services/xarray_reader.py`:

```python
import xarray as xr

class XArrayReaderService:
    def open_zarr(self, url: str, storage_options: dict = None) -> xr.Dataset:
        """Open a Zarr store with xarray."""
        return xr.open_zarr(
            url,
            storage_options=storage_options or {},
            consolidated=True
        )

    def point_query(self, ds: xr.Dataset, lon: float, lat: float,
                    variable: str, time_slice: slice = None) -> dict:
        """Extract time-series at a point."""
        da = ds[variable].sel(lat=lat, lon=lon, method="nearest")
        if time_slice:
            da = da.sel(time=time_slice)
        return {
            "values": da.values.tolist(),
            "times": [str(t)[:10] for t in da.time.values]
        }
```

---

## 5. TiTiler + Zarr Integration Lessons

### Summary

Successfully integrated ERA5 global climate data (~27GB, 9 variables, 744 hourly timesteps, 0.25° resolution) with TiTiler-xarray. Key lessons learned during integration.

### Issue 1: Zarr 3.x API Breaking Changes

**Problem:** `zarr.storage.FSStore` was removed in zarr 3.x.

```
AttributeError: module 'zarr.storage' has no attribute 'FSStore'
```

**Solution:** Use xarray's `storage_options` parameter:

```python
# OLD (zarr 2.x)
store = zarr.storage.FSStore(path, fs=fs)
ds.to_zarr(store)

# NEW (zarr 3.x compatible)
storage_opts = {'account_name': ..., 'account_key': ...}
ds.to_zarr("abfs://container/path", storage_options=storage_opts)
```

### Issue 2: Chunk Alignment Errors

**Problem:** Source data has irregular chunks that don't align with target.

```
ValueError: Specified Zarr chunks encoding['chunks']=(372, 150, 150) would overlap multiple Dask chunks
```

**Solution:** Explicitly set encoding chunks as tuples:

```python
encoding = {}
for var in combined.data_vars:
    var_dims = combined[var].dims
    var_chunks = tuple(actual_chunks.get(dim, combined.dims[dim]) for dim in var_dims)
    encoding[var] = {'chunks': var_chunks}

combined.to_zarr(url, encoding=encoding, zarr_format=2)
```

### Issue 3: Blosc Codec Compatibility

**Problem:** zarr 3.x changed codec handling.

```
TypeError: Expected a BytesBytesCodec. Got <class 'numcodecs.blosc.Blosc'> instead.
```

**Solution:** Use `zarr_format=2` when writing:

```python
combined.to_zarr(url, zarr_format=2, consolidated=True)
```

### Issue 4: TiTiler Empty Variables

**Problem:** TiTiler-xarray returned empty variables despite valid .zmetadata.

```json
{"detail":"\"No variable named 'air_temperature'. Variables on the dataset include []\""}
```

**Root Cause:** Incomplete .zmetadata file from initial consolidation.

**Temporary Workaround:**
```
&reader_options={%22consolidated%22:false}
```
Note: Braces must NOT be URL-encoded, only quotes.

**Permanent Solution:** Re-consolidate metadata:

```python
ds = xr.open_zarr(url, storage_options=storage_opts, consolidated=False)
ds.to_zarr(url, storage_options=storage_opts, mode='a', consolidated=True, zarr_format=2)
```

### Issue 5: Azure Storage Public Access

**Problem:** TiTiler couldn't access private containers.

**Solution:**
```bash
# Enable at account level
az storage account update --name $ACCOUNT --allow-blob-public-access true

# Set container level
az storage container set-permission --name silver-cogs --account-name $ACCOUNT --public-access blob
```

### Issue 6: HNS vs Non-HNS Storage

**Finding:** Both Hierarchical Namespace (HNS) and non-HNS storage accounts work identically with TiTiler once:
1. Public access is enabled
2. Metadata is properly consolidated

### Zarr Dataset Checklist

When preparing new Zarr datasets for TiTiler:

1. [ ] Write with `zarr_format=2` for compatibility
2. [ ] Use `consolidated=True` and verify .zmetadata is complete
3. [ ] Enable public blob access on container
4. [ ] Test `/xarray/variables` endpoint first
5. [ ] Use `decode_times=false` for climate data
6. [ ] Use `bidx=1` for first timestep
7. [ ] Set appropriate `rescale` range for your data

### Data Copy Script

See `scripts/copy_era5_subset.py` for a working example that handles:
- Planetary Computer STAC authentication
- Azure storage account key retrieval
- Proper chunk encoding
- zarr v2 format compatibility
- Metadata consolidation

```bash
# Dry run to see what would be copied
python scripts/copy_era5_subset.py --month 2020-01 --dry-run

# Actual copy
python scripts/copy_era5_subset.py --month 2020-01
```

---

## 6. Web Interfaces

Interactive web viewers are available for exploring data:

| Interface | URL | Purpose |
|-----------|-----|---------|
| Gallery | `/api/interface/gallery` | Featured dataset showcase |
| Map Viewer | `/api/interface/map` | OGC Features + Leaflet |
| STAC Browser | `/api/interface/stac` | STAC catalog explorer |
| Zarr Viewer | `/api/interface/zarr` | ERA5 climate visualization |

---

## 7. Deployment Summary

> **Detailed Architecture**: See [Standalone Deployment Architecture](#standalone-deployment-architecture) section above for complete file mappings and extraction guide.

### Deployment Options

| Option | Description | When to Use |
|--------|-------------|-------------|
| **Combined** | All APIs in single Function App | Development, low traffic |
| **Standalone** | Service Layer as separate app | Production, independent scaling |
| **TiTiler** | Docker container (always separate) | Required for tile serving |

### Current Production Setup

```
rmhazuregeoapi (B3 Basic)
├── ETL Layer (CoreMachine, Jobs, Platform)
└── Service Layer (STAC, OGC Features, Raster, Xarray)

rmh-titiler (Docker - future)
└── TiTiler tile serving
```

### TiTiler Deployment (Docker Required)

```bash
# Azure App Service for Containers
az webapp create --resource-group $RG --plan $PLAN --name $NAME \
  --deployment-container-image-name ghcr.io/developmentseed/titiler-pgstac:latest

# Environment variables
az webapp config appsettings set --name $NAME --resource-group $RG \
  --settings DATABASE_URL="postgresql://..." TITILER_API_CACHECONTROL="public, max-age=3600"
```

### When to Split to Standalone

Split the Service Layer when:
- **Performance bottlenecks**: Read APIs impacted by ETL workloads
- **Deployment conflicts**: Need to deploy API fixes without touching ETL
- **Security requirements**: Different auth policies for public vs internal
- **Cost optimization**: Scale read-heavy APIs independently

---

## 8. API Quick Reference

### STAC API
```bash
GET  /api/stac                               # Landing page
GET  /api/stac/collections                   # List collections
GET  /api/stac/collections/{id}/items        # Query items
POST /api/stac/search                        # Cross-collection search
```

### OGC Features API
```bash
GET  /api/features                           # Landing page
GET  /api/features/collections               # List collections
GET  /api/features/collections/{id}/items    # Query features
     ?bbox=-70,-56,-69,-55
     &datetime=2024-01-01/2024-12-31
     &limit=100&sortby=-created
```

### TiTiler (COGs) - Tile Serving
```bash
GET  /cog/tiles/{z}/{x}/{y}.png?url=...      # Map tiles
GET  /cog/info?url=...                       # Metadata
GET  /cog/point/{lon},{lat}?url=...          # Point query
```

### TiTiler (Zarr) - Tile Serving
```bash
GET  /xarray/variables?url=...&decode_times=false
GET  /xarray/info?url=...&variable=...&decode_times=false
GET  /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png
     ?url=...&variable=...&decode_times=false&bidx=1
     &colormap_name=viridis&rescale=250,320
```

### Raster Queries API (Synchronous - Under Consideration)
```bash
GET  /api/raster/point/{collection}/{item}   # Point value query
     ?lon=-77.0&lat=38.9&bands=1,2,3
POST /api/raster/zonal/{collection}/{item}   # Zonal statistics
     {"geometry": {...}, "stats": ["mean", "max"]}
GET  /api/raster/bandmath/{collection}/{item} # Band math
     ?expression=(b4-b3)/(b4+b3)&bbox=...
POST /api/raster/transect/{collection}/{item} # Transect profile
     {"geometry": {"type": "LineString", ...}}
```

### Xarray Queries API (Synchronous - Under Consideration)
```bash
GET  /api/xarray/point/{collection}/{item}   # Time-series at point
     ?location={lon},{lat}&start_time=...&end_time=...
GET  /api/xarray/statistics/{collection}/{item} # Regional stats
     ?bbox=...&start_time=...&end_time=...
GET  /api/xarray/aggregate/{collection}/{item}  # Temporal aggregation
     ?bbox=...&temporal_agg=mean&format=tif
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs_claude/APIM_ARCHITECTURE.md` | Future microservices architecture with APIM |
| `docs_claude/ZARR_TITILER_LESSONS.md` | Detailed zarr/TiTiler integration notes |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | Overall system architecture |
| `docs_claude/OGC_FEATURES_METADATA_INTEGRATION.md` | Metadata integration guide |
| `ogc_features/README.md` | OGC Features implementation details |
| `stac_api/README.md` | STAC API implementation details |

---

**Author:** Claude + Robert Harrison
**Last Updated:** 09 JAN 2026
