# Geospatial ETL Pipeline - Developer Onboarding

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Last Updated**: 18 NOV 2025
**Purpose**: Comprehensive onboarding guide for new developers joining the geospatial data platform team

---

## What This System Does

**Input**: Geospatial datasets in various formats
- **Vector**: Shapefile, GeoPackage, GeoJSON, KML, CSV with coordinates
- **Raster**: GeoTIFF, Cloud-Optimized GeoTIFF (COG), JPEG2000

**Process**: Validates, optimizes, and loads data into API-ready storage
- Geometry validation and repair (vector)
- COG optimization with compression and overviews (raster)
- Parallel processing for large datasets (millions of features, multi-GB files)
- Automatic STAC metadata catalog generation

**Output**: Standards-based REST APIs (no custom client code required)
- **OGC API - Features** for vector data (GeoJSON responses)
- **TiTiler** for raster tiles (XYZ tile endpoints)
- **STAC API** for catalog search (spatiotemporal queries)

---

## Core Design Principles

1. **Stateless Functions**: Azure Functions handle compute, PostgreSQL handles ALL state
2. **Cloud-Native**: No on-premises patterns (no POSIX ACLs, no filesystem mounting, no shared drives)
3. **Standards-Based**: Open Geospatial Consortium (OGC) APIs, STAC metadata, Cloud-Optimized GeoTIFFs
4. **Idempotent Operations**: All processes can safely retry without side effects (deterministic job IDs)
5. **Atomic Tasks**: Tasks succeed completely or fail completely - no partial states

---

## Architecture Overview

### The Two-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ PLATFORM LAYER (Client-Facing API)                         │
│ • HTTP job submission (POST /api/jobs/submit/{job_type})   │
│ • Status queries (GET /api/jobs/status/{job_id})           │
│ • Standards APIs (OGC Features, STAC, TiTiler)             │
│ • Interactive web maps (Leaflet-based viewers)             │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ COREMACHINE LAYER (Job Orchestration Engine)               │
│ • Job→Stage→Task orchestration (450 lines)                 │
│ • Service Bus queue management (jobs + tasks)              │
│ • PostgreSQL state tracking + advisory locks               │
│ • Composition over inheritance (dependencies injected)      │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ DATA STORAGE LAYER                                          │
│ • PostgreSQL with PostGIS (vector data in geo schema)      │
│ • PostgreSQL with pgSTAC (metadata in pgstac schema)       │
│ • Azure Blob Storage (COG rasters for TiTiler)             │
└─────────────────────────────────────────────────────────────┘
```

### CoreMachine Design

CoreMachine is a lightweight orchestration engine (450 lines) that coordinates workflow execution by delegating to specialized components:

- **StateManager**: Database operations (create/update jobs and tasks)
- **OrchestrationManager**: Dynamic task creation (fan-out patterns)
- **RepositoryFactory**: Connection management (PostgreSQL, Service Bus, Blob Storage)

**Architecture Pattern**: Dependency injection - all components are passed in, not created internally. Benefits:
- Easy to test (mock dependencies)
- Easy to swap implementations (e.g., different database backends)
- Clear separation of concerns (each component has one responsibility)

---

## Orchestration Pattern

### Job → Stage → Task Abstraction

```
JOB (Complete workflow, e.g., "ingest vector data")
 ├── STAGE 1: Validate file and extract metadata (sequential)
 │   └── Task A: Load file, check CRS, validate geometries
 │
 ├── STAGE 2: Create PostGIS table (sequential - waits for Stage 1)
 │   └── Task B: Generate schema, create indices
 │
 ├── STAGE 3: Upload chunks to PostGIS (parallel - fan-out)
 │   ├── Task C: Upload chunk 1 (10,000 rows)
 │   ├── Task D: Upload chunk 2 (10,000 rows)
 │   └── Task E: Upload chunk 3 (10,000 rows)
 │       ↓ Last task completes, stage advances
 │
 └── STAGE 4: Create STAC record and validate API (sequential)
     └── Task F: Insert STAC item, test OGC Features endpoint
