# H3 Geospatial Aggregation Pipeline System

## SAFe Planning Document

**Document Version**: 1.0  
**Created**: 28 December 2025  
**Epic Owner**: Robert  
**Architect**: Claude(s)  
**Status**: Draft - Needs integration with geospatial application

---
## Instructions for Claudes! PLS READ FIRST 
Please read this document with the rmhgeoapi project we are working inside of in mind. Please understand EPICS.MD and:
1. rename any epics you read in this document to match ours in EPICS.md if there is a match
2. translate the rest of them into EPICS.md structure 
3. consalidate into *separate* EPICS.md structured document
4. You and the human Robert will figure out how to integrate and assign weight


## Executive Summary

### Vision Statement

> Enable declarative, metadata-driven geospatial aggregation pipelines that transform heterogeneous Earth observation data into standardized H3-indexed analytics products, leveraging existing CoreMachine orchestration infrastructure and cloud-native data formats.

### Business Context

The World Bank's geospatial analytics capabilities require processing diverse data sources (climate projections, population estimates, soil properties, flood risk) into unified spatial indices for decision support. Current approaches require custom code for each analysis, limiting scalability and reproducibility.

### Solution Overview

A three-layer architecture that separates **what to compute** (declarative pipeline definitions) from **how to compute it** (CoreMachine execution engine) from **where data lives** (source catalog with cloud-native access patterns).

