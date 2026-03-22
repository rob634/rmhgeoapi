# V10 Migration: DAG-Based YAML Workflow Orchestration

**Created**: 14 MAR 2026
**Updated**: 21 MAR 2026
**Status**: ACTIVE — v0.10.5 handler decomposition COMPLETE (12 atomic handlers, 2 YAML workflows E2E verified). Orchestrator Release lifecycle implemented. Next: composable STAC (v0.10.6), tiled raster path, production parity.
**Target**: Decompose monolithic job/stage/task system into atomic DAG nodes with YAML workflow definitions
**Justification**: Interchangeable tasks, polling-based orchestration, no distributed messaging complexity
**Migration Strategy**: Strangler fig — DAG Brain runs alongside existing CoreMachine. Workflows ported one at a time via v0.10.x increments. Legacy removed in one clean cut at v0.11.0 when the fig has fully grown and replaced the host plant.
**End State (v0.11.0)**: Function App gateway + Docker DAG Brain + Docker workers + PostgreSQL. Zero Service Bus.
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
| **Non-composable tasks** | `stac_create_item` duplicated in raster, zarr, virtualzarr handlers | Composable STAC materialization layer — 3 generic handlers, zero type knowledge |

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

### Raster Pipeline: `process_raster_complete` → 9 Atomic Nodes (Finalized 16 MAR 2026)

**Current**: One 2,300-line handler with internal tiling decision.

**Design principles**: Granular reusable nodes for composability (FATHOM ETL etc.). All I/O on mount. Conditional routing: single COG vs tiled. One fan-out for tile processing — each tile: extract window → COG → upload.

| Atomic Handler | Used In | Shared With |
|---------------|---------|-------------|
| `raster_download_source` | Both paths | FATHOM, any raster pipeline |
| `raster_validate` | Both paths | FATHOM, any raster pipeline |
| `raster_create_cog` | Path A (single) | FATHOM post-merge |
| `raster_upload_cog` | Path A (single) | Any COG upload |
| `raster_generate_tiling_scheme` | Path B (tiled) | FATHOM |
| `raster_process_single_tile` | Path B (fan-out) | FATHOM (or custom handler) |
| `stac_materialize_item` | Both paths | **Composable**: any raster, zarr, or rebuild workflow |
| `stac_materialize_collection` | Both paths | **Composable**: recalc collection extent |
| `raster_persist_app_tables` | Both paths | All raster workflows |

See "Sample YAML Workflows → Raster Pipeline" for full DAG definition and FATHOM composability example.

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
| `unpublish_inventory_item` | All unpublish workflows | Query internal metadata, extract blob refs |
| `unpublish_delete_blob` | All unpublish workflows | Fan-out: one per blob |
| `stac_dematerialize_item` | Raster + zarr unpublish | Generic: remove from pgSTAC + recalc extent. See Composable STAC Architecture |
| `unpublish_cleanup_postgis` | Vector unpublish | DROP TABLE + metadata |
| `unpublish_cleanup_catalog` | All unpublish workflows | Remove from asset catalog |

### Cross-Cutting Reusable Handlers (Highest Value)

| Handler | Used By | Current Location | Extraction |
|---------|---------|-----------------|------------|
| `tipg_refresh_collections` | All vector workflows | `service_layer_client.py` | **Easy** — already isolated |
| `stac_materialize_item` | All raster + zarr (forward + rebuild) | NEW — composable STAC layer | See Composable STAC Architecture |
| `stac_materialize_collection` | All raster + zarr (forward + rebuild) | NEW — composable STAC layer | See Composable STAC Architecture |
| `stac_dematerialize_item` | All unpublish workflows | Refactor from `STACMaterializer` | See Composable STAC Architecture |
| `catalog_register_asset` | All forward workflows | Scattered | **Medium** — unify interface |
| `catalog_deregister_asset` | All unpublish workflows | Scattered | **Medium** — same |
| `validate_blob_exists` | All ingest workflows | `resource_validators` | **Easy** — exists |
| `unpublish_delete_blob` | All unpublish workflows | `unpublish_handlers.py` | **Easy** — exists |

---

## Composable STAC Architecture (Designed 18 MAR 2026)

### Core Principle: pgSTAC = Materialized View

**pgSTAC is a derived store, not a source of truth.** The source of truth is always the internal metadata tables (`cog_metadata`, zarr metadata, asset catalog, releases). pgSTAC is a selective materialization — a read-optimized view for STAC API consumers.

**Consequence**: If pgSTAC is wiped, it can be rebuilt entirely from internal state. No data loss. No special recovery code. Just re-run the same materialization handlers.

### The Split: Type-Specific Processing vs Generic Materialization

```
Processing (type-specific)              Materialization (generic)
┌──────────────────────────┐           ┌───────────────────────────┐
│ raster_create_cog        │           │ stac_materialize_item     │
│ raster_process_tile      │──writes──→│                           │──writes──→ pgSTAC
│ zarr_copy_store          │  internal │ Reads stac_item_json      │
│ netcdf_convert           │  metadata │ Applies B2C rules         │
│ virtualzarr_combine      │  tables   │ Injects preview URLs      │
└──────────────────────────┘           └───────────────────────────┘
                                                  ↑
                                       Same handler for forward ETL,
                                       approval, AND rebuild
```

**Contract boundary**: Internal metadata tables store a `stac_item_json` cache — a complete STAC item dict built by the processing handler (which has all the type-specific knowledge: bands, CRS, dimensions, etc.). The generic materialization handler reads this cache and writes to pgSTAC with zero type awareness.

### Composable STAC Handler Catalog

**3 generic handlers replace 5 type-specific registration handlers:**

| Handler | Input | What It Does | pgSTAC Write |
|---------|-------|-------------|-------------|
| `stac_materialize_item` | `item_id` (internal) | Read `stac_item_json` from internal tables → B2C sanitize → inject preview URLs → upsert | Upsert 1 item |
| `stac_materialize_collection` | `collection_id` | Recalculate spatial/temporal extent from all items in collection | Upsert collection |
| `stac_dematerialize_item` | `item_id`, `collection_id` | Remove item from pgSTAC → recalc extent or delete empty collection | Delete item |

**What they replace:**

| Before (type-specific) | After (composable) |
|------------------------|-------------------|
| `raster_register_stac_item` | `stac_materialize_item` |
| `raster_register_stac_collection` | fan-out `stac_materialize_item` + `stac_materialize_collection` |
| `ingest_zarr_register` (STAC part) | `stac_materialize_item` |
| `netcdf_register` (STAC part) | `stac_materialize_item` |
| `virtualzarr_register` (STAC part) | `stac_materialize_item` |
| `unpublish_cleanup_stac` | `stac_dematerialize_item` |

### Discovery Handlers (for rebuild workflows)

| Handler | Input | Output | Purpose |
|---------|-------|--------|---------|
| `stac_discover_collection_items` | `collection_id` | `[{item_id, ...}, ...]` | Query internal tables for all items in a collection |
| `stac_discover_all_collections` | — | `[{collection_id, item_count}, ...]` | Query internal tables for all collections with materializable items |

### How Materialization Works in Each Context

| Context | Trigger | Same Handler? |
|---------|---------|--------------|
| **Forward ETL** | Processing handler writes internal metadata → `stac_materialize_item` node runs | Yes |
| **Approval** | Human approves release → approval workflow calls `stac_materialize_item` | Yes |
| **Rebuild single item** | Admin submits `rebuild_stac_item` workflow | Yes |
| **Rebuild collection** | Admin submits `rebuild_stac_collection` workflow → fan-out per item | Yes |
| **Rebuild entire catalog** | Admin submits `rebuild_stac_catalog` workflow → fan-out per collection → fan-out per item | Yes |

### Tiled Raster: Fan-Out Materialization (Design Decision 18 MAR 2026)

Tiled rasters (N tiles → 1 collection) use **per-item fan-out materialization**, not batch:

```
aggregate_tiles (fan_in)
      │
      ▼
materialize_tiles (fan_out)     ← one stac_materialize_item per tile
      │
      ▼
aggregate_materialized (fan_in)
      │
      ▼
materialize_collection          ← recalc extent from all items
```

**Why fan-out, not batch**: Each tile is independently materializable and retryable. Same handler works for forward ETL AND rebuild. N+1 DB calls are fine — pgSTAC upserts are cheap (sub-ms each). Granularity matches the rebuild model perfectly.

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

### Raster Pipeline (Finalized 16 MAR 2026)

**Current**: One 2,300-line handler with internal tiling decision based on file size.

**Design principles**:
- Nodes are granular and reusable — FATHOM ETL and other complex raster pipelines compose from these same building blocks
- All raster I/O goes through the ETL mount — windowed reads prevent memory exhaustion
- Conditional routing: single COG (≤1GB) vs tiled COGs (>1GB) with fan-out
- Raw tile extraction then COG creation — tiles are NOT COGs on input, they're raw GeoTIFF windows

**Tiled path sequence**: Source → extract raw tile (windowed read) → COG-compress tile → upload COG. One fan-out handler does all three per tile. N tiles become N READY tasks claimed by workers via SKIP LOCKED — 1 worker or 10 workers, the DAG doesn't care.

**Fan-out → fan-in → STAC**: Fan-out creates N tile tasks (all READY). Workers process them in any order. Fan-in waits for all N to complete, collects COG blob URLs + item IDs. Then a second fan-out materializes each tile's STAC item independently via the generic `stac_materialize_item` handler. Finally `stac_materialize_collection` recalculates the collection extent — making the tile set searchable.

#### DAG Shape

```
download_source → validate → route_by_size
                                  │
                    ┌──────────────┴──────────────────────────┐
                    │ standard (≤1GB)                          │ large (>1GB)
                    ▼                                          ▼
              create_single_cog                    generate_tiling_scheme
                    │                                          │
              upload_single_cog                    process_tiles (fan_out)
                    │                                  │ each: extract window
          materialize_single_stac                      │       → COG compress
                    │                                  │       → upload to silver
          materialize_single_collection            aggregate_tiles (fan_in)
                    │                                          │
                    │                              materialize_tiles (fan_out)
                    │                                  → per-tile stac_materialize_item
                    │                              aggregate_materialized (fan_in)
                    │                                          │
                    │                              materialize_tiled_collection
                    │                                  → recalc collection extent
                    └──────────────┬───────────────────────────┘
                                   │
                            persist_metadata
```

#### Reusable Node Inventory

| Node | Handler | Reusable In | Key Design |
|------|---------|-------------|-----------|
| `download_source` | `raster_download_source` | Any raster pipeline, FATHOM | Streams blob to mount, returns path |
| `validate` | `raster_validate` | Any raster pipeline | Header + data validation. Rejects missing CRS. |
| `create_single_cog` | `raster_create_cog` | Single COG workflows | Reproject + compress on mount. Windowed reads. |
| `upload_single_cog` | `raster_upload_cog` | Any COG upload | Mount → silver blob storage |
| `generate_tiling_scheme` | `raster_generate_tiling_scheme` | Any tiled workflow, FATHOM | Pure computation: grid dims, overlap, tile specs |
| `process_tiles` (fan-out) | `raster_process_single_tile` | Any tiled workflow | Per-tile: extract window → COG → upload. Independently retryable. |
| `materialize_stac` | `stac_materialize_item` | **All raster + zarr** | Generic: reads internal metadata → pgSTAC. See Composable STAC Architecture |
| `materialize_collection` | `stac_materialize_collection` | **All raster + zarr** | Generic: recalc collection extent from items |
| `persist_metadata` | `raster_persist_app_tables` | All raster workflows | cog_metadata + render_config in app tables (source of truth for STAC) |

#### YAML Workflow

