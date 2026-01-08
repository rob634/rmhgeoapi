## Epic E7: Pipeline Infrastructure 🚧

**Type**: Foundational Enabler
**Value Statement**: The ETL brain that makes everything else possible.
**Status**: 🚧 PARTIAL (F7.1 ✅, F7.2 🚧, F7.3 ✅, F7.4 ✅, F7.8 📋)
**Last Updated**: 08 JAN 2026

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
| F7.8 | 📋 | **Unified Metadata Architecture** (Pydantic models, extensible) |

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

### Feature F7.2: IBAT Reference Data 🚧 PARTIAL

**Deliverable**: IBAT-sourced reference datasets (WDPA, KBAs) for spatial analysis
**Documentation**: [IBAT.md](/IBAT.md)
**Data Source**: IBAT Alliance API (https://api.ibat-alliance.org)
**Update Frequency**: Quarterly
**Auth**: Shared `IBAT_AUTH_KEY` + `IBAT_AUTH_TOKEN` env vars

| Story | Status | Description |
|-------|--------|-------------|
| S7.2.1 | ✅ | IBAT base handler (shared auth, version checking) |
| S7.2.2 | ✅ | WDPA handler (World Database on Protected Areas, ~250K polygons) |
| S7.2.3 | 📋 | KBAs handler (Key Biodiversity Areas, ~16K polygons) |
| S7.2.4 | 📋 | Style integration (IUCN categories for WDPA, KBA status) |
| S7.2.5 | 📋 | Manual trigger endpoint (currently placeholder) |

**Key Files**:
- `services/curated/wdpa_handler.py` (reference implementation)
- `core/models/curated.py`
- `infrastructure/curated_repository.py`

**Target Tables**:
- `geo.curated_wdpa_protected_areas`
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

### Feature F7.8: Unified Metadata Architecture 📋 PRIORITY

**Deliverable**: Pydantic-based metadata models providing single source of truth across all data types
**Status**: 📋 PLANNED
**Design Document**: [METADATA.md](/METADATA.md)
**Added**: 08 JAN 2026

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
| S7.8.1 | 📋 | Create `core/models/unified_metadata.py` with BaseMetadata + VectorMetadata |
| S7.8.2 | 📋 | Create `core/models/external_refs.py` with DDHRefs + ExternalRefs models |
| S7.8.3 | 📋 | Create `app.dataset_refs` table DDL (cross-type external linkage) |
| S7.8.4 | 📋 | Add `providers JSONB` and `custom_properties JSONB` to geo.table_metadata DDL |
| S7.8.5 | 📋 | Refactor `ogc_features/repository.py` to return VectorMetadata model |
| S7.8.6 | 📋 | Refactor `ogc_features/service.py` to use VectorMetadata.to_ogc_response() |
| S7.8.7 | 📋 | Refactor `services/stac_vector_catalog.py` to use VectorMetadata.to_stac_item() |
| S7.8.8 | 📋 | Wire Platform layer to populate app.dataset_refs on ingest |
| S7.8.9 | 📋 | Document pattern for future data types (RasterMetadata, ZarrMetadata) |
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
