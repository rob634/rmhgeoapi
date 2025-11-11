# STAC Isolation Architecture

**Date**: 11 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: 📋 PLANNING - Proposal for parallel STAC API implementation

---

## 🎯 Objective

Create a **parallel, read-only STAC API** implementation following the proven OGC Features portable module pattern, while preserving all existing ETL write operations.

**Key Principle**:
- **NEW**: `stac_api/` module - Read-only STAC v1.0.0 API (parallel implementation)
- **EXISTING**: All ETL write operations remain in place (untouched)

---

## 📊 Current STAC Ecosystem Analysis

### Infrastructure Layer (Shared by Both Systems)

**File**: `infrastructure/stac.py` (1,816 lines)

#### ✅ KEEP - Shared Read Operations (ETL + API)
These functions are READ-ONLY and will be used by both systems:

```python
# STAC API Reads (PgSTAC queries)
get_all_collections()           # Line 963, 1816 - List all collections
get_collection(collection_id)   # Line 1021 - Get single collection metadata
get_collection_items(...)       # Line 1064 - Get items with pagination
search_items(...)               # Line 1141 - STAC /search endpoint
get_item_by_id(...)            # Line 1616 - Get single item
get_collection_stats(...)       # Line 1485 - Collection statistics
get_collections_summary()       # Line 1754 - Summary across all collections
get_schema_info()              # Line 1365 - PgSTAC schema metadata
get_health_metrics()           # Line 1672 - Health check data
```

**Usage**:
- ✅ **New `stac_api/` module**: Will call these functions for API responses
- ✅ **Existing ETL workflows**: Already use these for validation/health checks

---

#### 🔒 KEEP - ETL Write Operations (MUST Stay in ETL Pipeline)
These functions WRITE to PgSTAC and are called by ETL jobs:

```python
# PgSTAC Infrastructure (One-time setup)
class PgStacInfrastructure:
    check_installation()        # Line 155 - Verify PgSTAC installed
    install_pgstac(...)        # Line 261 - Install/upgrade PgSTAC
    verify_installation()       # Line 420 - Deep validation

# Collection Management (ETL creates collections)
    create_collection(...)      # Line 531 - Create new STAC collection
    create_production_collection(...) # Line 637 - System collections
    determine_collection(...)   # Line 753 - Collection routing logic

# Item Management (ETL inserts STAC items)
    item_exists(...)           # Line 786 - Check if item exists
    insert_item(...)           # Line 818 - Insert single STAC item
    bulk_insert_items(...)     # Line 871 - Batch insert (100+ items)

# Maintenance Operations (Admin/ETL)
clear_stac_data(...)           # Line 1241 - Nuclear button (delete items/collections)
```

**Critical**: These MUST remain in `infrastructure/stac.py` because:
1. ETL jobs (`jobs/process_raster.py`, `jobs/ingest_vector.py`) call these
2. Admin triggers (`triggers/stac_nuke.py`, `triggers/stac_init.py`) use these
3. Services (`services/service_stac_metadata.py`) depend on these

---

### ETL Write Operations (DO NOT TOUCH)

#### Jobs (STAC Item Creation)
**These jobs WRITE STAC items during data ingestion**:

1. **`jobs/process_raster.py`** (Lines 644-664)
   - Creates STAC items for COGs after raster processing
   - Calls `infrastructure.stac.PgStacInfrastructure().insert_item()`
   - Collection: `system-rasters`

2. **`jobs/ingest_vector.py`** (Calls handler_finalize_vector_job)
   - Creates STAC items for PostGIS vector tables
   - Calls `services/handler_create_h3_stac.py` → `insert_item()`
   - Collection: `system-vectors`

3. **`jobs/process_raster_collection.py`**
   - Creates STAC items for MosaicJSON tile collections
   - Calls `services/stac_collection.py` → `insert_item()`
   - Collection: `system-rasters`

4. **`jobs/stac_catalog_vectors.py`**
   - Bulk catalog existing PostGIS tables into STAC
   - Calls `services/service_stac_vector.py` → `bulk_insert_items()`
   - Collection: `system-vectors`

