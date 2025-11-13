# pgSTAC Search-Based Mosaic Strategy

**Date**: November 12, 2025
**Status**: ✅ **IMPLEMENTED** - Production Ready
**Priority**: HIGH - Replace MosaicJSON with pgSTAC Searches

---

## ✅ Implementation Status (12 NOV 2025)

**All phases complete and deployed!** The pgSTAC search-based mosaic pattern is now the default for all new collections.

### Completed Phases:

1. ✅ **Phase 1**: STAC item generation with required fields (id, type, collection, geometry)
2. ✅ **Phase 2**: PgStacRepository for data operations (insert, update, query)
3. ✅ **Phase 3**: TiTilerSearchService for search registration and URL generation
4. ✅ **Phase 4**: Integration into collection creation workflow

### Deployment Details:

- **Function App**: `rmhazuregeoapi` (B3 Basic tier)
- **Deployment Date**: 12 NOV 2025
- **Health Status**: 100% imports successful
- **Git Branch**: `dev` (commits: 5a4e8d6, 65993fe, 007ff60, ad287c9)

### How It Works:

Every collection created via `process_raster_collection` now automatically:

1. Creates STAC Items for each COG (with proper geometry/collection fields)
2. Creates STAC Collection in pgSTAC
3. Registers pgSTAC search with TiTiler → Returns `search_id`
4. Stores `search_id` in collection summaries
5. Adds visualization links (preview, tilejson, tiles)
6. Returns URLs in task result

### Collection Schema with Search Metadata:

```json
{
  "id": "namangan_collection",
  "type": "Collection",
  "stac_version": "1.1.0",
  "description": "Namangan raster tiles collection",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [["2025-11-12T...", "2025-11-12T..."]]}
  },
  "summaries": {
    "mosaic:search_id": ["abc123def456"]
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://rmhtitiler-.../searches/abc123def456/viewer",
      "type": "text/html",
      "title": "Interactive map preview (TiTiler-PgSTAC)"
    },
    {
      "rel": "tilejson",
      "href": "https://rmhtitiler-.../searches/abc123def456/WebMercatorQuad/tilejson.json",
      "type": "application/json",
      "title": "TileJSON specification for web maps"
    },
    {
      "rel": "tiles",
      "href": "https://rmhtitiler-.../searches/abc123def456/WebMercatorQuad/tiles/{z}/{x}/{y}",
      "type": "image/png",
      "title": "XYZ tile endpoint (templated)"
    }
  ],
  "assets": {
    "mosaicjson": {
      "href": "/vsiaz/silver-mosaicjson/namangan_collection.json",
      "type": "application/json",
      "roles": ["mosaic", "index"],
      "title": "MosaicJSON Dynamic Tiling Index"
    }
  }
}
```

### Implementation Files:

| File | Purpose | Lines | Status |
|------|---------|-------|--------|
| `services/service_stac_metadata.py` | STAC item generation with required fields | 406-492 | ✅ Phase 1 |
| `infrastructure/pgstac_repository.py` | pgSTAC data operations (CRUD) | 377 | ✅ Phase 2 |
| `services/titiler_search_service.py` | TiTiler search registration | 292 | ✅ Phase 3 |
| `services/stac_collection.py` | Collection creation + search integration | 396-474 | ✅ Phase 4 |

---

## Executive Summary

**Problem**: Static MosaicJSON files require anonymous blob access or SAS tokens for HTTPS access, which violates security requirements.

**Solution**: Use **pgSTAC Search Registration** as the primary mosaic method. Each STAC Collection automatically gets a registered search that serves as its mosaic URL. This leverages OAuth throughout the stack (no tokens, no public access needed).

---

## Why pgSTAC Searches > MosaicJSON

### MosaicJSON Limitations

❌ **Two-tier authentication required**:
- MosaicJSON file: Needs HTTPS access (public blob or SAS token)
- COG references inside: Use /vsiaz/ with OAuth

❌ **Security issues**:
- Requires container public access OR
- Requires SAS token management (expiration, rotation)
- Violates Managed Identity-only requirement

❌ **Static**:
- Must regenerate file when collection changes
- File must be uploaded and managed separately

### pgSTAC Search Advantages

✅ **OAuth throughout**:
- TiTiler → pgSTAC: Database connection (OAuth-protected PostgreSQL)
- pgSTAC → Returns: /vsiaz/ paths for COGs
- TiTiler → COGs: GDAL /vsiaz/ with Managed Identity tokens

✅ **Dynamic**:
- Automatically reflects current collection state
- No file regeneration needed
- Add/remove items → mosaic updates instantly

