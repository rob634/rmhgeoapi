# STAC Integration Strategy

**Date**: 18 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Design Document

---

## 🎯 Overview

STAC serves **two distinct audiences** with different collection structures:

1. **Internal STAC** - Operational tracking (full detail, all tiles)
2. **User-Facing STAC** - Simplified catalog (logical datasets only)

**Philosophy**: "Pay no attention to the tiles behind the curtain" - users see datasets, not implementation details.

---

## 📊 Two-Layer Architecture

### **Layer 1: ETL Outputs** (What we create)
- PostGIS tables (vector data)
- COG files (raster tiles)
- MosaicJSON (combined raster views)

### **Layer 2: OGC APIs** (What we serve) - FUTURE
- OGC API Features (vector serving from PostGIS)
- OGC API Tiles (MVT from PostGIS)
- OGC API Coverages (raster serving from COGs)

**Both layers get STAC catalogs**, but with different granularity.

---

## 🗂️ STAC Collection Structure

### **Internal Collections** (Operational Tracking)

#### `internal-vectors`
**Purpose**: Track every PostGIS table created by ETL
**Granularity**: One STAC Item per table
**Who sees it**: Operations team, debugging, audit trail

**Example Items**:
```
internal-vectors/kba_shp_20251018_143022
internal-vectors/acled_csv_20251018_150134
internal-vectors/roads_gpkg_20251018_152045
```

**STAC Item Structure**:
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "kba_shp_20251018_143022",
  "collection": "internal-vectors",
  "geometry": {...bbox...},
  "properties": {
    "datetime": "2025-10-18T14:30:22Z",
    "created": "2025-10-18T14:30:22Z",
    "vector:feature_count": 12228,
    "vector:geometry_types": ["MultiPolygon"],
    "vector:source_format": "shapefile",
    "vector:source_file": "kba_shp.zip",
    "etl:job_id": "abc123...",
    "etl:stage_completed": 2,
    "etl:chunk_count": 17,
    "etl:processing_time_seconds": 45
  },
  "assets": {
    "postgis": {
      "href": "postgresql://rmhpgflex.postgres.database.azure.com/geo.kba_test",
      "type": "application/vnd.postgresql",
      "title": "PostGIS table: geo.kba_test",
      "roles": ["data"],
      "table:schema": "geo",
      "table:name": "kba_test",
      "table:row_count": 12228
    }
  },
  "links": [
    {
      "rel": "collection",
      "href": "/api/stac/collections/internal-vectors"
    }
  ]
}
```

---

#### `internal-rasters`
**Purpose**: Track every COG tile and MosaicJSON created by ETL
**Granularity**: One STAC Item per tile + one for MosaicJSON
**Who sees it**: Operations team, tile debugging

**Example Items**:
```
internal-rasters/maxar_tile_00_00_20251018_160022  (individual tile)
internal-rasters/maxar_tile_00_01_20251018_160023  (individual tile)
...
internal-rasters/maxar_mosaic_20251018_160145     (MosaicJSON combining all tiles)
```

**Tile STAC Item**:
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "maxar_tile_00_00_20251018_160022",
  "collection": "internal-rasters",
  "geometry": {...tile bbox...},
  "properties": {
    "datetime": "2025-10-18T16:00:22Z",
    "raster:bands": [...],
    "proj:epsg": 4326,
    "tile:x": 0,
    "tile:y": 0,
    "tile:parent_mosaic": "maxar_mosaic_20251018_160145",
    "etl:source_file": "maxar_20231015.tif",
    "etl:tier": "visualization",
    "etl:compression": "JPEG",
    "etl:job_id": "xyz789..."
  },
  "assets": {
    "cog": {
      "href": "https://rmhazuregeosilver.blob.core.windows.net/cogs/visualization/maxar_tile_00_00.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Visualization tier COG (JPEG 85%)",
      "roles": ["data", "visual"],
      "raster:bands": [...]
    }
  }
}
```

