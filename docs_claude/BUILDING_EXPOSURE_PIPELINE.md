# Building Exposure Analysis Pipeline

**Created**: 22 DEC 2025
**Status**: Scoping - High Priority
**Timeline**: ~1 week
**Epic**: E8 (H3 Analytics Pipeline) - New Feature F8.7

---

## Business Value

**Use Case**: Climate risk exposure analysis for buildings

> "How many buildings in Region X are exposed to flood depth > 1m? What's the average exposure per hexagon?"

**High-Profile Applications**:
- Insurance pricing models
- Climate adaptation planning
- Infrastructure vulnerability assessment
- Disaster response prioritization

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    BUILDING EXPOSURE ANALYSIS PIPELINE                       │
│                                                                              │
│  STAGE 1              STAGE 2              STAGE 3              STAGE 4     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │  BUILDINGS   │    │   EXTRACT    │    │     H3       │    │  OUTPUT   │ │
│  │              │    │              │    │  AGGREGATE   │    │           │ │
│  │  Load/Query  │───▶│  Sample at   │───▶│              │───▶│ GeoParquet│ │
│  │  Footprints  │    │  Centroids   │    │  Group by    │    │           │ │
│  │              │    │              │    │  Hexagon     │    │           │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│                                                                              │
│  Sources:            Raster Sources:     Aggregations:       Formats:       │
│  • MS Buildings      • FATHOM Flood      • building_count    • GeoParquet   │
│  • Google Buildings  • Any COG           • mean_exposure     • H3 Cells     │
│  • OSM               • Planetary Comp.   • max_exposure      • PostGIS      │
│  • User Vector       • Azure Storage     • pct_exposed                      │
│                                          • threshold_counts                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Job Definition

### `building_exposure_analysis` - 4-Stage Workflow

```python
job_type: str = "building_exposure_analysis"
description: str = "Extract raster values at building centroids and aggregate to H3"

stages = [
    {
        "number": 1,
        "name": "load_buildings",
        "task_type": "building_centroid_extract",
        "parallelism": "single",
        "description": "Load buildings, compute centroids, create batch ranges"
    },
    {
        "number": 2,
        "name": "sample_raster",
        "task_type": "building_raster_sample",
        "parallelism": "fan_out",
        "description": "Extract raster values at centroids (batched)"
    },
    {
        "number": 3,
        "name": "h3_aggregate",
        "task_type": "building_h3_aggregate",
        "parallelism": "single",
        "description": "Aggregate building values to H3 cells"
    },
    {
        "number": 4,
        "name": "export",
        "task_type": "h3_export_geoparquet",
        "parallelism": "single",
        "description": "Export results to GeoParquet"
    }
]
```

---

## Parameters Schema

```python
parameters_schema = {
    # Building Source
    'building_source': {
        'type': 'str',
        'required': True,
        'enum': ['ms_buildings', 'google_buildings', 'osm', 'postgis', 'geojson_url'],
        'description': 'Building footprint data source'
    },
    'building_collection': {
        'type': 'str',
        'default': None,
        'description': 'PostGIS table name or STAC collection (if building_source=postgis)'
    },

    # Raster Source (same as h3_raster_aggregation)
    'raster_source_type': {
        'type': 'str',
        'default': 'azure',
        'enum': ['azure', 'planetary_computer', 'url'],
        'description': 'Raster data source type'
    },
    'container': {'type': 'str', 'default': None},
    'blob_path': {'type': 'str', 'default': None},
    'collection': {'type': 'str', 'default': None},
    'item_id': {'type': 'str', 'default': None},
    'cog_url': {'type': 'str', 'default': None},
    'band': {'type': 'int', 'default': 1},

    # Spatial Scope
    'bbox': {
        'type': 'list',
        'required': True,
        'description': 'Bounding box [minx, miny, maxx, maxy]'
    },
    'iso3': {
        'type': 'str',
        'default': None,
        'description': 'Optional country filter'
    },

    # H3 Configuration
    'resolution': {
        'type': 'int',
        'required': True,
        'min': 4,
        'max': 9,
        'description': 'H3 resolution for aggregation (4=~1200km², 7=~5km²)'
    },

    # Exposure Thresholds
    'thresholds': {
        'type': 'list',
        'default': [0.5, 1.0, 2.0],
        'description': 'Exposure thresholds for counting (e.g., [0.5, 1.0, 2.0] meters)'
    },

    # Output
    'dataset_id': {
        'type': 'str',
        'required': True,
        'description': 'Output dataset identifier'
    },
    'output_format': {
        'type': 'str',
        'default': 'geoparquet',
        'enum': ['geoparquet', 'postgis', 'both'],
        'description': 'Output format'
    },

    # Performance
    'batch_size': {
        'type': 'int',
        'default': 5000,
        'description': 'Buildings per batch for raster sampling'
    }
}
```

