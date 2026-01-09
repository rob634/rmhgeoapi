# Working Backlog

**Last Updated**: 09 JAN 2026 (SP12.9 NiceGUI spike complete - staying with HTMX)
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) — Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| **1** | E9 | **FATHOM Rwanda Pipeline** | ✅ | Complete! Run fathom_stac_rebuild |
| **2** | E8 | **H3 Analytics (Rwanda)** | 🚧 | H3 bootstrap running (res 3-7) |
| **3** | E7 | **Unified Metadata Architecture** | ✅ | F7.8 complete (VectorMetadata) |
| **4** | E7→E2 | **RasterMetadata Architecture** | 🔴 | F7.9: CRITICAL - STAC depends on this |
| 5 | E8 | Building Flood Exposure | 📋 | F8.7: MS Buildings → FATHOM → H3 |
| 6 | E9 | Pre-prepared Raster Ingest | 📋 | F9.8: COG copy + STAC |
| 7 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 8 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| 9 | E1 | Vector Data as API | 🚧 | F1.8: ETL Style Integration |
| — | E7 | Pipeline Builder | 📋 | F7.5: Future (after concrete implementations) |

**Focus**: Rwanda as test region for all analytics pipelines before scaling.

---

## Current Sprint Focus

### ✅ Priority 1: FATHOM Rwanda Pipeline (COMPLETE)

**Epic**: E9 Large Data Hosting
**Goal**: End-to-end FATHOM processing on Rwanda data (1,872 TIF files, 1.85 GB)
**Test Region**: Rwanda (6 tiles: s01e030, s02e029, s02e030, s03e028, s03e029, s03e030)
**Completed**: 07 JAN 2026

#### Rwanda Data Dimensions

| Dimension | Values |
|-----------|--------|
| Flood Types | FLUVIAL_DEFENDED, FLUVIAL_UNDEFENDED, PLUVIAL_DEFENDED |
| Years | 2020, 2030, 2050, 2080 |
| SSP Scenarios | SSP1_2.6, SSP2_4.5, SSP3_7.0, SSP5_8.5 (future only) |
| Return Periods | 1in5, 1in10, 1in20, 1in50, 1in100, 1in200, 1in500, 1in1000 |
| Tiles | 6 tiles covering Rwanda |

#### F9.1: FATHOM Rwanda Processing

| Story | Description | Status |
|-------|-------------|--------|
| S9.1.R1 | Add `base_prefix` parameter to `inventory_fathom_container` job | ✅ Done (07 JAN) |
| S9.1.R2 | Deploy and run inventory for Rwanda (`base_prefix: "rwa"`) | ✅ Done (07 JAN) |
| S9.1.R3 | Run Phase 1 band stacking (8 return periods → 1 COG per scenario) | ✅ Done (07 JAN) |
| S9.1.R4 | Run Phase 2 spatial merge (6 tiles → merged COGs) | ✅ Done (07 JAN) |
| S9.1.R5 | Verify outputs in silver-fathom storage | ✅ Done (07 JAN) |
| S9.1.R6 | Register merged COGs in STAC catalog | 📋 Pending |
| S9.1.R7 | Change FATHOM grid from 5×5 to 4×4 degrees | ✅ Done (06 JAN) |
| S9.1.R8 | Fix region filtering bug (source_metadata->>'region') | ✅ Done (07 JAN) |

**Completed Results (07 JAN 2026)**:
- Inventory: 6 tiles, 234 Phase 1 groups, 39 Phase 2 groups
- Phase 1: 234/234 tasks completed, 0 failures (~7 min)
- Phase 2: 39/39 tasks completed, 0 failures (~8 min)
- Total pipeline: ~17 minutes
- Performance: 33 tasks/min (Phase 1), 5 tasks/min (Phase 2)
- See: [WIKI_JOB_FATHOM_ETL.md](/docs/wiki/WIKI_JOB_FATHOM_ETL.md)

**Key Files**:
- `jobs/inventory_fathom_container.py` - Inventory job with region filtering
- `services/fathom_container_inventory.py` - Bronze scanner with region extraction
- `services/fathom_etl.py` - Core handlers with region filtering
- `jobs/process_fathom_stack.py` - Phase 1 job
- `jobs/process_fathom_merge.py` - Phase 2 job

---

### 🟡 Priority 2: H3 Analytics on Rwanda

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: H3 aggregation of FATHOM flood data for Rwanda
**Dependency**: F9.1 ✅ (FATHOM merged COGs exist in silver-fathom)
**Status**: H3 bootstrap running (08 JAN 2026)

#### F8.13: Rwanda H3 Aggregation

| Story | Description | Status |
|-------|-------------|--------|
| S8.13.1 | Seed Rwanda H3 cells (res 2-7, country-filtered) | 🔴 Stage 3 timeout |
| S8.13.1a | **Fix H3 finalize timeout** - pg_cron + autovacuum | ✅ Done (08 JAN) |
| S8.13.1b | Enable pg_cron extension in Azure Portal | 📋 |
| S8.13.1c | Run pg_cron_setup.sql on database | 📋 |
| S8.13.1d | Re-run H3 bootstrap (run_vacuum=False) | 📋 |
| S8.13.2 | Add FATHOM merged COGs to source_catalog | 📋 |
| S8.13.3 | Run H3 raster aggregation on Rwanda FATHOM | 📋 |
| S8.13.4 | Verify zonal_stats populated for flood themes | 📋 |
| S8.13.5 | Test H3 export endpoint with Rwanda data | 📋 |

**S8.13.1 Issue (08 JAN 2026)**: H3 bootstrap completed Stage 2 (114M cells inserted) but Stage 3 finalize timed out at 30 minutes. Root cause: `VACUUM ANALYZE h3.cells` on 114M rows exceeds Azure Functions timeout.

**S8.13.1a Fix (08 JAN 2026)**: Implemented pg_cron + autovacuum tuning solution:
- `services/table_maintenance.py` - Fire-and-forget VACUUM via pg_cron
- `sql/pg_cron_setup.sql` - pg_cron extension + autovacuum tuning SQL
- `handler_finalize_h3_pyramid.py` - Updated with `run_vacuum` param (default: False)
- `docs_claude/TABLE_MAINTENANCE.md` - Setup guide

