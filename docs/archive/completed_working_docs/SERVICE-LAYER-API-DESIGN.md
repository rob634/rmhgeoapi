# Service Layer API Design

**Purpose:** Design document for implementing convenience wrapper endpoints and time-series extraction in a separate Azure Function App service layer.

**Date:** December 18, 2025

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              rmhogcstac (Read-Only Query Layer Function App)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  /api/stac  │  │/api/features│  │ /api/raster │  │ /api/xarray │        │
│  │  (existing) │  │  (existing) │  │  (TiTiler)  │  │   (Zarr)    │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
└─────────┼────────────────┼────────────────┼────────────────┼───────────────┘
          │                │                │                │
          ▼                ▼                ▼                ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
    │  pgSTAC  │     │ PostGIS  │     │ TiTiler  │     │  Zarr    │
    │(metadata)│     │ (vector) │     │ (tiles)  │     │ (direct) │
    └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

### Service Responsibilities

| Service | Responsibility |
|---------|---------------|
| **TiTiler** | Raster tile serving, single-band extraction, point queries |
| **xarray** | Direct Zarr access for time-series and temporal aggregation |
| **OGC Features** | Vector data from PostGIS tables |
| **STAC API** | Metadata catalog, search, asset discovery |

---

## Part B: Raster Convenience API (`/api/raster/...`)

### Problem Statement

TiTiler's raw endpoints require:
- Full blob storage URLs
- Knowledge of `bidx`, `decode_times`, `variable` parameters
- URL construction for each request

### Solution: Simplified Endpoints

The service layer provides intuitive endpoints that:
1. Look up asset URLs from STAC catalog
2. Apply sensible defaults
3. Handle parameter translation
4. Support friendly identifiers instead of raw URLs

**Route Prefix:** `/api/raster/` - clearly indicates raster operations via TiTiler

---

### Proposed Endpoints

#### 1. Extract by STAC Item ID

```
GET /api/raster/extract/{collection}/{item_id}
    ?bbox={minx},{miny},{maxx},{maxy}
    &format=tif|png|npy
    &asset=visual|data|zarr
    &time_index=1
    &colormap=turbo
    &rescale=auto
```

**Example:**
```bash
# Instead of:
curl "https://titiler.../xarray/bbox/-125,25,-65,50.tif?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1"

# Use:
curl "https://api.../raster/extract/cmip6/tasmax-ssp585?bbox=-125,25,-65,50&format=tif&time_index=1"
```

**Implementation:**
```python
@app.route("/api/raster/extract/{collection}/{item_id}")
async def extract_by_item(
    collection: str,
    item_id: str,
    bbox: str,
    format: str = "tif",
    asset: str = "data",
    time_index: int = 1,
    colormap: str = None,
    rescale: str = None
):
    # 1. Look up STAC item
    item = await stac_client.get_item(collection, item_id)

    # 2. Get asset URL
    asset_url = item["assets"][asset]["href"]
    media_type = item["assets"][asset].get("type", "")

    # 3. Determine if COG or Zarr
    is_zarr = "zarr" in media_type.lower()

    # 4. Build TiTiler URL
    if is_zarr:
        variable = item["properties"].get("cube:variables", {}).keys()[0]
        titiler_url = f"{TITILER_BASE}/xarray/bbox/{bbox}.{format}"
        params = {
            "url": asset_url,
            "variable": variable,
            "decode_times": "false",
            "bidx": time_index
        }
    else:
        titiler_url = f"{TITILER_BASE}/cog/bbox/{bbox}.{format}"
        params = {"url": asset_url}

    if colormap:
        params["colormap_name"] = colormap
    if rescale:
        params["rescale"] = rescale

    # 5. Proxy request to TiTiler
    response = await http_client.get(titiler_url, params=params)
    return Response(content=response.content, media_type=response.headers["content-type"])
```

---

#### 2. Point Query by Location Name

```
GET /api/raster/point/{collection}/{item_id}
    ?location={name}|{lon},{lat}
    &time_index=1
```

**Example:**
```bash
# Query temperature at a named location
curl "https://api.../raster/point/cmip6/tasmax-ssp585?location=washington_dc&time_index=1"

# Or by coordinates
curl "https://api.../raster/point/cmip6/tasmax-ssp585?location=-77.0,38.9&time_index=1"
```

