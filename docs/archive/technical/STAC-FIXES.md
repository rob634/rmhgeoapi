# STAC API Compliance Fixes

**Date**: November 11, 2025
**Status**: 🔧 Critical Fixes Needed
**Priority**: High - Items are not STAC spec compliant

---

## Current Status

### ✅ What's Working
- `stac_version`: ✅ "1.1.0"
- `stac_extensions`: ✅ Projection + Raster extensions declared
- Asset hrefs: ✅ Using `/vsiaz/` format for OAuth
- TiTiler URLs: ✅ Perfect - using `/cog/` endpoint correctly
- Metadata: ✅ Rich raster band statistics and histograms
- Links: ✅ Preview, TileJSON links present

### ❌ What's Broken (CRITICAL)
- `id`: ❌ **MISSING** on all items
- `type`: ❌ **MISSING** on all items
- `collection`: ❌ **MISSING** on all items

**Impact**: Items are NOT valid STAC Items and will fail validation. Many STAC clients will crash or refuse to load the data.

---

## Required Fixes

### Fix 1: Add `type` field (CRITICAL)
**STAC Requirement**: Every STAC Item MUST be a GeoJSON Feature

**Current**:
```json
{
  "bbox": [...],
  "geometry": {...},
  ...
}
```

**Required**:
```json
{
  "type": "Feature",
  "bbox": [...],
  "geometry": {...},
  ...
}
```

---

### Fix 2: Add `id` field (CRITICAL)
**STAC Requirement**: Every STAC Item MUST have a unique identifier

**Current**:
```json
{
  "bbox": [...],
  ...
}
```

**Required**:
```json
{
  "type": "Feature",
  "id": "dctest_cog_analysis",
  "bbox": [...],
  ...
}
```

**ID Generation Strategy**:
Use the blob name (without extension) as the ID, sanitized for URL safety:
- `dctest_cog_analysis.tif` → `"dctest_cog_analysis"`
- `nam_test_unified_v2/namangan14aug2019_R2C2cog_cog_analysis.tif` → `"nam_test_unified_v2-namangan14aug2019_R2C2cog_cog_analysis"`

**Python Example**:
```python
import os
from pathlib import Path

def generate_stac_item_id(blob_name: str) -> str:
    """
    Generate STAC item ID from blob path.

    Examples:
        "dctest_cog_analysis.tif" -> "dctest_cog_analysis"
        "nam_r2c2/file.tif" -> "nam_r2c2-file"
    """
    # Remove extension
    stem = Path(blob_name).stem

    # Replace / with - for subdirectories
    item_id = blob_name.replace("/", "-").replace("\\", "-")

    # Remove extension from the end
    if item_id.endswith(".tif"):
        item_id = item_id[:-4]

    return item_id

# Examples:
# "dctest_cog_analysis.tif" -> "dctest_cog_analysis"
# "nam_test_unified_v2/namangan14aug2019_R2C2cog_cog_analysis.tif"
#   -> "nam_test_unified_v2-namangan14aug2019_R2C2cog_cog_analysis"
```

---

### Fix 3: Add `collection` field (CRITICAL)
**STAC Requirement**: Items should reference their parent collection

**Current**:
```json
{
  "bbox": [...],
  ...
}
```

**Required**:
```json
{
  "type": "Feature",
  "id": "dctest_cog_analysis",
  "collection": "system-rasters",
  "bbox": [...],
  ...
}
```

---

## Complete Valid Item Example

Here's what a fully spec-compliant STAC Item should look like:

```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
  ],
  "id": "dctest_cog_analysis",
  "collection": "system-rasters",
  "bbox": [
    -77.02839834031046,
    38.90823318013706,
    -77.01291437694839,
    38.932173296054934
  ],
  "geometry": {
    "type": "Polygon",
    "coordinates": [[...]]
  },
  "properties": {
    "datetime": "2025-11-11T19:37:19.513080Z",
    "proj:epsg": 4326,
    "proj:bbox": [...],
    "proj:shape": [7777, 5030],
    "azure:tier": "silver",
    "azure:size_mb": 127.58423709869385,
    "azure:blob_path": "dctest_cog_analysis.tif",
    "azure:container": "silver-cogs",
    "azure:statistics_extracted": true
  },
  "links": [
    {
      "rel": "collection",
      "href": "system-rasters",
      "type": "application/json"
    },
    {
      "rel": "preview",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=%2Fvsiaz%2Fsilver-cogs%2Fdctest_cog_analysis.tif",
      "type": "text/html",
      "title": "Interactive map viewer (vanilla TiTiler)"
    },
    {
      "rel": "tilejson",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=%2Fvsiaz%2Fsilver-cogs%2Fdctest_cog_analysis.tif",
      "type": "application/json",
      "title": "TileJSON specification for web maps"
    },
    {
      "rel": "self",
      "href": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac_api/collections/system-rasters/items/dctest_cog_analysis",
      "type": "application/geo+json"
    }
  ],
  "assets": {
    "data": {
      "href": "/vsiaz/silver-cogs/dctest_cog_analysis.tif",
      "type": "image/tiff; application=geotiff",
      "roles": ["data"],
      "raster:bands": [
        {
          "scale": 1.0,
          "offset": 0.0,
          "sampling": "area",
          "data_type": "uint8",
          "histogram": {...},
          "statistics": {...}
        },
        ...
      ]
    },
    "thumbnail": {
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=%2Fvsiaz%2Fsilver-cogs%2Fdctest_cog_analysis.tif&max_size=256",
      "type": "image/png",
      "roles": ["thumbnail"],
      "title": "Thumbnail preview via TiTiler"
    }
  }
}
```

---

## Implementation Guide

### File to Modify
**`/Users/robertharrison/python_builds/rmhgeoapi/services/service_stac_metadata.py`**

### Location in Code
Around **line 216-400** in the `extract_item_from_blob()` method

### Current Code Pattern
```python
# Create STAC item using rio-stac
item = create_stac_item(
    source=src,
    input_datetime=datetime_value,
    ...
)

# Convert to dict
item_dict = item.to_dict()

# Add custom Azure properties
item_dict.setdefault("properties", {})
item_dict["properties"]["azure:tier"] = tier
item_dict["properties"]["azure:size_mb"] = size_mb
...

# Add TiTiler links
item_dict.setdefault("links", [])
item_dict["links"].append({
    "rel": "preview",
    "href": viewer_url,
    ...
})
```

### Required Changes
Add these fields BEFORE inserting to pgSTAC:

```python
# After converting to dict
item_dict = item.to_dict()

# === ADD THESE CRITICAL FIELDS ===

# 1. Add type (GeoJSON Feature type)
item_dict["type"] = "Feature"

# 2. Generate and add unique ID
item_id = generate_stac_item_id(blob_name)
item_dict["id"] = item_id

# 3. Add collection reference
item_dict["collection"] = collection_id  # e.g., "system-rasters"

# 4. Ensure stac_version is present (might already be set by rio-stac)
item_dict["stac_version"] = "1.1.0"

# 5. Ensure stac_extensions is present (might already be set by rio-stac)
if "raster:bands" in item_dict.get("assets", {}).get("data", {}):
    item_dict["stac_extensions"] = [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
    ]

# === CONTINUE WITH EXISTING CODE ===

# Add custom Azure properties
item_dict.setdefault("properties", {})
item_dict["properties"]["azure:tier"] = tier
...
```

### Helper Function to Add
```python
def generate_stac_item_id(blob_name: str) -> str:
    """
    Generate STAC-compliant item ID from blob path.

    Converts blob paths to URL-safe IDs by:
    - Removing file extension
    - Replacing path separators (/, \\) with hyphens
    - Preserving subdirectory structure in ID

    Args:
        blob_name: Blob path (e.g., "folder/file.tif")

    Returns:
        STAC item ID (e.g., "folder-file")

    Examples:
        >>> generate_stac_item_id("dctest_cog_analysis.tif")
        'dctest_cog_analysis'

        >>> generate_stac_item_id("nam_r2c2/namangan14aug2019.tif")
        'nam_r2c2-namangan14aug2019'
    """
    from pathlib import Path

    # Remove extension
    stem = Path(blob_name).stem

    # Get full path without extension
    parent = str(Path(blob_name).parent)

    # Build ID
    if parent and parent != ".":
        # Has subdirectory: folder/file.tif -> folder-file
        item_id = f"{parent}-{stem}".replace("/", "-").replace("\\", "-")
    else:
        # No subdirectory: file.tif -> file
        item_id = stem

    return item_id
```

---

## Testing the Fixes

### Test 1: Validate Item Structure
After making changes, test with:

```bash
curl -s "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac_api/collections/system-rasters/items" | python3 -c "
import json, sys
data = json.load(sys.stdin)
item = data['features'][0]

# Check required fields
checks = {
    'type': item.get('type'),
    'id': item.get('id'),
    'collection': item.get('collection'),
    'stac_version': item.get('stac_version'),
    'stac_extensions': 'present' if item.get('stac_extensions') else 'missing'
}

print('=== STAC Item Validation ===')
for field, value in checks.items():
    status = '✅' if value else '❌'
    print(f'{status} {field}: {value}')
"
```

**Expected Output** (after fixes):
```
=== STAC Item Validation ===
✅ type: Feature
✅ id: dctest_cog_analysis
✅ collection: system-rasters
✅ stac_version: 1.1.0
✅ stac_extensions: present
```

### Test 2: Validate with STAC Validator
```bash
# Install stac-validator
pip install stac-validator

# Validate an item
curl -s "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac_api/collections/system-rasters/items" | \
  python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin)['features'][0], indent=2))" | \
  stac-validator --item -
```

**Expected**: Should pass with no errors

### Test 3: Access Individual Item
After fixes, you should be able to access items by ID:

```bash
curl -s "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac_api/collections/system-rasters/items/dctest_cog_analysis" | python3 -m json.tool
```

**Expected**: Returns the specific item (not 404)

---

## Migration Strategy

### Option 1: Fix and Reprocess (Recommended)
1. Fix the code in `service_stac_metadata.py`
2. Delete existing items from `system-rasters` collection
3. Reprocess COGs through the pipeline
4. New items will have correct structure

### Option 2: SQL Update (Quick Fix)
Update existing items in pgSTAC database:

```sql
-- Add type field
UPDATE pgstac.items
SET content = jsonb_set(content, '{type}', '"Feature"', true)
WHERE collection = 'system-rasters';

-- Add id field (derive from blob path)
UPDATE pgstac.items
SET content = jsonb_set(
    content,
    '{id}',
    to_jsonb(
        replace(
            replace(content->'properties'->>'azure:blob_path', '.tif', ''),
            '/', '-'
        )
    ),
    true
)
WHERE collection = 'system-rasters';

-- Add collection field
UPDATE pgstac.items
SET content = jsonb_set(content, '{collection}', '"system-rasters"', true)
WHERE collection = 'system-rasters';

-- Verify changes
SELECT
    content->>'id' as id,
    content->>'type' as type,
    content->>'collection' as collection,
    content->>'stac_version' as stac_version
FROM pgstac.items
WHERE collection = 'system-rasters'
LIMIT 5;
```

### Option 3: Hybrid Approach
1. Apply SQL fix to existing items (immediate fix)
2. Update code for future items (prevents recurrence)
3. Gradually reprocess items as needed

---

## Implementation Checklist

- [ ] Add `generate_stac_item_id()` helper function to `service_stac_metadata.py`
- [ ] Add `item_dict["type"] = "Feature"` after rio-stac item creation
- [ ] Add `item_dict["id"] = generate_stac_item_id(blob_name)`
- [ ] Add `item_dict["collection"] = collection_id`
- [ ] Verify `stac_version` is set (should already be from rio-stac)
- [ ] Verify `stac_extensions` are declared
- [ ] Test with new COG upload
- [ ] Validate item structure with test script
- [ ] (Optional) Run SQL migration for existing items
- [ ] (Optional) Validate with stac-validator tool

---

## Success Criteria

After implementation, ALL items should:

✅ Have `type: "Feature"`
✅ Have unique `id` field
✅ Have `collection` reference
✅ Have `stac_version: "1.1.0"`
✅ Declare `stac_extensions` (if using extensions)
✅ Pass STAC validator
✅ Be accessible via `/collections/system-rasters/items/{id}` endpoint
✅ Work with STAC clients (QGIS, stac-browser, etc.)

---

## References

- **STAC Item Spec**: https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md
- **STAC API Spec**: https://github.com/radiantearth/stac-api-spec
- **Projection Extension**: https://github.com/stac-extensions/projection
- **Raster Extension**: https://github.com/stac-extensions/raster
- **STAC Validator**: https://github.com/stac-utils/stac-validator

---

**Status**: 📝 Ready for Implementation
**Priority**: HIGH - Items are currently non-compliant
**Estimated Effort**: 1-2 hours (code changes + testing)
