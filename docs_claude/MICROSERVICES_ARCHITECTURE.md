# Microservices Architecture (Queue-Based Decoupling)

**Date**: 04 FEB 2026 (Updated with Platform = Gateway = Custom Mini-APIM)
**Status**: Design Reference - Migration Ready
**Purpose**: Document queue-based decoupling enabling Function App separation

> **NOTE**: This project uses the **Platform layer as a custom mini-APIM** (API Gateway).
> We do NOT use Azure API Management. The Platform Function App handles:
> - HTTP endpoint exposure for external clients (DDH)
> - Request validation and translation
> - Queue submission to CoreMachine
> - Authentication (Azure AD / Managed Identity)
>
> **Terminology**: Platform = Gateway = Custom Mini-APIM (interchangeable)

---

## Critical Design Principle: Platform = Gateway = Custom Mini-APIM

**The Platform layer IS our API Gateway.** It's a custom mini-APIM that:
- Exposes HTTP endpoints for external clients (DDH)
- Validates and translates requests
- Enqueues jobs to Service Bus
- Returns immediately (async processing)

**The Service Bus queue is the contract boundary between Platform (Gateway) and CoreMachine.**

```
┌─────────────────────────────────────────────────────────────────────────┐
│          PLATFORM (GATEWAY) → QUEUE → COREMACHINE                        │
│                                                                          │
│   Platform/Gateway         SERVICE BUS           CoreMachine Layer       │
│   (Custom Mini-APIM)       (Contract)           (Job Orchestration)      │
│                                                                          │
│   ┌─────────────┐      ┌─────────────┐      ┌─────────────────────┐     │
│   │ Authenticate│      │             │      │ Consume job message │     │
│   │ Validate    │ ───► │ geospatial  │ ───► │ Create tasks        │     │
│   │ Translate   │      │ -jobs queue │      │ Execute handlers    │     │
│   │ Enqueue     │      │             │      │ Detect completion   │     │
│   │ Return 202  │      │             │      │                     │     │
│   └─────────────┘      └─────────────┘      └─────────────────────┘     │
│                                                                          │
│   Gateway knows          Durable,            CoreMachine knows          │
│   NOTHING about          decoupled,          NOTHING about              │
│   job execution          scalable            DDH/Gateway                │
└─────────────────────────────────────────────────────────────────────────┘

Deployments:
  - rmhgeogateway (APP_MODE=platform) - Gateway/Platform endpoints only
  - rmhazuregeoapi (APP_MODE=standalone) - Full monolith (dev/orchestration)
```

**Why This Matters for Migration**:
- Platform and CoreMachine are ALREADY decoupled by the queue
- Splitting to separate Function Apps = deployment change, NOT code change
- Each can scale independently
- Each can be deployed independently
- Fault isolation is built-in

---

## Current vs Future State

### Current: Production-Ready Monolith

**Status**: Fully functional monolithic Function App with queue-based internal decoupling

```
Azure Function App: rmhazuregeoapi (B3 Basic tier)
├── OGC Features (ogc_features/ - 2,600+ lines, standalone)
├── STAC API (pgstac/ + infrastructure/stac.py)
├── Platform Layer (platform schema + triggers) ──┐
│                                                 │ Queue boundary
├── CoreMachine (jobs/tasks + app schema) ────────┘
└── Service Bus Queues (geospatial-jobs, raster-tasks, vector-tasks)
```

**What We've Built**:
1. **STAC API** (pgstac/) - STAC v1.0 metadata catalog for spatial data discovery
2. **OGC Features API** (ogc_features/) - OGC API - Features Core 1.0 for vector feature access
3. **Platform Layer** - B2B API that validates, translates, and enqueues (stateless)
4. **CoreMachine** - Job orchestration that consumes from queue (queue-driven)

**Browser Tested & Operational**:
- 7 vector collections available via OGC Features
- Direct PostGIS queries with GeoJSON serialization
- STAC collections and items serving properly

---

## Future: Microservices Architecture

### Vision

Separate Function Apps communicating via Service Bus queues (NO APIM).

**Key Insight**: Platform and CoreMachine communicate ONLY via Service Bus queues - they can be separate Function Apps with zero code changes. No API gateway needed.

```
Potential Future State (Separate Function Apps):

Function App: rmhgeoapi-platform
  URL: https://rmhgeoapi-platform-xxx.azurewebsites.net
  Routes: /api/platform/*
  Role: B2B API - validates, translates, enqueues

Function App: rmhgeoapi-core
  URL: https://rmhgeoapi-core-xxx.azurewebsites.net
  Routes: /api/jobs/*, Service Bus triggers
  Role: Job orchestration - consumes queue, runs jobs

Function App: rmhgeoapi-data (optional)
  URL: https://rmhgeoapi-data-xxx.azurewebsites.net
  Routes: /api/features/*, /api/stac/*
  Role: Data APIs - OGC Features, STAC
```

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NO API GATEWAY NEEDED                             │
│           Queues provide all necessary coordination                  │
└─────────────────────────────────────────────────────────────────────┘

