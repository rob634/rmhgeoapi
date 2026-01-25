# Epic E8: GeoAnalytics Pipeline

**Type**: Business
**Status**: Partial
**Last Updated**: 24 JAN 2026

---

## Value Statement

Transform raw hosted data into analysis-ready H3-aggregated outputs. Enables climate risk analysis, exposure calculations, and spatial statistics at multiple resolutions.

---

## Architecture

```
Source Data (E2, E9)           Analytics (E8)                Outputs
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────┐
│ FATHOM COGs         │      │ H3 Zonal Statistics │      │ GeoParquet      │
│ CMIP6 Zarr          │─────▶│ (rasterstats)       │─────▶│ (res 2-8, OLAP) │
├─────────────────────┤      ├─────────────────────┤      ├─────────────────┤
│ PostGIS Vectors     │─────▶│ H3 Point Aggregation│─────▶│ OGC Features    │
│ (buildings, etc.)   │      │ (SQL)               │      │ (API + download)│
└─────────────────────┘      └─────────────────────┘      └─────────────────┘
```

**Key Principle**: H3 provides the universal aggregation grid. Raster data is aggregated via zonal statistics; vector data via point-in-cell counts.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F8.1 H3 Grid Infrastructure | ✅ | Normalized schema with cell-country mappings |
| F8.2 Grid Bootstrap System | ✅ | Res 2-7 pyramid generation |
| F8.3 Raster→H3 Aggregation | ✅ | Zonal statistics from COGs to H3 cells |
| F8.4 Vector→H3 Aggregation | 📋 | Point/polygon counts aggregated to H3 |
| F8.5 H3 Export to OGC Features | ✅ | Denormalized exports for mapping |
| F8.6 GeoParquet Export | 📋 | Columnar export for OLAP analytics |
| F8.7 Building Exposure Analysis | 📋 | MS Buildings → FATHOM → H3 |

---

## Feature Summaries

### F8.1: H3 Grid Infrastructure
Normalized H3 schema in PostgreSQL:
- `h3.cells`: Cell ID, geometry, resolution
- `h3.cell_admin0`: Cell-to-country mapping
- `h3.zonal_stats`: Raster aggregation results
- `h3.source_catalog`: Data source metadata

### F8.2: Grid Bootstrap System
Three-stage cascade job generating res 2-7 pyramid:
1. Generate base cells (res 2)
2. Cascade to descendants (res 3-7)
3. Finalize with country mappings

**Job**: `bootstrap_h3_land_grid_pyramid`

### F8.3: Raster→H3 Aggregation
Zonal statistics from COGs to H3 cells:
- Stats: mean, sum, min, max, count, std, median
- Sources: Azure COGs, Planetary Computer, direct URLs
- Memory-intensive: runs in Docker Worker

**Job**: `h3_raster_aggregation`

### F8.4: Vector→H3 Aggregation (Planned)
Point/polygon counts aggregated to H3 cells:
- Building footprints → building counts per cell
- Category grouping (e.g., building type)

### F8.5: H3 Export to OGC Features
Denormalized, wide-format exports:
- Join h3.cells with h3.zonal_stats
- Pivot to wide format (one column per stat)
- Export to geo schema for OGC Features access

**Job**: `h3_export_dataset`

### F8.6: GeoParquet Export (Planned)
Columnar export for OLAP analytics:
- PostgreSQL → GeoParquet
- DuckDB/Databricks compatible

### F8.7: Building Exposure Analysis (Planned)
Climate risk exposure calculation:
1. Load MS Building Footprints
2. Sample FATHOM flood depth at building centroids
3. Aggregate to H3 (% buildings in flood zones)

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E2 Raster Data (COGs) | Exposure analysis products |
| E9 FATHOM data | Climate risk reports |
| E7 Docker Worker | External analytics tools |

---

## Implementation Details

See `docs_claude/` for implementation specifics.
