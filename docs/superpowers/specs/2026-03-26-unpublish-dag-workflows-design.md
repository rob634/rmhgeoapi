# Unpublish DAG Workflows — Design Spec

**Created**: 26 MAR 2026
**Status**: DRAFT
**Version**: v0.10.9
**Author**: Claude + Robert Harrison
**Relates to**: V10_MIGRATION.md Phase 7 (v0.10.9), Epoch 4 unpublish jobs

---

## Summary

Wire the 7 existing Epoch 4 unpublish handlers into two YAML DAG workflows: `unpublish_raster.yaml` and `unpublish_vector.yaml`. No new handlers. No `stac_dematerialize_item`. The existing handlers are already atomic, proven, and registered in `ALL_HANDLERS`.

**Scope**: Two YAML workflow files + one standard codified (`dry_run: true` default).
**Out of scope**: `unpublish_vector_multi.yaml`, `unpublish_zarr.yaml`, platform routing changes (v0.10.10), new handler code.

---

## Design Decisions

### D1: Reuse existing Epoch 4 handlers — no new handler code

The 7 unpublish handlers in `services/unpublish_handlers.py` (1,441 lines) are already atomic and registered in `ALL_HANDLERS`. The V10_MIGRATION.md draft YAML referenced handler names that were never built (`unpublish_cleanup_postgis`, `unpublish_cleanup_catalog`, `unpublish_finalize`). Those drafts are superseded — the real handlers map directly to DAG nodes.

| ALL_HANDLERS Key | Handler Function | Role |
|------------------|-----------------|------|
| `unpublish_inventory_raster` | `inventory_raster_item` | Query STAC item, extract blob hrefs, check approval |
| `unpublish_inventory_vector` | `inventory_vector_item` | Query table_catalog + etl_tracking, check approval |
| `unpublish_delete_blob` | `delete_blob` | Delete single blob (idempotent, fan-out target) |
| `unpublish_drop_table` | `drop_postgis_table` | DROP TABLE CASCADE + delete metadata rows |
| `unpublish_delete_stac` | `delete_stac_and_audit` | STAC delete + revocation + audit (single transaction) |

Not used in this spec (lower priority, same pattern):
- `unpublish_inventory_vector_multi` — for `unpublish_vector_multi.yaml` (future)
- `unpublish_inventory_zarr` — for `unpublish_zarr.yaml` (future)

### D1b: `inventory_raster_item` self-fetch fix

The Epoch 4 path pre-populates `_stac_item` in handler params via the `stac_item_exists` resource validator (runs before job creation). In the DAG path, no validators run — the handler receives only the YAML-declared params.

**Fix**: At the `if not stac_item:` guard (line 84), instead of returning a validation error, fetch the STAC item directly from pgSTAC using `stac_item_id` + `collection_id`. This makes the handler self-sufficient for both Epoch 4 (validator pre-populates) and Epoch 5 (handler fetches). Backward compatible — the `_stac_item` params path is tried first.

The vector inventory handler (`inventory_vector_item`) does NOT need this fix — it queries `geo.table_catalog` directly from `table_name` with no validator dependency.

### D2: No `stac_dematerialize_item` handler

`delete_stac_and_audit` performs STAC item deletion, release revocation, empty collection cleanup, and audit trail insertion — all within a single PostgreSQL transaction. This is intentional: if any step fails, the entire operation rolls back, preventing inconsistent state (e.g., deleted STAC item with still-approved release).

Extracting a thin `stac_dematerialize_item` (just the pgSTAC DELETE) would break this transactional guarantee and require the audit/revocation logic to live elsewhere. There is no workflow that needs "delete STAC without auditing." The existing handler is the right granularity.

**Update V10_MIGRATION.md**: Remove `stac_dematerialize_item` from the v0.10.9 remaining items. Note that `delete_stac_and_audit` serves this role.

### D3: `dry_run: true` as universal default (NEW PROJECT STANDARD)

All destructive workflows MUST default `dry_run` to `true`. The caller must explicitly pass `dry_run: false` to execute mutations. This is a standard safety practice in integrated applications (Terraform plan/apply, Ansible --check, k8s --dry-run).

**Applies to**:
- All YAML workflow parameter declarations
- The `translate_for_dag()` routing layer (must not silently flip to false)
- Platform UI (if/when built — default toggle position is "preview")
- Future destructive workflows (rebuild, nuke, cleanup)

**Epoch 4 alignment**: `unpublish_vector_multi_source` currently defaults `dry_run: false`. Fix to `true` as part of this work.

### D4: No `finalize:` block

