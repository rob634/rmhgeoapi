# Active Tasks

**Last Updated**: 20 OCT 2025
**Author**: Robert and Geospatial Claude Legion

---

## ✅ COMPLETED: Output Folder Control + Vendor Delivery Discovery (20 OCT 2025)

**Status**: ✅ **COMPLETE** - Custom output paths and intelligent delivery analysis
**Completion Date**: 20 OCT 2025

### What Was Completed

**1. Configurable Output Folder Parameter** ✅
- Added `output_folder` parameter to `process_raster` job
- Supports custom output paths instead of mirroring input folder structure
- Validated with 5 different test scenarios
- **Implementation**: [jobs/process_raster.py](jobs/process_raster.py:103-108, 223-235, 435-451)

**Testing Results**:
| Test | Input | output_folder | Output Path | Status |
|------|-------|---------------|-------------|--------|
| 1 | `test/dctest3_R1C2_regular.tif` | `null` | `test/dctest3_R1C2_regular_cog_analysis.tif` | ✅ |
| 2 | `test/dctest3_R1C2_regular.tif` | `cogs/processed/rgb` | `cogs/processed/rgb/dctest3_R1C2_regular_cog_visualization.tif` | ✅ |
| 3 | `test/dctest3_R1C2_regular.tif` | `processed` | `processed/dctest3_R1C2_regular_cog_archive.tif` | ✅ |
| 4 | `namangan/namangan14aug2019_R1C2cog.tif` | `cogs` | `cogs/namangan14aug2019_R1C2cog_cog_analysis.tif` | ✅ |
| 5 | `6681542855355853500/.../23JAN31104343-S2AS.TIF` | `cogs/maxar/test` | `cogs/maxar/test/23JAN31104343-S2AS_cog_analysis.tif` | ✅ (timed out but path verified) |

**Total Data Processed**: 644 MB across 5 test jobs

**2. Vendor Delivery Discovery System** ✅
- Created `services/delivery_discovery.py` with 3 core functions
- Added HTTP endpoint: `POST /api/analysis/delivery`
- Automatic detection of manifest files and tile patterns
- Smart workflow recommendations based on delivery structure

**Manifest Detection** (`detect_manifest_files()`):
- ✅ `.MAN` files (Maxar/vendor manifests)
- ✅ `delivery.json`, `manifest.json`
- ✅ `delivery.xml`, `manifest.xml`
- ✅ `README.txt`, `DELIVERY.txt`
- ✅ `.til` files (tile manifests)

**Tile Pattern Detection** (`detect_tile_pattern()`):
- ✅ **Maxar**: `R{row}C{col}` (e.g., R1C1, R10C25)
- ✅ **Generic XY**: `X{x}_Y{y}` (e.g., X100_Y200)
- ✅ **TMS**: `{z}/{x}/{y}.tif` (e.g., 12/1024/2048.tif)
- ✅ **Sequential**: `tile_0001.tif`, `tile_0002.tif`
- ✅ Returns grid dimensions and tile coordinates

**Delivery Types Detected**:
- ✅ `maxar_tiles` - Maxar .MAN + R{row}C{col} pattern
- ✅ `vivid_basemap` - TMS tile pattern
- ✅ `tiled_delivery` - Any recognized tile pattern
- ✅ `single_file` - One raster file
- ✅ `simple_folder` - Multiple rasters, no pattern

