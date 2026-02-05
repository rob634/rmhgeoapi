# APP_MODE Endpoint Refactor Plan

**Date**: 05 FEB 2026
**Status**: Ready for Implementation
**Scope**: Restrict endpoints per APP_MODE, starting with PLATFORM mode

---

## Summary

Refactor endpoint registration so each APP_MODE exposes only its intended endpoints. This creates clear separation of concerns and reduces attack surface for public-facing deployments.

---

## Current State

All modes except WORKER_DOCKER currently register most endpoints. The `has_*_endpoints` properties only control a few blueprint groups.

**Current APP_MODE=platform registers:**
- Platform endpoints (`/api/platform/*`) - INTENDED
- Interface endpoints (`/api/interface/*`) - INTENDED
- Health probes (`/api/livez`, `/api/readyz`) - INTENDED
- Jobs endpoints (`/api/jobs/*`) - NOT INTENDED
- OGC Features (`/api/features/*`) - NOT INTENDED
- Raster API (`/api/raster/*`) - NOT INTENDED
- Storage (`/api/storage/*`) - NOT INTENDED
- Maps (`/api/maps/*`) - NOT INTENDED
- Curated (`/api/curated/*`) - NOT INTENDED
- Many others...

---

## Target State

### APP_MODE=platform (Gateway)

**Exposed Endpoints:**
```
/api/livez              - Liveness probe (process alive?)
/api/readyz             - Readiness probe (can accept traffic?)
/api/health             - Instance health (this app's status)

/api/platform/health    - B2B system health (can I submit jobs?)
/api/platform/*         - Platform API (17 endpoints)
/api/interface/*        - Web UI (calls platform API)
```

**NOT Exposed:**
- `/api/system-health` - Admin infrastructure view (use orchestrator)
- `/api/jobs/*` - Use platform API instead
- `/api/features/*` - Internal use only
- `/api/raster/*` - Internal use only
- `/api/storage/*` - Internal use only
- `/api/maps/*` - Internal use only
- `/api/curated/*` - Admin only
- `/api/dbadmin/*` - Admin only
- `/api/stac/*` - Admin only

### Three-Tier Health Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HEALTH ENDPOINT TIERS                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  /api/livez               │  Liveness probe                                 │
│  /api/readyz              │  Readiness probe                                │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  /api/health              │  THIS app instance                              │
│  ─────────────────────────┼───────────────────────────────────────────────  │
│  • Uptime, version        │  "Is this process healthy?"                     │
│  • Memory usage           │  Fast, local checks only (<100ms)               │
│  • APP_MODE               │  ALL modes expose this                          │
│  • Local connectivity     │                                                 │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  /api/platform/health     │  SYSTEM health for B2B                          │
│  ─────────────────────────┼───────────────────────────────────────────────  │
│  • ready_for_jobs: bool   │  "Can I submit work?"                           │
│  • Queue backlog          │  What B2B consumers care about (<500ms)         │
│  • Worker availability    │  PLATFORM, STANDALONE, ORCHESTRATOR             │
│  • Recent failure rate    │                                                 │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  /api/system-health       │  INFRASTRUCTURE health for admins               │
│  ─────────────────────────┼───────────────────────────────────────────────  │
│  • All app instances      │  "What's the state of everything?"              │
│  • All queues             │  Aggregates from multiple sources (<5s)         │
│  • All databases          │  ORCHESTRATOR, STANDALONE only                  │
│  • Cross-app errors       │  NOT exposed on PLATFORM (gateway)              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Endpoint | Scope | Available On | Response Time |
|----------|-------|--------------|---------------|
| `/api/livez` | Process alive | All modes | <10ms |
| `/api/readyz` | Ready for traffic | All modes | <100ms |
| `/api/health` | This instance | All modes | <100ms |
| `/api/platform/health` | B2B system | PLATFORM, ORCHESTRATOR, STANDALONE | <500ms |
| `/api/system-health` | Full infrastructure | ORCHESTRATOR, STANDALONE | <5s |

**Response Examples:**

`/api/health` (Instance - all modes)
```json
{
  "status": "healthy",
  "instance": {
    "app_name": "rmhgeogateway",
    "app_mode": "platform",
    "version": "0.8.9.2",
    "uptime_seconds": 3600,
    "memory_mb": 256
  },
  "connectivity": {
    "database": "ok",
    "service_bus": "ok",
    "storage": "ok"
  }
}
```

`/api/platform/health` (B2B System - platform, orchestrator, standalone)
```json
{
  "ready_for_jobs": true,
  "status": "healthy",
  "system": {
    "database": "healthy",
    "job_queue": "healthy",
    "workers": "available"
  },
  "metrics": {
    "queue_backlog": 3,
    "processing": 2,
    "failed_last_24h": 0,
    "avg_completion_minutes": 5.7
  }
}
```

