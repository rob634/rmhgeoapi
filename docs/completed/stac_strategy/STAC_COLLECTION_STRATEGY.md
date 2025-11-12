# STAC Collection Strategy

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Production Collection Architecture

### CRITICAL: Bronze Container is NOT in Production STAC

```
Bronze Container (rmhazuregeobronze)
    ↓
    PRE-ETL RAW DATA (DEV/TEST ONLY)
    ↓
    NOT in STAC catalog

ETL Processing Pipeline
    ↓
    ├─→ Raster ETL → COG (EPSG:4326) → Collection: "cogs"
    ├─→ Vector ETL → PostGIS Tables → Collection: "vectors"
    └─→ Analytics → GeoParquet       → Collection: "geoparquet" (future)
```

## 📦 Production Collections (3 Types)

### 1. Collection: `cogs`
**Purpose**: Cloud-Optimized GeoTIFFs in EPSG:4326

```json
{
    "id": "cogs",
    "title": "Cloud-Optimized GeoTIFFs",
    "description": "Raster data converted to COG format in EPSG:4326 for cloud-native access",
    "summaries": {
        "asset_type": ["raster"],
        "media_type": ["image/tiff; application=geotiff; profile=cloud-optimized"]
    }
}
```

**Items in this collection:**
- All raster data converted to COG format
- Must be in EPSG:4326
- Stored in Silver tier storage
- Queryable via STAC API

**Example Item:**
```json
{
    "id": "sentinel-2-l2a-20251005-tile-12abc",
    "collection": "cogs",
    "geometry": {...},
    "assets": {
        "data": {
            "href": "https://.../silver/sentinel-2-cog.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized"
        }
    }
}
```

---

### 2. Collection: `vectors`
**Purpose**: PostGIS Tables (Queryable Features)

```json
{
    "id": "vectors",
    "title": "Vector Features (PostGIS)",
    "description": "Vector data stored in PostGIS tables, queryable via OGC API - Features",
    "summaries": {
        "asset_type": ["vector"],
        "media_type": ["application/geo+json"]
    }
}
```

**CRITICAL: Vector Files ≠ STAC Assets**

**Architecture:**
```
Vector File Upload (Bronze)
    ↓
Load to PostGIS Table (geo schema)
    ↓
One Table = One STAC Collection
    ↓
Each Row = Feature in OGC API - Features (future)
```

**Items in this collection:**
- STAC Collection represents entire PostGIS table
- NOT individual vector files
- NOT individual features (those go to OGC API - Features)
- Collection metadata describes table structure

**Example Collection (for PostGIS table "parcels"):**
```json
{
    "id": "vectors",
    "type": "Collection",
    "description": "PostGIS tables with queryable vector features",
    "links": [
        {
            "rel": "items",
            "type": "application/geo+json",
            "href": "/collections/parcels/items",
            "title": "Features in parcels table"
        }
    ],
    "summaries": {
        "postgis:tables": ["parcels", "buildings", "roads"],
        "feature_count": [10000, 5000, 2000]
    }
}
```

**Rule**: Vector files NEVER appear as STAC Items - they're loaded to PostGIS or rejected as invalid.

---

### 3. Collection: `geoparquet` (Future)
**Purpose**: GeoParquet Analytical Datasets

```json
{
    "id": "geoparquet",
    "title": "GeoParquet Analytical Datasets",
    "description": "Cloud-optimized columnar vector data for analytical queries",
    "summaries": {
        "asset_type": ["vector"],
        "media_type": ["application/x-parquet"]
    }
}
```

**Items in this collection:**
- GeoParquet exports from PostGIS queries
- Analytical result datasets
- Cloud-optimized for Athena/DuckDB queries
- Each file is a STAC Item (unlike other vectors)

**Example Item:**
```json
{
    "id": "sf-building-analysis-2025-q1",
    "collection": "geoparquet",
    "geometry": {...},
    "assets": {
        "data": {
            "href": "https://.../gold/analysis.parquet",
            "type": "application/x-parquet",
            "roles": ["data", "analytics"]
        }
    }
}
```