```yaml
# workflows/process_raster_docker.yaml
workflow: process_raster_docker
description: "Raster file → COG (single or tiled) + STAC registration"
version: 1
reversed_by: unpublish_raster

parameters:
  blob_name: {type: str, required: true}
  container_name: {type: str, required: true}
  collection_id: {type: str, required: true}
  processing_options:
    type: dict
    default: {}
    nested:
      target_crs: {type: str, default: "EPSG:4326"}
      raster_type: {type: str, default: "auto"}
      output_tier: {type: str, default: "analysis"}
      overwrite: {type: bool, default: false}

validators:
  - type: blob_exists
    container_param: container_name
    blob_param: blob_name
    zone: bronze

nodes:
  # ── SHARED: Download + Validate (both paths) ──────────────────────

  download_source:
    type: task
    handler: raster_download_source
    params: [blob_name, container_name]
    # Streams blob to mount. Output: intermediate_path, file_size_bytes

  validate:
    type: task
    handler: raster_validate
    depends_on: [download_source]
    params: [processing_options]
    receives:
      source_path: "download_source.intermediate_path"
    # Header check (CRS, bands, format) + data validation (GDAL stats)
    # Rejects: missing CRS, corrupt file, empty raster

  route_by_size:
    type: conditional
    depends_on: [validate]
    condition: "validate.file_size_mb"
    branches:
      - name: large_raster
        condition: "> 1000"
        next: [generate_tiling_scheme]
      - name: standard_raster
        default: true
        next: [create_single_cog]

  # ── PATH A: Single COG (≤1GB) ─────────────────────────────────────

  create_single_cog:
    type: task
    handler: raster_create_cog
    params: [processing_options]
    receives:
      source_path: "download_source.intermediate_path"
      validation: "validate.validation_result"
    # Reproject + COG compress on mount. Windowed reads for memory safety.

  upload_single_cog:
    type: task
    handler: raster_upload_cog
    depends_on: [create_single_cog]
    params: [collection_id]
    receives:
      cog_path: "create_single_cog.intermediate_path"
      validation: "validate.validation_result"
    # Mount → silver blob storage

  # ── PATH A: STAC materialization (single COG) ─────────────────────

  materialize_single_stac:
    type: task
    handler: stac_materialize_item
    depends_on: [upload_single_cog]
    receives:
      item_id: "upload_single_cog.item_id"
    # Generic: reads stac_item_json from internal tables → pgSTAC

  materialize_single_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_single_stac]
    receives:
      collection_id: "materialize_single_stac.collection_id"
    # Recalc collection extent from all items

  # ── PATH B: Tiled COGs (>1GB) ─────────────────────────────────────

  generate_tiling_scheme:
    type: task
    handler: raster_generate_tiling_scheme
    params: [processing_options]
    receives:
      source_path: "download_source.intermediate_path"
      validation: "validate.validation_result"
    # Pure computation: grid dimensions, tile specs with overlap

  process_tiles:
    type: fan_out
    depends_on: [generate_tiling_scheme]
    source: "generate_tiling_scheme.tile_specs"
    task:
      handler: raster_process_single_tile
      params:
        tile_spec: "{{ item }}"
        source_path: "{{ nodes.download_source.intermediate_path }}"
        validation: "{{ nodes.validate.validation_result }}"
      timeout_seconds: 1800
      retry:
        max_attempts: 3
        backoff: exponential
        initial_delay_seconds: 30
    # Per tile: extract window from source → COG compress → upload to silver
    # Each tile independently retryable. Source file shared (concurrent reads safe).

  aggregate_tiles:
    type: fan_in
    depends_on: [process_tiles]
    aggregation: collect
    # Collects: [{cog_blob_url, tile_index, row, col, size_mb}, ...]

  # ── PATH B: STAC materialization (tiled — fan-out per tile) ──────

  materialize_tiles:
    type: fan_out
    depends_on: [aggregate_tiles]
    source: "aggregate_tiles.results"
    task:
      handler: stac_materialize_item
      params:
        item_id: "{{ item.item_id }}"
    # Generic: each tile item materialized independently, retryable

  aggregate_materialized:
    type: fan_in
    depends_on: [materialize_tiles]
    aggregation: collect

  materialize_tiled_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [aggregate_materialized]
    params: [collection_id]
    # Recalc collection extent from all N tile items

  # ── CONVERGE: Both paths → persist app tables ─────────────────────

  persist_metadata:
    type: task
    handler: raster_persist_app_tables
    depends_on:
      - "materialize_single_collection?"
      - "materialize_tiled_collection?"
    params: [collection_id, processing_options]
    # cog_metadata + render_config in app tables (source of truth for STAC)

finalize:
  handler: raster_finalize
```

#### FATHOM Composability Example

FATHOM ETL uses the same building blocks with a custom processing handler in the fan-out:

```yaml
# workflows/fathom_etl.yaml — same nodes, different handler in the middle
nodes:
  download:    {type: task, handler: raster_download_source, ...}
  validate:    {type: task, handler: raster_validate, ...}
  tiling:      {type: task, handler: raster_generate_tiling_scheme, ...}
  process:
    type: fan_out
    source: "tiling.tile_specs"
    task:
      handler: fathom_process_flood_tile    # ← custom FATHOM handler
      params: {tile_spec: "{{ item }}", ...}
  aggregate:   {type: fan_in, depends_on: [process], aggregation: collect}
  materialize: {type: fan_out, source: "aggregate.results", task: {handler: stac_materialize_item, ...}}
  agg_mat:     {type: fan_in, depends_on: [materialize], aggregation: collect}
  collection:  {type: task, handler: stac_materialize_collection, ...}
```

Same download, validate, tiling, and STAC materialization — different processing in the fan-out. This is the composability the DAG system was built for. The STAC nodes are identical across raster, FATHOM, and any future tiled pipeline.

### Zarr Pipelines (Finalized 16 MAR 2026)

**Three zarr pipeline families**, all already ~80% decomposed as isolated handlers in Epoch 4. The DAG adds: explicit fan-out/fan-in node types, conditional routing (copy vs rechunk), and proper batching.

**Technical context**: A Zarr store is a directory tree of chunk files — each chunk is a 256×256 spatial tile for one timestep of one variable (~100KB-1MB). A large climate dataset may have 50,000+ chunk blobs. This granularity enables fast spatial range requests (TiTiler fetches exactly the chunks needed for a map tile) but means blob-copy fan-outs must batch aggressively.

**Conversion mechanics**: `xr.open_mfdataset(nc_files)` opens NetCDF as lazy xarray Dataset. `ds.chunk(target_chunks)` applies optimal chunk shape. `ds.to_zarr(url, encoding=encoding)` writes to Zarr store. `_build_zarr_encoding()` configures: spatial dims → 256, time → 1, other dims → full size, compression → Blosc+LZ4 with BITSHUFFLE. For Zarr v3, codec objects differ from v2 (`zarr.codecs.BloscCodec` vs `numcodecs.Blosc`) and inherited v2 encoding must be cleared before writing v3.

#### Fan-Out Batching Convention

| Source Items | Item Size | Strategy |
|-------------|-----------|----------|
| 10-500 files (NetCDF, tiles) | MB-GB each | One task per item |
| 1,000-50,000 blobs (Zarr chunks) | KB each | **Pre-batch in validate handler** — target ~500MB per batch |

For Zarr blob copies, the validate handler calculates total size and divides into ~500MB batches (roughly 500-2000 blobs per task depending on chunk size). The fan-out creates one task per batch, not one per blob. This prevents 50,000 `workflow_tasks` rows for tiny blobs. Batch size fine-tuning is a handler parameter, not a schema concern.

```yaml
# validate handler outputs batched blob lists:
# blob_batches: [[blob_0..blob_1999], [blob_2000..blob_3999], ...]
# NOT: blob_list: [blob_0, blob_1, ..., blob_49999]
```

#### Ingest Zarr (native Zarr store → silver)

```
validate → route_copy_mode
                │
      ┌─────────┴──────────┐
      │ copy (default)      │ rechunk
      ▼                     ▼
  copy_batches (fan_out) rechunk (task)
      │                     │
  aggregate_copies          │
      └─────────┬───────────┘
                │
           register
```

```yaml
workflow: ingest_zarr
description: "Native Zarr store → silver-zarr + STAC registration"
version: 1
reversed_by: unpublish_zarr

parameters:
  source_url: {type: str, required: true}
  source_account: {type: str, required: true}
  dataset_id: {type: str, required: true}
  resource_id: {type: str, required: true}
  stac_item_id: {type: str, required: true}
  collection_id: {type: str, required: true}
  access_level: {type: str, required: true}
  rechunk: {type: bool, default: false}
  spatial_chunk_size: {type: int, default: 256}
  time_chunk_size: {type: int, default: 1}
  compressor: {type: str, default: "lz4"}
  compression_level: {type: int, default: 5}
  zarr_format: {type: int, default: 3}

nodes:
  validate:
    type: task
    handler: ingest_zarr_validate
    params: [source_url, source_account, dataset_id, resource_id]
    # Validates store structure, enumerates blobs
    # Output: blob_batches (pre-batched ~500MB each), zarr_metadata

  route_copy_mode:
    type: conditional
    depends_on: [validate]
    condition: "params.rechunk"
    branches:
      - name: rechunk
        condition: "true"
        next: [rechunk]
      - name: copy
        default: true
        next: [copy_batches]

  copy_batches:
    type: fan_out
    source: "validate.blob_batches"
    task:
      handler: ingest_zarr_copy_batch
      params:
        batch: "{{ item }}"
        source_url: "{{ inputs.source_url }}"
        source_account: "{{ inputs.source_account }}"
        dataset_id: "{{ inputs.dataset_id }}"
        resource_id: "{{ inputs.resource_id }}"
    # Each task copies ~500MB of blobs (500-2000 individual chunks)

  aggregate_copies:
    type: fan_in
    depends_on: [copy_batches]
    aggregation: collect

  rechunk:
    type: task
    handler: ingest_zarr_rechunk
    params: [source_url, source_account, dataset_id, resource_id,
             spatial_chunk_size, time_chunk_size, compressor,
             compression_level, zarr_format]
    # Opens source Zarr via xarray, clears v2 encoding, applies optimized
    # chunks (256×256 spatial, time=1, Blosc+LZ4), writes to silver as v3

  register:
    type: task
    handler: ingest_zarr_register
    depends_on:
      - "aggregate_copies?"
      - "rechunk?"
    params: [stac_item_id, collection_id, dataset_id, resource_id, access_level]
    receives:
      zarr_metadata: "validate.zarr_metadata"
    # Writes zarr metadata to internal tables (incl. stac_item_json cache)

  materialize_stac:
    type: task
    handler: stac_materialize_item
    depends_on: [register]
    receives:
      item_id: "register.item_id"
    # Generic: reads stac_item_json from internal tables → pgSTAC

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_stac]
    receives:
      collection_id: "materialize_stac.collection_id"
    # Recalc collection extent

finalize:
  handler: zarr_finalize
```

#### NetCDF-to-Zarr (NetCDF files → native Zarr)

```
scan → copy_to_mount (fan_out) → aggregate → validate_files (fan_out) → aggregate → convert → register
```

```yaml
workflow: netcdf_to_zarr
description: "NetCDF files → native Zarr store (optimized chunks) + STAC"
version: 1
reversed_by: unpublish_zarr

parameters:
  source_url: {type: str, required: true}
  source_account: {type: str, required: true}
  dataset_id: {type: str, required: true}
  resource_id: {type: str, required: true}
  stac_item_id: {type: str, required: true}
  collection_id: {type: str, required: true}
  access_level: {type: str, required: true}
  output_folder: {type: str, required: true}
  spatial_chunk_size: {type: int, default: 256}
  time_chunk_size: {type: int, default: 1}
  compressor: {type: str, default: "lz4"}
  compression_level: {type: int, default: 5}

nodes:
  scan:
    type: task
    handler: netcdf_scan
    params: [source_url, source_account, dataset_id, resource_id, output_folder]
    # Lists NetCDF files in bronze, builds manifest
    # Output: file_list (one entry per file, not batched — files are large)

  copy_to_mount:
    type: fan_out
    depends_on: [scan]
    source: "scan.file_list"
    task:
      handler: netcdf_copy
      params:
        file_info: "{{ item }}"
        source_account: "{{ inputs.source_account }}"
    # One task per file — files are 50MB-2GB each, worth individual tasks

  aggregate_copies:
    type: fan_in
    depends_on: [copy_to_mount]
    aggregation: collect

  validate_files:
    type: fan_out
    depends_on: [aggregate_copies]
    source: "aggregate_copies.results"
    task:
      handler: netcdf_validate
      params:
        local_path: "{{ item.local_path }}"
    # One task per file — xarray structure validation

  aggregate_validations:
    type: fan_in
    depends_on: [validate_files]
    aggregation: collect

  convert:
    type: task
    handler: netcdf_convert
    depends_on: [aggregate_validations]
    params: [output_folder, dataset_id, resource_id,
             spatial_chunk_size, time_chunk_size, compressor, compression_level]
    receives:
      validated_files: "aggregate_validations.results"
    # xr.open_mfdataset → .chunk(spatial=256, time=1) → .to_zarr(encoding=Blosc+LZ4)
    # Single task — must see all files for coordinate alignment
    # Heaviest operation: long timeout, potentially GB of I/O

  register:
    type: task
    handler: netcdf_register
    depends_on: [convert]
    params: [stac_item_id, collection_id, dataset_id, resource_id, access_level]
    receives:
      zarr_store_url: "convert.zarr_store_url"
    # Writes zarr metadata to internal tables (incl. stac_item_json cache)

  materialize_stac:
    type: task
    handler: stac_materialize_item
    depends_on: [register]
    receives:
      item_id: "register.item_id"

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_stac]
    receives:
      collection_id: "materialize_stac.collection_id"

finalize:
  handler: zarr_finalize
```