```

**Key Concepts**:
- **Stages execute sequentially**: Stage 2 waits for Stage 1 to complete
- **Tasks within a stage can run in parallel**: 20+ concurrent uploads tested at production scale
- **Results flow forward**: Stage 2 receives Stage 1 results via `previous_results` parameter

### State Management (PostgreSQL Tables)

```sql
-- Jobs Table (app schema)
CREATE TABLE jobs (
    job_id VARCHAR PRIMARY KEY,      -- SHA256 hash of parameters (idempotency)
    job_type VARCHAR,                -- 'process_vector', 'process_raster_v2', etc.
    status VARCHAR,                  -- 'Queued', 'Processing', 'Completed', 'Failed'
    stage INTEGER,                   -- Current stage (1 to n)
    total_stages INTEGER,            -- Total number of stages
    parameters JSONB,                -- Job configuration
    stage_results JSONB,             -- Accumulated results from completed stages
    error_message TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Tasks Table (app schema)
CREATE TABLE tasks (
    task_id VARCHAR PRIMARY KEY,     -- Deterministic: {job_id[0:8]}-{stage_name}-{task_index}
    job_id VARCHAR REFERENCES jobs(job_id),
    task_type VARCHAR,               -- Handler name ('validate_vector', 'upload_postgis', etc.)
    stage INTEGER,
    status VARCHAR,                  -- 'Queued', 'Processing', 'Completed', 'Failed'
    parameters JSONB,                -- Task-specific parameters
    result_data JSONB,               -- Output data (passed to next stage)
    error_message TEXT,
    retry_count INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### Orchestration Flow

```
1. HTTP Trigger: Submit Job
   ├─> Hash parameters → job_id (SHA256 for idempotency)
   ├─> Validate parameters (job-specific validation)
   ├─> Create Job Record (status: 'Queued', stage: 1)
   ├─> Send Job Message to Service Bus jobs queue
   └─> Return job_id to caller (202 Accepted)

2. Job Queue Trigger: Process Job Message
   ├─> Read Job Record from database
   ├─> Call job.create_tasks_for_stage(stage=1, ...)
   ├─> Create Task Record(s) for current stage
   ├─> Send Task Message(s) to Service Bus tasks queue
   └─> Update Job Record (status: 'Processing')

3. Task Queue Trigger: Process Task Message(s)
   ├─> Execute task handler (atomic operation)
   ├─> Update Task Record (status: 'Completed', store results)
   ├─> Call PostgreSQL function: complete_task_and_check_stage()
   │   ├─> Acquires advisory lock (prevents race conditions)
   │   ├─> Counts remaining incomplete tasks for this stage
   │   ├─> If count = 0: Returns TRUE (last task indicator)
   │   └─> Releases lock automatically
   ├─> If TRUE returned:
   │   ├─> Update Job Record (advance stage or mark complete)
   │   ├─> If more stages: Send new Job Message to jobs queue
   │   └─> If final stage: Call job.finalize_job()
   └─> If FALSE: Done (other tasks still running)

4. Repeat steps 2-3 for each stage until Job completes
```

### The "Last One Turns Off the Lights" Pattern

**Design**: When multiple tasks complete simultaneously, PostgreSQL functions with advisory locks prevent race conditions

**How it works**:
1. Task completes and calls `complete_task_and_check_stage(job_id, task_id, stage)`
2. PostgreSQL function:
   - Acquires advisory lock on `job_id:stage` (single serialization point)
   - Updates task status to 'Completed'
   - Counts remaining incomplete tasks: `SELECT COUNT(*) WHERE status != 'Completed'`
   - If count = 0, marks stage complete and returns TRUE
   - Releases lock automatically (transaction scope)
3. If TRUE returned, CoreMachine advances job to next stage


**SQL Implementation** (in schema - developers do not write this):
```sql
CREATE OR REPLACE FUNCTION complete_task_and_check_stage(
    p_job_id VARCHAR,
    p_task_id VARCHAR,
    p_stage INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    v_remaining INTEGER;
BEGIN
    -- Single serialization point per job-stage (O(1) complexity)
    PERFORM pg_advisory_xact_lock(hashtext(p_job_id || ':stage:' || p_stage::text));

    -- Update task status
    UPDATE tasks SET status = 'Completed', updated_at = NOW()
    WHERE task_id = p_task_id;

    -- Count remaining tasks (no row-level locks needed)
    SELECT COUNT(*) INTO v_remaining
    FROM tasks
    WHERE job_id = p_job_id AND stage = p_stage AND status != 'Completed';

    RETURN (v_remaining = 0);  -- TRUE if I'm the last one
END;
$$ LANGUAGE plpgsql;
```

### Deterministic Task IDs

Task IDs follow a pattern that enables stage-to-stage result passing:

```
Format: {job_id[0:8]}-{stage_name}-{task_index}

Example:
Job ID: a3f7b2c1d4e5f6g7h8i9j0k1l2m3n4o5
Stage 3, Task 2 of vector job:
Task ID: a3f7b2c1-upload-002

Why deterministic?
- Enables idempotency (resubmit same task = same task_id)
- Enables result lookup (Stage 3 queries Stage 2 results by task_id pattern)
- Enables debugging (task ID tells you job, stage, and position)
```

---

## Vector Processing Workflow

### Production Scale Example

**Typical Scale**: Multi-million row datasets (CSV, Shapefile, GeoPackage)
**Workflow**: 4 stages with parallel upload
**Performance**: ~15 minutes for 2.5M rows with 129 parallel tasks

### Stage 1: File Load & Validation

**Inputs**: File path in Azure Blob Storage workspace container
**Outputs**: GeoDataFrame metadata (row count, CRS, geometry types, bounds, validation status)
**Parallelism**: Single task (file is analyzed as a whole)

```python
import geopandas as gpd
from shapely.validation import explain_validity

async def stage1_load_and_validate(file_path: str) -> dict:
    """
    Load geospatial file and perform initial validation.
    Supports: Shapefile, GeoPackage, KML, KMZ, GeoJSON, CSV with coordinates
    """
    # Load to GeoDataFrame
    gdf = gpd.read_file(file_path)

    # Basic validation
    if gdf.empty:
        raise ValueError("Empty dataset")

    if gdf.crs is None:
        raise ValueError("No CRS defined - unable to determine coordinate system")

    # Check geometry validity (DON'T fix yet - just log for Stage 2)
    invalid = ~gdf.geometry.is_valid
    invalid_reasons = []
    if invalid.any():
        for idx in gdf[invalid].index[:10]:  # Sample first 10
            reason = explain_validity(gdf.loc[idx, 'geometry'])
            invalid_reasons.append(f"Row {idx}: {reason}")

    return {
        'row_count': len(gdf),
        'crs': str(gdf.crs),
        'geometry_types': gdf.geometry.type.unique().tolist(),
        'bounds': gdf.total_bounds.tolist(),  # [minx, miny, maxx, maxy]
        'invalid_count': invalid.sum(),
        'invalid_sample': invalid_reasons[:10]  # For debugging
    }
```

### Stage 2: PostGIS Preparation & Chunking

**Inputs**: File path, Stage 1 metadata
**Outputs**: Chunking strategy (n_chunks, chunk_size), table schema, chunk file paths
**Parallelism**: Single task (table creation is sequential)

```python
async def stage2_prepare_and_chunk(file_path: str, metadata: dict, params: dict) -> dict:
    """
    Fix geometries, determine chunking strategy, create target table.
    """
    # Reload file (Stage 1 didn't pass the GeoDataFrame to save memory)
    gdf = gpd.read_file(file_path)

    # Fix invalid geometries
    if metadata['invalid_count'] > 0:
        gdf['geometry'] = gdf.geometry.buffer(0)  # Common fix for self-intersections
        gdf['geometry'] = gdf.geometry.make_valid()  # Shapely 2.0+ method

    # Handle mixed geometry types (PostGIS requires single type per column)
    geom_types = gdf.geometry.type.unique()
    if len(geom_types) > 1:
        # Strategy: Keep most common type, convert others to that type
        main_type = gdf.geometry.type.mode()[0]
        # For production: might need more sophisticated handling
        logger.warning(f"Mixed geometry types: {geom_types}. Using {main_type}.")

    # Reproject if needed (API typically serves EPSG:4326 or EPSG:3857)
    target_crs = params.get('target_crs', 'EPSG:4326')
    if gdf.crs.to_string() != target_crs:
        gdf = gdf.to_crs(target_crs)

    # Determine chunking (balance memory vs parallelism)
    CHUNK_SIZE = params.get('chunk_size', 20000)  # Tested at production scale
    n_chunks = (len(gdf) // CHUNK_SIZE) + 1

    # Create table with indices
    table_name = params['target_table']
    indices = params.get('indices', [])  # User-specified attribute columns

    await create_postgis_table(
        table_name=table_name,
        schema=gdf.dtypes.to_dict(),
        geometry_type=main_type,
        srid=gdf.crs.to_epsg(),
        indices=['geometry'] + indices  # GIST on geometry column
    )

    # Serialize chunks to workspace storage for Stage 3
    chunk_paths = []
    for i in range(n_chunks):
        chunk = gdf.iloc[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        chunk_path = f"workspace/{job_id[:8]}/chunk_{i:03d}.parquet"
        chunk.to_parquet(chunk_path)  # Faster than pickle for GeoDataFrames
        chunk_paths.append(chunk_path)

    return {
        'n_chunks': n_chunks,
        'chunk_size': CHUNK_SIZE,
        'table_name': table_name,
        'chunk_paths': chunk_paths,
        'total_rows': len(gdf)
    }
```

### Stage 3: Parallel Upload to PostGIS

**Inputs**: Chunk paths from Stage 2
**Outputs**: Upload confirmation per chunk (rows_uploaded)
**Parallelism**: Fan-out to N tasks (tested with 129 concurrent tasks at production scale)

```python
async def stage3_upload_chunk(task_index: int, chunk_path: str, table_name: str):
    """
    Upload one chunk to PostGIS. This runs in parallel with other chunk uploads.
    """
    # Load chunk
    gdf = gpd.read_parquet(chunk_path)

    # Upload to PostGIS using GeoPandas
    # Note: Uses repository pattern - PostgreSQLRepository manages connection
    from infrastructure.postgresql import PostgreSQLRepository
    repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        gdf.to_postgis(
            name=table_name,
            con=conn,
            if_exists='append',  # Table created in Stage 2
            index=False,
            schema='geo'  # Our vector data schema
        )

    # Cleanup chunk file (save workspace storage costs)
    os.remove(chunk_path)

    return {
        'rows_uploaded': len(gdf),
        'chunk_index': task_index
    }
```

### Stage 4: STAC Record & API Validation

**Inputs**: Table name, metadata from previous stages
**Outputs**: STAC item ID, OGC Features API endpoint validation
**Parallelism**: Single task (finalization is sequential)

```python
async def stage4_finalize(job_id: str, table_name: str, all_metadata: dict):
    """
    Create STAC metadata record and validate API access.
    """
    # Create STAC Item in pgSTAC schema
    stac_item = {
        'type': 'Feature',
        'stac_version': '1.0.0',
        'id': job_id[:16],  # Shortened for readability
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[
                [all_metadata['bounds'][0], all_metadata['bounds'][1]],
                [all_metadata['bounds'][2], all_metadata['bounds'][1]],
                [all_metadata['bounds'][2], all_metadata['bounds'][3]],
                [all_metadata['bounds'][0], all_metadata['bounds'][3]],
                [all_metadata['bounds'][0], all_metadata['bounds'][1]]
            ]]
        },
        'bbox': all_metadata['bounds'],
        'properties': {
            'datetime': datetime.utcnow().isoformat() + 'Z',
            'table_name': table_name,
            'row_count': all_metadata['total_rows'],
            'geometry_types': all_metadata['geometry_types']
        },
        'assets': {
            'data': {
                'href': f'https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/{table_name}/items',
                'type': 'application/geo+json',
                'roles': ['data'],
                'title': 'OGC API - Features endpoint'
            }
        }
    }

    # Insert to pgSTAC (uses PgStacRepository)
    from infrastructure.pgstac_repository import PgStacRepository
    pgstac_repo = PgStacRepository()
    pgstac_repo.insert_item(stac_item)

    # Validate OGC API Features access (self-test)
    test_url = f'https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/{table_name}/items?limit=1'
    response = await httpx.get(test_url, timeout=30.0)
    if response.status_code != 200:
        raise ValueError(f"API validation failed: {response.text}")

    # Optional: Trigger completion webhook to client application
    if 'callback_url' in all_metadata:
        await httpx.post(
            all_metadata['callback_url'],
            json={'job_id': job_id, 'status': 'completed', 'api_endpoint': test_url}
        )

    return {
        'stac_item_id': stac_item['id'],
        'api_endpoint': test_url,
        'validation': 'passed'
    }
```

---

## Raster Processing Workflows

### Single COG Workflow

**Use Case**: Individual GeoTIFF or image file
**Stages**: 2 (COG optimization → STAC + TiTiler validation)

#### Stage 1: COG Optimization

**Goal**: Convert source raster to Cloud-Optimized GeoTIFF with:
- Internal tiling (512x512 blocks for web serving)
- Compression (JPEG for RGB imagery, DEFLATE for DEMs)
- Overviews (pyramids for zoom levels)
- Web Mercator reprojection (EPSG:3857 if needed)

```python
import rasterio
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

async def stage1_create_cog(input_path: str, output_path: str, params: dict):
    """
    Convert source raster to Cloud-Optimized GeoTIFF.

    COG Optimizations:
    - Internal tiling (512x512 blocks for web serving)
    - Compression: JPEG (RGB imagery), DEFLATE (DEMs), LZW (general)
    - Overviews: Automatically generated pyramids for zoom performance
    - Reprojection: Web Mercator (EPSG:3857) for web maps
    """

    with rasterio.open(input_path) as src:
        # Analyze source characteristics
        profile = src.profile
        dtype = src.dtypes[0]
        band_count = src.count

        # Select compression based on data type
        if dtype in ['uint8', 'uint16'] and band_count == 3:
            # RGB imagery: JPEG compression (lossy but efficient)
            compression = 'JPEG'
            quality = 85
        elif dtype in ['float32', 'float64']:
            # Elevation/continuous data: DEFLATE (lossless)
            compression = 'DEFLATE'
            quality = None
        else:
            # General case: LZW (lossless, good compression)
            compression = 'LZW'
            quality = None

        # Configure COG profile
        cog_profile = cog_profiles.get('lzw')  # Base profile
        cog_profile.update({
            'COMPRESS': compression,
            'TILED': True,
            'BLOCKXSIZE': 512,
            'BLOCKYSIZE': 512,
            'OVERVIEW_RESAMPLING': 'AVERAGE',  # Or CUBIC for DEMs
        })

        # Reproject to Web Mercator if needed
        if src.crs and src.crs.to_epsg() != 3857:
            cog_profile['dst_crs'] = 'EPSG:3857'

        # Translate to COG
        cog_translate(
            src,
            output_path,
            cog_profile,
            in_memory=False,  # Use temp files for large datasets (>1GB)
            quiet=False
        )

    # Upload to Azure Blob Storage (api-data container)
    blob_url = await upload_to_blob(output_path, container='api-data')

    return {
        'cog_path': blob_url,
        'size_mb': os.path.getsize(output_path) / 1024 / 1024,
        'compression': compression
    }
```

#### Stage 2: STAC Record & TiTiler Validation

**Goal**: Register COG in STAC catalog and validate TiTiler can serve tiles

```python
async def stage2_stac_and_validate(cog_path: str, metadata: dict):
    """
    Create STAC item and validate TiTiler can serve it.
    """
    # Build TiTiler URL (dynamic tile generation)
    titiler_url = f"https://functionapurl.eastus-01.azurewebsites.net/tiles/cog/tiles/{{z}}/{{x}}/{{y}}?url={cog_path}"

    # Validate: Fetch tile 0/0/0 (exists for global rasters)
    test_tile = titiler_url.format(z=0, x=0, y=0)
    response = await httpx.get(test_tile, timeout=30.0)
    if response.status_code != 200:
        raise ValueError(f"TiTiler validation failed: {response.text}")

    # Create STAC item
    stac_item = {
        'type': 'Feature',
        'stac_version': '1.0.0',
        'id': metadata['job_id'][:16],
        'geometry': metadata['bounds_as_geojson'],
        'bbox': metadata['bounds'],
        'properties': {
            'datetime': datetime.utcnow().isoformat() + 'Z',
            'gsd': metadata.get('ground_sample_distance'),  # Resolution in meters
        },
        'assets': {
            'cog': {
                'href': cog_path,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['data'],
                'title': 'Cloud-Optimized GeoTIFF'
            },
            'tiles': {
                'href': titiler_url,
                'type': 'application/json',
                'roles': ['tiles'],
                'title': 'TiTiler XYZ tiles'
            }
        }
    }

    # Insert to pgSTAC
    from infrastructure.pgstac_repository import PgStacRepository
    pgstac_repo = PgStacRepository()
    pgstac_repo.insert_item(stac_item)

    return {
        'stac_item_id': stac_item['id'],
        'tile_endpoint': titiler_url,
        'validation': 'passed'
    }
```

### Raster Collection Workflow (Multiple COGs)

**Use Case**: Time series, multi-scene imagery, or tiled global datasets
**Example**: Sentinel-2 imagery (multiple dates), FATHOM flood models (multiple return periods)

**Stage 1**: Parallel COG creation (fan-out to N tasks, one per source file)
**Stage 2**: TiTiler-pgSTAC registration (mosaic search query)

```python
async def stage2_register_mosaic(cog_paths: list, collection_id: str, metadata: dict):
    """
    Register a STAC Collection and enable TiTiler-pgSTAC mosaicking.

    TiTiler-pgSTAC serves multiple COGs as a single layer using STAC search queries.
    """
    # Create STAC Collection
    stac_collection = {
        'type': 'Collection',
        'stac_version': '1.0.0',
        'id': collection_id,
        'description': metadata.get('description', 'Raster collection'),
        'extent': {
            'spatial': {'bbox': [metadata['bounds']]},
            'temporal': {'interval': [[metadata['start_date'], metadata['end_date']]]}
        },
        'summaries': {
            'gsd': metadata.get('resolution_meters')
        }
    }

    # Insert collection to pgSTAC
    from infrastructure.pgstac_repository import PgStacRepository
    pgstac_repo = PgStacRepository()
    pgstac_repo.insert_collection(stac_collection)

    # Create STAC Items for each COG
    for idx, cog_path in enumerate(cog_paths):
        item = {
            'type': 'Feature',
            'stac_version': '1.0.0',
            'id': f"{collection_id}-{idx:04d}",
            'collection': collection_id,  # Link to parent collection
            'geometry': metadata['scene_geometries'][idx],
            'bbox': metadata['scene_bboxes'][idx],
            'properties': {
                'datetime': metadata['scene_dates'][idx]
            },
            'assets': {
                'cog': {
                    'href': cog_path,
                    'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                    'roles': ['data']
                }
            }
        }
        pgstac_repo.insert_item(item)

    # TiTiler-pgSTAC mosaic URL (dynamic mosaicking based on STAC search)
    # Client can query: /tiles/searches/{search_id}/tiles/{z}/{x}/{y}
    # Where search_id = collection_id (all items in collection)
    mosaic_url = f"https://functionapurl.eastus-01.azurewebsites.net/tiles/searches/{collection_id}/tiles/{{z}}/{{x}}/{{y}}"

    # Validate mosaic endpoint
    test_tile = mosaic_url.format(z=0, x=0, y=0)
    response = await httpx.get(test_tile, timeout=30.0)
    if response.status_code != 200:
        raise ValueError(f"TiTiler-pgSTAC validation failed: {response.text}")

    return {
        'collection_id': collection_id,
        'mosaic_url': mosaic_url,
        'item_count': len(cog_paths)
    }
```

---

## Standards-Based API Outputs

### ETL Jobs Output

When a job completes successfully, data is automatically available via industry-standard REST APIs. 

### 1. Vector Data → OGC API - Features

**Standard**: OGC API - Features Core 1.0 (official standard from Open Geospatial Consortium)
**Output Format**: GeoJSON (FeatureCollection)
**Client Support**: QGIS, ArcGIS Pro, Leaflet, OpenLayers, FME, GDAL/OGR

**Endpoints** (example for table `countries` in PostGIS):

```bash
# Landing page (entry point)
GET https://functionapurl.eastus-01.azurewebsites.net/api/features

# List all vector collections (automatically discovered from PostGIS geometry_columns)
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/collections

# Collection metadata (bbox, feature count, geometry type, CRS)
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries

# Query features with pagination
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries/items?limit=100&offset=0

# Spatial query with bounding box (minx,miny,maxx,maxy in EPSG:4326)
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries/items?bbox=-180,-90,180,90&limit=100

# Attribute filter (if supported)
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries/items?name=France

# Single feature by ID
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries/items/123

# Conformance classes (what standards we support)
GET https://functionapurl.eastus-01.azurewebsites.net/api/features/conformance
```

**Response Example** (GeoJSON FeatureCollection):
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]]
      },
      "properties": {
        "name": "France",
        "population": 67000000,
        "capital": "Paris"
      }
    }
  ],
  "numberMatched": 195,
  "numberReturned": 1,
  "links": [
    {"rel": "next", "href": "...?offset=1"}
  ]
}
```

**Client Integration** (JavaScript example):
```javascript
// Load features in web application (Leaflet example)
fetch('https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries/items?limit=100')
  .then(res => res.json())
  .then(data => {
    L.geoJSON(data, {
      onEachFeature: function(feature, layer) {
        layer.bindPopup(feature.properties.name);
      }
    }).addTo(map);
  });
