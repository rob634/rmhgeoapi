# V10 Deferred Fixes

**Purpose**: All known bugs and code quality issues that need fixing before production. These are NOT accepted risks — they are real problems deferred for timing reasons.

**Last Updated**: 27 MAR 2026

**Rule**: When you fix an item, delete it from this file. The fix lives in git history, not here.

---

## MUST FIX (Before UAT/Production)

### ~~DF-DAG-1: No heartbeat/pulse for DAG workflow tasks during execution~~ — RESOLVED

Already implemented at `docker_service.py:632-674`. Pulse thread updates `last_pulse` every 30s with CAS guard on RUNNING status. COMPETE Run 47 finding was stale — fixed between Run 47 (16 MAR) and Run 53 (26 MAR).

### DF-DAG-2: No retry mechanism for DAG workflow tasks

Handler failure → `fail_workflow_task` immediately. No automatic retry with backoff. A transient blob storage error permanently fails the task and the entire workflow.

- **File**: `docker_service.py` (`_process_workflow_task`)
- **Impact**: Transient failures kill workflows that should recover
- **Fix**: Check `max_retries` on task, use `retry_workflow_task` repo method with exponential backoff
- **Source**: COMPETE Run 47, AR-DAG-14

### DF-DAG-3: `when` clause in echo_test.yaml deadlocks

`when: "params.uppercase"` references `params.*` as a job_params key, but resolver looks for a node named `params` in predecessor outputs. Task stays PENDING forever. Test fixture only, but will confuse anyone using it as a template.

- **File**: `workflows/echo_test.yaml`
- **Impact**: Test workflow broken for when-clause testing
- **Fix**: Change to reference an actual predecessor output, or fix resolver to check job params
- **Source**: COMPETE Run 46, AR-DAG-1

---

## SHOULD FIX (Before v0.11.0)

### DF-PG-1: Remove backward-compatible aliases in postgresql.py

`postgresql.py:102-103` — `_register_type_adapters` and `_parse_jsonb_column` aliases point to `db_utils`. Update callers to import from `infrastructure.db_utils` directly.

- **File**: `infrastructure/postgresql.py`
- **Source**: PostgreSQL Decomposition (14 MAR 2026)

### DF-PG-2: `deployer.py` should use ConnectionManager directly

`core/schema/deployer.py` calls `self.repository._get_connection()` — accessing private method. Should use `ConnectionManager` or a public method.

- **File**: `core/schema/deployer.py`
- **Source**: PostgreSQL Decomposition (14 MAR 2026)

### DF-PG-3: `SnapshotRepository` in wrong location

`services/snapshot_service.py` contains `SnapshotRepository(PostgreSQLRepository)`. Should be in `infrastructure/` per Constitution Standard 1.4.

- **File**: `services/snapshot_service.py` → move to `infrastructure/snapshot_repository.py`
- **Source**: PostgreSQL Decomposition (14 MAR 2026)

### DF-PG-4: Remove redundant `json.dumps()` calls

~50+ sites call `json.dumps()` before passing to PostgreSQL despite psycopg3 type adapters handling JSONB automatically. Unnecessary and obscures the actual data flow.

- **File**: Multiple (grep for `json.dumps.*execute`)
- **Source**: PostgreSQL Decomposition (14 MAR 2026)

### DF-STAC-1: `process_raster_single_cog.yaml` lacks STAC + reverse workflow

Single COG path doesn't materialize to pgSTAC or support unpublish. Items created by this workflow are invisible to TiTiler.

- **File**: `workflows/process_raster_single_cog.yaml`
- **Fix**: Add `stac_materialize_item` + `stac_materialize_collection` nodes; create `unpublish_raster_single_cog.yaml`
- **Source**: COMPETE Run 53

### DF-STAC-2: `process_raster.yaml` missing `reversed_by` field

`unpublish_raster.yaml` declares `reverses: [process_raster]` but `process_raster.yaml` has no reciprocal `reversed_by: unpublish_raster`. Constitution Principle 5 (Paired Lifecycles) violation.

- **File**: `workflows/process_raster.yaml`
- **Fix**: Add `reversed_by: unpublish_raster` to workflow metadata
- **Source**: COMPETE Run 53

### DF-STAC-3: Shallow copy in `handler_materialize_item.py:105`

`.copy()` on nested dict — inner dicts are shared. Mutation of the copy mutates the original.

- **File**: `services/stac/handler_materialize_item.py:105`
- **Fix**: `copy.deepcopy()` or restructure to avoid mutation
- **Source**: COMPETE Run 56

### DF-STAC-4: Duplicate `_SENTINEL_DATETIME` constant

Defined in both `stac_preview.py:24` and `stac_item_builder.py:12`. Should be in one place.

- **File**: `services/stac/stac_preview.py`, `services/stac/stac_item_builder.py`
- **Fix**: Move to `core/models/stac.py` and import from there
- **Source**: COMPETE Run 56

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

Constitution §2.2 violation. Should route through config layer.

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

### DF-CFG-6: Workflows missing `finalize` handler blocks

Five workflows have no finalize: `unpublish_raster.yaml`, `unpublish_vector.yaml`, `acled_sync.yaml`, test workflows.

- **Source**: COMPETE Run 53

### DF-CFG-7: All finalize handlers use `vector_finalize` regardless of workflow type

- **Source**: COMPETE Run 53

---

## Known Bugs (from Development)

| Bug | File/Area | Impact |
|-----|-----------|--------|
| `materialize_collection` skipped via optional dep propagation on single COG path | `process_raster.yaml` | Collection extent not recalculated |
| `validate` handler `file_size_bytes` returns None for local files | `handler_validate.py` | Conditional routing uses download handler's value |
| `validate` reclaimed by janitor on large files (60s+ exceeds heartbeat) | Janitor vs handler runtime | Large file validation killed mid-flight |
| Epoch 4 Guardian enum mismatch after schema rebuild | Schema rebuild DDL | Harmless — Epoch 4 only |
