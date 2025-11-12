# STAC Vector Data Strategy

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Core Question

**How should vector files (GeoJSON, Shapefile, GeoPackage, etc.) be represented in STAC?**

## 📋 STAC Official Guidance on Vector Data

### From STAC Best Practices

> "The main route considered is to use STAC to describe vector layers, putting a shapefile or geopackage as the asset. Though there is nothing in the specification that prevents this, **it is not really the right level of abstraction** - a shapefile or geopackage corresponds to a **Collection, not a single Item**."

> "The ideal thing to do with one of those is to **serve it with OGC API - Features standard**, which allows each feature in the shapefile/geopackage to be represented online, and enables querying of the actual data."

### Key Insight

**Vector datasets (Shapefile, GeoPackage) = STAC Collection, NOT STAC Item**

## 🏗️ Vector Data Representation Strategies

### Strategy 1: File-Level STAC Items (Simple, Not Ideal)

**Use Case**: Treating entire vector file as a single asset

```python
# STAC Item for a Shapefile
{
    "id": "bronze-parcels-shapefile",
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [...]  # Total bounds of ALL features
    },
    "bbox": [-122.5, 37.5, -122.0, 38.0],  # Total bounds
    "properties": {
        "datetime": "2025-10-05T00:00:00Z",
        "vector:feature_count": 10000,
        "vector:geometry_types": ["Polygon"],
        "vector:layer_name": "parcels"
    },
    "assets": {
        "data": {
            "href": "https://.../parcels.gpkg",
            "type": "application/geopackage+sqlite3",
            "roles": ["data"]
        }
    }
}
```

**Pros:**
- ✅ Simple to implement
- ✅ Works with existing STAC infrastructure

**Cons:**
- ❌ Not semantically correct (file != feature)
- ❌ Can't query individual features
- ❌ Doesn't support spatial filtering within dataset

**When to Use:**
- Vector files as "deliverables" (e.g., exported analysis results)
- Small vector datasets that are treated as atomic units
- Bronze tier raw uploads

---

### Strategy 2: OGC API - Features (Ideal, Complex)

**Use Case**: Individual features queryable via API

```
Vector File → Load to PostGIS → Serve via OGC API - Features
                                 ↓
                          Each feature is a resource
                          Collection metadata in STAC
```

**Implementation:**
```python
# STAC Collection for vector layer
{
    "id": "silver-parcels",
    "type": "Collection",
    "description": "Property parcels for San Francisco",
    "extent": {
        "spatial": {"bbox": [[-122.5, 37.5, -122.0, 38.0]]},
        "temporal": {"interval": [["2025-01-01T00:00:00Z", null]]}
    },
    "links": [
        {
            "rel": "items",
            "type": "application/geo+json",
            "href": "https://.../collections/parcels/items"  # OGC API - Features
        }
    ]
}

# Individual feature accessible via OGC API
GET /collections/parcels/items/parcel-12345
→ Returns GeoJSON feature
```

**Pros:**
- ✅ Semantically correct (feature = feature)
- ✅ Queryable by bounding box, attributes, etc.
- ✅ Standard OGC API compliance
- ✅ Aligns with STAC best practices

**Cons:**
- ❌ Requires OGC API - Features server
- ❌ Requires loading data to PostGIS
- ❌ More complex infrastructure

**When to Use:**
- Silver/Gold tier vector data
- Data that needs to be queryable
- Production feature services

---

### Strategy 3: STAC Label Extension (ML/Training Data)

**Use Case**: Vector annotations for machine learning training

```python
# STAC Item with Label Extension
{
    "id": "training-data-buildings-sf-2025",
    "type": "Feature",
    "stac_extensions": [
        "https://stac-extensions.github.io/label/v1.0.0/schema.json"
    ],
    "properties": {
        "datetime": "2025-10-05T00:00:00Z",
        "label:properties": ["building_type", "height"],
        "label:classes": [
            {"name": "residential", "classes": ["residential"]},
            {"name": "commercial", "classes": ["commercial"]}
        ],
        "label:tasks": ["segmentation"],
        "label:methods": ["manual"],
        "label:type": "vector"
    },
    "assets": {
        "labels": {
            "href": "https://.../building_labels.geojson",
            "type": "application/geo+json",
            "roles": ["labels-vector", "labels-training"]
        }
    },
    "links": [
        {
            "rel": "source",
            "href": ".../sentinel-2-imagery-item",
            "type": "application/json"
        }
    ]
}
```

