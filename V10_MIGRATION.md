# V10 Migration: DAG-Based YAML Workflow Orchestration

**Created**: 14 MAR 2026
**Updated**: 16 MAR 2026
**Status**: ACTIVE — F1 done (v0.10.3), F-DAG + F4 starting (strangler fig migration)
**Target**: Decompose monolithic job/stage/task system into atomic DAG nodes with YAML workflow definitions
**Justification**: Interchangeable tasks, polling-based orchestration, no distributed messaging complexity
**Migration Strategy**: Strangler fig — DAG Brain runs alongside existing CoreMachine. Workflows ported one at a time. Legacy removed after all 14 proven.
**End State (v0.12.0)**: Function App gateway + Docker DAG Brain + Docker workers + PostgreSQL. Zero Service Bus.
**Azure Resources**: See [Azure Resource Map](#azure-resource-map) below.
**Spec**: `docs/superpowers/specs/2026-03-16-workflow-loader-yaml-schema-design.md` — YAML schema + Pydantic models

---

## Why This Migration

The current architecture works but has structural limitations:

| Problem | Current State | After Migration |
|---------|--------------|-----------------|
| **Rigid stage sequencing** | Stages execute in fixed order (1→2→3) | DAG allows parallel branches, conditional paths, diamond dependencies |
| **Monolithic handlers** | `vector_docker_complete` = 7 phases in 400 lines | 6 atomic handlers, each reusable across workflows |
| **Service Bus coupling** | 3 queues, AMQP warmup bugs, message loss risk, DLQ management | Polling loop on PostgreSQL — one coordination mechanism |
| **Multi-app signaling** | Workers send `stage_complete` back to orchestrator via queue | Orchestrator polls task status directly |
| **Python-only workflows** | Job types require Python class + registration | YAML file defines workflow, references existing handlers |
| **Non-composable tasks** | `stac_create_item` duplicated in raster, zarr, virtualzarr handlers | Single `stac_create_item` handler referenced by all workflows |

---

## Current Architecture (What We're Changing)

### Current Flow

```
HTTP POST /api/jobs/submit/{job_type}
    ↓
submit_job_trigger → validate → generate_job_id (SHA256) → create DB record
    ↓
Send JobQueueMessage → Service Bus (geospatial-jobs queue)
    ↓
CoreMachine.process_job_message()
    → Look up Python job class from ALL_JOBS registry
    → Call job.create_tasks_for_stage(stage, params, job_id, previous_results)
    → Send TaskQueueMessages → Service Bus (container-tasks queue)
    ↓
Docker Worker polls container-tasks queue (BackgroundQueueWorker)
    → CoreMachine.process_task_message()
    → handler(enriched_params) → {success: bool, result: {...}}
    → Atomic SQL: complete_task_and_check_stage()
    → If last task in stage: send stage_complete → Service Bus (geospatial-jobs)
    ↓
Orchestrator receives stage_complete
    → _handle_stage_completion() → advance to next stage OR finalize job
```

### Current Strengths (Keep These)

| Strength | Where | Why Keep |
|----------|-------|----------|
| Handler contract | `handler(params) → {success, result}` | Pure functions, stateless, testable |
| Explicit registries | `ALL_HANDLERS`, `ALL_JOBS` dicts | No decorator magic, fail-fast validation |
| Atomic stage completion | SQL advisory locks, "last task turns out the lights" | Race-condition-free — adapt for DAG |
| Idempotent job IDs | SHA256(job_type + params) | Deduplication still valuable |
| Fan-out/fan-in | `parallelism: fan_out` from previous results | DAG expresses this naturally |
| Resource validators | Pre-flight checks before job creation | Reusable in YAML `validators:` block |
| Exception categorization | Retryable vs permanent exceptions | Still needed for retry decisions |

### Current Weaknesses (Remove These)

| Weakness | File | Lines | Impact |
|----------|------|-------|--------|
| Service Bus AMQP warmup | `infrastructure/service_bus.py` | 800+ | Silent message loss without `_open()` |
| Multi-app stage signaling | `core/machine.py:_should_signal_stage_complete()` | ~50 | Complexity for worker→orchestrator |
| Fixed stage ordering | `stages = [{"number": 1, ...}, {"number": 2, ...}]` | — | No conditional branches, no diamonds |
| Monolithic handlers | `handler_vector_docker_complete.py` | 400+ | 7 phases in one function, not reusable |
| Python-only job defs | `jobs/*.py` | 14 files | Boilerplate even with JobBaseMixin |
| `create_tasks_for_stage()` | Per-job static method | — | Task creation logic mixed with job definition |

---

## Target Architecture

### YAML Workflow Definition

```yaml
# workflows/vector_docker_etl.yaml
workflow: vector_docker_etl
description: "Single vector file → PostGIS table"
reversed_by: unpublish_vector

parameters:
  blob_name: {type: str, required: true}
  table_name: {type: str, required: true}
  container_name: {type: str, required: true}
  schema_name: {type: str, default: "geo"}
  processing_options:
    type: dict
    default: {}
    nested:
      overwrite: {type: bool, default: false}
      split_column: {type: str, required: false}

validators:
  - type: blob_exists
    container_param: container_name
    blob_param: blob_name
    zone: bronze

tasks:
  validate_source:
    handler: vector_validate_source
    params: [blob_name, container_name]

  create_table:
    handler: vector_create_postgis_table
    depends_on: [validate_source]
    params: [blob_name, table_name, schema_name]
    receives:
      source_metadata: "validate_source.result.metadata"

  load_data:
    handler: vector_load_chunks
    depends_on: [create_table]
    params: [table_name, schema_name]
    receives:
      row_count: "create_table.result.row_count"

  create_split_views:
    handler: vector_create_split_views
    depends_on: [load_data]
    when: "params.processing_options.split_column"
    params: [table_name, schema_name, processing_options]

  register_catalog:
    handler: catalog_register_vector
    depends_on:
      - load_data
      - create_split_views?    # ? = optional dependency (skip if skipped)
    params: [table_name, schema_name]

  refresh_tipg:
    handler: tipg_refresh_collections
    depends_on: [register_catalog]

finalize:
  handler: vector_finalize
```

### DAG Orchestrator (Polling-Based)

```
┌─────────────────────────────────────────────────────────┐
│                    DAG Orchestrator                      │
│                                                         │
│  Poll Loop (every 2-5 seconds):                         │
│                                                         │
│  1. SELECT * FROM app.ready_tasks                       │
│     (tasks where all non-optional deps are completed)   │
│                                                         │
│  2. For each ready task:                                │
│     a. Resolve parameters:                              │
│        - Job params (from workflow_runs.parameters)      │
│        - Received values (from predecessor results)     │
│     b. Mark task RUNNING                                │
│     c. Execute handler(resolved_params)                 │
│     d. Write result → workflow_tasks.result_data        │
│     e. Mark task COMPLETED or FAILED                    │
│                                                         │
│  3. Evaluate conditional tasks:                         │
│     - Check `when:` clauses                             │
│     - Mark as SKIPPED if condition is false             │
│                                                         │
│  4. Check successor readiness:                          │
│     - For each completed/skipped task, check successors │
│     - Mark successors READY if all deps satisfied       │
│                                                         │
│  5. Check workflow completion:                          │
│     - If no PENDING/READY/RUNNING tasks remain          │
│     - Run finalize handler                              │
│     - Mark workflow_run COMPLETED                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Handler Contract (Unchanged)

```python
def handler_name(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    SAME CONTRACT AS TODAY.

    Args:
        params: Task parameters (job params + received values + system fields)
        context: Optional execution context

    Returns:
        {"success": True, "result": {...}}  — on success
        {"success": False, "error": "...", "error_type": "..."}  — on failure
    """
```

---

## YAML Workflow Schema Specification

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | str | Yes | Unique workflow identifier (replaces `job_type`) |
| `description` | str | Yes | Human-readable description |
| `reversed_by` | str | No | Unpublish workflow name |
| `reverses` | list[str] | No | Forward workflows this unpublishes |
| `parameters` | dict | Yes | Parameter schema (same validation as today) |
| `validators` | list[dict] | No | Pre-flight resource validators |
| `tasks` | dict | Yes | DAG node definitions (key = task name) |
| `finalize` | dict | No | Final aggregation handler |

### Task Node Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `handler` | str | Yes | Handler name from `ALL_HANDLERS` registry |
| `depends_on` | list[str] | No | Predecessor task names. `?` suffix = optional |
| `params` | list[str] | No | Job parameter names to pass through |
| `receives` | dict | No | Values received from predecessors: `{local_name: "task.result.path"}` |
| `when` | str | No | Condition for execution (dotted path truthiness) |
| `fan_out` | dict | No | Fan-out configuration (see below) |
| `retry` | dict | No | Retry policy override |
| `timeout` | int | No | Timeout in seconds |

### Fan-Out Configuration

```yaml
tasks:
  list_blobs:
    handler: zarr_list_blobs
    params: [source_url]

  copy_blob:
    handler: zarr_copy_single_blob
    depends_on: [list_blobs]
    fan_out:
      source: "list_blobs.result.blob_list"   # array from predecessor
      item_param: "blob_path"                  # parameter name for each item
    params: [source_url, target_container]

  consolidate:
    handler: zarr_consolidate_metadata
    depends_on: [copy_blob]        # waits for ALL fan-out instances
    receives:
      copied_blobs: "copy_blob.result[]"   # [] = collect all fan-out results
```

### Conditional Execution

```yaml
tasks:
  create_split_views:
    handler: vector_create_split_views
    depends_on: [load_data]
    when: "params.processing_options.split_column"
    # Evaluated as: bool(job_params.get('processing_options', {}).get('split_column'))
    # If false: task marked SKIPPED, optional dependents proceed
```

### Parameter Resolution

Parameters flow through three sources, merged in order:

1. **Job parameters** — from `params:` list (filtered from submission parameters)
2. **Received values** — from `receives:` dict (extracted from predecessor results)
3. **System parameters** — injected by orchestrator (`_run_id`, `_task_name`, `_workflow`)

```yaml
tasks:
  create_table:
    handler: vector_create_postgis_table
    depends_on: [validate_source]
    params: [blob_name, table_name, schema_name]       # from job submission
    receives:
      source_metadata: "validate_source.result.metadata"  # from predecessor
      column_count: "validate_source.result.column_count"
    # Handler receives: {blob_name, table_name, schema_name, source_metadata, column_count, _run_id, ...}
```

---

## Database Schema for DAG Execution

### New Tables

```sql
-- Workflow run (replaces app.jobs for DAG workflows)
CREATE TABLE app.workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    parameters JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending → running → completed | failed
    definition JSONB NOT NULL,           -- YAML snapshot at submission time (immutable)
    platform_version TEXT NOT NULL,      -- from config/__init__.py (e.g., "0.11.0")
    result_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    -- Platform integration
    request_id TEXT,                     -- platform request_id (for B2B status lookups)
    asset_id TEXT,                       -- linked asset
    release_id TEXT,                     -- linked release
    -- Backward compat: link to legacy job record during migration
    legacy_job_id TEXT
);

-- Task instance within a workflow run
CREATE TABLE app.workflow_tasks (
    task_instance_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES app.workflow_runs(run_id),
    task_name TEXT NOT NULL,
    handler TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending → ready → running → completed | failed | skipped | expanded
    --
    -- Status transitions:
    --   pending  → ready     (orchestrator: all deps satisfied)
    --   pending  → skipped   (orchestrator: `when:` condition false)
    --   ready    → running   (worker: claimed via SKIP LOCKED)
    --   ready    → expanded  (orchestrator: fan-out template, N instances created)
    --   running  → completed (worker: handler returned success)
    --   running  → failed    (worker: handler returned failure or exception)
    --   running  → ready     (janitor: stale heartbeat, retry_count < max)
    --   failed   → ready     (manual: retry via admin endpoint)
    --
    fan_out_index INTEGER,           -- NULL for non-fan-out, 0..N for fan-out instances
    fan_out_source TEXT,             -- "list_blobs" — which predecessor produced the fan-out
    when_clause TEXT,                -- condition expression from YAML (NULL = unconditional)
    parameters JSONB,                -- resolved parameters at execution time
    result_data JSONB,
    error_details TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    claimed_by TEXT,                 -- worker_id that claimed this task (NULL when unclaimed)
    last_pulse TIMESTAMPTZ,          -- heartbeat from worker during execution
    execute_after TIMESTAMPTZ,       -- scheduled execution (NULL = immediate, set for retry backoff)
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE(run_id, task_name, fan_out_index)
);

-- DAG edges (created when workflow starts)
CREATE TABLE app.workflow_task_deps (
    task_instance_id TEXT NOT NULL REFERENCES app.workflow_tasks(task_instance_id),
    depends_on_instance_id TEXT NOT NULL REFERENCES app.workflow_tasks(task_instance_id),
    optional BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (task_instance_id, depends_on_instance_id)
);

-- Indexes for the two poll queries (orchestrator + worker)
CREATE INDEX idx_workflow_tasks_status ON app.workflow_tasks(status)
    WHERE status IN ('pending', 'ready', 'running');

CREATE INDEX idx_workflow_tasks_run ON app.workflow_tasks(run_id);

-- Index for janitor stale-task detection
CREATE INDEX idx_workflow_tasks_stale ON app.workflow_tasks(status, last_pulse)
    WHERE status = 'running';

-- Index for worker SKIP LOCKED poll (covers the WHERE + ORDER BY)
CREATE INDEX idx_workflow_tasks_ready_poll ON app.workflow_tasks(status, execute_after, created_at)
    WHERE status = 'ready';
```

### Worker Poll Query (Competing Consumers via SKIP LOCKED)

```sql
-- Each worker runs this in a loop. SKIP LOCKED ensures:
-- - Worker A locks row 1 → Worker B skips row 1, grabs row 2
-- - No double-processing, no coordination needed
-- - Add more workers = more throughput, same query

BEGIN;

SELECT * FROM app.workflow_tasks
WHERE status = 'ready'
  AND (execute_after IS NULL OR execute_after < NOW())
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- Atomically claim the task (same transaction)
UPDATE app.workflow_tasks
SET status = 'running',
    claimed_by = $worker_id,
    started_at = NOW(),
    last_pulse = NOW()
WHERE task_instance_id = $1;

COMMIT;

-- Worker executes handler, then writes result:
UPDATE app.workflow_tasks
SET status = $status,           -- 'completed' or 'failed'
    result_data = $result::jsonb,
    error_details = $error,
    completed_at = NOW()
WHERE task_instance_id = $1;
```

### Orchestrator: Ready-Task Detection (Dependency Evaluation)

```sql
-- View: pending tasks whose dependencies are all satisfied
-- The orchestrator queries this to find tasks to mark 'ready'
-- (Workers do NOT use this view — they query status='ready' directly)
CREATE VIEW app.promotable_tasks AS
SELECT wt.*
FROM app.workflow_tasks wt
WHERE wt.status = 'pending'
  AND NOT EXISTS (
    SELECT 1
    FROM app.workflow_task_deps d
    JOIN app.workflow_tasks dep
      ON dep.task_instance_id = d.depends_on_instance_id
    WHERE d.task_instance_id = wt.task_instance_id
      AND d.optional = FALSE
      AND dep.status NOT IN ('completed', 'skipped', 'expanded')
  );

-- Orchestrator promotes pending → ready:
UPDATE app.workflow_tasks
SET status = 'ready'
WHERE task_instance_id IN (SELECT task_instance_id FROM app.promotable_tasks);
```

### Workflow Completion Detection

```sql
-- Workflow is complete when no tasks are pending/ready/running
SELECT NOT EXISTS (
    SELECT 1 FROM app.workflow_tasks
    WHERE run_id = %s
      AND status IN ('pending', 'ready', 'running')
) AS workflow_complete;
```

### Stale Task Recovery (Janitor Query)

```sql
-- Reclaim tasks from dead/stuck workers (janitor runs every 60s)
-- Replaces Service Bus lock timeout + auto-redelivery
UPDATE app.workflow_tasks
SET status = 'ready',
    claimed_by = NULL,
    retry_count = retry_count + 1,
    error_details = 'Worker unresponsive — reclaimed by janitor at ' || NOW(),
    -- Exponential backoff: 30s, 60s, 120s
    execute_after = NOW() + (INTERVAL '30 seconds' * POWER(2, retry_count))
WHERE status = 'running'
  AND last_pulse < NOW() - INTERVAL '5 minutes'
  AND retry_count < max_retries;

-- Permanently fail after max retries (replaces SB dead-letter queue)
UPDATE app.workflow_tasks
SET status = 'failed',
    error_details = 'Max retries exceeded — worker unresponsive after ' || max_retries || ' attempts',
    completed_at = NOW()
WHERE status = 'running'
  AND last_pulse < NOW() - INTERVAL '5 minutes'
  AND retry_count >= max_retries;
```

---

## Handler Decomposition Plan

### Vector Pipeline: `vector_docker_complete` → 6 Atomic Nodes (Finalized 16 MAR 2026)

**Current**: One 1,160-line function with 7 phases + checkpoint system.

**Design principle**: Validate everything upfront. No partial jobs, no partial parameters, no guessing. The B2B app submits a complete valid contract or the workflow fails at validation — never at node 4 of 6.

**Intermediate data**: GeoParquet on mount (`/mnt/etl/{run_id[:12]}/intermediate/`). See "Intermediate Data Architecture" section.

#### DAG Shape

```
load_source → validate_and_clean → create_and_load_tables → create_split_views? → register_catalog → refresh_tipg
```

Six nodes, linear with one conditional skip. Geometry type split (1-3 types) handled internally by `create_and_load_tables` — no fan-out needed (max 3 types, always known after validation).

#### Node Definitions

| Node | Handler | Can Reject? | Writes to Mount? | Internal Loop? |
|------|---------|-------------|------------------|----------------|
| `load_source` | `vector_load_source` | Yes — bad file, missing blob, corrupt format, non-spatial GPKG layer | Yes — raw GeoDataFrame parquet | No |
| `validate_and_clean` | `vector_validate_and_clean` | Yes — no CRS, 100% null geometry, unsupported types, invalid split_column | Yes — cleaned parquet (per geometry group) | No (outputs 1-3 groups) |
| `create_and_load_tables` | `vector_create_and_load_tables` | Yes — DDL/INSERT failure | No (writes to PostGIS) | Yes — 1-3 geometry groups |
| `create_split_views` | `vector_create_split_views` | Yes — column not found (shouldn't happen — validated upfront) | No (writes to PostGIS) | Yes — N views |
| `register_catalog` | `vector_register_catalog` | Unlikely | No | Yes — 1-3 catalog entries |
| `refresh_tipg` | `vector_refresh_tipg` | Tolerable (TiPG down) | No | No |

#### Upfront Validation (CRITICAL — `validate_and_clean` rejects early)

If the submission includes `processing_options.split_column`, `validate_and_clean` performs **all** split-column validation before any table is created:

1. Verify the column exists in the GeoDataFrame (after column sanitization)
2. Query distinct values — verify cardinality is within limits (max ~100 views)
3. Verify column has categorical data type (not geometry, not binary)
4. If ANY of these fail → reject the **entire job** immediately

This prevents the failure mode where 3 tables are created and loaded successfully but split views fail at Phase 3.7 — leaving orphaned tables with no views. **Fail before any writes, or succeed at all writes.**

#### `validate_and_clean` Full Responsibility

All operations run on the full GeoDataFrame before any split:
1. Remove null geometries (warn if partial, reject if 100%)
2. Fix invalid geometries (`make_valid`)
3. Force 2D (remove Z/M dimensions)
4. Antimeridian fix (split geometries crossing 180°)
5. Normalize to Multi-types (Point → MultiPoint, etc.)
6. Fix winding order (CCW exterior, CW holes)
7. PostGIS type validation
8. Datetime column validation
9. Null column pruning
10. CRS validation — **reject if missing or uncertain** (no silent EPSG:4326 assumption)
11. CRS reprojection → EPSG:4326
12. Column sanitization (reserved names, special chars)
13. Optional: simplify, quantize
14. **If `split_column` specified**: validate column exists, discover distinct values, verify cardinality
15. **Last step**: Split by geometry type → `{'polygon': gdf1, 'line': gdf2, 'point': gdf3}`

Output: `geometry_groups` metadata + parquet file(s) on mount + `split_column_values` (if applicable)

### Raster Pipeline: `raster_docker_complete` → 5 Atomic Handlers

| Atomic Handler | Input | Output | Shared With |
|---------------|-------|--------|-------------|
| `raster_validate_source` | blob_name, container | metadata, bands, crs, bounds | — |
| `raster_create_cog` | blob_path, cog_options | cog_blob_path, file_size | — |
| `raster_upload_cog` | cog_local_path, target_container | blob_url | — |
| `stac_create_item` | metadata, blob_url, collection_id | stac_item_id | Zarr workflows |
| `catalog_register_raster` | stac_item_id, metadata | catalog_entry_id | — |

### Zarr Pipelines: Already ~80% Decomposed

Current stages map almost directly to atomic handlers:

| Current Stage | Becomes Handler | Notes |
|--------------|----------------|-------|
| `ingest_zarr_validate` | `zarr_validate_store` | Already isolated |
| `ingest_zarr_copy_blob` (fan-out) | `zarr_copy_single_blob` | Already parallel |
| `ingest_zarr_rechunk` | `zarr_rechunk_store` | Conditional: `when: rechunk=true` |
| `ingest_zarr_register` | `zarr_register_metadata` | Already isolated |
| `netcdf_convert` (fan-out) | `netcdf_convert_chunk` | Already parallel |
| `zarr_consolidate_metadata` | `zarr_consolidate_metadata` | Already isolated |
| `virtualzarr_scan` | `virtualzarr_scan_references` | Domain-specific |
| `virtualzarr_combine` | `virtualzarr_combine_references` | Domain-specific |

### Unpublish Pipelines: ~5 Shared Atomic Handlers

| Atomic Handler | Used By | Notes |
|---------------|---------|-------|
| `unpublish_inventory_item` | All unpublish workflows | Query STAC/catalog, extract blob refs |
| `unpublish_delete_blob` | All unpublish workflows | Fan-out: one per blob |
| `unpublish_cleanup_stac` | Raster + zarr unpublish | Remove from pgSTAC |
| `unpublish_cleanup_postgis` | Vector unpublish | DROP TABLE + metadata |
| `unpublish_cleanup_catalog` | All unpublish workflows | Remove from asset catalog |

### Cross-Cutting Reusable Handlers (Highest Value)

| Handler | Used By | Current Location | Extraction |
|---------|---------|-----------------|------------|
| `tipg_refresh_collections` | All vector workflows | `service_layer_client.py` | **Easy** — already isolated |
| `stac_create_item` | All raster + zarr | Inline in handlers | **Medium** — needs param standardization |
| `catalog_register_asset` | All forward workflows | Scattered | **Medium** — unify interface |
| `catalog_deregister_asset` | All unpublish workflows | Scattered | **Medium** — same |
| `validate_blob_exists` | All ingest workflows | `resource_validators` | **Easy** — exists |
| `unpublish_delete_blob` | All unpublish workflows | `unpublish_handlers.py` | **Easy** — exists |

---

## Sample YAML Workflows

### Vector Pipeline (Finalized 16 MAR 2026)

```yaml
# workflows/vector_docker_etl.yaml
workflow: vector_docker_etl
description: "Vector file (CSV/SHP/KML/GeoJSON/GPKG) → PostGIS table(s) + TiPG URL"
version: 1
reversed_by: unpublish_vector

parameters:
  blob_name: {type: str, required: true}
  container_name: {type: str, required: true}
  table_name: {type: str, required: true}
  schema_name: {type: str, default: "geo"}
  file_extension: {type: str, required: true}
  processing_options:
    type: dict
    default: {}
    nested:
      overwrite: {type: bool, default: false}
      split_column: {type: str, required: false}
      chunk_size: {type: int, default: 100000}

validators:
  - type: blob_exists
    container_param: container_name
    blob_param: blob_name
    zone: bronze

nodes:
  load_source:
    type: task
    handler: vector_load_source
    params: [blob_name, container_name, file_extension, processing_options]
    # Streams blob to mount, converts format to GeoDataFrame
    # Rejects: corrupt file, unknown format, missing blob, non-spatial GPKG layer

  validate_and_clean:
    type: task
    handler: vector_validate_and_clean
    depends_on: [load_source]
    params: [processing_options]
    receives:
      source_path: "load_source.intermediate_path"
    # All geometry cleaning + validation on full GeoDataFrame
    # Rejects: no CRS, 100% null geometry, unsupported types
    # If split_column specified: validates column exists, cardinality OK — reject entire job if not
    # Last step: split by geometry type (1-3 groups)

  create_and_load_tables:
    type: task
    handler: vector_create_and_load_tables
    depends_on: [validate_and_clean]
    params: [table_name, schema_name, processing_options]
    receives:
      geometry_groups: "validate_and_clean.geometry_groups"
      validated_path: "validate_and_clean.intermediate_path"
    # Iterates 1-3 geometry groups internally:
    #   For each: CREATE TABLE, INSERT chunks, deferred indexes, ANALYZE

  create_split_views:
    type: task
    handler: vector_create_split_views
    depends_on: [create_and_load_tables]
    when: "processing_options.split_column"
    params: [table_name, schema_name, processing_options]
    receives:
      tables_info: "create_and_load_tables.tables_created"
    # Creates N views from categorical column values (pre-validated by validate_and_clean)

  register_catalog:
    type: task
    handler: vector_register_catalog
    depends_on:
      - create_and_load_tables
      - "create_split_views?"
    params: [table_name, schema_name]
    receives:
      tables_info: "create_and_load_tables.tables_created"

  refresh_tipg:
    type: task
    handler: vector_refresh_tipg
    depends_on: [register_catalog]
    params: [table_name, schema_name]

finalize:
  handler: vector_finalize
```

### Raster Pipeline

```yaml
# workflows/process_raster_docker.yaml
workflow: process_raster_docker
description: "Single raster → COG + STAC item"
reversed_by: unpublish_raster

parameters:
  blob_name: {type: str, required: true}
  container_name: {type: str, required: true}
  collection_id: {type: str, required: true}
  processing_options:
    type: dict
    default: {}

validators:
  - type: blob_exists
    container_param: container_name
    blob_param: blob_name
    zone: bronze

tasks:
  validate:
    handler: raster_validate_source
    params: [blob_name, container_name]

  create_cog:
    handler: raster_create_cog
    depends_on: [validate]
    params: [blob_name, container_name, processing_options]
    receives:
      source_metadata: "validate.result.metadata"

  upload_cog:
    handler: raster_upload_cog
    depends_on: [create_cog]
    receives:
      cog_local_path: "create_cog.result.cog_path"
      file_size: "create_cog.result.file_size"

  create_stac_item:
    handler: stac_create_item
    depends_on: [upload_cog]
    params: [collection_id]
    receives:
      blob_url: "upload_cog.result.blob_url"
      metadata: "validate.result.metadata"

  register_catalog:
    handler: catalog_register_raster
    depends_on: [create_stac_item]
    receives:
      stac_item_id: "create_stac_item.result.stac_item_id"

finalize:
  handler: raster_finalize
```

### Zarr Ingest Pipeline

```yaml
# workflows/ingest_zarr.yaml
workflow: ingest_zarr
description: "Ingest native Zarr store"
reversed_by: unpublish_zarr

parameters:
  source_url: {type: str, required: true}
  dataset_id: {type: str, required: true}
  target_container: {type: str, default: "zarr"}
  rechunk: {type: bool, default: false}
  collection_id: {type: str, required: true}

tasks:
  validate:
    handler: zarr_validate_store
    params: [source_url, dataset_id]

  copy_blobs:
    handler: zarr_copy_single_blob
    depends_on: [validate]
    fan_out:
      source: "validate.result.blob_list"
      item_param: "blob_path"
    params: [source_url, target_container]

  rechunk:
    handler: zarr_rechunk_store
    depends_on: [copy_blobs]
    when: "params.rechunk"
    params: [target_container, dataset_id]

  consolidate:
    handler: zarr_consolidate_metadata
    depends_on:
      - copy_blobs
      - rechunk?
    params: [target_container, dataset_id]

  create_stac_item:
    handler: stac_create_item
    depends_on: [consolidate]
    params: [collection_id, dataset_id]
    receives:
      zarr_metadata: "validate.result.metadata"

  register:
    handler: zarr_register_metadata
    depends_on: [create_stac_item]
    receives:
      stac_item_id: "create_stac_item.result.stac_item_id"

finalize:
  handler: zarr_finalize
```

### Unpublish Vector

```yaml
# workflows/unpublish_vector.yaml
workflow: unpublish_vector
description: "Drop PostGIS table + metadata"
reverses: [vector_docker_etl]

parameters:
  table_name: {type: str, required: true}
  schema_name: {type: str, default: "geo"}
  identifier: {type: str, required: true}
  force_approved: {type: bool, default: false}

tasks:
  inventory:
    handler: unpublish_inventory_vector
    params: [table_name, schema_name, identifier, force_approved]

  drop_table:
    handler: unpublish_cleanup_postgis
    depends_on: [inventory]
    receives:
      table_name: "inventory.result.table_name"
      views: "inventory.result.split_views"

  cleanup_catalog:
    handler: unpublish_cleanup_catalog
    depends_on: [drop_table]
    params: [identifier]

finalize:
  handler: unpublish_finalize
```

---

## What Replaces Service Bus

### Current: Service Bus as Coordination Mechanism

```
Orchestrator → SB(geospatial-jobs) → CoreMachine creates tasks
    → SB(container-tasks) → Docker Worker polls → executes
    → SB(geospatial-jobs) ← stage_complete signal
```

**Service Bus currently serves 3 roles:**

| Role | Queue | What Happens |
|------|-------|-------------|
| **Job dispatch** | geospatial-jobs | Orchestrator sends job message → CoreMachine creates tasks |
| **Task dispatch** | container-tasks | Orchestrator sends task message → Worker executes handler |
| **Completion signaling** | geospatial-jobs | Worker sends stage_complete → Orchestrator advances stage |

### After: PostgreSQL as Coordination Mechanism

**All three roles replaced by database polling:**

| Role | Current (SB) | After (PostgreSQL) |
|------|-------------|-------------------|
| **Job dispatch** | JobQueueMessage → geospatial-jobs | INSERT INTO workflow_runs → orchestrator poll detects it |
| **Task dispatch** | TaskQueueMessage → container-tasks | Orchestrator marks task `ready` → worker poll claims it |
| **Completion signaling** | StageCompleteMessage → geospatial-jobs | Worker writes `completed` + result → orchestrator poll evaluates successors |

### Two-Loop Architecture (Orchestrator + N Workers)

The system runs as **two independent polling loops** against the same PostgreSQL tables:

```
┌─────────────────────────────────────────┐
│          DAG Orchestrator               │
│       (lightweight process)             │
│                                         │
│  Poll loop (every 2-5 seconds):        │
│                                         │
│  1. Detect new workflow submissions     │
│     → Initialize DAG (create task       │
│       instances + dependency edges)     │
│     → Root tasks (no deps) marked       │
│       'ready' immediately               │
│                                         │
│  2. Detect newly completed tasks        │
│     → Evaluate successor dependencies   │
│     → Expand fan-outs (create N task    │
│       instances from array result)      │
│     → Evaluate `when:` conditions       │
│     → Mark successors 'ready' or        │
│       'skipped'                         │
│                                         │
│  3. Detect completed workflows          │
│     → Run finalize handler              │
│     → Mark workflow_run 'completed'     │
│                                         │
│  NEVER executes task handlers.          │
│  Only manages DAG state transitions.    │
└──────────────┬──────────────────────────┘
               │
               │  writes status='ready' rows
               │
        ┌──────┴───────────────────────────┐
        │         PostgreSQL               │
        │   app.workflow_tasks             │
        │                                  │
        │   The shared work queue.         │
        │   Workers claim rows via         │
        │   SELECT FOR UPDATE SKIP LOCKED  │
        └──┬──────────┬──────────┬─────────┘
           │          │          │
      ┌────┴───┐ ┌───┴────┐ ┌───┴────┐
      │Worker A│ │Worker B│ │Worker C│
      │(Docker)│ │(Docker)│ │(Docker)│
      └────────┘ └────────┘ └────────┘
      Each worker: independent poll loop
      Claims tasks atomically via SKIP LOCKED
      Executes handler, writes result to DB
```

### Horizontal Scaling: `SELECT FOR UPDATE SKIP LOCKED`

Service Bus provides horizontal scaling via **competing consumers** (peek-lock). PostgreSQL provides the exact same pattern via `FOR UPDATE SKIP LOCKED` — a first-class primitive designed for work-queue scenarios.

**How it works:**

```sql
-- Each worker runs this in a loop:
BEGIN;

-- Claim one unclaimed task. SKIP LOCKED means:
-- if Worker A has locked row 1, Worker B skips it and grabs row 2.
-- No double-processing. No coordination needed.
SELECT * FROM app.workflow_tasks
WHERE status = 'ready'
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- If got a row, atomically mark it claimed
UPDATE app.workflow_tasks
SET status = 'running',
    claimed_by = 'worker-A',
    started_at = NOW(),
    last_pulse = NOW()
WHERE task_instance_id = $1;

COMMIT;
```

After handler execution:

```sql
-- Write result (no transaction needed — single atomic UPDATE)
UPDATE app.workflow_tasks
SET status = 'completed',       -- or 'failed'
    result_data = $2::jsonb,
    completed_at = NOW()
WHERE task_instance_id = $1;
```

**Fan-out example — 100 blob copy tasks, 3 workers:**

```
Orchestrator: expands fan-out → INSERT 100 rows with status='ready'

Worker A poll: SELECT ... SKIP LOCKED → claims task 1, executes
Worker B poll: SELECT ... SKIP LOCKED → claims task 2, executes
Worker C poll: SELECT ... SKIP LOCKED → claims task 3, executes
Worker A finishes task 1 → writes result → claims task 4
Worker B finishes task 2 → writes result → claims task 5
... continues until all 100 claimed and completed

Orchestrator poll: detects all 100 completed → evaluates successor → marks next task 'ready'
```

Each worker processes tasks as fast as it can. No coordinator needed for distribution — PostgreSQL's row-level locking handles it. Add more workers = more throughput, same code.

### Side-by-Side: Service Bus vs PostgreSQL `SKIP LOCKED`

| Concern | Service Bus | PostgreSQL `SKIP LOCKED` |
|---------|------------|--------------------------|
| **Competing consumers** | Peek-lock (built-in) | `FOR UPDATE SKIP LOCKED` (built-in) |
| **Exactly-once processing** | Peek-lock + complete_message | Atomic `UPDATE SET status='running'` in same txn |
| **Visibility timeout** | Lock duration (5 min default, renewable to 2 hrs) | Heartbeat column + janitor reclaims stale |
| **Dead letter queue** | Separate DLQ after N delivery attempts | `status='failed'` + `retry_count` column |
| **Fan-out of 100 tasks** | 100 messages sent individually (crash after 50 = orphans) | 100 rows in single transaction (atomic) |
| **Scaling workers** | Add more consumers, SB distributes via peek-lock | Add more workers, `SKIP LOCKED` distributes |
| **Backpressure** | Messages accumulate in queue | Rows accumulate with `status='ready'` |
| **Priority** | Message priority or sessions | `ORDER BY priority, created_at` in SELECT |
| **Monitoring** | Azure Portal + peek endpoints + DLQ count | `SELECT status, COUNT(*) GROUP BY status` |
| **Cost** | Per-message pricing (~$0.05/10K operations) | Already have PostgreSQL |
| **Complexity** | AMQP protocol, connection warmup, credential rotation, `_open()` bugs | Standard SQL queries |
| **Failure recovery** | Message auto-redelivery after lock timeout | Janitor query: stale heartbeat → reset to 'ready' |
| **Debugging** | Peek + DLQ inspection (Azure Portal or SDK) | `SELECT * FROM workflow_tasks WHERE status='failed'` |
| **Transactional fan-out** | No — messages sent one at a time, crash = partial | Yes — all rows in one transaction |
| **Queryable state** | No — messages are opaque until consumed | Yes — full SQL queryability on all tasks |

### What You Gain Over Service Bus

1. **Transactional fan-out** — INSERT 100 tasks in one transaction. With SB, crashing after sending 50 messages creates 50 orphan tasks with no matching DB records. This is accepted risk G in `V10_DECISIONS.md` — eliminated by this migration.

2. **Atomic claim + parameter resolution** — worker claims task AND reads predecessor results in one transaction. With SB, task parameters are frozen at dispatch time and can't reference results that arrive later.

3. **No AMQP warmup bugs** — `service_bus.py` has 50+ lines dealing with `sender._open()` to prevent silent message loss (14 DEC 2025 critical fix). Gone.

4. **No DLQ management** — failed tasks are just rows with `status='failed'`. Query, retry, or ignore — all via SQL.

5. **Queryable state** — "show me all running tasks for workflow X" is a SELECT, not a peek + parse. Dashboard gets real-time task status for free.

6. **Eliminates accepted risk G** — non-atomic task create + Service Bus send. The DB insert IS the dispatch.

7. **Eliminates accepted risk H** — `_advance_stage` double infrastructure failure. Stage advancement is a status UPDATE, not a message send.

### What You Lose (And Why It Doesn't Matter)

1. **Push vs pull latency** — SB delivers messages immediately when a worker is waiting. DB polling has up to `poll_interval` delay (2-5 seconds). For ETL jobs taking minutes, 2-5 seconds is negligible. If latency matters for specific workflows, reduce `poll_interval` to 1 second.

2. **Azure Functions scale controller** — SB integrates with Functions auto-scaling (scale based on queue depth). Your direction is Docker-first, so this doesn't apply. For Docker, horizontal scaling is explicit (add container instances).

3. **Message scheduling** — SB supports scheduled delivery (used for retry backoff). Replacement: add `execute_after TIMESTAMPTZ` column to `workflow_tasks`, filter in poll query: `WHERE status='ready' AND (execute_after IS NULL OR execute_after < NOW())`.

### Stale Task Recovery (Replaces SB Lock Timeout)

Service Bus auto-redelivers messages when the peek-lock expires. With DB polling, the existing janitor pattern handles this:

```sql
-- Reclaim tasks from dead/stuck workers (janitor runs every 60s)
-- This replaces Service Bus lock timeout + auto-redelivery
UPDATE app.workflow_tasks
SET status = 'ready',
    claimed_by = NULL,
    retry_count = retry_count + 1,
    error_details = 'Worker unresponsive — reclaimed by janitor'
WHERE status = 'running'
  AND last_pulse < NOW() - INTERVAL '5 minutes'
  AND retry_count < 3;

-- Permanently fail after max retries (replaces SB dead-letter queue)
UPDATE app.workflow_tasks
SET status = 'failed',
    error_details = 'Max retries exceeded — worker unresponsive after 3 attempts'
WHERE status = 'running'
  AND last_pulse < NOW() - INTERVAL '5 minutes'
  AND retry_count >= 3;
```

Workers update `last_pulse` periodically during handler execution. This is identical to the existing heartbeat in `docker_service.py` — just targeting a different table.

### Concrete Worker Code Change

Current `docker_service.py:BackgroundQueueWorker._run_loop()`:

```python
# Current: Poll Service Bus
receiver = sb_client.get_queue_receiver("container-tasks")
messages = receiver.receive_messages(max_message_count=1, max_wait_time=30)
for msg in messages:
    result = core_machine.process_task_message(parse(msg))
    receiver.complete_message(msg)
```

Becomes:

```python
# After: Poll PostgreSQL with SKIP LOCKED
while True:
    task = None
    with db.transaction() as tx:
        row = tx.execute("""
            SELECT * FROM app.workflow_tasks
            WHERE status = 'ready'
              AND (execute_after IS NULL OR execute_after < NOW())
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """).fetchone()

        if row:
            tx.execute("""
                UPDATE app.workflow_tasks
                SET status = 'running',
                    claimed_by = %s,
                    started_at = NOW(),
                    last_pulse = NOW()
                WHERE task_instance_id = %s
            """, (self.worker_id, row.task_instance_id))
            task = row

    if task:
        # Resolve parameters (job params + predecessor results)
        params = resolve_task_params(task)

        # Execute handler — same contract as today
        handler = ALL_HANDLERS[task.handler]
        try:
            result = handler(params)
            status = 'completed' if result.get('success') else 'failed'
        except Exception as e:
            result = {'success': False, 'error': str(e), 'error_type': type(e).__name__}
            status = 'failed'

        # Write result — single atomic UPDATE
        db.execute("""
            UPDATE app.workflow_tasks
            SET status = %s,
                result_data = %s::jsonb,
                error_details = %s,
                completed_at = NOW()
            WHERE task_instance_id = %s
        """, (status, json.dumps(result),
              result.get('error'), task.task_instance_id))
    else:
        time.sleep(3)  # No work available, back off
```

Same poll loop pattern, different poll target. Workers still scale horizontally — add more Docker instances, they all compete via `SKIP LOCKED`.

### The Orchestrator (DAG Evaluation Engine)

The orchestrator **never executes handlers**. It only manages DAG state transitions:

```python
class DAGOrchestrator:
    """
    Single-process DAG evaluation engine.
    Polls PostgreSQL for state changes and advances workflow execution.
    Workers do all the heavy lifting — this just manages the graph.
    """

    def __init__(self, workflow_registry):
        self.workflows = workflow_registry     # Loaded YAML workflows
        self.poll_interval = 3                 # seconds

    def run(self):
        """Main poll loop — runs forever."""
        while True:
            # 1. Initialize new workflow submissions
            #    (INSERT workflow_tasks + workflow_task_deps from YAML definition)
            new_runs = self._get_pending_runs()
            for run in new_runs:
                self._initialize_dag(run)

            # 2. Evaluate completed tasks → mark successors ready
            #    (This is the core DAG advancement logic)
            newly_completed = self._get_newly_completed_tasks()
            for task in newly_completed:
                self._evaluate_successors(task)

            # 3. Check for completed workflows → run finalize
            self._check_workflow_completions()

            time.sleep(self.poll_interval)

    def _evaluate_successors(self, completed_task):
        """After a task completes, check if successors are now ready."""
        successors = self._get_successor_tasks(completed_task.task_instance_id)
        for successor in successors:
            if self._all_deps_satisfied(successor.task_instance_id):
                if successor.fan_out_config:
                    # Fan-out: create N task instances from array result
                    self._expand_fan_out(successor, completed_task.result_data)
                elif successor.when_clause:
                    # Conditional: evaluate and mark ready or skipped
                    if self._evaluate_condition(successor):
                        self._mark_ready(successor)
                    else:
                        self._mark_skipped(successor)
                else:
                    self._mark_ready(successor)

    def _expand_fan_out(self, template_task, source_result):
        """Create N task instances from a fan-out source array."""
        source_path = template_task.fan_out_config['source']
        items = self._resolve_dotted_path(source_result, source_path)

        # Atomic: insert all N instances in one transaction
        with db.transaction() as tx:
            for i, item in enumerate(items):
                instance_id = f"{template_task.task_instance_id}_{i}"
                tx.execute("""
                    INSERT INTO app.workflow_tasks
                    (task_instance_id, run_id, task_name, handler,
                     status, fan_out_index, parameters)
                    VALUES (%s, %s, %s, %s, 'ready', %s, %s::jsonb)
                """, (instance_id, template_task.run_id,
                      f"{template_task.task_name}_{i}",
                      template_task.handler, i,
                      json.dumps({**base_params, item_param: item})))

            # Update template task to 'expanded' (not executed itself)
            tx.execute("""
                UPDATE app.workflow_tasks
                SET status = 'expanded', result_data = %s::jsonb
                WHERE task_instance_id = %s
            """, (json.dumps({'fan_out_count': len(items)}),
                  template_task.task_instance_id))
```

---

## Gateway / Platform Integration

### Current: Gateway Sends to Service Bus

The gateway (`rmhgeogateway`, APP_MODE=platform) is the B2B-facing Function App — the anti-corruption layer between external clients (DDH) and the internal orchestration system. It exposes 20 platform endpoints (submit, status, approvals, catalog, unpublish, registry).

**Current `/api/platform/submit` flow** (from `triggers/platform/submit.py`, 556 lines):

```
B2B Client POST /api/platform/submit
    ↓
1. Validate PlatformRequest (Pydantic)
2. Generate request_id = SHA256(dataset_id|resource_id|version_id)
3. Translate DDH format → CoreMachine job_type + params
4. AssetService.find_or_create_asset() → WRITES TO DB
5. AssetService.get_or_overwrite_release() → WRITES TO DB
6. Finalize ordinals (table_name, stac_item_id) → WRITES TO DB
7. create_and_submit_job():
   a. validate_job_parameters() → validation only
   b. generate_job_id = SHA256(job_type + params) → deterministic
   c. Create JobRecord(QUEUED) → WRITES TO DB
   d. Record JOB_CREATED event → WRITES TO DB
   e. Link job to release → WRITES TO DB
   f. Store PlatformRequest tracking → WRITES TO DB
   g. ServiceBusRepository.send_message(JobQueueMessage) ← THE ONLY SB CALL
    ↓
HTTP 202 Accepted {request_id, job_id, monitor_url}
```

**Key observation**: Steps 1-7f are all database writes. Step 7g is the *only* Service Bus interaction. The gateway already does 95% of its work via PostgreSQL.

**Current `/api/platform/status/{id}` flow** — 100% database reads:

```
B2B Client GET /api/platform/status/{id}
    ↓
1. Auto-detect ID type (request_id, job_id, release_id, asset_id)
2. SELECT FROM app.jobs → job status, stage
3. SELECT FROM app.job_events → progress checkpoints
4. SELECT FROM app.tasks → task summary (count by status)
5. SELECT FROM app.asset_releases → outputs, approval state
6. Generate service URLs (TiTiler preview, tiles)
    ↓
HTTP 200 {job_status, progress, outputs, services, approval}
```

No Service Bus involved at all. The B2B client polls the gateway, which queries the database.

### After: Gateway Writes Directly to Workflow Tables

**The database IS the relay.** Replace the single `send_message()` call with an `INSERT`:

```
B2B Client POST /api/platform/submit
    ↓
Steps 1-7f: IDENTICAL (validation, asset/release, ordinals, tracking)
    ↓
Step 7g changes from:
  ServiceBusRepository.send_message(JobQueueMessage)    ← REMOVE
to:
  INSERT INTO app.workflow_runs (                        ← ADD
    run_id, workflow_name, parameters, status
  ) VALUES ($job_id, $workflow_name, $params, 'pending')

  -- Root tasks (no dependencies) created by orchestrator on next poll tick
  -- OR: gateway can create all task instances inline for faster startup
    ↓
HTTP 202 Accepted {request_id, job_id, monitor_url}
```

**Status queries change table names but keep the same pattern:**

```
B2B Client GET /api/platform/status/{id}
    ↓
1-2: Same auto-detect + lookup
3: SELECT FROM app.workflow_tasks → task status breakdown (replaces app.tasks)
4: SELECT FROM app.workflow_runs → workflow status (replaces app.jobs)
5-6: Same (asset_releases, service URLs unchanged)
    ↓
HTTP 200 {job_status, progress, outputs, services, approval}
```

### Three-Process Architecture (After Migration)

```
┌──────────────────────────────────────────────────────────────┐
│                    B2B Client (DDH)                           │
│                                                              │
│  POST /api/platform/submit     GET /api/platform/status/{id} │
│  (submits work)                (polls for progress — THEY    │
│                                 do the polling, not us)       │
└─────────────┬──────────────────────────┬─────────────────────┘
              │                          │
              ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│  GATEWAY (rmhgeogateway — Azure Function App)               │
│  APP_MODE=platform                                          │
│                                                             │
│  Responsibilities:                                          │
│  - Authentication & ACL (future: API keys or Azure AD)      │
│  - PlatformRequest validation (Pydantic)                    │
│  - DDH → workflow translation (data type inference)         │
│  - Asset/Release entity management                          │
│  - Ordinal finalization (table names, STAC IDs)             │
│  - INSERT INTO app.workflow_runs (replaces SB send)         │
│  - Status queries (read-only from DB)                       │
│  - Approval/reject/revoke lifecycle                         │
│  - Catalog lookup endpoints                                 │
│                                                             │
│  Does NOT: execute handlers, manage DAG, poll for work      │
│                                                             │
│  20 endpoints: submit, status, approvals, catalog,          │
│                unpublish, registry, health, failures        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │  WRITES: app.workflow_runs (submit)
                          │  READS:  app.workflow_tasks (status)
                          │
                   ┌──────┴──────────────────────────────┐
                   │          PostgreSQL                  │
                   │   rmhpostgres.postgres.database.     │
                   │   azure.com                          │
                   │                                      │
                   │   app.workflow_runs    ← gateway     │
                   │   app.workflow_tasks   ← orch + work │
                   │   app.workflow_task_deps             │
                   │   app.assets          ← gateway      │
                   │   app.asset_releases  ← gateway      │
                   │                                      │
                   │   The single source of truth.        │
                   │   No queues, no messages, no AMQP.   │
                   └──┬──────────────┬──────────────┬─────┘
                      │              │              │
                 POLLS│         POLLS│         POLLS│
                      │              │              │
        ┌─────────────┴──┐  ┌───────┴────┐  ┌─────┴──────┐
        │  ORCHESTRATOR  │  │  Worker A  │  │  Worker B  │
        │  (process)     │  │  (Docker)  │  │  (Docker)  │
        │                │  │            │  │            │
        │ Poll loop:     │  │ Poll loop: │  │ Poll loop: │
        │ - New runs     │  │ - Claim    │  │ - Claim    │
        │   → init DAG   │  │   ready    │  │   ready    │
        │ - Completed    │  │   task via │  │   task via │
        │   tasks        │  │   SKIP     │  │   SKIP     │
        │   → evaluate   │  │   LOCKED   │  │   LOCKED   │
        │   successors   │  │ - Execute  │  │ - Execute  │
        │ - Fan-out      │  │   handler  │  │   handler  │
        │   → expand     │  │ - Write    │  │ - Write    │
        │ - Workflow      │  │   result   │  │   result   │
        │   complete     │  │            │  │            │
        │   → finalize   │  │ Has: GDAL  │  │ Has: GDAL  │
        │                │  │ geopandas  │  │ geopandas  │
        │ Lightweight:   │  │ xarray     │  │ xarray     │
        │ no GDAL, no    │  │ rasterio   │  │ rasterio   │
        │ heavy libs     │  │            │  │            │
        └────────────────┘  └────────────┘  └────────────┘
```

### What Changes in the Gateway

| Component | Current | After | Effort |
|-----------|---------|-------|--------|
| `triggers/platform/submit.py` | Steps 1-7f write DB, step 7g sends SB | Steps 1-7f identical, 7g writes `workflow_runs` | **Minimal** — change one function call |
| `triggers/trigger_platform_status.py` | Reads `app.jobs` + `app.tasks` | Reads `app.workflow_runs` + `app.workflow_tasks` | **Low** — change table names in queries |
| `services/platform_job_submit.py` | `create_and_submit_job()` sends to SB | `create_and_submit_workflow()` writes to DB | **Low** — replace send with INSERT |
| `triggers/platform/unpublish.py` | Creates unpublish job → SB | Creates unpublish workflow → DB | **Low** — same change pattern |
| `triggers/platform/resubmit.py` | Resubmits to SB | Resets workflow_run status to 'pending' | **Low** — UPDATE instead of send |
| `triggers/platform/platform_bp.py` | Blueprint registration | **Unchanged** — all 20 endpoints stay | **Zero** |
| `services/platform_translation.py` | DDH → job_type + params | DDH → workflow_name + params | **Minimal** — rename |
| `services/platform_response.py` | Response builders | Query different tables | **Low** |
| Asset/Release management | All DB operations | **Unchanged** | **Zero** |
| Approval endpoints | All DB operations | **Unchanged** | **Zero** |
| Catalog endpoints | All DB operations | **Unchanged** | **Zero** |

**Total gateway change**: ~200 lines modified across 4 files. No new files needed. The gateway's core responsibility (auth, ACL, validation, translation, entity management) is entirely unaffected.

### What Changes in Status Queries

The B2B client polls `/api/platform/status/{id}` — this is their polling loop, not ours. The status endpoint currently reads from `app.jobs` and `app.tasks`. After migration it reads from `app.workflow_runs` and `app.workflow_tasks`.

The status response structure stays identical:

```json
{
  "success": true,
  "request_id": "a3f2c1b8...",
  "job_status": "processing",
  "progress": {
    "total_tasks": 6,
    "completed": 3,
    "running": 1,
    "pending": 2,
    "current_task": "load_data"
  },
  "outputs": {
    "blob_path": "/vsiaz/silver/...",
    "stac_item_id": "aerial-imagery-2024-site-alpha-ord1"
  },
  "services": {
    "preview": "https://titiler.../preview?url=...",
    "tiles": "https://titiler.../tiles/?url=..."
  }
}
```

**Improvement**: DAG-based status is richer than stage-based. Instead of "stage 2 of 5" (opaque), clients see "3 of 6 tasks completed, currently running load_data" (meaningful task names from YAML).

### What Stays the Same

These platform capabilities are **100% unchanged** by the migration:

- Authentication & ACL (future auth system — not affected)
- PlatformRequest validation (Pydantic schema)
- DDH → internal translation (data type inference, parameter mapping)
- Asset/Release entity lifecycle (find_or_create, ordinals, versioning)
- Approval/reject/revoke workflow
- Catalog lookup endpoints (by dataset_id, resource_id, asset_id)
- Platform registry (B2B platform definitions)
- Health and failure diagnostics

### Orchestrator Deployment Options

The DAG orchestrator is a lightweight process — it never executes handlers (no GDAL, no heavy libs). Two deployment options:

**Option A — Separate lightweight container:**
```
Gateway:       Azure Function App (rmhgeogateway) — HTTP only
Orchestrator:  Lightweight Docker container — poll loop only
Workers:       Heavy Docker containers (rmhheavyapi × N) — GDAL, geopandas, etc.
```

**Option B — Co-located with gateway Function App:**
```
Gateway:       Azure Function App — HTTP endpoints + timer-triggered poll loop
Workers:       Heavy Docker containers (rmhheavyapi × N)
```

Option B is simpler (fewer deployments) but couples the orchestrator to Function App lifecycle. Option A is cleaner separation. Either works — the orchestrator is ~400 lines of Python with no heavy dependencies.

---

## Migration Path — Versioned Phases

### Version Roadmap (Revised — Strangler Fig)

| Version | Phase | What | Breaking? |
|---------|-------|------|-----------|
| **v0.10.3** | F1 | Worker polls DB instead of Service Bus | No | **DONE** |
| **v0.10.4** | ~~F2~~ | ~~Orchestrator → 60s timer trigger~~ | ~~No~~ | **ELIMINATED** (strangler fig) |
| **v0.11.0** | F-DAG | DAG Foundation: loader, tables, initializer, resolver, orchestrator, gateway routing | Yes (schema — additive) |
| **v0.11.1** | F4 | Handler decomposition (monolithic → atomic) | No |
| **v0.11.2+** | F5 | Port workflows tier by tier (strangler fig — incremental) | No (per-workflow rollback) |
| **v0.12.0** | F6 | Cleanup: remove CoreMachine, Service Bus, Python jobs | Yes (infra) |

**Migration approach**: Strangler fig. DAG Brain (Docker) runs alongside Function App orchestrator. New YAML workflows go to DAG Brain; legacy Python jobs stay on CoreMachine. Ported one workflow at a time, each SIEGE-validated. When all 14 are proven, remove legacy system in one clean cut.

**What changed from original roadmap**:
- **F2 (timer trigger) eliminated** — the DAG Brain IS the new orchestrator. No point converting Function App to polling when we're about to replace it.
- **F3 (remove SB) deferred** — SB keeps working for legacy jobs during migration. Removed once at the end in F6.
- **F6 (Docker lift) free** — DAG Brain starts as Docker from day one.
- **19 stories instead of 25. 22-32 days instead of 25-38.**

**End state at v0.12.0**: Function App gateway + Docker DAG Brain + Docker workers + PostgreSQL. Zero Service Bus.

```
v0.12.0 Architecture:
  Gateway (Function App) — HTTP endpoints, validation, entity management, B2B integration
  DAG Brain (Docker)     — poll loop, DAG evaluation, brain guard HA
  Workers (Docker × N)   — SKIP LOCKED poll, handler execution, GDAL/xarray/etc.
  PostgreSQL             — single coordination mechanism (no queues, no AMQP)
```

The gateway remains a Function App — right tool for HTTP request/response with Azure's scaling, auth hooks, and APIM integration. Docker is for long-running poll loops and heavy compute.

Major version (v1.0.0) tracks with production deployment, not this infrastructure work.

---

### Phase 1: Worker Polls DB (v0.10.3)

**Risk**: Low — worker already runs a polling loop against Service Bus. Same pattern, different poll target.
**Effort**: Low-Medium — replace SB consumer with `SELECT FOR UPDATE SKIP LOCKED` in `docker_service.py`.
**Breaking**: No — CoreMachine, job definitions, handlers all unchanged.

The Docker worker's `BackgroundQueueWorker._run_loop()` currently polls Service Bus `container-tasks` queue. The queue was always just a replica of DB state — tasks were written to the database AND sent as messages. Remove the middleman:

1. Replace SB `receive_messages()` with `SELECT ... FOR UPDATE SKIP LOCKED` against `app.tasks`
2. Replace `complete_message()` with `UPDATE app.tasks SET status='completed'`
3. Worker heartbeat writes `last_pulse` to task row (replaces SB lock renewal)
4. Keep SB for orchestrator→worker dispatch (Phase 2 removes this)

**Validation**: Submit job → worker picks up task from DB → handler executes → results written. Same end-to-end behavior, no SB involved in task dispatch.

### Phase 2: Orchestrator → Timer Trigger (v0.10.4)

**Risk**: Low — same CoreMachine logic, just poll-driven instead of event-driven.
**Effort**: Low — replace SB queue trigger with 60-second Azure Functions timer trigger.
**Breaking**: No — same tables, same state machine, same handlers.

The orchestrator Function App currently triggers on SB queue messages (job dispatch + stage_complete signals). Convert to a timer trigger that polls for state changes:

1. Add 60-second timer trigger that polls `app.jobs` for pending work
2. CoreMachine evaluates stage readiness from DB state (tasks completed → advance stage)
3. Remove `_should_signal_stage_complete()` — orchestrator detects completion by polling
4. Remove `stage_complete` SB message sending from workers
5. Accept Function App cold-start latency (worst case: 60s vs instant SB trigger — negligible for ETL)

**Validation**: Same job lifecycle, same stage progression, same handler execution. Latency increases by up to 60s between stages — invisible for ETL jobs taking minutes.

### Phase 3: Remove Service Bus (v0.11.0)

**Risk**: Low — by this point neither worker nor orchestrator uses SB.
**Effort**: Low — delete code and Azure resources.
**Breaking**: Yes (infrastructure) — Service Bus Azure resources removed, `service_bus.py` deleted.

1. Remove `infrastructure/service_bus.py` (800+ lines)
2. Remove `triggers/service_bus/` directory (job_handler, task_handler, error_handler)
3. Remove SB connection strings from environment config
4. Remove 3 Azure Service Bus queues (`geospatial-jobs`, `container-tasks`, `stage-complete`)
5. Remove SB-related config fields from `QueueConfig`
6. Clean up `docker_service.py` — remove any remaining SB references

**What this eliminates**: AMQP warmup bugs, `_open()` silent message loss, DLQ management, peek-lock complexity, SB credential rotation, accepted risks G and H from V10_DECISIONS.md, ~$50/month Azure cost.

### Phase 4: Handler Decomposition (v0.11.1)

**Risk**: Zero — existing job definitions still work via wrapper handlers.
**Effort**: Medium — break monolithic handlers into composable functions.
**Breaking**: No — wrappers preserve existing behavior.

1. Extract `vector_docker_complete` → 6 atomic handlers
2. Extract `raster_docker_complete` → 5 atomic handlers
3. Standardize `stac_create_item` as shared handler (currently duplicated in raster, zarr, virtualzarr)
4. Standardize `catalog_register_asset` as shared handler
5. Create wrapper handler that calls atomic handlers in sequence (backward compat)
6. Update `ALL_HANDLERS` registry with new atomic handlers

**Validation**: Existing job types still work identically through wrappers. New atomic handlers also registered and testable independently. SIEGE regression test.

### Phase 5: YAML Workflows + DAG Orchestrator (v0.12.0)

**Risk**: Medium — new orchestration paradigm, but coexists with CoreMachine during transition.
**Effort**: High — YAML parser, DAG tables, orchestrator poll loop, parameter resolution, fan-out, conditionals.
**Breaking**: Yes (schema) — new tables, new submission path.

**5a: YAML Workflow Loader**

1. Build `WorkflowLoader` — parse YAML, validate schema, detect cycles
2. Build `WorkflowRegistry` — load all YAML files from `workflows/` directory
3. Add DAG database tables (`workflow_runs`, `workflow_tasks`, `workflow_task_deps`)
4. Build `DAGInitializer` — create task instances + dependency edges from YAML

**5b: DAG Orchestrator**

1. Build `DAGOrchestrator` with poll loop (detects new runs, evaluates DAG, promotes tasks)
2. Implement parameter resolution (`receives:` dotted path extraction)
3. Implement fan-out expansion (create N task instances from array result)
4. Implement conditional evaluation (`when:` clause)
5. Implement completion detection and `finalize` handler
6. Worker polls `app.workflow_tasks` via `SKIP LOCKED`

**5c: Gateway Migration**

1. Modify `services/platform_job_submit.py`: replace job creation with `INSERT INTO workflow_runs`
2. Modify `triggers/trigger_platform_status.py`: query `workflow_runs` + `workflow_tasks`
3. Modify unpublish/resubmit: create workflow runs instead of legacy jobs
4. Update `services/platform_translation.py`: `job_type` → `workflow_name` mapping
5. Verify B2B polling contract unchanged (same response shape, richer progress info)

**5d: Convert Python Jobs to YAML + Cleanup**

1. Convert all 14 Python job types to YAML workflow files
2. Verify all workflows pass end-to-end testing (SIEGE campaign)
3. Remove `core/machine.py` (CoreMachine)
4. Remove `jobs/*.py` Python job classes (14 files)
5. Remove `jobs/base.py`, `jobs/mixins.py`

**Gateway keeps**: All 20 platform endpoints, auth/ACL, asset/release management, approvals, catalog — zero changes.

### Phase 6: Orchestrator → Docker (v0.12.1)

**Risk**: Zero — standing up a new Docker container that takes over orchestration duties.
**Effort**: Trivial — ~20 lines changed. Same poll loop, different host.
**Breaking**: No — Function App retains all `/api/platform/*` B2B endpoints unchanged. Only the orchestration timer trigger is removed from it.

**Key architecture point**: The Function App currently serves two roles: (1) B2B gateway (`/api/platform/*` HTTP endpoints) and (2) orchestrator (timer/queue triggers that advance job stages). Phase 6 only replaces role #2. The Function App stays as the B2B integration point — same URL, same endpoints, same API signature. B2B clients see zero change.

1. Deploy DAGOrchestrator as lightweight Docker container with poll loop
2. Deploy with 2+ instances for HA (advisory lock ensures single-active)
3. Remove orchestration timer trigger from Function App (it keeps all HTTP endpoints)
4. Tiny Docker image: Python + psycopg3, no GDAL/heavy libs

**Result**: Function App = B2B gateway only (HTTP). Docker orchestrator = DAG evaluation only (poll loop). Clean separation.


---

## Extractability Assessment Summary

### By Pipeline Family

| Pipeline | Current Handlers | Atomic Handlers | DAG-Ready |
|----------|-----------------|-----------------|-----------|
| **Vector** (4 jobs) | 2 monolithic | → 7 atomic | 60% — needs decomposition |
| **Raster** (4 jobs) | 2 monolithic | → 6 atomic | 50% — needs decomposition |
| **Zarr** (4 jobs) | 8 staged | → 10 atomic | **80%** — already multi-stage |
| **Unpublish** (4 jobs) | 5 staged | → 5 shared | **70%** — good reuse potential |
| **Utility** (hello_world, validate) | 3 simple | → 3 unchanged | **100%** — already atomic |

### Cross-Cutting Reusable Tasks (Highest Value Extractions)

| Handler | Used By | Current State |
|---------|---------|--------------|
| `tipg_refresh_collections` | All vector workflows | Already isolated in `service_layer_client.py` |
| `stac_create_item` | Raster + zarr (6 workflows) | Duplicated inline — needs extraction |
| `catalog_register_asset` | All forward workflows (8+) | Scattered — needs unified interface |
| `catalog_deregister_asset` | All unpublish workflows (4) | Scattered — needs unified interface |
| `validate_blob_exists` | All ingest workflows | Already exists as resource validator |
| `unpublish_delete_blob` | All unpublish workflows | Already a fan-out handler |

---

## Intermediate Data Architecture

### The Problem

In the monolith, data flows through Python memory — one handler loads a GeoDataFrame, validates it, creates a table, and loads chunks, all in one process. In the DAG, each node is a separate worker claim — potentially a different process, potentially after a retry. Small outputs (metadata, counts, paths) fit in `workflow_tasks.result_data` JSONB. Large working data (GeoDataFrames, raster arrays, Zarr chunks) does not.

### Three Categories of Data

| Category | Size | Examples | Where It Lives |
|----------|------|---------|---------------|
| **Metadata** | Bytes-KB | CRS, column names, row counts, geometry type, file paths | `workflow_tasks.result_data` JSONB — handled by param resolver |
| **Working data** | MB-GB | GeoDataFrames, raster arrays, intermediate tile sets | **ETL mount scratch space** — this section |
| **Artifacts** | MB-GB | COGs in silver storage, PostGIS tables, STAC items | Blob storage or PostGIS — already handled |

### Solution: Mount-Based Scratch Space with Deterministic Paths

The Docker worker already has an Azure Files mount (`config.docker.etl_mount_path`). Every workflow run gets a scratch directory. Every node writes its intermediate output to a deterministic path. Downstream nodes read by convention — no lookup table, no registry, just path derivation.

```
Mount layout:
  /mnt/etl/
    /{run_id[:12]}/                          ← per-run scratch directory
      /source/                                ← raw downloaded blob (stream from bronze)
          site_alpha.geojson
      /intermediate/                          ← node outputs (working data between nodes)
          load_source.parquet                 ← GeoDataFrame from load_source node
          validate_and_clean.parquet          ← cleaned GeoDataFrame from validate node
      /checkpoints/                           ← within-node resumability
          load_chunks.checkpoint.json         ← {"last_chunk": 47, "rows_loaded": 4700000}
      /artifacts/                             ← produced outputs before upload to silver
          site_alpha_cog.tif
```

### Path Convention

Every path is deterministic — derivable from `run_id` and `node_name` alone:

```
Intermediate:  /mnt/etl/{run_id[:12]}/intermediate/{node_name}.parquet
Checkpoint:    /mnt/etl/{run_id[:12]}/checkpoints/{node_name}.checkpoint.json
Source:        /mnt/etl/{run_id[:12]}/source/{blob_basename}
Artifact:      /mnt/etl/{run_id[:12]}/artifacts/{output_filename}
Fan-out child: /mnt/etl/{run_id[:12]}/intermediate/{node_name}_fo{index}.parquet
```

No UUIDs in filenames. No lookup table. Given a run_id and node_name, you can always find or reconstruct the path. System params `_run_id` and `_node_name` are injected by the orchestrator into every handler call.

### Handler Convention

Every handler that produces working data follows this pattern:

```python
def handler(params):
    run_id = params['_run_id']
    node_name = params['_node_name']
    mount_path = get_config().docker.etl_mount_path

    scratch_dir = os.path.join(mount_path, run_id[:12], "intermediate")
    os.makedirs(scratch_dir, exist_ok=True)

    output_path = os.path.join(scratch_dir, f"{node_name}.parquet")

    # ... do work, produce gdf ...

    gdf.to_parquet(output_path, engine='pyarrow')

    return {
        "success": True,
        "result": {
            "intermediate_path": output_path,    # ← downstream reads this
            "row_count": len(gdf),
            # ... other metadata in result_data JSONB ...
        }
    }
```

Downstream node receives the path via `receives:` and reads the file:

```yaml
validate_and_clean:
  type: task
  handler: vector_validate_and_clean
  depends_on: [load_source]
  receives:
    source_path: "load_source.intermediate_path"    # parquet path on mount
```

```python
def vector_validate_and_clean(params):
    source_path = params['source_path']       # from receives
    gdf = gpd.read_parquet(source_path)       # read predecessor's output
    # ... validate, clean, write own output ...
```

### Why GeoParquet

| Format | Write (5M rows) | Read (5M rows) | Size | Preserves Geometry + CRS? | Resumable? |
|--------|-----------------|-----------------|------|--------------------------|-----------|
| **GeoParquet** | ~2-4s | ~1-2s | Compact (columnar + snappy) | Yes (WKB column + CRS metadata) | Yes (file on disk) |
| Pickle | ~2s | ~2s | Large | Yes but version-fragile | Yes |
| GeoJSON | ~30s | ~20s | 5-10x larger (text) | Yes | No (must write complete) |
| CSV + WKT | ~20s | ~15s | Large, lossy precision | Lossy | No |

GeoParquet is the standard format for geospatial columnar data. geopandas reads/writes it natively. It preserves column types, geometry, CRS, and is fast enough that I/O overhead is negligible against actual processing time.

For non-geospatial intermediates (raster metadata, Zarr manifests), use JSON:

```python
# Metadata intermediates
with open(os.path.join(scratch_dir, f"{node_name}.json"), 'w') as f:
    json.dump(metadata_dict, f)
```

### Resumability

The mount scratch space is the foundation of retry resumability. When a node fails and retries:

1. **Predecessor outputs are still on the mount** — the retry reads them directly, no re-execution of prior nodes
2. **Checkpoint files record within-node progress** — a handler can resume from where it left off

```
Example: load_chunks fails at chunk 47 of 100

Mount state:
  /mnt/etl/abc123/intermediate/
    load_source.parquet              ← COMPLETED — still here
    validate_and_clean.parquet       ← COMPLETED — still here
  /mnt/etl/abc123/checkpoints/
    load_chunks.checkpoint.json      ← {"last_chunk": 47, "rows_loaded": 4700000}

Retry: Worker claims load_chunks again.
  1. Reads validate_and_clean.parquet (predecessor output — no re-validation)
  2. Reads load_chunks.checkpoint.json (last successful chunk = 47)
  3. Resumes from chunk 48
  4. On success: writes final load_chunks result to result_data
```

### Checkpoint Convention

Handlers that do long-running chunked work write checkpoint files during execution:

```python
def vector_load_chunks(params):
    checkpoint_path = os.path.join(
        get_config().docker.etl_mount_path,
        params['_run_id'][:12], "checkpoints",
        f"{params['_node_name']}.checkpoint.json"
    )

    # Check for existing checkpoint (retry scenario)
    start_chunk = 0
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            cp = json.load(f)
        start_chunk = cp['last_chunk'] + 1
        logger.info(f"Resuming from chunk {start_chunk}")

    for i, chunk in enumerate(chunks[start_chunk:], start=start_chunk):
        # ... INSERT chunk into PostGIS ...

        # Write checkpoint after each successful chunk
        with open(checkpoint_path, 'w') as f:
            json.dump({"last_chunk": i, "rows_loaded": rows_so_far}, f)

    return {"success": True, "result": {"total_rows": total, "chunks_uploaded": n}}
```

This is the same checkpoint pattern the monolithic `vector_docker_complete` already uses — just persisted to the mount instead of held in memory.

### Fan-Out Reads

Fan-out children all read the same intermediate file from their predecessor:

```
validate_and_clean writes: .../intermediate/validate_and_clean.parquet
fan_out creates 3 children:
  child_0 reads: validate_and_clean.parquet (read-only, concurrent safe)
  child_1 reads: validate_and_clean.parquet
  child_2 reads: validate_and_clean.parquet

Each child writes its own output:
  child_0 writes: .../intermediate/create_table_fo0.parquet
  child_1 writes: .../intermediate/create_table_fo1.parquet
  child_2 writes: .../intermediate/create_table_fo2.parquet
```

Concurrent reads of the same parquet file are safe — parquet is read-only after write, no locking needed.

### Lifecycle Management

| Trigger | What Gets Cleaned | Who Does It |
|---------|-------------------|-------------|
| **Run succeeds** | Entire `/mnt/etl/{run_id[:12]}/` directory | Finalize handler (last step) |
| **Run fails** | Kept for debugging | Janitor (D.7) after configurable retention (default: 24 hours) |
| **Node retry** | Previous intermediate for that node overwritten | The retrying handler (same deterministic path) |
| **Mount fills up** | Oldest failed-run directories | Janitor: `find /mnt/etl -maxdepth 1 -mtime +1 -exec rm -rf {} \;` |

The finalize handler runs cleanup as its last step:

```python
def vector_finalize(params):
    # ... aggregate results ...
    scratch_dir = os.path.join(
        get_config().docker.etl_mount_path, params['_run_id'][:12]
    )
    if os.path.exists(scratch_dir):
        shutil.rmtree(scratch_dir)
    return {"success": True, "result": {...}}
```

### Mount Failure Mode

If the mount is unavailable (Azure Files outage, misconfiguration):

- **Fail-fast**: Handlers detect mount unavailability at first `os.makedirs()` or `to_parquet()` call
- **Clear error**: `"ETL mount path /mnt/etl is not writable — check Azure Files mount configuration"`
- **No silent degradation**: We do NOT fall back to in-memory passing. The DAG requires the mount for inter-node data flow. If the mount is down, the worker cannot process DAG workflows.
- **Legacy jobs**: Also affected (they already use the mount for streaming). This is an existing dependency, not a new one.

### Multi-Worker Scaling

Currently one Docker worker instance (`rmhheavyapi`) with one Azure Files mount. All containers on the same App Service Plan share the mount.

If scaling to N worker instances on the same plan: **works automatically** — Azure Files is a shared filesystem. Worker A writes intermediate, Worker B reads it. No changes needed.

If scaling to separate VMs with independent mounts: intermediate data would need to move to blob storage. This is a future scaling concern — the convention (deterministic paths, `intermediate_path` in result_data) would stay the same, just the root path changes from `/mnt/etl/` to `wasbs://scratch/`.

### Cloud-Native Accommodation

The mount is an accommodation for GDAL, geopandas, rasterio, and the geospatial ecosystem that assumes filesystem access. The design is still cloud-native where it matters:

- **Coordination**: PostgreSQL (not filesystem locks)
- **State**: Database (not mount — if the mount disappears, re-run the node)
- **Artifacts**: Blob storage (COGs, Zarr stores — durable)
- **Mount is ephemeral scratch**: Like tmpdir for a Unix process. Working files that don't need to survive beyond the workflow.

The orchestrator never reads the mount. Workers read/write it. The database tracks what happened (result_data JSONB with metadata + paths). If a mount file is missing but the node claims COMPLETED, the orchestrator can detect the inconsistency and force a re-run.

---

## Decisions Made

### Infrastructure & Scaling

- [x] **Worker dispatch model** — Workers poll DB directly via `SELECT FOR UPDATE SKIP LOCKED`. Orchestrator never executes handlers. Workers scale horizontally by adding Docker instances.
- [x] **Horizontal scaling** — PostgreSQL `SKIP LOCKED` provides competing consumers, equivalent to Service Bus peek-lock. N workers claim N different tasks atomically. Each `SKIP LOCKED` query skips rows already locked by other workers — no double-processing, no coordination needed.
- [x] **Worker batch size** — `LIMIT 1` per poll cycle. Each worker instance claims one task, executes it, then polls again. With multiple worker instances (e.g., 3 Docker containers), each independently grabs one unclaimed task per cycle. `LIMIT 1` gives optimal load distribution — every task completion is an immediate rebalancing opportunity. Poll overhead (one SELECT every 3 seconds) is negligible against ETL execution time (seconds to minutes).
- [x] **Orchestrator HA** — Active-passive via PostgreSQL advisory lock. Multiple orchestrator instances deployed; exactly one holds the lease (`pg_try_advisory_lock(73849201)`), others idle and poll for the lock every 10 seconds. If the active instance dies, its connection drops, lock auto-releases, standby grabs it. Failover: ~10-15 seconds. Workers are unaffected during gap (keep executing claimed tasks, just no new tasks promoted to `ready`).
- [x] **Orchestrator deployment** — Separate lightweight Docker container (NOT sidecar to workers). Independent deployment with 2+ instances for HA. Tiny image: Python + psycopg3, no GDAL/heavy libs. Advisory lock ensures exactly-one-active. Three deployments total: Gateway (Function App), Orchestrator (lightweight Docker × 2+), Workers (heavy Docker × N).

### Recovery & Resilience

- [x] **Stale task recovery** — Janitor query replaces SB lock timeout. Workers write `last_pulse` heartbeat; janitor reclaims tasks with stale pulse + exponential backoff via `execute_after`.
- [x] **Retry backoff** — `execute_after` column with exponential backoff (30s, 60s, 120s). Worker poll query filters `WHERE execute_after IS NULL OR execute_after < NOW()`.
- [x] **Message scheduling** — `execute_after TIMESTAMPTZ` column replaces SB scheduled delivery.
- [x] **Timeout enforcement** — Worker self-terminates using existing SIGTERM/signal handling infrastructure (memory watchdog, `docker_context.should_stop()`, graceful shutdown). Per-task `timeout` field in YAML (default: 3600s). Worker checks elapsed time periodically and returns `{success: false, error: "timeout"}`. If worker dies without writing (OOM, pod eviction), janitor's stale-heartbeat query catches it — same recovery path. Orchestrator never actively kills tasks, only observes state.

### Gateway & B2B Contract

- [x] **Gateway relay mechanism** — Gateway writes `INSERT INTO app.workflow_runs` instead of sending to Service Bus. Database is the relay — no queue, no message, no AMQP. Gateway changes are ~200 lines across 4 files.
- [x] **B2B polling contract** — B2B clients poll `/api/platform/status/{id}` (unchanged endpoint). Status queries read from `workflow_runs`/`workflow_tasks` instead of `jobs`/`tasks`. Response shape identical, progress info richer (task names vs opaque stage numbers).
- [x] **Gateway DAG init** — Gateway just INSERTs the `workflow_run` row. Orchestrator initializes the full DAG (task instances + dependency edges) on next poll cycle. Separation of concerns: gateway handles DDH translation + entity management, orchestrator handles DAG topology. One poll-cycle delay (3 seconds) is invisible to B2B clients polling on 10-30 second intervals.

### Workflow Definition

- [x] **Fan-out cardinality limits** — Default `max_fan_out: 500` with per-task YAML override. Hard ceiling at ASE instance limits (~30 concurrent workers), but DB can accommodate low hundreds of ready tasks without issue given adequate Azure PostgreSQL tier. We are not building Kubernetes — fan-outs beyond 500 indicate a design problem in the workflow, not a scaling need.
- [x] **Workflow versioning** — Two levels tracked: (1) **Platform version** from `config/__init__.py` stored in `workflow_runs.platform_version` — identifies which codebase executed the workflow; (2) **Workflow definition** snapshot stored in `workflow_runs.definition JSONB` at submission time — in-flight runs are immutable regardless of YAML changes. Both queryable for debugging and audit.

### Deferred to Review

- [ ] **`when:` clause complexity** — Defer to Review Committee. Current proposal: simple dotted-path truthiness. Open question: whether comparisons (`row_count > 10000`) will be needed.
- [x] **Backward compat period** — Resolved: Strangler fig (revised 16 MAR). SB stays for legacy jobs during migration. Removed in F6 cleanup after all workflows ported.
- [ ] **Observability architecture** — Goal: best possible observability system, not accommodation of legacy patterns. Current `JobEventType` events may be good framework or may be technical debt. Decision: evaluate honestly during Phase 5 — if the event model serves DAG observability well, keep it; if it constrains, build from scratch. Do not compromise observability to preserve old code.

### Resolved During Implementation (16 MAR 2026)

- [x] **TIMESTAMP not TIMESTAMPTZ** — We use UTC everywhere. No timezone data stored. TIMESTAMP is correct. No need for TIMESTAMPTZ.
- [x] **`task_name` vs `node_name` column** — DDL spec says `task_name`, conceptual model says `node_name`. Implemented as `task_name` in database. "Node" is the YAML blueprint concept, "task" is the execution/DB concept. Column is on the execution table → `task_name` is correct.
- [x] **CANCELLED as 8th WorkflowTaskStatus** — Added beyond the 7-value spec. Needed for admin force-stop of running workflows.
- [x] **`updated_at` on `workflow_tasks`** — Not in spec, added intentionally. Useful for janitor debugging (detect when a task was last modified).
- [x] **Extra indexes on `workflow_runs`** — workflow_name, status, created_at, request_id indexes added beyond spec. Needed for dashboard and platform status queries.
- [x] **Epoch 4 freeze enforced** — D.1 and D.2 are pure new code. Only additive changes to `__init__.py` and `sql_generator.py`. Zero Epoch 4 files modified.
- [x] **Intermediate data via mount scratch space** — GeoParquet on Azure Files mount (`/mnt/etl/{run_id[:12]}/intermediate/{node_name}.parquet`). Deterministic paths, no lookup table. Enables inter-node data flow AND retry resumability. Fail-fast if mount unavailable. Cleanup by finalize handler (success) or janitor (failure). See "Intermediate Data Architecture" section.

## Remaining Open Questions

See "Deferred to Review" items above. All other questions have been resolved in "Decisions Made".

---

## Azure Resource Map

### Active Resources (v0.12.1 End State)

| Resource | Type | Role | Phase Impact |
|----------|------|------|-------------|
| `rmhazuregeoapi` | Function App | B2B gateway (`/platform/*` endpoints) + orchestrator (today) | v0.10.4: orchestration moves to timer trigger. v0.12.1: orchestration removed entirely, gateway-only. |
| `rmhtitiler` | Web App (Docker) | Service layer (TiTiler + TiPG + STAC API) | **Untouched** — no ETL migration impact |
| `rmhheavyapi` | Web App (Docker) | ETL worker — executes handlers, heavy compute (GDAL, xarray, geopandas) | v0.10.3: SB polling → DB `SKIP LOCKED` polling. v0.12.0: polls `workflow_tasks` instead of `tasks`. |
| `rmhdagmaster` | Web App (Docker) | DAG orchestrator — lightweight poll loop, DAG evaluation | v0.12.1: takes over orchestration from `rmhazuregeoapi`. Advisory lock HA. No heavy libs. |

### Resources to Retire

| Resource | Type | Current State | Action |
|----------|------|---------------|--------|
| `rmhdagworker` | Web App (Docker) | Running (empty) | **Retire** — `rmhheavyapi` is the worker, no need for a separate DAG worker |
| `rmhdaggateway` | Function App | Stopped | **Retire** — `rmhazuregeoapi` stays as B2B gateway |
| `rmhgeogateway` | Function App | Stopped | Already deprecated |
| `rmhgeoapi-worker` | Function App | Running (legacy) | Already deprecated |

### Resource Topology by Phase

```
TODAY (v0.10.2.1):
  rmhazuregeoapi (Function App) ──SB──→ rmhheavyapi (Docker Worker)
       ↑ HTTP                              ↑ SB poll
       B2B clients                         geospatial-jobs + container-tasks queues

v0.10.3 (Worker polls DB):
  rmhazuregeoapi (Function App) ──SB──→ rmhheavyapi (Docker Worker)
       ↑ HTTP                              ↑ DB poll (SKIP LOCKED)
       B2B clients                         SB still used for job dispatch

v0.10.4 (Orchestrator timer):
  rmhazuregeoapi (Function App) ──DB──→ rmhheavyapi (Docker Worker)
       ↑ HTTP        ↑ 60s timer           ↑ DB poll
       B2B clients   polls DB for work     No SB involved

v0.11.0 (SB removed):
  rmhazuregeoapi (Function App) ──DB──→ rmhheavyapi (Docker Worker)
       ↑ HTTP        ↑ 60s timer           ↑ DB poll
       B2B clients   Service Bus deleted   Pure PostgreSQL coordination

v0.12.0 (YAML/DAG):
  rmhazuregeoapi (Function App) ──DB──→ rmhheavyapi (Docker Worker)
       ↑ HTTP        ↑ 60s timer           ↑ DB poll (workflow_tasks)
       B2B clients   DAGOrchestrator       YAML-defined workflows

v0.12.1 (Docker orchestrator — END STATE):
  rmhazuregeoapi (Function App)          rmhdagmaster (Docker)
       ↑ HTTP (gateway only)              ↑ poll loop (orchestration only)
       B2B clients                         DAG evaluation, lightweight
                          ↘       ↙
                        PostgreSQL
                          ↗
                 rmhheavyapi (Docker Worker × N)
                    SKIP LOCKED poll, handler execution

  rmhtitiler (Docker) — service layer, independent
```

---

## File Index

### Existing Files (to be modified/replaced)

| File | Current Role | Migration Impact |
|------|-------------|-----------------|
| `core/machine.py` | CoreMachine orchestrator (2,400 lines) | **Replace** with DAGOrchestrator |
| `core/state_manager.py` | DB state transitions (900 lines) | **Evolve** — add DAG task ops |
| `infrastructure/service_bus.py` | Service Bus client (800 lines) | **Remove** |
| `jobs/*.py` | 14 Python job definitions | **Replace** with YAML workflows |
| `jobs/base.py` | JobBase ABC | **Remove** |
| `jobs/mixins.py` | JobBaseMixin (boilerplate) | **Remove** |
| `services/__init__.py` | Handler registry | **Keep** — handlers still registered here |
| `services/handler_vector_docker_complete.py` | Monolithic vector handler | **Decompose** into 6 atomic handlers |
| `docker_service.py` | Docker worker + SB polling | **Modify** — poll DB instead of SB |
| `function_app.py` | App startup + SB triggers | **Modify** — remove SB triggers, add DAG endpoints |
| `triggers/service_bus/` | SB message handlers | **Remove** |

### New Files (to be created)

| File | Purpose | Lines (est) |
|------|---------|-------------|
| `workflows/*.yaml` | 14 workflow definitions | ~50-80 each |
| `core/dag_orchestrator.py` | Polling DAG engine | ~400 |
| `core/workflow_loader.py` | YAML parser + validator | ~300 |
| `core/workflow_registry.py` | Loaded workflow registry | ~100 |
| `core/param_resolver.py` | Dotted-path parameter resolution | ~150 |
| `core/fan_out.py` | Fan-out expansion logic | ~100 |
| `services/vector_validate_source.py` | Atomic vector validator | ~60 |
| `services/vector_create_postgis_table.py` | Atomic table creator | ~80 |
| `services/vector_load_chunks.py` | Atomic chunk loader | ~100 |
| `services/stac_create_item.py` | Shared STAC item creator | ~80 |
| `services/catalog_register.py` | Shared catalog registration | ~60 |

---

## SAFe Implementation Plan — Strangler Fig Migration

**Date**: 16 MAR 2026
**Team**: Robert (Product Owner + Dev) + Claude (Dev + SAFe Coach)
**Cadence**: 1-3 day stories, SIEGE regression after each ported workflow
**Epic**: V10 DAG Migration (v0.10.3 → v0.12.0)

### Migration Strategy: Strangler Fig

The DAG Brain (Docker orchestrator) runs **alongside** the existing Function App orchestrator. New workflows go to the DAG Brain; legacy jobs stay on the old path. Workflows are ported one at a time, each validated with SIEGE. When all 14 are ported, remove the old system.

```
Migration Window (peak operational complexity — invisible to clients):

  Gateway (Function App)
      │
      ├──→ DAG Brain (Docker) ──→ workflow_tasks ──→ Docker Worker (SKIP LOCKED)
      │    ↑ new YAML workflows                       ↑ polls BOTH tables
      │
      └──→ CoreMachine (Function App) ──→ app.tasks ──→ Docker Worker (SKIP LOCKED)
           ↑ legacy Python jobs                        ↑ same worker, two poll targets

  Routing logic (~10 lines in Gateway):
    if workflow_registry.has(workflow_name):
        INSERT INTO workflow_runs → DAG Brain handles it
    else:
        create_and_submit_job() → CoreMachine handles it (existing path)

  Rollback: remove a YAML file → that workflow falls back to the old path. No code changes.
```

### Why Strangler Fig (Not Sequential Cutover)

| Sequential Plan (Original) | Strangler Fig (Revised) |
|---------------------------|------------------------|
| F2: Convert Function App to timer trigger (3-5 days) | **Eliminated** — DAG Brain IS the new orchestrator |
| F3: Remove SB in separate phase | **Deferred** — SB keeps working for legacy jobs, removed once at the end |
| F5: Big-bang YAML cutover | **Incremental** — one workflow at a time, each SIEGE-validated |
| F6: Move orchestrator to Docker | **Free** — DAG Brain starts as Docker from day one |
| Risk: all 14 workflows must work before any go live | Risk: each workflow proven independently before the next |

**Time saved**: ~7 days (F2 eliminated, F6 free, F3 consolidated into cleanup).

### Epoch 4 Freeze Policy (CRITICAL — All Claude Instances Must Follow)

**Epoch 4 (CoreMachine, Python jobs, Service Bus) is in maintenance mode during the DAG build.** The existing system continues to run in production, but changes are restricted to prevent complicating the Epoch 5 migration. Every feature added to Epoch 4 is a feature that must be ported to Epoch 5.

| Change Type | Allowed? | Rationale |
|-------------|----------|-----------|
| Bug fix (known bugs from SIEGE/COMPETE) | **Yes** | Fix what's broken |
| Operational fix (health, diagnostics, logging) | **Yes** | Keep production stable |
| New atomic handler (F4 pattern, reusable) | **Yes** | **Feeds both epochs** — works in Epoch 4 via wrapper AND Epoch 5 via YAML node |
| New pipeline / job type | **No** | Build it as a YAML workflow from the start. Adding a Python job class creates porting debt. |
| CoreMachine refactoring | **No** | We're replacing it. Refactoring dead-end code is waste. |
| Schema redesign on `app.jobs`/`app.tasks` | **No** | New schema work goes into `workflow_runs`/`workflow_tasks` tables. |
| Service Bus changes | **No** | SB is deprecated. Will be deleted in F6 cleanup. |
| New job stages or stage logic | **No** | Stages are eliminated in Epoch 5. Build as DAG nodes instead. |

**The one bridge**: If a new handler is needed for a real business requirement, build it as an **atomic handler** and register it in `ALL_HANDLERS`. It works in Epoch 4 (called by existing monolithic handlers or via a thin wrapper job) AND in Epoch 5 (referenced by YAML nodes). Atomic handlers are additive — they don't complicate the migration, they accelerate it.

**When this policy ends**: After F6 cleanup (all 14 workflows on DAG Brain, CoreMachine deleted). At that point Epoch 5 is the sole system and the freeze is moot.

### Progress Tracker

| Phase | Feature | Status | SIEGE |
|-------|---------|--------|-------|
| **F1** | Worker polls DB (SKIP LOCKED) v0.10.3 | **DONE** | Run 18: 18/18 100% |
| **F-DAG** | DAG Foundation (loader, tables, resolver, orchestrator) | **D.1-D.6 DONE**, D.7-D.10 not started | — |
| **F4** | Handler decomposition (monolithic → atomic) | NOT STARTED | — |
| **Port** | Workflows ported one at a time (14 total) | 0/14 | — |
| **Cleanup** | Remove CoreMachine, SB, Python jobs | NOT STARTED | — |

### Agent Pipeline Recommendations (Per Story)

Each story should be dispatched to a separate Claude session with the appropriate agent pipeline. This session (architecture + review) stays high-level.

**Documents to provide to dispatched Claude sessions:**
- `V10_MIGRATION.md` — full migration context (this file)
- `docs/superpowers/specs/2026-03-16-workflow-loader-yaml-schema-design.md` — YAML schema spec
- `docs/superpowers/plans/2026-03-16-workflow-loader-yaml-schema.md` — D.1 plan (completed, but pattern for future plans)

| Story | Pipeline | Rationale |
|-------|----------|-----------|
| **D.1** Workflow loader | ~~GREENFIELD~~ **DONE** | Completed 16 MAR 2026. 36 tests, all passing. |
| **D.2** DAG tables | ~~GREENFIELD~~ **DONE** | Completed 16 MAR 2026. 37 tests, all passing. |
| **D.3** DAG initializer | ~~GREENFIELD~~ **DONE** | Completed 16 MAR 2026. GREENFIELD pipeline (S→A+C+O→M→B→V). |
| **D.4** Param resolver | ~~GREENFIELD~~ **DONE** | Completed 16 MAR 2026. GREENFIELD pipeline. V found 2 bugs, both fixed. |
| **D.5** DAG orchestrator | **ARB → GREENFIELD** | Most complex (~400 lines). Concurrency, brain guard, fan-out. ARB decomposes into subsystems first, then GREENFIELD per subsystem. |
| **D.6** Worker dual-poll | ~~Direct~~ **DONE** | Completed 16 MAR 2026. Dual SKIP LOCKED in _run_loop. |
| **D.7** Janitor | **GREENFIELD** | Port pattern from rmhdagmaster. ~80 lines. |
| **D.8** Gateway routing | **Direct implementation** | ~10 lines of routing logic. No pipeline needed. |
| **D.9** DAG status | **Direct implementation** | Query changes to existing endpoints. |
| **D.10** First blood | **SIEGE** | End-to-end validation of hello_world through DAG Brain. |
| **F4.1** Raster atomics | **GREENFIELD** per handler | Extract + rewrite from rmhdagmaster reference code. |
| **F4.2** Vector atomics | **GREENFIELD** per handler | Extract from existing monolithic handler. |
| **F5** Port workflows | **SIEGE** per tier | Each tier validated end-to-end against live system. |
| **F6** Cleanup | **COMPETE** | Adversarial review that no legacy references remain. |

**Key principle**: GREENFIELD for building new code. COMPETE for reviewing code. SIEGE for validating live system. ARB for decomposing complex stories before GREENFIELD.

---

### Feature DAG: DAG Foundation + Brain (v0.10.4 → v0.11.0)

**Goal**: Build the complete DAG orchestration system and stand it up as a Docker container running alongside the existing Function App. No disruption to existing workflows.

**Acceptance**: DAG Brain running as Docker container. `hello_world` workflow submitted via Gateway → routed to DAG Brain → completed via `workflow_tasks`. Legacy jobs unaffected.

#### Story D.1: Workflow Loader + Registry — DONE (16 MAR 2026)

**What**: Parse YAML workflow files, validate structure, cache in memory.

**Spec**: `docs/superpowers/specs/2026-03-16-workflow-loader-yaml-schema-design.md`
**Plan**: `docs/superpowers/plans/2026-03-16-workflow-loader-yaml-schema.md`

**Port from rmhdagmaster**: `services/workflow_service.py` (184) + `core/models/workflow.py` (260). Adapt to V10 schema (discriminated union, `depends_on`, `receives:`).

**Files**:
- NEW: `core/workflow_loader.py` (~200 lines)
- NEW: `core/workflow_registry.py` (~100 lines)
- NEW: `core/models/workflow_definition.py` (~300 lines)
- NEW: `core/models/workflow_enums.py` (~30 lines)
- NEW: `core/errors/workflow_errors.py` (~30 lines)

**Delivered** (16 MAR 2026):
- `core/models/workflow_enums.py` — NodeType, AggregationMode, BackoffStrategy
- `core/models/workflow_definition.py` — Discriminated union (TaskNode/ConditionalNode/FanOutNode/FanInNode) + WorkflowDefinition + all supporting models
- `core/workflow_loader.py` — WorkflowLoader with 9 structural validations + WorkflowValidationError
- `core/workflow_registry.py` — WorkflowRegistry (load_all, has, get_or_raise) + WorkflowNotFoundError
- `workflows/hello_world.yaml` — 1-node test workflow
- `workflows/echo_test.yaml` — 3-node test with receives, when, optional deps
- `tests/unit/test_workflow_loader.py` — 36 tests, all passing
- `requirements.txt` — added PyYAML, Jinja2
- Errors defined inline in loader/registry modules (not separate errors dir)

**Acceptance**: All met. 36/36 tests pass. Real YAML files load against ALL_HANDLERS registry.

#### Story D.2: DAG Database Tables — DONE (16 MAR 2026)

**What**: Create `workflow_runs`, `workflow_tasks`, `workflow_task_deps` tables.

**Delivered**:
- `core/models/workflow_run.py` — WorkflowRun model (97 lines), WorkflowRunStatus enum (4 values)
- `core/models/workflow_task.py` — WorkflowTask model (146 lines), WorkflowTaskStatus enum (8 values incl. CANCELLED)
- `core/models/workflow_task_dep.py` — WorkflowTaskDep model (57 lines)
- `core/schema/sql_generator.py` — registered 3 tables + 2 enums for DDL generation
- `tests/unit/test_workflow_dag_models.py` — 37 tests, all passing
- `tests/factories/model_factories.py` — added make_workflow_run, make_workflow_task factories

**Review findings** (16 MAR 2026):
- TIMESTAMP (no timezone) is correct — we use UTC everywhere, no TIMESTAMPTZ needed
- `updated_at` on `workflow_tasks` kept intentionally — useful for janitor debugging
- Extra indexes on `workflow_runs` (workflow_name, status, created_at, request_id) — beneficial for dashboard/status queries
- CANCELLED as 8th WorkflowTaskStatus — forward-looking addition beyond 7-value spec
- `task_name` column used (matching DDL spec) — V10_MIGRATION.md conceptual model says `node_name` but DDL says `task_name`, accepted as-is

**Acceptance**: All met. 37/37 tests pass. `action=ensure` additive (no existing table changes).

#### Story D.3: DAG Initializer — DONE (16 MAR 2026)

**What**: When a workflow run is created, instantiate blueprint nodes as execution tasks with dependency edges.

**Pipeline**: GREENFIELD (S→A+C+O→M→B→V). Full report: `docs/agent_review/agent_docs/greenfield_dag_initializer_d3.md`

**Delivered**:
- `core/dag_initializer.py` (~370 lines) — DAGInitializer class + 6 private pure functions
- `infrastructure/workflow_run_repository.py` (~290 lines) — atomic INSERT with UniqueViolation idempotency
- 3-pass pure `_build_tasks_and_deps`: validate refs → build tasks → build deduplicated deps
- Structural validation: missing refs, cycle detection (empty-roots guard)
- Idempotent via SHA256 run_id + UniqueViolation catch (no TOCTOU race)

**Open Questions Resolved**:
- Q1: Handler sentinels `__conditional__` / `__fan_in__` for non-worker nodes (NOT NULL preserved)
- Q2: All node types (including conditional/fan_in) instantiated as WorkflowTask rows
- Q3: No timestamp in run_id — pure content-addressing, FAILED retry deferred (D-1)

**GREENFIELD Agent Results**:
- A: 4-component design (collapsed to 2 files by M per Constraint 10)
- C: 5 ambiguities, 10 edge cases, 8 unstated assumptions, 4 contradictions
- O: 6 failure modes, 3 infrastructure constraints
- M: 11 conflicts resolved, 3 design tensions, 6 deferred decisions, 7 risks
- V: NEEDS MINOR WORK — 10 concerns, all resolved or accepted

**Deferred Decisions**:
- D-1: Retry/reset for FAILED runs (when retry UI needed)
- D-2: Full topological sort cycle detection (before production — Kahn's algorithm)
- D-3: GET /api/dbadmin/runs/{run_id} endpoint (when operator needs it)
- D-4: Index on workflow_task_deps(task_instance_id) (before D.5 orchestrator)

**Verification**: Tested with hello_world.yaml (1 task, 0 deps), multi-node synthetic (4 tasks, 4 deps, optional deps), cycle detection, missing ref detection. 73/73 existing tests (D.1+D.2) still pass.

**Acceptance criteria**:
- Create workflow run → all nodes instantiated as tasks in `workflow_tasks`
- Root nodes (no deps) immediately `ready`
- Dependency edges created in `workflow_task_deps`
- Conditional `next:` creates implicit dependency edges
- Optional deps (`?` suffix) stored with `optional=true`
- Transaction failure → no partial state

#### Story D.4: Parameter Resolver — DONE (16 MAR 2026)

**What**: Resolve `receives:` dotted paths from predecessor results and merge with job params. Jinja2 for fan-out `task.params` only.

**Pipeline**: GREENFIELD (S→A+C+O→M→B→V).

**Delivered**:
- `core/param_resolver.py` (~290 lines) — 3 public functions + ParameterResolutionError
- `resolve_dotted_path`: navigates predecessor result_data by dotted path, raises on missing
- `resolve_task_params`: list params (pass-through from job_params) or dict params (literals), receives overlay
- `resolve_fan_out_params`: Jinja2 NativeEnvironment with StrictUndefined, type-preserving
- Module-level `_JINJA_ENV = NativeEnvironment(undefined=StrictUndefined)` — read-only singleton

**Key Design Decisions (M resolutions)**:
- No "result" sentinel in dotted paths — `"node_name.field"` navigates raw result_data directly
- Missing job params in params: list → raise immediately (Constraint 1: fail explicitly)
- Jinja2 NativeEnvironment preserves native types (int, list, dict) for single-expression templates
- Fan-out does NOT support receives: (FanOutTaskDef has no receives field)
- Index is zero-based
- Jinja2 context: `{item, index, inputs (=job_params), nodes (=predecessor_outputs)}`

**V Findings (2 bugs fixed)**:
- C4: `TemplateSyntaxError` not caught → added to except clause
- C5: `node.params` type not validated → added type guard

**Acceptance**: All 8 inline tests pass. 73/73 existing tests (D.1+D.2) still pass.

#### Story D.5: DAG Orchestrator Core Loop (2-3 days) — ARB DECOMPOSED

**What**: The DAG Brain — a poll loop that evaluates DAG state, promotes tasks, expands fan-outs, evaluates conditionals, detects completion.

**Pipeline**: ARB → GREENFIELD (3 runs). ARB report: `docs/agent_review/agent_docs/arb_dag_orchestrator_d5.md`

**ARB Decomposition** (16 MAR 2026):
- Original 4 subsystems (D.5a/b/c/d) collapsed to 3 Greenfield runs by merging D.5b+D.5d (no independent test surface)
- R flagged 6 CRITICAL/HIGH risks — all resolved by P's architectural decisions
- Total: ~1,070 lines across 4 new files + 1 extended file

**Critical Architectural Decisions (P resolutions)**:
- Advisory lock: DEDICATED non-pooled connection (never pooled — zombie lock risk)
- Transaction boundaries: One transaction per handler call, committed before next handler
- Dispatch ordering: conditionals → transitions → fan-out → fan-in (prevents promote-before-skip)
- When-clause: `resolve_dotted_path()` + `bool()` only — no Jinja2, three-value return (True/False/None=wait)
- Fan-out child IDs: `{run_id[:12]}-{task_name}-fo{index}` (fo prefix prevents collision)
- State refresh: Full DB reload each cycle — no carried state between cycles
- Error model: Per-task catch → FAIL task + continue. ContractViolationError → FAIL entire run.

**Build Plan**:

| Phase | Run | File(s) | Lines | Status |
|-------|-----|---------|-------|--------|
| 1 | Run 1 | `core/dag_graph_utils.py` + repo additions to `workflow_run_repository.py` | ~740 | **DONE** |
| 2 | Run 2 | `core/dag_transition_engine.py` + `core/dag_fan_engine.py` + `set_task_parameters` | ~860 | **DONE** |
| 3 | Run 3 | `core/dag_orchestrator.py` | ~510 | **DONE** |

**Run 1 deliverables**: Shared graph traversal (pure functions: `build_adjacency`, `get_descendants`, `all_predecessors_terminal`, `is_run_terminal`), `TaskSummary` dataclass, `PredecessorOutputs` type alias, 8 new repository methods (IC-R1 through IC-R8).

**Run 2 deliverables**: `evaluate_conditionals()`, `evaluate_transitions()` (merged D.5b+D.5d), `expand_fan_outs()`, `aggregate_fan_ins()` (D.5c).

**Run 3 deliverables**: `DAGOrchestrator.run(run_id)`, advisory lock lifecycle, poll loop, `OrchestratorResult` dataclass, run terminal detection.

**Acceptance criteria** (end-to-end after all 3 runs):
- Brain guard: advisory lock ensures single active instance
- Poll loop: fixed order — conditionals → transitions → fan-out → fan-in → terminal check
- Fan-out: one blueprint node → N execution tasks (atomic INSERT)
- Conditional: evaluate branches → activate taken, skip untaken + exclusive descendants
- `hello_world` workflow completes end-to-end via DAG Brain
- Idempotent handlers: status guard clauses on every state transition

#### Story D.6: Worker Dual-Poll (1 day)

**What**: Worker's SKIP LOCKED poll targets both `app.tasks` (legacy) AND `workflow_tasks` (DAG). Same handler execution, same contract.

**Files**:
- `docker_service.py` — add second poll query for `workflow_tasks`
- `infrastructure/jobs_tasks.py` — `claim_ready_workflow_task()` method
- `core/param_resolver.py` — called at claim time for DAG tasks

**Acceptance criteria**:
- Worker claims tasks from both tables
- Legacy jobs (via `app.tasks`) work exactly as before
- DAG workflows (via `workflow_tasks`) resolve params at claim time, execute handler, write result
- Single worker instance serves both systems

#### Story D.7: Janitor — Stale Task Recovery (1 day)

**What**: Background thread in DAG Brain that reclaims stuck tasks with stale heartbeats. Covers both `workflow_tasks` (DAG) and `app.tasks` (legacy, deferred from v0.10.3).

**Port from rmhdagmaster**: Orphan scan pattern (~40 lines) + timing constants (ORPHAN_THRESHOLD=120s, SCAN_INTERVAL=60s).

**Files**:
- `core/dag_orchestrator.py` — janitor loop alongside main poll loop
- `infrastructure/jobs_tasks.py` — `reclaim_stale_tasks()` for legacy table

**Acceptance criteria**:
- Stale DAG task (simulated by killing worker mid-task) reclaimed within ~2 minutes
- Stale legacy task also reclaimed
- Exhausted retries → FAILED (not stuck forever)

#### Story D.8: Gateway Routing (1 day)

**What**: Gateway checks WorkflowRegistry before submitting. If YAML exists → DAG path. If not → legacy path.

**Files**:
- `services/platform_job_submit.py` — routing logic (~10 lines)
- `services/platform_translation.py` — `job_type` → `workflow_name` mapping
- `triggers/jobs.py` — direct submit path also checks registry

**Acceptance criteria**:
- Submit `hello_world` (YAML exists) → routed to DAG Brain → completes
- Submit `process_raster_docker` (no YAML yet) → routed to CoreMachine → completes as before
- Status endpoint works for both paths

#### Story D.9: DAG Status Integration (1 day)

**What**: Status endpoints (`/api/jobs/status`, `/api/platform/status`) query both `app.jobs`/`app.tasks` and `workflow_runs`/`workflow_tasks`.

**Files**:
- `triggers/get_job_status.py` — query DAG tables if run_id found
- `triggers/trigger_platform_status.py` — same dual-query
- `services/platform_response.py` — build response from DAG tables (task names, not stage numbers)

**Acceptance criteria**:
- Status for legacy job → same response as today
- Status for DAG workflow → response includes node-level progress (`"current_node": "create_cog"`)
- B2B response shape unchanged (same fields, richer progress for DAG workflows)

#### Story D.10: First Blood — `hello_world` End-to-End + SIEGE (0.5 day)

**What**: Deploy DAG Brain. Submit `hello_world` via Gateway. Verify full lifecycle. SIEGE regression for legacy workflows.

**Files**:
- NEW: `workflows/hello_world.yaml` (created in D.1)
- NEW: `entrypoint_orchestrator.py`
- Existing `Dockerfile` (DAG Brain uses same image with `APP_MODE=orchestrator`)

**Acceptance criteria**:
- DAG Brain running as Docker container alongside Function App
- `hello_world` submits via Gateway → DAG Brain → worker → completed
- SIEGE regression: all legacy workflows unaffected (≥ 95% pass rate)
- COMPETE adversarial review on DAG orchestrator code

---

### Feature 4: Handler Decomposition (v0.11.1)

**Goal**: Break monolithic handlers into atomic, reusable handlers that become DAG nodes. Wrappers preserve existing job compatibility.

**Acceptance**: All existing jobs work identically through wrappers. New atomic handlers registered and independently testable.

#### Story 4.1: Extract Raster Atomic Handlers (2-3 days)

**What**: Decompose `raster_docker_complete` into 5 atomic handlers.

**Port from rmhdagmaster**: `handlers/raster/` — validate (468 lines), cog_create (262), blob_copy (116), statistics (417), stac (706). Adapt to rmhgeoapi's blob/STAC layer.

**New handlers**:
| Handler | Extracted From | Est. Lines |
|---------|---------------|------------|
| `raster_validate_source` | Phase 1 validate | ~80 |
| `raster_create_cog` | Phase 2 COG creation | ~100 |
| `raster_upload_cog` | Phase 3 blob upload | ~60 |
| `stac_create_item` | Phase 4 STAC (shared) | ~80 |
| `catalog_register_raster` | Phase 5 catalog | ~50 |

**Files**:
- NEW: `services/raster/validate_source.py`
- NEW: `services/raster/create_cog.py`
- NEW: `services/raster/upload_cog.py`
- NEW: `services/shared/stac_create_item.py`
- NEW: `services/shared/catalog_register.py`
- `services/__init__.py` — register new handlers in `ALL_HANDLERS`
- `services/handler_raster_docker_complete.py` — wrapper calls atomics in sequence

**Acceptance criteria**:
- Existing raster job works identically (wrapper delegates to atomics)
- Each atomic handler independently callable with correct contract
- `stac_create_item` usable by raster, zarr, and virtualzarr workflows

#### Story 4.2: Extract Vector Atomic Handlers (2-3 days)

**What**: Decompose `vector_docker_complete` (400+ lines, 7 phases) into 6 atomic handlers.

**New handlers**:
| Handler | Extracted From | Est. Lines |
|---------|---------------|------------|
| `vector_validate_source` | Phase 1 | ~60 |
| `vector_create_postgis_table` | Phase 2 DDL | ~80 |
| `vector_load_chunks` | Phase 3 upload | ~100 |
| `vector_create_split_views` | Phase 3.7 | ~80 (already in `view_splitter.py`) |
| `catalog_register_vector` | Phase 4 | ~50 |
| `tipg_refresh_collections` | Phase 5 | ~20 (already in `service_layer_client.py`) |

**Files**:
- NEW: `services/vector/validate_source.py`
- NEW: `services/vector/create_table.py`
- NEW: `services/vector/load_chunks.py`
- NEW: `services/shared/catalog_register_vector.py`
- `services/__init__.py` — register new handlers
- `services/handler_vector_docker_complete.py` — wrapper calls atomics

**Acceptance criteria**:
- Existing vector job works identically through wrapper
- Split views handler already extracted (`view_splitter.py`) — just register
- TiPG refresh already isolated — just register

#### Story 4.3: Standardize Unpublish + Zarr Handlers (1-2 days)

**What**: Zarr pipelines are already ~80% decomposed. Standardize interfaces and register shared unpublish handlers.

**Tasks**:
1. Register existing zarr stage handlers as atomic handlers in `ALL_HANDLERS`
2. Create shared unpublish handlers: `unpublish_inventory_item`, `unpublish_delete_blob`, `unpublish_cleanup_stac`, `unpublish_cleanup_postgis`, `unpublish_cleanup_catalog`
3. Wrapper handlers preserve existing job behavior

**Acceptance criteria**:
- Zarr ingest, netcdf-to-zarr, virtualzarr, and all unpublish jobs work identically
- Shared handlers registered and reusable across workflow types

#### Story 4.4: SIEGE Regression (0.5 day)

**What**: Full regression after handler decomposition. Deploy v0.11.1.

**Acceptance criteria**:
- SIEGE pass rate ≥ 95%
- Zero regressions from decomposition (wrappers preserve behavior)
- All new atomic handlers visible in handler registry

---

### Feature 5: Port Workflows (Strangler Fig — Incremental) ~~(v0.12.0)~~

**Goal**: Port all 14 Python job classes to YAML workflows, one at a time. Each ported workflow is immediately live on the DAG Brain. Legacy jobs stay on CoreMachine until their YAML is ready.

**Requires**: F-DAG done (DAG Brain running) + F4 done (atomic handlers available).

**Rollback**: Remove a YAML file from `workflows/` → that workflow falls back to CoreMachine. No code changes.

#### Story 5.2: DAG Database Tables (1 day)

**What**: Create `workflow_runs`, `workflow_tasks`, `workflow_task_deps` tables.

**Files**:
- `core/models/` — NEW Pydantic models for WorkflowRun, WorkflowTask
- `core/schema/sql_generator.py` — DDL generation for new tables
- `infrastructure/` — NEW repository methods for DAG tables

**Tasks**:
1. Add Pydantic models with `__sql_table__` metadata
2. Generate DDL via existing `PydanticToSQL` pattern
3. Deploy via `action=ensure` (additive, no data loss)
4. Verify tables created with correct indexes

**Acceptance criteria**:
- `action=ensure` creates 3 new tables + indexes without touching existing tables
- `workflow_tasks` has partial indexes for orchestrator and worker poll queries

#### Story 5.3: DAG Initializer (1-2 days)

**What**: When a workflow run is created, instantiate blueprint nodes as execution tasks with dependency edges.

**Files**:
- NEW: `core/dag_initializer.py` (~200 lines)

**Tasks**:
1. Read workflow definition from `workflow_runs.definition` JSONB
2. For each node in blueprint: INSERT `workflow_tasks` row (status=pending)
3. For each `depends_on` edge: INSERT `workflow_task_deps` row
4. Mark root nodes (no dependencies) as `ready` immediately
5. Evaluate `when:` clauses for root nodes → `skipped` if false
6. All in one transaction (atomic DAG initialization)

**Acceptance criteria**:
- Create workflow run → all nodes instantiated as tasks
- Root nodes (no deps) immediately `ready`
- Dependency edges correctly created in `workflow_task_deps`
- Transaction failure → no partial state

#### Story 5.4: Parameter Resolver (1-2 days)

**What**: Resolve `receives:` dotted paths from predecessor results and merge with job params.

**Port from rmhdagmaster**: `orchestrator/engine/templates.py` (302 lines). Simplify — V10 uses explicit `receives:` mapping instead of Jinja2 in every param field.

**Files**:
- NEW: `core/param_resolver.py` (~150 lines)

**Tasks**:
1. Parse dotted paths: `"validate.result.metadata"` → look up `workflow_tasks` where `node_name='validate'`, extract `result_data.metadata`
2. Merge: job params (from `params:` list) + received values (from `receives:`) + system params (`_run_id`, `_node_name`)
3. Handle fan-out collection: `"copy_blob.result[]"` → collect all fan-out task results into array
4. Error on unresolved reference (strict mode — fail fast)

**Acceptance criteria**:
- `receives: {metadata: "validate.result.metadata"}` resolves to predecessor's result_data
- Fan-out collection `result[]` aggregates all fan-out task results
- Missing predecessor → clear error, task marked FAILED

#### Story 5.5: DAG Orchestrator Core Loop (2-3 days)

**What**: The orchestrator poll loop that evaluates DAG state and promotes tasks.

**Port from rmhdagmaster**: Brain guard (~225 lines), main loop structure, fan-out expansion (~140 lines), conditional evaluation (~80 lines), completion detection (~30 lines). Adapt from async to sync, from 3-level to 2-level state model.

**Files**:
- NEW: `core/dag_orchestrator.py` (~400 lines)

**Tasks**:
1. Brain guard: `pg_try_advisory_lock` on dedicated connection, standby retry
2. Main poll loop (every 3-5 seconds):
   - Detect new `workflow_runs` (status=pending) → call DAG initializer
   - Query `promotable_tasks` view → mark `ready`
   - Evaluate `when:` clauses on newly-ready tasks → `skipped` if false
   - Expand fan-out nodes: resolve source array → INSERT N execution tasks
   - Detect completed workflows → run finalize handler → mark run completed
3. Heartbeat loop: update `owner_heartbeat_at` on owned runs
4. Orphan scan: reclaim runs with stale heartbeats

**Acceptance criteria**:
- Submit workflow → orchestrator initializes DAG → root tasks become ready
- Worker completes task → orchestrator promotes successors → eventually workflow completes
- Fan-out: one blueprint node → N execution tasks → fan-in collects results
- Conditional: `when:` false → task skipped → optional dependents proceed
- Brain guard: only one orchestrator instance active at a time

#### Story 5.6: Worker Adapts to `workflow_tasks` (1 day)

**What**: Worker's SKIP LOCKED poll targets `workflow_tasks` instead of (or in addition to) `app.tasks`.

**Files**:
- `docker_service.py` — add second poll target or unify
- `infrastructure/jobs_tasks.py` — `claim_ready_workflow_task()` method

**Tasks**:
1. Worker poll query targets `workflow_tasks` with same SKIP LOCKED pattern
2. Parameter resolution at claim time (call param_resolver)
3. Handler execution unchanged — same contract
4. Result written to `workflow_tasks.result_data` directly

**Acceptance criteria**:
- Worker claims task from `workflow_tasks` → resolves params → executes handler → writes result
- Legacy `app.tasks` polling still works (dual-mode during transition)

#### Story 5.7: Write YAML Workflows for All 14 Job Types (2-3 days)

**What**: Convert every Python job class to a YAML workflow definition using the atomic handlers from v0.11.1.

**Files**:
- NEW: `workflows/` directory with 14 YAML files

**Workflows to create**:
| Workflow | Current Job Class | Nodes |
|----------|------------------|-------|
| `hello_world.yaml` | `HelloWorldJob` | 1 |
| `validate_only.yaml` | `ValidateOnlyJob` | 1 |
| `process_raster_docker.yaml` | `ProcessRasterDockerJob` | 5 |
| `vector_docker_etl.yaml` | `VectorDockerETLJob` | 6 |
| `vector_multi_source_docker.yaml` | `VectorMultiSourceDockerJob` | 6+ |
| `ingest_zarr.yaml` | `IngestZarrJob` | 6 |
| `netcdf_to_zarr.yaml` | `NetCDFToZarrJob` | 5 |
| `virtualzarr.yaml` | `VirtualZarrJob` | 5 |
| `unpublish_raster.yaml` | `UnpublishRasterJob` | 3 |
| `unpublish_vector.yaml` | `UnpublishVectorJob` | 3 |
| `unpublish_zarr.yaml` | `UnpublishZarrJob` | 3 |
| `unpublish_vector_multi_source.yaml` | `UnpublishVectorMultiSourceJob` | 3 |
| `fathom_etl.yaml` | `FathomETLJob` | 4 |
| `fathom_unpublish.yaml` | `FathomUnpublishJob` | 3 |

**Acceptance criteria**:
- Each YAML loads and validates without errors
- Workflow loader detects all at startup
- YAML structure matches blueprint spec (nodes:, depends_on:, receives:, when:, fan_out:, fan_in:)

#### Story 5.2: Port Workflows — Tier by Tier (4-6 days)

**What**: Write YAML workflows and activate them on the DAG Brain one tier at a time. Each tier is a SIEGE checkpoint. Gateway routing sends ported workflows to DAG Brain, unported to CoreMachine.

**Tier 1 — Simple** (1 day):
| Workflow | Nodes | Complexity |
|----------|-------|-----------|
| `hello_world.yaml` | 1 | Trivial (already proven in D.10) |
| `validate_only.yaml` | 1 | Trivial |

**Tier 2 — Linear Chains** (1-2 days):
| Workflow | Nodes | Complexity |
|----------|-------|-----------|
| `process_raster_docker.yaml` | 5 | Linear: validate → cog → upload → stac → register |
| `vector_docker_etl.yaml` | 6 | Linear + conditional split_views (`when:`) |
| `unpublish_raster.yaml` | 3 | Linear |
| `unpublish_vector.yaml` | 3 | Linear |

SIEGE after Tier 2: raster + vector full lifecycle through DAG Brain.

**Tier 3 — Fan-Out** (1-2 days):
| Workflow | Nodes | Complexity |
|----------|-------|-----------|
| `ingest_zarr.yaml` | 8 | Fan-out blob copy + fan-in + conditional rechunk |
| `netcdf_to_zarr.yaml` | 7 | Fan-out conversion + fan-in |
| `virtualzarr.yaml` | 7 | Fan-out scan + fan-in combine |
| `unpublish_zarr.yaml` | 5 | Fan-out delete + fan-in |

SIEGE after Tier 3: zarr lifecycle through DAG Brain. This tier proves fan-out/fan-in works.

**Tier 4 — Complex** (1-2 days):
| Workflow | Nodes | Complexity |
|----------|-------|-----------|
| `vector_multi_source_docker.yaml` | 6+ | Multi-file fan-out |
| `unpublish_vector_multi_source.yaml` | 3 | Multi-table cleanup |
| `fathom_etl.yaml` | 4 | Domain-specific |
| `fathom_unpublish.yaml` | 3 | Domain-specific |

SIEGE after Tier 4: all 14 workflows on DAG Brain. Legacy path receives zero traffic.

**Acceptance criteria per tier**:
- All workflows in tier load and validate
- End-to-end test for each workflow type (submit → complete → verify outputs)
- SIEGE regression: ported workflows via DAG Brain + unported via CoreMachine, ≥ 95%
- No changes to handler code — YAML wires existing atomic handlers

---

### Feature 6: Cleanup — Remove Legacy System (v0.12.0)

**Goal**: All 14 workflows proven on DAG Brain. Remove CoreMachine, Service Bus, Python job classes. Function App becomes gateway-only.

**Prerequisite**: All Tier 1-4 workflows ported and SIEGE-validated. Zero traffic on legacy path.

#### Story 6.1: Remove CoreMachine + Python Jobs (1-2 days)

**What**: Delete the old orchestration system.

**Files to DELETE**:
- `core/machine.py` — CoreMachine (2,400 lines)
- `core/state_manager.py` — legacy state management
- `jobs/*.py` — 14 Python job classes
- `jobs/base.py`, `jobs/mixins.py` — base classes
- Wrapper handlers from F4 — remove wrappers, keep atomics

**Files to CLEAN**:
- `services/__init__.py` — remove `ALL_JOBS` registry (keep `ALL_HANDLERS`)
- `function_app.py` — remove SB triggers and legacy orchestration
- `services/platform_job_submit.py` — remove legacy path from routing (DAG-only)
- `docker_service.py` — remove `app.tasks` poll (only `workflow_tasks`)

**Acceptance criteria**:
- `grep -r "CoreMachine\|JobBase\|JobBaseMixin" --include="*.py"` returns zero hits
- Worker polls `workflow_tasks` only
- Gateway routes all submissions to DAG Brain

#### Story 6.2: Remove Service Bus (1 day)

**What**: Delete all Service Bus code and Azure resources. Deferred from original F3 — now one clean cut.

**Files to DELETE**:
- `infrastructure/service_bus.py` (800+ lines)
- `triggers/service_bus/` directory (job_handler, task_handler, error_handler)

**Files to CLEAN**:
- `config/defaults.py` — remove queue config fields
- `requirements.txt` — remove `azure-servicebus` dependency
- Remove SB connection strings from Azure App Settings
- Delete 3 Azure SB queues (`geospatial-jobs`, `container-tasks`, `stage-complete`)

**Acceptance criteria**:
- `grep -r "service_bus\|ServiceBus\|servicebus" --include="*.py"` returns zero hits
- App starts without `azure-servicebus` installed
- Zero SB Azure resources (~$50/month savings)

#### Story 6.3: SIEGE Final + Deploy v0.12.0 (1 day)

**What**: Final regression. This is the V10 end state.

**Acceptance criteria**:
- SIEGE extended campaign: all 14 workflow types via DAG Brain
- Raster, vector, zarr, unpublish lifecycles complete end-to-end
- Platform submit/status/approve flow works
- COMPETE adversarial review on cleanup (no legacy references remain)
- Architecture: Function App (gateway) + Docker (DAG Brain) + Docker (workers) + PostgreSQL
- Zero Service Bus. Zero CoreMachine. Zero Python job classes.

---

### Porting Map: rmhdagmaster → Story (Revised for Strangler Fig)

Each story's relationship to rmhdagmaster code — what to port, what to write fresh, what to skip.

#### F-DAG: DAG Foundation + Brain

| Story | rmhdagmaster Source | Lines | Action |
|-------|-------------------|-------|--------|
| D.1 Workflow loader | `services/workflow_service.py` (184) + `core/models/workflow.py` (260) | 444 | **Direct port.** Adapt Pydantic model to V10 discriminated union schema. Keep cycle detection, reference validation, version pinning. |
| D.2 DAG tables | `core/schema/sql_generator.py` (538) | 538 | **Merge improvements.** rmhgeoapi already has PydanticToSQL. Write new Pydantic models from scratch (different schema). |
| D.3 DAG initializer | `orchestrator/loop.py:463-528` + `job_service.create_job()` | ~65 | **Adapt.** Same pattern, V10's 2-level model is simpler. |
| D.4 Param resolver | `orchestrator/engine/templates.py` (302) | 302 | **Direct port with simplification.** `receives:` is dotted-path lookup. Jinja2 scoped to fan-out only. |
| D.5 DAG orchestrator | `orchestrator/loop.py` — brain guard (~225), main cycle (~25), heartbeat (~32), orphan scan (~40), fan-out (~140), conditional (~80), fan-in (~100), completion (~55) | ~700 | **Largest port.** Drop async, SB, Node↔Task sync. Keep brain guard, fan-out/fan-in, conditional routing, completion detection. |
| | `orchestrator/engine/evaluator.py` (734) — FanOutHandler, ConditionEvaluator | 734 | **Port selectively.** FanOutHandler + aggregation modes directly. Full ConditionEvaluator for conditional nodes (operators needed). |
| D.6 Worker dual-poll | — | — | **Extend existing.** Add second SKIP LOCKED query for `workflow_tasks`. |
| D.7 Janitor | `orchestrator/loop.py:719-758` (orphan scan, ~40 lines) | ~40 | **Port pattern.** Same SQL, adapt to sync thread in DAG Brain. |
| D.8 Gateway routing | — | — | **Write fresh.** ~10 lines of routing logic. rmhdagmaster has no gateway. |
| D.9 DAG status | — | — | **Write fresh.** Dual-query for legacy + DAG tables. |
| D.10 First blood | `Dockerfile` (orchestrator variant) + `entrypoint.sh` | ~50 | **Direct port.** Same image with `APP_MODE=orchestrator`. |

#### F4: Handler Decomposition

| Story | rmhdagmaster Source | Action |
|-------|-------------------|--------|
| 4.1 Raster atomics | `handlers/raster/validate.py` (468), `cog_create.py` (262), `blob_copy.py` (116), `statistics.py` (417), `stac.py` (706) — **~2,000 lines** | **Rewrite to fit.** Reference code for logic and edge cases. Adapt to rmhgeoapi's BlobRepository, STAC layer, sync handler contract. |
| 4.2 Vector atomics | — | **Extract from existing.** Pull phases from `handler_vector_docker_complete.py`. No rmhdagmaster equivalent. |
| 4.3 Zarr/unpublish | — | **Register existing.** Already decomposed in rmhgeoapi. |
| 4.4 SIEGE | — | — |

#### F5: Port Workflows + F6: Cleanup

| Story | rmhdagmaster Source | Action |
|-------|-------------------|--------|
| 5.1 Write YAMLs | `workflows/*.yaml` (10 files) as **format reference only** | **Write fresh.** Different pipelines. Use rmhdagmaster YAMLs as structural template. |
| 5.2 Port tiers 1-4 | — | **Write fresh.** Wire existing atomic handlers into YAML graphs. |
| 6.1 Remove CoreMachine | — | **Delete only.** |
| 6.2 Remove SB | — | **Delete only.** One clean cut instead of 3 phases. |
| 6.3 SIEGE final | — | — |

#### Porting Summary

| Category | rmhdagmaster Lines | V10 Output Lines | Ratio |
|----------|-------------------|-----------------|-------|
| Workflow loader (D.1) | ~444 | ~400 (direct port) | 90% reuse |
| DAG initializer (D.3) | ~65 | ~200 (expanded) | Pattern port |
| Param resolver (D.4) | ~302 | ~150 (simplified) | 50% reuse |
| Orchestrator loop (D.5) | ~1,400 | ~400 (heavily adapted) | 30% reuse |
| Evaluator (D.5) | ~734 | ~200 (selective port) | 25% reuse |
| Raster handlers (4.1) | ~2,000 | ~400 (rewrite to fit) | Reference only |
| Dockerfile (D.10) | ~50 | ~50 (direct port) | 100% reuse |
| **Total** | **~5,000** | **~1,800** | |

### Effort Summary (Revised — Strangler Fig)

| Feature | Stories | Est. Days | Risk |
|---------|---------|-----------|------|
| ~~F1: Worker DB-Poll (v0.10.3)~~ | ~~done~~ | ~~DONE~~ | ~~DONE~~ |
| F-DAG: DAG Foundation + Brain | 10 | 10-14 days | **Medium** |
| F4: Handler Decomposition | 4 | 5-8 days | Low |
| F5: Port Workflows (4 tiers) | 2 | 4-6 days | Low (per-workflow rollback) |
| F6: Cleanup (remove legacy) | 3 | 3-4 days | Low |
| **Total** | **19 stories** | **22-32 days** | |

**Savings vs original plan**: ~6 stories eliminated (F2 timer trigger, F3 SB removal phases). F6 "Docker lift" is free (DAG Brain starts as Docker). SB removal consolidated into one cleanup story.

### Dependency Graph (Strangler Fig)

```
                  Stream A                    Stream B
                  (DAG Foundation + Brain)     (Handlers)

Week 1-2:         D.1 workflow loader          F4.1 raster atomics
                  D.2 DAG tables               F4.2 vector atomics
                  D.3 DAG initializer          F4.3 zarr/unpublish
                  D.4 param resolver           F4.4 SIEGE
                        │                            │
Week 3-4:         D.5 DAG orchestrator loop          │
                  D.6 worker dual-poll               │
                  D.7 janitor                        │
                  D.8 gateway routing                │
                  D.9 status integration             │
                  D.10 first blood (hello_world)     │
                        │                            │
                        ▼                            ▼
Week 5-6:         ┌─────────────────────────────────────────────────┐
                  │  F5: Port Workflows (Tier 1 → 2 → 3 → 4)       │
                  │  Requires: F-DAG ✓ + F4 ✓                       │
                  │  Each tier: write YAML + SIEGE                   │
                  │  Rollback: remove YAML file → legacy path        │
                  └──────────────────────┬──────────────────────────┘
                                         │
Week 7:           ┌──────────────────────┴──────────────────────────┐
                  │  F6: Cleanup — remove CoreMachine, SB, jobs/*.py │
                  │  One clean cut. SIEGE final.                      │
                  └─────────────────────────────────────────────────┘
```

**Two parallel streams** (team of 2):
- **Stream A**: DAG Foundation → DAG Brain → first blood. 10-14 days.
- **Stream B**: Handler decomposition. 5-8 days. Can start simultaneously.
- **Convergence**: F5 (port workflows) needs both streams done.
- **Cleanup**: F6 after all workflows ported. One clean cut.

### Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| **Two orchestration systems during migration** | Invisible to clients — Gateway routes transparently. Bounded: each ported workflow reduces legacy scope. Rollback: remove YAML file. |
| **Peak operational complexity** | 4 processes: Function App (gateway+legacy orch) + DAG Brain + Worker + PostgreSQL. But the Worker is unchanged and the Gateway routing is ~10 lines. Monitor via dashboard + SIEGE. |
| **Handler decomposition breaks existing jobs** | Wrapper pattern: monolithic handler calls atomics in sequence. Remove wrappers only in F6 after all workflows on DAG Brain. |
| **DAG orchestrator has subtle concurrency bugs** | Port brain guard from rmhdagmaster (proven). COMPETE adversarial review before first blood (D.10). |
| **YAML schema design needs iteration** | Tier 1 (hello_world) proves the basics. Tier 2 (raster+vector) proves linear chains + `when:`. Tier 3 (zarr) proves fan-out/fan-in. Iterate before Tier 4. |
| **Team of 2 — bus factor** | All decisions in V10_MIGRATION.md. Spec in `docs/superpowers/specs/`. Claude has full context. rmhdagmaster is reference implementation. |
| **Worker polling two tables** | Two SKIP LOCKED queries per cycle. Negligible overhead vs ETL execution time. Remove legacy poll in F6 cleanup. |

---

*Document created: 14 MAR 2026*
*Updated: 16 MAR 2026 — Strangler fig strategy, D.1 completed, agent pipeline recommendations, Epoch 4 freeze*
*Author: Claude + Robert Harrison*
