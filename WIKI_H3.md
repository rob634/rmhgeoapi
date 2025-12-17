# H3 Hexagonal Grid System

**Last Updated**: 17 DEC 2025

---

## Overview

The H3 system provides hierarchical hexagonal grids for geospatial aggregation and analysis. H3 cells serve as the spatial foundation for:
- Country/region-scoped land grids
- Administrative boundary attribution (ISO3 countries, Admin1 regions)
- Aggregated statistics from raster and vector data sources

**Current Status**: Bootstrap system operational with Greece (res 6) populated.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Database Schema](#database-schema)
3. [Bootstrap System](#bootstrap-system)
4. [Debug & Admin Endpoints](#debug--admin-endpoints)
5. [Cell Counts & Resolution Reference](#cell-counts--resolution-reference)
6. [Technical Details](#technical-details)
7. [Troubleshooting](#troubleshooting)
8. [Files Reference](#files-reference)
9. [Future Enhancements](#future-enhancements)

---

## Architecture

### Two-Table Design

The H3 system uses a normalized schema separating geometry from attribution:

```
┌─────────────────────────────────────────────────────────────────┐
│                         h3.cells                                │
│  Primary storage: H3 index + geometry + hierarchy               │
│  One row per unique H3 cell                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ h3.cell_admin0  │  │ h3.cell_admin1  │  │ h3.zonal_stats  │
│ ISO3 country    │  │ Admin1 region   │  │ Raster stats    │
│ attribution     │  │ attribution     │  │ (FUTURE)        │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

**Benefits**:
- Cells stored once, attributed many times
- Efficient spatial queries on cell geometry
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

### 3-Stage Bootstrap Workflow

```
Stage 1: Generate Base Grid (Resolution 2)
    ↓
Stage 2: Cascade to Higher Resolutions (3-7)
    ↓
Stage 3: Verify & Finalize
```

**Stage 1 - Base Generation**:
- Generates all H3 cells globally at resolution 2 (~5,882 cells)
- Filters by country geometry or bounding box
- Stores filtered cells in `h3.cells` table

**Stage 2 - Cascade Generation**:
- Reads parent cells from Stage 1
- Generates 7 children per parent for each target resolution
- Batched parallel execution (configurable batch size)
- Inherits parent lineage for hierarchy tracking

**Stage 3 - Finalization**:
- Verifies 7:1 ratio between adjacent resolutions
- Updates grid metadata with completion status
- Runs VACUUM ANALYZE for query optimization

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
| `coverage_fraction` | REAL | Fraction of cell in this country (0-1) |
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
| `coverage_fraction` | REAL | Fraction of cell in this region |
| `created_at` | TIMESTAMPTZ | Attribution timestamp |

### Legacy Tables

The following tables are from the original bootstrap system and remain operational:

| Table | Purpose |
|-------|---------|
| `h3.grids` | Original cell storage with grid_id grouping |
| `h3.grid_metadata` | Grid generation status tracking |
| `h3.batch_progress` | Batch-level idempotency tracking |
| `h3.reference_filters` | Pre-computed parent cell arrays |

#### h3.grids (Legacy)

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Auto-increment primary key |
| `h3_index` | BIGINT | H3 cell index (64-bit integer) |
| `resolution` | INTEGER | H3 resolution (0-15) |
| `geom` | GEOMETRY(Polygon, 4326) | Cell boundary polygon |
| `grid_id` | VARCHAR(255) | Grid identifier (e.g., `greece_res6`) |
| `grid_type` | VARCHAR(50) | Grid type (e.g., `land`) |
| `parent_res2` | BIGINT | Ancestor cell at resolution 2 |
| `parent_h3_index` | BIGINT | Immediate parent cell |
| `source_job_id` | VARCHAR(255) | Job that created this cell |
| `is_land` | BOOLEAN | Land/water flag |
| `country_code` | VARCHAR(3) | ISO3 country code |
| `created_at` | TIMESTAMPTZ | Creation timestamp |

---

## Bootstrap System

### Job: bootstrap_h3_land_grid_pyramid

Generates H3 cells for land areas using a 3-stage cascade architecture.

### Submit Bootstrap Job

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
| `grid_id_prefix` | string | `land` | Prefix for grid IDs (e.g., `greece` → `greece_res6`) |
| `country_filter` | string | null | ISO3 country code (e.g., `GRC`, `USA`) |
| `bbox_filter` | array | null | Bounding box `[minx, miny, maxx, maxy]` |
| `spatial_filter_table` | string | `system_admin0` | PostGIS table for land filtering |
| `cascade_batch_size` | int | 10 | Parent cells per cascade task |
| `target_resolutions` | array | `[3,4,5,6,7]` | Target resolutions to generate |

### Example Workflows

#### Country-Scoped (Greece)

```bash
# 1. Submit job
curl -X POST ".../api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "country_filter": "GRC",
    "grid_id_prefix": "greece",
    "target_resolutions": [3, 4, 5, 6]
  }'

# 2. Monitor progress
curl ".../api/jobs/status/{JOB_ID}"

# 3. Verify results
curl ".../api/h3/debug?operation=grid_summary"

# 4. Query bounding box (should be ~19-30°E, 34-42°N)
psql -c "SELECT grid_id, COUNT(*),
         ST_XMin(ST_Extent(geom)), ST_XMax(ST_Extent(geom))
         FROM h3.grids GROUP BY grid_id;"

# Result: 176,472 cells at resolution 6
# Plus 196,079 cell_admin0 attributions (GRC)
```

#### Global Land Grid

```bash
# Full global run (no country_filter)
curl -X POST ".../api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "grid_id_prefix": "land",
    "cascade_batch_size": 10,
    "target_resolutions": [3, 4, 5, 6, 7]
  }'
```

**Expected runtime**: 3-6 hours for ~39M cells globally.

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
- Schema ownership info

### Grid Summary

```bash
curl "https://{base-url}/api/h3/debug?operation=grid_summary"
```

Returns metadata for all grids including status, cell counts, and job IDs.

### Grid Details

```bash
curl "https://{base-url}/api/h3/debug?operation=grid_details&grid_id=greece_res6"
```

### Sample Cells

```bash
curl "https://{base-url}/api/h3/debug?operation=sample_cells&grid_id=greece_res6&limit=10&is_land=true"
```

### Parent-Child Check

```bash
curl "https://{base-url}/api/h3/debug?operation=parent_child_check&parent_id={H3_INDEX}"
```

Validates 7:1 parent-child relationships.

### Reference Filters

```bash
# List all filters
curl "https://{base-url}/api/h3/debug?operation=reference_filters"

# Filter details with IDs
curl "https://{base-url}/api/h3/debug?operation=reference_filter_details&filter_name=land_res2&include_ids=true"
```

### Delete Grids by Prefix

```bash
# Dry run
curl "https://{base-url}/api/h3/debug?operation=delete_grids&grid_id_prefix=test"

# Confirm delete
curl "https://{base-url}/api/h3/debug?operation=delete_grids&grid_id_prefix=test&confirm=yes"
```

### Nuke All H3 Data

```bash
# Truncates all H3 tables - DESTRUCTIVE!
curl "https://{base-url}/api/h3/debug?operation=nuke_h3&confirm=yes"
```

### Deploy/Drop Normalized Schema

```bash
# Deploy cells, cell_admin0, cell_admin1, zonal_stats, point_stats
curl "https://{base-url}/api/h3/debug?operation=deploy_normalized_schema&confirm=yes"

# Drop normalized tables (preserves legacy h3.grids)
curl "https://{base-url}/api/h3/debug?operation=drop_normalized_schema&confirm=yes"
```

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

### 7:1 Cascade Example (Albania)

| Resolution | Cells | Calculation |
|------------|-------|-------------|
| Res 2 | 2 | Base (filtered) |
| Res 3 | 14 | 2 × 7 |
| Res 4 | 98 | 14 × 7 |
| Res 5 | 686 | 98 × 7 |
| Res 6 | 4,802 | 686 × 7 |
| Res 7 | 33,614 | 4,802 × 7 |

### Global Land Estimates

| Resolution | Land Cells | Processing Time |
|------------|------------|-----------------|
| Res 4 | ~98,000 | ~5 min |
| Res 5 | ~686,000 | ~20 min |
| Res 6 | ~4.8M | ~2 hours |
| Res 7 | ~33.6M | ~6 hours |

---

## Technical Details

### Antimeridian Handling

H3 cells near the 180° longitude boundary have polygons that span from -179° to +179°, creating "wrapped" polygons that appear to span the globe.

**Solution**: During cell generation, skip cells where `max(longitude) - min(longitude) > 180°`.

```python
# Skip antimeridian-crossing cells
lngs = [c[0] for c in coords]
if max(lngs) - min(lngs) > 180:
    continue  # Skip this cell
```

### Idempotency

The bootstrap job is idempotent at the batch level:

1. **Stage 1**: Uses `ON CONFLICT DO NOTHING` for cell inserts
2. **Stage 2**: Tracks completed batches in `h3.batch_progress`
3. **Resume**: Resubmitting a job skips already-completed batches

### Verification

Stage 3 verifies the 7:1 ratio with 5% tolerance:

```python
ratio = actual_count / (previous_count * 7)
passed = 0.95 <= ratio <= 1.05
```

### COPY Bulk Insert

For performance, cell insertion uses PostgreSQL COPY protocol:

```python
# Stream cells directly to database
with conn.cursor().copy("COPY h3.cells FROM STDIN") as copy:
    for cell in cells:
        copy.write_row(cell)
```

This achieves ~50,000 cells/second vs ~5,000 with INSERT.

---

## Troubleshooting

### Stage 1 Fails - No cells generated

**Cause**: Country geometry not found or no H3 cells intersect.

**Debug**:
```bash
# Check country exists
psql -c "SELECT iso3, name FROM geo.system_admin0 WHERE iso3 = 'GRC';"

# Check H3 cell count
curl ".../api/h3/debug?operation=schema_status"
```

### Stage 2 Creates Wrong Number of Batches

**Cause**: `cells_inserted` count unreliable with COPY optimization.

**Fix**: Job now queries database directly for parent count.

### Bounding Box Spans -180 to +180

**Cause**: Antimeridian-crossing cells included in grid.

**Fix**: Cells crossing the antimeridian are now skipped during generation.

### KeyError: 0 in insert_h3_cells

**Cause**: psycopg3 RealDictCursor returns dict rows, not tuples.

**Fix**: Use `cur.fetchone()['count']` instead of `cur.fetchone()[0]`.

### Schema Ownership Errors

**Cause**: h3 schema owned by different database user than app.

**Debug**:
```bash
curl ".../api/h3/debug?operation=schema_status"
# Check schema_ownership and ownership_ok fields
```

**Fix**: Run as schema owner:
```sql
ALTER SCHEMA h3 OWNER TO rmhpgflexadmin;
ALTER TABLE h3.cells OWNER TO rmhpgflexadmin;
-- ... repeat for all tables
```

### Cleanup

```bash
# Delete specific grid prefix
curl ".../api/h3/debug?operation=delete_grids&grid_id_prefix=test&confirm=yes"

# Nuclear option - truncate all H3 tables
curl ".../api/h3/debug?operation=nuke_h3&confirm=yes"
```

---

## Files Reference

### Job Definition
- `jobs/bootstrap_h3_land_grid_pyramid.py` - 3-stage job orchestration

### Task Handlers
- `services/handler_generate_h3_grid.py` - Stage 1: Base generation
- `services/handler_cascade_h3_descendants.py` - Stage 2: Cascade
- `services/handler_finalize_h3_pyramid.py` - Stage 3: Finalization

### Infrastructure
- `infrastructure/h3_repository.py` - Database operations (COPY bulk insert)
- `infrastructure/h3_schema.py` - Schema deployment
- `infrastructure/h3_batch_tracking.py` - Batch idempotency

### Admin Endpoints
- `triggers/admin/h3_debug.py` - Debug and admin operations

### SQL Schema
- `sql/init/00_create_h3_schema.sql` - Schema creation
- `sql/init/02_create_h3_grids_table.sql` - Main grids table
- `sql/init/07_create_h3_batch_progress.sql` - Batch tracking

---

## Future Enhancements

The following features are planned but not yet implemented.

### Statistics Registry *(FUTURE)*

A metadata catalog documenting all aggregated datasets.

**Table: h3.stat_registry**

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(100) | Dataset ID (e.g., `worldpop_2020`) |
| `stat_category` | VARCHAR(50) | `raster_zonal`, `vector_point`, etc. |
| `display_name` | VARCHAR(255) | Human-readable name |
| `description` | TEXT | Detailed explanation |
| `source_name` | VARCHAR(255) | Data provider |
| `source_url` | VARCHAR(500) | Original data link |
| `source_license` | VARCHAR(100) | License (CC-BY-4.0, etc.) |
| `resolution_range` | INT[] | Available resolutions |
| `stat_types` | VARCHAR[] | Available statistics |
| `unit` | VARCHAR(50) | Unit of measurement |
| `last_aggregation_at` | TIMESTAMPTZ | Last update time |
| `cell_count` | INTEGER | Cells with this statistic |

**Purpose**: Self-documenting catalog of available aggregation datasets.

---

### Raster Zonal Statistics *(FUTURE)*

Aggregate raster data (COGs) to H3 cells using zonal statistics.

**Job: h3_raster_aggregation**

```bash
curl -X POST ".../api/jobs/submit/h3_raster_aggregation" \
  -H "Content-Type: application/json" \
  -d '{
    "container": "silver-cogs",
    "blob_path": "population/worldpop_2020.tif",
    "dataset_id": "worldpop_2020",
    "resolution": 6,
    "iso3": "GRC",
    "stats": ["sum", "mean", "count"]
  }'
```

**Stages**:
1. **Inventory Cells** - Load H3 cells for scope, calculate batches
2. **Compute Stats** - Fan-out: rasterstats zonal statistics per batch
3. **Finalize** - Update registry, verify counts

**Output Table: h3.zonal_stats**

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | H3 cell |
| `dataset_id` | VARCHAR(100) | Foreign key to stat_registry |
| `band` | SMALLINT | Raster band number |
| `stat_type` | VARCHAR(20) | `mean`, `sum`, `count`, etc. |
| `value` | DOUBLE PRECISION | Computed statistic |
| `computed_at` | TIMESTAMPTZ | Computation timestamp |

---

### Vector Point Aggregation *(FUTURE)*

Aggregate point features from PostGIS tables to H3 cells.

**Job: h3_vector_aggregation**

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

**Output Table: h3.point_stats**

| Column | Type | Description |
|--------|------|-------------|
| `h3_index` | BIGINT | H3 cell |
| `source_id` | VARCHAR(100) | Foreign key to stat_registry |
| `category` | VARCHAR(100) | Category value (optional) |
| `count` | INTEGER | Feature count |
| `weight_sum` | DOUBLE PRECISION | Weighted sum (optional) |
| `computed_at` | TIMESTAMPTZ | Computation timestamp |

---

### Planetary Computer Integration *(FUTURE)*

Aggregate Planetary Computer STAC catalog COGs to H3 cells.

**Job: h3_planetary_computer**

```bash
curl -X POST ".../api/jobs/submit/h3_planetary_computer" \
  -H "Content-Type: application/json" \
  -d '{
    "collection": "sentinel-2-l2a",
    "datetime_range": "2024-01-01/2024-03-31",
    "dataset_id": "sentinel2_2024q1",
    "resolution": 7,
    "iso3": "KEN",
    "band": "B04",
    "stats": ["mean", "std"]
  }'
```

**Workflow**:
1. Search STAC catalog for matching items
2. Fetch COG windows using signed URLs
3. Compute zonal statistics per H3 cell batch
4. Store results in h3.zonal_stats

---

### Line/Polygon Aggregation *(FUTURE)*

Extend vector aggregation to support:
- **Lines**: `ST_Intersection` + `ST_Length` (meters of road by type)
- **Polygons**: `ST_Intersection` + `ST_Area` (overlap percentage)

---

### Higher Resolutions *(FUTURE)*

Extend bootstrap to resolutions 8-10 for detailed urban analysis:
- Res 8: ~0.74 km² (census block level)
- Res 9: ~0.11 km² (building cluster)
- Res 10: ~0.015 km² (individual buildings)

---

### STAC Integration *(FUTURE)*

Publish H3 grids as STAC items for discoverability:
- Collection per resolution/scope
- Items with cell counts and bbox
- Links to GeoParquet exports

---

### GeoParquet Export *(FUTURE)*

Export H3 grids and statistics for cloud-native analysis:
- DuckDB direct query support
- Partitioned by resolution and country
- Compressed with Zstandard

---

## References

- **H3 Documentation**: https://h3geo.org/
- **H3 Resolution Table**: https://h3geo.org/docs/core-library/restable
- **Job Creation Guide**: `docs_claude/JOB_CREATION_QUICKSTART.md`
- **Architecture Reference**: `docs_claude/ARCHITECTURE_REFERENCE.md`
