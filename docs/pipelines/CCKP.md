# CCKP Backend Modernization - SAFe Planning Document

**Last Updated**: 04 JAN 2026
**Document Type**: Internal Working Document (Solution Architecture)
**Audience**: DDHGeo Team + Solution Architect
**Purpose**: Map CCKP requirements to platform capabilities, identify gaps, inform client proposal

> ⚠️ **IMPORTANT**: All implementation status refers to **DEV environment only**.
> Nothing has been promoted to QA/UAT. Client-facing estimates must account for
> environment promotion, testing, and hardening.

---

## SAFe Hierarchy

```
Portfolio Level
    └── Epic: CCKP Backend Modernization
            │
Program Level (ART)
            │
            │  PHASE 1 (MVP)
            ├── Feature: F1 - Climate Data Visualization Service
            ├── Feature: F2 - Tabular Data API
            ├── Feature: F3 - STAC Catalog Exposure
            ├── Feature: F4 - Data Download Service
            │
            │  PHASE 2 (Risk Analytics)
            ├── Feature: F5 - At-Risk Population Analysis
            │
            │  ENABLERS (Architectural Runway)
            ├── Enabler: EN1 - Geospatial Storage Consolidation
            ├── Enabler: EN2 - VirtualiZarr Pipeline for Legacy NetCDF
            ├── Enabler: EN3 - Automated Boundary Aggregation Pipeline
            └── Enabler: EN4 - H3 Analytics Backbone
                    │
Team Level
                    └── Stories & Spikes
```

---

## Epic Definition

| Field | Value |
|-------|-------|
| **Epic Name** | CCKP Backend Modernization |
| **Solution Intent** | Modernize climate data platform with cloud-native architecture enabling scalable visualization, API access, and analytics |
| **Business Outcome** | Economists and researchers can query, visualize, and download climate data without infrastructure bottlenecks |
| **Leading Indicators** | API response times, download completion rates, WMS request throughput |
| **Phase 1 MVP** | TiTiler serving Zarr + Tabular API for Admin 0/1 + STAC catalog exposure + Data downloads |
| **Phase 2 Target** | At-Risk Population Analysis - H3-based risk indicators combining climate/flood hazards with building/population exposure |

---

## Platform Implementation Mapping

> This section maps CCKP requirements to existing platform implementation.
> **All status reflects DEV environment only** - QA/UAT promotion not yet performed.

### Features Mapping

| CCKP Feature | Platform Coverage | DEV Status | Gap / Remaining Work |
|--------------|-------------------|------------|----------------------|
| **F1: Climate Data Visualization** | F9.3 VirtualiZarr + F9.6 TiTiler Services | 🚧 Partial | TiTiler-xarray deployed ✅; VirtualiZarr pipeline not built |
| **F2: Tabular Data API** | E1 OGC Features (partial) | 🚧 Partial | OGC Features exists but Admin 0/1/2 aggregation schema is CCKP-specific - needs design |
| **F3: STAC Catalog Exposure** | F2.3 Raster STAC + pgSTAC | ✅ DEV Complete | Infrastructure exists; need CCKP-specific collections + population |
| **F4: Data Download Service** | EN1 Job Orchestration + F8.9 H3 Export | ✅ DEV Complete | Orchestrator + async job pattern exists; need CCKP-specific download handlers |
| **F5: At-Risk Population Analysis** | E8 (F8.3, F8.4, F8.7) + E9 (F9.3, F9.4) | 📋 Blocked | Phase 2 - requires substantial runway (see Enabler Dependencies) |

### Enablers Mapping

| CCKP Enabler | Platform Coverage | DEV Status | Gap / Remaining Work |
|--------------|-------------------|------------|----------------------|
| **EN1: Storage Consolidation** | Bronze/Silver Storage (EN2, EN3) | ✅ DEV Complete | Architecture exists; CCKP containers to be provisioned |
| **EN2: VirtualiZarr Pipeline** | F9.3 VirtualiZarr Pipeline | 📋 Planned | Not implemented - key dependency for F1 |
| **EN3: Boundary Aggregation** | F8.3 Raster→H3 Aggregation (partial) | 🚧 Partial | H3 zonal stats exists; boundary-triggered recalc is new |
| **EN4: H3 Analytics Backbone** | E8 GeoAnalytics (F8.1-F8.9) | 🚧 Partial | Core H3 infrastructure complete; building exposure (F8.7) planned |

