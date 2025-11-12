# STAC Implementation Analysis

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Assess current STAC query implementation and plan nuclear button endpoint

---

## Executive Summary

✅ **STAC API Compliance**: The implementation follows **STAC API spec v1.0** and **OGC API - Features** standards
✅ **Query Endpoints**: 4 standard STAC API endpoints fully implemented
✅ **Backend**: Using **PgSTAC 0.8.5** (pgstac schema in PostgreSQL)
⚠️ **Missing**: No nuclear button endpoint for clearing items/collections (needed for dev/test)

---

## Current Implementation Status

### 🎯 STAC API Standard Endpoints (4/4 Implemented)

#### 1. **GET /api/collections** ✅
- **Purpose**: List all STAC collections
- **Standard**: STAC API spec v1.0 - Core
- **Implementation**: `function_app.py:786-822`
- **Backend**: `infrastructure/stac.py:get_all_collections()`
- **Returns**: `{ "collections": [...] }`

#### 2. **GET /api/collections/{collection_id}** ✅
- **Purpose**: Get single collection metadata
- **Standard**: STAC API spec v1.0 - Core
- **Implementation**: `function_app.py:825-872`
- **Backend**: `infrastructure/stac.py:get_collection()`
- **Returns**: STAC Collection object

#### 3. **GET /api/collections/{collection_id}/items** ✅
- **Purpose**: Get items in a collection
- **Standard**: STAC API spec v1.0 - Core
- **Implementation**: `function_app.py:875-949`
- **Backend**: `infrastructure/stac.py:get_collection_items()`
- **Query Parameters**:
  - `limit`: Max items (default 100)
  - `bbox`: Bounding box (minx,miny,maxx,maxy)
  - `datetime`: RFC 3339 or interval
- **Returns**: STAC ItemCollection (GeoJSON FeatureCollection)

#### 4. **GET/POST /api/search** ✅
- **Purpose**: Search items across multiple collections
- **Standard**: STAC API spec v1.0 - Item Search
- **Implementation**: `function_app.py:952-1040`
- **Backend**: `infrastructure/stac.py:search_items()`
- **Query Parameters** (GET) / Body (POST):
  - `collections`: Array or comma-separated IDs
  - `bbox`: Bounding box
  - `datetime`: Datetime filter
  - `limit`: Max results
  - `query`: Additional filters (POST only)
- **Returns**: STAC ItemCollection (GeoJSON FeatureCollection)
- **Media Type**: `application/geo+json`

---

## Standards Compliance

### ✅ STAC API Specification v1.0
Our implementation follows the **STAC API spec v1.0** (OGC API - Features extension):

**Required Core Endpoints** (3/3):
- ✅ `GET /collections` - List collections
- ✅ `GET /collections/{collectionId}` - Collection detail
- ✅ `GET /collections/{collectionId}/items` - Collection items

**Optional Extensions** (1/1 implemented):
- ✅ **Item Search** (`GET/POST /search`) - Cross-collection search

**Reference**: https://github.com/radiantearth/stac-api-spec

### ✅ OGC API - Features
STAC API builds on **OGC API - Features**, which we comply with:
- Collections as feature collections
- Items as GeoJSON features
- Spatial queries via `bbox`
- Temporal queries via `datetime`
- Pagination via `limit`

**Reference**: https://ogcapi.ogc.org/features/

---

## Backend Architecture

### PgSTAC Integration

**Version**: pypgstac 0.8.5
**Schema**: `pgstac` (separate from app schema)
**Tables**:
- `pgstac.collections` - STAC collections metadata
- `pgstac.items` - STAC items (features)
- `pgstac.partitions` - Automatic partitioning

**Key Functions** (infrastructure/stac.py):
```python
# Query functions (lines 956-1200+)
get_all_collections()           # Line 956
get_collection(collection_id)   # Line 1014
get_collection_items(...)       # Line 1057
search_items(...)               # Line 1134

# Management functions
install_stac(drop_existing)     # Line 936
StacInfrastructure class        # Line 51-950
```

### Existing Destructive Operations

**Full Schema Drop** (EXISTS):
```python
# infrastructure/stac.py:313-323
def _drop_pgstac_schema(self):
    """Drop pgstac schema (DESTRUCTIVE - development only!)."""
    cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
        sql.Identifier(self.PGSTAC_SCHEMA)
    ))
```

**Confirmation Pattern**:
```python
# Requires environment variable
PGSTAC_CONFIRM_DROP=true
```

---

## Current Collections

**Production Collections** (infrastructure/stac.py:82-120):

### System STAC (Layer 1 - Operational):
- `system-vectors` - PostGIS vector tables tracking
- `system-rasters` - COG files tracking

### Legacy Collections:
- `cogs` - Cloud-Optimized GeoTIFFs
- `vectors` - PostGIS vector features
- `geoparquet` - Analytical datasets (future)

---

## Gap Analysis: Nuclear Button Endpoint

### What's Missing

❌ **Targeted Data Clearing**: No endpoint to clear items/collections without dropping entire schema

### What Exists
✅ Full schema drop via `install_stac(drop_existing=True)`
✅ Requires `PGSTAC_CONFIRM_DROP=true` environment variable

### What We Need

**New Endpoint**: `POST /api/stac/nuke?confirm=yes`

**Capabilities**:
1. ⚠️ **Clear All Items** - `DELETE FROM pgstac.items CASCADE`
2. ⚠️ **Clear All Collections** - `DELETE FROM pgstac.collections CASCADE`
3. 🔄 **Preserve Schema** - Keep pgstac schema structure intact
4. 🔒 **Confirmation Required** - Query parameter `?confirm=yes`

