# DAG Workflow YAML Reference

**Last Updated**: 02 APR 2026
**Authoritative Model**: `core/models/workflow_definition.py`
**Workflows Directory**: `workflows/*.yaml`

---

## Top-Level Structure

```yaml
workflow: process_raster              # Unique identifier (replaces job_type)
description: "Human-readable purpose"
version: 2                            # Integer, increment on breaking changes
reversed_by: unpublish_raster         # Optional: paired unpublish workflow
reverses: [vector_docker_etl]         # Optional: forward workflows this reverses

parameters:
  blob_name: {type: str, required: true}
  processing_options:
    type: dict
    default: {}

validators:
  - type: blob_exists_with_size
    container_param: container_name
    blob_param: blob_name
    zone: bronze
    max_size_mb: 20480

nodes:
  node_name:
    type: task
    handler: handler_name
    # ... node-specific fields

finalize:
  handler: raster_finalize            # Optional: runs on COMPLETED or FAILED
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | str | yes | Unique workflow name (used in submission + run_id hash) |
| `description` | str | yes | Human-readable description |
| `version` | int | yes | Schema version (increment on breaking param changes) |
| `reversed_by` | str | no | Name of the unpublish workflow |
| `reverses` | list[str] | no | Forward workflows this unpublishes |
| `parameters` | dict | yes | Parameter schema (see Parameters) |
| `validators` | list | no | Pre-flight checks (run before workflow starts) |
| `nodes` | dict | yes | DAG node definitions (see Node Types) |
| `finalize` | object | no | Cleanup handler (runs regardless of outcome) |

---

## Parameters

Define expected inputs. The DAG initializer validates submitted params against this schema.

```yaml
parameters:
  blob_name: {type: str, required: true}
  schema_name: {type: str, default: "geo"}
  dry_run: {type: bool, default: true}
  processing_options:
    type: dict
    default: {}
```

Supported types: `str`, `int`, `float`, `bool`, `dict`, `list`

---

## Validators

Pre-flight checks that run at submission time, before the workflow starts. If any validator fails, the submission is rejected (no run created).

```yaml
validators:
  - type: blob_exists_with_size
    container_param: container_name    # References a parameter name
    blob_param: blob_name
    zone: bronze
    max_size_mb: 5120
    error_too_large: "File exceeds 5 GB limit."
```

Validators use `extra='allow'` — any fields beyond `type` are passed to the validator implementation.

---

## Node Types

Five node types, discriminated by the `type` field.

### 1. Task Node

Executes a handler function. The workhorse of the DAG.

```yaml
  validate:
    type: task
    handler: raster_validate_atomic
    depends_on: [download_source]
    params: [blob_name, container_name]
    receives:
      source_path: "download_source.result.source_path"
    when: "params.processing_options.validate"
    best_effort: true
    retry:
      max_attempts: 3
      backoff: exponential
    timeout_seconds: 600
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"task"` | — | Required discriminator |
| `handler` | str | — | Handler name from `ALL_HANDLERS` registry |
| `depends_on` | list[str] | `[]` | Upstream node names (append `?` for optional) |
| `params` | list or dict | `[]` | Parameter names to extract from job params |
| `receives` | dict[str, str] | `{}` | Values from predecessor outputs (dotted path) |
| `when` | str | null | Condition — task is SKIPPED if falsy |
| `best_effort` | bool | `false` | If true, failure doesn't fail the workflow |
| `retry` | RetryPolicy | null | Retry configuration |
| `timeout_seconds` | int | null | Task execution timeout |

### 2. Conditional Node

Routes execution by evaluating a condition from a predecessor's output.

```yaml
  route_by_size:
    type: conditional
    depends_on: [validate]
    condition: "download_source.result.file_size_bytes"
    branches:
      - name: large_raster
        condition: "gt 2000000000"
        next: [generate_tiling_scheme]
      - name: standard_raster
        default: true
        next: [create_single_cog]