`/api/system-health` (Infrastructure - orchestrator, standalone only)
```json
{
  "status": "healthy",
  "apps": {
    "rmhgeogateway": {"status": "healthy", "version": "0.8.9.2", "mode": "platform"},
    "rmhazuregeoapi": {"status": "healthy", "version": "0.8.9.2", "mode": "orchestrator"},
    "rmhheavyapi": {"status": "healthy", "version": "0.8.9.2", "mode": "worker_docker"}
  },
  "queues": {
    "geospatial-jobs": {"depth": 3, "status": "ok"},
    "functionapp-tasks": {"depth": 0, "status": "ok"},
    "container-tasks": {"depth": 1, "status": "ok"}
  },
  "database": {
    "host": "rmhpostgres.postgres.database.azure.com",
    "connections": 12,
    "status": "healthy"
  },
  "errors_last_hour": 0
}
```

**Note**: `/api/admin/*` is Azure-reserved and cannot be used.

---

## Implementation Plan

### Phase 1: Add `has_interface_endpoints` Property

**File**: `config/app_mode_config.py`

```python
@property
def has_interface_endpoints(self) -> bool:
    """Whether this mode exposes /api/interface/* endpoints (Web UI)."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.PLATFORM,      # Gateway serves UI
        AppMode.ORCHESTRATOR,  # Admin UI access
    ]
```

### Phase 2: Add Endpoint Category Properties

**File**: `config/app_mode_config.py`

Add granular control for each endpoint category:

```python
@property
def has_jobs_endpoints(self) -> bool:
    """Whether this mode exposes /api/jobs/* endpoints."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
    ]
    # NOTE: PLATFORM mode uses /api/platform/submit, not /api/jobs/*

@property
def has_ogc_endpoints(self) -> bool:
    """Whether this mode exposes OGC Features API (/api/features/*)."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
    ]

@property
def has_raster_endpoints(self) -> bool:
    """Whether this mode exposes /api/raster/* endpoints."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
    ]

@property
def has_storage_endpoints(self) -> bool:
    """Whether this mode exposes /api/storage/* endpoints."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
        AppMode.WORKER_FUNCTIONAPP,  # May need storage access
    ]

@property
def has_maps_endpoints(self) -> bool:
    """Whether this mode exposes /api/maps/* endpoints."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
    ]

@property
def has_curated_endpoints(self) -> bool:
    """Whether this mode exposes /api/curated/* endpoints."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
    ]

@property
def has_system_health_endpoint(self) -> bool:
    """Whether this mode exposes /api/system-health (admin infrastructure view)."""
    return self.mode in [
        AppMode.STANDALONE,
        AppMode.ORCHESTRATOR,
    ]
    # NOTE: NOT exposed on PLATFORM - admins use orchestrator for infra health
```

### Phase 3: Three-Tier Health Endpoints

**Design**: Three distinct health endpoints with different scopes:

| Endpoint | Scope | Modes |
|----------|-------|-------|
| `/api/health` | This instance | All |
| `/api/platform/health` | B2B system | PLATFORM, ORCHESTRATOR, STANDALONE |
| `/api/system-health` | Full infrastructure | ORCHESTRATOR, STANDALONE |

**File**: `triggers/probes.py` - Add instance health

```python
@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Instance health - THIS app's status.

    Fast, local checks only. All modes expose this.
    """
    app_mode = get_app_mode_config()

    health_data = {
        "status": "healthy",
        "instance": {
            "app_name": app_mode.app_name,
            "app_mode": app_mode.mode.value,
            "version": __version__,
            "uptime_seconds": get_uptime(),
            "memory_mb": get_memory_usage()
        },
        "connectivity": {
            "database": check_db_connectivity(),
            "service_bus": check_servicebus_connectivity(),
            "storage": check_storage_connectivity()
        },
        "timestamp": datetime.utcnow().isoformat()
    }

    return func.HttpResponse(json.dumps(health_data), mimetype="application/json")
```

**File**: `triggers/platform/platform_bp.py` - Keep B2B system health

```python
# /api/platform/health already exists - this is the B2B view
# Shows: ready_for_jobs, queue_backlog, worker_availability, failure_rate
# No changes needed - this is correct as-is
```

**File**: `triggers/system_health.py` (NEW) - Infrastructure health