---

## Stage Details

### Stage 1: Load Buildings

**Handler**: `building_centroid_extract`

```python
def handle_building_centroid_extract(params):
    """
    Load building footprints and extract centroids.

    Returns:
        {
            "total_buildings": 1234567,
            "num_batches": 247,
            "batch_ranges": [
                {"batch_index": 0, "start": 0, "count": 5000},
                {"batch_index": 1, "start": 5000, "count": 5000},
                ...
            ],
            "temp_table": "temp_building_centroids_abc123"
        }
    """
    building_source = params['building_source']
    bbox = params['bbox']

    if building_source == 'ms_buildings':
        # Query Microsoft Building Footprints (available on Planetary Computer)
        # SELECT ST_Centroid(geometry) as centroid FROM ms_buildings WHERE ...
        pass
    elif building_source == 'google_buildings':
        # Query Google Open Buildings
        pass
    elif building_source == 'postgis':
        # Query existing PostGIS table
        table = params['building_collection']
        sql = f"""
            SELECT
                id,
                ST_X(ST_Centroid(geometry)) as lon,
                ST_Y(ST_Centroid(geometry)) as lat
            FROM geo.{table}
            WHERE geometry && ST_MakeEnvelope({bbox})
        """

    # Store centroids in temp table for Stage 2
    # Return batch ranges
```

**Data Sources**:

| Source | Coverage | Count | Access Method |
|--------|----------|-------|---------------|
| Microsoft Building Footprints | Global | 1B+ | Planetary Computer |
| Google Open Buildings | Africa, S. Asia, Latin America | 1.8B | GCS / Direct |
| OpenStreetMap | Global (variable) | 600M+ | PostGIS |
| User PostGIS Table | Custom | Variable | Internal |

---

### Stage 2: Sample Raster Values (Fan-Out)

**Handler**: `building_raster_sample`

```python
def handle_building_raster_sample(params):
    """
    Extract raster values at building centroids for a batch.

    Uses TiTiler /point endpoint for efficient sampling.

    Returns:
        {
            "batch_index": 42,
            "buildings_sampled": 5000,
            "null_count": 23,  # Buildings with nodata
            "values_inserted": 4977
        }
    """
    batch_start = params['batch_start']
    batch_size = params['batch_size']

    # Load batch of centroids from temp table
    centroids = load_centroids_batch(batch_start, batch_size)

    # Batch extract raster values
    # Option A: TiTiler /point (one request per point, slow)
    # Option B: Direct rasterstats (efficient for local COGs)
    # Option C: GDAL VRT + point sampling (most efficient)

    for centroid in centroids:
        value = sample_raster_at_point(
            cog_url=params['cog_url'],
            lon=centroid['lon'],
            lat=centroid['lat'],
            band=params['band']
        )

        # Store: building_id, lon, lat, h3_cell, exposure_value
        insert_building_exposure(centroid['id'], value)
```

**Performance Considerations**:

| Method | Speed | Best For |
|--------|-------|----------|
| TiTiler /point | ~100 pts/sec | Remote COGs, small batches |
| rasterstats | ~10K pts/sec | Local/Azure COGs, large batches |
| GDAL VRT | ~50K pts/sec | Very large datasets |

**Recommendation**: Use `rasterstats` with `fsspec` for Azure COGs.

---

### Stage 3: H3 Aggregate

**Handler**: `building_h3_aggregate`