### Infrastructure Already Built (DEV)

| Component | Platform Location | What It Does | CCKP Benefit |
|-----------|-------------------|--------------|--------------|
| **Job Orchestrator** | EN1 | Async job queue, status polling, retry logic | Direct reuse for Data Download Service |
| **pgSTAC Catalog** | F2.3 | STAC API with spatial/temporal queries | Direct reuse for STAC Catalog Exposure |
| **H3 Grid Infrastructure** | F8.1-F8.3 | Normalized H3 schema, zonal stats, batch processing | Foundation for H3 Analytics Backbone |
| **xarray Service** | F9.5 | Time-series endpoints for multidimensional data | Partial coverage for Tabular API |
| **TiTiler COG Service** | F2.2, F9.6 | Tile serving for COGs | ✅ COG + xarray (Zarr) both deployed |
| **Bronze/Silver Storage** | EN2, EN3 | Governed blob storage with RBAC | Direct reuse for storage consolidation |

### What's NOT Built Yet

| Component | Why It's Missing | Effort Estimate (Rough) |
|-----------|------------------|-------------------------|
| **VirtualiZarr pipeline** | F9.3 planned but not started | New job type + handlers |
| **Admin 0/1/2 aggregation schema** | CCKP-specific requirement | Schema design + ETL |
| **Boundary change detection** | New requirement from CCKP | Event-driven pipeline |
| **CCKP STAC collections** | Need to define collection structure | Config + population job |

---

## Features (Phase 1 PI)

### Feature 1: Climate Data Visualization Service

| Field | Value |
|-------|-------|
| **Benefit Hypothesis** | Cloud-native tile serving will support 10+ concurrent map requests per user session with sub-second response times |
| **Acceptance Criteria** | Tile serving functional for all climate visualization layers via Zarr or VirtualiZarr references |
| **Enabler Dependencies** | Geospatial Storage Consolidation, VirtualiZarr Pipeline |
| **Platform Mapping** | F9.3 + F9.6 |
| **DEV Status** | 🚧 Partial - TiTiler-xarray deployed |

**Stories:**

- ~~Deploy TiTiler-xarray tile serving component~~ ✅ Complete
- Configure connections to consolidated storage (native Zarr + VirtualiZarr references)
- Implement tile caching layer
- Validate compatibility with existing client applications (spike)
- Load testing at expected scale

---

### Feature 2: Tabular Data API

| Field | Value |
|-------|-------|
| **Benefit Hypothesis** | PostgreSQL/PostGIS-backed API will return Admin 2 queries in <5 seconds, supporting concurrent analyst workflows |
| **Acceptance Criteria** | REST endpoints for Admin 0/1/2, watershed, EEZ with variable/scenario/time filtering |
| **Enabler Dependencies** | Geospatial Storage Consolidation, data source clarification |
| **Platform Mapping** | E1 OGC Features (partial), F9.5 xarray Service |
| **DEV Status** | 🚧 Partial - OGC Features exists, aggregation schema needed |

**Stories:**

- Design PostgreSQL/PostGIS schema for aggregated statistics
- Implement REST endpoints (Function App)
- Connection pooling and query optimization
- CSV/JSON response formatting
- API documentation (OpenAPI spec)

---

### Feature 3: STAC Catalog Exposure

| Field | Value |
|-------|-------|
| **Benefit Hypothesis** | Users can discover and access data files via standard STAC queries |
| **Acceptance Criteria** | STAC API with spatial, temporal, and metadata filters |
| **Enabler Dependencies** | Geospatial Storage Consolidation |
| **Platform Mapping** | F2.3 Raster STAC + pgSTAC infrastructure |
| **DEV Status** | ✅ Infrastructure complete - CCKP collections to be configured |

**Stories:**