DDH Client ──► Platform Function App (B2B API)
                        │
                        │ Enqueue JobQueueMessage
                        ▼
              ┌─────────────────────────┐
              │   SERVICE BUS QUEUE     │
              │   "geospatial-jobs"     │
              │                         │
              │   THE CONTRACT          │
              │   No direct calls       │
              │   No shared memory      │
              │   No API gateway        │
              └─────────────────────────┘
                        │
                        │ Consume (Service Bus Trigger)
                        ▼
              CoreMachine Function App (Job Orchestration)
                        │
                        ▼
              PostgreSQL (shared database, separate schemas)
```

### Platform → Queue → CoreMachine (The Contract)

```
Platform Function App                     CoreMachine Function App
━━━━━━━━━━━━━━━━━━━━━━                   ━━━━━━━━━━━━━━━━━━━━━━━━━

POST /api/platform/submit                 Service Bus Trigger
         │                                        │
         ▼                                        ▼
  Validate DDH request                    Consume job message
         │                                        │
         ▼                                        ▼
  Translate to CoreMachine format         Load job definition
         │                                        │
         ▼                                        ▼
  Generate request_id                     Create tasks for stage
         │                                        │
         ▼                                        ▼
  Enqueue to Service Bus ────────────────► Execute handlers
         │                                        │
         ▼                                        ▼
  Return {request_id, queued}             Update job/task status


Platform writes to: app.api_requests (tracking)
CoreMachine writes to: app.jobs, app.tasks (orchestration)
Both read from: PostgreSQL (shared, but separate tables)
```

---

## Benefits of Queue-Based Decoupling (No API Gateway)

| Benefit | How Achieved |
|---------|--------------|
| **Independent Scaling** | Scale CoreMachine workers without touching Platform |
| **Independent Deployment** | Deploy Platform fixes without affecting job processing |
| **Fault Isolation** | Platform failure doesn't affect running jobs |
| **Simple Architecture** | No API gateway to configure, manage, or pay for |
| **Cost Effective** | Service Bus is cheap; APIM is expensive (~$700/mo) |
| **Already Built** | Queue decoupling is in place - just deployment decision |

### Security Without APIM

Each Function App handles its own authentication:
- **Platform API**: Azure AD / Managed Identity validation in code
- **Data APIs**: Azure AD token validation for tenant users
- **Internal**: Service Bus shared access signatures

```python
# Example: Platform API auth in code (no APIM needed)
def validate_request(request):
    token = request.headers.get('Authorization')
    if not validate_azure_ad_token(token, allowed_app_ids=['ddh-app-id']):
        return HttpResponse(status_code=401)
```

---

## Key Design Decisions

### 1. No API Gateway (APIM)

**Decision**: Do NOT use Azure API Management.

| Reason | Explanation |
|--------|-------------|
| **Cost** | APIM Standard is ~$700/month - not justified for this use case |
| **Complexity** | Adds another component to manage, configure, debug |
| **Not Needed** | Service Bus queues provide all necessary decoupling |
| **Auth in Code** | Function Apps can validate Azure AD tokens directly |

### 2. Shared Code Strategy

| Option | Description | Recommendation |
|--------|-------------|----------------|
| **Option A** | Duplicate common modules (config, logger, infrastructure) in each Function App | Start here (simplest) |
| **Option B** | Create shared Python package deployed to private PyPI or Azure Artifacts | When patterns stabilize |
| **Option C** | Git submodules for shared code | Not recommended |

### 3. Database Connection Management
- All Function Apps share same PostgreSQL instance
- Use psycopg3 connection pooling per Function App
- Monitor connection limits carefully
- Memory-first pattern for bulk operations (see ARCHITECTURE_REFERENCE.md)

### 4. When to Split

**Migration Readiness**: HIGH - Queue decoupling is already in place

| Trigger | Action |
|---------|--------|
| **Now** | Continue with monolith, focus on features and data ingestion |
| **Performance** | Split CoreMachine to dedicated Function App (independent scaling) |
| **Deployment Conflicts** | Split Platform to enable independent release cycles |
| **Team Boundaries** | Split when different teams own different APIs |

**Decision Point**: Current monolith works perfectly, but the queue-based architecture means splitting is a deployment decision, not a code rewrite.

**What Splitting Requires**:
1. Create new Function App(s)
2. Copy shared code (config, infrastructure, models)
3. Move relevant triggers/handlers
4. Configure APIM routing
5. Done - queue contract unchanged

---

## Why This Architecture Works

1. **Queue-Based Decoupling** - Platform and CoreMachine communicate only via Service Bus
2. **Standards Compliance** - All APIs follow open standards (STAC, OGC, REST)
3. **Standalone Modules** - OGC Features already designed for separation (zero main app dependencies)
4. **Schema Separation** - PostgreSQL schemas (geo, pgstac, platform, app) enable clean boundaries
5. **No Gateway Lock-in** - Direct Function App URLs, no APIM dependency
6. **Proven Pattern** - Major geospatial platforms use queue-based coordination:
   - Planetary Computer (Microsoft)
   - AWS Open Data
   - Element84 Earth Search

---

## Current Status

**Production-Ready Monolith with Queue Decoupling**:
- All APIs operational and tested
- Standards-compliant implementations
- Platform → Queue → CoreMachine already implemented
- Ready for production data ingestion
- Can scale vertically before needing to split
- Split to microservices = deployment change, NOT code change

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Platform Layer Architecture details |
| [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md) | Visual diagrams including queue contract |
| [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) | Current deployment procedures |
