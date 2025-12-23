# Geospatial Data Platform - Technical Overview

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Last Updated**: 23 DEC 2025
**Audience**: Development team (all disciplines)
**Purpose**: High-level understanding of platform architecture, patterns, and technology stack
**Wiki**: Azure DevOps Wiki - Technical architecture documentation

---

## What We Built

A **serverless geospatial ETL pipeline** that transforms raw spatial data (shapefiles, GeoTIFFs, CSVs) into standards-based REST APIs that work with existing GIS tools (QGIS, ArcGIS, Leaflet, OpenLayers).

**Input**: Upload a shapefile with country boundaries
**Output**: 5 minutes later, OGC API endpoint serving GeoJSON + interactive web map + STAC catalog entry

**Scale**: Handles multi-million feature datasets and multi-GB rasters with parallel processing

---

## Serverless Architecture (Azure Functions)

### What "Serverless" Actually Means

**It doesn't mean "no servers"** - it means **Azure manages the web server infrastructure so you don't have to**.

**Traditional Web App**:
```
You manage:
├── Operating system patches
├── Web server configuration (nginx, Apache)
├── SSL certificates
├── Load balancer setup
├── Scaling (add more VMs when traffic increases)
├── Monitoring and restarts
└── Security updates
```

**Azure Functions (Serverless)**:
```
You manage:
└── Your code (Python functions)

Azure manages:
├── Operating system
├── Web server
├── SSL/HTTPS
├── Auto-scaling (0 to 1000s of instances automatically)
├── Load balancing
└── Infrastructure updates
```

### How It Works

**HTTP Trigger Functions** (like API endpoints):
```python
@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job(req: HttpRequest) -> HttpResponse:
    """
    This function runs when: POST /api/jobs/submit/process_vector
    Azure automatically:
    - Routes the HTTP request here
    - Provides request object with body/headers
    - Scales to handle 1 or 10,000 concurrent requests
    """
    job_params = req.get_json()
    # Your business logic here
    return HttpResponse(status_code=202)
```

**Queue Trigger Functions** (like background workers):
```python
@app.service_bus_queue_trigger(queue_name="geospatial-tasks")
def process_task(msg: ServiceBusMessage):
    """
    This function runs when: New message appears in Service Bus queue
    Azure automatically:
    - Polls the queue for new messages
    - Runs this function for each message
    - Scales out to 20+ parallel workers if queue backs up
    - Handles retries if function fails
    """
    task_data = msg.get_body().decode('utf-8')
    # Process the task
```

### When to Use Serverless

**Suitable for**:
- APIs with variable traffic (low usage at night, high usage during day)
- Event-driven workloads (process files when uploaded)
- Jobs that can be divided into independent tasks
- Prototypes and MVPs (deploy quickly, scale later)

**Not ideal for**:
- Long-running processes (>10 min timeout per function)
- Stateful applications (servers come and go)
- Predictable constant load (dedicated VMs might be cheaper)

**Our use case**: This architecture is well-suited to our needs. ETL jobs are event-driven (triggered by data uploads), highly parallelizable (chunks processed independently), and have variable load.

---

## Distributed Systems Patterns

### Fan-Out / Fan-In Pattern

**Problem**: Upload a CSV with 2.5 million rows to PostGIS. Single-threaded upload takes 2+ hours.

**Solution**: Fan-out to parallel workers, fan-in when complete.

```
                    ┌──────────────────────────────────────┐
                    │  HTTP Request: Upload 2.5M row CSV  │
                    └───────────────┬──────────────────────┘
                                    ↓
                    ┌──────────────────────────────────────┐
                    │  STAGE 1: Validate file (1 task)    │
                    │  Result: "File OK, 2.5M rows"        │
                    └───────────────┬──────────────────────┘
                                    ↓
                    ┌──────────────────────────────────────┐
                    │  STAGE 2: Create table & chunk       │
                    │  Result: "Created 129 chunks"        │
                    └───────────────┬──────────────────────┘
                                    ↓
                ┌───────────────────┴───────────────────┐
                │         FAN-OUT (129 tasks)           │
                │  Each task uploads 20,000 rows        │
                └───────────────────┬───────────────────┘
                                    ↓
      ┌─────────┬─────────┬─────────┼─────────┬─────────┬─────────┐
      ▼         ▼         ▼         ▼         ▼         ▼         ▼
   Task 1    Task 2    Task 3    ...      Task 127  Task 128  Task 129
   (20K)     (20K)     (20K)              (20K)     (20K)     (20K)
      │         │         │         │         │         │         │
      └─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────────────┐
                    │  FAN-IN: Last task completes         │
                    │  "All 129 tasks done, 2.5M uploaded" │
                    └───────────────┬──────────────────────┘
                                    ↓
                    ┌──────────────────────────────────────┐
                    │  STAGE 4: Create STAC + validate API │
                    │  Result: Job complete in 15 minutes  │
                    └──────────────────────────────────────┘
```

