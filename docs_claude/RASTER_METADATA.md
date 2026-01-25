# RasterMetadata Architecture (F7.9)

**Last Updated**: 24 JAN 2026
**Epic**: E7 Pipeline Infrastructure → E2 Raster Data as API
**Goal**: RasterMetadata model providing single source of truth for STAC-based raster catalogs
**Dependency**: F7.8 (BaseMetadata, VectorMetadata pattern established)
**Status**: Phase 1 Complete, Phase 2 IN PROGRESS
**Priority**: CRITICAL - Raster is primary STAC use case

---

## Why Critical

1. STAC is primarily a raster catalog standard
2. Current raster STAC items built ad-hoc without metadata registry
3. FATHOM, DEM, satellite imagery all need consistent metadata
4. TiTiler integration requires predictable metadata structure
5. DDH linkage for rasters depends on this

### Current Gap

- VectorMetadata has `geo.table_catalog` as source of truth
- Raster has NO equivalent — STAC items built directly from COG headers
- No way to query "all rasters for DDH dataset X"
- No consistent visualization defaults stored

---

## Raster Job Architecture

```
process_raster_v2 (Function App, <1GB)     process_raster_docker (Docker, large files)
        │                                           │
        │ Stage 3                                   │ Phase 3
        ▼                                           ▼
    ┌─────────────────────────────────────────────────┐
    │  services/stac_catalog.py:extract_stac_metadata │  ← SINGLE WIRING POINT
    │      Step 5: Insert STAC item to pgSTAC         │
    │      Step 5.5: Populate app.cog_metadata (NEW)  │
    └─────────────────────────────────────────────────┘
```

---

## Implementation Status

### Phase 1: Models & Repository - COMPLETE (09 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.1 | Create `RasterMetadata` class in `core/models/unified_metadata.py` | Done |
| S7.9.2 | Create `app.cog_metadata` table DDL with typed columns | Done |
| S7.9.3 | Create `RasterMetadataRepository` with CRUD operations | Done |
| S7.9.4 | Implement `RasterMetadata.from_db_row()` factory method | Done |
| S7.9.5 | Implement `RasterMetadata.to_stac_item()` conversion | Done |
| S7.9.6 | Implement `RasterMetadata.to_stac_collection()` conversion | Done |

### Phase 2: Integration - IN PROGRESS (12 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.8 | Wire `extract_stac_metadata` to populate `app.cog_metadata` | Done |
| S7.9.8a | Extract raster properties from STAC item for cog_metadata | Done |
| S7.9.8b | Call `RasterMetadataRepository.upsert()` after pgSTAC insert | Done |
| S7.9.8c | Handle graceful degradation if cog_metadata insert fails | Done |
| S7.11.5 | Enable raster rebuild in `rebuild_stac_handlers.py` | Done |
| S7.11.5a | Query `app.cog_metadata` for raster validation | Done |
| S7.11.5b | Use `RasterMetadata.to_stac_item()` for rebuild | Done |
| S7.9.TEST | Test: `process_raster_v2` populates cog_metadata + STAC | NEXT |

---

## RasterMetadata Class

```python
class RasterMetadata(BaseMetadata):
    # COG-specific fields
    cog_url: str                    # /vsiaz/ path or HTTPS URL
    container: str                  # Azure container name
    blob_path: str                  # Path within container

    # Raster properties
    width: int                      # Pixel width
    height: int                     # Pixel height
    band_count: int                 # Number of bands
    dtype: str                      # numpy dtype (uint8, int16, float32, etc.)
    nodata: Optional[float]         # NoData value
    crs: str                        # CRS as EPSG code or WKT
    transform: List[float]          # Affine transform (6 values)
    resolution: Tuple[float, float] # (x_res, y_res) in CRS units

    # Band metadata
    band_names: List[str]           # Band descriptions
    band_units: Optional[List[str]] # Units per band

    # Processing metadata
    is_cog: bool                    # Cloud-optimized GeoTIFF?
    overview_levels: List[int]      # COG overview levels
    compression: Optional[str]      # DEFLATE, LZW, etc.
    blocksize: Tuple[int, int]      # Internal tile size

    # Visualization defaults
    colormap: Optional[str]         # Default colormap name
    rescale_range: Optional[Tuple[float, float]]  # Default min/max

    # STAC extensions
    eo_bands: Optional[List[dict]]  # EO extension band metadata
    raster_bands: Optional[List[dict]]  # Raster extension metadata
```

