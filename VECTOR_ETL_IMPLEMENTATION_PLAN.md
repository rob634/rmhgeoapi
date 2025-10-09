# Vector ETL Implementation Plan

**Date**: 5 OCT 2025
**Last Updated**: 7 OCT 2025 - Phase 4 Complete ✅
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Complete implementation plan for vector file → PostGIS ETL pipeline

## 🎉 PHASE 1 COMPLETE (5 OCT 2025)

**Status**: Infrastructure setup DONE ✅

**Completed Tasks**:
- ✅ Created `services/vector/` directory structure
- ✅ Created `services/vector/helpers.py` - Conversion utilities (xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file)
- ✅ Created `services/vector/converters.py` - Format-specific converters (6 formats)
- ✅ Created `services/vector/tasks.py` - TaskRegistry handlers (load, validate, upload)
- ✅ Created `services/vector/__init__.py` - Package exports

**Files Created**:
1. `services/vector/helpers.py` (167 lines) - Pure utility functions
2. `services/vector/converters.py` (153 lines) - 6 format converters
3. `services/vector/tasks.py` (167 lines) - 3 task handlers
4. `services/vector/__init__.py` (29 lines) - Package initialization

## 🎉 PHASE 2 COMPLETE (5 OCT 2025)

**Status**: PostGIS Handler Implementation DONE ✅

**Completed Tasks**:
- ✅ Created `services/vector/postgis_handler.py` - VectorToPostGISHandler class
- ✅ Implemented `prepare_gdf()` - Validate geometries, reproject to EPSG:4326, clean columns
- ✅ Implemented `chunk_gdf()` - Split large GeoDataFrames for parallel processing
- ✅ Implemented `upload_chunk()` - Create table and insert features using psycopg
- ✅ Implemented helper methods - Type mapping, table creation, feature insertion
- ✅ Updated `services/vector/__init__.py` - Export VectorToPostGISHandler

**Files Created**:
1. `services/vector/postgis_handler.py` (374 lines) - PostGIS integration with intelligent chunking

**Key Features**:
- ✅ Automatic geometry validation and repair (buffer(0) for invalid geometries)
- ✅ CRS reprojection to EPSG:4326
- ✅ Column name sanitization (lowercase, replace spaces/special chars)
- ✅ **Intelligent chunk size calculation** (NEW!)
  - Analyzes column count and types
  - Evaluates geometry complexity (points vs complex polygons)
  - Auto-calculates optimal chunk size (100-5000 rows)
  - Manual override available
- ✅ Dynamic table creation with proper PostGIS geometry types
- ✅ Spatial index creation (GIST)
- ✅ Type mapping from pandas to PostgreSQL
- ✅ Efficient row-by-row insertion with parameterized queries

**Chunk Size Algorithm**:
```
Base: 1000 rows
× Column factor (0.3-1.0): More columns = smaller chunks
× Type factor (0.6-1.0): Text columns = smaller chunks
× Geometry factor (0.3-1.0): Complex polygons = smaller chunks
= Optimal size (bounded: 100-5000 rows)
```

**Examples**:
- Point CSV with 5 columns: ~1000 rows/chunk
- Polygon shapefile with 50 columns: ~150 rows/chunk
- Complex multipolygons with 20 text columns: ~120 rows/chunk

## 🎉 PHASE 3 COMPLETE (7 OCT 2025)

**Status**: Job Implementation DONE ✅

**Completed Tasks**:
- ✅ Created `jobs/ingest_vector.py` - Two-stage fan-out job with pickle intermediate storage
- ✅ Implemented Stage 1 task: `prepare_vector_chunks` - Load, validate, chunk, pickle to blob
- ✅ Implemented Stage 2 task: `upload_pickled_chunk` - Load pickled chunk and upload to PostGIS
- ✅ Updated `services/vector/tasks.py` with new task handlers (324 lines total)
- ✅ Updated `services/vector/__init__.py` to export new tasks
- ✅ Registered `IngestVectorJob` in `jobs/__init__.py`
- ✅ Fixed infrastructure imports (BlobRepository instead of non-existent StorageHandler)

**Files Created/Updated**:
1. `jobs/ingest_vector.py` (282 lines) - Two-stage job declaration
2. `services/vector/tasks.py` (324 lines) - Added prepare_vector_chunks, upload_pickled_chunk
3. `services/vector/__init__.py` (43 lines) - Export new tasks
4. `jobs/__init__.py` - Registered ingest_vector job

**Architecture: Two-Stage Fan-Out with Service Bus + Pickle**