**Pros:**
- ✅ Purpose-built for ML training data
- ✅ Links labels to source imagery
- ✅ Standard extension for ML workflows

**Cons:**
- ❌ Only for labeled training data
- ❌ Not for general vector datasets

**When to Use:**
- Training data for ML models
- Annotation datasets
- Research/analysis results

---

## 🛠️ Implementation Strategy for Our Architecture

### Bronze Tier: Raw Vector Files (File-Level Items)

**Approach**: Treat uploaded vector files as STAC Items at file level

```python
def extract_vector_metadata(container: str, blob_name: str) -> dict:
    """
    Extract metadata from vector file for STAC Item.

    Uses GeoPandas to extract bounds and feature info.
    """
    import geopandas as gpd

    # Generate blob URL with SAS token
    blob_url = blob_repo.generate_sas_url(container, blob_name)

    # Read vector file
    gdf = gpd.read_file(blob_url)

    # Extract metadata
    total_bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)

    # Create STAC Item
    item = {
        "id": f"bronze-{blob_name.replace('/', '-')}",
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [total_bounds[0], total_bounds[1]],
                [total_bounds[2], total_bounds[1]],
                [total_bounds[2], total_bounds[3]],
                [total_bounds[0], total_bounds[3]],
                [total_bounds[0], total_bounds[1]]
            ]]
        },
        "bbox": total_bounds.tolist(),
        "properties": {
            "datetime": datetime.now().isoformat(),
            "vector:feature_count": len(gdf),
            "vector:geometry_types": list(gdf.geometry.geom_type.unique()),
            "vector:crs": str(gdf.crs),
            "vector:columns": list(gdf.columns)
        },
        "assets": {
            "data": {
                "href": blob_url,
                "type": _get_media_type(blob_name),
                "roles": ["data"]
            }
        }
    }

    return item


def _get_media_type(filename: str) -> str:
    """Get media type for vector formats."""
    ext = filename.lower().rsplit('.', 1)[-1]

    media_types = {
        'geojson': 'application/geo+json',
        'json': 'application/geo+json',
        'gpkg': 'application/geopackage+sqlite3',
        'shp': 'application/x-shapefile',  # Note: Shapefile is multi-file
        'kml': 'application/vnd.google-earth.kml+xml',
        'gml': 'application/gml+xml',
        'parquet': 'application/x-parquet',  # GeoParquet
        'fgb': 'application/flatgeobuf'     # FlatGeobuf
    }

    return media_types.get(ext, 'application/octet-stream')
```

**Bronze Strategy:**
- ✅ Simple file-level STAC Items
- ✅ Quick metadata extraction with GeoPandas
- ✅ Discoverable in PgSTAC catalog
- ✅ Preserves original file format

---

### Silver Tier: PostGIS + OGC API - Features (Future)

**Approach**: Load vector data to PostGIS, serve via OGC API - Features

```python
# Phase 1: Load to PostGIS
def load_vector_to_postgis(
    container: str,
    blob_name: str,
    table_name: str
) -> dict:
    """
    Load vector file to PostGIS table.

    Creates STAC Collection (not Item) since table = collection.
    """
    import geopandas as gpd
    from sqlalchemy import create_engine

    # Read vector file
    blob_url = blob_repo.generate_sas_url(container, blob_name)
    gdf = gpd.read_file(blob_url)

    # Ensure WGS84 for STAC compliance
    if gdf.crs != 'EPSG:4326':
        gdf = gdf.to_crs('EPSG:4326')

    # Load to PostGIS
    engine = create_engine(config.postgis_connection_string)
    gdf.to_postgis(
        name=table_name,
        con=engine,
        schema='geo',
        if_exists='replace',
        index=True
    )

    # Create STAC Collection (not Item)
    collection = {
        "id": f"silver-{table_name}",
        "type": "Collection",
        "description": f"Vector features from {blob_name}",
        "extent": {
            "spatial": {"bbox": [gdf.total_bounds.tolist()]},
            "temporal": {"interval": [[None, None]]}
        },
        "summaries": {
            "vector:feature_count": [len(gdf)],
            "vector:geometry_types": list(gdf.geometry.geom_type.unique()),
            "azure:source_blob": [f"{container}/{blob_name}"]
        },
        "links": [
            {
                "rel": "items",
                "type": "application/geo+json",
                "href": f"/collections/{table_name}/items",  # Future OGC API
                "title": "Features in this collection"
            }
        ]
    }

    return collection


# Phase 2: OGC API - Features (Future Implementation)
# Serve PostGIS tables via OGC API - Features
# Each feature accessible at: /collections/{table_name}/items/{feature_id}
```

