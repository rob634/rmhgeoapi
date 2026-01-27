# B2B STAC Catalog Access - Implementation Plan

**Created**: 16 JAN 2026
**Epic**: F12.8 API Documentation Hub
**Feature**: B2B Catalog Endpoints for DDH Integration

---

## Executive Summary

DDH (Data Hub Dashboard) submits data through Platform API endpoints. After processing completes, DDH needs to verify STAC items exist and retrieve asset URLs for display in their catalog. This plan defines three new B2B endpoints that provide privileged STAC access using DDH identifiers.

---

## 1. Analysis: What DDH Needs

### Current Flow
```
DDH submits: POST /api/platform/submit
  ├── DDH provides: dataset_id, resource_id, version_id, file_name
  ├── Platform creates: request_id (SHA256 of DDH IDs)
  └── CoreMachine creates: job_id → STAC item (collection_id/item_id)

DDH polls: GET /api/platform/status/{request_id}
  └── Returns: job_status, job_result (includes cog_url, collection_id, stac_item_id)
```

### Gap Analysis
DDH currently gets `cog_url`, `collection_id`, and `stac_item_id` from job results. However:

1. **No verification**: DDH can't confirm STAC item actually exists in catalog
2. **No direct lookup**: DDH knows their identifiers, not our STAC IDs
3. **No asset URLs**: DDH needs TiTiler preview URLs for their UI
4. **No metadata**: DDH needs bbox, temporal extent for catalog display

### DDH's B2B Use Cases

| Use Case | Description | When |
|----------|-------------|------|
| **Verify Processing** | Confirm STAC item was created | After job completes |
| **Get Asset URLs** | Retrieve COG URL + TiTiler preview URLs | When displaying data in DDH |
| **Lookup by DDH IDs** | Find our STAC items using their identifiers | Any time (linkage) |
| **Get Metadata** | Retrieve bbox, temporal extent, properties | For DDH catalog display |

---

## 2. Data Model Review

### DDH Identifiers → STAC Mapping

DDH identifiers are stored in multiple locations:

```
┌─────────────────────────────────────────────────────────────────┐
│                        DDH Identifiers                          │
│  dataset_id + resource_id + version_id                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  app.api_requests (Platform thin tracking)                      │
│  ├── request_id = SHA256(dataset_id|resource_id|version_id)[:32]│
│  ├── job_id → Points to CoreMachine job                         │
│  └── DDH IDs stored (dataset_id, resource_id, version_id)       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  app.jobs (CoreMachine)                                         │
│  └── result_data contains:                                      │
│      ├── collection_id                                          │
│      ├── stac_item_id                                           │
│      └── cog_url                                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  pgstac.items (STAC Catalog)                                    │
│  └── properties contains:                                       │
│      ├── platform:dataset_id                                    │
│      ├── platform:resource_id                                   │
│      ├── platform:version_id                                    │
│      └── platform:request_id                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  app.dataset_refs (Cross-type DDH linkage)                      │
│  ├── dataset_id (internal: blob path or table name)             │
│  ├── data_type (raster/vector/zarr)                             │
│  └── ddh_dataset_id, ddh_resource_id, ddh_version_id            │
└─────────────────────────────────────────────────────────────────┘
```

### Lookup Strategy

**Primary Path** (recommended): DDH IDs → api_requests → job → result_data → STAC IDs → pgstac

**Alternative Path** (direct STAC query): Query pgstac.items WHERE properties @> '{"platform:dataset_id": "..."}'

The primary path is more reliable because:
- Uses indexed columns in relational tables
- Doesn't depend on JSONB index in pgstac
- Leverages existing Platform infrastructure

---

## 3. Proposed Endpoints

### 3.1 Catalog Lookup

**Endpoint**: `GET /api/platform/catalog/lookup`

**Purpose**: Verify STAC item exists for DDH identifiers, return basic info.

**Query Parameters**:
- `dataset_id` (required): DDH dataset identifier
- `resource_id` (required): DDH resource identifier
- `version_id` (required): DDH version identifier

**Response** (200 OK - found):
```json
{
  "found": true,
  "stac": {
    "collection_id": "flood-hazard-2024",
    "item_id": "magallanes-region-flood",
    "item_url": "/api/platform/catalog/item/flood-hazard-2024/magallanes-region-flood"
  },
  "ddh_refs": {
    "dataset_id": "flood-hazard-data",
    "resource_id": "res-001",
    "version_id": "v1.0"
  },
  "processing": {
    "request_id": "a3f2c1b8...",
    "job_id": "abc123...",
    "completed_at": "2026-01-15T10:00:00Z"
  }
}
```

