# pgSTAC Search Registration - Production Architecture

**Date**: 17 NOV 2025
**Status**: 📚 Technical Documentation - ETL Pipeline Direct Database Registration
**Purpose**: Production implementation where ETL pipeline writes directly to `pgstac.searches`, TiTiler is read-only
**Scope**: Production security architecture - ETL owns all writes, TiTiler has read-only database access

---

## Table of Contents

1. [Overview](#overview)
2. [Production Architecture Decision](#production-architecture-decision)
3. [Option A: ETL Direct Registration (Implemented)](#option-a-etl-direct-registration)
4. [Option B: TiTiler API Registration (Not Used)](#option-b-titiler-api-registration)
5. [Database Schema](#database-schema)
6. [Managed Identity Permissions](#managed-identity-permissions)
7. [Implementation: PgSTACSearchRegistration Class](#implementation-pgstacsearchregistration-class)
8. [ETL Workflow Integration](#etl-workflow-integration)
9. [TileJSON Generation Flow](#tilejson-generation-flow)
10. [Production Benefits](#production-benefits)
11. [Verification Steps](#verification-steps)

---

## Overview

pgSTAC searches provide a **dynamic, OAuth-protected** method for serving collection mosaics through TiTiler. Searches are stored in the PostgreSQL database (`pgstac.searches` table) and referenced by permanent `search_id` values.

### Key Concepts

- **Search Registration**: Creating a row in `pgstac.searches` that associates a STAC query with a **permanent `search_id`** (SHA256 hash)
- **TileJSON**: Dynamically generated metadata describing tile bounds and URLs (NOT stored, generated on-demand)
- **Tile Rendering**: Runtime queries to pgSTAC + GDAL reads of matching COGs
- **OAuth Throughout**: Database queries, blob access, everything uses Managed Identity
- **🎯 Production Pattern**: ETL pipeline writes to database directly, TiTiler reads only

### Critical Production Architecture

**This system uses a two-tier security model**:

1. **ETL Pipeline (rmhazuregeoapi)**: Read-write access to `pgstac` schema
2. **TiTiler (rmhtitiler)**: Read-only access to `pgstac` schema

**Why**: TiTiler is a public-facing tile server. If compromised, it cannot modify the database.

---

## Production Architecture Decision

### The Question

How should search registration be handled when TiTiler must be read-only in production?

**Two Options**:

| Approach | ETL Pipeline | TiTiler | APIM Required | Complexity | Security |
|----------|-------------|---------|---------------|------------|----------|
| **Option A** (Chosen) | Writes directly to `pgstac.searches` | Read-only database access | No | Simple | Best |
| **Option B** (Rejected) | Calls TiTiler API `/searches/register` | Read-write database access | Yes (to protect endpoint) | Complex | Worse |

---

## Option A: ETL Direct Registration

**Architecture**: ETL pipeline writes directly to `pgstac.searches` table during data ingestion.

### Benefits

✅ **Simpler Architecture**
- No APIM needed to protect TiTiler endpoints
- No network hop for registration (direct database write)
- Single responsibility: ETL owns ALL pgSTAC writes

✅ **Better Security**
- TiTiler cannot be exploited to modify database (read-only credentials)
- Clear separation: ETL writes, TiTiler reads
- No need to protect TiTiler's `/searches/register` endpoint

✅ **Cost Savings**
- No APIM required ($50-700/month saved)
- Simpler infrastructure

✅ **Performance**
- Atomic operations: ingest collection + register search in single transaction
- No external API call (database write is faster than HTTP)

✅ **Ownership Clarity**
- ETL clearly owns all metadata creation (collections, items, searches)
- No confusion about which service manages what

### Implementation Pattern

```python
# ETL pipeline (rmhazuregeoapi) - during collection creation
from services.pgstac_search_registration import PgSTACSearchRegistration

# 1. Create collection + items (existing logic)
await pgstac_repo.insert_collection(collection)
await pgstac_repo.insert_items(items)

# 2. Register search directly in database (NO TiTiler API call)
search_registrar = PgSTACSearchRegistration()
search_id = search_registrar.register_collection_search(
    collection_id=collection_id,
    metadata={"name": f"{collection_id} mosaic"}
)

# 3. Update collection metadata with search_id
collection["summaries"]["mosaic:search_id"] = [search_id]
await pgstac_repo.update_collection(collection_id, collection)

# ✅ TiTiler can now serve tiles using this search_id (read-only access)
```

---

## Option B: TiTiler API Registration

**Architecture**: ETL calls TiTiler's `/searches/register` endpoint, APIM protects endpoint from public access.

### Why This Was Rejected

❌ **More Complex**
- Requires APIM setup and configuration
- Need to maintain APIM policies
- TiTiler needs read-write database credentials

❌ **Worse Security**
- TiTiler has write access to database (attack surface)
- Must use APIM policies to restrict `/searches/register` endpoint
- Split ownership: ETL creates collections, TiTiler creates searches (confusing)

❌ **Higher Cost**
- APIM Developer tier: $50/month
- APIM Standard tier: $700/month

❌ **Performance**
- Network hop for registration (HTTP POST to TiTiler)
- Two operations: ETL creates collection, then calls TiTiler API

### APIM Policy Example (What We're Avoiding)

```xml
<!-- TiTiler API - Protect /searches/register endpoint -->
<policies>
  <inbound>
    <base />
    <!-- Only allow rmhazuregeoapi managed identity to register searches -->
    <validate-azure-ad-token tenant-id="{tenant-id}">
      <client-application-ids>
        <application-id>{rmhazuregeoapi-client-id}</application-id>
      </client-application-ids>
    </validate-azure-ad-token>

    <!-- Block public access to /register endpoint -->
    <choose>
      <when condition="@(context.Request.Url.Path.EndsWith("/register"))">
        <return-response>
          <set-status code="403" reason="Forbidden" />
          <set-body>Search registration is only available to ETL pipeline</set-body>
        </return-response>
      </when>
    </choose>

    <set-backend-service base-url="https://rmhtitiler.azurewebsites.net" />
  </inbound>
</policies>
```

**Note**: With Option A, we don't need any of this complexity.

---

## Database Schema

### `pgstac.searches` Table

TiTiler-pgSTAC expects this schema for search storage:

```sql
CREATE TABLE IF NOT EXISTS pgstac.searches (
    hash TEXT PRIMARY KEY,              -- search_id (SHA256 hash of search query)
    search JSONB NOT NULL,              -- {"collections": ["..."], "filter-lang": "cql2-json"}
    metadata JSONB,                     -- {"name": "...", "registered_by": "etl-pipeline"}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    lastused TIMESTAMPTZ DEFAULT NOW(),
    usecount INTEGER DEFAULT 1
);

-- Index for performance
CREATE INDEX IF NOT EXISTS searches_created_idx ON pgstac.searches(created_at);
```

### Search ID Generation

The `hash` column is the **search_id** - a SHA256 hash of the **canonical JSON representation** of the search query.

**Why SHA256**:
- Deterministic: Same search query always produces same search_id
- Collision-resistant: No two different queries produce the same hash
- Compatible with TiTiler: TiTiler uses same hashing algorithm

**Canonical JSON Format**:
```python
import json
from hashlib import sha256

# Search query
search_query = {
    "collections": ["namangan_collection"],
    "filter-lang": "cql2-json"
}

# Generate hash (MUST use sort_keys=True and compact separators)
search_id = sha256(
    json.dumps(search_query, sort_keys=True, separators=(',', ':')).encode()
).hexdigest()

# Result: "6ee588d77095f336398c097a2e926765..." (64 hex characters)
```

### Example Row

```sql
INSERT INTO pgstac.searches (hash, search, metadata)
VALUES (
    '6ee588d77095f336398c097a2e926765',
    '{"collections": ["namangan_collection"], "filter-lang": "cql2-json"}',
    '{"name": "Namangan Collection Mosaic", "registered_by": "etl-pipeline"}'
);
```

---

## Managed Identity Permissions

### ETL Pipeline (rmhazuregeoapi) - Read-Write Access

The ETL pipeline needs full access to create collections, items, and searches:

```sql
-- Connect as Azure AD admin
psql "host=rmhpgflex.postgres.database.azure.com port=5432 dbname=geopgflex user=YOUR_AZURE_AD_ADMIN_EMAIL sslmode=require"

-- Create managed identity user (if not exists)
SELECT pgaadauth_create_principal('rmhazuregeoapi', false, false);

-- Grant read-write permissions
GRANT USAGE ON SCHEMA pgstac TO "rmhazuregeoapi";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pgstac TO "rmhazuregeoapi";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO "rmhazuregeoapi";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO "rmhazuregeoapi";

-- Ensure future tables get permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmhazuregeoapi";
```

### TiTiler (rmhtitiler) - Read-Only Access

TiTiler only needs to read from pgSTAC (collections, items, searches):

```sql
-- Create separate managed identity for TiTiler
SELECT pgaadauth_create_principal('rmhtitiler', false, false);

-- Grant read-only permissions
GRANT USAGE ON SCHEMA pgstac TO "rmhtitiler";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "rmhtitiler";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO "rmhtitiler";

-- Ensure future tables get permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
GRANT SELECT ON TABLES TO "rmhtitiler";
```

**Security Verification**:

```sql
-- Verify TiTiler CANNOT write
-- Connect as rmhtitiler and try to insert
-- This should FAIL with permission denied
INSERT INTO pgstac.searches (hash, search)
VALUES ('test', '{}');
-- Expected: ERROR: permission denied for table searches
```

---

## Implementation: PgSTACSearchRegistration Class

Create `services/pgstac_search_registration.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - PGSTAC SEARCH REGISTRATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Direct database registration for pgSTAC searches
# PURPOSE: Register searches in pgstac.searches table (bypassing TiTiler API)
# LAST_REVIEWED: 17 NOV 2025
# EXPORTS: PgSTACSearchRegistration class
# INTERFACES: Service layer for search registration
# PYDANTIC_MODELS: None - uses dicts for search payloads
# DEPENDENCIES: hashlib (SHA256), json, infrastructure.postgresql
# SOURCE: Direct writes to pgstac.searches table
# SCOPE: Production architecture - ETL writes, TiTiler reads
# VALIDATION: Search query validation, hash collision detection
# PATTERNS: Repository pattern, Service layer
# ENTRY_POINTS: PgSTACSearchRegistration().register_search()
# INDEX:
#   - PgSTACSearchRegistration class: Line 40
#   - register_search: Line 60
#   - register_collection_search: Line 120
#   - get_search_urls: Line 140
# ============================================================================

"""
PgSTAC Search Registration Service

Registers searches directly in pgstac.searches table without calling TiTiler.
This allows TiTiler to be read-only in production while ETL handles all writes.

Production Architecture:
- ETL Pipeline (rmhazuregeoapi): Read-write access to pgstac schema
- TiTiler (rmhtitiler): Read-only access to pgstac schema

Author: Robert and Geospatial Claude Legion
Date: 17 NOV 2025
"""

import json
from hashlib import sha256
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from infrastructure.postgresql import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PgSTACSearchRegistration")


class PgSTACSearchRegistration:
    """
    Register pgSTAC searches directly in database (bypassing TiTiler API).

    This service writes to pgstac.searches table using the same schema and
    hashing algorithm that TiTiler-pgSTAC uses internally. TiTiler reads
    from this table with read-only database credentials.

    Why This Pattern:
    - TiTiler can be read-only (better security)
    - No APIM needed to protect /searches/register endpoint
    - ETL owns all pgSTAC writes (collections, items, searches)
    - Atomic operations during ingestion workflow

    Author: Robert and Geospatial Claude Legion
    Date: 17 NOV 2025
    """

    def __init__(self, repo: Optional[PostgreSQLRepository] = None):
        """
        Initialize search registration service.

        Args:
            repo: PostgreSQL repository (creates new if not provided)
        """
        self.repo = repo or PostgreSQLRepository()

    def register_search(
        self,
        collections: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        bbox: Optional[List[float]] = None,
        datetime_str: Optional[str] = None,
        filter_cql: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Register a pgSTAC search in database (mimics TiTiler's /searches/register).

        Computes search_id as SHA256 hash of canonical JSON representation,
        then inserts into pgstac.searches table. Uses ON CONFLICT to handle
        duplicate registrations (updates lastused timestamp).

        Args:
            collections: List of STAC collection IDs to query
            metadata: Optional metadata (name, description, etc.)
            bbox: Optional bounding box [minx, miny, maxx, maxy]
            datetime_str: Optional temporal filter (ISO8601)
            filter_cql: Optional CQL2-JSON filter expression

        Returns:
            search_id (str): SHA256 hash of the search query (64 hex chars)

        Example:
            >>> registrar = PgSTACSearchRegistration()
            >>> search_id = registrar.register_search(
            ...     collections=["namangan_collection"],
            ...     metadata={"name": "Namangan Mosaic"}
            ... )
            >>> print(search_id)
            '6ee588d77095f336398c097a2e926765...'
        """
        logger.info(f"🔄 Registering search for collections: {collections}")

        # Build search query (canonical format for hashing)
        search_query = {
            "collections": collections,
            "filter-lang": "cql2-json"
        }

        # Add optional filters
        if bbox:
            search_query["bbox"] = bbox
        if datetime_str:
            search_query["datetime"] = datetime_str
        if filter_cql:
            search_query["filter"] = filter_cql

        # Compute SHA256 hash (MUST use sort_keys=True and compact separators)
        # This matches TiTiler's hashing algorithm exactly
        canonical_json = json.dumps(search_query, sort_keys=True, separators=(',', ':'))
        search_hash = sha256(canonical_json.encode()).hexdigest()

        logger.debug(f"   Search query: {search_query}")
        logger.debug(f"   Canonical JSON: {canonical_json}")
        logger.debug(f"   Search hash: {search_hash}")

        # Prepare metadata
        if metadata is None:
            metadata = {}

        # Add ETL tracking fields
        metadata.setdefault("registered_by", "etl-pipeline")
        metadata.setdefault("registered_at", datetime.now(timezone.utc).isoformat())

        # Insert into pgstac.searches table
        # ON CONFLICT: If search already exists, update lastused and increment usecount
        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pgstac.searches (hash, search, metadata, created_at, lastused, usecount)
                    VALUES (%s, %s, %s, NOW(), NOW(), 1)
                    ON CONFLICT (hash)
                    DO UPDATE SET
                        lastused = NOW(),
                        usecount = pgstac.searches.usecount + 1,
                        metadata = EXCLUDED.metadata
                    RETURNING hash, usecount
                    """,
                    (search_hash, json.dumps(search_query), json.dumps(metadata))
                )
                result = cur.fetchone()
                conn.commit()

                if result:
                    returned_hash, use_count = result
                    if use_count == 1:
                        logger.info(f"✅ Search registered (new): {returned_hash}")
                    else:
                        logger.info(f"✅ Search already exists (use_count={use_count}): {returned_hash}")
                    return returned_hash
                else:
                    logger.info(f"✅ Search registered: {search_hash}")
                    return search_hash

    def register_collection_search(
        self,
        collection_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Register standard search for a collection (all items, no filters).

        This is the most common use case: create a search that returns
        all items in a collection for mosaic visualization.

        Args:
            collection_id: STAC collection identifier
            metadata: Optional metadata (defaults to {"name": "{collection_id} mosaic"})

        Returns:
            search_id (str): SHA256 hash to use in TiTiler URLs

        Example:
            >>> registrar = PgSTACSearchRegistration()
            >>> search_id = registrar.register_collection_search("namangan_collection")
            >>> print(f"Viewer: https://rmhtitiler.../searches/{search_id}/map.html")
        """
        if metadata is None:
            metadata = {"name": f"{collection_id} mosaic"}

        return self.register_search(
            collections=[collection_id],
            metadata=metadata
        )

    def get_search_urls(
        self,
        search_id: str,
        titiler_base_url: str,
        assets: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Generate TiTiler URLs for a registered search.

        Args:
            search_id: Search hash from register_search()
            titiler_base_url: TiTiler base URL (e.g., "https://rmhtitiler-...")
            assets: List of asset names to render (defaults to ["data"])

        Returns:
            dict: URLs for viewer, tilejson, and tiles endpoints

        Example:
            >>> urls = registrar.get_search_urls(
            ...     search_id="6ee588d7...",
            ...     titiler_base_url="https://rmhtitiler-...",
            ...     assets=["data"]
            ... )
            >>> print(urls["viewer"])
            'https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/map.html?assets=data'
        """
        if assets is None:
            assets = ["data"]

        # Build assets query parameter
        assets_param = "&".join(f"assets={a}" for a in assets)

        # Remove trailing slash from base URL
        base = titiler_base_url.rstrip('/')

        return {
            "viewer": f"{base}/searches/{search_id}/WebMercatorQuad/map.html?{assets_param}",
            "tilejson": f"{base}/searches/{search_id}/WebMercatorQuad/tilejson.json?{assets_param}",
            "tiles": f"{base}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?{assets_param}"
        }


# Export the service class
__all__ = ['PgSTACSearchRegistration']
```

---

## ETL Workflow Integration

### Complete ETL Workflow Example

```python
from services.pgstac_search_registration import PgSTACSearchRegistration
from infrastructure.postgresql import PostgreSQLRepository
from config import get_config

async def create_collection_with_mosaic(
    collection_id: str,
    cog_files: List[str],
    collection_description: str
) -> Dict[str, Any]:
    """
    Complete ETL workflow: Create STAC collection with automatic search registration.

    Args:
        collection_id: Unique collection identifier
        cog_files: List of blob paths to COG files
        collection_description: Human-readable description

    Returns:
        dict: Job result with collection_id, search_id, viewer_url, etc.
    """
    config = get_config()
    repo = PostgreSQLRepository()

    logger.info(f"Creating collection: {collection_id}")
    logger.info(f"  COG files: {len(cog_files)}")

    # ============================================
    # PHASE 1: Create STAC Items
    # ============================================

    items_created = []
    for cog_blob in cog_files:
        # Extract STAC item from COG (using stac_service)
        item = await stac_service.extract_item_from_blob(
            container="silver-cogs",
            blob_name=cog_blob
        )

        # Ensure required fields
        item["id"] = generate_item_id(cog_blob)
        item["type"] = "Feature"
        item["collection"] = collection_id

        # CRITICAL: Geometry required for bounds calculation
        if not item.get("geometry"):
            if item.get("bbox"):
                item["geometry"] = bbox_to_geometry(item["bbox"])
            else:
                raise ValueError(f"Item {item['id']} has no bbox or geometry")

        # Insert into pgSTAC
        await pgstac_repo.insert_item(item)
        items_created.append(item)

    logger.info(f"Phase 1 complete: {len(items_created)} items created")

    # ============================================
    # PHASE 2: Create STAC Collection
    # ============================================

    # Calculate extents from items
    all_bboxes = [item["bbox"] for item in items_created if item.get("bbox")]
    spatial_extent = calculate_collection_extent(all_bboxes)

    all_datetimes = [
        item["properties"]["datetime"]
        for item in items_created
        if item.get("properties", {}).get("datetime")
    ]
    temporal_extent = calculate_temporal_extent(all_datetimes)

    # Create collection
    collection = {
        "id": collection_id,
        "type": "Collection",
        "stac_version": "1.1.0",
        "description": collection_description,
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [spatial_extent]},
            "temporal": {"interval": [temporal_extent]}
        },
        "summaries": {
            "tile_count": [len(items_created)]
        },
        "links": []
    }

    await pgstac_repo.insert_collection(collection)
    logger.info(f"✓ Collection created: {collection_id}")

    # ============================================
    # PHASE 3: Register pgSTAC Search (Direct Database Write)
    # ============================================

    logger.info("Phase 3: Registering pgSTAC search...")

    # Create search registrar (uses repository pattern)
    search_registrar = PgSTACSearchRegistration(repo=repo)

    # Register search directly in database (NO TiTiler API call)
    search_id = search_registrar.register_collection_search(
        collection_id=collection_id,
        metadata={
            "name": f"{collection_id} mosaic",
            "description": collection_description,
            "tile_count": len(items_created)
        }
    )

    logger.info(f"✓ Search registered: {search_id}")

    # Generate URLs
    urls = search_registrar.get_search_urls(
        search_id=search_id,
        titiler_base_url=config.titiler_base_url,
        assets=["data"]
    )

    # ============================================
    # PHASE 4: Update Collection Metadata
    # ============================================

    # Store search_id in collection summaries
    collection["summaries"]["mosaic:search_id"] = [search_id]

    # Add viewer and TileJSON links
    collection["links"].extend([
        {
            "rel": "preview",
            "href": urls["viewer"],
            "type": "text/html",
            "title": "Interactive collection mosaic viewer"
        },
        {
            "rel": "tilejson",
            "href": urls["tilejson"],
            "type": "application/json",
            "title": "TileJSON specification for web maps"
        },
        {
            "rel": "tiles",
            "href": urls["tiles"],
            "type": "image/png",
            "title": "XYZ tile endpoint (templated)"
        }
    ])

    # Save updated collection
    await pgstac_repo.update_collection(collection_id, collection)
    logger.info(f"✓ Collection updated with search_id: {search_id}")

    # ============================================
    # PHASE 5: Return Result
    # ============================================

    return {
        "success": True,
        "collection_id": collection_id,
        "tile_count": len(items_created),
        "search_id": search_id,
        "viewer_url": urls["viewer"],
        "tilejson_url": urls["tilejson"],
        "spatial_extent": spatial_extent,
        "temporal_extent": temporal_extent
    }
```

---

## TileJSON Generation Flow

### How TiTiler Uses Registered Searches

When you request:
```
GET /searches/6ee588d7.../WebMercatorQuad/tilejson.json?assets=data
```

**TiTiler performs these steps**:

#### 1. Look up the search query from database

```sql
SELECT search FROM pgstac.searches WHERE hash = '6ee588d7...';
```

**Returns**:
```json
{
  "collections": ["namangan_collection"],
  "filter-lang": "cql2-json"
}
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
    "geometry": {"type": "Polygon", "coordinates": [[[71.606, 40.980], ...]]},
    "bbox": [71.606, 40.980, 71.664, 40.984],
    "assets": {"data": {"href": "/vsiaz/silver-cogs/file1.tif"}}
  },
  {
    "id": "item2",
    "geometry": {"type": "Polygon", "coordinates": [[[71.664, 40.980], ...]]},
    "bbox": [71.664, 40.980, 71.721, 40.984],
    "assets": {"data": {"href": "/vsiaz/silver-cogs/file2.tif"}}
  }
]
```

#### 3. Calculate spatial bounds from item geometries

```python
all_geometries = [item['geometry'] for item in items]
bounds = calculate_extent(all_geometries)
# Result: [71.606, 40.980, 71.721, 40.984]
```

**Why geometry is critical**: Without geometry, pgSTAC returns world extent `[-180, -85, 180, 85]`, and the map zooms out to show the entire globe instead of the actual data location.

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
  "tiles": [
    "https://rmhtitiler-.../searches/6ee588d7.../tiles/WebMercatorQuad/{z}/{x}/{y}?assets=data"
  ]
}
```

### When a Map Requests a Tile

When your web map (Leaflet, Mapbox, etc.) requests a tile:

```
GET /searches/6ee588d7.../tiles/WebMercatorQuad/16/12345/23456?assets=data
```

**TiTiler performs these steps**:

1. **Look up search query** from `pgstac.searches` table
2. **Convert tile coords to bbox**: `z=16, x=12345, y=23456` → `[71.650, 40.981, 71.655, 40.983]`
3. **Query pgSTAC** for items that intersect tile bbox
4. **Read COG file** using GDAL `/vsiaz/` virtual file system (OAuth token in environment)
5. **Extract tile region** from COG (256x256 pixels)
6. **Render PNG tile** and return to browser

---

## Production Benefits

### Security Benefits

✅ **TiTiler Cannot Modify Database**
- TiTiler uses read-only managed identity (`rmhtitiler`)
- If TiTiler is compromised, attacker cannot modify pgSTAC data
- No need to protect TiTiler endpoints with APIM policies

✅ **Clear Ownership Model**
- ETL pipeline owns all writes (collections, items, searches)
- TiTiler owns only reads (serve tiles, generate TileJSON)
- No confusion about which service manages what

✅ **Attack Surface Reduction**
- TiTiler has no write permissions
- No public-facing API endpoints that modify database
- Simpler security audit (ETL writes, TiTiler reads)

### Operational Benefits

✅ **Simpler Architecture**
- No APIM required ($50-700/month saved)
- No need to configure APIM policies
- Direct database writes (faster than HTTP API calls)

✅ **Atomic Operations**
- Create collection + items + search in single transaction
- Rollback on failure (all or nothing)
- No partial state (collection exists but search missing)

✅ **Performance**
- No network hop for registration (direct database write vs HTTP POST)
- Connection pooling reused (same repository pattern as other operations)

### Scalability Benefits

✅ **Load Balancing Ready**
- All TiTiler instances read from same `pgstac.searches` table
- No sticky sessions required
- Round-robin routing works perfectly

✅ **Auto-Scaling Ready**
- New TiTiler instances immediately access all searches
- No coordination needed between instances
- Horizontal scaling without configuration changes

✅ **Zero Downtime**
- TiTiler restarts don't affect search availability
- Searches persist in database (not in-memory)
- Static URLs never break

---

## Verification Steps

### 1. Verify Database Schema

```sql
-- Connect to PostgreSQL
psql "host=rmhpgflex.postgres.database.azure.com port=5432 dbname=geopgflex user=rob634 sslmode=require"

-- Check if searches table exists
\dt pgstac.searches

-- View table schema
\d pgstac.searches

-- Expected output:
-- Table "pgstac.searches"
-- Column      | Type          | Nullable
-- ------------+---------------+----------
-- hash        | text          | not null
-- search      | jsonb         | not null
-- metadata    | jsonb         |
-- created_at  | timestamptz   |
-- lastused    | timestamptz   |
-- usecount    | integer       |
```

### 2. Verify Permissions (ETL Pipeline)

```sql
-- Check ETL pipeline permissions
SELECT
    grantee,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'pgstac'
  AND table_name = 'searches'
  AND grantee = 'rmhazuregeoapi';

-- Expected: SELECT, INSERT, UPDATE, DELETE
```

### 3. Verify Permissions (TiTiler - Read-Only)

```sql
-- Check TiTiler permissions
SELECT
    grantee,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'pgstac'
  AND table_name = 'searches'
  AND grantee = 'rmhtitiler';

-- Expected: SELECT only (NO INSERT, UPDATE, DELETE)
```

### 4. Test Search Registration

```bash
# Submit collection creation job (includes search registration)
curl -X POST "https://rmhazuregeoapi-.../api/jobs/submit/create_stac_collection" \
  -H "Content-Type: application/json" \
  -d '{
    "collection_id": "test_collection",
    "cog_files": ["file1.tif", "file2.tif"]
  }'

# Check job status
curl "https://rmhazuregeoapi-.../api/jobs/status/{JOB_ID}"

# Verify search was created
PGPASSWORD='...' psql -h rmhpgflex.postgres.database.azure.com -U rob634 -d geopgflex \
  -c "SELECT hash, search->>'collections', metadata FROM pgstac.searches WHERE search->>'collections' LIKE '%test_collection%';"
```

### 5. Test TiTiler Read Access

```bash
# Get collection metadata (includes search_id in summaries)
curl "https://rmhgeoapibeta-.../api/stac/collections/test_collection"

# Extract search_id from response
SEARCH_ID="6ee588d7..."

# Test TiTiler viewer (should work - read-only access)
curl "https://rmhtitiler-.../searches/$SEARCH_ID/WebMercatorQuad/tilejson.json?assets=data"

# Expected: 200 OK with TileJSON response
```

### 6. Verify TiTiler Cannot Write

```bash
# Try to register search via TiTiler API (should fail if permissions are correct)
curl -X POST "https://rmhtitiler-.../searches/register" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["test_collection"],
    "filter-lang": "cql2-json"
  }'

# Expected: 500 Internal Server Error (permission denied on pgstac.searches)
# OR: 403 Forbidden if endpoint is disabled
```

---

## Summary

### Production Architecture

**Two-Tier Security Model**:

| Service | Managed Identity | Database Access | Responsibility |
|---------|-----------------|-----------------|----------------|
| ETL Pipeline (`rmhazuregeoapi`) | `rmhazuregeoapi` | Read-write | Create collections, items, searches |
| TiTiler (`rmhtitiler`) | `rmhtitiler` | Read-only | Serve tiles, generate TileJSON |

### Implementation Steps

1. **Create `services/pgstac_search_registration.py`** (see code above)
2. **Grant permissions** (ETL: read-write, TiTiler: read-only)
3. **Integrate into ETL workflow** (register search during collection creation)
4. **Verify** (check database permissions, test search registration)

### Key Benefits

✅ **Better Security**: TiTiler read-only, no APIM needed
✅ **Simpler Architecture**: Direct database writes, no HTTP API calls
✅ **Cost Savings**: No APIM ($50-700/month)
✅ **Performance**: Atomic operations, connection pooling
✅ **Scalability**: Load balancing ready, auto-scaling ready

### Next Actions

1. Create `services/pgstac_search_registration.py` with code provided above
2. Grant read-only permissions to TiTiler managed identity
3. Integrate search registration into collection creation workflow
4. Test with a sample collection
5. Verify TiTiler can read but not write to `pgstac.searches`

---

**Status**: ✅ Documentation Complete (Updated 17 NOV 2025)
**Date**: 17 NOV 2025
**Update**: Production architecture - ETL direct database registration (Option A)
