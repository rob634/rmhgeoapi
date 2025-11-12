# STAC ETL Fix for TiTiler-pgSTAC OAuth Integration

**Issue**: STAC items created by the ETL process have HTTPS URLs instead of `/vsiaz/` paths, preventing TiTiler-pgSTAC from accessing them with OAuth authentication.

**Date**: November 9, 2025
**Status**: 🔧 Fix Required in rmhgeoapi ETL

---

## Problem

The current STAC cataloging ETL in `rmhgeoapi` creates asset `href` values as HTTPS URLs:

```json
{
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif?sv=2023-01-03&st=2025-11..."
    }
  }
}
```

**Why this doesn't work**:
- HTTPS URLs bypass GDAL's `/vsiaz/` handler
- OAuth tokens set via `AZURE_STORAGE_ACCESS_TOKEN` are ignored
- HTTP 404 errors occur because the URL tries to access blobs without authentication

**What TiTiler-pgSTAC needs**:
```json
{
  "assets": {
    "data": {
      "href": "/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif"
    }
  }
}
```

---

## Root Cause

### Location: `/Users/robertharrison/python_builds/rmhgeoapi/services/service_stac_metadata.py`

**Current Code** (around line 180-190):
```python
# STEP A: Generate SAS URL for rasterio access
blob_url = self.blob_repo.get_blob_url_with_sas(
    container_name=container,
    blob_name=blob_name,
    hours=1
)
```

**Current Code** (around line 440):
```python
asset = Asset(
    href=blob_url,  # <-- Uses HTTPS URL with SAS token
    type="image/tiff; application=geotiff; profile=cloud-optimized",
    title=title or "Cloud Optimized GeoTIFF",
    roles=roles or ["data"]
)
```

---

## Solution

### Option 1: Use `/vsiaz/` Paths for Asset href (Recommended)

Modify `service_stac_metadata.py` to generate `/vsiaz/` paths for the asset href while still using SAS URLs for rasterio metadata extraction:

```python
def extract_item_from_blob(...):
    # STEP A: Generate SAS URL for rasterio access (temporary, for metadata extraction only)
    sas_url = self.blob_repo.get_blob_url_with_sas(
        container_name=container,
        blob_name=blob_name,
        hours=1
    )

    # Use SAS URL to open raster and extract metadata
    with rasterio.open(sas_url) as src:
        # ... extract metadata ...

    # STEP B: Create /vsiaz/ path for permanent storage in STAC item
    vsiaz_href = f"/vsiaz/{container}/{blob_name}"

    # Create asset with /vsiaz/ path (works with OAuth in TiTiler-pgSTAC)
    data_asset = self.create_cog_asset(
        blob_url=vsiaz_href,  # <-- Use /vsiaz/ path instead of HTTPS URL
        title="Cloud Optimized GeoTIFF",
        roles=["data"]
    )
```

**Changes needed**:
1. Keep SAS URL generation for rasterio metadata extraction (temporary use)
2. Create separate `/vsiaz/` path for asset href (permanent storage)
3. Update `create_cog_asset()` parameter name from `blob_url` to `asset_href` for clarity

### Option 2: Dual Asset Approach

Store both HTTPS (with SAS) and `/vsiaz/` paths:

```python
assets = {
    "data": {
        "href": f"/vsiaz/{container}/{blob_name}",
        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "title": "Cloud Optimized GeoTIFF",
        "roles": ["data"]
    },
    "data-https": {
        "href": f"https://{storage_account}.blob.core.windows.net/{container}/{blob_name}",
        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "title": "Cloud Optimized GeoTIFF (HTTPS)",
        "roles": ["alternate"]
    }
}
```

**Pros**:
- Provides fallback to HTTPS access
- Compatible with clients that don't support /vsiaz/

**Cons**:
- More complex
- HTTPS URLs without authentication won't work for private blobs

---

## Implementation Steps

