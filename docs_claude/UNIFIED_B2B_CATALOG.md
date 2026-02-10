# Unified B2B Catalog Implementation Plan

**Created**: 10 FEB 2026
**Status**: PLANNING
**Epic**: Platform API B2B Integration
**Priority**: High

---

## Overview

Extend the Platform Catalog API (`/api/platform/catalog/*`) to support **both raster and vector** data by querying the unified source of truth (`app.geospatial_assets`) directly, bypassing STAC and OGC Features APIs.

### Problem Statement

Current `/api/platform/catalog/lookup` only works for rasters because:
1. It queries `pgstac.items` (STAC catalog)
2. Vectors skip STAC cataloging by default (V0.8 architecture change)
3. DDH has no way to look up vector data by their identifiers

### Solution

Query `app.geospatial_assets` directly - the unified source of truth for all Platform API submissions. JOIN to metadata tables for bbox/extent:
- Vectors: `geo.table_catalog`
- Rasters: `app.cog_metadata`

---

## Architecture

### Current (Raster-Only)

```
/api/platform/catalog/lookup
    │
    ▼
api_requests → job → result_data → pgstac.items
                                        │
                                        ▼
                                   STAC metadata
                                   (rasters only)
```

### Proposed (Unified)

```
/api/platform/catalog/lookup
    │
    ▼
app.geospatial_assets  ◄── Single source of truth
    │
    ├── LEFT JOIN geo.table_catalog (vectors)
    │       └── bbox, feature_count, geometry_type
    │
    └── LEFT JOIN app.cog_metadata (rasters)
            └── bbox, band_count, dtype, dimensions
```

---

## Database Schema Reference

### app.geospatial_assets (Primary)

| Column | Type | Purpose |
|--------|------|---------|
| `asset_id` | VARCHAR(64) | PK: SHA256(platform_id\|platform_refs) |
| `platform_id` | VARCHAR(50) | "ddh" |
| `platform_refs` | JSONB | `{"dataset_id": "X", "resource_id": "Y", "version_id": "Z"}` |
| `data_type` | VARCHAR | "vector" \| "raster" |
| `table_name` | VARCHAR(63) | PostGIS table (vectors) |
| `blob_path` | VARCHAR(500) | Azure Blob path (rasters) |
| `stac_item_id` | VARCHAR(200) | STAC item ID |
| `stac_collection_id` | VARCHAR(200) | STAC collection ID |
| `processing_status` | ENUM | pending \| processing \| completed \| failed |
| `approval_state` | ENUM | pending_review \| approved \| rejected \| revoked |
| `clearance_state` | ENUM | uncleared \| ouo \| public |

### geo.table_catalog (Vector Metadata)

| Column | Type | Purpose |
|--------|------|---------|
| `table_name` | VARCHAR(255) | PK: PostGIS table name |
| `bbox_minx/miny/maxx/maxy` | FLOAT | Bounding box |
| `feature_count` | INT | Number of features |
| `geometry_type` | VARCHAR(50) | Point, Polygon, etc. |
| `title` | VARCHAR(500) | Human-readable title |
| `description` | TEXT | Dataset description |

### app.cog_metadata (Raster Metadata)

| Column | Type | Purpose |
|--------|------|---------|
| `cog_id` | VARCHAR(255) | PK: COG identifier |
| `bbox_minx/miny/maxx/maxy` | FLOAT | Bounding box |
| `band_count` | INT | Number of bands |
| `dtype` | VARCHAR(20) | Data type (uint8, float32) |
| `width/height` | INT | Dimensions in pixels |
| `container` | VARCHAR(100) | Azure container |
| `blob_path` | VARCHAR(500) | Path within container |

---

## Implementation Phases

### Phase 1: Repository Method ⬜ (~1 hour)

**File**: `infrastructure/asset_repository.py`

Add method to query asset with metadata JOIN:

```python
def get_with_metadata(
    self,
    platform_id: str,
    platform_refs: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Get asset with joined metadata (bbox, etc.) based on data_type.

    Returns combined dict with asset fields + metadata fields.
    """
```

**SQL Query**:
```sql
SELECT
    a.*,
    -- Vector metadata
    tc.bbox_minx as v_bbox_minx, tc.bbox_miny as v_bbox_miny,
    tc.bbox_maxx as v_bbox_maxx, tc.bbox_maxy as v_bbox_maxy,
    tc.feature_count, tc.geometry_type,
    -- Raster metadata
    cm.bbox_minx as r_bbox_minx, cm.bbox_miny as r_bbox_miny,
    cm.bbox_maxx as r_bbox_maxx, cm.bbox_maxy as r_bbox_maxy,
    cm.band_count, cm.dtype, cm.width, cm.height
FROM app.geospatial_assets a
LEFT JOIN geo.table_catalog tc
    ON a.data_type = 'vector' AND a.table_name = tc.table_name
LEFT JOIN app.cog_metadata cm
    ON a.data_type = 'raster' AND a.stac_item_id = cm.cog_id
WHERE a.platform_id = %s
  AND a.platform_refs @> %s
  AND a.deleted_at IS NULL
```

