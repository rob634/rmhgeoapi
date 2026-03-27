# Unified Zarr Ingest Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a unified DAG workflow that accepts NetCDF or Zarr inputs, copies to mount, rechunks to 256×256, generates multiscale pyramids via ndpyramid, and registers with STAC.

**Architecture:** Download-to-mount first node, then validate from local filesystem, conditional routing (NC vs Zarr), two processing paths converging on shared register+STAC tail. NC path is single-pass from mount (convert+chunk+pyramid). Zarr path is two-step from mount (rechunk, then pyramid).

**Tech Stack:** xarray, zarr 3.x, ndpyramid, rioxarray, Dask, adlfs, `conda activate azgeo`

**Spec:** `docs/superpowers/specs/2026-03-27-unified-zarr-ingest-design.md`

**COMPETE:** Run 58 — 5 fixes applied. D9 (copy-to-mount-first) added post-COMPETE.

---

## Status (27 MAR 2026)

### Completed (from first implementation round)

- [x] **Task 1**: Add ndpyramid + rioxarray dependencies — `a4935911`
- [x] **Task 2**: Create `zarr_validate_source` handler — `e96ddc92` (needs revision: D9 mount-first)
- [x] **Task 3**: Create `zarr_generate_pyramid` handler — `cc321e93`
- [x] **Task 4**: Create `netcdf_convert_and_pyramid` handler — `350290d8` (needs revision: D9 mount-first + COMPETE fixes)
- [x] **Task 5**: Modify `ingest_zarr_rechunk` — bypass + zarr_store_url — `6508d12f`
- [x] **Task 6**: Register handlers in ALL_HANDLERS — `a729fc57`
- [x] **Task 7**: Create unified `ingest_zarr.yaml` — `cc8e2704` (needs revision: add download node)
- [x] **Task 8**: Local validation — passed

### COMPETE Run 58 Fixes Applied

- [x] Fix 1: Register node URL — add `zarr_store_url` to NC handler result — `83cb6eb4`
- [x] Fix 2: Silver storage account — use `BlobRepository.for_zone("silver")` — `83cb6eb4`
- [x] Fix 3: dry_run guards in register + materialize handlers — `a8efeffd`
- [x] Fix 4: Pass encoding to `pyramid.to_zarr()` — `4dc4fb01`
- [x] Fix 5: Consolidated metadata fallback in validate — `4dc4fb01`

### E2E Fix Applied

- [x] Fix 6: BlobRepository credentials in validate — `4b5b3648`

### Remaining (D9: copy-to-mount-first revision)

These tasks revise the existing handlers to follow D9 — all reads from mounted local filesystem, not `abfs://` URLs.

---

## File Map (Revised)

