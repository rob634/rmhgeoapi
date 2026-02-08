# OGC Features API - Table Metadata Integration

**Date**: 06 DEC 2025
**Status**: Implementation Complete - Ready for Standalone OGC App Integration

---

## Overview

This document describes the integration between the OGC API - Features implementation and the new `geo.table_metadata` registry table. The registry is the **source of truth** for vector table metadata, with STAC serving as an optional catalog copy.

**Key Principle**: Metadata lives in PostGIS. STAC is optional and copies from PostGIS for catalog convenience.

---

## Architecture

**Updated 07 FEB 2026**: Stage 3 (STAC) is now optional. STAC is for discovery, not application logic.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ETL LAYER                                   │
├─────────────────────────────────────────────────────────────────────┤
│  process_vector Job                                                 │
│  ├── Stage 1: CREATE TABLE + INSERT INTO geo.table_metadata         │
│  ├── Stage 2: INSERT features (with etl_batch_id)                   │
│  └── Stage 3 (OPTIONAL): INSERT pgstac.items if collection_id given │
│               Only runs if collection_id parameter is provided      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    geo.table_metadata (SOURCE OF TRUTH)             │
├─────────────────────────────────────────────────────────────────────┤
│  table_name (PK)  │ etl_job_id │ source_file │ source_format │ ... │
│  kba_polygons     │ abc123...  │ kba.shp     │ shp           │ ... │
│  countries        │ def456...  │ world.gpkg  │ gpkg          │ ... │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    OGC FEATURES API LAYER                           │
├─────────────────────────────────────────────────────────────────────┤
│  GET /api/features/collections/{id}                                 │
│  ├── Query geometry_columns (required - table discovery)            │
│  └── Query geo.table_metadata (optional - enhanced metadata)        │
│                                                                     │
│  Response includes:                                                 │
│  ├── description: "Source: kba.shp (125,000 features)..."           │
│  ├── extent.spatial.bbox: [from cached_bbox OR ST_Extent]           │
│  └── properties: {etl:job_id, source:file, ...}                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Note**: OGC Features API reads from `geo.table_metadata`, NOT from STAC. STAC is purely
optional for discovery. Data is fully accessible via OGC Features API without STAC.

---

## Database Schema

### Table: `geo.table_metadata`

**Created during**: Schema rebuild (Step 5b in `db_maintenance.py`)

```sql
CREATE TABLE IF NOT EXISTS geo.table_metadata (
    -- Primary key
    table_name VARCHAR(255) PRIMARY KEY,
    schema_name VARCHAR(63) DEFAULT 'geo',

    -- ETL Traceability (populated at Stage 1)
    etl_job_id VARCHAR(64),          -- Full 64-char CoreMachine job ID
    source_file VARCHAR(500),        -- Original filename (e.g., "countries.shp")
    source_format VARCHAR(50),       -- File format (shp, gpkg, geojson, csv, etc.)
    source_crs VARCHAR(50),          -- Original CRS before reprojection (e.g., "EPSG:32610")

    -- STAC Linkage (populated at Stage 3)
    stac_item_id VARCHAR(100),       -- STAC item ID in pgstac
    stac_collection_id VARCHAR(100), -- STAC collection (e.g., "system-vectors")

    -- Statistics (populated at Stage 1)
    feature_count INTEGER,           -- Total number of features
    geometry_type VARCHAR(50),       -- PostGIS geometry type (e.g., "MULTIPOLYGON")

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Pre-computed extent (avoids ST_Extent query on every request)
    bbox_minx DOUBLE PRECISION,
    bbox_miny DOUBLE PRECISION,
    bbox_maxx DOUBLE PRECISION,
    bbox_maxy DOUBLE PRECISION
);

-- Indexes
CREATE INDEX idx_table_metadata_etl_job_id ON geo.table_metadata(etl_job_id);
CREATE INDEX idx_table_metadata_stac_item_id ON geo.table_metadata(stac_item_id);

-- Permissions
GRANT SELECT ON geo.table_metadata TO rmhpgflexreader;
```

---

## OGC Features Changes

### 1. Model Change: `OGCCollection.properties`

**File**: `ogc_features/models.py`
**Lines**: 146-166

