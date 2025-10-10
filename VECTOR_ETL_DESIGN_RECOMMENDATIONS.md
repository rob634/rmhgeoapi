# Vector ETL Design Recommendations
**Date**: 10 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Concrete recommendations for vector ETL based on established raster/STAC patterns

---

## Executive Summary

After analyzing the STAC cataloging and Raster ETL implementations, we've identified **proven patterns** that should be directly replicated for Vector ETL. The architecture demonstrates clean 3-layer separation with consistent patterns across all implementations.

**Key Insight**: The `.gdb` geodatabase aggregation feature in BlobRepository is **CRITICAL** for vector ETL and already handles one of the most complex vector formats!

---

## Immediate Action Items

### 1. Repository Layer - **READY TO USE**

✅ **BlobRepository is vector-ready**:
- Already aggregates `.gdb` folders as single units
- Handles SAS URL generation for GDAL/Fiona
- Supports all blob operations needed for vectors

**No new repository code needed** - Just use existing BlobRepository!

```python
# Vector ETL can immediately use:
from infrastructure.blob import BlobRepository

blob_repo = BlobRepository.instance()

# List vectors (already handles .gdb aggregation!)
blobs = blob_repo.list_blobs(container='bronze', prefix='vectors/')

# Generate SAS URL for GDAL access
vector_url = blob_repo.get_blob_url_with_sas('bronze', 'parcels.shp', hours=1)

# Upload processed vector to silver
blob_repo.write_blob('silver', 'parcels.gpkg', data)
```

### 2. Service Handlers - **NEED TO CREATE**

Create these handler functions following established patterns:

#### A. `services/vector_catalog.py::list_vector_files(params) -> dict`

**Pattern**: Same as `list_raster_files()` from STAC implementation

```python
def list_vector_files(params: dict) -> dict:
    """
    Stage 1: List all vector files in container with format detection.

    Args:
        params: {
            "container_name": str,
            "format_filter": list[str] = ['.shp', '.gpkg', '.gdb', '.geojson', '.parquet'],
            "prefix": str = "",
            "file_limit": int | None
        }

    Returns:
        {
            "success": True,
            "result": {
                "vector_files": [
                    {
                        "blob_name": "parcels.shp",
                        "format": "shapefile",
                        "size_mb": 45.2,
                        "companion_files": [".shx", ".dbf", ".prj"]  # For shapefiles
                    },
                    {
                        "blob_name": "buildings.gdb",  # Already aggregated!
                        "format": "geodatabase",
                        "size_mb": 234.5,
                        "file_count": 147  # From BlobRepository aggregation
                    }
                ],
                "total_count": 2,
                "execution_info": {...}
            }
        }
    """

    blob_repo = BlobRepository.instance()
    blobs = blob_repo.list_blobs(container=params["container_name"], prefix=params.get("prefix", ""))

    # Detect vector formats
    vector_files = []
    for blob in blobs:
        blob_name = blob['name']

        # .gdb already aggregated by BlobRepository!
        if blob_name.endswith('.gdb'):
            vector_files.append({
                "blob_name": blob_name,
                "format": "geodatabase",
                "size_mb": blob['size'] / (1024*1024),
                "file_count": blob['metadata'].get('file_count', 0)
            })

        # Shapefile detection
        elif blob_name.endswith('.shp'):
            # Check for companion files
            companion_files = detect_shapefile_companions(blobs, blob_name)
            vector_files.append({
                "blob_name": blob_name,
                "format": "shapefile",
                "size_mb": blob['size'] / (1024*1024),
                "companion_files": companion_files
            })

        # Other formats...
        elif blob_name.endswith('.gpkg'):
            vector_files.append({
                "blob_name": blob_name,
                "format": "geopackage",
                "size_mb": blob['size'] / (1024*1024)
            })

    return {"success": True, "result": {"vector_files": vector_files, "total_count": len(vector_files)}}
```

#### B. `services/vector_validation.py::validate_vector(params) -> dict`

**Pattern**: Same structure as `validate_raster()` with vector-specific checks

