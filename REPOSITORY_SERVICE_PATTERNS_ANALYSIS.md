# Repository and Service Pattern Analysis
**Date**: 10 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document established patterns from STAC and Raster ETL to inform Vector ETL design

---

## Executive Summary

This document analyzes the **repository and service layer patterns** established in the STAC cataloging and Raster ETL implementations. These patterns demonstrate a clean, consistent architecture that should be replicated for Vector ETL.

**Key Finding**: The architecture shows a clear **3-layer separation**:
1. **Infrastructure/Repository Layer** - Azure resource access (BlobRepository, StacInfrastructure)
2. **Service Layer** - Business logic handlers (list_raster_files, extract_stac_metadata, validate_raster, create_cog)
3. **Job/Workflow Layer** - Orchestration and task creation (StacCatalogContainerWorkflow, ProcessRasterWorkflow)

---

## Architecture Layers Deep Dive

### Layer 1: Infrastructure/Repository Layer

**Purpose**: Single source of truth for Azure resource access with managed authentication.

#### BlobRepository Pattern (`infrastructure/blob.py`)

**Key Characteristics**:
- ✅ **Singleton pattern** with `BlobRepository.instance()`
- ✅ **DefaultAzureCredential** for seamless authentication across environments
- ✅ **Connection pooling** via cached container clients
- ✅ **Pre-caches common containers** (bronze, silver, gold) for performance
- ✅ **IBlobRepository interface** for dependency injection and testing

**Core Operations**:
```python
# Read operations
read_blob(container, blob_path) -> bytes
read_blob_to_stream(container, blob_path) -> BytesIO
read_blob_chunked(container, blob_path, chunk_size) -> Iterator[bytes]

# Write operations
write_blob(container, blob_path, data, overwrite=True, content_type, metadata) -> Dict

# List operations
list_blobs(container, prefix="", limit=None) -> List[Dict]
  # Special handling: Aggregates .gdb folders as single units

# Utility operations
blob_exists(container, blob_path) -> bool
get_blob_properties(container, blob_path) -> Dict
get_blob_url_with_sas(container_name, blob_name, hours=1) -> str
  # Uses user delegation SAS token (no account key exposure)

# Advanced operations
copy_blob(source_container, source_path, dest_container, dest_path) -> Dict
batch_download(container, blob_paths, max_workers=10) -> Dict[str, BytesIO]
```

**Critical Design Decision**: SAS URL Generation
- Uses **user delegation key** instead of account keys
- Works with managed identity (no credentials in code)
- 1-hour default expiration (configurable)
- Pattern: `blob_repo.get_blob_url_with_sas(container, blob, hours=1)`

**Special Feature**: `.gdb` Geodatabase Aggregation
```python
# list_blobs() automatically:
# 1. Detects .gdb folders in blob paths
# 2. Aggregates all files within .gdb as single entry
# 3. Sums total size, tracks file count
# 4. Returns .gdb as single unit instead of 100+ individual files

# Example output:
{
    'name': 'data/parcels.gdb',
    'size': 524288000,  # Aggregate of all files
    'metadata': {
        'type': 'geodatabase',
        'file_count': 147  # All files in .gdb
    }
}
```

**Pattern for Vector ETL**:
```python
# Vector ETL should use BlobRepository for:
# - Listing containers to find vector data
# - Generating SAS URLs for GDAL/Fiona access
# - Reading vector metadata (size, type, last_modified)
# - Writing processed vectors to silver/gold containers
# - .gdb detection is CRITICAL for Esri File Geodatabases
```

#### StacInfrastructure Pattern (`infrastructure/stac.py`)

**Purpose**: Manages PgSTAC database interactions for STAC catalog.

**Key Operations** (inferred from usage):
```python
item_exists(item_id, collection_id) -> bool  # Idempotency check
insert_item(item, collection_id) -> dict     # Insert STAC Item to PgSTAC
```

**Pattern**: Repository pattern for database-specific operations, separate from general blob storage.

---

### Layer 2: Service Layer

