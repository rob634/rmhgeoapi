# OGC Features API - Implementation TODO

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: In Progress

## Overview

Standalone OGC API - Features implementation for serving PostGIS vector data through Azure Functions. This module is completely independent and can be deployed separately from the main application.

---

## Implementation Checklist

### Phase 1: Core Infrastructure ✅

- [x] **Create folder structure** (`ogc_features/`)
  - [x] `__init__.py` - Module exports and integration point
  - [x] `config.py` - Standalone configuration (NO dependency on main config)
  - [x] `models.py` - OGC Pydantic response models

### Phase 2: Data Access Layer 🔄

- [ ] **Implement `repository.py`** - PostGIS direct access
  - [ ] PostgreSQL connection management (psycopg)
  - [ ] Collection discovery (query `geometry_columns` view)
  - [ ] Collection metadata extraction
    - [ ] `ST_Extent()` for bbox
    - [ ] Row count for feature count
    - [ ] CRS detection from `geometry_columns`
  - [ ] Feature query methods
    - [ ] `query_features()` with bbox, limit, offset
    - [ ] `ST_AsGeoJSON()` for GeoJSON serialization
    - [ ] Optional `ST_Simplify()` for generalization
    - [ ] Configurable coordinate precision
    - [ ] **NEW: Temporal filtering with flexible column names**
    - [ ] **NEW: Attribute filtering (simple key=value)**
    - [ ] **NEW: Sorting (OGC sortby syntax)**
  - [ ] Single feature retrieval by ID
  - [ ] Datetime column auto-detection
  - [ ] Geometry column auto-detection (`geom`, `geometry`, `shape`)
  - [ ] **Validation (feature-flagged for production)**
    - [ ] Spatial index detection (warning only)
    - [ ] Primary key detection (warning only)
    - [ ] Optimization recommendations

### Phase 3: Business Logic Layer

- [ ] **Implement `service.py`** - Business logic orchestration
  - [ ] Landing page generation with conformance links
  - [ ] Collections list with metadata
  - [ ] Collection metadata retrieval
  - [ ] Feature query coordination
    - [ ] Parameter validation
    - [ ] Query execution
    - [ ] Response formatting
  - [ ] Link generation (self, next, prev, alternate)
  - [ ] Base URL detection and handling

### Phase 4: HTTP Trigger Layer

- [ ] **Implement `triggers.py`** - Azure Functions HTTP handlers
  - [ ] Landing page handler (`GET /api/features`)
  - [ ] Conformance handler (`GET /api/features/conformance`)
  - [ ] Collections list handler (`GET /api/features/collections`)
  - [ ] Collection metadata handler (`GET /api/features/collections/{id}`)
  - [ ] Features query handler (`GET /api/features/collections/{id}/items`)
  - [ ] Single feature handler (`GET /api/features/collections/{id}/items/{fid}`)
  - [ ] Error handling and logging
  - [ ] Query parameter parsing and validation

### Phase 5: Integration

- [ ] **Update `function_app.py`**
  - [ ] Import `get_ogc_triggers()` from `ogc_features`
  - [ ] Register all OGC routes
  - [ ] Test route registration

### Phase 6: Documentation

- [ ] **Create `README.md`** - Standalone deployment guide
  - [ ] Module overview
  - [ ] Architecture diagram
  - [ ] Environment variable reference
  - [ ] Deployment instructions (standalone)
  - [ ] Leaflet integration examples
  - [ ] Query parameter reference
  - [ ] Performance tuning guide

### Phase 7: Testing

- [ ] **Local testing**
  - [ ] Health check endpoint
  - [ ] Landing page response
  - [ ] Collections list
  - [ ] Feature query with bbox
  - [ ] Feature query with simplification
  - [ ] Pagination (offset/limit)
  - [ ] Error handling

- [ ] **Deployment testing**
  - [ ] Deploy to Azure Function App
  - [ ] Test with Leaflet map
  - [ ] Test with QGIS (OGC client)
  - [ ] Performance testing with large datasets
  - [ ] Spatial index verification

