# ADVOCATE Run 2 — Campaign Brief: Error Handling Audit

**Date**: 05 MAR 2026
**Version**: 0.9.13.2+
**Target**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
**Pipeline**: ADVOCATE (variant — narrow scope)
**Scope**: Error handling quality ONLY
**Prior Run**: ADVOCATE Run 1 (Run 31, 03 MAR 2026) — Error Quality scored 25%, Error Format graded F

---

## Objective

Evaluate error handling quality from the B2B developer perspective. Run 1 identified error handling as the weakest dimension (25% score, F grade). Since then:

- **FIXED (v0.9.13.2)**: `error: null` on failed jobs (ADV-8) — `error_details` now primary source, job metadata promoted to default response
- **FIXED (v0.9.13.0)**: ADV-3 partially addressed — platform error shapes normalized to `{success, error, error_type}`
- **FIXED (v0.9.11.11)**: ADV-9 — malformed JSON no longer returns 500

This run validates those fixes and probes deeper: **Can a developer diagnose and fix their problem from the error response alone?**

---

## Scope Boundaries

| In Scope | Out of Scope |
|----------|-------------|
| Submit with bad data (corrupt files, missing files) | Success-path lifecycle |
| Submit with invalid parameters (injection, nulls, overflow) | Approval/revoke/unpublish workflows |
| Poll status of failed jobs | TiTiler service URL audit |
| Error shape consistency across endpoints | Pagination, filtering, caching |
| HTTP status code correctness (400 vs 422 vs 500) | Response bloat, naming conventions |
| Error actionability (can developer self-fix?) | Discoverability, HATEOAS |

---

## Test Data Inventory

### Vector 1: Bad Data Files (wargames/bad-data/)

Submit real corrupt files and verify errors are descriptive. All files exist in `wargames` container under `bad-data/` prefix.

| Test ID | File | Corruption Type | Expected Behavior |
|---------|------|-----------------|-------------------|
| ERR-R1 | `bad-data/raster_truncated.tif` | First 1KB of valid TIFF | Error names the problem (truncated/corrupt), not a stack trace |
| ERR-R2 | `bad-data/raster_empty.tif` | Zero-byte .tif | Error says "empty file" or "zero bytes", HTTP 400 or fail with clear message |
| ERR-R3 | `bad-data/raster_garbage.tif` | 100KB random binary, .tif extension | Error says "not a valid raster" or "GDAL cannot open" |
| ERR-R4 | `bad-data/raster_corrupt_header.tif` | Valid TIFF magic bytes, garbage IFD | Error distinguishes from ERR-R3 (recognized format, corrupt content) |
| ERR-R5 | `bad-data/raster_no_crs.tif` | Valid pixels, no CRS | Error or warning about missing CRS (known bug SG6-P1) |
| ERR-R6 | `bad-data/raster_no_geo.tif` | Valid pixels, no geotransform or CRS | Error about missing spatial reference (known bug SG6-P2) |
| ERR-V1 | `bad-data/vector_truncated.geojson` | First 500 bytes of valid GeoJSON | Error says "JSON parse error" or "truncated" |
| ERR-V2 | `bad-data/vector_empty_file.geojson` | Zero-byte .geojson | Error says "empty file" |
| ERR-V3 | `bad-data/vector_empty.geojson` | Valid JSON, zero features | Error says "no features" or "empty dataset" |
| ERR-V4 | `bad-data/vector_null_geom.geojson` | 2 null geometry + 1 valid | How does it handle partial invalidity? |
| ERR-V5 | `bad-data/vector_html_disguised.geojson` | HTML 404 page, .geojson ext | Error says "not valid GeoJSON" |
| ERR-V6 | `bad-data/vector_mixed_geom.geojson` | Point + Line + Polygon mixed | Error or graceful handling? |
| ERR-A1 | `bad-data/shapefile_incomplete.zip` | Missing .dbf and .prj | Error names missing components |
| ERR-A2 | `bad-data/shapefile_two_layers.zip` | Two shapefiles in one zip | Error says "ambiguous" or picks one with warning |
| ERR-A3 | `bad-data/shapefile_nested_zip.zip` | Zip inside a zip | Error about nested archive |
| ERR-A4 | `bad-data/vector_empty_table.gpkg` | Valid GeoPackage, 0 rows | Error says "no features" or "empty table" |
| ERR-C1 | `bad-data/csv_wrong_columns.csv` | x_coord/y_coord instead of lat/lon | Error names expected columns vs found columns |
| ERR-C2 | `bad-data/csv_invalid_coords.csv` | lat=999, lon=-999 | Error about coordinate range |
| ERR-C3 | `bad-data/csv_header_only.csv` | Header row, zero data rows | Error says "no data rows" |
| ERR-K1 | `bad-data/kml_empty.kml` | Valid KML, no placemarks | Error says "no placemarks" or "empty" |