```python
class OGCCollection(BaseModel):
    # ... existing fields ...
    storageCrs: Optional[str] = Field(...)

    # NEW: Custom metadata properties (06 DEC 2025)
    # OGC API - Features allows additional properties beyond the core spec.
    properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom collection metadata (ETL traceability, STAC linkage)"
    )
```

**Properties Schema** (when available):
```json
{
  "etl:job_id": "abc123def456...",
  "source:file": "countries.shp",
  "source:format": "shp",
  "source:crs": "EPSG:32610",
  "stac:item_id": "countries-2024",
  "stac:collection_id": "system-vectors",
  "created": "2025-12-06T10:30:00+00:00",
  "updated": "2025-12-06T10:35:00+00:00"
}
```

---

### 2. Repository Method: `get_table_metadata()`

**File**: `ogc_features/repository.py`
**Lines**: 212-324

```python
def get_table_metadata(self, collection_id: str) -> Optional[Dict[str, Any]]:
    """
    Get custom metadata for a collection from geo.table_metadata registry.

    This registry is the SOURCE OF TRUTH for vector table metadata,
    populated during ETL (process_vector Stage 1) and updated with
    STAC linkage (Stage 3).

    Returns None if no metadata exists (table created outside process_vector,
    or geo.table_metadata table doesn't exist yet).

    Args:
        collection_id: Collection identifier (table name)

    Returns:
        Dict with metadata fields, or None if not found:
        {
            "etl_job_id": str,           # Full 64-char job ID
            "source_file": str,          # Original filename
            "source_format": str,        # File format (shp, gpkg, etc.)
            "source_crs": str,           # Original CRS before reprojection
            "stac_item_id": str,         # STAC item ID (if cataloged)
            "stac_collection_id": str,   # STAC collection (if cataloged)
            "feature_count": int,        # Number of features
            "geometry_type": str,        # PostGIS geometry type
            "created_at": str,           # ISO 8601 timestamp
            "updated_at": str,           # ISO 8601 timestamp
            "cached_bbox": [float, ...]  # [minx, miny, maxx, maxy] or None
        }
    """
```

**Key Implementation Details**:

1. **Table existence check**: First checks if `geo.table_metadata` exists (backward compatible with older deployments)
2. **Non-fatal errors**: Returns `None` on any error - collection can still be served without custom metadata
3. **Cached bbox**: Returns `[minx, miny, maxx, maxy]` array if all 4 coordinates present, otherwise `None`

**SQL Query**:
```sql
SELECT
    etl_job_id, source_file, source_format, source_crs,
    stac_item_id, stac_collection_id, feature_count,
    geometry_type, created_at, updated_at,
    bbox_minx, bbox_miny, bbox_maxx, bbox_maxy
FROM geo.table_metadata
WHERE table_name = %s
```

---

### 3. Service Enhancement: `get_collection()`

**File**: `ogc_features/service.py`
**Lines**: 171-303

**Changes**:

#### A. Fetch custom metadata
```python
# Get base metadata from geometry_columns (required - table must exist)
metadata = self.repository.get_collection_metadata(collection_id)

# Get custom metadata from geo.table_metadata registry (optional)
custom_metadata = self.repository.get_table_metadata(collection_id)
```

#### B. Prefer cached bbox over ST_Extent
```python
if custom_metadata and custom_metadata.get('cached_bbox'):
    # Use pre-computed bbox from geo.table_metadata (fast - no query)
    bbox = custom_metadata['cached_bbox']
elif metadata.get('bbox'):
    # Fall back to ST_Extent result (computed during get_collection_metadata)
    bbox = metadata['bbox']
```

**Performance Impact**: Avoids `ST_Extent(geom)` query on potentially large tables when cached bbox is available.

#### C. Enhanced description
```python
if custom_metadata and custom_metadata.get('source_file'):
    description = (
        f"Source: {custom_metadata['source_file']} "
        f"({feature_count:,} features). "
        f"Format: {custom_metadata.get('source_format', 'unknown')}. "
        f"Original CRS: {custom_metadata.get('source_crs', 'unknown')}."
    )
else:
    description = f"Vector features from {collection_id} table ({feature_count:,} features)"
```

