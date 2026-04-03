# Feature F2: Raster Data & Serving — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Raster Data & Serving converts GeoTIFF files into Cloud-Optimized GeoTIFFs (COGs) with STAC metadata, served through TiTiler for dynamic tile rendering and map visualization. The pipeline handles single files, large rasters exceeding 2GB (automatically tiled via fan-out/fan-in parallelization), and multi-file collections with homogeneity checking.

The raster DAG workflow (`process_raster.yaml`) is the most complex in the system at 10 nodes with conditional size-based routing between single-COG and tiled processing paths. The collection workflow (`process_raster_collection.yaml`) orchestrates 5 fan-out/fan-in cycles processing N files in parallel. Both workflows include approval gates and composable STAC materialization handlers shared with the Zarr pipeline.

The platform also hosts FATHOM global flood risk data through a specialized ETL pipeline with band stacking and spatial merge capabilities.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S2.1 | Single raster pipeline | Done | v0.10.5 | GeoTIFF to COG with validation, reprojection, compression |
| S2.2 | Large raster tiling | Done | v0.10.8 | >2GB conditional fan-out: tiling scheme, parallel tile processing, fan-in |
| S2.3 | Raster collection pipeline | Partial | v0.10.9 | `process_raster_collection.yaml` designed (5 fan-out/fan-in phases), not E2E tested |
| S2.4 | TiTiler integration | Done | v0.8.x | Dynamic tile rendering from COGs via pgSTAC |
| S2.5 | STAC integration | Done | v0.10.5 | Composable handlers: stac_materialize_item + stac_materialize_collection |
| S2.6 | COG compression tiers | Done | v0.8.x | Analysis (LZW), visualization (DEFLATE+overviews), archive (ZSTD) |
| S2.7 | Raster unpublish pipeline | Done | v0.10.9 | `unpublish_raster.yaml`: inventory, fan-out blob deletion, STAC cleanup |
| S2.8 | Raster DAG workflow | Done | v0.10.8 | `process_raster.yaml`: 10 nodes, conditional routing, approval gate |
| S2.9 | pgSTAC search registration | Done | v0.10.8 | Mosaic endpoints for tiled collections |
| S2.10 | Raster map viewer | Done | v0.8.x | Collection-aware Leaflet viewer |
| S2.11 | Raster data extract API | Done | v0.8.x | Point query, clip, preview endpoints |
| S2.12 | Raster classification | Planned | — | Automated classification: band count + dtype + value range decision tree |
| S2.13 | FATHOM ETL Phase 1 | Done | v0.9.x | Band stacking for flood return period data |
| S2.14 | FATHOM ETL Phase 2 | Partial | v0.9.x | Spatial merge: 46/47 tiles complete, 1 failed task pending retry |

---

## Story Detail

### S2.1: Single Raster Pipeline
**Status**: Done (v0.10.5, 19 MAR 2026)

Twelve atomic handlers compose the raster processing capabilities:

| Handler | Task Type | Purpose |
|---------|-----------|---------|
| `raster_download_source` | `raster_download_source` | Stream blob from bronze to ETL mount with namespace isolation |
| `raster_validate_atomic` | `raster_validate_atomic` | Header + data validation, CRS check, reprojection decision |
| `raster_create_cog_atomic` | `raster_create_cog_atomic` | Transform raster to COG, extract STAC metadata |
| `raster_upload_cog` | `raster_upload_cog` | Upload COG to silver, verify blob, return coordinates |
| `raster_persist_app_tables` | `raster_persist_app_tables` | Upsert cog_metadata + render_config, cache stac_item_json |
| `raster_finalize` | `raster_finalize` | Clean up ETL mount directory |

**Key files**: `services/raster/handler_*.py` (12 files), `workflows/process_raster.yaml`

### S2.2: Large Raster Tiling
**Status**: Done (v0.10.8, 22 MAR 2026)

Rasters exceeding 2GB are automatically routed through a tiled processing path. The conditional node in `process_raster.yaml` evaluates `file_size_bytes > 2000000000` and routes to: (1) `generate_tiling_scheme` which computes a tile grid, (2) fan-out of `process_single_tile` handlers (tested with 24 parallel tiles on 8.8GB data), (3) fan-in aggregation of tile results, (4) `persist_tiled` writes N cog_metadata rows.

**Key files**: `services/raster/handler_generate_tiling_scheme.py`, `services/raster/handler_process_single_tile.py`, `services/raster/handler_persist_tiled.py`

### S2.3: Raster Collection Pipeline
**Status**: Partial (v0.10.9 — workflow designed, not E2E tested)

