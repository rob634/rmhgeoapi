# H3 Grid Bootstrap System

**Last Updated**: 17 DEC 2025

## Overview

The H3 Bootstrap system generates hierarchical H3 hexagonal grids for land areas, storing them in PostGIS for spatial analysis and aggregation workflows.

**Key Features**:
- 3-stage cascade architecture for efficient grid generation
- Country/region filtering via ISO3 codes or bounding boxes
- Antimeridian-safe polygon generation
- 7:1 parent-child ratio verification
- Batch-level idempotency for resumable jobs

---

## Architecture

### 3-Stage Workflow

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
- Stores filtered cells in `h3.grids` table

**Stage 2 - Cascade Generation**:
- Reads parent cells from Stage 1
- Generates 7 children per parent for each target resolution
- Batched parallel execution (configurable batch size)
- Inherits parent lineage for hierarchy tracking

**Stage 3 - Finalization**:
- Verifies 7:1 ratio between adjacent resolutions
- Updates `h3.grid_metadata` with completion status
- Runs VACUUM ANALYZE for query optimization

---

## Database Schema

### h3.grids Table

Primary storage for H3 cells.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Auto-increment primary key |
| `h3_index` | BIGINT | H3 cell index (64-bit integer) |
| `resolution` | INTEGER | H3 resolution (0-15) |
| `geom` | GEOMETRY(Polygon, 4326) | Cell boundary polygon |
| `grid_id` | VARCHAR(255) | Grid identifier (e.g., `albania_res2`) |
| `grid_type` | VARCHAR(50) | Grid type (e.g., `land`) |
| `parent_res2` | BIGINT | Ancestor cell at resolution 2 |
| `parent_h3_index` | BIGINT | Immediate parent cell |
| `source_job_id` | VARCHAR(255) | Job that created this cell |
| `is_land` | BOOLEAN | Land/water flag (optional) |
| `country_code` | VARCHAR(3) | ISO3 country code (optional) |
| `created_at` | TIMESTAMPTZ | Creation timestamp |

**Key Indexes**:
- `UNIQUE (h3_index, grid_id)` - Prevents duplicate cells per grid
- `GiST (geom)` - Spatial queries
- `BTREE (grid_id)` - Grid filtering
- `BTREE (resolution)` - Resolution filtering
- `BTREE (parent_res2)` - Hierarchy queries

### h3.grid_metadata Table

Tracks grid generation status.

| Column | Type | Description |
|--------|------|-------------|
| `grid_id` | VARCHAR(255) | Primary key |
| `resolution` | INTEGER | H3 resolution |
| `status` | VARCHAR(50) | Generation status |
| `cell_count` | INTEGER | Total cells in grid |
| `source_job_id` | VARCHAR(255) | Bootstrap job ID |

### h3.batch_progress Table

Tracks batch completion for idempotency.

| Column | Type | Description |
|--------|------|-------------|
| `batch_id` | VARCHAR(255) | Batch identifier |
| `job_id` | VARCHAR(255) | Parent job ID |
| `stage_number` | INTEGER | Stage (1, 2, or 3) |
| `status` | VARCHAR(50) | Batch status |
| `completed_at` | TIMESTAMPTZ | Completion time |

---

## API Usage

### Submit Bootstrap Job

```bash
curl -X POST "https://{base-url}/api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "country_filter": "ALB",
    "grid_id_prefix": "albania",
    "cascade_batch_size": 10,
    "target_resolutions": [3, 4, 5, 6, 7]
  }'
```

### Job Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `grid_id_prefix` | string | `land` | Prefix for grid IDs (e.g., `albania` → `albania_res2`) |
| `country_filter` | string | null | ISO3 country code (e.g., `ALB`, `USA`) |
| `bbox_filter` | array | null | Bounding box `[minx, miny, maxx, maxy]` |
| `spatial_filter_table` | string | `system_admin0` | PostGIS table for land filtering |
| `cascade_batch_size` | int | 10 | Parent cells per cascade task |
| `target_resolutions` | array | `[3,4,5,6,7]` | Target resolutions to generate |

### Check Job Status

```bash
curl "https://{base-url}/api/jobs/status/{JOB_ID}"
```

### Debug Endpoints

