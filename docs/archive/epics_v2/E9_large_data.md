# Epic E9: Large & Multidimensional Data

**Type**: Business
**Status**: In Progress (20% - FATHOM ETL complete, hosting pipelines pending)
**Last Updated**: 30 JAN 2026
**ADO Feature**: "Large Dataset Processing"

---

## Value Statement

Host and serve FATHOM/CMIP6-scale datasets. Specialized pipelines for data that doesn't fit standard E1/E2 patterns due to size, structure, or access requirements.

---

## Architecture

```
Raw Data                     Processing (E9)              Serving (E6)
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│ FATHOM GeoTIFFs     │     │ Band Stack +        │     │ COG Tiles       │
│ (1000s of tiles)    │────▶│ Spatial Merge       │────▶│ (TiTiler)       │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────┤
│ CMIP6 NetCDF        │     │ VirtualiZarr        │     │ Zarr Tiles      │
│ (TB-scale)          │────▶│ References          │────▶│ (TiTiler-xarray)│
└─────────────────────┘     └─────────────────────┘     └─────────────────┘
     Bronze Storage              Silver Storage           Service Layer
```

**Key Principle**: Minimize data transformation. VirtualiZarr creates lightweight references to NetCDF without conversion. FATHOM merge creates analysis-ready COGs from raw tiles.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F9.1 FATHOM ETL Operations | ✅ | Band stacking + spatial merge |
| F9.2 FATHOM Data Hosting | 📋 | End-to-end hosting pipeline |
| F9.3 VirtualiZarr Pipeline | 📋 | NetCDF → Zarr references |
| F9.4 CMIP6 Data Hosting | 📋 | Curated climate projections |
| F9.5 FATHOM Query API | 📋 | Flood-specific semantic queries |

---

## Feature Summaries

### F9.1: FATHOM ETL Operations
Two-phase processing for FATHOM flood data:
1. **Band Stack**: Merge 8 return periods into single COG (8 bands)
2. **Spatial Merge**: Combine N×N tiles into regional COG

**Job**: `fathom_band_stack`, `fathom_spatial_merge` (Docker Worker)

### F9.2: FATHOM Data Hosting (Planned)
Complete hosting pipeline:
- STAC collection with datacube extension
- Scenario-based organization (fluvial/pluvial/coastal)
- Return period metadata

### F9.3: VirtualiZarr Pipeline (Planned)
Lightweight references to legacy NetCDF:
- Kerchunk JSON references (~KB per file)
- No data conversion required
- Enables TiTiler-xarray serving

### F9.4: CMIP6 Data Hosting (Planned)
Curated subset for East Africa:
- Variables: tas, pr, tasmax, tasmin
- Scenarios: SSP2-4.5, SSP5-8.5
- Time: 2020-2100

### F9.5: FATHOM Query API (Planned)
Flood-specific semantic queries:
- `GET /api/fathom/point?flood_type=fluvial&return_period=100`
- `GET /api/fathom/profile` - All return periods at location

---

## FATHOM Data Characteristics

| Attribute | Value |
|-----------|-------|
| Coverage | Global flood hazard maps |
| Types | Fluvial, Pluvial, Coastal |
| Return Periods | 1-in-5 to 1-in-1000 year |
| Resolution | 3 arcsec (~90m) |
| Projections | Multiple climate scenarios |

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E7 Docker Worker | E8 H3 aggregation |
| Azure Blob Storage | Climate risk analysis |

---

## Implementation Details

See `docs_claude/FATHOM_ETL.md` for FATHOM pipeline details.