#### VirtualiZarr (NetCDF → virtual Zarr references)

Same DAG shape as NetCDF-to-Zarr but `combine` replaces `convert` — builds virtual references instead of writing real chunks.

```yaml
workflow: virtualzarr
description: "NetCDF files → virtual Zarr references + STAC"
version: 1
reversed_by: unpublish_zarr

parameters:
  source_url: {type: str, required: true}
  source_account: {type: str, required: true}
  dataset_id: {type: str, required: true}
  resource_id: {type: str, required: true}
  stac_item_id: {type: str, required: true}
  collection_id: {type: str, required: true}
  access_level: {type: str, required: true}

nodes:
  scan:
    type: task
    handler: virtualzarr_scan
    params: [source_url, source_account, dataset_id, resource_id]

  copy_to_mount:
    type: fan_out
    depends_on: [scan]
    source: "scan.file_list"
    task:
      handler: virtualzarr_copy
      params:
        file_info: "{{ item }}"
        source_account: "{{ inputs.source_account }}"

  aggregate_copies:
    type: fan_in
    depends_on: [copy_to_mount]
    aggregation: collect

  validate_files:
    type: fan_out
    depends_on: [aggregate_copies]
    source: "aggregate_copies.results"
    task:
      handler: virtualzarr_validate
      params:
        local_path: "{{ item.local_path }}"

  aggregate_validations:
    type: fan_in
    depends_on: [validate_files]
    aggregation: collect

  combine:
    type: task
    handler: virtualzarr_combine
    depends_on: [aggregate_validations]
    params: [dataset_id, resource_id]
    receives:
      validated_files: "aggregate_validations.results"
    # Builds virtual references — no data copying, just metadata

  register:
    type: task
    handler: virtualzarr_register
    depends_on: [combine]
    params: [stac_item_id, collection_id, dataset_id, resource_id, access_level]
    receives:
      zarr_ref_url: "combine.reference_url"
    # Writes zarr metadata to internal tables (incl. stac_item_json cache)

  materialize_stac:
    type: task
    handler: stac_materialize_item
    depends_on: [register]
    receives:
      item_id: "register.item_id"

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_stac]
    receives:
      collection_id: "materialize_stac.collection_id"

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

### STAC Rebuild Workflows (Designed 18 MAR 2026)

**Principle**: pgSTAC is a materialized view of internal metadata tables. These workflows rebuild pgSTAC at any granularity using the same `stac_materialize_item` and `stac_materialize_collection` handlers used in forward ETL pipelines. No special recovery code.

#### Rebuild Single Item

```yaml
# workflows/rebuild_stac_item.yaml
workflow: rebuild_stac_item
description: "Rematerialize a single STAC item from internal metadata"
version: 1

parameters:
  item_id: {type: str, required: true}

nodes:
  materialize:
    type: task
    handler: stac_materialize_item
    params: [item_id]
    # Same handler used in forward ETL — reads stac_item_json → pgSTAC

  update_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize]
    receives:
      collection_id: "materialize.collection_id"
    # Recalc extent after item rematerialized
```

#### Rebuild Single Collection

```yaml
# workflows/rebuild_stac_collection.yaml
workflow: rebuild_stac_collection
description: "Rematerialize all STAC items in a collection from internal metadata"
version: 1

parameters:
  collection_id: {type: str, required: true}

nodes:
  discover:
    type: task
    handler: stac_discover_collection_items
    params: [collection_id]
    # Queries internal metadata tables → [{item_id, ...}, ...]

  materialize_items:
    type: fan_out
    depends_on: [discover]
    source: "discover.items"
    task:
      handler: stac_materialize_item
      params:
        item_id: "{{ item.item_id }}"
    # Each item independently materialized and retryable

  aggregate:
    type: fan_in
    depends_on: [materialize_items]
    aggregation: collect

  rebuild_extent:
    type: task
    handler: stac_materialize_collection
    depends_on: [aggregate]
    params: [collection_id]
    # Recalc collection extent from all materialized items
```

#### Rebuild Entire Catalog (Nuclear)

```yaml
# workflows/rebuild_stac_catalog.yaml
workflow: rebuild_stac_catalog
description: "Rematerialize entire pgSTAC catalog from internal metadata"
version: 1

nodes:
  discover_collections:
    type: task
    handler: stac_discover_all_collections
    # Queries internal tables → [{collection_id, item_count}, ...]

  rebuild_per_collection:
    type: fan_out
    depends_on: [discover_collections]
    source: "discover_collections.collections"
    task:
      handler: stac_rebuild_single_collection
      params:
        collection_id: "{{ item.collection_id }}"
    # Each collection: discover items → materialize each → rebuild extent
    # Handler internally does the discover → loop → extent pattern

  summary:
    type: fan_in
    depends_on: [rebuild_per_collection]
    aggregation: collect
    # Collects: [{collection_id, items_materialized, status}, ...]
```

**Note on `stac_rebuild_single_collection`**: This is a compound handler that internally discovers items and materializes them in a loop (not a sub-workflow). For collections with <100 items this is efficient. For very large collections (>1000 tiles), consider submitting `rebuild_stac_collection` as a sub-workflow instead.

---

### H3 Hexagonal Aggregation Pipelines (Designed 17 MAR 2026)

**Design source**: `rmhdagmaster/docs/HEXAGONS.md` — comprehensive H3 pipeline design document.

**Key design shift from Epoch 4**: No PostgreSQL for computed stats. H3 grid generated on-the-fly by `h3-py` (not pre-built in PostGIS). Parquet files on blob storage are the sole output. Database = recipe book (`h3_raster_sources`, `h3_vector_sources`, `h3_computation_runs`, `h3_output_manifest`). Output = Parquet queryable by DuckDB.

**Fan-out unit**: L3 cell (~2,800 descendants at L3-L7). Sweet spot — 50-500 tasks per raster, good parallelism, amortizes overhead.

**Static land filter**: Pre-computed list of ~15K L3 cell IDs covering land + littoral waters. No runtime geometry intersection. Discovery node intersects raster bbox with static set.

#### H3 Raster Zonal Stats

The core pipeline. Aggregates any raster (DEM, flood, land cover, climate) to H3 cells with mean/sum/median/stdev.

```
discover → fan_out (per L3 cell) → fan_in → compact → register
```

```yaml
workflow: h3_raster_zonal_stats
description: "Raster → H3 zonal statistics (Parquet output)"
version: 1

parameters:
  source_id: {type: str, required: true}          # registered in h3_raster_sources
  period: {type: str, default: "static"}           # "static", "2025-01", "2024"
  stats: {type: list, default: ["mean", "sum", "median", "stdev"]}
  h3_levels: {type: list, default: [3, 4, 5, 6, 7]}

nodes:
  discover:
    type: task
    handler: h3_discover_raster
    params: [source_id, period]
    # Loads source config from h3_raster_sources
    # Resolves raster: STAC URL or blob path → bbox, CRS, band info
    # Intersects bbox L3 cells with static land set
    # Pre-creates computation_run record (frozen config snapshot)
    # Output: raster_info, l3_cells (fan-out list)

  compute_stats:
    type: fan_out
    depends_on: [discover]
    source: "discover.l3_cells"
    task:
      handler: h3_zonal_stats
      params:
        l3_cell: "{{ item }}"
        raster_info: "{{ nodes.discover.raster_info }}"
        stats: "{{ inputs.stats }}"
        h3_levels: "{{ inputs.h3_levels }}"
      timeout_seconds: 300
      retry:
        max_attempts: 3
        backoff: exponential
        initial_delay_seconds: 10
    # Per L3 cell: generate ~2,800 descendant polygons via h3-py,
    # windowed raster read for L3 bbox, exactextract zonal stats,
    # write Parquet sorted by h3_index to blob storage

  aggregate:
    type: fan_in
    depends_on: [compute_stats]
    aggregation: collect

  compact:
    type: task
    handler: h3_compact_parquet
    depends_on: [aggregate]
    params: [source_id, period]
    receives:
      chunk_paths: "aggregate.results"
    # Merge per-chunk parquets into production files
    # Write h3_output_manifest entries

  register:
    type: task
    handler: h3_register_computation
    depends_on: [compact]
    params: [source_id, period]
    # Update h3_computation_runs status = completed

finalize:
  handler: h3_finalize
```

#### H3 Vector Aggregation (Points, Lines, Polygons)

Same DAG pattern. Handler varies by geometry type. Sources are Overture Maps GeoParquet (HTTP, no import) or internal PostGIS tables.

```yaml
workflow: h3_vector_aggregation
description: "Vector features → H3 aggregation (Parquet output)"
version: 1

parameters:
  source_id: {type: str, required: true}          # registered in h3_vector_sources
  period: {type: str, default: "static"}

nodes:
  discover:
    type: task
    handler: h3_discover_vector
    params: [source_id, period]
    # Loads source config from h3_vector_sources
    # Determines access method: overture | geoparquet | postgis
    # Intersects coverage bbox with static land set
    # Output: source_config, l3_cells, access_method

  route_by_geometry:
    type: conditional
    depends_on: [discover]
    condition: "discover.geometry_op"
    branches:
      - name: point_assign
        condition: "== assign"
        next: [aggregate_points]
      - name: line_clip
        condition: "== clip"
        next: [aggregate_lines]
      - name: polygon_area
        condition: "== area"
        next: [aggregate_polygons]
      - name: binary_intersect
        condition: "== binary_intersect"
        next: [aggregate_binary]
      - name: connectivity
        condition: "== connectivity"
        next: [aggregate_connectivity]
      - name: default_assign
        default: true
        next: [aggregate_points]

  # ── Point aggregation (POIs, events, buildings-as-centroids) ────
  aggregate_points:
    type: fan_out
    source: "discover.l3_cells"
    task:
      handler: h3_point_aggregation
      params:
        l3_cell: "{{ item }}"
        source_config: "{{ nodes.discover.source_config }}"

  # ── Line aggregation (roads, waterways — clip + length) ─────────
  aggregate_lines:
    type: fan_out
    source: "discover.l3_cells"
    task:
      handler: h3_line_aggregation
      params:
        l3_cell: "{{ item }}"
        source_config: "{{ nodes.discover.source_config }}"

  # ── Polygon aggregation (buildings area, land use area) ─────────
  aggregate_polygons:
    type: fan_out
    source: "discover.l3_cells"
    task:
      handler: h3_polygon_aggregation
      params:
        l3_cell: "{{ item }}"
        source_config: "{{ nodes.discover.source_config }}"

  # ── Binary intersect (national parks, flood zones — sparse) ─────
  aggregate_binary:
    type: fan_out
    source: "discover.l3_cells"
    task:
      handler: h3_binary_intersect
      params:
        l3_cell: "{{ item }}"
        source_config: "{{ nodes.discover.source_config }}"

  # ── Connectivity (road boundary crossings — edge list) ──────────
  aggregate_connectivity:
    type: fan_out
    source: "discover.l3_cells"
    task:
      handler: h3_connectivity
      params:
        l3_cell: "{{ item }}"
        source_config: "{{ nodes.discover.source_config }}"
    # Per L3 cell: load road segments, detect cell boundary crossings,
    # ownership filter (smaller L3 ID owns boundary edges — no shuffle),
    # output edge list parquet

  # ── Converge all paths ──────────────────────────────────────────
  collect_results:
    type: fan_in
    depends_on:
      - "aggregate_points?"
      - "aggregate_lines?"
      - "aggregate_polygons?"
      - "aggregate_binary?"
      - "aggregate_connectivity?"
    aggregation: collect

  compact:
    type: task
    handler: h3_compact_parquet
    depends_on: [collect_results]
    params: [source_id, period]
    receives:
      chunk_paths: "collect_results.results"

  register:
    type: task
    handler: h3_register_computation
    depends_on: [compact]
    params: [source_id, period]

finalize:
  handler: h3_finalize
```

#### H3 Complex Aggregation (Multi-Source Weighted)

Composes outputs from raster and vector workflows. No fan-out — operates on pre-computed parquet files.

```yaml
workflow: h3_weighted_aggregation
description: "Combine multiple H3 datasets with analyst-configured weights"
version: 1