```
STAGE 1: prepare_vector_chunks (Single Task, ~30-60s)
├─ Load source file from blob storage
├─ Validate & prepare GeoDataFrame
├─ Auto-calculate optimal chunk size
├─ Split into N chunks
├─ Pickle each chunk → silver/temp/vector_etl/{job_id}/chunk_N.pkl
└─ Return: {chunk_paths: [...], table_name, total_rows, chunk_count}

CoreMachine → Creates N Stage 2 tasks → Service Bus

STAGE 2: upload_pickled_chunk (N Parallel Tasks, each ~10-30s)
├─ Service Bus Message: {"chunk_path": "...", "table_name": "..."}
├─ Load pickled chunk from blob storage
├─ Upload to PostGIS (geo schema)
├─ Pickles persist for timer cleanup (audit/retry)
└─ Return: {rows_uploaded, chunk_index, table}

Job Completion (Automatic)
└─ Aggregate: {total_rows_uploaded, chunks_processed, total_chunks}
```

**Key Design Decisions**:

1. **Always Chunk (No Threshold)**
   - Small files (50 rows): 1 chunk, 1 Stage 2 task
   - Medium files (2000 rows): ~3 chunks, 3 Stage 2 tasks
   - Large files (10000 rows): ~20 chunks, 20 Stage 2 tasks
   - **Benefit**: Consistent code path, no special cases, simpler testing
   - Minimal overhead (~1s for pickle) worth it for architectural consistency

2. **Service Bus + Blob References** (Not embedded pickles)
   - Service Bus message: ~200 bytes (blob path only)
   - Pickled chunks: ~300-500KB each (stored in blob)
   - Service Bus Standard tier 256KB limit: ✅ No problem

3. **Pickle as Intermediate Format**
   - Fast serialization/deserialization
   - 100% fidelity (preserves dtypes, CRS, everything)
   - Temporary storage only (cleaned by timer job)
   - Python-only (acceptable for internal workflow)

4. **Timeout Prevention**
   - Single chunk upload: ~30 seconds (well under 5 min timeout)
   - Parallel execution: 50 chunks × 30s = 30s wall-clock time
   - Stage 1 task: ~60 seconds (safe)

5. **Pickle Cleanup Strategy**
   - Pickles persist after upload (for audit/retry)
   - Timer job will clean up pickles >24 hours old
   - Location: `silver/temp/vector_etl/{job_id}/`

**Benefits**:
- ✅ Solves Azure Functions timeout issue
- ✅ Parallel upload for performance
- ✅ Intelligent chunk sizing (auto-calculates based on data)
- ✅ Uses existing infrastructure (BlobRepository, Service Bus)
- ✅ Automatic job completion via CoreMachine
- ✅ Pickle persistence enables retry/debugging

**Next Phase**: Phase 6 - Testing with all 6 file formats

---

## 🎉 PHASE 4 COMPLETE (7 OCT 2025)

**Status**: HTTP Trigger Implementation DONE ✅

**Completed Tasks**:
- ✅ Created `triggers/ingest_vector.py` - HTTP trigger for POST /api/jobs/ingest_vector
- ✅ Registered route in `function_app.py`
- ✅ Implemented idempotency checking
- ✅ Integrated with explicit job registry (no decorators)
- ✅ Full parameter validation via IngestVectorJob

**Files Created/Updated**:
1. `triggers/ingest_vector.py` (189 lines) - HTTP trigger implementation
2. `function_app.py` - Added route registration and import

**Key Features**:
- Uses `JobManagementTrigger` base class pattern
- Explicit registry lookup (no magic, no decorators)
- Idempotent job submission (SHA256-based deduplication)
- Complete parameter validation
- Consistent error handling and logging
- Service Bus integration via CoreMachine

**API Endpoint**:
```bash
POST /api/jobs/ingest_vector

# Example request
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "data/parcels.gpkg",
    "file_extension": "gpkg",
    "table_name": "parcels_2025",
    "converter_params": {
      "layer_name": "parcels"
    }
  }'
```

**Next Phase**: Phase 6 - Testing with all 6 file formats

---

## 🎉 PHASE 5 COMPLETE (7 OCT 2025)

**Status**: STAC Vector Cataloging DONE ✅

**Completed Tasks**:
- ✅ Created `services/service_stac_vector.py` - STAC metadata extraction from PostGIS tables
- ✅ Created `triggers/stac_vector.py` - HTTP trigger for POST /api/stac/vector
- ✅ Registered route in `function_app.py`
- ✅ Integrated with existing `vectors` STAC collection
- ✅ PostGIS spatial queries for extent and metadata

**Files Created**:
1. `services/service_stac_vector.py` (260 lines) - STAC metadata service
2. `triggers/stac_vector.py` (135 lines) - HTTP trigger implementation