**Submit pattern for bad data** (all use `wargames` container):
```json
{
  "dataset_id": "adv2-{test_id}",
  "resource_id": "{test_id}",
  "file_name": "{file from table}",
  "container_name": "wargames",
  "data_type": "{raster|vector depending on file}"
}
```

CSV submissions MUST include `processing_options`:
```json
{
  "dataset_id": "adv2-err-c1",
  "resource_id": "err-c1",
  "file_name": "bad-data/csv_wrong_columns.csv",
  "container_name": "wargames",
  "data_type": "vector",
  "processing_options": {
    "lat_column": "latitude",
    "lon_column": "longitude"
  }
}
```

### Vector 2: Invalid Parameters

Submit with structurally invalid request bodies. No files involved — these should fail at validation before processing starts.

| Test ID | Attack | Payload | Expected |
|---------|--------|---------|----------|
| ERR-P1 | Missing required field | `{"dataset_id": "adv2-p1", "resource_id": "p1"}` (no file_name, no container_name) | 400/422 with field names listed |
| ERR-P2 | Null values | `{"dataset_id": null, "resource_id": null, "file_name": null, "container_name": null}` | 400/422 naming null fields |
| ERR-P3 | Empty strings | `{"dataset_id": "", "resource_id": "", "file_name": "", "container_name": ""}` | 400 — "field cannot be empty" |
| ERR-P4 | Path traversal | `{"dataset_id": "adv2-p4", "resource_id": "p4", "file_name": "../../etc/passwd", "container_name": "rmhazuregeobronze"}` | 400 or sanitized, no path leakage |
| ERR-P5 | SQL injection | `{"dataset_id": "'; DROP TABLE app.jobs;--", "resource_id": "injection", "file_name": "dctest.tif", "container_name": "rmhazuregeobronze"}` | 400 or safe handling, no 500 |
| ERR-P6 | Nonexistent container | `{"dataset_id": "adv2-p6", "resource_id": "p6", "file_name": "dctest.tif", "container_name": "container-that-does-not-exist"}` | Error names the container, not a connection timeout |
| ERR-P7 | Nonexistent file | `{"dataset_id": "adv2-p7", "resource_id": "p7", "file_name": "this_file_does_not_exist.tif", "container_name": "rmhazuregeobronze"}` | Error names the file, not a generic blob error |
| ERR-P8 | Unicode identifiers | `{"dataset_id": "adv2-p8", "resource_id": "emoji🚀", "file_name": "dctest.tif", "container_name": "rmhazuregeobronze"}` | 400 or sanitized |
| ERR-P9 | Overflow identifier | `{"dataset_id": "adv2-" + "a"*300, ...}` | 400 — "identifier too long" |
| ERR-P10 | Invalid data_type enum | `{"dataset_id": "adv2-p10", ..., "data_type": "blockchain"}` | 400 — lists valid enum values |
| ERR-P11 | Malformed JSON | `{not json at all}` | 400 — "invalid JSON", not 500 |
| ERR-P12 | Empty body | (empty POST) | 400 — "request body required" |
| ERR-P13 | Wrong content-type | POST with `text/plain` body | 400 or ignored gracefully |
| ERR-P14 | Unsupported extension | `{"...", "file_name": "malware.exe", ...}` | 400 — lists supported extensions |

### Vector 3: Failed Job Status Polling (Validates ADV-8 Fix)

For any bad-data submission that gets accepted (returns 202 with request_id), poll status to verify:

1. `error.message` is populated (not null)
2. `error.message` is actionable (developer can understand what went wrong)
3. `job` block is populated with `job_id`, `job_type`, `stage`, `duration_seconds`
4. No stack traces or internal class names leak into `error.message`

```bash
# After submitting bad data:
GET /api/platform/status/{request_id}

# Expected (v0.9.13.2+):
{
  "job_status": "failed",
  "error": {
    "message": "Queue processing error: ..."  // <-- must NOT be null
  },
  "job": {
    "job_id": "...",
    "job_type": "...",
    "stage": 1,
    "duration_seconds": 0.74
  }
}
```

---

## Agent Briefs

### Intern Brief (Phase 1)

```
You are a junior developer trying to integrate with a geospatial data platform.
Your task today is DIFFERENT from normal integration — you are testing what happens
when things go wrong.

You have been given a list of deliberately bad files and invalid parameters.
Your job: submit each one and evaluate the error response.

For EVERY submission, record:

1. What you sent (test ID + payload summary)
2. HTTP status code received
3. The full error response
4. GRADE the error on this scale:

   A: Error tells me exactly what's wrong AND how to fix it
   B: Error tells me what's wrong but not how to fix it
   C: Error is vague — I know something failed but not what
   D: Error is misleading — it points me in the wrong direction
   F: No error at all (null/empty) or a 500 with no useful info

5. For jobs that were accepted (202) but later failed, poll /status and grade
   the failure error the same way.

You do NOT have:
- API documentation
- Source code
- Admin endpoints

Work through ALL test vectors systematically. Bad data first, then invalid params.
```

