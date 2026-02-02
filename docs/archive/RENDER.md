# Raster Render Configs - Implementation Plan

**Created**: 22 JAN 2026
**Epic**: E2 Raster Data as API
**Feature**: F2.11 Raster Render Configuration System
**Status**: PLANNING

---

## Overview

Server-side render configurations for raster visualization via TiTiler, following the same "PostgreSQL as Source of Truth" pattern established for OGC Styles (vector symbology).

### Problem Statement

Raster "styling" is fundamentally different from vector styling:
- **Vector**: Client-side styling instructions (CartoSym-JSON, Mapbox GL, SLD)
- **Raster**: Server-side rendering parameters (colormap, rescale, band math)

TiTiler parameters control how tiles are rendered, not how clients display them. These configurations need:
1. A persistent storage location (source of truth)
2. CRUD API for management
3. Integration with STAC via the Renders Extension
4. Direct use by TiTiler for tile generation

---

## Architecture

### Current State (Vector Styles)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        VECTOR (OGC Styles)                               │
├─────────────────────────────────────────────────────────────────────────┤
│  PostgreSQL (Source of Truth)                                            │
│  └── geo.feature_collection_styles                                       │
│      • collection_id, style_id, style_spec (CartoSym-JSON)              │
│                         │                                                │
│                         ▼                                                │
│  OGC API Endpoints                     STAC                             │
│  GET /collections/{id}/styles          Links to style endpoints         │
│  GET /collections/{id}/styles/{sid}                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Target State (Raster Renders)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RASTER (Render Configs)                           │
├─────────────────────────────────────────────────────────────────────────┤
│  PostgreSQL (Source of Truth)                                            │
│  └── app.raster_render_configs                                          │
│      • cog_id (FK → cog_metadata)                                       │
│      • render_id (e.g., "default", "flood-depth", "ndvi")               │
│      • render_spec (TiTiler parameters as JSONB)                        │
│                         │                                                │
│         ┌───────────────┼───────────────┐                               │
│         ▼               ▼               ▼                               │
│  Render API       STAC Renders      TiTiler                            │
│  (CRUD)           Extension         Query Params                        │
│                                                                          │
│  GET  /raster/{cog_id}/renders                                          │
│  GET  /raster/{cog_id}/renders/{rid}                                    │
│  POST /raster/{cog_id}/renders                                          │
│         │               │               │                               │
│         └───────────────┴───────────────┘                               │
│                         ▼                                                │
│              STAC Item (Generated)                                       │
│              └── assets.data.renders: {...}                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Single Source of Truth Principle

| Data Type | Master Location | STAC Role | Client API |
|-----------|-----------------|-----------|------------|
| **Vector Styles** | `geo.feature_collection_styles` | Links only | OGC Styles API |
| **Raster Renders** | `app.raster_render_configs` | Embedded (renders ext) | Render Config API |

**Why `app.` schema for renders (not `geo.`)?**
- Render configs are internal/operational, not replicated to external databases
- Tied to `app.cog_metadata` via FK
- Similar to how `app.vector_etl_tracking` is internal while `geo.table_catalog` is replicable

---

## Data Model

### Table: `app.raster_render_configs`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PK | Auto-increment ID |
| `cog_id` | VARCHAR(255) | FK → cog_metadata, NOT NULL | COG identifier |
| `render_id` | VARCHAR(100) | NOT NULL | URL-safe render name |
| `title` | VARCHAR(500) | | Human-readable title |
| `description` | TEXT | | Render description |
| `render_spec` | JSONB | NOT NULL | TiTiler parameters |
| `is_default` | BOOLEAN | DEFAULT false | Default render for COG |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | Last update timestamp |

**Constraints:**
- `UNIQUE (cog_id, render_id)` - One render_id per COG
- `UNIQUE (cog_id) WHERE is_default = true` - Only one default per COG (partial unique index)

### Render Spec Schema (JSONB)

```json
{
  "colormap_name": "viridis",
  "rescale": [[0, 100]],
  "bidx": [1],
  "expression": "(b1-b2)/(b1+b2)",
  "color_formula": "gamma r 1.5",
  "resampling": "nearest",
  "return_mask": true,
  "nodata": -9999
}
```