See [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) for pg_cron setup steps.

**H3 Theme Structure** (flood data):
```
themes:
  flood_risk:
    - fathom_fluvial_defended_2020_1in100
    - fathom_fluvial_defended_2050_ssp245_1in100
    - fathom_pluvial_defended_2020_1in100
    ...
```

**Key Files**:
- `services/h3_aggregation/` - Aggregation handlers
- `jobs/h3_raster_aggregation.py` - Main job
- `core/models/h3_sources.py` - source_catalog entries

---

### ✅ Complete: Web Interface DRY Consolidation (v0.7.6.2)

**Epic**: E12 Interface Modernization
**Goal**: Eliminate copy-pasted CSS/JS across web interfaces to improve maintainability and provide clean template for future frontend teams
**Started**: 08 JAN 2026 | **Completed**: 09 JAN 2026
**Risk**: Low (additive CSS/JS changes, no logic changes)

#### Background

Code review identified significant DRY violations in `web_interfaces/`:
- ~30K lines across 36 interfaces
- Same CSS copied 4x (`.header-with-count`, `.action-bar`)
- Same JS function copied 3x (`filterCollections()`)
- Inconsistent method naming

**Why It Matters**: This code serves as a template for future frontend teams. Copy-paste patterns will propagate as anti-patterns.

#### F12.5: Web Interface DRY Consolidation

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S12.5.1 | Move `.header-with-count` CSS to COMMON_CSS | ✅ Done | `base.py` |
| S12.5.2 | Move `.action-bar` + `.filter-group` CSS to COMMON_CSS | ✅ Done | `base.py` |
| S12.5.3 | Remove duplicated CSS from interfaces | ✅ Done | `stac/`, `vector/` |
| S12.5.4 | Add `filterCollections()` JS to COMMON_JS | ✅ Done | `base.py` |
| S12.5.5 | Remove duplicated JS from interfaces | ✅ Done | `stac/`, `vector/` |
| S12.5.6 | Fix naming: `_generate_css` → `_generate_custom_css` | ✅ Done | `pipeline/interface.py` |
| S12.5.7 | Verify all affected interfaces render correctly | 📋 | Browser testing (post-deploy) |

#### Implementation Details

**S12.5.1 - CSS to add to COMMON_CSS**:
```css
/* Header with count badge - collection browsers */
.header-with-count {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 12px;
}
.header-with-count h1 { margin: 0; }
.collection-count {
    background: var(--ds-blue-primary);
    color: white;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 14px;
    font-weight: 600;
}
```

**S12.5.2 - CSS to add to COMMON_CSS**:
```css
/* Action bar - button + filters layout */
.action-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    gap: 16px;
}
.filter-group {
    display: flex;
    gap: 12px;
    align-items: center;
}
.filter-select {
    padding: 8px 12px;
    border: 1px solid var(--ds-gray-light);
    border-radius: 4px;
    font-size: 13px;
}
```

**S12.5.4 - JS to add to COMMON_JS**:
```javascript
/**
 * Filter collection cards by search term and optional type.
 * Requires: #search-filter input, optional #type-filter select
 * Requires: global allCollections array and renderCollections(filtered) function
 */
function filterCollections() {
    const searchTerm = (document.getElementById('search-filter')?.value || '').toLowerCase();
    const typeFilter = document.getElementById('type-filter')?.value || '';

    const filtered = allCollections.filter(c => {
        const matchesSearch = !searchTerm ||
            c.id.toLowerCase().includes(searchTerm) ||
            (c.title || '').toLowerCase().includes(searchTerm) ||
            (c.description || '').toLowerCase().includes(searchTerm);
        const matchesType = !typeFilter || c.type === typeFilter;
        return matchesSearch && matchesType;
    });

    renderCollections(filtered);
}
```

**S12.5.3/S12.5.5 - Files to clean up**:
| File | Remove CSS | Remove JS |
|------|------------|-----------|
| `stac/interface.py` | `.header-with-count`, `.action-bar`, `.filter-group`, `.filter-select` | `filterCollections()` |
| `vector/interface.py` | `.header-with-count`, `.action-bar` | `filterCollections()` |
| `stac_map/interface.py` | `.header-with-count` (if present) | Keep custom (DOM-based) |
| `h3/interface.py` | `.header-with-count` (if present) | N/A |

#### Verification Checklist

**Implementation Complete (08 JAN 2026)** - All syntax/import checks pass locally.
**Verification Complete (09 JAN 2026)** - All interfaces render correctly post-deployment.

| Interface | Status | Notes |
|-----------|--------|-------|
| `/api/interface/stac` | ✅ Pass | Header badge, search, type filter working |
| `/api/interface/vector` | ✅ Pass | Header badge, search input present |
| `/api/interface/stac-map` | ✅ Pass | Uses own DOM-based filter (as designed) |
| `/api/interface/pipeline` | ✅ Pass | Renders correctly, pipeline cards visible |

**F12.5 COMPLETE** - DRY consolidation deployed and verified.

---

### 🟢 Priority 3: Building Flood Exposure Pipeline

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: Calculate % of buildings in flood risk areas, aggregated to H3 level 7
**Dependency**: F8.13 (H3 cells for Rwanda), F9.1 ✅ (FATHOM COGs)
**Data Source**: Microsoft Building Footprints (direct download)
**Initial Scenario**: `fluvial-defended-2020` (baseline)

#### Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Load MS Building Footprints                                │
│ Input: MS Buildings GeoJSON/Parquet for Rwanda                      │
│ Output: buildings.footprints (id, centroid, h3_index_7, iso3)      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Sample FATHOM at Building Centroids                        │
│ Input: Building centroids + FATHOM COG (one scenario)              │
│ Output: buildings.flood_exposure (building_id, depth, is_flooded)  │
│ Binary: is_flooded = (flood_depth > 0)                             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Aggregate to H3 Level 7                                    │
│ SQL: GROUP BY h3_index_7                                            │
│ Output: h3.building_flood_stats                                     │
│   - total_buildings, flooded_buildings, pct_flooded                │
└─────────────────────────────────────────────────────────────────────┘
```

#### F8.7: Building Flood Exposure Job

| Story | Description | Status |
|-------|-------------|--------|
| S8.7.1 | Download MS Building Footprints for Rwanda | 📋 |
| S8.7.2 | Create `buildings` schema (footprints, flood_exposure tables) | 📋 |
| S8.7.3 | Create `BuildingFloodExposureJob` definition (4-stage) | 📋 |
| S8.7.4 | Stage 1 handler: `building_load_footprints` (GeoJSON → PostGIS) | 📋 |
| S8.7.5 | Stage 2 handler: `building_assign_h3` (centroid → H3 index) | 📋 |
| S8.7.6 | Stage 3 handler: `building_sample_fathom` (point → raster value) | 📋 |
| S8.7.7 | Stage 4 handler: `building_aggregate_h3` (SQL aggregation) | 📋 |
| S8.7.8 | End-to-end test: Rwanda + fluvial-defended-2020 | 📋 |
| S8.7.9 | Expand to all FATHOM scenarios (39 for Rwanda) | 📋 |

**Data Source**: Microsoft Building Footprints
- Download: `https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv`
- Rwanda file: ~500K buildings expected
- Format: GeoJSON with polygon footprints

**Output Schema** (`h3.building_flood_stats`):
```sql
CREATE TABLE h3.building_flood_stats (
    h3_index BIGINT,
    scenario VARCHAR(100),        -- e.g., 'fluvial-defended-2020'
    total_buildings INT,
    flooded_buildings INT,
    pct_flooded DECIMAL(5,2),     -- 0.00 to 100.00
    PRIMARY KEY (h3_index, scenario)
);
```

**Key Files** (to create):
- `jobs/building_flood_exposure.py` - Job definition
- `services/building_exposure.py` - Handlers
- `infrastructure/buildings_schema.py` - Schema DDL
- `core/models/building.py` - Pydantic models

---

### ⚪ Future: Pipeline Builder (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Generalize FATHOM pipeline to configuration-driven raster processing
**Timeline**: After FATHOM + H3 + Open Buildings working on Rwanda

#### F7.5: Pipeline Builder

| Story | Description | Status |
|-------|-------------|--------|
| S7.5.1 | Abstract FATHOM dimension parser to configuration | 📋 |
| S7.5.2 | Create `ComplexRasterPipeline` base class | 📋 |
| S7.5.3 | YAML/JSON pipeline definition schema | 📋 |
| S7.5.4 | Pipeline Builder UI (visual orchestration) | 📋 |

**Design Principle**: Build concrete implementations first (FATHOM, H3, Buildings), then extract patterns.

---

### ✅ Priority 3: Unified Metadata Architecture (Phase 2 Complete)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Pydantic-based metadata models providing single source of truth across all data types
**Design Document**: [docs/archive/METADATA.md](/docs/archive/METADATA.md) (archived)
**Status**: Phase 2 complete (09 JAN 2026)

#### F7.8: Unified Metadata Architecture

| Story | Description | Status |
|-------|-------------|--------|
| S7.8.1 | Create `core/models/unified_metadata.py` with BaseMetadata + VectorMetadata | ✅ Done (09 JAN) |
| S7.8.2 | Create `core/models/external_refs.py` with DDHRefs + ExternalRefs models | ✅ Done (09 JAN) |
| S7.8.3 | Create `app.dataset_refs` table DDL (cross-type external linkage) | ✅ Done (09 JAN) |
| S7.8.4 | Add `providers JSONB` and `custom_properties JSONB` to geo.table_metadata DDL | ✅ Done (09 JAN) |
| S7.8.5 | Refactor `ogc_features/repository.py` to return VectorMetadata model | ✅ Done (09 JAN) |
| S7.8.6 | Refactor `ogc_features/service.py` to use VectorMetadata.to_ogc_collection() | ✅ Done (09 JAN) |
| S7.8.7 | Refactor `services/service_stac_vector.py` to use VectorMetadata | ✅ Done (09 JAN) |
| S7.8.8 | Wire Platform layer to populate app.dataset_refs on ingest | ✅ Done (09 JAN) |
| S7.8.9 | Document pattern for future data types (RasterMetadata, ZarrMetadata) | ✅ Done (09 JAN) |
| S7.8.10 | Archive METADATA.md design doc to docs/archive after implementation | ✅ Done (09 JAN) |

**Phase 1 Complete (09 JAN 2026)**:
- Created `core/models/unified_metadata.py` with:
  - `Provider`, `ProviderRole` - STAC provider models
  - `SpatialExtent`, `TemporalExtent`, `Extent` - Extent models
  - `BaseMetadata` - Abstract base for all data types
  - `VectorMetadata` - Full implementation with `from_db_row()`, `to_ogc_properties()`, `to_ogc_collection()`, `to_stac_collection()`, `to_stac_item()`
- Created `core/models/external_refs.py` with:
  - `DataType` enum (vector, raster, zarr)
  - `DDHRefs`, `ExternalRefs`, `DatasetRef` - API models
  - `DatasetRefRecord` - Database record model
- Updated `core/schema/sql_generator.py` to generate `app.dataset_refs` table with indexes
- Updated `triggers/admin/db_maintenance.py` with F7.8 columns for geo.table_metadata
- Added `get_vector_metadata()` method to `ogc_features/repository.py` returning VectorMetadata model

**Key Files (Phase 1)**:
- `core/models/unified_metadata.py` - Main metadata models
- `core/models/external_refs.py` - External reference models
- `core/schema/sql_generator.py` - DDL for app.dataset_refs
- `triggers/admin/db_maintenance.py` - DDL for geo.table_metadata F7.8 columns
- `ogc_features/repository.py` - `get_vector_metadata()` method

**Phase 2 Complete (09 JAN 2026)**:
- OGC Features service uses VectorMetadata.to_ogc_collection() (S7.8.6)
- STAC vector service uses VectorMetadata for item enrichment (S7.8.7)
- Platform layer wired to populate app.dataset_refs on ingest (S7.8.8)
- Pattern documented for future RasterMetadata, ZarrMetadata (S7.8.9)
- METADATA.md archived to docs/archive/ (S7.8.10)

**Architecture**:
```
BaseMetadata (abstract)
    ├── VectorMetadata      → geo.table_metadata
    ├── RasterMetadata      → raster.cog_metadata (future E2)
    ├── ZarrMetadata        → zarr.dataset_metadata (future E9)
    └── NewFormatMetadata   → extensible for future formats