```

| Field | Type | Description |
|-------|------|-------------|
| `condition` | str | Dotted path to the value to evaluate |
| `branches` | list[BranchDef] | Min 2 branches. Exactly one must have `default: true` |

**BranchDef**:
| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Branch identifier |
| `condition` | str | Comparison (e.g., `"gt 2000000000"`, `"eq true"`) |
| `default` | bool | Fallback branch if no condition matches |
| `next` | list[str] | Downstream node names activated by this branch |

### 3. Fan-Out Node

Creates parallel task instances from a source list.

```yaml
  process_tiles:
    type: fan_out
    depends_on: [generate_tiling_scheme]
    source: "generate_tiling_scheme.result.tile_specs"
    max_fan_out: 500
    task:
      handler: raster_process_single_tile
      params:
        tile_spec: "{{ item }}"
        source_path: "{{ nodes.download_source.result.source_path }}"
        collection_id: "{{ inputs.collection_id }}"
      timeout_seconds: 3600
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source` | str | — | Dotted path to the array to fan out over |
| `task` | FanOutTaskDef | — | Task template applied to each item |
| `max_fan_out` | int | 500 | Safety limit (1-10000) |

**Template variables** in fan-out `task.params`:
- `{{ item }}` — current array element
- `{{ index }}` — 0-based index
- `{{ inputs.<param> }}` — job parameter
- `{{ nodes.<name>.result.<path> }}` — predecessor output

### 4. Fan-In Node

Aggregates results from upstream fan-out children.

```yaml
  aggregate_tiles:
    type: fan_in
    depends_on: [process_tiles]
    aggregation: collect
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `depends_on` | list[str] | — | Must include the fan-out node |
| `aggregation` | str | `"collect"` | Aggregation mode: `collect`, `sum`, `count`, `first` |

The aggregated result is available as `aggregate_tiles.items` (list of child results).

### 5. Gate Node

Suspends workflow execution until an external signal (e.g., human approval).

```yaml
  approval_gate:
    type: gate
    gate_type: approval
    depends_on:
      - "persist_single?"
      - "persist_tiled?"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gate_type` | str | `"approval"` | Gate classification |
| `depends_on` | list[str] | `[]` | Upstream nodes (use `?` for optional) |

**Lifecycle**: PENDING → WAITING (predecessors done) → COMPLETED (approved) or SKIPPED (rejected).

The Brain's gate reconciliation polls `asset_releases.approval_state` to detect approval.

---

## Dependencies and Ordering

### `depends_on`

Nodes execute when ALL dependencies reach a terminal state (COMPLETED, SKIPPED, FAILED, EXPANDED, CANCELLED).

```yaml
  my_node:
    depends_on: [node_a, node_b]   # Both must be terminal before my_node starts
```

### Optional Dependencies (`?` suffix)

Append `?` to tolerate SKIPPED or FAILED predecessors without propagating the skip.

```yaml
  approval_gate:
    depends_on:
      - "persist_single?"    # May not exist (conditional path)
      - "persist_tiled?"     # May not exist (conditional path)
```

Without `?`, a FAILED/SKIPPED predecessor causes the dependent task to be SKIPPED (failure cascade). With `?`, the dependent continues regardless.

### `best_effort` Nodes

A task marked `best_effort: true` has two effects:
1. **Dependency propagation**: downstream tasks continue even if this task FAILS
2. **Run-level status**: the workflow completes successfully even if this task FAILS

```yaml
  refresh_tipg:
    type: task
    handler: vector_refresh_tipg
    best_effort: true       # TiPG failure doesn't fail the ETL
```

Use for external service calls that are non-critical: TiPG refresh, email notifications, cache warming, analytics events.

### Comparison: `?` vs `best_effort`

| Mechanism | Scope | Effect |
|-----------|-------|--------|
| `depends_on: ["node?"]` | Single edge | This specific dependent tolerates upstream failure |
| `best_effort: true` | Node-wide | ALL dependents tolerate this node's failure, AND workflow status ignores it |

They are complementary. A `?` dependency is for "I don't need this predecessor's output." `best_effort` is for "this task's failure is non-critical to the entire workflow."

---

## Parameter Resolution

Handlers receive a `params` dict assembled from three sources (in priority order):

### 1. Job Parameters (from `params:` list)

```yaml
  my_node:
    params: [blob_name, container_name, processing_options]
```

The named keys are extracted from the submitted job parameters and passed to the handler.

### 2. Received Values (from `receives:` dict)

```yaml
  validate:
    receives:
      source_path: "download_source.result.source_path"
      crs: "load.result.metadata.crs"
```

Dotted path resolution: `node_name.result.nested.key`. Extracted from predecessor task `result_data`.

**Receives override params** — if the same key appears in both, the received value wins.

### 3. System Parameters (injected by orchestrator)

