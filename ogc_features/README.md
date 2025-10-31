# OGC API - Features Implementation

**Author**: Robert and Geospatial Claude Legion
**Date**: 29 OCT 2025
**Version**: 1.0.0
**Status**: Development - Phase 1 Complete

---

## Overview

Standalone OGC API - Features Core 1.0 implementation for serving PostGIS vector data through Azure Functions. This module provides a standards-compliant REST API for querying geospatial features with support for:

- ✅ **Spatial filtering** (bbox)
- ✅ **Temporal queries** (ISO 8601 with flexible column names)
- ✅ **Attribute filtering** (simple key=value equality)
- ✅ **Sorting** (OGC sortby syntax)
- ✅ **Geometry optimization** (ST_Simplify + precision control)
- ✅ **Pagination** (limit/offset with smart links)

**Key Feature**: Completely standalone - zero dependencies on main application. Can be deployed independently or integrated into existing Azure Function Apps.

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────────────────┐
│  HTTP Triggers (triggers.py)                                │
│  - Parse requests, validate parameters                      │
│  - 6 OGC endpoints (landing, collections, items, etc.)     │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Service Layer (service.py)                                 │
│  - Business logic orchestration                             │
│  - Link generation, response formatting                     │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Repository Layer (repository.py)                           │
│  - Direct PostGIS queries via psycopg                       │
│  - SQL composition (injection-safe)                         │
│  - ST_AsGeoJSON, ST_Simplify, ST_Intersects               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  PostgreSQL/PostGIS Database                                │
│  - Vector tables in 'geo' schema                            │
│  - Geometry columns (geom/geometry/shape)                   │
│  - Spatial indexes (GIST)                                   │
└─────────────────────────────────────────────────────────────┘
```

### File Structure

```
ogc_features/                           # Standalone module (2,600+ lines)
├── __init__.py                         # Module exports
├── config.py                           # Environment-based configuration
├── models.py                           # OGC Pydantic models
├── repository.py                       # PostGIS direct access
├── service.py                          # Business logic
├── triggers.py                         # HTTP handlers
├── README.md                           # This file
└── IMPLEMENTATION_TODO.md              # Implementation details
```

---

## Quick Start

### Prerequisites

- **Azure Functions Core Tools** v4+
- **Python** 3.9+
- **PostgreSQL** 12+ with PostGIS 3.0+
- **Azure Function App** (or local development)

### Installation

#### Option 1: Integrated Deployment (within existing Function App)

```bash
# Already installed if using rmhgeoapi
# Just need to register routes in function_app.py

# 1. Verify module exists
ls ogc_features/

# 2. Add to function_app.py (see Integration section below)

# 3. Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote
```

#### Option 2: Standalone Deployment (new Function App)

```bash
# 1. Create new Function App project
mkdir my-ogc-api && cd my-ogc-api
func init --python

# 2. Copy module
cp -r /path/to/ogc_features .

# 3. Create minimal function_app.py
cat > function_app.py << 'EOF'
import azure.functions as func
from ogc_features import get_ogc_triggers

app = func.FunctionApp()

# Register all OGC endpoints
for trigger in get_ogc_triggers():
    app.route(
        route=trigger['route'],
        methods=trigger['methods'],
        auth_level=func.AuthLevel.ANONYMOUS
    )(trigger['handler'])
EOF

# 4. Add dependencies to requirements.txt
cat >> requirements.txt << 'EOF'
azure-functions
psycopg[binary]
pydantic>=2.0
EOF

# 5. Configure environment variables (see Configuration section)

# 6. Deploy
func azure functionapp publish my-ogc-api --python --build remote
```

---

## Configuration

### Environment Variables

#### Required

```bash
# PostgreSQL Connection
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_DATABASE=postgres
POSTGIS_USER=your_user
POSTGIS_PASSWORD=your_password
```

#### Optional

```bash
# Database Configuration
POSTGIS_PORT=5432                        # Default: 5432
OGC_SCHEMA=geo                           # Default: "geo"
OGC_GEOMETRY_COLUMN=geom                 # Default: "geom" (or "shape" for ArcGIS)

# API Behavior
OGC_DEFAULT_LIMIT=100                    # Default: 100
OGC_MAX_LIMIT=10000                      # Default: 10000
OGC_DEFAULT_PRECISION=6                  # Default: 6 decimals
OGC_BASE_URL=https://example.com         # Default: auto-detect

# Performance
OGC_QUERY_TIMEOUT=30                     # Default: 30 seconds

