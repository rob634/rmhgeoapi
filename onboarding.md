# Geospatial ETL Pipeline - Developer Onboarding

### What This System Does

**Input**: Geospatial datasets in various formats (Shapefiles, GeoPackage, GeoTIFF, etc.)  
**Process**: Validates, optimizes, and loads data into API-ready storage  
**Output**: Standards-based REST APIs (OGC API Features for vector, TiTiler for raster tiles, STAC for catalog)

### Core Design Principles

1. **Stateless Functions**: Azure Functions handle compute, PostgreSQL handles state
2. **Cloud-Native**: No on-premises patterns (no POSIX ACLs, no filesystem mounting)
3. **Standards-Based**: OGC APIs, STAC metadata, Cloud-Optimized GeoTIFFs
4. **Idempotent Operations**: All processes can safely retry without side effects
5. **Atomic Tasks**: Tasks succeed completely or fail completely - no partial states

## Architecture

### The Four Layers

```
┌─────────────────────────────────────────────────────────────┐
│ INGRESS LAYER                                               │
│ - Azure Data Factory (scheduled ingestion)                  │
│ - HTTP Trigger Functions (API-driven submission)            │
│ - Workspace Container (temp storage for large files)        │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ETL LAYER                               │
│ - Azure Function Apps (orchestration & processing)          │
│ - Azure Service Bus (job/task queuing)                      │
│ - PostgreSQL (state management, job tracking)               │
│ - Key Vault (secrets management)                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ DATA LAYER                                                  │
│ - PostgreSQL with PostGIS + pgSTAC (vector data, metadata)  │
│ - Azure Blob Storage (Cloud-Optimized GeoTIFFs)            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ API SERVICE LAYER                                           │
│ - Vector API + STAC API Function App (OGC API Features)               │
│ - TiTiler App Service (raster tile serving)                │
│ - API Management (routing, rate limiting, auth)             │
│ - Cloudflare (CDN + WAF for public APIs)                   │
└─────────────────────────────────────────────────────────────┘
```

### Dual Deployment Pattern

The Data and API Service layers have a parallel external deployment to ensure isolation and security.

- **Internal Instance**: Official Use Only (OUO) data, accessible only within World Bank network
- **External Instance**: Public data, accessible via internet

Each has separate PostgreSQL databases and storage containers to prevent data leakage.

## Orchestration Pattern

### Abstract Models

**Job**: Complete workflow orchestration (e.g., "process this GeoJSON")  
**Stage**: Sequential execution phases within a Job (cannot be parallelized)  
**Task**: Granular work units that CAN parallelize within a stage

### State Management

```sql
-- Jobs Table
CREATE TABLE jobs (
    job_id VARCHAR PRIMARY KEY,      -- Hash of parameters (idempotency)
    status VARCHAR,                  -- 'Queued', 'Processing', 'Completed', 'Failed'
    stage INTEGER,                   -- Current stage (1 to n)
    parameters JSONB,                -- Job configuration
    error_message TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Tasks Table
CREATE TABLE tasks (
    task_id VARCHAR PRIMARY KEY,     -- Deterministic: {job_id[0:8]}_{jobtype}_{stage}_{task_index}
    job_id VARCHAR REFERENCES jobs(job_id),
    stage INTEGER,
    status VARCHAR,                  -- 'Queued', 'Processing', 'Completed', 'Failed'
    results_data JSONB,              -- Output data for next stage
    error_message TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### Orchestration Flow

```
1. HTTP Trigger: Submit Job
   ├─> Hash parameters → job_id (idempotency)
   ├─> Create Job Record (status: 'Queued', stage: 1)
   ├─> Send Job Message to Service Bus Queue
   └─> Return job_id to caller

2. Job Queue Trigger: Process Job Message
   ├─> Read Job Record from database
   ├─> Create Task Record(s) for current stage
   ├─> Send Task Message(s) to Service Bus Queue
   └─> Update Job Record (status: 'Processing')

3. Task Queue Trigger: Process Task Message(s)
   ├─> Execute task logic (atomic operation)
   ├─> Update Task Record (status: 'Completed' or 'Failed')
   ├─> Acquire advisory lock
   ├─> Check: Am I the last task in this stage?
   │   ├─> YES: 
   │   │   ├─> Update Job Record (advance stage or mark complete)
   │   │   ├─> If more stages: Send new Job Message
   │   │   └─> If final stage: Trigger completion webhook
   │   └─> NO: Release lock and exit
   └─> Release advisory lock

