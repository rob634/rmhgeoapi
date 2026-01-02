## Epic E9: Large and Multidimensional Data 🚧

**Type**: Business
**Value Statement**: We can host and serve FATHOM/CMIP6-scale data.
**Runs On**: E7 (Pipeline Infrastructure)
**Status**: 🚧 PARTIAL (F9.1 🚧, F9.5 ✅)
**Last Updated**: 31 DEC 2025

**Strategic Context**:
> E9 is the "data hosting" epic. It handles ingesting, processing, and serving very large datasets
> that feed into E8 (GeoAnalytics). First prototypes: FATHOM flood data (GeoTIFF) and CMIP6 climate
> data (Zarr/NetCDF). VirtualiZarr pipeline enables serving NetCDF without conversion.

**Architecture**:
```
Raw Data                  Processing                Serving
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ FATHOM GeoTIFFs │─────▶│ Band Stack +    │─────▶│ TiTiler COG     │
│ (1000s tiles)   │      │ Spatial Merge   │      │ Service         │
├─────────────────┤      ├─────────────────┤      ├─────────────────┤
│ CMIP6 NetCDF    │─────▶│ VirtualiZarr    │─────▶│ TiTiler Zarr    │
│ (TB-scale)      │      │ References      │      │ Service         │
└─────────────────┘      └─────────────────┘      └─────────────────┘
   Bronze Storage           Silver Storage           API Endpoints
```

**Feature Summary**:
| Feature | Status | Description |
|---------|--------|-------------|
| F9.1 | 🚧 | FATHOM ETL Operations (~~E10~~) |
| F9.2 | ⬜ | FATHOM Flood Data Hosting |
| F9.3 | 📋 | VirtualiZarr Pipeline (NetCDF → Zarr references) |
| F9.4 | 📋 | CMIP6 Data Hosting |
| F9.5 | ✅ | xarray Service Layer |
| F9.6 | 📋 | TiTiler Services (COG + Zarr) |
| F9.7 | ⬜ | Reader App Migration |
| F9.8 | 📋 | Pre-prepared Raster Ingest |
| F9.9 | 📋 | FATHOM Query API |
| F9.10 | 📋 | FATHOM Data Explorer UI |

---

### Feature F9.1: FATHOM ETL Operations 🚧 (formerly E10)

**Deliverable**: Band stacking, spatial merge, STAC registration for FATHOM flood data
**Documentation**: [FATHOM_ETL.md](docs_claude/FATHOM_ETL.md)
**Status**: 🚧 Phase 1 ✅, Phase 2 46/47 tasks

| Story | Status | Description |
|-------|--------|-------------|
| S9.1.1 | ✅ | Phase 1: Band stacking (8 return periods → 1 COG) |
| S9.1.2 | 🚧 | Phase 2: Spatial merge (N×N tiles → 1 COG) - 46/47 tasks |
| S9.1.3 | 📋 | Phase 3: STAC registration for merged COGs |
| S9.1.4 | 📋 | Phase 4: West Africa / Africa scale processing |

**Current Issue**: Phase 2 task `n10-n15_w005-w010` failed. Need retry with `force_reprocess=true`.

**Key Files**: `services/fathom/fathom_etl.py`, `jobs/fathom_*.py`

---

### Feature F9.2: FATHOM Flood Data Hosting ⬜ READY

**Deliverable**: End-to-end hosting pipeline for FATHOM flood risk data
**Partner**: FATHOM
**Data Patterns**: Zarr (preferred), COG (fallback)

| Story | Status | Description |
|-------|--------|-------------|
| S9.2.1 | ⬜ | FATHOM data inventory and schema analysis |
| S9.2.2 | ⬜ | FATHOM handler implementation |
| S9.2.3 | ⬜ | Zarr output configuration (chunking, compression) |
| S9.2.4 | ⬜ | STAC collection with datacube extension |
| S9.2.5 | ⬜ | TiTiler Zarr Service integration for tile serving |
| S9.2.6 | ⬜ | Manual update trigger endpoint |

**FATHOM Data Characteristics**:
- Global flood hazard maps (fluvial, pluvial, coastal)
- Multiple return periods (1-in-5 to 1-in-1000 year)
- High resolution (3 arcsec / ~90m)
- Time-series projections (climate scenarios)

---

### Feature F9.3: VirtualiZarr Pipeline 📋 PLANNED

**Deliverable**: Kerchunk/VirtualiZarr reference files enabling cloud-native access to legacy NetCDF

