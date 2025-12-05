# function_app.py Refactoring Plan

**Date**: 22 NOV 2025
**Status**: IN PROGRESS

## Overview

Refactor the monolithic `function_app.py` (2,403 lines, 54 routes) into a cleaner, more maintainable structure by:
1. Creating trigger factory modules that consolidate imports and instantiation
2. Building a parallel `function_app_new.py` implementation
3. Testing independently before swapping

**Goal**: Reduce to ~1,200-1,500 lines with better organization (decorators are unavoidable in Azure Functions v2)

---

## Critical Constraints

### Azure Functions v2 Decorator Requirement
```python
# CANNOT dynamically generate routes - decorators must exist in source code
# This is WHY we still need all 54 @app.route() declarations
# We're just making the FILE cleaner, not eliminating routes

@app.route(route="dbadmin/schemas", methods=["GET"])  # REQUIRED
def db_schemas(req): return admin['schemas'].handle_request(req)
```

### What We CAN Improve
- **Import consolidation**: 1 import per group instead of 10+
- **Trigger instantiation**: Done in factory, not function_app.py
- **Code organization**: Clear sections with headers
- **Handler compactness**: One-liners where possible

---

## Task Checklist

### Phase 1: Create Trigger Factories

#### Task 1.1: Create `triggers/admin/__init__.py`
- [ ] **File**: `triggers/admin/__init__.py`
- [ ] **Purpose**: Export all admin triggers as a single dict
- [ ] **Pattern**:
```python
# triggers/admin/__init__.py
"""
Admin trigger factory - consolidates all database admin triggers.
Import this module to get all admin triggers in one dict.
"""

from .db_schemas import AdminDbSchemasTrigger
from .db_tables import AdminDbTablesTrigger
from .db_queries import AdminDbQueriesTrigger
from .db_health import AdminDbHealthTrigger
from .db_maintenance import AdminDbMaintenanceTrigger
from .db_data import AdminDbDataTrigger
from .db_diagnostics import AdminDbDiagnosticsTrigger
from .servicebus import ServiceBusAdminTrigger
from .h3_debug import AdminH3DebugTrigger

# Single instantiation point
triggers = {
    'schemas': AdminDbSchemasTrigger(),
    'tables': AdminDbTablesTrigger(),
    'queries': AdminDbQueriesTrigger(),
    'health': AdminDbHealthTrigger(),
    'maintenance': AdminDbMaintenanceTrigger(),
    'data': AdminDbDataTrigger(),
    'diagnostics': AdminDbDiagnosticsTrigger(),
    'servicebus': ServiceBusAdminTrigger(),
    'h3': AdminH3DebugTrigger(),
}

def get_admin_triggers():
    """Return dict of all instantiated admin triggers."""
    return triggers
```

#### Task 1.2: Create `triggers/stac/__init__.py`
- [ ] **File**: `triggers/stac/__init__.py`
- [ ] **Purpose**: Export all STAC management triggers
- [ ] **Note**: These are STAC *management* triggers (setup, nuke, etc.), NOT the STAC API endpoints
- [ ] **Pattern**:
```python
# triggers/stac/__init__.py
"""
STAC management trigger factory.
NOT the STAC API (that's in stac_api/ module).
"""

from .stac_setup import StacSetupTrigger
from .stac_nuke import StacNukeTrigger
from .stac_collections import StacCollectionsTrigger
from .stac_init import StacInitTrigger
from .stac_extract import StacExtractTrigger
from .stac_vector import StacVectorTrigger

triggers = {
    'setup': StacSetupTrigger(),
    'nuke': StacNukeTrigger(),
    'collections': StacCollectionsTrigger(),
    'init': StacInitTrigger(),
    'extract': StacExtractTrigger(),
    'vector': StacVectorTrigger(),
}

def get_stac_triggers():
    """Return dict of all instantiated STAC management triggers."""
    return triggers
```

#### Task 1.3: Move STAC trigger files to subfolder
- [ ] Create `triggers/stac/` directory
- [ ] Move these files INTO `triggers/stac/`:
  - `triggers/stac_setup.py` → `triggers/stac/stac_setup.py`
  - `triggers/stac_nuke.py` → `triggers/stac/stac_nuke.py`
  - `triggers/stac_collections.py` → `triggers/stac/stac_collections.py`
  - `triggers/stac_init.py` → `triggers/stac/stac_init.py`
  - `triggers/stac_extract.py` → `triggers/stac/stac_extract.py`
  - `triggers/stac_vector.py` → `triggers/stac/stac_vector.py`
- [ ] Update internal imports in moved files if needed

