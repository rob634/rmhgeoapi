# Active Tasks

**Last Updated**: 16 OCT 2025
**Author**: Robert and Geospatial Claude Legion

---

## 🎯 Current Focus

**System Status**: ✅ FULLY OPERATIONAL

**Recent Completions** (See HISTORY.md for details):
- ✅ Phase 2 ABC Migration (16 OCT 2025) - All 10 jobs migrated to JobBase
- ✅ Python Header Standardization (16 OCT 2025) - 27 core/infrastructure files reviewed
- ✅ Documentation Archive Organization (16 OCT 2025) - 22 files archived with searchable headers
- ✅ Raster ETL Pipeline (10 OCT 2025) - Production-ready with granular logging
- ✅ STAC Metadata Extraction (6 OCT 2025) - Managed identity, rio-stac integration
- ✅ Multi-stage orchestration with advisory locks - Zero deadlocks at any scale

**Current Focus**: Ready for next feature development

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

### 3. Advanced Workflow Patterns ✅ PARTIALLY COMPLETE

**Implemented (16 OCT 2025)**:
- ✅ **Diamond Pattern**: Fan-out → Process → Fan-in → Aggregate
  - CoreMachine auto-creates aggregation tasks for `"parallelism": "fan_in"` stages
  - Complete documentation in ARCHITECTURE_REFERENCE.md
  - Ready for production use

- ✅ **Dynamic Stage Creation**: Stage 1 results determine Stage 2 tasks
  - Fully supported via `"parallelism": "fan_out"` pattern
  - Previous stage results passed to `create_tasks_for_stage()`

**Still To Implement**:
- **Task-to-Task Communication**: Direct lineage between predecessor/successor
- **Cross-Stage Data Dependencies**: Pass large data between stages via blob storage

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

### Vector ETL Pipeline
- [ ] GeoJSON → PostGIS ingestion
- [ ] Shapefile processing
- [ ] Vector tiling (MVT generation)
- [ ] Vector validation and repair

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