```

### 2. Raster Data → TiTiler + Cloud-Optimized GeoTIFFs

**Format**: Cloud-Optimized GeoTIFF (COG) stored in Azure Blob Storage
**Tile Server**: TiTiler (dynamic tile generation from COG)
**Client Support**: Leaflet, OpenLayers, MapLibre, Cesium, ArcGIS API, Google Maps API

**Endpoints**:

```bash
# Single raster XYZ tile (z=zoom, x=tile_x, y=tile_y)
GET https://functionapurl.eastus-01.azurewebsites.net/tiles/cog/tiles/{z}/{x}/{y}?url=https://storage_account.blob.core.windows.net/api-data/dataset.tif

# Raster metadata (bounds, bands, CRS, data type)
GET https://functionapurl.eastus-01.azurewebsites.net/tiles/cog/info?url=https://storage_account.blob.core.windows.net/api-data/dataset.tif

# Raster statistics (min, max, mean, std dev per band)
GET https://functionapurl.eastus-01.azurewebsites.net/tiles/cog/statistics?url=https://storage_account.blob.core.windows.net/api-data/dataset.tif

# Preview image (PNG thumbnail)
GET https://functionapurl.eastus-01.azurewebsites.net/tiles/cog/preview.png?url=https://storage_account.blob.core.windows.net/api-data/dataset.tif
```

**Client Integration** (Leaflet example):
```javascript
// Add raster tiles to web map
const tileUrl = 'https://functionapurl.eastus-01.azurewebsites.net/tiles/cog/tiles/{z}/{x}/{y}?url=https://storage_account.blob.core.windows.net/api-data/elevation.tif';