- Extend existing pgSTAC for CCKP collections
- Expose STAC FastAPI endpoints
- Catalog population pipeline for Zarr assets
- Documentation for data consumers

---

### Feature 4: Data Download Service

| Field | Value |
|-------|-------|
| **Benefit Hypothesis** | Users can download filtered datasets (variable/time/boundary combinations) without timeout failures |
| **Acceptance Criteria** | Sync downloads for small requests, async job queue for large requests with status polling |
| **Enabler Dependencies** | Tabular API, existing orchestrator |
| **Platform Mapping** | EN1 Job Orchestration + F8.9 H3 Export pattern |
| **DEV Status** | ✅ Pattern exists - need CCKP-specific handlers |

**Stories:**

- Implement size estimation logic
- Sync download endpoint
- Async job submission endpoint
- Job status polling endpoint
- Download link generation
- Integrate with existing orchestrator

---

## Features (Phase 2 PI)

### Feature 5: At-Risk Population Analysis

| Field | Value |
|-------|-------|
| **Benefit Hypothesis** | Pre-computed H3-based risk indicators enable instant queries for "buildings/population at risk" without per-request compute |
| **Acceptance Criteria** | API returns risk indicators (exposed buildings, affected population) by H3 cell for any supported hazard/climate scenario combination |
| **Phase** | Phase 2 - requires substantial architectural runway |
| **Platform Mapping** | E8 GeoAnalytics (F8.3, F8.4, F8.7) + E9 Large Data (F9.3, F9.4) |
| **DEV Status** | 📋 Blocked on enablers |

**What This Feature Delivers:**

Pre-computed risk indicators at H3 cell level combining:
- **Climate hazards**: CMIP6 temperature/precipitation extremes, derived indicators
- **Flood hazards**: FATHOM depth/extent by return period and scenario
- **Exposure assets**: Building footprints (MS/Google Open Buildings), population (WorldPop)
- **External data**: Any COG/Zarr from Planetary Computer or consolidated storage

**Output per H3 Cell:**
```
{
  "h3_index": "8a2a1072b59ffff",
  "resolution": 7,
  "building_count": 1247,
  "population_estimate": 4892,
  "flood_risk": {
    "fathom_fluvial_1in100_baseline": {
      "buildings_exposed": 89,
      "pct_buildings_exposed": 7.1,
      "mean_depth_m": 0.45
    },
    "fathom_fluvial_1in100_ssp585_2050": {
      "buildings_exposed": 142,
      "pct_buildings_exposed": 11.4,
      "mean_depth_m": 0.67
    }
  },
  "climate_risk": {
    "days_above_35c_ssp585_2050": 47,
    "drought_index_ssp585_2050": 0.72
  }
}
```

**Stories:**

- Design H3 risk indicator schema (hazard × exposure × scenario matrix)
- Implement building footprint → H3 aggregation pipeline
- Implement population → H3 aggregation pipeline
- Implement FATHOM flood → building exposure join
- Implement CMIP6 climate → population exposure join
- Create risk indicator query API (`/api/risk/h3/{cell_id}`)
- Create bulk export endpoint (GeoParquet with all indicators)

**Enabler Dependencies (Architectural Runway):**

This feature requires **all** of the following enablers to be complete:

| Enabler | Purpose | Status |
|---------|---------|--------|
| EN1: Storage Consolidation | Store processed outputs | ✅ DEV Complete |
| EN2: VirtualiZarr Pipeline | Access CMIP6 NetCDF without conversion | 📋 Not started |
| EN3: Boundary Aggregation | Reaggregate when admin boundaries change | 🚧 Partial |
| EN4: H3 Analytics Backbone | Core H3 grid + zonal stats infrastructure | 🚧 Partial |
| F8.3: Raster→H3 Aggregation | FATHOM/CMIP6 → H3 zonal stats | ✅ DEV Complete |
| F8.4: Vector→H3 Aggregation | Buildings/points → H3 counts | 📋 Planned |
| F8.7: Building Exposure Analysis | Buildings × raster value extraction | 📋 Planned |
| F9.4: CMIP6 Data Hosting | Access to climate projections | 📋 Planned |

**Runway Assessment:**

