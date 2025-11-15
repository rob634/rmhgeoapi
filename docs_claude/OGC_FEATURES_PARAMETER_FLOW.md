# OGC Features API - Parameter Flow Documentation

**Date**: 14 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ PRODUCTION - Live in $web container

---

## 🎯 Overview

Complete trace of `precision` and `simplify` parameters from browser UI → Azure Functions → PostGIS ST_AsGeoJSON.

---

## 📊 Parameter Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. BROWSER ($web static website)                                        │
│    https://rmhazuregeo.z13.web.core.windows.net/                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ User sets:
                                    │ • precision: 4 (dropdown)
                                    │ • simplify: 10 (input field)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. HTTP REQUEST                                                          │
│    GET /api/features/collections/test_geojson_fresh/items               │
│        ?limit=100&precision=4&simplify=10                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. AZURE FUNCTION TRIGGER (ogc_features/triggers.py)                    │
│    • Parses query string parameters                                     │
│    • Validates with OGCQueryParameters Pydantic model                   │
│    • precision: int (0-15, default=6)                                   │
│    • simplify: Optional[float] (>=0)                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. SERVICE LAYER (ogc_features/service.py)                              │
│    • Calls repository.get_features(...)                                 │
│    • Passes precision=4, simplify=10.0                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. REPOSITORY LAYER (ogc_features/repository.py)                        │
│    • _build_geometry_expression(geom_col, simplify=10.0, precision=4)  │
│    • Generates SQL with parameterized query                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. POSTGRESQL QUERY (psycopg parameterized)                             │
│    SELECT                                                                │
│        id, property1, property2, ...,                                   │
│        ST_AsGeoJSON(ST_Simplify(geom, $1), $2) as geometry              │
│    FROM geo.test_geojson_fresh                                          │
│    WHERE ... LIMIT 100                                                  │
│                                                                          │
│    Parameters: [$1=10.0, $2=4]                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 7. POSTGIS EXECUTION                                                     │
│    • ST_Simplify(geom, 10.0)     ← Reduce vertices (10m tolerance)     │
│    • ST_AsGeoJSON(..., 4)         ← Quantize coords (4 decimal places)  │
│    • Returns GeoJSON string                                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 8. JSON RESPONSE                                                         │
│    {                                                                     │
│      "type": "FeatureCollection",                                       │
│      "features": [{                                                      │
│        "geometry": {                                                     │
│          "type": "Polygon",                                              │
│          "coordinates": [[[-66.2, -54.94], ...]]  ← 4 decimals!         │
│        }                                                                 │
│      }]                                                                  │
│    }                                                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Detailed Code Trace

### Step 1: Browser UI ($web/index.html)

**File**: Azure Storage `$web/index.html`
**Lines**: 203-209

```html
<label for="precision-input">Precision (decimal places):</label>
<input type="number" id="precision-input" min="0" max="15" value="6" step="1">
<div class="help-text">0-15 decimals (6≈10cm, 4≈10m, 2≈1km)</div>

<label for="simplify-input">Simplify (meters):</label>
<input type="number" id="simplify-input" min="0" value="" step="1" placeholder="Optional (e.g., 10)">
<div class="help-text">Reduce vertices (empty = none, 10 = 10m tolerance)</div>
```

**JavaScript** (lines 311-340):
```javascript
async function loadFeatures() {
    const precision = document.getElementById('precision-input').value;
    const simplify = document.getElementById('simplify-input').value;

    // Build URL with optimization parameters
    let url = `${API_BASE_URL}/api/features/collections/${collectionId}/items?limit=${limit}`;

    // Add precision (always include since it has a default)
    if (precision) {
        url += `&precision=${precision}`;
    }

    // Add simplify (only if user specified a value)
    if (simplify && simplify > 0) {
        url += `&simplify=${simplify}`;
    }

    const response = await fetch(url);
    // ...
}
```

**Output**: `GET /api/features/collections/test_geojson_fresh/items?limit=100&precision=4&simplify=10`

---

### Step 2: Pydantic Validation (ogc_features/models.py)

**File**: `ogc_features/models.py`
**Lines**: 212-268

```python
class OGCQueryParameters(BaseModel):
    """Query parameters for OGC Features items endpoint."""

    # Pagination
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)

    # Spatial filtering
    bbox: Optional[List[float]] = Field(default=None)

    # Geometry optimization
    precision: int = Field(
        default=6,
        ge=0,
        le=15,
        description="Coordinate precision (decimal places for quantization)"
    )
    simplify: Optional[float] = Field(
        default=None,
        ge=0,
        description="Simplification tolerance in meters (ST_Simplify)"
    )
```

**Validation Rules**:
- `precision`: Integer, 0-15 range, default=6
- `simplify`: Optional float, must be >= 0 if provided

---

### Step 3: HTTP Trigger (ogc_features/triggers.py)

**File**: `ogc_features/triggers.py`
**Lines**: ~150-180 (approximate, need to verify exact location)

The trigger extracts query parameters and validates them:

```python
def get_collection_items(req: func.HttpRequest) -> func.HttpResponse:
    """Get features from a collection."""
    collection_id = req.route_params.get('collectionId')

    # Parse query parameters
    params = OGCQueryParameters(
        limit=int(req.params.get('limit', 100)),
        offset=int(req.params.get('offset', 0)),
        precision=int(req.params.get('precision', 6)),
        simplify=float(req.params.get('simplify')) if req.params.get('simplify') else None,
        # ... other params
    )

    # Call service layer
    return service.get_collection_items(collection_id, params)
```

**Output**: Pydantic-validated `OGCQueryParameters` object with `precision=4`, `simplify=10.0`

---

### Step 4: Service Layer (ogc_features/service.py)

**File**: `ogc_features/service.py`
**Lines**: ~200-250 (approximate)

```python
def get_collection_items(
    self,
    collection_id: str,
    params: OGCQueryParameters
) -> OGCFeatureCollection:
    """Get features from collection."""

    # Call repository with validated parameters
    features, total_count = self.repository.get_features(
        collection_id=collection_id,
        limit=params.limit,
        offset=params.offset,
        bbox=params.bbox,
        precision=params.precision,      # ← 4
        simplify=params.simplify,        # ← 10.0
        # ... other params
    )

    # Build response
    return OGCFeatureCollection(...)
```

**Output**: Passes `precision=4`, `simplify=10.0` to repository

---

### Step 5: Repository Layer (ogc_features/repository.py)

**File**: `ogc_features/repository.py`
**Lines**: 605-628

```python
def _build_geometry_expression(
    self,
    geom_column: str,
    simplify: Optional[float],
    precision: int
) -> Tuple[sql.Composed, List[Any]]:
    """
    Build ST_AsGeoJSON expression with optional simplification.

    Returns:
        Tuple of (SQL expression, parameters list)
    """
    if simplify and simplify > 0:
        # With simplification (2 parameters: simplify tolerance, precision)
        expr = sql.SQL(
            "ST_AsGeoJSON(ST_Simplify({geom_col}, %s), %s)"
        ).format(geom_col=sql.Identifier(geom_column))
        return (expr, [simplify, precision])
    else:
        # No simplification (1 parameter: precision)
        expr = sql.SQL(
            "ST_AsGeoJSON({geom_col}, %s)"
        ).format(geom_col=sql.Identifier(geom_column))
        return (expr, [precision])
```

**Called from** `_build_feature_query()` (lines ~420-450):

```python
def _build_feature_query(
    self,
    collection_id: str,
    limit: int,
    offset: int,
    # ... other params
    precision: int,
    simplify: Optional[float]
) -> Dict[str, Any]:
    """Build complete feature query with all filters and optimizations."""

    # Get geometry expression
    geom_expr, geom_params = self._build_geometry_expression(
        geom_column,
        simplify,    # ← 10.0
        precision    # ← 4
    )

    # Build final query
    query = sql.SQL("""
        SELECT
            {columns},
            {geom_expr} as geometry
        FROM {schema}.{table}
        WHERE ...
        LIMIT %s OFFSET %s
    """).format(
        columns=...,
        geom_expr=geom_expr,  # ← ST_AsGeoJSON(ST_Simplify(geom, %s), %s)
        schema=...,
        table=...
    )

    # Parameters list
    params = [...] + geom_params + [limit, offset]
    # geom_params = [10.0, 4] from _build_geometry_expression

    return {"query": query, "params": params}
```

**Output**: SQL with parameterized query

---

### Step 6: PostgreSQL Execution

**Generated SQL** (psycopg uses parameterized queries for safety):

```sql
SELECT
    id,
    ann_pre,
    ave_tem,
    barren,
    -- ... all non-geometry columns
    ST_AsGeoJSON(ST_Simplify(geom, $1), $2) as geometry
FROM geo.test_geojson_fresh
WHERE ... -- filters if any
LIMIT $3 OFFSET $4
```

**Parameters Array**: `[10.0, 4, 100, 0]`
- `$1` = 10.0 (simplify tolerance in meters)
- `$2` = 4 (precision decimal places)
- `$3` = 100 (limit)
- `$4` = 0 (offset)

---

### Step 7: PostGIS Execution

**PostGIS Functions**:

1. **ST_Simplify(geometry, tolerance)**
   - **Purpose**: Douglas-Peucker algorithm to reduce vertex count
   - **Tolerance**: 10.0 meters (in this example)
   - **Effect**: Removes vertices within 10m tolerance, preserving shape
   - **Input**: `POLYGON((-66.20 -54.94, -66.18 -54.94, ...))`
   - **Output**: `POLYGON((-66.20 -54.94, -66.17 -54.93, ...))` ← Fewer vertices!

2. **ST_AsGeoJSON(geometry, precision)**
   - **Purpose**: Convert PostGIS geometry to GeoJSON string
   - **Precision**: 4 decimal places (in this example)
   - **Effect**: Rounds coordinates to 4 decimals (~10m accuracy at equator)
   - **Input**: `POLYGON((-66.200001 -54.940002, ...))`
   - **Output**: `{"type":"Polygon","coordinates":[[[-66.2,-54.94],...]]}` ← 4 decimals!

