# Greensight: VirtualiZarr NetCDF Pipeline

**Date**: 27 FEB 2026
**Pipeline Used**: Greensight (S -> A+C+O -> M -> B -> V -> Spec Diff)
**Status**: Code committed (`ad3b8bd`), NEEDS MINOR WORK per Validator
**Agent V Rating**: NEEDS MINOR WORK -- architecture sound, 5 must-fix items before ship

---

## Spec: VirtualiZarr NetCDF Pipeline

### Purpose

This subsystem ingests NetCDF files from Azure Blob Storage, generates lightweight kerchunk reference files that make them accessible as virtual Zarr stores, and registers the results through the platform's Asset/Release approval workflow. The pipeline eliminates expensive physical Zarr conversion (which doubles storage and takes weeks) by producing ~1MB reference JSON files per NetCDF source (taking seconds each).

The pipeline serves climate researchers and data publishers who have multi-gigabyte NetCDF datasets (e.g., CMIP6 climate projections) and need to serve them via TiTiler-xarray for tile-based visualization and xarray API for time-series extraction.

### Boundaries

**In Scope**: Scan blob container for `.nc` files, validate chunking suitability, generate kerchunk references via VirtualiZarr, combine into virtual dataset, build STAC item, create Asset/Release records. All heavy processing on Docker Worker.

**Out of Scope**: Uploading NetCDFs, physical Zarr conversion, TiTiler-xarray deployment, approval workflow modifications, STAC collection creation, CMIP6-specific filename parsing.

### Contracts

**Contract 1: Job Submission** (`POST /api/platform/submit`)
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
    "max_files": 500
  }
}
```

**Contract 2: Scan Stage** -- `scan_netcdf_container(params, context) -> dict`
- Lists all `.nc` files matching pattern under source_url
- Writes manifest JSON to blob (avoids 256KB Service Bus limit)
- Returns `manifest_url`, `file_count`, `total_size_bytes`
- Returns error (not empty list) if zero files found

**Contract 3: Validate Stage** -- `validate_netcdf_chunking(params, context) -> dict`
- Reads only HDF5 headers (not full data)
- Returns structured chunking info per variable
- Warnings: no HDF5 chunking, chunk > 100MB, 2D coords > 50MB
- Error: NetCDF3/Classic format (no HDF5 layer)

**Contract 4: Combine Stage** -- `combine_virtual_datasets(params, context) -> dict`
- Opens all source NetCDFs via VirtualiZarr (header-only, ~1MB I/O per file)
- Pre-checks dimension/variable compatibility across files
- Concatenates along `concat_dim`, exports combined kerchunk reference JSON
- Extracts `time_range`, `spatial_extent`, `dimensions`, `variables`

**Contract 5: Register STAC** -- `register_zarr_stac(params, context) -> dict`
- Builds STAC item with xarray-specific properties (`xarray:open_kwargs`, `zarr:chunks`)
- Caches STAC dict on Release via `update_stac_item_json()`
- Updates blob_path, sets processing_status to COMPLETED
- Does NOT write to pgSTAC (that happens at approval)

### Invariants

1. **No data duplication**: Only lightweight reference JSON files created. <1% of source data size.
2. **Reference validity**: Every reference file resolves to same data as original NetCDF.
3. **One Release per pipeline run**: Combined reference is the Release artifact.
4. **STAC cached, not materialized**: Written to pgSTAC only at approval time.
5. **Original files untouched**: Pipeline is read-only against source container.
6. **Stage ordering**: Scan -> Validate -> Combine -> Register STAC (strict).

### Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| **Performance** | Scan <10s, Validate <5s/file, Generate <30s/file, Combine <60s. 50-file dataset <15min. |
| **Reliability** | Partial fan-out failure -> job FAILED. Idempotent retries via same job_id. |
| **Security** | Azure Managed Identity for all blob access. No user-supplied code execution. |
| **Observability** | INFO logging with params/count/duration per handler. Structured error returns. |

### Infrastructure Context

- **Docker Worker**: 4GB RAM (P0v3), 4 instances, shared `container-tasks` queue
- **Dependencies (new)**: `virtualizarr>=1.0,<2.0`, `kerchunk>=0.2.6,<0.3.0`, `h5py>=3.10.0,<4.0`
- **Storage**: Bronze (source NetCDF) -> Silver (output refs)
- **Constraint**: `numpy<2` pin for GDAL ABI compatibility

---

## Key Resolutions (from Mediator)

The Mediator resolved 12 conflicts between Advocate (A), Critic (C), and Operator (O) agents.

### Conflict 1.1: DataType Enum -- The Blocker

**Problem**: `DataType` enum has no `ZARR`. Asset model constrains to `Literal["vector", "raster"]`. Approval service infers data_type as `'raster' if blob_path else 'vector'` -- zarr would be misidentified.

**Resolution**: Three-part fix:
1. Add `ZARR = "zarr"` to platform DataType enum. `.nc` returns ZARR.
2. Widen Asset model to `Literal["vector", "raster", "zarr"]`.
3. Fix approval service to check `geoetl:data_type` from cached STAC, not blob_path inference.

### Conflict 1.2: numpy<2 Pin vs Dependencies

**Resolution**: Pin compatible versions (`virtualizarr>=1.0,<2.0`, `kerchunk>=0.2.6,<0.3.0`). If VirtualiZarr 1.x hard-requires numpy 2, fall back to 0.x series. numpy 2 migration is a separate enabler story.

### Conflict 1.3: Service Bus 256KB Message Limit

**Resolution**: Scan stage writes file list to blob as JSON manifest (`refs/{dataset_id}/manifest.json`). Subsequent stages receive only the manifest URL. Individual task messages contain a single file URL (~200 bytes).

### Conflict 1.4: Shared Queue Contention

**Resolution**: Accept shared `container-tasks` queue for V1. Add `max_files` cap (default 500) to limit fan-out. Dedicated queue is a V2 decision.

### Conflict 2.4: Stage 3 (Generate Individual Refs) Removed

**Problem**: VirtualiZarr's `open_virtual_dataset()` works directly on NetCDFs -- individual per-file refs serve no purpose.

**Resolution**: Pipeline reduced from 5 stages to 4: Scan -> Validate -> Combine -> Register. Net simplification.

### Conflict 2.5: STAC Collection Builder is Raster-Specific

**Resolution**: Do NOT reuse `build_raster_stac_collection()`. Register handler builds zarr-specific STAC item inline with `xarray:open_kwargs` and `application/json` media type.

### Conflict 2.6: Approval Materialization Has No Zarr Path

**Resolution**: Add zarr-specific branch in `materialize_item()`. Detection via `geoetl:data_type == 'zarr'` in cached STAC. No TiTiler URL injection for V1. Upserts to pgSTAC with B2C sanitization.

### Conflict 2.7: Dimension Mismatch During Combine

**Resolution**: Combine stage pre-checks all files share same variables and compatible non-concat dimensions. Fails fast with descriptive error on mismatch.

### Resolved Pipeline Architecture

**4-stage job** using CoreMachine Job -> Stage -> Task pattern:

```
VirtualZarrJob
├── Stage 1: Scan (single task)
│   └── List .nc files, write manifest to blob
├── Stage 2: Validate (fan-out, 1 task per file)
│   └── Check HDF5 chunking suitability
├── Stage 3: Combine (single task)
│   └── VirtualiZarr open_virtual_dataset + concat + export
└── Stage 4: Register (single task)
    └── Build STAC item, cache on Release