**Key Features**:
- Extracts spatial extent via PostGIS `ST_Extent()`
- Queries geometry types, row count, SRID from PostGIS
- Creates STAC Items with `postgis://` asset links
- Validates with stac-pydantic
- Inserts into `vectors` collection
- Supports custom properties for metadata enrichment

**API Endpoint**:
```bash
POST /api/stac/vector

# Example: Catalog a PostGIS table
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/vector \
  -H "Content-Type: application/json" \
  -d '{
    "schema": "geo",
    "table_name": "parcels_2025",
    "collection_id": "vectors",
    "source_file": "data/parcels.gpkg",
    "properties": {
      "jurisdiction": "county"
    }
  }'
```

**Integration Pattern**:
1. Ingest vector file: `POST /api/jobs/ingest_vector` → PostGIS table
2. Catalog table: `POST /api/stac/vector` → STAC Item in `vectors` collection

**Next Phase**: Phase 6 - Testing (all 6 file formats)

---

## 🎯 Overview

**Goal**: Implement end-to-end vector ETL pipeline that accepts multiple file formats from blob storage and loads them into PostGIS tables in the `geo` schema.

**Architecture Pattern**: Multi-stage job using TaskRegistry (NOT separate ConverterRegistry)

**Workflow**:
```
Blob Storage (bronze) → Load & Convert → Validate → Fan-out Parallel Upload → PostGIS (geo schema)
```

---

## 🏗️ Architecture Decisions

### ✅ Key Decision: Use TaskRegistry, Not ConverterRegistry

**Rationale**:
- Converters are just task handlers - functions that execute as part of tasks
- One registry (TaskRegistry) maintains consistency
- Simpler architecture, no parallel registry system
- CoreMachine already knows how to execute tasks

**Implementation**:
```python
# Converters become helper functions used by tasks
@TaskRegistry.register("load_vector_file")
def load_vector_file(parameters: Dict[str, Any]) -> Dict[str, Any]:
    file_extension = parameters["file_extension"]

    # Dispatch to helper based on extension
    if file_extension == "csv":
        gdf = _convert_csv(file_data, **params)
    elif file_extension == "gpkg":
        gdf = _convert_geopackage(file_data, **params)
    # ... etc

    return {"gdf": gdf.to_json(), "row_count": len(gdf)}
```

---

## 📂 Target File Structure

```
services/vector/
├── __init__.py
├── helpers.py              # xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file
├── converters.py           # _convert_csv, _convert_gpkg, etc. (private helpers)
├── postgis_handler.py      # VectorToPostGISHandler class
└── tasks.py                # @TaskRegistry tasks

jobs/
└── ingest_vector.py        # @JobRegistry job handler

triggers/
└── ingest_vector.py        # POST /api/jobs/ingest_vector

infrastructure/
└── postgresql.py           # Add deploy_geo_schema()
```

---

## 📋 Implementation Phases

### **Phase 1: Infrastructure Setup** (2-3 hours)

#### Task 1.1: Reorganize vector/ folder
```bash
# Move existing vector/ code to services/vector/
mkdir -p services/vector
mv vector/* services/vector/
# Update .funcignore if needed
```

#### Task 1.2: Create services/vector/helpers.py
```python
"""
Vector conversion utility functions.
"""

from io import BytesIO
from typing import List
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point

DEFAULT_CRS = "EPSG:4326"

def xy_df_to_gdf(df: pd.DataFrame, lat_name: str, lon_name: str,
                 crs: str = DEFAULT_CRS) -> gpd.GeoDataFrame:
    """
    Convert DataFrame with lat/lon columns to GeoDataFrame.

    Args:
        df: DataFrame with coordinate columns
        lat_name: Latitude column name
        lon_name: Longitude column name
        crs: Coordinate reference system

    Returns:
        GeoDataFrame with Point geometries
    """
    # Validate coordinates are within bounds
    if not (-180 <= df[lon_name].min() <= 180 and -180 <= df[lon_name].max() <= 180):
        raise ValueError(f"Longitude values out of range: {df[lon_name].min()}, {df[lon_name].max()}")

    if not (-90 <= df[lat_name].min() <= 90 and -90 <= df[lat_name].max() <= 90):
        raise ValueError(f"Latitude values out of range: {df[lat_name].min()}, {df[lat_name].max()}")

    # Create Point geometries
    geometry = [Point(xy) for xy in zip(df[lon_name], df[lat_name])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)

    return gdf


def wkt_df_to_gdf(df: pd.DataFrame, wkt_column: str,
                  crs: str = DEFAULT_CRS) -> gpd.GeoDataFrame:
    """
    Convert DataFrame with WKT geometry column to GeoDataFrame.

    Args:
        df: DataFrame with WKT column
        wkt_column: WKT geometry column name
        crs: Coordinate reference system

    Returns:
        GeoDataFrame with parsed geometries
    """
    from shapely.errors import WKTReadingError

    try:
        geometry = df[wkt_column].apply(wkt.loads)
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
        return gdf
    except WKTReadingError as e:
        raise ValueError(f"Invalid WKT in column {wkt_column}: {e}")


def extract_zip_file(zip_data: BytesIO, target_extension: str,
                     target_name: str = None) -> str:
    """
    Extract file from ZIP archive to temp directory.

    Args:
        zip_data: BytesIO containing ZIP data
        target_extension: File extension to find (e.g., '.shp', '.kml')
        target_name: Specific filename (optional)

    Returns:
        Path to extracted file in temp directory
    """
    import zipfile
    import tempfile
    from pathlib import Path

    temp_dir = tempfile.mkdtemp()

    with zipfile.ZipFile(zip_data) as zf:
        # Extract all files
        zf.extractall(temp_dir)

        # Find target file
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if target_name and file == target_name:
                    return os.path.join(root, file)
                elif file.endswith(target_extension):
                    return os.path.join(root, file)

        raise FileNotFoundError(
            f"No file with extension {target_extension} found in ZIP"
        )
```

