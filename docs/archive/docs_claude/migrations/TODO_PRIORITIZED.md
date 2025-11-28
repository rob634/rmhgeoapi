# Prioritized Roadmap

**Last Updated**: 18 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Vector ETL Complete - Ready for Next Phase

---

## 🎯 IMMEDIATE PRIORITIES (Time-Sensitive)

### **Priority 0A: STAC Completion for All ETL Processes** ⏰ CRITICAL
**Timeline**: Before Multi-Tier COG (infrastructure requirement)
**Business Value**: Complete audit trail, searchable catalog of all processed assets
**Handoff Ready**: Required for production readiness

**Problem**:
- Vector ETL completes but doesn't create STAC records
- Raster ETL creates STAC but needs consistent pattern
- No unified catalog of what's been processed

**Goal**: Every ETL job ends with STAC record creation

**Implementation Checklist**:

#### **A. Vector STAC Integration**
- [ ] Add Stage 3 to `ingest_vector` job: "create_stac_record"
- [ ] Create/enhance `services/stac_vector_catalog.py` handler
- [ ] Extract vector metadata from PostGIS:
  - Bounding box (ST_Extent)
  - Feature count
  - Geometry types
  - CRS (should always be EPSG:4326)
  - Table name and schema
- [ ] Create STAC Item with vector-specific properties
- [ ] Insert into PgSTAC `vectors` collection
- [ ] Test with all 6 vector formats

#### **B. Raster STAC Enhancement**
- [ ] Ensure `process_raster` Stage 3 creates STAC record
- [ ] Add tier information when multi-tier implemented
- [ ] Consistent asset naming (visualization/analysis/archive)
- [ ] Link original raster + all COG tiers in single STAC item

#### **C. STAC Collections Setup**
- [ ] Create `vectors` collection (if not exists)
- [ ] Create `rasters` collection (if not exists)
- [ ] Create `cogs` collection for processed rasters
- [ ] Define collection metadata (description, extent, license)

---

### **Priority 0B: Timer-Triggered Cleanup Function** ⏰ CRITICAL
**Timeline**: Before Multi-Tier COG (operational requirement)
**Business Value**: System self-heals, no manual intervention needed
**Handoff Ready**: Essential for production stability

**Problem**:
- Jobs stuck in "processing" forever (task died but job not marked failed)
- Jobs stuck in "queued" (never picked up by processor)
- Failed tasks don't always propagate to job failure
- No automated cleanup of zombie jobs

**Goal**: Timer function (every 5-10 minutes) detects and fixes stuck jobs

**Implementation Checklist**:

#### **A. Create Timer Trigger**
- [ ] New file: `triggers/trigger_cleanup_stuck_jobs.py`
- [ ] Timer schedule: `0 */5 * * * *` (every 5 minutes)
- [ ] Query database for problematic jobs/tasks

#### **B. Detection Logic**
Define "stuck" conditions:
- [ ] **Stuck Job**: Status = "processing" AND `updated_at` > 30 minutes ago
- [ ] **Stuck Task**: Status = "processing" AND `heartbeat` > 15 minutes ago
- [ ] **Zombie Task**: Status = "queued" AND `created_at` > 1 hour ago
- [ ] **Orphaned Task**: Task completed but job still "processing"

#### **C. Cleanup Actions**
- [ ] **Stuck Jobs**: Mark as FAILED with reason "Job timeout - no progress"
- [ ] **Stuck Tasks**: Mark task as FAILED → check stage completion
- [ ] **Zombie Tasks**: Mark as FAILED → trigger job failure detection
- [ ] **Orphaned Tasks**: Call stage completion logic

#### **D. Logging & Monitoring**
- [ ] Log every cleanup action
- [ ] Track cleanup metrics
- [ ] Alert if cleanup rate is high
- [ ] Application Insights custom metrics

#### **E. Safety Measures**
- [ ] Dry-run mode for testing
- [ ] Limit cleanup batch size (max 50 per run)
- [ ] Skip recently created jobs (5-minute grace period)
- [ ] Add `cleaned_up_at` timestamp

---

### **Priority 1: Multi-Tier COG Architecture** ⏰ URGENT
**Timeline**: After STAC + Cleanup complete
**Business Value**: Enables tiered pricing model (Budget/Standard/Enterprise)
**Handoff Ready**: Yes - clear patterns, familiar ETL concepts