parameters:
  model_id: {type: str, required: true}            # e.g., "flood_conservative"
  base_source_id: {type: str, required: true}      # e.g., "fathom_flood_30m"
  weight_sources: {type: list, required: true}      # [{source_id, column, weight}]
  output_name: {type: str, required: true}
  h3_levels: {type: list, default: [7]}

nodes:
  load_model:
    type: task
    handler: h3_load_model_profile
    params: [model_id]
    # Loads analyst-configured weights/thresholds from profile YAML
    # Output: weights, thresholds, output_columns

  validate_sources:
    type: task
    handler: h3_validate_source_availability
    depends_on: [load_model]
    params: [base_source_id, weight_sources]
    # Verifies all source parquets exist (completed computation runs)
    # Rejects if any source missing — fail before compute, not during

  compute_weighted:
    type: task
    handler: h3_weighted_aggregation
    depends_on: [validate_sources]
    params: [base_source_id, weight_sources, output_name, h3_levels]
    receives:
      model: "load_model.profile"
    # DuckDB joins: base parquet ⟕ weight parquets on h3_index
    # Applies weights, computes composite score
    # Writes output parquet

  register:
    type: task
    handler: h3_register_computation
    depends_on: [compute_weighted]
    params: [output_name]

finalize:
  handler: h3_finalize
```

#### H3 Node Inventory (All New Handlers)

| Handler | Category | Geometry | Reusable In |
|---------|----------|----------|-------------|
| `h3_discover_raster` | Reconnaissance | — | Raster zonal stats |
| `h3_discover_vector` | Reconnaissance | — | All vector aggregation |
| `h3_zonal_stats` | ETL | raster | Core raster aggregation, any source |
| `h3_point_aggregation` | ETL | point | POI counts, event counts, building centroids |
| `h3_line_aggregation` | ETL | line | Road length, waterway length by class |
| `h3_polygon_aggregation` | ETL | polygon | Building area, land use area |
| `h3_binary_intersect` | ETL | polygon | National parks, flood zones, admin boundaries |
| `h3_connectivity` | ETL | line | Road boundary crossings → edge list |
| `h3_weighted_aggregation` | Planning | — | Multi-source composite scores |
| `h3_compact_parquet` | ETL | — | Merge per-chunk parquets → production files |
| `h3_register_computation` | ETL | — | Update computation catalog |
| `h3_load_model_profile` | Inference | — | Analyst-configured weight profiles |
| `h3_validate_source_availability` | Reconnaissance | — | Verify all inputs exist before compute |

#### Parquet Output Layout

```
h3_stats/
  source={source_id}/
    period={period}/
      resolution={level}/
        h3_l3={cell_id}.parquet       ← per-chunk (fan-out output)
      resolution={level}.parquet      ← compacted (production)

h3_connectivity/
  resolution={level}/
    h3_l3={cell_id}.parquet           ← edge list per chunk

h3_views/
  {model_id}_{output_name}.parquet    ← materialized wide views
```

#### Database Catalog Tables (Recipe Book)

| Table | Purpose |
|-------|---------|
| `dagapp.h3_raster_sources` | Registered raster data sources + processing config |
| `dagapp.h3_vector_sources` | Registered vector data sources + geometry_op config |
| `dagapp.h3_computation_runs` | Run records with frozen config_snapshot |
| `dagapp.h3_output_manifest` | What parquet files were produced by each run |

Database stores what to compute and what was computed. Parquet stores the computed results. No OLTP for stats — pure OLAP via DuckDB.

### Zonal Statistics with Geometry Inputs (Designed 17 MAR 2026)

**Use case**: "Aggregate mean elevation per admin2 district in Kenya using the latest OCHA boundaries." Boundary sources change monthly (OCHA) to annually (GADM). The raster stays the same. Rerun often with new boundary versions.

**Key difference from H3**: H3 cells are uniform, deterministic, and eternal (math, not data). Admin boundaries are irregular, versioned, and politically contested. Multiple competing boundary sources (OCHA, GADM, Natural Earth) disagree on where districts are.

#### Boundary Source Catalog

Versioned — same source can have multiple versions. Composite primary key `(source_id, version)`.

```sql
CREATE TABLE dagapp.zonal_boundary_sources (
    source_id         TEXT NOT NULL,
    version           TEXT NOT NULL,           -- "2026-03", "4.1", "v2"
    name              TEXT NOT NULL,           -- "OCHA Administrative Boundaries"
    description       TEXT,
    access_type       TEXT NOT NULL,           -- geoparquet | postgis | overture
    access_uri        TEXT NOT NULL,           -- blob path, PostGIS table, Overture glob
    zone_id_column    TEXT NOT NULL,           -- "admin2_pcode", "GID_2", "basin_id"
    zone_name_column  TEXT,                    -- "admin2_name" (for display)
    admin_level       INT,                     -- 0=country, 1=province, 2=district (NULL for non-admin)
    total_zones       INT,
    coverage_bbox     FLOAT[],                -- [west, south, east, north]
    active            BOOLEAN NOT NULL DEFAULT true,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, version)
);
```

#### Memory-Safe Batching (CRITICAL — Prevents OOM)

Zonal stats reads a raster window covering the batch bounding box. Scattered polygons = huge window with wasted pixels. Batching must constrain the bbox area based on raster resolution.

**Memory budget calculation**:

| Raster Resolution | Max Batch Bbox | Why |
|-------------------|---------------|-----|
| 90m (SRTM) | ~2,000km × 2,000km | Window fits in ~2GB at 4 bytes/pixel |
| 30m (Copernicus DEM) | ~660km × 660km | Same budget, more pixels per km |
| 10m (ESA WorldCover) | ~220km × 220km | High-res = aggressive batching |
| 1m (custom aerial) | ~22km × 22km | City-scale batches only |

**Batching strategy**: Spatial proximity clustering, NOT arbitrary count-based chunking.

```python
def batch_by_proximity(polygons, pixel_size_m, worker_memory_gb=4):
    """
    Group polygons so each batch's raster window fits in worker memory.

    1. Calculate max_bbox_pixels from worker memory budget
    2. Sort polygons by centroid (Hilbert curve for spatial locality)
    3. Greedily add polygons to current batch
    4. If adding polygon would expand bbox beyond pixel budget → new batch
    """
    available_bytes = (worker_memory_gb - 0.7) * 1024**3  # 700MB for Python+GDAL overhead
    bytes_per_pixel = 4  # float32
    max_pixels = available_bytes / bytes_per_pixel
    max_extent_m = (max_pixels ** 0.5) * pixel_size_m
    max_bbox_area_km2 = (max_extent_m / 1000) ** 2

    # ... spatial clustering within this budget ...
```

**The `load_boundaries` node receives raster resolution from `discover_raster`** — this is a dependency. Can't batch boundaries without knowing the raster's pixel size.

**Giant polygon handling** (e.g., Sakha Republic = 3.1M km² at 30m = 40GB): The `zonal_compute_polygon_stats` handler internally tiles oversized polygons into sub-windows, computes partial stats per tile, and merges (mean = weighted average by pixel count, sum = simple sum). This is an **internal handler concern**, not a DAG node — doesn't change graph shape (passes granularity rule).

**`exactextract` specifics**: Does NOT load full raster into memory. Iterates per-polygon, reads only intersecting pixels. Main cost is the `rasterio` window covering the batch bbox. For COG streaming, scattered polygons cause excessive HTTP range requests (slow, not OOM). Proximity batching prevents both memory and I/O problems.

#### DAG Workflow

```
discover_raster ──→ load_boundaries ──→ plan ──→ compute_stats (fan_out) ──→ aggregate ──→ compact ──→ register
                  (needs pixel_size_m         ~50-100 polygons per batch
                   for bbox budgeting)        windowed raster read + exactextract
```

```yaml
workflow: zonal_stats_geometry
description: "Raster → zonal statistics by versioned polygon boundaries"
version: 1

parameters:
  raster_source_id: {type: str, required: true}
  boundary_source_id: {type: str, required: true}
  boundary_version: {type: str, required: true}
  period: {type: str, default: "static"}
  stats: {type: list, default: ["mean", "sum", "median", "stdev"]}
  admin_level: {type: int, required: false}

nodes:
  discover_raster:
    type: task
    handler: h3_discover_raster
    params: [raster_source_id, period]
    # REUSED from H3 pipeline — resolves raster bbox, CRS, bands, pixel_size_m
    # Doesn't know or care whether consumer is H3 cells or admin polygons

  load_boundaries:
    type: task
    handler: zonal_load_boundary_set
    depends_on: [discover_raster]
    params: [boundary_source_id, boundary_version, admin_level]
    receives:
      pixel_size_m: "discover_raster.pixel_size_m"
    # Loads versioned polygon boundaries from registered source
    # Validates: all polygons have zone_id, valid geometry, CRS = 4326
    # Batches by spatial proximity constrained by raster-resolution-dependent bbox budget
    # Rejects: invalid geometries, missing zone_ids, CRS mismatch
    # Output: boundary_batches (spatially clustered), total_zones

  plan_extraction:
    type: task
    handler: zonal_plan_extraction
    depends_on: [discover_raster, load_boundaries]
    receives:
      raster_info: "discover_raster.raster_info"
      boundary_bbox: "load_boundaries.coverage_bbox"
    # Verifies raster covers boundary extent (warn if partial coverage)
    # Output: extraction_plan with coverage_pct

  compute_stats:
    type: fan_out
    depends_on: [plan_extraction]
    source: "load_boundaries.boundary_batches"
    task:
      handler: zonal_compute_polygon_stats
      params:
        batch: "{{ item }}"
        raster_info: "{{ nodes.discover_raster.raster_info }}"
        stats: "{{ inputs.stats }}"
      timeout_seconds: 600
      retry:
        max_attempts: 3
        backoff: exponential
        initial_delay_seconds: 15
    # Per batch (~50-100 spatially proximate polygons):
    #   1. Compute batch bbox
    #   2. Windowed raster read covering batch bbox (NOT full raster)
    #   3. exactextract per polygon (reads only intersecting pixels)
    #   4. Giant polygon detection: internal tiling + stat merge
    #   5. Write Parquet: zone_id | zone_name | mean | sum | median | stdev

  aggregate:
    type: fan_in
    depends_on: [compute_stats]
    aggregation: collect

  compact:
    type: task
    handler: zonal_compact_results
    depends_on: [aggregate]
    params: [raster_source_id, boundary_source_id, boundary_version, period]
    receives:
      chunk_paths: "aggregate.results"
    # Merge per-batch parquets into single output file

  register:
    type: task
    handler: zonal_register_computation
    depends_on: [compact]
    params: [raster_source_id, boundary_source_id, boundary_version, period]

finalize:
  handler: zonal_finalize
```

#### Versioned Output Layout

```
zonal_stats/
  raster={raster_source_id}/
    boundary={boundary_source_id}/
      version={boundary_version}/
        period={period}/
          all.parquet                    ← compacted single file