```python
def handle_building_h3_aggregate(params):
    """
    Aggregate building exposure values to H3 cells.

    Computes per-hexagon:
        - building_count: Total buildings in cell
        - mean_exposure: Average exposure value
        - max_exposure: Maximum exposure value
        - pct_exposed_{threshold}: % buildings above threshold
        - count_exposed_{threshold}: Count above threshold

    Returns:
        {
            "cells_with_buildings": 12345,
            "total_buildings": 1234567,
            "stats_computed": 5  # Per cell
        }
    """
    resolution = params['resolution']
    thresholds = params['thresholds']

    # SQL aggregation (much faster than Python)
    sql = f"""
        INSERT INTO h3.building_exposure (
            h3_cell, dataset_id, resolution,
            building_count, mean_exposure, max_exposure,
            pct_exposed_0_5, pct_exposed_1_0, pct_exposed_2_0,
            count_exposed_0_5, count_exposed_1_0, count_exposed_2_0
        )
        SELECT
            h3_lat_lng_to_cell(lat, lon, {resolution}) as h3_cell,
            '{dataset_id}' as dataset_id,
            {resolution} as resolution,
            COUNT(*) as building_count,
            AVG(exposure_value) as mean_exposure,
            MAX(exposure_value) as max_exposure,
            -- Threshold percentages
            100.0 * SUM(CASE WHEN exposure_value > 0.5 THEN 1 ELSE 0 END) / COUNT(*) as pct_exposed_0_5,
            100.0 * SUM(CASE WHEN exposure_value > 1.0 THEN 1 ELSE 0 END) / COUNT(*) as pct_exposed_1_0,
            100.0 * SUM(CASE WHEN exposure_value > 2.0 THEN 1 ELSE 0 END) / COUNT(*) as pct_exposed_2_0,
            -- Threshold counts
            SUM(CASE WHEN exposure_value > 0.5 THEN 1 ELSE 0 END) as count_exposed_0_5,
            SUM(CASE WHEN exposure_value > 1.0 THEN 1 ELSE 0 END) as count_exposed_1_0,
            SUM(CASE WHEN exposure_value > 2.0 THEN 1 ELSE 0 END) as count_exposed_2_0
        FROM temp_building_exposures
        WHERE exposure_value IS NOT NULL
        GROUP BY h3_lat_lng_to_cell(lat, lon, {resolution})
    """
```

---

### Stage 4: Export

**Handler**: `h3_export_geoparquet`

```python
def handle_h3_export_geoparquet(params):
    """
    Export H3 aggregation results to GeoParquet.

    Returns:
        {
            "output_url": "https://storage.blob.../exports/building_exposure_kenya_2025.parquet",
            "file_size_mb": 12.3,
            "row_count": 12345,
            "columns": ["h3_cell", "geometry", "building_count", "mean_exposure", ...]
        }
    """
    dataset_id = params['dataset_id']

    # Query results with H3 geometries
    df = query_h3_with_geometry(dataset_id)

    # Convert to GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.lon, df.lat),  # Or h3 boundary polygons
        crs="EPSG:4326"
    )

    # Write to Azure Blob as GeoParquet
    output_path = f"exports/{dataset_id}.parquet"
    gdf.to_parquet(output_path)

    return {"output_url": get_blob_url(output_path)}
```

---

## Schema Additions

### New Table: `h3.building_exposure`

```sql
CREATE TABLE IF NOT EXISTS h3.building_exposure (
    h3_cell TEXT NOT NULL,
    dataset_id VARCHAR(64) NOT NULL,
    resolution SMALLINT NOT NULL,

    -- Core stats
    building_count INTEGER NOT NULL,
    mean_exposure REAL,
    max_exposure REAL,
    std_exposure REAL,

    -- Threshold stats (dynamic based on thresholds param)
    pct_exposed_0_5 REAL,
    pct_exposed_1_0 REAL,
    pct_exposed_2_0 REAL,
    count_exposed_0_5 INTEGER,
    count_exposed_1_0 INTEGER,
    count_exposed_2_0 INTEGER,

    -- Metadata
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    source_job_id UUID,

    PRIMARY KEY (h3_cell, dataset_id)
);

-- Partition by resolution for query performance
CREATE INDEX idx_building_exposure_res ON h3.building_exposure(resolution);
CREATE INDEX idx_building_exposure_dataset ON h3.building_exposure(dataset_id);
```

