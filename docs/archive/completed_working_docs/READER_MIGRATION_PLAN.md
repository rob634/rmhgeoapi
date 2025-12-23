# Reader App Migration Plan (F1.2)

**Created**: 19 DEC 2025
**Updated**: 19 DEC 2025
**Purpose**: Migrate raster_api and xarray_api modules from rmhazuregeoapi to rmhogcapi
**Target**: rmhogcapi Function App (Reader API)

---

## Overview

This migration moves read-only query endpoints from the ETL platform (rmhazuregeoapi) to the dedicated reader platform (rmhogcapi). The goal is clean separation:

- **rmhazuregeoapi**: ETL operations (ingest, process, transform)
- **rmhogcapi**: Read-only queries (OGC Features, STAC, raster ops, xarray ops)

### Key Design Decisions (19 DEC 2025)

| Decision | Rationale |
|----------|-----------|
| **All sync, no async** | Queries are ≤30 seconds; async adds complexity without benefit |
| **Config-independent** | Service clients use env vars, not config imports - enables zero-modification copy |
| **Portable code** | Same files run in both rmhazuregeoapi and rmhogcapi |
| **Explicit errors** | Missing env vars raise `ValueError` immediately |

---

## Architecture After Migration

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          rmhogcapi                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ OGC Features│  │  STAC API   │  │ Raster API  │  │ xarray API  │    │
│  │ (existing)  │  │ (existing)  │  │   (NEW)     │  │   (NEW)     │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         │                │                │                │            │
│         v                v                v                v            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    services/                                      │   │
│  │  ┌──────────────┐ ┌────────────────┐ ┌────────────────┐          │   │
│  │  │ stac_client  │ │ titiler_client │ │ xarray_reader  │          │   │
│  │  │   (SYNC)     │ │    (SYNC)      │ │    (SYNC)      │          │   │
│  │  └──────────────┘ └────────────────┘ └────────────────┘          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  Environment Variables:                                                  │
│  - STAC_API_BASE_URL    (self-referential to /api/stac)                 │
│  - TITILER_BASE_URL     (external TiTiler instance)                     │
│  - AZURE_STORAGE_ACCOUNT (for Zarr blob access)                         │
│  - POSTGIS_HOST, etc.   (for OGC Features - existing)                   │
│  - AZURE_CLIENT_ID      (managed identity - existing)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Source Files to Copy

All source files are located at: `/Users/robertharrison/python_builds/rmhgeoapi/`

### 1. Service Clients (SYNC, config-independent)

| Source Path | Description | Env Var Required |
|-------------|-------------|------------------|
| `services/stac_client.py` | Internal STAC API client with TTL cache | `STAC_API_BASE_URL` |
| `services/titiler_client.py` | TiTiler HTTP client for raster ops | `TITILER_BASE_URL` |
| `services/xarray_reader.py` | Direct Zarr reader using xarray | `AZURE_STORAGE_ACCOUNT` |

**Key change from original**: These files **no longer import from config**. They accept constructor params or fall back to environment variables.

### 2. Raster API Module

| Source Path | Description |
|-------------|-------------|
| `raster_api/__init__.py` | Module init, exports `get_raster_triggers` |
| `raster_api/config.py` | TiTiler configuration (named locations, defaults) |
| `raster_api/service.py` | Business logic - STAC lookup + TiTiler proxy (SYNC) |
| `raster_api/triggers.py` | HTTP handlers for raster endpoints (SYNC) |

**Endpoints provided**:
- `GET /api/raster/extract/{collection}/{item}` - Extract bbox as image
- `GET /api/raster/point/{collection}/{item}` - Point value query
- `POST /api/raster/clip/{collection}/{item}` - Clip to GeoJSON geometry
- `GET /api/raster/preview/{collection}/{item}` - Quick preview image

### 3. xarray API Module

| Source Path | Description |
|-------------|-------------|
| `xarray_api/__init__.py` | Module init, exports `get_xarray_triggers` |
| `xarray_api/config.py` | xarray configuration |
| `xarray_api/output.py` | Response formatters (GeoTIFF, PNG) |
| `xarray_api/service.py` | Business logic - direct Zarr access (SYNC) |
| `xarray_api/triggers.py` | HTTP handlers for xarray endpoints (SYNC) |

**Endpoints provided**:
- `GET /api/xarray/point/{collection}/{item}` - Time-series at a point
- `GET /api/xarray/statistics/{collection}/{item}` - Regional stats over time
- `GET /api/xarray/aggregate/{collection}/{item}` - Temporal aggregation export

---

## Implementation Steps

### Step 1: Copy Modules

