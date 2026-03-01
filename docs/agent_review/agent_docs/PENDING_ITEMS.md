# Consolidated Pending Items

**Last Updated**: 01 MAR 2026
**Source**: Runs 8-17 from AGENT_RUNS.md

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

## Run 14: SG-3 Catalog Dataset 500 (REFLEXION) — ALL PATCHES APPLIED

Root cause: SQL referenced `r.table_name` removed from `asset_releases` on 26 FEB 2026.

| Patch | Sev | Fix | Status |
|-------|-----|-----|--------|
| 1 | CRITICAL | SQL subquery joins `release_tables` instead of `r.table_name` | APPLIED — `platform_catalog_service.py:868-871` |
| 2 | HIGH | Structured error handling: 404 for missing datasets, typed 500s | APPLIED — `trigger_platform_catalog.py:515-532` |

**Residual faults (deferred)**: F-3 through F-10 (8 items, MEDIUM/LOW). Not blocking.

---

## Run 15: SG-5 Blob Deletion No-Op (REFLEXION) — ALL PATCHES APPLIED

Root cause: Three-bug cascade in unpublish raster pipeline.

| Patch | Sev | Fix | Status |
|-------|-----|-----|--------|
| 1 | CRITICAL | `/vsiaz/` href parsing — new `elif` branch in `unpublish_handlers.py:152-162` | APPLIED |
| 2 | HIGH | `blobs_deleted` passthrough added to `delete_stac_and_audit` return | APPLIED — `unpublish_handlers.py:1183` |
| 3 | MEDIUM | Accurate blob count filters for `deleted: True` only | APPLIED — `unpublish_raster.py:290-293` |

**Residual risks (deferred)**:
- `unpublish_zarr.py` `finalize_job` missing `blobs_deleted` field (LOW)
- Bug C: `delete_blob` masks wrong paths via silent success (MEDIUM)
- No end-to-end integration test for raster unpublish (MEDIUM)
- Dry-run return missing `blobs_deleted` field (LOW)

---

## Run 16: SG2-2 Revoked Release Retains is_served (REFLEXION) — ALL PATCHES APPLIED

Root cause: Both revocation SQL paths missing `is_served = false`.

| Patch | Location | Fix | Status |
|-------|----------|-----|--------|
| 1 | `release_repository.py:745` | `is_served = false` in `update_revocation()` SQL | APPLIED |
| 2 | `unpublish_handlers.py:1095` | `is_served = false` in inline revocation SQL | APPLIED |

---

## Run 17: SG2-3 Catalog Strips STAC Fields (REFLEXION) — ALL PATCHES APPLIED

Root cause: pgSTAC `content` JSONB missing `id`, `collection`, `geometry` stored in separate columns.

| Patch | Method | Fix | Status |
|-------|--------|-----|--------|
| 1 | `get_item()` | `content \|\| jsonb_build_object(...)` reconstitution | APPLIED — `pgstac_repository.py:351-400` |
| 2 | `search_by_platform_ids()` | Same reconstitution pattern | APPLIED — `pgstac_repository.py:578-647` |
| 3 | `get_items_by_platform_dataset()` | SQL reconstitution replaces Python merge | APPLIED — `pgstac_repository.py:649-699` |

---

## SIEGE Bug Tracker — Cumulative Status (01 MAR 2026)

### From SIEGE Run 1 (Run 11)

| ID | Severity | Description | Fixed By | Status |
|----|----------|-------------|----------|--------|
| SG-1 | CRITICAL | STAC materialization ordering | v0.9.10.0 | ~~FIXED~~ |
| SG-2 | HIGH | SQL error leak on approvals/status | v0.9.10.0 | ~~FIXED~~ |
| SG-3 | HIGH | catalog/dataset returns 500 | Run 14 (REFLEXION) | ~~FIXED~~ |
| SG-4 | MEDIUM | Approval rollbacks not surfaced on /failures | — | INCONCLUSIVE |
| SG-5 | HIGH | Unpublish blob deletion no-op | Run 15 (REFLEXION) | ~~FIXED~~ |
| SG-6 | MEDIUM | Cached STAC JSON uses stale `-ord` naming | Run 12 (COMPETE analysis) | OPEN — naming sound, hygiene incomplete |
| SG-7 | MEDIUM | is_latest not restored after rollback | v0.9.10.0 | ~~FIXED~~ |
| SG-8 | LOW | Inconsistent lineage 404 shape | v0.9.10.0 | ~~FIXED~~ |
| SG-9 | LOW | dbadmin/stats and diagnostics/all return 404 | — | OPEN |
| SG-10 | LOW | /api/health takes 3.9s | — | OPEN |
| SG-11 | LOW | Resubmit bumps revision not version | — | OPEN (by design) |

### From SIEGE Run 2 (Run 13)

| ID | Severity | Description | Fixed By | Status |
|----|----------|-------------|----------|--------|
| SG2-1 | MEDIUM | Unpublish doesn't accept release_id/version_ordinal | — | OPEN |
| SG2-2 | MEDIUM | Revoked release retains is_served=true | Run 16 (REFLEXION) | ~~FIXED~~ |
| SG2-3 | MEDIUM | Catalog API strips STAC 1.0.0 fields | Run 17 (REFLEXION) | ~~FIXED~~ |
| SG2-4 | LOW | Status endpoint shows revoked release as primary | — | OPEN |
| SG2-5 | LOW | outputs.stac_item_id shows processing-time name | — | OPEN |
| SG2-6 | INFO | /resubmit semantics documentation gap | — | OPEN |

### Score: 10/17 fixed, 7 open (0 CRITICAL, 0 HIGH remaining)

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

**All REFLEXION patches (Runs 14-17) — APPLIED to codebase (v0.9.10.1)**

**Next steps:**
1. Deploy v0.9.10.1 and run SIEGE 3 to verify SG-3, SG-5, SG2-2, SG2-3 fixes
2. Address remaining open items (SG-6, SG2-1, SG-9, SG-10 — all MEDIUM/LOW)
3. Consider WARGAME or TOURNAMENT for pre-release adversarial testing

**Before VirtualiZarr ship:**
4. V-T1 — Docker dependency verification
5. V-T2 — Handler tests
