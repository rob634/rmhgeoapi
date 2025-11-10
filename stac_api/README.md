# STAC API Implementation

**Author**: Robert and Geospatial Claude Legion
**Date**: 10 NOV 2025
**Version**: 1.0.0
**Status**: Production Ready - Phase 1 Complete

---

## Overview

Standalone STAC API v1.0.0 implementation for serving geospatial metadata through Azure Functions. This module provides a standards-compliant REST API for discovering and accessing geospatial collections and items with support for:

- ✅ **Landing Page** - STAC Catalog root with conformance links
- ✅ **Conformance Classes** - Standards compliance declaration
- ✅ **Collections** - List all STAC collections with metadata
- ⏳ **Collection Detail** - Individual collection metadata (Phase 2)
- ⏳ **Items Search** - Query STAC items with filters (Phase 2)
- ⏳ **Item Detail** - Individual item metadata (Phase 2)

**Key Feature**: Completely standalone - zero dependencies on main application. Can be deployed independently or integrated into existing Azure Function Apps. Returns **pure STAC JSON** without any extra fields.

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────────┐
│  HTTP Triggers (triggers.py)                                │
│  - Parse requests, return pure STAC JSON                    │
│  - 3 STAC endpoints (landing, conformance, collections)     │
│  - NO BaseHttpTrigger inheritance (spec compliance)         │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Service Layer (service.py)                                 │
│  - STAC response generation                                 │
│  - Link construction, metadata formatting                   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Infrastructure Layer (infrastructure/stac.py)              │
│  - pgSTAC database queries via psycopg                      │
│  - Collection and item retrieval                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  PostgreSQL + pgSTAC Extension                              │
│  - Collections in pgstac.collections table                  │
│  - Items in pgstac.items table                             │
│  - Native STAC JSON storage (JSONB)                        │
└─────────────────────────────────────────────────────────────┘
```

### File Structure

```
stac_api/                              # Standalone module (~500 lines)
├── __init__.py                        # Module exports
├── config.py                          # Environment-based configuration
├── service.py                         # STAC response generation
├── triggers.py                        # HTTP handlers (NO BaseHttpTrigger)
└── README.md                          # This file

Supporting Infrastructure (shared):
└── infrastructure/stac.py             # pgSTAC database operations
```

---

## Quick Start

### Prerequisites

- **Azure Functions Core Tools** v4+
- **Python** 3.9+
- **PostgreSQL** 12+ with **pgSTAC** 0.8.5+
- **Azure Function App** (or local development)

### Installation

#### Option 1: Integrated Deployment (within existing Function App)

```bash
# Already installed if using rmhgeoapi
# Just need to register routes in function_app.py

# 1. Verify module exists
ls stac_api/

# 2. Add to function_app.py (see Integration section below)

# 3. Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote
```

#### Option 2: Standalone Deployment (new Function App)

```bash
# 1. Create new Function App project
mkdir my-stac-api && cd my-stac-api
func init --python

# 2. Copy module and infrastructure
cp -r /path/to/stac_api .
cp -r /path/to/infrastructure .

# 3. Create minimal function_app.py
cat > function_app.py << 'EOF'
import azure.functions as func
from stac_api import get_stac_triggers

app = func.FunctionApp()

# Extract handlers from trigger registry
_stac_triggers = get_stac_triggers()
_stac_landing = _stac_triggers[0]['handler']
_stac_conformance = _stac_triggers[1]['handler']
_stac_collections = _stac_triggers[2]['handler']