```

### Deferred Decisions

| ID | Decision | Trigger to Revisit |
|----|----------|-------------------|
| D1 | TiTiler-xarray URL injection | When TiTiler-xarray is deployed |
| D2 | ETag verification for source files | Production deployment or data inconsistency report |
| D3 | Checkpoint/resume for Combine | Datasets routinely exceed 1000 files |
| D4 | datacube STAC extension | When STAC API consumers need dimension queries |
| D5 | Partial failure cleanup | When silver storage costs become meaningful |
| D6 | Independent queue for zarr tasks | When zarr + raster/vector cause queue starvation |
| D7 | numpy 2 migration | When VirtualiZarr drops numpy 1.x support |
| D8 | Per-file reference output (Stage 3) | When incremental dataset updates needed |
| D9 | Non-standard calendar handling | When climate model data with noleap/360_day submitted |

---

## Operator Constraints

### Infrastructure Fit

**Good fit**: Header-only I/O matches Docker worker profile. Job/Stage/Task pattern natural. Blob auth via Managed Identity solved. Task routing is one-line addition.

### Must-Fix Before Implementation

| # | Finding | Severity |
|---|---------|----------|
| 1 | `DataType` enum does not include "zarr" -- submit rejects with 400 | BLOCKER |
| 2 | `numpy<2` pin may conflict with virtualizarr/kerchunk | BLOCKER |
| 3 | Service Bus 256KB limit on Combine stage parameters | HIGH |
| 4 | Approval service infers data_type from blob_path -- zarr misclassified as raster | HIGH |

### Should-Fix Before Ship

| # | Finding | Severity |
|---|---------|----------|
| 5 | No progress reporting in spec | MEDIUM |
| 6 | No ETag verification for source files | MEDIUM |
| 7 | No checkpoint/resume for Combine stage | MEDIUM |
| 8 | Shared queue with raster/vector tasks | LOW |

### Failure Modes

| Mode | Trigger | Blast Radius | Recovery |
|------|---------|-------------|----------|
| F1: Import failure at start | HDF5 library mismatch | Only zarr tasks | Fix deps, rebuild image |
| F2: OOM during Combine | Large coordinate arrays | All in-flight tasks on instance | Reduce max_files or upgrade plan |
| F3: Blob throttling | 50+ concurrent reads | Individual task failure | Resubmit (idempotent refs) |
| F4: Source file modified | File changed mid-pipeline | Silently corrupt reference | Resubmit after files stable |
| F5: SB message >256KB | Thousands of files | Job stuck PROCESSING | Use manifest pattern (resolved) |
| F6: Cold start | Container restart | Single task delay | Automatic recovery |

### Cost Model

VirtualiZarr is dramatically cheaper than raster COG pipeline: no data conversion, no GDAL compute, no large temp files. For 1,000 NetCDFs totaling 50TB, reference storage is ~1GB (~$0.02/month). Dominant cost is existing App Service Plan.

---

## Validator Verdict

**Rating**: NEEDS MINOR WORK -- Pipeline architecture is sound, all integration points wired correctly.

### Spec Diff Summary

- **12 MATCHES**: All core requirements correctly implemented (purpose, boundaries, contracts, invariants, NFRs)
- **8 GAPS**: Stage count (5 -> 4, intentional), no recursive scan, empty-list behavior, missing output fields, no abfs:// validation, auth inconsistency
- **7 EXTRAS**: max_files cap, manifest blob, variable mismatch validation, validation read, output_mode, xarray:open_kwargs, zarr metadata -- all good additions

### Must-Fix Before Ship (5 items)

| # | Issue | Files |
|---|-------|-------|
| 1 | Hardcoded `rmhazuregeosilver` container name | `jobs/virtualzarr.py`, `handler_virtualzarr.py` |
| 2 | Auth inconsistency -- scan uses DefaultAzureCredential, validate/combine use bare fsspec | `handler_virtualzarr.py` |
| 3 | `to_kerchunk()` export likely fails without storage_options | `handler_virtualzarr.py` (combine handler) |
| 4 | Fragile manifest URL reconstruction in Stage 3 | `jobs/virtualzarr.py` |
| 5 | max_files limit mismatch (10000 vs 5000) | `jobs/virtualzarr.py` |

### Should-Fix (6 items)

| # | Issue |
|---|-------|
| 6 | Add recursive scan option or document limitation |
| 7 | Validate source_url starts with `abfs://` |
| 8 | Consolidate duplicate `_get_storage_account()` |
| 9 | Fix or remove validation read in combine handler |
| 10 | Update stale docstring on normalize_data_type |
| 11 | Normalize enum comparison pattern in submit trigger |

