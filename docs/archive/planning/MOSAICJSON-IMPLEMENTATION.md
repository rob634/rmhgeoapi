# MosaicJSON Implementation Guide for ETL

**Date**: November 12, 2025
**Status**: 🔧 Critical Implementation Guide
**Priority**: High - Correct MosaicJSON generation for TiTiler

---

## Executive Summary

MosaicJSON files enable TiTiler to serve multiple COGs as a single seamless mosaic. However, there's a critical distinction in how the MosaicJSON file itself vs. the COG references inside it must be accessed.

**Key Finding**:
- ✅ **MosaicJSON file location**: Must use **HTTPS URL** (GDAL `/vsiaz/` cannot read JSON)
- ✅ **COG file references inside MosaicJSON**: Must use **`/vsiaz/` paths** (OAuth-protected)

---

## The Problem

### ❌ Current Behavior (BROKEN)

Your ETL is generating MosaicJSON files with **HTTPS URLs + SAS tokens** for COG references:

```json
{
  "mosaicjson": "0.0.3",
  "tiles": {
    "quadkey1": [
      "https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif?st=2025-11-12T03:02:57Z&se=2025-11-12T04:02:57Z&sig=..."
    ]
  }
}
```

**Problems**:
1. SAS tokens **expire** (1 hour in your case) → MosaicJSON stops working
2. Not compatible with OAuth-based TiTiler
3. Regenerating tokens requires updating the MosaicJSON file

---

## The Solution

### ✅ Correct Pattern

**MosaicJSON file structure** (with `/vsiaz/` paths):

```json
{
  "mosaicjson": "0.0.3",
  "name": "Namangan Imagery Mosaic",
  "description": "Multi-tile mosaic of Namangan, Uzbekistan",
  "version": "1.0.0",
  "minzoom": 16,
  "maxzoom": 19,
  "quadkey_zoom": 16,
  "bounds": [71.606, 40.980, 71.721, 40.984],
  "center": [71.664, 40.982, 16],
  "tiles": {
    "1213223233323231": [
      "/vsiaz/silver-cogs/namangan14aug2019_R2C1cog_analysis.tif"
    ],
    "1213223233323320": [
      "/vsiaz/silver-cogs/namangan14aug2019_R2C1cog_analysis.tif"
    ],
    "1213223233323321": [
      "/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_analysis.tif"
    ]
  }
}
```

**Key Changes**:
- ❌ REMOVE: `https://rmhazuregeo.blob.core.windows.net/...?st=...&sig=...`
- ✅ USE: `/vsiaz/{container}/{blob_path}`

---

## STAC Collection Structure

### Collection-Level Assets

Store the MosaicJSON as a **Collection asset** with an HTTPS URL:

```json
{
  "type": "Collection",
  "id": "namangan-imagery",
  "title": "Namangan Imagery Collection",
  "description": "Multi-tile mosaic of Namangan, Uzbekistan",
  "stac_version": "1.1.0",
  "extent": {
    "spatial": {
      "bbox": [[71.606, 40.980, 71.721, 40.984]]
    },
    "temporal": {
      "interval": [[null, null]]
    }
  },
  "assets": {
    "mosaicjson": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_mosaic.json",
      "type": "application/json",
      "roles": ["mosaic"],
      "title": "MosaicJSON mosaic definition",
      "description": "Dynamic mosaic of all COGs in this collection for TiTiler visualization"
    },
    "tile_0": {
      "href": "/vsiaz/silver-cogs/namangan14aug2019_R2C1cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data", "cog"],
      "title": "COG Tile: namangan14aug2019_R2C1cog_analysis"
    },
    "tile_1": {
      "href": "/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data", "cog"],
      "title": "COG Tile: namangan14aug2019_R2C2cog_analysis"
    }
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/mosaicjson/WebMercatorQuad/map.html?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_mosaic.json",
      "type": "text/html",
      "title": "View collection mosaic in TiTiler"
    }
  ]
}
```

---

## Why This Pattern?

### GDAL /vsiaz/ Limitations

**What `/vsiaz/` CAN read**:
- ✅ GeoTIFF files (.tif, .tiff)
- ✅ Other geospatial formats (Shapefile, GeoPackage, etc.)

**What `/vsiaz/` CANNOT read**:
- ❌ JSON files
- ❌ Text files
- ❌ Non-geospatial formats

### TiTiler's Access Pattern

1. **TiTiler reads MosaicJSON** → Uses HTTP(S) to fetch the JSON file
2. **TiTiler reads COGs** → Uses GDAL (with `/vsiaz/` + OAuth) to read raster data

```
[TiTiler] --HTTP(S)--> [MosaicJSON file] (JSON metadata)
           ↓
    Parses quadkey → COG mapping
           ↓
[TiTiler] --GDAL /vsiaz/ + OAuth--> [COG files] (Raster data)
```

