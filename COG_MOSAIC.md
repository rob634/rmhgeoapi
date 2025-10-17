# COG Tiles to MosaicJSON to STAC Workflow

**Author**: Robert and Geospatial Claude Legion
**Date**: 15 OCT 2025
**Status**: Design Phase - Implementation Pending

## Overview
This document covers the complete workflow from completed COG tiles through MosaicJSON generation, STAC metadata creation, and TiTiler configuration.

**Context:** Multi-tile datasets where a large GeoTIFF is processed into multiple COG tiles that should be presented to users as a single dataset.

---

## Phase 1: All COG Tiles Complete

### Prerequisites (Already Done)
- ✅ All individual COG tiles processed and uploaded to blob storage
- ✅ Each tile is a valid Cloud Optimized GeoTIFF with:
  - Internal tiling (512×512 blocks)
  - Overviews/pyramids
  - Proper compression
  - Consistent nodata values
  - Matching CRS across all tiles
- ✅ Job orchestration system has tracked all tile metadata in Postgres

### Tile Metadata Required for Next Steps
For each tile, you need:
- **Blob storage URL** (e.g., `https://storage.azure.com/cogs/dataset_tile_001.tif`)
- **Bounding box** (minx, miny, maxx, maxy in the dataset's CRS)
- **Band information** (count, data types, descriptions)
- **Resolution/GSD** (ground sample distance)
- **CRS** (coordinate reference system)
- **File size** (for metadata)
- **Datetime** (processing timestamp or data acquisition date)

---

## Phase 2: Generate MosaicJSON

### What is MosaicJSON?
A lightweight JSON index that maps spatial areas (quadkeys) to COG URLs for efficient tile serving.

### MosaicJSON Structure
```json
{
  "mosaicjson": "1.0.0",
  "name": "Dataset Name",
  "description": "Description of the dataset",
  "version": "1.0",
  "minzoom": 0,
  "maxzoom": 18,
  "quadkey_zoom": 6,
  "bounds": [-180, -90, 180, 90],
  "center": [0, 0, 10],
  "tiles": {
    "000000": ["https://storage.azure.com/cogs/tile_001.tif"],
    "000001": ["https://storage.azure.com/cogs/tile_002.tif"],
    "000010": ["https://storage.azure.com/cogs/tile_003.tif"],
    "000011": ["https://storage.azure.com/cogs/tile_001.tif", "https://storage.azure.com/cogs/tile_003.tif"]
  }
}
```

### Generation Process

**Step 1: Calculate Quadkey Index**
- For each COG tile, determine which quadkeys it intersects
- Quadkeys are spatial indices at a specific zoom level (typically 6-8)
- A single tile may cover multiple quadkeys
- Multiple tiles may cover the same quadkey (overlaps)

**Step 2: Handle Overlaps**
When tiles overlap, define priority:
- **Last in list wins** (default)
- **First in list wins** (alternative)
- **Custom ordering** (by date, quality score, cloud cover, etc.)

**Step 3: Set Zoom Levels**
- `minzoom`: Lowest zoom level where data is useful (typically 0-5)
- `maxzoom`: Highest zoom level supported (based on COG resolution)
- `quadkey_zoom`: Zoom level for spatial indexing (6-8 recommended)

**Step 4: Calculate Global Bounds**
- Union of all tile bounding boxes
- Center point for initial map view

**Step 5: Generate and Upload**
- Write MosaicJSON file
- Upload to blob storage: `metadata/mosaics/{dataset_id}.json`
- Make publicly accessible (or with SAS token)

### Key Considerations

**Quadkey Zoom Level Selection:**
- Too low (e.g., zoom 3): Large quadkeys, inefficient spatial queries
- Too high (e.g., zoom 10): Massive index, slow to parse
- Sweet spot: zoom 6-8 for most use cases

**Overlap Handling:**
If tiles overlap (e.g., 256-512 pixel buffer):
```json
"tiles": {
  "000011": [
    "tile_001.tif",  // Priority 1 (center coverage)
    "tile_002.tif"   // Priority 2 (edge coverage)
  ]
}
```

**MosaicJSON Tools:**
- `cogeo-mosaic` Python library (recommended)
- Can be generated programmatically or via CLI
- Lightweight - typically <1MB even for thousands of tiles

---

## Phase 3: Create STAC Metadata

### Two Collections Strategy

#### Collection 1: `datasets` (User-Facing)
**Purpose:** Discoverable datasets that users can search and access

**Collection Metadata:**
```json
{
  "type": "Collection",
  "id": "datasets",
  "stac_version": "1.0.0",
  "title": "User Datasets",
  "description": "Processed geospatial datasets available for analysis and visualization",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [[null, null]]}
  },
  "links": [...]
}
```

#### Collection 2: `system_tiles` (Internal)
**Purpose:** Individual COG tiles for system tracking and maintenance

**Collection Metadata:**
```json
{
  "type": "Collection",
  "id": "system_tiles",
  "stac_version": "1.0.0",
  "title": "System Tile Registry",
  "description": "Internal collection of COG tiles (not exposed to end users)",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [[null, null]]}
  },
  "links": [...]
}
```

---

### STAC Items: User-Facing Dataset

**Location:** `datasets` collection  
**Represents:** The logical dataset (user's original 50GB GeoTIFF)

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "flood_model_2024_v1",
  "collection": "datasets",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-180, -90],
      [180, -90],
      [180, 90],
      [-180, 90],
      [-180, -90]
    ]]
  },
  "bbox": [-180, -90, 180, 90],
  "properties": {
    "datetime": "2024-10-15T12:00:00Z",
    "title": "Global Flood Model 2024",
    "description": "50GB multi-band flood depth raster processed into cloud-optimized format",
    
    "gsd": 30,
    "proj:epsg": 4326,
    
    "processing:datetime": "2024-10-15T12:00:00Z",
    "processing:software": {"etl-pipeline": "1.0.0"},
    "processing:level": "L3",
    
    "file:size": 48318382080,
    "file:tile_count": 47,
    "file:format": "COG",
    
    "eo:bands": [
      {"name": "10yr", "description": "10-year return period"},
      {"name": "20yr", "description": "20-year return period"},
      {"name": "50yr", "description": "50-year return period"}
    ]
  },
  "assets": {
    "mosaic": {
      "href": "https://storage.azure.com/metadata/mosaics/flood_model_2024_v1.json",
      "type": "application/json",
      "roles": ["mosaic", "data"],
      "title": "MosaicJSON for dynamic tile serving"
    },
    "thumbnail": {
      "href": "https://storage.azure.com/thumbnails/flood_model_2024_v1.png",
      "type": "image/png",
      "roles": ["thumbnail"],
      "title": "Dataset preview"
    },
    "metadata": {
      "href": "https://storage.azure.com/metadata/original/flood_model_2024_v1.json",
      "type": "application/json",
      "roles": ["metadata"],
      "title": "Original file metadata"
    }
  },
  "links": [
    {
      "rel": "self",
      "href": "https://your-api.com/stac/collections/datasets/items/flood_model_2024_v1"
    },
    {
      "rel": "collection",
      "href": "https://your-api.com/stac/collections/datasets"
    },
    {
      "rel": "parent",
      "href": "https://your-api.com/stac/collections/datasets"
    },
    {
      "rel": "root",
      "href": "https://your-api.com/stac"
    },
    {
      "rel": "derived_from",
      "href": "https://storage.azure.com/uploads/flood_model_2024_original.tif",
      "title": "Original uploaded file"
    },
    {
      "rel": "child",
      "href": "https://your-api.com/api/datasets/flood_model_2024_v1/tiles",
      "title": "Individual COG tiles (system collection)"
    }
  ]
}
```

**Key Fields:**
- `id`: Unique dataset identifier
- `collection`: `"datasets"` (user-facing)
- `geometry` & `bbox`: Union of all tile extents
- `properties.file:tile_count`: Number of tiles (informational)
- `assets.mosaic`: **THE KEY ASSET** - MosaicJSON URL
- `links.derived_from`: Original uploaded file
- `links.child`: Optional link to system tiles

---

### STAC Items: System Tiles (One Per COG Tile)

**Location:** `system_tiles` collection  
**Represents:** Individual COG tile (internal tracking)

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "flood_model_2024_v1_tile_001",
  "collection": "system_tiles",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-180, 0],
      [-170, 0],
      [-170, 10],
      [-180, 10],
      [-180, 0]
    ]]
  },
  "bbox": [-180, 0, -170, 10],
  "properties": {
    "datetime": "2024-10-15T12:00:00Z",
    "title": "Tile 001 of 047",
    
    "gsd": 30,
    "proj:epsg": 4326,
    
    "parent_dataset": "flood_model_2024_v1",
    "tile_index": 1,
    "tile_row": 0,
    "tile_col": 0,
    
    "processing:datetime": "2024-10-15T12:05:23Z",
    
    "file:size": 1048576000,
    
    "eo:bands": [
      {"name": "10yr", "description": "10-year return period"},
      {"name": "20yr", "description": "20-year return period"},
      {"name": "50yr", "description": "50-year return period"}
    ]
  },
  "assets": {
    "data": {
      "href": "https://storage.azure.com/cogs/flood_model_2024_v1_tile_001.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "Cloud Optimized GeoTIFF"
    }
  },
  "links": [
    {
      "rel": "self",
      "href": "https://your-api.com/stac/collections/system_tiles/items/flood_model_2024_v1_tile_001"
    },
    {
      "rel": "collection",
      "href": "https://your-api.com/stac/collections/system_tiles"
    },
    {
      "rel": "parent",
      "href": "https://your-api.com/stac/collections/system_tiles"
    },
    {
      "rel": "via",
      "href": "https://your-api.com/stac/collections/datasets/items/flood_model_2024_v1",
      "title": "Parent dataset"
    }
  ]
}
```

