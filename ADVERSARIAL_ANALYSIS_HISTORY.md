# Adversarial Analysis — Completed Fixes History

**Purpose**: Archive of resolved findings from adversarial reviews. Active/open findings remain in their respective analysis documents.

---

## Vector Workflow — 26 FEB 2026

**Source**: `ADVERSARIAL_ANALYSIS_VECTOR.md`
**Pipeline**: Omega → Alpha + Beta → Gamma → Delta
**Result**: 10 of 10 actionable findings RESOLVED. 330 tests passing, zero regressions.

### Batch 1: Top 5 Fixes — commit `8355f7c`

| Fix | Sev | Finding | Files Changed | Resolution |
|-----|------|---------|---------------|------------|
| C-1 | CRITICAL | `table_name` NameError in `asset_service.py:348` — crashes first-ever release creation | `services/asset_service.py` | Removed stale `table_name=table_name` kwarg from first-release creation path |
| H-1 | HIGH | Approval guard swallowed on DB failure allows unauthorized unpublish | `services/unpublish_handlers.py` | Changed approval guard from fail-open to fail-closed in both raster and vector inventory paths |
| H-2 | HIGH | Non-atomic STAC delete + release revocation uses separate connections | `services/unpublish_handlers.py` | Moved release revocation into same cursor/connection as STAC delete for atomic commit |
| H-3 | HIGH | Orphaned `release_tables` entry on ETL validation failure | `triggers/platform/submit.py` | Removed premature `release_tables` placeholder write with `geometry_type='UNKNOWN'` |
| M-1 | MEDIUM | Dual processing status update — handler vs callback race | `services/handler_vector_docker_complete.py` | Removed redundant COMPLETED and FAILED status updates — callback is canonical authority |

### Batch 2: Medium/Low Fixes — commit `8355f7c`

| Finding | Sev | Files Changed | Resolution |
|---------|------|---------------|------------|
| M-2 | MEDIUM | `services/vector/helpers.py` | Per-row WKT parsing with `_safe_wkt_load()` — drops bad rows instead of crashing. 5 new tests. |
| M-5 | MEDIUM | `services/platform_job_submit.py`, `triggers/platform/submit.py` | Service Bus send failure marks job FAILED (prevents orphans). Outer handler re-raises with context. |
| M-7 | MEDIUM | _(no changes needed)_ | Audit found all 14 `"success": False` returns already include `error_type`. Already resolved during Fix 2. |
| M-9 | MEDIUM | `jobs/vector_docker_etl.py` | Replaced 30+ manual `.get()` calls with declarative `_PASSTHROUGH_PARAMS` list. |
| L-1 | LOW | `services/vector/__init__.py`, `services/vector/core.py`, `services/vector/postgis_handler.py` | Centralized `EventCallback` type alias to `services/vector/__init__.py`. |

---

## Tiled Raster Pipeline — 26 FEB 2026

**Source**: `ADVERSARIAL_ANALYSIS_TILED_RASTER.md`
**Pipeline**: Omega → Alpha + Beta → Gamma → Delta
**Result**: 3 of 5 actionable findings RESOLVED (commit `51e8a28`). 2 remaining (FIX 4, FIX 5).

### Fixes Completed — commit `51e8a28`

| Fix | Sev | Finding | Files Changed | Resolution |
|-----|------|---------|---------------|------------|
| C-1 | CRITICAL | `config_obj.raster.use_etl_mount` AttributeError — crashes all single-COG Docker processing | `services/raster_cog.py` | Changed 4 references from `config_obj.raster.use_etl_mount`/`etl_mount_path` to `config_obj.docker.*` |
| C-2 | HIGH | `raster_type` unbound on VSI checkpoint resume — `NameError` when Phase 4 runs after Phase 3 skip | `services/handler_process_raster_complete.py` | Added `raster_type` recovery from `extraction_result.raster_metadata` in Phase 3 checkpoint skip branch |
| H-1 | HIGH | Zero tile overlap in mount workflow causes visible seams in TiTiler mosaics | `services/handler_process_raster_complete.py` | Added `overlap=512` to mount workflow tile grid, matching VSI workflow default from `tiling_scheme.py` |

---

## Platform Submit Workflow — 26 FEB 2026

**Source**: `docs/agent_review/SUBMISSION.md`
**Pipeline**: Omega → Alpha + Beta → Gamma → Delta
**Scope**: 12 files, ~6,700 LOC — submit endpoint, Asset/Release lifecycle, translation layer
**Result**: 5 of 5 actionable findings RESOLVED. 286 tests passing, zero regressions.

### Fixes Completed

| Fix | Sev | Finding | Files Changed | Resolution |
|-----|------|---------|---------------|------------|
| FIX 1 | CRITICAL | `config` NameError at `submit.py:168` — crashes every platform submit | `triggers/platform/submit.py` | Removed bare `config` arg; `translate_to_coremachine()` already has `cfg=None` default |
| FIX 4 | HIGH | `can_overwrite()` doesn't check `processing_status` — allows overwrite while PROCESSING | `core/models/asset.py`, `services/asset_service.py` | Added `processing_status == PROCESSING` guard; error message now includes both dimensions |
| FIX 2 | HIGH | `update_overwrite()` doesn't reset `approval_state` from REJECTED | `infrastructure/release_repository.py` | Added `approval_state`, `rejection_reason`, `reviewer`, `reviewed_at` to UPDATE SET clause |
| FIX 3 | HIGH | `update_overwrite()` doesn't clear stale `job_id` | `infrastructure/release_repository.py` | Added `job_id = NULL` to same UPDATE (combined with FIX 2) |
| FIX 5 | MEDIUM | Error response leaks internal exception details to HTTP callers | `triggers/platform/submit.py` | Replaced raw `str(e)` with generic messages; details remain in server logs via `exc_info=True` |