The `finalize:` block in YAML runs after DAG completion to clean up intermediate files on the ETL mount. Unpublish workflows don't download files — they query databases and call delete APIs. Nothing to clean up.

`finalize:` is `Optional[FinalizeDef] = None` in the workflow model — omitting it is valid.

### D5: DAG eliminates `_inventory_data` pass-through hack

In Epoch 4, `drop_postgis_table` receives `_inventory_data` from inventory and passes it through to Stage 3 unchanged. This exists because CoreMachine can only pass results from the immediately preceding stage.

The DAG parameter resolver supports cross-node references natively. The cleanup node can `receives:` directly from both inventory and drop_table nodes. No pass-through needed.

---

## Workflow Definitions

### `workflows/unpublish_raster.yaml`

**DAG shape**: inventory → fan_out(delete_blobs) → fan_in → cleanup

```yaml
workflow: unpublish_raster
description: "Unpublish raster: delete COG blobs + STAC item + audit trail"
version: 1
reverses: [process_raster]

parameters:
  stac_item_id: {type: str, required: true}
  collection_id: {type: str, required: true}
  dry_run: {type: bool, default: true}
  force_approved: {type: bool, default: false}
  unpublish_type: {type: str, default: "raster"}

nodes:
  inventory:
    type: task
    handler: unpublish_inventory_raster
    params: [stac_item_id, collection_id, dry_run, force_approved]

  delete_blobs:
    type: fan_out
    depends_on: [inventory]
    source: "inventory.result.blobs_to_delete"
    task:
      handler: unpublish_delete_blob
      params:
        container: "{{ item.container }}"
        blob_path: "{{ item.blob_path }}"
        dry_run: "{{ inputs.dry_run }}"

  aggregate_deletes:
    type: fan_in
    depends_on: [delete_blobs]
    aggregation: collect

  cleanup:
    type: task
    handler: unpublish_delete_stac
    depends_on: [aggregate_deletes]
    params: [stac_item_id, collection_id, dry_run, unpublish_type]
    receives:
      stac_item_snapshot: "inventory.result.stac_item_snapshot"
      original_job_id: "inventory.result.original_job_id"
```

**Notes**:
- Fan-out source is `inventory.result.blobs_to_delete` — a list of `{container, blob_path}` dicts
- `dry_run` propagates to all mutation nodes via workflow params
- `unpublish_type` is a workflow parameter with a fixed default (the param resolver does not support literal strings in `receives:` — only dotted path references)
- If `blobs_to_delete` is empty (e.g., `stac_catalog_container` items with no blobs), fan-out produces zero children — fan-in completes immediately, cleanup runs
- Approval check happens in inventory handler — if blocked, the workflow fails at the first node

### `workflows/unpublish_vector.yaml`

**DAG shape**: inventory → drop_table → cleanup (linear, no fan-out)

```yaml
workflow: unpublish_vector
description: "Unpublish vector: drop PostGIS table + metadata + optional STAC item + audit trail"
version: 1
reverses: [vector_docker_etl]

parameters:
  table_name: {type: str, required: true}
  schema_name: {type: str, default: "geo"}
  dry_run: {type: bool, default: true}
  force_approved: {type: bool, default: false}
  unpublish_type: {type: str, default: "vector"}

nodes:
  inventory:
    type: task
    handler: unpublish_inventory_vector
    params: [table_name, schema_name, dry_run, force_approved]

  drop_table:
    type: task
    handler: unpublish_drop_table
    depends_on: [inventory]
    params: [schema_name, dry_run]
    receives:
      table_name: "inventory.result.table_name"

  cleanup:
    type: task
    handler: unpublish_delete_stac
    depends_on: [drop_table]
    params: [dry_run, unpublish_type]
    receives:
      stac_item_id: "inventory.result.stac_item_id"
      collection_id: "inventory.result.stac_collection_id"
      metadata_snapshot: "inventory.result.metadata_snapshot"
      postgis_table: "inventory.result.table_name"
      table_dropped: "drop_table.result.table_dropped"
```

**Notes**:
- Linear DAG — no fan-out needed (single table drop)
- Cleanup node receives from BOTH inventory and drop_table — this is the DAG advantage over Epoch 4's `_inventory_data` pass-through
- STAC deletion is optional for vectors — `delete_stac_and_audit` handles `stac_item_id=None` gracefully
- `delete_metadata: "'true'"` is a literal boolean string — the handler interprets it

---

## Parameter Resolution Details

### How `dry_run` propagates

`dry_run` is declared as a workflow parameter with `default: true`. Each node that performs mutations includes `dry_run` in its `params:` list. The parameter resolver injects the workflow-level value. The caller must pass `dry_run: false` to execute.

