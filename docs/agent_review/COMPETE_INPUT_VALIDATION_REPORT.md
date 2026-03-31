# COMPETE Adversarial Review: Input Validation

**Pipeline**: Alpha (Gates) + Beta (Interior) + Gamma (Gaps) -> Delta (Final)
**Scope**: All input validation paths across raster, vector, and zarr/netcdf handlers
**Date**: 30 MAR 2026
**Version under review**: v0.10.9.x

---

## 1. Executive Summary

Three independent reviewers examined input validation across all data-type handlers (raster, vector, zarr/netcdf) in both Epoch 4 and Epoch 5 code paths. **2 critical, 8 high, and 12 medium findings** were identified after deduplication. The most urgent issues are: (1) zip-slip path traversal in `extractall()` with no defense, (2) no timeout mechanism for GDAL/pyogrio/xarray calls allowing hung tasks to live forever, and (3) a cross-type consistency gap where vector and zarr handlers never set the `retryable` field. Four findings are Epoch 4 only and will be retired by the v0.11.0 strangler fig completion.

---

## 2. Prioritized Fix List

### CRITICAL

| ID | Title | File:Line | Description | Epoch |
|----|-------|-----------|-------------|-------|
| IV-C1 | Zip-slip path traversal | `helpers.py:181` | `extractall()` with no member-path validation. Malicious ZIP can write outside extract dir. Symlink entries also unexamined. | Both |
| IV-C2 | No GDAL/pyogrio/xarray timeout | Multiple handlers | Pulse thread keeps hung tasks alive indefinitely. Corrupt files can hang `rasterio.open`, `cog_translate`, `gpd.read_file`, `xr.open_zarr`. Known project bug ("validate reclaimed by janitor") is a symptom. | Both |

### HIGH

| ID | Title | File:Line | Description | Epoch |
|----|-------|-----------|-------------|-------|
| IV-H1 | Vector + Zarr handlers never set `retryable` | `handler_load_source.py`, `handler_download_source.py` (vector/zarr) | Transient errors (blob download, DB connection) not retried. Only raster handlers set `retryable` consistently. | Both |
| IV-H2 | No blob existence pre-check at submit | `submit.py` | Orphaned Asset/Release created when blob missing. Failure deferred to download stage. | Both |
| IV-H3 | Vector handler missing path traversal guard | `handler_load_source.py` | Raster handler has explicit guard (L121-134). Vector uses `os.path.basename()` for filesystem but raw `blob_name` passed to SAS URL generation. | Both |
| IV-H4 | GPKG remote double-read | `handler_load_source.py:316-328` | `pyogrio.list_layers(blob_url)` called against REMOTE SAS URL when file is already local on mount. Should use `dest_path`. | Both |
| IV-H5 | NetCDF missing spatial dimension check | `handler_validate_source.py` | Non-spatial datasets pass validation, fail late at pyramid generation (Dresden pattern). | Both |
| IV-H6 | Partial PostGIS table orphans | `handler_load_source.py` (vector) | Multi-geometry-group load fails mid-loop; earlier tables remain with no rollback. | Both |
| IV-H7 | Path traversal via `filename` param | `handler_netcdf_to_zarr.py:447` | `os.path.join` with unsanitized `filename` in Epoch 4 netcdf-to-zarr handler. | E4 only |
| IV-H8 | `_skip_validation` bypass | `raster_validation.py` | Parameter bypasses ALL raster validation. Exposed in Epoch 4 job params. Epoch 5 DAG path not affected. | E4 only |

### MEDIUM

| ID | Title | File:Line | Description | Epoch |
|----|-------|-----------|-------------|-------|
| IV-M1 | No file size limits anywhere | `submit.py`, download handlers | No upper bound on file size at submit, download, or conversion. OOM/disk exhaustion risk. | Both |
| IV-M2 | No zip bomb defense | `helpers.py:181` | `extractall()` doesn't check decompressed size from central directory before extraction. | Both |
| IV-M3 | GeoJSON full-file memory load | GeoJSON converter | Loads entire file as JSON before type check. Large non-GeoJSON JSON files consume unbounded memory. | Both |
| IV-M4 | BlobNotFoundError marked retryable | `handler_download_source.py:208` | Missing blobs retried 3 times (210s wasted). Should be non-retryable. | Both |
| IV-M5 | No mount cleanup on handler failure | All handlers | Failed runs accumulate mount storage. 30-day janitor cleanup only. | Both |
| IV-M6 | GPKG default-to-first-layer is warning-only | Vector validation | Multi-layer GPKG silently picks first layer instead of rejecting or requiring explicit selection. | Both |
| IV-M7 | `BadZipFile` silently passed | Handler zip scan | Defers to converter, which may produce confusing error message. | Both |
| IV-M8 | Zarr download extension check bypassed | Zarr handler | Extensionless blob paths skip format verification. | Both |
| IV-M9 | Zarr consolidated metadata fallback hang risk | Zarr handler | Corrupt zarr stores could hang metadata consolidation. | Both |
| IV-M10 | Password-protected zip unhandled | `helpers.py` | `RuntimeError` from `extractall()` not caught. User gets generic "Format conversion failed". | Both |
| IV-M11 | `netcdf_scan` no URL scheme validation | `handler_netcdf_to_zarr.py:212` | Accepts arbitrary URL schemes. | E4 only |
| IV-M12 | `netcdf_copy` reads entire blob into memory | `handler_netcdf_to_zarr.py` (Epoch 4) | OOM risk on large files. Epoch 5 uses streaming. | E4 only |

