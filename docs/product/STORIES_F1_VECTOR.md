# Feature F1: Vector Data & Serving — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Vector Data & Serving is the end-to-end pipeline for ingesting vector geospatial data into PostGIS and exposing it as OGC API - Features collections. It accepts six input formats (Shapefile, GeoJSON, GeoPackage, CSV with coordinates, KML) and produces PostGIS tables with spatial indexes, standardized metadata columns, and automatic TiPG collection registration.

The pipeline supports three ingestion patterns: single-file (one file to one table), multi-source (N files or GPKG layers to N tables), and split views (one file to N OGC collections based on a categorical column). A two-phase TiPG discovery model makes tables browsable immediately for approval review, then adds rich metadata (title, description, keywords) after approval.

All vector workflows run on the Epoch 5 DAG engine. The `vector_docker_etl.yaml` workflow (9 nodes) handles the full pipeline including conditional split-column branching. The `acled_sync.yaml` workflow demonstrates API-driven scheduled ingestion as a reference implementation.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S1.1 | Vector ETL pipeline | Done | v0.10.5 | 7 atomic handlers: load, validate, create tables, split views, catalog, TiPG, finalize |
| S1.2 | OGC Features API | Done | v0.8.x | TiPG integration, bbox queries, spatial filtering |
| S1.3 | Multi-format support | Done | v0.10.5 | SHP, GeoJSON, GPKG, CSV (with coords), KML |
| S1.4 | Split views | Done | v0.10.0.2 | Single file to N OGC collections by categorical column (max 20 distinct values) |
| S1.5 | Multi-source vector | Done | v0.10.0.1 | N files to N tables; GPKG multi-layer to N tables |
| S1.6 | TiPG two-phase discovery | Done | v0.10.8 | Browsable pre-approval (bare table), searchable post-approval (rich metadata) |
| S1.7 | Vector unpublish pipeline | Done | v0.10.9 | `unpublish_vector.yaml`: inventory, drop table, STAC cleanup |
| S1.8 | ACLED scheduled sync | Done | v0.10.7 | `acled_sync.yaml`: fetch API, diff, append to PostGIS (cron-scheduled) |
| S1.9 | Catalog registration | Done | v0.10.5 | geo.table_catalog with title, bbox, feature count, CRS |
| S1.10 | Vector DAG workflow | Done | v0.10.7 | `vector_docker_etl.yaml`: 9 nodes, conditional split_column branching |
| S1.11 | Vector map viewer | Done | v0.8.x | Interactive Leaflet viewer at `/api/vector/viewer` |
| S1.12 | Enhanced data validation | Partial | — | Datetime range validation done; pandera evaluation pending |

---

## Story Detail

### S1.1: Vector ETL Pipeline
**Status**: Done (v0.10.5, 19 MAR 2026)

Seven atomic handlers compose the core vector pipeline:

| Handler | Task Type | Purpose |
|---------|-----------|---------|
| `vector_load_source` | `vector_load_source` | Stream blob from bronze to mount, detect format, convert to GeoParquet |
| `vector_validate_and_clean` | `vector_validate_and_clean` | Clean GeoDataFrame, split by geometry type, write GeoParquet |
| `vector_create_and_load_tables` | `vector_create_and_load_tables` | Create PostGIS tables, batch load with etl_batch_id tracking |
| `vector_create_split_views` | `vector_create_split_views` | Create PostgreSQL VIEWs on categorical column |
| `vector_register_catalog` | `vector_register_catalog` | Register in geo.table_catalog and app tracking tables |
| `vector_refresh_tipg` | `vector_refresh_tipg` | Refresh TiPG collection cache (best_effort) |
| `vector_finalize` | `vector_finalize` | Clean up ETL mount directory |

**Key files**: `services/vector/handler_*.py` (7 files), `workflows/vector_docker_etl.yaml`

### S1.2: OGC Features API
**Status**: Done (v0.8.x, NOV 2025)

OGC API - Features implementation via TiPG auto-discovery of PostGIS tables in the `geo` schema. Supports bbox spatial filtering, property filtering, pagination, and GeoJSON/JSON-FG output.

**Key files**: `ogc_features/` module
**Endpoints**: `/api/features/collections`, `/api/features/collections/{id}/items`