---

## Implementation Steps

### Step 1: Update MosaicJSON Generation

**File to Modify**: Location where MosaicJSON is created (likely in a mosaic service)

**Current Code** (WRONG):
```python
# Generate blob URL with SAS token
blob_url = blob_service.get_blob_url_with_sas(
    container_name="silver-cogs",
    blob_name="file.tif",
    hours=1
)

# Add to MosaicJSON tiles
tiles[quadkey] = [blob_url]
```

**Fixed Code** (CORRECT):
```python
# Generate /vsiaz/ path (NO SAS token needed)
vsiaz_path = f"/vsiaz/{container_name}/{blob_name}"

# Add to MosaicJSON tiles
tiles[quadkey] = [vsiaz_path]
```

### Step 2: Make MosaicJSON File Accessible via HTTPS

**Option A: Public Container** (Recommended for non-sensitive mosaics)
```bash
# Make silver-cogs container publicly readable for blob access
az storage container set-permission \
  --name silver-cogs \
  --public-access blob \
  --account-name rmhazuregeo
```

**Option B: Long-lived SAS Token** (for the JSON file only)
```python
# Generate SAS token for MosaicJSON file (1 year expiry)
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta

sas_token = generate_blob_sas(
    account_name="rmhazuregeo",
    container_name="silver-cogs",
    blob_name="namangan_mosaic.json",
    account_key=account_key,
    permission=BlobSasPermissions(read=True),
    expiry=datetime.utcnow() + timedelta(days=365)
)

mosaic_url = f"https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_mosaic.json?{sas_token}"
```

**Option C: Managed Identity for TiTiler** (Already implemented!)
Your TiTiler already has Managed Identity. If you configure TiTiler to read the MosaicJSON via Managed Identity (similar to how it reads COGs), you could use:
```
https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_mosaic.json
```

However, this requires TiTiler configuration changes. **Option A (public blob access for JSON files) is simplest**.

---

## Code Example: Complete MosaicJSON Generation

```python
from typing import List, Dict, Any
import json
from pathlib import Path

def create_mosaicjson_for_collection(
    collection_id: str,
    cog_blobs: List[Dict[str, Any]],
    container: str = "silver-cogs",
    output_path: str = None
) -> Dict[str, Any]:
    """
    Generate MosaicJSON with /vsiaz/ paths for OAuth compatibility.

    Args:
        collection_id: STAC collection ID
        cog_blobs: List of COG blob metadata [{"name": "file.tif", "bounds": [...], ...}]
        container: Azure storage container name
        output_path: Optional path to save MosaicJSON file

    Returns:
        MosaicJSON dict
    """
    from cogeo_mosaic.mosaic import MosaicJSON
    from cogeo_mosaic.backends import MosaicBackend

    # Build list of /vsiaz/ paths
    cog_paths = [
        f"/vsiaz/{container}/{blob['name']}"
        for blob in cog_blobs
    ]

    # Create MosaicJSON using cogeo-mosaic library
    mosaic = MosaicJSON.from_urls(
        cog_paths,
        minzoom=16,
        maxzoom=19,
        quadkey_zoom=16
    )

    # Set metadata
    mosaic.name = f"{collection_id} mosaic"
    mosaic.description = f"Dynamic mosaic for {collection_id} collection"

    # Convert to dict
    mosaic_dict = mosaic.dict(exclude_none=True)

    # Save to file if requested
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(mosaic_dict, f, indent=2)

    return mosaic_dict

# Example usage
cog_blobs = [
    {
        "name": "namangan14aug2019_R2C1cog_analysis.tif",
        "bounds": [71.606, 40.980, 71.664, 40.982]
    },
    {
        "name": "namangan14aug2019_R2C2cog_analysis.tif",
        "bounds": [71.664, 40.980, 71.721, 40.984]
    }
]

mosaic = create_mosaicjson_for_collection(
    collection_id="namangan-imagery",
    cog_blobs=cog_blobs,
    container="silver-cogs",
    output_path="/tmp/namangan_mosaic.json"
)

# Upload to blob storage
# az storage blob upload --file /tmp/namangan_mosaic.json --name namangan_mosaic.json ...
```

---

## TiTiler URL Construction

Once MosaicJSON is created with `/vsiaz/` paths and stored with HTTPS access:

```python
import urllib.parse

# MosaicJSON file location (HTTPS URL)
mosaic_url = "https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_mosaic.json"

# URL-encode for query parameter
encoded_mosaic = urllib.parse.quote(mosaic_url, safe='')

# TiTiler base URL
titiler_base = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Generate URLs
viewer_url = f"{titiler_base}/mosaicjson/WebMercatorQuad/map.html?url={encoded_mosaic}"
tilejson_url = f"{titiler_base}/mosaicjson/WebMercatorQuad/tilejson.json?url={encoded_mosaic}"
info_url = f"{titiler_base}/mosaicjson/info?url={encoded_mosaic}"
bounds_url = f"{titiler_base}/mosaicjson/bounds?url={encoded_mosaic}"
```