5. **`jobs/stac_catalog_container.py`**
   - Bulk catalog entire storage containers into STAC
   - Calls `services/service_stac_metadata.py` → `bulk_insert_items()`
   - Collection: Based on container

6. **`jobs/create_h3_base.py` / `jobs/generate_h3_level4.py`**
   - Creates STAC items for H3 grids
   - Calls `services/handler_create_h3_stac.py` → `insert_item()`
   - Collection: `system-h3-grids`

**Decision**: ✅ **LEAVE ALL ETL JOBS UNTOUCHED** - They write STAC items correctly

---

#### Services (STAC Metadata Extraction)
**These services EXTRACT metadata and INSERT into PgSTAC**:

1. **`services/service_stac_metadata.py`**
   - Extracts STAC metadata from raster files using rio-stac
   - Creates STAC items with bbox, assets, properties
   - Called by: `jobs/process_raster.py`, `jobs/stac_catalog_container.py`

2. **`services/service_stac_vector.py`**
   - Extracts STAC metadata from PostGIS vector tables
   - Creates STAC items with spatial extent from PostGIS
   - Called by: `jobs/ingest_vector.py`, `jobs/stac_catalog_vectors.py`

3. **`services/handler_create_h3_stac.py`**
   - Creates STAC items for H3 grids
   - Called by: H3 job finalize_job handlers

4. **`services/stac_collection.py`**
   - Creates STAC collections for raster tile sets with MosaicJSON
   - Called by: `jobs/process_raster_collection.py`

5. **`services/stac_catalog.py`**
   - Catalog utility functions (appears to be legacy)

6. **`services/stac_vector_catalog.py`**
   - Vector catalog utility functions (appears to be legacy)

**Decision**: ✅ **LEAVE ALL SERVICES UNTOUCHED** - They handle ETL metadata extraction

---

#### Triggers (Admin Operations - Some Write)
**These triggers perform ADMIN operations that modify STAC**:

1. **`triggers/stac_nuke.py`** ⚠️ WRITE
   - POST /api/stac/nuke?confirm=yes&mode=all
   - Deletes STAC items/collections without dropping schema
   - Calls `infrastructure.stac.clear_stac_data()`
   - **Decision**: ✅ KEEP - Admin operation, not API

2. **`triggers/stac_init.py`** ⚠️ WRITE
   - POST /api/stac/init
   - Creates production STAC collections (system-vectors, system-rasters, etc.)
   - Calls `infrastructure.stac.create_production_collection()`
   - **Decision**: ✅ KEEP - Admin operation, not API

3. **`triggers/stac_setup.py`** ⚠️ READ + WRITE
   - GET /api/stac/setup/status → Reads PgSTAC status
   - POST /api/stac/setup/install → Installs PgSTAC
   - Calls `infrastructure.stac.check_installation()`, `install_pgstac()`
   - **Decision**: ✅ KEEP - Admin operation, not API

4. **`triggers/stac_inspect.py`** ✅ READ ONLY
   - GET /api/stac/inspect/schema → Schema info
   - GET /api/stac/inspect/health → Health metrics
   - GET /api/stac/inspect/collections → Collections summary
   - GET /api/stac/inspect/stats/{collection_id} → Collection stats
   - Calls `get_schema_info()`, `get_health_metrics()`, etc.
   - **Decision**: ✅ KEEP - Useful admin endpoint (read-only)

5. **`triggers/stac_extract.py`** ⚠️ WRITE
   - POST /api/stac/extract → Extract and insert STAC from raster blobs
   - Calls `services/service_stac_metadata.py` → `insert_item()`
   - **Decision**: ✅ KEEP - ETL operation, not API

6. **`triggers/stac_vector.py`** ⚠️ WRITE
   - POST /api/stac/vector → Catalog PostGIS table into STAC
   - Calls `services/service_stac_vector.py` → `insert_item()`
   - **Decision**: ✅ KEEP - ETL operation, not API

7. **`triggers/stac_collections.py`** ⚠️ WRITE
   - POST /api/stac/collections/bronze → Create Bronze collection
   - Calls `infrastructure.stac.create_collection()`
   - **Decision**: ✅ KEEP - Admin operation, not API

