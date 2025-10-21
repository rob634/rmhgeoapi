# GeoAPI MVP: OGC-Compliant Vector Services Implementation

## Executive Summary

This document outlines the Minimum Viable Product (MVP) for World Bank's cloud-native geospatial vector API, replacing ArcGIS Enterprise Feature Services with modern, standards-based REST APIs. The MVP focuses on optimized GeoJSON delivery with intelligent simplification and precision control.

**Key Goals:**
- OGC API-Features Core compliance
- Intelligent on-the-fly geometry optimization
- Sub-200ms response times with CDN caching
- 60-80% file size reduction vs. raw PostGIS output
- Support for custom projections (Equal Earth, etc.)

**Future Enhancements:** MVT tiles, TopoJSON, CQL2 filtering

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│ Azure Front Door Premium (CDN + Cache)               │
│ - Cache GeoJSON responses (24 hours)                 │
│ - Gzip compression                                   │
│ - 99% of requests served from cache (~20ms)          │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│ Azure Function App (Premium - No Cold Start)         │
│ ┌──────────────────────────────────────────────────┐ │
│ │ HTTP Trigger: GET /collections                   │ │
│ │ HTTP Trigger: GET /collections/{id}              │ │
│ │ HTTP Trigger: GET /collections/{id}/items        │ │
│ └──────────────────┬───────────────────────────────┘ │
└────────────────────┼─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│ PostGIS (Azure PostgreSQL Flexible Server)           │
│ - ST_SimplifyPreserveTopology() for generalization   │
│ - ST_ReducePrecision() for coordinate quantization   │
│ - ST_AsGeoJSON() for output                          │
│ - Spatial indexes (GIST) for bbox queries            │
└───────────────────────────────────────────────────────┘
```

---

## OGC API-Features Compliance

### Core Conformance Classes (MVP)

#### 1. Landing Page
```
GET /
```
Returns API metadata and links to main endpoints.

**Response:**
```json
{
  "title": "World Bank Geospatial API",
  "description": "OGC API-Features compliant vector data services",
  "links": [
    {
      "href": "https://geoapi.worldbank.org/",
      "rel": "self",
      "type": "application/json",
      "title": "This document"
    },
    {
      "href": "https://geoapi.worldbank.org/conformance",
      "rel": "conformance",
      "type": "application/json",
      "title": "Conformance declaration"
    },
    {
      "href": "https://geoapi.worldbank.org/collections",
      "rel": "data",
      "type": "application/json",
      "title": "Collections"
    }
  ]
}
```

#### 2. Conformance Declaration
```
GET /conformance
```
Declares which OGC standards are implemented.

**Response:**
```json
{
  "conformsTo": [
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
  ]
}
```

#### 3. Collections List
```
GET /collections
```
Returns all available geospatial datasets.

**Response:**
```json
{
  "collections": [
    {
      "id": "countries",
      "title": "World Countries",
      "description": "International boundaries",
      "extent": {
        "spatial": {
          "bbox": [[-180, -90, 180, 90]],
          "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        },
        "temporal": {
          "interval": [["2024-01-01T00:00:00Z", null]]
        }
      },
      "links": [
        {
          "href": "https://geoapi.worldbank.org/collections/countries",
          "rel": "self",
          "type": "application/json"
        },
        {
          "href": "https://geoapi.worldbank.org/collections/countries/items",
          "rel": "items",
          "type": "application/geo+json"
        }
      ],
      "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]
    }
  ]
}
```

#### 4. Collection Metadata
```
GET /collections/{collectionId}
```
Returns metadata for a specific collection.

#### 5. Features (Core Endpoint)
```
GET /collections/{collectionId}/items
```
Returns GeoJSON feature collection.

**Query Parameters (OGC Standard):**
- `bbox` - Bounding box filter (minx,miny,maxx,maxy)
- `limit` - Maximum features to return (default: 100, max: 10000)
- `offset` - Pagination offset
- `datetime` - Temporal filter (ISO 8601)

**Custom Parameters (Optimization):**
- `precision` - Decimal places (1-8, default: auto)
- `simplify` - Simplification tolerance in degrees (default: auto)

---

## Smart Optimization Strategy

### Automatic Optimization Based on Scale

The API automatically adjusts precision and simplification based on the requested bounding box area to balance visual quality with file size.

```python
def calculate_optimization_settings(bbox):
    """
    Determine optimal precision and simplification
    based on geographic extent
    """
    width = bbox[2] - bbox[0]  # degrees longitude
    height = bbox[3] - bbox[1]  # degrees latitude
    area = width * height
    
    if area > 10000:  # Continental/global scale
        return {
            'precision': 4,        # ~11 meters
            'simplify': 0.01,      # ~1 km generalization
            'description': 'Global view'
        }
    elif area > 100:  # Country scale
        return {
            'precision': 5,        # ~1 meter
            'simplify': 0.001,     # ~100 meter generalization
            'description': 'Country view'
        }
    elif area > 1:  # Regional scale
        return {
            'precision': 5,
            'simplify': 0.0001,    # ~10 meter generalization
            'description': 'Regional view'
        }
    else:  # Local/city scale
        return {
            'precision': 6,        # ~10 centimeters
            'simplify': 0,         # No simplification
            'description': 'Local view'
        }
```

### Coordinate Precision Guidelines

| Decimal Places | Precision | Use Case | File Size Impact |
|----------------|-----------|----------|------------------|
| 1 | ~11 km | Continental outlines | -60% |
| 2 | ~1.1 km | Country borders | -50% |
| 3 | ~111 m | Regional features | -40% |
| 4 | ~11 m | **World maps (default)** | **-30%** |
| 5 | ~1 m | City-scale features | -20% |
| 6 | ~10 cm | **Standard GIS (PostGIS default)** | Baseline |
| 7 | ~1 cm | Surveying | +10% |
| 8 | ~1 mm | Engineering | +20% |

**Recommendation:** Default to 4-5 decimal places for web delivery. Only use 6+ for detailed local maps or when explicitly requested.

---

## PostGIS Implementation

### Core Query Template

```sql
-- Optimized GeoJSON query with automatic simplification
SELECT jsonb_build_object(
    'type', 'FeatureCollection',
    'features', jsonb_agg(feature),
    'metadata', jsonb_build_object(
        'count', count(*),
        'precision', :precision,
        'simplification', :simplify,
        'bbox', :bbox
    )
)
FROM (
    SELECT jsonb_build_object(
        'type', 'Feature',
        'id', id,
        'geometry', ST_AsGeoJSON(
            ST_ReducePrecision(
                CASE 
                    WHEN :simplify > 0 THEN 
                        ST_SimplifyPreserveTopology(geom, :simplify)
                    ELSE 
                        geom
                END,
                :precision_value  -- 10^-precision (e.g., 0.0001 for 4 decimals)
            ),
            :precision  -- Max decimal digits in JSON output
        )::jsonb,
        'properties', to_jsonb(row) - 'geom' - 'id'
    ) as feature
    FROM {table_name}
    WHERE 
        geom && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)
        AND (:datetime_filter IS NULL OR updated_at >= :datetime_filter)
    ORDER BY id
    LIMIT :limit
    OFFSET :offset
) features;
```

### Key PostGIS Functions

#### ST_SimplifyPreserveTopology()
Reduces vertex count while maintaining topology (no self-intersections).

```sql
-- Example: Simplify to ~1km tolerance
ST_SimplifyPreserveTopology(geom, 0.01)