4. Repeat steps 2-3 for each stage until Job completes
```

### The "Last One Turns Off the Lights" Pattern

**Problem**: How does the final parallel task know it's the last one without race conditions?

**Solution**: PostgreSQL advisory locks

```python
import asyncpg

async def check_and_advance_stage(pool, job_id: str, stage: int):
    """
    Check if this is the last task in the stage and advance if so.
    Uses advisory lock to prevent race conditions.
    """
    async with pool.acquire() as conn:
        # Acquire exclusive advisory lock based on job_id
        lock_id = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)
        await conn.execute("SELECT pg_advisory_lock($1)", lock_id)
        
        try:
            # Count incomplete tasks for this stage
            incomplete = await conn.fetchval("""
                SELECT COUNT(*) FROM tasks 
                WHERE job_id = $1 AND stage = $2 AND status != 'Completed'
            """, job_id, stage)
            
            if incomplete == 0:
                # I'm the last one! Advance the job stage
                await conn.execute("""
                    UPDATE jobs 
                    SET stage = stage + 1, updated_at = NOW()
                    WHERE job_id = $1
                """, job_id)
                return True  # Signal to queue next stage
            
            return False  # Other tasks still running
            
        finally:
            # Always release lock
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
```

### Deterministic Task IDs

Task IDs follow a pattern that allows stages to find their predecessor's results:

```
Format: {job_id[0:8]}_{jobtype}_{stagename}_{task_index}

Example:
Job ID: a3f7b2c1d4e5f6g7h8i9j0k1l2m3n4o5
Stage 3, Task 2 of vector job:
Task ID: a3f7b2c1_vector_stage3_002

This task needs chunk parameters from Stage 2?
Query: SELECT results_data FROM tasks 
       WHERE task_id = 'a3f7b2c1_vector_stage2_001'
```

## Vector Processing Workflow

### Stage 1: File Load & Validation

**Inputs**: File path in workspace container  
**Outputs**: Validated GeoDataFrame metadata

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
        raise ValueError("No CRS defined")
    
    # Check geometry validity
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        # Log invalid geometries with explanations
        for idx in gdf[invalid].index:
            reason = explain_validity(gdf.loc[idx, 'geometry'])
            # Store for Stage 2 to fix
    
    return {
        'row_count': len(gdf),
        'crs': str(gdf.crs),
        'geometry_type': gdf.geometry.type.unique().tolist(),
        'bounds': gdf.total_bounds.tolist(),
        'has_invalid': invalid.sum()
    }
```

### Stage 2: PostGIS Preparation & Chunking

**Inputs**: File path, Stage 1 metadata  
**Outputs**: Chunking strategy, table schema

```python
async def stage2_prepare_and_chunk(gdf: gpd.GeoDataFrame, params: dict) -> dict:
    """
    Fix geometries, determine chunking strategy, create target table.
    """
    # Fix invalid geometries
    gdf['geometry'] = gdf.geometry.buffer(0)  # Common fix
    
    # Handle mixed geometry types (PostGIS doesn't allow in single column)
    geom_types = gdf.geometry.type.unique()
    if len(geom_types) > 1:
        # Strategy: separate tables or convert to GeometryCollection
        pass
    
    # Reproject if needed (API serves Web Mercator typically)
    if gdf.crs.to_epsg() != 3857:
        gdf = gdf.to_crs(epsg=3857)
    
    # Determine chunking (balance memory vs parallelism)
    CHUNK_SIZE = 10000  # rows per chunk
    n_chunks = (len(gdf) // CHUNK_SIZE) + 1
    
    # Create table with indices
    table_name = params['target_table']
    indices = params.get('indices', [])  # User-specified columns
    
    await create_postgis_table(
        table_name=table_name,
        schema=gdf.dtypes.to_dict(),
        geometry_type=gdf.geometry.type.mode()[0],
        srid=gdf.crs.to_epsg(),
        indices=['geometry'] + indices  # GIST on geometry always
    )
    
    # Serialize chunks to pickles for Stage 3
    for i in range(n_chunks):
        chunk = gdf.iloc[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        chunk_path = f"workspace/{task_id}_chunk_{i}.pkl"
        chunk.to_pickle(chunk_path)
    
    return {
        'n_chunks': n_chunks,
        'table_name': table_name,
        'total_rows': len(gdf)
    }
```

### Stage 3: Parallel Upload to PostGIS

**Inputs**: Chunk paths from Stage 2  
**Outputs**: Upload confirmation per chunk