**Implementation:**
```python
# Named locations from PostGIS or config
NAMED_LOCATIONS = {
    "washington_dc": (-77.0369, 38.9072),
    "new_york": (-74.006, 40.7128),
    "los_angeles": (-118.2437, 34.0522),
    # Or query from OGC Features service
}

@app.route("/api/raster/point/{collection}/{item_id}")
async def point_query(
    collection: str,
    item_id: str,
    location: str,
    time_index: int = 1
):
    # 1. Resolve location
    if "," in location:
        lon, lat = map(float, location.split(","))
    else:
        lon, lat = await resolve_location(location)  # From PostGIS or lookup

    # 2. Get STAC item and build TiTiler request
    item = await stac_client.get_item(collection, item_id)
    asset_url = item["assets"]["data"]["href"]

    # 3. Query TiTiler
    response = await http_client.get(
        f"{TITILER_BASE}/xarray/point/{lon},{lat}",
        params={
            "url": asset_url,
            "variable": get_variable(item),
            "decode_times": "false",
            "bidx": time_index
        }
    )

    # 4. Enrich response
    result = response.json()
    result["location_name"] = location
    result["item_id"] = item_id
    result["timestamp"] = get_timestamp_for_bidx(item, time_index)

    return result
```

---

#### 3. Clip by Admin Boundary

```
GET /api/raster/clip/{collection}/{item_id}
    ?boundary_type=country|state|county
    &boundary_id={id}
    &format=tif|png
    &time_index=1
```

**Example:**
```bash
# Extract temperature for Virginia
curl "https://api.../raster/clip/cmip6/tasmax-ssp585?boundary_type=state&boundary_id=VA&format=tif&time_index=1"
```

**Implementation:**
```python
@app.route("/api/raster/clip/{collection}/{item_id}")
async def clip_by_boundary(
    collection: str,
    item_id: str,
    boundary_type: str,
    boundary_id: str,
    format: str = "tif",
    time_index: int = 1
):
    # 1. Get boundary geometry from OGC Features
    boundary = await ogc_client.get_feature(
        collection=f"admin_{boundary_type}",
        feature_id=boundary_id
    )
    geometry = boundary["geometry"]

    # 2. Get STAC item
    item = await stac_client.get_item(collection, item_id)
    asset_url = item["assets"]["data"]["href"]

    # 3. POST to TiTiler feature endpoint
    response = await http_client.post(
        f"{TITILER_BASE}/xarray/feature.{format}",
        params={
            "url": asset_url,
            "variable": get_variable(item),
            "decode_times": "false",
            "bidx": time_index,
            "max_size": 2048
        },
        json={
            "type": "Feature",
            "properties": {},
            "geometry": geometry
        }
    )

    return Response(content=response.content, media_type=f"image/{format}")
```

---

## Part D: xarray Direct Access API (`/api/xarray/...`)

### Problem Statement

TiTiler's `bidx` parameter selects a single time step. For time-series analysis, users need:
- Values across multiple time steps
- Temporal aggregations (mean, max, min over time)
- Time-range extractions

### Solution: Direct xarray Access

Instead of N HTTP requests to TiTiler, the service layer:
1. Looks up Zarr URL from STAC catalog
2. Opens Zarr directly with xarray (via fsspec/adlfs)
3. Performs efficient chunked reads for time slices
4. Returns aggregated results

**Route Prefix:** `/api/xarray/` - clearly indicates direct Zarr/xarray operations

---

### Proposed Endpoints

#### 1. Point Time-Series Query

```
GET /api/xarray/point/{collection}/{item_id}
    ?location={lon},{lat}
    &start_time={iso_date}
    &end_time={iso_date}
    &aggregation=none|daily|monthly|yearly
```

**Example:**
```bash
# Get daily max temperature for 2015 at Washington DC
curl "https://api.../xarray/point/cmip6/tasmax-ssp585?location=-77,38.9&start_time=2015-01-01&end_time=2015-12-31"
```