**Checklist**:
- [ ] Add `get_with_metadata()` method
- [ ] Add `list_by_dataset_with_metadata()` for listing all assets in a dataset
- [ ] Unit test with mock data

---

### Phase 2: Service Layer ⬜ (~2 hours)

**File**: `services/platform_catalog_service.py`

Add unified lookup methods:

```python
def lookup_unified(
    self,
    dataset_id: str,
    resource_id: str,
    version_id: str
) -> Dict[str, Any]:
    """
    Unified lookup - works for both raster and vector.
    Queries GeospatialAsset directly, bypasses STAC/OGC APIs.
    """

def _build_vector_response(self, asset: Dict, metadata: Dict) -> Dict:
    """Build vector-specific response with TiPG URLs."""

def _build_raster_response(self, asset: Dict, metadata: Dict) -> Dict:
    """Build raster-specific response with TiTiler URLs."""

def get_unified_urls(self, asset_id: str) -> Dict[str, Any]:
    """Get service URLs by asset_id."""

def list_dataset_unified(self, dataset_id: str, limit: int = 100) -> Dict[str, Any]:
    """List all assets for a dataset with metadata."""
```

**Checklist**:
- [ ] Add `lookup_unified()` method
- [ ] Add `_build_vector_response()` helper
- [ ] Add `_build_raster_response()` helper
- [ ] Add `get_unified_urls()` method
- [ ] Add `list_dataset_unified()` method
- [ ] Preserve existing STAC-based methods for backward compatibility

---

### Phase 3: HTTP Triggers ⬜ (~1 hour)

**File**: `triggers/trigger_platform_catalog.py`

Update/add endpoints:

| Endpoint | Method | Change |
|----------|--------|--------|
| `/api/platform/catalog/lookup` | GET | **Update**: Use `lookup_unified()` |
| `/api/platform/catalog/item/{collection}/{item}` | GET | Keep (STAC access) |
| `/api/platform/catalog/assets/{collection}/{item}` | GET | Keep (STAC access) |
| `/api/platform/catalog/asset/{asset_id}` | GET | **NEW**: Get by asset_id |
| `/api/platform/catalog/dataset/{dataset_id}` | GET | **Update**: Use `list_dataset_unified()` |

**Checklist**:
- [ ] Update `platform_catalog_lookup()` to use unified method
- [ ] Add `platform_catalog_asset()` endpoint
- [ ] Update `platform_catalog_dataset()` to use unified method
- [ ] Register new routes in `triggers/platform/platform_bp.py`

---

### Phase 4: Response Format ⬜ (~30 min)

Define unified response format that works for both data types:

```json
{
  "found": true,
  "asset_id": "a7803a5e9160779290f54877fc65fbe0",
  "data_type": "vector",

  "status": {
    "processing": "completed",
    "approval": "approved",
    "clearance": "public"
  },

  "metadata": {
    "bbox": [-66.45, -56.32, -64.77, -54.68],
    "title": "Eleventh Hour Test Dataset",
    "created_at": "2026-02-09T19:48:34Z"
  },

  "vector": {
    "table_name": "eleventhhourtest_v8_testing_v10",
    "schema": "geo",
    "feature_count": 3301,
    "geometry_type": "MultiPolygon",
    "endpoints": {
      "features": "/api/features/collections/eleventhhourtest_v8_testing_v10/items",
      "collection": "/api/features/collections/eleventhhourtest_v8_testing_v10"
    },
    "tiles": {
      "mvt": "https://rmhtitiler.../vector/collections/geo.eleventhhourtest_v8_testing_v10/tiles/{z}/{x}/{y}.pbf",
      "tilejson": "https://rmhtitiler.../vector/collections/geo.eleventhhourtest_v8_testing_v10/tiles/WebMercatorQuad/tilejson.json",
      "viewer": "/api/interface/vector-tiles?collection=geo.eleventhhourtest_v8_testing_v10"
    }
  },

  "ddh_refs": {
    "dataset_id": "eleventhhourtest",
    "resource_id": "v8_testing",
    "version_id": "v1.0"
  },

  "timestamp": "2026-02-10T21:05:59Z"
}
```

For rasters, `"vector"` block is replaced with:

