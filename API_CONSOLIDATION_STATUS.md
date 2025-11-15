# API Consolidation Status - Implementation vs. Plan

**Date**: 14 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Reference**: [FUNCTION_REVIEW.md](FUNCTION_REVIEW.md) (Consolidation Plan)

---

## 🎯 Executive Summary

**Current Implementation**: **81 total functions** in `function_app.py`
**Consolidation Target**: **~35 functions** for production
**Functions to Remove**: **~46 functions** (admin/debug endpoints)

### Implementation Status

| Category | Planned | Implemented | Status | Notes |
|----------|---------|-------------|--------|-------|
| **STAC API** | 16 | ~15 | ✅ **KEEP** | Standards-compliant, production-ready |
| **OGC Features** | 7 | 6 | ✅ **KEEP** | Standards-compliant, production-ready |
| **Platform API** | 5 | 3 | ✅ **KEEP** | Public ingestion interface |
| **CoreMachine** | 7 | 3 | ✅ **KEEP** | Job/task execution (internal) |
| **Database Admin** | 17 (REMOVE) | 31 | ⚠️ **REMOVE IN PROD** | Replace with Log Analytics |
| **Service Bus Admin** | 6 (REMOVE) | 6 | ⚠️ **REMOVE IN PROD** | Replace with Azure Portal |
| **H3 Debug** | 8 (REMOVE) | 1 | ⚠️ **REMOVE IN PROD** | Replace with App Insights |
| **Test/Debug Utilities** | - | ~10 | ⚠️ **REMOVE IN PROD** | Development only |
| **Service Bus Processors** | 2 | 2 | ✅ **KEEP** | Background workers |

**Key Finding**: Admin/debug endpoints have **expanded beyond the original plan** (31 database endpoints vs. 17 planned). This is intentional for development but confirms the consolidation strategy is critical for production.

---

## 📊 Detailed Implementation Analysis

### ✅ Production-Ready APIs (KEEP - 35 functions)

#### 1. STAC API (~15 functions) ✅
**Status**: Standards-compliant, production-ready
**Base Path**: `/api/stac/*` and `/api/collections/*`

**Implemented Endpoints**:
```python
# STAC API v1.0.0 Standard (11 NOV 2025)
GET  /api/stac                                       # Landing page
GET  /api/stac/conformance                           # Conformance classes
GET  /api/stac/collections                           # Collections list
GET  /api/stac/collections/{collection_id}           # Collection detail
GET  /api/stac/collections/{collection_id}/items     # Items list
GET  /api/stac/collections/{collection_id}/items/{item_id} # Item detail

# Legacy STAC endpoints (also working)
GET  /api/collections                                # Alternative collections endpoint
GET  /api/collections/{collection_id}                # Alternative collection detail
GET  /api/collections/{collection_id}/items          # Alternative items list
GET  /api/search                                     # STAC search (GET/POST)

# STAC Infrastructure (admin/inspection - consider removing)
GET  /api/stac/setup                                 # PgSTAC status/installation
POST /api/stac/setup?confirm=yes                     # PgSTAC installation
POST /api/stac/nuke?confirm=yes&mode=all             # NUCLEAR BUTTON (DEV ONLY)
GET  /api/stac/schema/info                           # Schema inspection
GET  /api/stac/health                                # Health metrics
```

**Assessment**:
- ✅ **Core STAC endpoints (6)** are production-ready
- ⚠️ **Infrastructure endpoints (5)** should be removed in production
- ✅ **Fully standards-compliant** with STAC v1.0.0

**Production Recommendation**: Keep only the 6 core STAC endpoints, remove infrastructure/admin endpoints.

---

#### 2. OGC Features API (6 functions) ✅
**Status**: Standards-compliant, production-ready
**Base Path**: `/api/features/*`

**Implemented Endpoints**:
```python
GET  /api/features                                   # Landing page
GET  /api/features/conformance                       # Conformance classes
GET  /api/features/collections                       # Collections list
GET  /api/features/collections/{collection_id}       # Collection metadata
GET  /api/features/collections/{collection_id}/items # Query features
GET  /api/features/collections/{collection_id}/items/{feature_id} # Single feature
```

**Assessment**:
- ✅ **All 6 endpoints** are production-ready
- ✅ **Fully standards-compliant** with OGC API - Features Core 1.0
- ✅ **Zero dependencies** on main app (standalone module)

