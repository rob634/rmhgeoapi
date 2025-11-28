# PgSTAC TiTiler Collection Design

**Date**: 22 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Design Complete - Ready for Implementation

---

## Overview

This document describes the `titiler` collection in PgSTAC, a specialized STAC collection designed for TiTiler-PgSTAC integration. This collection contains MosaicJSON datasets that TiTiler queries directly for dynamic tile serving.

---

## Three-Collection Strategy

### Collection 1: `system_tiles` (Internal Tracking)
**Purpose**: Track individual COG tiles for system management

**Contains**:
- Individual COG tiles from multi-tile raster processing
- Each tile is a separate STAC Item
- Full metadata per tile (bounds, resolution, file size)
- Direct COG URLs in assets

**Example Item**:
```json
{
  "id": "flood_model_2024_tile_001",
  "collection": "system_tiles",
  "geometry": {...},
  "properties": {
    "parent_dataset": "flood_model_2024",
    "tile_index": 1,
    "tile_row": 0,
    "tile_col": 0
  },
  "assets": {
    "data": {
      "href": "https://storage.blob.core.windows.net/silver/flood_model_2024_tile_001.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized"
    }
  }
}
```

**Visibility**: Internal only (not exposed to end users)

---

### Collection 2: `titiler` (TiTiler Serving Layer) ⭐ NEW
**Purpose**: Store MosaicJSON datasets for TiTiler-PgSTAC to query

**Contains**:
- MosaicJSON datasets (virtual mosaics of multiple COG tiles)
- One STAC Item per MosaicJSON
- MosaicJSON URL in assets (primary asset)
- Spatial/temporal extent of full dataset

**Example Item**:
```json
{
  "id": "flood_model_2024",
  "collection": "titiler",
  "stac_version": "1.0.0",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[...]]
  },
  "bbox": [-180, -90, 180, 90],
  "properties": {
    "datetime": "2024-10-22T12:00:00Z",
    "title": "Global Flood Model 2024",
    "description": "50GB multi-band flood depth raster (25 tiles)",
    "gsd": 30,
    "proj:epsg": 4326,
    "file:tile_count": 25,
    "mosaicjson:version": "1.0.0",
    "mosaicjson:quadkey_zoom": 7,
    "mosaicjson:minzoom": 0,
    "mosaicjson:maxzoom": 18
  },
  "assets": {
    "mosaicjson": {
      "href": "https://storage.blob.core.windows.net/silver/mosaics/flood_model_2024.json",
      "type": "application/json",
      "roles": ["mosaic", "data"],
      "title": "MosaicJSON for dynamic tile serving"
    }
  },
  "links": [
    {
      "rel": "tiles",
      "href": "https://titiler-pgstac.example.com/collections/titiler/items/flood_model_2024/tiles/{z}/{x}/{y}",
      "title": "Dynamic XYZ tiles via TiTiler"
    },
    {
      "rel": "child",
      "href": "/collections/system_tiles?parent_dataset=flood_model_2024",
      "title": "Individual COG tiles (25 items)"
    }
  ]
}
```

**Key Fields**:
- `assets.mosaicjson`: **PRIMARY ASSET** - URL to MosaicJSON file
- `properties.file:tile_count`: Number of constituent COG tiles
- `properties.mosaicjson:*`: MosaicJSON metadata
- `links.tiles`: TiTiler endpoint template (optional)
- `links.child`: Link to constituent tiles in `system_tiles` collection

**Visibility**: Internal (TiTiler queries this collection directly)

---

### Collection 3: `datasets` (User-Facing, Optional)
**Purpose**: User-discoverable datasets with simplified metadata

**Contains**:
- High-level dataset descriptions
- Links to `titiler` collection items
- Simplified metadata for end users
- Optional - depends on user access patterns

**Example Item**:
```json
{
  "id": "flood_model_2024_v1",
  "collection": "datasets",
  "geometry": {...},
  "properties": {
    "datetime": "2024-10-22T12:00:00Z",
    "title": "Global Flood Model 2024",
    "description": "User-friendly description...",
    "license": "proprietary"
  },
  "links": [
    {
      "rel": "alternate",
      "href": "/collections/titiler/items/flood_model_2024",
      "title": "TiTiler-compatible STAC item"
    }
  ]
}
```

**Visibility**: Public (user-facing search/discovery)

---

## TiTiler-PgSTAC Integration

### How TiTiler Queries PgSTAC

**TiTiler-PgSTAC Endpoint**:
```
GET /collections/{collection_id}/items/{item_id}/tiles/{z}/{x}/{y}
```

