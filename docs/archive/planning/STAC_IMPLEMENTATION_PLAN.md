# STAC Implementation Plan

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Phase 0 Complete - PgSTAC Installed ✅

---

## 🎯 Overview

Implementation plan for integrating SpatioTemporal Asset Catalog (STAC) into rmhgeoapi geospatial processing system. STAC provides standardized metadata for geospatial assets, enabling discovery and querying across Bronze/Silver/Gold data tiers.

---

## ✅ Phase 0: Foundation (COMPLETE - 5 OCT 2025)

### Infrastructure Setup
- ✅ PostgreSQL 17.6 deployed
- ✅ PostGIS 3.6 installed
- ✅ btree_gist extension enabled
- ✅ PgSTAC 0.8.5 installed (22 tables in `pgstac` schema)
- ✅ STAC endpoints: `/api/stac/setup`
- ✅ Connection string unified

### Verification
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/setup
```

**Response**:
```json
{
  "installed": true,
  "version": "0.8.5",
  "tables_count": 22,
  "roles": ["pgstac_admin", "pgstac_read", "pgstac_ingest"]
}
```

---

## 🚧 Phase 1: STAC Collections (NEXT - 30 minutes)

### Goal
Create Bronze/Silver/Gold tier STAC collections to organize geospatial assets by processing stage.

### Collections Schema

**Bronze Collection** - Raw Data Landing Zone
```json
{
  "id": "rmhazure-bronze",
  "type": "Collection",
  "stac_version": "1.0.0",
  "title": "RMH Azure Bronze Tier",
  "description": "Raw geospatial data as deposited by users",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [[null, null]]}
  },
  "keywords": ["raw", "bronze", "ingestion"],
  "providers": [
    {
      "name": "RMH Azure Geospatial",
      "roles": ["producer", "processor", "host"]
    }
  ]
}
```

**Silver Collection** - Validated Cloud-Optimized Data
```json
{
  "id": "rmhazure-silver",
  "type": "Collection",
  "stac_version": "1.0.0",
  "title": "RMH Azure Silver Tier",
  "description": "Cloud-optimized GeoTIFFs (COGs) with validated metadata and PostGIS integration",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [[null, null]]}
  },
  "keywords": ["cog", "silver", "processed", "postgis"],
  "providers": [
    {
      "name": "RMH Azure Geospatial",
      "roles": ["processor", "host"]
    }
  ]
}
```

**Gold Collection** - Optimized Analytical Datasets
```json
{
  "id": "rmhazure-gold",
  "type": "Collection",
  "stac_version": "1.0.0",
  "title": "RMH Azure Gold Tier",
  "description": "GeoParquet exports optimized for analytical queries",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [[null, null]]}
  },
  "keywords": ["geoparquet", "gold", "analytics"],
  "providers": [
    {
      "name": "RMH Azure Geospatial",
      "roles": ["processor", "host"]
    }
  ]
}
```

### Implementation Tasks

#### Task 1.1: Create Collection Management Trigger
**File**: `triggers/stac_collections.py`

**Endpoints**:
- `POST /api/stac/collections/bronze` - Create Bronze collection
- `POST /api/stac/collections/silver` - Create Silver collection
- `POST /api/stac/collections/gold` - Create Gold collection
- `GET /api/stac/collections` - List all collections
- `GET /api/stac/collections/{id}` - Get specific collection
- `DELETE /api/stac/collections/{id}?confirm=yes` - Delete collection (dev only)

**Implementation**:
```python
from infrastructure.stac import StacInfrastructure
from triggers.http_base import BaseHttpTrigger

class StacCollectionsTrigger(BaseHttpTrigger):
    def __init__(self):
        super().__init__(trigger_name="stac_collections")
        self._stac = None

    @property
    def stac(self):
        if self._stac is None:
            self._stac = StacInfrastructure()
        return self._stac

    def get_allowed_methods(self):
        return ["GET", "POST", "DELETE"]

    def process_request(self, req):
        method = req.method
        route_params = req.route_params

        if method == "POST":
            return self._create_collection(req)
        elif method == "GET":
            return self._get_collections(req)
        elif method == "DELETE":
            return self._delete_collection(req)