L.tileLayer(tileUrl, {
  attribution: 'Elevation Data',
  maxZoom: 18
}).addTo(map);
```

**TiTiler**
- No pre-generated tile pyramid (saves storage costs)
- Dynamic rendering (change color ramps, bands, processing on-the-fly)
- COG partial reads (only fetches needed blocks, not entire file)
- Industry standard (used by NASA, USGS, Planet, Maxar)

### 3. All Data → STAC Catalog (Metadata Search)

**Standard**: SpatioTemporal Asset Catalog (STAC) v1.0
**Purpose**: Searchable metadata catalog for all geospatial assets (vector + raster)
**Client Support**: QGIS (STAC Browser plugin), ArcGIS Pro, GDAL, Python pystac-client

**Endpoints**:

```bash
# Landing page
GET https://functionapurl.eastus-01.azurewebsites.net/api/stac

# List all STAC collections
GET https://functionapurl.eastus-01.azurewebsites.net/api/collections

# Get specific collection metadata
GET https://functionapurl.eastus-01.azurewebsites.net/api/collections/my_collection

# Search items (POST with spatial + temporal filters)
POST https://functionapurl.eastus-01.azurewebsites.net/api/search
Content-Type: application/json

{
  "bbox": [-180, -90, 180, 90],
  "datetime": "2024-01-01T00:00:00Z/..",
  "collections": ["sentinel2", "landsat8"],
  "limit": 100
}