**Query Flow**:
1. TiTiler receives tile request for `{collection_id}/{item_id}`
2. TiTiler queries PgSTAC `titiler` collection for STAC Item
3. Extracts `assets.mosaicjson.href` from STAC Item
4. Fetches MosaicJSON from blob storage (cached after first request)
5. Uses MosaicJSON to determine which COG(s) cover tile `{z}/{x}/{y}`
6. Makes HTTP range requests to relevant COG(s)
7. Renders and returns tile

**Configuration** (TiTiler-PgSTAC):
```bash
# Environment variables
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_DB=geo
POSTGRES_USER=...
POSTGRES_PASS=...

# TiTiler expects STAC Items with MosaicJSON asset
MOSAIC_ASSET_NAME=mosaicjson  # Must match asset key in STAC Item
```

**Example TiTiler Endpoints**:
```bash
# Get tile from MosaicJSON dataset
GET /collections/titiler/items/flood_model_2024/tiles/10/512/384

# Get MosaicJSON info
GET /collections/titiler/items/flood_model_2024/info

# Get bounds
GET /collections/titiler/items/flood_model_2024/bounds

# Preview image
GET /collections/titiler/items/flood_model_2024/preview.png?width=512
```

---

## MosaicJSON Structure

**Example MosaicJSON** (referenced in STAC Item assets):
```json
{
  "mosaicjson": "1.0.0",
  "name": "flood_model_2024",
  "description": "Global Flood Model 2024 (25 tiles)",
  "version": "1.0",
  "minzoom": 0,
  "maxzoom": 18,
  "quadkey_zoom": 7,
  "bounds": [-180, -90, 180, 90],
  "center": [0, 0, 5],
  "tiles": {
    "0000000": [
      "https://storage.blob.core.windows.net/silver/flood_model_2024_tile_001.tif"
    ],
    "0000001": [
      "https://storage.blob.core.windows.net/silver/flood_model_2024_tile_002.tif"
    ],
    "0000010": [
      "https://storage.blob.core.windows.net/silver/flood_model_2024_tile_001.tif",
      "https://storage.blob.core.windows.net/silver/flood_model_2024_tile_003.tif"
    ]
  }
}
```

**Key Points**:
- **Quadkeys**: Spatial index at zoom level 7 (configurable)
- **Tiles Array**: List of COG URLs covering each quadkey
- **Overlap Handling**: Multiple COGs per quadkey (last in list wins)
- **Lightweight**: Typically <1MB even for thousands of tiles

---

## Workflow Integration

### Multi-Tile Raster Processing (process_raster_collection)

**Stage 1: Validate Tiles**
- Parallel validation of all tiles
- Output: Validation metadata per tile

**Stage 2: Create COGs**
- Parallel COG creation for all tiles
- Output: Individual COG files in silver container

**Stage 3: Create MosaicJSON** (fan_in)
- Single task aggregates all COG paths
- Generate MosaicJSON with quadkey indexing
- Upload MosaicJSON to `silver/mosaics/`
- Output: MosaicJSON blob path

**Stage 4: Create STAC Items** (fan_in)
- **Add individual tiles to `system_tiles` collection**:
  - One STAC Item per COG tile
  - Direct COG URL in assets
  - Tile-specific metadata (bounds, index)
- **Add MosaicJSON dataset to `titiler` collection**:
  - One STAC Item for MosaicJSON
  - MosaicJSON URL in `assets.mosaicjson`
  - Full dataset extent and metadata
- **Atomic transaction**: All STAC Items created together
- Output: Dataset ready for TiTiler serving

---

## Database Schema

### PgSTAC Collections Table

**Create `titiler` Collection**:
```sql
-- Insert collection into PgSTAC
INSERT INTO pgstac.collections (id, content)
VALUES (
  'titiler',
  '{
    "type": "Collection",
    "id": "titiler",
    "stac_version": "1.0.0",
    "title": "TiTiler MosaicJSON Datasets",
    "description": "MosaicJSON datasets for TiTiler-PgSTAC dynamic tile serving. Each item represents a virtual mosaic of multiple COG tiles.",
    "license": "proprietary",
    "extent": {
      "spatial": {"bbox": [[-180, -90, 180, 90]]},
      "temporal": {"interval": [[null, null]]}
    },
    "summaries": {
      "gsd": [10, 30, 100],
      "proj:epsg": [4326]
    },
    "assets": {},
    "links": [
      {
        "rel": "self",
        "href": "/collections/titiler",
        "type": "application/json"
      },
      {
        "rel": "items",
        "href": "/collections/titiler/items",
        "type": "application/geo+json"
      },
      {
        "rel": "related",
        "href": "/collections/system_tiles",
        "title": "Individual COG tiles"
      }
    ]
  }'::jsonb
);
```