**Response** (200 OK - not found):
```json
{
  "found": false,
  "ddh_refs": {
    "dataset_id": "flood-hazard-data",
    "resource_id": "res-001",
    "version_id": "v1.0"
  },
  "suggestion": "Check /api/platform/status to see if processing is still in progress"
}
```

### 3.2 Get STAC Item

**Endpoint**: `GET /api/platform/catalog/item/{collection_id}/{item_id}`

**Purpose**: Retrieve full STAC item with all metadata.

**Response** (200 OK):
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "magallanes-region-flood",
  "collection": "flood-hazard-2024",
  "geometry": {...},
  "bbox": [-75.5, -56.5, -66.5, -49.0],
  "properties": {
    "datetime": "2026-01-15T00:00:00Z",
    "platform:dataset_id": "flood-hazard-data",
    "platform:resource_id": "res-001",
    "platform:version_id": "v1.0",
    "proj:epsg": 4326,
    "raster:bands": [...]
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeocogs.blob.core.windows.net/silver-cogs/flood.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    }
  },
  "links": [...]
}
```

### 3.3 Get Asset URLs

**Endpoint**: `GET /api/platform/catalog/assets/{collection_id}/{item_id}`

**Purpose**: Get asset URLs with pre-built TiTiler URLs for visualization.

**Query Parameters**:
- `include_titiler` (optional, default: true): Include TiTiler URLs

**Response** (200 OK):
```json
{
  "item_id": "magallanes-region-flood",
  "collection_id": "flood-hazard-2024",
  "assets": {
    "data": {
      "href": "https://rmhazuregeocogs.blob.core.windows.net/silver-cogs/flood.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "size_mb": 125.5
    }
  },
  "titiler": {
    "preview": "https://titiler.example.com/cog/preview?url=https%3A%2F%2Frmhazuregeocogs...",
    "info": "https://titiler.example.com/cog/info?url=...",
    "tiles": "https://titiler.example.com/cog/tiles/{z}/{x}/{y}?url=...",
    "wmts": "https://titiler.example.com/cog/WMTSCapabilities.xml?url=..."
  },
  "bbox": [-75.5, -56.5, -66.5, -49.0],
  "temporal_extent": {
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-01-15T00:00:00Z"
  }
}
```

---

## 4. Implementation Details

### 4.1 File Structure

```
triggers/
  trigger_platform_catalog.py     # New file - HTTP handlers

services/
  platform_catalog_service.py     # New file - Business logic

infrastructure/
  pgstac_repository.py            # Add: search_by_platform_ids()
```

### 4.2 Implementation Steps

#### Step 1: Add pgSTAC Query Method

Add to `infrastructure/pgstac_repository.py`:

```python
def search_by_platform_ids(
    self,
    dataset_id: str,
    resource_id: str,
    version_id: str
) -> Optional[Dict[str, Any]]:
    """
    Search for STAC item by DDH platform identifiers.

    Uses the platform:* properties stored in STAC item properties.

    Returns:
        STAC item dict if found, None otherwise
    """
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT content
                FROM pgstac.items
                WHERE content->'properties'->>'platform:dataset_id' = %s
                  AND content->'properties'->>'platform:resource_id' = %s
                  AND content->'properties'->>'platform:version_id' = %s
                LIMIT 1
            """, (dataset_id, resource_id, version_id))
            result = cur.fetchone()
            return result['content'] if result else None
```

#### Step 2: Create Catalog Service

Create `services/platform_catalog_service.py`:

```python
"""
Platform Catalog Service - B2B STAC Access.