# Get single STAC item
GET https://functionapurl.eastus-01.azurewebsites.net/api/collections/my_collection/items/item_123
```

**STAC Item Example** (what your ETL job creates):
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "a3f7b2c1-dataset",
  "geometry": {"type": "Polygon", "coordinates": [...]},
  "bbox": [-180, -90, 180, 90],
  "properties": {
    "datetime": "2024-11-18T00:00:00Z",
    "table_name": "countries",
    "row_count": 195
  },
  "assets": {
    "data": {
      "href": "https://functionapurl.eastus-01.azurewebsites.net/api/features/collections/countries/items",
      "type": "application/geo+json",
      "roles": ["data"],
      "title": "OGC API - Features endpoint"
    }
  },
  "links": [
    {"rel": "self", "href": "..."},
    {"rel": "collection", "href": "..."}
  ]
}
```

**Client Integration** (Python pystac-client example):
```python
from pystac_client import Client

# Connect to STAC API
catalog = Client.open('https://functionapurl.eastus-01.azurewebsites.net/api/stac')

# Search for data (spatial + temporal)
search = catalog.search(
    bbox=[-70.7, -56.3, -70.6, -56.2],  # Bounding box
    datetime='2024-01-01/2024-12-31',
    collections=['my_collection']
)

# Iterate results
for item in search.items():
    print(f"Found: {item.id}")
    print(f"Data URL: {item.assets['data'].href}")
```

### 4. Interactive Web Map
Purpose: preview map for approval workflows

**Features**:
- Collection selector dropdown (all PostGIS collections auto-discovered)
- Load 50-1000 features with loading spinner
- Click polygons → popup shows feature properties
- Hover highlighting
- Zoom to features button
- Feature count display ("Showing X of Y features")

**Technology Stack**:
- Single HTML file (ogc_features/map.html)
- Leaflet 1.9.4 (from CDN)
- Vanilla JavaScript (no framework dependencies)
- Azure Storage Static Website hosting

**Use Case**: Quick data validation, stakeholder demos, public data exploration

---

## Creating New Data Pipelines (JobBaseMixin Pattern)

### JobBaseMixin Pattern

JobBaseMixin provides a declarative approach to job creation, eliminating common boilerplate:

**Manual Implementation**:
- ~350 lines: validation, ID generation, database ops, queue management
- Development time: 2+ hours per job

**JobBaseMixin Pattern**:
- ~80 lines: declarative configuration only
- Automatic handling: validation, IDs, database, queues
- Development time: 30 minutes per job
- Code reduction: 77%

**Current Usage**: Standard pattern for all new jobs (see `hello_world.py` for reference)

### Quick Start: Create a New Job in 5 Steps

#### Step 1: Create Job File (5 minutes)

Create `jobs/my_vector_ingestion.py`:

```python

"""
Vector Data Ingestion Job

Multi-Stage Workflow:
1. Stage 1: Validate file and extract metadata (CRS, geometry types, bounds)
2. Stage 2: Create PostGIS table and chunk data
3. Stage 3: Parallel upload of chunks to PostGIS (fan-out pattern)
4. Stage 4: Create STAC record and validate OGC API Features endpoint

"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class MyVectorIngestionJob(JobBaseMixin, JobBase):  # Mixin first for correct method resolution order
    """
    Vector data ingestion to PostGIS with automatic STAC cataloging.

    Supports: Shapefile, GeoPackage, GeoJSON, KML, CSV with coordinates
    Workflow: Validate → Prepare/Chunk → Parallel Upload → STAC Record
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "my_vector_ingestion"
    description = "Ingest vector data to PostGIS with parallel uploads and STAC catalog"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_vector_file",
            "parallelism": "single"  # Single task (analyzes file as whole)
        },
        {
            "number": 2,
            "name": "prepare",
            "task_type": "prepare_and_chunk",
            "parallelism": "single"  # Single task (table creation is sequential)
        },
        {
            "number": 3,
            "name": "upload",
            "task_type": "upload_postgis_chunk",
            "parallelism": "fan_out"  # Fan-out to N tasks (parallel uploads)
        },
        {
            "number": 4,
            "name": "finalize",
            "task_type": "create_stac_and_validate",
            "parallelism": "single"  # Single task (finalization is sequential)
        }
    ]

    # Declarative parameter validation (JobBaseMixin handles validation)
    parameters_schema = {
        'file_path': {
            'type': 'str',
            'required': True
        },
        'target_table': {
            'type': 'str',
            'required': True
        },
        'target_crs': {
            'type': 'str',
            'default': 'EPSG:4326',
            'allowed': ['EPSG:4326', 'EPSG:3857']  # Enum-like validation
        },
        'chunk_size': {
            'type': 'int',
            'default': 20000,
            'min': 1000,
            'max': 50000
        },
        'indices': {
            'type': 'list',
            'default': []  # User-specified attribute columns to index
        }
    }

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Task Creation (~40 lines)
    # ========================================================================
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate tasks for each stage.

        This is the ONLY job-specific logic needed - everything else provided by mixin.
        """
        if stage == 1:
            # Stage 1: Single validation task
            return [{
                "task_id": f"{job_id[:8]}-validate",
                "task_type": "validate_vector_file",
                "parameters": {
                    "file_path": job_params['file_path']
                }
            }]

        elif stage == 2:
            # Stage 2: Single preparation task (receives Stage 1 metadata)
            stage1_result = previous_results[0]['result']
            return [{
                "task_id": f"{job_id[:8]}-prepare",
                "task_type": "prepare_and_chunk",
                "parameters": {
                    "file_path": job_params['file_path'],
                    "target_table": job_params['target_table'],
                    "target_crs": job_params['target_crs'],
                    "chunk_size": job_params['chunk_size'],
                    "indices": job_params['indices'],
                    "metadata": stage1_result  # Pass forward
                }
            }]

        elif stage == 3:
            # Stage 3: Fan-out to N parallel upload tasks
            stage2_result = previous_results[0]['result']
            n_chunks = stage2_result['n_chunks']
            chunk_paths = stage2_result['chunk_paths']
            table_name = stage2_result['table_name']

            return [
                {
                    "task_id": f"{job_id[:8]}-upload-{i:03d}",
                    "task_type": "upload_postgis_chunk",
                    "parameters": {
                        "chunk_path": chunk_paths[i],
                        "table_name": table_name,
                        "chunk_index": i
                    }
                }
                for i in range(n_chunks)
            ]

        elif stage == 4:
            # Stage 4: Single finalization task (receives all previous results)
            stage1_metadata = previous_results[0]['result']
            stage2_metadata = previous_results[1]['result']
            # stage3_results = previous_results[2:]  # All chunk upload results

            return [{
                "task_id": f"{job_id[:8]}-finalize",
                "task_type": "create_stac_and_validate",
                "parameters": {
                    "job_id": job_id,
                    "table_name": stage2_metadata['table_name'],
                    "total_rows": stage2_metadata['total_rows'],
                    "bounds": stage1_metadata['bounds'],
                    "geometry_types": stage1_metadata['geometry_types']
                }
            }]

    # ========================================================================
    # JOB-SPECIFIC LOGIC: Finalization (~15 lines)
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create job completion summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "my_vector_ingestion"
            }

        # Extract final results from Stage 4 (STAC creation)
        stage4_result = context.task_results[-1]['result']

        return {
            "status": "completed",
            "job_type": "my_vector_ingestion",
            "tasks_completed": len(context.task_results),
            "stac_item_id": stage4_result['stac_item_id'],
            "api_endpoint": stage4_result['api_endpoint']
        }
```

#### Step 2: Register Job (1 minute)

Edit `jobs/__init__.py`:

```python
# Add import at top
from .my_vector_ingestion import MyVectorIngestionJob

# Add to ALL_JOBS dict
ALL_JOBS = {
    # ... existing jobs ...
    "my_vector_ingestion": MyVectorIngestionJob,  # ← ADD THIS LINE
}
```

#### Step 3: Create Task Handlers (10-15 minutes)

Create `services/my_vector_handlers.py`:

```python
"""Task handlers for vector ingestion job."""

import geopandas as gpd
from shapely.validation import explain_validity

def validate_vector_file(params: dict) -> dict:
    """Stage 1: Validate vector file and extract metadata."""
    file_path = params['file_path']

    gdf = gpd.read_file(file_path)

    if gdf.empty:
        raise ValueError("Empty dataset")
    if gdf.crs is None:
        raise ValueError("No CRS defined")

    invalid = ~gdf.geometry.is_valid

    return {
        "success": True,
        "result": {
            'row_count': len(gdf),
            'crs': str(gdf.crs),
            'geometry_types': gdf.geometry.type.unique().tolist(),
            'bounds': gdf.total_bounds.tolist(),
            'invalid_count': invalid.sum()
        }
    }

def prepare_and_chunk(params: dict) -> dict:
    """Stage 2: Fix geometries, create table, chunk data."""
    # Implementation from "Vector Processing Workflow" section above
    # ... (refer to stage2_prepare_and_chunk function)
    pass

def upload_postgis_chunk(params: dict) -> dict:
    """Stage 3: Upload one chunk to PostGIS (runs in parallel)."""
    # Implementation from "Vector Processing Workflow" section above
    # ... (refer to stage3_upload_chunk function)
    pass

def create_stac_and_validate(params: dict) -> dict:
    """Stage 4: Create STAC record and validate OGC API."""
    # Implementation from "Vector Processing Workflow" section above
    # ... (refer to stage4_finalize function)
    pass
```

#### Step 4: Register Task Handlers (1 minute)

Edit `services/__init__.py`:

```python
# Add import at top
from .my_vector_handlers import (
    validate_vector_file,
    prepare_and_chunk,
    upload_postgis_chunk,
    create_stac_and_validate
)

# Add to ALL_HANDLERS dict
ALL_HANDLERS = {
    # ... existing handlers ...
    "validate_vector_file": validate_vector_file,
    "prepare_and_chunk": prepare_and_chunk,
    "upload_postgis_chunk": upload_postgis_chunk,
    "create_stac_and_validate": create_stac_and_validate,
}
```

### Parameters Schema Reference

**Supported Types**:

```python
parameters_schema = {
    # String parameter
    'name': {
        'type': 'str',
        'required': True,           # Provided by user
        'default': 'default_value',  # Default if not provided
        'allowed': ['opt1', 'opt2']  # Enum-like validation (optional)
    },

    # Integer parameter
    'count': {
        'type': 'int',
        'default': 10,
        'min': 1,      # Minimum value (optional)
        'max': 100     # Maximum value (optional)
    },

    # Float parameter
    'threshold': {
        'type': 'float',
        'default': 0.5,
        'min': 0.0,
        'max': 1.0
    },

    # Boolean parameter
    'enabled': {
        'type': 'bool',
        'default': True
    },

    # List parameter
    'indices': {
        'type': 'list',
        'default': []  # Default empty list
    }
}
```

**Validation Rules**:
- `required`: If True, parameter is required (no default needed)
- `default`: Value used if parameter not provided by user
- `min/max`: For int/float types, enforces range
- `allowed`: For str type, enforces enum-like values (whitelist)

### Advanced: Overriding Mixin Methods (Rare)

**95% of jobs don't need this.** Only override when you need custom logic.

**Custom Job ID** (exclude certain params from hash):
```python
@classmethod
def generate_job_id(cls, params: dict) -> str:
    """Custom job ID - excludes 'debug_flag' from hash for testing."""
    import hashlib, json

    # Exclude testing parameters from idempotency hash
    hash_params = {k: v for k, v in params.items() if k != 'debug_flag'}

    canonical = json.dumps({
        'job_type': cls.job_type,
        **hash_params
    }, sort_keys=True)

    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
```

**Full Guide**: See [JOB_CREATION_QUICKSTART.md](JOB_CREATION_QUICKSTART.md) for complete documentation

---

## Development Environment Setup

### Prerequisites

```bash
# Python 3.11+ required (Azure Functions Python v2 model)
python --version

# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Login to Azure (required for managed identity local testing)
az login

# Install Azure Functions Core Tools (v4)
npm install -g azure-functions-core-tools@4

# Verify installation
func --version  # Verify version 4.x.x
```

### Local Database Setup

```bash
# Install PostgreSQL 14+ with PostGIS
sudo apt install postgresql-14 postgresql-14-postgis-3

# Install pgSTAC (STAC metadata catalog extension)
git clone https://github.com/stac-utils/pgstac.git
cd pgstac
psql -U postgres -d postgres -f pgstac.sql

# Create development database
createdb -U postgres geospatial_dev

# Enable extensions
psql -U postgres -d geospatial_dev -c "CREATE EXTENSION postgis;"
psql -U postgres -d geospatial_dev -c "CREATE EXTENSION pgstac;"

# Create schemas (matches production structure)
psql -U postgres -d geospatial_dev -c "CREATE SCHEMA geo;"     # Vector data
psql -U postgres -d geospatial_dev -c "CREATE SCHEMA app;"     # Job orchestration
psql -U postgres -d geospatial_dev -c "CREATE SCHEMA h3;"      # H3 grid system
# pgstac schema created automatically by extension
```

### Python Environment

```bash
# Clone repository
git clone <repo_url>
cd rmhgeoapi

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Verify GeoPandas + GDAL installed correctly
python -c "import geopandas; print(geopandas.__version__)"
```

### Key Dependencies (requirements.txt)

```python
# Azure Functions & Services
azure-functions==1.18.0
azure-identity==1.15.0
azure-storage-blob==12.19.0
azure-servicebus==7.11.4

# Geospatial libraries
geopandas==0.14.3
rasterio==1.3.9
rio-cogeo==5.1.0
shapely==2.0.2
GDAL==3.7.3

# Database
psycopg[binary]==3.1.12  # PostgreSQL driver (psycopg3)

# STAC
pystac==1.9.0
pypgstac==0.8.4

# Utilities
httpx==0.26.0
pydantic==2.5.0
```

### Local Configuration

**Note**: Use the example file as template (do not commit `local.settings.json` to git)

```bash
# Copy example configuration
cp local.settings.example.json local.settings.json

# Edit with your local settings
nano local.settings.json
```

**local.settings.json** (development configuration):
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",

    "POSTGRES_HOST": "localhost",
    "POSTGRES_DATABASE": "geospatial_dev",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "your_local_password",
    "POSTGRES_PORT": "5432",
    "USE_MANAGED_IDENTITY": "false",

    "SERVICEBUS_CONNECTION_STRING": "<copy from Azure Portal>",
    "SERVICEBUS_JOBS_QUEUE": "geospatial-jobs-dev",
    "SERVICEBUS_TASKS_QUEUE": "geospatial-tasks-dev",

    "BRONZE_STORAGE_ACCOUNT": "storage_account",
    "SILVER_STORAGE_ACCOUNT": "storage_account",
    "STORAGE_ACCOUNT_KEY": "<copy from Azure Portal>"
  }
}
```

**Azure Production Configuration** (managed identity - no passwords):
```bash
# Set in Azure Portal → Function App → Configuration → Application Settings
USE_MANAGED_IDENTITY=true
MANAGED_IDENTITY_NAME=function_app_name  # Function app name
POSTGRES_HOST=dbname.postgres.database.azure.com
POSTGRES_DATABASE=dbname
POSTGRES_USER=function_app_name  # Matches managed identity name
# NO POSTGRES_PASSWORD - system acquires token automatically
```

**Managed Identity Setup Guide**: See [QA_DEPLOYMENT.md]
### Running Locally

```bash
# Start Azurite (local storage emulator)
azurite --silent --location ./azurite --debug ./azurite/debug.log &

