## Epic E2: Raster Data as API 🚧

**Type**: Business
**Value Statement**: Any imagery you have becomes analysis-ready and visualizable.
**Runs On**: E7 (Pipeline Infrastructure)
**Served By**: [E6 (Geospatial Tile Services)](E6_tile_services.md) - TiTiler for COG tile serving & pgSTAC mosaics
**Status**: 🚧 PARTIAL (F2.7 Collection + F2.8 Classification pending)
**Core Complete**: NOV 2025

**Feature Overview**:
| Feature | Status | Scope |
|---------|--------|-------|
| F2.1 | ✅ | Single Raster Pipeline |
| F2.2 | ✅ | TiTiler Integration |
| F2.3 | ✅ | STAC Cataloging |
| F2.4 | ✅ | Raster Unpublish |
| F2.5 | ✅ | Service Layer API |
| F2.6 | ✅ | Large Raster Tiling |
| F2.7 | 📋 | Raster Collection Pipeline |
| F2.8 | 📋 | Classification & Detection |
| F2.9 | ✅ | STAC-Integrated Raster Map Viewer |
| F2.10 | 🚧 | Add Rasters to Existing Collections |

### Feature F2.1: Raster ETL Pipeline ✅

**Deliverable**: `process_raster_v2` with 3-tier compression

**Enhancement**: Will integrate F2.8 (Classification) for automatic tier selection

| Story | Description |
|-------|-------------|
| S2.1.1 | Create COG conversion service |
| S2.1.2 | Implement 3-tier compression (analysis/visualization/archive) |
| S2.1.3 | Fix JPEG INTERLEAVE for YCbCr encoding |
| S2.1.4 | Add DEM auto-detection with colormap URLs |
| S2.1.5 | Implement blob size pre-flight validation |
| S2.1.6 | Create process_raster_v2 with JobBaseMixin (73% code reduction) |

**Key Files**: `jobs/process_raster_v2.py`, `services/raster_cog.py`

---

### Feature F2.2: TiTiler Integration ✅