### How fan-out works (raster)

The `delete_blobs` fan-out node:
1. Reads `inventory.result.blobs_to_delete` (a list)
2. Creates one child task per list item
3. Each child receives `container` and `blob_path` from `{{ item.X }}` template syntax
4. `dry_run` comes from `{{ inputs.dry_run }}` (workflow param)

This is the same fan-out pattern proven in `process_raster.yaml` (tile processing) and `ingest_zarr.yaml` (blob copy batches).

### Cross-node references (vector cleanup)

The cleanup node demonstrates the DAG's native diamond dependency resolution:

```
inventory ──→ drop_table ──→ cleanup
    │                           ↑
    └───────────────────────────┘
         (direct receives)
```

`cleanup.receives` pulls from both `inventory.result.*` and `drop_table.result.*`. No pass-through hack needed.

---

## Existing Handler Contracts (Reference)

### `unpublish_inventory_raster` → returns:
```python
{
    "success": True,
    "blobs_to_delete": [{"container": str, "blob_path": str, "asset_key": str, "href": str}],
    "blob_count": int,
    "original_job_id": str,
    "stac_item_snapshot": dict,
    "dry_run": bool
}
```

### `unpublish_inventory_vector` → returns:
```python
{
    "success": True,
    "table_name": str,
    "schema_name": str,
    "metadata_found": bool,
    "etl_job_id": str,
    "stac_item_id": str | None,
    "stac_collection_id": str | None,
    "source_file": str,
    "source_format": str,
    "feature_count": int,
    "metadata_snapshot": dict,
    "dry_run": bool
}
```

### `unpublish_delete_blob` → returns:
```python
{
    "success": True,
    "deleted": bool,
    "container": str,
    "blob_path": str,
    "dry_run": bool
}
```

### `unpublish_drop_table` → returns:
```python
{
    "success": True,
    "table_dropped": bool,
    "metadata_deleted": bool,
    "already_gone": bool,
    "table_name": str,
    "schema_name": str
}
```

### `unpublish_delete_stac` → returns:
```python
{
    "success": True,
    "stac_item_deleted": bool,
    "collection_deleted": bool,
    "collection_remaining_items": int,
    "audit_record_id": str,
    "dry_run": bool
}
```

---

## Validation Plan

### E2E test sequence (per workflow)

1. **Dry run first**: Submit with `dry_run: true` (default) → verify all nodes complete, no data mutated
2. **Live run**: Submit with `dry_run: false` → verify artifacts actually deleted
3. **Idempotent rerun**: Submit same params again with `dry_run: false` → verify graceful handling (blob already gone, table already dropped)
4. **Platform integration** (v0.10.10): Submit via `POST /api/platform/submit` with `workflow_engine: "dag"` → verify full asset lifecycle

### Raster test cases
- Single COG unpublish (1 blob) — happy path
- Tiled COG unpublish (N blobs) — fan-out proof
- STAC-only item (no blobs) — empty fan-out → fan-in → cleanup
- Approved release without `force_approved` — should fail at inventory
- Approved release with `force_approved: true` — should succeed with atomic revocation

### Vector test cases
- Table with STAC linkage — full cleanup including STAC delete
- Table without STAC linkage — STAC delete skipped gracefully
- Table with split views — CASCADE handles view drops
- Approved release without `force_approved` — should fail at inventory

---

## Impact on V10_MIGRATION.md

1. **v0.10.9 remaining items**: Remove `stac_dematerialize_item` — `delete_stac_and_audit` serves this role
2. **Unpublish Vector draft YAML** (line 1358): Superseded by this spec — handler names updated
3. **Progress tracker**: Update v0.10.9 status after E2E validation
4. **dry_run standard**: Add to DEV_BEST_PRACTICES.md as a project convention

---

## Files Changed

| File | Change | New? |
|------|--------|------|
| `workflows/unpublish_raster.yaml` | New YAML workflow | Yes |
| `workflows/unpublish_vector.yaml` | New YAML workflow | Yes |
| `jobs/unpublish_vector_multi_source.py` | Fix `dry_run` default to `true` | No (one-line fix) |
| `V10_MIGRATION.md` | Update v0.10.9 remaining items, supersede draft YAML | No |
| `docs_claude/DEV_BEST_PRACTICES.md` | Add `dry_run: true` default standard | No |

---

*Spec: docs/superpowers/specs/2026-03-26-unpublish-dag-workflows-design.md*
*Related: V10_MIGRATION.md Phase 7 (v0.10.9)*