**Result**: 2 hours → 15 minutes (8x faster)

**Key Challenge**: How does the last task know it's the last one?

### Idempotent Design

**Idempotency**: Running an operation multiple times produces the same result as running it once.

**Why it matters**: Distributed systems have failures. Network timeouts, server crashes, duplicate messages happen.

**Example - NOT Idempotent**:
```python
def process_upload(file_path):
    # ❌ BAD: Run this twice = data inserted twice!
    rows = read_csv(file_path)
    db.execute("INSERT INTO countries VALUES (?)", rows)
```

**Example - Idempotent**:
```python
def process_upload(file_path, job_id):
    # ✅ GOOD: Run this 100 times = same result
    # Job ID is deterministic hash of parameters

    # Check if already done
    if db.execute("SELECT * FROM jobs WHERE job_id = ?", job_id):
        return {"status": "already_completed"}

    # Do the work
    rows = read_csv(file_path)
    db.execute("INSERT INTO countries VALUES (?)", rows)

    # Mark as done
    db.execute("INSERT INTO jobs (job_id, status) VALUES (?, 'completed')", job_id)
```

**How we achieve idempotency**:
1. **Deterministic Job IDs**: SHA256 hash of parameters
   - Submit same job twice → Same job_id → Returns existing job
2. **Database constraints**: PRIMARY KEY on job_id prevents duplicates
3. **Check-then-act**: Always check if work already done before doing it

### Last Task Completion Detection Pattern

**Problem**: 129 tasks uploading chunks in parallel. When all tasks finish, which task triggers the next stage?

**Naive approach** (race condition):
```python
def upload_chunk(chunk_id):
    # Upload my chunk
    upload_to_postgis(chunk_id)

    # Check if I'm last
    remaining = db.count("SELECT COUNT(*) FROM tasks WHERE status != 'Completed'")
    if remaining == 0:  # ❌ RACE CONDITION!
        # 10 tasks might all see "0 remaining" at the same instant!
        advance_to_next_stage()
```

**Our solution** (PostgreSQL advisory locks):
```sql
CREATE OR REPLACE FUNCTION complete_task_and_check_stage(
    p_job_id VARCHAR,
    p_task_id VARCHAR,
    p_stage INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    v_remaining INTEGER;
BEGIN
    -- 🔒 LOCK: Only one task can run this code at a time
    PERFORM pg_advisory_xact_lock(hashtext(p_job_id || ':' || p_stage));

    -- Update my status
    UPDATE tasks SET status = 'Completed' WHERE task_id = p_task_id;

    -- Count remaining (safe because locked)
    SELECT COUNT(*) INTO v_remaining
    FROM tasks
    WHERE job_id = p_job_id AND stage = p_stage AND status != 'Completed';

    RETURN (v_remaining = 0);  -- TRUE if I'm the last one

    -- 🔓 UNLOCK: Lock released automatically at end of transaction
END;
$$ LANGUAGE plpgsql;
```

**Result**: Exactly one task gets TRUE back, triggers next stage. Zero race conditions.

### Serverless Database Connection Pattern

**Problem**: Traditional connection pooling doesn't work in serverless environments.

**Why connection pooling fails in Azure Functions**:

```
Traditional Web Server (Connection Pool Works):
┌─────────────────────────────────────────────────────────────┐
│  Web Server (always running)                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Connection Pool (10 connections, reused for hours)   │    │
│  │  ├── conn1 ──────> PostgreSQL                       │    │
│  │  ├── conn2 ──────> PostgreSQL                       │    │
│  │  └── conn3 ──────> PostgreSQL                       │    │
│  └─────────────────────────────────────────────────────┘    │
│  Requests share pooled connections efficiently               │
└─────────────────────────────────────────────────────────────┘

Azure Functions (Connection Pool FAILS):
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Instance 1      │ │ Instance 2      │ │ Instance 3      │
│ (scales to 0)   │ │ (just spawned)  │ │ (about to die)  │
│ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │ Pool: 10    │ │ │ │ Pool: 10    │ │ │ │ Pool: 10    │ │
│ │ connections │ │ │ │ connections │ │ │ │ connections │ │
│ └─────────────┘ │ └─────────────┘ │ │ └─────────────┘ │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         └───────────────────┴───────────────────┘
                              │
              30+ connections churning constantly!
              Pools never reach steady state.
              Instances spawn/die unpredictably.
```

**The disaster scenario** (23 DEC 2025 - this actually happened):

We scaled to 8 instances × 2 workers × 4 concurrent tasks = 64 parallel operations. Each task opened multiple connections for different stages of processing. Result: **1,000+ connection attempts churning against 200 max_connections**. The database became completely unresponsive.

**The correct pattern: Memory-First, Single-Connection Burst**

Instead of holding connections open while computing, do ALL computation in memory first, then open ONE connection for a fast bulk insert:

