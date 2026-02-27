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