Provides DDH-identifier-based STAC lookup and asset URL generation.
"""

from typing import Dict, Any, Optional
from urllib.parse import quote_plus

from infrastructure import PlatformRepository, JobRepository
from infrastructure.pgstac_repository import PgStacRepository
from config import get_config


class PlatformCatalogService:
    """Service for B2B STAC catalog access."""

    def __init__(self):
        self._platform_repo = PlatformRepository()
        self._job_repo = JobRepository()
        self._stac_repo = PgStacRepository()
        self._config = get_config()

    def lookup_by_ddh_ids(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Dict[str, Any]:
        """
        Lookup STAC item by DDH identifiers.

        Strategy:
        1. Generate request_id from DDH IDs
        2. Lookup api_request → job_id
        3. Get job result → stac IDs
        4. Verify STAC item exists
        """
        from config import generate_platform_request_id

        request_id = generate_platform_request_id(
            dataset_id, resource_id, version_id
        )

        # Lookup via Platform thin tracking
        api_request = self._platform_repo.get_request(request_id)
        if not api_request:
            return {"found": False, "reason": "No Platform request found"}

        # Get job result
        job = self._job_repo.get_job(api_request.job_id)
        if not job or job.status != "completed":
            return {
                "found": False,
                "reason": "Job not completed",
                "job_status": job.status if job else "not_found"
            }

        result_data = job.result_data or {}
        collection_id = result_data.get("collection_id")
        item_id = result_data.get("stac_item_id")

        if not collection_id or not item_id:
            return {"found": False, "reason": "STAC IDs not in job result"}

        # Verify STAC item exists
        item = self._stac_repo.get_item(item_id, collection_id)
        if not item:
            return {"found": False, "reason": "STAC item not found in catalog"}

        return {
            "found": True,
            "stac": {
                "collection_id": collection_id,
                "item_id": item_id
            },
            "processing": {
                "request_id": request_id,
                "job_id": api_request.job_id,
                "completed_at": job.updated_at.isoformat() if job.updated_at else None
            }
        }

    def get_asset_urls(
        self,
        collection_id: str,
        item_id: str,
        include_titiler: bool = True
    ) -> Dict[str, Any]:
        """Get asset URLs with optional TiTiler URLs."""
        item = self._stac_repo.get_item(item_id, collection_id)
        if not item:
            return {"error": "Item not found"}

        assets = item.get("assets", {})
        result = {
            "item_id": item_id,
            "collection_id": collection_id,
            "assets": {},
            "bbox": item.get("bbox")
        }

        # Process assets
        for asset_key, asset in assets.items():
            result["assets"][asset_key] = {
                "href": asset.get("href"),
                "type": asset.get("type")
            }

        # Generate TiTiler URLs
        if include_titiler and "data" in assets:
            cog_url = assets["data"].get("href")
            if cog_url:
                titiler_base = self._config.titiler_base_url
                encoded_url = quote_plus(cog_url)
                result["titiler"] = {
                    "preview": f"{titiler_base}/cog/preview?url={encoded_url}",
                    "info": f"{titiler_base}/cog/info?url={encoded_url}",
                    "tiles": f"{titiler_base}/cog/tiles/{{z}}/{{x}}/{{y}}?url={encoded_url}",
                    "wmts": f"{titiler_base}/cog/WMTSCapabilities.xml?url={encoded_url}"
                }

        return result
```

#### Step 3: Create HTTP Trigger

Create `triggers/trigger_platform_catalog.py`:

```python
"""
Platform Catalog HTTP Triggers - B2B STAC Access.

