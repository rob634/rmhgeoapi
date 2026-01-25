## Epic E6: Geospatial Tile Services (geotiler)

**Type**: Platform
**Value Statement**: ArcGIS Server replacement - modern, cloud-native geospatial tile serving
**Deployment**: Standalone containerized service (Azure App Service)
**Status**: 🚧 PARTIAL (Core ✅, ArcGIS Migration 📋)
**Last Updated**: 18 JAN 2026
**Repository**: `rmhtitiler`

**Strategic Context**:
> E6 is not just infrastructure - it's a product that replaces ArcGIS Servers. It delivers direct
> B2C value to external consumers while also enabling E1 (Vector), E2 (Raster), and E9 (Large Data)
> epics. The ArcGIS migration roadmap gives E6 its own backlog independent of ETL epics.

**Architecture**:
```
                    ┌─────────────────────────────┐
                    │  E6: Geospatial Tile        │
                    │  Services (geotiler)        │
                    │                             │
                    │  • Direct B2C value         │
                    │  • ArcGIS replacement       │
                    │  • Platform for E1/E2/E9    │
                    └───────────┬─────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            │ vector tiles      │ raster tiles      │ zarr tiles
            ▼                   ▼                   ▼
     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
     │ E1: Vector  │     │ E2: Raster  │     │ E9: Large & │
     │ Data ETL    │     │ Data ETL    │     │ Multidim    │
     └─────────────┘     └─────────────┘     └─────────────┘
```

**Relationship to Other Epics**:
| Epic | Relationship | What E6 Provides |
|------|--------------|------------------|
| E1 | Enables | Vector tiles (MVT) via TiPG, OGC Features API |
| E2 | Enables | COG tile serving, preview generation, viewer URLs |
| E9 | Enables | Zarr/NetCDF tiles, pgSTAC mosaic searches |
| E8 | Enables | Tile serving for H3 aggregation source data (FATHOM COGs) |
| E12 | Provides | Consumer documentation, interactive explorers |

**Feature Summary**:
| Feature | Status | Description |
|---------|--------|-------------|
| F6.1 | ✅ | COG Tile Serving (TiTiler-core) |
| F6.2 | ✅ | Vector Tiles & OGC Features (TiPG) |
| F6.3 | ✅ | Multidimensional Data (TiTiler-xarray) |
| F6.4 | ✅ | pgSTAC Mosaic Searches |
| F6.5 | 📋 | ArcGIS Migration Capabilities |
| F6.6 | ✅ | Service Operations |
| F6.7 | 🚧 | Consumer Documentation & Onboarding |

---

### Feature F6.1: COG Tile Serving ✅

**Deliverable**: Dynamic tile rendering for Cloud Optimized GeoTIFFs
**Technology**: TiTiler-core with GDAL

| Story | Status | Description |
|-------|--------|-------------|
| S6.1.1 | ✅ | Dynamic tile rendering with rescaling |
| S6.1.2 | ✅ | Colormap support (terrain, viridis, etc.) |
| S6.1.3 | ✅ | Band combination & expression rendering |
| S6.1.4 | ✅ | Preview/thumbnail generation |
| S6.1.5 | 📋 | Tile caching layer (ArcGIS parity) |

**Key Endpoints**:
- `GET /cog/tiles/{z}/{x}/{y}` - XYZ tiles
- `GET /cog/info?url={cog_url}` - COG metadata
- `GET /cog/preview?url={cog_url}` - Thumbnail preview
- `GET /cog/point/{lon}/{lat}?url={cog_url}` - Point query

**Key Files**: `geotiler/routers/cog_landing.py`

---

### Feature F6.2: Vector Tiles & OGC Features (TiPG) ✅

**Deliverable**: OGC Features API and MVT vector tiles from PostGIS
**Technology**: TiPG (titiler-pgstac)

| Story | Status | Description |
|-------|--------|-------------|
| S6.2.1 | ✅ | OGC Features API (`/vector/collections/{id}/items`) |
| S6.2.2 | ✅ | MVT Vector Tiles (`/vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}`) |
| S6.2.3 | ✅ | Multi-schema support (TIPG_SCHEMAS configuration) |
| S6.2.4 | ✅ | Startup diagnostics & pool management |
| S6.2.5 | ✅ | TiPG diagnostics endpoints (`/vector/diagnostics`) |
| S6.2.6 | 📋 | Style-aware rendering (MapBox GL compatibility) |

