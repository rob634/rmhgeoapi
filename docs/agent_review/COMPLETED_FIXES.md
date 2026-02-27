# Adversarial Review — Completed Fixes

**Date**: 26 FEB 2026
**Method**: Adversarial multi-agent pipeline (Omega → Alpha + Beta parallel → Gamma → Delta)
**Result**: 20 of 20 actionable findings RESOLVED across 3 subsystems. Zero regressions.

---

## Summary

| Subsystem | Fixes | Commit(s) | Tests |
|-----------|-------|-----------|-------|
| CoreMachine Orchestration | 5 (1 CRITICAL, 2 HIGH, 2 MEDIUM) | `fa05cc1` (V0.9.8.1) | 352 passing |
| Vector Workflow | 10 (1 CRITICAL, 3 HIGH, 4 MEDIUM, 1 LOW, 1 already resolved) | `8355f7c` | 330 passing |
| Tiled Raster Pipeline | 5 (1 CRITICAL, 2 HIGH, 2 MEDIUM) | `51e8a28` (fixes 1-3), uncommitted (fixes 4-5) | 352 passing |

---

## CoreMachine Orchestration

**Scope**: Job pipeline orchestrator — CoreMachine, StateManager, triggers, infrastructure.
**Files reviewed**: ~25 files across `core/`, `jobs/`, `infrastructure/`, `triggers/`.

### All 5 Fixes — commit `fa05cc1`

| # | Sev | Finding | Files Changed | Resolution |
|---|------|---------|---------------|------------|
| 1 | CRITICAL | Orphan PENDING tasks block stage completion forever — SB send fails after DB insert, task never cleaned up | `core/machine.py` | Mark orphan task FAILED on SB send failure via `fail_task()`. Zero-queued check fails job immediately. |
| 2 | HIGH | All 13 `_mark_job_failed` call sites omit `job_type` — platform callback always gets `'unknown'` | `core/machine.py` | Added `job_type=` kwarg to all 13 call sites using `job_message.job_type` or `task_message.job_type`. |
| 3 | HIGH | TOCTOU race in `complete_task_with_sql` — duplicate message raises `RuntimeError`, fails completed job | `core/state_manager.py` | Re-check task status on `task_updated=False`; return no-op if already COMPLETED/FAILED. |
| 4 | MEDIUM | `fail_all_job_tasks` bypasses repo pattern with raw SQL and hardcoded `"app"` schema | `infrastructure/jobs_tasks.py`, `core/state_manager.py` | New `fail_tasks_for_job()` on TaskRepository using `self.schema_name`. StateManager delegates. |
| 5 | MEDIUM | `_confirm_task_queued` creates fresh DB connections per task message | `triggers/service_bus/task_handler.py` | Accept optional `task_repo` param; caller passes `core_machine.repos['task_repo']`. |

---

## Vector Workflow

**Scope**: Complete vector pipeline — ingestion, PostGIS, STAC, approval, unpublish.
**Files reviewed**: ~20 files across `jobs/`, `services/`, `triggers/`, `config/`.

### Batch 1: Top 5 Fixes — commit `8355f7c`

| # | Sev | Finding | Files Changed | Resolution |
|---|------|---------|---------------|------------|
| C-1 | CRITICAL | `table_name` NameError in `asset_service.py:348` — crashes first-ever release creation | `services/asset_service.py` | Removed stale `table_name=table_name` kwarg from first-release creation path. |
| H-1 | HIGH | Approval guard swallowed on DB failure allows unauthorized unpublish | `services/unpublish_handlers.py` | Changed approval guard from fail-open to fail-closed in both raster and vector inventory paths. |
| H-2 | HIGH | Non-atomic STAC delete + release revocation uses separate connections | `services/unpublish_handlers.py` | Moved release revocation into same cursor/connection as STAC delete for atomic commit. |
| H-3 | HIGH | Orphaned `release_tables` entry on ETL validation failure | `triggers/platform/submit.py` | Removed premature `release_tables` placeholder write with `geometry_type='UNKNOWN'`. |
| M-1 | MEDIUM | Dual processing status update — handler vs callback race | `services/handler_vector_docker_complete.py` | Removed redundant COMPLETED and FAILED status updates — callback is canonical authority. |

### Batch 2: Medium/Low Fixes — commit `8355f7c`