**Key Fields:**
- `id`: `{dataset_id}_tile_{index}` (unique tile ID)
- `collection`: `"system_tiles"` (internal)
- `geometry` & `bbox`: Individual tile extent
- `properties.parent_dataset`: Links to parent dataset ID
- `properties.tile_index/row/col`: Tile position in grid
- `assets.data`: Direct COG URL
- `links.via`: Link back to parent dataset item

---

## Phase 4: Atomic Transaction Workflow

### The Fan-In Final Task

**Goal:** Create all metadata atomically so the dataset only appears when fully complete.

**Postgres Transaction Pattern:**

```
BEGIN TRANSACTION;

-- Step 1: Verify all tiles are complete
SELECT COUNT(*) FROM tasks 
WHERE job_id = ? AND status = 'COMPLETE';
-- If count != expected_tile_count, ROLLBACK

-- Step 2: Gather tile metadata
SELECT tile_url, bbox, tile_index, file_size, ... 
FROM tasks 
WHERE job_id = ?;

-- Step 3: Generate MosaicJSON (in application logic)
-- - Calculate quadkeys
-- - Build tile index
-- - Set zoom levels and bounds

-- Step 4: Upload MosaicJSON to blob storage
-- (outside transaction, idempotent)

-- Step 5: Insert system_tiles STAC items
INSERT INTO pgstac.items (id, collection_id, geometry, properties, assets, ...)
VALUES (...), (...), (...);
-- One row per tile

-- Step 6: Insert datasets STAC item (parent)
INSERT INTO pgstac.items (id, collection_id, geometry, properties, assets, ...)
VALUES (
  'flood_model_2024_v1',
  'datasets',
  ST_GeomFromGeoJSON(...),  -- Union of all tiles
  jsonb_build_object(
    'datetime', NOW(),
    'file:tile_count', 47,
    ...
  ),
  jsonb_build_object(
    'mosaic', jsonb_build_object(
      'href', 'https://storage.azure.com/metadata/mosaics/...',
      'type', 'application/json',
      ...
    )
  ),
  ...
);

-- Step 7: Update job status
UPDATE jobs SET status = 'COMPLETE', completed_at = NOW()
WHERE job_id = ?;

COMMIT;
```