**Key Endpoints**:
- `GET /vector/collections` - List PostGIS collections
- `GET /vector/collections/{id}/items` - Query features (GeoJSON)
- `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` - Vector tiles (MVT)

**Key Files**: `geotiler/routers/vector.py`, `geotiler/routers/diagnostics.py`

**Integration with E1**:
- E1.F1.10 (Vector Tile Optimization) creates `{table}_tiles` materialized views
- TiPG automatically discovers and serves these optimized views
- ST_Subdivide reduces vertex counts for faster MVT generation

---

### Feature F6.3: Multidimensional Data (TiTiler-xarray) ✅

**Deliverable**: Tile serving for Zarr and NetCDF data
**Technology**: TiTiler-xarray

| Story | Status | Description |
|-------|--------|-------------|
| S6.3.1 | ✅ | Zarr tile serving |
| S6.3.2 | ✅ | NetCDF support |
| S6.3.3 | ✅ | Planetary Computer integration |
| S6.3.4 | 📋 | Time-series animation endpoints |

**Key Endpoints**:
- `GET /xarray/tiles/{z}/{x}/{y}` - XYZ tiles from Zarr/NetCDF
- `GET /xarray/info` - Dataset metadata
- `GET /xarray/point/{lon}/{lat}` - Time-series at point

**Key Files**: `geotiler/routers/xarray_landing.py`, `geotiler/routers/planetary_computer.py`

---

### Feature F6.4: pgSTAC Mosaic Searches ✅

**Deliverable**: Dynamic mosaic generation from STAC catalog searches
**Technology**: TiTiler-pgstac

| Story | Status | Description |
|-------|--------|-------------|
| S6.4.1 | ✅ | Dynamic mosaic registration |
| S6.4.2 | ✅ | STAC search → tile serving |
| S6.4.3 | 📋 | Mosaic caching & optimization |

**Key Endpoints**:
- `POST /searches/register` - Register a mosaic search
- `GET /searches/{search_id}/tiles/{z}/{x}/{y}` - Tiles from search results

**Key Files**: `geotiler/routers/searches_landing.py`

---

### Feature F6.5: ArcGIS Migration Capabilities 📋 PLANNED

**Deliverable**: Feature parity with ArcGIS Server for common use cases
**Strategic Value**: Enables migration from expensive ArcGIS Server licenses

| Story | Status | Description |
|-------|--------|-------------|
| S6.5.1 | 📋 | MapServer endpoint compatibility layer |
| S6.5.2 | 📋 | FeatureServer query translation |
| S6.5.3 | 📋 | ArcGIS JS API client support |
| S6.5.4 | 📋 | Legend/symbology endpoint |
| S6.5.5 | 📋 | Export map image (print service) |
| S6.5.6 | 📋 | Migration assessment tooling |

**ArcGIS Parity Matrix**:
| ArcGIS Capability | TiTiler/TiPG Equivalent | Status |
|-------------------|------------------------|--------|
| MapServer (raster tiles) | `/cog/tiles/{z}/{x}/{y}` | ✅ |
| FeatureServer (vector features) | `/vector/collections/{id}/items` | ✅ |
| FeatureServer (vector tiles) | `/vector/collections/{id}/tiles` | ✅ |
| ImageServer (dynamic mosaic) | `/searches/register` + tiles | ✅ |
| Export Map Image | 📋 Needs implementation | |
| Legend/Symbology | 📋 Needs implementation | |
| Query (SQL-like) | Partial (bbox, property filters) | 🚧 |
| Geoprocessing | Out of scope (different pattern) | |

**Migration Use Cases**:
1. **Basemap Tile Services**: Replace ArcGIS cached map services with COG tiles
2. **Feature Services**: Replace with OGC Features API + vector tiles
3. **Dynamic Map Services**: Replace with pgSTAC mosaic searches
4. **Web AppBuilder Apps**: Provide compatible endpoints for existing apps

---

### Feature F6.6: Service Operations ✅

**Deliverable**: Production-ready service with health checks, auth, and observability
**Status**: Operational