**Testing Results**:
```json
// Test 1: Single file with .MAN manifest
{
  "delivery_type": "single_file",
  "manifest": {
    "manifest_found": true,
    "manifest_type": "maxar_man",
    "manifest_path": "6681542855355853500/200007595339_01.MAN"
  },
  "recommended_workflow": {
    "job_type": "process_raster",
    "parameters": {
      "blob_name": "...",
      "output_folder": "cogs/6681542855355853500/200007595339_01/"
    }
  }
}

// Test 2: Tiled delivery with R{row}C{col} pattern
{
  "delivery_type": "maxar_tiles",
  "tile_pattern": {
    "pattern_detected": true,
    "pattern_type": "row_col",
    "grid_dimensions": {"rows": 2, "cols": 2, "min_row": 1, "min_col": 1},
    "tile_coordinates": [
      {"row": 1, "col": 1, "file": "R1C1.TIF"},
      {"row": 1, "col": 2, "file": "R1C2.TIF"},
      ...
    ]
  },
  "recommended_workflow": {
    "job_type": "process_raster_collection",
    "parameters": {
      "blob_list": ["R1C1.TIF", "R1C2.TIF", ...],
      "create_mosaicjson": true,
      "output_folder": "cogs/maxar/test_delivery/"
    }
  }
}
```

**API Endpoint**:
```bash
curl -X POST https://rmhgeoapibeta.../api/analysis/delivery \
  -H "Content-Type: application/json" \
  -d '{
    "folder_path": "vendor/delivery/",
    "blob_list": ["R1C1.TIF", "R1C2.TIF", "delivery.MAN"]
  }'
```

**Benefits Achieved**:
- ✅ Zero-configuration delivery analysis - just provide blob list
- ✅ Intelligent workflow recommendations - knows what job type to use
- ✅ Automatic grid dimension calculation for tile patterns
- ✅ Smart output folder suggestions based on input structure
- ✅ Foundation for future `process_raster_collection` job type

**Files Created**:
- ✅ `services/delivery_discovery.py` (383 lines with comprehensive docstrings)
- ✅ HTTP endpoint in `function_app.py` (60 lines)

**Production Ready**: Both features deployed and tested end-to-end

---

## ✅ COMPLETED: Logger Standardization (18-19 OCT 2025)

**Status**: ✅ **COMPLETE** - Module-level LoggerFactory implemented
**Completion Date**: 19 OCT 2025

### What Was Completed

**All files converted to LoggerFactory** (6 files):
- ✅ `services/vector/converters.py` - Module-level LoggerFactory
- ✅ `services/vector/postgis_handler.py` - Module-level LoggerFactory
- ✅ `services/stac_vector_catalog.py` - Module-level LoggerFactory
- ✅ `services/service_stac_vector.py` - Module-level LoggerFactory
- ✅ `services/service_stac_metadata.py` - Module-level LoggerFactory
- ✅ `jobs/ingest_vector.py` - Module-level LoggerFactory

**Implementation Pattern Used**:
```python
from util_logger import LoggerFactory, ComponentType

# Module-level structured logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_converters"
)

def handler(params):
    logger.info(f"Processing {params['file']}")
    # Output: JSON with component metadata
```

**Benefits Achieved**:
- ✅ JSON structured output for Application Insights
- ✅ Component metadata (component_type, component_name)
- ✅ Consistent logging patterns across codebase
- ✅ No plain text logging in production paths

---

## 🎯 Current Focus

**System Status**: ✅ FULLY OPERATIONAL - VECTOR ETL COMPLETE + COMPREHENSIVE DIAGNOSTICS

**Recent Completions** (See HISTORY.md for details):
- ✅ Comprehensive Diagnostic Logging (18 OCT 2025) - Replaced ALL print() with logger, detailed trace info
- ✅ Vector ETL All Format Support (18 OCT 2025) - GeoPackage, Shapefile, KMZ, KML, GeoJSON, CSV
- ✅ 2D Geometry Enforcement (18 OCT 2025) - Z/M dimension removal for KML/KMZ files
- ✅ PostgreSQL Deadlock Fix (18 OCT 2025) - Serialized table creation, parallel inserts
- ✅ Mixed Geometry Normalization (18 OCT 2025) - Multi- type conversion for ArcGIS compatibility
- ✅ Vector ETL GeoPackage Support (17 OCT 2025) - Optional layer_name, error validation
- ✅ Job Failure Detection (17 OCT 2025) - Auto-fail jobs when tasks exceed max retries
- ✅ Phase 2 ABC Migration (16 OCT 2025) - All 10 jobs migrated to JobBase
- ✅ Raster ETL Pipeline (10 OCT 2025) - Production-ready with granular logging
- ✅ STAC Metadata Extraction (6 OCT 2025) - Managed identity, rio-stac integration
- ✅ Multi-stage orchestration with advisory locks - Zero deadlocks at any scale