**TiTiler Parameter Mapping:**

| render_spec field | TiTiler Query Param | Description |
|-------------------|---------------------|-------------|
| `colormap_name` | `colormap_name` | Named colormap (viridis, plasma, etc.) |
| `colormap` | `colormap` | Custom colormap dict |
| `rescale` | `rescale` | Min/max rescaling per band |
| `bidx` | `bidx` | Band indexes to use |
| `expression` | `expression` | Band math expression |
| `color_formula` | `color_formula` | rio-color formula |
| `resampling` | `resampling` | Resampling method |
| `return_mask` | `return_mask` | Include alpha mask |
| `nodata` | `nodata` | NoData value override |

---

## STAC Renders Extension Integration

When generating STAC items, render configs from PostgreSQL are embedded in the asset:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/render/v1.0.0/schema.json"
  ],
  "id": "fathom-fluvial-defended-2020",
  "assets": {
    "data": {
      "href": "https://storage.blob.core.windows.net/silver-cogs/fathom/merged.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "renders": {
        "default": {
          "title": "Flood Depth (Default)",
          "colormap_name": "blues",
          "rescale": [[0, 5]]
        },
        "binary": {
          "title": "Flood Presence",
          "colormap_name": "ylorrd",
          "expression": "where(b1>0,1,0)",
          "rescale": [[0, 1]]
        },
        "depth-classes": {
          "title": "Depth Classification",
          "colormap": {
            "0": "#ffffff",
            "1": "#ffffcc",
            "2": "#a1dab4",
            "3": "#41b6c4",
            "4": "#225ea8"
          },
          "expression": "where(b1>3,4,where(b1>2,3,where(b1>1,2,where(b1>0,1,0))))"
        }
      }
    }
  }
}
```

**TiTiler Usage:**
```
GET /cog/tiles/{z}/{x}/{y}?url={cog_url}&render=default
GET /cog/tiles/{z}/{x}/{y}?url={cog_url}&render=binary
```

---

## API Endpoints

### Render Config CRUD API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/raster/{cog_id}/renders` | List all renders for a COG |
| GET | `/api/raster/{cog_id}/renders/{render_id}` | Get specific render config |
| POST | `/api/raster/{cog_id}/renders` | Create new render config |
| PUT | `/api/raster/{cog_id}/renders/{render_id}` | Update render config |
| DELETE | `/api/raster/{cog_id}/renders/{render_id}` | Delete render config |
| POST | `/api/raster/{cog_id}/renders/{render_id}/default` | Set as default |

### Response Format

**List Renders:**
```json
{
  "cog_id": "fathom-fluvial-defended-2020",
  "renders": [
    {
      "render_id": "default",
      "title": "Flood Depth",
      "is_default": true,
      "render_spec": {...}
    }
  ],
  "links": [
    {"rel": "self", "href": "..."},
    {"rel": "cog", "href": "/api/stac/collections/.../items/..."}
  ]
}
```

---

## Implementation Plan

### Phase 1: Data Model & DDL (IaC Pattern)

| Story | Description | Status |
|-------|-------------|--------|
| S2.11.1 | Create `RasterRenderConfig` Pydantic model in `core/models/raster_render_config.py` | |
| S2.11.2 | Add `__sql_*` ClassVars for DDL generation | |
| S2.11.3 | Export from `core/models/__init__.py` | |
| S2.11.4 | Add to `PydanticToSQL.generate_app_schema_ddl()` or new method | |
| S2.11.5 | Deploy schema, verify table created | |

### Phase 2: Repository & Service

| Story | Description | Status |
|-------|-------------|--------|
| S2.11.6 | Create `infrastructure/raster_render_repository.py` with CRUD | |
| S2.11.7 | Create `services/raster_render_service.py` with business logic | |
| S2.11.8 | Add default render generation (like OGC Styles `create_default_style_for_collection`) | |

### Phase 3: HTTP API

| Story | Description | Status |
|-------|-------------|--------|
| S2.11.9 | Create `triggers/trigger_raster_renders.py` with HTTP handlers | |
| S2.11.10 | Register routes in `function_app.py` | |
| S2.11.11 | Add to OpenAPI spec | |