### Architect Brief (Phase 2)

```
You are a senior API architect reviewing error handling quality.
You have the Intern's error grading log as your investigation queue.

Your job:

Phase A — Replay and Classify
For each error the Intern graded C or below:
1. Reproduce it
2. Classify the root cause:
   - VALIDATION_GAP: Input should have been rejected at the gate
   - ERROR_SWALLOWED: Error occurred but response lost the detail
   - WRONG_STATUS_CODE: HTTP code doesn't match the error type
   - SHAPE_INCONSISTENCY: Error response shape differs from other endpoints
   - INFORMATION_LEAK: Stack trace, internal path, or class name exposed
   - MISSING_REMEDIATION: Error identified problem but gave no fix guidance

Phase B — Error Shape Consistency Matrix
Compare error response shapes across:
- /submit validation errors (missing field, bad type, bad value)
- /submit with nonexistent file/container (async failures)
- /status of failed jobs (the error block)
- /approve with invalid payload
- /reject with invalid payload
- /revoke with invalid payload

For each: document the exact JSON shape. Flag inconsistencies.

Phase C — Error Actionability Scorecard
For each error category (validation, file-not-found, corrupt-file, auth/token,
container-not-found), evaluate:
1. Does the error NAME the problem? (not just "error occurred")
2. Does the error LOCATE the problem? (which field, which file, which stage)
3. Does the error SUGGEST a fix? (remediation text)
4. Is the error MACHINE-PARSEABLE? (consistent code/category fields)

Phase D — Regression Check
Specifically verify these prior findings:
- ADV-8: error: null on failed jobs → should now show error.message + job block
- ADV-3: error shape consistency → platform endpoints should all use {success, error, error_type}
- ADV-9: malformed JSON → should return 400, not 500
```

### Editor Scoring (Phase 3)

Narrowed rubric for error-focused run:

| Category | Weight | What It Measures |
|----------|--------|------------------|
| Error Actionability | 35% | Can the developer fix the problem from the error alone? |
| Error Consistency | 25% | Same error shape across all endpoints and failure types? |
| Status Code Correctness | 15% | 400 vs 422 vs 500 — right code for the right failure? |
| Information Safety | 15% | No stack traces, internal paths, or class names leaked? |
| Regression Validation | 10% | ADV-3, ADV-8, ADV-9 fixes confirmed? |

---

## Prerequisites

```bash
BASE_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

# NO schema rebuild needed — we're testing error paths, not success paths.
# Existing state is fine.

# Health check
curl -sf "${BASE_URL}/api/platform/health"

# Verify bad-data files exist in wargames container
curl "${BASE_URL}/api/storage/wargames/blobs?zone=bronze&prefix=bad-data/&limit=50"
```

**Important**: Do NOT rebuild schema or nuke STAC. This run tests error handling against the current production-like state. Failed submissions should not corrupt anything.

---

## Expected Outputs

1. **Intern Error Grading Log** — every test vector graded A-F with full response
2. **Architect Error Audit** — root cause classification, consistency matrix, actionability scorecard
3. **Editor Synthesis** — `ADVOCATE_RUN_2.md` with:
   - Error Handling Score (compare to Run 1's 25%)
   - Regression validation (ADV-3, ADV-8, ADV-9)
   - New findings from bad-data and invalid-param vectors
   - Prioritized fix list for remaining error gaps

---

## Cross-Reference: Run 1 Error Findings

These findings from Run 1 are directly in scope for regression testing:

| ID | Run 1 Description | Status at Run 2 Start | What to Verify |
|----|--------------------|-----------------------|----------------|
| ADV-3 | 5 incompatible error shapes | PARTIALLY FIXED (v0.9.13.0) — platform normalized | All platform errors use `{success, error, error_type}` |
| ADV-8 | `error: null` on failed jobs | FIXED (v0.9.13.2) — error_details + job block | `error.message` populated, `job` block present |
| ADV-9 | Malformed JSON returns 500 | FIXED (v0.9.11.11) | POST with invalid JSON returns 400 |
| ADV-12 | Catalog 500 errors | FIXED (v0.9.13.0) — cursor fix | `/catalog/lookup` and `/catalog/dataset` no longer 500 |

---

## Token Estimate

| Agent | Estimated Tokens | Notes |
|-------|-----------------|-------|
| Dispatcher | ~1K | Verify bad-data files exist, namespace setup |
| Intern | ~50-70K | 34 test vectors × HTTP calls + polling failed jobs |
| Architect | ~40-50K | Replay C/D/F grades + consistency matrix |
| Editor | ~5K | Synthesis |
| **Total** | **~100-130K** | Comparable to Run 1 (error path calls are cheaper than lifecycle) |

---

*Campaign brief prepared 05 MAR 2026 — ADVOCATE Run 2 (Error Handling Audit)*