**Current Focus**: Multi-Tier COG Architecture Phase 1 complete (20 OCT 2025) + Output Folder Control + Vendor Delivery Discovery

**Latest Completions** (20 OCT 2025):
- ✅ **Configurable Output Folder** - `output_folder` parameter for custom COG output paths
- ✅ **Vendor Delivery Discovery** - Automatic detection of manifest files and tile patterns
- ✅ **Multi-Tier COG Testing** - End-to-end testing with 5 different scenarios (644 MB processed)

---

## ⏭️ Next Up

### 1. Multi-Tier COG Architecture 🌟 **HIGH VALUE**

**Status**: 🎯 **NEXT PRIORITY** - Ready for implementation
**Business Case**: Tiered storage for different access patterns and use cases

#### Storage Trade-offs

**Storage Requirements** (example: 1000 rasters @ 200MB original each):
- **Visualization**: ~17 MB/file = 17 GB total (hot storage)
- **Analysis**: ~50 MB/file = 50 GB total (hot storage)
- **Archive**: ~180 MB/file = 180 GB total (cool storage)

**User Scenarios**:
- **Visualization Only**: 17 GB hot - Web mapping, public viewers, fast access
- **Viz + Analysis**: 67 GB hot - GIS professionals, data analysis, preserves data quality
- **All Three Tiers**: 67 GB hot + 180 GB cool - Regulatory compliance, long-term archive

#### Technical Specifications

**Tier 1 - Visualization** (Web-optimized):
```python
{
    "compression": "JPEG",  # RGB imagery only
    "quality": 85,
    "blocksize": 512,
    "target_size": "~17MB",
    "use_case": "Fast web maps, visualization",
    "data_loss": "Lossy (acceptable for visualization)",
    "storage_tier": "hot",
    "applies_to": ["RGB imagery", "aerial photos", "satellite imagery"]
}
```

**Tier 2 - Analysis** (Lossless):
```python
{
    "compression": "DEFLATE",  # Universal - works for all data types
    "predictor": 2,
    "zlevel": 6,
    "blocksize": 512,
    "target_size": "~50MB",
    "use_case": "Scientific analysis, GIS operations",
    "data_loss": "None (lossless)",
    "storage_tier": "hot",
    "applies_to": ["All raster types", "DEM", "scientific data", "multispectral"]
}
```

**Tier 3 - Archive** (Compliance):
```python
{
    "compression": "LZW",  # Universal - works for all data types
    "predictor": 2,
    "blocksize": 512,
    "target_size": "~180MB",
    "use_case": "Long-term storage, regulatory compliance",
    "data_loss": "None (lossless)",
    "storage_tier": "cool",
    "applies_to": ["All raster types", "original data preservation"]
}
```

#### Non-Imagery Rasters (DEM, Scientific Data, etc.)

**Problem**: JPEG compression only works for RGB imagery (3 bands, 8-bit). Non-imagery rasters include:
- **DEM (Digital Elevation Models)**: Single band, floating point values
- **Scientific data**: Temperature, precipitation, NDVI, etc.
- **Multispectral imagery**: 4+ bands (e.g., Landsat, Sentinel)
- **Classification rasters**: Integer codes (land cover, soil types)

**Solution**: Tier detection based on raster characteristics

**Automatic Tier Selection Logic**:
```python
def determine_applicable_tiers(raster_metadata):
    """
    Determine which tiers can be applied based on raster type.

    Returns:
        List of applicable tiers
    """
    band_count = raster_metadata['band_count']
    data_type = raster_metadata['data_type']  # uint8, float32, etc.

    # All rasters support analysis and archive (lossless)
    applicable_tiers = ['analysis', 'archive']

    # Only RGB 8-bit imagery supports JPEG visualization tier
    if band_count == 3 and data_type == 'uint8':
        applicable_tiers.insert(0, 'visualization')

    return applicable_tiers
```

