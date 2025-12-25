# SAFe Epic & Feature Registry

**Last Updated**: 21 DEC 2025
**Framework**: SAFe (Scaled Agile Framework)
**Purpose**: Master reference for Azure DevOps Boards import
**Source of Truth**: This file defines Epic/Feature numbers; TODO.md should align

---

## Quick Reference

**FY26 Target (ends 30 JUN 2026)**: E1 ✅, E2, E3, E4

| Priority | Epic | Name | Status | Features | WSJF |
|:--------:|------|------|--------|:--------:|:----:|
| — | E1 | Vector Data as API | ✅ Complete | 4 | — |
| 1 | E2 | Raster Data as API | 🚧 Partial | 7 | 5.9 |
| 2 | E3 | DDH Platform Integration | 🚧 Partial | 8 | 4.8 |
| 3 | E4 | Data Externalization | 🚧 Partial | 5 | 4.3 |
| 4 | E9 | Zarr/Climate Data as API | 🚧 Partial | 3 | 2.0 |
| 5 | E7 | Custom Data Pipelines | 🚧 Partial | 3 | 2.6 |
| 6 | E5 | OGC Styles | 🚧 Partial | 2 | 3.7 |
| 7 | E8 | H3 Analytics Pipeline | 🚧 Partial | 7 | 1.2 |
| NEW | E11 | Pipeline Builder Demo | 📋 Proposed | 4 | — |
| NEW | E12 | Interface Modernization | 🚧 Active | 2 | — |

**Priority Notes**:
- **E3 includes Observability**: Merged E6 into E3 — observability is app-to-app monitoring for integration
- **E3 requires ITSDA coordination**: See ITSDA dependency tags on stories below
- **E7 + E9 synergy**: FATHOM pipeline (E7) drives Zarr/xarray capabilities (E9) — "future ready" patterns
- **E9, E7, E5, E8**: Secondary priority for FY26; E7 (FATHOM) may elevate based on partner timeline

### WSJF Calculation

**Formula**: WSJF = Cost of Delay ÷ Job Size (higher score = do first)

**Cost of Delay** = Business Value + Time Criticality + Risk Reduction (each 1-21 Fibonacci)

| Epic | Business Value | Time Crit | Risk Red | **CoD** | Job Size | **WSJF** |
|------|:--------------:|:---------:|:--------:|:-------:|:--------:|:--------:|
| E2 | 21 (platform foundation) | 13 (FATHOM blocked) | 13 (enables downstream) | **47** | 8 | **5.9** |
| E3 | 21 (analytics front-end) | 13 (high urgency) | 13 (observability+diagnostics) | **48** | 10 | **4.8** |
| E4 | 13 (external access) | 8 (post-platform) | 13 (security/audit) | **34** | 8 | **4.3** |
| E9 | 13 (CMIP client priority) | 5 (secondary tier) | 8 (technical complexity) | **26** | 13 | **2.0** |
| E7 | 5 (operational efficiency) | 3 | 5 | **13** | 5 | **2.6** |
| E5 | 5 (styling metadata) | 3 | 3 | **11** | 3 | **3.7** |
| E8 | 8 (analytics capability) | 3 | 5 | **16** | 13 | **1.2** |

**WSJF-Ordered Sequence**: E2 (5.9) → E3 (4.8) → E4 (4.3) → E5 (3.7) → E7 (2.6) → E9 (2.0) → E8 (1.2)

**Note**: E3 absorbs former E6 (Platform Observability) — observability is app-to-app monitoring that enables integration.

| Enabler | Name | Status | Enables |
|---------|------|--------|---------|
| EN1 | Job Orchestration Engine | ✅ Complete | E1, E2, E9 |
| EN2 | Database Architecture | ✅ Complete | All |
| EN3 | Azure Platform Integration | ✅ Complete | All |
| EN4 | Configuration System | ✅ Complete | All |
| EN5 | Pre-flight Validation | ✅ Complete | E1, E2 |
| EN6 | Long-Running Task Infrastructure | ⏳ FY26 Decision | E2, E9 |

---

# COMPONENT GLOSSARY

Abstract component names for ADO work items. Actual Azure resource names assigned during implementation.

## Storage

| Logical Name | Purpose | Access Pattern | Zone |
|--------------|---------|----------------|------|
| **Bronze Storage Account** | Raw uploaded data | Write: ETL jobs, Read: processing | Internal |
| **Silver Storage Account** | Processed COGs, Zarr | Write: ETL jobs, Read: TiTiler, APIs | Internal |
| **External Storage Account** | Public-facing data | Write: ADF copy, Read: CDN/External Reader | External |

## Compute

| Logical Name | Purpose | Runtime | Status |
|--------------|---------|---------|--------|
| **ETL Function App** | Job orchestration, HTTP APIs | Azure Functions (Python) | ✅ Deployed |
| **Reader Function App** | Read-only data access APIs | Azure Functions (Python) | 📋 Planned |
| **Long-Running Worker** | Tasks exceeding 30-min timeout | Docker Container App | ⏳ FY26 Decision |
| **TiTiler Raster Service** | COG tile serving | Docker Container App | ✅ Deployed |
| **TiTiler Zarr Service** | Zarr/NetCDF tile serving | Docker Container App | 📋 Planned |

### Docker Deployments Detail

| Service | Image Source | Deployment Target | Notes |
|---------|--------------|-------------------|-------|
| **TiTiler Raster** | `ghcr.io/stac-utils/titiler-pgstac` | Azure Container Apps | Production, serving COGs |
| **TiTiler Zarr** | Custom (xarray/zarr stack) | Azure Container Apps | Pending E9 progress |
| **Long-Running Worker** | Custom (GDAL/rasterio stack) | Azure Container Apps | See EN6; FY26 decision pending |

## Queues (Service Bus)

| Logical Name | Purpose |
|--------------|---------|
| **Job Queue** | Initial job submission |
| **Vector Task Queue** | Vector processing tasks |
| **Raster Task Queue** | Raster processing tasks |
| **Long-Running Task Queue** | Overflow to Docker worker |

## Database

| Logical Name | Purpose | Zone |
|--------------|---------|------|
| **App Database** | Job/task state, curated datasets (nukeable) | Internal |
| **Business Database** | PostGIS geo schema, pgSTAC catalog (protected) | Internal |
| **External Database** | External PostgreSQL with PostGIS for public data | External |
| **App Admin Identity** | Managed identity with DDL privileges | Internal |
| **App Reader Identity** | Managed identity with read-only privileges | Internal |
| **External Reader Identity** | Managed identity for external zone read access | External |

## External Systems

| Logical Name | Purpose |
|--------------|---------|
| **DDH Application** | Data Hub Dashboard — separate app, separate identity, already exists |
| **DDH Managed Identity** | DDH's own identity (already exists) — needs RBAC grants to platform resources |
| **CDN/WAF** | Cloudflare edge protection for external zone |
| **Data Factory Instance** | ADF for blob-to-blob copy operations |

---

# EPICS

## Epic E1: Vector Data as API ✅

**Business Requirement**: "Make vector data available as API"
**Status**: ✅ COMPLETE
**Completed**: NOV 2025

### Feature F1.1: Vector ETL Pipeline ✅

**Deliverable**: `process_vector` job with idempotent DELETE+INSERT pattern

| Story | Description |
|-------|-------------|
| S1.1.1 | Design etl_batch_id idempotency pattern |
| S1.1.2 | Create PostGIS handler with DELETE+INSERT |
| S1.1.3 | Implement chunked upload (500-row chunks) |
| S1.1.4 | Add spatial + batch index creation |
| S1.1.5 | Create process_vector job with JobBaseMixin |

**Key Files**: `jobs/process_vector.py`, `services/vector/process_vector_tasks.py`, `services/vector/postgis_handler.py`

---

### Feature F1.2: OGC Features API ✅

**Deliverable**: `/api/features/collections/{id}/items` with bbox queries

| Story | Description |
|-------|-------------|
| S1.2.1 | Create /api/features landing page |
| S1.2.2 | Implement /api/features/collections list |
| S1.2.3 | Add bbox query support |
| S1.2.4 | Create interactive map web interface |

**Key Files**: `web_interfaces/features/`, `triggers/ogc_features.py`

---

### Feature F1.3: Vector STAC Integration ✅

**Deliverable**: Items registered in pgSTAC `system-vectors` collection

| Story | Description |
|-------|-------------|
| S1.3.1 | Create system-vectors collection |
| S1.3.2 | Generate STAC items for vector datasets |
| S1.3.3 | Add vector-specific STAC properties |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `services/stac_metadata.py`

---

### Feature F1.4: Vector Unpublish ✅

**Deliverable**: `unpublish_vector` job for data removal

| Story | Description |
|-------|-------------|
| S1.4.1 | Create unpublish data models |
| S1.4.2 | Implement unpublish handlers |
| S1.4.3 | Add STAC item/collection validators |
| S1.4.4 | Create unpublish_vector job |