**Purpose**: Business logic handlers that execute actual work, called by task processor.

**Critical Pattern**: All service handlers follow the same signature:
```python
def handler_function(params: dict) -> dict:
    """
    Args:
        params: Task parameters from job workflow

    Returns:
        dict: {
            "success": True/False,
            "result": {...} if success,
            "error": "ERROR_CODE" if failed,
            "message": "Error description" if failed,
            "traceback": "..." if failed
        }
    """
```

#### Pattern 1: Container Listing (`services/stac_catalog.py::list_raster_files`)

**Stage**: 1 (single task, no fan-out)
**Purpose**: Enumerate files in container for subsequent processing

**Implementation**:
```python
def list_raster_files(params: dict) -> dict[str, Any]:
    """
    List all raster files in container with filtering.

    Returns list of file names for Stage 2 fan-out.
    """
    container_name = params["container_name"]
    extension_filter = params.get("extension_filter", ".tif")
    prefix = params.get("prefix", "")
    file_limit = params.get("file_limit")

    blob_repo = BlobRepository.instance()

    # Get all blobs and filter by extension
    blobs = blob_repo.list_blobs(container=container_name, prefix=prefix, limit=None)

    raster_files = []
    for blob in blobs:
        if blob['name'].lower().endswith(extension_filter):
            raster_files.append(blob['name'])
            if file_limit and len(raster_files) >= file_limit:
                break

    return {
        "success": True,
        "result": {
            "raster_files": raster_files,  # Stage 2 uses this for fan-out
            "total_count": len(raster_files),
            "execution_info": {...}
        }
    }
```

**Key Observations**:
- ✅ Uses BlobRepository singleton
- ✅ Returns list of file names (not full metadata)
- ✅ Stage 2 uses `result['raster_files']` to create N tasks
- ✅ Respects file_limit for testing

**Vector ETL Equivalent**: `list_vector_files()`
```python
# Should enumerate:
# - .shp files (with companion .shx, .dbf, .prj)
# - .gpkg files
# - .gdb folders (already aggregated by BlobRepository!)
# - .geojson/.json files
# - .parquet/.geoparquet files

# Filter logic more complex than raster:
extension_patterns = {
    '.shp': 'shapefile',
    '.gpkg': 'geopackage',
    '.gdb': 'geodatabase',  # Already aggregated!
    '.geojson': 'geojson',
    '.json': 'geojson',
    '.parquet': 'geoparquet',
    '.geoparquet': 'geoparquet'
}
```

#### Pattern 2: Metadata Extraction (`services/stac_catalog.py::extract_stac_metadata`)

**Stage**: 2 (N parallel tasks, one per file)
**Purpose**: Extract metadata from single file and insert to database

**Implementation Flow**:
```python
def extract_stac_metadata(params: dict) -> dict[str, Any]:
    """Extract STAC metadata for a single raster file."""

    # STEP 0: Lazy import heavy dependencies
    # StacMetadataService import inside function to avoid module-level GDAL loading
    from .service_stac_metadata import StacMetadataService
    from infrastructure.stac import StacInfrastructure

    # STEP 1: Extract parameters
    container_name = params["container_name"]
    blob_name = params["blob_name"]
    collection_id = params.get("collection_id", "dev")

    # STEP 2: Initialize services
    stac_service = StacMetadataService()

    # STEP 3: Extract STAC item (SLOW - 30-60s for large files)
    item = stac_service.extract_item_from_blob(
        container=container_name,
        blob_name=blob_name,
        collection_id=collection_id
    )

    # STEP 4: Insert to PgSTAC (with idempotency check)
    stac_infra = StacInfrastructure()
    if stac_infra.item_exists(item.id, collection_id):
        # Skip if already exists (idempotent)
        insert_result = {'success': True, 'skipped': True}
    else:
        insert_result = stac_infra.insert_item(item, collection_id)

    # STEP 5: Return metadata summary
    return {
        "success": True,
        "result": {
            "item_id": item.id,
            "blob_name": blob_name,
            "collection_id": collection_id,
            "bbox": item.bbox,
            "epsg": item.properties.get('proj:epsg'),
            "inserted_to_pgstac": insert_result['success'],
            "stac_item": item.model_dump()  # Full STAC Item
        }
    }
```