**Silver Strategy:**
- ✅ Vector data queryable in PostGIS
- ✅ Semantically correct (Collection, not Item)
- ✅ Ready for OGC API - Features in future
- ❌ Requires OGC API server (future work)

---

### Gold Tier: GeoParquet Exports

**Approach**: Export analytical results as GeoParquet STAC Items

```python
def create_geoparquet_stac_item(
    container: str,
    blob_name: str,
    description: str
) -> dict:
    """
    Create STAC Item for GeoParquet analytical export.

    GeoParquet = optimized for cloud analytics, perfect for STAC.
    """
    import geopandas as gpd
    import pyarrow.parquet as pq

    blob_url = blob_repo.generate_sas_url(container, blob_name)

    # Read GeoParquet metadata (lightweight)
    parquet_file = pq.ParquetFile(blob_url)
    geo_metadata = parquet_file.schema_arrow.metadata.get(b'geo')

    # Read minimal data for bounds
    gdf = gpd.read_parquet(blob_url)

    item = {
        "id": f"gold-{blob_name.replace('/', '-').replace('.parquet', '')}",
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [...]  # From total_bounds
        },
        "bbox": gdf.total_bounds.tolist(),
        "properties": {
            "datetime": datetime.now().isoformat(),
            "vector:feature_count": len(gdf),
            "parquet:row_groups": parquet_file.num_row_groups,
            "parquet:compression": "snappy",
            "description": description
        },
        "assets": {
            "data": {
                "href": blob_url,
                "type": "application/x-parquet",
                "roles": ["data", "analytics"]
            }
        }
    }

    return item
```

**Gold Strategy:**
- ✅ GeoParquet = cloud-optimized vector format
- ✅ Perfect for analytical queries
- ✅ File-level STAC Items appropriate here
- ✅ Columnar format for efficient filtering

---

## 📊 Vector Format Decision Matrix

| Format | Bronze | Silver | Gold | STAC Strategy |
|--------|--------|--------|------|---------------|
| **GeoJSON** | ✅ File Item | ✅ PostGIS → Collection | - | File (Bronze), Features API (Silver) |
| **Shapefile** | ✅ File Item | ✅ PostGIS → Collection | - | File (Bronze), Features API (Silver) |
| **GeoPackage** | ✅ File Item | ✅ PostGIS → Collection | - | File (Bronze), Features API (Silver) |
| **GeoParquet** | ✅ File Item | - | ✅ File Item | File at all tiers (cloud-optimized) |
| **FlatGeobuf** | ✅ File Item | - | ✅ File Item | File (cloud-optimized streaming) |
| **KML/KMZ** | ✅ File Item | ✅ PostGIS → Collection | - | File (Bronze), Features API (Silver) |

---

## 🔧 Metadata Extraction with GeoPandas

### What GeoPandas Can Extract

```python
import geopandas as gpd

# Read vector file
gdf = gpd.read_file("file.gpkg")

# Total bounds (for STAC bbox)
total_bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)

# CRS information
crs = gdf.crs  # CRS object
epsg_code = gdf.crs.to_epsg()  # EPSG code (e.g., 4326)

# Feature count
feature_count = len(gdf)

# Geometry types
geometry_types = gdf.geometry.geom_type.unique()  # ['Polygon', 'MultiPolygon']

# Attribute columns
columns = gdf.columns.tolist()  # ['id', 'name', 'area', 'geometry']

# Attribute statistics (if numeric)
gdf['area'].describe()  # min, max, mean, etc.

# Individual geometry bounds (for each feature)
gdf.bounds  # DataFrame with minx, miny, maxx, maxy per feature
```