### S1.3: Multi-Format Support
**Status**: Done (v0.10.5)

The `vector_load_source` handler detects input format and converts to GeoParquet as a normalized intermediate. Supported formats: Shapefile (.shp + sidecars), GeoJSON (.geojson/.json), GeoPackage (.gpkg), CSV with coordinate columns, KML (.kml). macOS `__MACOSX` resource forks are filtered from ZIP archives.

**Key files**: `services/vector/handler_load_source.py`

### S1.4: Split Views
**Status**: Done (v0.10.0.2, 10 MAR 2026)

When `split_column` is provided, the pipeline creates one base table and N PostgreSQL VIEWs (one per distinct value). Each view is registered in geo.table_catalog and discovered by TiPG as a separate OGC Features collection. Constraints: max 20 distinct values, text/integer/boolean columns only, 63-character PostgreSQL identifier limit.

**Key files**: `services/vector/handler_create_split_views.py`

### S1.5: Multi-Source Vector
**Status**: Done (v0.10.0.1, 10 MAR 2026)

Two patterns: (1) N separate files uploaded together produce N PostGIS tables; (2) a multi-layer GeoPackage produces N tables (one per layer). Both patterns register each table independently in the catalog.

**Key files**: `services/handler_vector_multi_source.py`

### S1.6: TiPG Two-Phase Discovery
**Status**: Done (v0.10.8, 28 MAR 2026)

Phase 1 (pre-approval): `refresh_tipg_preview` runs after table creation. TiPG discovers bare PostGIS table — tiles render, features queryable, but no rich metadata. Approvers can preview data.

Phase 2 (post-approval): `register_catalog` writes title, description, keywords to geo.table_catalog. `refresh_tipg` re-reads metadata. Collection now searchable with full OGC metadata.

**Key files**: `services/vector/handler_refresh_tipg.py`, `workflows/vector_docker_etl.yaml` (nodes: refresh_tipg_preview, register_catalog, refresh_tipg)

### S1.7: Vector Unpublish Pipeline
**Status**: Done (v0.10.9)

`unpublish_vector.yaml` (3 nodes): inventory lookup, PostGIS table drop with metadata cleanup, STAC item deletion with audit. The inventory handler looks up the release_id and revokes atomically in the same transaction as the table drop.

**Key files**: `workflows/unpublish_vector.yaml`, `services/unpublish_handlers.py`

### S1.8: ACLED Scheduled Sync
**Status**: Done (v0.10.7, 20 MAR 2026)

Reference implementation for API-driven scheduled workflows. `acled_sync.yaml` (3 nodes): fetch new ACLED conflict events via API and diff against existing Silver table, save raw responses to Bronze for audit, bulk-INSERT new events into PostGIS via COPY. Runs on a cron schedule via DAGScheduler.

**Key files**: `workflows/acled_sync.yaml`, `services/handler_acled_*.py` (3 files)

### S1.9: Catalog Registration
**Status**: Done (v0.10.5)

The `vector_register_catalog` handler writes table metadata to `geo.table_catalog` including title, bounding box, feature count, CRS, and column schema. Also updates `app.vector_metadata` for ETL tracking. Used by TiPG for rich collection metadata.

**Key files**: `services/vector/handler_register_catalog.py`

### S1.10: Vector DAG Workflow
**Status**: Done (v0.10.7, 20 MAR 2026)

`vector_docker_etl.yaml` v3: 9 nodes with conditional branching on `split_column`. When split_column is provided, the `create_split_views` node activates; otherwise it is skipped via `when` clause. TiPG refresh nodes are marked `best_effort: true` so failures do not block the pipeline. Includes an approval gate between data loading and catalog registration.

**Key files**: `workflows/vector_docker_etl.yaml`

### S1.11: Vector Map Viewer
**Status**: Done (v0.8.x, DEC 2025)

Interactive Leaflet-based map viewer for browsing vector collections. Accessible at `/api/vector/viewer?collection={id}`.

**Key files**: `vector_viewer/service.py`

### S1.12: Enhanced Data Validation
**Status**: Partial

Datetime range validation implemented (catches garbage dates like year 48113 in KML imports — NULL substitution applied). Systematic validation via pandera library pending a 4-hour evaluation spike.

**Key files**: `services/vector/handler_validate_and_clean.py`
