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
