# pgSTAC Search Registration Deep Dive

**Date**: November 13, 2025
**Status**: 📚 Technical Documentation
**Purpose**: Comprehensive explanation of pgSTAC search registration, TileJSON generation, and production resilience

---

## Table of Contents

1. [Overview](#overview)
2. [The pgSTAC Search Pattern Explained](#the-pgstac-search-pattern-explained)
3. [TileJSON Generation Flow](#tilejson-generation-flow)
4. [Search Registration Persistence](#search-registration-persistence)
5. [Production Strategy](#production-strategy)
6. [Complete Implementation Example](#complete-implementation-example)
7. [Handling TiTiler Restarts](#handling-titiler-restarts)

---

## Overview

pgSTAC searches provide a **dynamic, OAuth-protected** method for serving collection mosaics through TiTiler. Unlike static MosaicJSON files, searches query the pgSTAC database in real-time, eliminating the need for public blob access or SAS tokens.

### Key Concepts

- **Search Registration**: One-time API call that associates a STAC query with a permanent `search_id`
- **TileJSON**: Dynamically generated metadata describing tile bounds and URLs (NOT stored)
- **Tile Rendering**: Runtime queries to pgSTAC + GDAL reads of matching COGs
- **OAuth Throughout**: Database queries, blob access, everything uses Managed Identity

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
2. TiTiler stores this query (database or memory)
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

**Key Insight**: The `search_id` is now a **permanent URL path component** that represents this query.

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

## Search Registration Persistence

### Where the Search Registration IS Stored

When you register a search:

```bash
POST /searches/register
{
  "collections": ["namangan_collection"],
  "filter-lang": "cql2-json",
  "metadata": {"name": "Namangan Test"}
}
```

**TiTiler stores**:
- `search_id` → `6ee588d7...`
- Query parameters → `{"collections": ["namangan_collection"]}`
- Metadata → `{"name": "Namangan Test"}`

**Storage location** (depends on TiTiler-pgSTAC configuration):

#### Option A: In-memory (default, NOT persistent across restarts)

```python
# Stored in Python dictionary in TiTiler process memory
searches = {
    "6ee588d7...": {
        "collections": ["namangan_collection"],
        "metadata": {"name": "Namangan Test"}
    }
}
```

**Implications**:
- ❌ Lost when TiTiler restarts
- ❌ Not shared across multiple TiTiler instances
- ❌ Requires re-registration after deployment

#### Option B: In pgSTAC database (persistent, recommended)

```sql
-- Stored in pgSTAC searches table
INSERT INTO pgstac.searches (id, search, metadata)
VALUES (
    '6ee588d7...',
    '{"collections": ["namangan_collection"]}',
    '{"name": "Namangan Test"}'
);
```

**Implications**:
- ✅ Persists across TiTiler restarts
- ✅ Shared across multiple TiTiler instances
- ✅ Survives deployments and scaling events

---

### Current TiTiler Configuration

Your TiTiler deployment uses the default titiler-pgstac configuration:

```python
# In custom_pgstac_main.py
add_search_register_route(
    app,
    prefix="/searches",
    tile_dependencies=[...],
    tags=["STAC Search"]
)
```

**Testing shows**: Searches are **NOT persisting** across requests, indicating in-memory storage.

**Evidence**:
```bash
# Register search
curl -X POST '.../searches/register' -d '{"collections": ["test"]}'
# Returns: {"id": "abc123..."}

# Check if search exists
curl '.../searches/abc123...'
# Returns: {"detail": "Not Found"}
```

---

## Production Strategy

### The Problem

In production environments:
- **Multiple TiTiler instances** run in parallel (load balancing)
- **Instances restart frequently** (deployments, scaling, crashes)
- **Auto-scaling** adds/removes instances dynamically

**If searches are in-memory**:
- `search_id` becomes invalid after TiTiler restart
- Different TiTiler instances don't share searches
- Users get 404 errors when accessing viewer URLs

---

### Solution: Treat search_id as Ephemeral but Regeneratable

**Core Principle**: Store the **search query definition** in collection metadata, not just the `search_id`. The `search_id` can be regenerated from the query.

### 1. Store Search Query in Collection Metadata

```json
{
  "id": "namangan_collection",
  "type": "Collection",
  "summaries": {
    "mosaic:search_query": {
      "collections": ["namangan_collection"],
      "filter-lang": "cql2-json",
      "metadata": {"name": "Namangan Collection Mosaic"}
    },
    "mosaic:search_id": ["6ee588d7..."],
    "mosaic:last_registered": "2025-11-13T16:00:00Z"
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/map.html?assets=data",
      "type": "text/html"
    }
  ]
}
```

**What we store**:
- ✅ `mosaic:search_query`: The original query definition (can recreate search)
- ✅ `mosaic:search_id`: Current registered search ID (may become stale)
- ✅ `mosaic:last_registered`: When the search was last registered
- ✅ `links`: URLs using current search_id

---

### 2. ETL Always Registers Search (Idempotent)

The ETL pipeline should register the search **every time** it creates/updates a collection:

```python
async def ensure_collection_search(
    collection_id: str,
    titiler_service: TiTilerSearchService,
    pgstac_repo: PgStacRepository
) -> str:
    """
    Ensure collection has a valid search registration.

    This is idempotent - safe to call multiple times.
    Each call registers a new search with TiTiler.

    Args:
        collection_id: STAC collection identifier
        titiler_service: Service for TiTiler API calls
        pgstac_repo: Repository for pgSTAC database operations

    Returns:
        search_id (str): Valid search ID (newly registered)
    """

    # Define search query (standard pattern for all collections)
    search_query = {
        "collections": [collection_id],
        "filter-lang": "cql2-json",
        "metadata": {
            "name": f"{collection_id} mosaic"
        }
    }

    # Register search with TiTiler
    # Note: TiTiler returns a new ID each time (not idempotent)
    logger.info(f"Registering search for collection: {collection_id}")

    search_result = await titiler_service.register_search(**search_query)
    search_id = search_result["id"]

    logger.info(f"✓ Registered search: {search_id}")

    # Get current collection
    collection = await pgstac_repo.get_collection(collection_id)

    # Update collection with search metadata
    collection.setdefault("summaries", {})
    collection["summaries"]["mosaic:search_query"] = search_query
    collection["summaries"]["mosaic:search_id"] = [search_id]
    collection["summaries"]["mosaic:last_registered"] = datetime.utcnow().isoformat() + "Z"

    # Generate URLs with new search_id
    titiler_base = TITILER_BASE_URL
    viewer_url = f"{titiler_base}/searches/{search_id}/WebMercatorQuad/map.html?assets=data"
    tilejson_url = f"{titiler_base}/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data"
    tiles_url = f"{titiler_base}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?assets=data"

    # Update links (remove old preview/tilejson/tiles links, add new ones)
    existing_links = [
        link for link in collection.get("links", [])
        if link.get("rel") not in ["preview", "tilejson", "tiles"]
    ]

    new_links = [
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
    ]

    collection["links"] = existing_links + new_links

    # Save updated collection to pgSTAC
    await pgstac_repo.update_collection(collection_id, collection)

    logger.info(f"✓ Updated collection metadata with search_id: {search_id}")

    return search_id
```

---

### 3. Handle Stale search_id (Optional: Lazy Re-registration)

If you want to handle cases where the `search_id` becomes invalid, add a wrapper endpoint:

```python
@router.get("/collections/{collection_id}/viewer")
async def get_collection_viewer(
    collection_id: str,
    titiler_service: TiTilerSearchService = Depends(get_titiler_service),
    pgstac_repo: PgStacRepository = Depends(get_pgstac_repo)
):
    """
    Get collection viewer URL, re-registering search if needed.

    This endpoint checks if the search still exists in TiTiler.
    If not, it re-registers using the stored search query.
    """

    # 1. Get collection metadata
    collection = await pgstac_repo.get_collection(collection_id)

    if not collection:
        raise HTTPException(404, f"Collection '{collection_id}' not found")

    # 2. Get stored search metadata
    summaries = collection.get("summaries", {})
    search_id = summaries.get("mosaic:search_id", [None])[0]
    search_query = summaries.get("mosaic:search_query")

    if not search_query:
        raise HTTPException(
            500,
            f"Collection '{collection_id}' has no mosaic search configured"
        )

    # 3. Check if search still exists in TiTiler
    if search_id:
        try:
            # Try to get TileJSON (validates search exists)
            tilejson_url = f"{TITILER_BASE_URL}/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data"
            async with httpx.AsyncClient() as client:
                response = await client.get(tilejson_url)

                if response.status_code == 200:
                    # Search exists, use it
                    viewer_url = f"{TITILER_BASE_URL}/searches/{search_id}/WebMercatorQuad/map.html?assets=data"
                    return RedirectResponse(viewer_url)
        except Exception as e:
            logger.warning(f"Search {search_id} validation failed: {e}")

    # 4. Search doesn't exist, re-register
    logger.info(f"Search {search_id} not found, re-registering for {collection_id}")

    new_search_id = await ensure_collection_search(
        collection_id,
        titiler_service,
        pgstac_repo
    )

    # 5. Redirect to viewer with new search_id
    viewer_url = f"{TITILER_BASE_URL}/searches/{new_search_id}/WebMercatorQuad/map.html?assets=data"
    return RedirectResponse(viewer_url)
```

**Usage**:
```bash
# Instead of using TiTiler URL directly:
# https://rmhtitiler-.../searches/abc123.../map.html?assets=data

# Use wrapper endpoint:
https://rmhazuregeoapi-.../api/collections/namangan_collection/viewer

# Wrapper checks if search exists, re-registers if needed, then redirects
```

---

### 4. Startup Script: Re-register All Searches

Run this when your API starts up or as a scheduled job:

```python
async def reregister_all_searches():
    """
    Re-register searches for all collections that have mosaic:search_query.

    Run this:
    - On API startup
    - After TiTiler deployments
    - As a scheduled job (e.g., hourly)
    """

    logger.info("=" * 80)
    logger.info("Re-registering all collection searches")
    logger.info("=" * 80)

    # Get all collections
    collections = await pgstac_repo.list_collections()

    success_count = 0
    error_count = 0

    for collection in collections:
        collection_id = collection.get("id")
        search_query = collection.get("summaries", {}).get("mosaic:search_query")

        if search_query:
            try:
                logger.info(f"Re-registering search for: {collection_id}")
                search_id = await ensure_collection_search(
                    collection_id,
                    titiler_service,
                    pgstac_repo
                )
                logger.info(f"✓ {collection_id}: {search_id}")
                success_count += 1
            except Exception as e:
                logger.error(f"✗ {collection_id}: {e}")
                error_count += 1
        else:
            logger.debug(f"  Skipping {collection_id} (no search query)")

    logger.info("=" * 80)
    logger.info(f"Re-registration complete: {success_count} success, {error_count} errors")
    logger.info("=" * 80)
```

**Add to FastAPI startup**:
```python
@app.on_event("startup")
async def startup_event():
    """Run on API startup"""

    # Connect to database
    await connect_to_db()

    # Re-register all searches
    await reregister_all_searches()
```

---

## Complete Implementation Example

### ETL Workflow: Create Collection with Search

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
    # PHASE 3: Register pgSTAC Search
    # ============================================

    logger.info("Phase 3: Registering pgSTAC search...")

    try:
        search_id = await ensure_collection_search(
            collection_id,
            titiler_service,
            pgstac_repo
        )

        logger.info(f"✓ Search registered: {search_id}")

        # Get updated collection with search metadata
        collection = await pgstac_repo.get_collection(collection_id)

        # Extract URLs from links
        preview_link = next(
            (link for link in collection["links"] if link["rel"] == "preview"),
            None
        )
        tilejson_link = next(
            (link for link in collection["links"] if link["rel"] == "tilejson"),
            None
        )

        viewer_url = preview_link["href"] if preview_link else None
        tilejson_url = tilejson_link["href"] if tilejson_link else None

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

## Handling TiTiler Restarts

### Scenario 1: TiTiler Restarts, Search Lost

**User flow**:
```
1. User requests: GET /collections/namangan_collection
2. API returns collection with preview link
3. User clicks: https://rmhtitiler-.../searches/abc123.../map.html?assets=data
4. TiTiler returns: 404 Not Found (search was in-memory, now lost)
```

**Solutions**:

#### Option A: Direct Links (Current, Simple)
- Accept that links may become stale
- Re-run ETL job to regenerate search_id
- Users get 404 until regeneration

#### Option B: Wrapper Endpoint (Recommended)
- Add `/collections/{id}/viewer` endpoint
- Endpoint checks if search exists
- Re-registers if needed
- Redirects to TiTiler

#### Option C: Startup Re-registration (Proactive)
- On API startup, re-register all searches
- Updates all collection links
- Users always have valid links

---

### Scenario 2: Multiple TiTiler Instances

**Production setup**:
```
Load Balancer
    ↓
┌─────────────────────────────────────┐
│  TiTiler Instance 1 (in-memory)     │
│  TiTiler Instance 2 (in-memory)     │
│  TiTiler Instance 3 (in-memory)     │
└─────────────────────────────────────┘
```

**Problem**: Search registered on Instance 1 not available on Instance 2

**Solutions**:

1. **Use pgSTAC database backend** (configure TiTiler to store searches in DB)
2. **Use wrapper endpoint** (re-register on each API instance)
3. **Use sticky sessions** (load balancer routes user to same TiTiler instance)

---

## Summary: Production-Ready Approach

### What ETL Should Do

1. ✅ Create collection + items with **proper geometry fields**
2. ✅ Register search with TiTiler → Get `search_id`
3. ✅ Store **both** `search_query` and `search_id` in collection metadata
4. ✅ Generate and store viewer/tilejson/tiles links
5. ✅ Return URLs in job result for user access

### For Production Resilience

**Treat `search_id` as ephemeral but regeneratable**:

- ✅ Store the search query definition (not just the ID)
- ✅ Accept that search_id may change after TiTiler restarts
- ✅ Implement one or more:
  - **Option A**: Re-register searches on API startup (automated)
  - **Option B**: Lazy re-registration via wrapper endpoint
  - **Option C**: Schedule periodic re-registration job

### The Key Insight

**Collection metadata is the source of truth**, not TiTiler's search registry.

The `mosaic:search_query` in collection summaries allows you to:
- Recreate the search anytime
- Get a new `search_id` after restarts
- Update links programmatically
- Support multiple TiTiler instances

---

## References

- [PGSTAC-MOSAIC-STRATEGY.md](PGSTAC-MOSAIC-STRATEGY.md) - Overall strategy and implementation phases
- [STAC-FIXES.md](STAC-FIXES.md) - STAC item compliance fixes (id, type, collection, geometry)
- [MOSAICJSON-IMPLEMENTATION.md](MOSAICJSON-IMPLEMENTATION.md) - Why MosaicJSON is problematic
- [TITILER-VALIDATION-TASK.md](TITILER-VALIDATION-TASK.md) - TiTiler integration and validation

---

**Status**: ✅ Documentation Complete
**Date**: November 13, 2025
**Next Action**: Implement `ensure_collection_search()` in ETL pipeline
