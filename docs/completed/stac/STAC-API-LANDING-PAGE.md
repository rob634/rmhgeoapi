# STAC API Landing Page - What's Missing

**Date**: 10 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Issue**: `/api/stac/` returns 404 - Need STAC API Catalog (Landing Page)

---

## 🎯 What is a STAC API Landing Page?

The **STAC API Landing Page** (also called "Catalog" or "Root") is the **entry point** for a STAC API service. It's like the homepage of your STAC API - it tells clients what's available and how to navigate your catalog.

**Think of it like a restaurant menu**:
- Landing Page = Front cover with restaurant info + table of contents
- Collections endpoint = Menu sections (appetizers, entrees, desserts)
- Items endpoints = Individual dishes within each section

---

## 📋 STAC API Specification (OGC API - Features Part 1)

### Required Endpoints

**1. Landing Page** (`GET /`)
**Status**: ❌ **MISSING** (returns 404)

```json
{
  "id": "rmh-geospatial-stac",
  "type": "Catalog",
  "title": "RMH Geospatial STAC API",
  "description": "STAC catalog for geospatial raster and vector data",
  "stac_version": "1.0.0",
  "conformsTo": [
    "https://api.stacspec.org/v1.0.0/core",
    "https://api.stacspec.org/v1.0.0/collections",
    "https://api.stacspec.org/v1.0.0/ogcapi-features",
    "https://api.stacspec.org/v1.0.0/item-search"
  ],
  "links": [
    {
      "rel": "self",
      "type": "application/json",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"
    },
    {
      "rel": "root",
      "type": "application/json",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"
    },
    {
      "rel": "conformance",
      "type": "application/json",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/conformance"
    },
    {
      "rel": "data",
      "type": "application/json",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections"
    },
    {
      "rel": "search",
      "type": "application/geo+json",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/search",
      "method": "GET"
    },
    {
      "rel": "search",
      "type": "application/geo+json",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/search",
      "method": "POST"
    }
  ]
}
```

**2. Collections List** (`GET /collections`)
**Status**: ⚠️ **PARTIAL** (we have `/api/stac/collections/summary` but not standard endpoint)

```json
{
  "collections": [
    {
      "id": "system-rasters",
      "type": "Collection",
      "title": "System STAC - Raster Files",
      "description": "Operational tracking of COG files created by ETL",
      "license": "proprietary",
      "extent": {
        "spatial": {"bbox": [[-77.02, 38.90, -77.01, 38.93]]},
        "temporal": {"interval": [["2025-11-10T18:12:51Z", null]]}
      },
      "links": [
        {
          "rel": "self",
          "href": "https://rmhgeoapibeta.../api/stac/collections/system-rasters"
        },
        {
          "rel": "items",
          "href": "https://rmhgeoapibeta.../api/stac/collections/system-rasters/items"
        }
      ]
    },
    {
      "id": "system-vectors",
      "type": "Collection",
      "...": "..."
    }
  ],
  "links": [
    {
      "rel": "self",
      "href": "https://rmhgeoapibeta.../api/stac/collections"
    },
    {
      "rel": "root",
      "href": "https://rmhgeoapibeta.../api/stac"
    }
  ]
}
```

**3. Collection Detail** (`GET /collections/{collectionId}`)
**Status**: ❌ **MISSING**

**4. Items List** (`GET /collections/{collectionId}/items`)
**Status**: ❌ **MISSING** (we have `/api/stac/items/{itemId}` but not collection-scoped list)

**5. Item Detail** (`GET /collections/{collectionId}/items/{itemId}`)
**Status**: ✅ **EXISTS** (`/api/stac/items/{itemId}?collection={collectionId}`)

**6. Search** (`POST /search` and `GET /search`)
**Status**: ❌ **MISSING**

**7. Conformance** (`GET /conformance`)
**Status**: ❌ **MISSING**

---

## 🔍 What We Have vs What We Need

### What We Have ✅

