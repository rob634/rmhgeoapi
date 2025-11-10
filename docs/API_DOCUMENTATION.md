# RMH Geospatial API Documentation

**Author**: Robert and Geospatial Claude Legion
**Date**: 10 NOV 2025
**Version**: 1.0.0
**Base URL**: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net

---

## Overview

The RMH Geospatial API provides standards-compliant access to geospatial data through two main APIs:

1. **OGC API - Features** - Query vector features (points, lines, polygons) from PostGIS
2. **STAC API** - Discover and access raster/vector metadata through STAC catalog

Both APIs are:
- ✅ **Standards-compliant** (OGC and STAC specifications)
- ✅ **Production-ready** (Azure Functions serverless architecture)
- ✅ **Portable** (can be deployed separately for APIM routing)
- ✅ **GeoJSON-native** (direct integration with web maps)

---

## Quick Reference

### OGC API - Features (Vector Data)

**Purpose**: Query vector features with spatial/temporal/attribute filters

```bash
# Landing page
GET /api/features

# List collections
GET /api/features/collections

# Query features (main endpoint)
GET /api/features/collections/{collection_id}/items?bbox=-122.5,37.7,-122.3,37.9&limit=100
```

**Key Features**:
- Spatial filtering (bbox)
- Temporal queries (ISO 8601)
- Attribute filtering (key=value)
- Sorting (OGC sortby)
- Geometry simplification
- Pagination

**Documentation**: [ogc_features/README.md](../ogc_features/README.md)

---

### STAC API (Metadata Catalog)

**Purpose**: Discover geospatial collections and items metadata

```bash
# Landing page (catalog root)
GET /api/stac

# Conformance classes
GET /api/stac/conformance

# List collections
GET /api/stac/collections
```

**Key Features**:
- STAC v1.0.0 compliant
- pgSTAC backend
- Pure JSON responses
- Collection metadata
- Spatial/temporal extents

**Documentation**: [stac_api/README.md](../stac_api/README.md)

---

## API Comparison

| Feature | OGC API - Features | STAC API |
|---------|-------------------|----------|
| **Primary Use** | Query vector features | Discover metadata |
| **Data Type** | GeoJSON features | STAC JSON (metadata) |
| **Backend** | PostGIS (geo schema) | pgSTAC (pgstac schema) |
| **Filtering** | Spatial, temporal, attribute | Collection-based (Phase 2: item search) |
| **Output** | Feature geometries + properties | Metadata (extents, links, assets) |
| **Typical Client** | Web maps (Leaflet, MapLibre) | STAC Browser, pystac-client |

---

## Getting Started

### Prerequisites

- **HTTP Client** - curl, Postman, or programming language HTTP library
- **Web Browser** - For STAC Browser integration
- **Optional**: QGIS (for OGC Features), Python (for pystac-client)

### Authentication

**Current**: No authentication required (public endpoints)
**Future**: Azure AD OAuth2 via Azure API Management

---

## Common Use Cases

### Use Case 1: Display Vector Data on Web Map

**Scenario**: Show building footprints on Leaflet map with spatial filtering

**API**: OGC API - Features

**Steps**:
```javascript
// 1. Get user's map bounds
const bounds = map.getBounds();
const bbox = [
    bounds.getWest(),
    bounds.getSouth(),
    bounds.getEast(),
    bounds.getNorth()
].join(',');

// 2. Query features with optimization
const url = `/api/features/collections/buildings/items?` +
    `bbox=${bbox}&` +
    `simplify=10&` +
    `precision=5&` +
    `limit=1000`;

// 3. Fetch and display
fetch(url)
    .then(r => r.json())
    .then(geojson => {
        L.geoJSON(geojson).addTo(map);
    });
```