Provides DDH-facing endpoints for STAC catalog verification and asset URLs.
"""

import json
import azure.functions as func
from services.platform_catalog_service import PlatformCatalogService


async def platform_catalog_lookup(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/platform/catalog/lookup"""
    dataset_id = req.params.get('dataset_id')
    resource_id = req.params.get('resource_id')
    version_id = req.params.get('version_id')

    if not all([dataset_id, resource_id, version_id]):
        return func.HttpResponse(
            json.dumps({"error": "Missing required parameters"}),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

    service = PlatformCatalogService()
    result = service.lookup_by_ddh_ids(dataset_id, resource_id, version_id)
    result["ddh_refs"] = {
        "dataset_id": dataset_id,
        "resource_id": resource_id,
        "version_id": version_id
    }

    return func.HttpResponse(
        json.dumps(result, indent=2, default=str),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )


async def platform_catalog_item(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/platform/catalog/item/{collection_id}/{item_id}"""
    collection_id = req.route_params.get('collection_id')
    item_id = req.route_params.get('item_id')

    from infrastructure.pgstac_repository import PgStacRepository
    repo = PgStacRepository()

    item = repo.get_item(item_id, collection_id)
    if not item:
        return func.HttpResponse(
            json.dumps({"error": "Item not found"}),
            status_code=404,
            headers={"Content-Type": "application/json"}
        )

    return func.HttpResponse(
        json.dumps(item, indent=2, default=str),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )


async def platform_catalog_assets(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/platform/catalog/assets/{collection_id}/{item_id}"""
    collection_id = req.route_params.get('collection_id')
    item_id = req.route_params.get('item_id')
    include_titiler = req.params.get('include_titiler', 'true').lower() == 'true'

    service = PlatformCatalogService()
    result = service.get_asset_urls(collection_id, item_id, include_titiler)

    if "error" in result:
        return func.HttpResponse(
            json.dumps(result),
            status_code=404,
            headers={"Content-Type": "application/json"}
        )

    return func.HttpResponse(
        json.dumps(result, indent=2, default=str),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )
```

#### Step 4: Register Routes

Add to `function_app.py`:

```python
from triggers.trigger_platform_catalog import (
    platform_catalog_lookup,
    platform_catalog_item,
    platform_catalog_assets
)

app.register_functions(platform_catalog_lookup)  # GET /api/platform/catalog/lookup
app.register_functions(platform_catalog_item)    # GET /api/platform/catalog/item/{collection_id}/{item_id}
app.register_functions(platform_catalog_assets)  # GET /api/platform/catalog/assets/{collection_id}/{item_id}
```

---

## 5. Security Considerations

### Access Control
- All catalog endpoints under `/api/platform/` prefix
- Gateway can apply DDH-specific authentication
- No PII or secrets exposed in responses

### Data Exposure
- Only expose STAC items that have `platform:*` properties (DDH-submitted)
- TiTiler URLs are public (COGs in silver tier are public read)
- No internal paths or error details exposed

---

## 6. Testing Plan

### Unit Tests
- `test_platform_catalog_service.py`
  - Lookup by valid DDH IDs → returns STAC info
  - Lookup by invalid DDH IDs → returns not found
  - Get assets with TiTiler URLs
  - Get assets without TiTiler URLs

### Integration Tests
```bash
# Submit raster through Platform (unified endpoint)
curl -X POST /api/platform/submit -d '{"dataset_id": "...", "file_name": "image.tif", ...}'
# Wait for completion
curl /api/platform/status/{request_id}
# Lookup via catalog
curl "/api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z"
# Get full item
curl /api/platform/catalog/item/{collection_id}/{item_id}
# Get assets with TiTiler URLs
curl /api/platform/catalog/assets/{collection_id}/{item_id}
```

---

## 7. OpenAPI Spec Updates

The OpenAPI spec has already been updated with these endpoints (see `openapi/platform-api-v1.json`). Key additions:

- Tag: `Catalog`
- Endpoints: lookup, item, assets
- Response schemas with examples

---

## 8. Implementation Checklist

- [x] Add `search_by_platform_ids()` to `infrastructure/pgstac_repository.py` ✅ 16 JAN 2026
- [x] Create `services/platform_catalog_service.py` ✅ 16 JAN 2026
- [x] Create `triggers/trigger_platform_catalog.py` ✅ 16 JAN 2026
- [x] Register routes in `function_app.py` ✅ 16 JAN 2026
- [ ] Add unit tests
- [ ] Add integration tests
- [x] Update version to 0.7.14.6 ✅ 16 JAN 2026
- [ ] Deploy and validate

### Implementation Notes (16 JAN 2026)

**Files Created/Modified:**

1. `infrastructure/pgstac_repository.py` - Added:
   - `search_by_platform_ids()` - Direct STAC lookup using JSONB @> operator
   - `get_items_by_platform_dataset()` - List items by dataset_id

2. `services/platform_catalog_service.py` - New file with:
   - `PlatformCatalogService` class
   - `lookup_by_ddh_ids()` - Primary lookup via Platform thin-tracking
   - `lookup_direct()` - Direct pgstac query (bypass Platform)
   - `get_asset_urls()` - Asset URLs with TiTiler generation
   - `list_items_for_dataset()` - List all items for a dataset_id
   - `get_platform_catalog_service()` - Singleton factory

3. `triggers/trigger_platform_catalog.py` - New file with HTTP handlers:
   - `platform_catalog_lookup` - GET /api/platform/catalog/lookup
   - `platform_catalog_item` - GET /api/platform/catalog/item/{collection}/{item}
   - `platform_catalog_assets` - GET /api/platform/catalog/assets/{collection}/{item}
   - `platform_catalog_dataset` - GET /api/platform/catalog/dataset/{dataset_id}

4. `function_app.py` - Added 4 new routes under `/api/platform/catalog/`

**Additional Endpoint (Bonus):**
Added `/api/platform/catalog/dataset/{dataset_id}` endpoint that wasn't in the original plan.
This allows DDH to list all STAC items for a given dataset_id.

---

## 9. Dependencies

- Existing: `PlatformRepository`, `JobRepository`, `PgStacRepository`
- Config: `titiler_base_url` (already exists)
- No new Azure resources required

---

## 10. Rollout Plan

1. **Dev**: Implement and test locally
2. **Staging**: Deploy to staging Function App
3. **DDH Integration**: Coordinate with DDH team for testing
4. **Production**: Deploy after DDH validation

---

## Appendix: Alternative Approaches Considered

### A. Direct pgSTAC Query Only
Query pgstac.items directly by `platform:*` properties without going through api_requests.

**Pros**: Simpler, single database query
**Cons**: Requires JSONB index on pgstac.items, less reliable than relational lookup

### B. Add Catalog ID to api_requests
Store `collection_id` and `item_id` directly in api_requests table.

**Pros**: Fastest lookup
**Cons**: Redundant storage, requires schema migration

### C. Use dataset_refs Table
Lookup via app.dataset_refs which already stores DDH→internal mapping.

**Pros**: Already indexed
**Cons**: Doesn't include STAC IDs directly, requires join

**Decision**: Use api_requests → job → result_data path (Option B behavior without schema change).
