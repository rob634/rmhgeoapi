## Epic E8: GeoAnalytics Pipeline 🚧

**Business Requirement**: Transform raster/vector data to H3 hexagonal grid, export to GeoParquet and OGC Features
**Status**: 🚧 PARTIAL (F8.1-F8.3 ✅, F8.8 ✅, F8.9 ✅)
**Last Updated**: 30 DEC 2025

**Strategic Context**:
> E8 is the "transform and export" epic. Data hosted in E9 (FATHOM, CMIP6) gets aggregated to H3
> hexagons and exported as: (a) gargantuan GeoParquet files (res 2-8, hundreds of columns) for
> Databricks/DuckDB, or (b) OGC Feature collections for mapping and download.

**Architecture**:
```
E9: Large Data             E8: GeoAnalytics              Outputs
┌─────────────┐           ┌───────────────┐           ┌──────────────────┐
│ FATHOM COGs │──────────▶│ H3 Zonal      │──────────▶│ GeoParquet       │
│ CMIP6 Zarr  │           │ Statistics    │           │ (res 2-8, OLAP)  │
├─────────────┤           ├───────────────┤           ├──────────────────┤
│ PostGIS     │──────────▶│ H3 Point      │──────────▶│ OGC Features     │
│ Vectors     │           │ Aggregation   │           │ (API + download) │
└─────────────┘           └───────────────┘           └──────────────────┘
```

**Feature Summary**:
| Feature | Status | Description |
|---------|--------|-------------|
| F8.1 | ✅ | H3 Grid Infrastructure |
| F8.2 | ✅ | Grid Bootstrap System |
| F8.3 | ✅ | Raster→H3 Aggregation |
| F8.4 | ⬜ | Vector→H3 Aggregation |
| F8.5 | 📋 | GeoParquet Export (res 2-8, 100s columns) |
| F8.6 | 🚧 | Analytics API |
| F8.7 | 📋 | Building Exposure Analysis |
| F8.8 | ✅ | Source Catalog |
| F8.9 | ✅ | H3 Export to OGC Features (~~E14~~) |
| F8.10 | 📋 | Analytics Data Browser (~~E11~~) |
| F8.11 | 📋 | H3 Visualization UI (~~E11~~) |
| F8.12 | 📋 | Analytics Export UI (~~E11~~) |

### Feature F8.1: H3 Grid Infrastructure ✅

**Deliverable**: Normalized H3 schema with cell-country mappings

| Story | Status | Description |
|-------|--------|-------------|
| S8.1.1 | ✅ | Design normalized schema (cells, cell_admin0, cell_admin1) |
| S8.1.2 | ✅ | Create stat_registry metadata catalog |
| S8.1.3 | ✅ | Create zonal_stats table for raster aggregations |
| S8.1.4 | ✅ | Create point_stats table for vector aggregations |
| S8.1.5 | ✅ | Create batch_progress table for idempotency |
| S8.1.6 | ✅ | Implement H3Repository with COPY-based bulk inserts |

**Key Files**: `infrastructure/h3_schema.py`, `infrastructure/h3_repository.py`, `infrastructure/h3_batch_tracking.py`

---

### Feature F8.2: Grid Bootstrap System ✅

**Deliverable**: 3-stage cascade job generating res 2-7 pyramid

| Story | Status | Description |
|-------|--------|-------------|
| S8.2.1 | ✅ | Create generate_h3_grid handler (base + cascade modes) |
| S8.2.2 | ✅ | Create cascade_h3_descendants handler (multi-level) |
| S8.2.3 | ✅ | Create finalize_h3_pyramid handler |
| S8.2.4 | ✅ | Create bootstrap_h3_land_grid_pyramid job |
| S8.2.5 | ✅ | Implement batch-level idempotency (resumable jobs) |
| S8.2.6 | ✅ | Add country/bbox filtering for testing |

**Key Files**: `jobs/bootstrap_h3_land_grid_pyramid.py`, `services/handler_generate_h3_grid.py`, `services/handler_cascade_h3_descendants.py`, `services/handler_finalize_h3_pyramid.py`

**Expected Cell Counts** (land-filtered):
- Res 2: ~2,000 | Res 3: ~14,000 | Res 4: ~98,000
- Res 5: ~686,000 | Res 6: ~4.8M | Res 7: ~33.6M

---

### Feature F8.3: Raster→H3 Aggregation ✅ COMPLETE