app.dataset_refs (cross-type DDH linkage)
    ├── dataset_id (our ID) + data_type
    ├── ddh_dataset_id, ddh_resource_id, ddh_version_id (typed, indexed)
    └── other_refs JSONB (future external systems)
```

**Principles**:
1. Pydantic models as single source of truth
2. Typed columns over JSONB (minimize JSONB to `providers`, `custom_properties`, `other_refs`)
3. pgstac as catalog index (populated FROM metadata tables)
4. Open/Closed Principle — extend via inheritance
5. External refs in app schema — cross-cutting DDH linkage spans all data types

**DDH Integration Flow**:
```
PlatformRequest.dataset_id  ───► app.dataset_refs.ddh_dataset_id
PlatformRequest.resource_id ───► app.dataset_refs.ddh_resource_id
PlatformRequest.version_id  ───► app.dataset_refs.ddh_version_id
```

**Enables**: E1 (Vector), E2 (Raster), E9 (Zarr), E8 (Analytics) — consistent metadata + DDH linkage across all data types.

---

### 🟡 Priority 4: RasterMetadata Architecture (IN PROGRESS)

**Epic**: E7 Pipeline Infrastructure → E2 Raster Data as API
**Goal**: RasterMetadata model providing single source of truth for STAC-based raster catalogs
**Dependency**: F7.8 ✅ (BaseMetadata, VectorMetadata pattern established)
**Status**: Phase 1 Complete (09 JAN 2026) - Models, DDL, Repository
**Priority**: CRITICAL - Raster is primary STAC use case

#### F7.9: RasterMetadata Implementation

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.1 | Create `RasterMetadata` class in `core/models/unified_metadata.py` | ✅ Done (09 JAN) |
| S7.9.2 | Create `app.cog_metadata` table DDL with typed columns | ✅ Done (09 JAN) |
| S7.9.3 | Create `RasterMetadataRepository` with CRUD operations | ✅ Done (09 JAN) |
| S7.9.4 | Implement `RasterMetadata.from_db_row()` factory method | ✅ Done (09 JAN) |
| S7.9.5 | Implement `RasterMetadata.to_stac_item()` conversion | ✅ Done (09 JAN) |
| S7.9.6 | Implement `RasterMetadata.to_stac_collection()` conversion | ✅ Done (09 JAN) |
| S7.9.7 | Refactor `service_stac_metadata.py` to use RasterMetadata | 📋 |
| S7.9.8 | Refactor `stac_catalog.py` to use RasterMetadata | 📋 |
| S7.9.9 | Wire raster ingest to populate app.cog_metadata | 📋 |
| S7.9.10 | Wire raster STAC handlers to upsert app.dataset_refs | 📋 |
| S7.9.11 | Update `fathom_stac_register` to use RasterMetadata | 📋 |
| S7.9.12 | Update `fathom_stac_rebuild` to use RasterMetadata | 📋 |

**Phase 1 Complete (09 JAN 2026)**:
- `RasterMetadata` class added to `core/models/unified_metadata.py`
- `CogMetadataRecord` model in `core/models/raster_metadata.py` for DDL
- DDL added to `sql_generator.py` (table + 5 indexes)
- `RasterMetadataRepository` in `infrastructure/raster_metadata_repository.py`
- Implements: from_db_row, to_stac_item, to_stac_collection

**Key Files**:
- `core/models/unified_metadata.py` - RasterMetadata domain model
- `core/models/raster_metadata.py` - CogMetadataRecord for DDL
- `core/schema/sql_generator.py` - Table/index generation
- `infrastructure/raster_metadata_repository.py` - CRUD operations

**RasterMetadata Fields** (beyond BaseMetadata):
```python
class RasterMetadata(BaseMetadata):
    # COG-specific fields
    cog_url: str                    # /vsiaz/ path or HTTPS URL
    container: str                  # Azure container name
    blob_path: str                  # Path within container

    # Raster properties
    width: int                      # Pixel width
    height: int                     # Pixel height
    band_count: int                 # Number of bands
    dtype: str                      # numpy dtype (uint8, int16, float32, etc.)
    nodata: Optional[float]         # NoData value
    crs: str                        # CRS as EPSG code or WKT
    transform: List[float]          # Affine transform (6 values)
    resolution: Tuple[float, float] # (x_res, y_res) in CRS units

    # Band metadata
    band_names: List[str]           # Band descriptions
    band_units: Optional[List[str]] # Units per band

    # Processing metadata
    is_cog: bool                    # Cloud-optimized GeoTIFF?
    overview_levels: List[int]      # COG overview levels
    compression: Optional[str]      # DEFLATE, LZW, etc.
    blocksize: Tuple[int, int]      # Internal tile size

    # Visualization defaults
    colormap: Optional[str]         # Default colormap name
    rescale_range: Optional[Tuple[float, float]]  # Default min/max

    # STAC extensions
    eo_bands: Optional[List[dict]]  # EO extension band metadata
    raster_bands: Optional[List[dict]]  # Raster extension metadata
```

**app.cog_metadata Table** (in existing app schema):
```sql
CREATE TABLE app.cog_metadata (
    -- Identity
    cog_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,

    -- Location
    container TEXT NOT NULL,
    blob_path TEXT NOT NULL,
    cog_url TEXT NOT NULL,

    -- Spatial
    bbox DOUBLE PRECISION[4],
    geometry GEOMETRY(Polygon, 4326),
    crs TEXT NOT NULL DEFAULT 'EPSG:4326',

    -- Raster properties
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    band_count INTEGER NOT NULL,
    dtype TEXT NOT NULL,
    nodata DOUBLE PRECISION,
    resolution DOUBLE PRECISION[2],

    -- COG properties
    is_cog BOOLEAN DEFAULT true,
    compression TEXT,
    blocksize INTEGER[2],
    overview_levels INTEGER[],

    -- Metadata
    title TEXT,
    description TEXT,
    datetime TIMESTAMPTZ,
    start_datetime TIMESTAMPTZ,
    end_datetime TIMESTAMPTZ,

    -- Band metadata (JSONB for flexibility)
    band_names TEXT[],
    eo_bands JSONB,
    raster_bands JSONB,

    -- Visualization
    colormap TEXT,
    rescale_min DOUBLE PRECISION,
    rescale_max DOUBLE PRECISION,

    -- Extensibility
    providers JSONB,
    custom_properties JSONB,

    -- STAC linkage
    stac_item_id TEXT,
    stac_collection_id TEXT,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(container, blob_path)
);