**Overview**:
- Create 3 COG compression tiers for different use cases
- **Visualization**: JPEG 85% (~17 MB) - Fast web maps, lossy acceptable
- **Analysis**: DEFLATE lossless (~50 MB) - Scientific workflows, zero data loss
- **Archive**: Minimal compression (~180 MB) - Regulatory compliance, long-term storage

**Pricing Strategy**:
- Budget: $0.19/month per 1000 rasters (viz only)
- Standard: $0.79/month per 1000 rasters (viz + analysis)
- Enterprise: $1.20/month per 1000 rasters (all three tiers)

**Implementation Checklist**:
- [ ] Define COG profiles in config (JPEG/DEFLATE/minimal compression settings)
- [ ] Add `output_tier` parameter to `process_raster` job ("visualization", "analysis", "archive", "all")
- [ ] Update rio-cogeo calls to use tier-specific profiles
- [ ] Store outputs in tier-specific blob prefixes (e.g., `cogs/visualization/`, `cogs/analysis/`)
- [ ] Update STAC metadata with tier information
- [ ] Add storage cost tracking per tier
- [ ] Test with sample rasters across all three tiers

**Documentation Needs**:
- Explain compression tradeoffs (lossy vs lossless)
- When to use each tier (web mapping vs analysis vs compliance)
- Storage cost implications
- Quality comparison examples

---

### **Priority 2: API Standardization & Documentation** ⏰ URGENT
**Timeline**: Same sprint as Multi-Tier COG
**Business Value**: Knowledge transfer to non-geospatial developer
**Handoff Ready**: Critical for handoff

**Context**:
Codebase will be handed over to developer who knows:
- ✅ Azure Function Apps
- ✅ Data pipelines & ETL patterns
- ❌ **Geospatial data types** (need clear documentation)

**Strategy**: Use familiar ETL patterns, explain unfamiliar data types

**Implementation Checklist**:

#### **A. API Endpoint Standardization**
- [ ] Audit all `/api/jobs/submit/{job_type}` endpoints
- [ ] Standardize request/response formats across all jobs
- [ ] Consistent error responses (structure, HTTP codes)
- [ ] Parameter validation with clear error messages
- [ ] Example requests for every endpoint

#### **B. Geospatial Glossary for Non-Geo Developers**
Create `docs_claude/GEOSPATIAL_PRIMER.md`:
- [ ] **Raster Data**: What it is, common formats (GeoTIFF), use cases
- [ ] **Vector Data**: Points/Lines/Polygons, formats (Shapefile, GeoJSON), use cases
- [ ] **COG (Cloud Optimized GeoTIFF)**: Why it matters, HTTP range requests
- [ ] **CRS (Coordinate Reference System)**: EPSG codes, why EPSG:4326 is standard
- [ ] **STAC (SpatioTemporal Asset Catalog)**: Metadata standard for geospatial data
- [ ] **PostGIS**: PostgreSQL + spatial extensions, spatial indexing
- [ ] **MVT (Mapbox Vector Tiles)**: Efficient vector rendering for web maps
- [ ] **COG Compression**: JPEG (lossy) vs DEFLATE (lossless) vs LZW

#### **C. ETL Pipeline Documentation**
Create `docs_claude/ETL_PATTERNS.md`:
- [ ] Job→Stage→Task architecture (familiar ETL pattern)
- [ ] Fan-out/fan-in patterns (map-reduce analogy)
- [ ] Pickle intermediate storage (handling large datasets)
- [ ] Why we use PostgreSQL (ACID, spatial queries, no race conditions)
- [ ] Service Bus vs Queue Storage (when to use each)
- [ ] Idempotency via SHA256 hashing (duplicate prevention)

#### **D. API Reference Documentation**
Create `docs_claude/API_REFERENCE.md`:
- [ ] Every endpoint with curl examples
- [ ] Required vs optional parameters
- [ ] Expected response formats
- [ ] Error handling patterns
- [ ] Authentication (managed identity, storage keys)
- [ ] Rate limiting considerations

