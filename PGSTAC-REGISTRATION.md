# pgSTAC Search Registration Deep Dive

**Date**: 13 NOV 2025
**Status**: 📚 Technical Documentation - PostgreSQL-Only Configuration
**Purpose**: Comprehensive explanation of pgSTAC search registration with PostgreSQL-backed persistent storage
**Scope**: Production implementation guide - PostgreSQL backend required, no fallback workarounds

---

## Table of Contents

1. [Overview](#overview)
2. [The pgSTAC Search Pattern Explained](#the-pgstac-search-pattern-explained)
3. [TileJSON Generation Flow](#tilejson-generation-flow)
4. [Search Registration Persistence (PostgreSQL Backend)](#search-registration-persistence)
   - PostgreSQL-Backed Storage Architecture
   - Configuring TiTiler-pgSTAC for PostgreSQL Backend
   - Verifying Your Configuration
5. [Production Implementation](#production-strategy)
6. [Complete Implementation Example](#complete-implementation-example)
7. [Production Benefits](#handling-titiler-restarts)
   - Restart Resilience
   - Load Balancing and Auto-Scaling
8. [Summary: Production Implementation](#summary-production-ready-approach)

---

## Overview

pgSTAC searches provide a **dynamic, OAuth-protected** method for serving collection mosaics through TiTiler. Unlike static MosaicJSON files, searches query the pgSTAC database in real-time, eliminating the need for public blob access or SAS tokens.

### Key Concepts

- **Search Registration**: One-time API call that associates a STAC query with a **permanent `search_id`** (when using PostgreSQL backend)
- **TileJSON**: Dynamically generated metadata describing tile bounds and URLs (NOT stored)
- **Tile Rendering**: Runtime queries to pgSTAC + GDAL reads of matching COGs
- **OAuth Throughout**: Database queries, blob access, everything uses Managed Identity
- **🎯 Production Pattern**: Configure TiTiler-pgSTAC with PostgreSQL backend for persistent search storage

### Critical Production Requirement

**This documentation assumes TiTiler-pgSTAC is configured with PostgreSQL-backed search storage.** This is the ONLY supported production configuration for this system. The default in-memory storage is not supported and will not be documented with workarounds.

With PostgreSQL backend, `search_id` values become **truly permanent and static** - no workarounds or re-registration needed!

---

## The pgSTAC Search Pattern Explained

### Step 1: Register a Search Query with TiTiler

When you register a search, you're saying: **"TiTiler, please remember this STAC query and give it a permanent ID"**

**Registration Request**:
```bash
POST https://rmhtitiler-.../searches/register
Content-Type: application/json

{
  "collections": ["namangan_collection"],
  "filter-lang": "cql2-json",
  "metadata": {
    "name": "Namangan Collection Mosaic"
  }
}
```

**What Happens**:
1. TiTiler receives the search criteria
2. TiTiler stores this query in **PostgreSQL `pgstac.searches` table** (production) or memory (dev/testing)
3. TiTiler generates a unique `search_id` (e.g., `6ee588d77095f336398c097a2e926765`)
4. TiTiler returns the `search_id` to you

**Response**:
```json
{
  "id": "6ee588d77095f336398c097a2e926765",
  "links": [
    {
      "href": "https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/tilejson.json",
      "rel": "tilejson",
      "templated": true
    },
    {
      "href": "https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/map.html",
      "rel": "map",
      "templated": true
    }
  ]
}
```

**Key Insight**: The `search_id` is now a **permanent URL path component** that represents this query. With PostgreSQL-backed storage, this ID persists forever (survives restarts, scales across instances).

---

### Step 2: Using the Search ID in URLs

The `search_id` becomes part of the URL path for accessing the mosaic:

```
/searches/{search_id}/...
```

This is NOT a redirect - it's an actual endpoint that TiTiler serves.

**Example URLs**:
```
Viewer:   https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/map.html?assets=data
TileJSON: https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/tilejson.json?assets=data
Tiles:    https://rmhtitiler-.../searches/6ee588d7.../tiles/WebMercatorQuad/{z}/{x}/{y}?assets=data
```

---

## TileJSON Generation Flow

### What is TileJSON?

**TileJSON** is a specification that describes how to fetch map tiles. It provides:
- Spatial bounds of the data
- Center point and default zoom
- Tile URL template
- Min/max zoom levels

### How TileJSON is Generated (Dynamically)

When you request:
```
GET /searches/6ee588d7.../WebMercatorQuad/tilejson.json?assets=data
```

**TiTiler performs these steps**:

#### 1. Look up the search query
```
search_id: "6ee588d7..."
↓
Stored query: {"collections": ["namangan_collection"]}
```

#### 2. Execute query against pgSTAC database
```sql
SELECT id, geometry, assets, bbox
FROM pgstac.items
WHERE collection = 'namangan_collection'
```

**Returns**:
```json
[
  {
    "id": "item1",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[71.606, 40.980], [71.664, 40.980], ...]]
    },
    "bbox": [71.606, 40.980, 71.664, 40.984],
    "assets": {
      "data": {
        "href": "/vsiaz/silver-cogs/file1.tif"
      }
    }
  },
  {
    "id": "item2",
    "geometry": {...},
    "bbox": [71.664, 40.980, 71.721, 40.984],
    "assets": {
      "data": {
        "href": "/vsiaz/silver-cogs/file2.tif"
      }
    }
  }
]
```

#### 3. Calculate spatial bounds from item geometries

```python
# If items have geometry field
all_geometries = [item['geometry'] for item in items]
bounds = calculate_extent(all_geometries)
# Result: [71.606, 40.980, 71.721, 40.984]

# If items missing geometry field
bounds = [-180, -85, 180, 85]  # Default to world extent
```

**Why geometry is critical**: Without geometry, pgSTAC returns world extent, and the map zooms out to show the entire globe instead of the actual data location.

#### 4. Generate TileJSON JSON object (in memory)

```python
tilejson = {
    "tilejson": "2.2.0",
    "name": "Namangan Collection Mosaic",
    "bounds": [71.606, 40.980, 71.721, 40.984],
    "center": [71.664, 40.982, 16],
    "minzoom": 0,
    "maxzoom": 24,
    "tiles": [
        f"{titiler_base}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?assets=data"
    ]
}
```

#### 5. Return JSON response (never saved to disk/blob)

**Response**:
```json
{
  "tilejson": "2.2.0",
  "name": "Namangan Collection Mosaic",
  "bounds": [71.606, 40.980, 71.721, 40.984],
  "center": [71.664, 40.982, 16],
  "minzoom": 0,
  "maxzoom": 24,
  "tiles": [
    "https://rmhtitiler-.../searches/6ee588d7.../tiles/WebMercatorQuad/{z}/{x}/{y}?assets=data"
  ]
}
```

---

### When a Map Requests a Tile

When your web map (Leaflet, Mapbox, etc.) requests a tile:

```
GET /searches/6ee588d7.../tiles/WebMercatorQuad/16/12345/23456?assets=data
```

**TiTiler performs these steps**:

#### 1. Look up the search query
```
search_id → collections: ["namangan_collection"]
```

#### 2. Convert tile coordinates to geographic bbox
```python
# Tile coordinates
z = 16, x = 12345, y = 23456

# Convert to geographic bounds
tile_bbox = tile_to_bbox(z, x, y)
# Result: [71.650, 40.981, 71.655, 40.983]
```

#### 3. Query pgSTAC for items that intersect this tile
```sql
SELECT id, geometry, assets
FROM pgstac.items
WHERE collection = 'namangan_collection'
  AND ST_Intersects(geometry, ST_MakeEnvelope(71.650, 40.981, 71.655, 40.983, 4326))
```

**Returns**:
```json
[
  {
    "id": "item1",
    "assets": {
      "data": {"href": "/vsiaz/silver-cogs/file1.tif"}
    }
  }
]
```

#### 4. Read the COG file using GDAL
```python
# GDAL uses /vsiaz/ virtual file system
raster = gdal.Open("/vsiaz/silver-cogs/file1.tif")

# OAuth token already set in environment by TiTiler middleware
# AZURE_STORAGE_ACCESS_TOKEN = "eyJ0eXAiOiJKV1..."

# GDAL makes authenticated HTTP request to Azure Blob Storage
# Authorization: Bearer eyJ0eXAiOiJKV1...
```

#### 5. Extract tile region from COG
```python
# Read just the pixel data for this tile's geographic extent
tile_data = raster.ReadAsArray(
    xoff=tile_x_offset,
    yoff=tile_y_offset,
    xsize=256,
    ysize=256
)
```

#### 6. Render PNG tile
```python
# Apply any color/processing
# Encode as PNG
tile_image = render_to_png(tile_data)
```

#### 7. Return tile to browser
```
HTTP/1.1 200 OK
Content-Type: image/png

<PNG image data>
```

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. REGISTRATION (One-time, during ETL)                      │
└─────────────────────────────────────────────────────────────┘

  ETL → TiTiler: POST /searches/register
                 {"collections": ["namangan_collection"]}
            ↓
  TiTiler → Database/Memory: Store query with ID 6ee588d7...
            ↓
  TiTiler → ETL: {"id": "6ee588d7...", "links": [...]}
            ↓
  ETL → pgSTAC: UPDATE collection SET summaries = {
                  "mosaic:search_id": ["6ee588d7..."]
                }

┌─────────────────────────────────────────────────────────────┐
│ 2. TILEJSON REQUEST (Map initialization)                    │
└─────────────────────────────────────────────────────────────┘

  Browser → TiTiler: GET /searches/6ee588d7.../tilejson.json?assets=data
            ↓
  TiTiler → TiTiler: "What query is 6ee588d7?"
                     → collections: ["namangan_collection"]
            ↓
  TiTiler → pgSTAC DB: SELECT * FROM items
                       WHERE collection='namangan_collection'
            ↓
  pgSTAC → TiTiler: [
                      {id: "item1", geometry: {...}, assets: {...}},
                      {id: "item2", geometry: {...}, assets: {...}}
                    ]
            ↓
  TiTiler → TiTiler: Calculate bounds from geometries
                     → bounds: [71.606, 40.980, 71.721, 40.984]
            ↓
  TiTiler → Browser: {
                       "tilejson": "2.2.0",
                       "bounds": [71.606, 40.980, 71.721, 40.984],
                       "center": [71.664, 40.982, 16],
                       "tiles": ["https://.../tiles/{z}/{x}/{y}?assets=data"]
                     }
            ↓
  Browser → Browser: Initialize map centered at [71.664, 40.982]
                     Zoom level: 16
                     Tile URL template stored

┌─────────────────────────────────────────────────────────────┐
│ 3. TILE REQUEST (Every time user pans/zooms)                │
└─────────────────────────────────────────────────────────────┘

  Browser → TiTiler: GET /searches/6ee588d7.../tiles/16/12345/23456?assets=data
            ↓
  TiTiler → TiTiler: "What query is 6ee588d7?"
                     → collections: ["namangan_collection"]
            ↓
  TiTiler → TiTiler: Convert tile coords to bbox
                     z=16, x=12345, y=23456
                     → bbox: [71.650, 40.981, 71.655, 40.983]
            ↓
  TiTiler → pgSTAC DB: SELECT * FROM items
                       WHERE collection='namangan_collection'
                       AND ST_Intersects(geometry, tile_bbox)
            ↓
  pgSTAC → TiTiler: [
                      {id: "item1", assets: {
                        data: {href: "/vsiaz/silver-cogs/file1.tif"}
                      }}
                    ]
            ↓
  TiTiler → GDAL: Open("/vsiaz/silver-cogs/file1.tif")
            ↓
  GDAL → GDAL: Check environment for AZURE_STORAGE_ACCESS_TOKEN
                 → Found: "eyJ0eXAiOiJKV1QiLCJhbG..."
            ↓
  GDAL → Azure Storage: GET /silver-cogs/file1.tif
                        Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbG...
            ↓
  Azure Storage → GDAL: <GeoTIFF file data>
            ↓
  GDAL → TiTiler: Raster data for tile region (256x256 pixels)
            ↓
  TiTiler → TiTiler: Render PNG tile (apply colors, compression)
            ↓
  TiTiler → Browser: <PNG image, 256x256 pixels>
            ↓
  Browser → Screen: Display tile on map at position (16/12345/23456)
```

---

## What IS Stored vs. What's Dynamic

### ✅ Stored (Persistent)

| Data | Location | Format |
|------|----------|--------|
| Search query definition | TiTiler (memory or database) | `{"collections": ["..."], "filter-lang": "cql2-json"}` |
| STAC Items | pgSTAC PostgreSQL database | Database rows with id, geometry, assets, properties |
| STAC Collections | pgSTAC PostgreSQL database | Collection JSON with extent, links, summaries |
| COG files | Azure Blob Storage | `.tif` binary files |
| Search metadata in collection | pgSTAC (collection summaries) | `"mosaic:search_id": ["abc123..."]` |

### ❌ NOT Stored (Generated on Every Request)

| Data | Generated When | Why Dynamic |
|------|----------------|-------------|
| TileJSON | Every `/tilejson.json` request | Bounds may change as items are added/removed |
| Tile images | Every `/tiles/{z}/{x}/{y}` request | Rendered on-demand from COG data |
| Search results | Every tile/TileJSON request | Query results reflect current database state |
| Spatial bounds | Every TileJSON request | Calculated from current item geometries |

---

## Why TileJSON is Dynamic

This is a **key advantage** of the pgSTAC search pattern over static MosaicJSON.

### Scenario: You add a new COG to the collection

**Static MosaicJSON Approach** ❌:
```
1. Add COG to blob storage
2. Add STAC Item to pgSTAC database
3. Regenerate MosaicJSON file (includes new COG)
4. Upload new MosaicJSON.json to blob storage
5. Bounds/tiles update only after file regeneration
```

**pgSTAC Search Approach** ✅:
```
1. Add COG to blob storage
2. Add STAC Item to pgSTAC database (with geometry)
3. DONE! Next TileJSON request automatically includes new item
```

**Example**:

```bash
# Before adding item
curl ".../searches/abc123/tilejson.json?assets=data"
# Returns: {"bounds": [71.6, 40.9, 71.7, 40.9], ...}  # 2 items

# [You add a new STAC Item to the collection with geometry]

# After adding item (same URL, no changes needed!)
curl ".../searches/abc123/tilejson.json?assets=data"
# Returns: {"bounds": [71.6, 40.9, 71.8, 41.0], ...}  # 3 items, expanded bounds
```

---

## Search Registration Persistence (PostgreSQL Backend)

### PostgreSQL-Backed Storage Architecture

When you register a search:

```bash
POST /searches/register
{
  "collections": ["namangan_collection"],
  "filter-lang": "cql2-json",
  "metadata": {"name": "Namangan Test"}
}
```

**TiTiler stores in PostgreSQL**:
- `search_id` → `6ee588d7...`
- Query parameters → `{"collections": ["namangan_collection"]}`
- Metadata → `{"name": "Namangan Test"}`

---

### Database Schema

Searches are stored in the PostgreSQL database alongside your pgSTAC data.

```sql
-- TiTiler-pgSTAC creates this table in pgstac schema
CREATE TABLE pgstac.searches (
    id TEXT PRIMARY KEY,              -- search_id (e.g., "6ee588d7...")
    search JSONB NOT NULL,            -- {"collections": ["..."], "filter-lang": "cql2-json"}
    metadata JSONB,                   -- {"name": "Collection Mosaic"}
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**When TiTiler registers a search**:
```sql
INSERT INTO pgstac.searches (id, search, metadata)
VALUES (
    '6ee588d7...',
    '{"collections": ["namangan_collection"]}',
    '{"name": "Namangan Test"}'
);
```

**Benefits**:
- ✅ **Permanent**: Persists across TiTiler restarts
- ✅ **Scalable**: Shared across all TiTiler instances (load balancing ready)
- ✅ **Reliable**: Survives deployments and scaling events
- ✅ **Static URLs**: `search_id` never changes - no re-registration needed

**This makes your collection viewer URLs truly static and permanent!**

---

### Configuring TiTiler-pgSTAC for PostgreSQL Backend

To enable PostgreSQL-backed search storage, configure TiTiler-pgSTAC at startup:

```python
# In your TiTiler-pgSTAC main.py or app initialization
from titiler.pgstac.db import connect_to_db
from titiler.pgstac.factory import MosaicTilerFactory
from starlette.applications import Starlette
import os

# Database connection (same as your pgSTAC database)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@rmhpgflex.postgres.database.azure.com/geopgflex"
)

# Create app with database-backed search storage
app = Starlette()

@app.on_event("startup")
async def startup_event():
    """Connect to database for persistent search storage"""
    await connect_to_db(app, settings={"database_url": DATABASE_URL})

# Add search routes with database backend
mosaic = MosaicTilerFactory(
    router_prefix="/searches",
    # Database connection will be used automatically from app.state.pool
)
app.include_router(mosaic.router, prefix="/searches", tags=["STAC Search"])
```

**Key Configuration Points**:
1. **Database URL**: Use the same PostgreSQL connection as your pgSTAC database
2. **Connection Pool**: TiTiler creates a connection pool via `app.state.pool`
3. **Automatic Table Creation**: TiTiler creates `pgstac.searches` table on first use
4. **No Code Changes**: Your registration calls work exactly the same

---

### Verifying Your Configuration

Check if TiTiler is using PostgreSQL-backed storage:

```sql
-- Connect to your PostgreSQL database
-- Check if searches table exists
\dt pgstac.searches

-- If table exists, check contents
SELECT id, search->>'collections' as collections, metadata, created_at
FROM pgstac.searches
ORDER BY created_at DESC
LIMIT 10;
```

**If the table exists and has rows**: ✅ You're using PostgreSQL backend (production-ready!)

**If the table doesn't exist**: ❌ TiTiler is not configured correctly - see configuration section above.

---

## Production Implementation

### ETL Workflow Pattern

With PostgreSQL-backed search storage configured, the ETL implementation is straightforward:

```python
# 1. Create collection + items
await pgstac_repo.insert_collection(collection)
await pgstac_repo.insert_items(items)

# 2. Register search with TiTiler (stored in PostgreSQL)
search_result = await titiler_service.register_search({
    "collections": [collection_id],
    "filter-lang": "cql2-json",
    "metadata": {"name": f"{collection_id} mosaic"}
})

search_id = search_result["id"]  # This ID is now PERMANENT

# 3. Store search_id in collection metadata
collection["summaries"]["mosaic:search_id"] = [search_id]
collection["links"].append({
    "rel": "preview",
    "href": f"{TITILER_BASE}/searches/{search_id}/WebMercatorQuad/map.html?assets=data",
    "type": "text/html"
})

await pgstac_repo.update_collection(collection_id, collection)

# ✅ DONE! URL is permanent and static - no restart handling needed
```

**Key Points**:
- ✅ **No workarounds needed** - search_id is permanent
- ✅ **Static URLs** - viewer links never break
- ✅ **No re-registration logic** - set it once, works forever
- ✅ **Scales automatically** - load balancer can route to any TiTiler instance
- ✅ **Survives restarts** - deployments don't break anything

---

## Collection Metadata Storage

### Store search_id in Collection Summaries

After registering a search with TiTiler, store the permanent `search_id` in your STAC collection metadata:

```json
{
  "id": "namangan_collection",
  "type": "Collection",
  "summaries": {
    "mosaic:search_id": ["6ee588d7..."]
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/map.html?assets=data",
      "type": "text/html",
      "title": "Interactive collection mosaic viewer"
    },
    {
      "rel": "tilejson",
      "href": "https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/tilejson.json?assets=data",
      "type": "application/json",
      "title": "TileJSON specification for web maps"
    }
  ]
}
```

**What to store**:
- ✅ `mosaic:search_id`: The permanent search ID (never changes)
- ✅ `links`: Viewer and TileJSON URLs using the search_id

**Note**: With PostgreSQL backend, you only need to store the `search_id` for reference. You don't need to store the search query definition since the search persists in the database.

---

## Registration Helper Function

A simple helper function to register a search and update collection metadata:

```python
async def register_collection_search(
    collection_id: str,
    titiler_service: TiTilerSearchService,
    pgstac_repo: PgStacRepository
) -> str:
    """
    Register a permanent search for a collection.

    Args:
        collection_id: STAC collection identifier
        titiler_service: Service for TiTiler API calls
        pgstac_repo: Repository for pgSTAC database operations

    Returns:
        search_id (str): Permanent search ID (stored in PostgreSQL)
    """

    # Define search query (standard pattern for all collections)
    search_query = {
        "collections": [collection_id],
        "filter-lang": "cql2-json",
        "metadata": {"name": f"{collection_id} mosaic"}
    }

    # Register search with TiTiler (stored in pgstac.searches table)
    logger.info(f"Registering search for collection: {collection_id}")
    search_result = await titiler_service.register_search(**search_query)
    search_id = search_result["id"]  # This ID is PERMANENT

    logger.info(f"✓ Search registered: {search_id}")

    # Generate URLs with permanent search_id
    titiler_base = TITILER_BASE_URL
    viewer_url = f"{titiler_base}/searches/{search_id}/WebMercatorQuad/map.html?assets=data"
    tilejson_url = f"{titiler_base}/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data"

    # Get current collection
    collection = await pgstac_repo.get_collection(collection_id)

    # Update collection metadata
    collection.setdefault("summaries", {})
    collection["summaries"]["mosaic:search_id"] = [search_id]

    # Add viewer and TileJSON links
    collection.setdefault("links", [])
    collection["links"].extend([
        {
            "rel": "preview",
            "href": viewer_url,
            "type": "text/html",
            "title": "Interactive collection mosaic viewer"
        },
        {
            "rel": "tilejson",
            "href": tilejson_url,
            "type": "application/json",
            "title": "TileJSON specification for web maps"
        }
    ])

    # Save updated collection
    await pgstac_repo.update_collection(collection_id, collection)
    logger.info(f"✓ Collection updated with permanent search_id: {search_id}")

    return search_id
```

---

## Complete Implementation Example

### ETL Workflow: Create Collection with Search (PostgreSQL Backend)

**This example assumes TiTiler-pgSTAC is configured with PostgreSQL-backed search storage (production configuration).**

```python
from typing import List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

async def create_collection_with_mosaic(
    collection_id: str,
    collection_description: str,
    cog_files: List[str],
    pgstac_repo: PgStacRepository,
    titiler_service: TiTilerSearchService,
    stac_service: StacMetadataService
) -> Dict[str, Any]:
    """
    Complete ETL workflow: Create STAC collection with automatic search registration.

    Args:
        collection_id: Unique collection identifier
        collection_description: Human-readable description
        cog_files: List of blob paths to COG files
        pgstac_repo: pgSTAC database repository
        titiler_service: TiTiler API service
        stac_service: STAC metadata service

    Returns:
        dict: Job result with collection_id, search_id, viewer_url, etc.
    """

    logger.info(f"Creating collection: {collection_id}")
    logger.info(f"  COG files: {len(cog_files)}")

    # ============================================
    # PHASE 1: Create STAC Items
    # ============================================

    logger.info("Phase 1: Creating STAC Items...")

    items_created = []
    items_failed = []

    for cog_blob in cog_files:
        try:
            # Extract STAC item from COG
            item = await stac_service.extract_item_from_blob(
                container="silver-cogs",
                blob_name=cog_blob
            )

            # CRITICAL: Ensure required fields for pgSTAC searches
            item["id"] = stac_service.generate_item_id(cog_blob)
            item["type"] = "Feature"
            item["collection"] = collection_id

            # Geometry MUST be present for bounds calculation
            if not item.get("geometry"):
                logger.warning(f"  Item {item['id']} missing geometry, deriving from bbox")
                if item.get("bbox"):
                    item["geometry"] = stac_service.bbox_to_geometry(item["bbox"])
                else:
                    raise ValueError("Item has no bbox or geometry")

            # Insert item into pgSTAC
            await pgstac_repo.insert_item(item)
            items_created.append(item)

            logger.info(f"  ✓ Created item: {item['id']}")

        except Exception as e:
            logger.error(f"  ✗ Failed to create item for {cog_blob}: {e}")
            items_failed.append({"blob": cog_blob, "error": str(e)})

    if not items_created:
        raise ValueError("No items created successfully")

    logger.info(f"Phase 1 complete: {len(items_created)} items created, {len(items_failed)} failed")

    # ============================================
    # PHASE 2: Create STAC Collection
    # ============================================

    logger.info("Phase 2: Creating STAC Collection...")

    # Calculate spatial extent from items
    all_bboxes = [item["bbox"] for item in items_created if item.get("bbox")]
    spatial_extent = stac_service.calculate_collection_extent(all_bboxes)

    # Calculate temporal extent
    all_datetimes = [
        item["properties"]["datetime"]
        for item in items_created
        if item.get("properties", {}).get("datetime")
    ]
    temporal_extent = stac_service.calculate_temporal_extent(all_datetimes)

    # Create collection
    collection = {
        "id": collection_id,
        "type": "Collection",
        "stac_version": "1.1.0",
        "description": collection_description,
        "license": "proprietary",
        "extent": {
            "spatial": {
                "bbox": [spatial_extent]
            },
            "temporal": {
                "interval": [temporal_extent]
            }
        },
        "summaries": {
            "tile_count": [len(items_created)]
        },
        "links": []
    }

    await pgstac_repo.insert_collection(collection)

    logger.info(f"✓ Collection created: {collection_id}")
    logger.info(f"  Spatial extent: {spatial_extent}")
    logger.info(f"  Items: {len(items_created)}")

    # ============================================
    # PHASE 3: Register pgSTAC Search (One-Time, Permanent)
    # ============================================

    logger.info("Phase 3: Registering pgSTAC search...")

    try:
        # Register search with TiTiler (stored in PostgreSQL pgstac.searches table)
        search_result = await titiler_service.register_search({
            "collections": [collection_id],
            "filter-lang": "cql2-json",
            "metadata": {"name": f"{collection_id} mosaic"}
        })

        search_id = search_result["id"]  # PERMANENT ID (survives restarts!)
        logger.info(f"✓ Search registered: {search_id}")

        # Generate URLs with search_id (these are now PERMANENT!)
        titiler_base = TITILER_BASE_URL
        viewer_url = f"{titiler_base}/searches/{search_id}/WebMercatorQuad/map.html?assets=data"
        tilejson_url = f"{titiler_base}/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data"
        tiles_url = f"{titiler_base}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?assets=data"

        # Update collection metadata with permanent search_id
        collection["summaries"]["mosaic:search_id"] = [search_id]

        # Add links to collection
        collection["links"].extend([
            {
                "rel": "preview",
                "href": viewer_url,
                "type": "text/html",
                "title": "Interactive collection mosaic viewer"
            },
            {
                "rel": "tilejson",
                "href": tilejson_url,
                "type": "application/json",
                "title": "TileJSON specification for web maps"
            },
            {
                "rel": "tiles",
                "href": tiles_url,
                "type": "image/png",
                "title": "XYZ tile endpoint (templated)"
            }
        ])

        # Save updated collection to pgSTAC
        await pgstac_repo.update_collection(collection_id, collection)
        logger.info(f"✓ Collection updated with permanent search_id: {search_id}")

    except Exception as e:
        logger.error(f"✗ Search registration failed: {e}")
        search_id = None
        viewer_url = None
        tilejson_url = None

    # ============================================
    # PHASE 4: Return Result
    # ============================================

    result = {
        "success": True,
        "collection_id": collection_id,
        "stac_id": collection_id,
        "pgstac_id": collection_id,
        "tile_count": len(items_created),
        "items_created": len(items_created),
        "items_failed": len(items_failed),
        "spatial_extent": spatial_extent,
        "temporal_extent": temporal_extent,
        "search_id": search_id,
        "viewer_url": viewer_url,
        "tilejson_url": tilejson_url,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }

    if items_failed:
        result["failed_items"] = items_failed

    logger.info("=" * 80)
    logger.info(f"Collection creation complete: {collection_id}")
    logger.info(f"  Items: {len(items_created)}/{len(cog_files)}")
    logger.info(f"  Search ID: {search_id}")
    logger.info(f"  Viewer: {viewer_url}")
    logger.info("=" * 80)

    return result
```

---

## Production Benefits

### Restart Resilience

With PostgreSQL-backed search storage, TiTiler restarts have zero impact on users:

**What happens when TiTiler restarts**:
```
1. TiTiler instance restarts or scales
2. New instance connects to PostgreSQL database
3. Searches are immediately available (read from pgstac.searches table)
4. ✅ All URLs continue working - no action needed!
```

**User flow** (always works):
```
1. User requests: GET /collections/namangan_collection
2. API returns collection with preview link
3. User clicks: https://rmhtitiler-.../searches/abc123.../map.html?assets=data
4. TiTiler returns: ✅ 200 OK with viewer (search_id found in database)
```

**Benefits**:
- ✅ **Zero downtime** - restarts don't affect users
- ✅ **No re-registration** - searches persist forever
- ✅ **Load balancing ready** - all instances share same registry
- ✅ **Auto-scaling ready** - new instances automatically access existing searches

---

### Load Balancing and Auto-Scaling

**Setup**:
```
Load Balancer
    ↓
┌─────────────────────────────────────────────┐
│  TiTiler Instance 1 ────┐                   │
│  TiTiler Instance 2 ────┼─→ PostgreSQL      │
│  TiTiler Instance 3 ────┘    (Shared DB)    │
└─────────────────────────────────────────────┘
```

**Result**: ✅ All instances share same search registry - works perfectly!

**Production Characteristics**:
- ✅ **Horizontal Scaling**: Add TiTiler instances without configuration changes
- ✅ **No Sticky Sessions Required**: Load balancer can use round-robin routing
- ✅ **Consistent Behavior**: Every instance has access to all registered searches
- ✅ **Simplified Operations**: No coordination needed between instances

---

## Summary: Production Implementation

### Configuration Requirement

**TiTiler-pgSTAC MUST be configured with PostgreSQL-backed search storage.** This is the only supported configuration for this system.

See "Configuring TiTiler-pgSTAC for PostgreSQL Backend" section above for setup instructions.

---

### ETL Implementation (3 Steps)

**Step 1: Create STAC Collection + Items**
- Create collection with proper spatial/temporal extent
- Create items with **geometry fields** (critical for bounds calculation)
- Insert all into pgSTAC database

**Step 2: Register Search**
- Call TiTiler `/searches/register` endpoint
- Receive permanent `search_id` (stored in `pgstac.searches` table)

**Step 3: Update Collection Metadata**
- Store `search_id` in collection summaries
- Add viewer and TileJSON links to collection
- Save updated collection to pgSTAC

---

### Production Characteristics

**Static URLs**:
- ✅ `search_id` is **permanent** - persists across restarts
- ✅ Viewer URLs are **truly static** - never break
- ✅ **No re-registration logic needed** - set once, works forever

**Scalability**:
- ✅ **Horizontal Scaling**: Add TiTiler instances without reconfiguration
- ✅ **Load Balancing**: Round-robin routing works perfectly
- ✅ **Auto-Scaling**: New instances immediately access all searches

**Reliability**:
- ✅ **Zero Downtime**: Restarts don't affect users
- ✅ **Database-Backed**: Searches survive deployments and crashes
- ✅ **Shared Registry**: All TiTiler instances see same searches

---

### The Key Insight

**With PostgreSQL backend, the `search_id` IS permanent and static.** The pgSTAC database becomes the single source of truth for both STAC metadata AND search registrations.

**This is the only supported production architecture for this system.**

---

## References

- [PGSTAC-MOSAIC-STRATEGY.md](PGSTAC-MOSAIC-STRATEGY.md) - Overall strategy and implementation phases
- [STAC-FIXES.md](STAC-FIXES.md) - STAC item compliance fixes (id, type, collection, geometry)
- [MOSAICJSON-IMPLEMENTATION.md](MOSAICJSON-IMPLEMENTATION.md) - Why MosaicJSON is problematic
- [TITILER-VALIDATION-TASK.md](TITILER-VALIDATION-TASK.md) - TiTiler integration and validation

---

## Verification Steps

### 1. Check TiTiler-pgSTAC Configuration

```sql
-- Connect to your PostgreSQL database
-- Check if searches table exists
\dt pgstac.searches

-- If table exists, verify it's being used
SELECT id, search->>'collections' as collections, metadata, created_at
FROM pgstac.searches
ORDER BY created_at DESC
LIMIT 10;
```

**Expected Result**: Table exists and contains search registrations

**If table doesn't exist**: TiTiler-pgSTAC is not configured correctly - see "Configuring TiTiler-pgSTAC for PostgreSQL Backend" section

---

### 2. Test Search Registration

```bash
# Register a test search
curl -X POST "https://your-titiler.../searches/register" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["test_collection"],
    "filter-lang": "cql2-json",
    "metadata": {"name": "Test Mosaic"}
  }'

# Should return:
# {"id": "abc123...", "links": [...]}
```

---

### 3. Verify Persistence

```sql
-- Check that the search was stored in database
SELECT * FROM pgstac.searches WHERE id = 'abc123...';
```

**Expected Result**: Row exists with search query and metadata

---

**Status**: ✅ Documentation Complete (Updated 13 NOV 2025)
**Date**: 13 NOV 2025
**Update**: PostgreSQL-only configuration - no fallback workarounds supported
**Next Actions**:
1. Configure TiTiler-pgSTAC with PostgreSQL backend (required)
2. Verify configuration with SQL queries above
3. Implement ETL workflow using provided helper function