| Component | Runway Status | Gap |
|-----------|---------------|-----|
| H3 grid infrastructure | ✅ Built | — |
| Raster zonal stats | ✅ Built | — |
| Vector aggregation | 📋 Planned | F8.4 needed |
| Building exposure | 📋 Planned | F8.7 needed |
| CMIP6 access | 📋 Planned | F9.3/F9.4 needed |
| FATHOM access | 🚧 Partial | F9.1 Rwanda complete, need scaling |
| Population data | 📋 Not started | WorldPop ingestion needed |
| Risk indicator schema | 📋 Not started | Design work needed |

**External Data Sources:**

| Source | Type | Access Method | License |
|--------|------|---------------|---------|
| MS Building Footprints | Vector | Planetary Computer | ODbL |
| Google Open Buildings | Vector | GCS public bucket | CC-BY-4.0 |
| WorldPop | Raster (COG) | Planetary Computer / direct | CC-BY-4.0 |
| FATHOM | Raster (COG) | Licensed - Consolidated Storage | Commercial |
| CIL-GDPCIR (CMIP6) | Zarr | Planetary Computer | CC0 / CC-BY-4.0 |
| NASA NEX-GDDP-CMIP6 | NetCDF | Planetary Computer | CC-BY-SA-4.0 |

---

## Enablers

### Enabler: Geospatial Storage Consolidation

| Field | Value |
|-------|-------|
| **Type** | Infrastructure Enabler |
| **Description** | Consolidate geospatial data assets into governed Azure Storage with standardized access controls and cataloging |
| **Architectural Runway** | Foundation for all CCKP features |
| **Platform Mapping** | EN2 Database Architecture + EN3 Azure Platform Integration |
| **DEV Status** | ✅ Architecture exists - CCKP containers to be provisioned |

#### Storage Consolidation Objectives

Establish a single, governed storage tier for geospatial data assets with consistent access controls, audit capabilities, and catalog integration.

**Current State:**
```
┌─────────────────────────────────────────────────────────────┐
│  DISTRIBUTED STORAGE (Multiple Locations)                   │
│                                                              │
│  • Data assets across multiple storage accounts/regions     │
│  • Varying access control configurations                    │
│  • Limited provenance tracking                              │
│  • Mixed formats requiring format-specific handling         │
│  • Cross-cloud data transfer costs                          │
│  • Manual discovery processes                               │
└─────────────────────────────────────────────────────────────┘
```

**Target State:**
```
┌─────────────────────────────────────────────────────────────┐
│  CONSOLIDATED AZURE STORAGE                                 │
│                                                              │
│  • Centralized storage with role-based access control       │
│  • Comprehensive audit logging via Azure Monitor            │
│  • Authoritative source for each dataset                    │
│  • Cloud-optimized formats (Zarr, COG, GeoParquet)          │
│  • Collocated with compute resources                        │
│  • STAC catalog for programmatic discovery                  │
│  • Reference files for legacy formats (no conversion)       │
└─────────────────────────────────────────────────────────────┘
```

**Consolidation Approach:**

| Data Source | Approach | Outcome |
|-------------|----------|---------|
| External cloud storage (raw files) | Generate reference files where applicable | Access via references without data movement |
| External cloud storage (processed) | Migrate to Azure Storage containers | Governed, cataloged assets |
| Legacy formats (NetCDF) | VirtualiZarr reference generation | Cloud-native access without conversion |
| Planetary Computer datasets | Access in place via STAC API | No migration required |

**Key Principles:**

- Geospatial storage maintained separately from other organizational data stores
- Azure Blob Storage with role-based access control
- Object storage optimized for cloud-native geospatial formats
- Geospatial team maintains governance authority over storage architecture
- Prefer in-place access for externally-hosted public datasets

**Stories:**

- Inventory existing data assets across storage locations
- Provision Azure Storage containers with appropriate access controls
- Develop data consolidation plan with stakeholder input
- Implement ingestion validation pipeline
- Generate VirtualiZarr references for legacy NetCDF assets (see EN2)
- Transition data access from legacy storage to consolidated storage
- Document storage governance procedures

---