**Strategic Context**:
Eliminates need for traditional THREDDS/OPeNDAP infrastructure. NetCDF files
remain in blob storage unchanged; lightweight JSON references (~KB) enable
**TiTiler Zarr Service** to serve data via modern cloud-optimized patterns.

**Compute Profile**: Azure Function App (reference generation is I/O-bound, not compute-bound)

| Story | Status | Description |
|-------|--------|-------------|
| S9.3.1 | 📋 | CMIP6 filename parser (extract variable, model, scenario) |
| S9.3.2 | 📋 | Chunking validator (pre-flight NetCDF compatibility check) |
| S9.3.3 | 📋 | Reference generator (single NetCDF → Kerchunk JSON ~KB) |
| S9.3.4 | 📋 | Virtual combiner (merge time-series references) |
| S9.3.5 | 📋 | STAC datacube registration (xarray-compatible items) |
| S9.3.6 | 📋 | Inventory job (scan and group NetCDF files) |
| S9.3.7 | 📋 | Generate job (full reference pipeline) |

**Dependencies**: `virtualizarr`, `kerchunk`, `h5netcdf`, `h5py`

**Architecture**:
```
NetCDF Files (unchanged)     Reference Generation      TiTiler Zarr Service
┌─────────────────────┐     ┌──────────────────┐     ┌────────────────┐
│ tasmax_2015.nc      │     │                  │     │                │
│ tasmax_2016.nc      │────▶│ Kerchunk JSON    │────▶│ /tiles/{z}/{x} │
│ tasmax_2017.nc      │     │ (~5KB per file)  │     │ /point/{x},{y} │
│ ...                 │     │                  │     │                │
└─────────────────────┘     └──────────────────┘     └────────────────┘
  Bronze Storage Account     Silver Storage Account   Cloud-Native API
     (no conversion)           (lightweight refs)     (no THREDDS)
```

---

### Feature F9.4: CMIP6 Data Hosting 📋 PLANNED

**Deliverable**: Curated subset of CMIP6 climate projections for East Africa analysis
**Data Source**: Planetary Computer CMIP6 collection

| Story | Status | Description |
|-------|--------|-------------|
| S9.4.1 | 📋 | Identify priority variables (tas, pr, tasmax, tasmin) |
| S9.4.2 | 📋 | Identify priority scenarios (SSP2-4.5, SSP5-8.5) |
| S9.4.3 | 📋 | Download/mirror selected data to Azure storage |
| S9.4.4 | 📋 | Generate VirtualiZarr references for time-series access |
| S9.4.5 | 📋 | Register in STAC catalog with datacube extension |
| S9.4.6 | 📋 | Create source_catalog entries for H3 aggregation |

**NOT the whole thing** - curated subset for specific analysis:
- Variables: Temperature (tas, tasmax, tasmin), Precipitation (pr)
- Scenarios: SSP2-4.5 (moderate), SSP5-8.5 (high emissions)
- Region: East Africa bounding box
- Time: 2020-2100 (decadal snapshots)

---

### Feature F9.5: xarray Service Layer ✅

**Deliverable**: Time-series and statistics endpoints for multidimensional data

| Story | Status | Description |
|-------|--------|-------------|
| S9.5.1 | ✅ | Create xarray reader service |
| S9.5.2 | ✅ | Implement /api/xarray/point time-series |
| S9.5.3 | ✅ | Implement /api/xarray/statistics |
| S9.5.4 | ✅ | Implement /api/xarray/aggregate |

**Key Files**: `xarray_api/`, `services/xarray_reader.py`

---

### Feature F9.6: TiTiler Services 📋 PLANNED

**Deliverable**: Unified tile serving for COG and Zarr data

| Story | Status | Description |
|-------|--------|-------------|
| S9.6.1 | 📋 | TiTiler COG configuration for FATHOM merged COGs |
| S9.6.2 | 📋 | TiTiler Zarr configuration for VirtualiZarr references |
| S9.6.3 | 📋 | STAC-based asset discovery for dynamic tiling |
| S9.6.4 | 📋 | Colormap configuration for flood depth visualization |

---

### Feature F9.7: Reader App Migration ⬜ READY

**Deliverable**: Move read APIs to **Reader Function App** (clean separation)

| Story | Status | Description |
|-------|--------|-------------|
| S9.7.1 | ⬜ | Copy raster_api module |
| S9.7.2 | ⬜ | Copy xarray_api module |
| S9.7.3 | ⬜ | Copy service clients |
| S9.7.4 | ⬜ | Update requirements.txt |
| S9.7.5 | ⬜ | Register routes |
| S9.7.6 | ⬜ | Deploy and validate |