**Custom Inspection Endpoints** (not part of STAC spec):
- `GET /api/stac/collections/summary` - Quick collection summary
- `GET /api/stac/collections/{id}/stats` - Detailed collection statistics
- `GET /api/stac/items/{item_id}?collection={id}` - Item lookup
- `GET /api/stac/health` - Health check
- `GET /api/stac/schema/info` - Schema inspection

**Setup/Admin Endpoints**:
- `GET/POST /api/stac/setup` - PgSTAC installation
- `POST /api/stac/nuke` - Clear STAC data (dev only)

### What We're Missing ❌

**STAC API Standard Endpoints**:
1. ❌ **Landing Page** - `GET /api/stac/` (returns 404)
2. ❌ **Collections List** - `GET /api/stac/collections`
3. ❌ **Collection Detail** - `GET /api/stac/collections/{collectionId}`
4. ❌ **Items List** - `GET /api/stac/collections/{collectionId}/items`
5. ❌ **Search** - `POST /api/stac/search`
6. ❌ **Conformance** - `GET /api/stac/conformance`

---

## 📦 PgSTAC Native API vs Custom Endpoints

### Option 1: Use PgSTAC's Built-in FastAPI Server ⭐ RECOMMENDED

**PgSTAC comes with a complete STAC API implementation!**

```python
# From pypgstac package
from pypgstac.api import PgStacAPI

# This provides ALL standard STAC API endpoints:
# - GET /
# - GET /conformance
# - GET /collections
# - GET /collections/{collectionId}
# - GET /collections/{collectionId}/items
# - GET /collections/{collectionId}/items/{itemId}
# - POST /search
# - GET /search
```

**Why we haven't used it yet**:
- We built custom endpoints for specific inspection needs
- PgSTAC's API is a complete FastAPI app (not Azure Functions compatible directly)
- Need to adapt it to Azure Functions route pattern

### Option 2: Build Custom STAC API Endpoints (Current Approach)

**Pros**:
- Full control over implementation
- Can customize for Azure Functions
- Already started with custom endpoints

**Cons**:
- More work to implement all STAC spec endpoints
- Need to maintain compliance with STAC spec
- Reinventing the wheel (PgSTAC already has this)

---

## 🎯 Recommended Implementation Strategy

### Phase 1: Add STAC API Landing Page (Quick Win)

Create `triggers/stac_landing.py`:

```python
@app.route(route="stac", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_landing(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API Landing Page (Catalog Root).

    Spec: https://api.stacspec.org/v1.0.0/core
    """
    from infrastructure.stac import PgStacInfrastructure
    from config import get_config

    config = get_config()
    base_url = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"

    catalog = {
        "id": "rmh-geospatial-stac",
        "type": "Catalog",
        "title": "RMH Geospatial STAC API",
        "description": "STAC catalog for geospatial raster and vector data with OAuth-based tile serving",
        "stac_version": "1.0.0",
        "conformsTo": [
            "https://api.stacspec.org/v1.0.0/core",
            "https://api.stacspec.org/v1.0.0/collections",
            "https://api.stacspec.org/v1.0.0/ogcapi-features"
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/json",
                "href": f"{base_url}"
            },
            {
                "rel": "root",
                "type": "application/json",
                "href": f"{base_url}"
            },
            {
                "rel": "conformance",
                "type": "application/json",
                "href": f"{base_url}/conformance",
                "title": "STAC API conformance classes"
            },
            {
                "rel": "data",
                "type": "application/json",
                "href": f"{base_url}/collections",
                "title": "Collections in this catalog"
            },
            {
                "rel": "search",
                "type": "application/geo+json",
                "href": f"{base_url}/search",
                "method": "GET",
                "title": "STAC search endpoint (GET)"
            },
            {
                "rel": "search",
                "type": "application/geo+json",
                "href": f"{base_url}/search",
                "method": "POST",
                "title": "STAC search endpoint (POST)"
            },
            {
                "rel": "service-desc",
                "type": "application/vnd.oai.openapi+json;version=3.0",
                "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/openapi/v3.json",
                "title": "OpenAPI 3.0 service description"
            },
            {
                "rel": "service-doc",
                "type": "text/html",
                "href": "https://stacspec.org/en/api/",
                "title": "STAC API documentation"
            }
        ]
    }

    return func.HttpResponse(
        json.dumps(catalog, indent=2),
        mimetype="application/json",
        status_code=200
    )
```