**Key Validations**:
1. **CRS Detection** (same logic as raster - 4 cases)
2. **Geometry Validity** (use GDAL `IsValid()`)
3. **Encoding Detection** (for shapefiles - CP1252 vs UTF-8)
4. **Schema Validation** (field names, reserved words, duplicates)
5. **File Size Warnings** (> 100MB shapefile = bad practice)
6. **Feature Count** (> 1M features = warn about performance)

```python
def validate_vector(params: dict) -> dict:
    """
    Stage 1: Validate vector file before processing.

    Checks:
    - File readability (GDAL can open)
    - CRS presence and validity
    - Geometry validity (IsValid check on sample)
    - Encoding (shapefile .cpg detection)
    - Schema sanity (field names, types)
    - Bounds sanity checks
    - File format warnings

    Args:
        params: {
            "blob_url": str,  # SAS URL for GDAL
            "blob_name": str,
            "container_name": str,
            "input_crs": str | None,  # User override
            "format": str,  # From list_vector_files
            "strict_mode": bool
        }

    Returns:
        {
            "success": True,
            "result": {
                "valid": True,
                "source_crs": "EPSG:26910",
                "crs_source": "file_metadata",
                "geometry_type": "Polygon",
                "feature_count": 45203,
                "bounds": [-122.5, 37.7, -122.3, 37.9],
                "encoding": "UTF-8",  # For shapefiles
                "schema": {
                    "fields": [
                        {"name": "OBJECTID", "type": "Integer"},
                        {"name": "PARCEL_ID", "type": "String"}
                    ]
                },
                "warnings": [
                    {
                        "type": "LARGE_SHAPEFILE",
                        "severity": "MEDIUM",
                        "message": "Shapefile is 123 MB. Consider GeoPackage for better performance."
                    }
                ],
                "optimal_processing_settings": {
                    "output_format": "geopackage",  # For silver
                    "chunk_size": 1000  # For large files
                }
            }
        }
    """

    # Import GDAL/Fiona lazily
    from osgeo import ogr, osr

    # Open vector file via SAS URL
    datasource = ogr.Open(params['blob_url'])
    layer = datasource.GetLayer(0)

    # CRS validation (same 4-case logic as raster!)
    crs_result = _validate_crs_vector(layer, params.get('input_crs'))
    if not crs_result["success"]:
        return crs_result

    # Geometry validity check (sample 100 features)
    invalid_geometries = _check_geometry_validity(layer, sample_size=100)

    # Encoding detection (shapefiles)
    if params['format'] == 'shapefile':
        encoding = _detect_shapefile_encoding(params['blob_name'])

    # Feature count
    feature_count = layer.GetFeatureCount()

    # Schema validation
    schema_result = _validate_schema(layer.GetLayerDefn())

    # Bounds
    extent = layer.GetExtent()
    bounds = [extent[0], extent[2], extent[1], extent[3]]

    # File size warnings
    warnings = []
    if params['format'] == 'shapefile' and params.get('size_mb', 0) > 100:
        warnings.append({
            "type": "LARGE_SHAPEFILE",
            "severity": "MEDIUM",
            "message": f"Shapefile is {params['size_mb']:.1f} MB. GeoPackage recommended for files > 100 MB."
        })

    return {
        "success": True,
        "result": {
            "valid": True,
            "source_crs": str(crs_result["source_crs"]),
            "geometry_type": layer.GetGeomType(),
            "feature_count": feature_count,
            "bounds": bounds,
            "encoding": encoding,
            "schema": schema_result,
            "warnings": warnings,
            "optimal_processing_settings": {
                "output_format": "geopackage",
                "chunk_size": min(1000, feature_count // 10)
            }
        }
    }
```

#### C. `services/vector_processing.py::process_vector(params) -> dict`

**Pattern**: Same as `create_cog()` with vector transformations