```json
"raster": {
  "blob_path": "silver-cogs/eighteenmegabytes/v8-testing/v1.0/cog.tif",
  "container": "silver-cogs",
  "band_count": 3,
  "dtype": "uint8",
  "dimensions": {"width": 10000, "height": 8000},
  "stac": {
    "collection_id": "eighteenmegabytes",
    "item_id": "eighteenmegabytes-v8-testing-v10"
  },
  "tiles": {
    "xyz": "https://rmhtitiler.../cog/tiles/{z}/{x}/{y}?url=...",
    "tilejson": "https://rmhtitiler.../cog/tilejson.json?url=...",
    "preview": "https://rmhtitiler.../cog/preview?url=...",
    "viewer": "/api/interface/raster-viewer?..."
  }
}
```

**Checklist**:
- [ ] Define response Pydantic model (optional but recommended)
- [ ] Document response format in API docs

---

### Phase 5: Testing ⬜ (~1 hour)

**Test Cases**:

1. **Vector Lookup**
   - [ ] Lookup by DDH identifiers returns vector metadata
   - [ ] Response includes TiPG vector tile URLs
   - [ ] Response includes bbox from geo.table_catalog

2. **Raster Lookup**
   - [ ] Lookup by DDH identifiers returns raster metadata
   - [ ] Response includes TiTiler URLs
   - [ ] Response includes bbox from app.cog_metadata

3. **Edge Cases**
   - [ ] Not found returns appropriate error
   - [ ] Processing not complete returns status
   - [ ] Rejected asset returns approval state

4. **Integration**
   - [ ] Test with real vector: `eleventhhourtest_v8_testing_v10`
   - [ ] Test with real raster: `eighteenmegabytes-v8-testing-v10`

---

### Phase 6: Documentation ⬜ (~30 min)

- [ ] Update API documentation
- [ ] Add examples to B2B integration guide
- [ ] Update HISTORY.md

---

## Estimated Effort

| Phase | Time | Status |
|-------|------|--------|
| Phase 1: Repository | ~1 hour | ⬜ |
| Phase 2: Service | ~2 hours | ⬜ |
| Phase 3: Triggers | ~1 hour | ⬜ |
| Phase 4: Response | ~30 min | ⬜ |
| Phase 5: Testing | ~1 hour | ⬜ |
| Phase 6: Documentation | ~30 min | ⬜ |
| **Total** | **~6 hours** | |

---

## Files to Modify

| File | Changes |
|------|---------|
| `infrastructure/asset_repository.py` | Add `get_with_metadata()`, `list_by_dataset_with_metadata()` |
| `services/platform_catalog_service.py` | Add unified lookup methods |
| `triggers/trigger_platform_catalog.py` | Update endpoints |
| `triggers/platform/platform_bp.py` | Register new routes |
| `docs_claude/B2B_ERROR_HANDLING_GUIDE.md` | Add unified catalog examples |

---

## Backward Compatibility

- **Existing endpoints preserved**: `/api/platform/catalog/item/*` and `/api/platform/catalog/assets/*` continue to work for STAC-based queries
- **Response format**: Unified format is a superset - adds `data_type` field and type-specific blocks
- **No breaking changes**: DDH clients using existing raster endpoints will continue to work

---

## Success Criteria

1. ✅ `/api/platform/catalog/lookup` works for both rasters AND vectors
2. ✅ Response includes bbox regardless of data_type
3. ✅ Response includes appropriate tile URLs (TiTiler for rasters, TiPG for vectors)
4. ✅ Single query path - no STAC/OGC API dependency
5. ✅ Backward compatible with existing B2B integrations

---

## Test Commands

```bash
# Vector lookup (currently fails, should work after implementation)
curl "https://rmhazuregeoapi.../api/platform/catalog/lookup?dataset_id=eleventhhourtest&resource_id=v8_testing&version_id=v1.0"

# Raster lookup (currently works)
curl "https://rmhazuregeoapi.../api/platform/catalog/lookup?dataset_id=eighteenmegabytes&resource_id=v8-testing&version_id=v1.0"

# Dataset listing
curl "https://rmhazuregeoapi.../api/platform/catalog/dataset/eleventhhourtest"
```

---

## Related Documents

- `docs_claude/V0.8_ENTITIES.md` - GeospatialAsset architecture
- `docs_claude/B2B_ERROR_HANDLING_GUIDE.md` - Error response format
- `core/models/asset.py` - GeospatialAsset model
- `core/models/geo.py` - GeoTableCatalog model
- `core/models/raster_metadata.py` - CogMetadataRecord model

---

*Document maintained by: Engineering Team*
*Last updated: 10 FEB 2026*
