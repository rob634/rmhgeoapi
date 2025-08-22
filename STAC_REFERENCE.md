# STAC Operations Quick Reference

## Core STAC Operations

### 1. Standalone File Cataloging (Recommended)
```bash
# Catalog any file independently
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/catalog_file \
  -H "x-functions-key: YOUR_FUNCTION_KEY_HERE" \
  -d '{"dataset_id":"CONTAINER","resource_id":"FILENAME","version_id":"v1"}'
```

### 2. Smart STAC (Large Rasters)
```bash
# Header-only extraction for files >5GB
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/stac_item_smart \
  -H "x-functions-key: YOUR_FUNCTION_KEY_HERE" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"large_file.tif","version_id":"v1"}'
```

## STAC Collections

| Container | Collection | Description |
|-----------|------------|-------------|
| `rmhazuregeobronze` | `bronze-assets` | Raw ingested files |
| `rmhazuregeosilver` | `silver-assets` | Processed COGs |
| `rmhazuregeogold` | `gold-assets` | Analysis-ready products |

## STAC Metadata Fields

### Core Properties
- `datetime`: Item timestamp
- `type`: "raster" or "vector"
- `file:size`: Size in bytes
- `file:container`: Azure container name
- `file:name`: Original filename
- `proj:epsg`: EPSG code (4326 for silver)

### Raster-Specific
- `raster:bands`: Band count
- `width`, `height`: Dimensions
- `driver`: Format driver (GTiff, etc)
- `compression`: Compression type
- `is_tiled`: True for tiled formats
- `is_cog`: True for COGs

### COG Provenance (NEW)
- `processing:was_already_cog`: True if source was COG
- `processing:cog_converted`: True if we converted it
- `processing:cog_valid`: COG validation status
- `processing:cataloged_directly`: True if not from pipeline

### Vector-Specific
- `vector:format`: geojson, shapefile, geopackage, etc
- `vector:features`: Feature count (for GeoJSON)

## Database Schema

### PostgreSQL/PostGIS Tables
```sql
-- Collections table
geo.collections (
  id TEXT PRIMARY KEY,
  title TEXT,
  description TEXT,
  extent JSONB,
  summaries JSONB
)

-- Items table  
geo.items (
  id TEXT PRIMARY KEY,
  collection_id TEXT,
  geometry GEOMETRY,
  bbox GEOMETRY,
  properties JSONB,
  assets JSONB,
  links JSONB,
  stac_version TEXT
)
```

## Query Examples

### Find All COGs in Silver
```sql
SELECT id, properties->>'file:name' as filename
FROM geo.items
WHERE collection_id = 'silver-assets'
  AND properties->>'is_cog' = 'true';
```

### Find Files by EPSG
```sql
SELECT id, properties->>'file:name' as filename
FROM geo.items
WHERE properties->>'proj:epsg' = '4326';
```

### Find Already-COG Files
```sql
SELECT id, properties->>'file:name' as filename
FROM geo.items
WHERE properties->>'processing:was_already_cog' = 'true';
```

### Spatial Query (Within Bounds)
```sql
SELECT id, properties->>'file:name' as filename
FROM geo.items
WHERE ST_Intersects(
  geometry,
  ST_MakeEnvelope(-77.1, 38.8, -76.9, 39.0, 4326)
);
```

## Multi-Tile Scenes

For tile sets like Namangan (R1C1, R1C2, R2C1, R2C2):
- All tiles in same collection
- Query by name pattern: `namangan14aug2019%`
- Use for VRT creation: Get asset URLs from matching items

## File Support

### Raster Formats
- ✅ GeoTIFF (.tif, .tiff)
- ✅ JPEG2000 (.jp2)
- ✅ IMG (.img)
- ✅ HDF (.hdf)

### Vector Formats  
- ✅ GeoJSON (.geojson, .json)
- ✅ Shapefile (.shp)
- ✅ GeoPackage (.gpkg)
- ✅ KML/KMZ (.kml, .kmz)
- ✅ GML (.gml)

## Processing Modes

| Mode | File Size | Method | Speed |
|------|-----------|--------|-------|
| Quick | Any | Blob metadata only | <1 sec |
| Smart | >5GB rasters | Header-only via URL | 2-5 sec |
| Full | ≤5GB | Download & extract | 5-30 sec |

## Common Workflows

### 1. Process & Catalog Raster
```bash
# Step 1: Convert to COG
curl -X POST .../api/jobs/cog_conversion \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"file.tif"}'

# Step 2: Auto-cataloged in STAC (happens automatically)
```

### 2. Direct Catalog Existing COG
```bash
curl -X POST .../api/jobs/catalog_file \
  -d '{"dataset_id":"rmhazuregeosilver","resource_id":"existing_cog.tif"}'
```

### 3. Catalog Vector File
```bash
curl -X POST .../api/jobs/catalog_file \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"data.geojson"}'
```

## Key Features

1. **Automatic Collection Management**: Collections created on-demand
2. **Smart Mode**: No download for large raster metadata
3. **COG Detection**: Automatically identifies COGs
4. **Provenance Tracking**: Knows if file was already optimized
5. **Spatial Indexing**: PostGIS geometry for spatial queries
6. **Idempotent**: Same file → same STAC item ID (MD5 hash)

## API Response Structure

```json
{
  "success": true,
  "stac_item": {
    "id": "hash_of_container_and_filename",
    "collection": "silver-assets",
    "bbox": [-180, -90, 180, 90],
    "geometry": {"type": "Polygon", ...},
    "properties": {
      "datetime": "2024-12-21T...",
      "is_cog": true,
      "processing:was_already_cog": false,
      "processing:cog_converted": true,
      ...
    },
    "assets": {
      "data": {
        "href": "https://storage.../file.tif",
        "type": "image/tiff"
      }
    }
  }
}
```