**Deliverable**: Zonal statistics from COGs to H3 cells
**Completed**: 27 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S8.3.1 | ✅ | Create h3_raster_aggregation job definition |
| S8.3.2 | ✅ | Design 3-stage workflow (inventory → compute → finalize) |
| S8.3.3 | ✅ | Implement h3_inventory_cells handler |
| S8.3.4 | ✅ | Implement h3_raster_zonal_stats handler |
| S8.3.5 | ✅ | Implement h3_aggregation_finalize handler |
| S8.3.6 | ✅ | Create insert_zonal_stats_batch() repository method |
| S8.3.7 | ✅ | Add dynamic STAC tile discovery for Planetary Computer (27 DEC) |
| S8.3.8 | ✅ | Add theme-based zonal_stats partitioning (8 partitions) |

**Key Files**:
- `jobs/h3_raster_aggregation.py`
- `services/h3_aggregation/handler_inventory.py`
- `services/h3_aggregation/handler_raster_zonal.py`
- `services/h3_aggregation/handler_finalize.py`

**Stats Supported**: mean, sum, min, max, count, std, median

**Source Types Supported**:
- `azure`: Azure Blob Storage COGs (container + blob_path)
- `planetary_computer`: Planetary Computer STAC (collection + item_id OR source_id for dynamic discovery)
- `url`: Direct HTTPS URLs to COGs

---

### Feature F8.4: Vector→H3 Aggregation ⬜ READY

**Deliverable**: Point/polygon counts aggregated to H3 cells

| Story | Status | Description |
|-------|--------|-------------|
| S8.4.1 | ⬜ | Create h3_vector_aggregation job |
| S8.4.2 | ⬜ | Implement point-in-polygon handler |
| S8.4.3 | ⬜ | Implement category grouping |
| S8.4.4 | ✅ | Create insert_point_stats_batch() repository method |

**Schema Ready**: `h3.point_stats` table exists

---

### Feature F8.5: GeoParquet Export 📋 PLANNED

**Deliverable**: Columnar export for OLAP analytics

| Story | Status | Description |
|-------|--------|-------------|
| S8.5.1 | 📋 | Design export job parameters |
| S8.5.2 | 📋 | Implement PostgreSQL → GeoParquet writer |
| S8.5.3 | 📋 | Add DuckDB/Databricks compatibility |
| S8.5.4 | 📋 | Create export_h3_stats job |

---

### Feature F8.6: Analytics API 🚧 PARTIAL

**Deliverable**: Query endpoints for H3 statistics

| Story | Status | Description |
|-------|--------|-------------|
| S8.6.1 | 📋 | GET /api/h3/stats/{dataset_id} |
| S8.6.2 | ✅ | GET /api/h3/stats?iso3=&resolution= (cell counts) |
| S8.6.3 | ✅ | GET /api/h3/stats/countries (country list with counts) |
| S8.6.4 | 📋 | Interactive H3 map interface |

**Key Files**: `web_interfaces/h3_sources/interface.py`

---

### Feature F8.7: Building Exposure Analysis 📋 HIGH PRIORITY

**Deliverable**: Buildings → Raster Extract → H3 Aggregation pipeline
**Documentation**: [BUILDING_EXPOSURE_PIPELINE.md](docs_claude/BUILDING_EXPOSURE_PIPELINE.md)
**Timeline**: ~1 week
**Business Value**: Climate risk exposure analysis for high-profile projects

**Workflow**:
```
Buildings (MS/Google) → Centroids → Raster Sample → H3 Aggregate → GeoParquet
```

| Story | Status | Description |
|-------|--------|-------------|
| S8.7.1 | 📋 | Create `h3.building_exposure` schema |
| S8.7.2 | 📋 | Create `building_exposure_analysis` job definition |
| S8.7.3 | 📋 | Stage 1: `building_centroid_extract` handler |
| S8.7.4 | 📋 | Stage 2: `building_raster_sample` handler (rasterstats) |
| S8.7.5 | 📋 | Stage 3: `building_h3_aggregate` handler (SQL aggregation) |
| S8.7.6 | 📋 | Stage 4: `h3_export_geoparquet` handler |
| S8.7.7 | 📋 | Query API endpoints |
| S8.7.8 | 📋 | End-to-end test: Kenya + FATHOM + MS Buildings |

**Output per H3 Cell**:
- `building_count`: Total buildings
- `mean_exposure`: Average raster value
- `max_exposure`: Maximum raster value
- `pct_exposed_{threshold}`: % buildings above threshold
- `count_exposed_{threshold}`: Count above threshold

**Dependencies**:
- E10.F10.2 (FATHOM merge) for flood COGs
- Planetary Computer for MS Building Footprints
- rasterstats + geopandas for processing

---

### Feature F8.8: Source Catalog ✅ COMPLETE