### Phase 4: STAC Integration

| Story | Description | Status |
|-------|-------------|--------|
| S2.11.12 | Modify `RasterMetadata.to_stac_item()` to accept render configs | |
| S2.11.13 | Update `stac_catalog.py:extract_stac_metadata()` to fetch renders | |
| S2.11.14 | Add renders extension to STAC extensions list | |
| S2.11.15 | Test: STAC item includes renders from PostgreSQL | |

### Phase 5: ETL Integration

| Story | Description | Status |
|-------|-------------|--------|
| S2.11.16 | Auto-create default render on raster ETL completion | |
| S2.11.17 | Support render_spec in Platform API submit request | |
| S2.11.18 | Cascade delete renders when COG unpublished | |

### Phase 6: TiTiler Integration (Future - TiTiler App)

| Story | Description | Status |
|-------|-------------|--------|
| S2.11.19 | TiTiler endpoint to resolve render_id → params | |
| S2.11.20 | TiTiler reads renders from STAC item | |
| S2.11.21 | Document TiTiler integration in consumer docs | |

---

## Pydantic Model (Draft)

```python
# core/models/raster_render_config.py

from datetime import datetime
from typing import Dict, Any, Optional, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict


class RasterRenderConfig(BaseModel):
    """
    Render configuration for raster visualization via TiTiler.

    Maps to: app.raster_render_configs

    Following the same IaC pattern as:
    - GeoTableCatalog (geo.table_catalog)
    - FeatureCollectionStyles (geo.feature_collection_styles)
    - VectorEtlTracking (app.vector_etl_tracking)

    Created: 22 JAN 2026
    Epic: E2 Raster Data as API → F2.11 Raster Render Configuration
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # DDL generation hints
    __sql_table_name: ClassVar[str] = "raster_render_configs"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["id"]
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["cog_id", "render_id"], "name": "uq_render_cog_render"}
    ]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "cog_id": "app.cog_metadata(cog_id)"
    }
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["cog_id"], "name": "idx_render_cog"},
        {"columns": ["cog_id"], "name": "idx_render_default",
         "partial_where": "is_default = true", "unique": True},
    ]

    # ==========================================================================
    # IDENTITY
    # ==========================================================================
    id: Optional[int] = Field(
        default=None,
        description="Auto-generated primary key (SERIAL)"
    )

    cog_id: str = Field(
        ...,
        max_length=255,
        description="COG identifier (FK to cog_metadata)"
    )

    render_id: str = Field(
        ...,
        max_length=100,
        description="URL-safe render identifier (e.g., 'default', 'flood-depth')"
    )

    # ==========================================================================
    # METADATA
    # ==========================================================================
    title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Human-readable render title"
    )

    description: Optional[str] = Field(
        default=None,
        description="Render description"
    )

    # ==========================================================================
    # RENDER SPECIFICATION (TiTiler Parameters)
    # ==========================================================================
    render_spec: Dict[str, Any] = Field(
        ...,
        description="TiTiler render parameters (colormap, rescale, bidx, etc.)"
    )

    # ==========================================================================
    # FLAGS
    # ==========================================================================
    is_default: bool = Field(
        default=False,
        description="Whether this is the default render for the COG"
    )

    # ==========================================================================
    # TIMESTAMPS
    # ==========================================================================
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the render config was created"
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        description="When the render config was last updated"
    )

    # ==========================================================================
    # FACTORY METHODS
    # ==========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "RasterRenderConfig":
        """Create from database row."""
        return cls(
            id=row.get('id'),
            cog_id=row.get('cog_id'),
            render_id=row.get('render_id'),
            title=row.get('title'),
            description=row.get('description'),
            render_spec=row.get('render_spec') or {},
            is_default=row.get('is_default', False),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

    def to_stac_render(self) -> Dict[str, Any]:
        """
        Convert to STAC Renders Extension format.

        Returns:
            Dict suitable for embedding in asset.renders
        """
        render = {}
        if self.title:
            render["title"] = self.title

        # Map render_spec fields to STAC render format
        spec = self.render_spec or {}
        for key in ["colormap_name", "colormap", "rescale", "bidx",
                    "expression", "color_formula", "resampling",
                    "return_mask", "nodata"]:
            if key in spec and spec[key] is not None:
                render[key] = spec[key]

        return render

    def to_titiler_params(self) -> Dict[str, Any]:
        """
        Convert to TiTiler query parameters.

        Returns:
            Dict of query params for TiTiler tile requests
        """
        params = {}
        spec = self.render_spec or {}

        if "colormap_name" in spec:
            params["colormap_name"] = spec["colormap_name"]
        if "colormap" in spec:
            params["colormap"] = spec["colormap"]
        if "rescale" in spec:
            # TiTiler expects comma-separated: rescale=0,100
            for i, r in enumerate(spec["rescale"]):
                params[f"rescale"] = ",".join(map(str, r))
        if "bidx" in spec:
            params["bidx"] = spec["bidx"]
        if "expression" in spec:
            params["expression"] = spec["expression"]
        if "color_formula" in spec:
            params["color_formula"] = spec["color_formula"]
        if "resampling" in spec:
            params["resampling"] = spec["resampling"]
        if "nodata" in spec:
            params["nodata"] = spec["nodata"]

        return params
```