### Phase 2: Add Standard Collections Endpoint

Create `triggers/stac_api_collections.py`:

```python
@app.route(route="stac/collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API Collections List.

    Spec: https://api.stacspec.org/v1.0.0/collections
    """
    from infrastructure.stac import PgStacInfrastructure

    stac = PgStacInfrastructure()
    base_url = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"

    # Get collections from pgSTAC
    collections = []

    for coll_id in ['system-rasters', 'system-vectors']:
        try:
            # Query pgSTAC for collection details
            collection = stac.get_collection(coll_id)  # Implement this method

            collections.append({
                "id": collection['id'],
                "type": "Collection",
                "title": collection.get('title', ''),
                "description": collection.get('description', ''),
                "license": collection.get('license', 'proprietary'),
                "extent": collection.get('extent', {}),
                "links": [
                    {
                        "rel": "self",
                        "href": f"{base_url}/collections/{coll_id}"
                    },
                    {
                        "rel": "items",
                        "href": f"{base_url}/collections/{coll_id}/items"
                    },
                    {
                        "rel": "root",
                        "href": f"{base_url}"
                    }
                ]
            })
        except Exception as e:
            logger.error(f"Failed to get collection {coll_id}: {e}")

    response = {
        "collections": collections,
        "links": [
            {
                "rel": "self",
                "href": f"{base_url}/collections"
            },
            {
                "rel": "root",
                "href": f"{base_url}"
            }
        ]
    }

    return func.HttpResponse(
        json.dumps(response, indent=2, default=str),
        mimetype="application/json",
        status_code=200
    )
```

### Phase 3: Add Collection Items List

```python
@app.route(route="stac/collections/{collectionId}/items", methods=["GET"])
def stac_api_collection_items(req: func.HttpRequest) -> func.HttpResponse:
    """
    List items in a collection with pagination.

    Spec: https://api.stacspec.org/v1.0.0/ogcapi-features
    """
    collection_id = req.route_params.get('collectionId')
    limit = int(req.params.get('limit', '10'))
    offset = int(req.params.get('offset', '0'))

    # Query pgSTAC items table
    # ... implementation ...
```

### Phase 4: Use PgSTAC's Built-in API (Future Enhancement)

**Research**: Look into `pypgstac` package's FastAPI application:
- `pypgstac.api.app` - Complete STAC API server
- Wrap it in Azure Functions adapter
- Get all endpoints for free!

---

## 📚 STAC API Resources

**Specification**:
- STAC API Core: https://api.stacspec.org/v1.0.0/core
- STAC API Collections: https://api.stacspec.org/v1.0.0/collections
- STAC API Item Search: https://api.stacspec.org/v1.0.0/item-search

**Examples**:
- Planetary Computer: https://planetarycomputer.microsoft.com/api/stac/v1
- Earth Search: https://earth-search.aws.element84.com/v1

**Testing**:
- STAC Browser: https://radiantearth.github.io/stac-browser/
- STAC Validator: https://staclint.com/

---

## ✅ Summary

**Current Status**:
- ❌ Landing page missing (`GET /api/stac/`)
- ⚠️ Custom endpoints exist but don't follow STAC API spec
- ✅ Data is correct (1 item, /vsiaz/ paths working)

**What "Landing Page" Means**:
- Not just a welcome message
- JSON document describing the entire catalog
- Links to collections, search, conformance endpoints
- Entry point for STAC clients and browsers

