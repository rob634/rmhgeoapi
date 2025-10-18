# Active Tasks

**Last Updated**: 16 OCT 2025
**Author**: Robert and Geospatial Claude Legion

---

## 🎯 Current Focus

**System Status**: ✅ FULLY OPERATIONAL

**Recent Completions** (See HISTORY.md for details):
- ✅ Vector ETL GeoPackage Support (17 OCT 2025) - Optional layer_name, error validation
- ✅ Job Failure Detection (17 OCT 2025) - Auto-fail jobs when tasks exceed max retries
- ✅ Phase 2 ABC Migration (16 OCT 2025) - All 10 jobs migrated to JobBase
- ✅ Python Header Standardization (16 OCT 2025) - 27 core/infrastructure files reviewed
- ✅ Documentation Archive Organization (16 OCT 2025) - 22 files archived with searchable headers
- ✅ Raster ETL Pipeline (10 OCT 2025) - Production-ready with granular logging
- ✅ STAC Metadata Extraction (6 OCT 2025) - Managed identity, rio-stac integration
- ✅ Multi-stage orchestration with advisory locks - Zero deadlocks at any scale

**Current Focus**: Vector ETL format support (testing Shapefile, CSV, KML next)

---

## ⏭️ Next Up (Prioritized)

### 1. Multi-Tier COG Architecture 🌟 **HIGH VALUE**

**Business Case**: Clear upsell path from visualization → analysis → archive
- **Visualization Tier**: JPEG @ 85 quality (~17 MB, lossy, fast web maps)
- **Analysis Tier**: DEFLATE lossless (~50 MB, zero data loss, scientific analysis)
- **Archive Tier**: Minimal compression (~180 MB, long-term regulatory compliance)

**Pricing Model**:
- Budget: Visualization only ($0.19/month for 1000 rasters)
- Standard: Viz + Analysis ($0.79/month for 1000 rasters)
- Enterprise: All three tiers ($1.20/month for 1000 rasters)

**Implementation**:
```python
POST /api/jobs/submit/process_raster
{
  "blob_name": "input.tif",
  "output_tier": "visualization"  # or "analysis" or "both" or "all"
}
```

**Technical Work**:
- [ ] Add `output_tier` parameter to `process_raster` job
- [ ] Create separate COG profiles for each tier
- [ ] Update STAC records with tier information
- [ ] Add storage cost tracking per tier

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
- [ ] **Fix PostgreSQL deadlock on parallel uploads** ⚠️ HIGH PRIORITY
  - **Issue**: Multiple parallel tasks hit deadlock when creating table + inserting simultaneously
  - **Root Cause**: Concurrent DDL (CREATE TABLE IF NOT EXISTS) causes lock contention
  - **Solution**: Serialize table creation in Stage 1 aggregation, then parallel inserts in Stage 2
  - **Implementation Plan**:
    1. Modify `jobs/ingest_vector.py` → `aggregate_stage_results()` for Stage 1
    2. Create table ONCE after Stage 1 completes (using first chunk for schema)
    3. Split `services/vector/postgis_handler.py` methods:
       - `create_table_only()` - DDL only (Stage 1 aggregation)
       - `insert_features_only()` - DML only (Stage 2 parallel tasks)
    4. Update `upload_pickled_chunk()` to skip table creation
    5. Add `table_created: true` flag to Stage 1 results
  - **Files to modify**:
    - `jobs/ingest_vector.py` (aggregate_stage_results)
    - `services/vector/postgis_handler.py` (split create/insert logic)
    - `services/vector/tasks.py` (upload_pickled_chunk)
  - **Testing**: Re-test kba_shp.zip (currently deadlocks with >2 chunks)
- [ ] **Additional format support** - Next up
  - ✅ Shapefile processing (ZIP format) - Works with geometry normalization
  - [ ] CSV with geometry columns
  - [ ] KML/KMZ support
- [ ] Vector tiling (MVT generation)
- [ ] Vector validation and repair
- [ ] **Advanced Shapefile Support** ⚠️ FUTURE (Avoid for now!)
  - [ ] Read shapefile as group of files (.shp, .shx, .dbf, .prj, etc.)
  - [ ] Auto-detect related files in same blob prefix
  - [ ] Handle multi-file upload workflows
  - **Note**: This is a hot mess - stick with ZIP format for production use

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