---

## Default Render Generation

When a raster ETL job completes, auto-generate a default render based on data characteristics:

```python
def create_default_render_for_cog(
    cog_id: str,
    dtype: str,
    band_count: int,
    nodata: Optional[float] = None,
    data_min: Optional[float] = None,
    data_max: Optional[float] = None
) -> RasterRenderConfig:
    """
    Generate sensible default render config based on raster properties.
    """
    render_spec = {}

    # Set rescale based on dtype or actual data range
    if data_min is not None and data_max is not None:
        render_spec["rescale"] = [[data_min, data_max]]
    elif dtype == "uint8":
        render_spec["rescale"] = [[0, 255]]
    elif dtype == "uint16":
        render_spec["rescale"] = [[0, 65535]]
    elif dtype in ("float32", "float64"):
        render_spec["rescale"] = [[0, 1]]  # Assume normalized

    # Default colormap
    if band_count == 1:
        render_spec["colormap_name"] = "viridis"
    else:
        # RGB - no colormap needed
        render_spec["bidx"] = [1, 2, 3] if band_count >= 3 else [1]

    if nodata is not None:
        render_spec["nodata"] = nodata

    return RasterRenderConfig(
        cog_id=cog_id,
        render_id="default",
        title="Default Visualization",
        render_spec=render_spec,
        is_default=True
    )
```

---

## Testing Checklist

- [ ] Table `app.raster_render_configs` created via IaC DDL
- [ ] CRUD operations work via repository
- [ ] HTTP API endpoints return correct responses
- [ ] STAC item includes `renders` in asset when configs exist
- [ ] STAC item omits `renders` when no configs exist
- [ ] Default render auto-created on raster ETL completion
- [ ] Cascade delete works when COG unpublished
- [ ] Partial unique index enforces one default per COG

---

## References

- [STAC Renders Extension](https://github.com/stac-extensions/render)
- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [OGC Styles Implementation](ogc_styles/) - Pattern reference
- [Unified Metadata Architecture](docs_claude/ARCHITECTURE_REFERENCE.md)

---

## Appendix: Comparison with Vector Styles

| Aspect | Vector (OGC Styles) | Raster (Render Configs) |
|--------|---------------------|-------------------------|
| **Table** | `geo.feature_collection_styles` | `app.raster_render_configs` |
| **Schema** | `geo` (replicable) | `app` (internal) |
| **FK Reference** | `collection_id` (logical) | `cog_id` (FK to cog_metadata) |
| **Spec Format** | CartoSym-JSON | TiTiler params (JSONB) |
| **STAC Integration** | Links to OGC endpoints | Embedded in asset.renders |
| **Applied Where** | Client-side | Server-side (TiTiler) |
| **OGC Standard** | OGC API - Styles | STAC Renders Extension |
| **Output** | Styling instructions | Pre-rendered tiles |