```bash
# Grid summary
curl "https://{base-url}/api/h3/debug?operation=grid_summary"

# Grid details
curl "https://{base-url}/api/h3/debug?operation=grid_details&grid_id=albania_res2"

# Sample cells
curl "https://{base-url}/api/h3/debug?operation=sample_cells&grid_id=albania_res2&limit=10"

# Schema status
curl "https://{base-url}/api/h3/debug?operation=schema_status"

# Delete grids by prefix
curl "https://{base-url}/api/h3/debug?operation=delete_grids&grid_id_prefix=test&confirm=yes"

# Nuke all H3 data (destructive!)
curl "https://{base-url}/api/h3/debug?operation=nuke_h3&confirm=yes"
```

---

## Cell Counts & Ratios

### H3 7:1 Ratio

Each H3 parent cell has exactly 7 children at the next resolution level.

**Example - Albania**:
| Resolution | Cells | Calculation |
|------------|-------|-------------|
| Res 2 | 2 | Base (filtered) |
| Res 3 | 14 | 2 × 7 |
| Res 4 | 98 | 14 × 7 |
| Res 5 | 686 | 98 × 7 |
| Res 6 | 4,802 | 686 × 7 |
| Res 7 | 33,614 | 4,802 × 7 |

### Global Estimates (Land-Filtered)

| Resolution | Approx Cells | Hex Size |
|------------|--------------|----------|
| Res 2 | ~2,000 | ~86,745 km² |
| Res 3 | ~14,000 | ~12,392 km² |
| Res 4 | ~98,000 | ~1,770 km² |
| Res 5 | ~686,000 | ~252 km² |
| Res 6 | ~4.8M | ~36 km² |
| Res 7 | ~33.6M | ~5.16 km² |

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
- `infrastructure/h3_batch_tracking.py` - Batch idempotency tracking

### SQL Schema
- `sql/init/00_create_h3_schema.sql` - Schema creation
- `sql/init/02_create_h3_grids_table.sql` - Main grids table
- `sql/init/07_create_h3_batch_progress.sql` - Batch tracking

### Debug Endpoints
- `triggers/admin/h3_debug.py` - Debug and admin operations

---

## Example Workflows

### Country-Scoped Test (Albania)

```bash
# 1. Submit job
curl -X POST ".../api/jobs/submit/bootstrap_h3_land_grid_pyramid" \
  -H "Content-Type: application/json" \
  -d '{
    "country_filter": "ALB",
    "grid_id_prefix": "albania",
    "cascade_batch_size": 10
  }'

# 2. Monitor progress
curl ".../api/jobs/status/{JOB_ID}"

# 3. Verify results
curl ".../api/h3/debug?operation=grid_summary"

# 4. Query bounding box (should be ~17-23°E, 39-45°N)
psql -c "SELECT grid_id, COUNT(*),
         ST_XMin(ST_Extent(geom)), ST_XMax(ST_Extent(geom))
         FROM h3.grids GROUP BY grid_id;"
```

### Global Land Grid

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

### Cleanup

```bash
# Delete specific grid prefix
curl ".../api/h3/debug?operation=delete_grids&grid_id_prefix=test&confirm=yes"

# Nuclear option - truncate all H3 tables
curl ".../api/h3/debug?operation=nuke_h3&confirm=yes"
```

---

## Troubleshooting

### Stage 1 Fails - No cells generated

**Cause**: Country geometry not found or no H3 cells intersect.

**Debug**:
```bash
# Check country exists
psql -c "SELECT iso3, name FROM geo.system_admin0 WHERE iso3 = 'ALB';"

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

---

## Future Work

1. **Raster Zonal Statistics**: Aggregate Planetary Computer COG data to H3 cells
2. **Vector Aggregation**: Point-in-polygon aggregation (Overture Maps data)
3. **Higher Resolutions**: Extend to res 8-10 for detailed analysis
4. **STAC Integration**: Publish H3 grids as STAC items
5. **GeoParquet Export**: Export grids for DuckDB/cloud analysis

---

## References

- **H3 Documentation**: https://h3geo.org/
- **H3 Resolution Table**: https://h3geo.org/docs/core-library/restable
- **Job Creation Guide**: `docs_claude/JOB_CREATION_QUICKSTART.md`
- **Architecture Reference**: `docs_claude/ARCHITECTURE_REFERENCE.md`
