## Epic E7: Pipeline Infrastructure 🚧

**Type**: Foundational Enabler
**Value Statement**: The ETL brain that makes everything else possible.
**Status**: 🚧 PARTIAL (F7.1 ✅, F7.2 🟡, F7.3 ✅, F7.4 ✅, F7.8 ✅, F7.9 🚧, F7.10 ✅, F7.11 🚧, F7.12 ✅, F7.13 🚧, F7.16 ✅, F7.17 ✅, F7.18 🚧)
**Last Updated**: 16 JAN 2026

**This is the substrate.** E1, E2, E8, and E9 all run on E7. Without it, nothing processes.

**Core Capabilities**:

| Capability | What It Does |
|------------|--------------|
| Data type inference | "This is RGB imagery" / "multispectral" / "probably a DEM" |
| Validation logic | Garbage KML (redundant nodes, broken geometries) → beautiful PostGIS |
| Job orchestration | Durable Functions + Service Bus coordination |
| Advisory locks | PostgreSQL-based distributed coordination |
| Fan-out patterns | Parallel task processing with controlled concurrency |
| Observability | Job state tracking, monitoring, failure handling |

**Why it's separate from E1/E2**: The orchestration system serves *all* data pipelines. It's not "vector ETL" or "raster ETL" — it's the engine that runs both.

**Feature Summary**:
| Feature | Status | Description |
|---------|--------|-------------|
| F7.1 | ✅ | Pipeline Infrastructure (registry, scheduler) |
| F7.2 | 🚧 | IBAT Reference Data (WDPA, KBAs - quarterly) |
| F7.3 | ✅ | Collection Ingestion Pipeline (~~E15~~) |
| F7.4 | ✅ | Pipeline Observability (~~E13~~) |
| F7.5 | 📋 | Pipeline Builder UI |
| F7.6 | 📋 | ACLED Conflict Data (twice weekly) |
| F7.7 | 📋 | Static Reference Data (Admin0, manual) |
| F7.8 | ✅ | **Unified Metadata Architecture** (VectorMetadata complete 09 JAN 2026) |
| F7.9 | 🚧 | **RasterMetadata Architecture** (extends F7.8 for rasters) |
| F7.10 | ✅ | Metadata Consistency Enforcement (timer + checker) |
| F7.11 | 🚧 | STAC Catalog Self-Healing (rebuild job) - vectors working |
| F7.12 | ✅ | **Docker Worker Infrastructure** - Deployed with OpenTelemetry (v0.7.8-otel, 11 JAN 2026) |
| F7.13 | 🚧 | **Docker Job Definitions** - Phase 1 complete (checkpoint/resume) |
| F7.14 | 🔵 | Dynamic Task Routing (optional, if hybrid needed later) |
| F7.15 | 📋 | HTTP-Triggered Docker Worker (alternative architecture) |
| F7.16 | ✅ | Code Maintenance - db_maintenance.py split (12 JAN 2026) |
| F7.17 | ✅ | Job Resubmit & Platform Features (12 JAN 2026) |
| F7.18 | 🚧 | **Docker Orchestration Framework** - Connection pooling, checkpointing, graceful shutdown (16 JAN 2026) |

---

### Feature F7.1: Pipeline Infrastructure ✅

**Deliverable**: Registry, scheduler, update job framework

| Story | Description |
|-------|-------------|
| S7.1.1 | Create data models |
| S7.1.2 | Design database schema |
| S7.1.3 | Create repository layer |
| S7.1.4 | Create registry service |
| S7.1.5 | Implement HTTP CRUD endpoints |
| S7.1.6 | Create timer scheduler (2 AM UTC) |
| S7.1.7 | Create 4-stage update job |
| S7.1.8 | Implement WDPA handler (reference implementation) |

**Key Files**: `core/models/curated.py`, `infrastructure/curated_repository.py`, `services/curated/`, `jobs/curated_update.py`

---

### Feature F7.2: IBAT Reference Data 🟡 CODE COMPLETE