```python
# ❌ WRONG: Hold connection open during computation
def process_task_bad(items):
    with get_connection() as conn:  # Connection held for entire duration!
        for item in items:
            result = expensive_computation(item)  # Minutes of CPU work
            conn.execute("INSERT INTO results VALUES (?)", result)
        conn.commit()
    # Connection held for 5+ minutes per task
    # 64 parallel tasks = 64 connections held for minutes = disaster

# ✅ CORRECT: Memory-first, single-connection burst
def process_task_good(items):
    # Phase 1: Compute everything in memory (use RAM freely)
    all_results = []
    for item in items:
        result = expensive_computation(item)  # RAM is cheap!
        all_results.append(result)

    # Phase 2: Single connection, fast bulk insert
    with get_connection() as conn:  # Connection held for seconds
        bulk_insert(conn, all_results)  # COPY protocol: 100K rows/second
        conn.commit()
    # Connection released in seconds, not minutes
```

**Why this works**:

| Resource | Serverless Characteristic | Strategy |
|----------|---------------------------|----------|
| **RAM** | Abundant (4GB+ per worker), cheap | Use freely for computation |
| **CPU** | Abundant, cheap | Parallelize computation |
| **DB Connections** | Scarce (max_connections ÷ instances), expensive | Minimize hold time |

**Connection budget formula**:

```
Available connections = max_connections × 0.5 (safety margin)
Connections per task = Available connections ÷ concurrent_tasks

Example:
- PostgreSQL max_connections: 429
- Safety margin: 429 × 0.5 = 214 available
- Concurrent tasks: 64
- Budget per task: 214 ÷ 64 = ~3 connections per task

If your task needs 15 connections, you WILL exhaust the pool.
```

**Implementation pattern for bulk inserts**:

```python
def bulk_insert_with_copy(conn, table_name, rows: list[dict]):
    """
    Use PostgreSQL COPY protocol for maximum throughput.
    100,000+ rows/second vs 1,000 rows/second for individual INSERTs.
    """
    from io import StringIO

    # Build CSV in memory
    buffer = StringIO()
    columns = list(rows[0].keys())
    for row in rows:
        line = '\t'.join(str(row[col]) for col in columns)
        buffer.write(line + '\n')
    buffer.seek(0)

    # Single COPY command (one round-trip to database)
    with conn.cursor() as cur:
        cur.copy_from(buffer, table_name, columns=columns)
    conn.commit()
```

**Key principles**:

1. **Never hold connections during computation** - RAM is cheap, connections are precious
2. **Batch everything** - One connection for 100K rows beats 100K connections for 1 row each
3. **Use COPY protocol** - 100x faster than individual INSERTs
4. **Budget connections explicitly** - Calculate max connections per task before scaling
5. **Fail fast on connection errors** - Don't retry connection exhaustion (it makes it worse)

**Further reading**: See `docs_claude/ARCHITECTURE_REFERENCE.md` for implementation details and the H3 cascade handler refactoring that applied this pattern.

### Distributed Systems Challenges We Solved

| Challenge | Our Solution |
|-----------|-------------|
| **Duplicate messages** | Idempotent job IDs (hash of parameters) |
| **Race conditions** | PostgreSQL advisory locks |
| **Partial failures** | Atomic tasks (all-or-nothing) |
| **Task coordination** | PostgreSQL as single source of truth |
| **Retry logic** | Service Bus automatic retries + dead-letter queue |
| **Observability** | Application Insights structured logging |
| **Connection exhaustion** | Memory-first pattern, single-connection burst |

### Graceful Degradation (pgSTAC Optional)

**Design Principle**: The system continues to function with reduced capabilities when optional components are unavailable.

**Architecture Enabler**: Schema separation in PostgreSQL allows independent failure of components:

```
PostgreSQL Database (4 independent schemas)
├── app     (CoreMachine)  ← CRITICAL: Job/task orchestration
├── geo     (Vector Data)  ← CRITICAL: PostGIS tables, OGC Features API
├── pgstac  (STAC Catalog) ← OPTIONAL: Metadata discovery
└── h3      (H3 Grids)     ← OPTIONAL: Hexagonal grid system
```

**What Works WITHOUT pgSTAC**:

| Capability | Vector Jobs | Raster Jobs | Notes |
|------------|-------------|-------------|-------|
| Stage 1: Validation | ✅ | ✅ | No pgstac dependencies |
| Stage 2: Processing | ✅ | ✅ | PostGIS / COG creation |
| Stage 3: STAC Cataloging | ⚠️ Degraded | ⚠️ Degraded | Skipped with warning |
| OGC Features API | ✅ | N/A | Reads from `geo` schema directly |
| TiTiler COG Viewing | N/A | ✅ | URLs generated from config |
| Vector Viewer | ✅ | N/A | Uses OGC Features API |
| STAC API Discovery | ❌ | ❌ | Requires pgstac schema |

