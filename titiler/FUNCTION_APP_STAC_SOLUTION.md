# Using Your Function App for STAC Management

**Date**: 28 OCT 2025
**Purpose**: Use existing function app STAC API to catalog COGs for TiTiler

## Solution: No Direct Database Access Needed! 🎉

Your function app at `https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net` already has a **complete STAC API** that you can use from any network.

## Step 1: Add Your Namangan GeoTIFF to STAC

Use the `/api/stac/extract` endpoint to automatically catalog your COG:

```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "container": "rmhazuregeosilver",
    "blob_name": "namangan/namangan14aug2019_R1C2cog_analysis.tif",
    "collection_id": "cogs",
    "insert": true
  }'
```

**What this does:**
- ✅ Reads the COG from Azure Storage
- ✅ Extracts bounds, CRS, bands, and metadata
- ✅ Creates a proper STAC item
- ✅ Inserts it into the `cogs` collection in PgSTAC
- ✅ Returns the STAC item JSON

## Step 2: Verify the STAC Item Was Created

```bash
# Search for items in the cogs collection
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/search?collections=cogs&limit=10" | python3 -m json.tool
```

## Step 3: Use with TiTiler

Once the STAC item exists, TiTiler-pgstac can generate tiles:

```bash
# Create a search in TiTiler
curl -X POST "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/register" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["cogs"],
    "filter": {
      "op": "=",
      "args": [{"property": "id"}, "namangan14aug2019_R1C2cog_analysis"]
    }
  }'

# This returns a search_id, then use:
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/{search_id}/tiles/10/725/394.png" -o tile.png
```

## Complete Workflow Example

Here's a complete script to add your COG and test with TiTiler:

```bash
#!/bin/bash

# Configuration
FUNC_APP="https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net"
TITILER="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

echo "Step 1: Add COG to STAC catalog"
STAC_RESPONSE=$(curl -s -X POST "$FUNC_APP/api/stac/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "container": "rmhazuregeosilver",
    "blob_name": "namangan/namangan14aug2019_R1C2cog_analysis.tif",
    "collection_id": "cogs",
    "insert": true
  }')

echo "$STAC_RESPONSE" | python3 -m json.tool

# Extract item ID
ITEM_ID=$(echo "$STAC_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('stac_item', {}).get('id', 'unknown'))")
echo "Created STAC item: $ITEM_ID"

echo ""
echo "Step 2: Verify item in catalog"
curl -s "$FUNC_APP/api/search?collections=cogs&limit=5" | python3 -m json.tool

echo ""
echo "Step 3: Register search with TiTiler"
SEARCH_RESPONSE=$(curl -s -X POST "$TITILER/searches/register" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["cogs"]
  }')

echo "$SEARCH_RESPONSE" | python3 -m json.tool

# Extract search ID
SEARCH_ID=$(echo "$SEARCH_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', 'unknown'))")
echo "Search ID: $SEARCH_ID"

echo ""
echo "Step 4: Get a tile"
curl -s "$TITILER/searches/$SEARCH_ID/tiles/10/725/394.png" -o namangan_tile.png
ls -lh namangan_tile.png

echo ""
echo "Done! View the tile: open namangan_tile.png"
```

## Available STAC API Endpoints

### Your Function App (Management)

```bash
# List collections
GET https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/collections

# Search items
GET/POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/search

# Extract raster metadata and catalog
POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/extract
Body: {"container": "...", "blob_name": "...", "collection_id": "cogs"}

# Setup PgSTAC (if needed)
POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/setup?confirm=yes
```

### Current Collections

Based on the collections endpoint, you have:
- **dev** - Development & Testing
- **cogs** - Cloud-Optimized GeoTIFFs
- (possibly more)

## Expected Request/Response for /api/stac/extract

### Request:
```json
{
  "container": "rmhazuregeosilver",
  "blob_name": "namangan/namangan14aug2019_R1C2cog_analysis.tif",
  "collection_id": "cogs",
  "insert": true
}
```

### Response (Success):
```json
{
  "success": true,
  "stac_item": {
    "type": "Feature",
    "stac_version": "1.0.0",
    "id": "namangan14aug2019_R1C2cog_analysis",
    "collection": "cogs",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[...]]
    },
    "bbox": [minx, miny, maxx, maxy],
    "properties": {
      "datetime": "2019-08-14T00:00:00Z",
      "proj:epsg": 32642,
      "eo:bands": [...]
    },
    "assets": {
      "visual": {
        "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif",
        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "roles": ["data"]
      }
    }
  },
  "inserted": true
}
```

## Troubleshooting

### Error: "Collection not found"
```bash
# Check available collections
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/collections"

# Use "dev" collection for testing
# Or create collection with: POST /api/stac/collections/silver
```

### Error: "Blob not found"
- Verify container name: `rmhazuregeosilver` (not `rmhazuregeo`)
- Verify blob path: `namangan/namangan14aug2019_R1C2cog_analysis.tif`
- Check with Azure CLI:
```bash
az storage blob exists \
  --account-name rmhazuregeo \
  --container-name rmhazuregeosilver \
  --name namangan/namangan14aug2019_R1C2cog_analysis.tif
```

### Error: "GDAL/Rasterio import failed"
- The function app lazy-loads GDAL dependencies
- Check function app logs: `az webapp log tail --resource-group rmhazure_rg --name rmhgeoapibeta`

### TiTiler returns "no items found"
- Verify STAC item was created: Search endpoint should return features
- Check TiTiler is pointing to same PostgreSQL database
- Verify POSTGRES_SCHEMA=pgstac in TiTiler environment variables

## Architecture Overview

```
Your Workflow:
1. Public network (anywhere) → Function App STAC API
                                     ↓
                                 PgSTAC in PostgreSQL
                                     ↓
                              TiTiler-pgstac reads items
                                     ↓
                              Generates tiles from COGs in Azure Storage
```

**Key Benefit**: You never need direct PostgreSQL access! The function app's STAC API handles all database operations via HTTP endpoints.

## Next Steps

Once this works with one GeoTIFF:
1. Batch process multiple GeoTIFFs with a loop
2. Add more metadata (properties) to STAC items
3. Create custom collections for different datasets
4. Build automated ingestion pipelines
5. Integrate with QGIS or other STAC clients

## Testing Right Now

Try this command to add your namangan GeoTIFF:

```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "container": "rmhazuregeosilver",
    "blob_name": "namangan/namangan14aug2019_R1C2cog_analysis.tif",
    "collection_id": "cogs",
    "insert": true
  }' | python3 -m json.tool
```

This should work right now, from any network! 🚀