```python
async def stage3_upload_chunk(task_index: int, chunk_path: str, table_name: str):
    """
    Upload one chunk to PostGIS. This runs in parallel with other chunk uploads.
    """
    # Load chunk
    gdf = gpd.read_pickle(chunk_path)
    
    # Convert to PostGIS-compatible format
    # Use GeoPandas to_postgis() or manual INSERT
    await gdf.to_postgis(
        name=table_name,
        con=engine,
        if_exists='append',  # Table created in Stage 2
        index=False
    )
    
    # Cleanup
    os.remove(chunk_path)
    
    return {'rows_uploaded': len(gdf)}
```

### Stage 4: STAC Record & Validation

**Inputs**: Table name, metadata from previous stages  
**Outputs**: STAC record, OGC Features API validation

```python
async def stage4_finalize(job_id: str, table_name: str, metadata: dict):
    """
    Create STAC metadata record and validate API access.
    """
    # Create STAC Item in pgSTAC
    stac_item = {
        'type': 'Feature',
        'stac_version': '1.0.0',
        'id': job_id,
        'geometry': metadata['bounds_as_geojson'],
        'bbox': metadata['bounds'],
        'properties': {
            'datetime': metadata['created_at'],
            'table_name': table_name,
            'row_count': metadata['total_rows']
        },
        'assets': {
            'data': {
                'href': f'https://api.worldbank.org/vector/{table_name}',
                'type': 'application/geo+json',
                'roles': ['data']
            }
        }
    }
    
    await insert_stac_item(stac_item)
    
    # Validate OGC API Features access
    test_url = f'https://api.worldbank.org/vector/{table_name}/items?limit=1'
    response = await httpx.get(test_url)
    if response.status_code != 200:
        raise ValueError(f"API validation failed: {response.text}")
    
    # Optional: Trigger completion webhook to DDH
    if 'webhook_url' in metadata:
        await httpx.post(metadata['webhook_url'], json={'job_id': job_id, 'status': 'completed'})
```

## Raster Processing Workflows

### Single COG Workflow

**Stage 1: COG Optimization**

```python
import rasterio
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

async def stage1_create_cog(input_path: str, output_path: str, params: dict):
    """
    Convert source raster to Cloud-Optimized GeoTIFF.
    
    Optimizations:
    - Internal tiling (256x256 or 512x512)
    - Compression (LZW for general, JPEG for imagery, DEFLATE for DEMs)
    - Overviews (pyramids for multi-scale access)
    - Reprojection to Web Mercator (EPSG:3857) if needed
    """
    
    with rasterio.open(input_path) as src:
        # Analyze source
        profile = src.profile
        dtype = src.dtypes[0]
        
        # Select compression based on data type
        if dtype in ['uint8', 'uint16'] and src.count == 3:
            compression = 'JPEG'
            quality = 85
        else:
            compression = 'DEFLATE'
            quality = None
        
        # Configure COG profile
        cog_profile = cog_profiles.get('lzw')
        cog_profile.update({
            'COMPRESS': compression,
            'TILED': True,
            'BLOCKXSIZE': 512,
            'BLOCKYSIZE': 512,
            'OVERVIEW_RESAMPLING': 'AVERAGE',
        })
        
        # Reproject if needed
        if src.crs.to_epsg() != 3857:
            cog_profile['dst_crs'] = 'EPSG:3857'
        
        # Translate to COG
        cog_translate(
            src,
            output_path,
            cog_profile,
            in_memory=False,  # Use temp files for large datasets
            quiet=False
        )
    
    # Upload to read-only blob storage
    await upload_to_blob(output_path, container='api-data')
    
    return {
        'cog_path': output_path,
        'size_mb': os.path.getsize(output_path) / 1024 / 1024
    }
```

**Stage 2: STAC Record & TiTiler Validation**

```python
async def stage2_stac_and_validate(cog_path: str, metadata: dict):
    """
    Create STAC item and validate TiTiler can serve it.
    """
    # Build TiTiler URL
    titiler_url = f"https://api.worldbank.org/tiles/cog/tiles/{{z}}/{{x}}/{{y}}?url={cog_path}"
    
    # Validate: Fetch tile 0/0/0 (should always exist)
    test_tile = titiler_url.format(z=0, x=0, y=0)
    response = await httpx.get(test_tile)
    if response.status_code != 200:
        raise ValueError(f"TiTiler validation failed: {response.text}")
    
    # Create STAC item
    stac_item = {
        'type': 'Feature',
        'stac_version': '1.0.0',
        'id': metadata['job_id'],
        'geometry': metadata['bounds_as_geojson'],
        'bbox': metadata['bounds'],
        'properties': {
            'datetime': metadata['created_at']
        },
        'assets': {
            'cog': {
                'href': cog_path,
                'type': 'image/tiff; application=geotiff; profile=cloud-optimized',
                'roles': ['data']
            },
            'tiles': {
                'href': titiler_url,
                'type': 'application/json',
                'roles': ['tiles']
            }
        }
    }
    
    await insert_stac_item(stac_item)
```