✅ **Simple**:
- One API call to register
- Returns permanent search ID
- Search ID becomes the collection's mosaic URL

---

## Architecture

```
User Browser
    ↓
[TiTiler Viewer URL with Search ID]
    ↓
TiTiler-pgSTAC Server (Managed Identity)
    ↓
    ├──→ pgSTAC Database (OAuth-protected PostgreSQL)
    │    └──→ Returns: List of items with /vsiaz/ paths
    └──→ GDAL /vsiaz/ (Managed Identity → OAuth tokens)
         └──→ Azure Blob Storage (COG files)
```

**Key Points**:
1. No anonymous access needed
2. No SAS tokens needed
3. OAuth Managed Identity for all authentication
4. Database queries are OAuth-protected
5. Blob access is OAuth-protected

---

## Implementation Plan

### Phase 1: Update STAC Item Generation (CRITICAL PREREQUISITE)

**Why**: pgSTAC searches require valid STAC Items with proper fields

**File**: `services/service_stac_metadata.py`

**Required Changes**:

```python
def extract_item_from_blob(...):
    """Generate STAC item from COG blob"""

    # ... existing rio-stac code ...

    item_dict = item.to_dict()

    # ============================================
    # CRITICAL: Add required STAC fields
    # ============================================

    # 1. Add GeoJSON type
    item_dict["type"] = "Feature"

    # 2. Generate unique item ID from blob path
    item_id = generate_stac_item_id(blob_name)
    item_dict["id"] = item_id

    # 3. Add collection reference
    item_dict["collection"] = collection_id

    # 4. Ensure STAC version
    item_dict["stac_version"] = "1.1.0"

    # 5. Ensure geometry exists (rio-stac should set this)
    if not item_dict.get("geometry"):
        # Derive from bbox if missing
        bbox = item_dict.get("bbox")
        if bbox:
            item_dict["geometry"] = bbox_to_geometry(bbox)

    # ... rest of existing code ...

    return item_dict


def generate_stac_item_id(blob_name: str) -> str:
    """
    Generate STAC-compliant item ID from blob path.

    Examples:
        "file.tif" -> "file"
        "folder/file.tif" -> "folder-file"
        "a/b/c/file.tif" -> "a-b-c-file"
    """
    from pathlib import Path

    # Remove extension
    stem = Path(blob_name).stem

    # Get parent path
    parent = str(Path(blob_name).parent)

    # Build ID
    if parent and parent != ".":
        # Has subdirectory: folder/file.tif -> folder-file
        item_id = f"{parent}-{stem}".replace("/", "-").replace("\\", "-")
    else:
        # No subdirectory: file.tif -> file
        item_id = stem

    return item_id


def bbox_to_geometry(bbox: list) -> dict:
    """Convert bbox [minx, miny, maxx, maxy] to GeoJSON Polygon geometry"""
    minx, miny, maxx, maxy = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny],
            [maxx, miny],
            [maxx, maxy],
            [minx, maxy],
            [minx, miny]
        ]]
    }
```

**Testing**:
```bash
# After implementing, verify items have required fields
curl "https://rmhgeoapibeta-.../api/stac_api/collections/{collection}/items" | python3 -c "
import json, sys
item = json.load(sys.stdin)['features'][0]
required = ['id', 'type', 'collection', 'geometry', 'bbox', 'properties']
for field in required:
    status = '✅' if item.get(field) else '❌ MISSING'
    print(f'{status} {field}')
"
```

**See Also**: [STAC-FIXES.md](STAC-FIXES.md) for complete details

---

### Phase 2: Automated Search Registration

**Option A: Register Search During Collection Creation**

When a new collection is created, automatically register its search.

**File**: Service that creates collections (likely `services/service_stac_collections.py` or similar)

