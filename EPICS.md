# SAFe Epic & Feature Registry

**Last Updated**: 19 DEC 2025
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
| 3 | E4 | Data Externalization | 📋 Planned | 3 | 4.3 |
| 4 | E9 | Zarr/Climate Data as API | 🚧 Partial | 3 | 2.0 |
| 5 | E7 | Custom Data Pipelines | 🚧 Partial | 3 | 2.6 |
| 6 | E5 | OGC Styles | 🚧 Partial | 2 | 3.7 |
| 7 | E8 | H3 Analytics Pipeline | 🚧 Partial | 6 | 1.2 |

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
| EN6 | Long-Running Task Infrastructure | 📋 Planned | E2, E9 |

---

# COMPONENT GLOSSARY

Abstract component names for ADO work items. Actual Azure resource names assigned during implementation.

## Storage

| Logical Name | Purpose | Access Pattern |
|--------------|---------|----------------|
| **Bronze Storage Account** | Raw uploaded data | Write: ETL jobs, Read: processing |
| **Silver Storage Account** | Processed COGs, Zarr | Write: ETL jobs, Read: TiTiler, APIs |
| **External Storage Account** | Public-facing data | Write: ADF copy, Read: public CDN |

## Compute

| Logical Name | Purpose | Runtime |
|--------------|---------|---------|
| **ETL Function App** | Job orchestration, HTTP APIs | Azure Functions (Python) |
| **Reader Function App** | Read-only data access APIs | Azure Functions (Python) |
| **Long-Running Worker** | Tasks exceeding 30-min timeout | Docker container (not yet deployed) |
| **TiTiler Raster Service** | COG tile serving | Container App |
| **TiTiler Zarr Service** | Zarr/NetCDF tile serving | Container App (not yet deployed) |

## Queues (Service Bus)

| Logical Name | Purpose |
|--------------|---------|
| **Job Queue** | Initial job submission |
| **Vector Task Queue** | Vector processing tasks |
| **Raster Task Queue** | Raster processing tasks |
| **Long-Running Task Queue** | Overflow to Docker worker |

## Database

| Logical Name | Purpose |
|--------------|---------|
| **App Database** | Job/task state, curated datasets (nukeable) |
| **Business Database** | PostGIS geo schema, pgSTAC catalog (protected) |
| **App Admin Identity** | Managed identity with DDL privileges |
| **App Reader Identity** | Managed identity with read-only privileges |

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
**Status**: 🚧 PARTIAL (collection/mosaic workflow pending)
**Core Complete**: NOV 2025

### Feature F2.1: Raster ETL Pipeline ✅

**Deliverable**: `process_raster_v2` with 3-tier compression

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

### Feature F3.1: API Contract Documentation 📋 PLANNED

**Owner**: Geospatial Team
**Deliverable**: Formal API specification for cross-team development

| Story | Status | Description |
|-------|--------|-------------|
| S3.1.1 | 📋 | Document data access endpoints (OGC Features, Raster, STAC, H3) |
| S3.1.2 | 📋 | Document job submission request/response formats |
| S3.1.3 | 📋 | Document job status polling pattern and response schema |
| S3.1.4 | 📋 | Document STAC item structure for vectors/rasters |
| S3.1.5 | 📋 | Document error response contract |
| S3.1.6 | 📋 | Generate OpenAPI 3.0 spec from existing endpoints |
| S3.1.7 | 📋 | Publish API documentation (Swagger UI or static site) |

---

### Feature F3.2: Identity & Access Configuration 📋 PLANNED