| File | Action | Responsibility |
|------|--------|----------------|
| `services/zarr/handler_download_to_mount.py` | **Create** | Copy NC files or Zarr store from bronze to `/mount/etl-temp/{run_id}/` |
| `services/zarr/handler_validate_source.py` | **Revise** | Read from mount path (not abfs://), remove fsspec/credential code |
| `services/handler_netcdf_to_zarr.py` | **Revise** | `netcdf_convert_and_pyramid` reads NC from mount (local paths, no storage_options) |
| `services/handler_ingest_zarr.py` | **Revise** | `ingest_zarr_rechunk` reads Zarr from mount (local path) |
| `services/zarr/handler_generate_pyramid.py` | **Revise** | Read Zarr from mount (local path) |
| `services/__init__.py` | **Modify** | Register `zarr_download_to_mount` |
| `workflows/ingest_zarr.yaml` | **Revise** | Add `download_to_mount` as first node, wire mount paths |

---

### Task 9: Create `zarr_download_to_mount` handler

New handler that copies source data (NC files or Zarr store) from bronze blob storage to the Docker ETL mount.

**Files:**
- Create: `services/zarr/handler_download_to_mount.py`

**Behavior:**
- Receives: `source_url`, `source_account`, `_run_id` (system-injected)
- Creates mount directory: `/mount/etl-temp/{run_id}/source/`
- Lists all blobs under `source_url` prefix
- Streams each blob to the mount directory, preserving relative paths
- Returns: `{success: true, mount_path: "/mount/etl-temp/{run_id}/source/", file_count: N, total_bytes: N}`

**Design notes:**
- Uses `BlobRepository.for_zone("bronze")` for credentials (no bare storage_options)
- Handles both NC files (flat list of .nc files) and Zarr stores (directory tree with metadata + chunk files)
- Path traversal guard: reject blob names containing `..` or starting `/`
- Follow `raster_download_source` pattern (streaming, idempotent directory creation)

- [ ] Step 1: Write handler
- [ ] Step 2: Verify import
- [ ] Step 3: Commit

---

### Task 10: Revise `zarr_validate_source` to read from mount

**Files:**
- Modify: `services/zarr/handler_validate_source.py`

**Changes:**
- Replace `source_url` + `source_account` + fsspec cloud access with `mount_path` param
- Detect input type by scanning local directory (look for `.nc` files or `zarr.json`/`.zmetadata`)
- For Zarr: `xr.open_zarr(mount_path)` — local filesystem, no storage_options needed
- For NetCDF: `glob.glob(f"{mount_path}/*.nc")` — local file listing
- Remove `BlobRepository` import and all credential handling
- Keep same return contract: `{input_type, file_list, dimensions, current_chunks, needs_rechunk}`

- [ ] Step 1: Revise handler
- [ ] Step 2: Verify import
- [ ] Step 3: Commit

---

### Task 11: Revise `netcdf_convert_and_pyramid` to read from mount

**Files:**
- Modify: `services/handler_netcdf_to_zarr.py` (the `netcdf_convert_and_pyramid` function)

**Changes:**
- Replace `abfs://` URL construction from `file_list` with local mount paths
- `xr.open_mfdataset(local_paths, engine="netcdf4")` — no `storage_options` (netcdf4 reads local files natively)
- Keep silver write via `BlobRepository.for_zone("silver")` (output goes to blob, not mount)
- The Dask graph reads from local mount, writes pyramid to silver blob — this is the correct flow

- [ ] Step 1: Revise handler
- [ ] Step 2: Verify import
- [ ] Step 3: Commit

---

### Task 12: Revise `ingest_zarr_rechunk` to read from mount

**Files:**
- Modify: `services/handler_ingest_zarr.py` (the `ingest_zarr_rechunk` function)

**Changes:**
- Accept `mount_path` param (local Zarr store path on mount)
- `xr.open_zarr(mount_path)` — local filesystem, no storage_options for read
- Keep silver write via `BlobRepository.for_zone("silver")` storage_options (output to blob)
- Bypass logic unchanged (still checks `current_chunks` from validate)

- [ ] Step 1: Revise handler
- [ ] Step 2: Verify import
- [ ] Step 3: Commit

---

### Task 13: Revise `zarr_generate_pyramid` to read from mount

**Files:**
- Modify: `services/zarr/handler_generate_pyramid.py`

**Changes:**
- For Zarr path: receives `zarr_store_url` which may now be a local mount path (from rechunk) OR an abfs:// URL (rechunk writes to silver blob)
- Actually: rechunk writes to silver blob, so pyramid reads from silver blob — this is correct as-is
- **No change needed** if rechunk output stays in silver blob. The pyramid handler reads from wherever rechunk wrote.

Review whether this task is actually needed — if rechunk writes to silver blob and pyramid reads from silver blob, the mount-first principle was already satisfied by the download node at the start.

- [ ] Step 1: Review — determine if change needed
- [ ] Step 2: If needed, revise handler
- [ ] Step 3: Commit if changed

---

### Task 14: Revise `ingest_zarr.yaml` — add download_to_mount node

**Files:**
- Modify: `workflows/ingest_zarr.yaml`

**Changes:**
- Add `download_to_mount` as the first node (before validate)
- Validate node `depends_on: [download_to_mount]` and receives `mount_path`
- All downstream receives that referenced `source_url` now use `mount_path` from download node
- NC convert receives local file paths from validate (not abfs:// URLs)
- Rechunk receives mount path (local Zarr store)

New workflow shape:
```
download_to_mount → validate → detect_type
                                  /         \
                           NC path        Zarr path
                              |               |
                    convert_and_pyramid   rechunk
                              |               |
                              |        generate_pyramid
                               \             /
                              register → STAC
```

- [ ] Step 1: Revise YAML
- [ ] Step 2: Validate loads with zero errors
- [ ] Step 3: Commit

---

### Task 15: Register `zarr_download_to_mount` in ALL_HANDLERS

**Files:**
- Modify: `services/__init__.py`

- [ ] Step 1: Add import and registration
- [ ] Step 2: Verify handler count (should be 62)
- [ ] Step 3: Commit

---

### Task 16: Local validation + E2E retest

- [ ] Step 1: Verify all handlers resolve
- [ ] Step 2: Verify YAML loads with zero errors (9 nodes now)
- [ ] Step 3: Deploy and submit NC test
- [ ] Step 4: Deploy and submit Zarr test
- [ ] Step 5: Verify pyramid structure in output

---

## E2E Test Data (from SIEGE config)

- **NetCDF**: `wargames/good-data/climatology-spei12-annual-mean_cmip6-x0.25_ensemble-all-ssp370_climatology_median_2040-2059.nc` (4 MB)
- **Zarr**: `wargames/good-data/cmip6-tasmax-quick.zarr` (10 MB)