---

### Feature F9.8: Pre-prepared Raster Ingest 📋 PLANNED

**Deliverable**: Lightweight ingest pipeline for raster datasets already prepared as COGs
**Use Case**: Data provider has already converted to COG format; we just need to host and catalog

**Distinction from Other Features**:
| Feature | Input | Processing | STAC Source |
|---------|-------|------------|-------------|
| F2.1 (process_raster) | Raw GeoTIFF | Convert to COG | Auto-generated |
| F7.3 (ingest_collection) | COGs + STAC JSON | Copy only | Existing STAC sidecars |
| **F9.8 (ingest_prepared_raster)** | COGs (no STAC) | Copy only | **Custom from parameters** |

**Workflow**:
```
Bronze Storage              Silver Storage              pgSTAC
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│ prepared_cogs/  │        │ silver_rasters/ │        │ STAC Collection │
│ ├── tile_1.tif  │───────▶│ ├── tile_1.tif  │───────▶│ + Items         │
│ ├── tile_2.tif  │  Copy  │ ├── tile_2.tif  │ Create │                 │
│ └── tile_N.tif  │        │ └── tile_N.tif  │  STAC  │                 │
└─────────────────┘        └─────────────────┘        └─────────────────┘
     (already COG)              (hosted)             (from parameters)
```

| Story | Status | Description |
|-------|--------|-------------|
| S9.8.1 | 📋 | Design STAC structure parameter schema (collection metadata, item naming pattern) |
| S9.8.2 | 📋 | Create `ingest_prepared_raster` job definition (3-stage: inventory, copy, register) |
| S9.8.3 | 📋 | Inventory handler (scan source container, validate COG format) |
| S9.8.4 | 📋 | Copy handler (parallel blob copy bronze → silver) |
| S9.8.5 | 📋 | STAC generation handler (create collection + items from parameters) |
| S9.8.6 | 📋 | Support bbox/datetime extraction from COG metadata |
| S9.8.7 | 📋 | Support custom asset naming and properties |

**Parameter Schema**:
```json
{
    "source_container": "bronze-prepared",
    "source_prefix": "partner_data/cogs/",
    "target_container": "silver-rasters",
    "target_prefix": "partner_name/",
    "stac_config": {
        "collection_id": "partner-dataset-2025",
        "collection_title": "Partner Dataset 2025",
        "collection_description": "Pre-prepared COG dataset from partner",
        "item_id_pattern": "{filename_stem}",
        "datetime_source": "filename|metadata|fixed",
        "datetime_fixed": "2025-01-01T00:00:00Z",
        "bbox_source": "metadata",
        "custom_properties": {
            "provider": "Partner Name",
            "license": "CC-BY-4.0"
        }
    }
}
```

**Key Files**: `jobs/ingest_prepared_raster.py` (planned)

---

### Feature F9.9: FATHOM Query API 📋 PLANNED

**Deliverable**: Flood-specific query endpoints with semantic parameters
**Builds On**: F2.5 (Raster Data Extract API) - general raster query infrastructure
**Use Case**: Query flood depth/extent by return period, flood type, and climate scenario

**Why FATHOM-Specific?**
The general Raster API (F2.5) queries by STAC collection/item IDs. FATHOM users think in terms
of flood semantics: "What's the 1-in-100 year fluvial flood depth at this location?" not
"What's the value in item `fathom-fluvial-rp100-tile-n05w010`?"

**Architecture**:
```
User Request                    FATHOM Query API              Raster API (F2.5)
┌─────────────────────┐        ┌─────────────────────┐       ┌─────────────────┐
│ /api/fathom/point   │        │ Resolve semantic    │       │ /api/raster/    │
│ ?lon=-1.5&lat=6.2   │───────▶│ params to STAC      │──────▶│ point/{coll}/   │
│ &flood_type=fluvial │        │ collection/item     │       │ {item}          │
│ &return_period=100  │        │                     │       │                 │
└─────────────────────┘        └─────────────────────┘       └─────────────────┘
```

| Story | Status | Description |
|-------|--------|-------------|
| S9.9.1 | 📋 | Design FATHOM semantic parameter schema (flood_type, return_period, scenario) |
| S9.9.2 | 📋 | Create FATHOM item resolver (semantic params → STAC item ID) |
| S9.9.3 | 📋 | Implement `/api/fathom/point` endpoint (flood depth at location) |
| S9.9.4 | 📋 | Implement `/api/fathom/profile` endpoint (all return periods at location) |
| S9.9.5 | 📋 | Implement `/api/fathom/extent` endpoint (flood extent for return period) |
| S9.9.6 | 📋 | Add flood depth colormaps (blue gradient for depth visualization) |
| S9.9.7 | 📋 | Add return period legend generation |