---

## Implementation Details

### Repository Layer (`repository.py`)

**Key Classes**:
- `OGCFeaturesRepository` - Main repository class

**Key Methods**:

```python
class OGCFeaturesRepository:
    def __init__(self, config: OGCFeaturesConfig)

    def list_collections(self) -> List[Dict[str, Any]]
    """Query geometry_columns for all vector tables in schema."""

    def get_collection_metadata(self, collection_id: str) -> Dict[str, Any]
    """Get collection bbox, feature count, CRS, geometry type."""

    def query_features(
        self,
        collection_id: str,
        limit: int = 100,
        offset: int = 0,
        bbox: Optional[List[float]] = None,
        precision: int = 6,
        simplify: Optional[float] = None,
        crs: str = "EPSG:4326"
    ) -> Tuple[List[Dict], int]
    """
    Query features with PostGIS optimization.

    Returns:
        Tuple of (features list, total count)
    """

    def get_feature_by_id(
        self,
        collection_id: str,
        feature_id: str,
        precision: int = 6
    ) -> Optional[Dict]
    """Retrieve single feature by primary key."""

    def _detect_geometry_column(self, collection_id: str) -> str
    """Auto-detect geometry column name (geom, geometry, shape)."""

    def _has_spatial_index(self, collection_id: str, geom_column: str) -> bool
    """Check if GIST index exists on geometry column."""

    def _build_feature_query(self, ...) -> sql.Composed
    """Build safe SQL query using psycopg.sql composition."""
```

**SQL Pattern Example**:
```python
# Safe SQL composition (NO string concatenation!)
query = sql.SQL("""
    SELECT
        {columns},
        ST_AsGeoJSON(
            {simplify_expr},
            %s  -- precision
        ) as geometry
    FROM {schema}.{table}
    WHERE {where_clause}
    LIMIT %s OFFSET %s
""").format(
    columns=sql.SQL(",").join(sql.Identifier(c) for c in columns),
    schema=sql.Identifier(self.config.ogc_schema),
    table=sql.Identifier(collection_id),
    simplify_expr=self._build_simplify_expression(geom_column, simplify),
    where_clause=self._build_where_clause(bbox)
)
```

### Service Layer (`service.py`)

**Key Classes**:
- `OGCFeaturesService` - Business logic orchestrator

**Key Methods**:

```python
class OGCFeaturesService:
    def __init__(self, config: OGCFeaturesConfig)

    def get_landing_page(self, base_url: str) -> OGCLandingPage
    """Generate landing page with links."""

    def get_conformance(self) -> OGCConformance
    """Return conformance classes."""

    def list_collections(self, base_url: str) -> OGCCollectionList
    """List all collections with metadata."""

    def get_collection(self, collection_id: str, base_url: str) -> OGCCollection
    """Get single collection metadata."""

    def query_features(
        self,
        collection_id: str,
        params: OGCQueryParameters,
        base_url: str
    ) -> OGCFeatureCollection
    """Query features with pagination and links."""

    def get_feature(
        self,
        collection_id: str,
        feature_id: str,
        precision: int,
        base_url: str
    ) -> Dict[str, Any]
    """Get single feature."""

    def _generate_links(
        self,
        base_url: str,
        collection_id: str,
        params: OGCQueryParameters,
        total_count: int
    ) -> List[OGCLink]
    """Generate pagination links (self, next, prev)."""
```

### Trigger Layer (`triggers.py`)

**Key Functions**:

```python
def get_ogc_triggers() -> List[Dict[str, Any]]:
    """
    Return list of trigger configurations for function_app.py registration.

    Returns:
        List of dicts with 'route', 'methods', 'handler' keys
    """

class OGCLandingPageTrigger:
    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """GET /api/features"""

class OGCConformanceTrigger:
    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """GET /api/features/conformance"""

class OGCCollectionsTrigger:
    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """GET /api/features/collections"""

class OGCCollectionTrigger:
    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """GET /api/features/collections/{collection_id}"""

class OGCItemsTrigger:
    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """GET /api/features/collections/{collection_id}/items"""

class OGCItemTrigger:
    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """GET /api/features/collections/{collection_id}/items/{feature_id}"""
```