#### Task 1.3: Create services/vector/converters.py
```python
"""
Format-specific vector conversion helpers (private functions).
"""

from io import BytesIO
from typing import Dict, Any
import pandas as pd
import geopandas as gpd
from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS

def _convert_csv(data: BytesIO, lat_name: str = None, lon_name: str = None,
                 wkt_column: str = None, **kwargs) -> gpd.GeoDataFrame:
    """Convert CSV to GeoDataFrame (lat/lon or WKT)."""
    if not (wkt_column or (lat_name and lon_name)):
        raise ValueError("Must provide either wkt_column or lat_name+lon_name")

    df = pd.read_csv(data)

    if wkt_column:
        return wkt_df_to_gdf(df, wkt_column)
    else:
        return xy_df_to_gdf(df, lat_name, lon_name)


def _convert_geojson(data: BytesIO, **kwargs) -> gpd.GeoDataFrame:
    """Convert GeoJSON to GeoDataFrame."""
    return gpd.read_file(data)


def _convert_geopackage(data: BytesIO, layer_name: str, **kwargs) -> gpd.GeoDataFrame:
    """Convert GeoPackage to GeoDataFrame."""
    if not layer_name:
        raise ValueError("layer_name required for GeoPackage")
    return gpd.read_file(data, layer=layer_name)


def _convert_kml(data: BytesIO, **kwargs) -> gpd.GeoDataFrame:
    """Convert KML to GeoDataFrame."""
    return gpd.read_file(data)


def _convert_kmz(data: BytesIO, kml_name: str = None, **kwargs) -> gpd.GeoDataFrame:
    """Convert KMZ (zipped KML) to GeoDataFrame."""
    kml_path = extract_zip_file(data, '.kml', kml_name)
    return gpd.read_file(kml_path)


def _convert_shapefile(data: BytesIO, shp_name: str = None, **kwargs) -> gpd.GeoDataFrame:
    """Convert Shapefile (in ZIP) to GeoDataFrame."""
    shp_path = extract_zip_file(data, '.shp', shp_name)
    return gpd.read_file(shp_path)
```