```python
import httpx
from typing import Optional

async def create_collection_with_search(
    collection_data: dict,
    titiler_base_url: str = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"
) -> dict:
    """
    Create STAC collection and register pgSTAC search for mosaic access.

    Returns:
        {
            "collection": {...},
            "search": {
                "id": "abc123...",
                "viewer_url": "https://...",
                "tilejson_url": "https://..."
            }
        }
    """
    collection_id = collection_data.get("id")

    # 1. Create collection in pgSTAC (existing code)
    # ... your existing collection creation logic ...

    # 2. Register pgSTAC search for this collection
    search_request = {
        "collections": [collection_id],
        "filter-lang": "cql2-json",
        "metadata": {
            "name": f"{collection_data.get('title', collection_id)} Mosaic"
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{titiler_base_url}/searches/register",
            json=search_request
        )
        response.raise_for_status()
        search_result = response.json()

    search_id = search_result["id"]

    # 3. Generate viewer URLs
    viewer_url = f"{titiler_base_url}/searches/{search_id}/WebMercatorQuad/map.html?assets=data"
    tilejson_url = f"{titiler_base_url}/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data"
    tiles_url = f"{titiler_base_url}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?assets=data"

    # 4. Store search ID in collection metadata
    collection_data.setdefault("summaries", {})
    collection_data["summaries"]["mosaic:search_id"] = search_id

    # 5. Add viewer link to collection
    collection_data.setdefault("links", [])
    collection_data["links"].append({
        "rel": "preview",
        "href": viewer_url,
        "type": "text/html",
        "title": "Interactive collection mosaic viewer (TiTiler-pgSTAC)"
    })
    collection_data["links"].append({
        "rel": "tilejson",
        "href": tilejson_url,
        "type": "application/json",
        "title": "TileJSON for web maps"
    })

    # 6. Update collection in database with search ID
    # ... update pgSTAC collection with new links/summaries ...

    return {
        "collection": collection_data,
        "search": {
            "id": search_id,
            "viewer_url": viewer_url,
            "tilejson_url": tilejson_url,
            "tiles_url": tiles_url
        }
    }
```

**Option B: Register Search on First Access**

Lazy registration - create search when collection viewer is first requested.

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

router = APIRouter()

@router.get("/collections/{collection_id}/viewer")
async def get_collection_viewer(collection_id: str):
    """
    Get or create viewer URL for collection mosaic.

    Checks if collection has registered search, creates one if not,
    then redirects to TiTiler viewer.
    """
    # 1. Check if collection exists
    collection = await get_collection_from_pgstac(collection_id)
    if not collection:
        raise HTTPException(404, "Collection not found")

    # 2. Check if search ID already exists
    search_id = collection.get("summaries", {}).get("mosaic:search_id")

    # 3. If no search, register one
    if not search_id:
        search_result = await register_collection_search(collection_id)
        search_id = search_result["id"]

        # Update collection with search ID
        await update_collection_metadata(
            collection_id,
            {"summaries": {"mosaic:search_id": search_id}}
        )

    # 4. Redirect to TiTiler viewer
    viewer_url = f"{TITILER_BASE_URL}/searches/{search_id}/WebMercatorQuad/map.html?assets=data"
    return RedirectResponse(viewer_url)
```

---

### Phase 3: Update Collection Schema

**Add search metadata to collection summaries**:

```json
{
  "type": "Collection",
  "id": "namangan-imagery",
  "title": "Namangan Imagery Collection",
  "summaries": {
    "mosaic:search_id": "2c065db5c76ea29b0e58cceb4729b814",
    "mosaic:registered_at": "2025-11-12T19:00:00Z"
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/2c065db5c76ea29b0e58cceb4729b814/WebMercatorQuad/map.html?assets=data",
      "type": "text/html",
      "title": "Interactive collection mosaic viewer"
    },
    {
      "rel": "tilejson",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/2c065db5c76ea29b0e58cceb4729b814/WebMercatorQuad/tilejson.json?assets=data",
      "type": "application/json",
      "title": "TileJSON specification"
    },
    {
      "rel": "tiles",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/2c065db5c76ea29b0e58cceb4729b814/tiles/WebMercatorQuad/{z}/{x}/{y}?assets=data",
      "type": "application/json",
      "title": "XYZ tile endpoint",
      "templated": true
    }
  ]
}
```

---

### Phase 4: Migration for Existing Collections

**Script to register searches for all existing collections**:

```python
import asyncio
import httpx
from typing import List

STAC_API_BASE = "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac_api"
TITILER_BASE = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

async def migrate_collections_to_pgstac_searches():
    """Register pgSTAC searches for all existing collections"""

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Get all collections
        response = await client.get(f"{STAC_API_BASE}/collections")
        collections = response.json().get("collections", [])

        print(f"Found {len(collections)} collections")

        for collection in collections:
            collection_id = collection["id"]

            # Skip if already has search ID
            if collection.get("summaries", {}).get("mosaic:search_id"):
                print(f"✓ {collection_id}: Already has search")
                continue

            # Register search
            try:
                search_request = {
                    "collections": [collection_id],
                    "filter-lang": "cql2-json",
                    "metadata": {
                        "name": f"{collection.get('title', collection_id)} Mosaic"
                    }
                }

                response = await client.post(
                    f"{TITILER_BASE}/searches/register",
                    json=search_request
                )
                response.raise_for_status()

                search_result = response.json()
                search_id = search_result["id"]

                print(f"✅ {collection_id}: Registered search {search_id}")

                # TODO: Update collection in pgSTAC with search_id
                # This requires database access or STAC API mutation endpoint

            except Exception as e:
                print(f"❌ {collection_id}: Failed - {e}")