**Owner**: DevOps (Azure config) + Geospatial Team (requirements)
**Deliverable**: Service principals and access grants per environment

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S3.2.1 | ✅ | Authentication strategy decided | — | **Managed Identity only** (see below) |
| S3.2.2 | ✅ | DDH Managed Identity exists | — | DDH already has its own identity |
| S3.2.3 | 📋 | Grant DDH write access to **Bronze Storage Account** | DevOps | DDH identity has `Storage Blob Data Contributor` on bronze container |
| S3.2.4 | 📋 | Grant DDH access to **Platform API** | DevOps | DDH identity can call `/api/*` endpoints |
| S3.2.5 | 📋 | Configure **ETL Function App** authentication | Claude | Function App validates DDH identity on protected endpoints |
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
- [ ] **Bronze Access**: S3.2.3 — Grant DDH write to bronze container
- [ ] **API Access**: S3.2.4 — Configure Function App to accept DDH identity

---

### Feature F3.3: Environment Provisioning 📋 PLANNED

**Owner**: DevOps (provisioning) + Geospatial Team (validation)
**Deliverable**: Replicate integration configuration across environments

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S3.3.1 | ✅ | QA environment baseline | — | Current state operational |
| S3.3.2 | 📋 | Document QA configuration | DevOps | Checklist covers all items in table below |
| S3.3.3 | 📋 | Provision UAT service principals | DevOps | DDH identity exists in UAT Azure AD |
| S3.3.4 | 📋 | Provision UAT storage access | DevOps | Grants match F3.2 Access Matrix |
| S3.3.5 | 📋 | Validate UAT integration | Joint | DDH can submit job, poll status, query results |
| S3.3.6 | 📋 | Provision Production | DevOps | Same as UAT, production resource group |
| S3.3.7 | 📋 | Document connection strings | DevOps | Environment config template published |

### F3.3 Configuration Checklist (S3.3.2 Deliverable)

Export the following from QA for replication to UAT/Prod:

| Category | Item | Example Value (Abstract) |
|----------|------|--------------------------|
| **Compute** | ETL Function App URL | `https://{etl-function-app}.azurewebsites.net` |
| **Compute** | Reader Function App URL | `https://{reader-function-app}.azurewebsites.net` |
| **Storage** | Bronze Storage Account | `{bronze-storage}.blob.core.windows.net` |
| **Storage** | Silver Storage Account | `{silver-storage}.blob.core.windows.net` |
| **Storage** | Bronze Container Name | `uploads` or similar |
| **Storage** | Silver Container Name | `processed` or similar |
| **Database** | PostgreSQL Host | `{pg-server}.postgres.database.azure.com` |
| **Database** | Database Name | `{database-name}` |
| **Queue** | Service Bus Namespace | `{servicebus-namespace}.servicebus.windows.net` |
| **Identity** | DDH Service Principal Client ID | `{guid}` |
| **Identity** | App Admin Managed Identity Client ID | `{guid}` |
| **Tile Service** | TiTiler Raster URL | `https://{titiler-raster}.azurecontainerapps.io` |

### F3.3 Environment Progression

```
QA (current) ──S3.3.2──▶ Document ──S3.3.3-4──▶ UAT ──S3.3.5──▶ Validate ──S3.3.6──▶ Prod
                              │                                      │
                              └──────── Iterate if issues ───────────┘
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

### Feature F4.1: Publishing Workflow 📋 PLANNED

**Owner**: Claude (code)
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

### Feature F4.2: ADF Data Movement 📋 PLANNED

**Owner**: DevOps (ADF infrastructure) + Claude (trigger integration)
**Deliverable**: Blob copy pipelines with approval triggers

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.2.1 | ⬜ | Create **Data Factory Instance** | DevOps | ADF exists in resource group, managed identity enabled |
| S4.2.2 | ⬜ | Grant ADF access to **Silver Storage Account** | DevOps | ADF identity has `Storage Blob Data Reader` |
| S4.2.3 | ⬜ | Grant ADF access to **External Storage Account** | DevOps | ADF identity has `Storage Blob Data Contributor` |
| S4.2.4 | ⬜ | Create blob-to-blob copy pipeline | DevOps | Pipeline accepts source/dest params, copies blob |
| S4.2.5 | ⬜ | Create REST API trigger for pipeline | DevOps | Pipeline can be invoked via HTTP POST |
| S4.2.6 | ⬜ | Integrate approve endpoint with ADF trigger | Claude | `/api/publish/approve` triggers ADF pipeline |
| S4.2.7 | ⬜ | Add ADF status polling to audit log | Claude | Audit log updated with copy status |
| S4.2.8 | ⬜ | Add ADF config to **ETL Function App** | DevOps | Environment variables for ADF endpoint + credentials |

### F4.2 Pipeline Parameters

```json
{
  "source_container": "silver",
  "source_blob_path": "rasters/dataset-123/file.tif",
  "destination_container": "public",
  "destination_blob_path": "rasters/dataset-123/file.tif",
  "dataset_id": "dataset-123",
  "approved_by": "user@example.com",
  "approved_at": "2025-12-19T12:00:00Z"
}
```

### F4.2 Data Flow

```
Silver Storage ──ADF Copy──▶ External Storage ──CDN──▶ Public URL
       │                            │
       └── ADF Identity (Reader) ───┴── ADF Identity (Contributor)
