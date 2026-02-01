# WIKI_OGC_FEATURES.md - OGC API Features Implementation Guide

**Created**: 23 DEC 2025
**Last Updated**: 31 JAN 2026
**Last Verified**: 31 JAN 2026 (all endpoints tested)
**Status**: Production
**Spec Version**: OGC API - Features - Part 1: Core 1.0.0

---

## Overview

This document is the comprehensive reference for our OGC API - Features implementation. It covers spec compliance, architecture, error handling, and developer guidance.

**Spec URL**: https://docs.ogc.org/is/17-069r3/17-069r3.html

### Deployment Architecture

The orchestrator app provides OGC Features for **internal/emergency use**. For B2C production access, use TiTiler/TiPG which provides the same data plus vector tiles.

| Endpoint | Use Case | Vector Tiles |
|----------|----------|--------------|
| Orchestrator `/api/features` | Internal, emergency, debugging | ❌ No |
| TiPG `/vector` | B2C production, web mapping | ✅ Yes (MVT) |

**Note**: Collection metadata responses include links to TiPG endpoints for seamless integration.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Endpoints](#endpoints)
3. [Query Parameters](#query-parameters)
4. [Error Handling (OGC Compliant)](#error-handling-ogc-compliant)
5. [Metadata Integration](#metadata-integration)
6. [Performance Optimization](#performance-optimization)
7. [Known Issues](#known-issues)
8. [Testing](#testing)

---

## Architecture

### Component Structure

```
ogc_features/
├── __init__.py           # Package exports
├── config.py             # OGC Features configuration
├── models.py             # Pydantic models (OGCCollection, OGCQueryParameters, etc.)
├── repository.py         # PostgreSQL/PostGIS queries
├── service.py            # Business logic layer
└── triggers.py           # Azure Functions HTTP handlers
```

### Data Flow

```
HTTP Request
    │
    ▼
┌─────────────────────────────────────────────────┐
│ triggers.py                                      │
│ ├── Parse query params                          │
│ ├── Validate with OGCQueryParameters            │
│ └── Return 400 on InvalidParameterError         │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ service.py                                       │
│ ├── Orchestrate repository calls                │
│ ├── Build OGC response models                   │
│ └── Add HATEOAS links                           │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ repository.py                                    │
│ ├── Build parameterized SQL                     │
│ ├── Query PostGIS (ST_AsGeoJSON, ST_Simplify)   │
│ └── Return features + metadata                  │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ PostgreSQL + PostGIS                             │
│ ├── geo.* tables (vector data)                  │
│ ├── geo.table_catalog (service layer metadata)  │
│ └── geometry_columns (PostGIS catalog)          │
└─────────────────────────────────────────────────┘
```

---

## Endpoints

### Core Endpoints (OGC API - Features Part 1)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/features` | GET | Landing page |
| `/api/features/conformance` | GET | Conformance declaration |
| `/api/features/collections` | GET | List all collections |
| `/api/features/collections/{collectionId}` | GET | Collection metadata |
| `/api/features/collections/{collectionId}/items` | GET | Query features |
| `/api/features/collections/{collectionId}/items/{featureId}` | GET | Single feature |

### Response Content Types

- `application/geo+json` (default)
- `application/json`

---

## Query Parameters

### Standard OGC Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Max features to return (1-10000) |
| `offset` | integer | 0 | Skip N features (pagination) |
| `bbox` | string | - | Bounding box filter: `minx,miny,maxx,maxy` |
| `datetime` | string | - | Temporal filter (ISO 8601) |
| `crs` | string | CRS84 | Coordinate reference system |

### Extension Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `precision` | integer | 6 | Coordinate decimal places (0-15) |
| `simplify` | float | - | Geometry simplification tolerance |
| `sortby` | string | - | Sort by property |
| `datetime_property` | string | - | Property to use for datetime filter |

### Precision Reference

| Value | Accuracy | Use Case |
|-------|----------|----------|
| 0 | ~111 km | Country-level overview |
| 2 | ~1.1 km | City-level maps |
| 4 | ~11 m | Street-level maps |
| 6 | ~11 cm | Default, detailed |
| 8 | ~1 mm | Survey/engineering |

---

## Error Handling (OGC Compliant)

### Spec Requirements

Per OGC API - Features Part 1 Core, Section 7.6:

| Requirement | ID | Rule |
|-------------|-----|------|
| Unknown params | `/req/core/query-param-unknown` | Return 400 for unknown query parameters |
| Invalid values | `/req/core/query-param-invalid` | Return 400 for invalid parameter values |

### Implementation

**File**: `ogc_features/triggers.py`

```python
class InvalidParameterError(Exception):
    """
    OGC API Features parameter validation error.

    Requirement /req/core/query-param-invalid:
    "Server SHALL respond with status code 400 if request URI includes
    a query parameter with an INVALID value"
    """
    def __init__(self, param_name: str, param_value: str, expected_type: str):
        self.param_name = param_name
        self.param_value = param_value
        self.expected_type = expected_type
        super().__init__(
            f"Invalid value '{param_value}' for parameter '{param_name}': {expected_type}"
        )
```

### Error Response Format

```json
{
  "code": "InvalidParameterValue",
  "description": "Invalid value 'abc' for parameter 'limit': must be a positive integer"
}
```

### Error Examples

| Request | Response Code | Error |
|---------|---------------|-------|
| `?limit=abc` | 400 | Invalid value 'abc' for parameter 'limit': must be a positive integer |
| `?limit=-5` | 400 | Invalid value '-5' for parameter 'limit': must be a positive integer |
| `?bbox=1,2,three,4` | 400 | Invalid value '1,2,three,4' for parameter 'bbox': all values must be valid numbers |
| `?bbox=1,2,3` | 400 | Invalid value '1,2,3' for parameter 'bbox': must have 4 values (2D) or 6 values (3D) |
| `?precision=high` | 400 | Invalid value 'high' for parameter 'precision': must be a non-negative integer |

### DO NOT

```python
# WRONG - Silent fallback violates OGC spec
try:
    params['limit'] = int(req.params['limit'])
except ValueError:
    pass  # User never knows their param was ignored

# RIGHT - Explicit 400 error
try:
    params['limit'] = int(req.params['limit'])
except ValueError:
    raise InvalidParameterError('limit', req.params['limit'], 'must be a positive integer')
```

---

## Metadata Integration

### Source of Truth: `geo.table_catalog` (22 JAN 2026)

Vector table metadata is stored in PostGIS, with STAC as an optional catalog copy.

**Architecture Note**: The schema was refactored in JAN 2026 to separate:
- **Service layer metadata** (`geo.table_catalog`) - Suitable for replication to external databases
- **ETL traceability** (`app.vector_etl_tracking`) - Internal only, never replicated

DDL is generated from Pydantic models via IaC pattern. See `core/models/geo.py`.

```sql
-- geo.table_catalog: Service layer metadata (replicable)
CREATE TABLE geo.table_catalog (
    table_name VARCHAR(255) PRIMARY KEY,
    schema_name VARCHAR(100) NOT NULL DEFAULT 'geo',

    -- Service Layer Metadata
    title VARCHAR(500),
    description TEXT,
    attribution VARCHAR(500),
    license VARCHAR(100),
    keywords VARCHAR(500),
    providers JSONB DEFAULT '[]',

    -- STAC Linkage
    stac_item_id VARCHAR(255),
    stac_collection_id VARCHAR(100),

    -- Statistics
    feature_count INTEGER,
    geometry_type VARCHAR(50),
    srid INTEGER DEFAULT 4326,
    bbox JSONB,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ETL traceability is stored separately in app.vector_etl_tracking (internal only)
```

### Collection Response with Metadata

```json
{
  "id": "kba_polygons",
  "title": "Kba Polygons",
  "description": "Source: kba_shp.zip (125,000 features). Format: shp. Original CRS: EPSG:32610.",
  "extent": {
    "spatial": {
      "bbox": [[-70.7, -56.3, -70.5, -56.1]],
      "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    }
  },
  "properties": {
    "etl:job_id": "a1b2c3d4...",
    "source:file": "kba_shp.zip",
    "source:format": "shp",
    "source:crs": "EPSG:32610",
    "stac:item_id": "kba_polygons-2024",
    "stac:collection_id": "system-vectors"
  }
}
```

---

## Performance Optimization

### Geometry Optimization

**File**: `ogc_features/repository.py`

```python
def _build_geometry_expression(
    self,
    geom_column: str,
    simplify: Optional[float],
    precision: int
) -> Tuple[sql.Composed, List[Any]]:
    """Build ST_AsGeoJSON with optional simplification."""

    if simplify and simplify > 0:
        # With simplification
        expr = sql.SQL(
            "ST_AsGeoJSON(ST_Simplify({geom_col}, %s), %s)"
        ).format(geom_col=sql.Identifier(geom_column))
        return (expr, [simplify, precision])
    else:
        # No simplification
        expr = sql.SQL(
            "ST_AsGeoJSON({geom_col}, %s)"
        ).format(geom_col=sql.Identifier(geom_column))
        return (expr, [precision])
```

### Cached Bounding Box

When available, `geo.table_catalog.bbox_*` fields are used instead of computing `ST_Extent(geom)` on every request.

```python
if custom_metadata and custom_metadata.get('cached_bbox'):
    # Use pre-computed bbox (fast)
    bbox = custom_metadata['cached_bbox']
else:
    # Fall back to ST_Extent (slow for large tables)
    bbox = metadata.get('bbox')
```

### Response Size Optimization

| Scenario | Precision | Simplify | Response Size |
|----------|-----------|----------|---------------|
| Default | 6 | none | 1.2 MB |
| Optimized | 4 | 10m | 0.5 MB |
| Aggressive | 2 | 50m | 0.2 MB |

---

## Known Issues

### 1. Simplify Units (IMPORTANT)

**Status**: Known limitation (documented workaround)

The `simplify` parameter uses PostGIS `ST_Simplify` which operates in the geometry's SRID units. For EPSG:4326, this is **degrees**, not meters.

**Workaround**: Use very small values (e.g., `simplify=0.001` for ~111m tolerance at equator)

**Conversion**: At equator, 1 degree ≈ 111,000 meters

| simplify value | Approximate tolerance |
|----------------|----------------------|
| 0.0001 | ~11 meters |
| 0.001 | ~111 meters |
| 0.01 | ~1.1 km |

**Future**: Consider implementing meters-to-degrees conversion or using `ST_Transform` to project before simplifying.

### 2. Unknown Parameter Validation

**Status**: Not yet implemented (low priority)

OGC spec requirement `/req/core/query-param-unknown` requires 400 for unknown parameters. Currently, unknown parameters are passed through as property filters.

**Impact**: Low - unknown params are ignored or treated as property filters, which is generally safe behavior.

---

## Testing

### Verified Test Results (31 JAN 2026)

All endpoints tested against production deployment:

| Endpoint | Test | Result |
|----------|------|--------|
| `GET /api/features` | Landing page with HATEOAS links | ✅ Pass |
| `GET /api/features/conformance` | Returns core + geojson conformance | ✅ Pass |
| `GET /api/features/collections` | Lists 15 collections | ✅ Pass |
| `GET /api/features/collections/{id}` | Returns metadata with TiPG links | ✅ Pass |
| `GET /api/features/collections/{id}/items` | Returns FeatureCollection | ✅ Pass |
| `GET /api/features/collections/{id}/items/{fid}` | Returns single Feature | ✅ Pass |
| `?limit=N` | Pagination works | ✅ Pass |
| `?offset=N` | Offset pagination works | ✅ Pass |
| `?bbox=minx,miny,maxx,maxy` | Spatial filtering works | ✅ Pass |
| `?precision=N` | Coordinate precision works | ✅ Pass |
| `?simplify=N` | Geometry simplification works | ✅ Pass |
| `?limit=abc` | Returns 400 InvalidParameterValue | ✅ Pass |
| `?bbox=1,2,three,4` | Returns 400 InvalidParameterValue | ✅ Pass |
| Missing collection | Returns 404 NotFound | ✅ Pass |

### Manual Testing

```bash
BASE_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

# Landing page
curl $BASE_URL/api/features

# List collections
curl $BASE_URL/api/features/collections

# Query features with parameters
curl "$BASE_URL/api/features/collections/hard_cutlines_v8_testing_v10/items?limit=10&precision=4"

# Test bbox filtering
curl "$BASE_URL/api/features/collections/hard_cutlines_v8_testing_v10/items?bbox=-76,4,-75,5&limit=5"

# Test invalid parameter (should return 400)
curl "$BASE_URL/api/features/collections/hard_cutlines_v8_testing_v10/items?limit=abc"
```

### Expected 400 Response

```json
{
  "code": "InvalidParameterValue",
  "description": "Invalid value 'abc' for parameter 'limit': must be a positive integer"
}
```

### Conformance Check

```bash
curl $BASE_URL/api/features/conformance
```

Expected conformance classes:
- `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core`
- `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson`

---

## Related Documentation

| Document | Description |
|----------|-------------|
| `docs_claude/OGC_FEATURES_METADATA_INTEGRATION.md` | Detailed metadata integration design |
| `docs_claude/ARCHITECTURE_DIAGRAMS.md` | System architecture diagrams |
| `SILENT_ERRORS.md` | Exception handling fixes including OGC triggers |

---

## File Reference

| File | Purpose |
|------|---------|
| `ogc_features/triggers.py` | HTTP handlers, parameter parsing, error responses |
| `ogc_features/service.py` | Business logic, response building |
| `ogc_features/repository.py` | PostGIS queries, SQL generation |
| `ogc_features/models.py` | Pydantic models for validation |
| `ogc_features/config.py` | Configuration management |

---

## Changelog

| Date | Change |
|------|--------|
| 31 JAN 2026 | Full endpoint verification; added deployment architecture section; updated test commands |
| 23 DEC 2025 | Added OGC-compliant 400 errors for invalid parameter values |
| 06 DEC 2025 | Added `geo.table_catalog` integration |
| 14 NOV 2025 | Added `precision` and `simplify` parameters |