#### Task 1.4: Create `triggers/core/__init__.py`
- [ ] **File**: `triggers/core/__init__.py`
- [ ] **Purpose**: Core job orchestration triggers
- [ ] **Pattern**:
```python
# triggers/core/__init__.py
"""Core job orchestration triggers."""

from .submit_job import SubmitJobTrigger
from .get_job_status import GetJobStatusTrigger

triggers = {
    'submit': SubmitJobTrigger(),
    'status': GetJobStatusTrigger(),
}

def get_core_triggers():
    return triggers
```

#### Task 1.5: Move core trigger files to subfolder
- [ ] Create `triggers/core/` directory
- [ ] Move:
  - `triggers/submit_job.py` → `triggers/core/submit_job.py`
  - `triggers/get_job_status.py` → `triggers/core/get_job_status.py`

---

### Phase 2: Create function_app_new.py

#### Task 2.1: Create file with header and imports
- [ ] **File**: `function_app_new.py`
- [ ] **Section 1**: Claude context header (copy from original)
- [ ] **Section 2**: Consolidated imports
```python
# ============================================================================
# AZURE FUNCTIONS ENTRY POINT - REFACTORED
# ============================================================================
# ... standard header ...

import azure.functions as func
import logging
import json
import traceback

# Trigger factories (consolidated imports)
from triggers.admin import get_admin_triggers
from triggers.stac import get_stac_triggers
from triggers.core import get_core_triggers
from triggers.health import HealthCheckTrigger
from triggers.platform import PlatformSubmitTrigger, PlatformStatusTrigger
from triggers.analyze_container import AnalyzeContainerTrigger
from triggers.list_container_blobs import ListContainerBlobsTrigger
from triggers.get_blob_metadata import GetBlobMetadataTrigger

# Portable API modules
from stac_api import get_stac_triggers as get_stac_api_triggers
from ogc_features import get_ogc_triggers
from vector_viewer import get_vector_viewer_triggers

# Core systems
from core.machine import CoreMachine
from jobs import ALL_JOBS
from services import ALL_HANDLERS
from config import AppConfig
```

#### Task 2.2: Initialize triggers section
```python
# ============================================================================
# TRIGGER INITIALIZATION
# ============================================================================

# Get trigger instances from factories
admin = get_admin_triggers()
stac_mgmt = get_stac_triggers()
core = get_core_triggers()

# Individual triggers
health_trigger = HealthCheckTrigger()
platform_submit_trigger = PlatformSubmitTrigger()
platform_status_trigger = PlatformStatusTrigger()
analyze_container_trigger = AnalyzeContainerTrigger()
list_blobs_trigger = ListContainerBlobsTrigger()
blob_metadata_trigger = GetBlobMetadataTrigger()

# Portable API triggers
stac_api = get_stac_api_triggers()
ogc_api = get_ogc_triggers()
vector_viewer = get_vector_viewer_triggers()

# Core machine initialization
config = AppConfig()
core_machine = CoreMachine(all_jobs=ALL_JOBS, all_handlers=ALL_HANDLERS)
```

#### Task 2.3: Create app instance section
```python
# ============================================================================
# AZURE FUNCTION APP
# ============================================================================

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
```

#### Task 2.4: Health endpoint section
```python
# ============================================================================
# HEALTH CHECK (1 route)
# ============================================================================

@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return health_trigger.handle_request(req)
```

#### Task 2.5: Core job routes section
```python
# ============================================================================
# CORE JOB ORCHESTRATION (2 routes)
# ============================================================================

@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    return core['submit'].handle_request(req, core_machine)

@app.route(route="jobs/status/{job_id}", methods=["GET"])
def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
    return core['status'].handle_request(req)
```

#### Task 2.6: Database admin routes section (29 routes)
- [ ] Copy all 29 dbadmin routes from original
- [ ] Update handlers to use `admin['key']` pattern
- [ ] Group with clear header comment
```python
# ============================================================================
# DATABASE ADMIN - FCO (29 routes)
# For Claude Only - Development/debugging endpoints
# ============================================================================

# --- Schema & Tables (7 routes) ---
@app.route(route="dbadmin/schemas", methods=["GET"])
def db_schemas(req): return admin['schemas'].handle_request(req)

@app.route(route="dbadmin/schemas/{schema_name}", methods=["GET"])
def db_schema_detail(req): return admin['schemas'].handle_request(req)

# ... continue for all 29 routes
```

#### Task 2.7: Service Bus admin routes section (6 routes)
```python
# ============================================================================
# SERVICE BUS ADMIN (6 routes)
# ============================================================================

@app.route(route="servicebus/queues", methods=["GET"])
def servicebus_list(req): return admin['servicebus'].handle_request(req)

# ... continue for all 6 routes
```