### Raster Collection Workflow (Multiple COGs)

**Stage 1: Parallel COG Creation**

Same as single COG, but fan-out to n tasks if source is very large (>2GB).

**Stage 2: TiTiler-pgSTAC Registration**

```python
async def stage2_register_mosaic(cog_paths: list, collection_id: str):
    """
    Register a search query in TiTiler-pgSTAC for dynamic mosaicking.
    
    TiTiler-pgSTAC serves multiple COGs as a single layer using STAC queries.
    """
    # Create STAC Collection
    stac_collection = {
        'type': 'Collection',
        'stac_version': '1.0.0',
        'id': collection_id,
        'description': 'Raster collection',
        'extent': {
            'spatial': {'bbox': [...]},
            'temporal': {'interval': [...]}
        }
    }
    
    await insert_stac_collection(stac_collection)
    
    # Create STAC Items for each COG
    for cog_path in cog_paths:
        item = {...}  # Similar to single COG
        item['collection'] = collection_id
        await insert_stac_item(item)
    
    # Register TiTiler-pgSTAC search
    search_query = {
        'collections': [collection_id],
        'filter': {...}
    }
    
    # TiTiler-pgSTAC URL pattern
    mosaic_url = f"https://api.worldbank.org/tiles/searches/{{search_id}}/tiles/{{z}}/{{x}}/{{y}}"
    
    # Validate
    test_tile = mosaic_url.format(search_id=collection_id, z=0, x=0, y=0)
    response = await httpx.get(test_tile)
    if response.status_code != 200:
        raise ValueError(f"TiTiler-pgSTAC validation failed")
    
    return {'mosaic_url': mosaic_url}
```

## Development Environment Setup

### Prerequisites

```bash
# Python 3.11+ required
python --version

# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Install Azure Functions Core Tools
npm install -g azure-functions-core-tools@4
```

### Local Database Setup

```bash
# Install PostgreSQL with PostGIS
sudo apt install postgresql-14 postgresql-14-postgis-3

# Install pgSTAC
git clone https://github.com/stac-utils/pgstac.git
cd pgstac
psql -U postgres -d postgres -f pgstac.sql

# Create development database
createdb -U postgres geospatial_etl_dev
psql -U postgres -d geospatial_etl_dev -c "CREATE EXTENSION postgis;"
psql -U postgres -d geospatial_etl_dev -c "CREATE EXTENSION pgstac;"
```

### Python Environment

```bash
# Clone repository
git clone <repo_url>
cd geospatial-etl-pipeline

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Key Dependencies

```python
# requirements.txt
azure-functions==1.18.0
azure-identity==1.15.0
azure-storage-blob==12.19.0
azure-servicebus==7.11.4
asyncpg==0.29.0
geopandas==0.14.1
rasterio==1.3.9
rio-cogeo==5.1.0
shapely==2.0.2
pystac==1.9.0
httpx==0.26.0
```

### Local Configuration

```bash
# local.settings.json (Azure Functions)
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "POSTGRES_CONNECTION_STRING": "postgresql://postgres:password@localhost:5432/geospatial_etl_dev",
    "SERVICEBUS_CONNECTION_STRING": "<get_from_azure_portal>",
    "STORAGE_ACCOUNT_CONNECTION_STRING": "<get_from_azure_portal>"
  }
}
```

### Running Locally

```bash
# Start Azurite (local storage emulator)
azurite --silent --location ./azurite --debug ./azurite/debug.log &

# Start Functions
func start
```

## Common Development Tasks

### Adding a New Dataset Processor

Extend the framework for specialized datasets (e.g., FATHOM flood models, CMIP6 climate data).

**1. Create processor module**

```python
# processors/fathom_flood.py

from typing import Dict, Any
import geopandas as gpd
import rasterio