**How It Works**:

1. **Detection**: `PgStacBootstrap.is_available()` checks if pgstac schema is functional (cached for 60 seconds)
2. **Handler Behavior**: STAC handlers detect unavailability and return success with `degraded: true` flag
3. **Job Completion**: Jobs complete successfully with warnings in `degraded_mode` field
4. **Health Endpoint**: Reports `degraded_capabilities` and `available_capabilities` lists

**User-Facing Response** (degraded mode):

```json
{
  "success": true,
  "degraded_mode": true,
  "warnings": ["STAC cataloging skipped - pgSTAC unavailable"],
  "available_capabilities": ["OGC Features API", "TiTiler COG viewing"],
  "unavailable_capabilities": ["STAC API discovery"],
  "result": {
    "table_name": "my_dataset",
    "ogc_features_url": "/api/features/collections/my_dataset/items"
  }
}
```

**Why This Matters**:

- **Corporate environments**: DBA may not grant pgstac role prerequisites immediately
- **Deployment resilience**: pypgstac migration failures don't block entire system
- **Clear communication**: Users know exactly what works and what doesn't
- **Graceful recovery**: When pgstac is fixed, full functionality returns automatically

**Implementation Pattern** (for handlers):

```python
def my_stac_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    # Check availability FIRST (before any pgstac operations)
    if not PgStacBootstrap.is_available():
        logger.warning("pgSTAC unavailable - degraded mode")
        return {
            "success": True,
            "degraded": True,
            "warning": "pgSTAC schema not available",
            "result": {
                # Return whatever IS available
                "ogc_features_available": True,
                "stac_item_created": False
            }
        }

    # Normal pgstac operations...
```

---

## Free & Open Source Software (FOSS) Stack

### Why FOSS for Geospatial?

**Industry standards**: NASA, USGS, Planet, Maxar all use these tools
**Interoperability**: Works with QGIS, ArcGIS, FME, GDAL without additional configuration
**No vendor lock-in**: Can migrate to any cloud provider
**Production-proven**: Decades of development, billions of spatial operations

### The Stack (Bottom to Top)

#### 1. GDAL - The Foundation

**Geospatial Data Abstraction Library**

**What it does**: Read/write 200+ geospatial file formats (GeoTIFF, Shapefile, NetCDF, etc.)

**Comparison**: Similar to `ffmpeg` for video. ffmpeg converts video formats; GDAL converts spatial formats.

**Example**:
```python
import rasterio  # Python wrapper for GDAL

# Read elevation raster
with rasterio.open('elevation.tif') as src:
    elevation = src.read(1)  # Read band 1
    bounds = src.bounds      # Get geographic bounds
    crs = src.crs            # Get coordinate system
```

**Powers**: Rasterio, GeoPandas, QGIS, ArcGIS Pro, Google Earth Engine

#### 2. Shapely - Geometry Operations

**What it does**: Create, manipulate, and analyze geometric shapes

**Comparison**: Similar to JavaScript's `Path2D` API, but designed for geospatial coordinates.

**Example**:
```python
from shapely.geometry import Point, Polygon

# Create a point
eiffel_tower = Point(2.2945, 48.8584)  # longitude, latitude

# Create a polygon (bounding box around Paris)
paris_bbox = Polygon([
    (2.2, 48.8),   # Southwest corner
    (2.4, 48.8),   # Southeast corner
    (2.4, 48.9),   # Northeast corner
    (2.2, 48.9),   # Northwest corner
    (2.2, 48.8)    # Close the polygon
])

# Check if point is inside polygon
eiffel_tower.within(paris_bbox)  # True
```

**Why it matters**: All geometry validation, buffering, intersection checks use Shapely

#### 3. GeoPandas - Pandas with Spatial Support

**What it does**: Work with geospatial tabular data (Pandas DataFrame with geometry column)

**Comparison**: Combines tabular data operations (like Excel) with spatial geometry support.

**Example**:
```python
import geopandas as gpd

# Read a shapefile (like pd.read_csv for spatial data)
countries = gpd.read_file('countries.shp')

# It's a DataFrame with a special 'geometry' column
print(countries.head())
#   name       population    geometry
# 0 France     67,000,000    POLYGON((2.5 51.1, ...))
# 1 Germany    83,000,000    POLYGON((5.9 55.0, ...))

# Spatial operations work like Pandas operations
european_countries = countries[countries['continent'] == 'Europe']
large_countries = countries[countries.area > 1000000]  # > 1M km²

# Save to PostGIS
countries.to_postgis('countries', engine, schema='geo', if_exists='replace')
```

**Why we use it**: Perfect for ETL - read shapefiles, validate, clean, write to PostGIS

#### 4. Rasterio - Raster Input/Output

**What it does**: Read/write raster data (satellite imagery, elevation models, etc.)

**Comparison**: Similar to `PIL` (Python Imaging Library), but designed for geospatial rasters with coordinate systems.