---

## Database Schema

### Table: `app.cog_metadata`

```sql
CREATE TABLE app.cog_metadata (
    -- Identity
    cog_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,

    -- Location
    container TEXT NOT NULL,
    blob_path TEXT NOT NULL,
    cog_url TEXT NOT NULL,

    -- Spatial
    bbox DOUBLE PRECISION[4],
    geometry GEOMETRY(Polygon, 4326),
    crs TEXT NOT NULL DEFAULT 'EPSG:4326',

    -- Raster properties
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    band_count INTEGER NOT NULL,
    dtype TEXT NOT NULL,
    nodata DOUBLE PRECISION,
    resolution DOUBLE PRECISION[2],

    -- COG properties
    is_cog BOOLEAN DEFAULT true,
    compression TEXT,
    blocksize INTEGER[2],
    overview_levels INTEGER[],

    -- Metadata
    title TEXT,
    description TEXT,
    datetime TIMESTAMPTZ,
    start_datetime TIMESTAMPTZ,
    end_datetime TIMESTAMPTZ,

    -- Band metadata (JSONB for flexibility)
    band_names TEXT[],
    eo_bands JSONB,
    raster_bands JSONB,

    -- Visualization
    colormap TEXT,
    rescale_min DOUBLE PRECISION,
    rescale_max DOUBLE PRECISION,

    -- Extensibility
    providers JSONB,
    custom_properties JSONB,

    -- STAC linkage
    stac_item_id TEXT,
    stac_collection_id TEXT,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(container, blob_path)
);

-- Indexes
CREATE INDEX idx_cog_metadata_collection ON app.cog_metadata(collection_id);
CREATE INDEX idx_cog_metadata_bbox ON app.cog_metadata USING GIST(geometry);
CREATE INDEX idx_cog_metadata_datetime ON app.cog_metadata(datetime);
CREATE INDEX idx_cog_metadata_stac_item ON app.cog_metadata(stac_item_id);
CREATE INDEX idx_cog_metadata_container ON app.cog_metadata(container, blob_path);
```

---

## Key Files

| File | Purpose |
|------|---------|
| `core/models/unified_metadata.py` | RasterMetadata domain model |
| `core/models/raster_metadata.py` | CogMetadataRecord for DDL |
| `core/schema/sql_generator.py` | Table/index generation |
| `infrastructure/raster_metadata_repository.py` | CRUD operations |
| `services/stac_catalog.py` | Integration point (extract_stac_metadata) |
| `services/rebuild_stac_handlers.py` | Raster rebuild support |

---

## STAC Self-Healing Integration (F7.11)

RasterMetadata enables STAC self-healing for rasters:

1. **Detection**: F7.10 timer checks for orphaned STAC items or broken backlinks
2. **Validation**: `stac_rebuild_validate` queries `app.cog_metadata` to verify raster exists
3. **Rebuild**: `stac_rebuild_item` uses `RasterMetadata.to_stac_item()` to recreate STAC

### Stories

| Story | Description | Status |
|-------|-------------|--------|
| S7.11.5 | Add raster support to rebuild_stac_handlers | Done |
| S7.11.5a | Query `app.cog_metadata` for raster validation | Done |
| S7.11.5b | Use `RasterMetadata.to_stac_item()` for rebuild | Done |
| S7.11.6 | Timer auto-submit (F7.10 detects → auto-submit rebuild job) | Pending |
