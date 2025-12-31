## Epic E9: Large and Multidimensional Data 🚧

**Business Requirement**: Host and serve massive GeoTIFF and Zarr/NetCDF datasets at scale
**Status**: 🚧 PARTIAL (F9.1 🚧, F9.5 ✅)
**Last Updated**: 30 DEC 2025

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