**Example**:
```python
import rasterio
import numpy as np

# Read Landsat imagery
with rasterio.open('landsat_scene.tif') as src:
    # Read RGB bands
    red = src.read(4)    # Landsat band 4 = red
    green = src.read(3)  # Landsat band 3 = green
    blue = src.read(2)   # Landsat band 2 = blue

    # Stack into RGB array
    rgb = np.dstack([red, green, blue])

    # Get metadata
    bounds = src.bounds  # Geographic extent
    crs = src.crs        # Coordinate system
    transform = src.transform  # Maps pixel coords to lat/lon
```

**Why we use it**: Create Cloud-Optimized GeoTIFFs (COGs) for TiTiler

#### 5. PostGIS - Spatial Database Extension

**What it does**: PostgreSQL extension that adds spatial data types and functions

**Comparison**: Adds spatial query capabilities to PostgreSQL, similar to how MongoDB supports geospatial indexes.

**Spatial data types**:
```sql
-- Store points, lines, polygons in database
CREATE TABLE cities (
    name TEXT,
    location GEOMETRY(Point, 4326)  -- Point in WGS84 (lat/lon)
);

INSERT INTO cities VALUES
    ('Paris', ST_SetSRID(ST_MakePoint(2.3522, 48.8566), 4326)),
    ('London', ST_SetSRID(ST_MakePoint(-0.1276, 51.5074), 4326));
```

**Spatial queries**:
```sql
-- Find cities within 100km of Paris
SELECT name
FROM cities
WHERE ST_DWithin(
    location,
    (SELECT location FROM cities WHERE name = 'Paris'),
    100000  -- meters
);

-- Find countries that intersect this bounding box
SELECT name
FROM countries
WHERE ST_Intersects(
    geometry,
    ST_MakeEnvelope(-10, 35, 30, 60, 4326)  -- Europe bbox
);
```

**Why we use it**: Powers the OGC API - Features endpoint. Clients query PostGIS → get GeoJSON.

#### 6. Cloud-Optimized GeoTIFF (COG)

**What it is**: GeoTIFF file optimized for cloud storage (HTTP range requests)

**Comparison**: Similar concept to progressive JPEG images, but for geospatial rasters.

**Normal GeoTIFF problem**:
```
User requests tile at zoom level 5
→ Download entire 10GB file from cloud storage
→ Extract small 256x256 tile
→ Discard 99.99% of downloaded data
```

**COG solution**:
```
User requests tile at zoom level 5
→ HTTP range request: "bytes 5000-6000"
→ Download only 1KB needed for that tile
→ 10,000x faster, 10,000x less bandwidth
```

**Structure**:
```
COG File:
├── Overviews (pyramids)
│   ├── Zoom 0: 256x256 pixels (whole world in one tile)
│   ├── Zoom 1: 512x512 pixels
│   ├── Zoom 2: 1024x1024 pixels
│   └── ... up to full resolution
├── Internal tiling (512x512 blocks)
└── HTTP-friendly byte layout (metadata at front)
```

**Why we use it**: TiTiler can serve tiles without downloading entire file

#### 7. TiTiler - Dynamic Tile Server

**What it does**: Generates map tiles from COGs dynamically at request time (no pre-processing needed)

**Comparison**: A serverless image API specifically designed for geospatial data.

**Traditional tile server**:
```
Preprocessing step:
1. Take 10GB GeoTIFF
2. Generate 1 million pre-rendered PNG tiles (all zoom levels)
3. Store tiles in S3 (expensive!)
4. Client requests: /tiles/5/10/12.png → Serve pre-rendered PNG

Problem: If the user wants a different color scheme, all 1 million tiles must be regenerated.
```

**TiTiler (dynamic)**:
```
No preprocessing required. Upload COG to blob storage.

Client requests: /tiles/5/10/12?url=https://storage.blob.core.windows.net/data/elevation.tif&colormap=terrain&rescale=0,3000

TiTiler:
1. Makes HTTP range request to COG (downloads ~10KB)
2. Applies color ramp on-the-fly
3. Returns PNG tile

Change color ramp? Just change URL parameter. No regeneration needed.
```

**Why we use it**: Serve raster tiles without pre-processing or storage costs

#### 8. STAC - SpatioTemporal Asset Catalog

**What it does**: Standardized metadata format for searching and discovering geospatial data

**Comparison**: Similar to OpenGraph tags for websites or RSS feeds, but designed for geospatial data catalogs.

**STAC Item** (metadata for one dataset):
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "paris-dem-2024",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[2.2, 48.8], [2.4, 48.8], [2.4, 48.9], [2.2, 48.9], [2.2, 48.8]]]
  },
  "bbox": [2.2, 48.8, 2.4, 48.9],
  "properties": {
    "datetime": "2024-01-15T00:00:00Z",
    "gsd": 10.0  // Ground sample distance (10m resolution)
  },
  "assets": {
    "data": {
      "href": "https://storage.blob.core.windows.net/data/paris-dem.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    },
    "thumbnail": {
      "href": "https://storage.blob.core.windows.net/data/paris-dem-thumb.png",
      "type": "image/png",
      "roles": ["thumbnail"]
    }
  }
}
```

**STAC API search**:
```python
from pystac_client import Client