| Story | Status | Description |
|-------|--------|-------------|
| S6.6.1 | ✅ | Health probes (`/livez`, `/readyz`, `/health`) |
| S6.6.2 | ✅ | Azure Managed Identity authentication |
| S6.6.3 | ✅ | Token refresh lifecycle (background task) |
| S6.6.4 | ✅ | OpenTelemetry observability (App Insights) |
| S6.6.5 | ✅ | TiPG diagnostics endpoints |
| S6.6.6 | 📋 | Performance dashboard |

**Health Endpoint Details**:
- `/livez` - Quick liveness check (container alive?)
- `/readyz` - Readiness check (ready for traffic?)
- `/health` - Full diagnostics (database, storage, token status)

**Key Files**: `geotiler/routers/health.py`, `geotiler/auth/`, `geotiler/middleware/`

**Operational Features**:
- Graceful degradation (starts even if database unavailable)
- Thread-safe token caching with automatic refresh
- Structured JSON logging with custom dimensions
- Request timing middleware with endpoint normalization

---

### Feature F6.7: Consumer Documentation & Onboarding 🚧

**Deliverable**: Self-service documentation for tile service consumers
**Status**: Core docs ✅, Narrative guides 📋

| Story | Status | Description |
|-------|--------|-------------|
| S6.7.1 | ✅ | COG endpoint documentation (`/docs/cog`) |
| S6.7.2 | ✅ | XArray endpoint documentation (`/docs/xarray`) |
| S6.7.3 | ✅ | pgSTAC search documentation (`/docs/searches`) |
| S6.7.4 | ✅ | STAC Explorer UI (`/stac-explorer`) |
| S6.7.5 | 📋 | ArcGIS migration guide |
| S6.7.6 | 📋 | Client library examples (Leaflet, MapLibre, OpenLayers) |
| S6.7.7 | 📋 | Data science cookbook (Jupyter examples) |

**Key Files**: `geotiler/routers/docs_guide.py`, `geotiler/routers/stac_explorer.py`

**Documentation Endpoints**:
- `/docs/cog` - COG tile serving guide
- `/docs/xarray` - Zarr/NetCDF guide
- `/docs/searches` - pgSTAC mosaic guide
- `/stac-explorer` - Interactive STAC browser

---

## Technical Architecture

### Technology Stack
| Component | Technology | Purpose |
|-----------|------------|---------|
| Framework | FastAPI | HTTP API server |
| COG Tiles | TiTiler-core | Dynamic raster tile rendering |
| Vector Tiles | TiPG | OGC Features + MVT from PostGIS |
| Zarr Tiles | TiTiler-xarray | Multidimensional array tiles |
| Mosaics | TiTiler-pgstac | STAC-based dynamic mosaics |
| Auth | Azure Managed Identity | Storage + database OAuth |
| Observability | Azure Monitor OpenTelemetry | Telemetry + logging |

### Deployment
| Environment | Status | Notes |
|-------------|--------|-------|
| DEV | ✅ | Full stack deployed |
| QA | ✅ | Production-equivalent |
| PROD | ✅ | Azure App Service container |

### Version
- **Current**: See `geotiler/__init__.py` for `__version__`
- **Image**: `{acr}.azurecr.io/titiler-pgstac:v{version}`

---

## WSJF Calculation

| Factor | Score | Rationale |
|--------|-------|-----------|
| Business Value | 21 | ArcGIS replacement saves significant license costs |
| Time Criticality | 13 | Blocks E1/E2/E9 serving capabilities |
| Risk Reduction | 13 | Reduces vendor lock-in, modern architecture |
| **Cost of Delay** | **47** | |
| Job Size | 8 | Core operational, migrations remaining |
| **WSJF** | **5.9** | High priority |

---

## Cross-References

| Epic | Feature | Relationship |
|------|---------|--------------|
| E1 | F1.2 OGC Features API | Served by F6.2 (TiPG) |
| E1 | F1.10 Vector Tile Optimization | Optimizes data for F6.2 |
| E2 | F2.2 TiTiler Integration | Served by F6.1 (COG tiles) |
| E2 | F2.9 STAC Raster Viewer | Uses F6.1 + F6.4 |
| E9 | F9.5 xarray Service Layer | Served by F6.3 (Zarr tiles) |
| E9 | F9.6 TiTiler Services | **Moved to E6** |
| E12 | F12.9 TiTiler Consumer Docs | Implemented in F6.7 |

---