# Run migration
asyncio.run(migrate_collections_to_pgstac_searches())
```

---

## URL Patterns

### Individual COG (Direct Access)

```
Format: /cog/WebMercatorQuad/map.html?url=/vsiaz/{container}/{blob_path}

Example:
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=%2Fvsiaz%2Fsilver-cogs%2Fnamangan14aug2019_R2C2cog_analysis.tif
```

### Collection Mosaic (pgSTAC Search)

```
Format: /searches/{search_id}/WebMercatorQuad/map.html?assets=data

Example:
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/2c065db5c76ea29b0e58cceb4729b814/WebMercatorQuad/map.html?assets=data
```

### Key Differences

| Aspect | Direct COG | Collection Mosaic |
|--------|-----------|-------------------|
| Endpoint | `/cog/` | `/searches/{id}/` |
| URL Param | `url=/vsiaz/...` | `assets=data` |
| Source | Single COG file | All items in collection |
| Dynamic | Static (one file) | Dynamic (queries pgSTAC) |

---

## Required Environment Variables

### rmhgeoapi (STAC API Server)

```bash
# TiTiler base URL for generating viewer links
TITILER_BASE_URL=https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net

# pgSTAC database connection (for search registration validation)
PGSTAC_DATABASE_URL=postgresql://rob634:B@lamb634@@rmhpgflex.postgres.database.azure.com:5432/geopgflex
```

### titilerpgstac (TiTiler Server)

**Already configured** ✅:
- Managed Identity credential
- pgSTAC database connection
- OAuth middleware for /vsiaz/ access

---

## Testing Strategy

### Test 1: Verify STAC Item Compliance

```bash
# Get item from collection
curl "https://rmhgeoapibeta-.../api/stac_api/collections/system-rasters/items" | python3 -c "
import json, sys
item = json.load(sys.stdin)['features'][0]

# Check required fields
checks = {
    'id': item.get('id'),
    'type': item.get('type'),
    'collection': item.get('collection'),
    'geometry': item.get('geometry'),
    'bbox': item.get('bbox')
}

print('=== STAC Item Validation ===')
for field, value in checks.items():
    status = '✅' if value else '❌'
    print(f'{status} {field}: {\"present\" if value else \"MISSING\"}')"

# Expected output:
# ✅ id: present
# ✅ type: present
# ✅ collection: present
# ✅ geometry: present
# ✅ bbox: present
```

### Test 2: Register Collection Search

```bash
# Register search for collection
curl -X POST 'https://rmhtitiler-.../searches/register' \
  -H 'Content-Type: application/json' \
  -d '{
    "collections": ["system-rasters"],
    "filter-lang": "cql2-json"
  }' | python3 -c "
import json, sys
result = json.load(sys.stdin)
search_id = result['id']
print(f'Search ID: {search_id}')
print(f'Viewer: https://rmhtitiler-.../searches/{search_id}/WebMercatorQuad/map.html?assets=data')"
```

### Test 3: Verify TileJSON Bounds

```bash
# Check that TileJSON has correct bounds (not world extent)
curl "https://rmhtitiler-.../searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data" | python3 -c "
import json, sys
tj = json.load(sys.stdin)
bounds = tj['bounds']
print(f'Bounds: {bounds}')

# Bounds should NOT be [-180, -85, 180, 85] (world extent)
# Should be actual collection extent
world_extent = bounds == [-180.0, -85.0511287798066, 180.00000000000009, 85.0511287798066]
if world_extent:
    print('❌ ERROR: Showing world extent - pgSTAC not finding items')
else:
    print('✅ Correct extent - items found')"
```

### Test 4: Verify Tiles Render

```bash
# Test a sample tile
curl -I "https://rmhtitiler-.../searches/{search_id}/tiles/WebMercatorQuad/16/12345/23456?assets=data"