```

---

### Feature F4.3: External Delivery Infrastructure 📋 PLANNED

**Owner**: DevOps (infrastructure)
**Deliverable**: Cloudflare WAF/CDN, external storage

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.1 | ⬜ | Create **External Storage Account** | DevOps | Storage account exists, blob public access enabled |
| S4.3.2 | ⬜ | Configure storage CORS | DevOps | CORS allows reads from approved domains |
| S4.3.3 | ⬜ | Create Cloudflare zone | DevOps | Zone exists for external data domain |
| S4.3.4 | ⬜ | Configure **CDN/WAF** caching rules | DevOps | COGs and vectors cached at edge |
| S4.3.5 | ⬜ | Configure **CDN/WAF** security rules | DevOps | Rate limiting, bot protection enabled |
| S4.3.6 | ⬜ | Configure custom domain DNS | DevOps | CNAME points to Cloudflare |
| S4.3.7 | ⬜ | Validate end-to-end access | DevOps | Public URL serves data through CDN |

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

### F4.3 Dependencies

- **Depends on**: S4.2.3 (ADF needs write access to External Storage)
- **Blocked by**: None (can start immediately)

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

## Enabler EN6: Long-Running Task Infrastructure 📋 PLANNED

**Purpose**: Docker-based worker for tasks exceeding Azure Functions 30-min timeout
**What It Enables**: E2 (oversized rasters), E9 (large climate datasets)
**Reference**: See architecture diagram at `/api/interface/health`
**Owner**: DevOps (infrastructure) + Claude (handler integration)

### EN6 Stories

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| EN6.1 | 📋 | Create **Long-Running Worker** Docker image | DevOps | Image builds, contains GDAL 3.6+, rasterio, xarray, fsspec, adlfs |
| EN6.2 | 📋 | Deploy **Long-Running Worker** to Azure | DevOps | Container runs, has managed identity, can access **Bronze/Silver Storage** |
| EN6.3 | 📋 | Create **Long-Running Task Queue** | DevOps | Queue exists in Service Bus namespace, dead-letter enabled |
| EN6.4 | 📋 | Implement queue listener | DevOps | Worker receives messages, logs receipt, acks on completion |
| EN6.5 | 📋 | Integrate existing handlers | Claude | Worker calls `raster_cog.py` functions, writes to **Silver Storage** |
| EN6.6 | 📋 | Add health endpoint | DevOps | `/health` returns 200, shows queue connection status |
| EN6.7 | 📋 | Add routing logic in **ETL Function App** | Claude | Jobs exceeding size threshold route to **Long-Running Task Queue** |

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
| Active Epics | 6 |
| Planned Epics | 2 |
| **Total Epics** | **9** |
| Completed Features | 17 |
| Active Features | 6 |
| Planned Features | 12 |
| **Total Features** | **35** |
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

**Last Updated**: 19 DEC 2025 (Neutralized language; replaced specific names with Component Glossary terms)