**Production Recommendation**: Keep all 6 endpoints as-is. Ready for APIM routing.

---

#### 3. Platform API (3 functions) ✅
**Status**: Public ingestion interface
**Base Path**: `/api/platform/*`

**Implemented Endpoints**:
```python
POST /api/platform/submit                            # Submit ingestion request
GET  /api/platform/status/{request_id}               # Request status
GET  /api/platform/status                            # List all requests (query)
```

**Assessment**:
- ✅ **3 core endpoints** for external integration (DDH app)
- ⚠️ **Missing cancel endpoint** from plan (was planned: `/api/platform/cancel/{request_id}`)
- ✅ **Production-ready** with proper orchestration

**Production Recommendation**: Add cancel endpoint, then keep all 4 endpoints for APIM internal routing.

---

#### 4. CoreMachine (3 functions) ✅
**Status**: Internal job/task execution
**Base Path**: `/api/jobs/*`

**Implemented Endpoints**:
```python
POST /api/jobs/submit/{job_type}                     # Submit job
GET  /api/jobs/status/{job_id}                       # Job status
POST /api/jobs/ingest_vector                         # Vector ingestion (specific)
```

**Plus Service Bus Processors** (Background):
```python
@service_bus_queue_trigger: geospatial-jobs          # Job processor
@service_bus_queue_trigger: geospatial-tasks         # Task processor
```

**Assessment**:
- ✅ **Core job submission/status** working
- ✅ **Service Bus processors** handle background execution
- ⚠️ **Missing planned endpoints**: Task query, job cancel
- ✅ **Internal use only** (no APIM exposure)

**Production Recommendation**: Add task query/cancel endpoints, then keep for internal use only (no APIM routes).

---

### ⚠️ Admin/Debug Endpoints (REMOVE IN PRODUCTION - 46 functions)

#### 5. Database Admin (31 functions) ⚠️
**Status**: Development visibility tool (NO DBEAVER ACCESS)
**Base Path**: `/api/db/*` and `/api/dbadmin/*`

**Implemented Endpoints**:
```python
# Schema operations (3)
GET  /api/db/schemas                                 # List all schemas
GET  /api/db/schemas/{schema_name}                   # Schema details
GET  /api/db/schemas/{schema_name}/tables            # Schema tables

# Table operations (4)
GET  /api/db/tables/{table_identifier}               # Table details
GET  /api/db/tables/{table_identifier}/sample        # Sample rows
GET  /api/db/tables/{table_identifier}/columns       # Column definitions
GET  /api/db/tables/{table_identifier}/indexes       # Index information

# Query analysis (4)
GET  /api/db/queries/running                         # Active queries
GET  /api/db/queries/slow                            # Slow query log
GET  /api/db/locks                                   # Database locks
GET  /api/db/connections                             # Connection stats

# Health and performance (2)
GET  /api/db/health                                  # Database health
GET  /api/db/health/performance                      # Performance metrics

# Maintenance (3)
POST /api/db/maintenance/nuke?confirm=yes            # NUCLEAR BUTTON
POST /api/db/maintenance/redeploy?confirm=yes        # Nuke + redeploy
POST /api/db/maintenance/cleanup?confirm=yes         # VACUUM/ANALYZE

# Data queries (10 - for CoreMachine/Platform debugging)
GET  /api/dbadmin/jobs                               # Query jobs
GET  /api/dbadmin/jobs/{job_id}                      # Job by ID
GET  /api/dbadmin/tasks                              # Query tasks
GET  /api/dbadmin/tasks/{job_id}                     # Tasks for job
GET  /api/dbadmin/platform/requests                  # API requests
GET  /api/dbadmin/platform/requests/{request_id}     # Request by ID
GET  /api/dbadmin/platform/orchestration             # Orchestration jobs
GET  /api/dbadmin/platform/orchestration/{request_id} # Orch for request
GET  /api/dbadmin/stats                              # Database statistics
GET  /api/db/debug/all                               # Comprehensive dump

# Diagnostics (3)
GET  /api/dbadmin/diagnostics/enums                  # Enum type diagnosis
GET  /api/dbadmin/diagnostics/functions              # Function testing
GET  /api/dbadmin/diagnostics/all                    # All diagnostics

# Legacy (2 - deprecated but still active)
POST /api/db/schema/nuke?confirm=yes                 # Old nuke endpoint
POST /api/db/schema/redeploy?confirm=yes             # Old redeploy endpoint
```