**Response:**
```json
{
  "location": [-77, 38.9],
  "item_id": "tasmax-ssp585",
  "variable": "tasmax",
  "unit": "K",
  "time_series": [
    {"time": "2015-01-01", "value": 279.8, "bidx": 1},
    {"time": "2015-01-02", "value": 281.2, "bidx": 2},
    {"time": "2015-01-03", "value": 278.5, "bidx": 3},
    // ... 365 values
  ],
  "statistics": {
    "min": 265.2,
    "max": 312.4,
    "mean": 289.1,
    "std": 12.3
  }
}
```

**Implementation:**
```python
import xarray as xr
import fsspec

@app.route("/api/xarray/point/{collection}/{item_id}")
async def xarray_point(
    collection: str,
    item_id: str,
    location: str,
    start_time: str,
    end_time: str,
    aggregation: str = "none"
):
    lon, lat = map(float, location.split(","))

    # 1. Get STAC item and Zarr URL
    item = await stac_client.get_item(collection, item_id)
    zarr_url = item["assets"]["data"]["href"]
    variable = get_variable(item)

    # 2. Open Zarr directly with xarray (single connection, efficient chunked read)
    store = fsspec.get_mapper(zarr_url, account_name="rmhazuregeo")
    ds = xr.open_zarr(store, consolidated=True)

    # 3. Select point and time range in ONE operation
    da = ds[variable].sel(
        lat=lat, lon=lon, method="nearest"
    ).sel(
        time=slice(start_time, end_time)
    )

    # 4. Load data (only fetches needed chunks)
    values = da.values
    times = da.time.values

    # 5. Build results
    results = [
        {"time": str(t)[:10], "value": float(v)}
        for t, v in zip(times, values)
    ]

    # 6. Apply aggregation if requested
    if aggregation != "none":
        results = aggregate_timeseries(results, aggregation)

    # 7. Calculate statistics
    stats = {
        "min": float(da.min()),
        "max": float(da.max()),
        "mean": float(da.mean()),
        "std": float(da.std())
    }

    return {
        "location": [lon, lat],
        "item_id": item_id,
        "variable": variable,
        "unit": ds[variable].attrs.get("units"),
        "time_series": results,
        "statistics": stats
    }
```

---

#### 2. Regional Statistics Over Time

```
GET /api/xarray/statistics/{collection}/{item_id}
    ?bbox={minx},{miny},{maxx},{maxy}
    &start_time={iso_date}
    &end_time={iso_date}
    &stat=mean|max|min|sum
```

**Example:**
```bash
# Get mean temperature statistics over US for each month of 2015
curl "https://api.../xarray/statistics/cmip6/tasmax-ssp585?bbox=-125,25,-65,50&start_time=2015-01-01&end_time=2015-12-31&aggregation=monthly"
```

**Response:**
```json
{
  "bbox": [-125, 25, -65, 50],
  "item_id": "tasmax-ssp585",
  "variable": "tasmax",
  "aggregation": "monthly",
  "time_series": [
    {
      "period": "2015-01",
      "spatial_mean": 275.3,
      "spatial_min": 245.2,
      "spatial_max": 298.4,
      "valid_pixels": 12400
    },
    {
      "period": "2015-02",
      "spatial_mean": 278.1,
      // ...
    }
    // ... 12 months
  ]
}
```

---

#### 3. Temporal Aggregation Export

```
GET /api/xarray/aggregate/{collection}/{item_id}
    ?bbox={minx},{miny},{maxx},{maxy}
    &start_time={iso_date}
    &end_time={iso_date}
    &temporal_agg=mean|max|min
    &format=tif|png
```

**Example:**
```bash
# Export mean annual temperature as GeoTIFF
curl "https://api.../xarray/aggregate/cmip6/tasmax-ssp585?bbox=-125,25,-65,50&start_time=2015-01-01&end_time=2015-12-31&temporal_agg=mean&format=tif" -o annual_mean_2015.tif
```

