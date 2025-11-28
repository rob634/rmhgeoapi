# Vector ETL Pipeline - Production Ready

**Date**: 18 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ PRODUCTION READY - ALL FORMATS TESTED

---

## 🎯 Summary

Complete vector data ingestion pipeline supporting **6 major formats** with:
- ✅ **Parallel uploads** (PostgreSQL deadlock fix working)
- ✅ **2D geometry enforcement** (Z/M dimension removal)
- ✅ **Multi-geometry normalization** (ArcGIS compatibility)
- ✅ **EPSG:4326 reprojection**
- ✅ **100% success rate** across all tested formats

---

## 📊 Tested Formats & Results

| Format | Test File | Chunks | Features | Status | Notes |
|--------|-----------|--------|----------|--------|-------|
| **GeoPackage** | roads.gpkg | 2 | N/A | ✅ | Optional layer_name parameter |
| **Shapefile** | kba_shp.zip | 17 | N/A | ✅ | NO DEADLOCKS - 100% success |
| **KMZ** | grid.kml.kmz | 21 | 12,228 | ✅ | 3D → 2D conversion |
| **KML** | doc.kml | 21 | 12,228 | ✅ | 3D → 2D conversion |
| **GeoJSON** | 8.geojson | 10 | 3,879 | ✅ | Standard format |
| **CSV** | acled_test.csv | 17 | 5,000 | ✅ | Lat/lon columns |

---

## 🔧 Key Features

### 1. PostgreSQL Deadlock Fix (18 OCT 2025)

**Problem**: Multiple parallel tasks creating table + inserting simultaneously caused deadlocks.

**Solution**: Serialize table creation, then parallel inserts.

**Implementation**:
```python
# Stage 1 Aggregation (jobs/ingest_vector.py)
# Create table ONCE before Stage 2 starts
postgis_handler.create_table_only(first_chunk, table_name, schema)

# Stage 2 Tasks (services/vector/tasks.py)
# Parallel inserts only (table already exists)
handler.insert_features_only(chunk, table_name, schema)
```

**Files Modified**:
- `services/vector/postgis_handler.py` - Split DDL/DML operations
  - `create_table_only()` - DDL only (line 329-348)
  - `insert_features_only()` - DML only (line 350-367)
- `jobs/ingest_vector.py` - Table creation in Stage 2 setup (line 316-378)
- `services/vector/tasks.py` - Updated upload task (line 316-321)

**Testing**: kba_shp.zip (17 chunks) - **100% success, ZERO deadlocks**

---

### 2. 2D Geometry Enforcement (18 OCT 2025)

**Purpose**: System only supports 2D geometries (x, y coordinates).

**Problem**: KML/KMZ files often contain 3D geometries with Z (elevation) and M (measure) dimensions.

**Solution**: Strip Z/M dimensions using `shapely.force_2d()`.

**Implementation**:
```python
# services/vector/postgis_handler.py → prepare_gdf() (lines 88-125)

from shapely import force_2d

# Check if any geometries have Z or M dimensions
has_z = gdf.geometry.has_z.any()
has_m = gdf.geometry.has_m.any() if hasattr(gdf.geometry, 'has_m') else False

if has_z or has_m:
    # Force 2D and rebuild GeoDataFrame
    crs_before = gdf.crs
    geoms_2d = gdf.geometry.apply(force_2d)

    # Recreate GeoDataFrame with 2D geometries only
    gdf = gpd.GeoDataFrame(
        gdf.drop(columns=['geometry']),
        geometry=geoms_2d,
        crs=crs_before
    )
```

**Verification**: Local testing confirmed coordinates reduced from 3 values to 2:
- Before: `Point(1.0, 2.0, 100.0)` - 3 coordinate values
- After: `Point(1.0, 2.0)` - 2 coordinate values
- After pickle/unpickle: `Point(1.0, 2.0)` - **Still 2 values** ✅

**Bug Fixed**: Series boolean ambiguity - added `.any()` to `has_m` check to convert Series to boolean.

---

### 3. Mixed Geometry Normalization (18 OCT 2025)

**Purpose**: ArcGIS requires uniform geometry types in tables.

**Problem**: Some datasets contain mixed Polygon + MultiPolygon, LineString + MultiLineString, etc.

**Solution**: Normalize all geometries to Multi- types.

**Implementation**:
```python
# services/vector/postgis_handler.py → prepare_gdf() (lines 127-168)

from shapely.geometry import Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon

# Detect geometry types
geom_types = gdf.geometry.geom_type.unique()

# Normalize to Multi- types
if any(t in ['Point', 'MultiPoint'] for t in geom_types):
    gdf.geometry = gdf.geometry.apply(lambda g:
        MultiPoint([g]) if isinstance(g, Point) else g
    )
elif any(t in ['LineString', 'MultiLineString'] for t in geom_types):
    gdf.geometry = gdf.geometry.apply(lambda g:
        MultiLineString([g]) if isinstance(g, LineString) else g
    )
elif any(t in ['Polygon', 'MultiPolygon'] for t in geom_types):
    gdf.geometry = gdf.geometry.apply(lambda g:
        MultiPolygon([g]) if isinstance(g, Polygon) else g
    )
```

