# V10 Deferred Fixes

**Purpose**: All known bugs and code quality issues that need fixing before production. These are NOT accepted risks — they are real problems deferred for timing reasons.

**Last Updated**: 28 MAR 2026

**Rule**: When you fix an item, delete it from this file. The fix lives in git history, not here.

---

## MUST FIX (Before UAT/Production)

### ~~DF-RASTER-1: Tiled raster (>2GB) — no STAC materialization after approval~~ — RESOLVED 28 MAR 2026

Added `materialize_tiled_items` node with `when: "persist_tiled.result.cog_ids"`. Made `materialize_collection` depend on both `materialize_single_item?` and `materialize_tiled_items?`. Source: COMPETE T4 Run 64 + T9 Run 63.

### ~~DF-ENGINE-1: Finalize handler never invoked by DAG engine~~ — RESOLVED 28 MAR 2026

Added `_dispatch_finalize(workflow_def, run_id)` to `dag_orchestrator.py` at all 3 terminal exit paths (normal terminal, max_consecutive_errors, max_cycles_exhausted). Non-fatal — finalize failure logs warning, does not override terminal status. Follows same pattern as `_handle_release_lifecycle`. Source: COMPETE T5 Run 65.

---

## SHOULD FIX (Before v0.10.10 — DAG Switchover)

### ~~DF-STAC-5: Post-hoc builder mutation + Azure account_name leak in stac_item_json~~

**FIXED** (02 APR 2026). Removed `storage_options` (containing `account_name`) from `xarray:open_kwargs` at all 3 source handlers. Added safety-net stripping in `sanitize_item_properties()`. The `engine` and `chunks` metadata are retained — only the infrastructure credential is removed.

- **Files changed**: `handler_ingest_zarr.py`, `handler_netcdf_to_zarr.py`, `zarr/handler_register.py`, `stac_materialization.py`
- **Source**: COMPETE T6 Run 66 (28 MAR 2026)

### DF-STAC-6: STAC sentinel datetime `0001-01-01T00:00:00Z` is edge-case for parsers

`core/models/stac.py:61` uses `0001-01-01T00:00:00Z` as sentinel. While technically ISO 8601, many STAC clients (pystac, stac-fastapi) treat pre-epoch dates as invalid. The STAC spec allows `"datetime": null` when start/end are provided.

- **File**: `core/models/stac.py:61`, `services/stac/stac_item_builder.py:88`
- **Fix**: Use `null` instead of sentinel when both start_datetime and end_datetime are None
- **Source**: COMPETE T6 Run 66 (28 MAR 2026)

### DF-TIPG-1: TiPG refresh returns `success: True` on total failure

`handler_refresh_tipg.py:78-89` catches all exceptions and returns `{"success": True, "result": {"status": "failed"}}`. Design intent is "TiPG failure is tolerable", but for the preview phase (pre-approval), a failed TiPG refresh means the approval reviewer sees no data.

- **File**: `services/vector/handler_refresh_tipg.py:78-89`
- **Fix**: Consider returning `success: False` for the preview refresh (pre-approval) so the workflow pauses rather than presenting invisible data for approval
- **Source**: COMPETE T5 Run 65 (28 MAR 2026)

---

## SHOULD FIX (Before v0.11.0)

### ~~DF-PG-4: Remove redundant `json.dumps()` calls~~ — RESOLVED 27 MAR 2026

Removed from 21 files. psycopg3 type adapters handle dict → JSONB natively.

### ~~DF-STAC-1: `process_raster_single_cog.yaml` lacks STAC + reverse workflow~~ — NOT AN ISSUE

Orphan YAML — no Python code routes to it. All raster processing goes through `process_raster.yaml` which has conditional routing (single COG branch includes STAC materialization). File left in place as an unused prototype.

---

## NICE TO HAVE (Cleanup)

### DF-LOG-1: `get_tasks_for_run` logs at INFO on every call

24 log lines per minute per run at INFO level. Should be DEBUG.

- **File**: `infrastructure/workflow_run_repository.py:283-286`
- **Source**: COMPETE Run 54

### DF-LOG-2: Multi-band non-multispectral render falls through silently

Returns None implicitly when band configuration doesn't match known patterns.

- **File**: `services/stac_renders.py:80-142`
- **Fix**: Explicit return with warning log
- **Source**: COMPETE Run 56

### DF-CFG-1: JanitorConfig.from_environment reads os.environ directly

Constitution S2.2 violation. Should route through config layer.

- **File**: `core/dag_janitor.py:66-77`
- **Source**: COMPETE Run 54

### DF-CFG-2: `fail_task` docstring contradicts SQL behavior

Docstring says "no guard" but SQL has `WHERE status IN ('running', 'ready', 'pending')`.

- **File**: `infrastructure/workflow_run_repository.py:588-607`
- **Source**: COMPETE Run 54

### DF-CFG-3: `target_width_pixels` and `target_height_pixels` passed but unused

Tiling scheme computes them but tile handler ignores them.

- **File**: `services/raster/handler_generate_tiling_scheme.py:116-117`
- **Source**: COMPETE Run 55

### DF-CFG-4: Minute-level granularity in schedule `request_id`

Two manual triggers within the same minute produce identical request_ids and collide.

- **File**: `core/dag_scheduler.py:316-317`
- **Fix**: Add seconds or a random suffix
- **Source**: COMPETE Run 57

### DF-CFG-5: Missing EPOCH in `orchestration_manager.py` file header

- **File**: `core/orchestration_manager.py:1-8`
- **Source**: COMPETE Run 54