**Implementation:**
```python
@app.route("/api/xarray/aggregate/{collection}/{item_id}")
async def xarray_aggregate(
    collection: str,
    item_id: str,
    bbox: str,
    start_time: str,
    end_time: str,
    temporal_agg: str,  # mean, max, min, sum
    format: str = "tif"
):
    minx, miny, maxx, maxy = map(float, bbox.split(","))

    # 1. Get STAC item and open Zarr
    item = await stac_client.get_item(collection, item_id)
    zarr_url = item["assets"]["data"]["href"]
    variable = get_variable(item)

    store = fsspec.get_mapper(zarr_url, account_name="rmhazuregeo")
    ds = xr.open_zarr(store, consolidated=True)

    # 2. Select bbox and time range in ONE operation
    da = ds[variable].sel(
        lat=slice(maxy, miny),  # Note: lat often decreasing
        lon=slice(minx, maxx),
        time=slice(start_time, end_time)
    )

    # 3. Aggregate over time dimension (efficient - xarray handles chunking)
    if temporal_agg == "mean":
        result = da.mean(dim="time")
    elif temporal_agg == "max":
        result = da.max(dim="time")
    elif temporal_agg == "min":
        result = da.min(dim="time")
    elif temporal_agg == "sum":
        result = da.sum(dim="time")

    # 4. Load result (only now does computation happen)
    result_array = result.values

    # 5. Convert to output format
    if format == "npy":
        return Response(content=result_array.tobytes(), media_type="application/octet-stream")
    elif format == "tif":
        tif_bytes = create_geotiff(result_array, bbox, result.lat.values, result.lon.values)
        return Response(content=tif_bytes, media_type="image/tiff")
    elif format == "png":
        png_bytes = render_png(result_array, colormap="turbo")
        return Response(content=png_bytes, media_type="image/png")
```

---

## Implementation Recommendations

### Azure Function App Structure

```
service-layer-api/
├── function_app.py           # Main FastAPI/Functions entry
├── routers/
│   ├── extract.py            # Convenience extraction endpoints
│   ├── timeseries.py         # Time-series endpoints
│   └── batch.py              # Batch processing endpoints
├── services/
│   ├── titiler_client.py     # TiTiler HTTP client
│   ├── stac_client.py        # STAC API client
│   ├── ogc_client.py         # OGC Features client
│   └── cache.py              # Redis/memory caching
├── utils/
│   ├── time_utils.py         # Date/bidx conversion
│   ├── geo_utils.py          # Geometry helpers
│   └── aggregation.py        # Temporal aggregation
├── requirements.txt
└── host.json
```

### Key Dependencies

```txt
# requirements.txt
azure-functions
fastapi
httpx[http2]           # Async HTTP client for TiTiler

# xarray ecosystem (Part D)
xarray
zarr
fsspec                 # Abstract filesystem
adlfs                  # Azure Blob backend for fsspec
aiohttp                # Async support for fsspec

# Output formats
numpy
rasterio               # GeoTIFF creation
pillow                 # PNG rendering

# Caching (optional)
redis
```

### Performance Considerations

| Concern | Solution |
|---------|----------|
| Many TiTiler requests | Parallel async requests with batching |
| Large time ranges | Chunk into batches, stream results |
| Repeated queries | Redis cache for STAC lookups and results |
| Memory for aggregation | Stream arrays, don't load all at once |
| Rate limiting | Configurable concurrency limit to TiTiler |

### Caching Strategy

```python
# Cache STAC items (change rarely)
@cache(ttl=3600)
async def get_stac_item(collection, item_id):
    return await stac_client.get_item(collection, item_id)

# Cache time coordinates (static per item)
@cache(ttl=86400)
async def get_time_coordinates(item_id):
    return await fetch_time_coords(item_id)

# Don't cache extraction results (too large, unique queries)
```

---

## API Summary

### Raster API (Part B) - TiTiler Proxy

| Endpoint | Purpose |
|----------|---------|
| `GET /api/raster/extract/{collection}/{item}` | Extract bbox by STAC item ID |
| `GET /api/raster/point/{collection}/{item}` | Single point query (one time slice) |
| `GET /api/raster/clip/{collection}/{item}` | Clip to admin boundary |
| `GET /api/raster/preview/{collection}/{item}` | Quick preview image |

### xarray API (Part D) - Direct Zarr Access

| Endpoint | Purpose |
|----------|---------|
| `GET /api/xarray/point/{collection}/{item}` | Time-series at a point |
| `GET /api/xarray/statistics/{collection}/{item}` | Regional stats over time |
| `GET /api/xarray/aggregate/{collection}/{item}` | Temporal aggregation export |
| `POST /api/xarray/batch` | Batch queries |

