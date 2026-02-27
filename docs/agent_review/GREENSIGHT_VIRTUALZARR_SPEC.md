# Greensight Spec: VirtualiZarr NetCDF Pipeline

**Written by**: Agent S (Claude, 27 FEB 2026)
**Status**: SPEC — Awaiting A + C + O review

---

## PURPOSE

This subsystem ingests NetCDF files from Azure Blob Storage, generates lightweight kerchunk reference files that make them accessible as virtual Zarr stores, and registers the results through the platform's Asset/Release approval workflow. The pipeline eliminates the need for expensive physical Zarr conversion (which doubles storage and takes weeks) by instead producing ~1MB reference JSON files per NetCDF source (taking seconds each).

The pipeline serves climate researchers and data publishers who have multi-gigabyte NetCDF datasets (e.g., CMIP6 climate projections) and need to serve them via TiTiler-xarray for tile-based visualization and xarray API for time-series extraction.

---

## BOUNDARIES

### In Scope

- Scan a blob container path for `.nc` files
- Validate NetCDF internal chunking suitability for virtualization (HDF5 chunk layout)
- Generate individual kerchunk reference JSON files for each NetCDF file using VirtualiZarr
- Combine multiple single-file references into a combined virtual dataset (concatenation along a user-specified dimension, typically time)
- Build and cache a STAC item dict on the Release (for later materialization at approval)
- Create Asset + AssetRelease records through the existing platform submit flow
- Run all heavy processing on the Docker Worker (rmhheavyapi)
- Support generic NetCDF files (not just CMIP6 — use xarray metadata for grouping, not filename parsing)

### Out of Scope

- Uploading NetCDF files to blob storage (files are pre-staged)
- Physical Zarr conversion (the whole point is to avoid this)
- TiTiler-xarray deployment or configuration (already running)
- Approval workflow modifications (use existing approve/reject/revoke endpoints)
- STAC collection creation (use existing `create_stac_collection()`)
- xarray API endpoint modifications (existing `/api/xarray/*` endpoints serve Zarr stores)
- CMIP6-specific filename parsing (future extension, not core pipeline)

---

## CONTRACTS

### Contract 1: Job Submission (HTTP Trigger → CoreMachine)

**Interface**: `POST /api/platform/submit`

**Input** (PlatformRequest):
```json
{
  "dataset_id": "era5-temperature",
  "resource_id": "global-daily-2020",
  "data_type": "zarr",
  "source_url": "abfs://rmhazuregeobronze/netcdf/era5/",
  "processing_options": {
    "pipeline": "virtualzarr",
    "concat_dim": "time",
    "file_pattern": "*.nc",
    "fail_on_chunking_warnings": false,
    "overwrite": false
  }
}
```

**Output** (on success):
```json
{
  "success": true,
  "job_id": "abc123...",
  "release_id": "def456...",
  "asset_id": "ghi789...",
  "status": "queued"
}
```

**Promises**:
- Idempotent: same dataset_id + resource_id + source_url = same job_id (if not overwrite)
- Asset and Release created before job is queued
- job_id links to release_id for status polling

**Requirements**:
- Caller provides valid `dataset_id` and `resource_id` (non-empty strings)
- `source_url` must be an `abfs://` path to an existing container/prefix
- `data_type` must be `"zarr"` (to route to VirtualiZarr pipeline)

### Contract 2: Scan Stage (Task Handler)

**Interface**: `scan_netcdf_container(params, context) -> dict`

**Input**:
```python
{
    "source_url": "abfs://rmhazuregeobronze/netcdf/era5/",
    "file_pattern": "*.nc",
    "recursive": True
}
```

**Output** (on success):
```python
{
    "success": True,
    "result": {
        "nc_files": ["abfs://rmhazuregeobronze/netcdf/era5/tas_2020.nc", ...],
        "file_count": 12,
        "total_size_bytes": 52428800000
    }
}
```

**Promises**:
- Returns all `.nc` files matching pattern under source_url
- Files listed in sorted order (alphabetical)
- Returns empty list (not error) if no files match

**Requirements**:
- Azure storage credentials available via Managed Identity or env vars
- source_url points to existing container

### Contract 3: Validate Stage (Task Handler)

**Interface**: `validate_netcdf_chunking(params, context) -> dict`

**Input**:
```python
{
    "nc_url": "abfs://rmhazuregeobronze/netcdf/era5/tas_2020.nc",
    "fail_on_warnings": False
}
```