**Next Steps**:
1. Add landing page endpoint (`GET /api/stac/`)
2. Add standard collections list (`GET /api/stac/collections`)
3. Add collection items list (`GET /api/stac/collections/{id}/items`)
4. Add conformance endpoint (`GET /api/stac/conformance`)
5. Consider adopting pypgstac's built-in API server

**Priority**: Landing page is **HIGH** - without it, STAC clients can't discover your catalog!

---

## 📋 Implementation TODO List

### Phase 1: Core STAC API Endpoints (Using pypgstac + PostgreSQL pgSTAC)

**Goal**: Implement STAC API v1.0.0 Core + Collections conformance using existing pgSTAC database

#### Task 1.1: Research pypgstac API Capabilities
- [ ] Review `pypgstac` package documentation for FastAPI routes
- [ ] Identify which endpoints can be directly queried from pgSTAC database
- [ ] Document SQL queries for each STAC endpoint (collections, items, search)
- [ ] Check if `pypgstac` has ready-to-use functions we can import
- [ ] Research how to execute pgSTAC stored procedures from Python

**Tools**: `pypgstac` package (v0.8.5), PostgreSQL `pgstac` schema
**Resources**:
- https://github.com/stac-utils/pgstac
- https://stac-utils.github.io/pgstac/pypgstac/

---

#### Task 1.2: Implement Landing Page (GET /api/stac/)
- [ ] Create `triggers/stac_api_landing.py` with catalog root endpoint
- [ ] Return static JSON catalog descriptor with conformance links
- [ ] Include links to: collections, search, conformance, service-desc
- [ ] Set STAC version to 1.0.0
- [ ] Test with `curl https://.../api/stac/` returns JSON catalog
- [ ] Register route in `function_app.py`

**Dependencies**: None (static JSON response)
**Priority**: HIGH
**Estimated Effort**: 1-2 hours

**Code Template**:
```python
# triggers/stac_api_landing.py
@app.route(route="stac", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API Landing Page - Entry point for STAC catalog"""
    # Return catalog descriptor JSON (lines 227-288 in this doc)
```

---

#### Task 1.3: Implement Conformance Endpoint (GET /api/stac/conformance)
- [ ] Create `triggers/stac_api_conformance.py`
- [ ] Return conformance classes JSON array
- [ ] Include: Core, Collections, OGC API - Features, Item Search
- [ ] Test conformance response matches STAC spec

**Dependencies**: None (static JSON response)
**Priority**: HIGH
**Estimated Effort**: 30 minutes

**Code Template**:
```python
# triggers/stac_api_conformance.py
@app.route(route="stac/conformance", methods=["GET"])
def stac_api_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API Conformance Classes"""
    return {
        "conformsTo": [
            "https://api.stacspec.org/v1.0.0/core",
            "https://api.stacspec.org/v1.0.0/collections",
            "https://api.stacspec.org/v1.0.0/ogcapi-features",
            "https://api.stacspec.org/v1.0.0/item-search"
        ]
    }
```

---

#### Task 1.4: Implement Collections List (GET /api/stac/collections)
- [ ] Add method to `infrastructure/stac.py`: `get_all_collections()`
- [ ] Query pgSTAC `collections` table for collection metadata
- [ ] Calculate spatial/temporal extents from items (use pgSTAC functions)
- [ ] Format response per STAC Collections spec
- [ ] Include links: self, root, items for each collection
- [ ] Test with 2 collections: system-rasters, system-vectors

**Dependencies**: PostgreSQL pgSTAC schema, `infrastructure/stac.py`
**Priority**: HIGH
**Estimated Effort**: 2-3 hours

**Database Query**:
```sql
-- Query pgSTAC collections table
SELECT id, content FROM pgstac.collections ORDER BY id;

-- Use pgSTAC function to get collection with computed extents
SELECT * FROM pgstac.collection_extent('system-rasters');
```

---