# Start Azure Functions
func start

# Verify health endpoint (shows system status checks)
curl http://localhost:7071/api/health
```

---

## Debugging & Troubleshooting

### Production Debugging: Application Insights

**Access production logs without Azure Portal**

#### Prerequisites

```bash
# Log into Azure CLI
az login

# Verify login
az account show --query "{subscription:name, user:user.name}" -o table
```

#### Query Script Pattern

**Note**: Inline commands fail due to shell evaluation issues with KQL queries. Use script files for reliability.

```bash
# Create reusable query script
cat > /tmp/query_logs.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 20" \
  -G | python3 -m json.tool
EOF

# Make executable and run
chmod +x /tmp/query_logs.sh
/tmp/query_logs.sh
```

#### Common KQL Queries

**Recent errors** (severity level >= 3):
```kql
traces
| where timestamp >= ago(1h)
| where severityLevel >= 3
| order by timestamp desc
| take 20
```

**Track specific job**:
```kql
traces
| where timestamp >= ago(30m)
| where message contains "job_id_here"
| order by timestamp desc
```

**Task processing events**:
```kql
traces
| where timestamp >= ago(15m)
| where message contains "Processing task"
| order by timestamp desc
```

**Health endpoint calls**:
```kql
union requests, traces
| where timestamp >= ago(30m)
| where operation_Name contains "health"
| take 20
```

**Azure Functions Python Logging Behavior**

Azure SDK maps `logging.DEBUG` to severity 1 (INFO) instead of 0 (DEBUG).

**Note**: This query returns zero results:
```kql
traces | where severityLevel == 0  # Azure Functions maps DEBUG to 1
```

**Search by message content instead**:
```kql
traces | where message contains '"level": "DEBUG"'
```

Requires `DEBUG_LOGGING=true` environment variable in Azure Functions configuration.

### Common Issues

#### Issue: Tasks Stuck in "Processing"

**Symptom**: Tasks show "Processing" status in database but aren't completing.

**Causes**:
1. Function timeout (default 5 minutes) - task needs more time
2. Service Bus message lock expired (default 5 minutes)
3. Unhandled exception before status update committed

**Debugging**:
```bash
# Check Application Insights for exceptions
/tmp/query_logs.sh  # Replace query with: traces | where severityLevel >= 3

# Check Service Bus dead-letter queue
az servicebus queue show \
  --name geospatial-tasks \
  --namespace-name rmhservicebus \
  --resource-group resource_group \
  --query "deadLetterMessageCount"
```

**Resolution**:
- Increase Function timeout in `host.json`: `"functionTimeout": "00:10:00"`
- Extend Service Bus lock duration: `"maxAutoRenewDuration": "00:10:00"`
- Add try/finally around database status updates

#### Issue: Geometry Validation Failures

**Symptom**: Stage 1 or 2 fails with "Invalid geometry" errors.

**Common Causes**:
- Self-intersecting polygons
- Duplicate vertices
- Mixed geometry types (Polygon + MultiPolygon)
- Invalid coordinates (NaN, Inf)

**Fix** (in Stage 2 handler):
```python
# Automatic geometry repair
gdf['geometry'] = gdf.geometry.buffer(0)          # Fix self-intersections
gdf['geometry'] = gdf.geometry.make_valid()       # Shapely 2.0+ method
gdf['geometry'] = gdf.geometry.simplify(0.0001)   # Remove duplicate vertices
gdf = gdf[gdf.geometry.is_valid]                  # Drop unfixable (last resort)
```

#### Issue: COG Files Not Accessible via TiTiler

**Symptom**: TiTiler returns 403 or 404 errors when requesting tiles.

**Causes**:
1. COG not uploaded to correct container (use `api-data`)
2. TiTiler Function App managed identity lacks Blob Reader role
3. Incorrect blob URL format (missing SAS token or public access)

**Debugging**:
```bash
# Verify blob exists
az storage blob exists \
  --account-name storage_account \
  --container-name api-data \
  --name dataset.tif \
  --auth-mode login

# Check blob URL is accessible
curl -I "https://storage_account.blob.core.windows.net/api-data/dataset.tif"

# Check Function App logs (if TiTiler)
az webapp log tail \
  --name function_app_name \
  --resource-group resource_group \
  --filter traces
```

**Resolution**:
- Ensure blob uploaded to `api-data` container (not `bronze` or `workspace`)
- Grant Function App managed identity "Storage Blob Data Reader" role
- Set container to "Blob (anonymous read access for blobs only)" if public data

---

## Deployment

### Active Function App

**Active Function App:**

- **Name**: `function_app_name`
- **URL**: `https://functionapurl.eastus-01.azurewebsites.net`
- **Tier**: B3 Basic
- **Resource Group**: `resource_group`

### Deployment Workflow

```bash
# 1. Validate locally (run first)
python3 -c "from jobs import validate_job_registry; validate_job_registry()"

# 2. Deploy to Azure Functions
func azure functionapp publish function_app_name --python --build remote

# 3. Redeploy database schema (required after deployment)
curl -X POST "https://functionapurl.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# 4. Health check (verify all systems green)
curl "https://functionapurl.eastus-01.azurewebsites.net/api/health"

# 5. Submit test job (hello_world is simplest)
curl -X POST "https://functionapurl.eastus-01.azurewebsites.net/api/jobs/submit/hello_world" \
  -H "Content-Type: application/json" \
  -d '{"message": "deployment test", "n": 3}'

# 6. Check job status (use job_id from step 5 response)
curl "https://functionapurl.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}"

# 7. Verify job completed successfully
curl "https://functionapurl.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}"
```

**Expected Results**:
- Step 3: "38/38 statements executed successfully"
- Step 4: JSON with all "status": "healthy"
- Step 5: `{"job_id": "...", "status": "queued"}`
- Step 6: `{"status": "Completed"}` (after ~30 seconds)
- Step 7: All tasks show `"status": "Completed"`

### Git Workflow (Dev Branch Strategy)

**Note**: Work on `dev` branch and commit frequently with detailed messages

```bash
# 1. Ensure you're on dev branch
git checkout dev

# 2. Make changes and commit frequently (detailed messages)
git add -A
git commit -m "Add vector ingestion job with parallel upload support

Technical details:
- Created MyVectorIngestionJob with JobBaseMixin pattern
- Implemented 4-stage workflow (validate → prepare → upload → stac)
- Tested with 100K feature GeoJSON (completed in 45 seconds)

Status: Working end-to-end
Known issues: None
"

# 3. Push to remote dev branch
git push origin dev

# 4. When stable and tested, merge to master
git checkout master
git merge dev
git push origin master

# 5. Continue working on dev
git checkout dev
```