### 1. Update `service_stac_metadata.py`

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/service_stac_metadata.py`

**Change 1**: Update the extract method (around line 180-250)

```python
def extract_item_from_blob(self, container: str, blob_name: str, collection_id: str = "dev", item_id: str = None) -> Item:
    """
    Extract STAC Item from COG in Azure Blob Storage.

    Uses SAS URL for temporary rasterio access during metadata extraction,
    but stores /vsiaz/ path in asset href for OAuth-based access in TiTiler-pgSTAC.
    """
    logger.info(f"🔄 EXTRACTION START: {container}/{blob_name}")

    # STEP A: Generate SAS URL for rasterio access (temporary - for metadata extraction only)
    try:
        logger.debug("   Step A: Generating SAS URL for rasterio metadata extraction...")
        sas_url = self.blob_repo.get_blob_url_with_sas(
            container_name=container,
            blob_name=blob_name,
            hours=1  # Short-lived, only needed for metadata extraction
        )
        logger.debug(f"   ✅ Step A: SAS URL generated (temporary use only)")
    except Exception as e:
        logger.error(f"   ❌ Step A failed: {e}")
        raise

    # STEP B: Open raster with rasterio using SAS URL
    try:
        logger.debug("   Step B: Opening raster with rasterio...")
        with rasterio.open(sas_url) as src:
            # ... existing metadata extraction code ...

        logger.debug("   ✅ Step B: Metadata extracted")
    except Exception as e:
        logger.error(f"   ❌ Step B failed: {e}")
        raise

    # STEP C: Create /vsiaz/ path for permanent asset href (OAuth-compatible)
    try:
        logger.debug("   Step C: Creating /vsiaz/ path for STAC asset href...")
        vsiaz_href = f"/vsiaz/{container}/{blob_name}"
        logger.info(f"   ✅ Step C: Asset href will use /vsiaz/ path for OAuth: {vsiaz_href}")
    except Exception as e:
        logger.error(f"   ❌ Step C failed: {e}")
        raise

    # STEP D: Create COG asset with /vsiaz/ path
    try:
        logger.debug("   Step D: Creating STAC asset with /vsiaz/ path...")
        data_asset = self.create_cog_asset(
            blob_url=vsiaz_href,  # <-- KEY CHANGE: Use /vsiaz/ path instead of HTTPS URL
            title="Cloud Optimized GeoTIFF",
            roles=["data"]
        )
        logger.debug("   ✅ Step D: COG asset created with /vsiaz/ path")
    except Exception as e:
        logger.error(f"   ❌ Step D failed: {e}")
        raise

    # ... rest of the method ...
```

**Change 2**: Update `create_cog_asset()` method documentation (around line 430)

```python
def create_cog_asset(self, blob_url: str, title: str = None, roles: List[str] = None) -> Asset:
    """
    Create a validated STAC Asset for a Cloud Optimized GeoTIFF.

    Args:
        blob_url: Asset href - can be either:
                  - /vsiaz/ path (recommended for OAuth): /vsiaz/container/blob
                  - HTTPS URL (for SAS token access): https://account.blob.core.windows.net/...
        title: Human-readable asset title
        roles: Asset roles (data, thumbnail, overview, etc.)

    Returns:
        Validated stac-pydantic Asset

    Note:
        For OAuth-based access in TiTiler-pgSTAC, use /vsiaz/ paths.
        HTTPS URLs will bypass OAuth authentication.
    """
    asset = Asset(
        href=blob_url,  # Now accepts both /vsiaz/ paths and HTTPS URLs
        type="image/tiff; application=geotiff; profile=cloud-optimized",
        title=title or "Cloud Optimized GeoTIFF",
        roles=roles or ["data"]
    )

    logger.debug(f"Created COG asset: {blob_url}")
    return asset
```

### 2. Update Existing STAC Items (Manual Fix)

For items already in the database with HTTPS URLs, run this SQL update:

```sql
-- Check current asset hrefs
SELECT
    id,
    content->'assets'->'data'->>'href' as current_href
FROM pgstac.items
WHERE collection = 'system-rasters';

-- Update to /vsiaz/ paths (example for system-rasters collection)
UPDATE pgstac.items
SET content = jsonb_set(
    content,
    '{assets,data,href}',
    to_jsonb('/vsiaz/' ||
        regexp_replace(
            content->'assets'->'data'->>'href',
            'https://[^/]+/([^?]+).*',
            '\1'
        )
    )
)
WHERE collection = 'system-rasters'
AND content->'assets'->'data'->>'href' LIKE 'https://%';