**Assessment**:
- ⚠️ **31 endpoints** vs. **17 planned** - scope expanded during development
- 🎯 **Critical for development** because corporate network blocks DBeaver access
- ❌ **Remove in production** - replace with Log Analytics KQL queries
- ⚠️ **Nuclear buttons** are dangerous (intentionally) for DEV/TEST only

**Why So Many?**
1. **No DBeaver Access**: Corporate network restrictions required HTTP visibility
2. **Claude Code Development**: AI needs HTTP endpoints to inspect system state
3. **Rapid Debugging**: Comprehensive schema/table/query inspection
4. **Platform Layer Added**: Original plan didn't account for Platform schema (10 new endpoints)

**Production Replacement Strategy**:
```kql
// Log Analytics KQL Queries (replace database admin endpoints)
// Job queries
app_jobs
| where timestamp >= ago(24h)
| where status == "failed"
| project timestamp, job_id, job_type, error_details
| order by timestamp desc

// Task queries
app_tasks
| where parent_job_id == "{job_id}"
| project timestamp, task_id, task_type, status, error_details

// Database health
AzureMetrics
| where ResourceProvider == "MICROSOFT.DBFORPOSTGRESQL"
| where MetricName in ("cpu_percent", "memory_percent", "connections_active")
```

---

#### 6. Service Bus Admin (6 functions) ⚠️
**Status**: Queue monitoring tool (NO AZURE PORTAL ACCESS IN DEV)
**Base Path**: `/api/servicebus/*`

**Implemented Endpoints**:
```python
GET  /api/servicebus/queues                          # List all queues
GET  /api/servicebus/queues/{queue_name}             # Queue details
GET  /api/servicebus/queues/{queue_name}/peek        # Peek active messages
GET  /api/servicebus/queues/{queue_name}/deadletter  # Peek dead letters
GET  /api/servicebus/health                          # Service Bus health
POST /api/servicebus/queues/{queue_name}/nuke?confirm=yes # NUCLEAR BUTTON
```

**Assessment**:
- ⚠️ **6 endpoints** as planned
- 🎯 **Critical for development** (queue inspection without Azure Portal)
- ❌ **Remove in production** - use Azure Portal Service Bus monitoring
- ⚠️ **Nuclear button** for clearing queues in DEV/TEST

**Production Replacement**: Azure Portal → Service Bus → Queues → [Queue Name] → Messages

---

#### 7. H3 Debug (1 function) ⚠️
**Status**: H3 grid system debugging
**Base Path**: `/api/h3/debug`

**Implemented Endpoints**:
```python
GET  /api/h3/debug?operation={op}                    # H3 debug operations
    # Operations: schema_status, grid_summary, grid_details, reference_filters,
    #             reference_filter_details, sample_cells, parent_child_check
```

**Assessment**:
- ⚠️ **1 consolidated endpoint** vs. **8 planned** - good consolidation!
- 🎯 **Useful for H3 bootstrap validation**
- ❌ **Remove in production** - H3 is infrastructure, not runtime debugging

**Production Recommendation**: Remove. H3 grid creation is one-time bootstrap, not runtime operation.

---

#### 8. Test/Debug Utilities (~10 functions) ⚠️
**Status**: Development/testing tools

**Implemented Endpoints**:
```python
# Test utilities
POST /api/test/create-rasters                        # Create test raster files
GET  /api/analysis/container/{job_id}                # Analyze container job
POST /api/analysis/delivery                          # Discover delivery structure

# STAC infrastructure (beyond core API)
POST /api/stac/collections/{tier}                    # Tier-based collections
POST /api/stac/init                                  # Initialize collections
POST /api/stac/extract                               # Extract STAC metadata
POST /api/stac/vector                                # Catalog PostGIS table
GET  /api/stac/collections/summary                   # Collection summary
GET  /api/stac/collections/{id}/stats                # Collection statistics
GET  /api/stac/items/{item_id}                       # Item lookup (non-standard)

# Vector viewer (QA tool)
GET  /api/vector/viewer?collection={id}              # Visual QA preview
```

**Assessment**:
- ⚠️ **~10 endpoints** for development/testing
- 🎯 **Useful for development** (test data generation, QA validation)
- ❌ **Remove in production** - testing tools not needed in production

**Production Recommendation**: Remove all test/debug utilities. QA/testing should use dedicated test environments.