**Key Observations**:
- ✅ **Lazy imports** of heavy dependencies (StacMetadataService triggers GDAL loading)
- ✅ **Idempotency built-in** via `item_exists()` check
- ✅ **Service delegation** - StacMetadataService handles rio-stac complexity
- ✅ **Error handling** at each step with detailed logging
- ✅ Returns **full STAC Item** in result for aggregation

**Vector ETL Equivalent**: `extract_vector_metadata()`
```python
# Should extract:
# - Geometry type (Point, LineString, Polygon, etc.)
# - Feature count (could be millions - use GDAL layer count)
# - Bounds (bbox in native CRS + EPSG:4326)
# - CRS (native projection)
# - Schema (field names and types)
# - File size and format
# - Encoding (for shapefiles - UTF-8 vs CP1252)

# CRITICAL: Must handle:
# - .gdb with multiple feature classes (fan-out within fan-out?)
# - .gpkg with multiple layers
# - Shapefiles missing .prj (CRS detection)
# - Large files (streaming feature count, not load all)
```

#### Pattern 3: Validation (`services/raster_validation.py::validate_raster`)

**Stage**: 1 (single task, gatekeeper for Stage 2)
**Purpose**: Validate file before expensive processing, fail fast if invalid

**Implementation Flow**:
```python
def validate_raster(params: dict) -> dict:
    """
    Validate raster file for COG pipeline.

    Checks:
    - File readability
    - CRS presence and validity
    - Bit-depth efficiency (flags 64-bit as CRITICAL)
    - Raster type detection
    - Bounds sanity checks
    """

    # STEP 0: Initialize logger
    # STEP 1: Extract parameters
    blob_url = params['blob_url']  # SAS URL from workflow
    input_crs = params.get('input_crs')  # User override
    raster_type = params.get('raster_type', 'auto')
    strict_mode = params.get('strict_mode', False)

    # STEP 2: Lazy import rasterio (GDAL)
    np, rasterio, ColorInterp, Window = _lazy_imports()

    # STEP 3: Open raster file via SAS URL
    src = rasterio.open(blob_url)

    # STEP 4: Extract basic info
    with src:
        band_count = src.count
        dtype = src.dtypes[0]
        shape = src.shape
        bounds = src.bounds

        warnings = []

        # STEP 5: CRS validation
        crs_result = _validate_crs(src, input_crs, bounds, skip_validation)
        if not crs_result["success"]:
            return crs_result  # FAIL FAST
        source_crs = crs_result["source_crs"]

        # STEP 6: Bit-depth efficiency check
        bit_depth_result = _check_bit_depth_efficiency(src, dtype, strict_mode)
        if strict_mode and bit_depth_result.get("warning", {}).get("severity") == "CRITICAL":
            return {"success": False, "error": "BIT_DEPTH_POLICY_VIOLATION"}

        # STEP 7: Raster type detection
        type_result = _detect_raster_type(src, raster_type)
        if not type_result["success"]:
            return type_result  # FAIL FAST (type mismatch)

        # STEP 8: Get optimal COG settings
        optimal_settings = _get_optimal_cog_settings(type_result["detected_type"])

        # STEP 9: Return validation results
        return {
            "success": True,
            "result": {
                "valid": True,
                "source_crs": str(source_crs),
                "raster_type": {
                    "detected_type": type_result["detected_type"],
                    "confidence": type_result["confidence"],
                    "optimal_cog_settings": optimal_settings
                },
                "bit_depth_check": {...},
                "warnings": warnings
            }
        }
```

**Key Observations**:
- ✅ **Fail fast** - Returns error immediately if validation fails
- ✅ **User override support** - `input_crs` for files with missing metadata
- ✅ **Strict mode** - Converts warnings to errors for production
- ✅ **Optimal settings** - Returns recommended processing parameters for Stage 2
- ✅ **Type detection** - Auto-detects RGB, RGBA, DEM, categorical, etc.