### Enabler: VirtualiZarr Pipeline for Legacy NetCDF

| Field | Value |
|-------|-------|
| **Type** | Architecture Enabler |
| **Description** | Generate lightweight reference files enabling cloud-native access to existing NetCDF files without data conversion or duplication |
| **Architectural Runway** | Enables F1 (Climate Data Visualization) without format migration |
| **Platform Mapping** | F9.3 VirtualiZarr Pipeline |
| **DEV Status** | 📋 Not started |

**How It Works:**

```
Existing NetCDF files (current storage locations)
    ↓
VirtualiZarr scans byte offsets / chunk structure
    ↓
Reference files generated (JSON or Parquet, minimal size)
    ↓
Tile service reads references → serves tiles from original files
```

**Benefits:**

- No data duplication required
- Reference files are minimal size (KB vs TB)
- Incremental processing as needed
- Regenerate references when source files update
- Industry-standard approach (kerchunk-based)

**Stories:**

- Validate VirtualiZarr reference generation for existing NetCDF structure (spike)
- Implement reference generation pipeline
- Store references in consolidated storage
- Register references in STAC catalog
- Configure tile service to consume references

---

### Enabler: Automated Boundary Aggregation Pipeline

| Field | Value |
|-------|-------|
| **Type** | Infrastructure Enabler |
| **Description** | Automated pipeline to recalculate climate statistics when administrative boundaries are updated (2-4 updates/year for Admin 1/2) |
| **Architectural Runway** | Ensures aggregated statistics stay current with boundary changes without manual intervention |
| **Platform Mapping** | F8.3 Raster→H3 Aggregation (partial foundation) |
| **DEV Status** | 🚧 H3 zonal stats exists; boundary-triggered recalc is new |

**Trigger Events:**

- Admin 0/1/2 boundary updates (World Bank official boundaries)
- Watershed boundary updates
- EEZ boundary updates
- New climate data releases (if applicable)

**Pipeline Flow:**

```
Boundary Update Event (or scheduled trigger)
    ↓
Identify affected regions / delta from previous boundaries
    ↓
Queue zonal stats jobs (existing orchestrator)
    ↓
Aggregate climate variables to new boundaries
    ↓
Update PostgreSQL/PostGIS statistics tables
    ↓
Invalidate/regenerate affected API cache
```

**Stories:**

- Boundary change detection logic (compare incoming vs stored geometries)
- Integration with existing ETL orchestrator
- Incremental vs full recalculation decision logic
- Notification/logging for completed updates
- Scheduling configuration (on-demand + periodic validation)

---

### Enabler: H3 Analytics Backbone (Phase 2 Runway)

| Field | Value |
|-------|-------|
| **Type** | Architecture Enabler |
| **Description** | Pre-compute zonal statistics to H3 grid as canonical unit for flexible aggregation |
| **Architectural Runway** | Enables Phase 2 "at-risk population" and custom polygon analytics without per-request compute |
| **Platform Mapping** | E8 GeoAnalytics Pipeline (F8.1-F8.9) |
| **DEV Status** | 🚧 Core H3 infrastructure complete; F8.7 Building Exposure planned |

**Architecture Concept:**

```
Building Footprints (Open Buildings default, pluggable)
    ↓
Zonal Stats (FATHOM / WorldPop / CMIP6 slices)
    ↓
H3 Grid (canonical unit, pre-computed)
    ↓
Any Output: Admin2 / Watershed / EEZ / Custom Polygon
```

**Stories (Phase 2 PI):**

- Building footprint ingestion (Open Buildings default)
- Zonal stats pipeline (FATHOM, WorldPop, CMIP6)
- H3 aggregation and storage
- Polygon overlay query API

---

## Spikes (Uncertainty Reduction)

| Spike | Timebox | Question to Answer |
|-------|---------|-------------------|
| **Data Source Clarification** | 1 day | What processing has been applied to existing climate data? Are outputs derived products or subsets of standard CMIP6? |
| **VirtualiZarr Compatibility** | 2 days | Can VirtualiZarr generate valid references for existing NetCDF structure? Any edge cases with variable/dimension naming? |
| **Zonal Statistics Benchmark** | 2-3 days | What are response times for Admin 2 / country / continent polygon queries? Determines sync vs async boundary |
| **Client Compatibility** | 2 days | Can TiTiler serve OGC-compliant WMS for existing client applications? |
| **Capacity Planning** | 1 day | Can current Azure infrastructure handle expected load, or is additional capacity required? |

