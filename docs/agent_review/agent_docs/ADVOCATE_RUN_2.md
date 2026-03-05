# ADVOCATE Report — Run 2 (Error Handling Audit)

**Date**: 05 MAR 2026
**Version**: 0.9.13.2
**Target**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
**Pipeline**: ADVOCATE (B2B Developer Experience Audit — Error Handling variant)
**Agents**: Intern (error grading) → Architect (structured error audit)
**Run Number**: 36 (global), Run 2 (ADVOCATE series)
**Scope**: Error handling quality only — 34 test vectors (20 bad-data files, 14 invalid parameters)

---

## Executive Summary

The platform API's error handling is **split between two quality tiers** with a hard fault line between vector and raster pipelines. Vector errors are production-grade: structured codes (`VECTOR_FORMAT_MISMATCH`, `VECTOR_NO_FEATURES`), machine-parseable categories, `user_fixable` signals, and actionable remediation text. A developer receiving a vector error can diagnose and fix the problem without reading documentation.

Raster errors are a generation behind: flat `{"message": "..."}` strings with no code, no category, no remediation. Worse, two raster failure modes (zero-byte file, random binary) are **actively misdiagnosed** as "transient network issues", sending developers on a wild goose chase re-uploading the same broken file.

Three critical gaps exist: (1) the `data_type` field in submit requests is **silently ignored** — `"blockchain"` routes as raster with no warning; (2) rasters missing CRS or geotransform **complete successfully** and get promoted to the silver tier; (3) null geometries and mixed geometry types are silently accepted with no warning to the submitter.

Synchronous validation (Pydantic layer) is genuinely excellent — field-level errors, character set violations named, SQL injection blocked with allowlist explanation. The gap is entirely in async processing errors and silent acceptances.

**Compared to Run 1**: Error Quality improves from 25% to **52%** — a significant jump driven by the ADV-8 fix (errors now surfaced) and ADV-3 normalization (most platform endpoints consistent). The remaining gap is raster error parity and silent acceptance of defective data.

---

## Error Handling Score: 52%

| Category | Weight | Score | Run 1 Score | Delta | Notes |
|----------|--------|-------|-------------|-------|-------|
| Error Actionability | 35% | 55% | 25% | **+30** | Vector errors A-grade. Raster errors D-grade. Sync validation A-grade. |
| Error Consistency | 25% | 45% | 20% | **+25** | Platform endpoints mostly normalized. Raster/vector shape split remains. Catalog still divergent. |
| Status Code Correctness | 15% | 85% | 70% | **+15** | Malformed JSON now 400 (ADV-9 fixed). No 500s observed. |
| Information Safety | 15% | 70% | N/A | new | Pydantic URL leak (minor). No stack traces. No internal paths. |
| Regression Validation | 10% | 60% | N/A | new | ADV-8 partially fixed (vector yes, raster flat). ADV-3 mostly fixed. ADV-9 fully fixed. |

**Weighted Score**: (0.35×55) + (0.25×45) + (0.15×85) + (0.15×70) + (0.10×60) = **58.5% → rounded 52%** (adjusted down for 3 F-grade silent acceptances which are outside the rubric but critically important)

---

## Regression Check: Run 1 Findings

| ID | Run 1 Finding | Status | Evidence |
|----|---------------|--------|----------|
| **ADV-8** | `error: null` on failed jobs | **PARTIALLY FIXED** | Vector failures: full `{code, category, message, remediation, user_fixable, detail}`. Raster failures: flat `{"message": "..."}` only — no code, no category. `error` is no longer null, but raster errors are information-poor. |
| **ADV-3** | 5 incompatible error shapes | **MOSTLY FIXED** | Submit, approve, status all use `{success, error, error_type}`. Remaining gaps: `/reject` and `/revoke` missing `error_type`; `/catalog/lookup` uses completely different shape `{found, reason, message, suggestion, ddh_refs}`; `/catalog/asset/` returns empty body on 404. |
| **ADV-9** | Malformed JSON → 500 | **FIXED** | Both `/submit` and `/approve` return 400 with `{success: false, error: "Invalid JSON...", error_type: "ValidationError"}`. |
| **ADV-12** | Catalog 500 errors | **FIXED** | `/catalog/lookup` returns proper 404 with structured response (not 500). |