#### **E. Common Troubleshooting Guide**
Create `docs_claude/TROUBLESHOOTING.md`:
- [ ] Job stuck in "processing" → Check Application Insights logs
- [ ] "Blob not found" → Container name typo (rmhazuregeobronze vs rmhazuregeo)
- [ ] Invalid CRS → EPSG code format
- [ ] Geometry errors → 2D vs 3D, null geometries
- [ ] Deadlock issues → Already fixed (serialized table creation)
- [ ] Memory issues → Chunk size tuning

---

## 🚀 MAJOR FEATURES (Post-Handoff)

### **Priority 3: Vector API (OGC REST API Pattern)** 🌟 HIGH VALUE
**Timeline**: Separate sprint after handoff
**Business Value**: Standard geospatial API for clients
**Deployment**: **SEPARATE function app** (not part of ETL framework)

**Context**:
- This is a **read-only serving API**, not ETL
- Lives in separate function app for independent scaling
- ETL pipeline writes to PostGIS → Vector API reads from PostGIS
- Mimics OGC API Features standard (industry standard)

**Capabilities**:
- **GET /collections** - List available vector layers
- **GET /collections/{collectionId}/items** - Query features (GeoJSON)
- **GET /collections/{collectionId}/tiles/{z}/{x}/{y}** - Serve MVT tiles
- **GET /collections/{collectionId}/items/{featureId}** - Single feature
- Spatial filtering (bbox, intersects, within)
- Attribute filtering (CQL queries)
- Pagination (limit/offset)
- Response formats: GeoJSON, MVT, CSV

**Why Separate Function App**:
- Different scaling profile (read-heavy vs write-heavy)
- Independent deployment cycle
- No dependency on job orchestration framework
- Can use simpler architecture (HTTP triggers only)

**Implementation Checklist**:
- [ ] Create new function app project (`rmhvectorapi`)
- [ ] PostGIS connection pooling for read queries
- [ ] Implement OGC API Features spec (Collections, Items)
- [ ] MVT tile generation endpoint (PostGIS ST_AsMVT)
- [ ] Spatial query support (bbox, intersects)
- [ ] CQL filter parsing (attribute queries)
- [ ] GeoJSON output formatting
- [ ] Pagination with stable cursors
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Performance testing (concurrent requests)

**Proof of Concept Scope** (Establish Foundation):
- Single collection endpoint (`/collections/test`)
- Basic GeoJSON output
- Simple bbox filtering
- MVT tile endpoint (single zoom level)
- PostGIS query optimization

**PostGIS Heavy Lifting**:
- `ST_AsMVT()` - Generate MVT tiles
- `ST_AsGeoJSON()` - Format GeoJSON responses
- `ST_Intersects()` - Spatial filtering
- Spatial indexes (GIST) - Query performance
- `ST_TileEnvelope()` - Tile boundary calculation

---

### **Priority 4: Big Raster Automatic Tiling** 🔮 FUTURE
**Timeline**: Much later sprint based on client requirements
**Business Value**: Handle gigantic rasters (>10GB)
**Status**: Foundation work only