---

## 🚨 Current Problem: No STAC API Implementation

**Observation**: We have ZERO files implementing the STAC API v1.0.0 specification!

**Expected Files** (DO NOT EXIST):
- `triggers/stac_api_landing.py` - Landing page endpoint
- `triggers/stac_api_conformance.py` - Conformance classes
- `triggers/stac_api_collections.py` - Collection list + detail
- `triggers/stac_api_items.py` - Item list + detail
- `triggers/stac_api_search.py` - STAC /search endpoint (optional)

**What We DO Have**:
- ✅ Infrastructure layer (`infrastructure/stac.py`) with all query functions
- ✅ PgSTAC installed and populated with data (via ETL)
- ✅ Admin endpoints for setup, inspection, nuke
- ✅ ETL endpoints for item insertion
- ❌ NO STAC API v1.0.0 compliant read endpoints

**Root Cause**:
- TODO.md mentioned inheriting from `BaseHttpTrigger`
- But those trigger files were never created
- Only admin/ETL triggers exist

---

## 📐 Proposed Architecture: Parallel STAC API Module

### NEW: `stac_api/` Module (Read-Only STAC v1.0.0 API)

**Pattern**: Mirror `ogc_features/` portable module architecture

```
stac_api/
├── __init__.py              # Export get_stac_triggers()
├── triggers.py              # STAC API trigger handlers
├── service.py               # STAC API business logic
└── config.py                # STAC API configuration (optional)
```

---

### File Structure Detail

#### `stac_api/__init__.py`
```python
"""
STAC API v1.0.0 Portable Module

Read-only STAC API compliant with OGC STAC Core specification.
Completely isolated from ETL write operations.

Integration (in function_app.py):
    from stac_api import get_stac_triggers

    for trigger in get_stac_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Author: Robert and Geospatial Claude Legion
Date: 11 NOV 2025
"""

from .triggers import get_stac_triggers

__all__ = ['get_stac_triggers']
```

---

#### `stac_api/triggers.py`

**Purpose**: STAC API v1.0.0 HTTP trigger handlers

**Endpoints to Implement**:

1. **Landing Page**: `GET /api/stac`
   - Returns STAC catalog root with links
   - Calls `infrastructure.stac.get_all_collections()` for collection count

2. **Conformance**: `GET /api/stac/conformance`
   - Returns list of conformance classes
   - Static response (STAC Core, Item Search, etc.)

3. **Collections List**: `GET /api/stac/collections`
   - Returns all collections with metadata
   - Calls `infrastructure.stac.get_all_collections()`

4. **Collection Detail**: `GET /api/stac/collections/{collection_id}`
   - Returns single collection metadata
   - Calls `infrastructure.stac.get_collection(collection_id)`

5. **Items List**: `GET /api/stac/collections/{collection_id}/items`
   - Returns paginated items from collection
   - Calls `infrastructure.stac.get_collection_items(collection_id, limit, offset)`
   - Query params: `limit` (default: 10), `offset`, `bbox`

6. **Item Detail**: `GET /api/stac/collections/{collection_id}/items/{item_id}`
   - Returns single item metadata
   - Calls `infrastructure.stac.get_item_by_id(item_id, collection_id)`

7. **Search** (Optional - Phase 2): `POST /api/stac/search`
   - STAC search with spatial/temporal filters
   - Calls `infrastructure.stac.search_items(...)`
   - Request body: `bbox`, `datetime`, `collections`, `limit`

**Key Design**:
```python
def get_stac_triggers() -> List[Dict[str, Any]]:
    """
    Return list of STAC API trigger configurations.

    Returns:
        [
            {
                'route': 'stac',
                'methods': ['GET'],
                'handler': stac_landing_page_handler
            },
            {
                'route': 'stac/conformance',
                'methods': ['GET'],
                'handler': stac_conformance_handler
            },
            # ... more triggers
        ]
    """
    pass

def stac_landing_page_handler(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/stac - Landing page."""
    service = STACAPIService()
    catalog = service.get_catalog(base_url=req.url)
    return func.HttpResponse(
        body=json.dumps(catalog),
        mimetype='application/json',
        status_code=200
    )
```