```python
def process_vector(params: dict) -> dict:
    """
    Stage 2: Reproject and convert vector to target format.

    Operations:
    - Reproject to EPSG:4326
    - Convert to GeoPackage (silver) or GeoParquet (gold)
    - Fix geometries if needed
    - Handle encoding issues

    Args:
        params: {
            "blob_url": str,  # SAS URL
            "source_crs": str,  # From validation
            "target_crs": str = "EPSG:4326",
            "format": str,  # Source format
            "output_blob_name": str,
            "output_format": str = "geopackage",
            "fix_geometries": bool = True
        }

    Returns:
        {
            "success": True,
            "result": {
                "output_blob": "parcels.gpkg",
                "output_container": "silver",
                "reprojection_performed": True,
                "source_crs": "EPSG:26910",
                "target_crs": "EPSG:4326",
                "feature_count": 45203,
                "invalid_geometries_fixed": 12,
                "size_mb": 23.4,
                "processing_time_seconds": 45.2
            }
        }
    """

    # Lazy imports
    from osgeo import ogr
    import tempfile
    import os

    # Create temp directory
    temp_dir = tempfile.mkdtemp(prefix="vector_")

    try:
        # For shapefiles, download ALL companion files
        if params['format'] == 'shapefile':
            _download_shapefile_bundle(params['blob_name'], temp_dir)
            local_input = os.path.join(temp_dir, os.path.basename(params['blob_name']))
        else:
            # Download single file
            blob_repo = BlobRepository.instance()
            data = blob_repo.read_blob(params['container_name'], params['blob_name'])
            local_input = os.path.join(temp_dir, 'input_file')
            with open(local_input, 'wb') as f:
                f.write(data)

        # Process vector
        local_output = os.path.join(temp_dir, 'output.gpkg')

        # Use ogr2ogr for reprojection + format conversion
        result = _process_with_ogr2ogr(
            input_path=local_input,
            output_path=local_output,
            source_crs=params['source_crs'],
            target_crs=params['target_crs'],
            output_format=params['output_format'],
            fix_geometries=params.get('fix_geometries', True)
        )

        # Upload to silver container
        with open(local_output, 'rb') as f:
            blob_repo.write_blob(
                container=config.silver_container_name,
                blob_path=params['output_blob_name'],
                data=f.read()
            )

        return {
            "success": True,
            "result": {
                "output_blob": params['output_blob_name'],
                "output_container": "silver",
                "reprojection_performed": result['reprojected'],
                "feature_count": result['feature_count'],
                "processing_time_seconds": result['elapsed_time']
            }
        }

    finally:
        # Cleanup temp files
        shutil.rmtree(temp_dir, ignore_errors=True)
```

### 3. Workflow Classes - **NEED TO CREATE**

#### Option A: Two-Stage Sequential (Recommended for Single File)

**Pattern**: Same as `ProcessRasterWorkflow`

```python
class ProcessVectorWorkflow:
    """
    Two-stage workflow for single vector file processing.

    Stage 1: Validate vector
    Stage 2: Process vector (uses Stage 1 results)
    """

    job_type = "process_vector"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_vector",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "process",
            "task_type": "process_vector",
            "parallelism": "single"
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
        """Create tasks for each stage."""

        if stage == 1:
            # Stage 1: Validate vector
            blob_repo = BlobRepository.instance()
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=job_params['container_name'],
                blob_name=job_params['blob_name'],
                hours=1
            )

            return [
                {
                    "task_id": generate_deterministic_task_id(job_id, 1, "validate"),
                    "task_type": "validate_vector",
                    "parameters": {
                        "blob_url": blob_url,
                        "blob_name": job_params['blob_name'],
                        "container_name": job_params['container_name'],
                        "input_crs": job_params.get('input_crs'),
                        "format": job_params['format'],
                        "strict_mode": job_params.get('strict_mode', False)
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: Process vector (REQUIRES Stage 1 results)
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            validation_result = previous_results[0]['result']
            source_crs = validation_result['source_crs']  # From Stage 1

            blob_url = blob_repo.get_blob_url_with_sas(...)

            # Output naming: parcels.shp -> parcels.gpkg
            output_blob_name = job_params['blob_name'].rsplit('.', 1)[0] + '.gpkg'

            return [
                {
                    "task_id": generate_deterministic_task_id(job_id, 2, "process"),
                    "task_type": "process_vector",
                    "parameters": {
                        "blob_url": blob_url,
                        "source_crs": source_crs,  # From Stage 1
                        "target_crs": "EPSG:4326",
                        "format": job_params['format'],
                        "output_blob_name": output_blob_name,
                        "output_format": "geopackage",
                        "optimal_processing_settings": validation_result['optimal_processing_settings']
                    }
                }
            ]
```