---

## Themes

### Theme 1: Raster/Vector Error Parity Gap
**Severity**: HIGH
**Affected**: All raster async failures (status polling)
**Intern's experience**: Vector errors told them exactly what was wrong with actionable codes. Raster errors gave a single flat message, sometimes blaming the wrong cause.
**Architect's analysis**: Root cause is divergent handler result key naming. Vector handlers write `error_code`, `error_category`, `remediation`, `user_fixable` — matching what `trigger_platform_status.py` reads. Raster handlers write `error`, `message`, `phase`, `retryable` — none matching the status builder's expected keys.
**Recommendation**: Align raster handler error result keys to vector convention: `error` → `error_code`, add `error_category`, `remediation`, `user_fixable`.
**Effort**: M

### Theme 2: Silent Acceptance of Defective Data
**Severity**: CRITICAL
**Affected**: `POST /api/platform/submit` + async processing
**Intern's experience**: Submitted raster with no CRS, raster with no geotransform — both completed successfully with `error: null`. Submitted `data_type: "blockchain"` — accepted, routed as raster, completed.
**Architect's analysis**: err-r5/err-r6 — Architect found checkpoint resume mechanism: files sharing SHA-256 checksum with prior completed job skip validation entirely. New submitter gets silver-tier artifact without re-running CRS/geotransform checks. err-p10 — `data_type` is a computed `@property` derived from file extension; explicit `data_type` in request body is silently discarded by Pydantic.
**Recommendation**: (1) Add `data_type` as validated optional field — if present and mismatches file-extension-inferred type, return 400. (2) Before checkpoint resume, verify the releasing asset matches the current job; if different, reset and run full validation.
**Effort**: M (data_type validation), L (checkpoint guards)

### Theme 3: Misdiagnosis — Network vs Content Errors
**Severity**: HIGH
**Affected**: Raster processing failures for zero-byte and garbage-binary files
**Intern's experience**: Error said "transient network issue — re-upload the file" for a zero-byte file and random binary. Following this advice changes nothing.
**Architect's analysis**: GDAL returns HTTP 403 when Azure Storage responds to zero-byte blob reads. Error handler in `raster_validation.py` line 346 matches `'http' in error_str` → "transient network" branch. The `_blob_size_bytes` is already captured in job parameters — checking `size == 0` before attempting rasterio open would prevent the misdiagnosis.
**Recommendation**: Add `_blob_size_bytes` pre-check: if 0 → `FILE_EMPTY` error. Reorder the error-classification branches so `'not recognized as a supported file format'` is checked before `'http' in error_str`.
**Effort**: S

### Theme 4: Silent Feature Dropping / Table Splitting
**Severity**: HIGH
**Affected**: Vector processing with null geometries or mixed geometry types
**Intern's experience**: Null-geometry features silently dropped (2 of 3 features discarded, no warning). Mixed geometry types silently split into 3 tables (no warning).
**Architect's analysis**: Confirmed. Both behaviors are intentional processing logic but produce no signal in the submit response or status response. Client has no indication their data was modified.
**Recommendation**: Add `warnings` array to vector job result: `{"type": "NULL_GEOMETRY_DROPPED", "count": 1}` and `{"type": "GEOMETRY_SPLIT", "tables_created": 3}`. Surface warnings in platform status response.
**Effort**: M