### Accepted / Deferred (5 items)

| # | Issue | Rationale |
|---|-------|-----------|
| 12 | release_id injected by submit trigger | Working as designed |
| 13 | No unpublish path for zarr | Out of scope, V2 feature |
| 14 | ADF detection ordering assumption | Safe, document |
| 15 | Memory for virtual datasets | Monitor at scale |
| 16 | No standard Zarr STAC extension | Defer until available |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| R1: VirtualiZarr numpy 1.x incompatibility | MEDIUM | HIGH | Test pip install with numpy<2 before writing code. Fall back to 0.x. |
| R2: HDF5 library conflict in GDAL image | LOW | HIGH | Test Docker build + `import h5py` in CI. |
| R3: VirtualiZarr API instability | MEDIUM | MEDIUM | Pin specific minor version. Wrap in adapter module. |
| R4: Memory exhaustion during Combine | LOW | HIGH | Use `indexes={}`. Cap max_files at 500. Monitor memory. |
| R5: abfs:// URL scheme incompatibility | LOW | MEDIUM | Validate at submit. Test blob access in scan handler. |
| R6: Shared queue starvation | LOW | MEDIUM | max_files cap. Separate queue if needed (D6). |
| R7: Alphabetical != temporal ordering | MEDIUM | LOW | Document naming requirement. |
| R8: Kerchunk JSON format incompatibility | LOW | HIGH | Validation read after combine. |

---

## Pipeline Agent Summary

| Agent | Status | Output |
|-------|--------|--------|
| S (Spec) | DONE | Spec above |
| A (Advocate) | DONE | Fed into Mediator |
| C (Critic) | DONE | Fed into Mediator |
| O (Operator) | DONE | Operator Constraints above |
| M (Mediator) | DONE | Key Resolutions above |
| B (Builder) | DONE | Committed `ad3b8bd` |
| V (Validator) | DONE | Validator Verdict above |

### Next Steps

1. Fix the 5 must-fix items (estimated 1-2 hours)
2. Fix the 6 should-fix items (estimated 30 minutes)
3. Docker dependency verification (virtualizarr, kerchunk, h5py in Docker image)
4. Write tests for the 4 handlers
5. Optional: Chain to Adversarial Review for implementation-level review