**Endpoints**:
| Endpoint | Purpose | Parameters |
|----------|---------|------------|
| `GET /api/fathom/point` | Flood depth at location | `lon`, `lat`, `flood_type`, `return_period`, `scenario` |
| `GET /api/fathom/profile` | All return periods at location | `lon`, `lat`, `flood_type`, `scenario` → returns array |
| `GET /api/fathom/extent` | Flood extent as image | `bbox`, `flood_type`, `return_period`, `threshold` |
| `GET /api/fathom/tiles/{z}/{x}/{y}` | XYZ tiles | `flood_type`, `return_period`, `colormap` |

**Semantic Parameters**:
| Parameter | Values | Description |
|-----------|--------|-------------|
| `flood_type` | `fluvial`, `pluvial`, `coastal` | Type of flood hazard |
| `return_period` | `5`, `10`, `20`, `50`, `100`, `200`, `500`, `1000` | Annual exceedance probability |
| `scenario` | `baseline`, `ssp245_2050`, `ssp585_2050` | Climate scenario |
| `threshold` | float (meters) | Minimum depth for extent queries |

**Response Example** (`/api/fathom/profile`):
```json
{
    "location": [-1.5, 6.2],
    "flood_type": "fluvial",
    "scenario": "baseline",
    "profile": [
        {"return_period": 5, "depth_m": 0.0},
        {"return_period": 10, "depth_m": 0.12},
        {"return_period": 20, "depth_m": 0.45},
        {"return_period": 50, "depth_m": 0.89},
        {"return_period": 100, "depth_m": 1.23},
        {"return_period": 200, "depth_m": 1.56},
        {"return_period": 500, "depth_m": 2.01},
        {"return_period": 1000, "depth_m": 2.34}
    ],
    "units": "meters"
}
```

**Key Files**: `fathom_api/` (planned)

**Dependencies**:
- F9.1 (FATHOM ETL) - data must be processed and registered
- F9.2 (FATHOM Hosting) - STAC collection must exist
- F2.5 (Raster API) - underlying query infrastructure

---

### Feature F9.10: FATHOM Data Explorer UI 📋 PLANNED

**Deliverable**: Interactive map interface for exploring FATHOM flood data
**Endpoint**: `/api/interface/fathom`

| Story | Status | Description |
|-------|--------|-------------|
| S9.10.1 | 📋 | Create FATHOM explorer interface layout |
| S9.10.2 | 📋 | Add flood type selector (fluvial/pluvial/coastal tabs) |
| S9.10.3 | 📋 | Add return period slider (5 → 1000 year) |
| S9.10.4 | 📋 | Add climate scenario dropdown |
| S9.10.5 | 📋 | Implement click-to-query (show flood profile at point) |
| S9.10.6 | 📋 | Add flood depth legend with colormap |
| S9.10.7 | 📋 | Add coverage indicator (show available tiles) |

**UI Layout**:
```
┌─────────────────────────────────────────────────────────────────────┐
│ FATHOM FLOOD DATA EXPLORER                                          │
├─────────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ [Fluvial] [Pluvial] [Coastal]          Scenario: [Baseline ▼]  │ │
│ └─────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                    ┌─────────────────────────┐                     │
│                    │                         │                     │
│                    │      [MAP VIEWER]       │                     │
│                    │                         │                     │
│                    │    Click for profile    │                     │
│                    │                         │                     │
│                    └─────────────────────────┘                     │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Return Period: [====●==================] 100 year                   │
├─────────────────────────────────────────────────────────────────────┤
│ Legend:  [0m]▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓[5m+]               │
│          Light Blue ──────────────────────► Dark Blue               │
├─────────────────────────────────────────────────────────────────────┤
│ Flood Profile at (-1.500, 6.200):                                   │
│ ┌───────────────────────────────────────────────────────────────┐  │
│ │ RP    │  5yr │ 10yr │ 20yr │ 50yr │ 100yr│ 200yr│ 500yr│1000yr│  │
│ │ Depth │ 0.0m │ 0.1m │ 0.5m │ 0.9m │ 1.2m │ 1.6m │ 2.0m │ 2.3m │  │
│ └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Files**: `web_interfaces/fathom/interface.py` (planned)

**Dependencies**:
- F9.9 (FATHOM Query API) - backend for queries
- F12.2 (HTMX Integration) - UI patterns

---