-- Indexes
CREATE INDEX idx_cog_metadata_collection ON app.cog_metadata(collection_id);
CREATE INDEX idx_cog_metadata_bbox ON app.cog_metadata USING GIST(geometry);
CREATE INDEX idx_cog_metadata_datetime ON app.cog_metadata(datetime);
```

**Why Critical**:
1. STAC is primarily a raster catalog standard
2. Current raster STAC items built ad-hoc without metadata registry
3. FATHOM, DEM, satellite imagery all need consistent metadata
4. TiTiler integration requires predictable metadata structure
5. DDH linkage for rasters depends on this

**Current Gap**:
- VectorMetadata has `geo.table_metadata` as source of truth
- Raster has NO equivalent — STAC items built directly from COG headers
- No way to query "all rasters for DDH dataset X"
- No consistent visualization defaults stored

---

## Other Active Work

### E9: Large Data Hosting

| Feature | Description | Status |
|---------|-------------|--------|
| F9.1: FATHOM ETL | Band stacking + spatial merge | 🚧 Rwanda focus |
| F9.5: xarray Service | Time-series endpoints | ✅ Complete |
| F9.6: TiTiler Services | COG + Zarr tile serving | 🚧 TiTiler-xarray deployed 04 JAN |
| F9.8: Pre-prepared Ingest | COG copy + STAC from params | 📋 After Rwanda |

### E8: GeoAnalytics Pipeline

| Feature | Description | Status |
|---------|-------------|--------|
| F8.1-F8.3 | Grid infrastructure, bootstrap, raster aggregation | ✅ Complete |
| F8.8 | Source Catalog | ✅ Complete |
| F8.9 | H3 Export Pipeline | ✅ Complete |
| F8.13 | **Rwanda H3 Aggregation** | 📋 Priority 2 |
| F8.7 | **Building Exposure Pipeline** | 📋 Priority 3 |
| F8.4 | Vector→H3 Aggregation | 📋 After buildings |
| F8.5-F8.6 | GeoParquet, Analytics API | 📋 After Rwanda |

### E2: Raster Data as API

| Story | Description | Status |
|-------|-------------|--------|
| S2.2.5 | Fix TiTiler URLs for >3 band rasters | ✅ Complete (stac_metadata_helper.py bidx handling) |
| S2.2.6 | Auto-rescale DEM TiTiler URLs | ✅ Complete (04 JAN 2026, smart dtype defaults) |
| F2.9 | STAC-Integrated Raster Viewer | 📋 |

### E3: DDH Platform Integration

| Feature | Description | Status |
|---------|-------------|--------|
| F3.1 | API Docs (Swagger UI) | ✅ Deployed |
| F3.2 | Identity (DDH service principal) | 📋 |
| F3.3 | Environments (QA/UAT/Prod) | 📋 |

### E12: Interface Modernization

| Feature | Description | Status |
|---------|-------------|--------|
| F12.1-F12.3 | Cleanup, HTMX, Migration | ✅ Complete |
| F12.3.1 | DRY Consolidation (CSS/JS dedup) | ✅ Complete (09 JAN 2026) |
| SP12.9 | NiceGUI Evaluation Spike | ✅ Complete - **Not Pursuing** |
| F12.EN1 | Helper Enhancements | 📋 Planned |
| F12.4 | System Dashboard | 📋 Planned |
| F12.5 | Pipeline Workflow Hub | 📋 Planned |
| F12.6 | STAC & Raster Browser | 📋 Planned |
| F12.7 | OGC Features Browser | 📋 Planned |
| F12.8 | API Documentation Hub | 📋 Planned |

**SP12.9 Decision (09 JAN 2026)**: Evaluated NiceGUI and decided to stay with current HTMX + hardcoded JS/HTML/CSS approach. Rationale:
- NiceGUI requires persistent WebSocket connections → incompatible with Azure Functions
- Would require separate Docker deployment (Container Apps)
- Current approach is working well, simpler architecture, no additional infrastructure needed

---

## System Diagnostics & Configuration Drift Detection

**Added**: 04 JAN 2026
**Purpose**: Capture Azure platform configuration snapshots to detect changes in corporate environments

### Background

Corporate Azure environments (ASE, VNet) have configurations that can change without warning.
The enhanced health endpoint now captures 90+ environment variables. System snapshots will
persist this data for drift detection and audit trails.

### Completed (04 JAN 2026)

| Task | Description | Status |
|------|-------------|--------|
| Database schema | `app.system_snapshots` table with Pydantic model | ✅ |
| SQL generator | Enum, table, indexes added to `sql_generator.py` | ✅ |
| Health: network_environment | Captures all WEBSITE_*/AZURE_* vars | ✅ Deployed |
| Health: instance_info | Instance ID, worker config, cold start detection | ✅ Committed |
| Scale controller logging | `SCALE_CONTROLLER_LOGGING_ENABLED=AppInsights:Verbose` | ✅ Enabled |
| Blueprint pattern investigation | Reviewed probes.py; snapshot follows same Blueprint pattern | ✅ |
| Snapshot capture service | `services/snapshot_service.py` - capture + drift detection | ✅ |
| Config hash computation | SHA256 of stable config fields for drift detection | ✅ |
| Drift diff computation | Compare current vs previous snapshot, identify changes | ✅ |
| Startup trigger | Capture snapshot in `function_app.py` after Phase 2 validation | ✅ |
| Scheduled trigger | Timer trigger (hourly) in `function_app.py` | ✅ |
| Manual trigger | `POST /api/system/snapshot` + `GET /api/system/snapshot/drift` | ✅ |
| Version bump | 0.7.2.1 → 0.7.3 | ✅ |

### Deployment Complete (06 JAN 2026)

| Task | Description | Status |
|------|-------------|--------|
| Deploy changes | Deploy v0.7.4.3 to Azure | ✅ |
| Deploy schema | Run full-rebuild to create `system_snapshots` table | ✅ |
| Verify endpoints | Scheduled trigger capturing snapshots hourly | ✅ |

### Snapshot Trigger Types

| Trigger | When | Purpose |
|---------|------|---------|
| `startup` | App cold start | Baseline for each instance |
| `scheduled` | Timer (hourly) | Detect drift over time |
| `manual` | Admin endpoint | On-demand debugging |
| `drift_detected` | Hash changed | Record moment of change |

### Key Files

| File | Purpose |
|------|---------|
| `core/models/system_snapshot.py` | Pydantic model + SnapshotTriggerType enum |
| `core/schema/sql_generator.py` | DDL generation for system_snapshots table |
| `services/snapshot_service.py` | SnapshotService + SnapshotRepository |
| `triggers/admin/snapshot.py` | Blueprint with HTTP endpoints |
| `function_app.py` | Timer trigger + startup capture (lines 2484-2504, 3352-3395) |

### Application Insights Queries

```kusto
-- Scale controller decisions
traces
| where customDimensions.Category == "ScaleControllerLogs"
| where message == "Instance count changed"
| project timestamp,
    PreviousCount = customDimensions.PreviousInstanceCount,
    NewCount = customDimensions.CurrentInstanceCount,
    Reason = customDimensions.Reason