**Critical**: NO inheritance from `BaseHttpTrigger` - pure functions returning `func.HttpResponse`

---

#### `stac_api/service.py`

**Purpose**: STAC API business logic (calls infrastructure layer)

```python
class STACAPIService:
    """
    STAC API business logic layer.

    Transforms infrastructure responses into STAC v1.0.0 compliant JSON.
    """

    def __init__(self):
        """Initialize service (no config needed - uses infrastructure)."""
        pass

    def get_catalog(self, base_url: str) -> Dict[str, Any]:
        """
        Get STAC landing page.

        Returns:
            {
                "stac_version": "1.0.0",
                "type": "Catalog",
                "id": "rmh-geospatial-stac",
                "title": "RMH Geospatial STAC API",
                "description": "...",
                "links": [
                    {"rel": "self", "href": "..."},
                    {"rel": "conformance", "href": ".../conformance"},
                    {"rel": "data", "href": ".../collections"},
                    {"rel": "search", "href": ".../search"}
                ]
            }
        """
        from infrastructure.stac import get_all_collections

        collections_response = get_all_collections()
        num_collections = len(collections_response.get('collections', []))

        return {
            "stac_version": "1.0.0",
            "type": "Catalog",
            "id": "rmh-geospatial-stac",
            "title": "RMH Geospatial STAC API",
            "description": f"STAC API serving {num_collections} collections",
            "links": self._build_catalog_links(base_url)
        }

    def get_conformance(self) -> Dict[str, Any]:
        """
        Get conformance classes.

        Returns:
            {
                "conformsTo": [
                    "https://api.stacspec.org/v1.0.0/core",
                    "https://api.stacspec.org/v1.0.0/collections",
                    "https://api.stacspec.org/v1.0.0/item-search"
                ]
            }
        """
        return {
            "conformsTo": [
                "https://api.stacspec.org/v1.0.0/core",
                "https://api.stacspec.org/v1.0.0/collections",
                "https://api.stacspec.org/v1.0.0/item-search",
                "https://api.stacspec.org/v1.0.0/ogcapi-features",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
            ]
        }

    def get_collections(self, base_url: str) -> Dict[str, Any]:
        """
        Get all collections.

        Returns:
            {
                "collections": [
                    {
                        "id": "system-rasters",
                        "title": "System STAC - Raster Files",
                        "description": "...",
                        "extent": {...},
                        "links": [...]
                    }
                ],
                "links": [...]
            }
        """
        from infrastructure.stac import get_all_collections

        response = get_all_collections()
        collections = response.get('collections', [])

        # Add links to each collection
        for coll in collections:
            coll['links'] = self._build_collection_links(base_url, coll['id'])

        return {
            "collections": collections,
            "links": self._build_collections_links(base_url)
        }

    def get_collection(self, collection_id: str, base_url: str) -> Dict[str, Any]:
        """
        Get single collection metadata.

        Calls infrastructure.stac.get_collection(collection_id)
        Adds STAC API links
        """
        from infrastructure.stac import get_collection

        response = get_collection(collection_id)
        if 'error' in response:
            return response

        collection = response['collection']
        collection['links'] = self._build_collection_links(base_url, collection_id)

        return collection

    def get_items(
        self,
        collection_id: str,
        base_url: str,
        limit: int = 10,
        offset: int = 0,
        bbox: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get items from collection (paginated).

        Calls infrastructure.stac.get_collection_items(...)
        Transforms to STAC ItemCollection format
        """
        from infrastructure.stac import get_collection_items

        response = get_collection_items(
            collection_id=collection_id,
            limit=limit,
            offset=offset,
            bbox=bbox
        )

        if 'error' in response:
            return response

        return {
            "type": "FeatureCollection",
            "features": response.get('features', []),
            "links": self._build_items_links(base_url, collection_id, limit, offset),
            "numberMatched": response.get('numberMatched'),
            "numberReturned": response.get('numberReturned')
        }

    def get_item(
        self,
        collection_id: str,
        item_id: str,
        base_url: str
    ) -> Dict[str, Any]:
        """
        Get single item.

        Calls infrastructure.stac.get_item_by_id(item_id, collection_id)
        """
        from infrastructure.stac import get_item_by_id

        response = get_item_by_id(item_id, collection_id)
        if 'error' in response:
            return response

        item = response.get('item')
        item['links'] = self._build_item_links(base_url, collection_id, item_id)

        return item

    # ... _build_*_links() helper methods
```