---

## Environment Variables

```bash
# Required
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_DATABASE=postgres
POSTGIS_USER=your_user
POSTGIS_PASSWORD=your_password

# Optional
POSTGIS_PORT=5432
OGC_SCHEMA=geo
OGC_GEOMETRY_COLUMN=geom  # or "shape" for ArcGIS
OGC_DEFAULT_LIMIT=100
OGC_MAX_LIMIT=10000
OGC_DEFAULT_PRECISION=6
OGC_BASE_URL=https://your-app.azurewebsites.net
OGC_QUERY_TIMEOUT=30
```

---

## Deployment Steps

### Standalone Deployment

1. **Copy module**:
   ```bash
   cp -r ogc_features/ /path/to/new-function-app/
   ```

2. **Create `function_app.py`**:
   ```python
   import azure.functions as func
   from ogc_features import get_ogc_triggers

   app = func.FunctionApp()

   # Register OGC triggers
   for trigger in get_ogc_triggers():
       app.route(
           route=trigger['route'],
           methods=trigger['methods'],
           auth_level=func.AuthLevel.ANONYMOUS
       )(trigger['handler'])
   ```

3. **Set environment variables** in Azure Portal

4. **Deploy**:
   ```bash
   func azure functionapp publish your-ogc-app
   ```

### Integrated Deployment (within rmhgeoapi)

1. **Update `function_app.py`**:
   ```python
   # Add to existing function_app.py
   from ogc_features import get_ogc_triggers

   # Register OGC triggers
   for trigger in get_ogc_triggers():
       app.route(
           route=trigger['route'],
           methods=trigger['methods'],
           auth_level=func.AuthLevel.ANONYMOUS
       )(trigger['handler'])
   ```

2. **Deploy**:
   ```bash
   func azure functionapp publish rmhgeoapibeta --python --build remote
   ```

---

## Testing Checklist

### Manual Testing

```bash
# Landing page
curl https://your-app.azurewebsites.net/api/features

# Conformance
curl https://your-app.azurewebsites.net/api/features/conformance

# Collections list
curl https://your-app.azurewebsites.net/api/features/collections

# Collection metadata
curl https://your-app.azurewebsites.net/api/features/collections/your_table

# Query features (bbox)
curl "https://your-app.azurewebsites.net/api/features/collections/your_table/items?bbox=-122.5,37.7,-122.3,37.9&limit=100"

# Query with simplification
curl "https://your-app.azurewebsites.net/api/features/collections/your_table/items?simplify=100&precision=4"

# Single feature
curl "https://your-app.azurewebsites.net/api/features/collections/your_table/items/123"
```

### Leaflet Integration

```javascript
// Dynamic simplification based on zoom
const updateLayer = () => {
    const zoom = map.getZoom();
    const simplify = zoom < 10 ? 100 : (zoom < 13 ? 10 : 0);
    const precision = zoom < 10 ? 3 : (zoom < 13 ? 5 : 6);
    const bounds = map.getBounds();
    const bbox = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth()
    ].join(',');

    fetch(`/api/features/collections/your_table/items?bbox=${bbox}&simplify=${simplify}&precision=${precision}&limit=1000`)
        .then(r => r.json())
        .then(geojson => {
            layer.clearLayers();
            layer.addData(geojson);
        });
};

map.on('moveend', updateLayer);
```

---

## Performance Considerations

### PostGIS Optimization

1. **Spatial Indexes** (Critical):
   ```sql
   -- Verify index exists
   SELECT tablename, indexname
   FROM pg_indexes
   WHERE schemaname = 'geo' AND indexdef LIKE '%USING gist%';

   -- Create if missing
   CREATE INDEX idx_your_table_geom ON geo.your_table USING GIST(geom);
   ```

2. **Statistics** (for query planner):
   ```sql
   ANALYZE geo.your_table;
   ```