```

#### Task 1.2: Extend StacInfrastructure
**File**: `infrastructure/stac.py`

**New Methods**:
```python
def create_silver_collection(self) -> Dict[str, Any]:
    """Create Silver tier collection for COGs."""

def create_gold_collection(self) -> Dict[str, Any]:
    """Create Gold tier collection for GeoParquet."""

def list_collections(self) -> Dict[str, Any]:
    """List all STAC collections."""
    # Query: SELECT * FROM pgstac.collections

def get_collection(self, collection_id: str) -> Dict[str, Any]:
    """Get specific collection by ID."""
    # Query: SELECT * FROM pgstac.get_collection(%s)

def delete_collection(self, collection_id: str, confirm: bool = False) -> Dict[str, Any]:
    """Delete collection (dev only)."""
    # Query: DELETE FROM pgstac.collections WHERE id = %s
```

#### Task 1.3: Register Routes
**File**: `function_app.py`

```python
from triggers.stac_collections import stac_collections_trigger

@app.route(route="stac/collections/bronze", methods=["POST"])
def create_bronze_collection(req):
    return stac_collections_trigger.handle_request(req)

@app.route(route="stac/collections/silver", methods=["POST"])
def create_silver_collection(req):
    return stac_collections_trigger.handle_request(req)

@app.route(route="stac/collections/gold", methods=["POST"])
def create_gold_collection(req):
    return stac_collections_trigger.handle_request(req)

@app.route(route="stac/collections", methods=["GET"])
@app.route(route="stac/collections/{collection_id}", methods=["GET", "DELETE"])
def stac_collections(req):
    return stac_collections_trigger.handle_request(req)
```

### Testing Phase 1

```bash
# Create collections
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/bronze
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/silver
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/gold

# List collections
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections

# Get specific collection
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/rmhazure-bronze
```

**Deliverables**:
- ✅ Bronze/Silver/Gold collections created in PgSTAC
- ✅ Collection management endpoints working
- ✅ Collections queryable via STAC API

**Time Estimate**: 30 minutes

---

## 📦 Phase 2: STAC Item Ingestion (1-2 hours)

### Goal
Register geospatial assets (rasters, vectors) as STAC items within collections.

### STAC Item Schema

**Example Bronze Item** (Raw GeoTIFF)
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "bronze-{blob_name}-{timestamp}",
  "collection": "rmhazure-bronze",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]]
  },
  "bbox": [-180, -90, 180, 90],
  "properties": {
    "datetime": "2025-10-05T00:00:00Z",
    "created": "2025-10-05T02:30:00Z",
    "platform": "user-upload",
    "instruments": ["unknown"]
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeobronze/path/to/file.tif",
      "type": "image/tiff; application=geotiff",
      "roles": ["data"],
      "title": "Raw GeoTIFF"
    }
  }
}
```

**Example Silver Item** (COG)
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "silver-{cog_id}",
  "collection": "rmhazure-silver",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[...actual bounds from raster...]]]
  },
  "bbox": [-122.5, 37.5, -122.0, 38.0],
  "properties": {
    "datetime": "2025-10-05T02:30:00Z",
    "created": "2025-10-05T02:35:00Z",
    "gsd": 10.0,
    "eo:cloud_cover": 0,
    "proj:epsg": 4326,
    "processing:level": "L2"
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/cogs/processed.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "Cloud-Optimized GeoTIFF"
    },
    "thumbnail": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/cogs/processed_thumbnail.png",
      "type": "image/png",
      "roles": ["thumbnail"]
    }
  },
  "links": [
    {
      "rel": "derived_from",
      "href": "../../../bronze/original.tif",
      "type": "image/tiff"
    }
  ]
}
```

### Implementation Tasks

#### Task 2.1: Create STAC Item Ingestion Job
**File**: `jobs/ingest_stac_item.py`

**Job Type**: `ingest_stac_item`

**Parameters**:
```python
{
  "collection_id": "rmhazure-bronze",
  "blob_url": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeobronze/data.tif",
  "item_id": "bronze-data-20251005",  # Optional, auto-generated if not provided
  "metadata": {  # Optional additional metadata
    "platform": "sentinel-2",
    "instruments": ["msi"]
  }
}
```

**Workflow** (Single Stage):
```python
@JobRegistry.instance().register(job_type="ingest_stac_item")
class IngestStacItemJob:
    """
    Single-stage job to create STAC item from blob.

    Stage 1:
      Task 1: Extract spatial/temporal metadata from raster
      Task 2: Create STAC item in pgstac.items
    """

    def create_stage_1_tasks(self, context):
        return [
            TaskDefinition(
                task_type="extract_raster_metadata",
                parameters={
                    "blob_url": context.job_params["blob_url"]
                }
            ),
            TaskDefinition(
                task_type="create_stac_item",
                parameters={
                    "collection_id": context.job_params["collection_id"],
                    "metadata": context.stage_results.get(1, {})
                }
            )
        ]
