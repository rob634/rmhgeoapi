# Epic E3: DDH Platform Integration

**Type**: Enabler (Cross-Team Coordination)
**Status**: In Progress (50%)
**Last Updated**: 30 JAN 2026
**ADO Feature**: "DDH Platform Integration"
**Owner**: ITSDA Team (DDH) + Geospatial Team (Platform)

---

## Value Statement

Enable DDH (Data Hub Dashboard) to consume geospatial services via documented, stable APIs. This is a coordination epic managing another team's integration with our platform.

---

## Integration Contract

```
DDH Application                    Geospatial Platform
┌─────────────────┐               ┌─────────────────────┐
│                 │──── Submit ──▶│ /api/platform/*     │
│  Data Hub       │               │ (job submission)    │
│  Dashboard      │──── Poll ────▶│ /api/jobs/status/*  │
│                 │               │                     │
│                 │──── Query ───▶│ E6 Service Layer    │
│                 │               │ (TiTiler, TiPG)     │
└─────────────────┘               └─────────────────────┘
```

**Key Principle**: Platform exposes DATA ACCESS APIs. ETL orchestration is internal implementation detail. DDH submits jobs and polls status; callbacks are not part of the supported contract.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F3.1 API Contract Documentation | ✅ | OpenAPI spec, Swagger UI |
| F3.2 Identity & Access Configuration | 🚧 | Managed Identity grants |
| F3.3 Environment Provisioning | 📋 | QA → UAT → Prod |
| F3.4 Integration Verification | 📋 | End-to-end test suite |

---

## Feature Summaries

### F3.1: API Contract Documentation
Formal API specification:
- OpenAPI 3.0 spec: `openapi/platform-api-v1.json`
- Swagger UI: `/api/interface/swagger`
- Documented request/response formats

### F3.2: Identity & Access Configuration
Managed Identity integration:
- No secrets, no tokens - Managed Identity only
- DDH writes to Bronze Storage
- DDH calls Platform API
- DDH reads data via E6 Service Layer

### F3.3: Environment Provisioning (Planned)
Replicate configuration across environments:
- QA baseline documented
- UAT configuration (shared PDMZ, same identities)
- Production configuration (separate PDMZ)

### F3.4: Integration Verification (Planned)
End-to-end test suite:
- Vector dataset publish round-trip
- Raster dataset publish round-trip
- OGC Features query verification
- Job status polling verification

---

## Access Matrix

| Component | DDH Access | Notes |
|-----------|:----------:|-------|
| Bronze Storage | Write | Upload raw data |
| Silver Storage | None | Platform-only |
| Platform API `/api/platform/*` | Read/Write | Submit and monitor jobs |
| E6 Service Layer | Read | Query processed data |

---

## ITSDA Responsibilities

| Area | ITSDA Role |
|------|------------|
| API Documentation | Reviews and approves |
| Identity Configuration | Provides DDH managed identity |
| Integration Tests | Executes from DDH side |
| Environment Setup | Creates identities in each environment |

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E7 Platform API | DDH data publishing |
| E6 Service Layer | DDH data access |
