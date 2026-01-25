## Epic E3: DDH Platform Integration 🚧

**Type**: Enabler
**Value Statement**: DDH consumes geospatial services via documented, stable APIs.
**Runs On**: E1, E2 (Data APIs)
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