```

Immutable. Both versions queryable. DuckDB can compare across boundary versions:

```sql
-- What changed between March and April OCHA boundaries?
SELECT a.zone_id, a.zone_name, a.mean AS mar_elevation, b.mean AS apr_elevation
FROM 'zonal_stats/.../version=2026-03/.../all.parquet' a
FULL JOIN 'zonal_stats/.../version=2026-04/.../all.parquet' b USING (zone_id)
WHERE a.mean != b.mean OR a.zone_id IS NULL OR b.zone_id IS NULL
```

#### New Handlers

| Handler | Category | Shared? |
|---------|----------|---------|
| `h3_discover_raster` | Reconnaissance | **Reused** from H3 pipeline |
| `zonal_load_boundary_set` | Reconnaissance | **New** — versioned boundary loading + proximity batching |
| `zonal_plan_extraction` | Planning | **New** — raster/boundary coverage validation |
| `zonal_compute_polygon_stats` | ETL | **New** — exactextract per batch, giant polygon tiling |
| `zonal_compact_results` | ETL | **Reuse pattern** from H3 compact |
| `zonal_register_computation` | ETL | **Reuse pattern** from H3 register |

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

### Version Roadmap (Revised 19 MAR 2026 — Strangler Fig Increments)

The strangler fig grows through v0.10.x increments. Each version adds capability to the DAG system while legacy CoreMachine continues operating unchanged. At v0.11.0 the fig has fully grown — the host plant (CoreMachine + Service Bus) is removed in one clean cut.

| Version | Phase | What | Breaking? | Status |
|---------|-------|------|-----------|--------|
| **v0.10.3** | F1 | Worker polls DB instead of Service Bus | No | **DONE** |
| **v0.10.4** | F-DAG | DAG Foundation: loader, tables, initializer, resolver, orchestrator, gateway routing, hello_world E2E | No (additive schema) | **DONE** |
| **v0.10.4.x** | F-SCHED | Scheduler + API-driven workflows: DAGScheduler thread, app.schedules table, admin endpoints, APIRepository, ACLED sync workflow | No (additive schema) | **BUILT** — needs wiring + deploy |
| **v0.10.5** | F4a | Handler decomposition: raster + vector atomics | No (wrappers preserve existing) | **IN PROGRESS** — vector done, raster in progress |
| **v0.10.6** | F4b | Handler decomposition: composable STAC + unpublish + zarr atomics | No (wrappers preserve existing) | NOT STARTED |
| **v0.10.7** | F5a | Port vector workflows to DAG (vector_docker_etl, unpublish_vector, vector_multi_source) | No (opt-in routing, per-workflow rollback) | NOT STARTED |
| **v0.10.8** | F5b | Port raster workflows to DAG (process_raster_docker, unpublish_raster) | No (opt-in routing, per-workflow rollback) | NOT STARTED |
| **v0.10.9** | F5c | Port zarr workflows to DAG (ingest_zarr, netcdf_to_zarr, virtualzarr, unpublish_zarr + remaining) | No (opt-in routing, per-workflow rollback) | NOT STARTED |
| **v0.11.0** | F6 | **Strangler fig complete**: remove CoreMachine, Service Bus, Python job classes. DAG is sole orchestrator. | **Yes** (infra) | NOT STARTED |

**Migration approach**: Strangler fig. DAG Brain (Docker) runs alongside Function App orchestrator. Handlers decomposed first (v0.10.5-6), then workflows ported one tier at a time (v0.10.7-9), each SIEGE-validated. When all 14 are proven, legacy system removed in one clean cut (v0.11.0).

**Decomposition priority** (v0.10.5-6): Raster → vector → composable STAC → unpublish → zarr. Raster is the most complex monolith (2,300 lines), so decompose it first. Zarr handlers are already ~80% atomic, so they come last.

**Porting order** (v0.10.7-9): Vector → raster → zarr. Vector is simplest to validate E2E (linear DAG, no fan-out). Raster adds conditional routing (single vs tiled). Zarr adds fan-out/fan-in. Each tier proves incrementally more DAG capability.

**What changed from original roadmap**:
- **F2 (timer trigger) eliminated** — the DAG Brain IS the new orchestrator. No point converting Function App to polling when we're about to replace it.
- **v0.10.x increments replace v0.11.x/v0.12.x** (revised 19 MAR 2026) — all intermediate work stays in v0.10.x. v0.11.0 is reserved for the clean cut. This keeps each increment deployable and rollback-safe.
- **F6 (Docker lift) free** — DAG Brain starts as Docker from day one.

**End state at v0.11.0**: Function App gateway + Docker DAG Brain + Docker workers + PostgreSQL. Zero Service Bus.

```
v0.11.0 Architecture (strangler fig complete):
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

### Phase 2: DAG Foundation (v0.10.4) — DONE

**What**: Built the complete DAG orchestration system and stood it up as a Docker container alongside the existing Function App. 10 stories (D.1-D.10), all complete.

**Delivered**: Workflow loader + registry, DAG database tables, DAG initializer, parameter resolver, DAG orchestrator core loop (brain guard, fan-out, fan-in, conditionals), worker dual-poll, janitor, gateway opt-in routing, DAG status endpoints, hello_world E2E.

**Legacy impact**: Zero — CoreMachine unchanged, all existing jobs work identically.

### Phase 2b: Scheduler + API-Driven Workflows (v0.10.4.x) — BUILT, PENDING DEPLOY

**Spec**: `docs/superpowers/specs/2026-03-20-scheduler-api-workflows-design.md`
**COMPETE**: Run 50 — 28 findings, all top 5 fixes applied.
**Date**: 20 MAR 2026

Added two new capabilities to the DAG system:

1. **Scheduler** — DAG Brain background thread (alongside janitor) that polls `app.schedules` for due cron-based workflows and submits runs.
2. **API-driven workflows** — workflows that fetch data from external APIs, save raw responses to Bronze, and append to Silver.

**What was built (3 workstreams, 10 new files, ~2,300 lines):**

| Workstream | Files | Purpose |
|-----------|-------|---------|
| W1: API Repository | `infrastructure/api_repository.py`, `acled_repository.py`, `services/handler_acled_fetch_and_diff.py` | Abstract base for external API access (auth, retry, session) + ACLED OAuth client |
| W2: Scheduler Infra | `core/dag_scheduler.py`, `core/models/schedule.py`, `infrastructure/schedule_repository.py` + edits to `workflow_enums.py`, `workflow_run.py`, `dag_brain.py`, `dag_bp.py` | Scheduler thread, Schedule model/enum, CRUD repo, 6 admin endpoints, health monitoring |
| W3: ACLED Workflow | `workflows/acled_sync.yaml`, `services/handler_acled_save_to_bronze.py`, `handler_acled_append_to_silver.py` | 3-node DAG: fetch_and_diff → save_to_bronze → append_to_silver |

**Key design decisions:**
- No stored `next_run_at` — computed from `croniter(cron_expression, last_run_at)` at query time (DDIA doctrine)
- UTC only, no timezone support
- Scheduled runs indistinguishable from platform-submitted runs (same `workflow_runs` table, `schedule_id` for provenance)
- Handler return contract standardized: `{"success": True, "result": {...}}` with nested `result`
- `APIRepository` base class is config-agnostic — subclasses implement auth flavor (OAuth, API key, client secret)
- Bronze before Silver — raw API responses saved for audit trail and rebuild (Principle 2)

**Remaining before deployment:**

1. **Wire DAGScheduler startup** — add `DAGScheduler` creation and `.start(stop_event)` alongside janitor in Docker entrypoint (`docker_service.py` or wherever `DAGJanitor` is started). Follow exact same pattern.
2. **Schema deploy** — `action=ensure` to create `app.schedules` table, `app.schedule_status` enum, and `schedule_id` column on `app.workflow_runs`.
3. **ACLED credentials** — set `ACLED_USERNAME` and `ACLED_PASSWORD` env vars on Docker worker app settings.
4. **Config layer migration (deferred)** — `ACLEDRepository` reads credentials via `os.environ` directly (Standard 2.2 violation, COMPETE F1). Should migrate to `AppConfig` sub-config. Not blocking but noted for cleanup.
5. **E2E validation** — create a schedule via admin endpoint, verify scheduler thread picks it up, watch it submit a workflow run, verify ACLED data appears in `ops.acled_new`.

**Admin endpoints (all under `/api/dag/schedules`):**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/dag/schedules` | Create schedule |
| GET | `/api/dag/schedules` | List all schedules |
| GET | `/api/dag/schedules/{schedule_id}` | Get schedule + recent runs |
| PUT | `/api/dag/schedules/{schedule_id}` | Update (cron, params, status) |
| DELETE | `/api/dag/schedules/{schedule_id}` | Remove schedule |
| POST | `/api/dag/schedules/{schedule_id}/trigger` | Fire immediately |

---

### Phase 3: Handler Decomposition — Raster + Vector (v0.10.5)

**Risk**: Zero — existing job definitions still work via wrapper handlers.
**Effort**: Medium — break the two largest monolithic handlers into composable atomic functions.
**Breaking**: No — wrappers preserve existing behavior.

**Methodology: Build → Test → Assemble**

Handlers are built from their high-level node designs (see YAML workflow definitions in this document), then unit-tested in isolation via a handler test endpoint before being assembled into complete workflows (v0.10.7-9). This prevents the failure mode of assembling untested nodes into a workflow and debugging the entire chain at once.

1. Build handler test endpoint: `POST /api/dag/test/handler/{handler_name}` (see Handler Test Endpoint below)
2. Extract `raster_docker_complete` (2,300 lines) → atomic handlers: `raster_download_source`, `raster_validate`, `raster_create_cog`, `raster_upload_cog`, `raster_generate_tiling_scheme`, `raster_process_single_tile`, `raster_persist_app_tables`
3. Extract `vector_docker_complete` (1,160 lines) → atomic handlers: `vector_load_source`, `vector_validate_and_clean`, `vector_create_and_load_tables`, `vector_create_split_views`, `vector_register_catalog`, `vector_refresh_tipg`
4. Unit-test each handler via test endpoint — validate in Azure environment (managed identity, blob access, PostGIS)
5. Create wrapper handlers that call atomics in sequence (backward compat for CoreMachine)
6. Register new atomic handlers in `ALL_HANDLERS`

**Validation**: Each atomic handler proven independently via test endpoint. Existing raster and vector jobs work identically through wrappers. SIEGE regression test.

#### Handler Test Endpoint

A lightweight admin endpoint for invoking any registered handler directly — no workflow, no DAG orchestration, no DB state management. Proves handlers work in the Azure environment before they're wired into workflows.

```
POST /api/dag/test/handler/{handler_name}
Content-Type: application/json

{
    "params": {
        "blob_name": "test_file.geojson",
        "container_name": "wargames",
        ...
    },
    "dry_run": false
}