**Output** (on success):
```python
{
    "success": True,
    "result": {
        "nc_url": "abfs://...",
        "status": "success",  # or "warning" or "error"
        "variables": {
            "tas": {"shape": [365, 720, 1440], "dtype": "float32",
                    "chunks": [365, 180, 360], "compression": "gzip"}
        },
        "dimensions": {"time": 365, "lat": 720, "lon": 1440},
        "warnings": [],
        "recommendation": "suitable_for_virtualization"
    }
}
```

**Promises**:
- Reads only HDF5 headers (not full data)
- Returns structured chunking info for every variable
- Fails the task if `fail_on_warnings=True` and critical warnings found

### Contract 4: Generate Reference (Task Handler)

**Interface**: `generate_kerchunk_ref(params, context) -> dict`

**Input**:
```python
{
    "nc_url": "abfs://rmhazuregeobronze/netcdf/era5/tas_2020.nc",
    "ref_url": "abfs://rmhazuregeosilver/refs/era5-temperature/tas_2020.json"
}
```

**Output** (on success):
```python
{
    "success": True,
    "result": {
        "nc_url": "abfs://...",
        "ref_url": "abfs://...",
        "dimensions": {"time": 365, "lat": 720, "lon": 1440},
        "variables": ["tas", "lat", "lon", "time"],
        "ref_size_bytes": 524288
    }
}
```

**Promises**:
- Reads only headers from source NetCDF (~1MB I/O per file regardless of file size)
- Writes reference JSON to `ref_url`
- Reference file is valid kerchunk JSON readable by fsspec/xarray
- Idempotent: re-running overwrites the same ref_url

### Contract 5: Combine References (Task Handler)

**Interface**: `combine_virtual_datasets(params, context) -> dict`

**Input**:
```python
{
    "nc_urls": ["abfs://...1.nc", "abfs://...2.nc", ...],
    "combined_ref_url": "abfs://rmhazuregeosilver/refs/era5-temperature/combined.json",
    "concat_dim": "time",
    "dataset_id": "era5-temperature_global-daily-2020"
}
```

**Output** (on success):
```python
{
    "success": True,
    "result": {
        "dataset_id": "era5-temperature_global-daily-2020",
        "combined_ref_url": "abfs://...",
        "source_files": 12,
        "dimensions": {"time": 4380, "lat": 720, "lon": 1440},
        "variables": ["tas"],
        "time_range": ["2020-01-01", "2031-12-31"],
        "spatial_extent": [-180.0, -90.0, 180.0, 90.0],
        "ref_size_bytes": 2097152
    }
}
```

**Promises**:
- Concatenates all source files along `concat_dim`
- Extracts spatial extent from coordinate variables
- Extracts temporal range from time coordinate
- Combined reference file is valid for TiTiler-xarray and xarray API access

### Contract 6: Register STAC (Task Handler)

**Interface**: `register_zarr_stac(params, context) -> dict`

**Input**:
```python
{
    "release_id": "def456...",
    "dataset_id": "era5-temperature",
    "resource_id": "global-daily-2020",
    "collection_id": "era5-temperature",
    "combined_ref_url": "abfs://...",
    "dimensions": {...},
    "variables": ["tas"],
    "time_range": ["2020-01-01", "2031-12-31"],
    "spatial_extent": [-180.0, -90.0, 180.0, 90.0]
}
```

**Output** (on success):
```python
{
    "success": True,
    "result": {
        "stac_item_cached": True,
        "release_updated": True,
        "blob_path": "refs/era5-temperature/combined.json"
    }
}
```

**Promises**:
- Builds STAC item dict with xarray-specific properties (xarray:open_kwargs, zarr:chunks)
- Caches STAC dict on Release via `update_stac_item_json()`
- Updates Release blob_path to combined reference URL
- Updates Release processing_status to COMPLETED
- Does NOT write to pgSTAC (that happens at approval)

---

## INVARIANTS

1. **No data duplication**: The pipeline NEVER copies or converts the original NetCDF files. Only lightweight reference JSON files are created. Total reference storage is <1% of source data.

2. **Reference validity**: Every reference file produced by the pipeline, when opened via `fsspec.open_reference()` or `xr.open_zarr()`, must resolve to the same data as opening the original NetCDF with `xr.open_dataset()`.

3. **One Release per pipeline run**: Each job submission creates exactly one AssetRelease. The combined reference (not individual per-file refs) is the Release artifact.

4. **STAC cached, not materialized**: During processing, STAC metadata is cached on the Release as `stac_item_json`. It is only written to pgSTAC at approval time. This is the same pattern used by raster and vector pipelines.