**Key Technologies**:
- **Compute**: Azure Functions (Python) with Service Bus orchestration
- **Storage**: PostgreSQL/PostGIS (state, metadata, results) + Azure Blob (COGs, GeoParquet)
- **Data Access**: STAC API (Planetary Computer), HTTP range requests to COGs
- **Spatial Index**: H3 hexagonal grid (Uber's hierarchical spatial index)
- **Output Formats**: PostGIS tables (visualization), GeoParquet (analytics export)

---

## Epic Definition

### Epic: H3 Declarative Pipeline System

| Field | Value |
|-------|-------|
| **Epic ID** | E-H3-001 |
| **Epic Name** | H3 Declarative Pipeline System |
| **Epic Owner** | Robert |
| **Target PI** | PI-2025-Q1 |
| **Epic Type** | Business Epic |
| **State** | Funnel → Analysis |

### Epic Hypothesis Statement

**For** World Bank geospatial analysts and data scientists  
**Who** need to aggregate diverse Earth observation data to common spatial units  
**The** H3 Declarative Pipeline System  
**Is a** metadata-driven orchestration layer  
**That** enables reproducible, scalable geospatial aggregation without custom code  
**Unlike** current ad-hoc scripting approaches  
**Our solution** provides declarative pipeline definitions, automatic tile discovery, and full execution lineage tracking  

### Leading Indicators (In-Progress Measures)

| Indicator | Target | Measurement |
|-----------|--------|-------------|
| Pipeline definitions created | 5+ | Count in `h3.pipeline_definition` |
| Data sources registered | 10+ | Count in `h3.source_catalog` |
| Successful pipeline runs | 20+ | Count in `h3.pipeline_run` where status='completed' |
| Countries with H3 coverage | 3+ | Distinct iso3 in `h3.zonal_stats` |

### Lagging Indicators (Outcome Measures)

| Indicator | Target | Measurement |
|-----------|--------|-------------|
| Time to new aggregation product | <1 day | From request to production data |
| Code changes for new data source | 0 | Pipeline + source registration only |
| Analyst self-service rate | 80%+ | Pipelines run without developer intervention |

### MVP Definition

**Rwanda Coffee Climate Risk Demo**:
- Register 5 data sources (iSDA soil, WorldPop, CMIP6, elevation, MapSPAM)
- Define 1 multi-step pipeline (coffee suitability + climate risk)
- Execute for Rwanda at H3 resolution 7
- Export to GeoParquet for visualization
- Present to stakeholders as proof of concept

---

## Feature Breakdown

### Feature 1: Source Catalog Foundation

| Field | Value |
|-------|-------|
| **Feature ID** | F-H3-001 |
| **Feature Name** | Source Catalog Foundation |
| **Parent Epic** | E-H3-001 |
| **Target Sprint** | Sprint 1-2 |
| **Feature Owner** | Robert |
| **Story Points** | 21 |

#### Description

Implement comprehensive data source registry (`h3.source_catalog`) with metadata sufficient for automatic tile discovery, aggregation configuration, and provenance tracking.

#### Benefit Hypothesis

By registering data sources with rich metadata, pipeline definitions become source-agnostic, enabling reuse across different geographic scopes without code changes.

#### Acceptance Criteria

- [ ] `h3.source_catalog` table created with full schema
- [ ] CRUD API endpoints operational (`/api/h3/sources`)
- [ ] Planetary Computer sources registered (cop-dem-glo-30, sentinel-2-l2a)
- [ ] iSDA soil sources registered (pH, organic carbon, texture)
- [ ] WorldPop population source registered
- [ ] STAC tile discovery working for tiled datasets
- [ ] Source validation endpoint functional

#### Stories

| Story ID | Story Name | Points | Sprint |
|----------|------------|--------|--------|
| S-001 | Create source_catalog schema and migrations | 3 | S1 |
| S-002 | Implement SourceCatalogRepository with CRUD | 5 | S1 |
| S-003 | Create /api/h3/sources REST endpoints | 5 | S1 |
| S-004 | Implement STAC tile discovery service | 8 | S2 |
| S-005 | Register MVP data sources (5 sources) | 3 | S2 |

#### Dependencies

- CoreMachine job infrastructure (existing)
- PostgreSQL h3 schema (existing)
- Planetary Computer access token configuration

---

### Feature 2: Pipeline Definition Framework

| Field | Value |
|-------|-------|
| **Feature ID** | F-H3-002 |
| **Feature Name** | Pipeline Definition Framework |
| **Parent Epic** | E-H3-001 |
| **Target Sprint** | Sprint 2-3 |
| **Feature Owner** | Robert |
| **Story Points** | 34 |

#### Description

Implement declarative pipeline definition system (`h3.pipeline_definition`) with step dependency resolution, source reference binding, and validation.

#### Benefit Hypothesis

Declarative pipeline definitions enable non-developers to create and modify aggregation workflows, reducing time-to-insight and improving reproducibility.

#### Acceptance Criteria

- [ ] `h3.pipeline_definition` table created
- [ ] Pipeline JSONB schema documented and validated
- [ ] Step dependency resolution working (topological sort)
- [ ] `$prev_step` reference pattern implemented
- [ ] Pipeline validation endpoint (dry run without execution)
- [ ] CRUD API endpoints operational (`/api/h3/pipelines`)
- [ ] At least 2 pipeline templates created (simple + complex)

#### Stories

| Story ID | Story Name | Points | Sprint |
|----------|------------|--------|--------|
| S-006 | Create pipeline_definition schema | 3 | S2 |
| S-007 | Implement pipeline JSONB validation | 5 | S2 |
| S-008 | Build step dependency resolver | 8 | S3 |
| S-009 | Implement source reference binding | 5 | S3 |
| S-010 | Create /api/h3/pipelines REST endpoints | 5 | S3 |
| S-011 | Create pipeline validation service | 5 | S3 |
| S-012 | Define simple elevation pipeline template | 2 | S3 |
| S-013 | Define complex multi-step pipeline template | 3 | S3 |

#### Dependencies

- F-H3-001: Source Catalog Foundation

---

### Feature 3: Pipeline Execution Engine

| Field | Value |
|-------|-------|
| **Feature ID** | F-H3-003 |
| **Feature Name** | Pipeline Execution Engine |
| **Parent Epic** | E-H3-001 |
| **Target Sprint** | Sprint 3-4 |
| **Feature Owner** | Robert |
| **Story Points** | 55 |

#### Description

Implement `PipelineFactory` that compiles pipeline definitions into CoreMachine jobs, with full execution tracking via `h3.pipeline_run` and `h3.pipeline_step_run` tables. Batches tracked as first-class entities via CoreMachine tasks.

#### Benefit Hypothesis

Leveraging CoreMachine's proven orchestration infrastructure eliminates the need to build custom execution logic while providing enterprise-grade reliability, retry semantics, and observability.

#### Acceptance Criteria

- [ ] `h3.pipeline_run` and `h3.pipeline_step_run` tables created
- [ ] `PipelineFactory.build_job()` compiles pipelines to CoreMachine jobs
- [ ] `h3_pipeline` job type registered with CoreMachine
- [ ] `/api/h3/pipelines/run` endpoint triggers execution
- [ ] Pipeline status queryable via `/api/h3/pipelines/runs/{run_id}`
- [ ] Batch-level tracking via CoreMachine tasks
- [ ] Stage barrier enforced (N completes before N+1)
- [ ] Simple pipeline executes end-to-end (elevation for Rwanda)

#### Stories

| Story ID | Story Name | Points | Sprint |
|----------|------------|--------|--------|
| S-014 | Create pipeline_run and pipeline_step_run schemas | 3 | S3 |
| S-015 | Implement PipelineFactory service | 13 | S3-S4 |
| S-016 | Register h3_pipeline job type with CoreMachine | 5 | S4 |
| S-017 | Create pipeline inventory stage handler | 5 | S4 |
| S-018 | Enhance h3_raster_zonal with dynamic tile discovery | 8 | S4 |
| S-019 | Create pipeline finalize stage handler | 5 | S4 |
| S-020 | Implement /api/h3/pipelines/run endpoint | 5 | S4 |
| S-021 | Implement /api/h3/pipelines/runs status endpoint | 3 | S4 |
| S-022 | Create pipeline execution dashboard query | 3 | S4 |
| S-023 | End-to-end test: Rwanda elevation pipeline | 5 | S4 |

#### Dependencies

- F-H3-001: Source Catalog Foundation
- F-H3-002: Pipeline Definition Framework
- CoreMachine job/stage/task infrastructure (existing)
- Service Bus H3 queue (existing)

---

### Feature 4: Multi-Step Pipeline Operations

| Field | Value |
|-------|-------|
| **Feature ID** | F-H3-004 |
| **Feature Name** | Multi-Step Pipeline Operations |
| **Parent Epic** | E-H3-001 |
| **Target Sprint** | Sprint 5-6 |
| **Feature Owner** | Robert |
| **Story Points** | 42 |

#### Description

Implement additional pipeline operations beyond zonal_stats: spatial_join, h3_weighted_aggregate, filter, transform. Enable intermediate output handling between steps.

#### Benefit Hypothesis

Multi-step pipelines enable complex analytical workflows (e.g., population-weighted flood risk) that previously required custom scripts, democratizing access to sophisticated geospatial analysis.

#### Acceptance Criteria

- [ ] `h3_spatial_join` handler implemented
- [ ] `h3_weighted_aggregate` handler implemented
- [ ] Intermediate output storage working (temp tables or blob)
- [ ] Step output reference (`$prev_step`) resolves correctly
- [ ] Complex pipeline executes end-to-end (flood + pop → weighted risk)
- [ ] Intermediate cleanup policy enforced

#### Stories

| Story ID | Story Name | Points | Sprint |
|----------|------------|--------|--------|
| S-024 | Design intermediate output storage strategy | 5 | S5 |
| S-025 | Implement temp table intermediate storage | 8 | S5 |
| S-026 | Implement h3_spatial_join handler | 8 | S5 |
| S-027 | Implement h3_weighted_aggregate handler | 8 | S5 |
| S-028 | Implement step output reference resolution | 5 | S6 |
| S-029 | Create intermediate cleanup service | 3 | S6 |
| S-030 | End-to-end test: multi-step flood risk pipeline | 5 | S6 |

#### Dependencies

- F-H3-003: Pipeline Execution Engine

---

### Feature 5: Coffee Climate Risk Demo (MVP)

| Field | Value |
|-------|-------|
| **Feature ID** | F-H3-005 |
| **Feature Name** | Coffee Climate Risk Demo |
| **Parent Epic** | E-H3-001 |
| **Target Sprint** | Sprint 6-7 |
| **Feature Owner** | Robert |
| **Story Points** | 34 |

#### Description

Implement Rwanda coffee climate risk analysis as flagship demonstration: soil suitability (iSDA) + climate projections (CMIP6) + current production (MapSPAM) → risk assessment at H3 resolution 7.

#### Benefit Hypothesis

A compelling demo showing "where is coffee production at risk from climate change" validates the architecture and creates stakeholder buy-in for expanded investment.

#### Acceptance Criteria

- [ ] All required sources registered (iSDA pH/carbon/texture, CMIP6, DEM, MapSPAM)
- [ ] Coffee suitability pipeline defined
- [ ] Rwanda H3 res-7 cells seeded (~5,000 cells)
- [ ] Pipeline executes successfully
- [ ] Results exported to GeoParquet
- [ ] Simple visualization demonstrates risk zones
- [ ] Demo narrative documented

#### Stories

| Story ID | Story Name | Points | Sprint |
|----------|------------|--------|--------|
| S-031 | Register iSDA soil sources (pH, carbon, texture) | 3 | S6 |
| S-032 | Register CMIP6 temperature/precip sources | 5 | S6 |
| S-033 | Register MapSPAM coffee production source | 3 | S6 |
| S-034 | Seed Rwanda H3 res-7 cells | 2 | S6 |
| S-035 | Define coffee suitability calculation logic | 5 | S7 |
| S-036 | Define coffee climate risk pipeline | 5 | S7 |
| S-037 | Execute pipeline for Rwanda | 3 | S7 |
| S-038 | Export results to GeoParquet | 3 | S7 |
| S-039 | Create demo visualization | 5 | S7 |

#### Dependencies

- F-H3-004: Multi-Step Pipeline Operations
- iSDA S3 access
- CMIP6 data access (Planetary Computer or direct)

---

### Feature 6: OLAP Export Layer

| Field | Value |
|-------|-------|
| **Feature ID** | F-H3-006 |
| **Feature Name** | OLAP Export Layer |
| **Parent Epic** | E-H3-001 |
| **Target Sprint** | Sprint 7-8 |
| **Feature Owner** | Robert |
| **Story Points** | 21 |

#### Description

Implement export pipeline from H3 zonal_stats to consumer-friendly formats: PostGIS materialized views (for visualization/OGC APIs) and GeoParquet (for analytics/DuckDB consumers).

#### Benefit Hypothesis

Clean export formats enable self-service consumption by visualization tools (web maps) and analytics platforms (Databricks, DuckDB) without requiring direct database access.

#### Acceptance Criteria

- [ ] PostGIS materialized view generation working
- [ ] Geometry generation from H3 index at query time
- [ ] GeoParquet export with resolution partitioning
- [ ] Export triggered automatically on pipeline completion (optional)
- [ ] Export API endpoint for manual triggering
- [ ] Rwanda demo data available in both formats

#### Stories

| Story ID | Story Name | Points | Sprint |
|----------|------------|--------|--------|
| S-040 | Design materialized view generation pattern | 3 | S7 |
| S-041 | Implement PostGIS export service | 5 | S7 |
| S-042 | Implement GeoParquet export service | 8 | S8 |
| S-043 | Create /api/h3/export endpoint | 3 | S8 |
| S-044 | Add export hook to pipeline finalize | 2 | S8 |

#### Dependencies

- F-H3-003: Pipeline Execution Engine
- Azure Blob Storage for GeoParquet output

---

## Architectural Runway (Enablers)

### Enabler 1: Dynamic STAC Tile Discovery

| Field | Value |
|-------|-------|
| **Enabler ID** | EN-001 |
| **Type** | Infrastructure |
| **Sprint** | Sprint 1-2 |

#### Description

Implement service that queries STAC API to discover tiles covering a given H3 cell extent, eliminating manual tile specification.

#### Technical Approach

```python
class STACTileDiscovery:
    def discover_tiles(
        self, 
        source: SourceCatalog, 
        h3_cells: List[str]
    ) -> List[STACItem]:
        """
        1. Compute bounding box from H3 cells
        2. Query STAC API with bbox + collection
        3. Return matching items with asset URLs
        """
```

#### Acceptance Criteria

- [ ] Works with Planetary Computer STAC API
- [ ] Handles tiled datasets (cop-dem-glo-30)
- [ ] Handles single-item datasets (country-level)
- [ ] Caches tile inventory per source+extent

---

### Enabler 2: H3 Cell Batch Partitioning

| Field | Value |
|-------|-------|
| **Enabler ID** | EN-002 |
| **Type** | Infrastructure |
| **Sprint** | Sprint 2 |

#### Description

Formalize H3 batch partitioning strategy: use resolution-3 or resolution-4 parent cells as batch identifiers for fan-out parallelism.

#### Technical Approach

```python
def partition_cells_to_batches(
    h3_cells: List[str], 
    batch_resolution: int = 4
) -> Dict[str, List[str]]:
    """
    Group cells by their parent at batch_resolution.
    Returns {parent_h3: [child_h3, ...]}
    """
    batches = defaultdict(list)
    for cell in h3_cells:
        parent = h3.cell_to_parent(cell, batch_resolution)
        batches[parent].append(cell)
    return batches
```

#### Acceptance Criteria

- [ ] Partitioning produces balanced batches
- [ ] Batch IDs are deterministic (same input → same batches)
- [ ] Works across resolution levels (res 6, 7, 8 cells)

---

### Enabler 3: COG HTTP Range Request Optimization

| Field | Value |
|-------|-------|
| **Enabler ID** | EN-003 |
| **Type** | Infrastructure |
| **Sprint** | Sprint 3 |

#### Description

Optimize raster access via HTTP range requests to Cloud Optimized GeoTIFFs, reading only the portions needed for each H3 batch.

#### Technical Approach

```python
# Using rasterio with vsicurl
with rasterio.open(f"/vsicurl/{cog_url}") as src:
    # Window read - only fetches needed bytes
    window = from_bounds(*bbox, src.transform)
    data = src.read(1, window=window)
```

#### Acceptance Criteria

- [ ] Reads only required extent (not full raster)
- [ ] Works with iSDA S3 bucket
- [ ] Works with Planetary Computer signed URLs
- [ ] Handles overview levels for appropriate resolution

---

## Program Increment Planning

### PI-2025-Q1 Objectives

| # | Objective | Features | Business Value |
|---|-----------|----------|----------------|
| 1 | Establish H3 pipeline foundation | F-001, F-002 | Enable declarative pipeline definitions |
| 2 | Deliver working execution engine | F-003 | Prove CoreMachine integration works |
| 3 | Complete multi-step capability | F-004 | Enable complex analytical workflows |
| 4 | Ship Rwanda coffee demo | F-005 | Stakeholder validation and buy-in |
| 5 | Enable self-service exports | F-006 | Analyst consumption without developer help |

### Sprint Allocation

| Sprint | Dates | Focus | Features |
|--------|-------|-------|----------|
| Sprint 1 | Week 1-2 | Foundation | F-001 (partial), EN-001 |
| Sprint 2 | Week 3-4 | Catalog + Discovery | F-001, F-002 (partial), EN-002 |
| Sprint 3 | Week 5-6 | Pipeline Framework | F-002, F-003 (partial) |
| Sprint 4 | Week 7-8 | Execution Engine | F-003, EN-003 |
| Sprint 5 | Week 9-10 | Multi-Step Ops | F-004 (partial) |
| Sprint 6 | Week 11-12 | Multi-Step + Demo Start | F-004, F-005 (partial) |
| Sprint 7 | Week 13-14 | Demo Completion | F-005, F-006 (partial) |
| Sprint 8 | Week 15-16 | Export + Hardening | F-006, Documentation |

### Capacity Planning

| Role | Allocation | Notes |
|------|------------|-------|
| Robert | 50% | Split with org restructuring prep |
| Claude (Code) | 100% | Implementation partner |
| Claude (Chat) | As needed | Architecture, planning, research |

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Planetary Computer API rate limits | Medium | Medium | Implement caching, batch requests |
| CMIP6 data access complexity | Medium | High | Fallback to WorldClim if needed |
| CoreMachine modifications needed | Low | High | Design to use existing patterns only |
| iSDA S3 access issues | Low | Medium | Data already public, test early |
| Org restructuring disrupts work | High | High | Prioritize MVP demo completion |

---

## Definition of Done

### Story Level

- [ ] Code implemented and passing tests
- [ ] Code reviewed (by Claude or self-review documented)
- [ ] Database migrations created and tested
- [ ] API endpoints documented (OpenAPI)
- [ ] Integration test passing

### Feature Level

- [ ] All stories complete
- [ ] End-to-end test scenario passing
- [ ] Documentation updated
- [ ] Demo-able to stakeholders

### Epic Level

- [ ] All features complete
- [ ] Rwanda coffee demo delivered
- [ ] Architecture documentation complete
- [ ] Runbook for operations created
- [ ] Stakeholder sign-off received

---

## Appendix A: Technical Glossary

| Term | Definition |
|------|------------|
| **H3** | Uber's hierarchical hexagonal spatial index. Resolution 0 (largest) to 15 (smallest). |
| **COG** | Cloud Optimized GeoTIFF - raster format supporting HTTP range requests |
| **STAC** | SpatioTemporal Asset Catalog - metadata standard for geospatial assets |
| **Zonal Statistics** | Computing summary statistics (mean, max, etc.) for raster values within polygon zones |
| **CoreMachine** | Internal job orchestration framework using Service Bus + PostgreSQL |
| **GeoParquet** | Parquet files with geometry column and spatial metadata |
| **iSDA** | Innovative Solutions for Decision Agriculture - 30m African soil data |
| **Planetary Computer** | Microsoft's cloud platform for Earth observation data |

## Appendix B: Data Source Inventory

| Source ID | Description | Resolution | Format | Access |
|-----------|-------------|------------|--------|--------|
| cop-dem-glo-30 | Copernicus DEM | 30m | COG | Planetary Computer |
| isda-ph | iSDA Soil pH | 30m | COG | S3 (public) |
| isda-carbon | iSDA Organic Carbon | 30m | COG | S3 (public) |
| isda-texture | iSDA Soil Texture | 30m | COG | S3 (public) |
| worldpop-2020 | WorldPop Population | 100m | GeoTIFF | Direct download |
| cmip6-tas | CMIP6 Temperature | ~100km | NetCDF/Zarr | Planetary Computer |
| cmip6-pr | CMIP6 Precipitation | ~100km | NetCDF/Zarr | Planetary Computer |
| mapspam-coffee | MapSPAM Coffee Production | 10km | GeoTIFF | Direct download |

## Appendix C: Related Documents

- `H3_PIPELINE_ARCHITECTURE.md` - Detailed technical architecture
- `WIKI_H3.md` - Current H3 system documentation
- `ARCHITECTURE_REFERENCE.md` - CoreMachine patterns
- `JOB_CREATION_QUICKSTART.md` - Job implementation guide

---

*This document is maintained by the Geospatial Platform Team (Robert + Claudes)*