**Exception**: GeoParquet is the ONLY vector format that appears as STAC Items (because it's cloud-optimized and file-based).

---

### 4. Collection: `dev` (Development Only)
**Purpose**: Generic Collection for Testing

```json
{
    "id": "dev",
    "title": "Development & Testing",
    "description": "Generic collection for development and testing (not for production)",
    "summaries": {
        "asset_type": ["mixed"],
        "media_type": ["application/octet-stream"]
    }
}
```

**Use cases:**
- Testing STAC metadata extraction
- Experimenting with Bronze container data
- Development workflows
- NOT for production

---

## 🛠️ Implementation

### Create Production Collections

```python
from infrastructure.stac import StacInfrastructure

stac = StacInfrastructure()

# Create all production collections
stac.create_production_collection('cogs')
stac.create_production_collection('vectors')
stac.create_production_collection('geoparquet')
stac.create_production_collection('dev')
```

### Determine Collection for Item

```python
# Determine which collection an item belongs to
collection_id = StacInfrastructure.determine_collection('raster')
# → 'cogs'

collection_id = StacInfrastructure.determine_collection('postgis_table')
# → 'vectors'

collection_id = StacInfrastructure.determine_collection('geoparquet')
# → 'geoparquet'

collection_id = StacInfrastructure.determine_collection('dev')
# → 'dev'
```

---

## 🔄 ETL Workflow Integration

### Raster Workflow
```python
# Bronze → Silver ETL
1. Raw GeoTIFF uploaded to Bronze container
2. ETL converts to COG in EPSG:4326
3. COG stored in Silver container
4. STAC Item created in "cogs" collection
5. Item inserted into PgSTAC

# STAC Item
stac_service.extract_item_from_blob(
    container='silver',
    blob_name='sentinel-2-cog.tif',
    collection_id=StacInfrastructure.determine_collection('raster')  # → 'cogs'
)
```

### Vector Workflow
```python
# Bronze → PostGIS ETL
1. Shapefile/GeoJSON uploaded to Bronze container
2. ETL loads to PostGIS table in geo schema
3. PostGIS table metadata added to "vectors" collection summaries
4. Features queryable via OGC API - Features (future)

# NO STAC Item created for individual vector file
# Instead: PostGIS table metadata in collection summaries
```

### GeoParquet Workflow (Future)
```python
# PostGIS → GeoParquet Export
1. Analytical query executes on PostGIS
2. Results exported to GeoParquet
3. GeoParquet stored in Gold container
4. STAC Item created in "geoparquet" collection
5. Item inserted into PgSTAC

# STAC Item
stac_service.create_geoparquet_item(
    container='gold',
    blob_name='analysis-results.parquet',
    collection_id='geoparquet'
)
```

---

## 📋 Collection Management Rules

### Rule 1: Bronze Container NOT in STAC
❌ **Never create STAC Items for Bronze container blobs**
✅ Bronze is pre-ETL staging only

### Rule 2: Vector Files NOT in STAC (Except GeoParquet)
❌ **Never create STAC Items for Shapefile/GeoJSON/GeoPackage**
✅ Load to PostGIS, represent as Collection metadata
✅ Exception: GeoParquet files ARE STAC Items

### Rule 3: Rasters Must Be COGs in EPSG:4326
❌ **Never create STAC Items for non-COG rasters**
✅ Convert to COG + EPSG:4326 in ETL first

### Rule 4: One Collection Type Per Asset Type
❌ **Don't mix rasters and vectors in same collection**
✅ Rasters → "cogs"
✅ PostGIS tables → "vectors"
✅ GeoParquet → "geoparquet"

---

## 🎯 Development Strategy

### Phase 1: Development Collection (Current)
**Goal**: Test STAC metadata extraction with Bronze container

```python
# Create dev collection for testing
stac.create_production_collection('dev')

# Extract test items from Bronze
stac_service.extract_item_from_blob(
    container='rmhazuregeobronze',
    blob_name='test-raster.tif',
    collection_id='dev'  # Development only
)
```

### Phase 2: Production Collections
**Goal**: Create production collections, migrate dev items

```python
# Create production collections
stac.create_production_collection('cogs')
stac.create_production_collection('vectors')
stac.create_production_collection('geoparquet')

# New items go to correct collections
collection_id = StacInfrastructure.determine_collection('raster')
# → 'cogs'
```

### Phase 3: ETL Integration
**Goal**: Automatic STAC Item creation during ETL

```python
# Raster ETL creates STAC Items automatically
def convert_to_cog_and_catalog(blob_name):
    # Convert to COG
    cog_blob = convert_to_cog(blob_name)

    # Extract STAC metadata
    item = stac_service.extract_item_from_blob(
        container='silver',
        blob_name=cog_blob,
        collection_id='cogs'
    )

    # Insert into PgSTAC
    stac_infra.insert_item(item, 'cogs')
```

---

## 📚 API Endpoints

### Create Production Collection
```bash
POST /api/stac/collections/production

Body:
{
    "collection_type": "cogs"  # or "vectors", "geoparquet", "dev"
}
```

### List Collections
```bash
GET /api/stac/collections

Response:
{
    "collections": [
        {"id": "cogs", "title": "Cloud-Optimized GeoTIFFs"},
        {"id": "vectors", "title": "Vector Features (PostGIS)"},
        {"id": "geoparquet", "title": "GeoParquet Analytical Datasets"},
        {"id": "dev", "title": "Development & Testing"}
    ]
}
```

---

## 🔑 Key Decisions Summary

| Asset Type | Collection | Strategy |
|------------|------------|----------|
| **Raw files (Bronze)** | ❌ None | Pre-ETL staging, NOT in STAC |
| **COG (EPSG:4326)** | ✅ `cogs` | STAC Items in production |
| **Vector files** | ❌ None | Load to PostGIS, NOT STAC Items |
| **PostGIS tables** | ✅ `vectors` | Collection metadata, OGC API future |
| **GeoParquet** | ✅ `geoparquet` | STAC Items (exception to vector rule) |
| **Dev/Test** | ✅ `dev` | Generic collection for development |

---

## 🎓 References

- **STAC Collections Spec**: https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md
- **PgSTAC Collections**: https://github.com/stac-utils/pgstac
- **OGC API - Features**: https://ogcapi.ogc.org/features/

---

## 🔑 Key Takeaway

**Production STAC has 3 collections:**
1. **`cogs`** - Raster data (COG + EPSG:4326 only)
2. **`vectors`** - PostGIS tables (NOT files)
3. **`geoparquet`** - Analytical exports (cloud-optimized)

**Bronze container is DEV/TEST only** - use `dev` collection for development.

**Vector files are NOT STAC assets** - they're loaded to PostGIS or rejected.