**Key Insights:**
- ✅ Parent dataset item is inserted LAST (atomic visibility)
- ✅ If transaction fails, no partial metadata visible
- ✅ MosaicJSON upload happens outside transaction (idempotent)
- ✅ Advisory locks prevent concurrent access issues

---

## Phase 5: TiTiler Configuration

### TiTiler Deployment Options

**Option 1: Standalone TiTiler Service**
- Deploy TiTiler as separate Azure Container Instance or App Service
- Configure with environment variables
- Your API proxies requests to TiTiler

**Option 2: TiTiler in Your Function App**
- Not recommended (cold starts, heavy dependencies)
- Better to use dedicated service

**Option 3: Managed Service**
- Use TiTiler-PgSTAC with your Postgres database
- Directly queries STAC items from Postgres
- Most integrated option

### TiTiler Endpoints

**For MosaicJSON Serving:**

```
# Get tile
GET /mosaicjson/tiles/{z}/{x}/{y}
  ?url=https://storage.azure.com/metadata/mosaics/flood_model_2024_v1.json
  &bidx=1,2,3  (optional: band selection)
  &rescale=0,100  (optional: value rescaling)
  &colormap_name=viridis  (optional: colormap)

# Get MosaicJSON info
GET /mosaicjson/info
  ?url=https://storage.azure.com/metadata/mosaics/flood_model_2024_v1.json

# Get bounds
GET /mosaicjson/bounds
  ?url=https://storage.azure.com/metadata/mosaics/flood_model_2024_v1.json

# Get tile metadata (which COGs cover this tile)
GET /mosaicjson/tiles/{z}/{x}/{y}/assets
  ?url=https://storage.azure.com/metadata/mosaics/flood_model_2024_v1.json
```