5. **Original files untouched**: The pipeline is read-only with respect to the source NetCDF container. It reads headers, never modifies source data.

6. **Stage ordering**: Stages execute in strict order: Scan → Validate → Generate Refs → Combine → Register STAC. Each stage depends on the previous stage's output.

---

## NON-FUNCTIONAL REQUIREMENTS

### Performance
- **Scan**: <10 seconds for containers with up to 10,000 files
- **Validate**: <5 seconds per file (reads only HDF5 headers via byte-range GET)
- **Generate reference**: <30 seconds per file (header-only read, ~1MB I/O)
- **Combine**: <60 seconds for up to 100 source files
- **End-to-end**: A 50-file dataset should complete in <15 minutes including Service Bus latency

### Reliability
- **Partial failure in fan-out stage**: If 2 of 50 files fail validation or ref generation, those tasks fail individually. CoreMachine marks the job FAILED. No partial results are committed.
- **Idempotent retries**: Re-submitting the same dataset_id + resource_id produces the same job_id (unless overwrite=True). Reference files are overwritten idempotently.
- **Blob storage unavailable**: Tasks fail with clear error. No retry loop — retry is manual re-submission.

### Security
- **Azure Managed Identity** for all blob access (no storage keys in code or config)
- **No user-supplied code execution**: The pipeline executes fixed logic against user-specified blob paths. No custom scripts or Lambda-style functions.

### Observability
- **Logging**: Each handler logs at INFO level: input parameters, file count, output size, duration
- **Structured errors**: Failed tasks return `{"success": False, "error": "...", "error_type": "..."}` — consistent with existing handler contract
- **Job tracking**: Job status + task status visible via `/api/jobs/status/{job_id}` and `/api/dbadmin/tasks/{job_id}`

---

## INFRASTRUCTURE CONTEXT

### Runtime Environment
- **Orchestrator**: Azure Functions (rmhazuregeoapi) — receives HTTP submit, dispatches job messages to Service Bus
- **Docker Worker**: Azure App Service container (rmhheavyapi) — executes task handlers
- **Service Bus**: Azure Service Bus queues for job/task message routing
- **Database**: PostgreSQL (rmhpostgres) with `app` schema for jobs/tasks/assets/releases and `pgstac` schema for STAC catalog
- **Blob Storage**: rmhazuregeobronze (source NetCDF), rmhazuregeosilver (output refs + COGs)
- **Docker Image**: `rmhazureacr.azurecr.io/geospatial-worker:VERSION` — must include `virtualizarr`, `h5py`, `fsspec`, `adlfs` packages

### Resource Limits
- **Docker Worker memory**: ~4GB available (App Service B2 plan)
- **Service Bus message size**: 256KB (task parameters must fit)
- **Blob storage**: No practical limit for reference files (~1MB each)
- **CoreMachine fan-out**: No explicit limit, but >1000 parallel tasks untested

### Dependencies (New)
- `virtualizarr` — VirtualiZarr library for reference generation (pip install)
- `h5py` — HDF5 header reading for chunking validation
- `kerchunk` — May be needed as VirtualiZarr backend (check at implementation)
- `fsspec` + `adlfs` — Already in Docker image for Azure blob access
- `xarray` — Already in Docker image for dataset operations

---

## OPEN QUESTIONS

1. **VirtualiZarr API stability**: The `open_virtual_dataset()` and `.virtualize.to_kerchunk()` APIs were sketched in the DEC 2025 plan. Have they changed? Agent C should verify current API.

2. **Single-file vs combined**: Should the pipeline always produce a combined reference, or should single-file datasets skip the combine stage? (Spec assumes: always combine, even for 1 file — simplifies downstream.)

3. **data_type field**: The Asset model uses `data_type = "raster" | "vector"`. Adding `"zarr"` requires checking all code paths that switch on data_type. Agent C should enumerate these.

4. **Collection strategy**: Should each `dataset_id` map to its own STAC collection, or should there be a single `"virtualzarr"` collection? (Spec assumes: one collection per dataset_id, matching raster/vector pattern.)

5. **Spatial extent extraction**: For global climate data, spatial extent is typically [-180, -90, 180, 90]. How should the pipeline extract this from the NetCDF coordinate variables? (Use `lat.min()`, `lon.min()`, etc.)

6. **TiTiler-xarray URL injection**: At STAC materialization, should the item include TiTiler-xarray tile URLs (like raster items include TiTiler COG URLs)? This affects the STAC item builder.