```bash
# In rmhogcapi project directory
cd /Users/robertharrison/rmhogcapi

# Create services directory if needed
mkdir -p services

# Copy service clients (SYNC versions)
cp /Users/robertharrison/python_builds/rmhgeoapi/services/stac_client.py services/
cp /Users/robertharrison/python_builds/rmhgeoapi/services/titiler_client.py services/
cp /Users/robertharrison/python_builds/rmhgeoapi/services/xarray_reader.py services/

# Copy raster_api module
cp -r /Users/robertharrison/python_builds/rmhgeoapi/raster_api .

# Copy xarray_api module
cp -r /Users/robertharrison/python_builds/rmhgeoapi/xarray_api .
```

### Step 2: Update requirements.txt

Dependencies have been added to `/Users/robertharrison/rmhogcapi/requirements.txt`.

### Step 3: Configure Environment Variables

Add to Azure Function App settings or `local.settings.json`:

```json
{
  "Values": {
    "STAC_API_BASE_URL": "https://rmhogcapi-....azurewebsites.net/api/stac",
    "TITILER_BASE_URL": "https://your-titiler-instance.com",
    "AZURE_STORAGE_ACCOUNT": "rmhazuregeo",

    "POSTGIS_HOST": "rmhpgflex.postgres.database.azure.com",
    "POSTGIS_PORT": "5432",
    "POSTGIS_DATABASE": "geopgflex",
    "POSTGIS_USER": "rmhpgflexadmin",
    "USE_MANAGED_IDENTITY": "true",
    "AZURE_CLIENT_ID": "<your-managed-identity-client-id>"
  }
}
```

### Step 4: Register Routes in function_app.py

Add to rmhogcapi's `function_app.py`:

```python
# =============================================================================
# RASTER API ENDPOINTS (NEW - 19 DEC 2025)
# =============================================================================
try:
    from raster_api.triggers import (
        RasterExtractTrigger,
        RasterPointTrigger,
        RasterClipTrigger,
        RasterPreviewTrigger
    )

    _raster_extract = RasterExtractTrigger()
    _raster_point = RasterPointTrigger()
    _raster_clip = RasterClipTrigger()
    _raster_preview = RasterPreviewTrigger()

    @app.route(route="raster/extract/{collection}/{item}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def raster_extract(req: func.HttpRequest) -> func.HttpResponse:
        return _raster_extract.handle(req)

    @app.route(route="raster/point/{collection}/{item}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def raster_point(req: func.HttpRequest) -> func.HttpResponse:
        return _raster_point.handle(req)

    @app.route(route="raster/clip/{collection}/{item}", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
    def raster_clip(req: func.HttpRequest) -> func.HttpResponse:
        return _raster_clip.handle(req)

    @app.route(route="raster/preview/{collection}/{item}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def raster_preview(req: func.HttpRequest) -> func.HttpResponse:
        return _raster_preview.handle(req)

    logger.info("✅ Raster API registered (4 endpoints)")
except ImportError as e:
    logger.warning(f"⚠️ Raster API not available: {e}")

# =============================================================================
# XARRAY API ENDPOINTS (NEW - 19 DEC 2025)
# =============================================================================
try:
    from xarray_api.triggers import (
        XarrayPointTrigger,
        XarrayStatisticsTrigger,
        XarrayAggregateTrigger
    )

    _xarray_point = XarrayPointTrigger()
    _xarray_stats = XarrayStatisticsTrigger()
    _xarray_agg = XarrayAggregateTrigger()

    @app.route(route="xarray/point/{collection}/{item}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def xarray_point(req: func.HttpRequest) -> func.HttpResponse:
        return _xarray_point.handle(req)

    @app.route(route="xarray/statistics/{collection}/{item}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def xarray_statistics(req: func.HttpRequest) -> func.HttpResponse:
        return _xarray_stats.handle(req)

    @app.route(route="xarray/aggregate/{collection}/{item}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
    def xarray_aggregate(req: func.HttpRequest) -> func.HttpResponse:
        return _xarray_agg.handle(req)

    logger.info("✅ xarray API registered (3 endpoints)")
except ImportError as e:
    logger.warning(f"⚠️ xarray API not available: {e}")
```

**Note**: All handlers are **sync** - no `async def`, no `await`.

### Step 5: Deploy and Validate

```bash
# Deploy to Azure
func azure functionapp publish rmhogcapi --python --build remote

# Test endpoints
# 1. Raster point query
curl "https://rmhogcapi.../api/raster/point/{collection}/{item}?location=-77.0,38.9"

# 2. xarray time-series
curl "https://rmhogcapi.../api/xarray/point/{collection}/{item}?location=-77.0,38.9"

# 3. Raster preview
curl "https://rmhogcapi.../api/raster/preview/{collection}/{item}"
```