**MosaicJSON STAC Item**:
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "maxar_mosaic_20251018_160145",
  "collection": "internal-rasters",
  "geometry": {...full extent bbox...},
  "properties": {
    "datetime": "2025-10-18T16:01:45Z",
    "mosaic:tile_count": 40,
    "mosaic:tiles": [
      "maxar_tile_00_00_20251018_160022",
      "maxar_tile_00_01_20251018_160023",
      "..."
    ],
    "etl:source_file": "maxar_20231015.tif",
    "etl:tier": "visualization",
    "etl:job_id": "xyz789..."
  },
  "assets": {
    "mosaicjson": {
      "href": "https://rmhazuregeosilver.blob.core.windows.net/mosaics/maxar_mosaic.json",
      "type": "application/json",
      "title": "MosaicJSON combining 40 tiles",
      "roles": ["metadata"]
    }
  }
}
```

---

### **User-Facing Collections** (Simplified Catalog)

#### `datasets-vector`
**Purpose**: Logical vector datasets users can discover
**Granularity**: One STAC Item per logical dataset (NOT per table)
**Who sees it**: End users, external applications

**Example Items**:
```
datasets-vector/kenya_protected_areas
datasets-vector/acled_conflict_events
datasets-vector/road_network
```

**STAC Item Structure**:
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "kenya_protected_areas",
  "collection": "datasets-vector",
  "geometry": {...bbox...},
  "properties": {
    "title": "Kenya Protected Areas (KBA)",
    "description": "Key Biodiversity Areas in Kenya",
    "datetime": "2025-10-18T14:30:22Z",
    "created": "2025-10-18T14:30:22Z",
    "updated": "2025-10-18T14:30:22Z",
    "license": "proprietary",
    "providers": [
      {
        "name": "WDPA",
        "roles": ["producer"]
      }
    ],
    "vector:feature_count": 12228,
    "vector:geometry_types": ["MultiPolygon"]
  },
  "assets": {
    "ogc_features": {
      "href": "https://vectorapi.example.com/collections/kenya_protected_areas/items",
      "type": "application/geo+json",
      "title": "OGC API Features endpoint",
      "roles": ["data"],
      "api:specification": "OGC API - Features"
    },
    "ogc_tiles": {
      "href": "https://vectorapi.example.com/collections/kenya_protected_areas/tiles/{tileMatrixSetId}/{tileMatrix}/{tileRow}/{tileCol}",
      "type": "application/vnd.mapbox-vector-tile",
      "title": "OGC API Tiles endpoint (MVT)",
      "roles": ["data"],
      "api:specification": "OGC API - Tiles"
    }
  },
  "links": [
    {
      "rel": "derived_from",
      "href": "/api/stac/collections/internal-vectors/items/kba_shp_20251018_143022",
      "title": "Source ETL output"
    }
  ]
}
```

---

#### `datasets-raster`
**Purpose**: Logical raster datasets users can discover
**Granularity**: One STAC Item per logical dataset (references MosaicJSON, hides tiles)
**Who sees it**: End users, external applications

**Example Items**:
```
datasets-raster/maxar_imagery_20231015
datasets-raster/sentinel2_composite_q3_2024
```

**STAC Item Structure**:
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "maxar_imagery_20231015",
  "collection": "datasets-raster",
  "geometry": {...bbox...},
  "properties": {
    "title": "Maxar Satellite Imagery - October 2023",
    "description": "High-resolution satellite imagery covering region XYZ",
    "datetime": "2023-10-15T00:00:00Z",
    "created": "2025-10-18T16:01:45Z",
    "gsd": 0.5,
    "platform": "Maxar WorldView-3",
    "instruments": ["WV110"],
    "eo:cloud_cover": 5,
    "raster:bands": [...]
  },
  "assets": {
    "visualization": {
      "href": "https://rasterapi.example.com/cog/maxar_mosaic_viz",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Visualization tier (web mapping optimized)",
      "roles": ["visual"],
      "tier": "visualization",
      "compression": "JPEG",
      "file_size_mb": 17
    },
    "analysis": {
      "href": "https://rasterapi.example.com/cog/maxar_mosaic_analysis",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Analysis tier (lossless)",
      "roles": ["data"],
      "tier": "analysis",
      "compression": "DEFLATE",
      "file_size_mb": 50
    },
    "archive": {
      "href": "https://rasterapi.example.com/cog/maxar_mosaic_archive",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Archive tier (regulatory compliance)",
      "roles": ["archive"],
      "tier": "archive",
      "compression": "LZW",
      "file_size_mb": 180
    }
  },
  "links": [
    {
      "rel": "derived_from",
      "href": "/api/stac/collections/internal-rasters/items/maxar_mosaic_20251018_160145",
      "title": "Source MosaicJSON"
    }
  ]
}
```

---

## 🔄 ETL Integration Points

### **Vector ETL** (`ingest_vector` job)

**Current Stages**:
1. Stage 1: Prepare chunks (download, validate, pickle)
2. Stage 2: Upload chunks to PostGIS (parallel)

**Add Stage 3**: Create STAC records

```python
# Stage 3: Create STAC Records
{
    "number": 3,
    "name": "create_stac_records",
    "task_type": "create_vector_stac",
    "description": "Create internal STAC record for PostGIS table",
    "parallelism": "single"
}
```

**Stage 3 Task Handler** (`services/stac_vector_catalog.py`):
```python
def create_vector_stac(params):
    """
    Create internal STAC Item for completed PostGIS table.

    Args:
        params: {
            "table_name": "kba_test",
            "schema": "geo",
            "job_id": "abc123...",
            "source_file": "kba_shp.zip",
            "source_format": "shapefile"
        }
    """
    # Extract metadata from PostGIS
    metadata = extract_postgis_metadata(
        schema=params["schema"],
        table=params["table_name"]
    )

    # Create STAC Item
    stac_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": f"{params['table_name']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        "collection": "internal-vectors",
        "geometry": metadata["bbox_geojson"],
        "properties": {
            "datetime": datetime.utcnow().isoformat() + "Z",
            "vector:feature_count": metadata["feature_count"],
            "vector:geometry_types": metadata["geometry_types"],
            "vector:source_format": params["source_format"],
            "vector:source_file": params["source_file"],
            "etl:job_id": params["job_id"]
        },
        "assets": {
            "postgis": {
                "href": f"postgresql://rmhpgflex.postgres.database.azure.com/{params['schema']}.{params['table_name']}",
                "type": "application/vnd.postgresql",
                "table:schema": params["schema"],
                "table:name": params["table_name"],
                "table:row_count": metadata["feature_count"]
            }
        }
    }

    # Insert into PgSTAC
    insert_stac_item(stac_item, collection="internal-vectors")

    return {"success": True, "stac_id": stac_item["id"]}
