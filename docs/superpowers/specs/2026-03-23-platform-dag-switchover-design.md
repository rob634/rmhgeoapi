# Platform-to-DAG Switchover Design (v0.10.10)

**Date**: 23 MAR 2026
**Status**: Draft
**Author**: Claude + Robert
**Epoch**: 5 — DAG Orchestration
**Depends on**: v0.10.8 (raster DAG), v0.10.9 (zarr DAG)

---

## 1. Purpose

Complete the strangler fig migration by making DAG the **default and only** workflow engine for all `platform/*` submissions. CoreMachine code remains in the codebase (removed at v0.11.0) but is no longer invoked by any platform endpoint.

### Success Criteria

All `platform/*` endpoints trigger Epoch 5 (DAG) workflows instead of Epoch 4 (CoreMachine + Service Bus) workflows, with **identical output** as verified by SIEGE.

### What This Design Covers

- Explicit routing table: `(data_type, operation)` to YAML workflow name
- Parameter translation from platform refs to DAG workflow params
- Unpublish YAML workflows + atomic handlers (vector, raster, zarr)
- Unpublish becomes asynchronous (202 Accepted + polling URL)
- Two-phase SIEGE verification strategy

### What This Design Does NOT Cover

- Deleting CoreMachine, Service Bus, or legacy handler code (v0.11.0)
- Tiled raster workflow (v0.10.8 prerequisite — not yet built)
- Raster collection workflow (depends on tiled path)
- Multi-source vector workflow (separate design)

---

## 2. Routing Table

A new module `core/workflow_routing.py` replaces `JOB_TYPE_ALIASES` and the `translate_to_coremachine()` function as the single source of truth for workflow resolution.

### 2.1 Route Definitions

```python
DAG_ROUTES: dict[tuple[str, str], str] = {
    # (data_type, operation) -> YAML workflow name

    # Publish
    ("vector", "create"):           "vector_docker_etl",
    ("raster", "create"):           "process_raster_single_cog",
    ("zarr", "create"):             "ingest_zarr",
    ("netcdf", "create"):           "netcdf_to_zarr",

    # Unpublish
    ("vector", "unpublish"):        "unpublish_vector",
    ("raster", "unpublish"):        "unpublish_raster",
    ("zarr", "unpublish"):          "unpublish_zarr",
}
```

### 2.2 Lookup

```python
def resolve(data_type: str, operation: str) -> str:
    """
    Resolve a (data_type, operation) pair to a YAML workflow name.

    Raises ValueError if no route exists (no fallback to CoreMachine).
    """
    key = (data_type.lower(), operation.lower())
    workflow = DAG_ROUTES.get(key)
    if not workflow:
        raise ValueError(
            f"No DAG workflow for ({data_type}, {operation}). "
            f"Available routes: {sorted(DAG_ROUTES.keys())}"
        )
    return workflow
```

### 2.3 Raster Single vs Tiled

The routing table currently maps `("raster", "create")` to `process_raster_single_cog`. When the tiled raster workflow (v0.10.8) is ready, the resolution logic will inspect the request to determine single vs tiled:

- Single file submission: `process_raster_single_cog`
- Multi-file / collection submission: `process_raster_tiled` (not yet built)

This distinction is determined before the routing table lookup — the `data_type` key may become `"raster_collection"` for tiled paths, or a separate parameter selects the variant. Deferred to v0.10.8 design.

---

## 3. Parameter Translation

### 3.1 Renamed Function

`translate_to_coremachine()` is replaced by `translate_platform_params()` in the same `core/workflow_routing.py` module:

```python
def translate_platform_params(
    request: PlatformRequest,
    workflow_name: str,
    cfg=None,
) -> dict:
    """
    Translate DDH PlatformRequest into DAG workflow parameters.

    Each workflow expects specific params defined in its YAML parameters: block.
    This function maps platform ref fields to those params.

    Nothing DDH-native leaks through — all fields are abstracted to
    platform refs (dataset_id, resource_id, version_id) and internal
    naming conventions (table_name, stac_item_id, collection_id).
    """
```