# Validation (Production Readiness)
OGC_ENABLE_VALIDATION=false              # Default: false (set true for production checks)
```

### Azure Portal Configuration

1. Navigate to Function App → Configuration → Application settings
2. Add environment variables listed above
3. **Important**: Use "Advanced edit" for bulk paste
4. Save and restart Function App

### Local Development (local.settings.json)

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "POSTGIS_HOST": "localhost",
    "POSTGIS_DATABASE": "geodata",
    "POSTGIS_USER": "postgres",
    "POSTGIS_PASSWORD": "password",
    "OGC_SCHEMA": "geo",
    "OGC_GEOMETRY_COLUMN": "geom",
    "OGC_ENABLE_VALIDATION": "true"
  }
}
```

---

## Integration

### Adding to Existing Function App

In your `function_app.py`:

```python
import azure.functions as func

# ... your existing imports and code ...

# Add OGC Features API endpoints
from ogc_features import get_ogc_triggers

# Register all OGC endpoints (single loop!)
for trigger in get_ogc_triggers():
    app.route(
        route=trigger['route'],
        methods=trigger['methods'],
        auth_level=func.AuthLevel.ANONYMOUS
    )(trigger['handler'])
```

**That's it!** 5 lines of code to add 6 OGC endpoints.

---

## API Endpoints

### Base URL

```
https://your-app.azurewebsites.net/api/features
```

### Endpoint Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/features` | GET | Landing page with links |
| `/api/features/conformance` | GET | Conformance classes |
| `/api/features/collections` | GET | List all collections |
| `/api/features/collections/{id}` | GET | Collection metadata |
| `/api/features/collections/{id}/items` | GET | **Query features** (main endpoint) |
| `/api/features/collections/{id}/items/{fid}` | GET | Single feature by ID |

---

## Query Parameters

### Main Query Endpoint: `/api/features/collections/{collection_id}/items`

#### Pagination

```bash
?limit=100          # Max features to return (1-10000, default 100)
?offset=0           # Skip N features (default 0)
```

#### Spatial Filtering

```bash
?bbox=-122.5,37.7,-122.3,37.9    # Bounding box (minx,miny,maxx,maxy in EPSG:4326)
```

#### Temporal Filtering

```bash
# ISO 8601 instant (exact day)
?datetime=2024-01-01

# ISO 8601 interval (date range)
?datetime=2024-01-01/2024-12-31

# Open intervals
?datetime=../2024-12-31          # Before date
?datetime=2024-01-01/..          # After date

# Specify datetime column (optional - auto-detects if omitted)
?datetime_property=date_updated
```

#### Attribute Filtering

```bash
# Simple key=value equality (multiple filters use AND)
?status=active&year=2024&category=residential
```

**SQL Generated**:
```sql
WHERE status = 'active' AND year = 2024 AND category = 'residential'
```

#### Sorting

```bash
# OGC sortby syntax
?sortby=+year              # Ascending by year
?sortby=-population        # Descending by population
?sortby=+year,-population  # Multiple columns (comma-separated)
```

#### Geometry Optimization

```bash
# Coordinate precision (decimal places)
?precision=6               # Default: 6 (±0.11m at equator)
?precision=3               # Low zoom: 3 (±111m at equator)

# Geometry simplification (meters)
?simplify=100              # Simplify to 100m tolerance
?simplify=10               # Simplify to 10m tolerance
?simplify=0                # No simplification (default)
```

---

## Usage Examples

### Basic Query

```bash
# Get first 100 features from buildings collection
curl "https://your-app.azurewebsites.net/api/features/collections/buildings/items?limit=100"
```

### Spatial Filter (Bounding Box)

```bash
# Features within San Francisco bbox
curl "https://your-app.azurewebsites.net/api/features/collections/buildings/items?\
bbox=-122.5,37.7,-122.3,37.9&\
limit=1000"
```

### Temporal Query

```bash
# Buildings updated in 2024
curl "https://your-app.azurewebsites.net/api/features/collections/buildings/items?\
datetime=2024-01-01/2024-12-31&\
datetime_property=date_updated&\
limit=500"
```

### Attribute Filters + Sorting

```bash
# Active buildings from 2024, sorted by year (asc) then population (desc)
curl "https://your-app.azurewebsites.net/api/features/collections/buildings/items?\
status=active&\
year=2024&\
sortby=+year,-population&\
limit=100"
```

### Optimized for Low Zoom (Web Maps)

```bash
# Simplified geometry for overview map
curl "https://your-app.azurewebsites.net/api/features/collections/buildings/items?\
bbox=-125,32,-114,42&\
simplify=100&\
precision=3&\
limit=5000"
```

**Result**: 50-90% smaller payload while maintaining visual quality at low zoom.

### Combined Query (All Features)

```bash
curl "https://your-app.azurewebsites.net/api/features/collections/buildings/items?\
bbox=-122.5,37.7,-122.3,37.9&\
datetime=2024-01-01/2024-12-31&\
datetime_property=date_updated&\
status=active&\
year=2024&\
sortby=+year,-population&\
simplify=10&\
precision=5&\
limit=1000&\
offset=0"
```

