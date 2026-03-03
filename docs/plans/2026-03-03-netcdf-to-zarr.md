# NetCDF-to-Zarr Pipeline — Implementation Plan

**Date**: 03 MAR 2026
**Replaces**: VirtualiZarr pipeline (`virtualzarr` job type)
**New job type**: `netcdf_to_zarr`

---

## Overview

Replace the broken VirtualiZarr pipeline (kerchunk/virtualizarr dependencies removed) with a
real NetCDF → Zarr conversion pipeline. Source NetCDF files live in bronze storage. The pipeline
copies them to the Docker worker's mounted temp storage for fast local processing, converts to
native Zarr, writes to silver-zarr, and registers a STAC item pointing at the Zarr store.

**Key decisions:**
- Chunking: preserve source chunks (rechunking is a future enhancement)
- Pipeline name: `netcdf_to_zarr` (new job type, separate from `virtualzarr`)
- Submit: via `/api/platform/submit` with `data_type: "zarr"` (default pipeline changes from `virtualzarr` → `netcdf_to_zarr`)
- Dependencies: `xarray`, `zarr`, `adlfs` only — no `kerchunk`, no `virtualizarr`

---

## Pipeline Stages

```
Bronze (NetCDF) → scan → copy to mount → validate → convert to Zarr → register
```

| Stage | Name | Task Type | Parallelism | Description |
|-------|------|-----------|-------------|-------------|
| 1 | scan | `netcdf_scan` | single | List NetCDF files in bronze, write manifest |
| 2 | copy | `netcdf_copy` | fan_out | Copy each file from bronze → /mounts/etl-temp/{job_id}/ |
| 3 | validate | `netcdf_validate` | fan_out | Open each local file with xarray, extract metadata |
| 4 | convert | `netcdf_convert` | single | xr.open_mfdataset() → ds.to_zarr() to silver-zarr |
| 5 | register | `netcdf_register` | single | Build STAC item, update release |

### Stage Details