**Key Files**: `jobs/unpublish_vector.py`, `services/unpublish_handlers.py`, `core/models/unpublish.py`

**Note**: Code complete, needs deploy + test with `dry_run=true`

---

---

## Epic E2: Raster Data as API 🚧

**Business Requirement**: "Make GeoTIFF available as API"
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

| Story | Description |
|-------|-------------|
| S2.2.1 | Configure TiTiler for COG access |
| S2.2.2 | Generate viewer URLs in job results |
| S2.2.3 | Add preview image endpoints |
| S2.2.4 | Implement tile URL generation |

**Key Files**: `services/titiler_client.py`

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

---

## Epic E3: DDH Platform Integration 🚧

**Business Requirement**: Enable DDH application to consume geospatial platform data services
**Status**: 🚧 PARTIAL (Observability complete, Identity/Access in progress, Documentation planned)
**Owner**: ITSDA Team (DDH) + Geospatial Team (Platform)

**Architectural Boundary**:
> Platform exposes **DATA ACCESS APIs**; ETL orchestration is internal implementation.
> DDH submits jobs via `/api/jobs/submit/*` and polls status via `/api/jobs/status/{id}`.
> Push-based callbacks are not part of the supported integration contract.

**Integration Contract**:
```
DDH Application                    Geospatial Platform
┌─────────────────┐               ┌─────────────────────┐
│                 │──── Submit ──▶│ /api/jobs/submit/*  │
│  Data Hub       │               │ (vector, raster)    │
│  Dashboard      │──── Poll ────▶│ /api/jobs/status/*  │
│                 │               │                     │
│                 │──── Query ───▶│ /api/features/*     │ DATA ACCESS
│                 │               │ /api/raster/*       │ (primary surface)
│                 │               │ /api/stac/*         │
│                 │               │ /api/h3/*           │
└─────────────────┘               └─────────────────────┘
```

---

### Feature F3.1: API Contract Documentation ✅ COMPLETE

**Owner**: Geospatial Team
**Deliverable**: Formal API specification for cross-team development
**Completed**: 21 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S3.1.1 | ✅ | Document data access endpoints (OGC Features, Raster, STAC, H3) |
| S3.1.2 | ✅ | Document job submission request/response formats |
| S3.1.3 | ✅ | Document job status polling pattern and response schema |
| S3.1.4 | ✅ | Document STAC item structure for vectors/rasters |
| S3.1.5 | ✅ | Document error response contract |
| S3.1.6 | ✅ | Generate OpenAPI 3.0 spec from existing endpoints |
| S3.1.7 | ✅ | Publish API documentation (Swagger UI or static site) |

**Deliverables**:
- OpenAPI 3.0.1 spec: `openapi/platform-api-v1.json` (19 endpoints, 20 schemas)
- Swagger UI: `/api/interface/swagger` (self-contained, no CDN)
- JSON spec endpoint: `/api/openapi.json`

---

### Feature F3.2: Identity & Access Configuration 📋 PLANNED

**Owner**: DevOps (Azure config) + Geospatial Team (requirements)
**Deliverable**: Service principals and access grants per environment

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S3.2.1 | ✅ | Authentication strategy decided | — | **Managed Identity only** (see below) |
| S3.2.2 | ✅ | DDH Managed Identity exists | — | DDH already has its own identity |
| S3.2.3 | ✅ | Grant DDH write access to **Bronze Storage Account** | DevOps | DDH identity has `Storage Blob Data Contributor` on bronze container |
| S3.2.4 | 📋 | Grant DDH access to **Platform API** | DevOps | DDH identity can call `/api/*` endpoints |
| S3.2.5 | 📋 | Configure **ETL Function App** authentication | Geospatial | Function App validates DDH identity on protected endpoints |
| S3.2.6 | 📋 | Document integration setup | DevOps | Runbook: role assignments, endpoint URLs |

### F3.2 Authentication Strategy (S3.2.1 Decision)

**Principle**: No secrets. No tokens. Managed Identity only.

**Architecture**: DDH and Platform are separate applications with separate identities.
DDH does NOT directly access Silver Storage — it consumes processed data through Platform APIs.

```
DDH Application                         Geospatial Platform
(separate identity)                     (separate identity)
       │                                       │
       ├── writes to ──▶ Bronze Storage        │
       │                      │                │
       ├── calls ──────▶ Platform API ◀────────┤
       │                (jobs, features,       │
       │                 raster, stac)         │
       │                      │                │
       │                      ▼                │
       │              Silver Storage ◀─────────┤
       │              (Platform only)          │
       │                      │                │
       └── reads via API ◀────┘                │
```

| Scenario | Authentication Method |
|----------|----------------------|
| DDH → Bronze Storage (write) | DDH's managed identity + RBAC |
| DDH → Platform API | DDH's managed identity + Azure AD token |
| Platform → Database | Platform's managed identity |
| Platform → Bronze/Silver Storage | Platform's managed identity |
| External APIs (if unavoidable) | Key Vault (exception only) |

### F3.2 Access Matrix

| Component | DDH Access | Notes |
|-----------|:----------:|-------|
| **Bronze Storage Account** | Write | Upload raw data for processing |
| **Silver Storage Account** | None | Platform-only; DDH reads via API |
| **Platform API** `/api/jobs/*` | Read/Write | Submit and monitor jobs |
| **Platform API** `/api/features/*` | Read | Query OGC Features |
| **Platform API** `/api/raster/*` | Read | Query raster extracts |
| **Platform API** `/api/stac/*` | Read | Query STAC catalog |

### F3.2 Prerequisites

- [x] **Decision**: S3.2.1 ✅ Managed Identity only — no secrets, no tokens
- [x] **DDH Identity**: S3.2.2 ✅ DDH already has its own managed identity
- [x] **Bronze Access**: S3.2.3 ✅ DDH has write access to bronze container
- [ ] **API Access**: S3.2.4 — Configure Function App to accept DDH identity

---

### Feature F3.3: Environment Provisioning 📋 PLANNED

**Owner**: DevOps (provisioning) + Geospatial Team (validation)
**Deliverable**: Replicate integration configuration across environments

**Key Simplification**: QA and UAT share the same PDMZ (Protected DMZ), so existing QA
user-assigned managed identities can be reused for UAT. No new service principals needed.

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S3.3.1 | ✅ | QA environment baseline | — | Current state operational |
| S3.3.2 | 📋 | Document QA configuration | DevOps | Checklist covers all items in table below |
| S3.3.3 | 📋 | Configure UAT resource access | DevOps | QA identities granted access to UAT resources |
| S3.3.4 | 📋 | Deploy UAT Function App | DevOps | UAT Function App exists, uses same managed identity |
| S3.3.5 | 📋 | Validate UAT integration | Joint | DDH can submit job, poll status, query results |
| S3.3.6 | 📋 | Provision Production | DevOps | Production may require separate identities (different PDMZ) |
| S3.3.7 | 📋 | Document connection strings | DevOps | Environment config template published |

### F3.3 Identity Reuse Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    PDMZ (Protected DMZ)                      │
│  ┌──────────────────────┐    ┌──────────────────────────┐  │
│  │   QA Environment      │    │   UAT Environment         │  │
│  │   • QA Function App   │    │   • UAT Function App      │  │
│  │   • QA Storage        │    │   • UAT Storage           │  │
│  │   • QA Database       │    │   • UAT Database          │  │
│  └──────────┬───────────┘    └────────────┬─────────────┘  │
│             │                              │                 │
│             └──────────┬───────────────────┘                 │
│                        ▼                                     │
│            ┌────────────────────────┐                        │
│            │ Shared User-Assigned   │                        │
│            │ Managed Identities     │                        │
│            │ (reused across QA/UAT) │                        │
│            └────────────────────────┘                        │
└─────────────────────────────────────────────────────────────┘

Production (separate PDMZ) → May require separate identities
```

### F3.3 Configuration Checklist (S3.3.2 Deliverable)

Export the following from QA for replication to UAT/Prod:

| Category | Item | QA/UAT Shared? | Example Value (Abstract) |
|----------|------|:--------------:|--------------------------|
| **Compute** | ETL Function App URL | No | `https://{etl-function-app}.azurewebsites.net` |
| **Storage** | Bronze Storage Account | No | `{bronze-storage}.blob.core.windows.net` |
| **Storage** | Silver Storage Account | No | `{silver-storage}.blob.core.windows.net` |
| **Database** | PostgreSQL Host | No | `{pg-server}.postgres.database.azure.com` |
| **Queue** | Service Bus Namespace | No | `{servicebus-namespace}.servicebus.windows.net` |
| **Identity** | App Managed Identity | **Yes** | Same identity used for QA and UAT |
| **Identity** | DDH Managed Identity | **Yes** | Same identity used for QA and UAT |
| **Tile Service** | TiTiler Raster URL | TBD | `https://{titiler-raster}.azurecontainerapps.io` |