-- Typical tolerances by scale:
-- Global: 0.01-0.05 degrees (~1-5 km)
-- Country: 0.001-0.01 degrees (~100m-1km)
-- Regional: 0.0001-0.001 degrees (~10-100m)
-- Local: 0.00001 or none (~1m or original)
```

#### ST_ReducePrecision()
Rounds coordinates to specified precision without changing topology.

```sql
-- Example: Round to 4 decimal places
ST_ReducePrecision(geom, 0.0001)  -- 10^-4

-- Common values:
-- 0.1 = 1 decimal place
-- 0.01 = 2 decimal places
-- 0.001 = 3 decimal places
-- 0.0001 = 4 decimal places (recommended)
-- 0.00001 = 5 decimal places
```

#### ST_AsGeoJSON()
Converts PostGIS geometry to GeoJSON string.

```sql
-- Syntax: ST_AsGeoJSON(geom, max_decimals, options)
ST_AsGeoJSON(geom, 4, 0)  -- 4 decimal places, no bbox

-- Options bitmask:
-- 0 = Default
-- 1 = Include bbox
-- 2 = Use short CRS format
-- 4 = Use long CRS format
```

### Optimization Order

**Always apply in this sequence:**
1. **Simplify** first (reduces vertices)
2. **Reduce precision** second (rounds coordinates)
3. **Convert to JSON** last (serialization)

```sql
-- ✅ CORRECT ORDER
ST_AsGeoJSON(
    ST_ReducePrecision(
        ST_SimplifyPreserveTopology(geom, 0.01),
        0.0001
    ),
    4
)