**Query `titiler` Collection**:
```sql
-- Find MosaicJSON datasets by extent
SELECT id, content->>'title', content->'properties'->>'datetime'
FROM pgstac.items
WHERE collection_id = 'titiler'
  AND ST_Intersects(
    geometry,
    ST_MakeEnvelope(-120, 35, -115, 40, 4326)
  );

-- Get MosaicJSON URL from STAC Item
SELECT content->'assets'->'mosaicjson'->>'href' as mosaicjson_url
FROM pgstac.items
WHERE collection_id = 'titiler' AND id = 'flood_model_2024';
```

---

## Implementation Checklist

### Database Setup
- [ ] Create `titiler` collection in PgSTAC (SQL above)
- [ ] Create `system_tiles` collection (if not exists)
- [ ] Verify indexes on `collection_id` and `geometry`

### Service Implementation
- [ ] Update `services/raster_mosaicjson.py` handler:
  - Generate MosaicJSON from COG list
  - Upload to `silver/mosaics/` container
  - Return MosaicJSON blob path
- [ ] Update `services/stac_collection.py` handler:
  - Create STAC Items for individual tiles → `system_tiles`
  - Create STAC Item for MosaicJSON → `titiler` collection
  - Use atomic transaction for all inserts
  - Return success with dataset ID

### Workflow Integration
- [ ] Update `jobs/process_raster_collection.py`:
  - Stage 3: Create MosaicJSON (fan_in)
  - Stage 4: Create STAC Items (fan_in, dual-collection insert)
  - Pass MosaicJSON path from Stage 3 → Stage 4

### TiTiler Deployment
- [ ] Deploy TiTiler-PgSTAC container
- [ ] Configure PgSTAC connection
- [ ] Set `MOSAIC_ASSET_NAME=mosaicjson`
- [ ] Test tile serving endpoint

### Testing
- [ ] Submit test job with 2 tiles
- [ ] Verify MosaicJSON created in blob storage
- [ ] Verify 2 items in `system_tiles` collection
- [ ] Verify 1 item in `titiler` collection
- [ ] Test TiTiler tile endpoint
- [ ] Verify MosaicJSON caching in TiTiler

---

## Benefits

**1. Efficient Tile Serving**:
- TiTiler fetches only relevant COG(s) per tile request
- HTTP range requests minimize data transfer
- MosaicJSON provides fast quadkey spatial index

**2. Granular Access**:
- Individual tiles accessible via `system_tiles` collection
- Virtual mosaic accessible via `titiler` collection
- No storage waste from merged COG

**3. Scalability**:
- Thousands of tiles indexed in single MosaicJSON
- PgSTAC handles spatial queries efficiently
- TiTiler caches MosaicJSON after first request

**4. Clean Separation**:
- `system_tiles`: Internal tile tracking
- `titiler`: TiTiler serving layer
- `datasets`: User-facing discovery (optional)

---

## Example API Workflow

### Submit Multi-Tile Job
```bash
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster_collection \
  -H "Content-Type: application/json" \
  -d '{
    "blob_list": ["tile_001.tif", "tile_002.tif", "..."],
    "collection_id": "flood_model_2024",
    "container_name": "rmhazuregeobronze"
  }'
```

### Check Job Status
```bash
curl https://rmhgeoapibeta.../api/jobs/status/{JOB_ID}
```

### Query TiTiler for Tiles
```bash
# Get tile via TiTiler-PgSTAC
curl https://titiler-pgstac.example.com/collections/titiler/items/flood_model_2024/tiles/10/512/384

# Get preview image
curl https://titiler-pgstac.example.com/collections/titiler/items/flood_model_2024/preview.png?width=512

# Get dataset info
curl https://titiler-pgstac.example.com/collections/titiler/items/flood_model_2024/info
```

---

## Next Steps

1. Create `titiler` collection in PgSTAC (SQL above)
2. Update STAC service to insert into dual collections
3. Test with 2-tile workflow
4. Deploy TiTiler-PgSTAC
5. Validate end-to-end tile serving

---

**Key Takeaway**: The `titiler` collection is the bridge between MosaicJSON datasets and TiTiler-PgSTAC. TiTiler queries this collection to find MosaicJSON URLs, which it then uses for dynamic tile serving. Individual tiles remain accessible via `system_tiles`, providing both granular access and virtual mosaic capabilities.