`process_raster_collection.yaml` orchestrates 5 fan-out/fan-in cycles: (1) download N files, (2) validate N files, (3) check homogeneity across all validations, (4) create N COGs, (5) upload N COGs. Post-upload: persist collection metadata, approval gate, materialize N STAC items, materialize collection. Three new handlers: `raster_collection_entrypoint`, `raster_check_homogeneity`, `raster_persist_collection`.

**Key files**: `workflows/process_raster_collection.yaml`, `services/raster/handler_check_homogeneity.py`, `services/raster/handler_persist_collection.py`, `services/raster/handler_collection_entrypoint.py`

### S2.4: TiTiler Integration
**Status**: Done (v0.8.x)

Dynamic tile serving via TiTiler (titiler-pgstac 2.1.0). COGs registered in pgSTAC are automatically discoverable. TiTiler renders tiles on-the-fly with rescale, colormap, and band math parameters.

**Key files**: `services/stac_metadata_helper.py` (visualization metadata), TiTiler is an external service at `rmhtitiler`

### S2.5: STAC Integration
**Status**: Done (v0.10.5)

Two composable STAC handlers shared across raster and Zarr pipelines:

| Handler | Purpose |
|---------|---------|
| `stac_materialize_item` | Read stac_item_json from cog_metadata, sanitize properties, inject TiTiler URLs, upsert to pgSTAC |
| `stac_materialize_collection` | Recalculate collection spatial/temporal extent from pgSTAC items |

These handlers are generic — they operate on cached `stac_item_json` regardless of data type.

**Key files**: `services/stac/handler_materialize_item.py`, `services/stac/handler_materialize_collection.py`

### S2.6: COG Compression Tiers
**Status**: Done (v0.8.x)

Three compression profiles optimized for different access patterns:
- **Analysis**: LZW compression, no overviews (smallest decode overhead)
- **Visualization**: DEFLATE compression, internal overviews (fast tile serving)
- **Archive**: ZSTD compression (maximum compression ratio)

**Key files**: `services/raster/handler_create_cog.py`

### S2.7: Raster Unpublish Pipeline
**Status**: Done (v0.10.9)

`unpublish_raster.yaml` (3 nodes): inventory STAC item to extract asset blob paths, fan-out deletion of blobs from silver storage, STAC item deletion with audit trail. Idempotent — re-running on already-deleted assets is a no-op.

**Key files**: `workflows/unpublish_raster.yaml`, `services/unpublish_handlers.py`

### S2.8: Raster DAG Workflow
**Status**: Done (v0.10.8, 22 MAR 2026)

`process_raster.yaml`: 10 nodes with conditional size-based routing. PATH A (standard): download, validate, create COG, upload, persist, approval gate, materialize item, materialize collection. PATH B (large): same but with tiling scheme generation, fan-out tile processing, fan-in aggregation before persist. 16 DAG engine bugs fixed during E2E validation.

**Key files**: `workflows/process_raster.yaml`

### S2.9: pgSTAC Search Registration
**Status**: Done (v0.10.8)

Tiled raster collections register a pgSTAC search hash enabling mosaic tile endpoints. TiTiler uses the search hash to serve composite tiles across all items in a collection.

**Key files**: `services/pgstac_search_registration.py`

### S2.10: Raster Map Viewer
**Status**: Done (v0.8.x, 30 DEC 2025)

Collection-aware Leaflet viewer at `/api/raster/viewer?collection={id}`.

**Key files**: `raster_collection_viewer/service.py`

### S2.11: Raster Data Extract API
**Status**: Done (v0.8.x)

Endpoints for extracting raster data without visualization:
- `/api/raster/point` — value at coordinates
- `/api/raster/clip` — extract by bounding box
- `/api/raster/preview` — low-resolution preview image
- `/api/raster/extract` — general extraction

**Key files**: `raster_api/`

### S2.12: Raster Classification
**Status**: Planned

Automated raster classification using band count + dtype + value range to determine: DEM, RGB, Grayscale, Multispectral, Hyperspectral. Classification drives tier selection and default visualization parameters. Decision tree designed, not implemented.

### S2.13: FATHOM ETL Phase 1
**Status**: Done (v0.9.x)

Band stacking for FATHOM global flood return period data. Multiple GeoTIFFs (one per return period) stacked into a single multi-band COG for efficient storage and tile serving.

**Key files**: `services/fathom/fathom_etl.py`, `jobs/fathom_*.py`

### S2.14: FATHOM ETL Phase 2
**Status**: Partial (v0.9.x — 46/47 tiles complete)

Spatial merge of FATHOM tiles into contiguous coverage. 46 of 47 spatial merge tasks completed. One task (`n10-n15_w005-w010`) failed and requires retry with `force_reprocess=true`.

**Key files**: `services/fathom/fathom_etl.py`