#### Task 1.4: Create services/vector/tasks.py
```python
"""
Vector ETL task handlers using TaskRegistry.
"""

from typing import Dict, Any
import geopandas as gpd
from infrastructure.blob import StorageHandler
from .converters import (
    _convert_csv, _convert_geojson, _convert_geopackage,
    _convert_kml, _convert_kmz, _convert_shapefile
)
from .postgis_handler import VectorToPostGISHandler

# Note: TaskRegistry import will be added when it exists
# from core.registry import TaskRegistry


def load_vector_file(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Task: Load vector file from blob storage to GeoDataFrame.

    Parameters:
        blob_name: str - Blob path
        container_name: str - Container name
        file_extension: str - File extension (determines converter)
        **converter_params - Format-specific params

    Returns:
        gdf: str - Serialized GeoDataFrame (JSON)
        row_count: int
        geometry_types: List[str]
        bounds: List[float]
        crs: str
    """
    blob_name = parameters["blob_name"]
    container_name = parameters.get("container_name", "bronze")
    file_extension = parameters["file_extension"].lower().lstrip('.')

    # Get file from blob storage
    storage = StorageHandler(workspace_container_name=container_name)
    file_data = storage.blob_to_bytesio(blob_name)

    # Extract converter params
    converter_params = {
        k: v for k, v in parameters.items()
        if k not in ['blob_name', 'container_name', 'file_extension']
    }

    # Dispatch to appropriate converter
    converters = {
        'csv': _convert_csv,
        'geojson': _convert_geojson,
        'json': _convert_geojson,
        'gpkg': _convert_geopackage,
        'kml': _convert_kml,
        'kmz': _convert_kmz,
        'shp': _convert_shapefile,
        'zip': _convert_shapefile  # Assume shapefile if .zip
    }

    if file_extension not in converters:
        raise ValueError(f"Unsupported file extension: {file_extension}")

    gdf = converters[file_extension](file_data, **converter_params)

    return {
        "gdf": gdf.to_json(),
        "row_count": len(gdf),
        "geometry_types": gdf.geometry.type.unique().tolist(),
        "bounds": gdf.total_bounds.tolist(),
        "crs": str(gdf.crs) if gdf.crs else None
    }


def validate_vector(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Task: Validate and prepare GeoDataFrame for PostGIS.

    Parameters:
        gdf_serialized: str - JSON serialized GeoDataFrame

    Returns:
        validated_gdf: str - Serialized validated GeoDataFrame
        geometry_types: List[str]
    """
    gdf = gpd.read_file(parameters["gdf_serialized"])

    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf)

    return {
        "validated_gdf": validated_gdf.to_json(),
        "geometry_types": validated_gdf.geometry.type.unique().tolist()
    }


def upload_vector_chunk(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Task: Upload GeoDataFrame chunk to PostGIS.

    Parameters:
        chunk_data: str - JSON serialized GeoDataFrame chunk
        table_name: str - Target table name
        schema: str - Target schema (default: 'geo')

    Returns:
        rows_uploaded: int
        table: str
    """
    chunk = gpd.read_file(parameters["chunk_data"])
    table_name = parameters["table_name"]
    schema = parameters.get("schema", "geo")

    handler = VectorToPostGISHandler()
    handler.upload_chunk(chunk, table_name, schema)

    return {
        "rows_uploaded": len(chunk),
        "table": f"{schema}.{table_name}"
    }
```

---

### **Phase 2: PostGIS Handler** (2-3 hours)

#### Task 2.1: Create services/vector/postgis_handler.py
```python
"""
Vector to PostGIS handler - validation, chunking, upload.
"""

from typing import List
import geopandas as gpd
from config import get_config
import psycopg

class VectorToPostGISHandler:
    """Handles GeoDataFrame → PostGIS operations."""

    def __init__(self):
        config = get_config()
        self.conn_string = config.postgis_connection_string

    def prepare_gdf(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Validate, reproject, and clean GeoDataFrame.

        - Ensures valid geometries
        - Reprojects to EPSG:4326 if needed
        - Removes null geometries
        - Cleans column names (lowercase, no spaces)
        """
        # Remove null geometries
        gdf = gdf[~gdf.geometry.isna()].copy()

        # Ensure valid geometries
        if not gdf.geometry.is_valid.all():
            gdf.geometry = gdf.geometry.buffer(0)  # Fix invalid geometries

        # Reproject to EPSG:4326 if needed
        if gdf.crs and gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")

        # Clean column names
        gdf.columns = [col.lower().replace(' ', '_') for col in gdf.columns]

        return gdf

    def chunk_gdf(self, gdf: gpd.GeoDataFrame, chunk_size: int = 1000) -> List[gpd.GeoDataFrame]:
        """
        Split GeoDataFrame into chunks for parallel upload.

        Args:
            gdf: GeoDataFrame to split
            chunk_size: Rows per chunk

        Returns:
            List of GeoDataFrame chunks
        """
        chunks = []
        for i in range(0, len(gdf), chunk_size):
            chunks.append(gdf.iloc[i:i + chunk_size].copy())
        return chunks

    def upload_chunk(self, chunk: gpd.GeoDataFrame, table_name: str, schema: str = "geo"):
        """
        Upload GeoDataFrame chunk to PostGIS using psycopg.

        Args:
            chunk: GeoDataFrame chunk
            table_name: Target table name
            schema: Target schema (default: 'geo')
        """
        with psycopg.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                # Create table if not exists (from first chunk)
                # This is simplified - production should use proper schema detection
                geom_type = chunk.geometry.type.iloc[0].upper()

                # Create table
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {schema}.{table_name} (
                        id SERIAL PRIMARY KEY,
                        geom GEOMETRY({geom_type}, 4326)
                    );
                """)

                # Add attribute columns dynamically
                for col in chunk.columns:
                    if col != 'geometry':
                        # Simplified type detection
                        dtype = 'TEXT'  # Default to TEXT for now
                        cur.execute(f"""
                            ALTER TABLE {schema}.{table_name}
                            ADD COLUMN IF NOT EXISTS {col} {dtype};
                        """)

                # Insert data
                for idx, row in chunk.iterrows():
                    geom_wkt = row.geometry.wkt
                    values = {col: row[col] for col in chunk.columns if col != 'geometry'}

                    cols = ', '.join(values.keys())
                    placeholders = ', '.join(['%s'] * len(values))

                    cur.execute(f"""
                        INSERT INTO {schema}.{table_name} (geom, {cols})
                        VALUES (ST_GeomFromText(%s, 4326), {placeholders});
                    """, [geom_wkt] + list(values.values()))

                conn.commit()
```