#### Task 2.8: STAC management routes section (6 routes)
```python
# ============================================================================
# STAC MANAGEMENT (6 routes)
# Setup, initialization, and maintenance - NOT the STAC API
# ============================================================================

@app.route(route="stac/setup", methods=["GET", "POST"])
def stac_setup(req): return stac_mgmt['setup'].handle_request(req)

# ... continue for all 6 routes
```

#### Task 2.9: STAC API routes section (6 routes)
```python
# ============================================================================
# STAC API v1.0.0 (6 routes)
# Standards-compliant STAC catalog API
# ============================================================================

# Note: These come from the portable stac_api module
@app.route(route="stac", methods=["GET"])
def stac_landing(req): return stac_api[0]['handler'](req)

# ... map remaining routes from stac_api list
```

#### Task 2.10: OGC Features API routes section (6 routes)
```python
# ============================================================================
# OGC FEATURES API (6 routes)
# OGC API - Features Core 1.0 compliant
# ============================================================================

@app.route(route="features", methods=["GET"])
def features_landing(req): return ogc_api[0]['handler'](req)

# ... map remaining routes from ogc_api list
```

#### Task 2.11: Platform service routes section (3 routes)
```python
# ============================================================================
# PLATFORM SERVICE (3 routes)
# ============================================================================

@app.route(route="platform/submit", methods=["POST"])
def platform_submit(req): return platform_submit_trigger.handle_request(req)

@app.route(route="platform/status/{request_id}", methods=["GET"])
def platform_status(req): return platform_status_trigger.handle_request(req)

@app.route(route="platform/status", methods=["GET"])
def platform_status_all(req): return platform_status_trigger.handle_request(req)
```

#### Task 2.12: Analysis/container routes section
```python
# ============================================================================
# ANALYSIS & CONTAINER (3+ routes)
# ============================================================================

@app.route(route="analysis/container/{job_id}", methods=["GET"])
def analyze_container(req): return analyze_container_trigger.handle_request(req)

@app.route(route="containers/{container_name}/blobs", methods=["GET"])
def list_container_blobs(req): return list_blobs_trigger.handle_request(req)

# ... any other analysis routes
```

#### Task 2.13: Vector viewer route
```python
# ============================================================================
# VECTOR VIEWER (1 route)
# ============================================================================

@app.route(route="vector/viewer", methods=["GET"])
def vector_viewer_page(req): return vector_viewer[0]['handler'](req)
```

#### Task 2.14: H3 debug route
```python
# ============================================================================
# H3 GRID DEBUG (1 route)
# ============================================================================

@app.route(route="h3/debug", methods=["GET"])
def h3_debug(req): return admin['h3'].handle_request(req)
```

#### Task 2.15: Queue triggers section
- [ ] Copy Service Bus queue triggers from original
- [ ] Keep inline (these are complex and coupled to core_machine)
```python
# ============================================================================
# SERVICE BUS QUEUE TRIGGERS (2 triggers)
# ============================================================================

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="geospatial-jobs",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
    # ... copy existing implementation
    pass

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="geospatial-tasks",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def process_service_bus_task(msg: func.ServiceBusMessage) -> None:
    # ... copy existing implementation
    pass
```

#### Task 2.16: Timer triggers section (janitor)
```python
# ============================================================================
# TIMER TRIGGERS - JANITOR (3 triggers)
# ============================================================================

# Copy from original - these handle background maintenance
```

---

### Phase 3: Testing

#### Task 3.1: Local syntax validation
```bash
# Check for Python syntax errors
python -m py_compile function_app_new.py
```

#### Task 3.2: Import validation
```bash
# Test that all imports resolve
python -c "import function_app_new"
```

#### Task 3.3: Local function start test
```bash
# Temporarily point to new file for testing
# Option A: Rename files
mv function_app.py function_app_backup.py
mv function_app_new.py function_app.py
func start

# Option B: Or modify host.json temporarily (if supported)
```

#### Task 3.4: Route registration verification
```bash
# When func start runs, verify all 54 routes appear in console output
# Look for lines like:
# health: [GET] http://localhost:7071/api/health
# db_schemas: [GET] http://localhost:7071/api/dbadmin/schemas
```

#### Task 3.5: Smoke test key endpoints
```bash
# Health
curl http://localhost:7071/api/health

# Job submission
curl -X POST http://localhost:7071/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "refactor test"}'

# DB admin
curl http://localhost:7071/api/dbadmin/stats

# STAC API
curl http://localhost:7071/api/stac

# OGC Features
curl http://localhost:7071/api/features
```

---