| # | Sev | Files Changed | Resolution |
|---|------|---------------|------------|
| M-2 | MEDIUM | `services/vector/helpers.py` | Per-row WKT parsing with `_safe_wkt_load()` — drops bad rows instead of crashing. 5 new tests. |
| M-5 | MEDIUM | `services/platform_job_submit.py`, `triggers/platform/submit.py` | Service Bus send failure marks job FAILED (prevents orphans). Outer handler re-raises with context. |
| M-7 | MEDIUM | _(no changes needed)_ | Audit found all 14 `"success": False` returns already include `error_type`. Already resolved. |
| M-9 | MEDIUM | `jobs/vector_docker_etl.py` | Replaced 30+ manual `.get()` calls with declarative `_PASSTHROUGH_PARAMS` list. |
| L-1 | LOW | `services/vector/__init__.py`, `services/vector/core.py`, `services/vector/postgis_handler.py` | Centralized `EventCallback` type alias to `services/vector/__init__.py`. |

---

## Tiled Raster Pipeline

**Scope**: Large file COG tiling → pgSTAC registration → TiTiler mosaic.
**Files reviewed**: `services/handler_process_raster_complete.py`, `services/raster_cog.py`, `services/stac_collection.py`, `services/tiling_scheme.py`, and ~10 supporting files.

### Fixes 1-3 — commit `51e8a28`

| # | Sev | Finding | Files Changed | Resolution |
|---|------|---------|---------------|------------|
| C-1 | CRITICAL | `config_obj.raster.use_etl_mount` AttributeError — crashes all single-COG Docker processing | `services/raster_cog.py` | Changed 4 references from `config_obj.raster.use_etl_mount`/`etl_mount_path` to `config_obj.docker.*`. |
| C-2 | HIGH | `raster_type` unbound on VSI checkpoint resume — `NameError` when Phase 4 runs after Phase 3 skip | `services/handler_process_raster_complete.py` | Added `raster_type` recovery from `extraction_result.raster_metadata` in Phase 3 checkpoint skip branch. |
| H-1 | HIGH | Zero tile overlap in mount workflow causes visible seams in TiTiler mosaics | `services/handler_process_raster_complete.py` | Added `overlap=512` to mount workflow tile grid, matching VSI workflow default from `tiling_scheme.py`. |

### Fixes 4-5 — 26 FEB 2026

| # | Sev | Finding | Files Changed | Resolution |
|---|------|---------|---------------|------------|
| 4 | MEDIUM | `_calculate_spatial_extent_from_tiles` opens every COG via HTTP to read bounds (~200 GETs) | `services/handler_process_raster_complete.py` | Both handler call sites (VSI + mount) extract `spatial_extent` from `tiling_result` bounds and pass to `create_stac_collection()`. HTTP fallback retained for collection handler. |
| 5 | MEDIUM | `AZURE_STORAGE_KEY` unguarded env access — undefined GDAL behavior with Managed Identity | `services/stac_collection.py` | Removed all `AZURE_STORAGE_KEY`/`AZURE_STORAGE_ACCESS_KEY` references. Fallback uses `AZURE_STORAGE_AUTH_TYPE="AZURE_AD"`. Removed unused `import os`. |

### Additional Cleanup — 26 FEB 2026

| # | Sev | Finding | Resolution |
|---|------|---------|------------|
| M-5 | MEDIUM | `TiTilerSearchService` is dead code (266 lines, not imported anywhere) | Deleted `services/titiler_search_service.py`. |

---

## Review Methodology

Each subsystem was reviewed using the same adversarial multi-agent pipeline:

| Agent | Role |
|-------|------|
| **Omega** | Orchestrator — splits review into asymmetric lenses |
| **Alpha** | Architecture reviewer — design patterns, contracts, coupling |
| **Beta** | Correctness reviewer — race conditions, atomicity, data integrity |
| **Gamma** | Adversarial contradiction finder — disagreements, blind spots, severity recalibration |
| **Delta** | Final arbiter — prioritized, actionable fixes |

Key value of the pipeline:
- **Information asymmetry**: Alpha and Beta see different concerns, preventing confirmation bias.
- **Gamma's blind spots**: Found the most critical findings across all 3 reviews (orphan PENDING tasks, orphaned release_tables, spatial extent HTTP waste).
- **Execution**: All agents ran as Claude Code subagents. No external API key required.
