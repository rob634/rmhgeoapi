# V10 Migration: DAG-Based YAML Workflow Orchestration

**Created**: 14 MAR 2026
**Updated**: 14 MAR 2026
**Status**: DESIGN — versioned migration path agreed (v0.10.3 → v0.13.0)
**Target**: Decompose monolithic job/stage/task system into atomic DAG nodes with YAML workflow definitions
**Justification**: Interchangeable tasks, polling-based orchestration, no distributed messaging complexity
**End State (v0.12.1)**: Function App gateway + Docker orchestrator + Docker workers + PostgreSQL. Zero Service Bus.
**Azure Resources**: See [Azure Resource Map](#azure-resource-map) below.

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

### Vector Pipeline: `vector_docker_complete` → 6 Atomic Handlers

**Current**: One 400-line function with 7 phases.

| Atomic Handler | Extracted From | Input | Output | Lines (est) |
|---------------|---------------|-------|--------|-------------|
| `vector_validate_source` | Phase 1 (validate) | blob_name, container | metadata, row_count, geom_type, crs | ~60 |
| `vector_create_postgis_table` | Phase 2 (DDL) | table_name, schema, metadata | table_created, columns | ~80 |
| `vector_load_chunks` | Phase 3 (upload) | table_name, schema, blob_ref | rows_loaded, chunk_count | ~100 |
| `vector_create_split_views` | Phase 3.7 (conditional) | table_name, split_column | views_created, view_names | ~80 (already in `view_splitter.py`) |
| `catalog_register_vector` | Phase 4 (catalog) | table_name, schema, metadata | catalog_entry_id | ~50 |
| `tipg_refresh_collections` | Phase 5 (TiPG) | (none) | collections_refreshed | ~20 (already in `service_layer_client.py`) |

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

### Version Roadmap

| Version | Phase | What | Breaking? |
|---------|-------|------|-----------|
| **v0.10.3** | 1 | Worker polls DB instead of Service Bus | No |
| **v0.10.4** | 2 | Orchestrator → 60s timer trigger (poll-based) | No |
| **v0.11.0** | 3 | Remove Service Bus entirely | Yes (infra) |
| **v0.11.1** | 4 | Handler decomposition (monolithic → atomic) | No |
| **v0.12.0** | 5 | YAML workflows + DAG tables + DAGOrchestrator | Yes (schema) |
| **v0.12.1** | 6 | Orchestrator → Docker container | No |

**End state at v0.12.1**: Function App gateway + two Docker process types + PostgreSQL. Zero Service Bus.

```
v0.12.1 Architecture:
  Gateway (Function App) — HTTP endpoints, validation, entity management, B2B integration
  Orchestrator (Docker)  — lightweight poll loop, DAG evaluation, no heavy libs
  Workers (Docker × N)   — SKIP LOCKED poll, handler execution, GDAL/xarray/etc.
  PostgreSQL             — single coordination mechanism (no queues, no AMQP)
```

The gateway remains a Function App — it's the right tool for HTTP request/response with Azure's built-in scaling, auth hooks, and APIM integration. Docker is for long-running poll loops and heavy compute, not HTTP endpoints behind Azure infrastructure.

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
- [x] **Backward compat period** — Resolved: Service Bus removed at v0.11.0 (Phase 3), before YAML/DAG work begins. No coexistence period — SB is eliminated while still using Python jobs + CoreMachine. YAML migration (Phase 5, v0.12.0) replaces CoreMachine, not SB.
- [ ] **Observability architecture** — Goal: best possible observability system, not accommodation of legacy patterns. Current `JobEventType` events may be good framework or may be technical debt. Decision: evaluate honestly during Phase 5 — if the event model serves DAG observability well, keep it; if it constrains, build from scratch. Do not compromise observability to preserve old code.

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

*Document created: 14 MAR 2026*
*Author: Claude + Robert Harrison*
