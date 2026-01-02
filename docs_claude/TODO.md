# Working Backlog

**Last Updated**: 31 DEC 2025
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) — Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| 🔴 1 | E9 | Large Data Hosting | 🚧 | **F9.8: Pre-prepared Raster Ingest** |
| 2 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 3 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| 4 | E4 | Data Externalization | 📋 | F4.1: Publishing Workflow |
| 5 | E9 | Large Data Hosting | 🚧 | F9.1: FATHOM Phase 2 retry |
| 6 | E7 | Pipeline Infrastructure | 🚧 | F7.2: Reference Data Pipelines |
| 7 | E8 | GeoAnalytics Pipeline | 🚧 | F8.4: Vector→H3 |
| — | E1 | Vector Data as API | 🚧 | F1.8: ETL Style Integration |
| — | E12 | Integration Onboarding | ✅ | Phase 1 Complete |

**Epic Consolidation (31 DEC 2025)**:
- ~~E5~~ → F1.7-F1.8 (OGC Styles) - now in E1
- ~~E10~~ → F9.1 (FATHOM ETL Operations) - now in E9
- ~~E11~~ → F8.10-12 (Analytics UI) - now in E8
- ~~E13~~ → F7.4 (Pipeline Observability) ✅
- ~~E14~~ → F8.9 (H3 Export Pipeline) ✅
- ~~E15~~ → F7.3 (Collection Ingestion) ✅

---

## Current Sprint Focus

### 🔴 F9.8: Pre-prepared Raster Ingest (HIGH PRIORITY)

**Epic**: E9 Large Data Hosting
**Goal**: Lightweight ingest for raster datasets already prepared as COGs (no conversion needed)
**Use Case**: Partner provides COGs; we copy to silver storage and create STAC from parameters

| Story | Description | Status |
|-------|-------------|--------|
| S9.8.1 | Design STAC structure parameter schema | 📋 |
| S9.8.2 | Create `ingest_prepared_raster` job (3-stage) | 📋 |
| S9.8.3 | Inventory handler (scan source, validate COG) | 📋 |
| S9.8.4 | Copy handler (parallel blob copy) | 📋 |
| S9.8.5 | STAC generation handler (collection + items) | 📋 |
| S9.8.6 | Support bbox/datetime from COG metadata | 📋 |
| S9.8.7 | Support custom asset naming | 📋 |