**Deliverable**: Comprehensive metadata catalog for H3 aggregation data sources
**Completed**: 27 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S8.8.1 | ✅ | Create `h3.source_catalog` table schema |
| S8.8.2 | ✅ | Implement H3SourceRepository with full CRUD |
| S8.8.3 | ✅ | Create REST API endpoints (GET/POST/PATCH/DELETE /api/h3/sources) |
| S8.8.4 | ✅ | Support Planetary Computer, Azure Blob, URL, PostGIS source types |
| S8.8.5 | ✅ | Integrate with h3_raster_zonal_stats for dynamic tile discovery |

**Key Files**:
- `infrastructure/h3_schema.py` (source_catalog table)
- `infrastructure/h3_source_repository.py`
- `web_interfaces/h3_sources/interface.py`

**Source Catalog Fields**:
- Identity: id, display_name, description
- Connection: source_type, stac_api_url, collection_id, asset_key
- Tile pattern: item_id_pattern, tile_size_degrees, tile_naming_convention
- Raster properties: native_resolution_m, crs, data_type, nodata_value, value_range
- Aggregation: theme (partition key), recommended_stats, recommended_h3_res_min/max
- Provenance: source_provider, source_url, source_license, citation

---

### Feature F8.9: H3 Export to OGC Features ✅ (formerly E14)

**Deliverable**: Denormalized, wide-format exports from H3 zonal_stats for mapping and download
**Completed**: 28 DEC 2025
**Use Case**: "I want a specific map" or "I want a copy of a specific extract" (NOT for analytics)

| Story | Status | Description |
|-------|--------|-------------|
| S8.9.1 | ✅ | Create `h3_export_dataset` job definition (3-stage workflow) |
| S8.9.2 | ✅ | Validate handler (check table doesn't exist or overwrite=true) |
| S8.9.3 | ✅ | Build handler (join h3.cells with h3.zonal_stats, pivot to wide format) |
| S8.9.4 | ✅ | Register handler (update export catalog) |
| S8.9.5 | ✅ | Support multiple geometry options (polygon/centroid) |
| S8.9.6 | ✅ | Support spatial scope filtering (iso3, bbox, polygon_wkt) |

**Key Files**:
- `jobs/h3_export_dataset.py`
- `services/h3_aggregation/handler_export.py`

**Output Table**:
```sql
geo.{table_name}
├── h3_index BIGINT PRIMARY KEY
├── geom GEOMETRY(Polygon/Point, 4326)
├── iso3 VARCHAR(3)          -- optional
├── {dataset_id}_{stat_type} -- pivot columns
└── ...
```

**Usage**:
```bash
POST /api/jobs/submit/h3_export_dataset
{
    "table_name": "rwanda_terrain_res6",
    "resolution": 6,
    "iso3": "RWA",
    "variables": [
        {"dataset_id": "cop_dem_rwanda_res6", "stat_types": ["mean", "min", "max"]}
    ],
    "geometry_type": "polygon",
    "overwrite": false
}
```

---

### Feature F8.10: Analytics Data Browser 📋 (~~E11~~)

**Deliverable**: STAC + Promoted datasets gallery view for analytics exploration

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S8.10.1 | 📋 | STAC collection browser with search | `/api/stac/*` ✅ |
| S8.10.2 | 📋 | Promoted datasets gallery view | `/api/promote/gallery` ✅ |
| S8.10.3 | 📋 | Preview thumbnails from TiTiler | TiTiler ✅ |
| S8.10.4 | 📋 | Click to view on map | TiTiler ✅ |

---

### Feature F8.11: H3 Visualization UI 📋 (~~E11~~)

**Deliverable**: Hexagonal analytics visualization with drill-down (KEY FEATURE)

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S8.11.1 | 📋 | H3 hexagon layer (Mapbox GL + deck.gl) | `/api/h3/stats/*/cells` (F8.6) |
| S8.11.2 | 📋 | Resolution switcher (zoom mapping) | H3 pyramid ✅ |
| S8.11.3 | 📋 | Click hexagon → drill to children | H3 schema ✅ |
| S8.11.4 | 📋 | Choropleth styling by stat value | OGC Styles ✅ |
| S8.11.5 | 📋 | Country/Admin filter | `/api/h3/stats?iso3=` (F8.6) |
| S8.11.6 | 📋 | Time slider for temporal stats | xarray service ✅ |

**Blockers**: Requires F8.3 (H3 aggregation handlers) + F8.6 (H3 API)

---

### Feature F8.12: Analytics Export UI 📋 (~~E11~~)

**Deliverable**: Export capabilities for external tools

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S8.12.1 | 📋 | Export H3 stats as GeoParquet | `/api/h3/export` (F8.5) |
| S8.12.2 | 📋 | DuckDB SQL preview (WASM) | Client-side |
| S8.12.3 | 📋 | Copy tile URL for other tools | TiTiler URLs ✅ |
| S8.12.4 | 📋 | STAC item JSON download | `/api/stac/items/*` ✅ |

---

---

