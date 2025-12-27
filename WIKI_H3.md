# H3 Hexagonal Grid System

**Last Updated**: 27 DEC 2025

---

## Overview

The H3 system provides hierarchical hexagonal grids for geospatial aggregation and analysis. H3 cells serve as the spatial foundation for:
- Country/region-scoped land grids
- Administrative boundary attribution (ISO3 countries, Admin1 regions)
- Aggregated statistics from raster and vector data sources (elevation, population, climate, etc.)

**Current Status**:
- **Cells**: 85,662 (Greece res 6 + Rwanda res 2-8)
- **Elevation Stats**: 68,260 zonal statistics (Greece cop-dem-glo-30)
- **Registered Datasets**: 1 (cop-dem-glo-30 terrain)

---

## Table of Contents

1. [Architecture](#architecture)
2. [Database Schema](#database-schema)
3. [H3 Aggregation System](#h3-aggregation-system)
4. [Bootstrap System](#bootstrap-system)
5. [Debug & Admin Endpoints](#debug--admin-endpoints)
6. [System Reference Tables](#system-reference-tables)
7. [Cell Counts & Resolution Reference](#cell-counts--resolution-reference)
8. [Technical Details](#technical-details)
9. [Troubleshooting](#troubleshooting)
10. [Files Reference](#files-reference)
11. [Future Enhancements](#future-enhancements)

---

## Architecture

### Normalized Schema Design

The H3 system uses a normalized schema separating geometry from attribution and statistics:

```
┌─────────────────────────────────────────────────────────────────┐
│                         h3.cells                                │
│  Primary storage: H3 index + geometry + hierarchy               │
│  One row per unique H3 cell                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐
│ h3.cell_admin0  │  │ h3.cell_admin1  │  │ h3.zonal_stats      │
│ ISO3 country    │  │ Admin1 region   │  │ (partitioned)       │
│ attribution     │  │ attribution     │  │ Raster statistics   │
└─────────────────┘  └─────────────────┘  └─────────────────────┘
                                                    │
                              ┌──────────────────────┼──────────────────────┐
                              ▼                      ▼                      ▼
                    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
                    │ zonal_stats_    │  │ zonal_stats_    │  │ zonal_stats_    │
                    │ terrain         │  │ climate         │  │ demographics    │
                    └─────────────────┘  └─────────────────┘  └─────────────────┘
```

**Benefits**:
- Cells stored once, attributed many times
- Efficient spatial queries on cell geometry
- Partitioned statistics tables for performance
- Clean separation of concerns
- Supports border cells belonging to multiple countries

### H3 Hierarchical Structure

Each H3 parent cell has exactly **7 children** at the next resolution level.

```
Resolution 2 (1 cell)
       │
       └── Resolution 3 (7 cells)
                  │
                  └── Resolution 4 (49 cells)
                             │
                             └── Resolution 5 (343 cells)
                                        │
                                        └── Resolution 6 (2,401 cells)
```

---

## Database Schema

### h3.cells

Primary storage for H3 cell geometry and hierarchy.

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | Primary key - H3 cell index (64-bit integer) |
| `resolution` | SMALLINT | H3 resolution (0-15) |
| `geom` | GEOMETRY(Polygon, 4326) | Cell boundary polygon |
| `center_lat` | DOUBLE PRECISION | Cell center latitude |
| `center_lon` | DOUBLE PRECISION | Cell center longitude |
| `parent_h3_index` | BIGINT | Immediate parent cell (res-1) |
| `is_land` | BOOLEAN | Land/water flag |
| `is_coastal` | BOOLEAN | Coastal zone flag |
| `source_job_id` | VARCHAR(64) | Bootstrap job that created this cell |
| `created_at` | TIMESTAMPTZ | Creation timestamp |

**Key Indexes**:
- `PRIMARY KEY (h3_index)` - Unique cell lookup
- `GiST (geom)` - Spatial queries
- `BTREE (resolution)` - Resolution filtering
- `BTREE (parent_h3_index)` - Hierarchy traversal

### h3.cell_admin0

Maps cells to ISO3 country codes (many-to-many for border cells).

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | Foreign key to cells |
| `iso3` | VARCHAR(3) | ISO 3166-1 alpha-3 country code |
| `coverage_pct` | REAL | Fraction of cell in this country (0-1) |
| `created_at` | TIMESTAMPTZ | Attribution timestamp |

**Key Indexes**:
- `UNIQUE (h3_index, iso3)` - Prevents duplicates
- `BTREE (iso3)` - Country queries (e.g., "all cells in GRC")
- `BTREE (h3_index)` - Cell queries

### h3.cell_admin1

Maps cells to Admin1 regions (states, provinces).

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | Foreign key to cells |
| `admin1_id` | VARCHAR(20) | Admin1 identifier |
| `iso3` | VARCHAR(3) | Parent country code |
| `coverage_pct` | REAL | Fraction of cell in this region |
| `created_at` | TIMESTAMPTZ | Attribution timestamp |

### h3.dataset_registry

Metadata catalog documenting all aggregated datasets.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(100) | Dataset ID (e.g., `cop-dem-glo-30`) |
| `data_category` | VARCHAR(50) | Category: `terrain`, `climate`, `demographics`, etc. |
| `theme` | VARCHAR(50) | Theme for partition routing |
| `display_name` | VARCHAR(255) | Human-readable name |
| `description` | TEXT | Detailed explanation |
| `source_name` | VARCHAR(255) | Data provider |
| `source_url` | VARCHAR(500) | Original data link |
| `source_license` | VARCHAR(100) | License (CC-BY-4.0, etc.) |
| `source_config` | JSONB | STAC collection, bands, etc. |
| `resolution_range` | INT[] | Available resolutions |
| `stat_types` | VARCHAR[] | Available statistics (mean, sum, etc.) |
| `unit` | VARCHAR(50) | Unit of measurement |
| `aggregation_job_id` | VARCHAR(64) | Last aggregation job |
| `cells_aggregated` | INTEGER | Cells with this statistic |
| `created_at` | TIMESTAMPTZ | Registration time |
| `updated_at` | TIMESTAMPTZ | Last update time |

### h3.zonal_stats (Partitioned)

Aggregated raster statistics per H3 cell. Partitioned by theme for performance.

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | H3 cell (FK to cells) |
| `dataset_id` | VARCHAR(100) | FK to dataset_registry |
| `stat_type` | VARCHAR(20) | `mean`, `sum`, `count`, `min`, `max`, `std` |
| `value` | DOUBLE PRECISION | Computed statistic |
| `pixel_count` | INTEGER | Pixels in computation |
| `theme` | VARCHAR(50) | Partition key |
| `computed_at` | TIMESTAMPTZ | Computation timestamp |

**Partitions**:
- `h3.zonal_stats_terrain` - Elevation, slope, aspect
- `h3.zonal_stats_climate` - Temperature, precipitation
- `h3.zonal_stats_demographics` - Population, density
- `h3.zonal_stats_vegetation` - NDVI, land cover
- `h3.zonal_stats_water` - Water bodies, hydrology
- `h3.zonal_stats_infrastructure` - Built environment
- `h3.zonal_stats_landcover` - Land use classification

### h3.point_stats

Aggregated point feature counts per H3 cell.

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | H3 cell |
| `source_id` | VARCHAR(100) | FK to dataset_registry |
| `category` | VARCHAR(100) | Category value (optional) |
| `count` | INTEGER | Feature count |
| `weight_sum` | DOUBLE PRECISION | Weighted sum (optional) |
| `computed_at` | TIMESTAMPTZ | Computation timestamp |

---

## H3 Aggregation System

The aggregation system computes zonal statistics from raster data sources (local COGs or Planetary Computer) and stores results in H3 cells.

### 3-Stage Aggregation Workflow

```
Stage 1: INVENTORY
    ├── Load H3 cells for scope (country, bbox, or grid)
    ├── Register dataset in h3.dataset_registry
    ├── Calculate batch count for fan-out
    └── Output: cell_count, batch_definitions

Stage 2: COMPUTE (Fan-out parallel tasks)
    ├── Each task processes one batch of cells
    ├── Fetch raster data (COG or Planetary Computer)
    ├── Compute zonal statistics (rasterstats)
    └── Insert results into h3.zonal_stats_{theme}

Stage 3: FINALIZE
    ├── Verify stat counts match expectations
    ├── Update dataset_registry provenance
    └── Output: summary with actual vs expected counts
```

### Job: h3_raster_aggregation

Aggregate raster data to H3 cells using zonal statistics.

```bash
curl -X POST "https://{base-url}/api/jobs/submit/h3_raster_aggregation" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "cop-dem-glo-30",
    "resolution": 6,
    "iso3": "RWA",
    "batch_size": 500
  }'
```

### Job Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dataset_id` | string | required | Dataset identifier (must be in dataset_registry) |
| `resolution` | int | 6 | H3 resolution to aggregate |
| `iso3` | string | null | ISO3 country filter |
| `bbox` | array | null | Bounding box `[minx, miny, maxx, maxy]` |
| `batch_size` | int | 500 | Cells per compute task |

### Supported Data Sources

#### Planetary Computer (Remote COGs)

Currently supported collections:

| Dataset ID | Collection | Description | Theme |
|------------|------------|-------------|-------|
| `cop-dem-glo-30` | cop-dem-glo-30 | Copernicus DEM 30m | terrain |

**Configuration** (in dataset_registry.source_config):
```json
{
  "type": "planetary_computer",
  "collection": "cop-dem-glo-30",
  "asset_key": "data"
}
```

#### Local COGs (Azure Blob Storage)

```json
{
  "type": "azure_blob",
  "container": "silver-cogs",
  "blob_path": "population/worldpop_2020.tif"
}
```

### Example: Elevation Aggregation for Rwanda

```bash
# 1. Ensure cells exist (seed if needed)
curl "https://{base-url}/api/h3/debug?operation=seed_country_cells&iso3=RWA&resolution=6&confirm=yes"

# 2. Submit aggregation job
curl -X POST "https://{base-url}/api/jobs/submit/h3_raster_aggregation" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "cop-dem-glo-30",
    "resolution": 6,
    "iso3": "RWA"
  }'

# 3. Monitor progress
curl "https://{base-url}/api/jobs/status/{JOB_ID}"

# 4. Query results
# Stats stored in h3.zonal_stats_terrain
```

### Computed Statistics

For each cell, the following statistics are computed:

| Stat Type | Description |
|-----------|-------------|
| `mean` | Average pixel value |
| `sum` | Sum of all pixels |
| `count` | Number of valid pixels |
| `min` | Minimum pixel value |
| `max` | Maximum pixel value |
| `std` | Standard deviation |

---

## Bootstrap System

### Job: bootstrap_h3_land_grid_pyramid

Generates H3 cells for land areas using a 3-stage cascade architecture.

```bash
curl -X POST "https://{base-url}/api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "country_filter": "GRC",
    "grid_id_prefix": "greece",
    "cascade_batch_size": 10,
    "target_resolutions": [3, 4, 5, 6]
  }'
```

### Job Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `grid_id_prefix` | string | `land` | Prefix for grid IDs |
| `country_filter` | string | null | ISO3 country code (e.g., `GRC`, `RWA`) |
| `bbox_filter` | array | null | Bounding box `[minx, miny, maxx, maxy]` |
| `spatial_filter_table` | string | `system_admin0` | PostGIS table for land filtering |
| `cascade_batch_size` | int | 10 | Parent cells per cascade task |
| `target_resolutions` | array | `[3,4,5,6,7]` | Target resolutions to generate |

---

## Debug & Admin Endpoints

All debug operations are available at `/api/h3/debug?operation={op}`.

### Schema Status

```bash
curl "https://{base-url}/api/h3/debug?operation=schema_status"
```

Returns:
- Schema existence
- Table list and row counts
- Index inventory

### Seed Country Cells (Test Seeding)

Quick seeding of H3 cells for a country without running full bootstrap job.

```bash
# Dry run - see cell count
curl "https://{base-url}/api/h3/debug?operation=seed_country_cells&iso3=RWA&resolution=6"

# Confirm insert
curl "https://{base-url}/api/h3/debug?operation=seed_country_cells&iso3=RWA&resolution=6&confirm=yes"
```

**Available Countries**:
- `GRC` - Greece
- `ALB` - Albania
- `MLT` - Malta
- `CYP` - Cyprus
- `RWA` - Rwanda

**Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iso3` | string | required | ISO3 country code |
| `resolution` | int | 6 | H3 resolution (0-10) |
| `confirm` | string | no | Set to `yes` to insert |

### Deploy/Drop Normalized Schema

```bash
# Deploy all normalized tables
curl "https://{base-url}/api/h3/debug?operation=deploy_normalized_schema&confirm=yes"

# Drop normalized tables
curl "https://{base-url}/api/h3/debug?operation=drop_normalized_schema&confirm=yes"
```

### Nuke All H3 Data

```bash
# DESTRUCTIVE - Truncates all H3 tables
curl "https://{base-url}/api/h3/debug?operation=nuke_h3&confirm=yes"
```

---

## System Reference Tables

The H3 system uses promoted datasets with system roles for discovering reference tables.

### Admin0 Boundaries

The admin0 boundaries table provides country geometries for:
- Filtering H3 cells by country
- ISO3 attribution
- Spatial intersection queries

**Registration**:
```bash
curl -X POST "https://{base-url}/api/promote" \
  -H "Content-Type: application/json" \
  -d '{
    "promoted_id": "system_admin0",
    "ogc_features_collection_id": "system_admin0",
    "title": "National Boundaries",
    "is_system_reserved": true,
    "system_role": "admin0_boundaries"
  }'
```

**Discovery** (in code):
```python
from services.promote_service import PromoteService

service = PromoteService()
admin0 = service.get_by_system_role("admin0_boundaries")
# Returns: {"promoted_id": "system_admin0", "stac_collection_id": "system_admin0", ...}
```

### System Roles

| Role | Purpose | Table |
|------|---------|-------|
| `admin0_boundaries` | Country boundaries for ISO3 attribution | `geo.system_admin0` |
| `h3_land_grid` | H3 land-only grid cells | (future) |

---

## Cell Counts & Resolution Reference

### H3 Resolution Table

| Resolution | Avg Hex Area | Avg Edge Length | Example Use |
|------------|--------------|-----------------|-------------|
| 0 | 4,357,449 km² | 1,108 km | Continental |
| 1 | 609,788 km² | 419 km | Large region |
| 2 | 86,802 km² | 158 km | Country |
| 3 | 12,393 km² | 60 km | State/Province |
| 4 | 1,770 km² | 23 km | Metro area |
| 5 | 253 km² | 8.5 km | City |
| 6 | 36 km² | 3.2 km | Neighborhood |
| 7 | 5.2 km² | 1.2 km | Block group |
| 8 | 0.74 km² | 460 m | Census block |

### Current Cell Counts

| Country | Resolution | Cells |
|---------|------------|-------|
| Greece | 6 | 17,065 |
| Rwanda | 2 | 1 |
| Rwanda | 3 | 4 |
| Rwanda | 4 | 24 |
| Rwanda | 5 | 174 |
| Rwanda | 6 | 1,199 |
| Rwanda | 7 | 8,394 |
| Rwanda | 8 | 58,801 |
| **Total** | | **85,662** |

### Current Statistics

| Dataset | Theme | Cells | Stats |
|---------|-------|-------|-------|
| cop-dem-glo-30 | terrain | 17,065 | 68,260 (4 types × cells) |

---

## Technical Details

### Planetary Computer Integration

The system uses `planetary-computer` library to access signed URLs for COG data:

```python
import planetary_computer
import pystac_client

catalog = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace
)

items = catalog.search(
    collections=["cop-dem-glo-30"],
    bbox=cell_bbox
).item_collection()

# Access signed URL
signed_href = items[0].assets["data"].href
```

### Zonal Statistics with rasterstats

```python
from rasterstats import zonal_stats

stats = zonal_stats(
    cell_geometry,  # H3 cell polygon
    raster_path,    # COG URL or local path
    stats=["mean", "sum", "count", "min", "max", "std"]
)
```

### Antimeridian Handling

H3 cells near the 180° longitude boundary have polygons that span from -179° to +179°, creating "wrapped" polygons.

**Solution**: During cell generation, skip cells where `max(longitude) - min(longitude) > 180°`.

### Idempotency

- **Cell insertion**: Uses `ON CONFLICT DO NOTHING`
- **Statistics insertion**: Uses `ON CONFLICT DO UPDATE` to refresh values
- **Batch tracking**: `h3.batch_progress` tracks completed batches

### COPY Bulk Insert

For performance, cell insertion uses PostgreSQL COPY protocol:

```python
with conn.cursor().copy("COPY h3.cells FROM STDIN") as copy:
    for cell in cells:
        copy.write_row(cell)
```

Achieves ~50,000 cells/second vs ~5,000 with INSERT.

---

## Troubleshooting

### No cells generated for country

**Cause**: Country geometry not found in system_admin0.

**Fix**:
```bash
# Check system_admin0 is registered
curl "https://{base-url}/api/promote/system_admin0"

# Check country exists in OGC Features
curl "https://{base-url}/api/features/collections/system_admin0/items?iso3=GRC&limit=1"
```

### Aggregation job fails at Stage 2

**Cause**: Planetary Computer rate limiting or network issues.

**Fix**: Reduce batch_size and retry. The job is idempotent.

### Statistics count mismatch in Stage 3

**Cause**: Some cells had no valid raster data (nodata, ocean, etc.)

**Note**: This is a warning only - aggregation still succeeds.

### "Dataset not found in registry"

**Cause**: Dataset not registered before aggregation.

**Fix**: Register dataset first:
```bash
curl -X POST "https://{base-url}/api/jobs/submit/h3_register_dataset" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "cop-dem-glo-30",
    "data_category": "terrain",
    "display_name": "Copernicus DEM 30m",
    "source_config": {
      "type": "planetary_computer",
      "collection": "cop-dem-glo-30"
    }
  }'
```

---

## Files Reference

### Jobs
| File | Purpose |
|------|---------|
| `jobs/h3_raster_aggregation.py` | 3-stage raster aggregation job |
| `jobs/h3_register_dataset.py` | Dataset registration job |
| `jobs/bootstrap_h3_land_grid_pyramid.py` | Cell generation job |

### Service Handlers
| File | Purpose |
|------|---------|
| `services/h3_aggregation/handler_inventory.py` | Stage 1: Cell inventory |
| `services/h3_aggregation/handler_compute.py` | Stage 2: Zonal statistics |
| `services/h3_aggregation/handler_finalize.py` | Stage 3: Verification |

### Infrastructure
| File | Purpose |
|------|---------|
| `infrastructure/h3_repository.py` | Database operations |
| `infrastructure/h3_schema.py` | Schema deployment |

### Admin Endpoints
| File | Purpose |
|------|---------|
| `triggers/admin/h3_debug.py` | Debug and admin operations |

---

## Future Enhancements

### Vector Point Aggregation

Aggregate point features from PostGIS tables to H3 cells.

```bash
curl -X POST ".../api/jobs/submit/h3_vector_aggregation" \
  -H "Content-Type: application/json" \
  -d '{
    "source_table": "acled_events",
    "source_id": "acled_2024",
    "geometry_type": "point",
    "resolution": 6,
    "iso3": "UKR",
    "category_column": "event_type"
  }'
```

### Line/Polygon Aggregation

- **Lines**: `ST_Intersection` + `ST_Length` (meters of road by type)
- **Polygons**: `ST_Intersection` + `ST_Area` (overlap percentage)

### Additional Planetary Computer Datasets

| Dataset | Collection | Description |
|---------|------------|-------------|
| WorldPop | - | Population density |
| ESA WorldCover | esa-worldcover | Land cover classification |
| Sentinel-2 | sentinel-2-l2a | Multispectral imagery |
| MODIS | modis-* | Vegetation indices |

### Higher Resolutions

Extend to resolutions 9-10 for detailed urban analysis:
- Res 9: ~0.11 km² (building cluster)
- Res 10: ~0.015 km² (individual buildings)

### GeoParquet Export

Export H3 grids and statistics for cloud-native analysis:
- DuckDB direct query support
- Partitioned by resolution and country
- Compressed with Zstandard

---

## References

- **H3 Documentation**: https://h3geo.org/
- **H3 Resolution Table**: https://h3geo.org/docs/core-library/restable
- **Planetary Computer**: https://planetarycomputer.microsoft.com/
- **rasterstats**: https://pythonhosted.org/rasterstats/
- **Job Creation Guide**: `docs_claude/JOB_CREATION_QUICKSTART.md`