---

### **Phase 3: Job Implementation** (3-4 hours)

#### Task 3.1: Create jobs/ingest_vector.py
```python
"""
Vector Ingest Job - Multi-stage ETL workflow.

Stage 1: Load vector file from blob → GeoDataFrame
Stage 2: Validate and prepare GeoDataFrame
Stage 3: Fan-out chunked parallel upload to PostGIS
"""

from typing import List, Dict, Any
from core.registry import JobRegistry
from core.models.task import TaskDefinition
from core.models.job import JobContext
from services.vector.postgis_handler import VectorToPostGISHandler
import geopandas as gpd


@JobRegistry.instance().register(job_type="ingest_vector")
class IngestVectorJob:
    """
    Multi-stage vector ETL job.

    Input Parameters:
        blob_name: str - Source file path in blob storage
        file_extension: str - File extension (csv, gpkg, geojson, etc.)
        table_name: str - Target PostGIS table name
        container_name: str - Blob container (default: 'bronze')
        chunk_size: int - Rows per upload chunk (default: 1000)
        converter_params: Dict - Format-specific params
            For CSV: lat_name, lon_name OR wkt_column
            For GPKG: layer_name
            For KMZ/Shapefile: optional file name in archive
    """

    def create_stage_1_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Stage 1: Load vector file from blob storage."""
        params = context.parameters

        return [
            TaskDefinition(
                task_type="load_vector_file",
                parameters={
                    "blob_name": params["blob_name"],
                    "container_name": params.get("container_name", "bronze"),
                    "file_extension": params["file_extension"],
                    **params.get("converter_params", {})
                }
            )
        ]

    def create_stage_2_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Stage 2: Validate and prepare GeoDataFrame."""
        # Get GeoDataFrame from stage 1 results
        gdf_json = context.previous_stage_results[0]["gdf"]

        return [
            TaskDefinition(
                task_type="validate_vector",
                parameters={
                    "gdf_serialized": gdf_json
                }
            )
        ]

    def create_stage_3_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Stage 3: Fan-out chunked parallel upload to PostGIS."""
        # Get validated GeoDataFrame from stage 2
        validated_gdf_json = context.previous_stage_results[0]["validated_gdf"]
        gdf = gpd.read_file(validated_gdf_json)

        # Chunk the GeoDataFrame
        chunk_size = context.parameters.get("chunk_size", 1000)
        handler = VectorToPostGISHandler()
        chunks = handler.chunk_gdf(gdf, chunk_size)

        # Create task for each chunk
        tasks = []
        for i, chunk in enumerate(chunks):
            tasks.append(
                TaskDefinition(
                    task_type="upload_vector_chunk",
                    semantic_id=f"chunk_{i}",
                    parameters={
                        "chunk_data": chunk.to_json(),
                        "table_name": context.parameters["table_name"],
                        "schema": "geo"
                    }
                )
            )

        return tasks

    def aggregate_stage_results(self, stage: int, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate results from completed stage."""
        if stage == 3:
            # Aggregate upload results
            total_rows = sum(r["rows_uploaded"] for r in results)
            return {
                "total_rows_uploaded": total_rows,
                "chunks_uploaded": len(results),
                "table": results[0]["table"]
            }
        return {}
```

---

### **Phase 4: HTTP Trigger** (1 hour)