3. **Simplification Guidelines**:
   - Zoom 1-9: `simplify=100` (100m tolerance)
   - Zoom 10-12: `simplify=10` (10m tolerance)
   - Zoom 13+: `simplify=0` (no simplification)

4. **Precision Guidelines**:
   - Zoom 1-9: `precision=3` (~111m resolution)
   - Zoom 10-12: `precision=5` (~1.1m resolution)
   - Zoom 13+: `precision=6` (~0.11m resolution)

### Azure Functions Settings

```json
{
  "extensions": {
    "http": {
      "routePrefix": "api",
      "maxConcurrentRequests": 100
    }
  },
  "functionTimeout": "00:05:00"
}
```

---

## Known Limitations (Phase 1)

1. **Single CRS Output**:
   - Only outputs EPSG:4326 (WGS84)
   - All PostGIS data stored as EPSG:4326
   - Client-side projection (Leaflet handles Equal Earth, etc.)
   - Future: CRS transformation via ST_Transform (Phase 2)

2. **Simple Attribute Filtering**:
   - Only supports key=value equality filters
   - Multiple filters use AND logic
   - No comparison operators (gt, lt, like, in) yet
   - Future: Advanced CQL2-JSON filters (Phase 2)

3. **No Property Selection**:
   - Returns all attributes
   - Future: `properties` parameter to select specific columns

4. **Read-Only API**:
   - No write operations (by design)
   - No POST/PUT/DELETE/PATCH
   - Future: NEVER (this is intentional)

---

## Future Enhancements

### Phase 2 Features (Lower Priority)
- [ ] CRS transformation support (ST_Transform) - **Confirmed future enhancement**
- [ ] Advanced CQL2-JSON filtering
- [ ] Property selection (properties parameter)
- [ ] Caching layer (Redis)
- [ ] Enhanced validation reports

### Phase 3 Features (Not Planned)
- ❌ **Vector tiles (MVT)** - Not needed (client uses Equal Earth maps, GeoJSON only)
- ❌ **Write operations** - Read-only API by design
- ❌ **Transactions extension** - Not applicable for read-only

### Production Readiness Features
- [ ] Enable validation checks (OGC_ENABLE_VALIDATION=true)
- [ ] Easy Auth integration (Azure Portal configuration)
- [ ] Performance monitoring and alerts
- [ ] Rate limiting (Azure API Management)
- [ ] Comprehensive logging

---

## Success Criteria

- [ ] All OGC Core conformance classes pass
- [ ] Leaflet map loads features smoothly
- [ ] Simplification reduces payload size by >50% at low zoom
- [ ] **Temporal queries work with flexible column names**
- [ ] **Attribute filtering works with simple key=value syntax**
- [ ] **Sorting works with OGC sortby syntax**
- [ ] Query execution <2 seconds for 10,000 features
- [ ] QGIS can connect as OGC client
- [ ] Module can be deployed standalone (no main app dependencies)
- [ ] Validation can be enabled for production readiness checks
- [ ] Documentation complete and clear

---

## Notes

**CRITICAL**: This module must remain COMPLETELY standalone:
- NO imports from `core/`, `infrastructure/`, `jobs/`, `services/`
- NO dependency on main `config.py`
- ONLY integration point is `function_app.py` route registration

**DATA ASSUMPTIONS** (Phase 1 - Development):
- All tables in `geo` schema are ETL-optimized
- Spatial indexes (GIST) exist on geometry columns
- Primary keys exist for feature IDs
- No validation checks performed (OGC_ENABLE_VALIDATION=false)
- For production, enable validation to verify optimization

**AUTHENTICATION**:
- Development: `auth_level=ANONYMOUS` (Azure Functions setting)
- Production: Easy Auth configured in Azure Portal (not in code)

**PROJECTION**:
- All data stored as EPSG:4326 in PostGIS
- API serves GeoJSON in EPSG:4326
- Client-side projection (Leaflet, MapLibre handle Equal Earth, etc.)
- No server-side CRS transformation in Phase 1