-- ❌ WRONG ORDER (precision then simplify - less effective)
ST_AsGeoJSON(
    ST_SimplifyPreserveTopology(
        ST_ReducePrecision(geom, 0.0001),
        0.01
    ),
    4
)
```

---

## Performance Targets

### Response Times

| Scenario | Target | Strategy |
|----------|--------|----------|
| Cache hit (Front Door) | < 50ms | CDN edge location |
| Cache miss, simple query | < 200ms | Optimized PostGIS query |
| Large bbox (1000+ features) | < 500ms | Limit features, suggest tiling |
| Complex geometries | < 1000ms | Aggressive simplification |

### File Size Reduction

| Dataset Type | Raw Size | Optimized Size | Reduction |
|--------------|----------|----------------|-----------|
| World countries (247) | 2.8 MB | 650 KB | 77% |
| US states (51) | 450 KB | 180 KB | 60% |
| City boundaries (500) | 1.2 MB | 400 KB | 67% |
| Project points (5000) | 800 KB | 350 KB | 56% |

**Key Factors:**
- Simplification: 40-60% reduction
- Precision reduction: 20-30% reduction
- Gzip compression: Additional 60-70% reduction

---

## Caching Strategy

### Cache Headers

```python
# For static/slow-changing data (admin boundaries)
headers = {
    'Cache-Control': 'public, max-age=86400',  # 24 hours
    'Vary': 'Accept-Encoding',
    'Content-Type': 'application/geo+json'
}

# For frequently updated data (project locations)
headers = {
    'Cache-Control': 'public, max-age=3600',  # 1 hour
    'Vary': 'Accept-Encoding',
    'Content-Type': 'application/geo+json'
}

# For real-time data (if needed)
headers = {
    'Cache-Control': 'public, max-age=300',  # 5 minutes
    'Vary': 'Accept-Encoding',
    'Content-Type': 'application/geo+json'
}
```

### Cache Invalidation

```python
from azure.mgmt.cdn import CdnManagementClient

def invalidate_collection_cache(collection_id):
    """
    Purge CDN cache when source data updates
    """
    cdn_client = CdnManagementClient(credential, subscription_id)
    
    # Purge all cached responses for this collection
    cdn_client.endpoints.begin_purge_content(
        resource_group='rg-geoapi',
        profile_name='fd-geoapi',
        endpoint_name='geoapi',
        content_paths=[
            f'/collections/{collection_id}',
            f'/collections/{collection_id}/items*'
        ]
    )
```

---

## Implementation Priorities

### Phase 1: Core OGC Compliance (Week 1-2)

**Endpoints to implement:**
1. ✅ `GET /` - Landing page
2. ✅ `GET /conformance` - Standards declaration
3. ✅ `GET /collections` - List datasets
4. ✅ `GET /collections/{id}` - Collection metadata
5. ✅ `GET /collections/{id}/items` - GeoJSON features

**Query parameters:**
- ✅ `bbox` - Spatial filter
- ✅ `limit` - Feature count limit
- ✅ `offset` - Pagination

### Phase 2: Optimization (Week 3-4)

**Features to add:**
1. ✅ Auto-optimization based on bbox area
2. ✅ `precision` query parameter
3. ✅ `simplify` query parameter
4. ✅ Response metadata (count, optimization settings)
5. ✅ Cache headers and CDN integration

### Phase 3: Polish (Week 5-6)

**Enhancements:**
1. ✅ OpenAPI/Swagger documentation
2. ✅ HTML responses (human-browsable)
3. ✅ Performance monitoring (Application Insights)
4. ✅ Error handling and validation
5. ✅ Load testing and optimization

### Future Enhancements (Post-MVP)

**Ordered by priority:**
1. **TopoJSON support** - 70-90% smaller files for admin boundaries
2. **CQL2 filtering** - Advanced attribute queries (`?filter=population > 1000000`)
3. **MVT tiles** - For large datasets or interactive exploration
4. **Property selection** - Return subset of attributes (`?properties=name,population`)
5. **Sorting** - Order results (`?sortby=+population,-name`)
6. **Multiple CRS support** - Beyond WGS84 (low priority for web)

---

## Example API Usage

### World Countries (Global View)

```bash
# Request
GET /collections/countries/items?bbox=-180,-90,180,90&limit=1000