### Existing APIs (Already in rmhogcstac)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/stac/...` | STAC catalog (pgSTAC) |
| `GET /api/features/...` | OGC Features (PostGIS) |

---

## Implementation Plan

**Strategy:** Build in `rmhazuregeoapi` first (this repo), validate, then migrate to `rmhogcstac`.

---

### Phase 1: Foundation (Clients + Infrastructure)

| Step | Task | Files |
|------|------|-------|
| 1.1 | Add xarray dependencies to requirements.txt | `requirements.txt` |
| 1.2 | Create TiTiler HTTP client service | `services/titiler_client.py` |
| 1.3 | Create internal STAC client (queries own /api/stac) | `services/stac_client.py` |
| 1.4 | Create xarray/Zarr reader service | `services/xarray_reader.py` |
| 1.5 | Add TITILER_BASE_URL to config if not present | `config/settings.py` |

**Deliverable:** Three service classes that can be imported by triggers.

---

### Phase 2: Raster API (`/api/raster/...`)

| Step | Task | Endpoint |
|------|------|----------|
| 2.1 | Create raster router module | `raster_api/__init__.py` |
| 2.2 | Implement extract endpoint | `GET /api/raster/extract/{collection}/{item}` |
| 2.3 | Implement point endpoint | `GET /api/raster/point/{collection}/{item}` |
| 2.4 | Implement clip endpoint | `GET /api/raster/clip/{collection}/{item}` |
| 2.5 | Implement preview endpoint | `GET /api/raster/preview/{collection}/{item}` |
| 2.6 | Register routes in function_app.py | `function_app.py` |
| 2.7 | Test locally with existing STAC items | Manual testing |

**Deliverable:** Four working `/api/raster/` endpoints proxying TiTiler.

---

### Phase 3: xarray API (`/api/xarray/...`)

| Step | Task | Endpoint |
|------|------|----------|
| 3.1 | Create xarray router module | `xarray_api/__init__.py` |
| 3.2 | Implement point time-series endpoint | `GET /api/xarray/point/{collection}/{item}` |
| 3.3 | Implement statistics endpoint | `GET /api/xarray/statistics/{collection}/{item}` |
| 3.4 | Implement aggregate endpoint | `GET /api/xarray/aggregate/{collection}/{item}` |
| 3.5 | Add GeoTIFF/PNG output helpers | `xarray_api/output.py` |
| 3.6 | Register routes in function_app.py | `function_app.py` |
| 3.7 | Test locally with Zarr files | Manual testing |

**Deliverable:** Three working `/api/xarray/` endpoints with direct Zarr access.

---

### Phase 4: Polish + Deploy

| Step | Task |
|------|------|
| 4.1 | Add error handling (missing items, invalid params) |
| 4.2 | Add request validation (bbox format, date ranges) |
| 4.3 | Add caching for STAC lookups (in-memory or Redis) |
| 4.4 | Deploy to rmhazuregeoapi and test |
| 4.5 | Document API in README or separate doc |

**Deliverable:** Production-ready endpoints in rmhazuregeoapi.

---

### Phase 5: Migration to rmhogcstac

| Step | Task |
|------|------|
| 5.1 | Copy `raster_api/` and `xarray_api/` modules |
| 5.2 | Copy service clients (`titiler_client.py`, `xarray_reader.py`) |
| 5.3 | Update requirements.txt in rmhogcstac |
| 5.4 | Register routes in rmhogcstac function_app.py |
| 5.5 | Remove from rmhazuregeoapi (optional, or keep as fallback) |
| 5.6 | Deploy rmhogcstac and validate |

**Deliverable:** Clean separation - read-only queries in rmhogcstac, ETL in rmhazuregeoapi.

---

### File Structure (New)

```
rmhazuregeoapi/
├── services/
│   ├── titiler_client.py      # Phase 1.2
│   ├── stac_client.py         # Phase 1.3
│   └── xarray_reader.py       # Phase 1.4
├── raster_api/                 # Phase 2
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   └── triggers.py
├── xarray_api/                 # Phase 3
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   ├── output.py
│   └── triggers.py
└── function_app.py            # Register new routes
```

---

**Author:** Claude + Robert Harrison
**Last Updated:** 18 DEC 2025