---

## Key Dependencies Between Files

```
raster_api/
├── __init__.py
├── config.py
├── service.py ────────────┬──> services/stac_client.py (env: STAC_API_BASE_URL)
│                          └──> services/titiler_client.py (env: TITILER_BASE_URL)
└── triggers.py ──────────────> raster_api/service.py

xarray_api/
├── __init__.py
├── config.py
├── output.py
├── service.py ────────────┬──> services/stac_client.py (env: STAC_API_BASE_URL)
│                          └──> services/xarray_reader.py (env: AZURE_STORAGE_ACCOUNT)
└── triggers.py ──────────────> xarray_api/service.py

services/
├── stac_client.py ───────────> httpx (NO config import)
├── titiler_client.py ────────> httpx (NO config import)
└── xarray_reader.py ─────────> xarray, zarr, fsspec (NO config import)
```

---

## Service Client Details

### STACClient (SYNC)

```python
from services.stac_client import STACClient

# Option 1: Explicit base_url
client = STACClient(base_url="https://rmhogcapi.../api/stac")

# Option 2: From STAC_API_BASE_URL env var
client = STACClient()

# Get item (SYNC - no await)
response = client.get_item("collection", "item_id")
if response.success:
    zarr_url = response.item.get_asset_url("data")

client.close()
```

Features:
- TTL Cache: 5-minute for items, 1-hour for collections
- `httpx.Client` (sync, not async)
- `STACItem` dataclass with `get_asset_url()`, `is_zarr()`, `is_cog()` methods

### TiTilerClient (SYNC)

```python
from services.titiler_client import TiTilerClient

# Option 1: Explicit base_url
client = TiTilerClient(base_url="https://titiler.../")

# Option 2: From TITILER_BASE_URL env var
client = TiTilerClient()

# Get COG info (SYNC - no await)
response = client.get_cog_info("https://storage.../file.tif")

client.close()
```

Endpoints:
- COG: `/cog/info`, `/cog/point`, `/cog/bbox`, `/cog/preview`, `/cog/feature`
- xarray: `/xarray/info`, `/xarray/point`, `/xarray/bbox`, `/xarray/preview`

### XarrayReader (SYNC)

```python
from services.xarray_reader import XarrayReader

# Option 1: Explicit storage_account
reader = XarrayReader(storage_account="rmhazuregeo")

# Option 2: From AZURE_STORAGE_ACCOUNT env var
reader = XarrayReader()

# Get time-series (SYNC)
result = reader.get_point_timeseries(
    zarr_url="https://storage.../data.zarr",
    variable="tasmax",
    lon=-77.0,
    lat=38.9
)

reader.close()
```

Features:
- Lazy imports (xarray/zarr loaded on first use)
- Dataset caching (reuse open datasets)
- Azure Blob support via fsspec/adlfs

---

## Acceptance Criteria

| Story | Acceptance Criteria |
|-------|---------------------|
| S1.2.1: Copy service clients | `services/stac_client.py`, `titiler_client.py`, `xarray_reader.py` exist |
| S1.2.2: Copy raster_api module | Module exists, imports succeed without config errors |
| S1.2.3: Copy xarray_api module | Module exists, imports succeed without config errors |
| S1.2.4: Update requirements.txt | httpx, xarray, zarr, fsspec, adlfs added |
| S1.2.5: Configure env vars | STAC_API_BASE_URL, TITILER_BASE_URL, AZURE_STORAGE_ACCOUNT set |
| S1.2.6: Register routes | 7 new routes visible in Azure Functions list |
| S1.2.7: Deploy and validate | All endpoints return correct responses |

---

## What's NOT Needed from rmhazuregeoapi

| Module | Reason |
|--------|--------|
| `config/` | Service clients use env vars directly |
| `jobs/` | ETL only - not used by reader |
| `repository/` | PostGIS access via existing rmhogcapi infrastructure |
| `vector_api/` | Uses OGC Features (already in rmhogcapi) |
| `platform_api/` | DDH integration - ETL only |
| `analytics/` | DuckDB exports - ETL only |

---

## Notes

- **All code is synchronous** - no async/await, no asyncio event loops
- **STAC client caches are global** - shared across requests in same process
- **xarray reader caches datasets** - memory-efficient for repeated queries
- **TiTiler requires separate deployment** - this plan doesn't include TiTiler setup
- **Code runs in both apps** - same files work in rmhazuregeoapi (dev) and rmhogcapi (prod)

---

**Document Location**: `/Users/robertharrison/python_builds/rmhgeoapi/READER_MIGRATION_PLAN.md`