class FathomFloodProcessor:
    """
    Specialized processor for FATHOM flood depth models.
    
    FATHOM specifics:
    - Multiple return periods (10yr, 100yr, 1000yr)
    - Both defended and undefended scenarios
    - Global coverage in ~90m resolution tiles
    """
    
    def get_stages(self) -> list:
        """Define processing stages for this dataset type."""
        return [
            {'name': 'extract_scenarios', 'parallelizable': False},
            {'name': 'process_tiles', 'parallelizable': True},
            {'name': 'create_collection', 'parallelizable': False}
        ]
    
    async def extract_scenarios(self, input_path: str) -> Dict[str, Any]:
        """
        Stage 1: Parse FATHOM directory structure to identify scenarios.
        
        FATHOM structure:
        /FATHOM-GLOBAL-v3/
          /DEFENDED/
            /return_period_10/
              tile_001.tif
              tile_002.tif
            /return_period_100/
          /UNDEFENDED/
        """
        scenarios = []
        for scenario in ['DEFENDED', 'UNDEFENDED']:
            for period in [10, 100, 1000]:
                path = f"{input_path}/{scenario}/return_period_{period}/"
                tiles = [f for f in os.listdir(path) if f.endswith('.tif')]
                scenarios.append({
                    'scenario': scenario,
                    'return_period': period,
                    'tiles': tiles,
                    'tile_count': len(tiles)
                })
        
        return {'scenarios': scenarios}
    
    async def process_tiles(self, task_index: int, scenario: dict, tile_path: str):
        """
        Stage 2: Convert FATHOM tile to COG with specific optimizations.
        
        FATHOM tiles need:
        - NoData value: -9999
        - Compression: DEFLATE (float32 data)
        - Color ramp: Blue gradient (0-10m depth)
        """
        output_path = f"output/{scenario['scenario']}_{scenario['return_period']}_{task_index}.tif"
        
        with rasterio.open(tile_path) as src:
            profile = src.profile
            profile.update({
                'compress': 'deflate',
                'tiled': True,
                'blockxsize': 512,
                'blockysize': 512,
                'nodata': -9999
            })
            
            # Write COG
            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(src.read())
        
        await upload_to_blob(output_path, container='api-data')
        return {'cog_path': output_path}
    
    async def create_collection(self, scenarios: list):
        """
        Stage 3: Create STAC collection with TiTiler-pgSTAC mosaics.
        """
        collection_id = 'fathom-flood-v3'
        
        # Create parent collection
        await insert_stac_collection({
            'id': collection_id,
            'description': 'FATHOM Global Flood Model v3',
            'extent': {...}
        })
        
        # Create sub-collections for each scenario/period
        for scenario in scenarios:
            sub_collection_id = f"{collection_id}-{scenario['scenario'].lower()}-{scenario['return_period']}yr"
            
            # Register in TiTiler-pgSTAC
            mosaic_url = await register_mosaic(sub_collection_id, scenario['tiles'])
            
            # Create STAC items for each tile
            # ...
        
        return {'collection_id': collection_id}
```

**2. Register processor**

```python
# processors/__init__.py

from .fathom_flood import FathomFloodProcessor
from .cmip6_climate import CMIP6Processor

PROCESSORS = {
    'vector': VectorProcessor,
    'raster': RasterProcessor,
    'fathom_flood': FathomFloodProcessor,
    'cmip6': CMIP6Processor
}

def get_processor(job_type: str):
    """Factory function to get appropriate processor."""
    return PROCESSORS.get(job_type)
```

**3. Submit job with processor**

```python
job_params = {
    'job_type': 'fathom_flood',
    'input_path': 'workspace/FATHOM-GLOBAL-v3/',
    'output_collection': 'fathom-flood-v3'
}

# Hash params for idempotent job ID
job_id = hashlib.sha256(json.dumps(job_params, sort_keys=True).encode()).hexdigest()

# Submit
await submit_job(job_id, job_params)
```

### Testing Your Changes

```bash
# Unit tests
pytest tests/unit/

# Integration tests (requires local PostgreSQL + Service Bus connection)
pytest tests/integration/

# Test specific processor
pytest tests/integration/test_fathom_processor.py -v
```

### Debugging Failed Jobs

```sql
-- Find failed jobs
SELECT job_id, error_message, updated_at 
FROM jobs 
WHERE status = 'Failed' 
ORDER BY updated_at DESC 
LIMIT 10;

-- Find failed tasks for a job
SELECT task_id, stage, error_message 
FROM tasks 
WHERE job_id = 'a3f7b2c1...' AND status = 'Failed';

-- Check task results from previous stage
SELECT task_id, results_data 
FROM tasks 
WHERE job_id = 'a3f7b2c1...' AND stage = 2;
```

### Monitoring Queries

```sql
-- Jobs in progress
SELECT job_id, stage, 
       (SELECT COUNT(*) FROM tasks WHERE job_id = j.job_id AND status = 'Completed') as completed_tasks,
       (SELECT COUNT(*) FROM tasks WHERE job_id = j.job_id AND status = 'Processing') as running_tasks