**CRS Validation Logic** (CRITICAL for vectors too):
```python
def _validate_crs(src, input_crs, bounds, skip_validation):
    """
    1. File has CRS + User provides CRS:
       - FAIL if mismatch (unless skip_validation=True for testing)

    2. File has CRS + User provides nothing:
       - Use file CRS (normal case)

    3. File has NO CRS + User provides CRS:
       - Use user CRS (necessary override for broken files)

    4. File has NO CRS + User provides nothing:
       - FAIL (cannot proceed without CRS)
    """
```

**Vector ETL Equivalent**: `validate_vector()`
```python
# Should validate:
# - File readability (GDAL can open it)
# - CRS presence (critical for vectors - shapefiles often missing .prj)
# - Geometry validity (use GDAL IsValid check)
# - Encoding (shapefiles - detect CP1252 vs UTF-8)
# - Schema sanity (field names, no reserved words)
# - File size warnings (> 100MB shapefile = bad practice)
# - Feature count warnings (> 1M features = consider splitting)
# - Bounds sanity checks (same as raster)

# CRITICAL: Shapefile .prj detection
# - Check for companion .prj file
# - If missing + user provides source_crs: allow with warning
# - If missing + no user CRS: FAIL
```

#### Pattern 4: Processing (`services/raster_cog.py::create_cog`)

**Stage**: 2 (uses validation results from Stage 1)
**Purpose**: Execute expensive processing operation

**Implementation Flow**:
```python
def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF with optional reprojection.

    Uses validation results to auto-select optimal settings.
    """

    # STEP 1: Extract parameters
    blob_url = params['blob_url']
    source_crs = params['source_crs']  # From Stage 1 validation
    target_crs = params.get('target_crs', 'EPSG:4326')
    raster_type = params['raster_type']['detected_type']  # From Stage 1
    optimal_settings = params['raster_type']['optimal_cog_settings']  # From Stage 1

    # User overrides or optimal settings
    compression = params.get('compression') or optimal_settings['compression']
    overview_resampling = params.get('overview_resampling') or optimal_settings['overview_resampling']

    # STEP 2: Lazy import dependencies
    rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()

    # STEP 3: Setup COG profile and temp directory
    temp_dir = tempfile.mkdtemp(prefix="cog_")
    local_output = os.path.join(temp_dir, "output_cog.tif")

    try:
        # STEP 4: Determine reprojection needs
        needs_reprojection = (str(source_crs) != str(target_crs))
        config = {"dst_crs": target_crs, "resampling": ...} if needs_reprojection else {}

        # STEP 5: Create COG (single-pass reproject + COG if needed)
        cog_translate(
            blob_url,  # Input: SAS URL
            local_output,  # Output: /tmp file
            cog_profile,
            config=config,  # Reprojection config
            overview_resampling=overview_resampling,
            in_memory=config.raster_cog_in_memory  # Configurable
        )

        # STEP 6: Upload to silver container
        blob_repo = BlobRepository.instance()
        with open(local_output, 'rb') as f:
            blob_repo.write_blob(
                container=config.silver_container_name,
                blob_path=output_blob_name,
                data=f.read()
            )

        return {
            "success": True,
            "result": {
                "cog_blob": output_blob_name,
                "cog_container": "silver",
                "reprojection_performed": needs_reprojection,
                "compression": compression,
                "processing_time_seconds": elapsed_time
            }
        }

    finally:
        # STEP 7: Cleanup temp files
        if os.path.exists(local_output):
            os.remove(local_output)
        os.rmdir(temp_dir)
```

**Key Observations**:
- ✅ **Uses Stage 1 results** - source_crs, raster_type, optimal_settings
- ✅ **Temp file management** - Downloads to /tmp, processes, uploads, cleans up
- ✅ **Single-pass optimization** - rio-cogeo does reproject + COG in one operation
- ✅ **Configurable memory mode** - `in_memory=True` for small files, `False` for large
- ✅ **Finally block cleanup** - Always removes temp files, even on failure

