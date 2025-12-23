# Pipeline Builder Vision

**Created**: 22 DEC 2025
**Status**: Draft - For Team Lead Review
**Purpose**: Demo application showcasing H3 analytics and pipeline orchestration

---

## Executive Summary

**The Pitch**: We've built a modern, cloud-native geospatial data platform with industry-leading capabilities. A lightweight demo "app" would showcase these capabilities to leadership, demonstrating why a proper UI investment would unlock significant value.

**Key Message**: "This is what the backend can do. Imagine what real UI developers could build on top of it."

---

## Two Parallel Tracks

### Track 1: Simple Demo (E11 - Pipeline Builder)

**User Flow**: Select dataset → Draw bbox → Get H3 GeoParquet

```
Planetary Computer ────┐
Azure Storage ─────────┼──▶ [Draw BBox] ──▶ [H3 Aggregation] ──▶ 📦 GeoParquet
FATHOM Flood ──────────┘
```

**Output**: Download-ready GeoParquet with H3 cells + stats

### Track 2: Complex Pipeline (E8.F8.7 - Building Exposure)

**User Flow**: Buildings + Raster → Point extraction → H3 aggregation

```
MS Buildings ──────┐
Google Buildings ──┼──▶ [Centroids] ──▶ [Raster Sample] ──▶ [H3 Aggregate] ──▶ 📦 GeoParquet
OSM ───────────────┘        +
                      FATHOM Flood
```

**Output**: Per-hexagon building exposure stats (count, mean, % exposed)

**See**: [BUILDING_EXPOSURE_PIPELINE.md](./BUILDING_EXPOSURE_PIPELINE.md)

---

## Buzzword Arsenal (What We Already Have)

| Capability | Status | Industry Buzzword |
|------------|:------:|-------------------|
| H3 Hexagonal Grid | ✅ Built | **Uber H3 Discrete Global Grid** |
| Multi-Resolution Pyramid | ✅ Res 2-7 | **Hierarchical Spatial Index** |
| Zonal Statistics | 🚧 Framework Ready | **Scalable Raster Analytics** |
| COG Pipeline | ✅ Production | **Cloud-Optimized GeoTIFFs** |
| STAC Catalog | ✅ Production | **SpatioTemporal Asset Catalog** |
| OGC Features | ✅ Production | **OGC API - Features** |
| OGC Styles | ✅ Production | **OGC API - Styles** |
| TiTiler Tiles | ✅ Production | **Dynamic Tile Serving** |
| Job Engine | ✅ Production | **Declarative Pipeline Orchestration** |
| xarray Time-Series | ✅ Production | **Datacube Analytics** |
| FATHOM Pipeline | 🚧 Testing | **Climate Risk Analytics** |
| Azure Managed Identity | ✅ Production | **Zero-Secret Architecture** |
| GeoParquet Export | 📋 Planned | **Columnar OLAP Analytics** |

