# COMPETE: ETL Input Validation & Defensive Handling

**Purpose**: Adversarial review of all ETL handlers focused on how invalid, malformed, oversized, ambiguous, or adversarial input is detected, rejected, and reported to the user. Find every path where bad data causes a timeout, silent failure, or unhelpful error instead of a fast, descriptive rejection.

**Best for**: Run after ETL handler stabilization. Targets the full handler chain from submit through load/validate/process for all three data types (raster, vector, zarr).

**Motivation**: A QA team submitted a 33MB zip containing 29 shapefiles. The platform accepted it, downloaded it, tried to process it, and timed out with no useful error. The validation existed deep in the converter but ran too late — after extraction, not before. This review finds every instance of that pattern: validation that exists but runs too late, or doesn't exist at all.

---

## Scope Split: Split E — Gate vs Interior (custom for input validation)

**Why this split**: The Dresden zip bug taught us that validation can exist but be worthless if it's in the wrong layer. Alpha inspects the **gates** (entry points, early checks, fast rejections). Beta inspects the **interior** (what happens when bad data gets past the gate — does it fail gracefully or hang?). Gamma finds the gaps where neither gate nor interior handles a case.

### Alpha — Input Gates and Early Rejection

Review every point where user-supplied data first touches the system. The question is: **can the system reject bad input BEFORE doing expensive I/O?**

Checklist for each handler's entry point:
- Are required parameters validated before any blob download or mount I/O?
- Are file format/extension checks done before streaming?
- Are archive contents scanned (zip central directory) before extraction?
- Are file size limits enforced before download?
- Are ambiguous inputs rejected (multi-layer without layer_name, multi-file archives)?
- Is the error message actionable? Does it tell the user exactly what's wrong and how to fix it?
- Does the error propagate to the platform status endpoint, or does it get swallowed?
- Are there workarounds or escape hatches that shouldn't exist? (`shp_name`, `layer_name` defaults to "first match", etc.)

**Gate inventory** (Alpha must review each):

| Gate | File | What it guards |
|------|------|---------------|
| Submit validation | `triggers/platform/submit.py` | Request body schema, file_name, container, data_type detection |
| Raster download | `services/raster/handler_download_source.py` | Blob existence, streaming errors |
| Raster validate | `services/raster/handler_validate.py` | GDAL readability, CRS, band count, dimensions |
| Raster create_cog | `services/raster/handler_create_cog.py` | COG translation failures, GDAL errors |
| Vector load_source | `services/vector/handler_load_source.py` | Format detection, mount setup, zip scan (H1-B12), blob streaming |
| Vector converters | `services/vector/converters.py` | Per-format validation: CSV columns, GPKG layers, SHP companions, KML structure, KMZ integrity |
| Vector validate_and_clean | `services/vector/handler_validate_and_clean.py` | Geometry validity, CRS, null geometries, QGIS metadata detection |
| Vector create_and_load_tables | `services/vector/handler_create_and_load_tables.py` | Table existence, overwrite guards, PostGIS load errors |
| Zarr download_to_mount | `services/zarr/handler_download_to_mount.py` | URL scheme validation, blob existence, mount write |
| Zarr validate_source | `services/zarr/handler_validate_source.py` | xarray readability, dimension detection, variable presence |
| Zarr rechunk | `services/handler_netcdf_to_zarr.py` (ingest_zarr_rechunk) | Chunk alignment, encoding compatibility |
| Zarr pyramid | `services/zarr/handler_generate_pyramid.py` | Spatial dim detection, level computation, pyramid write |
| NetCDF convert | `services/handler_netcdf_to_zarr.py` (netcdf_convert_and_pyramid) | NC open, encoding, pyramid generation |

**Alpha does NOT examine**: What happens after the gate fails (error propagation, cleanup). That's Beta's job.

---

### Beta — Interior Failure Modes and Error Propagation

Review what happens when bad data **gets past** the gates — either because a gate is missing, or because the data looks valid at the gate but fails during processing. The question is: **when processing fails, does the user get a clear error or a timeout?**

Checklist for each handler's interior:
- When a handler raises an exception, does it become a `{"success": false, "error": "..."}` response or an unhandled crash?
- Are all exception paths non-retryable when appropriate? (The janitor retries 3x by default — retrying a malformed file 3 times wastes 4 minutes before failing)
- Are timeouts handled? What happens when GDAL hangs on a corrupt raster, or pyogrio hangs on a malformed GeoJSON?
- After failure, is the mount cleaned up? Are partial PostGIS tables dropped? Are orphan blobs removed?
- Does `processing_status` transition to FAILED with a meaningful `last_error`?
- Can the user see the error via `GET /api/platform/status/{request_id}`?
- Are there silent `except Exception: pass` blocks that swallow errors?
- Are there log-only errors that should be user-facing?

**Interior failure scenarios Beta must trace**:

| Scenario | Handler chain | Expected behavior |
|----------|--------------|-------------------|
| Corrupt/truncated GeoTIFF (valid header, bad data) | download → validate → create_cog | Fail at validate with "corrupt raster" |
| GeoTIFF with no CRS (.prj missing) | download → validate | Fail at validate with "no CRS detected" |
| CSV with wrong lat/lon column names | load_source → converter | Fail at converter with "column not found" |
| GeoJSON with mixed geometry types (Point + Polygon) | load_source → validate_and_clean | Handled? Split? Error? |
| GPKG with only non-spatial tables | load_source → GPKG validator | Fail with "no spatial layers" |
| Empty file (0 bytes) | download → validate | Fail at download or validate |
| File larger than mount capacity | download (streaming) | Fail before mount full, or mount-full error? |
| NetCDF with no spatial dimensions (time series only) | validate_source | Fail with "no spatial dims detected" |
| Zarr store with unsupported compression codec | validate_source or rechunk | Fail with codec error, or hang? |
| Blob path with `../` traversal attempt | submit or download | Rejected at submit? Or resolved by blob SDK? |
| Container that doesn't exist | download | Fail with "container not found"? |
| File extension doesn't match contents (.tif that's actually a PDF) | download → validate | GDAL fails — is error descriptive? |
| Vector file with 10M+ features | load_source → create_and_load | Memory/timeout? Size guard? |
| Raster file > 2GB (exceeds mount?) | download | Mount space check? Streaming handles it? |

