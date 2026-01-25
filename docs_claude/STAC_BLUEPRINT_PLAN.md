# Phase 17.3: Unified STAC Blueprint Implementation

**Date**: 24 JAN 2026
**Status**: PLANNING
**Option**: B - Single Unified Blueprint

---

## Overview

Consolidate ALL 19 stac/* endpoints into a single `triggers/stac/stac_bp.py` blueprint. The B2C STAC API is handled by the service layer/Docker, so this internal API can be safely restructured.

---

## Current State (19 endpoints across 3 locations)

### Location 1: `stac_api/` module (6 endpoints)
| Route | Method | Handler | Lines |
|-------|--------|---------|-------|
| `/stac` | GET | STACLandingPageTrigger | ~30 |
| `/stac/conformance` | GET | STACConformanceTrigger | ~25 |
| `/stac/collections` | GET | STACCollectionsTrigger | ~40 |
| `/stac/collections/{id}` | GET | STACCollectionDetailTrigger | ~45 |
| `/stac/collections/{id}/items` | GET | STACItemsTrigger | ~80 |
| `/stac/collections/{id}/items/{item_id}` | GET | STACItemDetailTrigger | ~55 |

### Location 2: `triggers/admin/admin_stac.py` (6 endpoints)
| Route | Method | Handler | Lines |
|-------|--------|---------|-------|
| `/stac/init` | POST | stac_init | ~15 |
| `/stac/collections/{tier}` | POST | stac_collections | ~20 |
| `/stac/nuke` | POST | nuke_stac_data | ~20 |
| `/stac/repair/test` | GET | stac_repair_test | ~10 |
| `/stac/repair/inventory` | POST | stac_repair_inventory | ~15 |
| `/stac/repair/item` | POST | stac_repair_item | ~15 |

### Location 3: `function_app.py` inline (7 endpoints)
| Route | Method | Handler | Lines |
|-------|--------|---------|-------|
| `/stac/extract` | POST | stac_extract | ~20 |
| `/stac/vector` | POST | stac_vector | ~25 |
| `/stac/schema/info` | GET | stac_schema_info | ~30 |
| `/stac/collections/summary` | GET | stac_collections_summary | ~25 |
| `/stac/collections/{id}/stats` | GET | stac_collection_stats | ~40 |
| `/stac/items/{item_id}` | GET | stac_item_lookup | ~40 |
| `/stac/health` | GET | stac_health | ~25 |

---

## Target State

### New File: `triggers/stac/stac_bp.py`

```
triggers/stac/
├── __init__.py          # Exports: stac_bp
├── stac_bp.py           # Blueprint with all 19 routes
├── config.py            # STACAPIConfig (from stac_api/config.py)
└── service.py           # STACAPIService (from stac_api/service.py)
```

### Blueprint Organization

```python
# ============================================================================
# STAC BLUEPRINT - Unified STAC API & Admin Endpoints
# ============================================================================
# triggers/stac/stac_bp.py
#
# Routes (19 total):
#
#   STAC API v1.0.0 Core (6 routes - OGC Compliant):
#     GET  /stac                                    Landing page
#     GET  /stac/conformance                        Conformance classes
#     GET  /stac/collections                        List collections
#     GET  /stac/collections/{id}                   Get collection
#     GET  /stac/collections/{id}/items             List items (paginated)
#     GET  /stac/collections/{id}/items/{item_id}   Get item
#
#   Admin - Initialization (3 routes):
#     POST /stac/init                               Initialize collections
#     POST /stac/collections/{tier}                 Create tier collection
#     POST /stac/nuke                               Clear STAC data
#
#   Admin - Repair (3 routes):
#     GET  /stac/repair/test                        Test repair handler
#     POST /stac/repair/inventory                   Generate inventory
#     POST /stac/repair/item                        Repair single item
#
#   Admin - Catalog Operations (2 routes):
#     POST /stac/extract                            Extract raster metadata
#     POST /stac/vector                             Catalog vector table
#
#   Admin - Inspection (5 routes):
#     GET  /stac/schema/info                        PgSTAC schema info
#     GET  /stac/collections/summary                Quick summary
#     GET  /stac/collections/{id}/stats             Collection statistics
#     GET  /stac/items/{item_id}                    Item lookup shortcut
#     GET  /stac/health                             Health metrics
#
# ============================================================================
```

---

## Implementation Steps

### Step 1: Create Blueprint Structure
```bash
mkdir -p triggers/stac
touch triggers/stac/__init__.py
```

### Step 2: Move Config & Service
- Copy `stac_api/config.py` → `triggers/stac/config.py`
- Copy `stac_api/service.py` → `triggers/stac/service.py`
- Update imports in service.py

### Step 3: Create stac_bp.py
Create unified blueprint with all 19 routes organized by category:

```python
import azure.functions as func
from azure.functions import Blueprint

bp = Blueprint()

# ============================================================================
# STAC API v1.0.0 CORE (6 routes)
# ============================================================================

@bp.route(route="stac", methods=["GET"])
def stac_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 landing page."""
    from .service import STACAPIService
    from .config import get_stac_config
    # ... implementation

@bp.route(route="stac/conformance", methods=["GET"])
def stac_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API v1.0.0 conformance classes."""
    # ... implementation

# ... (remaining 4 core routes)

# ============================================================================
# ADMIN - INITIALIZATION (3 routes)
# ============================================================================

@bp.route(route="stac/init", methods=["POST"])
def stac_init(req: func.HttpRequest) -> func.HttpResponse:
    """Initialize STAC production collections."""
    from triggers.stac_init import stac_init_trigger
    return stac_init_trigger.handle_request(req)

# ... (remaining 2 init routes)

# ============================================================================
# ADMIN - REPAIR (3 routes)
# ============================================================================

# ... (3 repair routes)

# ============================================================================
# ADMIN - CATALOG OPERATIONS (2 routes)
# ============================================================================

@bp.route(route="stac/extract", methods=["POST"])
def stac_extract(req: func.HttpRequest) -> func.HttpResponse:
    """Extract STAC metadata from raster blob."""
    return stac_extract_trigger.handle_request(req)

@bp.route(route="stac/vector", methods=["POST"])
def stac_vector(req: func.HttpRequest) -> func.HttpResponse:
    """Catalog PostGIS vector table in STAC."""
    return stac_vector_trigger.handle_request(req)

# ============================================================================
# ADMIN - INSPECTION (5 routes)
# ============================================================================

@bp.route(route="stac/schema/info", methods=["GET"])
def stac_schema_info(req: func.HttpRequest) -> func.HttpResponse:
    """Deep inspection of pgstac schema structure."""
    from infrastructure.pgstac_bootstrap import get_schema_info
    # ... implementation

# ... (remaining 4 inspection routes)
```

### Step 4: Update function_app.py

```python
# Remove:
# - All inline stac/* routes (~200 lines)
# - stac_api trigger registration (~15 lines)
# - admin_stac_bp registration

# Add:
from triggers.stac import stac_bp
app.register_functions(stac_bp)
```

### Step 5: Delete Old Files
```bash
rm -rf stac_api/                          # Old module (replaced)
rm triggers/admin/admin_stac.py           # Old blueprint (merged)
rm triggers/admin/stac_repair.py          # Move to triggers/stac/
```

### Step 6: Update Imports
- `triggers/stac_init.py` - No change (still called by blueprint)
- `triggers/stac_collections.py` - No change
- `triggers/stac_nuke.py` - No change
- `triggers/stac_extract.py` - No change
- `triggers/stac_vector.py` - No change
- Move `triggers/admin/stac_repair.py` → `triggers/stac/repair.py`

---

## Files to Create

| File | Purpose | Lines (est) |
|------|---------|-------------|
| `triggers/stac/__init__.py` | Export stac_bp | ~10 |
| `triggers/stac/stac_bp.py` | All 19 routes | ~450 |
| `triggers/stac/config.py` | STACAPIConfig | ~55 (copy) |
| `triggers/stac/service.py` | STACAPIService | ~365 (copy) |
| `triggers/stac/repair.py` | Repair handlers | ~150 (move) |

## Files to Delete

| File | Reason |
|------|--------|
| `stac_api/__init__.py` | Replaced by triggers/stac/ |
| `stac_api/config.py` | Moved to triggers/stac/ |
| `stac_api/service.py` | Moved to triggers/stac/ |
| `stac_api/triggers.py` | Merged into stac_bp.py |
| `triggers/admin/admin_stac.py` | Merged into stac_bp.py |
| `triggers/admin/stac_repair.py` | Moved to triggers/stac/ |

## Files to Modify

| File | Changes |
|------|---------|
| `function_app.py` | Delete ~215 lines, add 2 lines for blueprint |
| `triggers/admin/__init__.py` | Remove admin_stac exports |

---

## Line Count Summary

| Action | Lines |
|--------|-------|
| Created (new blueprint) | ~1,030 |
| Deleted (function_app.py inline) | ~200 |
| Deleted (stac_api/ module) | ~600 |
| Deleted (admin_stac.py) | ~180 |
| **Net reduction** | **~950 lines removed from function_app.py scope** |

---

## Testing Checklist

### STAC API v1.0.0 Core
- [ ] `GET /api/stac` returns valid Catalog with conformsTo
- [ ] `GET /api/stac/conformance` returns conformance classes
- [ ] `GET /api/stac/collections` returns collections array
- [ ] `GET /api/stac/collections/{id}` returns single collection
- [ ] `GET /api/stac/collections/{id}/items` returns FeatureCollection
- [ ] `GET /api/stac/collections/{id}/items/{item_id}` returns Feature

### Admin - Initialization
- [ ] `POST /api/stac/init` initializes collections
- [ ] `POST /api/stac/collections/{tier}` creates tier collection
- [ ] `POST /api/stac/nuke?confirm=yes` clears data

### Admin - Repair
- [ ] `GET /api/stac/repair/test` returns handler status
- [ ] `POST /api/stac/repair/inventory` generates inventory
- [ ] `POST /api/stac/repair/item` repairs single item

### Admin - Catalog Operations
- [ ] `POST /api/stac/extract` extracts raster metadata
- [ ] `POST /api/stac/vector` catalogs vector table

### Admin - Inspection
- [ ] `GET /api/stac/schema/info` returns schema structure
- [ ] `GET /api/stac/collections/summary` returns summary
- [ ] `GET /api/stac/collections/{id}/stats` returns statistics
- [ ] `GET /api/stac/items/{item_id}` returns item
- [ ] `GET /api/stac/health` returns health metrics

---

## Acceptance Criteria

- [ ] All 19 stac/* endpoints functional
- [ ] No inline stac/* routes in function_app.py
- [ ] stac_api/ module deleted
- [ ] admin_stac.py merged into stac_bp
- [ ] Blueprint registered conditionally by APP_MODE
- [ ] All tests pass

---

*Document created: 24 JAN 2026*
*Author: Claude + Robert Harrison*