**Result**:
```
https://rmhtitiler-.../mosaicjson/WebMercatorQuad/map.html?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_mosaic.json
```

---

## Testing Checklist

- [ ] MosaicJSON contains `/vsiaz/` paths (not HTTPS URLs with SAS tokens)
- [ ] MosaicJSON file is accessible via HTTPS (public or with SAS token)
- [ ] TiTiler viewer URL loads successfully
- [ ] TiTiler can read tiles from the mosaic
- [ ] STAC Collection has correct `mosaicjson` asset with HTTPS href
- [ ] STAC Collection has correct preview link to TiTiler viewer
- [ ] No SAS token expirations (MosaicJSON uses permanent OAuth access for COGs)

---

## Common Errors and Solutions

### Error 1: "No such file or directory: '/vsiaz/...json'"
**Cause**: Trying to read MosaicJSON via `/vsiaz/` (GDAL can't read JSON)
**Solution**: Use HTTPS URL for MosaicJSON location, keep `/vsiaz/` for COG references inside

### Error 2: "404: Blob not found"
**Cause**: MosaicJSON file not accessible via HTTPS
**Solution**: Make container public or add SAS token to MosaicJSON URL

### Error 3: Tiles return 401/403 errors
**Cause**: COG files inside MosaicJSON using expired SAS tokens
**Solution**: Update MosaicJSON to use `/vsiaz/` paths for COG references

### Error 4: "not recognized as being in a supported file format"
**Cause**: COG file is corrupted or not a valid GeoTIFF
**Solution**: Run TiTiler validation (see TITILER-VALIDATION-TASK.md)

---

## Migration Guide for Existing MosaicJSONs

### Quick Fix Script

```python
import json
from urllib.parse import urlparse
from azure.storage.blob import BlobServiceClient

def fix_mosaicjson(
    container: str,
    blob_name: str,
    account_name: str = "rmhazuregeo"
):
    """Fix existing MosaicJSON to use /vsiaz/ paths."""

    # Download existing MosaicJSON
    blob_service = BlobServiceClient(
        account_url=f"https://{account_name}.blob.core.windows.net",
        credential=DefaultAzureCredential()
    )

    blob_client = blob_service.get_blob_client(container, blob_name)
    mosaic_json = blob_client.download_blob().readall()
    mosaic = json.loads(mosaic_json)

    # Fix tile URLs
    for quadkey, urls in mosaic['tiles'].items():
        fixed_urls = []
        for url in urls:
            if url.startswith('http'):
                # Parse HTTPS URL and convert to /vsiaz/
                parsed = urlparse(url)
                path_parts = parsed.path.lstrip('/').split('/', 1)
                cog_container = path_parts[0]
                cog_blob = path_parts[1] if len(path_parts) > 1 else ''
                vsiaz_path = f"/vsiaz/{cog_container}/{cog_blob}"
                fixed_urls.append(vsiaz_path)
            else:
                # Already correct format
                fixed_urls.append(url)
        mosaic['tiles'][quadkey] = fixed_urls

    # Upload fixed version
    fixed_json = json.dumps(mosaic, indent=2)
    blob_client.upload_blob(fixed_json, overwrite=True)

    print(f"✅ Fixed {blob_name}")
    return mosaic

# Fix all MosaicJSONs
fix_mosaicjson("silver-cogs", "namangan_success_test.json")
fix_mosaicjson("silver-cogs", "namangan_titiler_test.json")
```

---

## Summary

### ✅ Correct Pattern

1. **MosaicJSON file location**: HTTPS URL (public or SAS token)
2. **COG references inside MosaicJSON**: `/vsiaz/` paths (OAuth)
3. **STAC Collection asset**: Points to MosaicJSON via HTTPS
4. **TiTiler viewer URL**: References MosaicJSON via HTTPS URL

### ❌ Incorrect Pattern

1. ❌ MosaicJSON using HTTPS URLs with SAS tokens for COG references
2. ❌ MosaicJSON using `/vsiaz/` path as its own location
3. ❌ Short-lived SAS tokens that expire

### 🎯 Key Takeaway

**Two-tier access pattern**:
- **Metadata (MosaicJSON)**: HTTP(S) access
- **Data (COGs)**: GDAL `/vsiaz/` + OAuth access

---

**Status**: 📝 Ready for Implementation
**Priority**: HIGH - Required for working MosaicJSON mosaics
**Estimated Effort**: 2-3 hours (update generation code + migrate existing files)