---

## API Endpoints

### Submit Job

```bash
POST /api/jobs/submit/building_exposure_analysis
{
    "building_source": "ms_buildings",
    "raster_source_type": "azure",
    "container": "silver-cogs",
    "blob_path": "fathom/merged/pluvial_defended_100yr.tif",
    "bbox": [33.5, -5.0, 42.0, 5.5],  # Kenya
    "iso3": "KEN",
    "resolution": 6,
    "thresholds": [0.5, 1.0, 2.0],
    "dataset_id": "kenya_flood_exposure_2025",
    "output_format": "geoparquet"
}
```

### Query Results

```bash
GET /api/h3/building_exposure/{dataset_id}
GET /api/h3/building_exposure/{dataset_id}/cells?iso3=KEN&min_buildings=100
GET /api/h3/building_exposure/{dataset_id}/summary
```

### Download Export

```bash
GET /api/h3/export/{dataset_id}?format=geoparquet
```

---

## Implementation Plan (~1 Week)

| Day | Task | Deliverable |
|-----|------|-------------|
| **Day 1** | Schema + Job Definition | `h3.building_exposure` table, `building_exposure_analysis` job stub |
| **Day 2** | Stage 1 Handler | `building_centroid_extract` - PostGIS centroid extraction |
| **Day 3** | Stage 2 Handler | `building_raster_sample` - Batch raster sampling with rasterstats |
| **Day 4** | Stage 3 Handler | `building_h3_aggregate` - SQL aggregation |
| **Day 5** | Stage 4 + API | `h3_export_geoparquet` + query endpoints |
| **Day 6** | Testing | Kenya FATHOM flood + MS Buildings end-to-end |
| **Day 7** | Polish | Error handling, documentation, demo prep |

---

## Dependencies

| Dependency | Status | Action |
|------------|:------:|--------|
| H3 grid infrastructure | ✅ | None |
| FATHOM merged COGs | 🚧 | Complete E10.F10.2 (spatial merge) |
| MS Buildings access | 📋 | Configure Planetary Computer client |
| rasterstats library | 📋 | Add to requirements.txt |
| GeoParquet writer | 📋 | Add geopandas + pyarrow |

---

## Example Output (GeoParquet Schema)

```
┌─────────────────┬────────────────┬──────────────┬───────────────┬─────────────────┐
│ h3_cell         │ building_count │ mean_exposure│ pct_exposed_1 │ geometry        │
├─────────────────┼────────────────┼──────────────┼───────────────┼─────────────────┤
│ 866a4a1cfffffff │ 2,847          │ 0.73         │ 28.4%         │ POLYGON(...)    │
│ 866a4a1dfffffff │ 1,234          │ 1.21         │ 45.2%         │ POLYGON(...)    │
│ 866a4a1efffffff │ 5,621          │ 0.12         │ 5.1%          │ POLYGON(...)    │
└─────────────────┴────────────────┴──────────────┴───────────────┴─────────────────┘
```

**DuckDB Query Example**:
```sql
-- Top 10 most exposed hexagons
SELECT
    h3_cell,
    building_count,
    mean_exposure,
    pct_exposed_1_0 as pct_over_1m
FROM read_parquet('kenya_flood_exposure_2025.parquet')
WHERE building_count > 100
ORDER BY mean_exposure DESC
LIMIT 10;
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| End-to-end runtime (Kenya, 1M buildings) | < 10 minutes |
| Buildings sampled per second | > 5,000 |
| Output file size (Kenya, res 6) | < 50 MB |
| API response time (query) | < 500ms |

---

## Next Steps

1. **Approve scope** with team lead
2. **Add to EPICS.md** as F8.7
3. **Create job definition** (`jobs/building_exposure_analysis.py`)
4. **Implement handlers** (4 stages)
5. **Test with Kenya** (FATHOM + MS Buildings)
6. **Demo to stakeholders**

---

*"Buildings + Flood Depth + Hexagons = Climate Risk Analytics"*
