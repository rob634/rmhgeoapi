# Azure API Management (APIM) Architecture

**Date**: 15 DEC 2025 (Extracted from CLAUDE.md)
**Status**: Future Planning
**Purpose**: Single domain routing to specialized Function Apps

---

## Current vs Future State

### Current: Production-Ready Monolith

**Status**: Fully functional monolithic Function App with 3 standards-compliant APIs

```
Azure Function App: rmhazuregeoapi (B3 Basic tier)
├── OGC Features (ogc_features/ - 2,600+ lines, standalone)
├── STAC API (pgstac/ + infrastructure/stac.py)
├── Platform Layer (platform schema + triggers)
└── CoreMachine (jobs/tasks + app schema)
```

**What We've Built**:
1. **STAC API** (pgstac/) - STAC v1.0 metadata catalog for spatial data discovery
2. **OGC Features API** (ogc_features/) - OGC API - Features Core 1.0 for vector feature access
3. **Platform/CoreMachine** - Custom job orchestration and geospatial data processing

**Browser Tested & Operational**:
- 7 vector collections available via OGC Features
- Direct PostGIS queries with GeoJSON serialization
- STAC collections and items serving properly

---

## Future: Microservices Architecture

### Vision

Single custom domain routing to specialized Function Apps via Azure API Management:

```
User Experience (Single Domain):
https://geospatial.rmh.org/api/features/*     → OGC Features Function App (vector queries)
https://geospatial.rmh.org/api/collections/*  → STAC API Function App (metadata search)
https://geospatial.rmh.org/api/platform/*     → Platform Function App (data ingestion)
https://geospatial.rmh.org/api/jobs/*         → CoreMachine Function App (job processing)
```

### Architecture Diagram

```
Azure API Management (geospatial.rmh.org)
├─→ Function App: OGC Features (ogc_features/ only)
├─→ Function App: STAC API (pgstac/ + stac infrastructure)
├─→ Function App: Platform (platform triggers + orchestration)
└─→ Function App: CoreMachine (job processing + tasks)

All connect to: PostgreSQL (shared database with 4 schemas)
```

---

## APIM Benefits

| Benefit | Description |
|---------|-------------|
| **Seamless User Experience** | Single domain, users never see backend complexity |
| **Granular Access Control** | Different auth rules per API path |
| **Independent Scaling** | Scale each API based on its specific load patterns |
| **Separate Deployments** | Deploy OGC fixes without touching STAC or Platform |
| **API Versioning** | /v1/, /v2/ support for breaking changes |
| **Centralized Security** | Auth, rate limiting, CORS, validation in one place |
| **SSL/TLS Termination** | Custom domain with certificates |
| **Request Transformation** | Modify requests/responses without changing backends |
| **Analytics & Monitoring** | Unified dashboard across all APIs |

---

## Security Architecture with APIM Policies

APIM manages all access control via policies - this is one of its killer features.

### Public API Policy (Open to Tenant Users)

```xml
<policies>
  <inbound>
    <base />
    <validate-azure-ad-token tenant-id="{tenant-id}">
      <audiences>
        <audience>api://geospatial-public</audience>
      </audiences>
    </validate-azure-ad-token>
    <rate-limit calls="1000" renewal-period="60" />
    <cors>
      <allowed-origins>
        <origin>*</origin>
      </allowed-origins>
    </cors>
    <set-backend-service base-url="https://ogc-features-app.azurewebsites.net" />
  </inbound>
</policies>
```

### Internal API Policy (DDH App Only)

```xml
<policies>
  <inbound>
    <base />
    <validate-azure-ad-token tenant-id="{tenant-id}">
      <client-application-ids>
        <application-id>{ddh-app-id}</application-id>
        <!-- Future apps added here -->
        <application-id>{future-app-id}</application-id>
      </client-application-ids>
      <audiences>
        <audience>api://geospatial-internal</audience>
      </audiences>
    </validate-azure-ad-token>
    <rate-limit calls="10000" renewal-period="60" />
    <set-backend-service base-url="https://coremachine-app.azurewebsites.net" />
  </inbound>
</policies>
```

### Security Policy Matrix

