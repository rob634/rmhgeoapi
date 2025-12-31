## Epic E7: Pipeline Infrastructure 🚧

**Business Requirement**: Generic pipeline orchestration infrastructure (enabler for E8 and E9)
**Status**: 🚧 PARTIAL (F7.1 ✅, F7.3 ✅, F7.4 ✅)
**Last Updated**: 30 DEC 2025

**Strategic Context**:
> E7 provides generic pipeline infrastructure that enables E8 (GeoAnalytics) and E9 (Large Data).
> Domain-specific pipelines (FATHOM, CMIP6) are now in E9. H3 analytics pipelines are in E8.
> E7 focuses on: job orchestration, ingestion patterns, observability, and pipeline builder UI.

**Feature Summary**:
| Feature | Status | Description |
|---------|--------|-------------|
| F7.1 | ✅ | Pipeline Infrastructure (registry, scheduler) |
| F7.2 | 📋 | Reference Data Pipelines (Admin0, WDPA) |
| F7.3 | ✅ | Collection Ingestion Pipeline (~~E15~~) |
| F7.4 | ✅ | Pipeline Observability (~~E13~~) |
| F7.5 | 📋 | Pipeline Builder UI |

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

### Feature F7.2: Reference Data Pipelines 📋 PLANNED

**Deliverable**: Common reference datasets for spatial joins

| Story | Status | Description |
|-------|--------|-------------|
| S7.2.1 | 📋 | Admin0 handler (Natural Earth boundaries) |
| S7.2.2 | 📋 | WDPA updates (protected areas) |
| S7.2.3 | 📋 | Style integration (depends on E5) |

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

---