### Your API Wrapper Endpoints

**User-Facing REST API:**

```
# Search datasets
GET /api/datasets
  ?bbox=-180,-90,180,90
  &datetime=2024-01-01/2024-12-31
  &limit=10
→ Queries pgSTAC 'datasets' collection

# Get specific dataset
GET /api/datasets/{dataset_id}
→ Returns STAC Item with MosaicJSON URL in assets

# Get tiles (proxies to TiTiler)
GET /api/datasets/{dataset_id}/tiles/{z}/{x}/{y}
  ?bands=1,2,3
  &colormap=viridis
→ Internally: 
  1. Fetch STAC Item from Postgres
  2. Extract MosaicJSON URL from assets
  3. Proxy to TiTiler with MosaicJSON URL

# Get preview/thumbnail
GET /api/datasets/{dataset_id}/preview
→ Returns thumbnail from STAC assets

# Get metadata
GET /api/datasets/{dataset_id}/metadata
→ Returns full STAC Item JSON
```

### TiTiler Configuration

**Environment Variables:**
```bash
# CORS (for web apps)
CORS_ORIGINS=https://your-frontend.com

# Cache
CACHE_DISABLE=false
MEMCACHE_HOST=your-memcache.com

# Postgres (if using TiTiler-PgSTAC)
POSTGRES_HOST=your-db.postgres.database.azure.com
POSTGRES_DB=stac
POSTGRES_USER=...
POSTGRES_PASS=...
```

**Performance Optimization:**
- Enable caching (Redis or Memcache)
- TiTiler caches MosaicJSON after first load
- HTTP caching headers for tile responses
- CDN in front of TiTiler for public datasets

---

## Phase 6: Complete Workflow Summary

### Step-by-Step Process