### F3.3 Environment Progression

```
QA (current) ──S3.3.2──▶ Document ──S3.3.3-4──▶ UAT ──S3.3.5──▶ Validate ──S3.3.6──▶ Prod
                              │                                      │
                              └──────── Iterate if issues ───────────┘

Note: S3.3.3 is simplified — no new identities needed for UAT (same PDMZ as QA)
```

---

### Feature F3.4: Integration Verification 📋 PLANNED

**Owner**: ITSDA Team + Geospatial Team
**Deliverable**: End-to-end test suite validating integration contract

| Story | Status | Description |
|-------|--------|-------------|
| S3.4.1 | 📋 | Define integration test scenarios with ITSDA |
| S3.4.2 | 📋 | Write vector dataset publish round-trip test |
| S3.4.3 | 📋 | Write raster dataset publish round-trip test |
| S3.4.4 | 📋 | Write OGC Features query verification test |
| S3.4.5 | 📋 | Write job status polling verification test |
| S3.4.6 | 📋 | Document expected response times and SLAs |

---

### Feature F3.5: Job Completion Callbacks 🔵 BACKLOG

**Status**: Deferred — polling pattern is the supported integration contract
**Trigger**: Revisit if polling creates unacceptable API load or latency issues

| Story | Status | Description | ITSDA |
|-------|--------|-------------|:-----:|
| S3.5.1 | 🔵 | Design callback payload schema | Consumes |
| S3.5.2 | 🔵 | Add callback_url parameter to job submission | — |
| S3.5.3 | 🔵 | Implement webhook POST on job completion/failure | Receives |
| S3.5.4 | 🔵 | Add retry logic for failed callbacks | — |

---

### Feature F3.6: Health & Diagnostics ✅ COMPLETE

**Deliverable**: Comprehensive health and status APIs for integration monitoring
**Owner**: Geospatial Team (complete)