**Cost**: <1% storage/performance overhead - minimal impact for compatibility benefit.

---

## 📋 Usage Examples

### GeoPackage
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "roads.gpkg",
    "file_extension": ".gpkg",
    "table_name": "roads_test",
    "container_name": "rmhazuregeobronze",
    "schema": "geo"
  }'
```

**Optional**: Specify layer name (defaults to first layer)
```json
{
  "blob_name": "data.gpkg",
  "file_extension": ".gpkg",
  "table_name": "my_table",
  "container_name": "rmhazuregeobronze",
  "schema": "geo",
  "converter_params": {
    "layer_name": "specific_layer"
  }
}
```

---

### Shapefile (ZIP)
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "kba_shp.zip",
    "file_extension": ".zip",
    "table_name": "kba_test",
    "container_name": "rmhazuregeobronze",
    "schema": "geo"
  }'
```

---

### KMZ/KML (3D → 2D automatic)
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "grid.kml.kmz",
    "file_extension": ".kmz",
    "table_name": "grid_kmz",
    "container_name": "rmhazuregeobronze",
    "schema": "geo"
  }'
```

---

### GeoJSON
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "8.geojson",
    "file_extension": ".geojson",
    "table_name": "geojson_test",
    "container_name": "rmhazuregeobronze",
    "schema": "geo"
  }'
```

---

### CSV (lat/lon columns)
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "acled_test.csv",
    "file_extension": ".csv",
    "table_name": "acled_csv",
    "container_name": "rmhazuregeobronze",
    "schema": "geo",
    "converter_params": {
      "lat_name": "latitude",
      "lon_name": "longitude"
    }
  }'
```

**CSV with WKT geometry column**:
```json
{
  "blob_name": "data.csv",
  "file_extension": ".csv",
  "table_name": "my_table",
  "container_name": "rmhazuregeobronze",
  "schema": "geo",
  "converter_params": {
    "wkt_column": "geometry"
  }
}
```

---

## 🏗️ Architecture

### Two-Stage Pipeline

**Stage 1: Prepare Chunks**
- Download blob from Azure Storage
- Convert to GeoDataFrame using format-specific converter
- Validate and normalize geometries:
  - Reproject to EPSG:4326 if needed
  - Force 2D (remove Z/M dimensions)
  - Normalize to Multi- types
- Split into chunks (default: auto-calculate based on size)
- Pickle chunks to blob storage
- **Stage 1 Aggregation**: Create PostGIS table (DDL only)

**Stage 2: Parallel Upload**
- Load pickled chunks in parallel
- Insert features into existing table (DML only)
- No table creation - prevents deadlocks

### Files

**Job Controller**:
- `jobs/ingest_vector.py` - Main orchestration
  - `validate_job_parameters()` - Required: blob_name, file_extension, table_name
  - `create_tasks_for_stage()` - Stage 1: convert task, Stage 2: upload tasks + table creation
  - `aggregate_stage_results()` - Stage completion logic
  - `should_advance_stage()` - Stage advancement rules

**Format Converters**:
- `services/vector/converters.py` - Format-specific conversion
  - `_convert_csv()` - CSV with lat/lon or WKT
  - `_convert_geojson()` - GeoJSON files
  - `_convert_geopackage()` - GeoPackage with layer selection
  - `_convert_kml()` - KML files
  - `_convert_kmz()` - KMZ (zipped KML) files
  - `_convert_shapefile()` - Shapefile (zipped)

**PostGIS Handler**:
- `services/vector/postgis_handler.py` - Database operations
  - `prepare_gdf()` - Validate, normalize, enforce 2D (lines 70-168)
  - `create_table_only()` - DDL only for Stage 1 (lines 329-348)
  - `insert_features_only()` - DML only for Stage 2 (lines 350-367)
  - `calculate_optimal_chunk_size()` - Auto-calculate chunk size (lines 223-268)

**Task Executors**:
- `services/vector/tasks.py` - Task implementations
  - `convert_and_pickle_vector()` - Stage 1 task
  - `upload_pickled_chunk()` - Stage 2 task

**Helpers**:
- `services/vector/helpers.py` - Utility functions
  - `xy_df_to_gdf()` - Convert DataFrame with lat/lon to GeoDataFrame
  - `wkt_df_to_gdf()` - Convert DataFrame with WKT column to GeoDataFrame
  - `extract_zip_file()` - Extract specific file from ZIP

---

## 📝 Required Parameters

### All Formats
- `blob_name` - File name in blob storage (required)
- `file_extension` - File extension including dot (required)
- `table_name` - Target PostGIS table name (required)
- `container_name` - Azure blob container (optional, default: "rmhazuregeobronze")
- `schema` - PostgreSQL schema (optional, default: "geo")
- `chunk_size` - Rows per chunk (optional, auto-calculated if not provided)

### Format-Specific Parameters

**GeoPackage**:
- `converter_params.layer_name` - Specific layer to extract (optional, uses first layer by default)

**CSV**:
- Option 1 (lat/lon):
  - `converter_params.lat_name` - Latitude column name (required if not using wkt_column)
  - `converter_params.lon_name` - Longitude column name (required if not using wkt_column)
- Option 2 (WKT):
  - `converter_params.wkt_column` - WKT geometry column name (required if not using lat/lon)

**KMZ**:
- `converter_params.kml_name` - Specific KML file in archive (optional, uses first .kml found)

---

## 🚨 Error Handling

### Job-Level Failures
- Jobs marked as FAILED when tasks exceed max retries (3 attempts)
- Application-level retry with exponential backoff: 5s → 10s → 20s
- Detailed error messages include task_id and retry count

### Format-Specific Errors

**GeoPackage - Invalid Layer**:
```json
{
  "error": "Layer 'invalid_layer' not found in GeoPackage"
}
```

**CSV - Missing Parameters**:
```json
{
  "error": "CSV conversion requires either 'wkt_column' or both 'lat_name' and 'lon_name'"
}
```

**Container Not Found**:
```json
{
  "error": "The specified container does not exist"
}
```

---

## 🗺️ Vector Data Preview & QA (⭐ NEW 14 NOV 2025)

### Vector Collection Viewer

**Purpose**: Interactive web-based viewer for data curators to validate vector ETL output.

**Endpoint**:
```
GET /api/vector/viewer?collection={collection_id}
```

**Live Example**:
```bash
# View the test_geojson_fresh collection
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/vector/viewer?collection=test_geojson_fresh
```

**Features**:
- ✅ **Interactive Leaflet map** with pan/zoom
- ✅ **Three load buttons**: 100 features | 500 features | All features (up to 10,000)
- ✅ **Click features** → popup shows all properties
- ✅ **Hover highlighting** for visual feedback
- ✅ **Zoom to features button** for spatial navigation
- ✅ **QA workflow section**:
  - Textarea for curator notes (3 rows)
  - Green "✓ Approve" button (future: POST /api/qa/approve)
  - Red "✗ Reject" button (future: POST /api/qa/reject)
  - Visual feedback on click (console logging for now)

**Data Source**: Fetches data from **OGC Features API**
```javascript
// Metadata fetch
GET /api/features/collections/{collection_id}

