# Minimal STAC Setup for Single GeoTIFF

**Date**: 28 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Minimal STAC records needed to test TiTiler-pgstac with one GeoTIFF

## Overview

To use TiTiler-pgstac with a single GeoTIFF, you need:
1. **PgSTAC schema** installed in PostgreSQL
2. **One STAC Collection** (container/category)
3. **One STAC Item** (pointing to your GeoTIFF)

## Step-by-Step Setup

### Step 1: Install PgSTAC Schema

Connect to PostgreSQL and run:

```sql
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Create pgstac schema
CREATE SCHEMA IF NOT EXISTS pgstac;

-- Install PgSTAC (version 0.8.5 or later)
-- Download from: https://github.com/stac-utils/pgstac/releases
-- Or use: \i /path/to/pgstac.sql
```

**Alternative: Use PgSTAC Docker container to generate SQL:**
```bash
# Pull PgSTAC image
docker pull ghcr.io/stac-utils/pgstac:v0.8.5

# Extract migration SQL
docker run --rm ghcr.io/stac-utils/pgstac:v0.8.5 cat /opt/src/pgstac/sql/pgstac.sql > pgstac.sql

# Connect to your PostgreSQL and run the SQL
psql "postgresql://rob634:B@lamb634@@rmhpgflex.postgres.database.azure.com:5432/postgres" -f pgstac.sql
```

### Step 2: Create Minimal STAC Collection

A collection is a container for items. Here's the absolute minimum:

```json
{
  "type": "Collection",
  "id": "namangan-collection",
  "stac_version": "1.0.0",
  "description": "Namangan test imagery",
  "license": "proprietary",
  "extent": {
    "spatial": {
      "bbox": [[71.0, 40.0, 72.0, 41.0]]
    },
    "temporal": {
      "interval": [["2019-08-14T00:00:00Z", null]]
    }
  },
  "links": []
}
```

**Insert into PgSTAC:**
```sql
SELECT pgstac.create_collection('{
  "type": "Collection",
  "id": "namangan-collection",
  "stac_version": "1.0.0",
  "description": "Namangan test imagery",
  "license": "proprietary",
  "extent": {
    "spatial": {
      "bbox": [[71.0, 40.0, 72.0, 41.0]]
    },
    "temporal": {
      "interval": [["2019-08-14T00:00:00Z", null]]
    }
  },
  "links": []
}'::jsonb);
```

### Step 3: Create Minimal STAC Item (Your GeoTIFF)

This is the minimal item pointing to your namangan GeoTIFF:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "namangan-test-item",
  "collection": "namangan-collection",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [71.6262, 40.9859],
      [71.6262, 41.0141],
      [71.6738, 41.0141],
      [71.6738, 40.9859],
      [71.6262, 40.9859]
    ]]
  },
  "bbox": [71.6262, 40.9859, 71.6738, 41.0141],
  "properties": {
    "datetime": "2019-08-14T00:00:00Z"
  },
  "assets": {
    "visual": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data", "visual"]
    }
  },
  "links": []
}
```

**Insert into PgSTAC:**
```sql
SELECT pgstac.create_items('{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "namangan-test-item",
  "collection": "namangan-collection",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [71.6262, 40.9859],
      [71.6262, 41.0141],
      [71.6738, 41.0141],
      [71.6738, 40.9859],
      [71.6262, 40.9859]
    ]]
  },
  "bbox": [71.6262, 40.9859, 71.6738, 41.0141],
  "properties": {
    "datetime": "2019-08-14T00:00:00Z"
  },
  "assets": {
    "visual": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data", "visual"]
    }
  },
  "links": []
}'::jsonb);
```

### Step 4: Test with TiTiler

Once the collection and item are in PgSTAC:

```bash
# Search for items
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["namangan-collection"],
    "limit": 10
  }'

# Get tiles from the search
# TiTiler will return a search_id, then use:
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/{search_id}/tiles/{z}/{x}/{y}.png"
```

## Complete Setup Script

Save this as `setup_minimal_stac.sql`:

```sql
-- ============================================================================
-- Minimal STAC Setup for TiTiler-pgstac Testing
-- ============================================================================

-- Step 1: Ensure extensions exist
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Step 2: Verify pgstac schema exists
-- (Assumes pgstac.sql was already run)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'pgstac') THEN
    RAISE EXCEPTION 'pgstac schema does not exist. Run pgstac.sql first.';
  END IF;
END $$;

-- Step 3: Create collection
SELECT pgstac.create_collection('{
  "type": "Collection",
  "id": "namangan-collection",
  "stac_version": "1.0.0",
  "description": "Namangan test imagery",
  "license": "proprietary",
  "extent": {
    "spatial": {
      "bbox": [[71.0, 40.0, 72.0, 41.0]]
    },
    "temporal": {
      "interval": [["2019-08-14T00:00:00Z", null]]
    }
  },
  "links": []
}'::jsonb);