**See**: [OGC Features README - Leaflet Integration](../ogc_features/README.md#leaflet-integration)

---

### Use Case 2: Discover Available Datasets

**Scenario**: Build a data catalog showing what's available

**API**: STAC API

**Steps**:
```python
from pystac_client import Client

# 1. Connect to STAC catalog
catalog = Client.open('https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac')

# 2. List all collections
for collection in catalog.get_collections():
    print(f"{collection.id}: {collection.title}")
    print(f"  Spatial extent: {collection.extent.spatial.bboxes}")
    print(f"  Temporal extent: {collection.extent.temporal.intervals}")
```

**See**: [STAC API README - Python Client](../stac_api/README.md#python-client-integration)

---

### Use Case 3: Export Data for Analysis

**Scenario**: Download features for offline analysis in QGIS/ArcGIS

**API**: OGC API - Features

**Steps**:
```bash
# 1. Query features as GeoJSON
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/buildings/items?\
bbox=-122.5,37.7,-122.3,37.9&\
limit=10000" > buildings.geojson

# 2. Open in QGIS
# Layer → Add Layer → Add Vector Layer → buildings.geojson
```

**Alternative**: Add OGC WFS connection directly in QGIS (live connection)

---

### Use Case 4: Time Series Analysis

**Scenario**: Find all features updated in a specific time range

**API**: OGC API - Features

**Steps**:
```bash
# Query features updated between dates
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/buildings/items?\
datetime=2024-01-01/2024-12-31&\
datetime_property=date_updated&\
sortby=+date_updated&\
limit=1000"
```

---

## API Endpoints Reference

### OGC API - Features Endpoints

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/api/features` | GET | Landing page | [Link](https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features) |
| `/api/features/conformance` | GET | Conformance classes | [Link](https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/conformance) |
| `/api/features/collections` | GET | List collections | [Link](https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections) |
| `/api/features/collections/{id}` | GET | Collection metadata | `/api/features/collections/buildings` |
| `/api/features/collections/{id}/items` | GET | **Query features** | `/api/features/collections/buildings/items?bbox=...` |
| `/api/features/collections/{id}/items/{fid}` | GET | Single feature | `/api/features/collections/buildings/items/42` |

**Full Documentation**: [ogc_features/README.md](../ogc_features/README.md)

---

### STAC API Endpoints

| Endpoint | Method | Status | Description | Example |
|----------|--------|--------|-------------|---------|
| `/api/stac` | GET | ✅ Live | Landing page (catalog) | [Link](https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac) |
| `/api/stac/conformance` | GET | ✅ Live | Conformance classes | [Link](https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/conformance) |
| `/api/stac/collections` | GET | ✅ Live | List collections | [Link](https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections) |
| `/api/stac/collections/{id}` | GET | ⏳ Phase 2 | Collection detail | N/A |
| `/api/stac/collections/{id}/items` | GET | ⏳ Phase 2 | Query items | N/A |
| `/api/stac/search` | POST | ⏳ Phase 2 | Advanced search | N/A |

**Full Documentation**: [stac_api/README.md](../stac_api/README.md)

---

## Query Parameters Reference

### OGC API - Features Query Parameters

#### Pagination
```
?limit=100              # Max features to return (1-10000, default 100)
?offset=0               # Skip N features (default 0)
```

#### Spatial Filtering
```
?bbox=minx,miny,maxx,maxy   # Bounding box in EPSG:4326
                             # Example: -122.5,37.7,-122.3,37.9
```

#### Temporal Filtering
```
?datetime=2024-01-01                    # Exact date
?datetime=2024-01-01/2024-12-31        # Date range
?datetime=../2024-12-31                 # Before date
?datetime=2024-01-01/..                 # After date
?datetime_property=date_updated         # Specify datetime column (optional)
```

#### Attribute Filtering
```
?key=value                              # Simple equality (AND logic for multiple)
?status=active&year=2024                # Multiple filters
```

#### Sorting
```
?sortby=+field                          # Ascending
?sortby=-field                          # Descending
?sortby=+field1,-field2                 # Multiple columns
```

#### Geometry Optimization
```
?precision=6                            # Coordinate decimals (default: 6)
?simplify=100                           # Simplification tolerance (meters)
```

**Examples**:
```bash
# Optimized for web map (low zoom)
?bbox=-125,32,-114,42&simplify=100&precision=3&limit=5000

# High detail query
?bbox=-122.5,37.7,-122.3,37.9&precision=6&limit=1000

# Temporal + spatial
?bbox=-122.5,37.7,-122.3,37.9&datetime=2024-01-01/2024-12-31
```

---

## Response Formats

### OGC API - Features Response (GeoJSON)

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-122.4, 37.8], ...]]
      },
      "properties": {
        "name": "Building A",
        "status": "active",
        "year": 2024
      }
    }
  ],
  "links": [
    {"rel": "self", "href": "..."},
    {"rel": "next", "href": "..."}
  ],
  "numberMatched": 1250,
  "numberReturned": 100
}
```

---

### STAC API Response (STAC Catalog)

**Landing Page**:
```json
{
  "id": "rmh-geospatial-stac",
  "type": "Catalog",
  "stac_version": "1.0.0",
  "description": "STAC catalog for geospatial data",
  "links": [
    {"rel": "self", "href": "https://.../api/stac"},
    {"rel": "data", "href": "https://.../api/stac/collections"}
  ]
}
```

**Collections**:
```json
{
  "collections": [
    {
      "id": "landsat-8",
      "type": "Collection",
      "stac_version": "1.0.0",
      "title": "Landsat 8 Imagery",
      "extent": {
        "spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [["2013-04-11T00:00:00Z", null]]}
      },
      "links": [
        {"rel": "self", "href": "https://.../collections/landsat-8"},
        {"rel": "items", "href": "https://.../collections/landsat-8/items"}
      ]
    }
  ]
}
```

---

## Performance Guidelines

### OGC API - Features Optimization

**For Web Maps**:
| Zoom Level | Recommended Settings | Expected Reduction |
|------------|---------------------|-------------------|
| 1-9 (World) | `simplify=100&precision=3` | 90% |
| 10-12 (City) | `simplify=10&precision=5` | 60% |
| 13+ (Street) | `simplify=0&precision=6` | 0% (full detail) |

**Query Performance**:
- Spatial index required (GIST on geometry column)
- Target: <2 seconds for 10,000 features
- Use `limit` parameter to paginate large results

---

### STAC API Optimization

**Collection Queries**:
- Collections list cached at service layer
- Typical response: <500ms for catalog with 100 collections
- pgSTAC uses JSONB indexes for fast metadata queries

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success | Valid query returned features |
| 400 | Bad Request | Invalid bbox format |
| 404 | Not Found | Collection doesn't exist |
| 500 | Internal Server Error | Database connection failed |

### Error Response Format

**OGC API - Features**:
```json
{
  "code": "BadRequest",
  "description": "Invalid bbox format: expected 4 numbers"
}
```

**STAC API**:
```json
{
  "code": "InternalServerError",
  "description": "Database connection failed"
}
```

---

## Integration Examples

### Python (OGC Features)

```python
import requests

# Query features
response = requests.get(
    'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/buildings/items',
    params={
        'bbox': '-122.5,37.7,-122.3,37.9',
        'limit': 1000,
        'simplify': 10
    }
)

geojson = response.json()
print(f"Found {geojson['numberReturned']} features")
```

---

### Python (STAC API)

```python
from pystac_client import Client

# Connect to catalog
catalog = Client.open('https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac')

# List collections
for collection in catalog.get_collections():
    print(f"{collection.id}: {collection.title}")
```

---

### JavaScript (Leaflet + OGC Features)

```javascript
const map = L.map('map').setView([37.8, -122.4], 12);

function loadFeatures() {
    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    fetch(`/api/features/collections/buildings/items?bbox=${bbox}&limit=1000`)
        .then(r => r.json())
        .then(geojson => L.geoJSON(geojson).addTo(map));
}

map.on('moveend', loadFeatures);
loadFeatures();
```

---

## Standards Compliance

### OGC API - Features

**Conforms to**:
- ✅ OGC API - Features Core 1.0
- ✅ GeoJSON (RFC 7946)
- ⏳ OpenAPI 3.0 (planned)

**Reference**: http://www.opengis.net/doc/IS/ogcapi-features-1/1.0

---

### STAC API

**Conforms to**:
- ✅ STAC API v1.0.0 Core
- ✅ STAC API v1.0.0 Collections
- ✅ OGC API - Features Core (basis for STAC)
- ⏳ STAC API Item Search (Phase 2)

**Reference**: https://github.com/radiantearth/stac-api-spec/tree/v1.0.0

---

## Future Enhancements

### OGC API - Features (Phase 2)

- [ ] CRS transformation (EPSG:3857, etc.)
- [ ] CQL2-JSON advanced filtering
- [ ] Property selection (`?properties=name,status`)
- [ ] OpenAPI 3.0 documentation endpoint

### STAC API (Phase 2)

- [ ] Collection detail endpoint
- [ ] Items search endpoint (`/collections/{id}/items`)
- [ ] Item detail endpoint (`/collections/{id}/items/{item_id}`)
- [ ] Advanced search (`POST /search`)
- [ ] CQL2 filtering support

### Azure API Management Integration

**Future Architecture** (when ready):
```
https://geospatial.rmh.org/api/features/*  → OGC Features Function App
https://geospatial.rmh.org/api/stac/*      → STAC API Function App
```

Benefits:
- Unified domain and SSL
- Granular access control (Azure AD)
- Rate limiting per client
- API versioning (/v1/, /v2/)

**See**: [APIM Integration Architecture](../docs_claude/APIM_INTEGRATION_ARCHITECTURE.md)

---

## Support & Contact

### Documentation

- **OGC Features**: [ogc_features/README.md](../ogc_features/README.md)
- **STAC API**: [stac_api/README.md](../stac_api/README.md)
- **Project Context**: [CLAUDE.md](../CLAUDE.md)

### Troubleshooting

**Check Application Insights** for detailed error logs:
```bash
# See CLAUDE.md section "Application Insights Log Access"
az login
# Query logs using KQL
```

### Reporting Issues

For production issues:
1. Check endpoint health: `GET /api/health`
2. Review Application Insights logs
3. Verify database connectivity
4. Check environment variable configuration

---

## Version History

### 1.0.0 (10 NOV 2025)

**Initial Release**

**OGC API - Features**:
- ✅ 6 endpoints operational
- ✅ Spatial, temporal, attribute filtering
- ✅ Geometry optimization (simplify + precision)
- ✅ 2,600+ lines, fully documented

**STAC API**:
- ✅ 3 endpoints operational (Phase 1)
- ✅ STAC v1.0.0 compliant
- ✅ Pure JSON responses
- ✅ ~500 lines, portable module

**Infrastructure**:
- ✅ Azure Functions serverless
- ✅ PostgreSQL + PostGIS + pgSTAC
- ✅ Production-ready deployment

---

## License

Part of rmhgeoapi project - Internal use only.

---

## Authors

**Robert and Geospatial Claude Legion**
Date: 10 NOV 2025

For detailed technical documentation, see module-specific READMEs.