FROM jobs j
WHERE status = 'Processing';

-- Average processing time by stage
SELECT stage, AVG(updated_at - created_at) as avg_duration
FROM tasks
WHERE status = 'Completed'
GROUP BY stage;
```

## Code Structure

```
geospatial-etl-pipeline/
├── functions/
│   ├── job_submit/              # HTTP trigger to create jobs
│   ├── job_queue_trigger/       # Processes job messages
│   └── task_queue_trigger/      # Processes task messages
├── processors/
│   ├── __init__.py
│   ├── vector.py
│   ├── raster.py
│   ├── fathom_flood.py
│   └── cmip6_climate.py
├── shared/
│   ├── db.py                    # Database utilities
│   ├── orchestration.py         # Job/task management
│   ├── storage.py               # Blob storage utilities
│   └── stac.py                  # STAC operations
├── tests/
│   ├── unit/
│   └── integration/
├── requirements.txt
├── local.settings.json
└── host.json
```

## Error Handling Philosophy

### Task-Level Errors (Atomic Failures)

Tasks are **100% atomic**: they succeed completely or fail completely.

```python
async def task_execution_wrapper(task_func, task_id: str, params: dict):
    """
    Wrapper that ensures atomic task execution.
    """
    try:
        # Execute task
        result = await task_func(params)
        
        # Update task record
        await update_task_status(task_id, 'Completed', results_data=result)
        
    except Exception as e:
        # Log full traceback
        logger.exception(f"Task {task_id} failed")
        
        # Update task record with error
        await update_task_status(
            task_id, 
            'Failed', 
            error_message=str(e)
        )
        
        # Azure Functions Service Bus will handle retry based on queue config
        raise
```

### Job-Level Errors (Currently: Fail Fast)

For development purposes, **any task failure = job failure**.

```python
# Future TODO: Sophisticated retry logic with timer trigger
# For now: If any task fails, mark entire job as failed

async def check_job_health(job_id: str):
    """Check if any tasks have failed for this job."""
    failed_tasks = await db.fetch("""
        SELECT task_id, error_message 
        FROM tasks 
        WHERE job_id = $1 AND status = 'Failed'
    """, job_id)
    
    if failed_tasks:
        # Mark job as failed
        error_summary = '; '.join([t['error_message'] for t in failed_tasks])
        await db.execute("""
            UPDATE jobs 
            SET status = 'Failed', error_message = $2
            WHERE job_id = $1
        """, job_id, error_summary)