### ~~DF-CFG-6: Workflows missing `finalize` handler blocks~~ — RESOLVED 27 MAR 2026

Added finalize blocks to `unpublish_raster.yaml` and `unpublish_vector.yaml`. Test workflows and `acled_sync.yaml` are lightweight (no mount cleanup needed).

### ~~DF-CFG-7: All finalize handlers use `vector_finalize` regardless of workflow type~~ — RESOLVED 27 MAR 2026

Created `raster_finalize` handler. Updated `process_raster.yaml` and `unpublish_raster.yaml` to use it. Vector workflows use `vector_finalize`.

---

## Known Bugs (from Development)

| Bug | File/Area | Impact |
|-----|-----------|--------|
| `validate` reclaimed by janitor on large files (60s+ exceeds heartbeat) | Janitor vs handler runtime | Large file validation killed mid-flight |
| Epoch 4 Guardian enum mismatch after schema rebuild | Schema rebuild DDL | Harmless — Epoch 4 only |

---

## Resolved Items (29 MAR 2026)

### SIEGE-DAG Run 2 Fixes (29 MAR 2026)

| ID | Item | Resolution |
|----|------|------------|
| SIEGE-1 | BS3 when-clause skip-vs-fail: `materialize_tiled_items` failed on single-COG path because BS3 fix treated SKIPPED predecessor as unresolvable contract bug | Refined `dag_transition_engine.py` BS3 catch: checks if referenced predecessor is SKIPPED → skip task (conditional routing). Only fail when predecessor COMPLETED but output key genuinely missing. |
| SIEGE-2 | `zarr_metadata` table missing PRIMARY KEY — `ON CONFLICT (zarr_id)` upsert silently failed | Added PK to `generate_table_composed` hardcoded list in `sql_generator.py`. Also added `__sql_primary_key` ClassVar to `ZarrMetadataRecord` model for future `generate_table_from_model` migration. |
| SIEGE-3 | `download_to_mount` raised `FileExistsError` on stale mount dirs from previous runs | Added `shutil.rmtree(run_dir)` before download in `handler_download_to_mount.py`. Mount data is ephemeral — always overwrite. |
| SIEGE-4 | DAG approval blocked: `processing_status='completed'` hard guard rejected DAG workflows at approval gate (`processing_status='processing'`) | Relaxed guard in `asset_approval_service.py:155` to accept `processing` when release has `workflow_id` (DAG runs). Epoch 4 path unchanged. |
| SIEGE-5 | `orchestrator_lease` table missing after `action=rebuild` — Brain couldn't acquire lease | Registered `OrchestratorLease` model in DDL generator (`sql_generator.py`). Table now created by rebuild alongside all other app schema tables. |
| SIEGE-6 | `max_cycles_exhausted` fired in Brain's single-tick mode (`max_cycles=1`) — every run marked FAILED after 1 cycle | Added `max_cycles > 1` guard in `dag_orchestrator.py` else clause. Single-tick mode (Brain) exits cleanly without marking FAILED. |
| SIEGE-7 | `dag_brain: unhealthy` health check — `workflows_dir` NameError + `datetime - string` TypeError + fail-fast registry | Fixed `workflows_dir` → `registry._dir`. Added `fromisoformat()` parse for `last_scan_at`. Made `load_all()` resilient (per-file catch, degraded mode). |

---

## Resolved Items (28 MAR 2026)

| ID | Item | Resolution |
|----|------|------------|
| DF-DAG-1 | No heartbeat/pulse | Already implemented (docker_service.py:632-674) |
| DF-DAG-2 | No retry mechanism | Retry with exponential backoff + progress via pulse thread |
| DF-DAG-3 | echo_test when-clause deadlock | Already fixed (dag_transition_engine.py:103 handles params.*) |
| DF-PG-1 | Backward-compatible aliases | Removed aliases, updated callers to db_utils |
| DF-PG-2 | deployer.py private method | Added public get_connection() to PostgreSQLRepository |
| DF-PG-3 | SnapshotRepository location | Moved to infrastructure/snapshot_repository.py |
| DF-STAC-2 | Missing reversed_by | Added to process_raster.yaml |
| DF-STAC-3 | Shallow copy | Changed to copy.deepcopy() |
| DF-STAC-4 | Duplicate _SENTINEL_DATETIME | Moved to core/models/stac.py |
| DF-CFG-6 | Workflows missing finalize blocks | Added finalize to unpublish_raster + unpublish_vector |
| DF-CFG-7 | All finalize handlers use vector_finalize | Created raster_finalize, fixed YAML references |
| DF-BUG-1 | `materialize_collection` skipped on single COG path | Removed `?` from dependency in `process_raster.yaml` (28 MAR 2026) |
| DF-BUG-2 | `validate` handler `file_size_bytes` returns None | Added `os.path.getsize()` fallback in `handler_validate.py` (28 MAR 2026) |
| DF-DAG-4 | Status `services` null for DAG runs | Resolve release via `dag_run.release_id` in status handler (28 MAR 2026) |
| DF-DAG-5 | `asset_releases.job_id` FK violation on DAG submissions | Guard `link_job_to_release` for DAG runs in `submit.py` (28 MAR 2026) |
| DF-DAG-6 | Catalog `xarray_urls` empty for zarr | Cache `stac_item_json` in release in `handler_register.py` (28 MAR 2026) |
| DF-DAG-7 | `.zarr` prefix misclassified as single file | `.zarr` directory detection in `etl_mount.py` (28 MAR 2026) |
| DF-DAG-8 | Spatial extent global bbox for pyramid stores | Extract bbox in validate, pass to register via YAML receives (28 MAR 2026) |