**Use Cases**:
- Development testing with fresh STAC state
- Integration test cleanup
- Demo resets without full schema rebuild
- Faster than full drop/recreate cycle

---

## Recommended Implementation Plan

### Step 1: Add Nuke Functions to infrastructure/stac.py

```python
def clear_all_items() -> Dict[str, Any]:
    """
    Clear all STAC items (preserve collections and schema).
    ⚠️ DESTRUCTIVE - Development/testing only!
    """

def clear_all_collections() -> Dict[str, Any]:
    """
    Clear all STAC collections and items (preserve schema).
    ⚠️ DESTRUCTIVE - Development/testing only!
    """

def clear_stac_data(items_only: bool = False) -> Dict[str, Any]:
    """
    Clear STAC data with CASCADE deletes.

    Args:
        items_only: If True, only delete items (keep collections)
                   If False, delete collections + items

    Returns:
        Status dict with counts deleted
    """
```

### Step 2: Add HTTP Trigger

**File**: Create `triggers/stac_nuke.py` following db_query.py pattern

**Route**: `POST /api/stac/nuke?confirm=yes&mode=all|items|collections`

**Query Parameters**:
- `confirm`: Must be "yes" (400 error otherwise)
- `mode`: "all" (default), "items", or "collections"

**Response**:
```json
{
  "success": true,
  "operation": "stac_nuke",
  "mode": "all",
  "deleted": {
    "items": 1234,
    "collections": 5
  },
  "execution_time_ms": 456.78,
  "warning": "⚠️ DEV/TEST ONLY - All STAC data cleared"
}
```

### Step 3: Add to function_app.py

```python
from triggers.stac_nuke import stac_nuke_trigger

@app.route(route="stac/nuke", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def nuke_stac_data(req: func.HttpRequest) -> func.HttpResponse:
    """
    🚨 NUCLEAR: Clear STAC items/collections (DEV/TEST ONLY)
    POST /api/stac/nuke?confirm=yes&mode=all
    """
    return stac_nuke_trigger.handle_request(req)
```

### Step 4: Update Documentation

- Add to CLAUDE.md database debugging section
- Add to FILE_CATALOG.md triggers section
- Update function_app.py docstring

---

## SQL Implementation Details

### Clear Items Only (Preserve Collections)
```sql
-- Fast - just items
DELETE FROM pgstac.items;

-- Returns: Number of items deleted
```

### Clear Collections + Items (CASCADE)
```sql
-- CASCADE automatically deletes related items
DELETE FROM pgstac.collections CASCADE;

-- Returns: Number of collections deleted (items deleted via CASCADE)
```

### Get Counts Before Delete
```sql
SELECT
    (SELECT COUNT(*) FROM pgstac.items) as items_count,
    (SELECT COUNT(*) FROM pgstac.collections) as collections_count;
```

---

## Safety Considerations

### ⚠️ Development/Testing Only
- **NOT for production use**
- Should be disabled via environment variable in production
- Similar pattern to existing schema nuke endpoint

### 🔒 Confirmation Required
- Must pass `?confirm=yes` query parameter
- 400 error if missing confirmation
- Log all nuke operations with timestamps

### 📊 Execution Reporting
- Report counts deleted (items, collections)
- Execution time tracking
- Success/failure status

### 🔄 Recovery
- Schema remains intact - can immediately add new collections
- No need to reinstall PgSTAC
- Faster than full drop/recreate (keeps functions, indexes, partitions)

---

## Testing Workflow

```bash
# 1. Check current STAC state
curl https://rmhgeoapibeta-.../api/collections

# 2. Add test data
curl -X POST https://rmhgeoapibeta-.../api/stac/init ...

# 3. Verify data exists
curl https://rmhgeoapibeta-.../api/search?limit=10

# 4. Nuclear button - clear everything
curl -X POST "https://rmhgeoapibeta-.../api/stac/nuke?confirm=yes&mode=all"

# 5. Verify cleared
curl https://rmhgeoapibeta-.../api/collections
# Should return: {"collections": []}
```

---

## Comparison: Nuclear Button vs Full Schema Drop

| Operation | Nuclear Button | Full Schema Drop |
|-----------|---------------|------------------|
| **Deletes Items** | ✅ | ✅ |
| **Deletes Collections** | ✅ | ✅ |
| **Drops Schema** | ❌ | ✅ |
| **Drops Functions** | ❌ | ✅ |
| **Requires Reinstall** | ❌ | ✅ |
| **Speed** | Fast (DELETE) | Slower (DROP + CREATE) |
| **Preserves Indexes** | ✅ | ❌ |
| **Preserves Partitions** | ✅ | ❌ |
| **Use Case** | Quick data clear | Full reset |

---

## Next Steps

1. ✅ **Analysis Complete** - This document
2. 📝 **Implement Functions** - Add to infrastructure/stac.py
3. 🔧 **Create Trigger** - New triggers/stac_nuke.py
4. 🔌 **Register Route** - Add to function_app.py
5. 🧪 **Test** - Verify with real data
6. 📚 **Document** - Update CLAUDE.md and FILE_CATALOG.md
7. 🚀 **Deploy** - Push to Azure Functions

---

## References

- **STAC API Spec**: https://github.com/radiantearth/stac-api-spec
- **OGC API - Features**: https://ogcapi.ogc.org/features/
- **PgSTAC**: https://github.com/stac-utils/pgstac
- **Current Implementation**: `infrastructure/stac.py`, `function_app.py:786-1040`
- **Nuclear Button Pattern**: `triggers/db_query.py:943-1198` (SchemaNukeQueryTrigger)