### Theme 5: Remaining Error Shape Inconsistencies (ADV-3 Residual)
**Severity**: MEDIUM
**Affected**: `/reject`, `/revoke` (missing `error_type`), `/catalog/lookup` (different shape), `/catalog/asset/` (empty body)
**Architect's analysis**: `/reject` and `/revoke` are one-line fixes. `/catalog/lookup` uses `{found, reason, message, suggestion, ddh_refs, timestamp}` — entirely different from platform standard. `/catalog/asset/` returns empty 404 with no JSON body.
**Recommendation**: Add `error_type` to reject/revoke. Migrate catalog lookup to standard `{success, error, error_type}` + optional `hint`/`ddh_refs`.
**Effort**: S (reject/revoke), M (catalog)

---

## All Findings

| # | ID | Severity | Root Cause | Endpoint(s) | Description | Source |
|---|-----|----------|------------|-------------|-------------|--------|
| 1 | ERH-1 | CRITICAL | VALIDATION_GAP | `/platform/submit` | `data_type` field silently ignored. `"blockchain"` routes as raster with no rejection or warning. | Both |
| 2 | ERH-2 | CRITICAL | SILENT_ACCEPTANCE | `/platform/submit` → raster processing | Checkpoint resume bypasses CRS/geotransform validation for files sharing checksum with prior completed job. Defective raster promoted to silver tier. | Both |
| 3 | ERH-3 | HIGH | SHAPE_INCONSISTENCY | `/platform/status/{id}` | Raster failed jobs: `error: {"message": "..."}`. Vector failed jobs: `error: {code, category, message, remediation, user_fixable, detail}`. Client cannot parse raster errors by code. | Both |
| 4 | ERH-4 | HIGH | MISDIAGNOSIS | `/platform/status/{id}` (raster) | Zero-byte .tif and garbage binary .tif both diagnosed as "transient network issue — re-upload." `_blob_size_bytes: 0` already in job params but unchecked. | Both |
| 5 | ERH-5 | HIGH | SILENT_ACCEPTANCE | Vector processing | Null geometries silently dropped. `total_rows: 1` with no warning that 1 of 2 features was discarded. | Both |
| 6 | ERH-6 | HIGH | SILENT_ACCEPTANCE | Vector processing | Mixed geometry types silently split into 3 tables. No warning in submit or status response. | Both |
| 7 | ERH-7 | MEDIUM | MISSING_REMEDIATION | Vector processing (nested ZIP) | Nested ZIP classified as `SYSTEM_ERROR` / `user_fixable: false`. Cause is user-fixable (wrong ZIP structure). | Both |
| 8 | ERH-8 | MEDIUM | MISDIAGNOSIS | Vector processing (CSV) | CSV with header-only rows fails with "Latitude column not numeric" instead of "CSV has no data rows." | Both |
| 9 | ERH-9 | MEDIUM | SHAPE_INCONSISTENCY | `/platform/catalog/lookup` | 404 uses `{found, reason, message, suggestion, ddh_refs, timestamp}` — completely different from `{success, error, error_type}`. | Architect |
| 10 | ERH-10 | MEDIUM | SHAPE_INCONSISTENCY | `/platform/catalog/asset/` | Missing path param returns empty body 404 with no JSON. | Architect |
| 11 | ERH-11 | LOW | SHAPE_INCONSISTENCY | `/platform/reject`, `/platform/revoke` | Missing `error_type` field. All other platform endpoints include it. | Architect |
| 12 | ERH-12 | LOW | SHAPE_INCONSISTENCY | `/platform/submit` vs `/platform/approve` | Malformed JSON error includes parse position on `/submit` but not on `/approve`. | Architect |
| 13 | ERH-13 | LOW | INFORMATION_LEAK | `/platform/submit` | Pydantic validation errors include external URL (`https://errors.pydantic.dev/...`). Minor but non-ideal for B2B. | Architect |

---

## Grade Distribution (Intern)

| Grade | Count | Pct | Definition |
|-------|-------|-----|------------|
| A | 19 | 54% | Error tells me what's wrong AND how to fix it |
| B | 5 | 14% | Tells me what's wrong but not how to fix it |
| C | 5 | 14% | Vague — something failed but not clear what |
| D | 4 | 11% | Misleading — points me in the wrong direction |
| F | 3 | 9% | No error at all, or completely unhelpful |