-- Step 4: Create item pointing to your GeoTIFF
SELECT pgstac.create_items('{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "namangan-test-item",
  "collection": "namangan-collection",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [71.6262, 40.9859],
      [71.6262, 41.0141],
      [71.6738, 41.0141],
      [71.6738, 40.9859],
      [71.6262, 40.9859]
    ]]
  },
  "bbox": [71.6262, 40.9859, 71.6738, 41.0141],
  "properties": {
    "datetime": "2019-08-14T00:00:00Z"
  },
  "assets": {
    "visual": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data", "visual"]
    }
  },
  "links": []
}'::jsonb);

-- Step 5: Verify setup
SELECT 'Collection count:' as check, count(*)::text as result FROM pgstac.collections
UNION ALL
SELECT 'Item count:' as check, count(*)::text as result FROM pgstac.items;
```

## Run the Setup

```bash
# Download PgSTAC SQL (one-time)
curl -o pgstac.sql https://raw.githubusercontent.com/stac-utils/pgstac/v0.8.5/sql/pgstac.sql

# Connect to PostgreSQL
export PGPASSWORD='B@lamb634@'

# Install PgSTAC schema
psql -h rmhpgflex.postgres.database.azure.com \
  -U rob634 \
  -d postgres \
  -f pgstac.sql

# Create collection and item
psql -h rmhpgflex.postgres.database.azure.com \
  -U rob634 \
  -d postgres \
  -f setup_minimal_stac.sql
```

## Verification

After setup, verify in PostgreSQL:

```sql
-- Check collections
SELECT id, description FROM pgstac.collections;

-- Check items
SELECT id, collection, datetime FROM pgstac.items;

-- Get the full item with asset
SELECT jsonb_pretty(content)
FROM pgstac.items
WHERE id = 'namangan-test-item';
```

## Using with TiTiler

### Method 1: STAC Search API

```bash
# Create a search
SEARCH_RESPONSE=$(curl -s "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["namangan-collection"]
  }')

# Extract search_id
SEARCH_ID=$(echo $SEARCH_RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

# Get tiles
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/$SEARCH_ID/tiles/10/725/394.png" -o tile.png
```

### Method 2: Direct Collection Access

```bash
# Get collection info
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/namangan-collection"

# Get collection tiles
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/namangan-collection/tiles/10/725/394.png" -o tile.png
```

### Method 3: Item-Level Access

```bash
# Register item for tiling
curl -X POST "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/stac/register" \
  -H "Content-Type: application/json" \
  -d '{
    "collection": "namangan-collection",
    "item": "namangan-test-item"
  }'
```

## Important Notes

### Geometry Accuracy
The `geometry` and `bbox` in the STAC item should match your GeoTIFF's actual extent. You can get the real values using:

```python
from osgeo import gdal
import json

# Open the GeoTIFF
ds = gdal.Open('/vsicurl/https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif')

# Get extent
gt = ds.GetGeoTransform()
width = ds.RasterXSize
height = ds.RasterYSize

minx = gt[0]
maxy = gt[3]
maxx = minx + gt[1] * width
miny = maxy + gt[5] * height

bbox = [minx, miny, maxx, maxy]
geometry = {
    "type": "Polygon",
    "coordinates": [[
        [minx, miny],
        [minx, maxy],
        [maxx, maxy],
        [maxx, miny],
        [minx, miny]
    ]]
}

print(f"bbox: {bbox}")
print(f"geometry: {json.dumps(geometry, indent=2)}")
```

### Asset Key
The asset key (`visual` in our example) must be used when requesting tiles. TiTiler will look for this asset to generate tiles.

### COG Requirement
The GeoTIFF MUST be a Cloud-Optimized GeoTIFF (COG) for TiTiler to work efficiently. Verify with:

```bash
rio cogeo validate https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif
```

## Minimal Fields Required

### Collection (Absolute Minimum):
```json
{
  "type": "Collection",
  "id": "my-collection",
  "stac_version": "1.0.0",
  "description": "Description",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[minx, miny, maxx, maxy]]},
    "temporal": {"interval": [["2019-01-01T00:00:00Z", null]]}
  }
}
```

### Item (Absolute Minimum):
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "my-item",
  "collection": "my-collection",
  "geometry": {"type": "Polygon", "coordinates": [[[...]]]},
  "bbox": [minx, miny, maxx, maxy],
  "properties": {"datetime": "2019-01-01T00:00:00Z"},
  "assets": {
    "visual": {
      "href": "https://storage/path/to/cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized"
    }
  }
}
```

## Troubleshooting

### Error: "schema pgstac does not exist"
- PgSTAC schema not installed
- Run `pgstac.sql` first

### Error: "collection not found"
- Collection not created or wrong ID
- Check: `SELECT * FROM pgstac.collections;`

### Error: "no items found"
- Item not inserted or wrong collection reference
- Check: `SELECT * FROM pgstac.items WHERE collection = 'your-collection';`

### Tiles return 404
- Check asset `href` URL is accessible
- Verify managed identity has storage permissions
- Ensure GeoTIFF is a valid COG

## Next Steps

After this minimal setup works:
1. Add more items to the collection
2. Add metadata (cloud cover, sensor info, etc.)
3. Create multiple collections for different datasets
4. Use STAC search filters (bbox, datetime, properties)
5. Implement automated STAC ingestion pipeline