#### Task 4.1: Create triggers/ingest_vector.py
```python
"""
Vector Ingest HTTP Trigger.
"""

import azure.functions as func
import json
from triggers.http_base import BaseHttpTrigger
from core.machine import CoreMachine


class IngestVectorTrigger(BaseHttpTrigger):
    """
    POST /api/jobs/ingest_vector

    Submit vector file for ETL to PostGIS.
    """

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Request Body:
        {
            "blob_name": "data/parcels.gpkg",
            "file_extension": "gpkg",
            "table_name": "parcels_2025",
            "container_name": "bronze",  // optional
            "chunk_size": 1000,  // optional
            "converter_params": {  // format-specific
                "layer_name": "parcels"  // for GPKG
                // OR
                "lat_name": "latitude",  // for CSV
                "lon_name": "longitude"
            }
        }
        """
        try:
            job_params = req.get_json()

            # Validate required fields
            required = ["blob_name", "file_extension", "table_name"]
            missing = [f for f in required if f not in job_params]
            if missing:
                return self.error_response(
                    f"Missing required fields: {', '.join(missing)}",
                    status_code=400
                )

            # Submit job
            machine = CoreMachine()
            job_id = machine.submit_job("ingest_vector", job_params)

            return self.success_response({
                "job_id": job_id,
                "job_type": "ingest_vector",
                "status": "submitted"
            })

        except Exception as e:
            return self.error_response(str(e), status_code=500)


# Function binding
ingest_vector_trigger = IngestVectorTrigger()
```

#### Task 4.2: Register in function_app.py
```python
# Add to function_app.py

from triggers.ingest_vector import ingest_vector_trigger

@app.route(route="jobs/ingest_vector", methods=["POST"])
def ingest_vector_http(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/jobs/ingest_vector - Submit vector ETL job"""
    return ingest_vector_trigger.handle_request(req)
```

---

### **Phase 5: Database Schema Enhancement** (1 hour)

#### Task 5.1: Update infrastructure/postgresql.py

Add to `deploy_schema()` method:

```python
def deploy_geo_schema(self):
    """Deploy geo schema for vector data storage."""
    statements = [
        # Create schema
        "CREATE SCHEMA IF NOT EXISTS geo;",

        # Enable PostGIS
        "CREATE EXTENSION IF NOT EXISTS postgis;",

        # Metadata table for vector datasets
        """
        CREATE TABLE IF NOT EXISTS geo.datasets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            table_name TEXT UNIQUE NOT NULL,
            source_file TEXT,
            row_count INTEGER,
            geometry_type TEXT,
            srid INTEGER DEFAULT 4326,
            bounds JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,

        # Create index on table_name
        """
        CREATE INDEX IF NOT EXISTS idx_datasets_table_name
        ON geo.datasets(table_name);
        """,

        # Trigger for updated_at
        """
        CREATE TRIGGER update_datasets_updated_at
        BEFORE UPDATE ON geo.datasets
        FOR EACH ROW EXECUTE FUNCTION app.update_updated_at_column();
        """
    ]

    with psycopg.connect(self.conn_string) as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
```

Call this in `deploy_schema()`:
```python
def deploy_schema(self):
    """Deploy all schemas."""
    self.deploy_app_schema()  # Existing
    self.deploy_geo_schema()   # New
    # self.deploy_pgstac_schema() called separately via /api/stac/setup
```

---

### **Phase 6: Testing** (2-3 hours)

#### Test Cases

**Test 1: CSV with lat/lon**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/stores.csv",
    "file_extension": "csv",
    "table_name": "retail_stores",
    "converter_params": {
      "lat_name": "latitude",
      "lon_name": "longitude"
    }
  }'
```

**Test 2: GeoPackage**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/parcels.gpkg",
    "file_extension": "gpkg",
    "table_name": "land_parcels",
    "converter_params": {
      "layer_name": "parcels"
    }
  }'
```

**Test 3: GeoJSON**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/boundaries.geojson",
    "file_extension": "geojson",
    "table_name": "admin_boundaries"
  }'
```

**Test 4: KML**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/routes.kml",
    "file_extension": "kml",
    "table_name": "transit_routes"
  }'
```

**Test 5: KMZ (zipped KML)**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/boundaries.kmz",
    "file_extension": "kmz",
    "table_name": "kmz_boundaries"
  }'
```

**Test 6: Shapefile (zipped)**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/roads.zip",
    "file_extension": "shp",
    "table_name": "road_network"
  }'
```

#### Verification Queries

```bash
# Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Check tasks
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}

# Query PostGIS table (via psql or DBeaver)
SELECT COUNT(*), ST_GeometryType(geom)
FROM geo.retail_stores
GROUP BY ST_GeometryType(geom);
```

---

### **Phase 7: Deployment** (1 hour)

#### Deployment Steps

```bash
# 1. Deploy function app
func azure functionapp publish rmhgeoapibeta --python --build remote

# 2. Wait for deployment
sleep 60

# 3. Redeploy schema (includes new geo schema)
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# 4. Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# 5. Run end-to-end test (use one of the test cases above)

# 6. Verify PostGIS tables created
# Connect via psql/DBeaver and check:
SELECT * FROM geo.datasets;
\dt geo.*
```

---

## 📊 Success Criteria