---

#### `stac_api/config.py` (Optional - Phase 2)

**Purpose**: STAC API module configuration (if needed)

```python
from pydantic import BaseModel, Field

class STACAPIConfig(BaseModel):
    """STAC API module configuration."""

    catalog_id: str = Field(
        default="rmh-geospatial-stac",
        description="STAC catalog ID"
    )

    catalog_title: str = Field(
        default="RMH Geospatial STAC API",
        description="Human-readable catalog title"
    )

    max_items_per_page: int = Field(
        default=100,
        description="Maximum items per page"
    )
```

---

### Integration with function_app.py

**Add to function_app.py** (after existing route registrations):

```python
# ============================================================================
# STAC API v1.0.0 - Read-Only Endpoints (11 NOV 2025)
# ============================================================================
from stac_api import get_stac_triggers

for trigger in get_stac_triggers():
    app.route(
        route=trigger['route'],
        methods=trigger['methods'],
        auth_level=func.AuthLevel.ANONYMOUS
    )(trigger['handler'])
```

**Result**: 6-7 new STAC API endpoints registered automatically

---

## 🔄 Testing Strategy: Parallel Implementation

### Phase 1: Create Parallel Module (No Breaking Changes)

**Step 1**: Create `stac_api/` module with all files
**Step 2**: Add routes to `function_app.py`
**Step 3**: Deploy to Azure
**Step 4**: Test new STAC API endpoints

**Existing System**:
- ✅ All ETL write operations continue working
- ✅ All admin endpoints (`/api/stac/nuke`, `/api/stac/init`) continue working
- ✅ Zero impact on existing functionality

**New System**:
- ✅ STAC API endpoints available at `/api/stac`, `/api/stac/collections`, etc.
- ✅ Read-only queries to PgSTAC
- ✅ STAC v1.0.0 compliant responses

---

### Phase 2: Validation & Testing

**STAC API Testing Checklist**:

1. **Landing Page**:
   ```bash
   curl https://rmhgeoapibeta-.../api/stac | jq .
   # Expect: STAC catalog with links
   ```

2. **Conformance**:
   ```bash
   curl https://rmhgeoapibeta-.../api/stac/conformance | jq .
   # Expect: List of conformance classes
   ```

3. **Collections List**:
   ```bash
   curl https://rmhgeoapibeta-.../api/stac/collections | jq .
   # Expect: Array of collections (system-rasters, system-vectors, etc.)
   ```

4. **Collection Detail**:
   ```bash
   curl https://rmhgeoapibeta-.../api/stac/collections/system-rasters | jq .
   # Expect: Collection metadata with extent, links
   ```

5. **Items List**:
   ```bash
   curl "https://rmhgeoapibeta-.../api/stac/collections/system-rasters/items?limit=5" | jq .
   # Expect: FeatureCollection with 5 items
   ```

6. **Item Detail**:
   ```bash
   curl https://rmhgeoapibeta-.../api/stac/collections/system-rasters/items/{item_id} | jq .
   # Expect: Single STAC item with geometry, assets
   ```

7. **Pagination**:
   ```bash
   curl "https://rmhgeoapibeta-.../api/stac/collections/system-rasters/items?limit=10&offset=10" | jq .
   # Expect: Next page of items with prev/next links
   ```

8. **Browser Testing**:
   - Open https://rmhgeoapibeta-.../api/stac in browser
   - Should render as JSON (pure STAC response, no extra fields)
   - Test with STAC Browser client (if available)

**Validation**:
- ✅ All responses are pure STAC JSON (no `request_id`, `timestamp` fields)
- ✅ All responses include proper `links` arrays
- ✅ Pagination works correctly
- ✅ Bbox filtering works (if implemented)
- ✅ Error responses are STAC-compliant

---

### Phase 3: Documentation & Cleanup (Optional)