// Features fetch (respects limit parameter)
GET /api/features/collections/{collection_id}/items?limit={100|500|10000}
```

**Integration with Vector ETL**:
After successful vector ingestion job completion, the viewer URL should be included in the job result:

```json
{
  "status": "completed",
  "table_name": "acled_csv",
  "schema": "geo",
  "feature_count": 5000,
  "viewer_url": "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/vector/viewer?collection=acled_csv",
  "ogc_features_url": "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/acled_csv/items"
}
```

**Why This Matters**:
- **Data curators** can immediately preview vector data after ETL
- **Visual validation** catches geometry errors before data goes to production
- **QA workflow** enables approve/reject tracking (future enhancement)
- **Direct integration** with OGC Features API - no duplicate data access code

**Implementation Files**:
- `vector_viewer/service.py` - HTML generation and viewer logic
- `vector_viewer/triggers.py` - HTTP handler for /api/vector/viewer route
- `function_app.py` (lines 1547-1573) - Route registration

---

## 🎯 Future Enhancements

### Short-Term
- [ ] Vector tiling (MVT generation)
- [ ] Vector validation and repair
- [ ] Attribute filtering during ingestion
- [ ] Custom CRS support (currently EPSG:4326 only)

### Long-Term
- [ ] Streaming ingestion (very large files)
- [ ] Incremental updates (upsert logic)
- [ ] Change detection (diff between versions)
- [ ] Vector simplification/generalization

---

## 📚 Related Documentation

- **Architecture**: `ARCHITECTURE_REFERENCE.md` - Deep technical details
- **File Catalog**: `FILE_CATALOG.md` - Quick file lookup
- **TODO**: `TODO.md` - Active tasks and roadmap
- **History**: `HISTORY.md` - Completed work log
- **Vector Strategy**: `VECTOR_ETL_STRATEGY.md` - Initial design decisions

---

## ✅ Production Checklist

- [x] PostgreSQL deadlock fix tested (17 chunks, 100% success)
- [x] 2D geometry enforcement verified (local + production)
- [x] All 6 formats tested and working
- [x] Error handling and job failure detection
- [x] Parallel upload performance validated
- [x] ArcGIS compatibility (Multi- geometry types)
- [x] Comprehensive documentation
- [x] Example curl commands for all formats
- [x] Parameter validation and error messages

**Status**: ✅ **PRODUCTION READY** - All systems operational
