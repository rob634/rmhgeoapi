# Reader App Migration Plan (F1.2)

**Created**: 19 DEC 2025
**Purpose**: Migrate raster_api and xarray_api modules from rmhazuregeoapi to rmhogcstac
**Target**: rmhogcstac Function App (Reader API)

---

## Overview

This migration moves read-only query endpoints from the ETL platform (rmhazuregeoapi) to the dedicated reader platform (rmhogcstac). The goal is clean separation:

- **rmhazuregeoapi**: ETL operations (ingest, process, transform)
- **rmhogcstac**: Read-only queries (OGC Features, STAC, raster ops, xarray ops)

---

## Source Files to Copy

All source files are located at: `/Users/robertharrison/python_builds/rmhgeoapi/`

### 1. Raster API Module

| Source Path | Description |
|-------------|-------------|
| `raster_api/__init__.py` | Module init, exports `get_raster_triggers` |
| `raster_api/config.py` | TiTiler configuration (TITILER_BASE_URL) |
| `raster_api/service.py` | Business logic - STAC lookup + TiTiler proxy |
| `raster_api/triggers.py` | HTTP handlers for raster endpoints |

**Endpoints provided**:
- `GET /api/raster/extract/{collection}/{item}` - Extract bbox as image
- `GET /api/raster/point/{collection}/{item}` - Point value query
- `GET /api/raster/clip/{collection}/{item}` - Clip to admin boundary
- `GET /api/raster/preview/{collection}/{item}` - Quick preview image

### 2. xarray API Module

| Source Path | Description |
|-------------|-------------|
| `xarray_api/__init__.py` | Module init, exports `get_xarray_triggers` |
| `xarray_api/config.py` | xarray configuration |
| `xarray_api/output.py` | Response formatters |
| `xarray_api/service.py` | Business logic - direct Zarr access |
| `xarray_api/triggers.py` | HTTP handlers for xarray endpoints |

**Endpoints provided**:
- `GET /api/xarray/point/{collection}/{item}` - Time-series at a point
- `GET /api/xarray/statistics/{collection}/{item}` - Regional stats over time
- `GET /api/xarray/aggregate/{collection}/{item}` - Temporal aggregation export

### 3. Service Clients (copy to `services/` folder)

| Source Path | Description | Dependencies |
|-------------|-------------|--------------|
| `services/stac_client.py` | Internal STAC API client with TTL cache | httpx |
| `services/titiler_client.py` | TiTiler HTTP client for raster ops | httpx |
| `services/xarray_reader.py` | Direct Zarr reader using xarray | xarray, zarr, fsspec, numpy |

### 4. Config Module (may need to adapt)

| Source Path | Description |
|-------------|-------------|
| `config/__init__.py` | Configuration loader |
| `config/app_config.py` | AppConfig dataclass with service URLs |