```

**Helper Function** (extract PostGIS metadata):
```python
def extract_postgis_metadata(schema: str, table: str) -> dict:
    """
    Extract metadata from PostGIS table for STAC record.

    Returns:
        {
            "feature_count": 12228,
            "bbox": [minx, miny, maxx, maxy],
            "bbox_geojson": {...},
            "geometry_types": ["MultiPolygon"],
            "crs": "EPSG:4326"
        }
    """
    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cur:
            # Feature count
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table)
            ))
            feature_count = cur.fetchone()[0]

            # Bounding box (ST_Extent returns BOX format)
            cur.execute(sql.SQL("""
                SELECT
                    ST_XMin(extent) as minx,
                    ST_YMin(extent) as miny,
                    ST_XMax(extent) as maxx,
                    ST_YMax(extent) as maxy
                FROM (
                    SELECT ST_Extent(geometry) as extent
                    FROM {}.{}
                ) t
            """).format(
                sql.Identifier(schema),
                sql.Identifier(table)
            ))
            row = cur.fetchone()
            bbox = [row[0], row[1], row[2], row[3]]

            # Convert bbox to GeoJSON polygon
            bbox_geojson = {
                "type": "Polygon",
                "coordinates": [[
                    [bbox[0], bbox[1]],
                    [bbox[2], bbox[1]],
                    [bbox[2], bbox[3]],
                    [bbox[0], bbox[3]],
                    [bbox[0], bbox[1]]
                ]]
            }

            # Geometry types
            cur.execute(sql.SQL("""
                SELECT DISTINCT ST_GeometryType(geometry)
                FROM {}.{}
            """).format(
                sql.Identifier(schema),
                sql.Identifier(table)
            ))
            geom_types = [row[0].replace('ST_', '') for row in cur.fetchall()]

            return {
                "feature_count": feature_count,
                "bbox": bbox,
                "bbox_geojson": bbox_geojson,
                "geometry_types": geom_types,
                "crs": "EPSG:4326"
            }
```

---

### **Raster ETL** (`process_raster` job)

**Current Stages** (assumed):
1. Stage 1: Validate raster
2. Stage 2: Create COG(s)
3. Stage 3: Create STAC record

**Enhancement for Tiled Rasters**:

When a raster is tiled (40 individual COGs + 1 MosaicJSON):

**Option A: Create STAC in Stage 3** (after all COGs created)
```python
# Stage 3: Create STAC Records
def create_raster_stac(params):
    """
    Create internal STAC Items for all COG tiles + MosaicJSON.

    Args:
        params: {
            "job_id": "xyz789...",
            "source_file": "maxar_20231015.tif",
            "tier": "visualization",
            "tiles": [
                {"href": "blob_url", "bbox": [...], "x": 0, "y": 0},
                ...
            ],
            "mosaic_href": "blob_url_to_mosaicjson"
        }
    """
    stac_ids = []

    # Create STAC Item for each tile
    for tile in params["tiles"]:
        tile_item = {
            "id": f"{job_id}_tile_{tile['x']}_{tile['y']}_{timestamp}",
            "collection": "internal-rasters",
            "properties": {
                "tile:x": tile["x"],
                "tile:y": tile["y"],
                "tile:parent_mosaic": f"{job_id}_mosaic_{timestamp}",
                "etl:tier": params["tier"]
            },
            "assets": {
                "cog": {
                    "href": tile["href"],
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized"
                }
            }
        }
        insert_stac_item(tile_item, collection="internal-rasters")
        stac_ids.append(tile_item["id"])

    # Create STAC Item for MosaicJSON
    mosaic_item = {
        "id": f"{job_id}_mosaic_{timestamp}",
        "collection": "internal-rasters",
        "properties": {
            "mosaic:tile_count": len(params["tiles"]),
            "mosaic:tiles": stac_ids,
            "etl:tier": params["tier"]
        },
        "assets": {
            "mosaicjson": {
                "href": params["mosaic_href"],
                "type": "application/json"
            }
        }
    }
    insert_stac_item(mosaic_item, collection="internal-rasters")

    return {"success": True, "tile_count": len(stac_ids), "mosaic_id": mosaic_item["id"]}