-- Active instances in last 30 min
performanceCounters
| where timestamp > ago(30m)
| summarize LastSeen=max(timestamp) by cloud_RoleInstance
| order by LastSeen desc
```

---

## Thread Safety Investigation

**Added**: 05 JAN 2026
**Trigger**: KeyError race condition in BlobRepository when scaled to 8 instances
**Status**: Initial fix applied, broader investigation needed

### Background

With `maxConcurrentCalls: 4` and 8 instances = 32 parallel task executions, we hit race conditions in BlobRepository's container client caching. Root cause: **check-then-act pattern without locking**.

### Key Concepts (05 JAN 2026 Discussion)

| Coordination Type | Scope | Lock Mechanism | Example |
|-------------------|-------|----------------|---------|
| **Distributed** | Across instances/processes | PostgreSQL `pg_advisory_xact_lock` | "Last task turns out lights" |
| **Local** | Within single process | Python `threading.Lock` | Dict caching in singletons |

**Why PostgreSQL can't help with local coordination**: The `_container_clients` dict exists only in Python process memory. PostgreSQL can only lock things it knows about (database rows/tables).

**The race condition pattern**:
```python
# UNSAFE: Three separate bytecode ops, GIL releases between them
if key not in dict:      # ① CHECK
    dict[key] = value    # ② STORE (may trigger dict resize!)
return dict[key]         # ③ RETURN (KeyError during resize!)
```

**The fix (double-checked locking)**:
```python
# SAFE: Lock protects entire sequence
if key in dict:                    # Fast path (no lock)
    return dict[key]
with lock:                         # Slow path (locked)
    if key not in dict:            # Double-check
        dict[key] = create_value()
    return dict[key]
```

### Completed (05 JAN 2026)

| Task | Description | Status |
|------|-------------|--------|
| BlobRepository fix | Added `_instances_lock` and `_container_clients_lock` | ✅ |
| Double-checked locking | `_get_container_client()` uses fast path + locked slow path | ✅ |
| Documentation | Explained pattern in docstrings | ✅ |

### Future Investigation

| Area | Concern | Priority |
|------|---------|----------|
| Other singletons | PostgreSQLRepository, other repos - same pattern? | 🟡 Medium |
| GDAL/rasterio threading | GDAL releases GIL - potential issues with concurrent raster ops | 🟡 Medium |
| Connection pools | psycopg3 pool thread safety under high concurrency | 🟡 Medium |
| Azure SDK clients | BlobServiceClient thread safety documentation | 🟢 Low |

### Key Files

| File | What Was Fixed |
|------|----------------|
| `infrastructure/blob.py` | `_instances_lock`, `_container_clients_lock`, double-checked locking |

### Related Context

- **CoreMachine uses PostgreSQL advisory locks** for distributed coordination (see `core/state_manager.py`, `core/schema/sql_generator.py`)
- **OOM concerns** have historically limited multi-threading exploration
- **GDAL threading issues** are separate from Python GIL (GDAL has own thread pool)

---

## E4: Classification Enforcement & ADF Integration

**Added**: 07 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Make `access_level` (OUO/Public/Restricted) mandatory and prepare for ADF integration
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters

### Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

Currently `access_level` is inconsistently enforced across the codebase. This work makes it:
1. **Mandatory** at Platform API entry point
2. **Type-safe** using `AccessLevel` enum throughout
3. **Fail-fast** in pipeline tasks if somehow missing

### Current State Analysis (07 JAN 2026)

| Location | Type | Default | Required | Issue |
|----------|------|---------|----------|-------|
| `PlatformRequest` | `str` | `"OUO"` | ✅ | Not using enum |
| `AccessLevel` enum | `Enum` | N/A | N/A | Exists but unused |
| Job parameter schemas | `str` | `None` | ❌ | Loses value |
| `PlatformMetadata` dataclass | `Optional[str]` | `None` | ❌ | Loses value |
| `PlatformProperties` model | `Optional[AccessLevel]` | `None` | ❌ | Uses enum but optional |

**Key Files**:
- `core/models/stac.py:57-62` - `AccessLevel` enum definition
- `core/models/platform.py:147-151` - `PlatformRequest.access_level` field
- `triggers/trigger_platform.py` - Translation functions
- `jobs/process_raster_v2.py:92` - Job parameter schema
- `jobs/raster_mixin.py:93-98` - `PLATFORM_PASSTHROUGH_SCHEMA`
- `services/stac_metadata_helper.py:69` - `PlatformMetadata` dataclass
- `infrastructure/data_factory.py` - ADF repository (ready for testing)

### Phase 1: Enforce at Platform Level

**Goal**: Reject requests with invalid/missing classification at API entry point

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.1 | Update `PlatformRequest.access_level` to use `AccessLevel` enum | 📋 | `core/models/platform.py` |
| S4.CL.2 | Add Pydantic validator to normalize case (accept "OUO" → store as "ouo") | 📋 | `core/models/platform.py` |
| S4.CL.3 | Make `access_level` required (remove default) OR keep secure default "ouo" | 📋 | `core/models/platform.py` |
| S4.CL.4 | Update `_translate_to_coremachine()` to pass enum value (lowercase string) | 📋 | `triggers/trigger_platform.py` |
| S4.CL.5 | Add validation tests for Platform API rejection of invalid values | 📋 | `tests/` |

**Implementation Notes for S4.CL.1-3**:
```python
# core/models/platform.py - Change from:
access_level: str = Field(default="OUO", max_length=50, ...)