#### D. Build properties dict
```python
properties = None
if custom_metadata:
    properties = {
        "etl:job_id": custom_metadata.get('etl_job_id'),
        "source:file": custom_metadata.get('source_file'),
        "source:format": custom_metadata.get('source_format'),
        "source:crs": custom_metadata.get('source_crs'),
        "stac:item_id": custom_metadata.get('stac_item_id'),
        "stac:collection_id": custom_metadata.get('stac_collection_id'),
        "created": custom_metadata.get('created_at'),
        "updated": custom_metadata.get('updated_at')
    }
    # Remove None values for cleaner JSON output
    properties = {k: v for k, v in properties.items() if v is not None}
```

---

## Example API Responses

### Before (no custom metadata):
```json
{
  "id": "kba_polygons",
  "title": "Kba Polygons",
  "description": "Vector features from kba_polygons table (125000 features)",
  "extent": {
    "spatial": {
      "bbox": [[-180, -90, 180, 90]],
      "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    }
  },
  "itemType": "feature",
  "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84", "http://www.opengis.net/def/crs/EPSG/0/4326"],
  "storageCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
  "links": [...]
}
```

### After (with custom metadata):
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
  "itemType": "feature",
  "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84", "http://www.opengis.net/def/crs/EPSG/0/4326"],
  "storageCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
  "properties": {
    "etl:job_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
    "source:file": "kba_shp.zip",
    "source:format": "shp",
    "source:crs": "EPSG:32610",
    "stac:item_id": "kba_polygons-2024",
    "stac:collection_id": "system-vectors",
    "created": "2025-12-06T10:30:00+00:00",
    "updated": "2025-12-06T10:35:00+00:00"
  },
  "links": [...]
}
```

---

## Standalone OGC App Integration Checklist

To integrate these changes into the standalone OGC Features app:

### 1. Model Changes
- [ ] Add `properties: Optional[Dict[str, Any]]` field to `OGCCollection` model
- [ ] Add import: `from typing import Dict, Any` (if not already present)

### 2. Repository Changes
- [ ] Add `get_table_metadata()` method to repository class
- [ ] Ensure it handles missing `geo.table_metadata` table gracefully (returns `None`)

### 3. Service Changes
- [ ] Modify `get_collection()` to call `get_table_metadata()`
- [ ] Implement cached bbox preference logic
- [ ] Implement enhanced description logic
- [ ] Implement properties dict building logic

### 4. Database Prerequisites
- [ ] Ensure `geo.table_metadata` table exists (created by schema rebuild or manually)
- [ ] Ensure read permissions on `geo.table_metadata` for the database user

---

## Backward Compatibility

The implementation is fully backward compatible:

1. **Missing `geo.table_metadata` table**: Returns `None`, collection served with default metadata
2. **Missing metadata row**: Returns `None`, collection served with default metadata
3. **Database errors**: Logged as warning, collection served with default metadata
4. **Empty properties**: If no custom metadata fields have values, `properties` is `null` in response

Tables created outside the ETL pipeline (e.g., manually uploaded, existing tables) will simply have the default OGC behavior with no custom `properties` field.

---

## OGC Compliance Notes

The OGC API - Features Core 1.0 specification does not prescribe:
- How collection metadata is stored
- How bounding boxes are computed
- What additional properties can be included

Our implementation:
- Stores metadata in `geo.table_metadata` (PostgreSQL)
- Uses pre-computed bbox when available (performance optimization)
- Adds a `properties` field with ETL/STAC metadata (allowed by spec)

All responses remain OGC-compliant. The `properties` field is simply an additional field that OGC clients can ignore if they don't understand it.

---

## Files Modified

| File | Lines | Description |
|------|-------|-------------|
| `ogc_features/models.py` | 146-166 | Added `properties` field to `OGCCollection` |
| `ogc_features/repository.py` | 212-324 | Added `get_table_metadata()` method |
| `ogc_features/service.py` | 171-303 | Enhanced `get_collection()` with metadata integration |

---

## Testing

After deployment, verify with:

```bash
# 1. Check collection with metadata
curl https://your-app.azurewebsites.net/api/features/collections/kba_polygons | jq

# Expected: description shows source file, properties field present

# 2. Check collection without metadata (legacy table)
curl https://your-app.azurewebsites.net/api/features/collections/some_old_table | jq

# Expected: default description, no properties field (or properties: null)

# 3. Verify no ST_Extent in logs for tables with cached bbox
# Check Application Insights for query patterns
```