---

## PI Planning View

### Phase 1 PI (10 weeks - MVP)

Assuming 10-week PI with 5 x 2-week iterations:

| Iteration | Focus |
|-----------|-------|
| **1** | Spikes complete, storage consolidation begins, tile service deployment begins |
| **2** | Storage consolidation complete, tile service functional, PostgreSQL/PostGIS schema finalized |
| **3** | Tabular API development, STAC catalog population |
| **4** | Data Download Service, integration testing |
| **5** | Hardening, documentation, PI demo prep |

### Phase 2 PI (10 weeks - Risk Analytics)

Requires Phase 1 complete + enabler runway built:

| Iteration | Focus |
|-----------|-------|
| **1** | VirtualiZarr pipeline complete, CMIP6 access validated, WorldPop ingestion |
| **2** | Building footprint ingestion (MS/Google), Vector→H3 aggregation (F8.4) |
| **3** | Building exposure pipeline (F8.7), FATHOM × buildings join |
| **4** | Risk indicator schema finalized, API endpoints, bulk export |
| **5** | Integration testing, performance tuning, documentation |

**Phase 2 Prerequisites**:
- EN2 (VirtualiZarr) complete
- EN4 (H3 Analytics Backbone) complete
- F8.4 (Vector→H3) complete
- F8.7 (Building Exposure) complete
- F9.4 (CMIP6 Hosting) complete

---

## WSJF Prioritization

### Phase 1 Features

| Feature | Business Value | Time Criticality | Risk Reduction | Job Size | WSJF Score |
|---------|---------------|------------------|----------------|----------|------------|
| F1: Climate Data Visualization | 8 | 8 | 5 | 5 | 4.2 |
| F2: Tabular API | 8 | 5 | 3 | 8 | 2.0 |
| F3: STAC Exposure | 5 | 3 | 2 | 3 | 3.3 |
| F4: Data Download | 5 | 3 | 2 | 5 | 2.0 |

### Enablers (Runway)

| Enabler | Risk Reduction | Job Size | Priority |
|---------|----------------|----------|----------|
| EN1: Storage Consolidation | 8 | 5 | **Do First** |
| EN2: VirtualiZarr Pipeline | 6 | 3 | **Do First** |
| EN3: Boundary Aggregation | 5 | 5 | **Do Second** |
| EN4: H3 Analytics Backbone | 8 | 8 | **Do Second** (partially complete) |

### Phase 2 Features

| Feature | Business Value | Time Criticality | Risk Reduction | Job Size | WSJF Score | Notes |
|---------|---------------|------------------|----------------|----------|------------|-------|
| F5: At-Risk Population Analysis | 13 | 3 | 8 | 13 | 1.8 | Blocked on EN2, EN4, F8.4, F8.7 |

**Phase 2 Note**: F5 has high business value but large job size and is blocked on multiple enablers. WSJF score is lower due to dependencies - sequence correctly by completing runway first.

---

## Non-Functional Requirements (NFRs)