```python
@app.route(route="system-health", methods=["GET"])
def system_health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Infrastructure health - admin view of ALL components.

    Only exposed on ORCHESTRATOR and STANDALONE modes.
    Aggregates health from all apps, queues, databases.
    """
    # Check all app instances
    apps = {}
    for app_url in [GATEWAY_URL, ORCHESTRATOR_URL, DOCKER_WORKER_URL]:
        apps[app_name] = fetch_app_health(app_url)

    # Check all queues
    queues = check_all_queue_depths()

    # Check database
    database = check_database_health()

    # Recent errors from App Insights
    errors = query_recent_errors()

    return func.HttpResponse(json.dumps({
        "status": determine_overall_status(apps, queues, database),
        "apps": apps,
        "queues": queues,
        "database": database,
        "errors_last_hour": errors
    }), mimetype="application/json")
```

### Phase 4: Conditional Endpoint Registration in function_app.py

**File**: `function_app.py`

Wrap endpoint registrations with mode checks:

```python
# ============================================================================
# CONDITIONAL ENDPOINT REGISTRATION (05 FEB 2026)
# ============================================================================

# Health probes - ALL MODES
# /api/livez, /api/readyz already registered in Phase 1
# /api/health - unified health endpoint
@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return health_trigger.handle(req)

# Platform API - PLATFORM, ORCHESTRATOR, STANDALONE
if _app_mode.has_platform_endpoints:
    from triggers.platform import platform_bp
    app.register_functions(platform_bp)

# Interface (Web UI) - PLATFORM, ORCHESTRATOR, STANDALONE
if _app_mode.has_interface_endpoints:
    @app.route(route="interface", methods=["GET"])
    def web_interface_redirect(req): ...

    @app.route(route="interface/{name}", methods=["GET", "POST"])
    def web_interface_unified(req): ...

# Jobs API - ORCHESTRATOR, STANDALONE only (not PLATFORM)
if _app_mode.has_jobs_endpoints:
    @app.route(route="jobs/submit/{job_type}", methods=["POST"])
    def submit_job(req): ...
    # ... other jobs endpoints

# OGC Features - ORCHESTRATOR, STANDALONE only
if _app_mode.has_ogc_endpoints:
    # Register OGC features routes
    ...

# Raster API - ORCHESTRATOR, STANDALONE only
if _app_mode.has_raster_endpoints:
    # Register raster routes
    ...

# Storage API - ORCHESTRATOR, STANDALONE, WORKER_FUNCTIONAPP
if _app_mode.has_storage_endpoints:
    # Register storage routes
    ...
```

### Phase 5: Blueprint Refactoring (Optional)

For cleaner organization, group endpoints into blueprints by category:

```
triggers/
├── probes.py              # livez, readyz, health (all modes)
├── platform/
│   └── platform_bp.py     # /api/platform/*
├── jobs/
│   └── jobs_bp.py         # /api/jobs/*
├── ogc/
│   └── features_bp.py     # /api/features/*
├── raster/
│   └── raster_bp.py       # /api/raster/*
└── admin/
    └── ...                # /api/dbadmin/*, /api/stac/*
```

Then registration becomes:

```python
if _app_mode.has_jobs_endpoints:
    from triggers.jobs import jobs_bp
    app.register_functions(jobs_bp)
```

---

## APP_MODE Summary Table (Target State)