-- Verify the update
SELECT
    id,
    content->'assets'->'data'->>'href' as updated_href
FROM pgstac.items
WHERE collection = 'system-rasters';
```

**Expected result**:
```
Before: https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif?sv=...
After:  /vsiaz/silver-cogs/file.tif
```

### 3. Test the Fix

**After updating the code**:

```bash
# 1. Re-catalog a test file
curl -X POST "http://localhost:5000/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "stac_catalog_container",
    "parameters": {
      "container_name": "silver-cogs",
      "collection_id": "system-rasters",
      "file_limit": 1
    }
  }'

# 2. Check the STAC item asset href
PGPASSWORD='B@lamb634@' psql -h rmhpgflex.postgres.database.azure.com \
  -U rob634 -d geopgflex \
  -c "SELECT content->'assets'->'data'->>'href' FROM pgstac.items ORDER BY datetime DESC LIMIT 1;"

# Expected output: /vsiaz/silver-cogs/filename.tif

# 3. Test with TiTiler-pgSTAC
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=$(curl -s ... | jq -r '.href')"
```

---

## Testing Checklist

- [ ] Update `service_stac_metadata.py` with /vsiaz/ path generation
- [ ] Test metadata extraction still works (SAS URL for rasterio)
- [ ] Test STAC item creation with /vsiaz/ href
- [ ] Verify item inserted to pgSTAC has correct href format
- [ ] Test TiTiler-pgSTAC can access the item via search
- [ ] Update existing items in database with SQL script
- [ ] Verify all three access patterns work:
  - [ ] Direct COG: `/cog/info?url=/vsiaz/container/blob.tif`
  - [ ] pgSTAC Search: `/searches/register` → `/searches/{id}/tiles/...`
  - [ ] Viewer: `/cog/WebMercatorQuad/map.html?url=/vsiaz/...`

---

## Related Files

- **ETL Job**: `/Users/robertharrison/python_builds/rmhgeoapi/jobs/stac_catalog_container.py`
- **Task Handler**: `/Users/robertharrison/python_builds/rmhgeoapi/services/stac_catalog.py`
- **STAC Service**: `/Users/robertharrison/python_builds/rmhgeoapi/services/service_stac_metadata.py` ⚠️ **NEEDS UPDATE**
- **TiTiler OAuth**: `/Users/robertharrison/python_builds/titilerpgstac/custom_pgstac_main.py`

---

## Key Insights

1. **Two Different Use Cases for URLs**:
   - **During ETL** (temporary): SAS URL needed for rasterio to extract metadata
   - **In STAC item** (permanent): `/vsiaz/` path needed for OAuth-based tile serving

2. **Why /vsiaz/ Paths Work Better**:
   - Single OAuth token grants access to ALL containers (RBAC-based)
   - No need to manage/refresh per-container SAS tokens
   - Managed Identity handles authentication transparently
   - Simpler, more secure, more scalable

3. **Backward Compatibility**:
   - Existing items with HTTPS URLs can be batch-updated via SQL
   - New items will use /vsiaz/ paths automatically
   - Both formats can coexist during transition

---

## Success Criteria

After implementing this fix:

✅ **ETL creates items with `/vsiaz/` paths**
```json
{
  "assets": {
    "data": {
      "href": "/vsiaz/silver-cogs/file.tif"
    }
  }
}
```

✅ **TiTiler-pgSTAC can access items via searches**
```bash
# Register search
SEARCH_ID=$(curl -X POST .../searches/register ...)

# Get tile - works!
curl .../searches/$SEARCH_ID/tiles/14/11454/6143.png?assets=data -o tile.png
```

✅ **All viewers work**
- Direct COG viewer: `/cog/WebMercatorQuad/map.html?url=/vsiaz/...`
- pgSTAC search viewer: `/searches/{id}/WebMercatorQuad/map.html?assets=data`

---

## Notes

- This fix aligns the ETL with TiTiler-pgSTAC's OAuth authentication architecture
- No changes needed to TiTiler-pgSTAC (already working with OAuth)
- Only the STAC item creation needs to be updated to use correct href format
- Once implemented, the entire workflow is OAuth-based with no SAS tokens in production

---

**Status**: 📝 Documentation Complete - Ready for Implementation