```
1. User uploads 50GB GeoTIFF
   ↓
2. ETL determines file > 2GB threshold → Tile strategy
   ↓
3. Calculate tiling grid (e.g., 5×10 = 50 tiles)
   ↓
4. Fan-out: 50 parallel tasks (each uses existing COG pipeline)
   ↓
5. Each task:
   - Extracts tile from source
   - Creates COG with overviews, compression, etc.
   - Uploads to blob storage (cogs/{dataset_id}_tile_{i}.tif)
   - Records metadata in Postgres tasks table
   ↓
6. All tiles complete → Trigger fan-in task
   ↓
7. Fan-in task (atomic transaction):
   a. Query all tile metadata from Postgres
   b. Generate MosaicJSON:
      - Calculate quadkey index
      - Set zoom levels
      - Define tile priority
   c. Upload MosaicJSON to blob storage
   d. Create STAC Items in system_tiles collection (50 items)
   e. Create STAC Item in datasets collection (1 item):
      - Geometry = union of all tiles
      - Assets = MosaicJSON URL
      - Properties = aggregated metadata
   f. Update job status = COMPLETE
   g. COMMIT transaction
   ↓
8. Dataset now discoverable:
   GET /api/datasets → includes new dataset
   ↓
9. User requests tiles:
   GET /api/datasets/{id}/tiles/{z}/{x}/{y}
   ↓
10. API proxies to TiTiler with MosaicJSON URL
    ↓
11. TiTiler:
    - Loads MosaicJSON (cached after first request)
    - Queries quadkey index for tile {z}/{x}/{y}
    - Identifies relevant COG(s)
    - Makes HTTP range requests to COG(s)
    - Renders and returns tile
```

---

## Implementation Checklist

### MosaicJSON Generation
- [ ] Install/implement cogeo-mosaic library
- [ ] Calculate optimal quadkey zoom level
- [ ] Define overlap priority rules
- [ ] Set appropriate min/max zoom levels
- [ ] Upload to predictable blob storage path
- [ ] Make publicly accessible (or with SAS token)

### STAC Metadata
- [ ] Define/create `datasets` collection in pgSTAC
- [ ] Define/create `system_tiles` collection in pgSTAC
- [ ] Implement STAC Item generation logic
- [ ] Set up parent-child relationships via links
- [ ] Include all required STAC properties
- [ ] Add custom properties (tile_count, parent_dataset, etc.)

### Atomic Transaction
- [ ] Implement fan-in task in orchestration
- [ ] Verify all tiles complete before proceeding
- [ ] Wrap metadata creation in Postgres transaction
- [ ] Upload MosaicJSON idempotently
- [ ] Test rollback scenarios

### TiTiler Setup
- [ ] Deploy TiTiler service (or TiTiler-PgSTAC)
- [ ] Configure environment variables
- [ ] Set up caching (Redis/Memcache)
- [ ] Test MosaicJSON endpoints
- [ ] Implement API proxy layer
- [ ] Add authentication if needed

### REST API
- [ ] Implement STAC search endpoint
- [ ] Filter by `datasets` collection only
- [ ] Implement tile proxy endpoint
- [ ] Extract MosaicJSON URL from STAC assets
- [ ] Handle errors gracefully
- [ ] Document API endpoints

### Testing
- [ ] Test with small multi-tile dataset
- [ ] Verify STAC Items created correctly
- [ ] Verify MosaicJSON structure
- [ ] Test TiTiler tile serving
- [ ] Test parent-child STAC relationships
- [ ] Verify transaction atomicity
- [ ] Load test tile serving performance

---

## Next Steps

1. **Circle back to tiling strategy:**
   - How to calculate optimal tile grid
   - Handling overlap buffers
   - Edge case considerations

2. **Thumbnail generation:**
   - Create preview images for STAC Items
   - Store in thumbnails/ blob container

3. **Error handling:**
   - What happens if MosaicJSON generation fails?
   - Retry logic for fan-in task
   - Cleanup of partial uploads

4. **Performance optimization:**
   - MosaicJSON caching strategy
   - STAC query optimization
   - TiTiler tuning

---

## Key Takeaways

✅ **User Mental Model:** One file in → One dataset out  
✅ **Implementation:** Tiles are hidden in system collection  
✅ **Discovery:** STAC provides searchable metadata  
✅ **Serving:** MosaicJSON + TiTiler provide seamless tile serving  
✅ **Atomicity:** Postgres transaction ensures all-or-nothing visibility  
✅ **URLs Not Files:** Everything is HTTP-accessible, no VRT filesystem nightmares  

**The dataset only appears when it's fully ready. The tiling is invisible to users. The serving is fast and cloud-native.** 🎯