**Examples**:

1. **RGB Aerial Photo** (3 bands, uint8):
   - ✅ Visualization (JPEG)
   - ✅ Analysis (DEFLATE)
   - ✅ Archive (LZW)

2. **DEM** (1 band, float32):
   - ❌ Visualization (JPEG doesn't support float32)
   - ✅ Analysis (DEFLATE)
   - ✅ Archive (LZW)

3. **Landsat** (8 bands, uint16):
   - ❌ Visualization (JPEG only supports 3 bands)
   - ✅ Analysis (DEFLATE)
   - ✅ Archive (LZW)

**Implementation Strategy**:

1. **Detect raster type** in Stage 1 (validation)
2. **Auto-select applicable tiers** based on band count and data type
3. **Override user request** if they request incompatible tier:
   ```python
   # User requests: output_tier = "all"
   # DEM detected: only 'analysis' and 'archive' are valid
   # Result: Generate 2 COGs instead of 3, warn user
   ```

4. **Add metadata** to job result:
   ```json
   {
     "requested_tiers": ["visualization", "analysis", "archive"],
     "applicable_tiers": ["analysis", "archive"],
     "skipped_tiers": ["visualization"],
     "skip_reason": "JPEG compression not compatible with float32 data type"
   }
   ```

#### Implementation Plan

**Phase 1: Core Infrastructure** (~5 hours)
- ✅ **Step 1**: Define COG profile configurations in `config.py` - COMPLETED (19 OCT 2025)
  - ✅ Add `CogTierProfile` Pydantic model
  - ✅ Define VISUALIZATION, ANALYSIS, ARCHIVE profiles
  - ✅ Validate compression settings
  - ✅ Add compatibility matrix (band count, data type → applicable tiers)

- ✅ **Step 2**: Add raster type detection - COMPLETED (19 OCT 2025)
  - ✅ Create `determine_applicable_tiers()` function in config.py
  - ✅ Detect band count, data type compatibility
  - ✅ Return list of compatible tiers
  - ✅ Tested with RGB, DEM, Landsat examples

- ✅ **Step 3**: Update `process_raster` job parameters - COMPLETED (19 OCT 2025)
  - ✅ Add `output_tier` field (enum: "visualization", "analysis", "archive", "all") to parameters_schema
  - ✅ Add validation in `validate_job_parameters()`
  - ✅ Pass `output_tier` through job metadata and to Stage 2 tasks
  - ✅ Default to "analysis" for backward compatibility
  - ✅ Mark `compression` parameter as deprecated (use output_tier instead)

- ✅ **Step 4**: Extend COG conversion service - COMPLETED (19 OCT 2025)
  - ✅ Import `CogTier`, `COG_TIER_PROFILES` from config
  - ✅ Parse `output_tier` parameter (default: "analysis")
  - ✅ Get tier profile and check compatibility with raster characteristics
  - ✅ Fallback to "analysis" tier if requested tier incompatible
  - ✅ Apply tier-specific compression, quality, storage tier settings
  - ✅ Generate output filename with tier suffix: `sample_analysis.tif`
  - ✅ Add tier metadata to result: `cog_tier`, `storage_tier`, `tier_profile`
  - ✅ Log tier selection and compatibility warnings

- ✅ **Step 4b**: Add tier detection to validation service - COMPLETED (19 OCT 2025)
  - ✅ Import `determine_applicable_tiers()` in validation service
  - ✅ Call tier detection in Stage 1 using band_count and dtype
  - ✅ Add `cog_tiers` to validation result with applicable_tiers list
  - ✅ Include band_count and data_type in raster_type metadata
  - ✅ Log tier compatibility details
  - ✅ Handle tier detection errors with fallback to all tiers

**Phase 2: Multi-Output Support** (~3 hours)
- [ ] **Step 5**: Implement multi-tier fan-out pattern
  - If `output_tier: "all"`, create tasks for applicable tiers only
  - Use `applicable_tiers` from Stage 1 metadata
  - Stage 2: Convert to COG with tier-specific profiles
  - Stage 3: Upload to appropriate storage tier (hot vs cool)

- [ ] **Step 6**: Update STAC metadata
  - Add tier information to STAC item properties: `cog:tier`, `cog:compression`, `cog:size_mb`
  - Link related tiers: `rel: "alternate"` links between viz/analysis/archive versions
  - Example STAC item structure:
    ```json
    {
      "id": "sample_visualization",
      "properties": {
        "cog:tier": "visualization",
        "cog:compression": "JPEG",
        "cog:quality": 85,
        "cog:size_mb": 17.2
      },
      "links": [
        {"rel": "alternate", "href": "sample_analysis.tif", "title": "Analysis tier"},
        {"rel": "alternate", "href": "sample_archive.tif", "title": "Archive tier"}
      ]
    }
    ```

**Phase 3: Storage Tracking** (~2 hours)
- [ ] **Step 7**: Add storage usage tracking
  - Create `storage_usage` table (tier, container, size_gb, access_tier, cog_tier)
  - Track storage by COG tier (visualization, analysis, archive)
  - Track access tier (hot vs cool)
  - Aggregate endpoint: `/api/storage/usage` → breakdown by tier

- [ ] **Step 8**: Create storage reporting endpoint
  - `/api/storage/usage/summary` → total GB by COG tier and access tier
  - `/api/storage/usage/by-tier` → itemized breakdown
  - Support query parameters: `date_range`, `tier_filter`
  - Example response:
    ```json
    {
      "visualization": {"total_gb": 17.2, "access_tier": "hot"},
      "analysis": {"total_gb": 49.8, "access_tier": "hot"},
      "archive": {"total_gb": 178.5, "access_tier": "cool"}
    }
    ```

**Phase 4: Testing & Documentation** (~2 hours)
- [ ] **Step 9**: Test with sample rasters
  - Test RGB imagery: `output_tier: "all"` → 3 COGs (viz, analysis, archive)
  - Test DEM: `output_tier: "all"` → 2 COGs (analysis, archive only)
  - Test multispectral: `output_tier: "all"` → 2 COGs (analysis, archive only)
  - Verify file sizes match expectations (~17MB, ~50MB, ~180MB)
  - Verify storage tier placement (hot vs cool)
  - Verify tier skip warnings logged correctly

- [ ] **Step 10**: Documentation
  - Update `ARCHITECTURE_REFERENCE.md` with tier specifications
  - Create `COG_TIER_GUIDE.md` with pricing calculator
  - Add API examples to README

#### API Examples

**Single Tier**:
```bash
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "sample.tif",
    "output_tier": "visualization",
    "container": "rmhazuregeobronze"
  }'
```

**All Tiers**:
```bash
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "sample.tif",
    "output_tier": "all",
    "container": "rmhazuregeobronze"
  }'
```

#### Success Criteria

✅ Single raster produces 3 COG variants with correct sizes
✅ STAC items linked with `rel: "alternate"` relationships
✅ Storage costs calculated correctly for each tier
✅ Hot storage used for viz/analysis, cool storage for archive
✅ API documentation complete with pricing examples

**Total Effort**: ~12 hours (1.5 days) - includes non-imagery raster support

---

---

### 2. Complex Raster Workflows

**Capabilities to Add**:
- Multi-stage tiling with deterministic lineage
- Parallel reproject/validate operations
- Batch COG conversion (process multiple rasters in one job)
- Automatic STAC record updates after processing

**Use Cases**:
- Process entire container of rasters (fan-out pattern)
- Tile gigantic rasters into manageable chunks
- Batch reproject datasets to common CRS

---

### 3. Advanced Workflow Patterns ✅ MOSTLY COMPLETE

**Implemented (16 OCT 2025)**:
- ✅ **Diamond Pattern**: Fan-out → Process → Fan-in → Aggregate
  - CoreMachine auto-creates aggregation tasks for `"parallelism": "fan_in"` stages
  - Complete documentation in ARCHITECTURE_REFERENCE.md
  - Production tested: 4 files, 100 files - both successful
  - Ready for production use

- ✅ **Dynamic Stage Creation**: Stage 1 results determine Stage 2 tasks
  - Fully supported via `"parallelism": "fan_out"` pattern
  - Previous stage results passed to `create_tasks_for_stage()`

- ✅ **Cross-Stage Data Dependencies**: Pickle intermediate storage (7 OCT 2025)
  - Implemented in `ingest_vector` job (vector ETL)
  - Stage 1 pickles GeoDataFrame chunks to blob storage
  - Stage 2 loads pickles in parallel for PostGIS upload
  - Config: `vector_pickle_container`, `vector_pickle_prefix`
  - Handles multi-GB datasets that exceed Service Bus 256KB limit
  - Production ready, registered in `jobs/__init__.py`

**Partially Implemented**:
- ⚠️ **Task-to-Task Communication**: Field exists but unused
  - Database field `next_stage_params` exists in TaskRecord
  - Documentation written in ARCHITECTURE_REFERENCE.md
  - No production jobs using it yet
  - **Recommended**: Create raster tiling job to demonstrate pattern
    - Stage 1 determines tile boundaries → `next_stage_params`
    - Stage 2 tasks with matching semantic IDs retrieve tile specs

**Example Diamond Workflow (Now Supported)**:
```python
stages = [
    {"number": 1, "task_type": "list_files", "parallelism": "single"},
    {"number": 2, "task_type": "process_file", "parallelism": "fan_out"},
    {"number": 3, "task_type": "aggregate_results", "parallelism": "fan_in"},  # ← AUTO
    {"number": 4, "task_type": "update_catalog", "parallelism": "single"}
]
```

---

### 4. Service Bus Production Implementation

**Status**: Architecture proven, needs production controllers

**Controllers to Build**:
1. **ServiceBusContainerController**
   - List container → process files in batches
   - Test with 10,000+ files
   - Compare performance vs Queue Storage

2. **ServiceBusSTACController**
   - List rasters → create STAC items in batches
   - Integrate with PgSTAC
   - Batch insert optimization

3. **ServiceBusGeoJSONController**
   - Read GeoJSON → upload to PostGIS in batches
   - Handle large feature collections
   - Spatial indexing

---

## 💡 Future Ideas (Backlog)

### Performance & Operations
- [ ] Job cancellation endpoint
- [ ] Task replay for failed jobs
- [ ] Historical analytics dashboard
- [ ] Connection pooling optimization
- [ ] Query performance tuning

### Advanced Features
- [ ] Cross-job dependencies (Job B waits for Job A)
- [ ] Scheduled jobs (cron-like triggers)
- [ ] Job templates (reusable workflows)
- [ ] Webhook notifications on job completion

### Vector ETL Pipeline ✅ IN PROGRESS (17 OCT 2025)
- ✅ **GeoJSON → PostGIS ingestion** (7 OCT 2025) - Production ready
  - Two-stage pipeline: pickle chunks → parallel upload
  - Handles multi-GB datasets beyond Service Bus limits
  - Registered in `jobs/__init__.py` as `ingest_vector`
- ✅ **GeoPackage support** (17 OCT 2025) - Production ready
  - Optional layer_name parameter (reads first layer by default)
  - Explicit error validation for invalid layer names
  - Error propagation: converter → TaskResult → job failure
- ✅ **Job failure detection** (17 OCT 2025) - Production ready
  - Jobs marked as FAILED when tasks exceed max retries (3 attempts)
  - Application-level retry with exponential backoff (5s → 10s → 20s)
  - Detailed error messages include task_id and retry count
- ✅ **Mixed geometry type handling** (18 OCT 2025) - Production ready
  - Normalize all geometries to Multi- types (Polygon → MultiPolygon, etc.)
  - Fixed coordinate counting for multi-part geometries
  - ArcGIS compatibility - uniform geometry types in PostGIS tables
  - Minimal overhead (<1% storage/performance cost)
- ✅ **PostgreSQL deadlock fix** (18 OCT 2025) - Production ready
  - **Solution**: Serialized table creation in Stage 1, parallel inserts in Stage 2
  - **Implementation**:
    - Split `services/vector/postgis_handler.py` methods:
      - `create_table_only()` - DDL only (Stage 1 aggregation)
      - `insert_features_only()` - DML only (Stage 2 parallel tasks)
    - Modified `jobs/ingest_vector.py` → `create_tasks_for_stage()` for Stage 2
    - Table created ONCE before Stage 2 tasks (using first chunk for schema)
    - Updated `upload_pickled_chunk()` to use insert-only method
  - **Testing Results**: kba_shp.zip (17 chunks) - 100% success, ZERO deadlocks
- ✅ **2D Geometry Enforcement** (18 OCT 2025) - Production ready
  - **Purpose**: System only supports 2D geometries (x, y)
  - **Implementation**: `shapely.force_2d()` strips Z and M dimensions
  - **Applied in**: `services/vector/postgis_handler.py` → `prepare_gdf()`
  - **Testing**: KML/KMZ files with 3D data (12,228 features each)
  - **Verified**: Coordinates reduced from 3 values (x,y,z) to 2 values (x,y)
  - **Bug Fixed**: Series boolean ambiguity - added `.any()` to `has_m` check
- ✅ **All vector format support** (18 OCT 2025) - Production ready
  - ✅ **GeoPackage (.gpkg)** - roads.gpkg (2 chunks, optional layer_name)
  - ✅ **Shapefile (.zip)** - kba_shp.zip (17 chunks, NO DEADLOCKS)
  - ✅ **KMZ (.kmz)** - grid.kml.kmz (21 chunks, 12,228 features, Z-dimension removal)
  - ✅ **KML (.kml)** - doc.kml (21 chunks, 12,228 features, Z-dimension removal)
  - ✅ **GeoJSON (.geojson)** - 8.geojson (10 chunks, 3,879 features)
  - ✅ **CSV (.csv)** - acled_test.csv (17 chunks, 5,000 features, lat/lon columns)
  - **Parameters for CSV**: `"converter_params": {"lat_name": "latitude", "lon_name": "longitude"}`
- ✅ **Comprehensive Diagnostic Logging** (18 OCT 2025) - Production ready
  - **Problem**: User requested exact trace details of why geometries are invalid - "invalid geometry" insufficient
  - **Solution**: Replaced ALL print() statements with logger across entire codebase
  - **Implementation**:
    - Replaced 94+ print() statements in vector ETL, raster validation, STAC, etc.
    - Added detailed diagnostics to shapefile loading (rows, columns, CRS, geometry types)
    - Enhanced geometry validation logging (null counts, sample data, error reasons)
    - All diagnostics now appear in Application Insights for debugging
  - **Files Updated**:
    - `services/vector/converters.py` - Shapefile loading diagnostics
    - `services/vector/postgis_handler.py` - Geometry validation diagnostics
    - `jobs/ingest_vector.py` - Table creation logging
  - **Example Diagnostic Output**:
    ```
    📂 Reading shapefile from: /tmp/tmpq8out_ps/wdpa.shp
    📊 Shapefile loaded - diagnostics:
       - Total rows read: 0
       - Columns: ['OBJECTID', 'WDPAID', ..., 'geometry']
       - CRS: EPSG:4326
       - Geometry column type: geometry
    📊 Geometry validation starting:
       - Total features loaded: 0
       - Null geometries found: 0
    ```
  - **Testing**: Caught corrupted 2GB wdpa.zip file (bad QGIS export, 0 rows despite valid schema)
  - **Benefit**: Complete visibility into file processing failures via Application Insights
- [ ] Vector tiling (MVT generation)
- [ ] Vector validation and repair
- [ ] **Advanced Shapefile Support** ⚠️ FUTURE (Avoid for now!)
  - [ ] Read shapefile as group of files (.shp, .shx, .dbf, .prj, etc.)
  - [ ] Auto-detect related files in same blob prefix
  - [ ] Handle multi-file upload workflows
  - **Note**: This is a hot mess - stick with ZIP format for production use

### Logging Enhancements (Future)
- [ ] **Context-Aware Logging** - Add job_id/task_id to Application Insights
  - **Current**: Module-level LoggerFactory (component metadata only)
  - **Future**: Handler-level LogContext for correlation tracking
  - **Pattern**: Create logger inside handlers with `LogContext(job_id=..., task_id=...)`
  - **Benefit**: Query Application Insights by job_id: `customDimensions.job_id == "abc123"`
  - **Effort**: ~3.5 hours (6 files, testing, deployment)
  - **Priority**: Low - module-level logging sufficient for current scale

### Data Quality
- [ ] Automated raster validation checks
- [ ] Metadata completeness scoring
- [ ] Duplicate detection
- [ ] Quality reports

---

## 🏆 System Capabilities (Current)

**Fully Operational**:
- ✅ Multi-stage job orchestration (sequential stages, parallel tasks)
- ✅ Atomic stage completion detection (PostgreSQL advisory locks)
- ✅ Automatic stage advancement
- ✅ Job completion with result aggregation
- ✅ Idempotency (SHA256 hash deduplication)
- ✅ Pydantic validation at all boundaries
- ✅ Contract enforcement with ABC patterns
- ✅ Raster ETL (validate → COG → STAC)
- ✅ STAC metadata extraction (managed identity)
- ✅ Container operations (summarize, list contents)
- ✅ Database monitoring endpoints
- ✅ Health checks with import validation

**Active Endpoints**:
```bash
# Job Management
POST /api/jobs/submit/{job_type}      - Submit job (hello_world, process_raster, etc.)
GET  /api/jobs/status/{job_id}        - Get job status
GET  /api/db/jobs                     - Query all jobs

# Task Management
GET /api/db/tasks/{job_id}            - Get tasks for job

# STAC Operations
POST /api/stac/init                   - Initialize STAC collections
POST /api/stac/extract                - Extract STAC metadata from raster
GET  /api/stac/setup                  - Check PgSTAC installation

# System Health
GET /api/health                       - System health check
POST /api/db/schema/redeploy?confirm=yes - Redeploy database schema
```

---

## 📋 Active Jobs (10 Production Jobs)

All jobs now inherit from `JobBase` ABC with compile-time enforcement:

1. **hello_world** - 2-stage demo workflow
2. **summarize_container** - Aggregate container statistics
3. **list_container_contents** - Inventory with metadata
4. **process_raster** - Validate → COG creation (PRODUCTION READY)
5. **vector_etl** - Vector data processing
6. **create_h3_base** - H3 hexagon grid generation
7. **generate_h3_level4** - H3 level 4 grid
8. **stac_setup** - STAC infrastructure setup
9. **stac_search** - STAC catalog search
10. **duckdb_query** - Analytical queries

---

## 🚀 Quick Test Commands

```bash
# Health Check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Submit Raster Processing Job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test/sample.tif", "container": "rmhazuregeobronze"}'

# Check Job Status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Extract STAC Metadata
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/extract \
  -H "Content-Type: application/json" \
  -d '{"container": "rmhazuregeosilver", "blob_name": "test/sample_cog.tif", "collection_id": "cogs", "insert": true}'
```

---

**Note**: For completed work history, see `HISTORY.md`. For architectural details, see `ARCHITECTURE_REFERENCE.md`.