### 3.2 Anti-Corruption Layer

The translation maintains the existing anti-corruption boundary:

| Platform Ref | Internal Field | Used By |
|-------------|---------------|---------|
| `dataset_id` | `dataset_id` | All workflows (identity) |
| `resource_id` | `resource_id` | All workflows (identity) |
| `version_id` | `version_id` | All workflows (versioning) |
| `container_name` + `file_name` | `source_container`, `source_blob` | Publish workflows |
| `processing_options.table_name` | `table_name` | Vector workflows |
| N/A (generated) | `stac_item_id` | Raster/zarr workflows |
| N/A (generated) | `collection_id` | Raster/zarr workflows |

### 3.3 Unpublish Parameters

Unpublish parameter resolution uses existing logic from `_build_unpublish_params()`:

| Data Type | Params Produced | Source |
|-----------|----------------|--------|
| Vector | `table_names`, `table_name` | `release_tables` junction (authoritative) |
| Raster | `stac_item_id`, `collection_id` | Release record (authoritative) |
| Zarr | `stac_item_id`, `collection_id` | Release record (authoritative) |

All unpublish workflows also receive `dry_run` and `delete_blobs` from the platform request.

---

## 4. Unpublish Workflows

Three new YAML workflows. Each is the **inverse** of its publish counterpart — same tables, same STAC paths, same blob locations, but DELETE instead of CREATE.

### 4.1 `unpublish_vector.yaml`

| Node | Handler | Purpose |
|------|---------|---------|
| `drop_tables` | `vector_unpublish_tables` | DROP TABLE for base table + split views |
| `deregister_catalog` | `vector_deregister_catalog` | Remove from `geo.table_catalog` metadata |
| `refresh_tipg` | `vector_refresh_tipg` | Refresh TiPG collection cache (existing handler, reused) |

Parameters: `table_names`, `table_name`, `dry_run`

### 4.2 `unpublish_raster.yaml`

| Node | Handler | Purpose |
|------|---------|---------|
| `remove_stac` | `raster_remove_stac` | Delete STAC item from pgSTAC |
| `delete_cog` | `raster_delete_cog` | Delete COG blob from Silver storage (conditional on `delete_blobs`) |
| `cleanup_metadata` | `raster_cleanup_metadata` | Remove `cog_metadata` record |

Parameters: `stac_item_id`, `collection_id`, `delete_blobs`, `dry_run`

### 4.3 `unpublish_zarr.yaml`

| Node | Handler | Purpose |
|------|---------|---------|
| `remove_stac` | `zarr_remove_stac` | Delete STAC item from pgSTAC |
| `delete_store` | `zarr_delete_store` | Delete zarr store from Silver storage (conditional on `delete_blobs`) |
| `cleanup_metadata` | `zarr_cleanup_metadata` | Remove zarr metadata record |

Parameters: `stac_item_id`, `collection_id`, `delete_blobs`, `dry_run`

### 4.4 `dry_run` Handling

`dry_run` is handled at the **platform layer**, not in the workflow:

- `dry_run=true`: Platform endpoint returns a synchronous 200 preview of what would be deleted. No DAG workflow is submitted.
- `dry_run=false`: Platform endpoint submits the DAG workflow and returns 202 Accepted with `monitor_url`.

This preserves existing dry_run behavior — the preview response is immediate, not asynchronous.

### 4.5 Release Lifecycle

The DAG orchestrator's `_handle_release_lifecycle` handles PROCESSING/COMPLETED/FAILED transitions for unpublish runs, same as publish. The platform layer handles Asset-level bookkeeping (decrement `release_count`, update `is_served`) on completion.

---

## 5. Integration: `platform/submit`

### 5.1 Current Flow (Epoch 4 default, DAG opt-in)