# Connect to catalog
catalog = Client.open('https://api.example.com/stac')

# Search for elevation data in Paris from 2024
search = catalog.search(
    bbox=[2.2, 48.8, 2.4, 48.9],           # Paris bounding box
    datetime='2024-01-01/2024-12-31',      # Year 2024
    collections=['elevation'],              # DEM data only
    query={'gsd': {'lte': 30}}             # Resolution ≤ 30m
)

# Get results
for item in search.items():
    print(f"Found: {item.id}")
    cog_url = item.assets['data'].href
    # Download or stream the COG
```

**Why we use it**: NASA, USGS, Planet, Microsoft Planetary Computer all use STAC. QGIS and ArcGIS can browse STAC catalogs natively.

#### 9. OGC API - Features

**What it is**: REST API standard for serving vector data (points, lines, polygons)

**Comparison**: A REST API standard for geospatial features, similar in purpose to GraphQL but with spatial query support.

**Replaces**: WFS (Web Feature Service) - old XML-based SOAP standard

**Example endpoints**:
```bash
# List all feature collections
GET /api/features/collections
→ Returns: ["countries", "cities", "rivers"]

# Get collection metadata
GET /api/features/collections/countries
→ Returns: {bbox: [...], featureCount: 195, geometryType: "Polygon"}

# Get features with spatial filter
GET /api/features/collections/countries/items?bbox=-180,-90,180,90&limit=10
→ Returns: GeoJSON FeatureCollection

# Get single feature
GET /api/features/collections/countries/items/123
→ Returns: GeoJSON Feature
```

**Why it matters**:
- Works with QGIS, ArcGIS, FME, GDAL without additional configuration
- Client gets GeoJSON (already understood by Leaflet, Mapbox, etc.)
- No custom API documentation needed because it follows a published standard.

---

## How It All Fits Together

### Example Workflow: "Upload a Shapefile"

```
User uploads countries.shp to Azure Blob Storage
              ↓
┌─────────────────────────────────────────────────┐
│ Azure Function (HTTP Trigger)                   │
│ • Receives upload notification                  │
│ • Creates job_id (SHA256 hash)                  │
│ • Queues job to Service Bus                     │
└─────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────┐
│ Azure Function (Queue Trigger)                  │
│ STAGE 1: Validate                               │
│ • GeoPandas reads shapefile                     │
│ • Shapely validates geometries                  │
│ • Result: "195 countries, valid"                │
└─────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────┐
│ STAGE 2: Prepare & Chunk                        │
│ • Create PostGIS table                          │
│ • Chunk into 10 batches (20 countries each)     │
│ • Queue 10 tasks                                │
└─────────────────────────────────────────────────┘
              ↓
      ┌───────┴───────┐
      ▼       ▼       ▼  (Fan-out: 10 parallel tasks)
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Upload   │ │ Upload   │ │ Upload   │
│ chunk 1  │ │ chunk 2  │ │ chunk 10 │
│ (20 rows)│ │ (20 rows)│ │ (20 rows)│
└──────────┘ └──────────┘ └──────────┘
      │         │         │
      └─────────┴─────────┘ (Fan-in: Last task completes)
              ↓
┌─────────────────────────────────────────────────┐
│ STAGE 4: Finalize                               │
│ • Create STAC item in pgSTAC                    │
│ • Validate OGC API endpoint                     │
│ • Job complete                                  │
└─────────────────────────────────────────────────┘

Now available:
• OGC API: GET /api/features/collections/countries/items
• STAC API: Search in catalog
• Interactive Map: View on web map
```

### Front-End Consumption

**Your JavaScript/TypeScript app**:
```typescript
// No custom API client needed - the response is standard GeoJSON
const response = await fetch(
  'https://api.example.com/api/features/collections/countries/items?limit=100'
);
const geojson = await response.json();

// Works directly with Leaflet
L.geoJSON(geojson, {
  style: { color: '#3388ff' },
  onEachFeature: (feature, layer) => {
    layer.bindPopup(feature.properties.name);
  }
}).addTo(map);

// Or Mapbox GL JS
map.addSource('countries', {
  type: 'geojson',
  data: 'https://api.example.com/api/features/collections/countries/items'
});