# Auto-optimized response
# - Precision: 4 decimals (~11m)
# - Simplification: 0.01 degrees (~1km)
# - Size: 650 KB (vs 2.8 MB raw)
# - Load time: ~200ms first request, ~20ms cached
```

### US States (Country View)

```bash
# Request
GET /collections/countries/items?bbox=-125,24,-66,49&limit=100

# Auto-optimized response
# - Precision: 5 decimals (~1m)
# - Simplification: 0.001 degrees (~100m)
# - Size: 180 KB (vs 450 KB raw)
```

### Manual Override (High Detail)

```bash
# Request detailed local data
GET /collections/parcels/items?bbox=-77.04,38.90,-77.03,38.91&precision=6&simplify=0

# Response
# - Precision: 6 decimals (~10cm) 
# - Simplification: None
# - Use for: Detailed local maps, analysis
```

### Client Integration (D3.js + Equal Earth)

```javascript
// Fetch optimized world countries
const data = await fetch(
  '/collections/countries/items?bbox=-180,-90,180,90'
).then(r => r.json());

// Use with Equal Earth projection
const projection = d3.geoEqualEarth()
  .fitSize([width, height], data);

const path = d3.geoPath(projection);

svg.selectAll('path')
  .data(data.features)
  .enter()
  .append('path')
  .attr('d', path)
  .attr('fill', d => colorScale(d.properties.indicator_value));
```

---

## Success Metrics

### Technical Metrics
- ✅ Response times < 200ms (cache miss)
- ✅ File sizes 60-80% smaller than raw output
- ✅ 99%+ cache hit rate at CDN
- ✅ Zero downtime deployments
- ✅ OGC validation passing

### Business Metrics
- ✅ Replace 100% of ArcGIS Feature Services
- ✅ Support Data360 and DDH integration
- ✅ Enable Equal Earth and custom projections
- ✅ Reduce infrastructure costs by 90%
- ✅ Eliminate weekend maintenance windows

### User Experience
- ✅ Maps load in < 3 seconds (vs 10+ seconds with ArcGIS)
- ✅ Mobile-friendly file sizes
- ✅ Works with all modern mapping libraries
- ✅ Self-service via OpenAPI documentation

---

## Cost Analysis

### Current State (ArcGIS Enterprise)
- Windows VMs: $20,000/year
- ArcGIS licenses: $100,000/year
- Maintenance time: $30,000/year (20% of geospatial architect time)
- **Total: ~$150,000/year**

### Future State (Cloud-Native)
- PostgreSQL Flex (8 vCore): $7,200/year
- Functions Premium (EP2): $3,600/year
- Front Door Premium: $4,800/year
- Storage/bandwidth: $1,200/year
- Maintenance time: $3,000/year (2% of time)
- **Total: ~$20,000/year**

### ROI
- **Savings: $130,000/year (87% reduction)**
- **Payback period: Immediate**
- **Additional benefits:**
  - Zero unplanned downtime
  - Modern API standards
  - Custom projection support
  - Developer-friendly integration

---

## Appendix: OGC Resources

### Official Specifications
- [OGC API-Features Part 1: Core](https://docs.ogc.org/is/17-069r4/17-069r4.html)
- [OGC API-Features Part 2: CRS](https://docs.ogc.org/is/18-058r1/18-058r1.html)
- [RFC 7946: GeoJSON](https://datatracker.ietf.org/doc/html/rfc7946)

### Testing Tools
- [OGC Test Suite](https://cite.opengeospatial.org/teamengine/)
- [GeoJSON Validator](https://geojson.io/)

### Related Standards
- [STAC (SpatioTemporal Asset Catalog)](https://stacspec.org/) - For raster metadata
- [OGC API-Tiles](https://docs.ogc.org/is/20-057/20-057.html) - For MVT (future)

---

## Document Version

- **Version:** 1.0
- **Date:** October 2025
- **Author:** Robert and Claude Legion
- **Status:** MVP Implementation Guide