Always available in the handler's `params` dict:
- `_run_id` — 64-char DAG run ID
- `_task_name` — node name from YAML
- `_workflow` — workflow name

---

## `when` Clause (Conditional Execution)

Skip a task if a condition is falsy.

```yaml
  create_split_views:
    when: "params.processing_options.split_column"
```

Evaluated against the task's resolved parameters. If the expression resolves to a falsy value (None, False, 0, empty string/list), the task is SKIPPED.

Can also reference predecessor outputs:
```yaml
  materialize_single_item:
    when: "upload_single_cog.result.stac_item_id"
```

---

## Retry Policy

```yaml
  download:
    retry:
      max_attempts: 3                  # 1-10 (default 3)
      backoff: exponential             # exponential | linear | fixed
      initial_delay_seconds: 5         # default 5
      max_delay_seconds: 300           # default 300
```

After `max_attempts` failures, the task is marked FAILED.

---

## Finalize Handler

Runs after the workflow reaches a terminal state (COMPLETED or FAILED). Used for cleanup (e.g., deleting mount temp files).

```yaml
finalize:
  handler: raster_finalize
```

Non-fatal — finalize failure doesn't change the workflow's terminal status.

---

## Complete Example (Minimal)

```yaml
workflow: hello_world
description: "Minimal two-node workflow for testing"
version: 1

parameters:
  message: {type: str, default: "hello"}

nodes:
  greet:
    type: task
    handler: hello_world_greet
    params: [message]

  log_result:
    type: task
    handler: hello_world_log
    depends_on: [greet]
    receives:
      greeting: "greet.result.text"
```

---

## Complete Example (Production — Vector ETL)

```yaml
workflow: vector_docker_etl
description: "Vector file → PostGIS table(s) + catalog + TiPG"
version: 3
reversed_by: unpublish_vector

parameters:
  blob_name: {type: str, required: true}
  container_name: {type: str, required: true}
  table_name: {type: str, required: true}
  schema_name: {type: str, default: "geo"}
  file_extension: {type: str, required: true}
  processing_options: {type: dict, default: {}}
  release_id: {type: str, required: false}

validators:
  - type: blob_exists_with_size
    container_param: container_name
    blob_param: blob_name
    zone: bronze
    max_size_mb: 5120

nodes:
  load_source:
    type: task
    handler: vector_load_source
    params: [blob_name, container_name, file_extension, processing_options]

  validate_and_clean:
    type: task
    handler: vector_validate_and_clean
    depends_on: [load_source]
    receives:
      source_path: "load_source.result.intermediate_path"

  create_and_load_tables:
    type: task
    handler: vector_create_and_load_tables
    depends_on: [validate_and_clean]
    params: [table_name, schema_name, processing_options]

  refresh_tipg_preview:
    type: task
    handler: vector_refresh_tipg
    depends_on: [create_and_load_tables]
    best_effort: true                    # TiPG failure is non-critical

  approval_gate:
    type: gate
    gate_type: approval
    depends_on: [refresh_tipg_preview]

  register_catalog:
    type: task
    handler: vector_register_catalog
    depends_on: [approval_gate, create_and_load_tables]
    receives:
      tables_info: "create_and_load_tables.result.tables_created"

  refresh_tipg:
    type: task
    handler: vector_refresh_tipg
    depends_on: [register_catalog]
    best_effort: true

finalize:
  handler: vector_finalize
```

---

## Registered Workflows

| Workflow | Data Type | Nodes | Gate | Description |
|----------|-----------|-------|------|-------------|
| `process_raster` | Raster | 14 | yes | Single/tiled COG routing via conditional |
| `vector_docker_etl` | Vector | 9 | yes | PostGIS table + TiPG + catalog |
| `ingest_zarr` | Zarr/NC | 9 | yes | NetCDF→Zarr or native Zarr + pyramid |
| `unpublish_raster` | Raster | 3 | no | STAC delete + blob delete |
| `unpublish_vector` | Vector | 3 | no | Table drop + metadata cleanup |
| `unpublish_zarr` | Zarr | 3+ | no | Pyramid blob fan-out delete |
| `acled_sync` | Vector | 5 | no | Scheduled API sync (no gate) |
| `hello_world` | Test | 2 | no | Minimal test workflow |
| `echo_test` | Test | 3 | no | Conditional routing test |
| `test_fan_out` | Test | 3 | no | Fan-out/fan-in test |