| NFR | Target | Validation |
|-----|--------|------------|
| **Tile Response Time** | <500ms p95 | Load test |
| **API Response Time** | <5s for Admin 2 queries | Load test |
| **Concurrent Users** | 100+ simultaneous sessions | Load test |
| **Availability** | 99.5% uptime | Azure monitoring |
| **Data Governance** | All storage in approved Azure tenancy under DDHGeo governance | Architecture review |

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                   DATA SOURCES                               │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Planetary Computer (Azure - ZERO EGRESS)                ││
│  │   • CIL-GDPCIR (Zarr) - temp, precip, 4 SSPs           ││
│  │   • NASA NEX-GDDP-CMIP6 (NetCDF) - extended variables  ││
│  └─────────────────────────────────────────────────────────┘│
│                           ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Consolidated Azure Storage (proprietary/licensed data)  ││
│  │   • VirtualiZarr references for NetCDF sources          ││
│  │   • Derived indicator outputs                            ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                     PROCESSING                               │
│  VirtualiZarr reference generation (for NetCDF sources)     │
│              (lightweight JSON/Parquet refs)                │
│                          ↓                                   │
│  Automated Boundary Aggregation (on Admin 1/2 updates)      │
│                          ↓                                   │
│                   pgSTAC catalog                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      SERVING                                 │
│                                                              │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ TiTiler-xarray  │    │      Query Function App         │ │
│  │ (App Service)   │    │                                 │ │
│  │                 │    │  - Tabular API (PostgreSQL/     │ │
│  │  - Reads Zarr   │    │    PostGIS)                     │ │
│  │    OR VirtZarr  │    │  - STAC API                     │ │
│  │    refs → tiles │    │  - CSV/JSON export              │ │
│  │  - 10 req/visit │    │  - Polygon extraction (Ph2)     │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                 PHASE 2: ANALYTICS                           │
│                                                              │
│   Building Footprints (Open Buildings, pluggable)           │
│                          ↓                                   │
│   Zonal Stats (FATHOM / WorldPop / CMIP6 slices)           │
│                          ↓                                   │
│   H3 Grid (canonical unit, pre-computed)                    │
│                          ↓                                   │
│   Any Output: Admin2 / Watershed / EEZ / Custom Polygon     │
└─────────────────────────────────────────────────────────────┘
```

---

## Open Questions (Pre-Planning)

1. **Data Processing Lineage**: What processing has been applied to existing climate data outputs? Understanding whether these are derived products or subsets of standard datasets informs the ingestion approach.

2. **Data Licensing and Hosting**: Which datasets require hosting in organizational storage versus accessing from public repositories (e.g., Planetary Computer)?

3. **Data Volume Assessment**: What are the expected row counts and variable dimensions for Admin 2 aggregations? Required for schema design and capacity planning.

4. **Current Usage Patterns**: What are typical request volumes and peak load characteristics? Required for infrastructure sizing.

---

## Appendix A: Available CMIP6 Data Inventory (Planetary Computer)

The following datasets are **already hosted on Microsoft Azure** via Planetary Computer. Before building ingestion pipelines, we must determine what CCKP requires beyond these existing sources.

### CIL-GDPCIR (Climate Impact Lab - Zarr Format) ✅ PREFERRED

| Attribute | Value |
|-----------|-------|
| **Format** | Zarr (cloud-native, no conversion needed) |
| **Total Size** | ~23 TB |
| **Resolution** | 0.25° (~25km) global grid |
| **Models** | 25 CMIP6 GCMs |
| **License** | CC0 (public domain) or CC-BY 4.0 |
| **Azure Location** | `abfs://cil-gdpcir/...` (same cloud, zero egress) |
| **STAC Catalog** | Yes, with CMIP6 controlled vocabularies |

**Variables:**

| Variable | Description | Temporal |
|----------|-------------|----------|
| `tasmin` | Daily minimum air temperature | Daily |
| `tasmax` | Daily maximum air temperature | Daily |
| `pr` | Daily cumulative precipitation | Daily |

**Scenarios:**

| Scenario | Time Period |
|----------|-------------|
| Historical | 1950-2014 |
| SSP1-2.6 | 2015-2100 |
| SSP2-4.5 | 2015-2100 |
| SSP3-7.0 | 2015-2100 |
| SSP5-8.5 | 2015-2100 |

**Value-Add Already Applied:**
- Bias-corrected (trend-preserving)
- Downscaled from native GCM resolution
- Standardized grid across all models

---

### NASA NEX-GDDP-CMIP6 (NetCDF Format)

| Attribute | Value |
|-----------|-------|
| **Format** | NetCDF (requires VirtualiZarr for TiTiler serving) |
| **Resolution** | 0.25° global grid |
| **Models** | 35 CMIP6 GCMs |
| **License** | CC-BY-SA 4.0 |
| **Azure Location** | Azure Blob Storage via Planetary Computer |
| **STAC Catalog** | Yes |