// Or MapLibre, OpenLayers, Cesium, etc.
```

**For rasters** (elevation, satellite imagery):
```typescript
// TiTiler serves XYZ tiles (standard format)
const tileLayer = L.tileLayer(
  'https://api.example.com/tiles/cog/tiles/{z}/{x}/{y}?url={cog_url}&colormap=terrain',
  {
    attribution: 'Elevation Data',
    maxZoom: 14
  }
).addTo(map);
```

---

## Key Takeaways

1. **Serverless** = Azure manages infrastructure, you manage code
2. **Fan-out/Fan-in** = Break big jobs into parallel tasks for speed
3. **Idempotency** = Safe to retry operations (critical for distributed systems)
4. **FOSS Stack** = Industry-standard tools (NASA, USGS use same stack)
5. **Standards-Based APIs** = OGC + STAC = works with existing GIS tools
6. **Cloud-Optimized Formats** = COG enables streaming without downloading entire files

---

## Architecture Diagrams (Mermaid)

Visual diagrams for CoreMachine orchestration and state lifecycle. These render in GitHub, Azure DevOps Wiki, and VS Code with Mermaid extension.

### CoreMachine Composition

The CoreMachine is a stateless orchestrator that coordinates job execution through composition (not inheritance).

```mermaid
flowchart TB
    subgraph CoreMachine["CoreMachine (Stateless Orchestrator)"]
        direction TB
        PJM["process_job_message()"]
        PTM["process_task_message()"]
    end

    subgraph Composed["Composed Components (Injected)"]
        SM["StateManager<br/>━━━━━━━━━━━━━<br/>• update_job_status()<br/>• update_task_status()<br/>• get_stage_results()<br/>• check_stage_completion()"]

        OM["OrchestrationManager<br/>━━━━━━━━━━━━━━━━<br/>• create_tasks_for_stage()<br/>• batch_tasks()<br/>• route_to_queue()"]

        SCR["StageCompletionRepository<br/>━━━━━━━━━━━━━━━━━━━━<br/>• acquire_advisory_lock()<br/>• detect_last_task()<br/>• signal_stage_complete()"]
    end

    subgraph Registries["Explicit Registries"]
        AJ["ALL_JOBS{}<br/>━━━━━━━━━━━━<br/>27 job definitions<br/>Validated at import"]

        AH["ALL_HANDLERS{}<br/>━━━━━━━━━━━━━━<br/>56 task handlers<br/>Validated at import"]
    end

    PJM --> SM
    PJM --> OM
    PJM --> AJ

    PTM --> SM
    PTM --> SCR
    PTM --> AH

    OM --> SCR
```

### CoreMachine Internal Flow

```mermaid
flowchart TD
    subgraph JobProcessing["process_job_message()"]
        J1["Receive job message<br/>from geospatial-jobs queue"]
        J2["Load JobRecord<br/>from database"]
        J3["Get job definition<br/>from ALL_JOBS"]
        J4["Determine current stage"]
        J5["Call create_tasks_for_stage()"]
        J6["Batch tasks (100 per batch)"]
        J7["Route to appropriate queue<br/>(raster-tasks or vector-tasks)"]
        J8["Update job status<br/>QUEUED → PROCESSING"]

        J1 --> J2 --> J3 --> J4 --> J5 --> J6 --> J7 --> J8
    end

    subgraph TaskProcessing["process_task_message()"]
        T1["Receive task message"]
        T2["Load TaskRecord"]
        T3["Get handler from<br/>ALL_HANDLERS"]
        T4["Execute handler(params, context)"]
        T5{"Success?"}
        T6["Update task: COMPLETED"]
        T7["Update task: FAILED"]
        T8["Check stage completion<br/>(advisory lock)"]
        T9{"Last task<br/>in stage?"}
        T10["Signal stage complete"]
        T11["Trigger next stage<br/>or finalize job"]
        T12["Done (not last task)"]

        T1 --> T2 --> T3 --> T4 --> T5
        T5 -->|Yes| T6 --> T8
        T5 -->|No| T7 --> T8
        T8 --> T9
        T9 -->|Yes| T10 --> T11
        T9 -->|No| T12
    end

    JobProcessing -.->|"Creates tasks"| TaskProcessing
    T11 -.->|"Next stage"| J4