# Register STAC endpoints using decorator pattern
@app.route(route="stac", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API landing page: GET /api/stac"""
    return _stac_landing(req)

@app.route(route="stac/conformance", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API conformance: GET /api/stac/conformance"""
    return _stac_conformance(req)

@app.route(route="stac/collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API collections list: GET /api/stac/collections"""
    return _stac_collections(req)
EOF

# 4. Add dependencies to requirements.txt
cat >> requirements.txt << 'EOF'
azure-functions
psycopg[binary]
pydantic>=2.0
pypgstac==0.8.5
EOF

# 5. Configure environment variables (see Configuration section)

# 6. Deploy
func azure functionapp publish my-stac-api --python --build remote
```

---

## Configuration

### Environment Variables

#### Required

```bash
# PostgreSQL Connection
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_DATABASE=postgres
POSTGIS_USER=your_user
POSTGIS_PASSWORD=your_password
```

#### Optional

```bash
# Database Configuration
POSTGIS_PORT=5432                        # Default: 5432

# STAC API Configuration
STAC_CATALOG_ID=rmh-geospatial-stac     # Default: "rmh-geospatial-stac"
STAC_CATALOG_TITLE=RMH Geospatial STAC API  # Default shown
STAC_CATALOG_DESCRIPTION=...             # Default shown
STAC_VERSION=1.0.0                       # Default: "1.0.0"
STAC_BASE_URL=https://example.com        # Default: auto-detect from request
```

### Azure Portal Configuration

1. Navigate to Function App → Configuration → Application settings
2. Add environment variables listed above
3. **Important**: Use "Advanced edit" for bulk paste
4. Save and restart Function App

### Local Development (local.settings.json)

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "POSTGIS_HOST": "localhost",
    "POSTGIS_DATABASE": "geodata",
    "POSTGIS_USER": "postgres",
    "POSTGIS_PASSWORD": "password",
    "STAC_CATALOG_ID": "my-stac-catalog",
    "STAC_BASE_URL": "http://localhost:7071"
  }
}
```

---

## Integration

### Adding to Existing Function App

In your `function_app.py`:

```python
import azure.functions as func

# ... your existing imports and code ...

# Add STAC API endpoints
from stac_api import get_stac_triggers

# Extract handlers from trigger registry
_stac_triggers = get_stac_triggers()
_stac_landing = _stac_triggers[0]['handler']
_stac_conformance = _stac_triggers[1]['handler']
_stac_collections = _stac_triggers[2]['handler']

# Register STAC endpoints using decorator pattern (Azure Functions requirement)
@app.route(route="stac", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_landing(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API landing page: GET /api/stac"""
    return _stac_landing(req)

@app.route(route="stac/conformance", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API conformance: GET /api/stac/conformance"""
    return _stac_conformance(req)

@app.route(route="stac/collections", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def stac_api_collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """STAC API collections list: GET /api/stac/collections"""
    return _stac_collections(req)
```

**Important**: Azure Functions requires the decorator pattern for route registration. Loop-based registration (`app.route(...)(...)`)) does **not** work and will result in 404 errors.

---

## API Endpoints

### Base URL

```
https://your-app.azurewebsites.net/api/stac
```

### Endpoint Reference (Phase 1)

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/api/stac` | GET | ✅ Live | Landing page (STAC Catalog) |
| `/api/stac/conformance` | GET | ✅ Live | Conformance classes |
| `/api/stac/collections` | GET | ✅ Live | List all collections |

### Planned Endpoints (Phase 2)

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/api/stac/collections/{id}` | GET | ⏳ Planned | Collection metadata |
| `/api/stac/collections/{id}/items` | GET | ⏳ Planned | Query items with filters |
| `/api/stac/collections/{id}/items/{item_id}` | GET | ⏳ Planned | Single item by ID |
| `/api/stac/search` | POST | ⏳ Planned | Advanced search (STAC API - Item Search) |

---

## Usage Examples

### Landing Page (Catalog Root)

**Request**:
```bash
curl https://your-app.azurewebsites.net/api/stac | python3 -m json.tool
```

**Response**:
```json
{
  "id": "rmh-geospatial-stac",
  "type": "Catalog",
  "title": "RMH Geospatial STAC API",
  "description": "STAC catalog for geospatial raster and vector data with OAuth-based tile serving via TiTiler-pgSTAC",
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
      "href": "https://your-app.azurewebsites.net/api/stac",
      "title": "This catalog"
    },
    {
      "rel": "root",
      "type": "application/json",
      "href": "https://your-app.azurewebsites.net/api/stac",
      "title": "Root catalog"
    },
    {
      "rel": "conformance",
      "type": "application/json",
      "href": "https://your-app.azurewebsites.net/api/stac/conformance",
      "title": "STAC API conformance classes"
    },
    {
      "rel": "data",
      "type": "application/json",
      "href": "https://your-app.azurewebsites.net/api/stac/collections",
      "title": "Data collections"
    }
  ]
}
```

### Conformance Classes

**Request**:
```bash
curl https://your-app.azurewebsites.net/api/stac/conformance | python3 -m json.tool
```

**Response**:
```json
{
  "conformsTo": [
    "https://api.stacspec.org/v1.0.0/core",
    "https://api.stacspec.org/v1.0.0/collections",
    "https://api.stacspec.org/v1.0.0/ogcapi-features",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
  ]
}
```

### Collections List

**Request**:
```bash
curl https://your-app.azurewebsites.net/api/stac/collections | python3 -m json.tool
```

**Response**:
```json
{
  "collections": [
    {
      "id": "landsat-8",
      "type": "Collection",
      "stac_version": "1.0.0",
      "title": "Landsat 8 Imagery",
      "description": "Landsat 8 surface reflectance data",
      "license": "proprietary",
      "extent": {
        "spatial": {
          "bbox": [[-180, -90, 180, 90]]
        },
        "temporal": {
          "interval": [["2013-04-11T00:00:00Z", null]]
        }
      },
      "links": [
        {
          "rel": "self",
          "type": "application/json",
          "href": "https://your-app.azurewebsites.net/api/stac/collections/landsat-8"
        },
        {
          "rel": "items",
          "type": "application/geo+json",
          "href": "https://your-app.azurewebsites.net/api/stac/collections/landsat-8/items"
        }
      ]
    }
  ],
  "links": [
    {
      "rel": "self",
      "type": "application/json",
      "href": "https://your-app.azurewebsites.net/api/stac/collections"
    },
    {
      "rel": "root",
      "type": "application/json",
      "href": "https://your-app.azurewebsites.net/api/stac"
    }
  ]
}
```

---

## STAC Browser Integration

### Using STAC Browser (Radiant Earth)

**Official STAC Browser**: https://radiantearth.github.io/stac-browser

1. Open STAC Browser
2. Enter your catalog URL: `https://your-app.azurewebsites.net/api/stac`
3. Browse collections and items visually
4. View metadata, extents, and assets

### Custom Integration

```html
<!DOCTYPE html>
<html>
<head>
    <title>My STAC Catalog</title>
    <script src="https://cdn.jsdelivr.net/npm/@radiantearth/stac-browser@3.0.0/dist/stac-browser.min.js"></script>
</head>
<body>
    <div id="stac-browser"></div>
    <script>
        const browser = new STACBrowser({
            catalogUrl: 'https://your-app.azurewebsites.net/api/stac',
            container: '#stac-browser'
        });
    </script>
</body>
</html>
```

---

## Python Client Integration

### Using pystac-client

```python
from pystac_client import Client

# Connect to catalog
catalog = Client.open('https://your-app.azurewebsites.net/api/stac')

# List collections
collections = list(catalog.get_collections())
print(f"Found {len(collections)} collections")

for collection in collections:
    print(f"- {collection.id}: {collection.title}")
    print(f"  Extent: {collection.extent.spatial.bboxes}")

# (Phase 2) Search for items
search = catalog.search(
    collections=['landsat-8'],
    bbox=[-122.5, 37.7, -122.3, 37.9],
    datetime='2024-01-01/2024-12-31',
    limit=100
)

items = list(search.items())
print(f"Found {len(items)} items")
```

---

## Database Setup

### pgSTAC Installation

```bash
# Install pgSTAC extension (requires PostgreSQL superuser)
psql -h your-host -U postgres -d your-database -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -h your-host -U postgres -d your-database -c "CREATE EXTENSION IF NOT EXISTS pgstac CASCADE;"
```

### Verify Installation

```sql
-- Check pgSTAC version
SELECT pgstac.get_version();

-- List pgSTAC tables
\dt pgstac.*

-- Expected tables:
-- pgstac.collections
-- pgstac.items
-- pgstac.queryables
-- pgstac.collection_summaries
```

### Add Collection (Example)

```python
from pypgstac.db import PgstacDB
from pystac import Collection, Extent, SpatialExtent, TemporalExtent

# Connect to database
with PgstacDB(dsn='postgresql://user:pass@host/db') as db:
    # Create collection
    collection = Collection(
        id='my-collection',
        description='My test collection',
        extent=Extent(
            spatial=SpatialExtent([[-180, -90, 180, 90]]),
            temporal=TemporalExtent([[None, None]])
        ),
        license='proprietary'
    )

    # Load into pgSTAC
    db.add_collection(collection)
    print(f"Added collection: {collection.id}")
```

---

## Architecture Decisions

### Why NO BaseHttpTrigger?

**Problem**: BaseHttpTrigger adds non-spec fields to responses:
```json
{
  "id": "my-catalog",
  "type": "Catalog",
  "request_id": "abc123",      // ❌ Not in STAC spec
  "timestamp": "2025-11-10..."  // ❌ Not in STAC spec
}
```

**Solution**: Custom `BaseSTACTrigger` class that returns **pure STAC JSON**:
```python
class BaseSTACTrigger:
    """Custom base class - returns pure JSON without extra fields."""

    def _json_response(self, data: Any) -> func.HttpResponse:
        return func.HttpResponse(
            body=json.dumps(data, indent=2),
            mimetype="application/json"
        )
```

### Why Decorator Pattern (Not Loop)?

**Problem**: Loop-based route registration doesn't work in Azure Functions:
```python
# ❌ WRONG - Causes 404 errors on all endpoints
for trigger in get_stac_triggers():
    app.route(...)(trigger['handler'])
```

**Solution**: Decorator pattern with extracted handlers:
```python
# ✅ CORRECT - Azure Functions requirement
_stac_triggers = get_stac_triggers()
_stac_landing = _stac_triggers[0]['handler']

@app.route(route="stac", methods=["GET"], ...)
def stac_api_landing(req):
    return _stac_landing(req)
```

---

## Troubleshooting

### Common Issues

#### 1. "404 Not Found" on all endpoints

**Cause**: Using loop-based route registration instead of decorator pattern

**Solution**: Use decorator pattern as shown in Integration section

#### 2. "pgSTAC not installed"

**Cause**: pgSTAC extension not enabled in database

**Solution**:
```sql
-- Run as superuser
CREATE EXTENSION IF NOT EXISTS pgstac CASCADE;

-- Verify
SELECT pgstac.get_version();
```

#### 3. "Collections array is empty"

**Cause**: No collections in pgstac.collections table

**Solution**: Add collections using pypgstac or infrastructure/stac.py functions

#### 4. Response has extra fields (request_id, timestamp)

**Cause**: Accidentally using BaseHttpTrigger instead of BaseSTACTrigger

**Solution**: Ensure triggers inherit from `BaseSTACTrigger`, not `BaseHttpTrigger`

---

## API Specification Compliance

### STAC API v1.0.0

This implementation conforms to:

- ✅ **STAC Core** (conformance class)
- ✅ **STAC Collections** (conformance class)
- ✅ **OGC API - Features Core** (conformance class)
- ⏳ **STAC Item Search** (Phase 2)
- ⏳ **STAC Filter** (Phase 2)

### Specification Reference

- [STAC API Specification v1.0.0](https://github.com/radiantearth/stac-api-spec/tree/v1.0.0)
- [STAC Specification v1.0.0](https://github.com/radiantearth/stac-spec/tree/v1.0.0)
- [OGC API - Features Core 1.0](https://docs.ogc.org/is/17-069r4/17-069r4.html)

---

## Limitations (Phase 1)

### Not Implemented (Yet)

- ❌ **Collection detail** - Individual collection metadata (Phase 2)
- ❌ **Items search** - Query items with filters (Phase 2)
- ❌ **Item detail** - Single item by ID (Phase 2)
- ❌ **Advanced search** - POST /search endpoint (Phase 2)
- ❌ **CQL2 filtering** - Advanced queries (Phase 3)

### Workarounds

**Item Search**: Use pystac-client with POST /search (requires Phase 2)
**Filtering**: Direct pgSTAC SQL queries (for advanced use cases)

---

## Version History

### 1.0.0 (10 NOV 2025)

**Initial Release - Phase 1 Complete**

- ✅ STAC API v1.0.0 landing page
- ✅ Conformance classes endpoint
- ✅ Collections list endpoint
- ✅ Pure JSON responses (no extra fields)
- ✅ Decorator pattern route registration
- ✅ Standalone deployment support
- ✅ pgSTAC integration

**Statistics**:
- **Total Lines**: ~500
- **Files**: 4 Python modules
- **Endpoints**: 3 STAC-compliant
- **Test Coverage**: Manual (automated tests planned)

**Key Achievements**:
- Fixed Unicode encoding errors in logger statements
- Fixed route registration pattern (decorator vs loop)
- Fixed database connection string access
- Verified all endpoints return pure STAC JSON

---

## License

Part of rmhgeoapi project - Internal use only.

---

## Authors

**Robert and Geospatial Claude Legion**
Date: 10 NOV 2025

For questions or issues, refer to main project documentation (CLAUDE.md).