**After validation**:
1. Update API documentation (`docs_claude/API_STAC.md`)
2. Add STAC API examples to README
3. Consider deprecating old admin endpoints (if desired)
4. Move to QA checklist → COMPLETE

**Future**: When ready for production corporate Azure:
- Keep parallel implementation (both systems work)
- Optionally remove old admin endpoints if not needed
- But for now, NO breaking changes

---

## 📋 Summary

### ETL Write Operations (DO NOT TOUCH - Already Working)

**Infrastructure**:
- `infrastructure/stac.py` - Keep ALL functions (reads + writes)

**Jobs** (STAC item insertion):
- `jobs/process_raster.py`
- `jobs/ingest_vector.py`
- `jobs/process_raster_collection.py`
- `jobs/stac_catalog_vectors.py`
- `jobs/stac_catalog_container.py`
- `jobs/create_h3_base.py`
- `jobs/generate_h3_level4.py`

**Services** (Metadata extraction):
- `services/service_stac_metadata.py`
- `services/service_stac_vector.py`
- `services/handler_create_h3_stac.py`
- `services/stac_collection.py`

**Triggers** (Admin operations):
- `triggers/stac_nuke.py` - Delete items/collections
- `triggers/stac_init.py` - Create production collections
- `triggers/stac_setup.py` - PgSTAC installation
- `triggers/stac_inspect.py` - Admin health checks (read-only, but keep)
- `triggers/stac_extract.py` - Extract and insert from blobs
- `triggers/stac_vector.py` - Catalog PostGIS tables
- `triggers/stac_collections.py` - Create collections

**Decision**: ✅ **LEAVE ALL EXISTING FILES COMPLETELY UNTOUCHED**

---

### NEW: Read-Only STAC API Module

**Create**:
```
stac_api/
├── __init__.py              # Export get_stac_triggers()
├── triggers.py              # 6-7 STAC API endpoint handlers
├── service.py               # STACAPIService (business logic)
└── config.py                # STACAPIConfig (optional)
```

**Endpoints**:
1. GET /api/stac - Landing page
2. GET /api/stac/conformance - Conformance classes
3. GET /api/stac/collections - Collection list
4. GET /api/stac/collections/{id} - Collection detail
5. GET /api/stac/collections/{id}/items - Items list (paginated)
6. GET /api/stac/collections/{id}/items/{item_id} - Item detail
7. POST /api/stac/search - STAC search (Phase 2)

**Dependencies**:
- Calls `infrastructure.stac.get_all_collections()`, `get_collection()`, `get_collection_items()`, `get_item_by_id()`, `search_items()`
- Zero changes to infrastructure layer
- Pure STAC v1.0.0 JSON responses

---

## 🚀 Implementation Timeline

**Total Estimated Time**: 2-3 hours

1. **Create stac_api/ module structure** (10 min)
   - Create folder and files
   - Add __init__.py exports

2. **Implement stac_api/service.py** (45 min)
   - STACAPIService class
   - 6 endpoint methods
   - Link building helpers

3. **Implement stac_api/triggers.py** (30 min)
   - get_stac_triggers() function
   - 6-7 handler functions
   - URL parsing and parameter extraction

4. **Update function_app.py** (5 min)
   - Add import and route registration loop

5. **Deploy and test** (30 min)
   - Deploy to Azure
   - Test all 6 endpoints with curl
   - Validate STAC compliance

6. **Documentation** (15 min)
   - Update TODO.md (mark QA item complete)
   - Update HISTORY.md

**Total**: ~2 hours 15 minutes

---

## ✅ Benefits of Parallel Implementation

1. **Zero Breaking Changes**: All existing ETL continues working
2. **Proven Pattern**: Mirrors successful `ogc_features/` module
3. **STAC Compliant**: Pure spec-compliant responses
4. **Portable**: Ready for microservices split (APIM)
5. **Testable**: Can validate new API without touching ETL
6. **Safe**: Can roll back by removing `stac_api/` import
7. **Future-Proof**: Both systems can coexist indefinitely

---

**Next Step**: Approve this plan, then implement `stac_api/` module following OGC Features pattern.