```
PlatformRequest
  -> translate_to_coremachine() -> (job_type, params)
  -> if workflow_engine == "dag":
       create_and_submit_dag_run(job_type, params)
     else:
       create_and_submit_job(job_type, params)  # CoreMachine
```

### 5.2 New Flow (DAG only)

```
PlatformRequest
  -> workflow_routing.resolve(data_type, operation) -> workflow_name
  -> workflow_routing.translate_platform_params(request, workflow_name) -> params
  -> create_and_submit_dag_run(workflow_name, params, request_id, asset_id, release_id)
```

### 5.3 Changes to `submit.py`

- Remove the `if workflow_engine == 'dag' / else` branch — DAG is the only path
- Replace `translate_to_coremachine()` call with `resolve()` + `translate_platform_params()`
- Replace `create_and_submit_job()` call with `create_and_submit_dag_run()`
- All surrounding code (Asset/Release management, ApiRequest tracking, error handling) stays identical

---

## 6. Integration: `platform/unpublish`

### 6.1 Current Flow (synchronous, inline handlers)

```
Unpublish request
  -> Resolve asset + release
  -> dry_run? Return preview (200)
  -> Call unpublish service functions directly (sync)
  -> Return result (200)
```

### 6.2 New Flow (async via DAG)

```
Unpublish request
  -> Resolve asset + release
  -> dry_run? Return preview (200) -- stays synchronous
  -> workflow_routing.resolve(data_type, "unpublish") -> workflow_name
  -> workflow_routing.translate_platform_params(...) -> params
  -> create_and_submit_dag_run(workflow_name, params, request_id)
  -> PlatformRepository.create_request() -- tracking record
  -> Return 202 Accepted with monitor_url
```

### 6.3 Behavioral Change

Unpublish becomes **asynchronous**. The response changes from:

```json
{"success": true, "deleted": {...}, "message": "Unpublished"}
```

To:

```json
{
    "success": true,
    "request_id": "abc123...",
    "job_id": "def456...",
    "status": "processing",
    "monitor_url": "/api/platform/status/abc123..."
}
```

Clients poll `platform/status/{request_id}` for completion — identical to the publish polling contract. The client does not need to know whether a publish or unpublish was submitted.

---

## 7. Prerequisites

These must be complete before the switchover can be attempted:

| Prerequisite | Version | Status |
|-------------|---------|--------|
| Vector YAML workflow E2E | v0.10.7 | DONE |
| Raster single COG YAML E2E | v0.10.8 | DONE |
| Zarr YAML workflows (ingest_zarr, netcdf_to_zarr) | v0.10.9 | NOT STARTED |
| Unpublish YAML workflows (vector, raster, zarr) | v0.10.10 | NOT STARTED (this design) |
| Unpublish atomic handlers | v0.10.10 | NOT STARTED (this design) |
| Routing table module | v0.10.10 | NOT STARTED (this design) |
| SIEGE Phase 1 pass (DAG-only) | v0.10.10 | Blocked by above |
| SIEGE Phase 2 pass (golden diff) | v0.10.10 | Blocked by Phase 1 |

---

## 8. Verification Strategy

Two-phase SIEGE verification proves output parity between Epoch 4 and Epoch 5.

### 8.1 Phase 1: DAG-Only SIEGE (Pre-Switchover Confidence)

Run all 26 SIEGE sequences with `"workflow_engine": "dag"` in every submit request body. Unpublish sequences route through the new DAG workflows.

**Gate**: All 26 sequences PASS with identical assertions as today's SIEGE runs.

This phase can run repeatedly during development. It proves DAG workflows produce correct outputs independently of whether they're the default.

### 8.2 Phase 2: Golden Baseline Diff (Switchover Proof)

1. **Capture baseline**: Run SIEGE against current CoreMachine default. Record all outputs:
   - HTTP response codes and bodies for every step
   - Final state of all STAC items, geo tables, approval records
   - Service URLs from `platform/status` responses

2. **Flip the default**: Apply the routing table change (DAG becomes the only path in `submit.py` and `unpublish.py`).