```

---

## 🚀 Implementation Phases

### **Phase 1: Internal STAC (Priority 0A)**
**Timeline**: Immediate (before Multi-Tier COG)

- [ ] Create `internal-vectors` collection in PgSTAC
- [ ] Create `internal-rasters` collection in PgSTAC
- [ ] Add Stage 3 to `ingest_vector` job
- [ ] Implement `create_vector_stac` handler
- [ ] Implement `extract_postgis_metadata` helper
- [ ] Test with all 6 vector formats
- [ ] Enhance `process_raster` Stage 3 for COG STAC
- [ ] Test with single COG and tiled COGs

**Deliverable**: Every completed ETL job creates internal STAC records

---

### **Phase 2: User-Facing STAC** (Future - with OGC APIs)
**Timeline**: After Vector API / Raster API are built

- [ ] Create `datasets-vector` collection in PgSTAC
- [ ] Create `datasets-raster` collection in PgSTAC
- [ ] Manual process to promote internal items to user-facing
- [ ] Add metadata enrichment (title, description, license)
- [ ] Link to OGC API endpoints (when available)
- [ ] Public STAC browser interface

**Deliverable**: Simplified catalog for external users

---

## 🔍 Query Patterns

### **Internal Queries** (Operations)

```python
# Find all vector tables created in last 24 hours
GET /api/stac/search?collections=internal-vectors&datetime=2025-10-18T00:00:00Z/..

# Find all COG tiles for specific job
GET /api/stac/search?collections=internal-rasters&etl:job_id=xyz789

# Find MosaicJSON for tiled raster
GET /api/stac/search?collections=internal-rasters&mosaic:tile_count=>0

# Find all visualization tier COGs
GET /api/stac/search?collections=internal-rasters&etl:tier=visualization
```

### **User-Facing Queries** (Future)

```python
# Browse all available vector datasets
GET /api/stac/search?collections=datasets-vector

# Browse all available raster datasets
GET /api/stac/search?collections=datasets-raster

# Spatial search (bbox)
GET /api/stac/search?bbox=-180,-90,180,90

# Temporal search
GET /api/stac/search?datetime=2023-10-01/2023-12-31
```

---

## 📝 Configuration

**Add to `config.py`**:
```python
class AppConfig(BaseSettings):
    # Existing config...

    # STAC Configuration
    stac_internal_vectors_collection: str = "internal-vectors"
    stac_internal_rasters_collection: str = "internal-rasters"
    stac_user_vectors_collection: str = "datasets-vector"
    stac_user_rasters_collection: str = "datasets-raster"

    # PgSTAC connection (reuse PostgreSQL)
    pgstac_connection_string: str = Field(
        alias="PGSTAC_CONNECTION_STRING",
        default=None  # Falls back to postgis_connection_string
    )
```

---

## 🎯 Success Criteria

### **Phase 1 Complete When**:
- [ ] Every `ingest_vector` job creates internal STAC Item
- [ ] Every `process_raster` job creates internal STAC Item(s)
- [ ] Can query all processed vectors via STAC API
- [ ] Can query all processed rasters via STAC API
- [ ] Tile-level tracking works (40 tiles + 1 mosaic)
- [ ] Complete audit trail of ETL outputs

### **Phase 2 Complete When**:
- [ ] User-facing collections exist
- [ ] Simplified items reference internal items
- [ ] OGC API endpoints linked in assets
- [ ] Public STAC browser works
- [ ] Users can discover datasets without seeing tiles

---

## 🚫 Intentional Limitations

**What We're NOT Doing** (for now):
- ❌ User querying of files directly (APIs only)
- ❌ Automatic promotion from internal → user-facing (manual curation)
- ❌ STAC API authentication (rely on Azure AD for now)
- ❌ STAC transactions (create-only, no updates/deletes)
- ❌ Complex relationships (parent/child beyond derived_from)

**Why**: Scope control - build foundation first, expand when needed

---

**Last Updated**: 18 OCT 2025
**Next Review**: After Phase 1 implementation complete