# To:
from core.models.stac import AccessLevel

access_level: AccessLevel = Field(
    default=AccessLevel.OUO,
    description="Data classification: public, ouo, restricted"
)

@field_validator('access_level', mode='before')
@classmethod
def normalize_access_level(cls, v):
    """Accept case-insensitive input, normalize to enum."""
    if isinstance(v, str):
        try:
            return AccessLevel(v.lower())
        except ValueError:
            raise ValueError(f"Invalid access_level '{v}'. Must be: public, ouo, restricted")
    return v
```

**Decision Point**: Keep `default=AccessLevel.OUO` (secure by default) or make truly required (no default). Recommend keeping default since OUO is the safe choice.

### Phase 2: Fail-Fast in Pipeline Tasks

**Goal**: Defense-in-depth - tasks fail immediately if access_level missing (shouldn't happen if Phase 1 works)

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.6 | Add `access_level` to job schemas with `required: True` | 📋 | `jobs/raster_mixin.py`, `jobs/process_raster_v2.py`, `jobs/process_vector.py` |
| S4.CL.7 | Add validation in STAC metadata creation (fail if missing) | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.8 | Add validation in promote handlers (data export tasks) | 📋 | `services/promote_service.py` |
| S4.CL.9 | Update `PlatformMetadata` dataclass to require access_level | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.10 | Add checkpoints logging for access_level at key stages | 📋 | Various handlers |

**Implementation Notes for S4.CL.6**:
```python
# jobs/raster_mixin.py - Update PLATFORM_PASSTHROUGH_SCHEMA:
PLATFORM_PASSTHROUGH_SCHEMA = {
    'dataset_id': {'type': 'str', 'default': None},
    'resource_id': {'type': 'str', 'default': None},
    'version_id': {'type': 'str', 'default': None},
    'access_level': {
        'type': 'str',
        'required': True,  # Now required!
        'allowed': ['public', 'ouo', 'restricted']
    },
}
```

**Implementation Notes for S4.CL.7**:
```python
# services/stac_metadata_helper.py - Add validation in augment_item():
def augment_item(self, item_dict, ..., platform: Optional[PlatformMetadata] = None, ...):
    # Fail fast if platform metadata provided but access_level missing
    if platform and not platform.access_level:
        raise ValueError(
            "access_level is required for STAC item creation. "
            "This is a pipeline bug - access_level should be set at Platform API."
        )
```

### Phase 3: ADF Integration Testing

**Goal**: Verify Python can call ADF and pass classification parameter

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.ADF.1 | Create `/api/admin/adf/health` endpoint exposing health_check() | 📋 | `triggers/admin/` |
| S4.ADF.2 | Create `/api/admin/adf/pipelines` endpoint listing available pipelines | 📋 | `triggers/admin/` |
| S4.ADF.3 | Verify ADF env vars are set (`ADF_SUBSCRIPTION_ID`, `ADF_FACTORY_NAME`) | 📋 | Azure portal |
| S4.ADF.4 | Test trigger_pipeline() with simple test pipeline (colleague creates) | 📋 | Manual test |
| S4.ADF.5 | Add access_level to ADF pipeline parameters when triggering | 📋 | Future promote job |

**ADF Test Endpoint Implementation (S4.ADF.1-2)**:
```python
# triggers/admin/adf.py (new file)
from infrastructure.data_factory import get_data_factory_repository