**Context**:
- This is for **very large rasters** that exceed memory limits
- Need to tile BEFORE processing (can't load entire raster)
- Complex workflow: analyze → generate tiling scheme → parallel tile processing

**Foundation Work (Now)**:
- [ ] Document tiling strategy in ARCHITECTURE_REFERENCE.md
- [ ] Research optimal tile size (512x512 vs 1024x1024)
- [ ] Identify rasterio tiling methods (windowed reading)
- [ ] Design stage workflow (analyze → tile → process tiles → mosaic)
- [ ] Determine memory thresholds (when to tile vs process whole)

**Full Implementation (Later)**:
- [ ] Analyze raster dimensions/memory requirements
- [ ] Generate tiling scheme (tile grid calculation)
- [ ] Stage 2: Extract tiles to temporary storage
- [ ] Stage 3: Process tiles in parallel (COG conversion)
- [ ] Stage 4: Update STAC with tiled COG references
- [ ] Handle edge tiles (partial tiles at boundaries)
- [ ] Overlap strategy (seamless mosaicking)

**Why Foundation First**:
- Design decisions impact ETL architecture
- Tiling is complex - need solid plan before implementing
- Client requirements may change approach
- Foundation work = 20% effort, enables 80% of implementation later

---

## 📚 Documentation Hierarchy (For Handoff)

```
docs_claude/
├── README.md                      # Start here - project overview
├── GEOSPATIAL_PRIMER.md          # NEW - Geospatial 101 for non-geo devs
├── ETL_PATTERNS.md                # NEW - Job→Stage→Task architecture
├── API_REFERENCE.md               # NEW - All endpoints with examples
├── TROUBLESHOOTING.md             # NEW - Common issues & solutions
├── CLAUDE_CONTEXT.md              # Existing - Technical deep dive
├── ARCHITECTURE_REFERENCE.md      # Existing - System design details
├── VECTOR_ETL_COMPLETE.md         # Existing - Vector pipeline guide
├── TODO_PRIORITIZED.md            # THIS FILE - Roadmap
└── HISTORY.md                     # Existing - Completed work log
```

**Documentation Priorities**:
1. **GEOSPATIAL_PRIMER.md** - Explain unfamiliar data types
2. **ETL_PATTERNS.md** - Connect to familiar pipeline concepts
3. **API_REFERENCE.md** - Practical usage guide
4. **TROUBLESHOOTING.md** - Self-service debugging

---

## 🎯 Success Metrics

### Multi-Tier COG (Priority 1)
- [ ] Can process same raster to 3 different tiers
- [ ] Storage costs calculated per tier
- [ ] STAC metadata includes tier information
- [ ] Documentation explains tier selection

### API Documentation (Priority 2)
- [ ] Non-geo developer can submit jobs without assistance
- [ ] Geospatial terms have clear definitions
- [ ] Every endpoint has working curl example
- [ ] Troubleshooting guide covers 80% of common issues

### Vector API POC (Priority 3)
- [ ] Single collection serves GeoJSON
- [ ] MVT tiles render in MapLibre
- [ ] Bbox filtering works correctly
- [ ] PostGIS queries are optimized (<100ms)
- [ ] Architecture documented for full implementation

### Raster Tiling Foundation (Priority 4)
- [ ] Tiling strategy documented
- [ ] Memory thresholds defined
- [ ] Stage workflow designed
- [ ] Ready for implementation when client requirements arrive

---

## 🚫 Explicitly NOT Priorities

These are good ideas but deferred:

- ❌ Job cancellation endpoint (nice-to-have)
- ❌ Historical analytics dashboard (future monitoring)
- ❌ Cross-job dependencies (complex, no use case yet)
- ❌ Scheduled jobs (cron-like triggers)
- ❌ Webhook notifications (not requested)
- ❌ Vector validation/repair (ETL handles this)
- ❌ Automated quality reports (future enhancement)

---

## 📝 Notes for Handoff Developer

**What You Need to Know**:
1. **This is an ETL pipeline** - You know this pattern already
2. **Geospatial data is just data** - Points, lines, polygons, images with coordinates
3. **PostGIS = PostgreSQL + spatial** - Familiar database, spatial queries added
4. **COG = optimized image format** - Like progressive JPEG, but for geo data
5. **STAC = metadata catalog** - Like a product catalog, but for geospatial assets

**What's Already Handled**:
- ✅ Parallel processing (Job→Stage→Task)
- ✅ Idempotency (duplicate prevention)
- ✅ Error handling (retry logic, failure detection)
- ✅ Monitoring (Application Insights, health checks)
- ✅ Schema validation (Pydantic, PostgreSQL)
- ✅ All 6 vector formats working
- ✅ Raster ETL production-ready

**Where to Focus**:
1. Read GEOSPATIAL_PRIMER.md first (unfamiliar concepts)
2. Review ETL_PATTERNS.md (familiar patterns)
3. Use API_REFERENCE.md for daily work
4. Consult TROUBLESHOOTING.md when issues arise

**Red Flags to Watch**:
- ⚠️ Never use `print()` - Always use `logger` (Azure Functions requirement)
- ⚠️ Container names matter - `rmhazuregeobronze` NOT `rmhazurebronze`
- ⚠️ CRS format - EPSG:4326 NOT just "4326"
- ⚠️ Geometry dimension - 2D only (x,y) NOT 3D (x,y,z)
- ⚠️ Chunk sizes - Auto-calculated, but can override if needed

---

**Last Updated**: 18 OCT 2025
**Next Review**: After Multi-Tier COG + Documentation complete