| Story | Status | Description | ITSDA |
|-------|--------|-------------|:-----:|
| S3.6.1 | ✅ | Enhanced /api/health endpoint | Consumes |
| S3.6.2 | ✅ | Platform status for DDH (/api/platform/*) | Consumes |
| S3.6.3 | ✅ | 29 dbadmin endpoints | — |

**Key Files**: `web_interfaces/health/`, `triggers/admin/db_*.py`

---

### Feature F3.7: Error Telemetry ✅ COMPLETE

**Deliverable**: Structured logging and retry tracking
**Owner**: Geospatial Team (complete)

| Story | Status | Description |
|-------|--------|-------------|
| S3.7.1 | ✅ | Add error_source field to logs |
| S3.7.2 | ✅ | Create 6 retry telemetry checkpoints |
| S3.7.3 | ✅ | Implement log_nested_error() helper |
| S3.7.4 | ✅ | Add JSON deserialization error handling |

**Key Files**: `core/error_handler.py`, `core/machine.py`

---

### Feature F3.8: Verbose Validation 🔵 BACKLOG

**Deliverable**: Enhanced error context for debugging
**Owner**: Geospatial Team

| Story | Status | Description |
|-------|--------|-------------|
| S3.8.1 | 🔵 | Verbose pre-flight validation |
| S3.8.2 | 🔵 | Unified DEBUG_MODE |

---

---

## E3 ITSDA Dependency Summary

Stories requiring ITSDA team action or coordination:

| Feature | Story | ITSDA Role | Description |
|---------|-------|------------|-------------|
| F3.1 | S3.1.1-7 | **Reviews** | Must review/approve API documentation |
| F3.2 | S3.2.3 | **Provides** | Must provide DDH managed identity client ID |
| F3.2 | S3.2.4 | **Provides** | Must confirm DDH can reach Platform API endpoints |
| F3.3 | S3.3.3-4 | **Provides** | Must create DDH identity in UAT/Prod Azure AD |
| F3.3 | S3.3.5 | **Executes** | Must run integration tests from DDH side |
| F3.4 | S3.4.1 | **Co-owns** | Must define test scenarios jointly |
| F3.4 | S3.4.2-5 | **Executes** | Must write/run tests from DDH side |
| F3.5 | S3.5.3 | **Implements** | Must implement callback receiver (if activated) |
| F3.6 | S3.6.1-2 | **Consumes** | Uses health/status endpoints for monitoring |

**Legend**:
- **Reviews**: ITSDA reviews Platform team output
- **Provides**: ITSDA provides information or resources
- **Executes**: ITSDA performs the action
- **Co-owns**: Joint ownership
- **Consumes**: ITSDA uses the output (no action needed)
- **Implements**: ITSDA builds functionality on their side

---

---

## Epic E4: Data Externalization 📋

**Business Requirement**: Controlled data movement to external access zones
**Status**: 📋 PLANNED

```
INTERNAL ZONE                    EXTERNAL ZONE
(Bronze/Silver Storage)    →     (External Storage Account)
              ↓
     Approval + Data Factory Copy
              ↓
         CDN/WAF
              ↓
       Public Access
```

### Architecture: Python ↔ Data Factory Integration

```
ETL Function App (Python)              Azure Data Factory              Target
┌─────────────────────────┐           ┌─────────────────────┐        ┌─────────────┐
│ AzureDataFactoryRepository │──────▶│ Pipeline Execution  │───────▶│ External    │
│ • trigger_pipeline()     │◀──────│ • Copy Activity     │        │ Storage     │
│ • wait_for_completion()  │ status │ • Linked Services   │        │ or Database │
│ • get_activity_runs()    │        │ • Parameterized     │        │             │
└─────────────────────────┘          └─────────────────────┘        └─────────────┘
        Python side                        ADF GUI side                 Infra side
     (Geospatial owns)                  (DevOps owns)               (DevOps owns)
```

**Python Status**: ✅ `AzureDataFactoryRepository` built (`infrastructure/data_factory.py`)

---

### Feature F4.1: Publishing Workflow 📋 PLANNED

**Owner**: Geospatial Team
**Deliverable**: Approval queue, audit log, status APIs

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S4.1.1 | ⬜ | Design publish schema (`app.publish_queue`, `app.publish_audit_log`) |
| S4.1.2 | ⬜ | Create publishing repository |
| S4.1.3 | ⬜ | Submit for review endpoint |
| S4.1.4 | ⬜ | Approve/Reject endpoints |
| S4.1.5 | ⬜ | Status check endpoint |
| S4.1.6 | ⬜ | Audit log queries |

---

### Feature F4.2: ADF Python Integration 🚧 PARTIAL

**Owner**: Geospatial Team
**Deliverable**: Python code to trigger and monitor ADF pipelines
**Depends on**: F4.4 (ADF infrastructure must exist first)

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.2.1 | ✅ | Create `AzureDataFactoryRepository` | Repository can trigger, poll, wait for pipelines |
| S4.2.2 | ✅ | Add ADF config to `app_config.py` | `adf_subscription_id`, `adf_factory_name`, `adf_resource_group` |
| S4.2.3 | ⬜ | Integrate approve endpoint with ADF trigger | `/api/publish/approve` triggers ADF pipeline |
| S4.2.4 | ⬜ | Add ADF status polling to audit log | Audit log updated with copy status |
| S4.2.5 | ⬜ | Add ADF health check to `/api/health` | Health endpoint shows ADF connectivity |
| S4.2.6 | ⬜ | Create `/api/adf/pipelines` listing endpoint | List available pipelines for debugging |
| S4.2.7 | ⬜ | Create `/api/adf/status/{run_id}` endpoint | Check pipeline run status |

**Key Files**: `infrastructure/data_factory.py`, `infrastructure/interface_repository.py`

### F4.2 Python Usage Pattern

```python
# Triggered from approve endpoint after approval workflow completes
from infrastructure import RepositoryFactory

adf_repo = RepositoryFactory.create_data_factory_repository()

# Trigger the pipeline
result = adf_repo.trigger_pipeline(
    pipeline_name="CopyBlobToExternal",
    parameters={
        "source_container": "silver-cogs",
        "source_blob": "rasters/dataset-123/file.tif",
        "destination_container": "public",
        "destination_blob": "rasters/dataset-123/file.tif"
    },
    reference_name=job_id  # For correlation in logs
)

# Optionally wait for completion (or poll asynchronously)
final = adf_repo.wait_for_pipeline_completion(result['run_id'])
# Returns: {'status': 'Succeeded', 'duration_ms': 45000, ...}
```

---

### Feature F4.3: External Delivery Infrastructure 🚧 PARTIAL

**Owner**: DevOps (infrastructure)
**Deliverable**: External storage, database, CDN, and identity configuration

**Current State**: Storage and database are **provisioned** but need validation and configuration.

#### Phase 1: Storage Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.1 | ✅ | Create **External Storage Account** | DevOps | Storage account exists |
| S4.3.2 | ⬜ | Validate storage access | DevOps | Confirm connectivity, list containers |
| S4.3.3 | ⬜ | Configure storage RBAC | DevOps | Required identities have appropriate roles |
| S4.3.4 | ⬜ | Configure storage CORS | DevOps | CORS allows reads from approved domains |

#### Phase 2: Database Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.5 | ✅ | Create **External PostgreSQL** | DevOps | Database server exists |
| S4.3.6 | ⬜ | Validate database connectivity | DevOps | Can connect from approved networks |
| S4.3.7 | ⬜ | Install PostGIS extension | DevOps | **Service Request Required** — PostGIS enabled on external DB |
| S4.3.8 | ⬜ | Create external schemas | Geospatial | `geo`, `app`, `pgstac` schemas created |
| S4.3.9 | ⬜ | Configure database RBAC | DevOps | Required identities have appropriate roles |

#### Phase 3: Identity Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.10 | ⬜ | Create **External Reader Identity** | DevOps | User-assigned managed identity for external read access |
| S4.3.11 | ⬜ | Grant External Reader → External Storage | DevOps | `Storage Blob Data Reader` on external storage |
| S4.3.12 | ⬜ | Grant External Reader → External Database | DevOps | Read-only access to external PostgreSQL |
| S4.3.13 | ⬜ | Document identity separation | DevOps | Internal vs External reader identity matrix |

### F4.3 Identity Separation

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        INTERNAL ZONE                                     │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐ │
│  │ Internal Reader ID   │────────▶│ Bronze/Silver Storage            │ │
│  │ (existing)           │         │ Internal PostgreSQL              │ │
│  └──────────────────────┘         └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL ZONE                                     │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐ │
│  │ External Reader ID   │────────▶│ External Storage                 │ │
│  │ (NEW - S4.3.10)      │         │ External PostgreSQL              │ │
│  └──────────────────────┘         └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘

Principle: Separate identities for internal vs external access
```

#### Phase 4: CDN/WAF Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.14 | ⬜ | Create Cloudflare zone | DevOps | Zone exists for external data domain |
| S4.3.15 | ⬜ | Configure **CDN/WAF** caching rules | DevOps | COGs and vectors cached at edge |
| S4.3.16 | ⬜ | Configure **CDN/WAF** security rules | DevOps | Rate limiting, bot protection enabled |
| S4.3.17 | ⬜ | Configure custom domain DNS | DevOps | CNAME points to Cloudflare |
| S4.3.18 | ⬜ | Validate end-to-end access | DevOps | Public URL serves data through CDN |

### F4.3 Cloudflare Configuration

**Caching Rules**:
| Path Pattern | Cache TTL | Notes |
|--------------|-----------|-------|
| `*.tif`, `*.tiff` | 7 days | COG files rarely change |
| `*.geojson` | 1 day | Vector exports |
| `*.parquet` | 7 days | Analytics exports |
| `*/metadata.json` | 1 hour | STAC-like metadata |

**Security Rules**:
| Rule | Setting | Rationale |
|------|---------|-----------|
| Rate Limiting | 1000 req/min per IP | Prevent abuse |
| Bot Protection | Challenge suspicious | Block scrapers |
| Hotlink Protection | Enabled | Prevent bandwidth theft |
| Browser Integrity Check | Enabled | Block headless browsers |

### F4.3 Service Requests Required

| Item | Request Type | Notes |
|------|--------------|-------|
| **PostGIS on External DB** | Service Request | Azure Flexible Server requires support ticket for extensions |

---

### Feature F4.4: ADF Infrastructure & Pipelines 📋 PLANNED

**Owner**: DevOps (100% Azure Portal / CLI / ARM work — no Python)
**Deliverable**: Functional ADF instance with copy pipelines
**Skills Needed**: Azure Portal, Data Factory GUI, ARM templates, Azure RBAC

> **For DevOps teammates**: This feature is entirely Azure infrastructure work.
> No Python or geospatial knowledge required. Standard Azure Data Factory patterns.

#### Phase 1: ADF Instance Setup

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.1 | ⬜ | Create Data Factory instance | `az datafactory create --name rmhazureadf --resource-group rmhazure_rg` succeeds |
| S4.4.2 | ⬜ | Enable system-assigned managed identity | ADF has managed identity in Azure AD |
| S4.4.3 | ⬜ | Grant ADF read access to Silver Storage | `Storage Blob Data Reader` role on `rmhstorage123` |
| S4.4.4 | ⬜ | Grant ADF write access to External Storage | `Storage Blob Data Contributor` role on external account |
| S4.4.5 | ⬜ | Document ADF resource names | Add to environment config template |

#### Phase 2: Linked Services (Connections)

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.6 | ⬜ | Create Silver Storage linked service | ADF can connect to Silver using managed identity |
| S4.4.7 | ⬜ | Create External Storage linked service | ADF can connect to External using managed identity |
| S4.4.8 | ⬜ | Test linked service connections | "Test connection" succeeds in ADF UI |

#### Phase 3: Pipeline Development (GUI)

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.9 | ⬜ | Create `CopyBlobToExternal` pipeline | Pipeline exists in ADF with Copy activity |
| S4.4.10 | ⬜ | Add pipeline parameters | Accepts `source_container`, `source_blob`, `destination_container`, `destination_blob` |
| S4.4.11 | ⬜ | Configure Copy activity source | Uses Silver linked service + parameterized path |
| S4.4.12 | ⬜ | Configure Copy activity sink | Uses External linked service + parameterized path |
| S4.4.13 | ⬜ | Add logging/audit activity (optional) | Pipeline logs execution metadata |

#### Phase 4: Testing & Validation

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.14 | ⬜ | Manual pipeline test (Debug) | Run in ADF Debug mode with test parameters |
| S4.4.15 | ⬜ | Trigger test from Azure CLI | `az datafactory pipeline create-run` succeeds |
| S4.4.16 | ⬜ | Monitor run in ADF UI | Can see run status, duration, rows copied |
| S4.4.17 | ⬜ | Verify blob in External Storage | Copied file exists and is identical to source |

#### Phase 5: Function App Configuration

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.18 | ⬜ | Set `ADF_SUBSCRIPTION_ID` in Function App | Environment variable configured |
| S4.4.19 | ⬜ | Set `ADF_FACTORY_NAME` in Function App | Environment variable configured |
| S4.4.20 | ⬜ | Grant Function App identity access to ADF | Function App can trigger pipelines |
| S4.4.21 | ⬜ | End-to-end Python→ADF test | `/api/adf/pipelines` returns list successfully |

### F4.4 Pipeline Parameters Schema

```json
{
  "source_container": "silver-cogs",
  "source_blob": "rasters/dataset-123/file.tif",
  "destination_container": "public",
  "destination_blob": "rasters/dataset-123/file.tif"
}
```

### F4.4 Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Azure Data Factory                                │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Pipeline: CopyBlobToExternal                                    │ │
│  │  ┌─────────────┐    ┌────────────────┐    ┌─────────────────┐  │ │
│  │  │ Parameters  │───▶│ Copy Activity  │───▶│ (Optional)      │  │ │
│  │  │ source_*    │    │ Binary copy    │    │ Logging/Audit   │  │ │
│  │  │ dest_*      │    │ No transform   │    │ Activity        │  │ │
│  │  └─────────────┘    └───────┬────────┘    └─────────────────┘  │ │
│  └─────────────────────────────┼─────────────────────────────────────┘ │
│                                │                                      │
│  ┌─────────────────────────────┼─────────────────────────────────────┐ │
│  │  Linked Services            │                                     │ │
│  │  ┌──────────────────┐       │       ┌──────────────────────────┐ │ │
│  │  │ SilverStorage    │───────┴──────▶│ ExternalStorage          │ │ │
│  │  │ (Managed ID)     │  Binary copy  │ (Managed ID)             │ │ │
│  │  │ Blob Data Reader │               │ Blob Data Contributor    │ │ │
│  │  └──────────────────┘               └──────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### F4.4 Azure CLI Quick Reference (for DevOps)

```bash
# Phase 1: Create ADF
az datafactory create \
  --name rmhazureadf \
  --resource-group rmhazure_rg \
  --location eastus

# Enable managed identity (usually automatic with create)
az datafactory show --name rmhazureadf --resource-group rmhazure_rg \
  --query identity

# Phase 1: Grant storage access
ADF_PRINCIPAL_ID=$(az datafactory show --name rmhazureadf \
  --resource-group rmhazure_rg --query identity.principalId -o tsv)

# Reader on Silver
az role assignment create \
  --assignee $ADF_PRINCIPAL_ID \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/{sub}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhstorage123

# Contributor on External
az role assignment create \
  --assignee $ADF_PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/{sub}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/{external-account}

# Phase 5: Set Function App env vars
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings ADF_SUBSCRIPTION_ID={subscription-id} ADF_FACTORY_NAME=rmhazureadf
```

---

### Feature F4.5: Database-to-Database Pipelines 🔵 BACKLOG

**Owner**: DevOps (ADF) + Geospatial Team (triggers)
**Deliverable**: ADF pipelines for database copy operations
**Status**: Deferred — implement when database promotion workflow is needed

> **Use Case**: Copy staging tables to production, or archive data between databases.
> Similar pattern to blob copy, but uses Azure Database linked services.

| Story | Status | Description |
|-------|--------|-------------|
| S4.5.1 | 🔵 | Create PostgreSQL linked service | ADF connects to Business Database |
| S4.5.2 | 🔵 | Create `CopyTableToProduction` pipeline | Parameterized table copy |
| S4.5.3 | 🔵 | Add database triggers to Python repo | Same pattern as blob triggers |

---

### E4 Dependency Summary

```
F4.4: ADF Infrastructure ──────────────▶ F4.2: Python Integration
        (DevOps)                              (Geospatial)
            │                                      │
            ▼                                      ▼
F4.3: External Storage ─────────────────▶ F4.1: Publishing Workflow
        (DevOps)                              (Geospatial)
                                                   │
                                                   ▼
                                          End-to-End Testing
```

**Critical Path**: F4.4 → F4.2 → F4.1 → Integration Testing

---

---

## Epic E5: OGC Styles 🚧

**Business Requirement**: Support styling metadata for all data formats
**Status**: 🚧 PARTIAL
**Note**: Building capability first; population method (SLD ingest vs manual) TBD

### Feature F5.1: OGC API Styles ✅

**Deliverable**: CartoSym-JSON storage with multi-format output

| Story | Description |
|-------|-------------|
| S5.1.1 | Create Pydantic models |
| S5.1.2 | Build style translator (CartoSym → Leaflet/Mapbox) |
| S5.1.3 | Create repository layer |
| S5.1.4 | Implement service orchestration |
| S5.1.5 | Create GET /features/collections/{id}/styles |
| S5.1.6 | Create GET /features/collections/{id}/styles/{sid} |
| S5.1.7 | Add geo.feature_collection_styles table |

**Key Files**: `ogc_styles/`

**Tested**: 18 DEC 2025 - All three output formats verified (Leaflet, Mapbox GL, CartoSym-JSON)

---

### Feature F5.2: ETL Style Integration 📋 PLANNED

**Deliverable**: Auto-create default styles on vector ingest

| Story | Status | Description |
|-------|--------|-------------|
| S5.2.1 | 📋 | Design default style templates |
| S5.2.2 | 📋 | Integrate into process_vector job |

---

---

## Epic E7: Custom Data Pipelines 🚧

**Business Requirement**: Custom ETL pipelines for strategic partners with modern, cloud-native data patterns
**Status**: 🚧 PARTIAL (infrastructure complete, FATHOM pipeline in progress)
**Key Partner**: FATHOM (flood risk analytics)

**Strategic Context**:
> Partners like FATHOM are embracing "future ready" data patterns — Zarr-first, cloud-optimized,
> analysis-ready. E7 builds partner-specific pipelines that align with these modern standards
> while leveraging our core ETL infrastructure.

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

### Feature F7.2: FATHOM Flood Data Pipeline ⬜ READY

**Deliverable**: End-to-end pipeline for FATHOM flood risk data
**Partner**: FATHOM
**Data Patterns**: Zarr (preferred), COG (fallback)

| Story | Status | Description |
|-------|--------|-------------|
| S7.2.1 | ⬜ | FATHOM data inventory and schema analysis |
| S7.2.2 | ⬜ | FATHOM handler implementation |
| S7.2.3 | ⬜ | Zarr output configuration (chunking, compression) |
| S7.2.4 | ⬜ | STAC collection with datacube extension |
| S7.2.5 | ⬜ | **TiTiler Zarr Service** integration for tile serving |
| S7.2.6 | ⬜ | Manual update trigger endpoint |

**FATHOM Data Characteristics**:
- Global flood hazard maps (fluvial, pluvial, coastal)
- Multiple return periods (1-in-5 to 1-in-1000 year)
- High resolution (3 arcsec / ~90m)
- Time-series projections (climate scenarios)

**Target Architecture**:
```
FATHOM Source       ETL Function App       Consumer Access
┌─────────────┐    ┌─────────────────┐    ┌───────────────────┐
│ GeoTIFF or  │───▶│ Zarr conversion │───▶│ TiTiler Zarr      │
│ NetCDF      │    │ + STAC catalog  │    │ Service           │
└─────────────┘    └─────────────────┘    └───────────────────┘
                          │
                          ▼
                   Silver Storage Account
                   (cloud-optimized Zarr)
```

---

### Feature F7.3: Reference Data Pipelines 📋 PLANNED

**Deliverable**: Common reference datasets for spatial joins

| Story | Status | Description |
|-------|--------|-------------|
| S7.3.1 | 📋 | Admin0 handler (Natural Earth boundaries) |
| S7.3.2 | 📋 | WDPA updates (protected areas) |
| S7.3.3 | 📋 | Style integration (depends on E5) |

---

---

## Epic E8: H3 Analytics Pipeline 🚧

**Business Requirement**: Columnar aggregations of raster/vector data to H3 hexagonal grid
**Status**: 🚧 PARTIAL (Infrastructure complete, aggregation handlers in progress)

**Architecture**:
```
Source Data           H3 Aggregation          Output
┌─────────────┐       ┌───────────────┐       ┌─────────────────┐
│ Rasters     │──────▶│ Zonal Stats   │──────▶│ PostgreSQL OLTP │
│ (COGs)      │       │ (mean,sum,etc)│       │ (h3.zonal_stats)│
├─────────────┤       ├───────────────┤       ├─────────────────┤
│ Vectors     │──────▶│ Point Counts  │──────▶│ GeoParquet OLAP │
│ (PostGIS)   │       │ (category agg)│       │ (DuckDB export) │
└─────────────┘       └───────────────┘       └─────────────────┘
```

### Feature F8.1: H3 Grid Infrastructure ✅

**Deliverable**: Normalized H3 schema with cell-country mappings

| Story | Status | Description |
|-------|--------|-------------|
| S8.1.1 | ✅ | Design normalized schema (cells, cell_admin0, cell_admin1) |
| S8.1.2 | ✅ | Create stat_registry metadata catalog |
| S8.1.3 | ✅ | Create zonal_stats table for raster aggregations |
| S8.1.4 | ✅ | Create point_stats table for vector aggregations |
| S8.1.5 | ✅ | Create batch_progress table for idempotency |
| S8.1.6 | ✅ | Implement H3Repository with COPY-based bulk inserts |

**Key Files**: `infrastructure/h3_schema.py`, `infrastructure/h3_repository.py`, `infrastructure/h3_batch_tracking.py`

---

### Feature F8.2: Grid Bootstrap System ✅

**Deliverable**: 3-stage cascade job generating res 2-7 pyramid

| Story | Status | Description |
|-------|--------|-------------|
| S8.2.1 | ✅ | Create generate_h3_grid handler (base + cascade modes) |
| S8.2.2 | ✅ | Create cascade_h3_descendants handler (multi-level) |
| S8.2.3 | ✅ | Create finalize_h3_pyramid handler |
| S8.2.4 | ✅ | Create bootstrap_h3_land_grid_pyramid job |
| S8.2.5 | ✅ | Implement batch-level idempotency (resumable jobs) |
| S8.2.6 | ✅ | Add country/bbox filtering for testing |

**Key Files**: `jobs/bootstrap_h3_land_grid_pyramid.py`, `services/handler_generate_h3_grid.py`, `services/handler_cascade_h3_descendants.py`, `services/handler_finalize_h3_pyramid.py`

**Expected Cell Counts** (land-filtered):
- Res 2: ~2,000 | Res 3: ~14,000 | Res 4: ~98,000
- Res 5: ~686,000 | Res 6: ~4.8M | Res 7: ~33.6M

---

### Feature F8.3: Raster→H3 Aggregation 🚧 IN PROGRESS

**Deliverable**: Zonal statistics from COGs to H3 cells

| Story | Status | Description |
|-------|--------|-------------|
| S8.3.1 | ✅ | Create h3_raster_aggregation job definition |
| S8.3.2 | ✅ | Design 3-stage workflow (inventory → compute → finalize) |
| S8.3.3 | ⬜ | Implement h3_inventory_cells handler |
| S8.3.4 | ⬜ | Implement h3_raster_zonal_stats handler |
| S8.3.5 | ⬜ | Implement h3_aggregation_finalize handler |
| S8.3.6 | ✅ | Create insert_zonal_stats_batch() repository method |

**Key Files**: `jobs/h3_raster_aggregation.py`

**Stats Supported**: mean, sum, min, max, count, std, median

---

### Feature F8.4: Vector→H3 Aggregation ⬜ READY

**Deliverable**: Point/polygon counts aggregated to H3 cells

| Story | Status | Description |
|-------|--------|-------------|
| S8.4.1 | ⬜ | Create h3_vector_aggregation job |
| S8.4.2 | ⬜ | Implement point-in-polygon handler |
| S8.4.3 | ⬜ | Implement category grouping |
| S8.4.4 | ✅ | Create insert_point_stats_batch() repository method |

**Schema Ready**: `h3.point_stats` table exists

---

### Feature F8.5: GeoParquet Export 📋 PLANNED

**Deliverable**: Columnar export for OLAP analytics

| Story | Status | Description |
|-------|--------|-------------|
| S8.5.1 | 📋 | Design export job parameters |
| S8.5.2 | 📋 | Implement PostgreSQL → GeoParquet writer |
| S8.5.3 | 📋 | Add DuckDB/Databricks compatibility |
| S8.5.4 | 📋 | Create export_h3_stats job |

---

### Feature F8.6: Analytics API 📋 PLANNED

**Deliverable**: Query endpoints for H3 statistics

| Story | Status | Description |
|-------|--------|-------------|
| S8.6.1 | 📋 | GET /api/h3/stats/{dataset_id} |
| S8.6.2 | 📋 | GET /api/h3/stats/{dataset_id}/cells?iso3=&bbox= |
| S8.6.3 | 📋 | GET /api/h3/registry (list all datasets) |
| S8.6.4 | 📋 | Interactive H3 map interface |

---

### Feature F8.7: Building Exposure Analysis 📋 HIGH PRIORITY

**Deliverable**: Buildings → Raster Extract → H3 Aggregation pipeline
**Documentation**: [BUILDING_EXPOSURE_PIPELINE.md](docs_claude/BUILDING_EXPOSURE_PIPELINE.md)
**Timeline**: ~1 week
**Business Value**: Climate risk exposure analysis for high-profile projects

**Workflow**:
```
Buildings (MS/Google) → Centroids → Raster Sample → H3 Aggregate → GeoParquet
```

| Story | Status | Description |
|-------|--------|-------------|
| S8.7.1 | 📋 | Create `h3.building_exposure` schema |
| S8.7.2 | 📋 | Create `building_exposure_analysis` job definition |
| S8.7.3 | 📋 | Stage 1: `building_centroid_extract` handler |
| S8.7.4 | 📋 | Stage 2: `building_raster_sample` handler (rasterstats) |
| S8.7.5 | 📋 | Stage 3: `building_h3_aggregate` handler (SQL aggregation) |
| S8.7.6 | 📋 | Stage 4: `h3_export_geoparquet` handler |
| S8.7.7 | 📋 | Query API endpoints |
| S8.7.8 | 📋 | End-to-end test: Kenya + FATHOM + MS Buildings |

**Output per H3 Cell**:
- `building_count`: Total buildings
- `mean_exposure`: Average raster value
- `max_exposure`: Maximum raster value
- `pct_exposed_{threshold}`: % buildings above threshold
- `count_exposed_{threshold}`: Count above threshold

**Dependencies**:
- E10.F10.2 (FATHOM merge) for flood COGs
- Planetary Computer for MS Building Footprints
- rasterstats + geopandas for processing

---

---

## Epic E9: Zarr/Climate Data as API 🚧

**Business Requirement**: Zarr/NetCDF data access with time-series query support
**Status**: 🚧 PARTIAL

### Feature F9.1: xarray Service Layer ✅

**Deliverable**: Time-series and statistics endpoints

| Story | Description |
|-------|-------------|
| S9.1.1 | Create xarray reader service |
| S9.1.2 | Implement /api/xarray/point time-series |
| S9.1.3 | Implement /api/xarray/statistics |
| S9.1.4 | Implement /api/xarray/aggregate |

**Key Files**: `xarray_api/`, `services/xarray_reader.py`

---

### Feature F9.2: Virtual Zarr Pipeline 📋 PLANNED

**Deliverable**: Kerchunk reference files enabling cloud-native access to legacy NetCDF

**Strategic Context**:
Eliminates need for traditional THREDDS/OPeNDAP infrastructure. NetCDF files
remain in blob storage unchanged; lightweight JSON references (~KB) enable
**TiTiler Zarr Service** to serve data via modern cloud-optimized patterns.

**Compute Profile**: Azure Function App (reference generation is I/O-bound, not compute-bound)

| Story | Status | Description |
|-------|--------|-------------|
| S9.2.1 | ⬜ | CMIP6 filename parser (extract variable, model, scenario) |
| S9.2.2 | ⬜ | Chunking validator (pre-flight NetCDF compatibility check) |
| S9.2.3 | ⬜ | Reference generator (single NetCDF → Kerchunk JSON ~KB) |
| S9.2.4 | ⬜ | Virtual combiner (merge time-series references) |
| S9.2.5 | ⬜ | STAC datacube registration (xarray-compatible items) |
| S9.2.6 | ⬜ | Inventory job (scan and group NetCDF files) |
| S9.2.7 | ⬜ | Generate job (full reference pipeline) |
| S9.2.8 | ⬜ | **TiTiler Zarr Service** configuration for virtual Zarr serving |

**Dependencies**: `virtualizarr`, `kerchunk`, `h5netcdf`, `h5py`

**Architecture**:
```
NetCDF Files (unchanged)     Reference Generation      TiTiler Zarr Service
┌─────────────────────┐     ┌──────────────────┐     ┌────────────────┐
│ tasmax_2015.nc      │     │                  │     │                │
│ tasmax_2016.nc      │────▶│ Kerchunk JSON    │────▶│ /tiles/{z}/{x} │
│ tasmax_2017.nc      │     │ (~5KB per file)  │     │ /point/{x},{y} │
│ ...                 │     │                  │     │                │
└─────────────────────┘     └──────────────────┘     └────────────────┘
  Bronze Storage Account     Silver Storage Account   Cloud-Native API
     (no conversion)           (lightweight refs)     (no THREDDS)
```

---

### Feature F9.3: Reader App Migration ⬜ READY

**Deliverable**: Move read APIs to **Reader Function App** (clean separation)

| Story | Status | Description |
|-------|--------|-------------|
| S9.3.1 | ⬜ | Copy raster_api module |
| S9.3.2 | ⬜ | Copy xarray_api module |
| S9.3.3 | ⬜ | Copy service clients |
| S9.3.4 | ⬜ | Update requirements.txt |
| S9.3.5 | ⬜ | Register routes |
| S9.3.6 | ⬜ | Deploy and validate |

---

# COMPLETED ENABLERS

Technical foundation that enables all Epics above.

## Enabler EN1: Job Orchestration Engine ✅

**What It Enables**: All ETL jobs (E1, E2, E9)

| Component | Description |
|-----------|-------------|
| CoreMachine | Job→Stage→Task state machine |
| JobBaseMixin | 70%+ code reduction for new jobs |
| Retry Logic | Exponential backoff with telemetry |
| Stage Completion | "Last task turns out the lights" pattern |

**Key Files**: `core/machine.py`, `core/state_manager.py`, `jobs/base.py`, `jobs/mixins.py`

---

## Enabler EN2: Database Architecture ✅

**What It Enables**: Data separation, safe schema management

| Component | Description |
|-----------|-------------|
| Dual Database | App DB (nukeable) vs Business DB (protected) |
| Schema Management | full-rebuild, redeploy, nuke endpoints |
| Managed Identity | Same identity, different permission grants |

**Key Files**: `config/database_config.py`, `triggers/admin/db_maintenance.py`

---

## Enabler EN3: Azure Platform Integration ✅

**What It Enables**: Secure, scalable Azure deployment

| Component | Description |
|-----------|-------------|
| Managed Identity | User-assigned identity for all services |
| Service Bus | Queue-based job orchestration |
| Blob Storage | Bronze/Silver tier with SAS URLs |

**Key Files**: `infrastructure/service_bus.py`, `infrastructure/storage.py`

---

## Enabler EN4: Configuration System ✅

**What It Enables**: Environment-based configuration

| Component | Description |
|-----------|-------------|
| Modular Config | Split from 1200-line monolith |
| Type Safety | Pydantic-based config classes |

**Key Files**: `config/__init__.py`, `config/database_config.py`, `config/storage_config.py`, `config/queue_config.py`, `config/raster_config.py`

---

## Enabler EN5: Pre-flight Validation ✅

**What It Enables**: Early failure before queue submission

| Validator | Description |
|-----------|-------------|
| blob_exists | Validate blob container + name |
| blob_exists_with_size | Combined existence + size check |
| collection_exists | Validate STAC collection |
| stac_item_exists | Validate STAC item |

**Key Files**: `infrastructure/validators.py`

---

# BACKLOG ENABLERS

## Enabler EN6: Long-Running Task Infrastructure ⏳ FY26 DECISION PENDING

**Purpose**: Docker-based worker for tasks exceeding Azure Functions 30-min timeout
**What It Enables**: E2 (oversized rasters), E9 (large climate datasets)
**Reference**: See architecture diagram at `/api/interface/health`
**Owner**: DevOps (infrastructure) + Geospatial Team (handler integration)

**Decision Context**: Deploy as part of FY26 work is pending. Current chunked processing
in Azure Functions handles most use cases. EN6 activates if:
- FATHOM data volumes exceed Function App timeout limits
- Climate data (E9) requires multi-hour processing jobs
- Production workloads demonstrate need for dedicated worker

### EN6 Stories

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| EN6.1 | 📋 | Create **Long-Running Worker** Docker image | DevOps | Image builds, contains GDAL 3.6+, rasterio, xarray, fsspec, adlfs |
| EN6.2 | 📋 | Deploy **Long-Running Worker** to Azure | DevOps | Container runs, has managed identity, can access **Bronze/Silver Storage** |
| EN6.3 | 📋 | Create **Long-Running Task Queue** | DevOps | Queue exists in Service Bus namespace, dead-letter enabled |
| EN6.4 | 📋 | Implement queue listener | DevOps | Worker receives messages, logs receipt, acks on completion |
| EN6.5 | 📋 | Integrate existing handlers | Geospatial | Worker calls `raster_cog.py` functions, writes to **Silver Storage** |
| EN6.6 | 📋 | Add health endpoint | DevOps | `/health` returns 200, shows queue connection status |
| EN6.7 | 📋 | Add routing logic in **ETL Function App** | Geospatial | Jobs exceeding size threshold route to **Long-Running Task Queue** |

### EN6.1 Docker Image Specification

```dockerfile
# Base: Official GDAL image (includes Python + GDAL bindings)
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.6.4

# Python dependencies (copy from ETL Function App requirements)
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt

# Required packages:
# - rasterio>=1.3.0
# - xarray>=2023.1.0
# - zarr>=2.14.0
# - fsspec>=2023.1.0
# - adlfs>=2023.1.0  (Azure blob access)
# - azure-servicebus>=7.11.0
# - azure-identity>=1.14.0

COPY worker/ /app/worker/
WORKDIR /app
CMD ["python", "-m", "worker.main"]
```

### EN6.4 Message Schema

```json
{
  "task_id": "uuid",
  "job_id": "uuid",
  "task_type": "process_large_raster",
  "parameters": {
    "source_blob": "bronze://container/path/to/large.tif",
    "destination_blob": "silver://container/path/to/output.tif",
    "compression": "lzw",
    "options": {}
  },
  "retry_count": 0,
  "submitted_at": "2025-12-19T12:00:00Z"
}
```

### EN6.4 Queue Listener Pattern

```python
# worker/main.py (skeleton)
from azure.servicebus import ServiceBusClient
from azure.identity import DefaultAzureCredential

def process_message(message):
    """Route to appropriate handler based on task_type."""
    payload = json.loads(str(message))
    task_type = payload["task_type"]

    if task_type == "process_large_raster":
        from handlers.raster_cog import process_cog
        result = process_cog(payload["parameters"])
    # ... other task types

    # Report completion back to App Database
    update_task_status(payload["task_id"], "completed", result)

def main():
    credential = DefaultAzureCredential()
    client = ServiceBusClient(namespace, credential)
    receiver = client.get_queue_receiver("long-running-raster-tasks")

    for message in receiver:
        try:
            process_message(message)
            receiver.complete_message(message)
        except Exception as e:
            receiver.dead_letter_message(message, reason=str(e))

if __name__ == "__main__":
    main()
```

**Enables**:
- F2.6 (Large Raster Support) - files exceeding chunked processing limits

---

## Enabler: Repository Pattern Enforcement 🔵

**Purpose**: Eliminate remaining direct database connections

| Task | Status | Notes |
|------|--------|-------|
| Fix triggers/schema_pydantic_deploy.py | ⬜ | Has psycopg.connect |
| Fix triggers/health.py | ⬜ | Has psycopg.connect |
| Fix core/schema/sql_generator.py | ⬜ | Has psycopg.connect |
| Fix core/schema/deployer.py | ⬜ | Review for direct connections |

---

## Enabler: Dead Code Audit 🔵

**Purpose**: Remove orphaned code, reduce maintenance burden

| Task | Status |
|------|--------|
| Audit core/ folder | ⬜ |
| Audit infrastructure/ folder | ⬜ |
| Remove commented-out code | ⬜ |
| Update FILE_CATALOG.md | ⬜ |

---

# COMPLETED ENABLERS (ADDITIONAL)

## Enabler: PgSTAC Repository Consolidation ✅

**Purpose**: Fix "Collection not found after insertion" - two classes manage pgSTAC data
**Completed**: DEC 2025

| Task | Status |
|------|--------|
| Rename PgStacInfrastructure → PgStacBootstrap | ✅ |
| Create PgStacRepository | ✅ |
| Move data operations to PgStacRepository | ✅ |
| Remove duplicate methods | ✅ |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `infrastructure/pgstac_repository.py`

---

# SUMMARY

## Counts

| Category | Count |
|----------|-------|
| Completed Epics | 1 |
| Active Epics | 7 |
| Planned Epics | 2 |
| **Total Epics** | **10** |
| Completed Features | 18 |
| Active Features | 6 |
| Planned Features | 19 |
| **Total Features** | **43** |
| Completed Enablers | 6 |
| Backlog Enablers | 3 |

## For Azure DevOps Import

| ADO Work Item Type | Maps To |
|-------------------|---------|
| Epic | Epic (E1-E9) |
| Feature | Feature (F1.1, F2.1, etc.) |
| User Story | Story (S1.1.1, S2.1.1, etc.) |
| Task | Enabler tasks |

**Cross-Team Assignment**:
- E3 (DDH Platform Integration) → Assign to DDH Team in ADO
- All other Epics → Assign to Geospatial Team

---

## Epic E11: Pipeline Builder Demo App 📋 NEW

**Business Requirement**: Visual demonstration of platform capabilities for stakeholder engagement
**Status**: 📋 PROPOSED
**Owner**: Geospatial Team (demo) → UI Team (production)
**Documentation**: [PIPELINE_BUILDER_VISION.md](docs_claude/PIPELINE_BUILDER_VISION.md)

**Strategic Purpose**:
> "Show leadership what the backend can do. Demonstrate why proper UI investment unlocks value."

**Buzzword Summary** (What we already have):
- ✅ H3 Hexagonal Hierarchical Spatial Index
- ✅ Cloud-Optimized GeoTIFFs (COG)
- ✅ SpatioTemporal Asset Catalog (STAC)
- ✅ OGC API Features & Styles
- ✅ Declarative Pipeline Orchestration
- ✅ Zero-Secret Azure Architecture
- 🚧 Zonal Statistics at Scale
- 📋 Columnar OLAP Export (GeoParquet)

### Feature F11.1: Data Source Browser 📋

**Deliverable**: STAC + Promoted datasets gallery view

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S11.1.1 | 📋 | STAC collection browser with search | `/api/stac/*` ✅ |
| S11.1.2 | 📋 | Promoted datasets gallery view | `/api/promote/gallery` ✅ |
| S11.1.3 | 📋 | Preview thumbnails from TiTiler | TiTiler ✅ |
| S11.1.4 | 📋 | Click to view on map | TiTiler ✅ |

---

### Feature F11.2: Pipeline Composer 📋

**Deliverable**: Visual job submission interface

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S11.2.1 | 📋 | List available job types | `/api/jobs/types` (new) |
| S11.2.2 | 📋 | Visual parameter form generator | Job.parameters_schema ✅ |
| S11.2.3 | 📋 | Submit pipeline and show queue | `/api/jobs/submit/*` ✅ |
| S11.2.4 | 📋 | Real-time job progress tracker | `/api/jobs/status/*` ✅ |

---

### Feature F11.3: H3 Analytics Viewer 📋 (KEY FEATURE)

**Deliverable**: Hexagonal analytics visualization with drill-down

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S11.3.1 | 📋 | H3 hexagon layer (Mapbox GL + deck.gl) | `/api/h3/stats/*/cells` (F8.6) |
| S11.3.2 | 📋 | Resolution switcher (zoom mapping) | H3 pyramid ✅ |
| S11.3.3 | 📋 | Click hexagon → drill to children | H3 schema ✅ |
| S11.3.4 | 📋 | Choropleth styling by stat value | OGC Styles ✅ |
| S11.3.5 | 📋 | Country/Admin filter | `/api/h3/stats?iso3=` (F8.6) |
| S11.3.6 | 📋 | Time slider for temporal stats | xarray service ✅ |

**Blockers**: Requires E8.F8.3 (H3 aggregation handlers) + E8.F8.6 (H3 API)

---

### Feature F11.4: Export & Interoperability 📋

**Deliverable**: Export capabilities for external tools

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S11.4.1 | 📋 | Export H3 stats as GeoParquet | `/api/h3/export` (F8.5) |
| S11.4.2 | 📋 | DuckDB SQL preview (WASM) | Client-side |
| S11.4.3 | 📋 | Copy tile URL for other tools | TiTiler URLs ✅ |
| S11.4.4 | 📋 | STAC item JSON download | `/api/stac/items/*` ✅ |

---

### E11 Technology Stack (Demo Quality)

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Frontend | Vanilla JS + Mapbox GL | "Demo quality" - no framework |
| H3 Rendering | h3-js + deck.gl | Purpose-built for hexagons |
| Hosting | Azure Static Web App | Free tier |
| Backend | Existing APIs | Already production-ready |

---

### E11 Dependencies

```
E8.F8.3: H3 Aggregation Handlers ──┬──▶ E11.F11.3: H3 Viewer
E8.F8.6: H3 Analytics API ─────────┘
E8.F8.5: GeoParquet Export ───────────▶ E11.F11.4: Export
```

**Critical Path**: F8.3 → F8.6 → F11.3 → Demo Ready

---

### E11 Success Criteria

Demo successful if leadership says:
1. "Get real UI developers on this."
2. "Can we show this to [external stakeholder]?"
3. "When can we have a production version?"

---

---

## Epic E12: Interface Modernization 🚧 ACTIVE

**Business Requirement**: Clean, maintainable admin interfaces with modern interactivity
**Status**: 🚧 ACTIVE (Phase 1 in progress)
**Owner**: Geospatial Team
**Documentation**: [NICEGUI.md](docs_claude/NICEGUI.md)

**Strategic Context**:
> Current `web_interfaces/` contains 15 interfaces with ~3,500 LOC of duplicated code.
> Phase 1 cleans up and adds HTMX. Phase 2 evaluates NiceGUI on Docker Web App.

**Architecture**:
```
Phase 1: HTMX (Azure Functions)     Phase 2: NiceGUI (Docker Web App)
┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│ Clean up duplicated code        │ │ Pure Python UI framework        │
│ Add HTMX for interactivity      │ │ Rich components (AG Grid, maps) │
│ Create component library        │ │ WebSocket-based reactivity      │
│ Build Submit Vector interface   │ │ Requires persistent server      │
└─────────────────────────────────┘ └─────────────────────────────────┘
       Works on Azure Functions           Requires Docker Web App
```

---

### Feature F12.1: Interface Cleanup (Enabler) 🚧 IN PROGRESS

**Deliverable**: Consolidated CSS/JS, reusable Python components
**Effort**: 2.5 days

**Current State Audit (23 DEC 2025)**:
| Metric | Value | Issue |
|--------|-------|-------|
| Duplicated CSS | ~2,000 LOC | Dashboard headers copied 9x |
| Duplicated JS | ~1,500 LOC | Same patterns reimplemented |
| Status badge styles | 4 different | Need standardization |
| Filter implementations | 5 different | Need shared component |
| Largest file | health/interface.py (1,979 LOC) | Needs decomposition |

| Story | Status | Description | Effort | Acceptance Criteria |
|-------|--------|-------------|--------|---------------------|
| S12.1.1 | ⬜ | CSS Consolidation | 1 day | Move duplicates to `COMMON_CSS`, remove ~1,500 LOC |
| S12.1.2 | ⬜ | JavaScript Utilities | 0.5 day | Add `formatDate()`, `formatBytes()`, `debounce()`, `handleError()` to `COMMON_JS` |
| S12.1.3 | ⬜ | Python Component Helpers | 1 day | Add `render_header()`, `render_status_badge()`, `render_card()`, `render_empty_state()`, `render_table()` to `BaseInterface` |

**Key Files**: `web_interfaces/base.py`

---

### Feature F12.2: HTMX Integration 🚧 IN PROGRESS

**Deliverable**: HTMX-powered interactivity without custom JavaScript
**Effort**: 2.5 days (includes Storage refactor + Submit Vector)

| Story | Status | Description | Effort | Acceptance Criteria |
|-------|--------|-------------|--------|---------------------|
| S12.2.1 | ⬜ | Add HTMX to BaseInterface | 0.5 day | HTMX loaded in all interfaces, config set |
| S12.2.2 | ⬜ | Refactor Storage Interface | 1 day | Zone→Container cascade via `hx-get`, file loading via HTMX |
| S12.2.3 | ⬜ | Create Submit Vector Interface | 2 days | File browser, form fields, `hx-post` submission |

**HTMX Patterns**:
```html
<!-- Cascading dropdowns (zone → container) -->
<select name="zone" hx-get="/api/interface/storage/containers"
        hx-target="#container-select" hx-trigger="change">

<!-- Form submission with result display -->
<form hx-post="/api/jobs/submit/process_vector"
      hx-target="#result" hx-swap="innerHTML">

<!-- Auto-polling for job status -->
<div hx-get="/api/jobs/status/{job_id}"
     hx-trigger="every 5s" hx-target="this">
```

**Key Files**: `web_interfaces/base.py`, `web_interfaces/storage/interface.py`, `web_interfaces/submit_vector/interface.py` (new)

---

### Feature F12.3: Interface Migration 📋 PLANNED

**Deliverable**: All 15 interfaces using new patterns
**Effort**: 2-3 days

| Story | Status | Description | Priority |
|-------|--------|-------------|----------|
| S12.3.1 | 📋 | Migrate Jobs interface | P1 |
| S12.3.2 | 📋 | Migrate Tasks interface | P1 |
| S12.3.3 | 📋 | Migrate STAC interface | P2 |
| S12.3.4 | 📋 | Migrate Vector interface | P2 |
| S12.3.5 | 📋 | Migrate H3 interface | P2 |
| S12.3.6 | 📋 | Migrate Health interface (decompose 1,979 LOC) | P2 |
| S12.3.7 | 📋 | Migrate remaining interfaces (pipeline, gallery, docs, queues, home, map) | P3 |

---

### Feature F12.4: NiceGUI Evaluation 📋 PHASE 2

**Deliverable**: Proof-of-concept NiceGUI app on Docker Web App
**Status**: 📋 Planned after Phase 1 HTMX completion
**Prerequisite**: Existing Docker Web App infrastructure

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S12.4.1 | 📋 | Create NiceGUI project structure | Docker Web App |
| S12.4.2 | 📋 | Build Storage browser with NiceGUI | `/api/storage/*` ✅ |
| S12.4.3 | 📋 | Build Submit Vector form with NiceGUI | `/api/jobs/submit/*` ✅ |
| S12.4.4 | 📋 | Evaluate developer experience vs HTMX | — |
| S12.4.5 | 📋 | Decision: Migrate more interfaces to NiceGUI? | — |

**NiceGUI Advantages** (if Phase 2 proceeds):
- 60+ UI components (AG Grid, Leaflet maps, charts)
- Pure Python (no HTML/JS strings)
- Reactive data binding
- Tailwind CSS built-in

**NiceGUI Constraints**:
- Requires persistent WebSocket connection
- Cannot run on Azure Functions (serverless)
- Needs Docker Web App or Container Apps

---

### E12 Phased Rollout

```
Phase 1: HTMX (Week 1-2)                    Phase 2: NiceGUI (Week 3+)
┌─────────────────────────────────────┐     ┌─────────────────────────────────┐
│ S12.1.1-3: Cleanup (2.5 days)       │     │ S12.4.1-5: NiceGUI PoC          │
│ S12.2.1: Add HTMX (0.5 day)         │     │ Evaluate on Docker Web App      │
│ S12.2.2: Storage refactor (1 day)   │────▶│ Decision: Expand or stay HTMX   │
│ S12.2.3: Submit Vector (2 days)     │     │                                 │
│ S12.3.*: Migrate others (2-3 days)  │     │                                 │
└─────────────────────────────────────┘     └─────────────────────────────────┘
        Azure Functions                              Docker Web App
```

**Total Phase 1 Effort**: 8-10 days

---

### E12 Success Criteria

**Phase 1 Complete When**:
1. ✅ Duplicated CSS/JS removed from individual interfaces
2. ✅ `BaseInterface` has reusable component methods
3. ✅ Storage interface uses HTMX for dropdowns/file loading
4. ✅ Submit Vector interface works end-to-end
5. ✅ Job submission triggers `process_vector` successfully

**Phase 2 Decision Point**:
After Phase 1, evaluate:
- Is HTMX sufficient for our needs?
- Does NiceGUI's richer component library justify Docker deployment?
- What's the cost/benefit of maintaining two interface patterns?

---

---

**Last Updated**: 23 DEC 2025 (Added E12 Interface Modernization)