def adf_health(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/admin/adf/health - Test ADF connectivity."""
    try:
        adf_repo = get_data_factory_repository()
        result = adf_repo.health_check()
        return func.HttpResponse(json.dumps(result), status_code=200, ...)
    except Exception as e:
        return func.HttpResponse(json.dumps({
            "status": "error",
            "error": str(e),
            "hint": "Check ADF_SUBSCRIPTION_ID, ADF_RESOURCE_GROUP, ADF_FACTORY_NAME env vars"
        }), status_code=500, ...)
```

### Testing Checklist

After implementation, verify:

- [ ] `POST /api/platform/submit` with `access_level: "INVALID"` returns 400
- [ ] `POST /api/platform/submit` with `access_level: "OUO"` (uppercase) succeeds
- [ ] `POST /api/platform/submit` with `access_level: "ouo"` (lowercase) succeeds
- [ ] `POST /api/platform/submit` without `access_level` uses default "ouo"
- [ ] STAC items have `platform:access_level` property populated
- [ ] Job parameters include `access_level` in task parameters
- [ ] `GET /api/admin/adf/health` returns ADF status (Phase 3)

### Acceptance Criteria

**Phase 1 Complete When**:
- Platform API validates and normalizes access_level on entry
- Invalid values rejected with clear error message
- Existing Platform API tests pass

**Phase 2 Complete When**:
- Pipeline tasks fail fast if access_level missing
- All STAC items have access_level in metadata
- Checkpoints logged at key stages

**Phase 3 Complete When**:
- ADF health endpoint working
- Can list pipelines from Python
- Ready to trigger actual export pipeline (pending ADF build)

---

## Reference Data Pipelines (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Automated updates of reference datasets for spatial analysis
**Infrastructure**: Curated Datasets System (F7.1 ✅) - timer scheduler, 4-stage job, registry

### F7.2: IBAT Reference Data (Quarterly)

**Documentation**: [IBAT.md](/IBAT.md)
**Data Source**: IBAT Alliance API
**Auth**: `IBAT_AUTH_KEY` + `IBAT_AUTH_TOKEN`

| Story | Description | Status |
|-------|-------------|--------|
| S7.2.1 | IBAT base handler (shared auth) | ✅ Done |
| S7.2.2 | WDPA handler (protected areas, ~250K polygons) | ✅ Done |
| S7.2.3 | KBAs handler (Key Biodiversity Areas, ~16K polygons) | 📋 |
| S7.2.4 | Style integration (IUCN categories) | 📋 |
| S7.2.5 | Manual trigger endpoint | 📋 |

**Target Tables**: `geo.curated_wdpa_protected_areas`, `geo.curated_kbas`

### F7.6: ACLED Conflict Data (Twice Weekly)

**Documentation**: [ACLED.md](/ACLED.md)
**Data Source**: ACLED API
**Auth**: `ACLED_API_KEY` + `ACLED_EMAIL`
**Update Strategy**: `upsert` (incremental by event_id)

| Story | Description | Status |
|-------|-------------|--------|
| S7.6.1 | ACLED handler (API auth, pagination) | 📋 |
| S7.6.2 | Event data ETL (point geometry, conflict categories) | 📋 |
| S7.6.3 | Incremental updates (upsert vs full replace) | 📋 |
| S7.6.4 | Schedule config (Monday/Thursday timer) | 📋 |
| S7.6.5 | Style integration (conflict type symbology) | 📋 |

**Target Table**: `geo.curated_acled_events`

### F7.7: Static Reference Data (Manual)

| Story | Description | Status |
|-------|-------------|--------|
| S7.7.1 | Admin0 handler (Natural Earth countries) | 📋 |
| S7.7.2 | Admin1 handler (states/provinces) | 📋 |

**Target Tables**: `geo.curated_admin0`, `geo.curated_admin1`

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| S9.2.2 | E9 | Create DDH service principal | Azure AD, IAM |
| S9.2.3 | E9 | Grant blob read access | Azure RBAC |
| EN6.1 | EN6 | Docker image with GDAL/rasterio | Docker, Python |
| EN6.2 | EN6 | Container deployment | Azure, DevOps |
| F7.2.1 | E7 | Create ADF instance | Azure Data Factory |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 09 JAN 2026 | **SP12.9 NiceGUI Spike Complete** - Decision: Stay with HTMX/JS/HTML/CSS | E12 |
| 09 JAN 2026 | **F12.3.1 DRY Consolidation** - CSS/JS deduplication across interfaces | E12 |
| 09 JAN 2026 | **F7.8 Unified Metadata Architecture Phase 1** (models, schema, repository) | E7 |
| 08 JAN 2026 | **pg_cron + autovacuum implementation** (table_maintenance.py, pg_cron_setup.sql) | E8 |
| 08 JAN 2026 | H3 finalize handler updated with run_vacuum param (default: False) | E8 |
| 08 JAN 2026 | TABLE_MAINTENANCE.md documentation created | E8 |
| 08 JAN 2026 | H3 finalize timeout root cause identified: VACUUM ANALYZE on 114M rows | E8 |
| 08 JAN 2026 | h3-pg PostgreSQL extension spike: NOT available on Azure Flexible Server | E8 |
| 07 JAN 2026 | **FATHOM Rwanda Pipeline COMPLETE** (234 Phase 1 + 39 Phase 2 tasks, 0 failures) | E9 |
| 07 JAN 2026 | Region filtering bug fix (`source_metadata->>'region'` WHERE clauses) | E9 |
| 07 JAN 2026 | WIKI_JOB_FATHOM_ETL.md created (performance metrics, instance monitoring) | — |
| 05 JAN 2026 | **Docstring Review COMPLETE** (236/236 stable files, archived to docs_claude/) | — |
| 05 JAN 2026 | Thread-safety fixes for BlobRepository (concurrent pipeline support) | — |
| 05 JAN 2026 | FATHOM tile deduplication bug fix (8x duplicates) | E9 |
| 05 JAN 2026 | Database admin interface added to web_interfaces | E12 |
| 04 JAN 2026 | S2.2.5: Multi-band TiTiler URLs with bidx params | E2 |
| 04 JAN 2026 | S2.2.6: Auto-rescale for DEMs and non-uint8 rasters | E2 |
| 04 JAN 2026 | TiTiler-xarray deployed to DEV (Zarr tile serving) | E9 |
| 04 JAN 2026 | System snapshots schema (Pydantic model + DDL) | — |
| 04 JAN 2026 | Health: network_environment (90+ Azure vars) | — |
| 04 JAN 2026 | Health: instance_info (cold start detection) | — |
| 04 JAN 2026 | Scale controller logging enabled | — |
| 04 JAN 2026 | SERVICE_BUS_NAMESPACE explicit env var | — |
| 04 JAN 2026 | Version bump to 0.7.1 | — |
| 03 JAN 2026 | STARTUP_REFORM.md Phases 1-4 (livez/readyz probes) | — |
| 03 JAN 2026 | Blueprint refactor for probes.py | — |
| 30 DEC 2025 | Platform API Submit UI COMPLETE | E3 |
| 29 DEC 2025 | Epic Consolidation (E10,E11,E13,E14,E15 absorbed) | — |
| 29 DEC 2025 | F7.5 Collection Ingestion COMPLETE | E7 |
| 28 DEC 2025 | F8.12 H3 Export Pipeline COMPLETE | E8 |
| 28 DEC 2025 | F7.6 Pipeline Observability COMPLETE | E7 |
| 28 DEC 2025 | F8.8 Source Catalog COMPLETE | E8 |
| 24 DEC 2025 | F12.3 Migration COMPLETE (14 interfaces HTMX) | E12 |
| 21 DEC 2025 | FATHOM Phase 1 complete (CI), Phase 2 46/47 | E7 |

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |
| [H3_REVIEW.md](./H3_REVIEW.md) | H3 aggregation implementation |
| [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) | pg_cron + autovacuum setup |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |

---

**Workflow**:
1. ~~Complete Rwanda FATHOM pipeline (Priority 1)~~ ✅ DONE
2. Run H3 aggregation on FATHOM outputs (Priority 2) - 🚧 H3 bootstrap running
3. Building flood exposure pipeline: MS Buildings → FATHOM sample → H3 aggregation (Priority 3)
4. Generalize to Pipeline Builder (Future)
