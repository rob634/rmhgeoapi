# Consolidated Pending Items

**Last Updated**: 28 FEB 2026
**Source**: Runs 8, 9, 10 from AGENT_RUNS.md (all other runs are complete)

---

## Run 8: VirtualiZarr Pipeline (Greensight) — MUST-FIX COMPLETE

Code committed (`ad3b8bd`) but Validator flagged 11 items before ship-ready.

### Must-Fix (5 items — ALL RESOLVED)

| # | Issue | Files | Status |
|---|-------|-------|--------|
| V-1 | Hardcoded `rmhazuregeosilver` container name — should use config | `jobs/virtualzarr.py`, `services/handler_virtualzarr.py` | RESOLVED (prior commit) |
| V-2 | Auth inconsistency — scan uses `DefaultAzureCredential`, validate/combine use bare fsspec | `services/handler_virtualzarr.py` | RESOLVED — auth already routed through BlobRepository; added clarifying comment, removed redundant import |
| V-3 | `to_kerchunk()` export likely fails without `storage_options` for writing to blob | `services/handler_virtualzarr.py` (combine handler) | RESOLVED — verified: `open_virtual_dataset()` calls pass `storage_options` via `reader_options`; `to_kerchunk()` correctly writes to local temp file |
| V-4 | Fragile manifest URL reconstruction in Stage 3 — should pass URL from Stage 1 result | `jobs/virtualzarr.py` | RESOLVED (prior commit) |
| V-5 | `max_files` limit mismatch (10000 in schema vs 5000 in handler) | `jobs/virtualzarr.py` | RESOLVED (prior commit) |

### Should-Fix (6 items — ALL RESOLVED)

| # | Issue | Status |
|---|-------|--------|
| V-6 | Add recursive scan option or document limitation | RESOLVED — not an issue; Azure SDK `list_blobs()` recurses by default. Added comment. |
| V-7 | Validate `source_url` starts with `abfs://` at submit time | RESOLVED — added `validate_job_parameters` override in `VirtualZarrJob` |
| V-8 | Consolidate duplicate `_get_silver_netcdf_container()` helpers | RESOLVED — removed from handler, imports from `jobs/virtualzarr.py` |
| V-9 | Fix or remove validation read in combine handler (reads full data unnecessarily) | RESOLVED — not an issue; already uses in-memory `ref_dict`, no blob re-read |
| V-10 | Update stale docstring on `normalize_data_type` | RESOLVED — added recognized variant forms to docstring |
| V-11 | Normalize enum comparison pattern in submit trigger | RESOLVED — not a bug; strings are correct. Added clarifying comment. |

### Pre-Ship Tasks

| # | Task | Effort |
|---|------|--------|
| V-T1 | Docker dependency verification (`virtualizarr`, `kerchunk`, `h5py` in image with `numpy<2`) | Medium |
| V-T2 | Write tests for 4 handlers (scan, validate, combine, register) | Medium |
| V-T3 | Optional: Chain to Adversarial Review for implementation-level review | Large |

---

## Run 9: Unpublish Subsystem (COMPETE) — ALL FIXES APPLIED

2 CRITICAL fixes applied inline. 3 HIGH fixes applied 28 FEB 2026.

### Fixes Applied (28 FEB 2026)

| # | Sev | Issue | Status |
|---|-----|-------|--------|
| U-3 | HIGH | `stac_item_snapshot` not passed to Stage 3 — raster audit `artifacts_deleted` always empty | APPLIED — added `"stac_item_snapshot": stac_item` to Stage 3 params in `jobs/unpublish_raster.py` |
| U-4 | HIGH | Vector unpublish missing retry support — failed jobs can never be retried | APPLIED — copied retry pattern from raster to `_execute_vector_unpublish` in `triggers/platform/unpublish.py` |
| U-5 | HIGH | Validator `_stac_original_job_id` uses wrong property names (`processing:job_id` instead of `geoetl:job_id`) — always returns None | APPLIED — added `geoetl:job_id` as primary lookup in `infrastructure/validators.py` |

### Applied Fixes (for reference)

| # | Sev | Issue | Status |
|---|-----|-------|--------|
| U-1 | CRITICAL | Zero-task Stage 2 causes permanent job hang in CoreMachine | APPLIED |
| U-2 | CRITICAL | Release revocation before job submission has no compensating transaction | APPLIED |

---

## Run 10: Zarr Unpublish (Greenfield) — DEPLOYED

Code complete, V fixes applied. Deployment complete.

### Deployment Steps (ordered)

| # | Step | Status |
|---|------|--------|
| Z-1 | Database migration: `ALTER TYPE app.unpublish_type ADD VALUE 'zarr'` (must run outside transaction) | DONE — verified 28 FEB 2026 |
| Z-2 | Code deployment (ACR build + container restart) | DONE |
| Z-3 | `action=ensure` for any new columns | DONE — verified 28 FEB 2026 |

### Deferred Items (V2, not blocking)

| ID | Item | Trigger to Revisit |
|----|------|-------------------|
| ZD-1 | Failed forward pipeline cleanup | Storage costs become material |
| ZD-2 | Collection-level zarr unpublish | Multi-item zarr collections needed |
| ZD-3 | Concurrent unpublish + forward guard | Race condition observed in production |
| ZD-4 | Deep dry-run with full inventory | User request |
| ZD-5 | TiTiler-xarray cache invalidation | TiTiler-xarray deployed |

---

## Cross-Cutting Tech Debt (from Runs 1-6, accepted risks)

These are not blocking any run but were identified across the COMPETE reviews as longer-term work.

| Theme | Affected Subsystem | Effort | Priority |
|-------|-------------------|--------|----------|
| Tiled workflow consolidation (H-2) — two duplicate ~500-line workflows | Tiled Raster | Large (multi-day) | Medium |
| `prepare_gdf()` God method (H-5) — 700+ lines, 15+ concerns | Vector | Large (multi-day) | Medium |
| Canonical `HandlerResult` contract (H-6) | Vector | Medium | Low |
| DI/Repository cleanup (C1, C9) | CoreMachine | Medium | Low |
| 812-line `process_task_message()` (C7) | CoreMachine | Large | Low |

---

## Priority Order

**Immediate (before next deploy):**
1. ~~U-3, U-4, U-5~~ — DONE (28 FEB 2026)
2. ~~V-1 through V-5~~ — DONE (V-1/V-4/V-5 prior commit; V-2/V-3 verified/cleaned 28 FEB 2026)

**Before VirtualiZarr ship:**
3. ~~V-6 through V-11~~ — DONE (28 FEB 2026)
4. V-T1 — Docker dependency verification
5. V-T2 — Handler tests

**Before Zarr Unpublish ship:**
6. Z-1 through Z-3 — Deployment sequence