---

## 🔄 Migration Path to Production

### Phase 1: Current (Development Monolith) ✅
**Status**: ACTIVE
**Function Count**: 81 functions
**Purpose**: Rapid development, learning, prototyping

**Characteristics**:
- ✅ All admin/debug endpoints available
- ✅ No DBeaver? No problem! HTTP visibility into everything
- ✅ Claude Code can inspect database without database access
- ✅ Rapid iteration, comprehensive debugging

---

### Phase 2: Pre-Production (Testing) 🔄
**Status**: NEXT MILESTONE
**Function Count**: ~40-50 functions (remove some admin endpoints)
**Purpose**: Test APIM routing, validate inter-app communication

**Tasks**:
1. ✅ Extract STAC API to separate module (DONE - `stac_api/`)
2. ✅ Extract OGC Features to separate module (DONE - `ogc_features/`)
3. ⚠️ Remove most admin endpoints (keep core debugging)
4. ⚠️ Test APIM routing configuration
5. ⚠️ Validate log aggregation (Log Analytics, App Insights)

**Endpoints to Keep Temporarily**:
- Core database queries (`/api/dbadmin/jobs`, `/api/dbadmin/tasks`) - for troubleshooting
- Service Bus health (`/api/servicebus/health`) - for integration testing
- Minimal schema inspection (`/api/db/schemas`, `/api/db/health`) - for deployment validation

**Endpoints to Remove**:
- ❌ Nuclear buttons (`nuke`, `redeploy`) - Azure Portal only
- ❌ Deep schema inspection (`/api/db/tables/*`, `/api/db/queries/*`) - Log Analytics
- ❌ Test utilities (`/api/test/*`) - Test environment only
- ❌ H3 debug (`/api/h3/debug`) - Bootstrap is done

---

### Phase 3: Production (Locked Down) 🎯
**Status**: TARGET
**Function Count**: **~35 functions** (matches consolidation plan)
**Purpose**: Secure, scalable production deployment

**Function Apps** (4 separate apps via APIM):
```
1. STAC API Function App (6 functions)
   - /api/stac/*
   - Access: Public (Azure AD tenant users)
   - APIM Route: geospatial.rmh.org/api/collections/*

2. OGC Features Function App (7 functions)
   - /api/features/*
   - Access: Public (Azure AD tenant users)
   - APIM Route: geospatial.rmh.org/api/features/*

3. Platform API Function App (5 functions)
   - /api/platform/*
   - Access: Internal (DDH app + approved apps)
   - APIM Route: geospatial.rmh.org/api/platform/*

4. CoreMachine Function App (7 functions - INTERNAL ONLY)
   - /api/jobs/*
   - Service Bus processors
   - Access: Internal (no APIM exposure)
   - Used by: Platform layer, Service Bus queues

5. Admin/Debug Endpoints (REMOVED)
   - All /api/db/*, /api/dbadmin/*, /api/servicebus/*, /api/h3/* REMOVED
   - Replaced with: Log Analytics, App Insights, Azure Portal
```

**Monitoring Replacement**:
```
Admin Endpoint                  → Production Replacement
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GET /api/dbadmin/jobs           → Log Analytics: app_jobs table
GET /api/dbadmin/tasks          → Log Analytics: app_tasks table
GET /api/db/queries/running     → Azure Portal: PostgreSQL Monitoring
GET /api/db/health              → Azure Monitor: Database metrics
GET /api/servicebus/queues      → Azure Portal: Service Bus → Queues
POST /api/db/schema/nuke        → Azure Portal: PostgreSQL → Query editor
GET /api/db/debug/all           → Log Analytics: Kusto queries
```

---

## 📋 Production Consolidation Checklist

### Endpoints to KEEP (35 functions)
- [x] **STAC API Core** (6) - `/api/stac/*`
- [x] **OGC Features API** (7) - `/api/features/*`
- [x] **Platform API** (4) - `/api/platform/*` (add cancel endpoint)
- [x] **CoreMachine** (5) - `/api/jobs/*` (add task query/cancel)
- [x] **System Health** (1) - `/api/health`
- [x] **Service Bus Processors** (2) - Background workers
- [x] **Vector Ingestion** (1) - `/api/jobs/ingest_vector`