**Variables (broader than CIL-GDPCIR):**

| Variable | Description |
|----------|-------------|
| `tasmin` | Daily minimum temperature |
| `tasmax` | Daily maximum temperature |
| `pr` | Precipitation |
| `hurs` | Near-surface relative humidity |
| `huss` | Near-surface specific humidity |
| `rlds` | Surface downwelling longwave radiation |
| `rsds` | Surface downwelling shortwave radiation |
| `sfcWind` | Near-surface wind speed |

**Scenarios:**

| Scenario | Time Period |
|----------|-------------|
| Historical | 1950-2014 |
| SSP2-4.5 | 2015-2100 |
| SSP5-8.5 | 2015-2100 |

**Trade-offs vs CIL-GDPCIR:**
- More variables (humidity, radiation, wind)
- More models (35 vs 25)
- Fewer scenarios (2 vs 4 SSPs)
- NetCDF format requires VirtualiZarr pipeline

---

### Decision Matrix: Data Source Strategy

| Requirement | Recommended Approach | Notes |
|-------------|----------------------|-------|
| Temperature + precipitation, 4 SSPs | Access CIL-GDPCIR directly | Already cloud-optimized Zarr format |
| Humidity, wind, radiation | VirtualiZarr references to NASA NEX | NetCDF format, references enable cloud-native access |
| Custom derived indicators | Define formulas, compute via pipeline | Drought indices, heat wave definitions, etc. |
| Admin-level aggregations | Automated boundary aggregation pipeline | Recompute on boundary updates |
| Proprietary or licensed datasets | Ingest to consolidated storage | Requires data transfer and cataloging |

### Key Architecture Decision

> **Clarification Required**: What processing is applied to existing climate data outputs that is not available from standard CMIP6 sources (CIL-GDPCIR, NASA NEX-GDDP-CMIP6)?

| If Answer Is... | Recommended Approach |
|-----------------|----------------------|
| Custom indicator formulas | Document formulas, automate computation in platform |
| Admin boundary aggregations | Automate via boundary aggregation pipeline |
| Standard CMIP6 subsets | Access Planetary Computer directly, no data duplication |
| Proprietary model outputs | Ingest to consolidated storage with appropriate governance |

---

## Appendix B: Platform Reference

### Relevant Epic/Feature Documentation

| Platform Doc | Relevance to CCKP |
|--------------|-------------------|
| `docs/epics/E8_geoanalytics.md` | H3 Analytics Backbone details |
| `docs/epics/E9_large_data.md` | VirtualiZarr (F9.3), CMIP6 Hosting (F9.4), xarray Service (F9.5) |
| `docs/epics/E2_raster_data.md` | STAC integration, TiTiler patterns |
| `docs/epics/E3_ddh_integration.md` | API contract patterns, identity/access |
| `docs/epics/ENABLERS.md` | EN1 Job Orchestration, EN2 Database, EN3 Azure Platform |

### Key Platform Endpoints (DEV)

| Endpoint | Purpose | CCKP Use |
|----------|---------|----------|
| `/api/stac/*` | STAC catalog queries | F3: STAC Catalog Exposure |
| `/api/jobs/submit/*` | Async job submission | F4: Data Download Service |
| `/api/jobs/status/*` | Job status polling | F4: Data Download Service |
| `/api/features/*` | OGC Features API | F2: Tabular API (partial) |
| `/api/xarray/*` | Time-series/stats endpoints | F2: Tabular API (partial) |
| `/api/h3/*` | H3 analytics queries | EN4: H3 Analytics Backbone |

---

## Governance and Responsibilities

### Technical Governance

The geospatial platform team maintains decision authority over:

- Database architecture and configuration
- Storage infrastructure design
- Cloud service selection and deployment
- API design and implementation patterns

### Engagement Model

| Stakeholder | Responsibility |
|-------------|----------------|
| Client teams | Define functional requirements, acceptance criteria, and business priorities |
| Platform team | Technical architecture, implementation approach, and infrastructure decisions |
| Joint | Integration testing, performance validation, and deployment coordination |