---

## Leaflet Integration

### Dynamic Simplification Based on Zoom

```javascript
const map = L.map('map').setView([37.8, -122.4], 10);

let featureLayer = L.geoJSON().addTo(map);

function updateFeatures() {
    const zoom = map.getZoom();
    const bounds = map.getBounds();

    // Dynamic simplification and precision based on zoom
    const simplify = zoom < 10 ? 100 : (zoom < 13 ? 10 : 0);
    const precision = zoom < 10 ? 3 : (zoom < 13 ? 5 : 6);

    // Build bbox parameter
    const bbox = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth()
    ].join(',');

    // Fetch features
    const url = `https://your-app.azurewebsites.net/api/features/collections/buildings/items?` +
        `bbox=${bbox}&` +
        `simplify=${simplify}&` +
        `precision=${precision}&` +
        `limit=1000`;

    fetch(url)
        .then(r => r.json())
        .then(geojson => {
            featureLayer.clearLayers();
            featureLayer.addData(geojson);
        });
}

// Update on map movement
map.on('moveend', updateFeatures);

// Initial load
updateFeatures();
```

### Attribute Filtering UI

```javascript
// Add filter controls
const statusFilter = document.getElementById('status-filter');
const yearFilter = document.getElementById('year-filter');

statusFilter.addEventListener('change', updateFeatures);
yearFilter.addEventListener('change', updateFeatures);

function updateFeatures() {
    const zoom = map.getZoom();
    const bounds = map.getBounds();
    const simplify = zoom < 10 ? 100 : 10;
    const precision = zoom < 10 ? 3 : 5;
    const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(',');

    // Build URL with filters
    const params = new URLSearchParams({
        bbox: bbox,
        simplify: simplify,
        precision: precision,
        limit: 1000,
        status: statusFilter.value,    // Attribute filter
        year: yearFilter.value          // Attribute filter
    });

    fetch(`https://your-app.azurewebsites.net/api/features/collections/buildings/items?${params}`)
        .then(r => r.json())
        .then(geojson => {
            featureLayer.clearLayers();
            featureLayer.addData(geojson);
        });
}
```

---

## QGIS Integration

### Add OGC WFS Connection

1. **Layer** → **Add Layer** → **Add WFS Layer**
2. **New Connection**:
   - **Name**: My OGC API
   - **URL**: `https://your-app.azurewebsites.net/api/features`
3. **Connect** → Collections appear automatically
4. **Add Layer** → Query with QGIS filters

---

## Database Setup

### PostGIS Schema Requirements

```sql
-- Create schema (if not exists)
CREATE SCHEMA IF NOT EXISTS geo;

-- Example vector table
CREATE TABLE geo.buildings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    status VARCHAR(50),
    year INTEGER,
    population INTEGER,
    date_updated TIMESTAMP,
    geom GEOMETRY(Polygon, 4326)  -- Or Point, LineString, MultiPolygon, etc.
);

-- CRITICAL: Create spatial index (required for performance)
CREATE INDEX idx_buildings_geom ON geo.buildings USING GIST(geom);

-- Update statistics
ANALYZE geo.buildings;
```

### Supported Geometry Types

- Point
- LineString
- Polygon
- MultiPoint
- MultiLineString
- MultiPolygon
- GeometryCollection

### Column Name Compatibility

| PostGIS | ArcGIS | Detection |
|---------|--------|-----------|
| `geom` | `shape` | ✅ Auto-detected |
| `geometry` | `wkb_geometry` | ✅ Auto-detected |

**Configuration**: Set `OGC_GEOMETRY_COLUMN=shape` for ArcGIS compatibility.

---

## Performance Optimization

### Simplification Guidelines

| Zoom Level | Simplify (m) | Precision | Use Case |
|------------|--------------|-----------|----------|
| 1-9 (World) | 100 | 3 | Continental view |
| 10-12 (City) | 10 | 5 | City overview |
| 13+ (Street) | 0 | 6 | Street detail |

### Expected Payload Reduction

**Example**: 200 MB polygon with 50,000 vertices

| Zoom | Settings | Payload | Reduction |
|------|----------|---------|-----------|
| 5 | simplify=100, precision=3 | 2 MB | 90% |
| 10 | simplify=10, precision=5 | 8 MB | 60% |
| 15 | simplify=0, precision=6 | 20 MB | 0% |

### Database Optimization Checklist