**Vector ETL Equivalent**: `process_vector()`
```python
# Should:
# 1. Download vector to /tmp (or stream if possible)
# 2. Reproject to EPSG:4326 (using ogr2ogr or GeoPandas)
# 3. Convert to target format (GeoParquet for gold, GeoPackage for silver?)
# 4. Upload to target container
# 5. Cleanup temp files

# CRITICAL differences from raster:
# - Vectors can be streamed feature-by-feature (memory efficient)
# - Shapefiles need all companion files (.shp, .shx, .dbf, .prj)
# - .gdb needs entire folder downloaded
# - Large shapefiles (>100MB) should warn to use better format
```

---

### Layer 3: Job/Workflow Layer

**Purpose**: Orchestrate multi-stage workflows, create tasks, aggregate results.

#### Two-Stage Fan-Out Pattern (`jobs/stac_catalog_container.py`)

**Workflow**: List container → Extract metadata for each file

```python
class StacCatalogContainerWorkflow:
    """
    Two-stage fan-out job for bulk STAC cataloging.

    Stage 1: Single task lists all raster files
    Stage 2: N parallel tasks extract STAC metadata
    """

    job_type: str = "stac_catalog_container"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "list_rasters",
            "task_type": "list_raster_files",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "extract_stac",
            "task_type": "extract_stac_metadata",
            "parallelism": "fan_out"
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
        """Generate task parameters for a stage."""

        if stage == 1:
            # Stage 1: Single task to list files
            return [
                {
                    "task_id": generate_deterministic_task_id(job_id, 1, "list_rasters"),
                    "task_type": "list_raster_files",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "extension_filter": job_params.get("extension_filter", ".tif"),
                        "prefix": job_params.get("prefix", ""),
                        "file_limit": job_params.get("file_limit")
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: FAN-OUT - one task per file
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            stage_1_result = previous_results[0]
            raster_files = stage_1_result['result']['raster_files']

            tasks = []
            for raster_file in raster_files:
                tasks.append({
                    "task_id": generate_deterministic_task_id(job_id, 2, raster_file),
                    "task_type": "extract_stac_metadata",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "blob_name": raster_file,
                        "collection_id": job_params.get("collection_id", "dev")
                    }
                })

            return tasks

    @staticmethod
    def aggregate_job_results(context) -> Dict[str, Any]:
        """Aggregate results from all tasks."""

        stage_1_tasks = [t for t in context.task_results if t.task_type == "list_raster_files"]
        stage_2_tasks = [t for t in context.task_results if t.task_type == "extract_stac_metadata"]

        total_files_found = stage_1_tasks[0].result_data["result"]["total_count"]
        successful_insertions = sum(1 for t in stage_2_tasks if t.result_data.get("result", {}).get("inserted_to_pgstac"))

        return {
            "job_type": "stac_catalog_container",
            "summary": {
                "total_files_found": total_files_found,
                "successful_insertions": successful_insertions,
                "failed_insertions": len(stage_2_tasks) - successful_insertions
            }
        }
```

**Key Observations**:
- ✅ **Stage 2 reads Stage 1 results** via `previous_results` parameter
- ✅ **Deterministic task IDs** using file name as semantic identifier
- ✅ **Empty list handling** - If no files found, Stage 2 returns `[]`
- ✅ **Result aggregation** - Counts successes/failures across all tasks

#### Two-Stage Sequential Pattern (`jobs/process_raster.py`)

**Workflow**: Validate raster → Create COG (uses validation results)