### Functionality ✅
- [ ] All 6 file formats convert successfully (CSV, GeoJSON, GPKG, KML, KMZ, Shapefile)
- [ ] Multi-stage job execution works (Load → Validate → Upload)
- [ ] Fan-out parallel upload completes for large datasets (10,000+ rows)
- [ ] PostGIS tables created in `geo` schema with correct geometry types
- [ ] geo.datasets metadata table tracks all ingested datasets

### Performance ✅
- [ ] 1,000 row CSV uploads in < 10 seconds
- [ ] 10,000 row GeoPackage uploads in < 60 seconds
- [ ] Parallel chunk uploads scale linearly

### Code Quality ✅
- [ ] No separate ConverterRegistry (uses TaskRegistry)
- [ ] Single responsibility for each component
- [ ] Proper error handling with meaningful messages
- [ ] Pydantic validation at all boundaries
- [ ] Helper functions are pure utilities (no side effects)

### Documentation ✅
- [ ] FILE_CATALOG.md updated with new files
- [ ] API endpoint documented
- [ ] Example requests for all formats provided

---

## 🚀 Quick Start Commands

```bash
# 1. Create test CSV file
cat > /tmp/test_stores.csv << EOF
name,latitude,longitude,category
Store A,40.7128,-74.0060,retail
Store B,34.0522,-118.2437,wholesale
EOF

# 2. Upload to blob storage
az storage blob upload \
  --account-name rmhazuregeo \
  --container-name bronze \
  --name test/stores.csv \
  --file /tmp/test_stores.csv

# 3. Submit ingest job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test/stores.csv",
    "file_extension": "csv",
    "table_name": "test_stores",
    "converter_params": {
      "lat_name": "latitude",
      "lon_name": "longitude"
    }
  }'

# 4. Check status (use job_id from step 3)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## 📝 Implementation Checklist

### Phase 1: Infrastructure ✅ COMPLETE
- [x] Task 1.1: Create services/vector/ directory structure
- [x] Task 1.2: Create helpers.py (xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file)
- [x] Task 1.3: Create converters.py (format-specific helpers)
- [x] Task 1.4: Create tasks.py with TaskRegistry handlers
- [x] Task 1.5: Create __init__.py for package exports

### Phase 2: PostGIS Handler ✅ COMPLETE
- [x] Task 2.1: Create postgis_handler.py with VectorToPostGISHandler class
- [x] Task 2.2: Implement prepare_gdf() (validation, reprojection, column cleaning)
- [x] Task 2.3: Implement chunk_gdf() (chunking for parallel upload)
- [x] Task 2.4: Implement upload_chunk() (psycopg PostGIS upload)
- [x] Task 2.5: Implement _get_postgres_type() (dtype mapping)
- [x] Task 2.6: Implement _create_table_if_not_exists() (table + spatial index)
- [x] Task 2.7: Implement _insert_features() (parameterized inserts)
- [x] Task 2.8: Update __init__.py to export VectorToPostGISHandler

### Phase 3: Job Implementation ✅
- [ ] Task 3.1: Create jobs/ingest_vector.py
- [ ] Task 3.2: Implement create_stage_1_tasks() (load file)
- [ ] Task 3.3: Implement create_stage_2_tasks() (validate)
- [ ] Task 3.4: Implement create_stage_3_tasks() (fan-out upload)

### Phase 4: HTTP Trigger ✅
- [ ] Task 4.1: Create triggers/ingest_vector.py
- [ ] Task 4.2: Register in function_app.py

### Phase 5: Database Schema ✅
- [ ] Task 5.1: Add deploy_geo_schema() to postgresql.py
- [ ] Task 5.2: Create geo.datasets metadata table

### Phase 6: Testing ✅
- [ ] Test 6.1: CSV with lat/lon
- [ ] Test 6.2: GeoPackage with layer
- [ ] Test 6.3: GeoJSON
- [ ] Test 6.4: KML
- [ ] Test 6.5: KMZ (zipped KML)
- [ ] Test 6.6: Shapefile (zipped)

### Phase 7: Deployment ✅
- [ ] Deploy to rmhgeoapibeta
- [ ] Redeploy schema with geo schema
- [ ] Run end-to-end test
- [ ] Update FILE_CATALOG.md

---

## 🔗 Related Documentation

- **Architecture**: `docs/architecture_quickstart.md`
- **Task Registry Pattern**: `docs/TASK_REGISTRY_PATTERN.md`
- **Job Implementation Guide**: `docs_claude/CLAUDE_CONTEXT.md`
- **PostgreSQL Setup**: `POSTGRES_REQUIREMENTS.md`
- **Vector Reference Code**: `vector/` (original design docs)

---

**Estimated Total Time**: 12-15 hours

**Next Claude Session**: Start with Phase 1, Task 1.1 (reorganize vector/ folder)