**Translation for leadership**: "We have a production-ready platform that rivals what companies spend millions to build."

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PIPELINE BUILDER DEMO                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                     Frontend (Demo Quality)                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │ │
│  │  │  Data Source │  │   Pipeline   │  │  H3 Results  │  │  Export to  │ │ │
│  │  │   Browser    │  │   Composer   │  │    Viewer    │  │  GeoParquet │ │ │
│  │  │              │  │              │  │              │  │             │ │ │
│  │  │ • STAC Search│  │ • Job Types  │  │ • Hex Map    │  │ • Download  │ │ │
│  │  │ • Promoted   │  │ • Parameters │  │ • Drill Down │  │ • DuckDB    │ │ │
│  │  │ • Gallery    │  │ • Submit     │  │ • Time Slider│  │ • Parquet   │ │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                     │                                        │
│                                     ▼                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Backend APIs (Production Ready)                      │ │
│  │                                                                          │ │
│  │  /api/stac/*        /api/jobs/*      /api/h3/*       /api/export/*     │ │
│  │  /api/promote/*     /api/features/*  /api/raster/*   /api/xarray/*     │ │
│  │                                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Proposed Epic Structure

### Epic E11: Pipeline Builder Demo App

**Business Requirement**: Visual demonstration of platform capabilities for stakeholder engagement
**WSJF**: High (demonstrates value of existing investment, unlocks UI budget)
**Owner**: Geospatial Team (demo build) → UI Team (production build)

---

### Feature F11.1: Data Source Browser

**Purpose**: Show users what data is available for analysis

| Story | Description | Backend Dependency |
|-------|-------------|-------------------|
| S11.1.1 | STAC collection browser with search | `/api/stac/collections` ✅ |
| S11.1.2 | Promoted datasets gallery view | `/api/promote/gallery` ✅ |
| S11.1.3 | Preview thumbnails from TiTiler | TiTiler `/preview` ✅ |
| S11.1.4 | Click to view on map | TiTiler `/tiles` ✅ |

**Demo Scenario**: "Browse 47 flood risk datasets from FATHOM. Click to preview any layer on the map."

---

### Feature F11.2: Pipeline Composer

**Purpose**: Show the declarative pipeline system visually

| Story | Description | Backend Dependency |
|-------|-------------|-------------------|
| S11.2.1 | List available job types | `/api/jobs/types` (needs endpoint) |
| S11.2.2 | Visual parameter form generator | Job.parameters_schema ✅ |
| S11.2.3 | Submit pipeline and show queue position | `/api/jobs/submit/*` ✅ |
| S11.2.4 | Real-time job progress tracker | `/api/jobs/status/{id}` ✅ |

**Demo Scenario**: "Select H3 Aggregation, choose the FATHOM 100-year flood layer, pick resolution 5, click Submit. Watch it process 686,000 hexagons in under 2 minutes."

---

### Feature F11.3: H3 Analytics Viewer

**Purpose**: THE showcase feature - hexagonal analytics visualization

| Story | Description | Backend Dependency |
|-------|-------------|-------------------|
| S11.3.1 | H3 hexagon layer renderer (Mapbox GL) | `/api/h3/stats/{id}/cells` (E8.F8.6) |
| S11.3.2 | Resolution switcher (zoom → resolution mapping) | H3 pyramid ✅ |
| S11.3.3 | Click hexagon → drill to children | H3.cells + H3.cell_admin0 ✅ |
| S11.3.4 | Choropleth styling by stat value | OGC Styles ✅ |
| S11.3.5 | Country/Admin filter | `/api/h3/stats?iso3=KEN` (E8.F8.6) |
| S11.3.6 | Time slider for temporal stats | xarray service ✅ |

**Demo Scenario**: "View mean flood depth aggregated to hexagons. Click Kenya to filter. Drill from resolution 4 (500km²) to resolution 7 (5km²). Slide the timeline to see 2030, 2050, 2080 projections."

---

### Feature F11.4: Export & Interoperability

**Purpose**: Show data can leave the platform in modern formats

| Story | Description | Backend Dependency |
|-------|-------------|-------------------|
| S11.4.1 | Export H3 stats as GeoParquet | `/api/h3/export` (E8.F8.5) |
| S11.4.2 | DuckDB SQL preview | Client-side DuckDB WASM |
| S11.4.3 | Copy tile URL for use in other tools | TiTiler URLs ✅ |
| S11.4.4 | STAC item JSON download | `/api/stac/items/{id}` ✅ |

**Demo Scenario**: "Export to GeoParquet. Open in DuckDB. Run SQL: `SELECT country, AVG(flood_depth) FROM h3_stats GROUP BY country` - instant results."

---

## Demo Technology Stack (Intentionally Simple)

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Frontend** | Vanilla JS + Mapbox GL | "Demo quality" - no framework |
| **Map Tiles** | Mapbox GL JS | Industry standard, H3 plugin available |
| **H3 Rendering** | h3-js + deck.gl H3HexagonLayer | Purpose-built for hexagons |
| **Hosting** | Azure Static Web App | Free tier, no infra |
| **Backend** | Existing APIs | Already production-ready |

**Key Point**: The demo should look "rough enough" that leadership says "this is great, let's get real UI devs on it."

---

## Demo Workflow Storyboard

### Scene 1: "What Data Do We Have?"

```
┌─────────────────────────────────────────────────────────────────┐
│  📦 DATA CATALOG                                    [Search...] │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ⭐ FEATURED GALLERY                                            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ FATHOM  │ │ Sentinel│ │ WDPA    │ │ Admin0  │ │ DEM     │   │
│  │ 100-yr  │ │ NDVI    │ │ Parks   │ │ Borders │ │ Terrain │   │
│  │ [thumb] │ │ [thumb] │ │ [thumb] │ │ [thumb] │ │ [thumb] │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
│                                                                  │
│  📁 ALL COLLECTIONS (47)                                        │
│  ├── fathom-global-flood (raster) - 8 bands, 100yr-500yr       │
│  ├── wdpa-protected-areas (vector) - 280,000 features          │
│  └── ...                                                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Talking Point**: "Every dataset ingested through our ETL is cataloged in STAC and available here."

---

### Scene 2: "Let's Run an Analysis"

```
┌─────────────────────────────────────────────────────────────────┐
│  🔧 PIPELINE BUILDER                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: Select Pipeline Type                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ● H3 Raster Aggregation                                  │  │
│  │    Compute zonal statistics to hexagonal grid             │  │
│  │  ○ H3 Vector Aggregation                                  │  │
│  │  ○ Raster to COG                                          │  │
│  │  ○ Vector to PostGIS                                      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Step 2: Configure Parameters                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Source:      [fathom-global-flood     ▼]                 │  │
│  │  Band:        [band_5 (100yr)          ▼]                 │  │
│  │  Resolution:  [5 (686K cells)          ▼]                 │  │
│  │  Statistics:  [✓] mean [✓] max [ ] sum [ ] count          │  │
│  │  Filter:      [Africa (iso3 filter)    ▼]                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  [Submit Pipeline]                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Talking Point**: "No code required. Select data, set parameters, submit. The job engine handles parallelization."

---

### Scene 3: "Watch It Run"

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚡ JOB PROGRESS: h3_raster_aggregation_7a8b2c                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ████████████████████░░░░░░░░░░░░  Stage 2 of 3                │
│                                                                  │
│  Stage 1: Inventory Cells ✅ (14,832 cells in scope)            │
│  Stage 2: Compute Zonal Stats 🔄 (8,421 / 14,832)              │
│           ├─ Task batch 1-100: ✅                               │
│           ├─ Task batch 101-200: ✅                             │
│           ├─ Task batch 201-300: 🔄 processing                  │
│           └─ Task batch 301-400: ⏳ queued                      │
│  Stage 3: Finalize Registry ⏳                                  │
│                                                                  │
│  Elapsed: 47s | Est. Remaining: 23s | Workers: 4               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Talking Point**: "Our job engine splits work into parallel tasks. Watch thousands of cells process in real-time."

---

### Scene 4: "Explore the Results"

```
┌─────────────────────────────────────────────────────────────────┐
│  🌍 H3 ANALYTICS VIEWER                         [Export ▼]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Resolution: [4] [5] [6] [7]     Stat: [mean ▼]                │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │         ⬡ ⬡ ⬡                                            │  │
│  │       ⬡ ⬡ ⬡ ⬡ ⬡          AFRICA                         │  │
│  │     ⬡ ⬡ ⬡ ⬡ ⬡ ⬡ ⬡                                       │  │
│  │   ⬡ ⬡ ⬡ ⬡ ⬡ ⬡ ⬡ ⬡ ⬡      Color = Mean Flood Depth       │  │
│  │     ⬡ ⬡ ⬡ ⬡ ⬡ ⬡ ⬡                                       │  │
│  │       ⬡ ⬡ ⬡ ⬡ ⬡          [Click to drill down]          │  │
│  │         ⬡ ⬡ ⬡                                            │  │
│  │                                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Selected: Kenya (KEN)                                          │
│  ├─ Mean Flood Depth: 1.23m                                    │
│  ├─ Max Flood Depth: 4.87m                                     │
│  └─ Cell Count: 1,847                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Talking Point**: "H3 gives us resolution-independent analytics. Click any hexagon to drill down to finer detail."

---

## Dependencies & Blockers

### Must Complete Before Demo

| Dependency | Status | Blocker For |
|------------|:------:|-------------|
| E8.F8.3: H3 Raster Aggregation handlers | 🚧 | F11.3 H3 Viewer |
| E8.F8.6: H3 Analytics API | 📋 | F11.3 H3 Viewer |
| Promote API | ✅ Done | F11.1 Gallery |

### Nice to Have for Demo

| Dependency | Status | Enhances |
|------------|:------:|----------|
| E8.F8.5: GeoParquet Export | 📋 | F11.4 Export |
| E10.F10.3: FATHOM STAC | 📋 | More demo data |

---

## Resource Estimate

| Phase | Effort | Output |
|-------|--------|--------|
| **Phase 1**: H3 API completion (F8.3, F8.6) | 3-5 days | Backend ready |
| **Phase 2**: Demo frontend (F11.1-F11.4) | 5-7 days | Clickable prototype |
| **Phase 3**: Demo refinement | 2-3 days | Leadership-ready demo |
| **Total** | ~2 weeks | Demo App |

---

## Success Criteria

**Demo is successful if leadership says**:
1. "This is impressive - I want real UI developers on this."
2. "Can we show this to [external stakeholder]?"
3. "When can we have a production version?"

**Demo should NOT be**:
- Polished enough to ship to users
- A replacement for proper frontend development
- A distraction from core platform work

---

## Appendix: Backend Endpoints for Demo

### Currently Available ✅

```
GET  /api/stac/collections           # List all data
GET  /api/stac/collections/{id}      # Collection details
GET  /api/promote/gallery            # Featured datasets
GET  /api/promote/{id}               # Dataset metadata
POST /api/jobs/submit/h3_raster_aggregation
GET  /api/jobs/status/{id}           # Job progress
GET  /api/features/collections       # OGC Features
GET  /api/raster/preview?item_id=    # Quick thumbnails
```

### Needs Implementation 📋

```
GET  /api/jobs/types                 # List available job types (new)
GET  /api/h3/registry                # List H3 stat datasets (F8.6)
GET  /api/h3/stats/{id}              # Get H3 statistics (F8.6)
GET  /api/h3/stats/{id}/cells        # Get cells with values (F8.6)
POST /api/h3/export                  # Export to GeoParquet (F8.5)
```

---

## Next Steps

1. **Review with Team Lead**: Get feedback on this vision
2. **Prioritize E8**: Complete H3 analytics handlers (F8.3)
3. **Add H3 API**: Implement analytics endpoints (F8.6)
4. **Build Demo**: Create minimal frontend
5. **Demo to Leadership**: Present capabilities

---

*"It's not a website. It's a capability demonstration."*