### Endpoints to REMOVE (46 functions)
- [ ] **Database Admin** (31) - `/api/db/*`, `/api/dbadmin/*`
  - Exception: Keep `/api/db/health` and `/api/dbadmin/stats` for deployment validation
- [ ] **Service Bus Admin** (6) - `/api/servicebus/*`
- [ ] **H3 Debug** (1) - `/api/h3/debug`
- [ ] **Test Utilities** (~10) - `/api/test/*`, analysis endpoints
- [ ] **STAC Infrastructure** (5) - `/api/stac/setup`, `/api/stac/nuke`, inspection endpoints
- [ ] **Nuclear Buttons** (3) - All `nuke`/`redeploy` endpoints

### Monitoring Migration Tasks
- [ ] **Set up Log Analytics workspace** with app_jobs/app_tasks tables
- [ ] **Create KQL query templates** for common debugging scenarios
- [ ] **Configure Application Insights** dashboards for job/task monitoring
- [ ] **Document Azure Portal workflows** for Service Bus inspection
- [ ] **Test deployment validation** without admin endpoints

---

## 🚀 APIM Integration Architecture

### External Access (APIM Routes)

#### Public APIs (Azure AD Tenant Users)
```xml
<!-- STAC API - Public metadata search -->
<policy route="/api/collections/*">
  <validate-azure-ad-token tenant-id="{tenant}">
    <audiences><audience>api://geospatial-public</audience></audiences>
  </validate-azure-ad-token>
  <rate-limit calls="1000" renewal-period="60" />
  <backend-service url="https://stac-app.azurewebsites.net" />
</policy>

<!-- OGC Features API - Public vector access -->
<policy route="/api/features/*">
  <validate-azure-ad-token tenant-id="{tenant}">
    <audiences><audience>api://geospatial-public</audience></audiences>
  </validate-azure-ad-token>
  <rate-limit calls="1000" renewal-period="60" />
  <backend-service url="https://ogc-app.azurewebsites.net" />
</policy>
```

#### Internal APIs (DDH App + Approved Apps)
```xml
<!-- Platform API - Internal data ingestion -->
<policy route="/api/platform/*">
  <validate-azure-ad-token tenant-id="{tenant}">
    <client-application-ids>
      <application-id>{ddh-app-id}</application-id>
      <!-- Future approved apps here -->
    </client-application-ids>
    <audiences><audience>api://geospatial-internal</audience></audiences>
  </validate-azure-ad-token>
  <rate-limit calls="10000" renewal-period="60" />
  <backend-service url="https://platform-app.azurewebsites.net" />
</policy>
```

### Internal Only (No APIM Exposure)
```
CoreMachine Function App
- /api/jobs/* (direct Service Bus triggers only)
- No HTTP exposure to APIM
- Used by: Platform layer, background workers
```

---

## 🎯 Key Takeaways

### Why Admin Endpoints Expanded (31 vs. 17 planned)
1. **Corporate Network Restrictions**: No direct PostgreSQL access (DBeaver blocked)
2. **Claude Code Development**: AI needs HTTP visibility into system state
3. **Platform Layer Added**: Original plan didn't include Platform schema (10+ endpoints)
4. **Comprehensive Debugging**: Learned we need more visibility during development

### Production Consolidation is Critical
- **46 endpoints** (57% of total) are admin/debug tools for development
- **35 endpoints** (43% of total) are production APIs
- **Clear separation** between dev visibility and production security

### APIM Benefits
- ✅ **Seamless user experience** - Single domain, clean API
- ✅ **Security isolation** - Public APIs can't access internal CoreMachine
- ✅ **Independent scaling** - STAC API scales separately from Platform
- ✅ **Deployment independence** - Update OGC without touching STAC

---

## 📚 Related Documentation

- **Consolidation Plan**: [FUNCTION_REVIEW.md](FUNCTION_REVIEW.md)
- **STAC API Docs**: [stac_api/README.md](stac_api/README.md)
- **OGC Features Docs**: [ogc_features/README.md](ogc_features/README.md)
- **Platform Architecture**: [docs_claude/PLATFORM_SERVICE_ARCHITECTURE.md](docs_claude/PLATFORM_SERVICE_ARCHITECTURE.md)
- **APIM Integration**: [docs_claude/APIM_INTEGRATION_ARCHITECTURE.md](docs_claude/APIM_INTEGRATION_ARCHITECTURE.md)

---

**Last Updated**: 14 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Development Monolith (81 functions) → Production Target (35 functions)