**Branch Strategy Benefits**:
- Frequent commits on dev = Detailed change history
- Clean master = Only stable, tested code
- Easy rollback = Revert to last working commit
- Clear debugging = Git log shows what changed between states

Commit frequently with detailed messages to maintain good development history.

### CI/CD Pipeline (Future)

Deployments will use Azure DevOps with environment promotion:

1. **Dev**: Automatic deployment on merge to `dev` branch
2. **QA**: Manual approval required + automated tests
3. **Production**: Manual approval + change window + stakeholder notification


---

## Performance Considerations

### Chunking Strategy

**Goal**: Balance parallelism (faster) vs overhead (message size, memory)

```python
def calculate_optimal_chunks(row_count: int, avg_row_size_bytes: int) -> int:
    """
    Determine chunk size balancing parallelism vs overhead.

    Goals:
    - Each chunk fits in Function App memory (~2GB available)
    - Minimize Service Bus message overhead (256KB maximum)
    - Maximize parallelism for large datasets
    """
    MAX_CHUNK_SIZE = 50000   # rows per chunk (tested at production scale)
    MIN_CHUNK_SIZE = 1000    # avoid too many small tasks
    TARGET_CHUNK_MB = 500    # MB per chunk in memory

    # Estimate chunk size for target memory usage
    rows_per_chunk = int((TARGET_CHUNK_MB * 1024 * 1024) / avg_row_size_bytes)

    # Clamp to min/max
    rows_per_chunk = max(MIN_CHUNK_SIZE, min(MAX_CHUNK_SIZE, rows_per_chunk))

    n_chunks = (row_count // rows_per_chunk) + 1

    return n_chunks, rows_per_chunk
```

**Production Example**:
- 2.5 million rows, avg 400 bytes/row
- Chunk size: 20,000 rows/chunk (8MB memory per chunk)
- Total chunks: 129
- Concurrent processing: 20 tasks (Service Bus `maxConcurrentCalls`)
- Total time: ~15 minutes

### PostGIS Index Strategy

**Create GIST index on geometry** (spatial queries), optionally add B-tree on attribute columns.

```python
async def create_optimized_indices(table_name: str, attribute_columns: list):
    """
    Create indices for efficient OGC API Features queries.

    Standard indices:
    - GIST index on geometry (spatial queries via ST_Intersects, ST_DWithin)

    Optionally create (based on expected queries):
    - B-tree on frequently filtered columns (name, date, category)
    - Partial indices for common queries (e.g., WHERE active = true)
    """
    from infrastructure.postgresql import PostgreSQLRepository
    repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            # Spatial index (REQUIRED for performance)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {table_name}_geom_idx
                ON geo.{table_name} USING GIST (geometry);
            """)

            # Attribute indices (optional, based on parameters)
            for col in attribute_columns:
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS {table_name}_{col}_idx
                    ON geo.{table_name} ({col});
                """)

            # Update statistics for query planner
            cur.execute(f"ANALYZE geo.{table_name};")

        conn.commit()
```

**Query Performance Impact**:
- Without GIST index: 2-5 seconds for bbox query on 100K features
- With GIST index: 50-200ms for same query

### COG Optimization Parameters

**Goal**: Balance file size vs quality vs tile serving performance

```python
def get_cog_profile(src_profile: dict) -> dict:
    """
    Determine optimal COG configuration based on source characteristics.

    Decision tree:
    - RGB imagery (uint8, 3 bands) → JPEG compression
    - Elevation/continuous (float32) → DEFLATE compression + predictor
    - Categorical/general → LZW compression
    """
    dtype = src_profile['dtype']
    band_count = src_profile['count']

    if dtype in ['uint8', 'uint16'] and band_count == 3:
        # RGB imagery: JPEG compression (lossy but 10x smaller), AVERAGE resampling
        return {
            'compress': 'JPEG',
            'jpeg_quality': 85,                 # 85 = good balance quality/size
            'overview_resampling': 'AVERAGE',   # Smooth appearance at zoom out
            'blocksize': 512
        }
    elif dtype in ['float32', 'float64']:
        # Elevation/continuous data: DEFLATE (lossless), CUBIC resampling
        return {
            'compress': 'DEFLATE',
            'predictor': 3,                     # Floating-point predictor (better compression)
            'overview_resampling': 'CUBIC',     # Preserve elevation profiles
            'blocksize': 512
        }
    else:
        # General case: LZW (lossless, universal), NEAREST resampling
        return {
            'compress': 'LZW',
            'overview_resampling': 'NEAREST',   # Preserve values (categorical data)
            'blocksize': 512
        }
```

**Compression Comparison** (10GB GeoTIFF):
- Uncompressed: 10GB
- LZW: 3-5GB (lossless, universal)
- DEFLATE: 2-4GB (lossless, better than LZW)
- JPEG (RGB imagery): 500MB-1GB (lossy, visual quality)

---

## Security & Access Patterns

### Managed Identity Authentication (Production)

**All Azure resources use managed identities - no connection strings or passwords in code**

```python
from azure.identity import ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient

# Managed identity credential (automatic in Azure Functions)
credential = ManagedIdentityCredential()

# Blob Storage access (RBAC - Storage Blob Data Reader role required)
blob_client = BlobServiceClient(
    account_url="https://storage_account.blob.core.windows.net",
    credential=credential
)

# PostgreSQL access (Entra authentication - no password)
from infrastructure.postgresql import PostgreSQLRepository
repo = PostgreSQLRepository()  # Automatically uses managed identity in Azure

# With managed identity:
# - Tokens acquired automatically (hourly rotation)
# - No secrets in code or config
# - Centralized permission management via Azure RBAC
# - Audit trail of all access
```



### RBAC vs POSIX ACLs (Why We Don't Use Filesystem ACLs)

**Container-level RBAC with managed identity**

```python
# Direct blob access with RBAC
async def read_cog(blob_path: str):
    blob_client = blob_service.get_blob_client(container='api-data', blob=blob_path)
    data = await blob_client.download_blob()
    return data.readall()
```

**Avoid: Mount blob storage as filesystem with ACL checks**

```python
# Mounting as filesystem with POSIX ACL checks (not recommended)
# /mnt/blobfuse/api-data/dataset.tif
# - Slow ACL checks on every read operation
# - Breaks CDN edge caching
# - On-premises pattern in cloud environment
# - Single point of failure (mount)
```

**Why RBAC is Superior for Cloud**:
1. Token validated once per session (not per file access)
2. Enables CDN edge caching (no server-side ACL checks)
3. Container-level permissions scale better (not per-file)
4. Cloud-native pattern (matches Azure architecture)
5. Works with TiTiler's HTTP range requests

---

### Learning Resources

**Official Standards**:
- **PostGIS**: https://postgis.net/documentation/
- **STAC Spec**: https://stacspec.org/
- **OGC API - Features**: https://ogcapi.ogc.org/features/
- **TiTiler**: https://developmentseed.org/titiler/
- **COG Format**: https://www.cogeo.org/

**Azure Documentation**:
- **Azure Functions Python**: https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python
- **Service Bus**: https://learn.microsoft.com/en-us/azure/service-bus-messaging/
- **PostgreSQL Flexible Server**: https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/

**Python Geospatial**:
- **GeoPandas**: https://geopandas.org/
- **Rasterio**: https://rasterio.readthedocs.io/
- **Shapely**: https://shapely.readthedocs.io/