```

#### Task 2.2: Create Metadata Extraction Service
**File**: `services/metadata_extractor.py`

**Purpose**: Extract spatial/temporal metadata from rasters using rasterio

```python
class MetadataExtractorService:
    """Extract STAC-compatible metadata from rasters."""

    def extract_from_raster(self, blob_url: str) -> Dict[str, Any]:
        """
        Extract metadata from GeoTIFF.

        Returns:
            {
                "bbox": [-122.5, 37.5, -122.0, 38.0],
                "geometry": {...},
                "properties": {
                    "datetime": "2025-10-05T00:00:00Z",
                    "proj:epsg": 4326,
                    "gsd": 10.0
                }
            }
        """
        with rasterio.open(blob_url) as src:
            bounds = src.bounds
            crs = src.crs
            transform = src.transform
            # Extract bbox, geometry, projection, resolution
```

#### Task 2.3: Create STAC Item Service
**File**: `services/stac_item_service.py`

**Purpose**: Insert/update STAC items in PgSTAC

```python
class StacItemService:
    """Manage STAC items in PgSTAC."""

    def create_item(self, collection_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create STAC item in collection.

        Uses: SELECT pgstac.upsert_item(%s)
        """

    def get_item(self, item_id: str) -> Dict[str, Any]:
        """Get STAC item by ID."""

    def delete_item(self, item_id: str) -> Dict[str, Any]:
        """Delete STAC item."""
```

#### Task 2.4: Integration with Existing Jobs
**Modify**: `jobs/list_container.py` (or create new COG processing job)

**Add**: Automatic STAC item creation after COG generation

```python
# After COG created in Silver container
if cog_created:
    # Submit ingest_stac_item job
    job_params = {
        "collection_id": "rmhazure-silver",
        "blob_url": cog_url,
        "metadata": {
            "derived_from": original_blob_url
        }
    }
    submit_job("ingest_stac_item", job_params)
```

### Testing Phase 2

```bash
# Submit STAC ingestion job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/ingest_stac_item \
  -H "Content-Type: application/json" \
  -d '{
    "collection_id": "rmhazure-bronze",
    "blob_url": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeobronze/test.tif"
  }'

# Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{job_id}

# Verify item in STAC
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/rmhazure-bronze/items
```

**Deliverables**:
- ✅ Metadata extraction from rasters
- ✅ STAC item creation in pgstac.items
- ✅ Integration with COG workflows
- ✅ Bronze/Silver items populated

**Time Estimate**: 1-2 hours

---

## 🔍 Phase 3: STAC Search & Query API (2-3 hours)

### Goal
Implement STAC-compliant search endpoints for discovering geospatial assets.

### STAC API Endpoints

#### GET /api/stac/collections
**Purpose**: List all collections

**Response**:
```json
{
  "collections": [
    {"id": "rmhazure-bronze", "title": "RMH Azure Bronze Tier", ...},
    {"id": "rmhazure-silver", "title": "RMH Azure Silver Tier", ...},
    {"id": "rmhazure-gold", "title": "RMH Azure Gold Tier", ...}
  ],
  "links": [...]
}
```

#### GET /api/stac/collections/{collection_id}
**Purpose**: Get collection details

**Response**: Single collection object

#### GET /api/stac/collections/{collection_id}/items
**Purpose**: List items in collection with pagination

**Query Parameters**:
- `limit` - Max items to return (default: 10)
- `bbox` - Spatial filter: `bbox=-122.5,37.5,-122.0,38.0`
- `datetime` - Temporal filter: `datetime=2025-01-01/2025-12-31`

**Response**:
```json
{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "id": "item-1", ...},
    {"type": "Feature", "id": "item-2", ...}
  ],
  "links": [
    {"rel": "next", "href": "/api/stac/collections/rmhazure-bronze/items?page=2"}
  ]
}
```

#### POST /api/stac/search
**Purpose**: Advanced search across all collections

**Request Body**:
```json
{
  "bbox": [-122.5, 37.5, -122.0, 38.0],
  "datetime": "2025-01-01/2025-12-31",
  "collections": ["rmhazure-silver"],
  "query": {
    "eo:cloud_cover": {"lt": 10},
    "gsd": {"lte": 10}
  },
  "limit": 50
}
```

**Implementation**: Uses `pgstac.search()` function

```python
def search_items(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute STAC search query.

    Uses: SELECT * FROM pgstac.search(%s)
    """
    with psycopg.connect(self.connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pgstac.search(%s)",
                [json.dumps(search_params)]
            )
            return cur.fetchone()[0]
```

#### GET /api/stac/items/{item_id}
**Purpose**: Get specific item by ID

**Response**: Single STAC item

### Implementation Tasks

#### Task 3.1: Create STAC Search Trigger
**File**: `triggers/stac_search.py`

**Endpoints**:
- `GET /api/stac/collections` - List collections
- `GET /api/stac/collections/{id}` - Get collection
- `GET /api/stac/collections/{id}/items` - List items
- `GET /api/stac/items/{id}` - Get item
- `POST /api/stac/search` - Search items

#### Task 3.2: Extend StacInfrastructure
**File**: `infrastructure/stac.py`

**New Methods**:
```python
def search_items(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute STAC search."""

def list_items(self, collection_id: str, limit: int = 10, bbox: Optional[List] = None) -> Dict[str, Any]:
    """List items in collection."""

def get_item(self, item_id: str) -> Dict[str, Any]:
    """Get specific item."""
```

### Testing Phase 3

```bash
# List collections
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections

# List items in Bronze
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/rmhazure-bronze/items?limit=10

# Search with spatial filter
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/search \
  -H "Content-Type: application/json" \
  -d '{
    "bbox": [-122.5, 37.5, -122.0, 38.0],
    "collections": ["rmhazure-silver"],
    "limit": 50
  }'

# Get specific item
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/items/bronze-test-20251005
```

**Deliverables**:
- ✅ STAC-compliant search API
- ✅ Spatial/temporal filtering
- ✅ Pagination support
- ✅ Cross-collection search

**Time Estimate**: 2-3 hours

---

## 🌐 Phase 4: STAC Browser Integration (Optional - 1 hour)

### Goal
Provide web UI for browsing STAC catalog.

### Option 1: Radiant Earth STAC Browser
**Repository**: https://github.com/radiantearth/stac-browser

**Setup**:
1. Fork/clone STAC Browser
2. Configure to point at your STAC API
3. Deploy as static site (Azure Static Web Apps or Blob Storage)

**Config**:
```json
{
  "catalogUrl": "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac"
}
```

### Option 2: stac-fastapi
**Repository**: https://github.com/stac-utils/stac-fastapi

**Benefit**: Drop-in replacement for custom STAC API using FastAPI + PgSTAC

**Note**: May not integrate well with existing Azure Functions architecture

### Option 3: Custom Simple Browser
**File**: `static/stac-browser.html`

Simple HTML/JS page using Leaflet + STAC search API

**Deliverables**:
- ✅ Web UI for STAC catalog
- ✅ Map-based search
- ✅ Item preview

**Time Estimate**: 1 hour (using existing browser)

---

## 📊 Success Metrics

### Phase 1
- [ ] Bronze/Silver/Gold collections created
- [ ] Collections queryable via API
- [ ] Collection CRUD operations working

### Phase 2
- [ ] STAC items created from rasters
- [ ] Metadata extraction working
- [ ] Items linked to blob storage
- [ ] Bronze tier populated with 10+ items
- [ ] Silver tier populated with COGs

### Phase 3
- [ ] Search by bbox working
- [ ] Search by datetime working
- [ ] Pagination working
- [ ] Response times < 1 second for typical queries

### Phase 4
- [ ] Browser deployed and accessible
- [ ] Map search working
- [ ] Item details viewable

---

## 🔗 Integration Points

### With Existing System

**Container Analysis** (`jobs/list_container.py`):
- After analyzing container → create STAC items for discovered assets
- Tag with metadata: size, format, detected CRS

**COG Generation** (future `jobs/create_cog.py`):
- After creating COG → create Silver STAC item
- Link to Bronze original via `derived_from`

**GeoParquet Export** (future `jobs/export_geoparquet.py`):
- After export → create Gold STAC item
- Link to Silver source

### Workflow Example
```
1. User uploads GeoTIFF → rmhazuregeobronze/data.tif
2. Trigger: ingest_stac_item → Bronze STAC item created
3. Job: stage_raster → Validates, reprojects
4. Job: create_cog → Silver COG created
5. Trigger: ingest_stac_item → Silver STAC item created (linked to Bronze)
6. Job: export_geoparquet → Gold export created
7. Trigger: ingest_stac_item → Gold STAC item created (linked to Silver)
```

**Result**: Full lineage tracked in STAC catalog

---

## 📝 Development Notes

### PgSTAC Functions to Use

**Collections**:
- `pgstac.create_collection(jsonb)` - Create collection
- `pgstac.get_collection(text)` - Get collection by ID
- `pgstac.all_collections()` - List all collections
- `pgstac.delete_collection(text)` - Delete collection

**Items**:
- `pgstac.create_item(jsonb)` - Create item
- `pgstac.upsert_item(jsonb)` - Insert or update item
- `pgstac.get_item(text)` - Get item by ID
- `pgstac.delete_item(text)` - Delete item

**Search**:
- `pgstac.search(jsonb)` - Execute STAC search
- `pgstac.search_query(jsonb)` - Get search SQL

### Connection Pattern
**CRITICAL**: All STAC operations MUST use `config.postgis_connection_string`

```python
from config import get_config
config = get_config()
conn_string = config.postgis_connection_string

with psycopg.connect(conn_string) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT pgstac.search(%s)", [search_params])
```

### Error Handling
- **Contract Violations**: Programming bugs (wrong types) → `ContractViolationError` → crash
- **Business Errors**: Missing resources, invalid data → `BusinessLogicError` → handle gracefully

---

## 🚀 Deployment Checklist

### Before Phase 1
- [x] PgSTAC installed
- [x] Connection string unified
- [ ] STAC endpoints documented

### Before Phase 2
- [ ] Bronze/Silver/Gold collections created
- [ ] Rasterio installed (for metadata extraction)
- [ ] Blob storage access verified

### Before Phase 3
- [ ] STAC items exist in collections
- [ ] Search function tested
- [ ] Pagination logic implemented

### Before Phase 4
- [ ] STAC API fully functional
- [ ] CORS configured (if needed)
- [ ] Browser deployment target chosen

---

## 📚 References

- **STAC Spec**: https://stacspec.org/
- **PgSTAC**: https://github.com/stac-utils/pgstac
- **STAC Browser**: https://github.com/radiantearth/stac-browser
- **STAC Extensions**: https://stac-extensions.github.io/
- **STAC API Spec**: https://github.com/radiantearth/stac-api-spec

---

## 🎯 Priority Recommendation

**Start with Phase 1**: Create collections (30 minutes)
- Low risk, high value
- Required before any item ingestion
- Easy to test and verify

**Then Phase 2**: Item ingestion (1-2 hours)
- Enables populating catalog
- Integrates with existing workflows
- Provides immediate value

**Then Phase 3**: Search API (2-3 hours)
- Makes catalog queryable
- Enables discovery
- Foundation for applications

**Skip Phase 4**: Unless web UI specifically requested
- Not critical for core functionality
- Can use existing STAC browsers
- Focus on API first

---

**Total Implementation Time**: 4-6 hours for Phases 1-3
**Next Step**: Implement Phase 1 collections
