# Service Layer API Documentation

> **Navigation**: [Technical Overview](TECHNICAL_OVERVIEW.md) | [Environment Variables](ENVIRONMENT_VARIABLES.md) | **Service Layer** | [Platform API](../api-reference/PLATFORM_API.md)

**Purpose:** Documentation for the unified Service Layer that serves finished geospatial products.

**Last Updated:** 01 FEB 2026

---

## Overview

The Service Layer provides read-only query access to processed geospatial data through standardized APIs. As of **V0.8**, the Service Layer is deployed as a **single Docker container** running three Dev Seed applications:

| Application | Provider | Purpose | Documentation |
|-------------|----------|---------|---------------|
| **TiTiler** | [Development Seed](https://developmentseed.org/) | Dynamic COG/Zarr tile serving | [TiTiler Docs](https://developmentseed.org/titiler/) |
| **TiPG** | [Development Seed](https://developmentseed.org/) | OGC Features API + MVT tiles | [TiPG Docs](https://developmentseed.org/tipg/) |
| **stac-fastapi** | STAC Community | STAC API for raster catalog | [stac-fastapi Docs](https://stac-utils.github.io/stac-fastapi/) |

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Service Layer Docker App (Unified Container)               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      FastAPI Application                              │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │  │
│  │  │  STAC API   │  │    TiPG     │  │   TiTiler   │  │  TiTiler   │  │  │
│  │  │  /stac/*    │  │ /features/* │  │   /cog/*    │  │  /xarray/* │  │  │
│  │  │  (Catalog)  │  │ /tiles/mvt/*│  │ (COG tiles) │  │(Zarr tiles)│  │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘  │  │
│  └─────────┼────────────────┼────────────────┼───────────────┼─────────┘  │
└────────────┼────────────────┼────────────────┼───────────────┼────────────┘
             │                │                │               │
             ▼                ▼                ▼               ▼
       ┌──────────┐     ┌──────────┐     ┌──────────┐    ┌──────────┐
       │  pgSTAC  │     │ PostGIS  │     │   COGs   │    │   Zarr   │
       │(metadata)│     │ (vector) │     │  (Blob)  │    │  (Blob)  │
       └──────────┘     └──────────┘     └──────────┘    └──────────┘
```

### API Categories

| Category | API | Provider | Endpoints | Backend |
|----------|-----|----------|-----------|---------|
| **Catalog** | STAC API | stac-fastapi | `/stac/*` | pgSTAC (PostgreSQL) |
| **Vector Features** | OGC Features | TiPG | `/features/*` | PostGIS |
| **Vector Tiles** | MVT Tiles | TiPG | `/tiles/mvt/*` | PostGIS |
| **Raster Tiles** | TiTiler-pgSTAC | TiTiler | `/cog/*` | COGs (Blob Storage) |
| **Xarray Tiles** | TiTiler-xarray | TiTiler | `/xarray/*` | Zarr (Blob Storage) |

### Key Benefits of Unified Architecture

- **Single deployment**: One Docker container to manage
- **Shared connection pools**: Efficient database connections across all APIs
- **Consistent routing**: Single FastAPI application handles all requests
- **Simplified configuration**: One set of environment variables
- **Lower operational overhead**: Single health check, single log stream

---

## Dev Seed Open Source Stack

The Service Layer is built on the [Development Seed](https://developmentseed.org/) open source geospatial stack:

### TiTiler

**Repository**: [developmentseed/titiler](https://github.com/developmentseed/titiler)
**Documentation**: [developmentseed.org/titiler](https://developmentseed.org/titiler/)

TiTiler is a dynamic tile server for Cloud Optimized GeoTIFFs (COGs). Key features:
- **Dynamic tiling**: Generate tiles on-the-fly without pre-rendering
- **Band math**: Calculate derived indices (NDVI, etc.)
- **Rescaling and colormaps**: Apply visualization parameters per request
- **Multiple formats**: PNG, JPEG, WebP, GeoTIFF

The platform uses two TiTiler extensions:
- **titiler-pgstac**: Serves tiles from STAC-cataloged COGs
- **titiler-xarray**: Serves tiles from Zarr/NetCDF datasets

### TiPG

**Repository**: [developmentseed/tipg](https://github.com/developmentseed/tipg)
**Documentation**: [developmentseed.org/tipg](https://developmentseed.org/tipg/)

TiPG implements OGC API - Features and OGC API - Tiles for PostGIS tables:
- **OGC Features**: GeoJSON feature access with filtering
- **MVT Tiles**: Mapbox Vector Tiles for efficient rendering
- **Auto-discovery**: Automatically exposes PostGIS tables as collections
- **CQL2 Filtering**: Advanced query filtering support

### stac-fastapi

**Repository**: [stac-utils/stac-fastapi](https://github.com/stac-utils/stac-fastapi)
**Documentation**: [stac-utils.github.io/stac-fastapi](https://stac-utils.github.io/stac-fastapi/)

STAC API implementation with pgSTAC backend:
- **STAC 1.0.0 compliant**: Full specification support
- **pgSTAC backend**: Efficient PostGIS-based queries
- **Cross-collection search**: Query multiple collections at once
- **Transactions support**: Create/update/delete items (if enabled)

---

## 1. STAC API (`/stac/...`)

### Overview

Implements **STAC API v1.0.0** specification for raster metadata discovery. Powered by [stac-fastapi](https://stac-utils.github.io/stac-fastapi/) with pgSTAC backend.

### Core Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /stac` | Landing page with API links |
| `GET /stac/conformance` | Supported conformance classes |
| `GET /stac/collections` | List all collections |
| `GET /stac/collections/{id}` | Collection metadata |
| `GET /stac/collections/{id}/items` | List items in collection |
| `GET /stac/collections/{id}/items/{item_id}` | Single item metadata |
| `POST /stac/search` | Cross-collection search |

### Query Parameters

```bash
# Search items by bbox
curl "/stac/collections/my-cogs/items?bbox=-70.7,-56.3,-70.6,-56.2"

# Search by datetime
curl "/stac/collections/my-cogs/items?datetime=2024-01-01/2024-12-31"

# Full-text search
curl -X POST "/stac/search" \
  -H "Content-Type: application/json" \
  -d '{"collections": ["my-cogs"], "bbox": [-180,-90,180,90], "limit": 10}'
```

### Key Features

- **Pure STAC JSON**: Compliant with standard STAC clients
- **pgSTAC Backend**: Efficient PostGIS-based queries for millions of items
- **Cross-Collection Search**: Single query across multiple collections
- **Pagination**: Standard `limit` and `next` token support

### STAC Browser Integration

The STAC API integrates with [STAC Browser](https://github.com/radiantearth/stac-browser) for interactive catalog exploration.

---

## 2. OGC Features API (`/features/...`)

### Overview

Implements **OGC API - Features Core 1.0** for serving vector data. Powered by [TiPG](https://developmentseed.org/tipg/).

### Core Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /features` | Landing page |
| `GET /features/conformance` | Conformance declaration |
| `GET /features/collections` | List all collections |
| `GET /features/collections/{id}` | Collection metadata |
| `GET /features/collections/{id}/items` | Query features |
| `GET /features/collections/{id}/items/{fid}` | Single feature |

### Query Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `bbox` | Bounding box filter | `bbox=-70.7,-56.3,-70.6,-56.2` |
| `datetime` | Temporal filter | `datetime=2024-01-01/2024-12-31` |
| `limit` | Max features returned | `limit=100` |
| `offset` | Pagination offset | `offset=100` |
| `sortby` | Sort field (+/- prefix) | `sortby=-created` |
| `filter` | CQL2 filter expression | `filter=status='active'` |
| `filter-lang` | Filter language | `filter-lang=cql2-text` |

### Examples

```bash
# Query by bounding box
curl "/features/collections/buildings/items?bbox=-70.7,-56.3,-70.6,-56.2&limit=5"

# Temporal filter
curl "/features/collections/observations/items?datetime=2024-06-01/2024-06-30"

# CQL2 filter with sorting
curl "/features/collections/parcels/items?filter=type='residential'&sortby=-area&limit=10"
```

### CQL2 Filtering

TiPG supports [CQL2](https://docs.ogc.org/DRAFTS/21-065.html) for advanced filtering:

```bash
# Text filter
curl "/features/collections/buildings/items?filter=name LIKE 'School%'"

# Numeric comparison
curl "/features/collections/parcels/items?filter=area > 1000"

# Spatial filter
curl "/features/collections/sites/items?filter=S_INTERSECTS(geom, POLYGON((...)))"
```

---

## 3. Vector Tiles (`/tiles/mvt/...`)

### Overview

TiPG generates [Mapbox Vector Tiles (MVT)](https://docs.mapbox.com/vector-tiles/specification/) directly from PostGIS, enabling efficient client-side rendering.

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /tiles/mvt/{collection}/{z}/{x}/{y}.pbf` | Vector tile |
| `GET /tiles/mvt/{collection}/tilejson.json` | TileJSON metadata |
| `GET /tiles/mvt/{collection}/style.json` | MapLibre style |

### Integration with MapLibre GL

```javascript
// Add TiPG vector tiles to MapLibre GL
map.addSource('buildings', {
  type: 'vector',
  url: 'https://service-layer/tiles/mvt/buildings/tilejson.json'
});

map.addLayer({
  id: 'buildings-fill',
  type: 'fill',
  source: 'buildings',
  'source-layer': 'default',
  paint: {
    'fill-color': '#627BC1',
    'fill-opacity': 0.5
  }
});
```

---

## 4. COG Tile Serving (`/cog/...`)

### Overview

[TiTiler-pgSTAC](https://developmentseed.org/titiler/advanced/tiler_factories/#titiler-pgstac) provides dynamic tile serving for Cloud Optimized GeoTIFFs cataloged in STAC.

### Core Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /cog/tiles/{z}/{x}/{y}.png` | Map tiles |
| `GET /cog/tilejson.json` | TileJSON metadata |
| `GET /cog/info` | COG metadata |
| `GET /cog/statistics` | Band statistics |
| `GET /cog/preview.png` | Quick preview image |
| `GET /cog/point/{lon},{lat}` | Point value query |
| `GET /cog/bbox/{minx},{miny},{maxx},{maxy}.tif` | Extract bbox |

### Examples

```bash
# Get tile with URL
curl "/cog/tiles/10/512/384.png?url=https://storage.blob.core.windows.net/cogs/image.tif"

# Get COG info
curl "/cog/info?url=https://storage.blob.core.windows.net/cogs/image.tif"

# Point query
curl "/cog/point/-77.0,38.9?url=https://storage.blob.core.windows.net/cogs/image.tif"

# Band math (NDVI)
curl "/cog/tiles/10/512/384.png?url=...&expression=(b4-b3)/(b4+b3)&colormap_name=rdylgn"
```

### Visualization Parameters

| Parameter | Purpose | Example |
|-----------|---------|---------|
| `bidx` | Band indexes | `bidx=1&bidx=2&bidx=3` |
| `expression` | Band math | `expression=(b4-b3)/(b4+b3)` |
| `rescale` | Value range | `rescale=0,255` |
| `colormap_name` | Named colormap | `colormap_name=viridis` |
| `return_mask` | Include alpha | `return_mask=true` |

---

## 5. Zarr/Xarray Tile Serving (`/xarray/...`)

### Overview

[TiTiler-xarray](https://developmentseed.org/titiler/advanced/tiler_factories/#titiler-xarray) serves tiles from Zarr and NetCDF datasets using xarray.

### Core Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /xarray/variables` | List Zarr variables |
| `GET /xarray/info` | Variable metadata |
| `GET /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png` | Map tiles |
| `GET /xarray/point/{lon},{lat}` | Point query |
| `GET /xarray/WebMercatorQuad/map.html` | Interactive viewer |

### Examples

```bash
# List variables
curl "/xarray/variables?url=https://storage.blob.core.windows.net/zarr/era5.zarr&decode_times=false"

# Get variable info
curl "/xarray/info?url=https://storage.blob.core.windows.net/zarr/era5.zarr&variable=temperature&decode_times=false"

# Get tile (temperature visualization)
curl "/xarray/tiles/WebMercatorQuad/3/4/2@1x.png\
?url=https://storage.blob.core.windows.net/zarr/era5.zarr\
&variable=temperature\
&decode_times=false\
&bidx=1\
&colormap_name=viridis\
&rescale=250,320"

# Point query
curl "/xarray/point/-77.0,38.9\
?url=https://storage.blob.core.windows.net/zarr/era5.zarr\
&variable=temperature\
&decode_times=false"
```

### Critical Parameters

| Parameter | Purpose | Required |
|-----------|---------|----------|
| `url` | Zarr store URL | Yes |
| `variable` | Data variable name | Yes (for tiles/point) |
| `decode_times=false` | Handle non-standard calendars | Yes (climate data) |
| `bidx=N` | Band/time index (1-based) | Yes (temporal data) |
| `colormap_name` | Color palette | Optional |
| `rescale=min,max` | Value range for colormap | Recommended |

---

## 6. Deployment Architecture

### Current Production Setup

```
Azure API Management (api.example.com)
├─→ Platform Function App (<platform-function-app>)
│   ├── /api/platform/*    → Platform API (job submission)
│   ├── /api/jobs/*        → Job status
│   └── /api/dbadmin/*     → Admin endpoints
│
└─→ Service Layer Docker App (<service-layer-app>)
    ├── /stac/*            → STAC API (stac-fastapi)
    ├── /features/*        → OGC Features (TiPG)
    ├── /tiles/mvt/*       → Vector Tiles (TiPG)
    ├── /cog/*             → COG Tiles (TiTiler)
    └── /xarray/*          → Zarr Tiles (TiTiler)

Both connect to: PostgreSQL (shared database)
```

### Docker Deployment

The Service Layer runs as a single Docker container:

```bash
# Build and push
az acr build --registry $ACR --image service-layer:$VERSION --file Dockerfile.service .

# Deploy to Azure Web App for Containers
az webapp create --resource-group $RG --plan $PLAN --name $NAME \
  --deployment-container-image-name $ACR.azurecr.io/service-layer:$VERSION

# Configure environment
az webapp config appsettings set --name $NAME --resource-group $RG --settings \
  DATABASE_URL="postgresql://..." \
  PGSTAC_SCHEMA="pgstac" \
  TIPG_SCHEMA="geo" \
  TITILER_API_CACHECONTROL="public, max-age=3600"
```

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `PGSTAC_SCHEMA` | Schema for STAC metadata | `pgstac` |
| `TIPG_SCHEMA` | Schema for vector tables | `geo` |
| `TITILER_API_CACHECONTROL` | Cache headers | `public, max-age=3600` |
| `AZURE_STORAGE_ACCOUNT` | Storage for COGs/Zarr | `myaccount` |
| `AZURE_STORAGE_SAS_TOKEN` | SAS token (if private) | `sv=2022-...` |

### Database Access Pattern

The Service Layer is **read-only** and accesses these schemas:

| Schema | Tables | Access |
|--------|--------|--------|
| `geo` | Vector tables, `table_catalog` | SELECT only |
| `pgstac` | `collections`, `items`, `searches` | SELECT only |

The Service Layer does **NOT** access:
- `app` schema (jobs, tasks) - Platform API only
- Service Bus queues - Platform API only
- Bronze storage account - Platform API only

---

## 7. Zarr Dataset Integration

### Preparing Zarr for TiTiler

When preparing new Zarr datasets:

1. **Write with zarr_format=2** for TiTiler compatibility
2. **Consolidate metadata** - verify `.zmetadata` is complete
3. **Enable public blob access** (or configure SAS tokens)
4. **Test `/xarray/variables` endpoint** before tile requests
5. **Use `decode_times=false`** for climate data with non-standard calendars

### Common Issues

**Empty Variables Error**
```json
{"detail":"No variable named 'temperature'. Variables on the dataset include []"}
```
**Solution**: Re-consolidate metadata or use `&reader_options={"consolidated":false}`

**Chunk Alignment Errors**
```
ValueError: Specified Zarr chunks encoding would overlap multiple Dask chunks
```
**Solution**: Explicitly set encoding chunks as tuples matching Dask chunks.

See `docs_claude/ZARR_TITILER_LESSONS.md` for detailed troubleshooting.

---

## 8. API Quick Reference

### STAC API (stac-fastapi)
```bash
GET  /stac                               # Landing page
GET  /stac/collections                   # List collections
GET  /stac/collections/{id}/items        # Query items
POST /stac/search                        # Cross-collection search
```

### OGC Features API (TiPG)
```bash
GET  /features                           # Landing page
GET  /features/collections               # List collections
GET  /features/collections/{id}/items    # Query features
     ?bbox=-70,-56,-69,-55
     &datetime=2024-01-01/2024-12-31
     &limit=100&sortby=-created
     &filter=status='active'             # CQL2 filter
```

### Vector Tiles (TiPG)
```bash
GET  /tiles/mvt/{collection}/{z}/{x}/{y}.pbf   # Vector tile
GET  /tiles/mvt/{collection}/tilejson.json     # TileJSON
GET  /tiles/mvt/{collection}/style.json        # MapLibre style
```

### COG Tiles (TiTiler)
```bash
GET  /cog/tiles/{z}/{x}/{y}.png?url=...  # Map tiles
GET  /cog/info?url=...                   # Metadata
GET  /cog/point/{lon},{lat}?url=...      # Point query
GET  /cog/preview.png?url=...            # Preview image
```

### Zarr Tiles (TiTiler-xarray)
```bash
GET  /xarray/variables?url=...&decode_times=false
GET  /xarray/info?url=...&variable=...&decode_times=false
GET  /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png
     ?url=...&variable=...&decode_times=false&bidx=1
     &colormap_name=viridis&rescale=250,320
```

---

## 9. Observability

### Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Combined health status |
| `GET /stac/health` | STAC API health |
| `GET /features/health` | TiPG health |

### Metrics

Service latency is tracked via blob-based metrics when `OBSERVABILITY_MODE=true`:

**Path**: `applogs/service-metrics/{date}/{instance_id}/{timestamp}.jsonl`

**Format**:
```json
{"ts": "2026-01-10T14:30:52Z", "op": "stac.search", "ms": 145.2, "status": "success"}
{"ts": "2026-01-10T14:30:53Z", "op": "tipg.query_features", "ms": 89.1, "status": "success"}
```

### Logging

All logs are sent to the container's stdout and captured by Azure App Service logging. View via:
- Azure Portal → Web App → Log stream
- Azure CLI: `az webapp log tail --name $NAME --resource-group $RG`

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [TiTiler Documentation](https://developmentseed.org/titiler/) | Official TiTiler docs |
| [TiPG Documentation](https://developmentseed.org/tipg/) | Official TiPG docs |
| [stac-fastapi Documentation](https://stac-utils.github.io/stac-fastapi/) | Official stac-fastapi docs |
| [STAC Specification](https://stacspec.org/) | STAC standard |
| [OGC API - Features](https://ogcapi.ogc.org/features/) | OGC standard |
| `docs_claude/ZARR_TITILER_LESSONS.md` | Zarr integration notes |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | Overall system architecture |

---

**Author:** Platform Team
**Last Updated:** 01 FEB 2026