#### Option B: Two-Stage Fan-Out (Recommended for Bulk Processing)

**Pattern**: Same as `StacCatalogContainerWorkflow`

```python
class BulkVectorCatalogWorkflow:
    """
    Two-stage fan-out workflow for bulk vector processing.

    Stage 1: List all vector files (single task)
    Stage 2: Process each vector file (N parallel tasks)
    """

    job_type = "bulk_vector_catalog"

    stages = [
        {
            "number": 1,
            "name": "list_vectors",
            "task_type": "list_vector_files",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "process_vectors",
            "task_type": "process_vector",
            "parallelism": "fan_out"
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
        """Create tasks for each stage."""

        if stage == 1:
            # Stage 1: List vector files
            return [
                {
                    "task_id": generate_deterministic_task_id(job_id, 1, "list_vectors"),
                    "task_type": "list_vector_files",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "format_filter": job_params.get("format_filter", ['.shp', '.gpkg', '.gdb']),
                        "prefix": job_params.get("prefix", ""),
                        "file_limit": job_params.get("file_limit")
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: FAN-OUT - Process each vector file
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results")

            vector_files = previous_results[0]['result']['vector_files']

            tasks = []
            for vector_file in vector_files:
                tasks.append({
                    "task_id": generate_deterministic_task_id(job_id, 2, vector_file['blob_name']),
                    "task_type": "process_vector",
                    "parameters": {
                        "blob_name": vector_file['blob_name'],
                        "container_name": job_params["container_name"],
                        "format": vector_file['format'],
                        "output_format": "geopackage"
                    }
                })

            return tasks
```

---

## Critical Implementation Details

### 1. Shapefile Companion Files

**Problem**: Shapefiles require `.shp`, `.shx`, `.dbf`, `.prj`, `.cpg` to be present together.

**Solution**:
```python
def _download_shapefile_bundle(blob_name: str, dest_dir: str):
    """Download all companion files for a shapefile."""
    blob_repo = BlobRepository.instance()
    base_name = blob_name.rsplit('.', 1)[0]

    # Required extensions
    extensions = ['.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']

    for ext in extensions:
        companion_blob = base_name + ext
        try:
            data = blob_repo.read_blob(container, companion_blob)
            with open(os.path.join(dest_dir, os.path.basename(companion_blob)), 'wb') as f:
                f.write(data)
        except ResourceNotFoundError:
            if ext in ['.shp', '.shx', '.dbf']:
                raise  # Required files
            # Optional files - skip if missing
```

### 2. File Geodatabase (.gdb) Handling

**Problem**: `.gdb` is a folder structure, not a single file. Can contain multiple feature classes.

**Solution**: BlobRepository already aggregates, but need to download entire folder:

```python
def _download_gdb_folder(gdb_path: str, dest_dir: str):
    """Download entire .gdb folder structure."""
    blob_repo = BlobRepository.instance()

    # List all blobs with .gdb path as prefix
    gdb_blobs = blob_repo.list_blobs(container, prefix=gdb_path + '/')

    for blob in gdb_blobs:
        # Recreate folder structure locally
        relative_path = blob['name'][len(gdb_path)+1:]  # Remove .gdb/ prefix
        local_path = os.path.join(dest_dir, os.path.basename(gdb_path), relative_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        data = blob_repo.read_blob(container, blob['name'])
        with open(local_path, 'wb') as f:
            f.write(data)
```

**Multi-Layer Handling**: One .gdb can have multiple feature classes. Options:
1. **Process all layers to single GeoPackage** (layers preserved)
2. **Fan-out per layer** (creates multiple tasks per .gdb)

Recommend Option 1 for simplicity.

### 3. Encoding Detection (Shapefiles)

**Problem**: Shapefiles default to CP1252 encoding but `.cpg` file can specify UTF-8.