**Deliverable**: Tile serving, previews, viewer URLs via **TiTiler Raster Service**
**Served By**: [E6.F6.1 (COG Tile Serving)](E6_tile_services.md#feature-f61-cog-tile-serving-)

| Story | Description |
|-------|-------------|
| S2.2.1 | Configure TiTiler for COG access |
| S2.2.2 | Generate viewer URLs in job results |
| S2.2.3 | Add preview image endpoints |
| S2.2.4 | Implement tile URL generation |

**Key Files**: `services/titiler_client.py`

**Note**: Tile serving is handled by the geotiler service (E6). E2 handles ETL to COG format; E6 handles tile rendering and serving.

---

### Feature F2.3: Raster STAC Integration ✅

**Deliverable**: Items registered in pgSTAC with COG assets

| Story | Description |
|-------|-------------|
| S2.3.1 | Create system-rasters collection |
| S2.3.2 | Generate STAC items with COG assets |
| S2.3.3 | Add raster-specific STAC properties |
| S2.3.4 | Integrate DDH metadata passthrough |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `services/stac_metadata.py`

---

### Feature F2.4: Raster Unpublish ✅

**Deliverable**: `unpublish_raster` job for data removal

| Story | Description |
|-------|-------------|
| S2.4.1 | Implement raster unpublish handlers |
| S2.4.2 | Create unpublish_raster job |

**Key Files**: `jobs/unpublish_raster.py`, `services/unpublish_handlers.py`

**Note**: Code complete, needs deploy + test with `dry_run=true`

---

### Feature F2.5: Raster Data Extract API ✅

**Deliverable**: Pixel-level data access endpoints (distinct from tile service)

**Access Pattern Distinction**:
| F2.2: Tile Service | F2.5: Data Extract API |
|--------------------|------------------------|
| XYZ tiles for map rendering | Pixel values for analysis |
| `/tiles/{z}/{x}/{y}` | `/api/raster/point`, `/extract`, `/clip` |
| Visual consumption | Data consumption |
| Pre-rendered, cached | On-demand, precise |

| Story | Description |
|-------|-------------|
| S2.5.1 | Create TiTiler client service |
| S2.5.2 | Create STAC client service with TTL cache |
| S2.5.3 | Implement /api/raster/extract endpoint (bbox → image) |
| S2.5.4 | Implement /api/raster/point endpoint (lon/lat → value) |
| S2.5.5 | Implement /api/raster/clip endpoint (geometry → masked image) |
| S2.5.6 | Implement /api/raster/preview endpoint (quick thumbnail) |
| S2.5.7 | Add error handling + validation |

**Key Files**: `raster_api/`, `services/titiler_client.py`, `services/stac_client.py`

---

### Feature F2.6: Large Raster Support ✅

**Deliverable**: `process_large_raster_v2` for oversized files

**Enhancement**: Will integrate F2.8 (Classification) for automatic tier selection

| Story | Description |
|-------|-------------|
| S2.6.1 | Create large raster processing job |
| S2.6.2 | Implement chunked processing strategy |

**Key Files**: `jobs/process_large_raster_v2.py`

**Note**: For files exceeding chunked processing limits, requires EN6 (Long-Running Task Infrastructure)

---

### Feature F2.7: Raster Collection Processing 📋 PLANNED

**Deliverable**: `process_raster_collection` job creating pgstac searches (unchanging mosaic URLs)

**Distinction from F2.1**:
| Aspect | F2.1: Individual TIF | F2.7: TIF Collection |
|--------|---------------------|----------------------|
| Input | Single blob | Manifest or folder |
| ETL output | Single COG + STAC item | Multiple COGs + pgstac search |
| API artifact | Item URL | **Search URL** (unchanging mosaic) |
| Use case | One-off analysis layer | Basemap/tile service |

| Story | Status | Description |
|-------|--------|-------------|
| S2.7.1 | 📋 | Design collection manifest schema |
| S2.7.2 | 📋 | Create multi-file orchestration job |
| S2.7.3 | 📋 | Implement pgstac search registration |
| S2.7.4 | 📋 | Generate stable mosaic URL in job results |
| S2.7.5 | 📋 | Add collection-level STAC metadata |

**Key Files**: `jobs/process_raster_collection.py` (planned)

**Dependency**: Requires F2.8 (Classification & Detection) for input routing

---

### Feature F2.8: Raster Classification & Detection 📋 PLANNED

**Deliverable**: Automated raster classification to inform processing mode and tier selection

**Purpose**: Cross-cutting detection logic that serves F2.1 (single), F2.6 (large), and F2.7 (collection) pipelines.

```
Raster Input → F2.8 (Classify) → Route to F2.1/F2.6/F2.7 → Tier Selection → Output
```

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S2.8.1 | 📋 | Band Metadata Extraction | Extract band count, dtype, nodata, statistics from COG/TIF header |
| S2.8.2 | 📋 | Image Type Classification | Detect: RGB, RGBA, Grayscale, Multispectral, Hyperspectral, DEM |
| S2.8.3 | 📋 | DEM Detection & Processing | Identify elevation via dtype (float32/int16) + value range; apply terrain colormap |
| S2.8.4 | 📋 | Sensor Profile Matching | Match known profiles (Landsat, Sentinel-2, WorldView-3) by band count/metadata |
| S2.8.5 | 📋 | Tier Auto-Selection | Route to Analysis/Visualization/Archive tier based on classification result |

**Classification Decision Tree**:
```
┌─────────────────────────────────────────────────────────────────┐
│                     Raster Classification                        │
├─────────────────────────────────────────────────────────────────┤
│  Band Count = 1                                                  │
│  ├── dtype float32/float64 + range [-500, 9000] → DEM           │
│  ├── dtype uint8 + range [0, 255] → Grayscale                   │
│  └── else → Single-band Analysis                                │
│                                                                  │
│  Band Count = 3                                                  │
│  ├── dtype uint8 → RGB (Visualization tier)                     │
│  └── dtype uint16/float → Multispectral (Analysis tier)         │
│                                                                  │
│  Band Count = 4                                                  │
│  ├── dtype uint8 → RGBA (Visualization tier)                    │
│  └── dtype uint16/float → Multispectral (Analysis tier)         │
│                                                                  │
│  Band Count = 8 → WorldView-3 profile                           │
│  Band Count = 10-13 → Sentinel-2 / Landsat profile              │
│  Band Count > 100 → Hyperspectral (Analysis tier)               │
└─────────────────────────────────────────────────────────────────┘
```

**Tier Selection Logic**:
| Classification | Default Tier | Compression | Notes |
|----------------|--------------|-------------|-------|
| DEM | Analysis | DEFLATE + predictor=3 | Lossless, float preservation |
| RGB/RGBA | Visualization | JPEG 85% | Lossy OK for imagery |
| Multispectral | Analysis | DEFLATE | Preserve band values |
| Hyperspectral | Archive | LZW | Balance size vs quality |
| Grayscale | Visualization | JPEG 90% | Higher quality for detail |

**Key Files**: `services/raster_classifier.py` (planned), `models/band_mapping.py` (exists)

**Existing Foundation**: `models/band_mapping.py` added 21 DEC 2025 contains WorldView-3 profile

---

### Feature F2.9: STAC-Integrated Raster Map Viewer ✅ COMPLETE

**Deliverable**: Interactive Leaflet map viewer for browsing STAC raster collections with smart TiTiler URL generation
**Uses**: [E6.F6.1 (COG Tiles)](E6_tile_services.md#feature-f61-cog-tile-serving-) + [E6.F6.4 (pgSTAC Mosaics)](E6_tile_services.md#feature-f64-pgstac-mosaic-searches-)
**Created**: 30 DEC 2025
**Completed**: 30 DEC 2025
**Reference**: TiTiler URL Guide at `/rmhtitiler/docs/TITILER-URL-GUIDE.md`

**Goal**: Create a collection-aware raster viewer (like F1.5 Vector Viewer) that loads STAC items and generates appropriate TiTiler URLs based on raster type (DEM, RGB, multi-band, etc.).

#### Phase 1: Persist Raster Metadata in STAC Items ✅

| Story | Status | Description |
|-------|--------|-------------|
| S2.9.1 | ✅ | Add `rmh:raster_type` to STAC item properties (rgb, rgba, dem, nir, multispectral) |
| S2.9.2 | ✅ | Add `rmh:band_count` and `rmh:dtype` explicitly |
| S2.9.3 | ✅ | Add `rmh:rgb_bands` array for multi-band (e.g., `[5,3,2]` for WV-3) |
| S2.9.4 | ✅ | Add `rmh:rescale` object with p2/p98 values when stats available |
| S2.9.5 | ✅ | Add `rmh:colormap` recommendation based on raster type |

**Implementation**: `RasterVisualizationMetadata` dataclass in `services/stac_metadata_helper.py`

#### Phase 2: Smart TiTiler URL Generation ✅

| Story | Status | Description |
|-------|--------|-------------|
| S2.9.6 | ✅ | Create URL builder with decision tree (`_build_titiler_url_params()`) |
| S2.9.7 | ✅ | Integrate URL builder into `stac_metadata_helper.py` |
| S2.9.8 | 📋 | Update existing STAC items via migration script (optional - future) |

**URL Patterns by Raster Type**:
| Type | URL Pattern |
|------|-------------|
| DEM (1 band float) | `?url={cog}&rescale={p2},{p98}&colormap_name=terrain` |
| RGB (3 bands) | `?url={cog}` |
| RGBA (4 bands) | `?url={cog}&bidx=1&bidx=2&bidx=3` |
| Multi-band (8+) | `?url={cog}&bidx=5&bidx=3&bidx=2` (or custom rgb_bands) |

**Implementation**: `_build_titiler_url_params()` method in `services/stac_metadata_helper.py`

#### Phase 3: Collection-Aware Raster Viewer Interface ✅

| Story | Status | Description |
|-------|--------|-------------|
| S2.9.9 | ✅ | Create `RasterCollectionViewerService` (like `VectorViewerService`) |
| S2.9.10 | ✅ | Create viewer endpoint `/api/raster/viewer?collection={id}` |
| S2.9.11 | ✅ | Build Leaflet UI with item browser sidebar (70/30 map/sidebar layout) |
| S2.9.12 | ✅ | Add band combo selector (presets + custom R/G/B dropdowns) |
| S2.9.13 | ✅ | Add rescale controls (auto from stats / manual override) |
| S2.9.14 | ✅ | Add colormap selector for single-band rasters |

**Endpoint**: `/api/raster/viewer?collection={collection_id}`

**Files**: `raster_collection_viewer/service.py`, `raster_collection_viewer/triggers.py`

**UI Features** (all implemented):
- ✅ Load STAC items from collection via `/api/stac/collections/{id}/items`
- ✅ Click item → load on map with smart TiTiler URL
- ✅ Band combo selector populated from item's band count
- ✅ Rescale controls (manual min/max input)
- ✅ Colormap dropdown for single-band rasters
- ✅ 70/30 map-left/sidebar-right layout

**Deployed**: Commit `ddebba1` (30 DEC 2025)

---

### Feature F2.10: Add Rasters to Existing Collections 🚧 IN PROGRESS

**Deliverable**: Support adding rasters to existing STAC collections instead of always creating new ones
**Added**: 12 JAN 2026
**Status**: Core implementation ✅, Platform wiring 📋

**Purpose**: Enable incremental raster additions to existing collections. Previously, each raster either auto-created a minimal collection or used the default collection. Now callers can explicitly require that a collection exists before adding.

**Use Cases**:
- Add new tiles to an existing basemap collection
- Append time-series imagery to a temporal collection
- Platform API integration where collection is pre-created

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S2.10.1 | ✅ | Add `collection_must_exist` param to `extract_stac_metadata` handler | Handler fails with clear error if collection missing and flag=true |
| S2.10.2 | ✅ | Add `collection_must_exist` to `process_raster_v2` parameters_schema | Parameter accepted in job submission |
| S2.10.3 | ✅ | Add `collection_must_exist` to `process_raster_docker` parameters_schema | Parameter accepted in Docker job |
| S2.10.4 | 📋 | Create Platform endpoint `POST /api/platform/raster/add-to-collection` | New endpoint with `collection_id` required |
| S2.10.5 | 📋 | Endpoint wrapper enforces `collection_must_exist=true` | Cannot accidentally create collection via this endpoint |
| S2.10.6 | 📋 | Update `process_raster_collection_v2` to support adding tiles to existing collection | Batch job can append to existing collection |
| S2.10.7 | 📋 | Test: `collection_must_exist=true` + existing collection → success | Raster added to existing collection |
| S2.10.8 | 📋 | Test: `collection_must_exist=true` + missing collection → clear error | Job fails with helpful message |
| S2.10.9 | 📋 | Document new parameter in API reference | Usage examples in docs |

**Usage Examples**:
```bash
# Add raster to existing collection (fails if collection doesn't exist)
curl -X POST .../api/jobs/submit/process_raster_v2 \
  -d '{"container_name": "uploads", "blob_name": "new_tile.tif",
       "collection_id": "existing-collection", "collection_must_exist": true}'

# Default behavior unchanged (auto-creates collection if missing)
curl -X POST .../api/jobs/submit/process_raster_v2 \
  -d '{"container_name": "uploads", "blob_name": "my_raster.tif"}'
```

**Key Files**:
- `services/stac_catalog.py:224,357-362` - collection_must_exist check
- `jobs/process_raster_v2.py:87` - parameter schema
- `jobs/process_raster_docker.py:90` - parameter schema

---