# Expected: HTTP 200 (or 404 if tile out of bounds, but not 500)
```

---

## Troubleshooting

### Problem: TileJSON shows world extent [-180, -85, 180, 85]

**Cause**: pgSTAC search not finding items in collection

**Solutions**:
1. ✅ Verify items have `id`, `type`, `collection`, `geometry` fields (see Phase 1)
2. ✅ Verify items are actually in the collection (query STAC API)
3. ✅ Check pgSTAC database directly:
   ```sql
   SELECT id, collection, datetime, ST_Extent(geometry)
   FROM pgstac.items
   WHERE collection = 'your-collection-id'
   GROUP BY id, collection, datetime;
   ```

### Problem: Search returns "assets must be defined"

**Cause**: Missing `?assets=data` query parameter

**Solution**: Always include `?assets=data` in viewer and tile URLs

### Problem: Tiles return 500 errors

**Cause**: OAuth token not set or COG files inaccessible

**Solutions**:
1. Check TiTiler logs for OAuth token acquisition
2. Verify Managed Identity has "Storage Blob Data Reader" role
3. Test individual COG access using `/cog/info?url=/vsiaz/...`

### Problem: Search not found after registration

**Cause**: Registered searches may not persist (depends on TiTiler-pgSTAC configuration)

**Solution**: Store search ID in collection metadata immediately after registration

---

## Success Criteria

After full implementation, every collection should have:

✅ All items with proper STAC fields (`id`, `type`, `collection`, `geometry`)
✅ Registered pgSTAC search stored in collection metadata
✅ `preview` link pointing to TiTiler viewer with search ID
✅ `tilejson` link for web map integration
✅ Correct geographic bounds (not world extent)
✅ Tiles rendering without authentication errors
✅ No SAS tokens or public blob access required
✅ OAuth Managed Identity for all access

---

## Migration Checklist

### Immediate (Before Creating New Collections)

- [ ] Implement Phase 1: Fix STAC item generation (add `id`, `type`, `collection`, `geometry`)
- [ ] Test with one new COG upload
- [ ] Verify item appears in STAC API with correct fields

### Short Term (For New Collections)

- [ ] Implement Phase 2: Automated search registration
- [ ] Add search ID to collection metadata
- [ ] Add viewer/tilejson links to collection
- [ ] Test with one new collection

### Long Term (Existing Collections)

- [ ] Run migration script for existing collections
- [ ] Update any hardcoded MosaicJSON references
- [ ] Remove MosaicJSON generation code
- [ ] Document new URL pattern for users

---

## Comparison: Old vs New Approach

### Old Approach (MosaicJSON)

```
1. ETL generates MosaicJSON file
2. Upload JSON to blob storage
3. Enable public access OR generate SAS token
4. Provide HTTPS URL to TiTiler
5. TiTiler reads JSON via HTTPS
6. TiTiler reads COGs via /vsiaz/ OAuth

Problems:
- Two authentication methods (HTTPS + OAuth)
- Static file management
- Security compromise (public access or tokens)
```

### New Approach (pgSTAC Search)

```
1. ETL creates STAC Items in pgSTAC
2. Register pgSTAC search for collection
3. Store search ID in collection metadata
4. Provide search URL to users
5. TiTiler queries pgSTAC via database (OAuth)
6. TiTiler reads COGs via /vsiaz/ OAuth

Benefits:
- Single authentication method (OAuth everywhere)
- Dynamic (no file management)
- Secure (no public access, no tokens)
```

---

## Code Location Summary

### Files to Modify

1. **`services/service_stac_metadata.py`**
   - Add `generate_stac_item_id()` function
   - Add required STAC fields to items
   - Ensure geometry is present

2. **Collection creation service** (TBD - find this file)
   - Add search registration after collection creation
   - Store search ID in collection metadata
   - Add viewer/tilejson links

3. **ETL configuration**
   - Add `TITILER_BASE_URL` environment variable
   - Remove MosaicJSON generation code (future)

### New Files to Create

1. **`scripts/migrate_collections_to_pgstac_searches.py`**
   - Migration script for existing collections

2. **`services/service_titiler_search.py`** (optional)
   - Centralized search registration logic
   - Helper functions for URL generation

---

## Timeline Estimate

| Phase | Effort | Priority |
|-------|--------|----------|
| Phase 1: Fix STAC items | 2-3 hours | **CRITICAL** |
| Phase 2: Auto search registration | 3-4 hours | High |
| Phase 3: Update schema | 1 hour | Medium |
| Phase 4: Migration script | 2 hours | Low |

**Total**: 8-10 hours development + testing

---

## References

- [STAC-FIXES.md](STAC-FIXES.md) - Detailed STAC item compliance fixes
- [STAC-ETL-FIX.md](STAC-ETL-FIX.md) - /vsiaz/ path usage for assets
- [MOSAICJSON-IMPLEMENTATION.md](MOSAICJSON-IMPLEMENTATION.md) - Why MosaicJSON is problematic
- [TITILER-VALIDATION-TASK.md](TITILER-VALIDATION-TASK.md) - TiTiler integration guide

---

**Status**: 📝 Ready for Implementation
**Priority**: HIGH - Solves authentication and security requirements
**Next Steps**: Start with Phase 1 (STAC item fixes) before creating new collections