**Stage 1 — Scan**
- Input: `source_url` (abfs:// bronze path), `file_pattern` (default `*.nc`), `max_files`
- Lists blobs matching pattern, sorts alphabetically
- Writes `manifest.json` to silver-zarr at `{output_folder}/manifest.json`
- Returns: `manifest_url`, `file_count`, `total_size_bytes`

**Stage 2 — Copy to mount**
- Fan-out: one task per file from manifest
- Input per task: `source_url`, `source_account`, `local_dir` (`/mounts/etl-temp/{job_id}/`)
- Copies blob to local mount path
- Returns: `local_path`, `bytes_copied`

**Stage 3 — Validate**
- Fan-out: one task per file
- Input per task: `local_path` (path on mount)
- Opens with `xarray` + `netcdf4` engine
- Extracts: variables (shape, dtype, chunks), dimensions, coordinate info
- Generates warnings for problematic structures
- Returns: `local_path`, `variables`, `dimensions`, `warnings`

**Stage 4 — Convert**
- Single task
- Input: `local_dir`, `output_folder`, `concat_dim`, `dataset_id`, `resource_id`
- `xr.open_mfdataset(glob.glob(local_dir/*.nc))` with chunks preserved
- `ds.to_zarr(store, mode='w')` writing to silver-zarr via adlfs/fsspec
- Cleans up temp files from mount after successful write
- Extracts: spatial_extent (from lat/lon coords), time_range (from time coord), variables, dimensions
- Returns: `zarr_url`, `spatial_extent`, `time_range`, `variables`, `dimensions`, `source_file_count`

**Stage 5 — Register**
- Single task
- Input: `release_id`, `stac_item_id`, `collection_id`, `dataset_id`, `resource_id`, `zarr_url`, plus metadata from Stage 4
- Builds STAC item with `geoetl:pipeline = "netcdf_to_zarr"`, `geoetl:data_type = "zarr"`
- STAC asset points at native Zarr store (type `application/vnd+zarr`)
- Updates release: `stac_item_json`, `physical_outputs` (output_mode=`zarr_store`), `processing_status=COMPLETED`
- Returns: `stac_item_cached`, `release_updated`, `blob_path`

---

## Files to Create

### 1. `jobs/netcdf_to_zarr.py` — Job definition
- Class `NetCDFToZarrJob(JobBaseMixin, JobBase)`
- `job_type = "netcdf_to_zarr"`
- `reversed_by = "unpublish_zarr"` (reuse existing unpublish pipeline)
- 5 stages as defined above
- `parameters_schema` with: `source_url`, `source_account`, `file_pattern`, `concat_dim`, `max_files`, `output_folder`, `stac_item_id`, `collection_id`, `dataset_id`, `resource_id`, `version_id`
- `create_tasks_for_stage()` with manifest-driven fan-out for stages 2 and 3

### 2. `services/handler_netcdf_to_zarr.py` — Handler implementations
- `netcdf_scan(params, context)` — list blobs, write manifest to silver-zarr
- `netcdf_copy(params, context)` — copy single file from bronze blob to local mount
- `netcdf_validate(params, context)` — open with xarray, extract metadata
- `netcdf_convert(params, context)` — open_mfdataset → to_zarr, cleanup temp
- `netcdf_register(params, context)` — build STAC item, update release

---

## Files to Modify

### 3. `jobs/__init__.py` — Register new job
- Add `from jobs.netcdf_to_zarr import NetCDFToZarrJob`
- Add `"netcdf_to_zarr": NetCDFToZarrJob` to `ALL_JOBS`

### 4. `services/__init__.py` — Register new handlers
- Add imports for all 5 handlers from `services.handler_netcdf_to_zarr`
- Add all 5 to `ALL_HANDLERS` dict

### 5. `config/defaults.py` — Add task types to DOCKER_TASKS
- Add `netcdf_scan`, `netcdf_copy`, `netcdf_validate`, `netcdf_convert`, `netcdf_register`
  to `TaskRoutingDefaults.DOCKER_TASKS` frozenset

### 6. `services/platform_translation.py` — Route zarr submissions to new pipeline
- Change default pipeline from `'virtualzarr'` to `'netcdf_to_zarr'` in the zarr translation block
- Update the `else` branch to return `'netcdf_to_zarr'` with appropriate params
- Keep `ingest_zarr` path unchanged
- Add `output_folder` param (like `ref_output_prefix` but for zarr output): `zarr/{dataset_id}/{resource_id}`

---

## Implementation Order

1. **Create `jobs/netcdf_to_zarr.py`** — job definition with stages and task creation logic
2. **Create `services/handler_netcdf_to_zarr.py`** — all 5 handler functions
3. **Register in `jobs/__init__.py`** and **`services/__init__.py`**
4. **Add task types to `config/defaults.py`** DOCKER_TASKS
5. **Update `services/platform_translation.py`** — route default zarr to new pipeline
6. **Test**: submit a zarr job via `/api/platform/submit` and verify all stages complete

---

## What Stays / What Goes

| Component | Action |
|-----------|--------|
| `jobs/virtualzarr.py` | Keep for now (historical job lookups). Do NOT delete yet. |
| `services/handler_virtualzarr.py` | Keep for now. No new jobs will route here. |
| `jobs/ingest_zarr.py` | Unchanged — separate pipeline for native Zarr input |
| `jobs/unpublish_zarr.py` | Unchanged — reused by `netcdf_to_zarr` via `reversed_by` |
| `silver-netcdf` container | No longer used by new pipeline. Existing data stays. |
| `kerchunk`, `virtualizarr` deps | Not needed. Can be removed from requirements in a separate cleanup. |

---

## Key Differences from VirtualiZarr

| Aspect | VirtualiZarr (old) | NetCDF-to-Zarr (new) |
|--------|-------------------|---------------------|
| Output | Kerchunk JSON reference | Native Zarr store |
| Silver container | silver-netcdf | silver-zarr |
| Copy target | silver-netcdf (permanent) | /mounts/etl-temp (temporary) |
| Stage 4 | virtualizarr combine → JSON | xarray open_mfdataset → to_zarr |
| STAC asset type | application/json | application/vnd+zarr |
| STAC open_kwargs | kerchunk reference protocol | Direct zarr store URL |
| Dependencies | virtualizarr, kerchunk, h5py | xarray, zarr, adlfs |
| TiTiler compat | Broken | Works directly |
| output_mode | zarr_reference | zarr_store |

---

## Manifest Location Change

Old: `silver-netcdf/{ref_output_prefix}/manifest.json`
New: `silver-zarr/{output_folder}/manifest.json`

The manifest is a coordination artifact — it lists the source files discovered in Stage 1 so
Stages 2 and 3 can fan out. Storing it alongside the zarr output in silver-zarr keeps all
pipeline artifacts in one container.

---

## Temp File Cleanup

Stage 4 (convert) is responsible for cleaning up `/mounts/etl-temp/{job_id}/` after successful
Zarr write. If Stage 4 fails, the janitor service's existing temp cleanup will handle it
(files older than 24h in etl-temp are purged).