### What GeoPandas CANNOT Extract (Requires File Access)

❌ File size (use BlobRepository)
❌ Last modified date (use BlobRepository)
❌ File format details (use blob metadata)
❌ Compression info (GeoPackage, FlatGeobuf)

---

## 🎯 Recommended Implementation Plan

### Phase 1: Bronze Vector Support (File-Level)
- [ ] Add GeoPandas to requirements.txt (if not present)
- [ ] Create `extract_vector_metadata()` in `StacMetadataService`
- [ ] Support GeoJSON, GeoPackage, Shapefile formats
- [ ] Extract bounds, CRS, feature count with GeoPandas
- [ ] Create file-level STAC Items
- [ ] Insert into PgSTAC catalog

### Phase 2: Silver Vector Support (PostGIS)
- [ ] Create `load_vector_to_postgis()` service
- [ ] Load vector files to PostGIS tables
- [ ] Create STAC Collections (not Items) for tables
- [ ] Add summaries with feature count, geometry types

### Phase 3: OGC API - Features (Future)
- [ ] Research OGC API - Features implementations (pygeoapi, stac-fastapi)
- [ ] Configure OGC API to serve PostGIS tables
- [ ] Link STAC Collections to OGC API endpoints
- [ ] Enable feature-level querying

### Phase 4: Gold GeoParquet Support
- [ ] Create GeoParquet export workflows
- [ ] Create STAC Items for GeoParquet files
- [ ] Add Parquet-specific metadata (row groups, compression)

---

## 🔑 Key Decisions

### For Uploaded Vector Files (Bronze):
✅ **File-level STAC Items** - Pragmatic, simple, discoverable

### For Processed Vector Data (Silver):
✅ **PostGIS Tables + STAC Collections** - Semantically correct, queryable

### For Analytical Exports (Gold):
✅ **GeoParquet STAC Items** - Cloud-optimized, analytical

### ML Training Data:
✅ **STAC Label Extension** - Purpose-built for annotations

---

## 📚 STAC Extensions for Vector Data

### Relevant Extensions

1. **Label Extension** (v1.0.0)
   - Vector annotations for ML training
   - Links labels to source imagery
   - Roles: `labels-vector`, `labels-training`

2. **Projection Extension** (v1.0.0)
   - CRS information for vector data
   - EPSG codes, WKT2, PROJJSON

3. **Scientific Citation Extension**
   - For published vector datasets
   - DOIs, citations, publications

### Custom Properties

```python
# Azure-specific vector properties
{
    "properties": {
        "vector:feature_count": 10000,
        "vector:geometry_types": ["Polygon"],
        "vector:crs": "EPSG:4326",
        "vector:layer_name": "parcels",
        "azure:container": "rmhazuregeobronze",
        "azure:tier": "bronze"
    }
}
```

---

## 🎓 References

- **STAC Best Practices**: https://github.com/radiantearth/stac-spec/blob/master/best-practices.md
- **OGC API - Features**: https://ogcapi.ogc.org/features/
- **STAC Label Extension**: https://github.com/stac-extensions/label
- **GeoPandas Documentation**: https://geopandas.org/
- **GeoParquet Specification**: https://geoparquet.org/

---

## 🔑 Key Takeaway

**Vector data in STAC depends on use case:**

1. **Bronze (Raw Uploads)**: File-level STAC Items (pragmatic)
2. **Silver (Queryable Features)**: PostGIS + STAC Collections + OGC API - Features (ideal)
3. **Gold (Analytics)**: GeoParquet STAC Items (cloud-optimized)
4. **ML Training**: STAC Label Extension (purpose-built)

**GeoPandas provides all metadata extraction we need** for Bronze tier file-level items. For Silver tier, move to PostGIS + OGC API - Features for proper feature-level access.