```python
class ProcessRasterWorkflow:
    """
    Small file raster processing workflow.

    Stage 1: Validate raster
    Stage 2: Create COG (uses Stage 1 results)
    """

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "create_cog",
            "task_type": "create_cog",
            "parallelism": "single"
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
        """Generate task parameters for a stage."""

        if stage == 1:
            # Stage 1: Validate raster
            container_name = job_params.get('container_name') or config.bronze_container_name

            blob_repo = BlobRepository.instance()
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=job_params['blob_name'],
                hours=1
            )

            return [
                {
                    "task_id": generate_deterministic_task_id(job_id, 1, "validate"),
                    "task_type": "validate_raster",
                    "parameters": {
                        "blob_url": blob_url,
                        "blob_name": job_params['blob_name'],
                        "container_name": container_name,
                        "input_crs": job_params.get('input_crs'),
                        "raster_type": job_params.get('raster_type', 'auto'),
                        "strict_mode": job_params.get('strict_mode', False)
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: Create COG (REQUIRES Stage 1 results)
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 validation failed: {stage_1_result.get('error')}")

            validation_result = stage_1_result['result']
            source_crs = validation_result['source_crs']  # CRITICAL: From Stage 1

            blob_url = blob_repo.get_blob_url_with_sas(...)

            return [
                {
                    "task_id": generate_deterministic_task_id(job_id, 2, "create_cog"),
                    "task_type": "create_cog",
                    "parameters": {
                        "blob_url": blob_url,
                        "source_crs": source_crs,  # From Stage 1
                        "target_crs": "EPSG:4326",
                        "raster_type": validation_result['raster_type'],  # From Stage 1
                        "compression": job_params.get('compression'),  # User override
                        "output_blob_name": output_blob_name
                    }
                }
            ]
```

**Key Observations**:
- ✅ **Stage 2 depends on Stage 1** - Reads `source_crs` and `raster_type` from validation
- ✅ **Fails Stage 2 if Stage 1 failed** - `raise ValueError()` if validation didn't succeed
- ✅ **SAS URL generation in workflow** - Not in service layer
- ✅ **User overrides respected** - `compression` can override optimal settings

---

## Critical Patterns for Vector ETL

### Pattern 1: Repository Layer

**Vector ETL needs**:
- ✅ **Use BlobRepository.instance()** - Already handles `.gdb` aggregation!
- ✅ **list_blobs()** for container enumeration
- ✅ **get_blob_url_with_sas()** for GDAL/Fiona access
- ✅ **write_blob()** for output to silver/gold

**Additional requirement**:
- ❓ **PostgreSQL/PostGIS repository** - Similar to StacInfrastructure
  - Feature metadata storage (bounds, feature count, schema)
  - Vector STAC Items (if using pgstac for vectors)
  - Or separate `vectors` schema in PostgreSQL

### Pattern 2: Service Handlers

**Vector ETL needs these handlers**:

1. **list_vector_files(params) -> dict**
   - Container: `bronze`
   - Extensions: `.shp`, `.gpkg`, `.gdb`, `.geojson`, `.parquet`
   - Returns: List of vector file names/paths
   - Fan-out: Stage 2 creates N tasks

2. **validate_vector(params) -> dict**
   - Checks: CRS, geometry validity, encoding, schema
   - Returns: Validation results + optimal processing settings
   - Fails fast: If invalid CRS, corrupt geometry, etc.

3. **extract_vector_metadata(params) -> dict** (optional, if doing STAC)
   - Extracts: Bounds, feature count, geometry type, schema
   - Inserts: Vector STAC Item to PgSTAC or metadata to PostgreSQL
   - Idempotent: Checks if already exists

4. **process_vector(params) -> dict**
   - Input: SAS URL from bronze
   - Operations: Reproject to EPSG:4326, convert format
   - Output: Write to silver (GeoPackage?) or gold (GeoParquet)
   - Cleanup: Remove temp files

### Pattern 3: Workflow Orchestration

**Option A: Two-Stage Fan-Out (like STAC)**
```python
# Stage 1: List vector files (single task)
# Stage 2: Process each vector file (N parallel tasks)

# Good for: Bulk processing of many vectors
# Example: Process entire container of shapefiles
```