### Phase 4: Swap and Deploy

#### Task 4.1: Backup original
```bash
mv function_app.py function_app_old.py
```

#### Task 4.2: Activate new
```bash
mv function_app_new.py function_app.py
```

#### Task 4.3: Deploy
```bash
func azure functionapp publish rmhazuregeoapi --python --build remote
```

#### Task 4.4: Production smoke test
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

---

## Reference: Current Route Inventory

For Claude reference - all routes that MUST exist in function_app_new.py:

### Health (1)
- `GET /api/health`

### Core Jobs (2)
- `POST /api/jobs/submit/{job_type}`
- `GET /api/jobs/status/{job_id}`

### Database Admin (29)
- `GET /api/dbadmin/schemas`
- `GET /api/dbadmin/schemas/{schema_name}`
- `GET /api/dbadmin/schemas/{schema_name}/tables`
- `GET /api/dbadmin/tables/{table_identifier}`
- `GET /api/dbadmin/tables/{table_identifier}/sample`
- `GET /api/dbadmin/tables/{table_identifier}/columns`
- `GET /api/dbadmin/tables/{table_identifier}/indexes`
- `GET /api/dbadmin/queries/running`
- `GET /api/dbadmin/queries/slow`
- `GET /api/dbadmin/locks`
- `GET /api/dbadmin/connections`
- `GET /api/dbadmin/health`
- `GET /api/dbadmin/health/performance`
- `POST /api/dbadmin/maintenance/nuke`
- `POST /api/dbadmin/maintenance/redeploy`
- `POST /api/dbadmin/maintenance/cleanup`
- `POST /api/dbadmin/maintenance/pgstac/redeploy`
- `GET /api/dbadmin/jobs`
- `GET /api/dbadmin/jobs/{job_id}`
- `GET /api/dbadmin/tasks`
- `GET /api/dbadmin/tasks/{job_id}`
- `GET /api/dbadmin/platform/requests`
- `GET /api/dbadmin/platform/requests/{request_id}`
- `GET /api/dbadmin/platform/orchestration`
- `GET /api/dbadmin/platform/orchestration/{request_id}`
- `GET /api/dbadmin/stats`
- `GET /api/dbadmin/diagnostics/enums`
- `GET /api/dbadmin/diagnostics/functions`
- `GET /api/dbadmin/diagnostics/all`

### Service Bus Admin (6)
- `GET /api/servicebus/queues`
- `GET /api/servicebus/queues/{queue_name}`
- `GET /api/servicebus/queues/{queue_name}/peek`
- `GET /api/servicebus/queues/{queue_name}/deadletter`
- `GET /api/servicebus/health`
- `POST /api/servicebus/queues/{queue_name}/nuke`

### STAC Management (6)
- `GET,POST /api/stac/setup`
- `POST /api/stac/nuke`
- `POST /api/stac/collections/{tier}`
- `POST /api/stac/init`
- `POST /api/stac/extract`
- `POST /api/stac/vector`

### STAC API (6)
- `GET /api/stac` (landing)
- `GET /api/stac/conformance`
- `GET /api/stac/collections`
- `GET /api/stac/collections/{collection_id}`
- `GET /api/stac/collections/{collection_id}/items`
- `GET /api/stac/collections/{collection_id}/items/{item_id}`

### OGC Features (6)
- `GET /api/features`
- `GET /api/features/conformance`
- `GET /api/features/collections`
- `GET /api/features/collections/{collection_id}`
- `GET /api/features/collections/{collection_id}/items`
- `GET /api/features/collections/{collection_id}/items/{feature_id}`

### Platform Service (3)
- `POST /api/platform/submit`
- `GET /api/platform/status/{request_id}`
- `GET /api/platform/status`

### Analysis/Container (varies)
- `GET /api/analysis/container/{job_id}`
- `GET /api/containers/{container_name}/blobs`
- `POST /api/analysis/delivery`

### Vector Viewer (1)
- `GET /api/vector/viewer`

### H3 Debug (1)
- `GET /api/h3/debug`

### Queue Triggers (2)
- Service Bus: `geospatial-jobs`
- Service Bus: `geospatial-tasks`

### Timer Triggers (3)
- Janitor watchdog
- Job health monitor
- Orphan detector

---

## Notes for Claude Agents

1. **Don't invent routes** - Only implement routes that exist in current `function_app.py`
2. **Check trigger signatures** - Some triggers need `core_machine` passed, some don't
3. **Preserve exact route paths** - Including path parameters like `{job_id}`
4. **Keep queue/timer triggers intact** - These are complex, just reorganize them
5. **Test incrementally** - Syntax check → import check → local run → deploy
