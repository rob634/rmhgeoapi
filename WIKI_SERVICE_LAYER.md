# Service Layer API Documentation

**Purpose:** Comprehensive documentation for the data access APIs that serve finished geospatial products.

**Last Updated:** 21 DEC 2025

---

## Overview

The Service Layer provides read-only query access to processed geospatial data through standardized APIs. Each component can be deployed independently or grouped in a single Azure Function App, except TiTiler which requires Docker.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Service Layer (Read-Only Query APIs)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  /api/stac  │  │/api/features│  │ /api/raster │  │ /api/xarray │        │
│  │  (Catalog)  │  │  (Vectors)  │  │  (TiTiler)  │  │   (Zarr)    │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
└─────────┼────────────────┼────────────────┼────────────────┼───────────────┘
          │                │                │                │
          ▼                ▼                ▼                ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
    │  pgSTAC  │     │ PostGIS  │     │ TiTiler  │     │  Zarr    │
    │(metadata)│     │ (vector) │     │ (tiles)  │     │ (direct) │
    └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

### Component Summary

| Component | Purpose | Backend | Deployment |
|-----------|---------|---------|------------|
| **STAC API** | Raster metadata catalog | pgSTAC (PostgreSQL) | Azure Functions |
| **OGC Features** | Vector data access | PostGIS | Azure Functions |
| **Raster API** | Tile serving, extraction | TiTiler (Docker) | Docker / App Service |
| **xarray API** | Time-series, Zarr access | Direct xarray | Azure Functions |

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

## 3. Raster API - TiTiler (`/api/raster/...`)

### Overview

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

## 4. xarray API (`/api/xarray/...`)

### Overview

Direct Zarr access via xarray for time-series analysis and temporal aggregations. More efficient than multiple TiTiler requests when querying many time steps.

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

## 7. Deployment Architecture

### Option A: Combined Function App

All service layer components (except TiTiler) in a single Azure Function App:

```
rmhazuregeoapi/
├── stac_api/        # /api/stac/*
├── ogc_features/    # /api/features/*
├── raster_api/      # /api/raster/* (proxies to TiTiler)
├── xarray_api/      # /api/xarray/*
└── web_interfaces/  # /api/interface/*
```

### Option B: Separate Function Apps

For better scaling and isolation:

```
rmhogcstac/          # Read-only query layer
├── stac_api/
├── ogc_features/
├── raster_api/
└── xarray_api/

rmhazuregeoapi/      # ETL and admin
├── jobs/
├── dbadmin/
└── platform_api/
```

### TiTiler (Always Separate)

TiTiler requires Docker and runs separately:

```bash
# Azure App Service for Containers
az webapp create --resource-group $RG --plan $PLAN --name $NAME \
  --deployment-container-image-name ghcr.io/developmentseed/titiler-pgstac:latest

# Environment variables
az webapp config appsettings set --name $NAME --resource-group $RG \
  --settings DATABASE_URL="postgresql://..." TITILER_API_CACHECONTROL="public, max-age=3600"
```

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

### TiTiler (COGs)
```bash
GET  /cog/tiles/{z}/{x}/{y}.png?url=...      # Map tiles
GET  /cog/info?url=...                       # Metadata
GET  /cog/point/{lon},{lat}?url=...          # Point query
```

### TiTiler (Zarr)
```bash
GET  /xarray/variables?url=...&decode_times=false
GET  /xarray/info?url=...&variable=...&decode_times=false
GET  /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png
     ?url=...&variable=...&decode_times=false&bidx=1
     &colormap_name=viridis&rescale=250,320
GET  /xarray/point/{lon},{lat}?url=...&variable=...&decode_times=false&bidx=1
```

### xarray API (Direct Zarr)
```bash
GET  /api/xarray/point/{collection}/{item}
     ?location={lon},{lat}&start_time=...&end_time=...
GET  /api/xarray/statistics/{collection}/{item}
     ?bbox=...&start_time=...&end_time=...
GET  /api/xarray/aggregate/{collection}/{item}
     ?bbox=...&temporal_agg=mean&format=tif
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs_claude/ZARR_TITILER_LESSONS.md` | Detailed zarr/TiTiler integration notes |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | Overall system architecture |
| `ogc_features/README.md` | OGC Features implementation details |
| `stac_api/README.md` | STAC API implementation details |
| `titiler/README.md` | TiTiler deployment guide |
| `SERVICE-LAYER-API-DESIGN.md` | API design document |

---

**Author:** Claude + Robert Harrison
**Last Updated:** 21 DEC 2025