**Coordinate Accuracy by Precision**:
- `precision=0`: ~111 km (degree level)
- `precision=1`: ~11 km
- `precision=2`: ~1.1 km
- `precision=3`: ~111 m
- `precision=4`: ~11 m
- `precision=5`: ~1.1 m
- `precision=6`: ~11 cm (default)
- `precision=7`: ~1 cm
- `precision=15`: Maximum precision

---

## 🎯 Why This Matters

### Performance Benefits

**Example with 1000 features**:

| Scenario | Precision | Simplify | Avg Coords/Feature | Response Size | Transfer Time |
|----------|-----------|----------|-------------------|---------------|---------------|
| Default | 6 | none | 50 | 1.2 MB | 2.4s |
| Optimized | 4 | 10m | 30 | 0.5 MB | 1.0s |
| Aggressive | 2 | 50m | 15 | 0.2 MB | 0.4s |

**Benefits**:
- ✅ **Smaller payloads**: Fewer decimals = smaller JSON
- ✅ **Faster rendering**: Fewer vertices = faster Leaflet drawing
- ✅ **Reduced bandwidth**: Critical for mobile users
- ✅ **Better UX**: Faster map interactions

### Trade-offs

**Precision**:
- ❌ **Too low (0-2)**: Distorted shapes, inaccurate coordinates
- ✅ **Balanced (4-5)**: Good for web maps, ~10m accuracy
- ⚠️ **Too high (8-15)**: Unnecessary precision, larger payloads

**Simplify**:
- ❌ **Too aggressive (>100m)**: Collapsed geometries, visual artifacts
- ✅ **Balanced (5-20m)**: Cleaner shapes, faster rendering
- ⚠️ **None**: Maximum detail but slower performance

---

## 📝 User Guidance ($web Map)

**Help Text in UI**:

```
Precision (0-15 decimals):
  6 ≈ 10cm accuracy (default, detailed)
  4 ≈ 10m accuracy (balanced for web maps)
  2 ≈ 1km accuracy (overview maps)

Simplify (meters):
  empty = no simplification (max detail)
  10 = 10m tolerance (balanced)
  50 = 50m tolerance (aggressive, use cautiously)
```

---

## 🚨 Important Notes

### 1. Simplify Units (Meters vs Degrees)

**Current Implementation**: `simplify` parameter is in **meters**, but data is stored in **EPSG:4326 (degrees)**.

**How it works**:
- PostGIS ST_Simplify uses **geometry's SRID units**
- For EPSG:4326, tolerance is in **degrees**, not meters
- A `simplify=10` means **10 degrees** (huge!), not 10 meters

**⚠️ CRITICAL BUG DISCOVERED**:
The OGC Features API says "meters" but it's actually using degrees. This is why `simplify=10` collapses geometries!

**Conversion**:
- At equator: 1 degree ≈ 111,000 meters
- For 10m tolerance: `simplify=10/111000 = 0.00009` degrees

**TODO**: Fix this in `ogc_features/repository.py`:
```python
# Option 1: Convert meters to degrees
if simplify and simplify > 0:
    # Convert meters to degrees at equator (rough approximation)
    simplify_degrees = simplify / 111000.0

# Option 2: Use ST_Transform to project before simplifying
# ST_Simplify(ST_Transform(geom, 3857), tolerance_meters)
```

### 2. Small Geometries Warning

H3 hexagons in `test_geojson_fresh` are **tiny** (a few hundred meters across):
- `simplify=10` degrees = 1,110 km tolerance → **Collapses to null!**
- `simplify=0.0001` degrees = 11m tolerance → Should work

### 3. Parameter Validation

Pydantic ensures:
- ✅ `precision` is 0-15 integer
- ✅ `simplify` is >= 0 if provided
- ✅ No SQL injection (psycopg parameterized queries)

---

## 📚 Related Files

**Backend**:
- `ogc_features/models.py` (lines 258-268) - Parameter definitions
- `ogc_features/triggers.py` - HTTP parameter parsing
- `ogc_features/service.py` - Service layer orchestration
- `ogc_features/repository.py` (lines 605-628) - SQL generation

**Frontend**:
- Azure Storage `$web/index.html` (lines 203-340) - UI and JavaScript

**Documentation**:
- `docs_claude/VECTOR_ETL_COMPLETE.md` - Vector ETL workflow
- `CLAUDE.md` (lines 320-342) - OGC Features API overview

---

## ✅ Status

- ✅ Parameters implemented in OGC Features API
- ✅ UI controls added to $web map
- ✅ Live in production (https://rmhazuregeo.z13.web.core.windows.net/)
- ⚠️ **Bug identified**: Simplify parameter uses degrees, not meters (needs fix)

**Next Steps**:
1. Fix simplify units (meters → degrees conversion)
2. Add validation to prevent geometry collapse
3. Update help text with correct units
4. Test with larger geometries (not tiny H3 hexagons)