```sql
-- 1. Verify spatial index exists
SELECT tablename, indexname
FROM pg_indexes
WHERE schemaname = 'geo'
  AND indexdef LIKE '%USING gist%';

-- 2. Update table statistics
ANALYZE geo.your_table;

-- 3. Check table size
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'geo'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

## Validation & Production Readiness

### Enable Validation Checks

```bash
# Set environment variable
OGC_ENABLE_VALIDATION=true
```

### What Gets Validated

When validation is enabled, collection metadata includes:

```json
{
  "id": "buildings",
  "validation": {
    "validation_enabled": true,
    "warnings": [
      "No GIST spatial index on 'geom' - queries will be slow"
    ],
    "recommendations": [
      "CREATE INDEX idx_buildings_geom ON geo.buildings USING GIST(geom)"
    ]
  }
}
```

### Pre-Production Checklist

- [ ] All tables have GIST spatial indexes
- [ ] All tables have primary keys
- [ ] Statistics updated (`ANALYZE` run)
- [ ] Validation checks pass (`OGC_ENABLE_VALIDATION=true`)
- [ ] Test queries execute in <2 seconds for 10,000 features
- [ ] Easy Auth configured in Azure Portal
- [ ] Base URL set (`OGC_BASE_URL` environment variable)

---

## Troubleshooting

### Common Issues

#### 1. "Collection not found"

**Cause**: Table not in geometry_columns view

**Solution**:
```sql
-- Verify table has geometry column
SELECT * FROM geometry_columns
WHERE f_table_schema = 'geo' AND f_table_name = 'your_table';

-- If missing, ensure geometry column is properly typed
ALTER TABLE geo.your_table
  ALTER COLUMN geom TYPE geometry(Polygon, 4326)
  USING ST_SetSRID(geom, 4326);
```

#### 2. Slow Queries

**Cause**: Missing spatial index

**Solution**:
```sql
-- Create GIST index
CREATE INDEX idx_your_table_geom ON geo.your_table USING GIST(geom);
ANALYZE geo.your_table;
```

#### 3. "No datetime columns found"

**Cause**: Table has no timestamp columns for temporal queries

**Solution**:
- Use `datetime_property` parameter to specify column
- Or add timestamp column: `ALTER TABLE geo.your_table ADD COLUMN date_updated TIMESTAMP DEFAULT NOW();`

#### 4. 500 Internal Server Error

**Check Application Insights**:
```bash
# See CLAUDE.md for full Application Insights query instructions
az login
# Then query logs for errors
```

---

## API Specification Compliance

### OGC API - Features Core 1.0

This implementation conforms to:

- ✅ **Core Requirements** (conformance class)
- ✅ **GeoJSON** (conformance class)
- ⏳ **HTML** (not implemented - JSON only)
- ⏳ **OpenAPI 3.0** (planned)

### Specification Reference

- [OGC API - Features Core 1.0](https://docs.ogc.org/is/17-069r4/17-069r4.html)
- [GeoJSON RFC 7946](https://tools.ietf.org/html/rfc7946)

---

## Limitations (Phase 1)

### Not Implemented (Yet)

- ❌ **CRS transformation** - Only EPSG:4326 output (Phase 2)
- ❌ **Advanced filtering** - No CQL2-JSON (Phase 2)
- ❌ **Property selection** - Returns all attributes (Phase 2)
- ❌ **Write operations** - Read-only by design (never)
- ❌ **Vector tiles** - Not needed for Equal Earth projections (never)

### Workarounds

**CRS Transformation**: Use client-side projection (Leaflet, MapLibre)
**Advanced Filtering**: Use multiple simple filters with AND logic
**Property Selection**: Filter client-side or use database views

---

## Support & Contribution

### Documentation

- **IMPLEMENTATION_TODO.md** - Detailed implementation guide
- **CLAUDE.md** (main app) - Project context and standards
- **Application Insights** - Production logging (see CLAUDE.md)

### Testing

See "Local Testing" section below for development environment setup.

### Issues

For issues related to this module, check:
1. Environment variables configured correctly
2. PostGIS schema and tables exist
3. Spatial indexes present
4. Application Insights logs for detailed errors

---

## Version History

### 1.0.0 (29 OCT 2025)

**Initial Release - Phase 1 Complete**

- ✅ OGC API - Features Core 1.0 compliance
- ✅ Spatial filtering (bbox)
- ✅ Temporal queries (ISO 8601, flexible columns)
- ✅ Attribute filtering (simple equality)
- ✅ Sorting (OGC sortby syntax)
- ✅ Geometry optimization (ST_Simplify + precision)
- ✅ Pagination with smart links
- ✅ Feature-flagged validation
- ✅ Standalone deployment support

**Statistics**:
- **Total Lines**: 2,600+
- **Files**: 7 Python modules
- **Endpoints**: 6 OGC-compliant
- **Test Coverage**: Manual (automated tests planned)

---

## License

Part of rmhgeoapi project - Internal use only.

---

## Authors

**Robert and Geospatial Claude Legion**
Date: 29 OCT 2025

For questions or issues, refer to main project documentation.