**Deliverable**: IBAT-sourced reference datasets (WDPA, KBAs) for spatial analysis
**Documentation**: [IBAT.md](/IBAT.md)
**Data Source**: IBAT Alliance API (https://api.ibat-alliance.org)
**Update Frequency**: Quarterly
**Auth**: `WDPA_AUTH_KEY` + `WDPA_AUTH_TOKEN` env vars
**Status**: Code complete but NOT OPERATIONAL - credentials not configured, never executed

| Story | Status | Description |
|-------|--------|-------------|
| S7.2.1 | ✅ | IBAT base handler (shared auth, version checking) |
| S7.2.2 | ✅ | WDPA handler (World Database on Protected Areas, ~250K polygons) |
| S7.2.3 | 📋 | KBAs handler (Key Biodiversity Areas, ~16K polygons) |
| S7.2.4 | 📋 | Style integration (IUCN categories for WDPA, KBA status) |
| S7.2.5 | 📋 | Manual trigger endpoint (currently placeholder) |

**To Make Operational**:
1. Get IBAT API credentials from https://api.ibat-alliance.org
2. Set env vars in Azure: `WDPA_AUTH_KEY`, `WDPA_AUTH_TOKEN`
3. Submit job: `POST /api/jobs/submit/curated_wdpa_update`

**Key Files**:
- `services/curated/wdpa_handler.py` (544 lines - complete handler)
- `jobs/curated_update.py` (4-stage job)
- `core/models/curated.py`
- `infrastructure/curated_repository.py`

**Target Tables**:
- `geo.curated_wdpa_protected_areas` (not yet populated)
- `geo.curated_kbas` (planned)

---

### Feature F7.3: Collection Ingestion Pipeline ✅ (formerly E15)

**Deliverable**: Ingest pre-processed COG collections with existing STAC metadata
**Completed**: 29 DEC 2025
**Use Case**: Data already converted to COG with STAC JSON sidecars (MapSPAM agricultural data)

| Story | Status | Description |
|-------|--------|-------------|
| S7.3.1 | ✅ | Create `ingest_collection` job definition (5-stage workflow) |
| S7.3.2 | ✅ | Inventory handler (download collection.json, parse items) |
| S7.3.3 | ✅ | Copy handler (parallel blob copy bronze → silver) |
| S7.3.4 | ✅ | Register handlers (pgSTAC collection + items) |
| S7.3.5 | ✅ | Finalize handler (h3.source_catalog entry) |

**Key Files**:
- `jobs/ingest_collection.py`
- `services/ingest/handler_inventory.py`
- `services/ingest/handler_copy.py`
- `services/ingest/handler_register.py`

**Usage**:
```bash
POST /api/jobs/submit/ingest_collection
{
    "source_container": "bronzemapspam",
    "target_container": "silvermapspam",
    "batch_size": 100
}
```

---

### Feature F7.4: Pipeline Observability ✅ (formerly E13)

**Deliverable**: Real-time metrics for long-running jobs with massive task counts
**Completed**: 28 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S7.4.1 | ✅ | Create `config/metrics_config.py` with env vars |
| S7.4.2 | ✅ | Create `app.job_metrics` table (self-bootstrapping) |
| S7.4.3 | ✅ | Create `infrastructure/metrics_repository.py` |
| S7.4.4 | ✅ | Create `infrastructure/job_progress.py` - base tracker |
| S7.4.5 | ✅ | Create `infrastructure/job_progress_contexts.py` - H3/FATHOM/Raster mixins |
| S7.4.6 | ✅ | Create HTTP API + dashboard at `/api/interface/metrics` |
| S7.4.7 | ✅ | Integrate H3AggregationTracker into `handler_raster_zonal.py` |
| S7.4.8 | ✅ | Integrate FathomETLTracker into FATHOM handlers |
| S7.4.9 | 📋 | Integrate into `handler_inventory_cells.py` (deferred) |

**Key Files**:
- `config/metrics_config.py`
- `infrastructure/metrics_repository.py`
- `infrastructure/job_progress.py`
- `infrastructure/job_progress_contexts.py`
- `web_interfaces/metrics/interface.py`

**Dashboard Features**: HTMX live updates, job cards with progress bars, rate display, ETA calculation, context-specific metrics

---

### Feature F7.5: Pipeline Builder UI 📋

**Deliverable**: Visual interface for defining and executing pipelines
**Status**: 📋 PLANNED

| Story | Status | Description |
|-------|--------|-------------|
| S7.5.1 | 📋 | Design pipeline builder wireframes |
| S7.5.2 | 📋 | Create drag-and-drop step editor |
| S7.5.3 | 📋 | Integrate with pipeline definitions |
| S7.5.4 | 📋 | Add execution monitoring view |

---

### Feature F7.6: ACLED Conflict Data 📋 LOW PRIORITY

**Deliverable**: Armed Conflict Location & Event Data for risk analysis
**Documentation**: [ACLED.md](/ACLED.md)
**Data Source**: ACLED API (https://acleddata.com)
**Update Frequency**: Twice weekly (Monday, Thursday)
**Auth**: Separate `ACLED_API_KEY` + `ACLED_EMAIL` env vars

| Story | Status | Description |
|-------|--------|-------------|
| S7.6.1 | 📋 | ACLED handler (API auth, pagination) |
| S7.6.2 | 📋 | Event data ETL (point geometry, conflict categories) |
| S7.6.3 | 📋 | Incremental updates (upsert by event_id, not full replace) |
| S7.6.4 | 📋 | Schedule config (twice-weekly timer or cron) |
| S7.6.5 | 📋 | Style integration (conflict type symbology) |

**Key Differences from IBAT**:
- **Frequency**: Twice weekly vs quarterly
- **Update Strategy**: `upsert` (incremental) vs `full_replace`
- **Geometry**: Points (events) vs Polygons (areas)
- **Volume**: High frequency, smaller batches

**Target Table**: `geo.curated_acled_events`

**Schema** (planned):
```sql
CREATE TABLE geo.curated_acled_events (
    event_id BIGINT PRIMARY KEY,
    event_date DATE,
    event_type VARCHAR(100),
    sub_event_type VARCHAR(100),
    actor1 TEXT,
    actor2 TEXT,
    country VARCHAR(100),
    admin1 VARCHAR(200),
    location TEXT,
    fatalities INTEGER,
    geom GEOMETRY(Point, 4326),
    source_url TEXT,
    updated_at TIMESTAMPTZ
);
```

---

### Feature F7.7: Static Reference Data 📋 LOW PRIORITY

**Deliverable**: Manually-updated reference datasets (no automated API)
**Update Frequency**: Manual (on Natural Earth releases, ~annually)

| Story | Status | Description |
|-------|--------|-------------|
| S7.7.1 | 📋 | Admin0 handler (Natural Earth country boundaries) |
| S7.7.2 | 📋 | Admin1 handler (Natural Earth state/province boundaries) |
| S7.7.3 | 📋 | Coastlines/land polygons (optional) |
| S7.7.4 | 📋 | Manual trigger UI (no scheduler needed) |

**Target Tables**:
- `geo.curated_admin0`
- `geo.curated_admin1` (optional)

**Note**: These use `source_type: manual` in the curated_datasets registry - no automatic scheduling.

---

### Feature F7.8: Unified Metadata Architecture ✅ COMPLETE

**Deliverable**: Pydantic-based metadata models providing single source of truth across all data types
**Status**: ✅ COMPLETE (VectorMetadata - 09 JAN 2026)
**Design Document**: [METADATA.md](/METADATA.md)
**Added**: 08 JAN 2026
**Completed**: 09 JAN 2026

**Problem Statement**:
- Vector metadata in `geo.table_metadata`, raster metadata only in `pgstac.items`
- No common interface for metadata across data types
- JSONB soup for type-specific fields loses schema validation
- Difficult to add new data formats (GeoParquet, point clouds, etc.)

**Solution**: Pydantic inheritance pattern with typed columns (minimal JSONB)

```
BaseMetadata (abstract)
    │
    ├── VectorMetadata      → geo.table_metadata
    ├── RasterMetadata      → raster.cog_metadata (future)
    ├── ZarrMetadata        → zarr.dataset_metadata (future)
    └── NewFormatMetadata   → extensible for future formats
```

**Architecture Principles**:
1. **Pydantic models as single source of truth** — validation, serialization, documentation
2. **Typed columns over JSONB** — `feature_count INT` not `properties->>'feature_count'`
3. **Minimal JSONB for extensibility** — `providers`, `external_refs`, `custom_properties` only
4. **pgstac as catalog index** — populated FROM metadata tables, not source of truth
5. **Open/Closed Principle** — extend via inheritance, don't modify base
6. **External refs in app schema** — cross-cutting DDH linkage lives in `app.dataset_refs`

| Story | Status | Description |
|-------|--------|-------------|
| S7.8.1 | ✅ | Create `core/models/unified_metadata.py` with BaseMetadata + VectorMetadata |
| S7.8.2 | ✅ | Create `core/models/external_refs.py` with DDHRefs + ExternalRefs models |
| S7.8.3 | ✅ | Create `app.dataset_refs` table DDL (cross-type external linkage) |
| S7.8.4 | ✅ | Add `providers JSONB` and `custom_properties JSONB` to geo.table_metadata DDL |
| S7.8.5 | ✅ | Refactor `ogc_features/repository.py` to return VectorMetadata model |
| S7.8.6 | ✅ | Refactor `ogc_features/service.py` to use VectorMetadata.to_ogc_response() |
| S7.8.7 | ✅ | Refactor `services/stac_vector_catalog.py` to use VectorMetadata.to_stac_item() |
| S7.8.8 | 📋 | Wire Platform layer to populate app.dataset_refs on ingest |
| S7.8.9 | ➡️ | Document pattern for future data types → moved to F7.9 |
| S7.8.10 | 📋 | Archive METADATA.md design doc to docs/archive after implementation |

**Key Files** (planned):
- `core/models/unified_metadata.py` — BaseMetadata, VectorMetadata, Provider
- `core/models/external_refs.py` — DDHRefs, ExternalRefs (cross-type linkage)
- `infrastructure/external_refs_repository.py` — CRUD for app.dataset_refs
- `triggers/admin/db_maintenance.py` — DDL updates for new columns/tables
- `ogc_features/repository.py` — return VectorMetadata instead of dict
- `ogc_features/service.py` — use model methods for response building
- `services/stac_vector_catalog.py` — use model methods for STAC item creation

**BaseMetadata Common Fields**:
```python
class BaseMetadata(BaseModel):
    id: str
    data_type: Literal["vector", "raster", "zarr"]
    title: Optional[str]
    description: Optional[str]
    bbox: Optional[List[float]]
    temporal_start: Optional[datetime]
    temporal_end: Optional[datetime]
    license: Optional[str]  # SPDX identifier
    providers: List[Provider]  # [{name, roles[], url}]
    keywords: List[str]
    etl_job_id: Optional[str]
    stac_collection_id: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    custom_properties: Dict[str, Any]  # Extensibility
```

**VectorMetadata Type-Specific Fields**:
```python
class VectorMetadata(BaseMetadata):
    data_type: Literal["vector"] = "vector"
    feature_count: Optional[int]
    geometry_type: Optional[str]
    source_crs: Optional[str]
    temporal_property: Optional[str]
```

**Future Extensibility Example**:
```python
class GeoParquetMetadata(BaseMetadata):
    data_type: Literal["geoparquet"] = "geoparquet"
    row_groups: int
    compression: str
    geometry_encoding: str
```

**External References Architecture** (DDH linkage):
```python
# core/models/external_refs.py

class DDHRefs(BaseModel):
    """DDH (Data Hub Dashboard) external system references."""
    dataset_id: Optional[str] = None   # DDH dataset identifier
    resource_id: Optional[str] = None  # DDH resource identifier
    version_id: Optional[str] = None   # DDH version identifier

class ExternalRefs(BaseModel):
    """References to external catalog systems."""
    ddh: Optional[DDHRefs] = None
    # Future: other external systems
    # acme_catalog: Optional[AcmeRefs] = None
```

**app.dataset_refs Table** (cross-type linkage):
```sql
-- Lives in app schema (not geo) because it spans all data types
CREATE TABLE app.dataset_refs (
    -- Internal reference
    dataset_id VARCHAR(255) PRIMARY KEY,  -- Our ID (table_name, cog_path, zarr_path)
    data_type VARCHAR(20) NOT NULL,       -- 'vector', 'raster', 'zarr'

    -- DDH linkage (typed columns for indexing)
    ddh_dataset_id VARCHAR(100),
    ddh_resource_id VARCHAR(100),
    ddh_version_id VARCHAR(100),

    -- Future external systems (JSONB for extensibility)
    other_refs JSONB DEFAULT '{}',

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Indexes for DDH lookups
    CONSTRAINT idx_ddh_combo UNIQUE (ddh_dataset_id, ddh_resource_id, ddh_version_id)
);

-- Fast lookups by DDH IDs
CREATE INDEX idx_dataset_refs_ddh_dataset ON app.dataset_refs(ddh_dataset_id);
```

**Platform Layer Flow**:
```
PlatformRequest                    app.dataset_refs
├── dataset_id     ─────────────► ddh_dataset_id
├── resource_id    ─────────────► ddh_resource_id
├── version_id     ─────────────► ddh_version_id
└── source_url     ─────────────► (determines data_type + dataset_id)
```

**Enables**:
- E1 (Vector): Clean metadata for OGC Features API
- E2 (Raster): Parallel `raster.cog_metadata` table with RasterMetadata
- E9 (Zarr): Parallel `zarr.dataset_metadata` table with ZarrMetadata
- E8 (Analytics): Consistent metadata across aggregation outputs

---

### Feature F7.10: Metadata Consistency Enforcement ✅

**Deliverable**: Automated detection of cross-schema metadata inconsistencies
**Completed**: 10 JAN 2026
**Design Document**: [METADATA_CONSISTENCY_DESIGN.md](/METADATA_CONSISTENCY_DESIGN.md)

**Problem Statement**:
- STAC items can become orphaned (no corresponding metadata record)
- Metadata records can have broken backlinks (stac_item_id → non-existent STAC item)
- Dataset refs can have dangling foreign keys
- COG blobs can be deleted but metadata remains

**Solution**: Two-tier validation with timer-based detection

| Tier | Frequency | Checks | Cost |
|------|-----------|--------|------|
| **Tier 1** (Timer) | Every 6 hours | DB cross-refs, blob HEAD | 💰 Cheap |
| **Tier 2** (CoreMachine) | Weekly | Full file validation | 💰💰💰 Expensive |

| Story | Status | Description |
|-------|--------|-------------|
| S7.10.1 | ✅ | Create `triggers/timer_base.py` - DRY pattern for timer handlers |
| S7.10.2 | ✅ | Extract geo_orphan_timer and system_snapshot_timer to handlers |
| S7.10.3 | ✅ | Create `services/metadata_consistency.py` - 7 cross-schema checks |
| S7.10.4 | ✅ | Create timer trigger (schedule: 03:00, 09:00, 15:00, 21:00 UTC) |
| S7.10.5 | ✅ | Add HTTP endpoint `GET /api/cleanup/metadata-health` |
| S7.10.6 | ✅ | Integrate with janitor `POST /api/admin/janitor/run?type=metadata_consistency` |

**Checks Implemented**:
1. `stac_vector_orphans` - pgstac.items without geo.table_metadata
2. `stac_raster_orphans` - pgstac.items without app.cog_metadata
3. `vector_backlinks` - table_metadata.stac_item_id → pgstac
4. `raster_backlinks` - cog_metadata.stac_item_id → pgstac
5. `dataset_refs_vector` - dataset_refs → table_metadata FK
6. `dataset_refs_raster` - dataset_refs → cog_metadata FK
7. `raster_blob_exists` - HEAD request for recent COGs

**Key Files**:
- `triggers/timer_base.py` - TimerHandlerBase ABC
- `triggers/admin/metadata_consistency_timer.py` - Timer handler
- `services/metadata_consistency.py` - MetadataConsistencyChecker (580 lines)

---

### Feature F7.11: STAC Catalog Self-Healing 🚧

**Deliverable**: Job-based remediation for metadata consistency issues
**Status**: 🚧 IN PROGRESS (vectors working, raster pending)
**Added**: 10 JAN 2026
**Implemented**: 10 JAN 2026

**Problem Statement**:
- F7.10 timer detects issues but cannot fix them (would timeout on large repairs)
- Current STAC generation is embedded in ETL jobs (process_vector, process_raster)
- No standalone batch rebuild capability

**Solution**: Dedicated `rebuild_stac` job with fan-out pattern

```
Timer Detection (F7.10)
    ↓ finds 9 broken backlinks
Job Submission
    POST /api/jobs/submit/rebuild_stac
    {"data_type": "vector", "items": [...], "dry_run": false}
    ↓
Stage 1: VALIDATE (single task)
    - Check each source exists (geo.table for vectors, COG blob for rasters)
    - Filter out items with missing source data
    - Return list of rebuildable items
    ↓
Stage 2: REBUILD (fan_out - 1 task per item)
    - Reuse existing create_vector_stac / extract_stac_metadata handlers
    - STAC item regenerated + backlink updated
    - Independent, parallel execution
    ↓
Completion
    - Summary logged to Application Insights
    - Broken backlinks resolved
```

| Story | Status | Description |
|-------|--------|-------------|
| S7.11.1 | ✅ | Create `jobs/rebuild_stac.py` - 2-stage job definition |
| S7.11.2 | ✅ | Create `services/rebuild_stac_handlers.py` - validate + rebuild handlers |
| S7.11.3 | ✅ | Register job and handlers in `__init__.py` files |
| S7.11.4 | ✅ | Add `force_recreate` mode (delete existing STAC before rebuild) |
| S7.11.5 | 📋 | Add raster support (rebuild from COG metadata) |
| S7.11.6 | 📋 | Optional: Timer auto-submit (detect issues → submit rebuild job) |

**Parameters**:
```python
parameters_schema = {
    'data_type': {'type': 'str', 'required': True, 'enum': ['vector', 'raster']},
    'items': {'type': 'list', 'required': True},  # table names or cog_ids
    'dry_run': {'type': 'bool', 'default': True},
    'force_recreate': {'type': 'bool', 'default': False},
    'collection_id': {'type': 'str', 'default': None}  # Override collection
}
```

**Key Files**:
- `jobs/rebuild_stac.py` - RebuildStacJob class (227 lines)
- `services/rebuild_stac_handlers.py` - stac_rebuild_validate, stac_rebuild_item (367 lines)

**Usage**:
```bash
# Rebuild STAC for specific vector tables
POST /api/jobs/submit/rebuild_stac
{
    "data_type": "vector",
    "items": ["curated_admin0", "system_ibat_kba"],
    "schema": "geo",
    "dry_run": false
}
```

**Design Principles**:
1. **Reuse existing handlers** - Stage 2 calls battle-tested `create_vector_stac`
2. **Safe by default** - `dry_run: true` validates without modifying
3. **Batch support** - Single job can rebuild multiple items
4. **Idempotent** - Safe to re-run (existing STAC items skipped unless force_recreate)

---

### Feature F7.12: Docker Worker Infrastructure ✅ COMPLETE

**Deliverable**: Docker worker with Managed Identity OAuth for PostgreSQL and Storage
**Status**: ✅ DEPLOYED (11 JAN 2026)
**Deployed To**: `rmhheavyapi` Web App
**Image**: `rmhazureacr.azurecr.io/geospatial-worker:v0.7.8-otel`
**Version**: 0.7.8

**Problem Solved**:
- Function App has 10-minute timeout, limited GDAL support
- Large rasters (>1GB) need Docker worker with full GDAL
- Docker worker needs OAuth tokens for Azure services
- **Multi-app observability** - Docker worker logs to same App Insights as Function App

**Implementation**:
- FastAPI health endpoints (`/livez`, `/readyz`, `/health`)
- Managed Identity OAuth for PostgreSQL (user-assigned) and Storage (system-assigned)
- Background token refresh thread (45-minute interval)
- OSGeo GDAL ubuntu-full-3.10.1 base image
- **OpenTelemetry integration** - `azure-monitor-opentelemetry` sends logs to App Insights

| Story | Status | Description |
|-------|--------|-------------|
| S7.12.1 | ✅ | Create `docker_main.py` (queue polling entry point) |
| S7.12.2 | ✅ | Create `workers_entrance.py` (FastAPI + health endpoints) |
| S7.12.3 | ✅ | Create `Dockerfile`, `requirements-docker.txt`, `docker.env.example` |
| S7.12.4 | ⏭️ | Skip testing/ directory (building new tests later) |
| S7.12.5 | ✅ | Create `.funcignore` to exclude Docker files from Functions |
| S7.12.6 | ✅ | Create `infrastructure/auth/` module for Managed Identity OAuth |
| S7.12.7 | ✅ | Verify ACR build succeeds |
| S7.12.8 | ✅ | Deploy to rmhheavyapi Web App |
| S7.12.9 | ✅ | Configure identities (PostgreSQL: user-assigned, Storage: system-assigned) |
| S7.12.10 | ✅ | Verify all health endpoints working |
| S7.12.11 | ✅ | Add `azure-monitor-opentelemetry` to requirements-docker.txt |
| S7.12.12 | ✅ | Configure OpenTelemetry in `workers_entrance.py` BEFORE FastAPI import |
| S7.12.13 | ✅ | Configure OpenTelemetry in `docker_main.py` for queue polling |
| S7.12.14 | ✅ | Build v0.7.8-otel image with OpenTelemetry and push to ACR |
| S7.12.15 | ✅ | Deploy to rmhheavyapi and verify telemetry transmission to App Insights |

**Key Files Created/Modified**:
| File | Purpose | Lines |
|------|---------|-------|
| `docker_main.py` | Queue polling entry point + OpenTelemetry setup | 180+ |
| `workers_entrance.py` | FastAPI app + health + OpenTelemetry (before FastAPI) | 550+ |
| `Dockerfile` | OSGeo GDAL ubuntu-full-3.10.1 base | 24 |
| `requirements-docker.txt` | Dependencies + azure-monitor-opentelemetry | 35 |
| `docker.env.example` | Environment variable template | 110 |
| `.funcignore` | Excludes Docker files from Functions | 15 |
| `infrastructure/auth/__init__.py` | Auth module initialization | 71 |
| `infrastructure/auth/token_cache.py` | Thread-safe token caching | 105 |
| `infrastructure/auth/postgres_auth.py` | PostgreSQL OAuth | 233 |
| `infrastructure/auth/storage_auth.py` | Storage OAuth + GDAL config | 263 |

**Identity Configuration**:
| Resource | Identity | Type | Principal ID |
|----------|----------|------|--------------|
| PostgreSQL (`rmhpgflexadmin`) | User-assigned MI | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | `ab45e154...` |
| Storage (`rmhazuregeo`) | System-assigned MI | Web App identity | `cea30c4b...` |

**Health Endpoints**:
| Endpoint | Purpose | Response |
|----------|---------|----------|
| `/livez` | Liveness probe | `{"status":"ok"}` |
| `/readyz` | Readiness probe | Token status |
| `/health` | Detailed health | DB + Storage connectivity |
| `/test/database` | DB connectivity test | Connection details |
| `/test/storage` | Storage connectivity test | Account access |

**Background Workers**:
- Token refresh thread: 45-minute interval, 5-minute buffer before expiry
- Tokens valid for ~24 hours (Azure AD default)

**OpenTelemetry Integration (v0.7.8-otel)**:
- Package: `azure-monitor-opentelemetry>=1.6.0`
- Configuration must be called BEFORE FastAPI import
- Sends logs, traces, metrics to same App Insights as Function App
- Cross-app correlation via `cloud_RoleName`

**Multi-App Log Query**:
```kql
traces
| where cloud_RoleName in ("rmhazuregeoapi", "docker-worker-azure")
| project timestamp, cloud_RoleName, message
| order by timestamp desc
```

---

### Feature F7.13: Docker Job Definitions 📋 PRIORITY

**Deliverable**: Consolidated single-task job definitions for Docker worker
**Status**: 📋 PLANNED - PRIORITY
**Added**: 10 JAN 2026
**Blocks**: F7.12 (need Docker infrastructure first)

**Approach**: Each Docker job consolidates multi-stage Function App logic into one handler.

```python
# Function App: 3 stages, 3 handlers
class ProcessRasterV2Job:
    stages = [
        {"number": 1, "task_type": "validate_raster"},
        {"number": 2, "task_type": "create_cog"},
        {"number": 3, "task_type": "stac_raster"},
    ]

# Docker: 1 stage, 1 handler (does everything)
class ProcessRasterDockerJob:
    stages = [
        {"number": 1, "task_type": "process_raster_complete"},
    ]
```

**Handler Pattern**:
```python
def process_raster_complete(params: dict, context: dict) -> dict:
    """Complete raster processing in one execution."""
    # Reuse existing logic functions (not handlers)
    validation = _validate_raster_impl(params)
    cog_result = _create_cog_impl(params, validation)
    stac_result = _register_stac_impl(params, cog_result)
    return {**cog_result, **stac_result}
```

| Story | Status | Description |
|-------|--------|-------------|
| S7.13.1 | 📋 | Create `jobs/process_raster_docker.py` - single-stage job definition |
| S7.13.2 | 📋 | Create `services/raster/handler_complete.py` - consolidated handler |
| S7.13.3 | 📋 | Extract reusable `_impl` functions from existing handlers |
| S7.13.4 | 📋 | Register job and handler in `__init__.py` files |
| S7.13.5 | 📋 | Add submission endpoint or use generic `/api/jobs/submit/{job_type}` |
| S7.13.6 | 📋 | Test locally with `workers_entrance.py` |
| S7.13.7 | 📋 | Test end-to-end: submit job → Docker executes → job complete |
| S7.13.8 | 📋 | Add `process_vector_docker` job (same pattern) |

**Jobs to Create**:
| Docker Job | Consolidates | Handler |
|------------|--------------|---------|
| `process_raster_docker` | validate + COG + STAC | `process_raster_complete` |
| `process_vector_docker` | validate + load + STAC | `process_vector_complete` |
| `process_large_raster_docker` | chunked + COG + STAC | `process_large_raster_complete` |

**Key Files** (planned):
- `jobs/process_raster_docker.py` - Job definition
- `services/raster/handler_complete.py` - Consolidated handler
- `jobs/process_vector_docker.py` - Vector job
- `services/vector/handler_complete.py` - Vector handler

**Testing**:
```bash
# Local Docker test
curl -X POST http://localhost:8080/execute/process_raster_complete \
    -H "Content-Type: application/json" \
    -d '{"source_url": "...", "output_container": "silvercogs"}'

# Full job test
curl -X POST http://localhost:8080/test/execute/process_raster_complete \
    -d '{"params": {"source_url": "..."}}'
```

---

### Feature F7.14: Dynamic Task Routing 🔵 OPTIONAL

**Deliverable**: Configurable task-to-queue routing with environment-based overrides
**Status**: 🔵 BACKLOG - Optional, implement if needed
**Design Document**: [UNIFICATION.md Section 4](/Users/robertharrison/python_builds/rmhgeoapi-docker/UNIFICATION.md#4-taskroutingconfig-design)
**Added**: 10 JAN 2026
**Revised**: 10 JAN 2026 - Demoted to optional (separate Docker jobs is simpler)

**When This Would Be Needed**:
- If you want Function App and Docker to share the SAME job definitions
- If you want to route SOME tasks to Docker, others to Functions dynamically
- If you want hybrid execution (e.g., validate in Functions, COG in Docker)

**Current Decision**: Use separate job definitions (F7.13) instead.
- Simpler to implement, test, and troubleshoot
- No CoreMachine changes required
- Clear separation of concerns

**If Needed Later**:
`TaskRoutingConfig` class would allow:
```bash
# Route all raster tasks to Docker
ROUTE_ALL_RASTER_TO_DOCKER=true

# Or specific tasks only
ROUTE_TO_DOCKER=create_cog,create_cog_streaming
```

| Story | Status | Description |
|-------|--------|-------------|
| S7.14.1 | 🔵 | Create `config/task_routing_config.py` |
| S7.14.2 | 🔵 | Update `config/defaults.py` with task lists |
| S7.14.3 | 🔵 | Integrate with CoreMachine `_get_queue_for_task()` |
| S7.14.4 | 🔵 | Add `/routing` health endpoint |

**Revisit When**: Separate Docker jobs prove insufficient for a use case.

---

### Feature F7.9: RasterMetadata Architecture 🚧 IN PROGRESS

**Deliverable**: Extend F7.8 metadata pattern for raster data
**Status**: 🚧 IN PROGRESS (combined with F7.11 as next priority)
**Added**: 12 JAN 2026
**Depends On**: F7.8 ✅

**Goal**: Apply the same Pydantic-based metadata architecture to rasters that F7.8 established for vectors.

| Story | Status | Description |
|-------|--------|-------------|
| S7.9.1 | 📋 | Create `RasterMetadata` model extending BaseMetadata |
| S7.9.2 | 📋 | Add raster-specific fields (bands, resolution, nodata, etc.) |
| S7.9.3 | 📋 | Create `app.cog_metadata` table DDL |
| S7.9.4 | 📋 | Refactor `stac_catalog.py` to use RasterMetadata model |
| S7.9.5 | 📋 | Wire Platform layer to populate raster metadata |
| S7.9.6 | 📋 | Test STAC item generation from RasterMetadata |

**Key Files** (planned):
- `core/models/unified_metadata.py` — add RasterMetadata class
- `app.cog_metadata` table DDL in db_maintenance
- `services/stac_catalog.py` — refactor to use model

---

### Feature F7.15: HTTP-Triggered Docker Worker 📋 PLANNED

**Deliverable**: Alternative Docker architecture using HTTP triggers instead of queue polling
**Status**: 📋 PLANNED (alternative to current queue-based approach)
**Added**: 12 JAN 2026

**Context**: Current Docker worker polls Service Bus queues. This alternative uses Azure Container Apps with HTTP triggers for simpler scaling.

| Story | Status | Description |
|-------|--------|-------------|
| S7.15.1 | 📋 | Design HTTP-triggered architecture |
| S7.15.2 | 📋 | Create FastAPI endpoint for task execution |
| S7.15.3 | 📋 | Configure Azure Container Apps HTTP scaling |
| S7.15.4 | 📋 | Compare performance with queue-based approach |

**Note**: May not be needed if current queue-based Docker worker (F7.12) meets requirements.

---

### Feature F7.16: Code Maintenance ✅ COMPLETE

**Deliverable**: Split oversized db_maintenance.py into focused modules
**Status**: ✅ COMPLETE (12 JAN 2026)
**Added**: 12 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| S7.16.1 | ✅ | Split db_maintenance.py into schema-specific modules |
| S7.16.2 | ✅ | Create db_maintenance_app.py (app schema) |
| S7.16.3 | ✅ | Create db_maintenance_geo.py (geo schema) |
| S7.16.4 | ✅ | Create db_maintenance_h3.py (h3 schema) |
| S7.16.5 | ✅ | Update imports and verify functionality |

**Key Files**:
- `triggers/admin/db_maintenance.py` — router only
- `triggers/admin/db_maintenance_app.py` — app schema DDL
- `triggers/admin/db_maintenance_geo.py` — geo schema DDL
- `triggers/admin/db_maintenance_h3.py` — h3 schema DDL

---

### Feature F7.17: Job Resubmit & Platform Features ✅ COMPLETE

**Deliverable**: Job resubmission capability and Platform processing_mode parameter
**Status**: ✅ COMPLETE (12 JAN 2026)
**Added**: 12 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| S7.17.1 | ✅ | Add job resubmit endpoint `POST /api/jobs/{job_id}/resubmit` |
| S7.17.2 | ✅ | Implement failed task retry logic |
| S7.17.3 | ✅ | Add `processing_mode` parameter to Platform requests |
| S7.17.4 | ✅ | Route `processing_mode=docker` to Docker worker queue |

**Key Files**:
- `triggers/trigger_jobs.py` — resubmit endpoint
- `services/job_orchestrator.py` — resubmit logic
- `triggers/trigger_platform.py` — processing_mode routing

---

### Feature F7.18: Docker Orchestration Framework 🚧 PRIORITY

**Deliverable**: Reusable infrastructure for Docker-based long-running jobs
**Status**: 🚧 IN PROGRESS
**Added**: 16 JAN 2026
**Updated**: 16 JAN 2026 (revised after reviewing existing implementation)
**Priority**: HIGH - Foundation for all Docker jobs
**Depends On**: F7.12 ✅ (Docker Worker Infrastructure)
**Enables**: F7.13 (Docker Job Definitions), E8 H3 Docker Jobs

---

#### Existing Infrastructure (Already Implemented)

**IMPORTANT**: Review of `process_raster_docker` (16 JAN 2026) revealed substantial existing infrastructure:

| Component | Status | Location |
|-----------|--------|----------|
| **CheckpointManager** | ✅ EXISTS | `infrastructure/checkpoint_manager.py` |
| **Task checkpoint fields** | ✅ EXISTS | `checkpoint_phase`, `checkpoint_data`, `checkpoint_updated_at` |
| **Task schema deployed** | ✅ EXISTS | `core/models/task.py`, `core/schema/sql_generator.py` |
| **Handler pattern** | ✅ EXISTS | `services/handler_process_raster_complete.py` |
| **Connection pooling** | ❌ MISSING | Need to create |
| **DockerTaskContext** | ❌ MISSING | Need to create |
| **Graceful shutdown** | ❌ MISSING | Need to integrate |

**Existing CheckpointManager API**:
```python
# infrastructure/checkpoint_manager.py - ALREADY EXISTS!
checkpoint = CheckpointManager(task_id, task_repo)

checkpoint.should_skip(phase)      # Check if phase completed
checkpoint.save(phase, data, validate_artifact)  # Save checkpoint
checkpoint.get_data(key, default)  # Retrieve checkpoint data
checkpoint.reset()                 # Clear checkpoint
```

**Existing Handler Pattern** (`handler_process_raster_complete.py`):
```python
def process_raster_complete(params: Dict, context: Optional[Dict] = None):
    task_id = params.get('_task_id')

    # Handler creates CheckpointManager (current pattern)
    if task_id:
        checkpoint = CheckpointManager(task_id, task_repo)
        if checkpoint.current_phase > 0:
            logger.info(f"Resuming from phase {checkpoint.current_phase}")

    # Phase 1
    if checkpoint and checkpoint.should_skip(1):
        validation_result = checkpoint.get_data('validation_result', {})
    else:
        validation_result = validate_raster(params)
        checkpoint.save(1, data={'validation_result': validation_result})

    # Phase 2 (with artifact validation)
    if checkpoint and checkpoint.should_skip(2):
        cog_blob = checkpoint.get_data('cog_blob')
    else:
        cog_result = create_cog(params)
        checkpoint.save(2, data={'cog_blob': cog_blob},
                       validate_artifact=lambda: blob_exists(cog_blob))
```

---

#### Problem Statement

Docker workers have different characteristics than Azure Functions:

| Characteristic | Function App | Docker Worker |
|----------------|--------------|---------------|
| **Timeout** | 10 min max | Hours/unlimited |
| **Lifecycle** | Unpredictable (serverless) | Predictable (container) |
| **Connections** | Single-use (leak risk) | Pooled (safe) |
| **Crash Recovery** | Auto-retry | Needs checkpoint/resume |
| **Token Expiry** | Rarely hits expiry | Must handle mid-task |

**Current Gap**: Handlers manually create CheckpointManager and have no shutdown awareness.

**Solution**: Wrap existing CheckpointManager in DockerTaskContext with shutdown awareness.

---

#### Framework Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Docker Orchestration Framework                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ ConnectionPool  │  │  Checkpoint     │  │  Graceful       │             │
│  │ Manager         │  │  Manager        │  │  Shutdown       │             │
│  │ (NEW)           │  │  (EXISTS ✅)    │  │  (NEW)          │             │
│  │                 │  │                 │  │                 │             │
│  │ • Mode-aware    │  │ • Phase-based   │  │ • SIGTERM       │             │
│  │ • Token refresh │  │ • Data persist  │  │ • Save state    │             │
│  │ • Auto-recreate │  │ • Resume logic  │  │ • Drain work    │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                            │
│                    ┌───────────▼───────────┐                               │
│                    │   DockerTaskContext   │                               │
│                    │   (NEW - wraps above) │                               │
│                    │                       │                               │
│                    │  • checkpoint (mgr)   │                               │
│                    │  • shutdown_event     │                               │
│                    │  • should_stop()      │                               │
│                    │  • report_progress()  │                               │
│                    └───────────────────────┘                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

#### Phase 1: Connection Pool Manager (S7.18.1-4)

**Goal**: Mode-aware database connections - pool for Docker, single-use for Functions

**Design**:
```python
# infrastructure/connection_pool.py

class ConnectionPoolManager:
    """
    Docker-aware connection pool manager.

    - Function App mode: Returns single-use connections (current behavior)
    - Docker mode: Returns pooled connections (new capability)
    - Handles token refresh with pool recreation
    """

    _pool: Optional[ConnectionPool] = None
    _pool_lock = threading.Lock()

    @classmethod
    def get_connection(cls) -> ContextManager[Connection]:
        """Get connection (mode-aware)."""
        if _is_docker_mode():
            return cls._get_pool().connection()
        else:
            return _single_use_connection()

    @classmethod
    def recreate_pool(cls):
        """Recreate pool with fresh credentials (called on token refresh)."""
        with cls._pool_lock:
            if cls._pool:
                cls._pool.close(timeout=30)
                cls._pool = None
        # Next get_connection() creates new pool with new token
```

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.1 | ✅ DONE | Create `ConnectionPoolManager` class | `infrastructure/connection_pool.py` |
| S7.18.2 | ✅ DONE | Integrate with `PostgreSQLRepository._get_connection()` | `infrastructure/postgresql.py` |
| S7.18.3 | ✅ DONE | Wire token refresh to call `recreate_pool()` | `infrastructure/auth/__init__.py` |
| S7.18.4 | ✅ DONE | Add pool config env vars (`DOCKER_DB_POOL_MIN`, `DOCKER_DB_POOL_MAX`) | `infrastructure/connection_pool.py` |

**Acceptance Criteria**:
- [x] Docker mode uses connection pool (verify via health endpoint)
- [x] Function App mode unchanged (single-use connections)
- [x] Token refresh recreates pool without losing in-flight connections
- [x] Pool stats available via `ConnectionPoolManager.get_pool_stats()`

**Completed**: 16 JAN 2026

---

#### Phase 2: Checkpoint Integration (S7.18.5-7) ✅ COMPLETE (16 JAN 2026)

**Goal**: Extend existing CheckpointManager for framework integration

**NOTE**: Schema already exists! Task model has `checkpoint_phase`, `checkpoint_data`, `checkpoint_updated_at`.

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.5 | ✅ DONE | Task checkpoint schema (already exists) | `core/models/task.py` |
| S7.18.6 | ✅ DONE | CheckpointManager class (already exists) | `infrastructure/checkpoint_manager.py` |
| S7.18.7 | ✅ DONE | Add shutdown awareness methods to CheckpointManager | `infrastructure/checkpoint_manager.py` |

**Methods Added** (S7.18.7):
```python
# infrastructure/checkpoint_manager.py - IMPLEMENTED

def __init__(self, task_id, task_repo, shutdown_event=None):
    """Now accepts optional shutdown_event in constructor."""

def set_shutdown_event(self, shutdown_event: threading.Event) -> None:
    """Set shutdown event for graceful shutdown awareness."""

def is_shutdown_requested(self) -> bool:
    """Check if shutdown has been requested."""

def should_stop(self) -> bool:
    """Alias for is_shutdown_requested() - more intuitive for loops."""

def save_and_stop_if_requested(self, phase: int, data: Dict = None) -> bool:
    """Save checkpoint if shutdown requested, returns True if should stop."""
```

**Completed**: 16 JAN 2026

---

#### Phase 3: Docker Task Context (S7.18.8-11) ✅ COMPLETE (16 JAN 2026)

**Goal**: Unified context object passed to all Docker handlers

**Design**:
```python
# core/docker_context.py

@dataclass
class DockerTaskContext:
    """
    Context provided to Docker handlers.

    Wraps existing CheckpointManager with shutdown awareness and
    additional Docker-specific services.
    """

    # Core identifiers
    task_id: str
    job_id: str

    # Existing checkpoint manager (wrapped)
    checkpoint: CheckpointManager

    # Shutdown coordination
    shutdown_event: threading.Event

    def should_stop(self) -> bool:
        """Check if handler should stop (shutdown requested)."""
        return self.shutdown_event.is_set()

    def report_progress(self, percent: float, message: str = None):
        """Report progress (updates task metadata, visible in API)."""
        # Updates task record with progress info
```

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.8 | ✅ DONE | Create `DockerTaskContext` dataclass | `core/docker_context.py` |
| S7.18.9 | ✅ DONE | Modify `BackgroundQueueWorker` to create context | `docker_service.py` |
| S7.18.10 | ✅ DONE | Pass context to handlers via CoreMachine | `core/machine.py` |
| S7.18.11 | ✅ DONE | Add progress reporting to task metadata | Uses existing `update_task_metadata()` |

**Completed**: 16 JAN 2026

**Handler Migration Pattern**:
```python
# OLD PATTERN (handler creates checkpoint)
def handler(params, context):
    task_id = params.get('_task_id')
    checkpoint = CheckpointManager(task_id, repo)  # Handler creates
    if not checkpoint.should_skip(1):
        ...

# NEW PATTERN (context provides checkpoint)
def handler(params, context: DockerTaskContext):
    if context.should_stop():  # Shutdown awareness!
        return {'interrupted': True, 'resumable': True}
    if not context.checkpoint.should_skip(1):  # Checkpoint provided
        ...
```

---

#### Phase 4: Graceful Shutdown Integration (S7.18.12-15) ✅ COMPLETE (16 JAN 2026)

**Goal**: Docker worker saves checkpoint and exits cleanly on SIGTERM

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.12 | ✅ DONE | Create `DockerWorkerLifecycle` class | `docker_service.py` |
| S7.18.13 | ✅ DONE | Integrate shutdown event with `BackgroundQueueWorker` | `docker_service.py` |
| S7.18.14 | ✅ DONE | Add shutdown status to `/health` endpoint | `docker_service.py` |
| S7.18.15 | ✅ DONE | Test graceful shutdown (SIGTERM → checkpoint saved) | Manual test |

**Completed**: 16 JAN 2026

---

#### Phase 5: First Consumer - H3 Bootstrap Docker (S7.18.16-20)

**Goal**: Prove the framework with H3 bootstrap job

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.16 | 📋 | Create `bootstrap_h3_docker` job definition | `jobs/bootstrap_h3_docker.py` |
| S7.18.17 | 📋 | Create `h3_bootstrap_complete` handler (uses DockerTaskContext) | `services/handler_h3_bootstrap_complete.py` |
| S7.18.18 | 📋 | Register job and handler in `__init__.py` | `jobs/__init__.py`, `services/__init__.py` |
| S7.18.19 | 📋 | Test: Rwanda bootstrap with checkpoint/resume | Manual test |
| S7.18.20 | 📋 | Test: Graceful shutdown mid-cascade | Manual test |

---

#### Phase 6: Migrate process_raster_docker (S7.18.21-23) ✅ COMPLETE

**Status**: Complete (17 JAN 2026)
**Goal**: Migrate existing Docker raster job to use framework

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.21 | ✅ | Update `handler_process_raster_complete` to receive `DockerTaskContext` | `services/handler_process_raster_complete.py` |
| S7.18.22 | ✅ | Use `context.checkpoint` with fallback for Function App mode | `services/handler_process_raster_complete.py` |
| S7.18.23 | ✅ | Add `context.should_stop()` checks between phases | `services/handler_process_raster_complete.py` |

**Implementation Pattern** (supports both Docker and Function App modes):
```python
def process_raster_complete(params: Dict, context: Optional[Dict] = None):
    # F7.18: Use DockerTaskContext if available (Docker mode)
    docker_context = params.get('_docker_context')

    if docker_context:
        # Docker mode: use pre-configured checkpoint
        checkpoint = docker_context.checkpoint
    elif task_id:
        # Function App fallback: create manually
        checkpoint = CheckpointManager(task_id, task_repo)

    # ... phase 1 processing ...

    # F7.18: Check for graceful shutdown before Phase 2
    if docker_context and docker_context.should_stop():
        return {'success': True, 'interrupted': True, 'resumable': True}

    # ... phase 2 processing ...
```

**Key Benefits**:
- Backward compatible with Function App deployment
- Graceful shutdown saves checkpoint before exit
- Task resumes from last completed phase on next container pickup

---

#### Phase 7: Documentation (S7.18.24-26)

**Goal**: Document the framework for future Claude sessions

| Story | Status | Description | Files |
|-------|--------|-------------|-------|
| S7.18.24 | 📋 | Create `docs_claude/DOCKER_FRAMEWORK.md` | `docs_claude/DOCKER_FRAMEWORK.md` |
| S7.18.25 | 📋 | Add handler template to `JOB_CREATION_QUICKSTART.md` | `docs_claude/JOB_CREATION_QUICKSTART.md` |
| S7.18.26 | 📋 | Update `ARCHITECTURE_DIAGRAMS.md` with framework diagram | `docs_claude/ARCHITECTURE_DIAGRAMS.md` |

---

**Story Summary**:

| Phase | Stories | Status | Description |
|-------|---------|--------|-------------|
| 1 | S7.18.1-4 | ✅ DONE | Connection Pool Manager (16 JAN 2026) |
| 2 | S7.18.5-7 | ✅ DONE | Checkpoint Integration (16 JAN 2026) |
| 3 | S7.18.8-11 | ✅ DONE | Docker Task Context (16 JAN 2026) |
| 4 | S7.18.12-15 | ✅ DONE | Graceful Shutdown (16 JAN 2026) |
| 5 | S7.18.16-20 | 📋 | H3 Bootstrap Docker (first consumer) |
| 6 | S7.18.21-23 | 📋 | Migrate process_raster_docker |
| 7 | S7.18.24-26 | 📋 | Documentation |

**Total**: 26 stories across 7 phases (15 complete: Phases 1-4)

**Key Files**:
| File | Status | Purpose |
|------|--------|---------|
| `infrastructure/checkpoint_manager.py` | ✅ EXISTS | Checkpoint management |
| `infrastructure/connection_pool.py` | ✅ DONE | Connection pool manager (16 JAN 2026) |
| `core/docker_context.py` | ✅ DONE | Docker task context (16 JAN 2026) |
| `jobs/bootstrap_h3_docker.py` | 📋 NEW | H3 Docker job definition |
| `services/handler_h3_bootstrap_complete.py` | 📋 NEW | H3 consolidated handler |
| `services/handler_process_raster_complete.py` | ✅ EXISTS | Migrate to framework |
| `docs_claude/DOCKER_FRAMEWORK.md` | 📋 NEW | Framework documentation |

**Implementation Order**:
1. Phase 1 (Connection Pool) - independent, can ship first
2. Phase 2 (Checkpoint Integration) - mostly done, add shutdown awareness
3. Phase 3 (Context) - depends on Phase 2
4. Phase 4 (Shutdown) - depends on Phase 3
5. Phase 5 (H3 Job) - first consumer, uses all above
6. Phase 6 (Raster Migration) - second consumer
7. Phase 7 (Docs) - after framework proven

---