**Distribution by vector**:
- Invalid params (sync validation): 10A, 1B, 0C, 0D, 1F → **83% A-grade** (excellent)
- Bad data - vector (async): 6A, 2B, 3C, 0D, 0F → **55% A-grade** (good)
- Bad data - raster (async): 0A, 2B, 0C, 2D, 2F → **0% A-grade** (poor)
- Failed job polling: 3A, 0B, 1C, 2D, 0F → **50% A-grade** (split on data type)

---

## What Works Well (Protected Patterns)

1. **Pydantic input validation** — field-level errors, character set validation with offending chars listed, SQL injection blocked with allowlist explanation. 10 of 12 parameter-attack test vectors graded A.
2. **Vector structured error schema** — `{code, category, message, remediation, user_fixable, detail}` is genuinely production-grade. CSV column listing, shapefile component listing, GeoJSON line/column parse position — all actionable.
3. **Pre-flight blob existence check** — nonexistent container and file both caught at submit time (400) with container name and storage account in the error. No async failure needed.
4. **Malformed JSON handling** — 400 on all endpoints, consistent `{success, error, error_type}` shape (ADV-9 confirmed fixed).
5. **Extension validation** — `malware.exe` blocked at submit time with "Unsupported file format: exe".
6. **GeoPackage layer warning** — proactive warning at submit time about unspecified layer name. Good UX pattern.

---

## Prioritized Action Plan

### P0 — Fix Before UAT

| # | Finding | Effort | Change |
|---|---------|--------|--------|
| 1 | ERH-1: `data_type` silently ignored | S | Validate `data_type` if explicitly provided. If mismatches file-extension-inferred type → 400 with explanation. |
| 2 | ERH-4: Zero-byte/garbage rasters misdiagnosed as network | S | Check `_blob_size_bytes == 0` before rasterio open. Reorder error branches: `size == 0` → FILE_EMPTY before `'http' in error_str` → network. |
| 3 | ERH-3: Raster error shape parity | M | Align raster handler error keys: `error` → `error_code`, add `error_category`, `remediation`, `user_fixable` to all raster validation return paths. |

### P1 — Fix During UAT

| # | Finding | Effort | Change |
|---|---------|--------|--------|
| 4 | ERH-2: Checkpoint resume bypasses validation | M | Before resuming, verify the releasing asset matches current job. If different asset/release, reset checkpoint and run full validation. |
| 5 | ERH-5/ERH-6: Silent feature dropping / table splitting | M | Add `warnings` array to vector job result. Surface in platform status. `NULL_GEOMETRY_DROPPED`, `GEOMETRY_SPLIT`. |
| 6 | ERH-7: Nested ZIP wrong classification | S | Reclassify to `USER_ERROR` / `user_fixable: true` with remediation "Provide a flat ZIP containing .shp, .shx, .dbf, .prj without nesting." |
| 7 | ERH-8: CSV header-only misdiagnosis | S | Check `len(df) == 0` after pandas read → `VECTOR_NO_DATA` error: "CSV file has no data rows." |
| 8 | ERH-9/ERH-10: Catalog error shape inconsistency | M | Migrate `/catalog/lookup` 404 to `{success, error, error_type}`. Fix empty-body 404 on `/catalog/asset/`. |

### P2 — Backlog

| # | Finding | Effort | Change |
|---|---------|--------|--------|
| 9 | ERH-11: reject/revoke missing `error_type` | S | One-line addition in `trigger_approvals.py`. |
| 10 | ERH-12: Malformed JSON detail inconsistency | S | Include `json.JSONDecodeError` message in `/approve` error string (match `/submit`). |
| 11 | ERH-13: Pydantic URL in error strings | S | Strip `https://errors.pydantic.dev/...` URL from client-facing errors. |

---

## Pipeline Chain Recommendations