Response:
{
    "handler": "vector_load_source",
    "success": true,
    "result": { ... },
    "execution_time_ms": 1234
}
```

**Design**:
- Looks up handler from `ALL_HANDLERS` registry — same registry used by DAG workers
- Calls `handler(params)` directly — same contract as DAG execution
- Returns raw handler result + execution time for performance profiling
- Optional `dry_run` flag for handlers that support it (skip destructive operations)
- Admin-only: gated behind `APP_MODE` (orchestrator/standalone only, not worker)
- ~30-40 lines of implementation

**Use cases**:
- **During decomposition (v0.10.5-6)**: Validate each extracted handler works before wrappers are built
- **During workflow porting (v0.10.7-9)**: Debug individual nodes when a workflow fails mid-chain
- **Post-deployment**: Lightweight regression — hit each handler independently after deploy
- **SIEGE enhancement**: Handler-level test vectors alongside workflow-level sequences

### Phase 4: Handler Decomposition — Composable STAC + Unpublish + Zarr (v0.10.6)

**Risk**: Zero — same wrapper pattern as v0.10.5.
**Effort**: Low-Medium — STAC handlers are highest-value extraction (used by 9+ workflows). Zarr handlers are already ~80% atomic.
**Breaking**: No — wrappers preserve existing behavior.

1. Create composable STAC materialization layer (see Composable STAC Architecture):
   - `stac_materialize_item` — generic: reads stac_item_json from internal tables → pgSTAC
   - `stac_materialize_collection` — generic: recalc collection extent from items
   - `stac_dematerialize_item` — generic: remove item from pgSTAC + recalc extent
   - `stac_discover_collection_items`, `stac_discover_all_collections` — discovery handlers for rebuild workflows
2. Extract unpublish atomic handlers: `unpublish_inventory_item`, `unpublish_delete_blob`, `unpublish_cleanup_postgis`, `unpublish_cleanup_catalog`
3. Extract zarr atomic handlers (mostly renaming existing staged handlers): `zarr_validate_store`, `zarr_copy_single_blob`, `zarr_rechunk_store`, `zarr_register_metadata`, `zarr_consolidate_metadata`
4. Standardize `catalog_register_asset` and `catalog_deregister_asset` as shared handlers
5. Unit-test all new handlers via test endpoint

**Validation**: Each handler proven independently. All existing workflows work identically. Composable STAC handlers usable by raster, zarr, virtualzarr, AND rebuild workflows. SIEGE regression test.

### Phase 5: Port Vector Workflows to DAG (v0.10.7)

**Risk**: Low — vector is the simplest pipeline (linear DAG, no fan-out).
**Effort**: Low — YAML files already designed in this document. Atomic handlers proven via test endpoint in v0.10.5-6.
**Breaking**: No — opt-in routing via `workflow_engine=dag`. Per-workflow rollback by removing YAML file.

**Prerequisite**: All vector + shared handlers unit-tested via test endpoint (v0.10.5-6). This phase assembles proven pieces — it should not be debugging handler logic.

1. Finalize `workflows/vector_docker_etl.yaml` (6 nodes, linear with conditional skip)
2. Finalize `workflows/unpublish_vector.yaml` (3 nodes)
3. Finalize `workflows/vector_multi_source_docker.yaml` (multi-file and GPKG multi-layer)
4. SIEGE validation: submit vector jobs via DAG path, verify full lifecycle
5. Gateway routing: vector workflows opt-in to DAG Brain

**Validation**: Vector E2E via DAG Brain — submit → process → TiPG endpoint live. Legacy vector jobs still work on CoreMachine. SIEGE regression on both paths.

### Phase 6: Port Raster Workflows to DAG (v0.10.8)

**Risk**: Low-Medium — raster adds conditional routing (single COG vs tiled) and fan-out for tiles.
**Effort**: Medium — conditional + fan-out nodes exercised for the first time in production.
**Breaking**: No — opt-in routing. Per-workflow rollback.

1. Finalize `workflows/process_raster_docker.yaml` (9 nodes, conditional routing, fan-out/fan-in for tiles)
2. Finalize `workflows/unpublish_raster.yaml`
3. SIEGE validation: single COG path + tiled COG path (fan-out)
4. Gateway routing: raster workflows opt-in to DAG Brain

**Validation**: Raster E2E via DAG Brain — both single and tiled paths. Fan-out/fan-in proven with real tile sets. SIEGE regression.

### Phase 7: Port Zarr Workflows to DAG (v0.10.9)

**Risk**: Low — zarr handlers already ~80% atomic. Fan-out/fan-in proven by raster in v0.10.8.
**Effort**: Low-Medium — 4 zarr workflow variants + any remaining workflows (hello_world already on DAG).
**Breaking**: No — opt-in routing. Per-workflow rollback.

1. Finalize `workflows/ingest_zarr.yaml` (conditional copy vs rechunk, fan-out for blob batches)
2. Finalize `workflows/netcdf_to_zarr.yaml` (double fan-out: copy + validate)
3. Finalize `workflows/virtualzarr.yaml` (same shape as netcdf)
4. Finalize `workflows/unpublish_zarr.yaml`
5. Port any remaining workflows not covered above
6. SIEGE validation: all 14 workflows running on DAG Brain
7. **All 14 workflows proven** — legacy CoreMachine now has zero active consumers

**Validation**: Complete SIEGE campaign — all workflows on DAG, zero regressions. This is the gate for v0.11.0.

### Phase 8: Strangler Fig Complete — Remove Legacy (v0.11.0)

**Risk**: Low — by this point all 14 workflows are SIEGE-proven on DAG. Legacy has zero active consumers.
**Effort**: Low — delete code and Azure resources. One clean cut.
**Breaking**: Yes (infrastructure) — CoreMachine, Service Bus, and Python job classes removed.

1. Remove `core/machine.py` (CoreMachine)
2. Remove `jobs/*.py` Python job classes (14 files)
3. Remove `jobs/base.py`, `jobs/mixins.py`
4. Remove `infrastructure/service_bus.py` (800+ lines)
5. Remove `triggers/service_bus/` directory (job_handler, task_handler, error_handler)
6. Remove SB connection strings from environment config
7. Remove 3 Azure Service Bus queues (`geospatial-jobs`, `container-tasks`, `stage-complete`)
8. Remove SB-related config fields from `QueueConfig`
9. Remove legacy poll from worker (`app.tasks` query — only `workflow_tasks` remains)
10. Remove wrapper handlers (atomics called directly by DAG)
11. COMPETE adversarial review: verify no legacy references remain
12. SIEGE final: all workflows, clean codebase

**What this eliminates**: CoreMachine (~2,300 lines), Service Bus infrastructure (~800 lines), 14 Python job classes, AMQP warmup bugs, DLQ management, peek-lock complexity, SB credential rotation, accepted risks G and H from V10_DECISIONS.md, ~$50/month Azure cost.

**Result**: Function App = B2B gateway only (HTTP). Docker DAG Brain = DAG evaluation only (poll loop). Docker workers = handler execution. PostgreSQL = single coordination mechanism. Clean, simple, no queues.


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
| `stac_materialize_item` | Raster + zarr + rebuild (9+ workflows) | Composable STAC layer — see Composable STAC Architecture |
| `catalog_register_asset` | All forward workflows (8+) | Scattered — needs unified interface |
| `catalog_deregister_asset` | All unpublish workflows (4) | Scattered — needs unified interface |
| `validate_blob_exists` | All ingest workflows | Already exists as resource validator |
| `unpublish_delete_blob` | All unpublish workflows | Already a fan-out handler |

---

## Node Design Principles

### The Granularity Rule

A node should be its own node when its output **changes what happens next** in the graph. If it just produces intermediate data consumed by the next sequential step, it belongs inside a larger node.

**The test**: "If this operation's output were different, would the DAG take a different path?" If yes → node. If no → internal to a handler.

| Should Be a Node | Should Be Inside a Handler |
|-------------------|---------------------------|
| Output feeds a conditional or fan-out | Output consumed only by the next sequential step |
| Can meaningfully fail independently | Failure is inseparable from parent operation |
| Reusable across 2+ workflows | Used in exactly one context |
| Represents a decision point | Represents an implementation detail |

**Examples**:
- `scan_gpkg_layers` → **Node** — output determines fan-out count (1 layer vs N layers = different graph shape)
- "count features in a layer" → **Inside handler** — no decision flows from it, just metadata
- `infer_raster_type` → **Node** — output determines compression profile, STAC properties, possibly routing
- "compute bbox" → **Inside handler** — consumed by register, no branching

### Node Categories

The DAG system has four categories of nodes. ETL nodes (the "do" nodes) are only one category. Intelligence nodes are equally important — they inspect data and make decisions that shape the rest of the workflow.

#### Category 1: Reconnaissance — "What's there?"

Scan a source location, enumerate contents, filter, and structure for downstream consumption. These feed fan-outs and conditionals.

| Node | Input | Output | Reusable In |
|------|-------|--------|-------------|
| `scan_blob_prefix` | container, prefix, pattern | file_list with names/sizes/extensions | Any batch pipeline |
| `scan_gpkg_layers` | blob_name, container | spatial_layers [{name, geometry_type, feature_count}] | Multi-layer vector |
| `scan_zarr_store` | source_url | blob_batches (~500MB each), zarr_metadata | Ingest Zarr |
| `scan_netcdf_files` | source_url, pattern | file_list with dims/vars per file | NetCDF-to-Zarr, VirtualiZarr |
| `scan_raster_folder` | container, prefix, pattern | file_list with band counts/CRS/sizes | FATHOM, batch raster ingest |

**Design rule**: Reconnaissance nodes do the batching. If the source has 50,000 tiny items, the scan node groups them into ~500MB batches (see "Fan-Out Batching Convention" in Zarr Pipelines). Fan-out nodes should never create more than ~500 tasks.

#### Category 2: Inference — "What is it?"

Inspect data and classify it without transforming. These feed conditionals that route to different processing paths.

| Node | Input | Output | Reusable In |
|------|-------|--------|-------------|
| `infer_raster_type` | file_path or header metadata | detected_type (RGB/DEM/multi-band), confidence, band_mapping | Any raster pipeline |
| `infer_crs` | file_path | detected_crs, confidence, source (header/prj/sidecar) | Raster + vector validation |
| `infer_zarr_chunking` | zarr_store metadata | current_chunks, optimal_chunks, rechunk_needed (bool) | Ingest Zarr — skip rechunk if already optimal |
| `infer_file_convention` | file_list with names | naming_pattern, group_by field, batch_structure | FATHOM — "{return_period}_{scenario}_{year}.tif" |
| `infer_temporal_extent` | file_list or dataset coords | time_range, time_step, calendar type | Any temporal dataset |

#### Category 3: Planning — "How should we process it?"

Take reconnaissance + inference results and produce a processing plan. These structure the fan-out.

| Node | Input | Output | Reusable In |
|------|-------|--------|-------------|
| `plan_batch_structure` | file_list, naming_pattern, constraints | batches (list of file groups), processing_order | FATHOM, batch ingest |
| `plan_tiling_scheme` | raster metadata, target_tile_mb | tile_specs, grid_dimensions | Any tiled raster workflow |
| `plan_zarr_encoding` | dataset metadata, target_chunk_shape | encoding dict, estimated output size | Pre-compute before conversion |

#### Category 4: ETL — "Do the work"

Transform, load, register. These are the handler nodes in the vector/raster/zarr workflows already designed above.

### The Pattern: Reconnaissance → Decision → Action

Intelligence nodes enable workflows that **adapt at runtime** based on what they find:

```yaml
# Example: B2B client submits "process everything under /flood-data/north-america/"
nodes:
  scan_source:
    type: task
    handler: scan_blob_prefix
    # Finds: 148 .tif files

  infer_convention:
    type: task
    handler: infer_file_convention
    depends_on: [scan_source]
    # Detects: {return_period}_{scenario}_{year}.tif naming pattern

  infer_types:
    type: fan_out
    depends_on: [scan_source]
    source: "scan_source.sample_files"
    task:
      handler: infer_raster_type
    # Samples a few files → all DEM (single-band float32)

  aggregate_types:
    type: fan_in
    depends_on: [infer_types]
    aggregation: collect

  plan_batches:
    type: task
    handler: plan_batch_structure
    depends_on: [infer_convention, aggregate_types]
    # Groups: 5 return periods × 3 scenarios = 15 batches, ~10 files each

  route_by_type:
    type: conditional
    depends_on: [plan_batches]
    condition: "plan_batches.processing_mode"
    branches:
      - name: tiled_dem
        condition: "== dem_tiled"
        next: [process_dem_tiles]
      - name: standard
        default: true
        next: [process_standard]

  process_dem_tiles:
    type: fan_out
    source: "plan_batches.batches"
    task:
      handler: fathom_process_dem_batch
```

None of this was known at submission time. The workflow figured it out from the data.

### GPKG Multi-Layer Example

GPKG files may contain multiple spatial layers. The scan determines the graph shape:

```yaml
nodes:
  scan_layers:
    type: task
    handler: gpkg_scan_layers
    # Output: spatial_layers (filtered, non-spatial removed)
    # Rejects: zero spatial layers found

  route_by_layer_count:
    type: conditional
    depends_on: [scan_layers]
    condition: "scan_layers.spatial_layer_count"
    branches:
      - name: single_layer
        condition: "== 1"
        next: [process_single]
      - name: multi_layer
        default: true
        next: [process_layers]

  process_single:
    type: task
    handler: vector_load_source
    # Simple path — same as vector_docker_etl

  process_layers:
    type: fan_out
    source: "scan_layers.spatial_layers"
    task:
      handler: vector_process_single_layer
      params:
        layer_name: "{{ item.name }}"
        table_name: "{{ inputs.table_name }}_{{ item.name }}"
    # Each layer → full vector ETL internally
```

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

### Memory Management for Raster Operations (CRITICAL)

Raster operations can easily exceed worker memory if not managed. The core principle: **all raster I/O is windowed, and batch sizes are constrained by raster resolution**.

#### The Memory Model

```
Worker memory (4GB Azure P1v3):
  Python + GDAL overhead:  ~700MB (fixed)
  Available for raster:    ~2-3GB
  At float32 (4 bytes):    ~500-750M pixels
  As square window:        ~22K-27K × 22K-27K pixels
```

#### Where OOM Can Happen

| Operation | Risk | Mitigation |
|-----------|------|-----------|
| Single COG creation | **Low** — `rasterio` streams via windowed reads | Already windowed in `raster_create_cog` |
| Tiled COG extraction | **Low** — each tile is a small window (~256MB) | Fan-out: one tile per task |
| Zonal stats (H3) | **Low** — L3 cell bbox is small (~70km, ~5M pixels at 30m) | Natural batching by L3 cell |
| Zonal stats (admin polygons) | **MEDIUM** — batch bbox depends on polygon scatter | Proximity batching constrained by pixel budget |
| Zonal stats (giant polygon) | **HIGH** — Sakha Republic at 30m = 40GB | Internal tiling in handler |
| Zarr rechunk | **MEDIUM** — `xarray.to_zarr()` chunks in memory | Chunk size controls memory (~256×256 = small) |
| Vector GeoDataFrame | **LOW-MEDIUM** — proportional to feature count | GeoParquet on mount for inter-node passing |

#### Handler Convention: Resolution-Aware Batching

Any handler that batches work against a raster must respect the pixel budget:

```python
def calculate_max_bbox_km2(pixel_size_m, worker_memory_gb=4):
    """Calculate max batch bbox that fits in worker memory."""
    available_bytes = (worker_memory_gb - 0.7) * 1024**3
    bytes_per_pixel = 4  # float32
    max_pixels = available_bytes / bytes_per_pixel
    max_extent_m = (max_pixels ** 0.5) * pixel_size_m
    return (max_extent_m / 1000) ** 2

# Results:
# 90m raster → ~4,000,000 km² (half a continent)
# 30m raster → ~435,000 km² (large country)
# 10m raster → ~48,000 km² (province)
# 1m raster  → ~480 km² (city)
```

This function is shared infrastructure — used by `zonal_load_boundary_set`, `plan_batch_structure`, and any future handler that batches spatial work against a raster.

#### Windowed Reads (How rasterio Avoids OOM)

```python
import rasterio
from rasterio.windows import from_bounds

with rasterio.open(cog_url) as src:
    # Read ONLY the pixels within this bbox — NOT the full raster
    window = from_bounds(west, south, east, north, src.transform)
    data = src.read(window=window)
    # data shape: (bands, window_height, window_width)
    # Memory: bands × height × width × dtype_bytes
```

For COGs via HTTP: range requests fetch only the needed tiles. For local files: seek + read. Neither loads the full raster.

`exactextract` builds on this — iterates per-polygon, reads only intersecting pixels. The batch bbox sets the outer bound but actual memory usage is proportional to the largest single polygon, not the batch bbox.

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
- [x] **Resolution-aware batching for zonal stats** (17 MAR 2026) — Batch spatial work by proximity, constrained by raster pixel size. `calculate_max_bbox_km2(pixel_size_m)` → max bbox area per batch. 30m raster = ~435K km², 10m = ~48K km². `load_boundaries` depends on `discover_raster` to get pixel_size_m before batching. Giant polygons (>max_bbox) tiled internally by handler, not by DAG.
- [x] **H3 stats are Parquet-only, not PostgreSQL** (17 MAR 2026) — Per HEXAGONS.md design. No OLTP for computed stats. Database = recipe book (4 catalog tables). Parquet on blob = output. Queryable by DuckDB. Previous Epoch 4 design (h3.zonal_stats PostgreSQL table, billion rows) is superseded.
- [x] **H3 grid generated on-the-fly, not pre-built** (17 MAR 2026) — Per HEXAGONS.md. `h3-py` generates cells in microseconds. No PostGIS bootstrap needed. Static L3 land cell list (~15K IDs as JSON artifact) replaces runtime geometry intersection. Previous Epoch 4 design (40M rows in h3.cells) is superseded.
- [x] **Boundary sources are versioned** (17 MAR 2026) — `zonal_boundary_sources` has composite PK `(source_id, version)`. Each OCHA/GADM update is a new version. Outputs are immutable per version. DuckDB compares across versions.

## Remaining Open Questions

See "Deferred to Review" items above. All other questions have been resolved in "Decisions Made".

---

## Azure Resource Map

### Active Resources (v0.11.0 End State)

| Resource | Type | Role | Phase Impact |
|----------|------|------|-------------|
| `rmhazuregeoapi` | Function App | B2B gateway (`/platform/*` endpoints) + orchestrator (today) | v0.10.4: DAG Brain takes over orchestration. v0.11.0: orchestration fully removed, gateway-only. |
| `rmhtitiler` | Web App (Docker) | Service layer (TiTiler + TiPG + STAC API) | **Untouched** — no ETL migration impact |
| `rmhheavyapi` | Web App (Docker) | ETL worker — executes handlers, heavy compute (GDAL, xarray, geopandas) | v0.10.3: SB polling → DB `SKIP LOCKED` polling. v0.11.0: legacy `app.tasks` poll removed, `workflow_tasks` only. |
| `rmhdagmaster` | Web App (Docker) | DAG orchestrator — lightweight poll loop, DAG evaluation | v0.10.4: running alongside Function App. v0.11.0: sole orchestrator. Advisory lock HA. No heavy libs. |

### Resources to Retire

| Resource | Type | Current State | Action |
|----------|------|---------------|--------|
| `rmhdagworker` | Web App (Docker) | Running (empty) | **Retire** — `rmhheavyapi` is the worker, no need for a separate DAG worker |
| `rmhdaggateway` | Function App | Stopped | **Retire** — `rmhazuregeoapi` stays as B2B gateway |
| `rmhgeogateway` | Function App | Stopped | Already deprecated |
| `rmhgeoapi-worker` | Function App | Running (legacy) | Already deprecated |

### Resource Topology by Phase

```
v0.10.3 (Worker polls DB — DONE):
  rmhazuregeoapi (Function App) ──SB──→ rmhheavyapi (Docker Worker)
       ↑ HTTP                              ↑ DB poll (SKIP LOCKED)
       B2B clients                         SB still used for job dispatch

v0.10.4 (DAG Foundation — DONE):
  rmhazuregeoapi (Function App)          rmhdagmaster (Docker)
       ↑ HTTP + SB triggers                ↑ poll loop (DAG orchestration)
       B2B clients                         hello_world on DAG Brain
                          ↘       ↙
                        PostgreSQL
                          ↗
                 rmhheavyapi (Docker Worker)
                    dual-poll: app.tasks (legacy) + workflow_tasks (DAG)

v0.10.5-6 (Handler decomposition):
  Same topology as v0.10.4
  Atomic handlers extracted, wrappers preserve existing behavior
  Both CoreMachine + DAG Brain operational

v0.10.7-9 (Port workflows — strangler fig growing):
  Same topology, but traffic shifts from CoreMachine → DAG Brain
  v0.10.7: vector workflows on DAG
  v0.10.8: + raster workflows on DAG
  v0.10.9: + zarr workflows on DAG — all 14 proven, legacy has zero consumers

v0.11.0 (Strangler fig complete — END STATE):
  rmhazuregeoapi (Function App)          rmhdagmaster (Docker)
       ↑ HTTP (gateway only)              ↑ poll loop (orchestration only)
       B2B clients                         DAG evaluation, lightweight
                          ↘       ↙
                        PostgreSQL
                          ↗
                 rmhheavyapi (Docker Worker × N)
                    SKIP LOCKED poll (workflow_tasks only), handler execution

  CoreMachine: deleted
  Service Bus: deleted
  Python job classes: deleted

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
| `services/shared/stac_materialize_item.py` | Composable: internal metadata → pgSTAC item | ~100 |
| `services/shared/stac_materialize_collection.py` | Composable: recalc collection extent | ~60 |
| `services/shared/stac_dematerialize_item.py` | Composable: remove item from pgSTAC | ~60 |
| `services/shared/stac_discover.py` | Discovery handlers for rebuild workflows | ~80 |
| `services/shared/catalog_register.py` | Shared catalog registration | ~60 |

---

## SAFe Implementation Plan — Strangler Fig Migration

**Date**: 16 MAR 2026
**Team**: Robert (Product Owner + Dev) + Claude (Dev + SAFe Coach)
**Cadence**: 1-3 day stories, SIEGE regression after each ported workflow
**Epic**: V10 DAG Migration (v0.10.3 → v0.11.0)

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

### Progress Tracker (Revised 19 MAR 2026)

| Version | Phase | Feature | Status | SIEGE |
|---------|-------|---------|--------|-------|
| **v0.10.3** | F1 | Worker polls DB (SKIP LOCKED) | **DONE** | Run 18: 18/18 100% |
| **v0.10.4** | F-DAG | DAG Foundation + Brain (D.1-D.10) | **DONE** | hello_world E2E verified |
| **v0.10.5** | F4a | Handler decomposition: raster + vector | NOT STARTED | — |
| **v0.10.6** | F4b | Handler decomposition: composable STAC + unpublish + zarr | NOT STARTED | — |
| **v0.10.7** | F5a | Port vector workflows to DAG | NOT STARTED | — |
| **v0.10.8** | F5b | Port raster workflows to DAG | NOT STARTED | — |
| **v0.10.9** | F5c | Port zarr + remaining workflows to DAG (all 14 proven) | NOT STARTED | — |
| **v0.11.0** | F6 | **Strangler fig complete**: remove CoreMachine, SB, Python jobs | NOT STARTED | — |

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
| **D.7** Janitor | ~~GREENFIELD~~ **DONE** | Completed 16 MAR 2026. Direct implementation (~250 lines). |
| **D.8** Gateway routing + endpoint migration | **D.8a DONE**, D.8b deferred to F6 | D.8a: opt-in `workflow_engine=dag` routing (17 MAR 2026). D.8b: endpoint migration deferred — all routes stay on Function App until Epoch 4 retired. |
| **D.9** DAG status | ~~Direct~~ **DONE** | Completed 17 MAR 2026. New /api/dag/runs/* endpoints (3 routes). platform/* untouched. |
| **D.10** First blood | **SIEGE** | End-to-end validation of hello_world through DAG Brain. |
| **F4.1** Raster atomics | **GREENFIELD** per handler | Extract + rewrite from rmhdagmaster reference code. |
| **F4.2** Vector atomics | **GREENFIELD** per handler | Extract from existing monolithic handler. |
| **F5** Port workflows | **SIEGE** per tier | Each tier validated end-to-end against live system. |
| **F6** Cleanup | **COMPETE** | Adversarial review that no legacy references remain. |

**Key principle**: GREENFIELD for building new code. COMPETE for reviewing code. SIEGE for validating live system. ARB for decomposing complex stories before GREENFIELD.

---

### Feature DAG: DAG Foundation + Brain (v0.10.4) — DONE

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

#### Story D.8: Gateway Routing + Endpoint Migration (2-3 days)

**What**: Opt-in DAG workflow routing + move admin endpoints from Function App to DAG Brain Docker container. Function App becomes a thin B2B gateway with ~23 routes.

##### D.8a: Opt-In DAG Routing

**Design decision (17 MAR 2026):** Routing uses an **explicit opt-in parameter**, NOT auto-detection from WorkflowRegistry. Default is ALWAYS legacy CoreMachine until full replacement (F6). This prevents a newly added YAML file from accidentally routing production traffic to the untested DAG path.

**Opt-in mechanism**: `"workflow_engine": "dag"` in the submit request body. Without this parameter → legacy CoreMachine path (always). With it → check WorkflowRegistry, create DAGInitializer run, launch DAGOrchestrator.

**Files**:
- `services/platform_job_submit.py` — routing check (~15 lines)
- `services/platform_translation.py` — `job_type` → `workflow_name` mapping
- `triggers/platform/submit.py` — pass `workflow_engine` param through

**Acceptance criteria**:
- Submit `hello_world` with `"workflow_engine": "dag"` → routed to DAG Brain → completes
- Submit `hello_world` WITHOUT `workflow_engine` → routed to CoreMachine → completes as before
- Submit `process_raster_docker` with `"workflow_engine": "dag"` but no YAML → 400 error
- Status endpoint works for both paths

##### D.8b: Endpoint Migration — Route Classification

**Audit (17 MAR 2026):** The Function App currently has **112 HTTP routes** across 14 blueprint files. Only 23 should remain on the B2B-facing Function App. The rest are admin/ops tooling that moves to DAG Brain (Docker, `APP_MODE=orchestrator`).

**Stays on Function App (Gateway) — 23 routes:**

| Group | Count | Routes | Why stays |
|-------|-------|--------|-----------|
| **platform/*** | 20 | submit, status, approve/reject/revoke, unpublish, resubmit, catalog, registry, approvals | B2B client API — the only surface external apps hit |
| **Probes** | 3 | `/api/livez`, `/api/readyz`, `/api/health` | Required by Azure for liveness/readiness |

**Moves to DAG Brain (Docker) — ~80 routes:**

| Group | Count | What it is | Blueprint file |
|-------|-------|-----------|----------------|
| `dbadmin/*` | 18 | Schema ops, table inspection, job queries, diagnostics | `admin/admin_db.py` |
| `stac/*` | 20 | STAC catalog admin, nuke, extract, rebuild, OGC API | `stac/stac_bp.py` |
| `admin/artifacts/*` | 7 | Internal audit/lineage registry | `admin/admin_artifacts.py` |
| `cleanup/*` | 4 | Janitor/maintenance runs | `admin/admin_janitor.py` |
| `system/*` | 4 | Stats, snapshots, drift detection | `admin/admin_system.py`, `admin/snapshot.py` |
| `data-migration/*` | 3 | ADF pipeline triggers | `admin/admin_data_migration.py` |
| `dbadmin/external/*` | 2 | External DB initialization | `admin/admin_external_db.py` |
| `jobs/services/*` | 8 | External service registry | `admin/admin_external_services.py` |
| `auth/status` | 1 | Token debugging | `probes.py` |
| `diagnostics` | 1 | Deep system diagnostics | `probes.py` |
| `metrics/*` | 2 | Metrics flush/stats | `probes.py` |
| `appinsights/*` | 3 | Log queries | `probes.py` |

**Remove (duplicate or deprecated) — ~9 routes:**

| Group | Count | Why remove |
|-------|-------|-----------|
| `approvals/{id}/approve\|reject\|revoke` | 5 | Admin approval path — duplicates `platform/approve\|reject\|revoke` |
| `assets/{id}/approve\|reject\|revoke` | 4 (of 7) | Asset-centric approvals — duplicates `platform/` path. Keep read-only `pending-review`, `approval-stats`, `approval`, `by-approval-state` on DAG Brain for ops visibility. |
| `servicebus/*` | 2 | Being eliminated in v0.11.0 |

**Implementation**: The route classification is controlled by `APP_MODE` in `function_app.py`. Currently `has_platform_endpoints` gates the platform blueprint. Add inverse gates:
- `APP_MODE=platform` (Function App): registers only `platform_bp` + probes
- `APP_MODE=orchestrator` (DAG Brain): registers admin blueprints, STAC, cleanup, etc.
- `APP_MODE=worker_docker`: registers only probes (no HTTP routes needed)

**Files**:
- `function_app.py` — conditional blueprint registration based on `APP_MODE`
- `config/app_mode.py` — add `has_admin_endpoints`, `has_stac_endpoints` properties
- No blueprint code changes needed — just registration gating

**Acceptance criteria**:
- Function App (`APP_MODE=platform`) serves only `platform/*` + probes (23 routes)
- DAG Brain (`APP_MODE=orchestrator`) serves admin, STAC, cleanup, diagnostics (~80 routes)
- Worker (`APP_MODE=worker_docker`) serves only probes (3 routes)
- B2B clients see no change — `platform/*` endpoints identical
- SIEGE regression: all 25 sequences pass against Function App

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

### Feature 4: Handler Decomposition (v0.10.5-v0.10.6)

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
| `stac_materialize_item` | Phase 4 STAC (shared composable) | ~100 |
| `stac_materialize_collection` | Phase 4 STAC (shared composable) | ~60 |
| `catalog_register_raster` | Phase 5 catalog | ~50 |

**Files**:
- NEW: `services/raster/validate_source.py`
- NEW: `services/raster/create_cog.py`
- NEW: `services/raster/upload_cog.py`
- NEW: `services/shared/stac_materialize_item.py` — generic: reads stac_item_json from internal tables → pgSTAC
- NEW: `services/shared/stac_materialize_collection.py` — generic: recalc collection extent
- NEW: `services/shared/stac_dematerialize_item.py` — generic: remove item from pgSTAC
- NEW: `services/shared/stac_discover.py` — discovery handlers for rebuild workflows
- NEW: `services/shared/catalog_register.py`
- `services/__init__.py` — register new handlers in `ALL_HANDLERS`
- `services/handler_raster_docker_complete.py` — wrapper calls atomics in sequence

**Acceptance criteria**:
- Existing raster job works identically (wrapper delegates to atomics)
- Each atomic handler independently callable with correct contract
- `stac_materialize_item` usable by raster, zarr, virtualzarr, AND rebuild workflows
- `rebuild_stac_item` and `rebuild_stac_collection` workflows validate and load

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
2. Zarr `register` handlers now write to internal tables (incl. `stac_item_json` cache) — STAC materialization is separate composable node
3. Create shared unpublish handlers: `unpublish_inventory_item`, `unpublish_delete_blob`, `stac_dematerialize_item`, `unpublish_cleanup_postgis`, `unpublish_cleanup_catalog`
4. Wrapper handlers preserve existing job behavior

**Acceptance criteria**:
- Zarr ingest, netcdf-to-zarr, virtualzarr, and all unpublish jobs work identically
- Shared STAC handlers (`stac_materialize_item`, `stac_dematerialize_item`) registered and reusable
- Rebuild STAC workflows (`rebuild_stac_item`, `rebuild_stac_collection`, `rebuild_stac_catalog`) load and validate

#### Story 4.4: SIEGE Regression (0.5 day)

**What**: Full regression after handler decomposition. Deploy v0.10.6.

**Acceptance criteria**:
- SIEGE pass rate ≥ 95%
- Zero regressions from decomposition (wrappers preserve behavior)
- All new atomic handlers visible in handler registry

---

### Feature 5: Port Workflows (Strangler Fig — Incremental) (v0.10.7-v0.10.9)

**Goal**: Port all 14 Python job classes to YAML workflows, one tier at a time. Each ported workflow is immediately live on the DAG Brain. Legacy jobs stay on CoreMachine until their YAML is ready.

**Requires**: F-DAG done (v0.10.4 ✓) + F4 done (v0.10.5-6 — handler decomposition).

**Tier order**: Vector (v0.10.7) → Raster (v0.10.8) → Zarr + remaining (v0.10.9).

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

**What**: Convert every Python job class to a YAML workflow definition using the atomic handlers from v0.10.5-6.

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
| `rebuild_stac_item.yaml` | NEW (no legacy equivalent) | 2 |
| `rebuild_stac_collection.yaml` | NEW (no legacy equivalent) | 4 |
| `rebuild_stac_catalog.yaml` | NEW (no legacy equivalent) | 3 |

**Acceptance criteria**:
- Each YAML loads and validates without errors
- Workflow loader detects all at startup
- YAML structure matches blueprint spec (nodes:, depends_on:, receives:, when:, fan_out:, fan_in:)
- Rebuild workflows use same `stac_materialize_item` handler as forward ETL pipelines

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

### Feature 6: Strangler Fig Complete — Remove Legacy System (v0.11.0)

**Goal**: All 14 workflows proven on DAG Brain (v0.10.9 ✓). Remove CoreMachine, Service Bus, Python job classes. Function App becomes gateway-only. The fig has fully grown and replaced the host plant.

**Prerequisite**: All workflows ported (v0.10.7-9) and SIEGE-validated. Zero traffic on legacy path.

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

#### Story 6.3: SIEGE Final + Deploy v0.11.0 (1 day)

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
| D.8 Gateway routing + endpoint migration | — | — | **Write fresh.** Opt-in routing (~15 lines) + APP_MODE route gating. 112→23 routes on Function App. |
| D.9 DAG status | — | — | **Write fresh.** Dual-query for legacy + DAG tables. |
| D.10 First blood | `Dockerfile` (orchestrator variant) + `entrypoint.sh` | ~50 | **Direct port.** Same image with `APP_MODE=orchestrator`. |

#### F4: Handler Decomposition

| Story | rmhdagmaster Source | Action |
|-------|-------------------|--------|
| 4.1 Raster atomics | `handlers/raster/validate.py` (468), `cog_create.py` (262), `blob_copy.py` (116), `statistics.py` (417), `stac.py` (706) — **~2,000 lines** | **Rewrite to fit.** Reference code for logic and edge cases. Adapt to rmhgeoapi's BlobRepository, STAC layer, sync handler contract. |
| 4.2 Vector atomics | — | **Extract from existing.** Pull phases from `handler_vector_docker_complete.py`. No rmhdagmaster equivalent. |
| 4.3 Zarr/unpublish | — | **Register existing.** Already decomposed in rmhgeoapi. |
| 4.4 SIEGE | — | — |

#### F5: Port Workflows (v0.10.7-9) + F6: Cleanup (v0.11.0)

| Story | rmhdagmaster Source | Action |
|-------|-------------------|--------|
| 5.1 Write YAMLs | `workflows/*.yaml` (10 files) as **format reference only** | **Write fresh.** Different pipelines. Use rmhdagmaster YAMLs as structural template. |
| 5.2a Port vector (v0.10.7) | — | **Write fresh.** Wire vector atomic handlers into YAML graphs. Simplest E2E. |
| 5.2b Port raster (v0.10.8) | — | **Write fresh.** First conditional + fan-out in production. |
| 5.2c Port zarr + remaining (v0.10.9) | — | **Write fresh.** All 14 proven on DAG. |
| 6.1 Remove CoreMachine | — | **Delete only.** |
| 6.2 Remove SB | — | **Delete only.** One clean cut. |
| 6.3 SIEGE final (v0.11.0) | — | — |

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

### Effort Summary (Revised 19 MAR 2026 — v0.10.x Increments)

| Version | Feature | Est. Days | Risk | Status |
|---------|---------|-----------|------|--------|
| ~~v0.10.3: F1 Worker DB-Poll~~ | — | — | — | **DONE** |
| ~~v0.10.4: F-DAG Foundation + Brain~~ | 10 stories | — | — | **DONE** |
| v0.10.5: F4a Raster + vector atomics | 2 stories | 4-6 days | Low | NOT STARTED |
| v0.10.6: F4b STAC + unpublish + zarr atomics | 2 stories | 3-5 days | Low | NOT STARTED |
| v0.10.7: F5a Port vector workflows | 1 story | 2-3 days | Low | NOT STARTED |
| v0.10.8: F5b Port raster workflows | 1 story | 2-4 days | Low-Medium | NOT STARTED |
| v0.10.9: F5c Port zarr + remaining workflows | 1 story | 3-5 days | Low | NOT STARTED |
| v0.11.0: F6 Strangler fig complete | 1 story | 2-3 days | Low | NOT STARTED |
| **Remaining** | **8 stories** | **16-26 days** | | |

### Dependency Graph (Revised 19 MAR 2026 — v0.10.x Increments)

```
  DONE                          REMAINING
  ════                          ═════════

  v0.10.3: F1 Worker DB-Poll ✓
              │
  v0.10.4: F-DAG Foundation ✓
              │
              ▼
  v0.10.5: F4a Handler Decomposition ───────────────────────────────
              │  Raster atomics (2,300 lines → ~7 handlers)
              │  Vector atomics (1,160 lines → ~6 handlers)
              │  Wrappers preserve existing jobs
              ▼
  v0.10.6: F4b Handler Decomposition ───────────────────────────────
              │  Composable STAC (3 generic handlers, used by 9+ workflows)
              │  Unpublish atomics (4 shared handlers)
              │  Zarr atomics (mostly renaming existing staged handlers)
              ▼
  v0.10.7: F5a Port Vector Workflows ───────────────────────────────
              │  vector_docker_etl, unpublish_vector, vector_multi_source
              │  Simplest E2E: linear DAG, no fan-out
              │  SIEGE: vector lifecycle on DAG Brain
              ▼
  v0.10.8: F5b Port Raster Workflows ──────────────────────────────
              │  process_raster_docker (conditional + fan-out), unpublish_raster
              │  First real fan-out/fan-in in production
              │  SIEGE: single COG + tiled COG paths
              ▼
  v0.10.9: F5c Port Zarr + Remaining ──────────────────────────────
              │  ingest_zarr, netcdf_to_zarr, virtualzarr, unpublish_zarr
              │  All 14 workflows proven on DAG Brain
              │  SIEGE: complete campaign — all workflows, zero regressions
              ▼
  v0.11.0: F6 Strangler Fig Complete ──────────────────────────────
              Delete CoreMachine, Service Bus, Python jobs, wrapper handlers
              One clean cut. COMPETE + SIEGE final.
```

**Sequential execution**: Each version depends on the previous. No parallel streams — handler decomposition must precede workflow porting, and each porting tier validates incrementally more DAG capability before the next.

### Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| **Two orchestration systems during v0.10.5-9** | Invisible to clients — Gateway routes transparently. Bounded: each ported workflow (v0.10.7-9) reduces legacy scope. Rollback: remove YAML file → legacy path resumes. |
| **Peak operational complexity (v0.10.7-9)** | 4 processes: Function App (B2B gateway) + DAG Brain (orchestration) + Worker + PostgreSQL. Function App surface shrinks as workflows migrate. APP_MODE gates control which blueprints load. |
| **Handler decomposition breaks existing jobs (v0.10.5-6)** | Wrapper pattern: monolithic handler calls atomics in sequence. Remove wrappers only in v0.11.0 after all workflows on DAG Brain. |
| **DAG orchestrator concurrency bugs** | Brain guard ported from rmhdagmaster (proven). COMPETE adversarial review completed before D.10. |
| **YAML schema needs iteration** | v0.10.7 (vector) proves linear chains + `when:`. v0.10.8 (raster) proves conditional routing + fan-out. v0.10.9 (zarr) proves double fan-out + conditional copy/rechunk. Each tier validates before the next. |
| **Team of 2 — bus factor** | All decisions in V10_MIGRATION.md. Spec in `docs/superpowers/specs/`. Claude has full context. rmhdagmaster is reference implementation. |
| **Worker polling two tables (v0.10.4-9)** | Two SKIP LOCKED queries per cycle. Negligible overhead vs ETL execution time. Remove legacy poll in v0.11.0 cleanup. |

---

*Document created: 14 MAR 2026*
*Updated: 17 MAR 2026 — D.8 rewritten: opt-in routing + endpoint migration (112→23 routes on Function App), COMPETE 46+47 fixes applied*
*Updated: 19 MAR 2026 — Version roadmap revised: v0.10.x increments for handler decomposition + workflow porting, v0.11.0 = strangler fig complete (SB removed, CoreMachine deleted)*
*Author: Claude + Robert Harrison*