**Solution**:
```python
def _detect_shapefile_encoding(blob_name: str) -> str:
    """Detect encoding for shapefile from .cpg file."""
    blob_repo = BlobRepository.instance()

    cpg_blob = blob_name.rsplit('.', 1)[0] + '.cpg'
    try:
        cpg_data = blob_repo.read_blob(container, cpg_blob)
        encoding = cpg_data.decode('utf-8').strip()
        return encoding
    except ResourceNotFoundError:
        # No .cpg file - assume CP1252 (shapefile default)
        return "CP1252"
```

### 4. CRS Validation (Same as Raster!)

**Critical**: Use EXACT same 4-case logic as raster validation:

```python
def _validate_crs_vector(layer, input_crs: Optional[str]) -> dict:
    """
    Same 4-case logic as raster:
    1. File has CRS + User provides CRS: FAIL if mismatch
    2. File has CRS + No user CRS: Use file CRS
    3. No file CRS + User provides CRS: Use user CRS (with warning)
    4. No file CRS + No user CRS: FAIL
    """

    spatial_ref = layer.GetSpatialRef()

    if spatial_ref:
        file_crs = spatial_ref.ExportToWkt()

        if input_crs:
            if file_crs != input_crs:
                return {
                    "success": False,
                    "error": "CRS_MISMATCH",
                    "message": f"File CRS {file_crs} doesn't match user CRS {input_crs}"
                }

        return {"success": True, "source_crs": file_crs, "crs_source": "file_metadata"}

    else:
        if input_crs:
            return {"success": True, "source_crs": input_crs, "crs_source": "user_override_required"}
        else:
            return {"success": False, "error": "CRS_MISSING", "message": "No CRS in file or parameters"}
```

### 5. Geometry Validation

**Check**: Use GDAL `IsValid()` to detect corrupt geometries.

```python
def _check_geometry_validity(layer, sample_size=100):
    """Check sample of features for invalid geometries."""
    invalid_count = 0
    total_checked = 0

    layer.ResetReading()
    for i, feature in enumerate(layer):
        if i >= sample_size:
            break

        geom = feature.GetGeometryRef()
        if geom and not geom.IsValid():
            invalid_count += 1

        total_checked += 1

    return {
        "invalid_count": invalid_count,
        "total_checked": total_checked,
        "invalid_percentage": (invalid_count / total_checked * 100) if total_checked > 0 else 0
    }
```

---

## Testing Strategy

### Phase 1: Service Handlers
1. Test `list_vector_files()` with sample container
2. Test `.gdb` aggregation (verify BlobRepository works correctly)
3. Test shapefile companion file detection
4. Test `validate_vector()` with various formats
5. Test CRS validation logic (all 4 cases)
6. Test encoding detection
7. Test `process_vector()` with single shapefile

### Phase 2: Workflow Orchestration
1. Test `ProcessVectorWorkflow` with single file
2. Verify Stage 1 → Stage 2 result passing
3. Test failure scenarios (validation fails)
4. Test `BulkVectorCatalogWorkflow` with small container

### Phase 3: Format-Specific Testing
1. **Shapefile**: CP1252 encoding, missing .prj, large files
2. **.gdb**: Multiple feature classes, large folders
3. **GeoPackage**: Multiple layers
4. **GeoParquet**: Partitioned files

---

## Summary Checklist

### Infrastructure (Ready)
- ✅ BlobRepository - List, read, write, SAS URLs
- ✅ `.gdb` aggregation - Already implemented!
- ✅ SAS token generation - Works with GDAL

### Service Layer (To Create)
- ⬜ `list_vector_files()` handler
- ⬜ `validate_vector()` handler
- ⬜ `process_vector()` handler
- ⬜ Shapefile companion file download
- ⬜ `.gdb` folder download
- ⬜ Encoding detection
- ⬜ CRS validation (reuse raster logic)
- ⬜ Geometry validation

### Workflow Layer (To Create)
- ⬜ `ProcessVectorWorkflow` class
- ⬜ `BulkVectorCatalogWorkflow` class
- ⬜ Task creation logic
- ⬜ Result aggregation

### Testing
- ⬜ Unit tests for each handler
- ⬜ Integration tests for workflows
- ⬜ Format-specific tests

---

**Next Step**: Start with `list_vector_files()` handler to prove BlobRepository `.gdb` aggregation works correctly!

