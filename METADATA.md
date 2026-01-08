# METADATA.md - Unified Metadata Architecture

**Created**: 08 JAN 2026
**Status**: Design Document
**Goal**: STAC-like universal metadata accessible from both OGC Features and STAC endpoints

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Architecture](#current-architecture)
3. [Current Metadata Fields](#current-metadata-fields)
4. [Gap Analysis: Current vs STAC Standard](#gap-analysis-current-vs-stac-standard)
5. [Proposed Unified Schema](#proposed-unified-schema)
6. [Implementation TODO](#implementation-todo)
7. [Key Files Reference](#key-files-reference)

---

## Executive Summary

### Problem Statement

Currently, metadata for vector datasets is stored in `geo.table_metadata` and exposed via OGC Features collections. However:

1. The structure is **not formally aligned** with STAC metadata standards
2. Getting rich metadata requires either:
   - Querying the OGC collection endpoint, OR
   - Querying a separate STAC endpoint
3. Users expect **consistent metadata** regardless of access path

### Goal

Create a **single source of truth** for metadata that:
- Is stored once in `geo.table_metadata`
- Maps cleanly to STAC Collection/Item metadata
- Is exposed identically via both `/api/features/collections/{id}` and `/api/stac/collections/{id}`
- Supports both vector (PostGIS) and raster (COG) data types

---

## Current Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ETL PIPELINE                                   │
│  (process_vector job / process_raster job)                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      geo.table_metadata                                  │
│  Source of truth for vector table metadata                              │
│  - ETL traceability (job_id, source_file, format, crs)                  │
│  - STAC linkage (stac_item_id, stac_collection_id)                      │
│  - User metadata (title, description, license, etc.)                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────────┐
│   OGC Features API            │   │   STAC API (pgstac)               │
│   /api/features/collections   │   │   /api/stac/collections           │
│                               │   │                                   │
│   - Uses geo.table_metadata   │   │   - Separate metadata in pgstac   │
│   - Returns OGC Collection    │   │   - Returns STAC Collection       │
│     with `properties` block   │   │     with full STAC structure      │
└───────────────────────────────┘   └───────────────────────────────────┘
```

### Storage Locations

| System | Table | Purpose |
|--------|-------|---------|
| Vector Metadata | `geo.table_metadata` | ETL-generated metadata for PostGIS tables |
| STAC Catalog | `pgstac.collections` / `pgstac.items` | STAC-compliant catalog (separate copy) |
| Promoted Layer | `app.promoted_datasets` | Display overrides, gallery, system roles |

### Current Problem

Metadata is **duplicated** between `geo.table_metadata` and `pgstac`. When vector data is ingested:

1. Stage 1: Creates PostGIS table + writes to `geo.table_metadata`
2. Stage 3: Creates STAC Item/Collection in `pgstac` (separate metadata copy)

This duplication means updates to one don't propagate to the other.

---

## Current Metadata Fields

### geo.table_metadata Schema

```sql
CREATE TABLE geo.table_metadata (
    -- Identity
    table_name          VARCHAR(255) PRIMARY KEY,

    -- ETL Traceability
    etl_job_id          VARCHAR(64),
    source_file         VARCHAR(500),
    source_format       VARCHAR(50),    -- shp, gpkg, geojson, etc.
    source_crs          VARCHAR(100),   -- Original CRS (e.g., EPSG:32618)

    -- STAC Linkage
    stac_item_id        VARCHAR(100),
    stac_collection_id  VARCHAR(100),

    -- Computed Fields
    feature_count       INTEGER,
    geometry_type       VARCHAR(50),    -- Point, LineString, Polygon, etc.
    bbox_minx           DOUBLE PRECISION,
    bbox_miny           DOUBLE PRECISION,
    bbox_maxx           DOUBLE PRECISION,
    bbox_maxy           DOUBLE PRECISION,

    -- User-Provided Metadata (added 09 DEC 2025)
    title               VARCHAR(200),
    description         TEXT,
    attribution         VARCHAR(500),
    license             VARCHAR(100),   -- SPDX identifier
    keywords            TEXT,           -- Comma-separated
    temporal_start      TIMESTAMPTZ,
    temporal_end        TIMESTAMPTZ,
    temporal_property   VARCHAR(100),   -- Column name for temporal queries

    -- Timestamps
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### OGC Collection Response (Current)

From `/api/features/collections/{collection_id}`:

```json
{
    "id": "admin_boundaries_chile",
    "title": "Chile Administrative Boundaries",
    "description": "Source: admin_chile.gpkg (156 features). Format: gpkg. Original CRS: EPSG:4326.",
    "links": [...],
    "extent": {
        "spatial": {
            "bbox": [[-75.6, -55.9, -66.4, -17.5]],
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        },
        "temporal": {
            "interval": [["2020-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]
        }
    },
    "itemType": "feature",
    "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
    "storageCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
    "properties": {
        "etl:job_id": "abc123...",
        "source:file": "admin_chile.gpkg",
        "source:format": "gpkg",
        "source:crs": "EPSG:4326",
        "stac:item_id": "admin-boundaries-chile-v1",
        "stac:collection_id": "vector-admin-boundaries",
        "created": "2025-12-09T14:30:00Z",
        "updated": "2025-12-09T14:30:00Z",
        "attribution": "OpenStreetMap Contributors",
        "license": "ODbL-1.0",
        "keywords": ["admin", "boundaries", "chile"],
        "feature_count": 156,
        "temporal_property": "updated_date"
    }
}
```

### app.promoted_datasets Schema

```sql
CREATE TABLE app.promoted_datasets (
    promoted_id         VARCHAR(64) PRIMARY KEY,

    -- STAC Reference (one required)
    stac_collection_id  VARCHAR(100),
    stac_item_id        VARCHAR(100),

    -- Display Overrides
    title               VARCHAR(200),
    description         TEXT,

    -- Thumbnail
    thumbnail_url       VARCHAR(500),
    thumbnail_generated_at TIMESTAMPTZ,

    -- Discovery
    tags                JSONB,          -- Array of strings
    viewer_config       JSONB,          -- Viewer-specific settings
    style_id            VARCHAR(100),   -- OGC Style reference

    -- Gallery
    in_gallery          BOOLEAN DEFAULT FALSE,
    gallery_order       INTEGER,

    -- System
    is_system_reserved  BOOLEAN DEFAULT FALSE,
    system_role         VARCHAR(50),    -- admin0_boundaries, h3_land_grid
    classification      VARCHAR(20) DEFAULT 'public',  -- public, ouo

    -- Timestamps
    promoted_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Gap Analysis: Current vs STAC Standard

### STAC Collection Fields

| STAC Field | Current Support | Location | Notes |
|------------|-----------------|----------|-------|
| `id` | ✅ Full | table_name | Direct mapping |
| `type` | ✅ Full | Hardcoded | Always "Collection" |
| `stac_version` | ✅ Full | Hardcoded | "1.0.0" |
| `stac_extensions` | ❌ Missing | - | Need to declare extensions |
| `title` | ✅ Full | geo.table_metadata | User-provided or auto |
| `description` | ✅ Full | geo.table_metadata | User-provided or auto |
| `keywords` | ⚠️ Partial | geo.table_metadata | Stored as comma-separated string |
| `license` | ✅ Full | geo.table_metadata | SPDX identifier |
| `providers` | ❌ Missing | - | Only have simple `attribution` |
| `extent.spatial` | ✅ Full | geo.table_metadata | bbox cached |
| `extent.temporal` | ✅ Full | geo.table_metadata | start/end timestamps |
| `summaries` | ❌ Missing | - | Property value ranges |
| `links` | ✅ Full | Generated | OGC + STAC links |
| `assets` | ❌ N/A | - | Collections don't have assets |

### STAC Item Fields (for vector items)

| STAC Field | Current Support | Location | Notes |
|------------|-----------------|----------|-------|
| `id` | ✅ Full | stac_item_id | |
| `type` | ✅ Full | Hardcoded | "Feature" |
| `stac_version` | ✅ Full | Hardcoded | |
| `stac_extensions` | ❌ Missing | - | |
| `geometry` | ✅ Full | Computed | From bbox |
| `bbox` | ✅ Full | geo.table_metadata | |
| `properties.datetime` | ⚠️ Partial | temporal_start | Single datetime or null |
| `properties.start_datetime` | ✅ Full | temporal_start | |
| `properties.end_datetime` | ✅ Full | temporal_end | |
| `properties.created` | ✅ Full | created_at | |
| `properties.updated` | ✅ Full | updated_at | |
| `links` | ✅ Full | Generated | |
| `assets` | ⚠️ Partial | - | Need OGC Features link as asset |
| `collection` | ✅ Full | stac_collection_id | |

### Custom Extensions Needed

For full STAC compatibility, we should use these extension namespaces:

```json
{
    "stac_extensions": [
        "https://stac-extensions.github.io/table/v1.2.0/schema.json",
        "https://stac-extensions.github.io/processing/v1.1.0/schema.json"
    ]
}
```

**Table Extension** (for vector data):
- `table:columns` - Column definitions
- `table:primary_geometry` - Primary geometry column
- `table:row_count` - Feature count

**Processing Extension** (for ETL traceability):
- `processing:software` - ETL pipeline info
- `processing:lineage` - Source file info

---

## Proposed Unified Schema

### New Fields for geo.table_metadata

```sql
ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS
    -- Provider info (STAC providers array as JSONB)
    providers           JSONB,          -- [{"name": "...", "roles": [...], "url": "..."}]

    -- STAC Extensions
    stac_extensions     JSONB,          -- Array of extension URIs

    -- Table Extension fields
    column_definitions  JSONB,          -- Column metadata
    primary_geometry    VARCHAR(100),   -- Primary geometry column name

    -- Processing Extension fields
    processing_software JSONB,          -- {"name": "rmhgeoapi", "version": "0.7.x"}
    processing_lineage  TEXT,           -- Processing description

    -- Additional STAC fields
    sci_doi             VARCHAR(200),   -- Scientific DOI if applicable
    sci_citation        TEXT;           -- Citation text
```

### Unified Metadata Model (Python)

```python
# Proposed: core/models/unified_metadata.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class ProviderRole(str, Enum):
    LICENSOR = "licensor"
    PRODUCER = "producer"
    PROCESSOR = "processor"
    HOST = "host"

class Provider(BaseModel):
    """STAC Provider definition."""
    name: str
    description: Optional[str] = None
    roles: List[ProviderRole] = []
    url: Optional[str] = None

class SpatialExtent(BaseModel):
    """Spatial extent with bbox."""
    bbox: List[List[float]]  # [[minx, miny, maxx, maxy]]
    crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

class TemporalExtent(BaseModel):
    """Temporal extent with interval."""
    interval: List[List[Optional[str]]]  # [[start, end]]

class Extent(BaseModel):
    """Combined spatial and temporal extent."""
    spatial: Optional[SpatialExtent] = None
    temporal: Optional[TemporalExtent] = None

class UnifiedMetadata(BaseModel):
    """
    Unified metadata model that maps to both OGC and STAC.

    This is the canonical representation stored in geo.table_metadata
    and served via both /api/features and /api/stac endpoints.
    """
    # Identity
    id: str = Field(..., description="Collection/table identifier")

    # Core STAC fields
    title: Optional[str] = None
    description: Optional[str] = None
    keywords: List[str] = []
    license: Optional[str] = None  # SPDX identifier

    # Providers (STAC standard)
    providers: List[Provider] = []

    # Extent
    extent: Optional[Extent] = None

    # ETL Traceability (Processing Extension)
    etl_job_id: Optional[str] = None
    source_file: Optional[str] = None
    source_format: Optional[str] = None
    source_crs: Optional[str] = None

    # Table Extension (vector-specific)
    feature_count: Optional[int] = None
    geometry_type: Optional[str] = None
    primary_geometry_column: Optional[str] = None

    # STAC Linkage
    stac_item_id: Optional[str] = None
    stac_collection_id: Optional[str] = None
    stac_extensions: List[str] = []

    # Timestamps
    created: Optional[datetime] = None
    updated: Optional[datetime] = None

    # Scientific (optional)
    sci_doi: Optional[str] = None
    sci_citation: Optional[str] = None

    def to_ogc_properties(self) -> Dict[str, Any]:
        """Convert to OGC Features collection properties block."""
        props = {}

        if self.etl_job_id:
            props["etl:job_id"] = self.etl_job_id
        if self.source_file:
            props["source:file"] = self.source_file
        if self.source_format:
            props["source:format"] = self.source_format
        if self.source_crs:
            props["source:crs"] = self.source_crs
        if self.stac_item_id:
            props["stac:item_id"] = self.stac_item_id
        if self.stac_collection_id:
            props["stac:collection_id"] = self.stac_collection_id
        if self.created:
            props["created"] = self.created.isoformat()
        if self.updated:
            props["updated"] = self.updated.isoformat()
        if self.license:
            props["license"] = self.license
        if self.keywords:
            props["keywords"] = self.keywords
        if self.feature_count:
            props["feature_count"] = self.feature_count
        if self.providers:
            props["attribution"] = ", ".join(p.name for p in self.providers)

        return props

    def to_stac_collection(self, base_url: str) -> Dict[str, Any]:
        """Convert to STAC Collection JSON."""
        collection = {
            "type": "Collection",
            "stac_version": "1.0.0",
            "stac_extensions": self.stac_extensions,
            "id": self.id,
            "title": self.title or self.id.replace("_", " ").title(),
            "description": self.description or f"Vector dataset: {self.id}",
            "keywords": self.keywords,
            "license": self.license or "proprietary",
            "providers": [p.model_dump() for p in self.providers],
            "extent": self.extent.model_dump() if self.extent else {},
            "links": [
                {
                    "rel": "self",
                    "href": f"{base_url}/api/stac/collections/{self.id}",
                    "type": "application/json"
                },
                {
                    "rel": "items",
                    "href": f"{base_url}/api/stac/collections/{self.id}/items",
                    "type": "application/geo+json"
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/items",
                    "href": f"{base_url}/api/features/collections/{self.id}/items",
                    "type": "application/geo+json",
                    "title": "OGC Features API items"
                }
            ]
        }

        # Add table extension properties
        if self.feature_count or self.geometry_type:
            collection["summaries"] = {}
            if self.feature_count:
                collection["summaries"]["table:row_count"] = [self.feature_count]

        return collection
```

---

## Implementation TODO

### Phase 1: Schema Updates (Database)

- [ ] **1.1** Add new columns to `geo.table_metadata`:
  ```sql
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS providers JSONB;
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS stac_extensions JSONB;
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS column_definitions JSONB;
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS primary_geometry VARCHAR(100);
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS processing_software JSONB;
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS sci_doi VARCHAR(200);
  ALTER TABLE geo.table_metadata ADD COLUMN IF NOT EXISTS sci_citation TEXT;
  ```

- [ ] **1.2** Update `infrastructure/database_utils.py` schema deployment to include new columns

- [ ] **1.3** Migrate existing `attribution` string to `providers` JSONB array

### Phase 2: Model Layer

- [ ] **2.1** Create `core/models/unified_metadata.py` with `UnifiedMetadata` Pydantic model

- [ ] **2.2** Add conversion methods:
  - `to_ogc_properties()` - For OGC Features collection response
  - `to_stac_collection()` - For STAC collection response
  - `to_stac_item()` - For STAC item response

- [ ] **2.3** Update `ogc_features/models.py` to use `UnifiedMetadata`

### Phase 3: Repository Layer

- [ ] **3.1** Update `ogc_features/repository.py`:
  - `get_table_metadata()` to return `UnifiedMetadata` model
  - Add `update_table_metadata()` for metadata updates

- [ ] **3.2** Create metadata sync service:
  - `services/metadata_sync.py`
  - Sync `geo.table_metadata` → `pgstac` on metadata changes

### Phase 4: API Layer

- [ ] **4.1** Update `ogc_features/service.py`:
  - Use `UnifiedMetadata.to_ogc_properties()` for collection response
  - Ensure consistent structure with STAC

- [ ] **4.2** Update STAC catalog service to read from `geo.table_metadata`:
  - For vector collections, use `UnifiedMetadata.to_stac_collection()`
  - Keep pgstac as index but source metadata from geo.table_metadata

- [ ] **4.3** Add metadata update endpoint:
  ```
  PATCH /api/features/collections/{id}/metadata
  PATCH /api/stac/collections/{id}/metadata
  ```
  Both should update `geo.table_metadata` and trigger sync.

### Phase 5: ETL Integration

- [ ] **5.1** Update `process_vector` job Stage 1:
  - Write full `UnifiedMetadata` to `geo.table_metadata`
  - Include providers, extensions, column definitions

- [ ] **5.2** Update `process_vector` job Stage 3 (STAC cataloging):
  - Read from `geo.table_metadata` instead of building fresh
  - Use `UnifiedMetadata.to_stac_item()` / `to_stac_collection()`

- [ ] **5.3** Update `process_raster` jobs similarly

### Phase 6: Testing & Validation

- [ ] **6.1** Add unit tests for `UnifiedMetadata` model conversions

- [ ] **6.2** Add integration tests:
  - Ingest vector → verify OGC metadata
  - Ingest vector → verify STAC metadata matches OGC
  - Update metadata → verify both endpoints reflect change

- [ ] **6.3** Add STAC validator check to CI/CD

---

## Key Files Reference

### Current Implementation Files

| File | Purpose |
|------|---------|
| `ogc_features/service.py` | OGC Features business logic, builds collection response |
| `ogc_features/repository.py` | Database access, `get_table_metadata()` method |
| `ogc_features/models.py` | Pydantic models for OGC responses |
| `services/stac_vector_catalog.py` | STAC cataloging for vector data |
| `infrastructure/database_utils.py` | Schema deployment including geo.table_metadata |
| `jobs/process_vector.py` | Vector ETL job (writes to geo.table_metadata) |
| `core/models/promoted.py` | PromotedDataset model |
| `infrastructure/promoted_repository.py` | Promoted dataset CRUD |

### Database Tables

| Table | Schema | Purpose |
|-------|--------|---------|
| `geo.table_metadata` | geo | Vector table metadata (source of truth) |
| `pgstac.collections` | pgstac | STAC collections (index) |
| `pgstac.items` | pgstac | STAC items (index) |
| `app.promoted_datasets` | app | Featured datasets overlay |

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/features/collections` | List OGC collections |
| `GET /api/features/collections/{id}` | Get OGC collection with metadata |
| `GET /api/features/collections/{id}/items` | Query features |
| `GET /api/stac/collections` | List STAC collections |
| `GET /api/stac/collections/{id}` | Get STAC collection |
| `GET /api/stac/collections/{id}/items` | Get STAC items |

---

## Phase 7: Metadata Import Templates (Future Enhancement)

### Concept

Allow users to define **metadata templates** that can be applied during data import. This enables:
- Standardized metadata for datasets from known providers
- Pre-filled fields (license, attribution, keywords) for common data sources
- Consistent metadata quality across the platform

### Proposed Template Structure

```python
# core/models/metadata_template.py

class MetadataTemplate(BaseModel):
    """
    Reusable metadata template for data imports.

    Templates can be:
    - Provider-specific (e.g., "FATHOM flood data")
    - Theme-specific (e.g., "Administrative boundaries")
    - Organization-specific (e.g., "WorldPop datasets")
    """
    template_id: str = Field(..., description="Unique template identifier")
    name: str = Field(..., description="Human-readable template name")
    description: Optional[str] = None

    # Pre-filled metadata fields
    default_license: Optional[str] = None  # SPDX identifier
    default_providers: List[Provider] = []
    default_keywords: List[str] = []
    default_stac_extensions: List[str] = []

    # Validation rules
    required_fields: List[str] = []  # Fields that must be provided
    keyword_prefix: Optional[str] = None  # Auto-prepend to keywords

    # Classification
    default_classification: str = "public"

    # Template metadata
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    is_system_template: bool = False
```

### Example Templates

```json
{
    "template_id": "fathom-flood",
    "name": "FATHOM Flood Hazard Data",
    "description": "Template for FATHOM flood depth COGs",
    "default_license": "proprietary",
    "default_providers": [
        {
            "name": "Fathom",
            "roles": ["producer", "licensor"],
            "url": "https://www.fathom.global/"
        }
    ],
    "default_keywords": ["flood", "hazard", "fathom"],
    "default_stac_extensions": [
        "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
    ],
    "required_fields": ["fathom:flood_type", "fathom:year"],
    "keyword_prefix": "fathom:"
}
```

```json
{
    "template_id": "admin-boundaries",
    "name": "Administrative Boundaries",
    "description": "Template for admin boundary vector datasets",
    "default_license": "ODbL-1.0",
    "default_providers": [
        {
            "name": "OpenStreetMap Contributors",
            "roles": ["producer"],
            "url": "https://www.openstreetmap.org/"
        }
    ],
    "default_keywords": ["boundaries", "admin", "political"],
    "default_stac_extensions": [
        "https://stac-extensions.github.io/table/v1.2.0/schema.json"
    ],
    "required_fields": ["iso3", "admin_level"]
}
```

### Implementation TODO (Phase 7)

- [ ] **7.1** Create `app.metadata_templates` table:
  ```sql
  CREATE TABLE app.metadata_templates (
      template_id         VARCHAR(64) PRIMARY KEY,
      name                VARCHAR(200) NOT NULL,
      description         TEXT,
      default_license     VARCHAR(100),
      default_providers   JSONB,
      default_keywords    JSONB,
      default_stac_extensions JSONB,
      required_fields     JSONB,
      keyword_prefix      VARCHAR(50),
      default_classification VARCHAR(20) DEFAULT 'public',
      created_by          VARCHAR(100),
      created_at          TIMESTAMPTZ DEFAULT NOW(),
      is_system_template  BOOLEAN DEFAULT FALSE
  );
  ```

- [ ] **7.2** Create `core/models/metadata_template.py` Pydantic model

- [ ] **7.3** Create `infrastructure/template_repository.py` CRUD operations

- [ ] **7.4** Add template API endpoints:
  ```
  GET    /api/metadata/templates           - List all templates
  GET    /api/metadata/templates/{id}      - Get template
  POST   /api/metadata/templates           - Create template
  PATCH  /api/metadata/templates/{id}      - Update template
  DELETE /api/metadata/templates/{id}      - Delete template
  ```

- [ ] **7.5** Update job submission to accept `template_id`:
  ```json
  POST /api/jobs/submit/process_vector
  {
      "source_url": "az://bronze/admin_chile.gpkg",
      "template_id": "admin-boundaries",
      "metadata_overrides": {
          "title": "Chile Administrative Boundaries",
          "keywords": ["chile"]
      }
  }
  ```

- [ ] **7.6** Update ETL jobs to apply template:
  - Merge template defaults with user-provided metadata
  - User overrides take precedence
  - Validate required fields from template

- [ ] **7.7** Create system templates for common data types:
  - `fathom-flood` - FATHOM flood hazard data
  - `admin-boundaries` - Administrative boundaries
  - `worldpop` - WorldPop population data
  - `osm-features` - OpenStreetMap extracts

### Template Application Logic

```python
def apply_template(template: MetadataTemplate, user_metadata: dict) -> UnifiedMetadata:
    """
    Apply template defaults and merge with user-provided metadata.

    Priority: user_metadata > template defaults > system defaults
    """
    # Start with template defaults
    merged = {
        "license": template.default_license,
        "providers": template.default_providers,
        "keywords": list(template.default_keywords),
        "stac_extensions": list(template.default_stac_extensions),
    }

    # Apply keyword prefix if specified
    if template.keyword_prefix and user_metadata.get("keywords"):
        user_keywords = user_metadata["keywords"]
        user_metadata["keywords"] = [
            f"{template.keyword_prefix}{kw}" if not kw.startswith(template.keyword_prefix) else kw
            for kw in user_keywords
        ]

    # Merge user overrides (user wins)
    for key, value in user_metadata.items():
        if value is not None:
            if key == "keywords":
                # Combine keywords, template first
                merged["keywords"] = list(set(merged.get("keywords", []) + value))
            elif key == "providers":
                # User providers override
                merged["providers"] = value
            else:
                merged[key] = value

    # Validate required fields
    missing = [f for f in template.required_fields if f not in merged or merged[f] is None]
    if missing:
        raise ValueError(f"Missing required fields from template '{template.template_id}': {missing}")

    return UnifiedMetadata(**merged)
```

---

## Design Principles

1. **Single Source of Truth**: `geo.table_metadata` is canonical for vector metadata
2. **No Duplication**: STAC catalog indexes data but doesn't duplicate metadata
3. **Consistent Structure**: Same metadata accessible from OGC or STAC endpoints
4. **STAC Alignment**: Use STAC extensions and field names where possible
5. **Backward Compatible**: Existing API responses should not break
6. **Template-Driven**: Common metadata patterns can be captured as reusable templates

---

## References

- [STAC Specification](https://stacspec.org/)
- [STAC Table Extension](https://github.com/stac-extensions/table)
- [STAC Processing Extension](https://github.com/stac-extensions/processing)
- [OGC API - Features](https://ogcapi.ogc.org/features/)
- [SPDX License List](https://spdx.org/licenses/)