**Option B: Two-Stage Sequential (like Raster)**
```python
# Stage 1: Validate vector (single task)
# Stage 2: Process vector (single task, uses Stage 1 results)

# Good for: Single-file processing with validation
# Example: User uploads one shapefile, validate then process
```

**Option C: Three-Stage (list + validate + process)**
```python
# Stage 1: List vector files (single task)
# Stage 2: Validate each vector (N parallel tasks, fail-fast)
# Stage 3: Process valid vectors (M parallel tasks, M <= N)

# Good for: Bulk processing with quality control
# Example: Only process files that pass validation
```

### Pattern 4: Special Considerations for Vectors

**Shapefiles**:
- ✅ Must download ALL companion files (.shp, .shx, .dbf, .prj, .cpg)
- ✅ Encoding detection critical (CP1252 vs UTF-8)
- ✅ Missing .prj handling (user override or fail)
- ✅ Size warnings (> 100MB = bad practice, recommend GeoPackage)

**File Geodatabases (.gdb)**:
- ✅ Already aggregated by BlobRepository.list_blobs()!
- ✅ Must download entire folder structure
- ✅ Multiple feature classes = multiple layers
- ❓ **Fan-out within fan-out?** One task per feature class?

**GeoPackage (.gpkg)**:
- ✅ Single file (easy to handle)
- ✅ Multiple layers possible
- ✅ Supports advanced geometry types (Curves, TIN, etc.)

**GeoParquet**:
- ✅ Single file, columnar format
- ✅ Partitioned files possible (multiple .parquet files)
- ✅ Ideal for gold tier (analytics-ready)

---

## Summary Recommendations for Vector ETL

### Use Existing Infrastructure
1. ✅ **BlobRepository** - List containers, generate SAS URLs, write outputs
2. ✅ **Singleton pattern** - Follow same factory pattern
3. ✅ **DefaultAzureCredential** - Seamless authentication

### Service Layer Pattern
1. ✅ **Handler signature**: `def handler(params: dict) -> dict` with `success`/`error` format
2. ✅ **Lazy imports** - Import GDAL/Fiona inside handler functions
3. ✅ **Step-by-step logging** - Log each major step with timings
4. ✅ **Fail fast** - Return error dict immediately if validation fails
5. ✅ **Idempotency** - Check if already processed before doing work

### Workflow Pattern
1. ✅ **Two-stage recommended**: List → Process (simpler) OR List → Validate → Process (safer)
2. ✅ **Previous results** - Stage 2 reads Stage 1 output via `previous_results` parameter
3. ✅ **Deterministic task IDs** - Use file name/path as semantic identifier
4. ✅ **Result aggregation** - Count successes/failures, summarize outcomes

### Special Vector Handling
1. ✅ **.gdb aggregation** - Already handled by BlobRepository!
2. ✅ **Shapefile companions** - Download all related files together
3. ✅ **Encoding detection** - Check for .cpg file, detect CP1252 vs UTF-8
4. ✅ **CRS validation** - Same as raster (file metadata, user override, fail if missing)
5. ✅ **Geometry validation** - Use GDAL `IsValid()` check
6. ✅ **Feature count** - Use layer.GetFeatureCount() (don't load all features)

---

## Next Steps

1. **Design vector workflow classes**:
   - `ProcessVectorWorkflow` (single file, 2-stage: validate → process)
   - `BulkVectorCatalogWorkflow` (bulk processing, 2-stage: list → process)

2. **Implement service handlers**:
   - `services/vector_catalog.py` - list_vector_files()
   - `services/vector_validation.py` - validate_vector()
   - `services/vector_processing.py` - process_vector()

3. **Create PostgreSQL repository** (if needed):
   - `infrastructure/vector_metadata.py` - VectorMetadataRepository
   - Store: feature count, bounds, geometry type, schema

4. **Testing strategy**:
   - Test each handler independently with sample files
   - Test workflow orchestration with small container
   - Test .gdb handling (multi-layer feature class)
   - Test shapefile companion file handling
   - Test encoding detection (CP1252 shapefiles)

---

**End of Analysis**