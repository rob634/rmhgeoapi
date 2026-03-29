# V10 Deferred Fixes

**Purpose**: All known bugs and code quality issues that need fixing before production. These are NOT accepted risks — they are real problems deferred for timing reasons.

**Last Updated**: 28 MAR 2026

**Rule**: When you fix an item, delete it from this file. The fix lives in git history, not here.

---

## MUST FIX (Before UAT/Production)

### DF-RASTER-1: Tiled raster (>2GB) — no STAC materialization after approval

`process_raster.yaml` has NO STAC materialization nodes for the tiled path (Path B). After approval, `materialize_single_item` tries to resolve `upload_single_cog.result.stac_item_id` which is SKIPPED on the tiled path → `ParameterResolutionError` → task FAILED → `materialize_collection` SKIPPED. Net result: N tiled COGs processed, uploaded, approved, but never published to pgSTAC. TiTiler cannot serve them.

- **File**: `workflows/process_raster.yaml:156-175`
- **Impact**: All rasters >2GB silently fail to publish after human approval
- **Fix**: Add `materialize_tiled_items` node (fan-out over `persist_tiled` cog_ids calling `stac_materialize_item` per tile). Make `materialize_collection` depend on `materialize_single_item?` and `materialize_tiled_items?` (both optional).
- **Source**: COMPETE T9 Run 63 (28 MAR 2026)

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