**Beta does NOT examine**: Whether the gate checks exist or are in the right place. That's Alpha's job.

---

### Gamma — Gaps Between Gate and Interior

Gamma receives Alpha's gate inventory and Beta's failure trace, then looks for:

1. **Missing gates**: Scenarios in Beta's failure list that have NO corresponding gate in Alpha's inventory
2. **Late gates**: Gates that exist but run after expensive I/O (the Dresden pattern — validation inside converter, after full zip extraction)
3. **Swallowed errors**: Gates that catch errors but log them instead of returning them to the user
4. **Retry waste**: Non-retryable errors that aren't marked as such (janitor retries 3x, wasting minutes)
5. **Error message gaps**: Failures that produce Python tracebacks instead of user-actionable messages
6. **Inconsistency across data types**: A validation that exists for vector but not raster, or vice versa

**Gamma's priority files** (most likely to have gaps):
- `services/vector/handler_load_source.py` — freshly hardened, compare pattern to raster/zarr
- `services/raster/handler_download_source.py` — is it as defensive as vector?
- `services/zarr/handler_download_to_mount.py` — URL scheme validation, mount handling
- `services/handler_netcdf_to_zarr.py` — monolith, likely has late validation
- `triggers/platform/submit.py` — first gate, does it catch obvious garbage?
- `services/vector/converters.py` — per-format validators, each a potential gap

---

## Target Files

### Primary (all agents review)
| # | File | Lines | Role |
|---|------|-------|------|
| 1 | `triggers/platform/submit.py` | ~500 | Submit gate — first user touchpoint |
| 2 | `services/vector/handler_load_source.py` | ~440 | Vector entry — zip scan, format routing |
| 3 | `services/vector/converters.py` | ~750 | Per-format converters — CSV, GeoJSON, GPKG, KML, KMZ, SHP |
| 4 | `services/vector/handler_validate_and_clean.py` | ~300 | Geometry validation, CRS, null checks |
| 5 | `services/raster/handler_download_source.py` | ~200 | Raster blob streaming |
| 6 | `services/raster/handler_validate.py` | ~250 | GDAL validation, band/CRS checks |
| 7 | `services/zarr/handler_download_to_mount.py` | ~200 | Zarr/NC download, URL scheme gate |
| 8 | `services/zarr/handler_validate_source.py` | ~250 | xarray open, dimension detection |
| 9 | `services/handler_netcdf_to_zarr.py` | ~1150 | NC monolith — convert + pyramid (late validation?) |

### Secondary (Gamma + Delta only)
| # | File | Lines | Role |
|---|------|-------|------|
| 10 | `services/vector/handler_create_and_load_tables.py` | ~300 | PostGIS load — table exists guard |
| 11 | `services/vector/helpers.py` | ~200 | extract_zip_file, nested zip check |
| 12 | `services/raster/handler_create_cog.py` | ~300 | GDAL translate — can hang on bad input |
| 13 | `services/zarr/handler_generate_pyramid.py` | ~250 | Pyramid generation — chunk/encoding edge cases |
| 14 | `infrastructure/etl_mount.py` | ~150 | Mount utilities — cloud source detection |

---

## Severity Classification

Findings should be classified using this rubric:

| Severity | Definition | Example |
|----------|-----------|---------|
| **CRITICAL** | Bad input causes hang/timeout with no error to user | Dresden zip: 29 shapefiles, times out |
| **HIGH** | Bad input produces wrong result silently (data corruption) | Mixed geometry types silently dropped |
| **HIGH** | Error exists but is unreachable by user (swallowed, log-only) | Exception caught, logged, returns `{"success": true}` |
| **MEDIUM** | Error message is unhelpful (Python traceback, generic "processing failed") | `"ValueError: could not convert string to float"` |
| **MEDIUM** | Validation runs after expensive I/O when it could run before | CRS check after full file load, could check .prj in zip first |
| **LOW** | Missing validation for unlikely but possible input | Zarr with exotic compression codec |
| **LOW** | Error is correct but could be more actionable | "File not found" without saying which file or container |

---

## Delta Report Format

Delta produces the final report with:

1. **Gate Coverage Matrix**: For each data type (raster, vector, zarr), list every validation check and whether it runs at submit-time, download-time, or process-time. Flag any that run too late.

2. **Missing Gate List**: Scenarios from Beta's failure trace that have no gate. Each entry: scenario, expected gate location, recommended error message.

3. **Error Propagation Audit**: For each handler, does `{"success": false, "error": "..."}` actually reach `GET /api/platform/status`? Trace the full path.

4. **Retry Classification Audit**: Which errors are marked `non-retryable`? Which should be but aren't? (Every validation error should be non-retryable.)

5. **Cross-Type Consistency**: Validation that exists for one data type but not another. E.g., "vector checks for empty file, raster doesn't."

6. **Prioritized Fix List**: Ordered by severity, with file paths and line numbers.
