# Feature F3: Multidimensional Data & Serving — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Partial — core pipelines operational, CMIP6 hosting and unified TiTiler planned

---

## Feature Description

Multidimensional Data & Serving handles NetCDF and Zarr stores — the primary formats for climate, weather, and Earth observation time-series data. The platform supports two ingest paths: native Zarr (cloud-native passthrough using abfs:// URLs that read directly from Azure Blob Storage) and NetCDF-to-Zarr conversion with spatial 256x256, time=1 rechunking optimized for TiTiler xarray tile serving.

All Zarr outputs use flat Zarr v3 format with Blosc+LZ4 compression. Pyramid generation was evaluated and removed — TiTiler xarray cannot read multiscale DataTree stores, so flat stores with optimized chunking are the correct approach. A VirtualiZarr pipeline creates lightweight Kerchunk-style reference stores that enable cloud-native access to NetCDF files without copying the full dataset.

The xarray service layer provides point queries, time-series statistics, and spatial aggregation endpoints for direct analytical access to Zarr stores.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S3.1 | Native Zarr ingest | Done | v0.9.11.8 | Cloud-native passthrough for abfs:// URLs, no copy needed |
| S3.2 | NetCDF to Zarr conversion | Done | v0.9.13.4 | Rechunked flat v3: spatial 256x256, time=1, Blosc+LZ4 |
| S3.3 | Zarr v3 consolidation fix | Done | v0.9.16.1 | Explicit zarr.consolidate_metadata() after every to_zarr() |
| S3.4 | TiTiler xarray integration | Done | v0.9.16.1 | Tile serving verified with ERA5 + CMIP6 data |
| S3.5 | VirtualiZarr pipeline | Done | v0.9.9.0 | Lazy Kerchunk-style reference stores (5-stage pipeline) |
| S3.6 | Zarr unpublish pipeline | Done | v0.10.9 | `unpublish_zarr.yaml`: inventory, fan-out blob deletion, cleanup |
| S3.7 | Zarr observability | Done | v0.9.16.0 | Tier 1 + Tier 2 checkpoint events at operation boundaries |
| S3.8 | xarray service layer | Done | v0.9.x | Point, statistics, aggregate endpoints |
| S3.9 | CMIP6 data hosting | Planned | — | Curated East Africa climate projections (SSP2-4.5, SSP5-8.5) |
| S3.10 | TiTiler unified services | Planned | — | Unified tile serving for COG + Zarr via single TiTiler instance |

---

## Story Detail

### S3.1: Native Zarr Ingest
**Status**: Done (v0.9.11.8, 2 MAR 2026)

Native Zarr stores already in Azure Blob Storage are ingested via cloud-native passthrough — the `zarr_download_to_mount` handler detects abfs:// URLs and skips the download step entirely. The Zarr store is read directly from blob storage, validated, and registered. Optional rechunking creates a new store with optimal chunk alignment (256x256 spatial, time=1). .zarr suffix auto-detection on file type.

**Key files**: `services/zarr/handler_download_to_mount.py`, `services/zarr/handler_validate_source.py`, `workflows/ingest_zarr.yaml`

### S3.2: NetCDF to Zarr Conversion
**Status**: Done (v0.9.13.4, 5 MAR 2026)

NetCDF files are converted to flat Zarr v3 stores with optimized chunking: spatial 256x256 pixels, time=1 slice, Blosc+LZ4 compression. This chunking pattern aligns with TiTiler xarray's access pattern for fast tile rendering. Pyramid generation (ndpyramid + pyresample) was evaluated and removed — TiTiler xarray cannot read multiscale DataTree stores.

**Key files**: `services/handler_netcdf_to_zarr.py`, `services/zarr/handler_download_to_mount.py`

### S3.3: Zarr v3 Consolidation Fix
**Status**: Done (v0.9.16.1, 9 MAR 2026)

Critical fix: xarray trusts consolidated metadata — if the consolidated metadata file is empty or stale, xarray reports zero variables. Solution: explicit `zarr.consolidate_metadata()` call after every `to_zarr()` write for zarr_format==3. Verified with ERA5 and CMIP6 data rendering on TiTiler.

**Key files**: `services/handler_netcdf_to_zarr.py`, `services/handler_ingest_zarr.py`

### S3.4: TiTiler xarray Integration
**Status**: Done (v0.9.16.1, 9 MAR 2026)

TiTiler xarray (titiler-xarray) serves dynamic tiles from Zarr stores. The platform injects `xarray:open_kwargs` with `account_name` and storage URL into STAC items so TiTiler can locate the Zarr store. Tile serving verified with rescale and colormap parameters on ERA5 temperature and CMIP6 precipitation data.

**Key files**: `services/zarr/handler_register.py` (xarray URL injection)
**Known issue**: `account_name` leaks to B2C consumers via STAC item properties (tracked as DF-STAC-5, deferred to v0.10.10)

### S3.5: VirtualiZarr Pipeline
**Status**: Done (v0.9.9.0, 28 FEB 2026)

Five-stage pipeline creating lightweight Kerchunk-style reference stores: (1) scan_netcdf_variables, (2) copy_netcdf_to_silver, (3) validate_netcdf, (4) combine_virtual_zarr, (5) register_zarr_catalog. The reference store is ~KB in size while the source NetCDF files remain unchanged in Bronze storage. Enables cloud-native access without THREDDS or full data copy.

**Key files**: `services/handler_netcdf_to_zarr.py`

### S3.6: Zarr Unpublish Pipeline
**Status**: Done (v0.10.9)

`unpublish_zarr.yaml` (3 nodes): inventory Zarr metadata to identify blob paths, fan-out deletion of Zarr chunks from silver-zarr storage, STAC item deletion with audit trail.

**Key files**: `workflows/unpublish_zarr.yaml`, `services/unpublish_handlers.py`

### S3.7: Zarr Observability
**Status**: Done (v0.9.16.0, 8 MAR 2026)

Tier 1 (inline logging): progress percentage and elapsed time at operation boundaries. Tier 2 (structured checkpoints): JobEventType.CHECKPOINT events with checkpoint_type (validate_start, copy_progress, rechunk_complete, etc.) for fine-grained progress tracking during long-running Zarr operations.

**Key files**: `services/zarr/handler_*.py`, `core/models/events.py`

### S3.8: xarray Service Layer
**Status**: Done (v0.9.x)

Direct analytical access to Zarr stores via REST API:
- `/api/xarray/point` — time-series value at coordinates
- `/api/xarray/statistics` — zonal statistics over bounding box
- `/api/xarray/aggregate` — temporal aggregation

**Key files**: `xarray_api/`, `services/xarray_reader.py`

### S3.9: CMIP6 Data Hosting
**Status**: Planned

Curated East Africa climate projections from CMIP6 models. Variables: tas, pr, tasmax, tasmin. Scenarios: SSP2-4.5, SSP5-8.5. Will use the native Zarr ingest pipeline (S3.1) with rechunking optimized for the target spatial domain.

### S3.10: TiTiler Unified Services
**Status**: Planned

Consolidate COG tile serving (titiler-pgstac) and Zarr tile serving (titiler-xarray) into a single TiTiler deployment or a unified routing layer. Currently separate services.