3. **Capture DAG outputs**: Run SIEGE again with identical test data. Record same outputs.

4. **Diff**: Compare baseline vs DAG outputs. Success = identical HTTP codes, response shapes, STAC items, service URLs, approval states, geo table contents.

**Gate**: Phase 2 diff shows zero divergences. This is the merge gate for the switchover PR.

### 8.3 SIEGE Sequence Coverage

All scenarios from the roadmap notes are covered:

| Scenario | SIEGE Sequences |
|----------|----------------|
| Publish new | S1 (raster), S2 (vector), S5/S6 (zarr) |
| Publish overwrite | S3 (multi-version), S10 (overwrite draft) |
| Approve | S1, S2 (approve step in lifecycle) |
| Publish overwrite approved (reject) | S22 (approved overwrite guard) |
| Unpublish | S4, S23 (blob preservation), S25 (DDH-only) |
| Release successions + overwrite | S14, S15, S16, S17, S18 |
| REST standards | S26 (headers, HEAD, pagination, CORS) |

---

## 9. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `core/workflow_routing.py` | Routing table + `resolve()` + `translate_platform_params()` |
| `workflows/unpublish_vector.yaml` | Vector unpublish DAG workflow |
| `workflows/unpublish_raster.yaml` | Raster unpublish DAG workflow |
| `workflows/unpublish_zarr.yaml` | Zarr unpublish DAG workflow |
| `services/handler_vector_unpublish_tables.py` | Drop base table + split views |
| `services/handler_vector_deregister_catalog.py` | Remove from table_catalog |
| `services/handler_raster_remove_stac.py` | Delete STAC item from pgSTAC |
| `services/handler_raster_delete_cog.py` | Delete COG blob from Silver |
| `services/handler_raster_cleanup_metadata.py` | Remove cog_metadata record |
| `services/handler_zarr_remove_stac.py` | Delete zarr STAC item |
| `services/handler_zarr_delete_store.py` | Delete zarr store from Silver |
| `services/handler_zarr_cleanup_metadata.py` | Remove zarr metadata record |

### Modified Files

| File | Change |
|------|--------|
| `triggers/platform/submit.py` | Remove if/else branch, use `resolve()` + `translate_platform_params()` + `create_and_submit_dag_run()` |
| `triggers/platform/unpublish.py` | Live path (dry_run=false) submits DAG workflow, returns 202 + monitor_url |
| `services/__init__.py` | Register new unpublish handlers in `ALL_HANDLERS` |
| `config/defaults.py` | Add unpublish handlers to `DOCKER_TASKS` |
| `core/workflow_registry.py` | Remove `JOB_TYPE_ALIASES` (routing table replaces it) |

### Untouched (Removed at v0.11.0)

| File | Why Kept |
|------|----------|
| `core/machine.py` | Dead code — no longer invoked but not deleted yet |
| `services/platform_job_submit.py` → `create_and_submit_job()` | Dead code |
| `triggers/service_bus/*` | Dead code — SB triggers still registered but never fire |
| `jobs/` directory | Dead code — Python job classes no longer instantiated |
| Legacy monolithic handlers (34) | Dead code — DAG atomic handlers replace them |

---

## 10. Risks

| Risk | Mitigation |
|------|------------|
| Zarr workflows not ready (v0.10.9 prerequisite) | Switchover blocked until v0.10.9 complete. Routing table returns clear error for missing routes. |
| Unpublish async change breaks existing B2B consumers | Consumers already poll `platform/status` for publish. Same contract. `dry_run` preview stays synchronous. |
| SIEGE golden diff shows unexpected divergences | Fix divergences before merging. Phase 1 (DAG-only SIEGE) catches most issues early. |
| Tiled raster not in routing table | Returns explicit error. Single COG path works. Tiled path is a separate v0.10.8 deliverable. |
| Dead CoreMachine code causes confusion | Document clearly in V10_MIGRATION.md that CoreMachine is dead code awaiting v0.11.0 cleanup. |