**Docs**: [E9_large_data.md](/docs/epics/E9_large_data.md#feature-f98-pre-prepared-raster-ingest--planned)

---

### E9: Large Data Hosting

| Feature | Description | Status |
|---------|-------------|--------|
| F9.1: FATHOM ETL | Band stacking + spatial merge | 🚧 46/47 tasks |
| F9.5: xarray Service | Time-series endpoints | ✅ Complete |
| F9.8: Pre-prepared Ingest | COG copy + STAC from params | 📋 HIGH PRIORITY |

**F9.1 Current Issue**: Phase 2 task `n10-n15_w005-w010` failed. Need retry with `force_reprocess=true`.
**Docs**: [FATHOM_ETL.md](./FATHOM_ETL.md)

---

### E7: Pipeline Infrastructure

| Feature | Description | Status |
|---------|-------------|--------|
| F7.3: Collection Ingestion | Pre-processed COG ingest (MapSPAM) | ✅ Complete |
| F7.4: Pipeline Observability | Real-time job metrics | ✅ Complete |
| F7.5: Pipeline Builder UI | Visual orchestration | 📋 Planned |

### E2: Raster Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| **S2.2.5** | **🔴 HIGH: Fix TiTiler URLs for >3 band rasters** | Claude | 📋 |
| **S2.2.6** | **🔴 HIGH: Auto-rescale DEM TiTiler URLs** | Claude | 📋 |
| **F2.9** | **🆕 STAC-Integrated Raster Viewer** (14 stories) | Claude | 📋 |
| F2.7 | Raster Collection Processing (pgstac searches) | Claude | 📋 |

**S2.2.5 Details** (HIGH PRIORITY): TiTiler viewer URLs fail for rasters with >3 bands because the default URL doesn't specify which bands to render. The 4th band (alpha or extra band) confuses TiTiler, but specifying `&bidx=1&bidx=2&bidx=3` works.

**Root Cause**: Raster ETL generates default viewer URLs without `bidx` parameters. Need to:
- Detect band count during raster ETL (STAC metadata extraction phase)
- For 4+ band rasters: add `&bidx=1&bidx=2&bidx=3` to viewer/preview URLs
- For WorldView-3 8-band: use `&bidx=5&bidx=3&bidx=2` (RGB mapping)
- Store band mapping in STAC item properties for downstream use

**Affected Files**:
- `services/raster_handlers.py` - STAC metadata extraction
- `models/band_mapping.py` - Band profiles (WorldView-3 added 21 DEC 2025)

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S2.2.6 | Auto-rescale DEM TiTiler URLs using p2/p98 statistics | Claude | 📋 |

**S2.2.6 Details**: DEMs render grey without proper stretch. Need to:
- Query TiTiler `/cog/statistics` for p2/p98 percentiles during STAC extraction
- Add `&rescale={p2},{p98}&colormap_name=terrain` to DEM preview/viewer URLs
- Store rescale values in STAC item properties for client use

---

### F2.9: STAC-Integrated Raster Viewer 🆕

**Created**: 30 DEC 2025
**Goal**: Create a collection-aware raster viewer (like vector viewer) that loads STAC items and generates appropriate TiTiler URLs based on raster type.
**Reference**: TiTiler URL Guide at `/rmhtitiler/docs/TITILER-URL-GUIDE.md`

#### Current State Assessment

| Component | Status | Location |
|-----------|--------|----------|
| Raster type detection | ✅ Complete | `services/raster_validation.py:835` (`_detect_raster_type()`) |
| Band count/dtype capture | ✅ Complete | `services/raster_validation.py:247` |
| ColorInterp checking | ✅ Complete | `services/raster_validation.py:871` |
| Band mapping models | ✅ Complete | `models/band_mapping.py` (WV-2/3, Sentinel-2, Landsat) |
| Statistics extraction | ⚠️ Partial | Skipped for files >1GB in `service_stac_metadata.py:188` |
| Raster type in STAC items | ❌ Missing | Detected but not persisted to item properties |
| Smart TiTiler URLs | ❌ Missing | `stac_metadata_helper.py:329` generates generic URLs only |
| Collection-aware viewer | ❌ Missing | Existing `raster-viewer` requires manual URL entry |
| Vector viewer reference | ✅ Complete | `vector_viewer/service.py` - 30/70 layout, Leaflet, OGC Features |

#### Implementation Plan

##### Phase 1: Persist Raster Metadata in STAC Items

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S2.9.1 | Add `rmh:raster_type` to STAC item properties | Claude | 📋 |
| S2.9.2 | Add `rmh:band_count` and `rmh:dtype` explicitly | Claude | 📋 |
| S2.9.3 | Add `rmh:rgb_bands` array for multi-band (e.g., `[5,3,2]` for WV-3) | Claude | 📋 |
| S2.9.4 | Add `rmh:rescale` object with p2/p98 values when stats available | Claude | 📋 |
| S2.9.5 | Add `rmh:colormap` recommendation based on raster type | Claude | 📋 |

**S2.9.1-5 Implementation Details**:

Files to modify:
- `services/service_stac_metadata.py` - Add properties after rio-stac extraction
- `services/stac_metadata_helper.py` - New method `build_raster_visualization_properties()`

Property schema:
```python
{
    "rmh:raster_type": "dem",           # rgb, rgba, dem, nir, multispectral, categorical
    "rmh:band_count": 1,
    "rmh:dtype": "float32",
    "rmh:rgb_bands": null,              # [5,3,2] for WV-3, [4,3,2] for Sentinel-2
    "rmh:rescale": {
        "min": 276.0,
        "max": 362.0,
        "source": "p2_p98"              # or "min_max", "manual"
    },
    "rmh:colormap": "terrain",          # terrain, viridis, rdylgn, null
    "rmh:colorinterp": ["gray"]         # or ["red","green","blue"], ["blue","green","red","alpha"]
}
```

##### Phase 2: Smart TiTiler URL Generation

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S2.9.6 | Create `TiTilerUrlBuilder` utility class | Claude | 📋 |
| S2.9.7 | Integrate URL builder into `stac_metadata_helper.py` | Claude | 📋 |
| S2.9.8 | Update existing STAC items via migration script (optional) | Claude | 📋 |

**S2.9.6 Implementation Details** (`services/titiler_url_builder.py`):

```python
class TiTilerUrlBuilder:
    """Generate TiTiler URLs based on raster metadata."""

    @staticmethod
    def build_viewer_url(base_url: str, cog_path: str, metadata: dict) -> str:
        """
        Build TiTiler viewer URL with appropriate parameters.

        Decision tree (from TITILER-URL-GUIDE.md):
        - 1 band + float → rescale + colormap
        - 1 band + uint8 → grayscale (no params)
        - 3 bands RGB → no params
        - 3 bands BGR → bidx=3&bidx=2&bidx=1
        - 4+ bands → bidx=1&bidx=2&bidx=3 (or custom rgb_bands)
        """
```

URL patterns by raster type:
| Type | URL Pattern |
|------|-------------|
| DEM | `?url={cog}&rescale={p2},{p98}&colormap_name=terrain` |
| RGB (3 bands) | `?url={cog}` |
| BGR (3 bands) | `?url={cog}&bidx=3&bidx=2&bidx=1` |
| RGBA (4 bands) | `?url={cog}&bidx=1&bidx=2&bidx=3` |
| WV-3 (8 bands) | `?url={cog}&bidx=5&bidx=3&bidx=2` |
| NDVI | `?url={cog}&rescale=-1,1&colormap_name=rdylgn` |

##### Phase 3: Collection-Aware Raster Viewer Interface

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S2.9.9 | Create `RasterCollectionViewerService` (like `VectorViewerService`) | Claude | 📋 |
| S2.9.10 | Create viewer endpoint `/api/raster/viewer?collection={id}` | Claude | 📋 |
| S2.9.11 | Build Leaflet UI with item browser sidebar | Claude | 📋 |
| S2.9.12 | Add band combo selector (presets + custom) | Claude | 📋 |
| S2.9.13 | Add rescale controls (auto/manual) | Claude | 📋 |
| S2.9.14 | Add colormap selector for single-band | Claude | 📋 |

**S2.9.9-14 Implementation Details**:

New files:
- `raster_collection_viewer/service.py` - Main service class
- `raster_collection_viewer/triggers.py` - HTTP trigger registration

UI Layout (30/70 like vector viewer):
```
┌─────────────────┬───────────────────────────────────────┐
│   SIDEBAR 30%   │              MAP 70%                  │
├─────────────────┤                                       │
│ 🗺️ Raster       │                                       │
│ Collection      │         [TiTiler XYZ Tiles]           │
│ Viewer          │                                       │
├─────────────────┤                                       │
│ Collection:     │                                       │
│ [aerial-2024]   │                                       │
├─────────────────┤                                       │
│ Items (12)      │                                       │
│ ┌─────────────┐ │                                       │
│ │ tile_001 ▶  │ │                                       │
│ │ tile_002    │ │                                       │
│ │ tile_003    │ │                                       │
│ └─────────────┘ │                                       │
├─────────────────┤                                       │
│ Band Selection  │                                       │
│ R: [Band 5 ▼]   │                                       │
│ G: [Band 3 ▼]   │                                       │
│ B: [Band 2 ▼]   │                                       │
│                 │                                       │
│ Presets:        │                                       │
│ [RGB] [NIR] [1] │                                       │
├─────────────────┤                                       │
│ Rescale         │                                       │
│ ○ Auto (stats)  │                                       │
│ ○ Manual        │                                       │
│ Min: [___]      │                                       │
│ Max: [___]      │                                       │
├─────────────────┤                                       │
│ Colormap        │                                       │
│ [terrain ▼]     │                                       │
├─────────────────┤                                       │
│ QA Section      │                                       │
│ [Approve][Reject│                                       │
└─────────────────┴───────────────────────────────────────┘
```

Features:
- Load STAC items from collection via `/api/stac/collections/{id}/items`
- Click item → load on map with smart TiTiler URL
- Band combo selector (populated from item's `rmh:band_count`)
- Auto-apply `rmh:rgb_bands` preset if available
- Rescale from `rmh:rescale` or manual override
- Colormap from `rmh:colormap` or selector
- Point query on click (all band values)
- QA approve/reject (future: update item metadata)

#### Dependencies

| Dependency | Required For | Status |
|------------|--------------|--------|
| S2.2.5 (bidx fix) | S2.9.6, S2.9.7 | 📋 Planned |
| S2.2.6 (DEM rescale) | S2.9.6, S2.9.7 | 📋 Planned |
| TiTiler deployment | All | ✅ Available |
| pgSTAC collections | S2.9.9-14 | ✅ Available |

#### Acceptance Criteria

1. **Metadata Persistence** (Phase 1):
   - [ ] New raster ETL jobs store `rmh:*` properties in STAC items
   - [ ] Raster type correctly identified (RGB/RGBA/DEM/NIR/multispectral)
   - [ ] Band statistics captured when file size <1GB

2. **Smart URLs** (Phase 2):
   - [ ] DEM viewer URLs include `rescale` + `colormap_name=terrain`
   - [ ] 4+ band rasters include appropriate `bidx` parameters
   - [ ] WorldView-3 uses `bidx=5&bidx=3&bidx=2`

3. **Viewer Interface** (Phase 3):
   - [ ] `/api/raster/viewer?collection={id}` returns Leaflet viewer
   - [ ] Sidebar shows collection items with click-to-load
   - [ ] Band selector populated from item metadata
   - [ ] Rescale/colormap controls functional
   - [ ] Point query returns all band values

---

### E3: DDH Platform Integration

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F3.1: API Docs | OpenAPI 3.0 spec + Swagger UI | Claude | ✅ Deployed |
| **F3.1: Validate** | Review Swagger UI, test endpoints | User | 🔍 **Review** |
| F3.2: Identity | DDH service principal setup | DevOps | 📋 |
| F3.3: Envs | QA → UAT → Prod provisioning | DevOps | 📋 |

### E9: Zarr/Climate Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F9.3: Reader Migration | Copy raster_api/xarray_api to rmhogcstac | Claude | ⬜ Ready |

### E12: Interface Modernization 🚧 ACTIVE

**Docs**: [NICEGUI.md](./NICEGUI.md)
**Goal**: Clean up interfaces, add HTMX, build Submit Vector UI

**Audit Findings (23 DEC 2025)**:
- 15 interfaces with ~3,500 LOC duplicated code
- Dashboard headers copied 9x identically
- 4 different status badge implementations
- 5 different filter/search patterns

#### Phase 1: Cleanup + HTMX (8-10 days total)

| Story | Description | Effort | Owner | Status |
|-------|-------------|--------|-------|--------|
| **F12.1: Cleanup** | | | | ✅ COMPLETE |
| S12.1.1 | CSS Consolidation → `COMMON_CSS` | 1 day | Claude | ✅ 23 DEC |
| S12.1.2 | JS Utilities → `COMMON_JS` | 0.5 day | Claude | ✅ 23 DEC |
| S12.1.3 | Python Component Helpers in `BaseInterface` | 1 day | Claude | ✅ 23 DEC |
| **F12.2: HTMX** | | | | ✅ COMPLETE |
| S12.2.1 | Add HTMX to BaseInterface | 0.5 day | Claude | ✅ 23 DEC |
| S12.2.2 | Refactor Storage Interface (HTMX) | 1 day | Claude | ✅ 23 DEC |
| S12.2.3 | Create Submit Vector Interface | 2 days | Claude | ✅ 23 DEC |
| **F12.3: Migration** | | | | ✅ COMPLETE |
| S12.3.1 | Migrate Jobs Interface (HTMX + component helpers) | 0.5 day | Claude | ✅ 24 DEC |
| S12.3.2 | Migrate Tasks Interface (HTMX) | 0.5 day | Claude | ✅ 24 DEC |
| S12.3.3 | Migrate P1 interfaces (STAC, Vector) | 1 day | Claude | ✅ 24 DEC |
| S12.3.4 | Migrate P2 interfaces (H3, Health, Pipeline) | 1 day | Claude | ✅ 24 DEC |
| S12.3.5 | Migrate P3 interfaces (platform, docs, queues, gallery, home) | 1 day | Claude | ✅ 24 DEC |

**Progress**: 14/18 interfaces HTMX-enabled (4 specialized full-page interfaces use custom HTML: map, zarr, swagger, stac-map)

#### Phase 1.5: Health Interface Enhancements

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S12.5.1 | Multi-Function App Health Display | Claude | 📋 Ready |

**S12.5.1 Details**: When `APP_MODE` indicates external workers exist (`routes_raster_externally` or `routes_vector_externally`), fetch health data from worker URLs and display additional "Function App Resources" blocks:
- Check `app_mode.details.routing` for `raster_app_url` and `vector_app_url`
- Fetch `/api/health` from each worker URL
- Render additional hardware blocks with worker name labels
- Handle errors gracefully when workers are unreachable
- Display in "Worker Environments" section below main Function App Resources

#### Phase 2: NiceGUI Evaluation (Future)

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S12.4.1-5 | NiceGUI PoC on Docker Web App | Claude | 📋 After Phase 1 |

### E8: H3 Analytics Pipeline

**Consolidated from**: E8 + E14

| Feature | Description | Status |
|---------|-------------|--------|
| F8.1-F8.3 | Grid infrastructure, bootstrap, raster aggregation | ✅ Complete |
| F8.8 | Source Catalog | ✅ Complete |
| F8.12 | H3 Export Pipeline (~~E14~~) | ✅ Complete |
| F8.4 | Vector→H3 Aggregation | ⬜ Ready |
| F8.5-F8.7 | GeoParquet, Analytics API, Building Exposure | 📋 Planned |
| F8.9-F8.11 | Pipeline Framework, Multi-Step, Rwanda Demo | 📋 Planned |

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| **S9.2.2**: Create DDH service principal | E9 | Azure AD service principal for QA | Azure AD, IAM |
| **S9.2.3**: Grant blob read access | E9 | Assign Storage Blob Data Reader | Azure RBAC |
| **S9.2.4**: Grant blob write access | E9 | Assign Storage Blob Data Contributor | Azure RBAC |
| **S9.3.2**: Document QA config | E9 | Export current config for replication | Documentation |
| **EN6.1**: Docker image | EN6 | Create image with GDAL/rasterio/xarray | Docker, Python |
| **EN6.2**: Container deployment | EN6 | Azure Container App or Web App | Azure, DevOps |
| **EN6.3**: Service Bus queue | EN6 | Create `long-running-raster-tasks` queue | Azure Service Bus |
| **EN6.4**: Queue listener | EN6 | Implement in Docker worker | Python, Service Bus SDK |
| **F7.2.1**: Create ADF instance | E7 | `az datafactory create` in rmhazure_rg | Azure Data Factory |
| **F7.3.1**: External storage account | E7 | New storage for public data | Azure Storage |
| **F7.3.2**: Cloudflare WAF rules | E7 | Rate limiting, geo-blocking | Cloudflare |

### Ready After Dependencies

| Task | Epic | Depends On | Description |
|------|------|------------|-------------|
| S9.3.3-6: UAT provisioning | E9 | S9.3.2 | Replicate QA setup to UAT |
| EN6.5: Routing logic | EN6 | EN6.1-4 | Dispatch oversized jobs to Docker worker |
| F7.2.3: Blob-to-blob copy | E7 | F7.2.1 | ADF copy activity |
| F7.2.4: Approve trigger | E7 | F7.1 | Trigger ADF from approval endpoint |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 30 DEC 2025 | **Platform API Submit UI COMPLETE** - submit-vector + submit-raster migrated to Platform API | E3 |
| 29 DEC 2025 | **Epic Consolidation** - E10,E11,E13,E14,E15 absorbed into E7/E8 | — |
| 29 DEC 2025 | **F7.5 Collection Ingestion COMPLETE** - Pre-processed COG ingest (MapSPAM) | E7 |
| 29 DEC 2025 | **Agriculture theme added** - New H3 theme for crop data | E8 |
| 28 DEC 2025 | **F8.12 H3 Export Pipeline COMPLETE** - Denormalized map exports from zonal_stats | E8 |
| 28 DEC 2025 | **F7.6 Pipeline Observability COMPLETE** - Universal metrics + H3/FATHOM contexts | E7 |
| 28 DEC 2025 | **F8.8 Source Catalog COMPLETE** - source_catalog, repository, API, dynamic tile discovery | E8 |
| 27 DEC 2025 | **Vector Workflow UI COMPLETE** - Submit Vector + Promote interfaces polished | E12 |
| 27 DEC 2025 | Timestamps standardized to Eastern Time across all interfaces | E12 |
| 27 DEC 2025 | Architecture diagram v2 created (grid layout, component mapping) | — |
| 24 DEC 2025 | **F12.3 Migration COMPLETE** - All 14 standard interfaces HTMX-enabled | E12 |
| 24 DEC 2025 | S12.3.3-5: STAC, Vector, H3, Health, Pipeline, Platform, Docs, Queues, Gallery, Home | E12 |
| 24 DEC 2025 | Jobs/Tasks interfaces migrated to HTMX (S12.3.1-2) | E12 |
| 23 DEC 2025 | F12.1 Cleanup complete (COMMON_CSS, COMMON_JS, component helpers) | E12 |
| 23 DEC 2025 | F12.2 HTMX complete (Storage + Submit Vector interfaces) | E12 |
| 23 DEC 2025 | Interface audit, E12 epic created, NICEGUI.md documentation | E12 |
| 21 DEC 2025 | F7.4 FATHOM Phase 1 complete (CI), Phase 2 46/47 tasks | E7 |
| 21 DEC 2025 | Fixed dict_row + source_container bugs in fathom_etl.py | E7 |
| 20 DEC 2025 | Swagger UI + OpenAPI spec (19 endpoints, 20 schemas) | E3.F3.1 |
| 18 DEC 2025 | OGC API Styles module | E5.F5.1 |
| 18 DEC 2025 | Service Layer API Phase 4 | E2.F2.5 |
| 12 DEC 2025 | Unpublish workflows | E1.F1.4, E2.F2.4 |
| 11 DEC 2025 | Service Bus queue standardization | EN3 |
| 07 DEC 2025 | Container inventory consolidation | — |
| DEC 2025 | PgSTAC Repository Consolidation | EN (completed) |

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |
| [docs/archive/revisions.md](/docs/archive/revisions.md) | SAFe Portfolio context (archived) |
| [HISTORY.md](./HISTORY.md) | Full completion log |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |

---

**Workflow**:
1. Pick task from "Current Sprint Focus" or "DevOps Tasks"
2. Update status here as work progresses
3. Reference EPICS.md for acceptance criteria
4. Log completion in HISTORY.md