#### Task 1.5: Implement Collection Detail (GET /api/stac/collections/{collectionId})
- [ ] Add method to `infrastructure/stac.py`: `get_collection(collection_id)`
- [ ] Query single collection from pgSTAC
- [ ] Include computed extents (bbox, temporal interval)
- [ ] Add links: self, root, items, parent
- [ ] Handle 404 if collection not found
- [ ] Test with valid and invalid collection IDs

**Dependencies**: Task 1.4 (get_all_collections method)
**Priority**: HIGH
**Estimated Effort**: 1-2 hours

**Database Query**:
```sql
-- Get single collection with extents
SELECT * FROM pgstac.get_collection('system-rasters');
```

---

#### Task 1.6: Implement Collection Items List (GET /api/stac/collections/{collectionId}/items)
- [ ] Add method to `infrastructure/stac.py`: `get_collection_items(collection_id, limit, offset, bbox)`
- [ ] Query pgSTAC `items` table with pagination
- [ ] Support query parameters: limit (default 10), offset, bbox
- [ ] Return GeoJSON FeatureCollection format
- [ ] Include pagination links: next, prev, self
- [ ] Test pagination with multiple items

**Dependencies**: PostgreSQL pgSTAC schema
**Priority**: HIGH
**Estimated Effort**: 3-4 hours

**Database Query**:
```sql
-- Get items for collection with pagination
SELECT content FROM pgstac.items
WHERE collection = 'system-rasters'
ORDER BY datetime DESC
LIMIT 10 OFFSET 0;
```

---

#### Task 1.7: Implement Item Detail (GET /api/stac/collections/{collectionId}/items/{itemId})
- [ ] Adapt existing `/api/stac/items/{itemId}?collection=...` endpoint
- [ ] Create standard route: `/api/stac/collections/{collectionId}/items/{itemId}`
- [ ] Reuse existing item lookup logic from `stac_inspect.py`
- [ ] Add collection validation (verify item belongs to collection)
- [ ] Test with valid collection+item, invalid collection, item not in collection

**Dependencies**: Existing item lookup code in `triggers/stac_inspect.py`
**Priority**: MEDIUM (already have working endpoint, just need standard route)
**Estimated Effort**: 1 hour

---

### Phase 2: STAC Search API (Item Search Extension)

#### Task 2.1: Implement POST /search Endpoint
- [ ] Research pgSTAC `search()` function for complex queries
- [ ] Create `triggers/stac_api_search.py`
- [ ] Support search parameters: collections, bbox, datetime, limit, query
- [ ] Use pgSTAC's native search function (optimized for performance)
- [ ] Return paginated GeoJSON FeatureCollection
- [ ] Include next/prev pagination links

**Dependencies**: pgSTAC `search()` function
**Priority**: MEDIUM
**Estimated Effort**: 4-6 hours

**Database Function**:
```sql
-- Use pgSTAC's optimized search function
SELECT * FROM pgstac.search(
    '{"collections": ["system-rasters"], "limit": 10}' :: jsonb
);
```

---

#### Task 2.2: Implement GET /search Endpoint
- [ ] Create GET version of search (query string parameters)
- [ ] Convert GET params to JSON for pgSTAC search function
- [ ] Support same parameters as POST /search
- [ ] Test equivalence between GET and POST searches

**Dependencies**: Task 2.1 (POST /search)
**Priority**: LOW (POST is more common)
**Estimated Effort**: 2 hours

---

### Phase 3: Testing & Validation