```

### Service Bus Retry Configuration

```json
// host.json
{
  "extensions": {
    "serviceBus": {
      "messageHandlerOptions": {
        "maxConcurrentCalls": 16,
        "autoComplete": false,
        "maxAutoRenewDuration": "00:05:00"
      },
      "prefetchCount": 32,
      "sessionHandlerOptions": {
        "maxConcurrentSessions": 2000,
        "messageWaitTimeout": "00:00:30"
      }
    }
  }
}
```

## Idempotency Patterns

### Job Submission Idempotency

```python
def create_job_id(params: dict) -> str:
    """
    Generate deterministic job ID from parameters.
    Allows safe retries of job submission.
    """
    # Sort keys for consistent hashing
    canonical = json.dumps(params, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()

async def submit_job(params: dict):
    """Submit job idempotently."""
    job_id = create_job_id(params)
    
    # Check if job already exists
    existing = await db.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
    
    if existing:
        if existing['status'] in ['Completed', 'Processing']:
            return {'job_id': job_id, 'status': 'already_exists'}
        elif existing['status'] == 'Failed':
            # Optionally allow retry of failed jobs
            await db.execute("UPDATE jobs SET status = 'Queued' WHERE job_id = $1", job_id)
    else:
        # Create new job
        await db.execute("""
            INSERT INTO jobs (job_id, status, stage, parameters, created_at)
            VALUES ($1, 'Queued', 1, $2, NOW())
        """, job_id, json.dumps(params))
    
    # Queue job message
    await service_bus.send_message({'job_id': job_id, 'params': params})
    
    return {'job_id': job_id, 'status': 'queued'}
```

### Task Execution Idempotency

```python
async def execute_task_idempotently(task_id: str, task_func, params: dict):
    """
    Execute task only if not already completed.
    Service Bus "at-least-once" delivery means tasks might be retried.
    """
    # Check current status
    task = await db.fetchrow("SELECT status FROM tasks WHERE task_id = $1", task_id)
    
    if task['status'] == 'Completed':
        logger.info(f"Task {task_id} already completed, skipping")
        return
    
    # Mark as processing (prevent duplicate execution)
    updated = await db.execute("""
        UPDATE tasks 
        SET status = 'Processing', updated_at = NOW()
        WHERE task_id = $1 AND status = 'Queued'
    """, task_id)
    
    if updated == 0:
        # Another instance already started processing
        logger.warning(f"Task {task_id} already being processed")
        return
    
    # Execute task
    await task_func(params)
```

## Performance Considerations

### Chunking Strategy

```python
def calculate_optimal_chunks(row_count: int, avg_row_size_bytes: int) -> int:
    """
    Determine chunk size balancing parallelism vs overhead.
    
    Goals:
    - Each chunk should fit in Function App memory (~2GB)
    - Minimize Service Bus message overhead
    - Maximize parallelism for large datasets
    """
    MAX_CHUNK_SIZE = 50000  # rows
    MIN_CHUNK_SIZE = 1000   # rows
    TARGET_CHUNK_MB = 500   # MB per chunk
    
    # Estimate chunk size for target memory usage
    rows_per_chunk = int((TARGET_CHUNK_MB * 1024 * 1024) / avg_row_size_bytes)
    
    # Clamp to min/max
    rows_per_chunk = max(MIN_CHUNK_SIZE, min(MAX_CHUNK_SIZE, rows_per_chunk))
    
    n_chunks = (row_count // rows_per_chunk) + 1
    
    return n_chunks
```

### PostGIS Index Strategy

```python
async def create_optimized_indices(table_name: str, columns: list):
    """
    Create indices for efficient API queries.
    
    Always create:
    - GIST index on geometry (spatial queries)
    
    Optionally create (based on parameters):
    - B-tree on frequently filtered columns
    - Partial indices for common queries
    """
    # Spatial index (required)
    await db.execute(f"""
        CREATE INDEX IF NOT EXISTS {table_name}_geom_idx 
        ON {table_name} USING GIST (geometry);
    """)
    
    # Additional indices
    for col in columns:
        await db.execute(f"""
            CREATE INDEX IF NOT EXISTS {table_name}_{col}_idx 
            ON {table_name} ({col});
        """)
    
    # Analyze for query planner
    await db.execute(f"ANALYZE {table_name};")
```

### COG Optimization Parameters

```python
def get_cog_profile(src_profile: dict) -> dict:
    """
    Determine optimal COG configuration based on source characteristics.
    
    Factors:
    - Data type (uint8 imagery vs float32 elevation)
    - Number of bands (RGB vs single band)
    - Source file size (small = in-memory, large = temp files)
    """
    dtype = src_profile['dtype']
    count = src_profile['count']
    
    if dtype in ['uint8', 'uint16'] and count == 3:
        # RGB imagery: JPEG compression, AVERAGE resampling
        return {
            'compress': 'JPEG',
            'jpeg_quality': 85,
            'overview_resampling': 'AVERAGE',
            'blocksize': 512
        }
    elif dtype in ['float32', 'float64']:
        # Elevation/continuous data: DEFLATE, CUBIC resampling
        return {
            'compress': 'DEFLATE',
            'predictor': 3,  # Floating-point predictor
            'overview_resampling': 'CUBIC',
            'blocksize': 512
        }
    else:
        # General case: LZW, NEAREST resampling
        return {
            'compress': 'LZW',
            'overview_resampling': 'NEAREST',
            'blocksize': 512
        }
```

## Security & Access Patterns

### Managed Identity Authentication

All Azure resources use managed identities (no connection strings in code).

```python
from azure.identity import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

# Automatically uses:
# - Local: Environment variables or Azure CLI login
# - Azure: Managed Identity
credential = DefaultAzureCredential()

# Blob Storage
blob_client = BlobServiceClient(
    account_url="https://wbggeospatial.blob.core.windows.net",
    credential=credential
)

# PostgreSQL (requires Entra authentication enabled)
conn = await asyncpg.connect(
    host='wbggeospatial.postgres.database.azure.com',
    database='geospatial',
    user='managed_identity_name',
    password=await get_entra_token(),  # Token from managed identity
    ssl='require'
)
```

### RBAC vs POSIX ACLs (Why We Don't Use Filesystem ACLs)

**DO**: Container-level RBAC with managed identity read permissions

```python
# ✅ GOOD: Direct blob access with RBAC
async def read_cog(blob_path: str):
    blob_client = blob_service.get_blob_client(container='api-data', blob=blob_path)
    data = await blob_client.download_blob()
    return data.readall()
```

**DON'T**: Mount blob storage as filesystem with ACLs

```python
# ❌ BAD: Mounting as filesystem with ACL checks
# /mnt/blobfuse/api-data/dataset.tif
# - Slow ACL checks on every read
# - Breaks CDN caching
# - On-prem pattern in cloud environment
```

**Why RBAC is Superior**:
1. Token validated once per session (not per file access)
2. Enables CDN edge caching
3. Container-level permissions scale better
4. Cloud-native pattern

## Common Issues & Troubleshooting

### Issue: Tasks Stuck in "Processing"

**Symptom**: Tasks show "Processing" status but aren't completing.

**Causes**:
1. Function timeout (default 5 minutes)
2. Service Bus message lock expired
3. Unhandled exception before status update

**Debugging**:
```bash
# Check Application Insights
az monitor app-insights query \
  --app <app-insights-name> \
  --analytics-query "traces | where message contains 'task_id_here' | order by timestamp desc"

# Check Service Bus dead-letter queue
az servicebus queue show \
  --name tasks-queue \
  --namespace-name <namespace> \
  --query "deadLetterMessageCount"
```

**Resolution**:
- Increase Function timeout in host.json
- Extend Service Bus lock duration
- Add try/catch around status updates

### Issue: Geometry Validation Failures

**Symptom**: Stage 2 fails with "Invalid geometry" errors.

**Common Causes**:
- Self-intersecting polygons
- Duplicate vertices
- Mixed geometry types
- Invalid coordinates (NaN, Inf)

**Fix**:
```python
# Automatic geometry repair
gdf['geometry'] = gdf.geometry.buffer(0)  # Fix self-intersections
gdf['geometry'] = gdf.geometry.simplify(0.0001)  # Remove duplicate vertices
gdf = gdf[gdf.geometry.is_valid]  # Drop unfixable
```

### Issue: COG Files Not Accessible via TiTiler

**Symptom**: TiTiler returns 403 or 404 errors.

**Causes**:
1. Blob not in correct container (should be `api-data`)
2. TiTiler managed identity lacks read permission
3. Incorrect blob URL format

**Debugging**:
```bash
# Verify blob exists
az storage blob exists \
  --account-name wbggeospatial \
  --container-name api-data \
  --name dataset.tif

# Check TiTiler logs
az webapp log tail --name titiler-app --resource-group geospatial-rg
```

### Issue: Advisory Lock Deadlock

**Symptom**: Multiple tasks waiting indefinitely, job stuck.

**Rare but possible**: Two tasks acquire locks in different order.

**Prevention**:
```python
# Always acquire locks in consistent order (by job_id hash)
lock_id = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)

# Set lock timeout
await conn.execute("SET lock_timeout = '10s'")
```

**Recovery**:
```sql
-- View locks
SELECT * FROM pg_locks WHERE locktype = 'advisory';

-- Force release (emergency only)
SELECT pg_advisory_unlock_all();
```

## Deployment

### CI/CD Pipeline

Deployments use Azure DevOps with environment promotion:

1. **Dev**: Automatic deployment on merge to `develop` branch
2. **Staging**: Manual approval required
3. **Production**: Manual approval + change window

### Infrastructure as Code

```bash
# Deploy infrastructure (Terraform/Bicep)
cd infrastructure/
terraform apply -var-file=prod.tfvars

# Deploy Function Apps
func azure functionapp publish geospatial-etl-prod
```

### Environment Variables

Each environment has separate configuration:

```bash
# Set in Azure Portal or via CLI
az functionapp config appsettings set \
  --name geospatial-etl-prod \
  --resource-group geospatial-rg \
  --settings \
    "POSTGRES_CONNECTION_STRING=@Microsoft.KeyVault(SecretUri=...)" \
    "STORAGE_ACCOUNT_NAME=wbggeospatial"
```

## Next Steps

### Your First Week

**Day 1-2**: Environment setup, run existing tests, explore codebase  
**Day 3-4**: Fix a small bug or add logging to existing processor  
**Day 5**: Pair programming session on adding new dataset type

### Learning Resources

- **PostGIS**: https://postgis.net/documentation/
- **STAC Spec**: https://stacspec.org/
- **TiTiler**: https://developmentseed.org/titiler/
- **COG Format**: https://www.cogeo.org/
- **OGC APIs**: https://ogcapi.ogc.org/

### Questions?

Reach out to the team:
- Architecture questions: [Your name]
- Azure/deployment: Dimitar
- Dataset-specific: Domain experts in DDH

Welcome to the team! 🌍