| Endpoint Group | STANDALONE | PLATFORM | ORCHESTRATOR | WORKER_FA | WORKER_DOCKER |
|----------------|------------|----------|--------------|-----------|---------------|
| `/api/livez` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/api/readyz` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/api/health` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/api/platform/health` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/api/system-health` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `/api/platform/*` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/api/interface/*` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/api/jobs/*` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `/api/features/*` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `/api/raster/*` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `/api/storage/*` | ✅ | ❌ | ✅ | ✅ | ❌ |
| `/api/maps/*` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `/api/curated/*` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `/api/dbadmin/*` | ✅ | ❌ | ✅ | ✅ | ❌ |
| `/api/stac/*` | ✅ | ❌ | ✅ | ❌ | ❌ |

---

## Interface Endpoints for PLATFORM Mode

The web interfaces that make sense for PLATFORM mode (B2B gateway):

| Interface | Path | Purpose | Calls |
|-----------|------|---------|-------|
| home | `/api/interface/home` | Landing page | - |
| submit | `/api/interface/submit` | Submit data form | `/api/platform/submit` |
| platform | `/api/interface/platform` | Platform status | `/api/platform/status` |
| health | `/api/interface/health` | Health dashboard | `/api/health` |
| docs | `/api/interface/docs` | API documentation | - |
| swagger | `/api/interface/swagger` | Swagger UI | `/api/openapi.json` |
| redoc | `/api/interface/redoc` | ReDoc | `/api/openapi.json` |

Interfaces that should NOT be on PLATFORM mode:
- `jobs` - Use `/api/interface/platform` instead
- `storage` - Admin only
- `database` - Admin only
- `queues` - Admin only

**Decision**: For Phase 1, allow all interfaces on PLATFORM mode. The interfaces themselves can check app_mode and show/hide features. Restricting interfaces can be Phase 2.

---

## Testing Plan

### 1. Unit Tests

```python
def test_platform_mode_endpoints():
    """PLATFORM mode should only expose platform, interface, health."""
    config = AppModeConfig(mode=AppMode.PLATFORM)

    assert config.has_platform_endpoints == True
    assert config.has_interface_endpoints == True
    assert config.has_system_health_endpoint == False  # Admin only
    assert config.has_jobs_endpoints == False
    assert config.has_ogc_endpoints == False
    assert config.has_admin_endpoints == False

def test_orchestrator_mode_endpoints():
    """ORCHESTRATOR mode should expose all endpoints including system-health."""
    config = AppModeConfig(mode=AppMode.ORCHESTRATOR)

    assert config.has_platform_endpoints == True
    assert config.has_interface_endpoints == True
    assert config.has_system_health_endpoint == True  # Admin infra view
    assert config.has_jobs_endpoints == True
    assert config.has_ogc_endpoints == True
    assert config.has_admin_endpoints == True
```

### 2. Integration Tests - PLATFORM Mode (Gateway)

```bash
# Deploy to gateway with APP_MODE=platform

# Test health tiers
curl https://rmhgeogateway.../api/livez           # 200 - liveness
curl https://rmhgeogateway.../api/readyz          # 200 - readiness
curl https://rmhgeogateway.../api/health          # 200 - instance health
curl https://rmhgeogateway.../api/platform/health # 200 - B2B system health

# Test allowed endpoints
curl https://rmhgeogateway.../api/platform/submit # 200 (POST)
curl https://rmhgeogateway.../api/interface/home  # 200

# Test disallowed endpoints return 404
curl https://rmhgeogateway.../api/system-health   # 404 - admin only
curl https://rmhgeogateway.../api/jobs/status/xxx # 404
curl https://rmhgeogateway.../api/features        # 404
curl https://rmhgeogateway.../api/dbadmin/stats   # 404
```

### 3. Integration Tests - ORCHESTRATOR Mode

```bash
# Deploy to orchestrator with APP_MODE=orchestrator

# Test all health endpoints available
curl https://rmhazuregeoapi.../api/health          # 200 - instance
curl https://rmhazuregeoapi.../api/platform/health # 200 - B2B system
curl https://rmhazuregeoapi.../api/system-health   # 200 - infrastructure

# Test admin endpoints available
curl https://rmhazuregeoapi.../api/dbadmin/stats   # 200
curl https://rmhazuregeoapi.../api/jobs/status/xxx # 200/404 (job exists?)
```

---

## Rollback Plan

If issues arise, revert to current behavior by:

1. Remove `if _app_mode.has_*` guards in function_app.py
2. All endpoints register unconditionally (current behavior)

---

## Files to Modify

| File | Changes |
|------|---------|
| `config/app_mode_config.py` | Add `has_interface_endpoints`, `has_ogc_endpoints`, `has_system_health_endpoint`, etc. |
| `function_app.py` | Wrap endpoint registrations with mode checks |
| `triggers/probes.py` | Add `/api/health` (instance health) |
| `triggers/system_health.py` | NEW: Add `/api/system-health` (infrastructure health, orchestrator only) |
| `triggers/platform/platform_bp.py` | Keep `/api/platform/health` (B2B system health) |

---

## Implementation Order

1. **Phase 1**: Add properties to `app_mode_config.py` (low risk)
   - `has_interface_endpoints`, `has_ogc_endpoints`, `has_system_health_endpoint`, etc.

2. **Phase 2**: Implement three-tier health endpoints (low risk)
   - `/api/health` - Instance health (all modes)
   - `/api/platform/health` - Already exists, keep as-is
   - `/api/system-health` - New, orchestrator/standalone only

3. **Phase 3**: Wrap PLATFORM mode endpoints with conditionals (medium risk)
   - Only register platform/*, interface/*, health endpoints for PLATFORM mode

4. **Phase 4**: Deploy and test on rmhgeogateway
   - Verify only intended endpoints are exposed
   - Test health endpoints return correct data

5. **Phase 5**: Apply same pattern to other modes
   - ORCHESTRATOR, WORKER_FUNCTIONAPP, WORKER_DOCKER

6. **Phase 6**: (Optional) Refactor into blueprints for cleaner code

---

## Success Criteria

1. **PLATFORM mode**: Only exposes health, platform/*, interface/*
2. **Unified health**: `/api/health` works on all modes
3. **No regression**: STANDALONE and ORCHESTRATOR modes unchanged
4. **Tests pass**: Unit and integration tests validate behavior