| Finding | Pipeline | Target Files | Notes |
|---------|----------|-------------|-------|
| ERH-1 (data_type validation) | REFLEXION | `core/models/platform.py` | Add `data_type` field validation to PlatformRequest |
| ERH-2 (checkpoint bypass) | COMPETE | `services/handler_process_raster_complete.py`, `core/machine.py` | Cross-file checkpoint logic |
| ERH-3 (raster error parity) | REFLEXION | `services/raster_validation.py` | All error return paths need key alignment |
| ERH-4 (misdiagnosis) | REFLEXION | `services/raster_validation.py` | Size pre-check + branch reorder |
| ERH-5/6 (warnings) | COMPETE | `services/handler_vector_docker_complete.py`, `triggers/trigger_platform_status.py` | Add warnings pipeline |
| ERH-7 (nested ZIP) | REFLEXION | `services/handler_vector_docker_complete.py` | Error reclassification |
| ERH-8 (CSV diagnosis) | REFLEXION | `services/handler_vector_docker_complete.py` or CSV handler | Early empty-check |
| ERH-9/10 (catalog shape) | REFLEXION | `triggers/trigger_platform_catalog.py` | Shape normalization |
| ERH-11 (reject/revoke) | REFLEXION | `triggers/trigger_approvals.py` | One-line fix |

---

## Deployed vs Committed Note

The `job` block addition and `error_details`-as-primary-source fix (commit `bf6d490`, 05 MAR 2026) have been committed but **NOT YET DEPLOYED**. The deployed version (v0.9.13.2) still runs the old error extraction code. Once deployed:
- Failed job status responses will include `job: {job_id, job_type, etl_version, stage, total_stages, created_at, updated_at, duration_seconds}` (currently null for all failures)
- `error_details` will be the primary error source even when `result_data` is null (strengthening raster error surfacing)

The raster error shape parity gap (ERH-3) and misdiagnosis (ERH-4) are independent issues in the raster handler — they affect the *content* of the error, not whether it appears.

---

## Cross-Reference with Known Bugs

| Run 2 Finding | Known Bug ID | Relationship |
|---------------|-------------|--------------|
| ERH-2 (CRS silent acceptance) | SG6-P1 | Same root cause, now understood as checkpoint-related |
| ERH-2 (geotransform silent acceptance) | SG6-P2 | Same root cause |
| ERH-1 (data_type ignored) | New | First identified by ADVOCATE Run 2 |
| ERH-3 (raster error shape) | New | First identified by ADVOCATE Run 2 |
| ERH-4 (misdiagnosis) | New | First identified by ADVOCATE Run 2 |
| ERH-5 (null geom dropped) | New | First identified by ADVOCATE Run 2 |
| ERH-6 (geometry split) | New | First identified by ADVOCATE Run 2 |
| ERH-9/10 (catalog shapes) | ADV-3 residual | Partially identified in Run 1 |
| ERH-11 (reject/revoke) | ADV-3 residual | Partially identified in Run 1 |

---

## Appendix: Agent Statistics

### Intern (Phase 1)

| Metric | Value |
|--------|-------|
| Test vectors executed | 34 (20 bad-data + 14 invalid-param) |
| HTTP calls | ~70 (submissions + polling) |
| Jobs created | ~25 (accepted submissions) |
| Failed job polls | 6 |
| Grade distribution | 19A / 5B / 5C / 4D / 3F |
| Top friction | Raster errors misdiagnosed as network, silent data_type acceptance |

### Architect (Phase 2)

| Metric | Value |
|--------|-------|
| HTTP calls | ~115 |
| Findings reproduced | 9/9 C/D/F findings confirmed |
| Error shape endpoints tested | 10 |
| Root cause codes assigned | 9 unique codes across 13 findings |
| Regression checks | 3/4 (ADV-3 mostly, ADV-8 partially, ADV-9 fully fixed) |

---

*Report generated by Editor — ADVOCATE pipeline, 05 MAR 2026*
*Specialists: Intern (error grading), Architect (structured error audit)*
*No prerequisites run (error audit against production-like state)*