**Required config values**:
- `STAC_API_BASE_URL` - Internal STAC API (e.g., https://rmhogcstac.../stac)
- `TITILER_BASE_URL` - TiTiler server URL

---

## Implementation Steps

### Step 1: Copy Modules

```bash
# In rmhogcstac project directory
mkdir -p raster_api xarray_api services

# Copy raster_api module
cp -r /path/to/rmhgeoapi/raster_api/* raster_api/

# Copy xarray_api module
cp -r /path/to/rmhgeoapi/xarray_api/* xarray_api/

# Copy service clients
cp /path/to/rmhgeoapi/services/stac_client.py services/
cp /path/to/rmhgeoapi/services/titiler_client.py services/
cp /path/to/rmhgeoapi/services/xarray_reader.py services/
```

### Step 2: Update requirements.txt

Add to rmhogcstac requirements.txt:

```
# HTTP client
httpx>=0.25.0

# xarray/Zarr support
xarray>=2024.1.0
zarr>=2.16.0
fsspec>=2024.2.0
adlfs>=2024.2.0  # Azure Data Lake filesystem
h5netcdf>=1.3.0
numpy>=1.24.0
```

### Step 3: Adapt Config Imports

The source files use `from config import get_config`. You have two options:

**Option A: Copy config module**
```bash
mkdir -p config
cp /path/to/rmhgeoapi/config/__init__.py config/
cp /path/to/rmhgeoapi/config/app_config.py config/
```

**Option B: Adapt to existing config pattern**

If rmhogcstac has its own config pattern, update imports in:
- `services/stac_client.py` line 30: `from config import get_config`
- `services/titiler_client.py` line 27: `from config import get_config`

The config needs to provide:
```python
@dataclass
class AppConfig:
    stac_api_base_url: str  # e.g., "https://rmhogcstac.../stac"
    titiler_base_url: str   # e.g., "https://titiler.../api"
```

### Step 4: Register Routes in function_app.py

Add to rmhogcstac's `function_app.py`:

```python
import azure.functions as func
from raster_api import get_raster_triggers
from xarray_api import get_xarray_triggers

# Register Raster API routes
for trigger in get_raster_triggers():
    @app.route(
        route=trigger['route'],
        methods=trigger['methods'],
        auth_level=func.AuthLevel.ANONYMOUS
    )
    def _make_handler(handler=trigger['handler']):
        def wrapped(req: func.HttpRequest) -> func.HttpResponse:
            return handler(req)
        return wrapped
    _make_handler.__name__ = f"raster_{trigger['route'].replace('/', '_')}"

# Register xarray API routes
for trigger in get_xarray_triggers():
    @app.route(
        route=trigger['route'],
        methods=trigger['methods'],
        auth_level=func.AuthLevel.ANONYMOUS
    )
    def _make_handler(handler=trigger['handler']):
        def wrapped(req: func.HttpRequest) -> func.HttpResponse:
            return handler(req)
        return wrapped
    _make_handler.__name__ = f"xarray_{trigger['route'].replace('/', '_')}"
```

**Alternative (explicit registration):**

```python
from raster_api.triggers import (
    RasterExtractTrigger,
    RasterPointTrigger,
    RasterClipTrigger,
    RasterPreviewTrigger
)
from xarray_api.triggers import (
    XarrayPointTrigger,
    XarrayStatisticsTrigger,
    XarrayAggregateTrigger
)

# Raster endpoints
_raster_extract = RasterExtractTrigger()
_raster_point = RasterPointTrigger()
_raster_clip = RasterClipTrigger()
_raster_preview = RasterPreviewTrigger()

@app.route(route="raster/extract/{collection}/{item}", methods=["GET"])
async def raster_extract(req: func.HttpRequest) -> func.HttpResponse:
    return await _raster_extract.handle(req)

@app.route(route="raster/point/{collection}/{item}", methods=["GET"])
async def raster_point(req: func.HttpRequest) -> func.HttpResponse:
    return await _raster_point.handle(req)

@app.route(route="raster/clip/{collection}/{item}", methods=["GET"])
async def raster_clip(req: func.HttpRequest) -> func.HttpResponse:
    return await _raster_clip.handle(req)

@app.route(route="raster/preview/{collection}/{item}", methods=["GET"])
async def raster_preview(req: func.HttpRequest) -> func.HttpResponse:
    return await _raster_preview.handle(req)

# xarray endpoints
_xarray_point = XarrayPointTrigger()
_xarray_stats = XarrayStatisticsTrigger()
_xarray_agg = XarrayAggregateTrigger()

@app.route(route="xarray/point/{collection}/{item}", methods=["GET"])
async def xarray_point(req: func.HttpRequest) -> func.HttpResponse:
    return await _xarray_point.handle(req)

@app.route(route="xarray/statistics/{collection}/{item}", methods=["GET"])
async def xarray_statistics(req: func.HttpRequest) -> func.HttpResponse:
    return await _xarray_stats.handle(req)

@app.route(route="xarray/aggregate/{collection}/{item}", methods=["GET"])
async def xarray_aggregate(req: func.HttpRequest) -> func.HttpResponse:
    return await _xarray_agg.handle(req)
```

### Step 5: Configure Environment Variables

Add to Azure Function App settings or local.settings.json:

```json
{
  "Values": {
    "STAC_API_BASE_URL": "https://rmhogcstac-....azurewebsites.net/stac",
    "TITILER_BASE_URL": "https://your-titiler-instance.com",
    "AZURE_STORAGE_ACCOUNT": "rmhazuregeo"
  }
}
```

### Step 6: Deploy and Validate

```bash
# Deploy to Azure
func azure functionapp publish rmhogcstac --python --build remote

# Test endpoints
# 1. Raster point query
curl "https://rmhogcstac.../api/raster/point/{collection}/{item}?lon=-77.0&lat=38.9"

# 2. xarray time-series
curl "https://rmhogcstac.../api/xarray/point/{collection}/{item}?lon=-77.0&lat=38.9&variable=tasmax"

# 3. Raster preview
curl "https://rmhogcstac.../api/raster/preview/{collection}/{item}"
```

---

## Key Dependencies Between Files

```
raster_api/
├── __init__.py
├── config.py
├── service.py ────────────┬──> services/stac_client.py
│                          └──> services/titiler_client.py
└── triggers.py ──────────────> raster_api/service.py

xarray_api/
├── __init__.py
├── config.py
├── output.py
├── service.py ────────────┬──> services/stac_client.py
│                          └──> services/xarray_reader.py
└── triggers.py ──────────────> xarray_api/service.py

services/
├── stac_client.py ───────────> config (get_config)
├── titiler_client.py ────────> config (get_config)
└── xarray_reader.py ─────────> xarray, zarr, fsspec
```

---

## STAC Client Details

The `stac_client.py` provides:

1. **TTL Cache**: 5-minute TTL for items, 1-hour TTL for collections
2. **STACItem dataclass**: Parsed item with asset URL extraction
3. **Async HTTP**: Uses httpx for non-blocking requests

Key classes:
- `TTLCache` - Thread-safe cache with auto-expiry
- `STACItem` - Parsed item with `get_asset_url()`, `is_zarr()`, `is_cog()` methods
- `STACClient` - Async client with `get_item()`, `get_collection()`, `list_items()`

---

## TiTiler Client Details

The `titiler_client.py` provides:

1. **COG endpoints**: `/cog/info`, `/cog/point`, `/cog/bbox`, `/cog/preview`, `/cog/feature`
2. **xarray endpoints**: `/xarray/info`, `/xarray/point`, `/xarray/bbox`, `/xarray/preview`
3. **Async HTTP**: Uses httpx with configurable timeout

---

## xarray Reader Details

The `xarray_reader.py` provides:

1. **Point time-series**: Extract values at lon/lat over time range
2. **Regional statistics**: Spatial stats per time period over bbox
3. **Temporal aggregation**: Mean/max/min/sum over time range

Key features:
- Lazy imports (xarray/zarr only loaded when needed)
- Dataset caching (reuse open datasets)
- Azure Blob support via fsspec/adlfs

---

## Acceptance Criteria

| Story | Acceptance Criteria |
|-------|---------------------|
| S1.2.1: Copy raster_api module | Module exists in rmhogcstac, imports succeed |
| S1.2.2: Copy xarray_api module | Module exists in rmhogcstac, imports succeed |
| S1.2.3: Copy service clients | stac_client, titiler_client, xarray_reader in services/ |
| S1.2.4: Update requirements.txt | xarray, zarr, httpx, fsspec added |
| S1.2.5: Register routes | Routes visible in Azure Functions list |
| S1.2.6: Deploy and validate | All endpoints return correct responses |

---

## Notes

- The modules use async/await - ensure rmhogcstac supports async handlers
- STAC client caches are global (shared across requests in same process)
- xarray reader caches open datasets (memory-efficient for repeated queries)
- TiTiler client requires a running TiTiler instance (separate deployment)

---

**Document Location**: `/Users/robertharrison/python_builds/rmhgeoapi/READER_MIGRATION_PLAN.md`