| API Path | Access Level | Auth Method | Policy |
|----------|--------------|-------------|--------|
| `/api/features/*` | **Public** (tenant users) | Azure AD token (any tenant user) | Validate AAD token, allow all tenant users |
| `/api/collections/*` | **Public** (tenant users) | Azure AD token (any tenant user) | Validate AAD token, allow all tenant users |
| `/api/platform/*` | **Internal** (DDH app only) | Managed Identity or App Registration | Validate specific client application IDs |
| `/api/jobs/*` | **Internal** (DDH app + future apps) | Managed Identity or App Registration | Validate specific client application IDs list |

---

## APIM Policy Capabilities

### 1. Azure AD Token Validation
- Validate tokens issued by your Azure AD tenant
- Check specific application IDs (DDH app, future apps)
- Verify user roles/groups (e.g., "GeoAdmins" group)
- Check token scopes and audiences

### 2. IP Whitelisting (Optional)
```xml
<ip-filter action="allow">
  <address-range from="10.0.0.0" to="10.255.255.255" />
  <address>12.34.56.78</address>
</ip-filter>
```

### 3. Rate Limiting Per Client
- Different limits for different APIs
- Per-subscription keys
- Per-IP address
- Per-user identity

### 4. Request Validation
- Validate request headers, query params, body
- Block malicious payloads
- Enforce content type restrictions

---

## Product Structure

```
APIM Products (Subscription Units):
├── Public Geospatial Data (open to tenant)
│   ├── /api/features/* → Open (with AAD validation)
│   ├── /api/collections/* → Open (with AAD validation)
│   └── Rate Limit: 1,000 calls/minute
│
└── Internal Processing APIs (restricted apps)
    ├── /api/platform/* → DDH app + future apps only
    ├── /api/jobs/* → DDH app + future apps only
    └── Rate Limit: 10,000 calls/minute (higher for internal)
```

---

## Backend Security

Backend Function Apps can be completely locked down:
- Function Apps don't need their own auth - APIM handles it
- Set Function App auth level to `AuthLevel.ANONYMOUS` (APIM is the gatekeeper)
- Only APIM can reach Function Apps (using VNET integration or private endpoints)
- Even if someone discovers your Function App URLs, they can't access them directly

### Future Enhancement - User Claims in Policies
```xml
<!-- Example: Only allow users in "GeoAdmins" group to submit jobs -->
<check-header name="X-User-Roles" failed-check-httpcode="403">
  <value>GeoAdmins</value>
</check-header>
```

---

## Key Design Decisions

### 1. Shared Code Strategy

| Option | Description | Recommendation |
|--------|-------------|----------------|
| **Option A** | Duplicate common modules (config, logger, infrastructure) in each Function App | Start here (simplest) |
| **Option B** | Create shared Python package deployed to private PyPI or Azure Artifacts | When patterns stabilize |
| **Option C** | Git submodules for shared code | Not recommended |

### 2. Database Connection Management
- All Function Apps share same PostgreSQL instance
- Use psycopg3 connection pooling per Function App
- Consider Azure PostgreSQL connection pooler (PgBouncer)
- Monitor connection limits carefully

### 3. APIM Pricing

| Tier | Cost | Use Case |
|------|------|----------|
| **Developer** | $50/month | Development/testing |
| **Standard** | $700/month | Production-ready with SLA |
| **Consumption** | Pay-per-request | Low-volume or spiky traffic |

### 4. When to Split
- **Now**: Continue with monolith, focus on features and data ingestion
- **Later**: Split when performance bottlenecks or deployment conflicts emerge
- **Decision Point**: Current monolith works perfectly, no urgency to split

---

## Why This Architecture Works

1. **Standards Compliance** - All APIs follow open standards (STAC, OGC, REST)
2. **Standalone OGC Module** - Already designed for separation (zero main app dependencies)
3. **Schema Separation** - PostgreSQL schemas (geo, pgstac, platform, app) enable clean boundaries
4. **Proven Pattern** - Major geospatial platforms use this architecture:
   - Planetary Computer (Microsoft)
   - AWS Open Data
   - Element84 Earth Search

---

## Current Status

**Production-Ready Monolith**:
- All APIs operational and tested
- Standards-compliant implementations
- Ready for production data ingestion
- Can scale vertically (bigger Function App tier) before needing microservices
- APIM can be added later without code changes (just routing configuration)

---

*See Azure API Management Policy Reference for full policy documentation.*