```

### "Last Task Turns Out the Lights" Pattern

This sequence diagram shows how PostgreSQL advisory locks prevent race conditions when parallel tasks complete.

```mermaid
sequenceDiagram
    autonumber
    participant T1 as Task 1
    participant T2 as Task 2
    participant T3 as Task 3
    participant DB as PostgreSQL
    participant Lock as Advisory Lock
    participant CM as CoreMachine

    Note over T1,T3: Stage 1 has 3 parallel tasks

    par Parallel Execution
        T1->>T1: Execute handler
        T2->>T2: Execute handler
        T3->>T3: Execute handler
    end

    T2->>DB: UPDATE task SET status='COMPLETED'
    T2->>Lock: TRY pg_try_advisory_lock(stage_id)
    Lock-->>T2: Lock acquired ✓
    T2->>DB: SELECT COUNT(*) FROM tasks WHERE stage=1 AND status='PENDING'
    DB-->>T2: 2 remaining (T1, T3 not done)
    T2->>Lock: pg_advisory_unlock()
    Note over T2: Not last → exit

    T1->>DB: UPDATE task SET status='COMPLETED'
    T1->>Lock: TRY pg_try_advisory_lock(stage_id)
    Lock-->>T1: Lock acquired ✓
    T1->>DB: SELECT COUNT(*) FROM tasks WHERE stage=1 AND status='PENDING'
    DB-->>T1: 1 remaining (T3 not done)
    T1->>Lock: pg_advisory_unlock()
    Note over T1: Not last → exit

    T3->>DB: UPDATE task SET status='COMPLETED'
    T3->>Lock: TRY pg_try_advisory_lock(stage_id)
    Lock-->>T3: Lock acquired ✓
    T3->>DB: SELECT COUNT(*) FROM tasks WHERE stage=1 AND status='PENDING'
    DB-->>T3: 0 remaining ← LAST TASK!
    T3->>CM: Signal stage_complete(stage=1)
    T3->>Lock: pg_advisory_unlock()

    CM->>CM: Advance to Stage 2 or Finalize
```

### Job State Machine

```mermaid
stateDiagram-v2
    [*] --> QUEUED: Job submitted

    QUEUED --> PROCESSING: CoreMachine picks up job

    PROCESSING --> PROCESSING: Stage N complete,<br/>advance to Stage N+1

    PROCESSING --> COMPLETED: All stages complete,<br/>all tasks successful

    PROCESSING --> COMPLETED_WITH_ERRORS: All stages complete,<br/>some tasks failed

    PROCESSING --> FAILED: Critical error or<br/>all tasks in stage failed

    COMPLETED --> [*]
    COMPLETED_WITH_ERRORS --> [*]
    FAILED --> [*]

    note right of PROCESSING
        Job stays in PROCESSING
        while stages execute.
        Stage transitions happen
        internally.
    end note
```

### Task State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: Task created

    PENDING --> QUEUED: Routed to Service Bus

    QUEUED --> PROCESSING: Worker picks up message

    PROCESSING --> COMPLETED: Handler returns success=true

    PROCESSING --> FAILED: Handler returns success=false<br/>or raises exception

    COMPLETED --> [*]
    FAILED --> [*]

    note right of PROCESSING
        Task execution is atomic.
        No partial completion.
        Result stored in task record.
    end note
```

### Stage State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: Stage defined in job

    PENDING --> IN_PROGRESS: First task starts processing

    IN_PROGRESS --> COMPLETED: Last task completes<br/>(advisory lock detects)

    IN_PROGRESS --> FAILED: All tasks failed<br/>or critical error

    COMPLETED --> [*]: Triggers next stage
    FAILED --> [*]: Job fails

    note right of IN_PROGRESS
        Multiple tasks execute
        in parallel within stage.
        "Last task turns out lights"
        pattern detects completion.
    end note
```

### Combined State Flow

```mermaid
flowchart LR
    subgraph Job["Job Lifecycle"]
        JQ["QUEUED"] --> JP["PROCESSING"]
        JP --> JC["COMPLETED"]
        JP --> JE["COMPLETED_WITH_ERRORS"]
        JP --> JF["FAILED"]
    end

    subgraph Stage["Stage Lifecycle (per stage)"]
        SP["PENDING"] --> SI["IN_PROGRESS"]
        SI --> SC["COMPLETED"]
        SI --> SF["FAILED"]
    end

    subgraph Task["Task Lifecycle (per task)"]
        TP["PENDING"] --> TQ["QUEUED"]
        TQ --> TI["PROCESSING"]
        TI --> TC["COMPLETED"]
        TI --> TF["FAILED"]
    end

    JP -.->|"Creates stages"| SP
    SI -.->|"Creates tasks"| TP
    SC -.->|"Next stage or"| JC
    TC -.->|"Last task signals"| SC
```

---

**Full diagram set**: See [ARCHITECTURE_DIAGRAMS.md](docs_claude/ARCHITECTURE_DIAGRAMS.md) for additional C4 views (System Context, Container, Data Flow, Sequences)

---

## Further Reading

**Distributed Systems**:
- [Azure Functions Best Practices](https://learn.microsoft.com/en-us/azure/azure-functions/functions-best-practices)
- [Martin Kleppmann - Designing Data-Intensive Applications](https://dataintensive.net/)

**Geospatial Basics**:
- [PostGIS Documentation](https://postgis.net/documentation/)
- [STAC Specification](https://stacspec.org/)
- [OGC API - Features Standard](https://ogcapi.ogc.org/features/)

**Python Libraries**:
- [GeoPandas User Guide](https://geopandas.org/en/stable/getting_started.html)
- [Rasterio Documentation](https://rasterio.readthedocs.io/)
- [Shapely Manual](https://shapely.readthedocs.io/)

---

**Questions?** See the [full onboarding guide](onboarding.md) or contact the team.