#### Task 3.1: STAC API Validation
- [ ] Test all endpoints with STAC Validator (https://staclint.com/)
- [ ] Verify conformance to STAC API v1.0.0 spec
- [ ] Test with STAC Browser (https://radiantearth.github.io/stac-browser/)
- [ ] Create integration tests for each endpoint
- [ ] Document example requests/responses

**Priority**: HIGH
**Estimated Effort**: 3-4 hours

---

#### Task 3.2: Performance Optimization
- [ ] Add database indexes if needed (check pgSTAC default indexes)
- [ ] Implement response caching for collections list (rarely changes)
- [ ] Test pagination performance with large result sets
- [ ] Monitor query times in Application Insights

**Priority**: MEDIUM
**Estimated Effort**: 2-3 hours

---

### Phase 4: Documentation & Client Tools

#### Task 4.1: OpenAPI/Swagger Documentation
- [ ] Generate OpenAPI 3.0 spec for STAC API endpoints
- [ ] Host at `/api/stac/openapi.json`
- [ ] Add link from landing page (service-desc rel)
- [ ] Test with Swagger UI

**Priority**: LOW
**Estimated Effort**: 2-3 hours

---

#### Task 4.2: Update CLAUDE.md Documentation
- [ ] Document new STAC API endpoints in CLAUDE.md
- [ ] Add example curl commands for each endpoint
- [ ] Update FILE_CATALOG.md with new trigger files
- [ ] Move this TODO to docs_claude/TODO.md (active task list)

**Priority**: MEDIUM
**Estimated Effort**: 1 hour

---

## 🔧 Technical Implementation Notes

### Database Queries - Use pgSTAC Functions

**pgSTAC provides optimized PostgreSQL functions**:
```sql
-- Get all collections
SELECT * FROM pgstac.all_collections();

-- Get single collection with extents
SELECT * FROM pgstac.get_collection('system-rasters');

-- Search items (powerful!)
SELECT * FROM pgstac.search('{"collections": ["system-rasters"], "limit": 10}' :: jsonb);

-- Get items for collection
SELECT content FROM pgstac.items WHERE collection = 'system-rasters' LIMIT 10;
```

### Response Formatting

**All STAC API responses use consistent link structure**:
```python
def add_stac_links(obj, base_url, rel_links):
    """Add STAC-compliant links to response object"""
    if 'links' not in obj:
        obj['links'] = []

    obj['links'].extend([
        {"rel": "self", "href": f"{base_url}{self_path}"},
        {"rel": "root", "href": f"{base_url}"},
        # ... additional links
    ])
    return obj
```

### Azure Functions Route Pattern

**Use route parameters for RESTful paths**:
```python
# Collection detail: /api/stac/collections/{collectionId}
@app.route(route="stac/collections/{collectionId}", methods=["GET"])
def stac_api_collection_detail(req: func.HttpRequest) -> func.HttpResponse:
    collection_id = req.route_params.get('collectionId')
    # ...

# Item detail: /api/stac/collections/{collectionId}/items/{itemId}
@app.route(route="stac/collections/{collectionId}/items/{itemId}", methods=["GET"])
def stac_api_item_detail(req: func.HttpRequest) -> func.HttpResponse:
    collection_id = req.route_params.get('collectionId')
    item_id = req.route_params.get('itemId')
    # ...
```

---

## 📊 Success Criteria

**Phase 1 Complete** when:
- ✅ Landing page returns valid STAC Catalog JSON
- ✅ Collections endpoint returns all collections with extents
- ✅ Collection detail shows individual collection metadata
- ✅ Items list supports pagination (limit/offset)
- ✅ Item detail returns individual STAC items
- ✅ All endpoints pass STAC Validator checks

**Phase 2 Complete** when:
- ✅ POST /search supports bbox, datetime, collections queries
- ✅ Search results include pagination links
- ✅ GET /search provides same functionality as POST

**Phase 3 Complete** when:
- ✅ STAC Browser can navigate entire catalog
- ✅ All endpoints tested with integration tests
- ✅ Performance meets SLA (< 1s for most queries)

---

## 🎯 Estimated Total Effort

- **Phase 1 (Core Endpoints)**: 10-14 hours
- **Phase 2 (Search)**: 6-8 hours
- **Phase 3 (Testing)**: 5-7 hours
- **Phase 4 (Documentation)**: 3-4 hours

**Total**: 24-33 hours (3-4 days of focused work)

**Quick Win**: Tasks 1.2 + 1.3 (Landing Page + Conformance) = 1.5-2 hours for immediate STAC discoverability!