---

## 3. Cross-Type Consistency Gaps

| Validation | Raster | Vector | Zarr/NC (E5) | Zarr/NC (E4) | Recommendation |
|------------|--------|--------|--------------|--------------|----------------|
| Path traversal guard | YES | PARTIAL | NO | NO | Standardize guard in shared utility; apply to all types |
| Blob existence pre-check | NO | NO | NO | NO | Add to `submit.py` -- single fix covers all types |
| File size limit | NO | NO | NO | NO | Add configurable max at submit + download; single shared check |
| Format/extension check | YES | YES | YES | PARTIAL | E4 gap resolved by strangler fig |
| Empty file detection | YES | YES | PARTIAL | PARTIAL | Add to zarr download handler |
| CRS validation | YES | NO | NO | NO | Add CRS check to vector validation; zarr N/A (multi-CRS possible) |
| `retryable` marking | YES | NO | NO | NO | **Priority fix**: Copy raster pattern to vector + zarr handlers |
| Mount cleanup on failure | NO | NO | PARTIAL | NO | Add cleanup in shared `finally` block or handler base class |
| Zip-slip defense | N/A | NO | N/A | N/A | **Priority fix**: Add member path validation in `extract_zip_file` |
| URL scheme validation | N/A | N/A | YES | NO | E4 gap resolved by strangler fig |

**Key actions:**
- `retryable` marking and zip-slip defense are the highest-value consistency fixes
- Blob pre-check and file size limits are single-point fixes that cover all types
- CRS validation for vector is a new feature (not a bug), lower priority

---

## 4. Dresden Pattern Instances

Validations that run AFTER expensive I/O when they could run BEFORE:

| # | What happens | Where | Cost of late check | Fix |
|---|-------------|-------|--------------------|-----|
| 1 | Blob downloaded, THEN blob existence discovered missing | Download handlers | Full blob download attempt + retry cycle | Pre-check blob existence at submit time (IV-H2) |
| 2 | NetCDF downloaded + opened, THEN spatial dimension check fails | `handler_validate_source.py` | Full file download + xarray open | Add spatial dim check to validation stage before download (IV-H5) |
| 3 | GPKG downloaded to mount, THEN layer list fetched via REMOTE SAS URL | `handler_load_source.py:316-328` | Redundant remote I/O on already-local file | Use `dest_path` for `list_layers` call (IV-H4) |
| 4 | Full GeoJSON loaded into memory, THEN type check applied | GeoJSON converter | Entire file in memory before rejection | Stream-check first few bytes for `FeatureCollection`/`Feature` (IV-M3) |
| 5 | ZIP extracted, THEN format validation applied | Vector handler | Full extraction before rejection | Check central directory entries before extraction (IV-M2) |

---

## 5. Epoch 4 vs Epoch 5 Triage

### Epoch 4 Only -- Retired by v0.11.0 Strangler Fig

These findings exist solely in Epoch 4 code paths. No fix needed if v0.11.0 is imminent.

| ID | Finding | Rationale |
|----|---------|-----------|
| IV-H7 | Path traversal via `filename` in `handler_netcdf_to_zarr.py:447` | Epoch 4 handler only |
| IV-H8 | `_skip_validation` bypass in `raster_validation.py` | Exposed only in Epoch 4 job params |
| IV-M11 | `netcdf_scan` no URL scheme validation | Epoch 4 handler only |
| IV-M12 | `netcdf_copy` full blob memory read | Epoch 5 already uses streaming |

### Must Fix in Both Epochs (or Epoch 5 at minimum)

All other findings (IV-C1, IV-C2, IV-H1 through IV-H6, IV-M1 through IV-M10) affect the active Epoch 5 DAG path and must be addressed regardless of strangler fig timeline.

### Recommendation

If v0.11.0 is within 1-2 sprints, skip E4-only fixes entirely. If v0.11.0 is further out, fix IV-H7 (path traversal) as a security issue; the rest are acceptable risk in E4.

---

*Generated by COMPETE Delta pipeline. Reviewers: Alpha (Gates), Beta (Interior), Gamma (Gaps), Delta (Final).*
