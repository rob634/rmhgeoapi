# Unpublish DAG Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `unpublish_raster.yaml` and `unpublish_vector.yaml` DAG workflows that wire existing Epoch 4 handlers, enabling raster and vector unpublish via the DAG Brain.

**Architecture:** Two new YAML workflow files reference 5 existing handlers from `ALL_HANDLERS`. One handler (`inventory_raster_item`) needs a small fix to self-fetch the STAC item when not pre-populated by an Epoch 4 validator. No new handlers, no `stac_dematerialize_item`.

**Tech Stack:** YAML workflow definitions, Python handler fix, `conda activate azgeo`, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-unpublish-dag-workflows-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `workflows/unpublish_raster.yaml` | Create | Raster unpublish DAG: inventory → fan-out blob delete → fan-in → cleanup+audit |
| `workflows/unpublish_vector.yaml` | Create | Vector unpublish DAG: inventory → drop table → cleanup+audit |
| `services/unpublish_handlers.py:74-89` | Modify | Make `inventory_raster_item` self-sufficient (fetch STAC item if `_stac_item` not pre-populated) |
| `jobs/unpublish_vector_multi_source.py` | Modify | Fix `dry_run` default from `false` to `true` |
| `V10_MIGRATION.md` | Modify | Update v0.10.9 remaining items — remove `stac_dematerialize_item`, supersede draft YAML |
| `docs_claude/DEV_BEST_PRACTICES.md` | Modify | Add `dry_run: true` default standard |

---

### Task 1: Make `inventory_raster_item` self-sufficient

The handler currently expects `_stac_item` pre-populated by the Epoch 4 `stac_item_exists` validator. In the DAG path, no validator runs — the handler must fetch the STAC item itself.

**Files:**
- Modify: `services/unpublish_handlers.py:74-89`

- [ ] **Step 1: Add STAC self-fetch fallback**

In `services/unpublish_handlers.py`, replace lines 79-89 (the block that reads `_stac_item` from params and fails if absent) with a fallback that fetches from pgSTAC:

```python
        # Get pre-validated STAC item from validator (Epoch 4 path)
        # OR fetch directly from pgSTAC (DAG path — no validator)
        stac_item = params.get('_stac_item')
        assets = params.get('_stac_item_assets', {})
        original_job_id = params.get('_stac_original_job_id')

        if not stac_item:
            # DAG path: no validator pre-populated _stac_item — fetch directly
            if not stac_item_id or not collection_id:
                return {
                    "success": False,
                    "error": "stac_item_id and collection_id are required",
                    "error_type": "ValidationError"
                }
            from infrastructure.pgstac_repository import PgStacRepository
            pgstac_repo = PgStacRepository()
            stac_item = pgstac_repo.get_item(stac_item_id, collection_id)
            if not stac_item:
                return {
                    "success": False,
                    "error": f"STAC item not found: {collection_id}/{stac_item_id}",
                    "error_type": "NotFoundError"
                }
            assets = stac_item.get('assets', {})
            original_job_id = stac_item.get('properties', {}).get('geoetl:job_id')
            logger.info(
                "inventory_raster_item: fetched STAC item directly (DAG path): %s/%s (%d assets)",
                collection_id, stac_item_id, len(assets)
            )
```

This preserves backward compatibility: Epoch 4 still passes `_stac_item` via the validator, DAG path fetches it. Both work.

- [ ] **Step 2: Verify existing Epoch 4 tests still pass**

Run: `conda activate azgeo && python -m pytest tests/ -k "unpublish" -v --no-header 2>&1 | head -40`

Expected: All existing unpublish tests pass (they use the `_stac_item` params path).

- [ ] **Step 3: Commit**

```bash
git add services/unpublish_handlers.py
git commit -m "fix: inventory_raster_item self-fetches STAC item when _stac_item absent (DAG path)"
```

---

### Task 2: Create `unpublish_raster.yaml`

**Files:**
- Create: `workflows/unpublish_raster.yaml`

- [ ] **Step 1: Write the workflow YAML**

Create `workflows/unpublish_raster.yaml`:

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

- [ ] **Step 2: Validate YAML loads and passes schema validation**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
defn = loader.load_workflow('unpublish_raster')
errors = loader.validate_workflow(defn)
print(f'Loaded: {defn.workflow}, nodes: {len(defn.nodes)}, errors: {errors}')
"`

Expected: `Loaded: unpublish_raster, nodes: 4, errors: []`

- [ ] **Step 3: Verify workflow appears in registry**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
registry = loader.load_all()
print(f'Total workflows: {len(registry)}')
print('unpublish_raster' in registry)
"`

Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add workflows/unpublish_raster.yaml
git commit -m "feat: unpublish_raster.yaml — DAG workflow wiring existing handlers"
```

---

### Task 3: Create `unpublish_vector.yaml`

**Files:**
- Create: `workflows/unpublish_vector.yaml`

- [ ] **Step 1: Write the workflow YAML**

Create `workflows/unpublish_vector.yaml`:

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

- [ ] **Step 2: Validate YAML loads and passes schema validation**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
defn = loader.load_workflow('unpublish_vector')
errors = loader.validate_workflow(defn)
print(f'Loaded: {defn.workflow}, nodes: {len(defn.nodes)}, errors: {errors}')
"`

Expected: `Loaded: unpublish_vector, nodes: 3, errors: []`

- [ ] **Step 3: Verify workflow appears in registry**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
registry = loader.load_all()
for name in sorted(registry):
    if 'unpublish' in name:
        print(name)
"`

Expected:
```
unpublish_raster
unpublish_vector
```

- [ ] **Step 4: Commit**

```bash
git add workflows/unpublish_vector.yaml
git commit -m "feat: unpublish_vector.yaml — DAG workflow wiring existing handlers"
```

---

### Task 4: Fix `dry_run` default in `unpublish_vector_multi_source`

**Files:**
- Modify: `jobs/unpublish_vector_multi_source.py`

- [ ] **Step 1: Find and fix the `dry_run` default**

In `jobs/unpublish_vector_multi_source.py`, in the `parameters_schema` dict, change:

```python
        'dry_run': {'type': 'bool', 'default': False},
```

to:

```python
        'dry_run': {'type': 'bool', 'default': True},
```

- [ ] **Step 2: Verify the fix**

Run: `conda activate azgeo && python -c "
from jobs.unpublish_vector_multi_source import UnpublishVectorMultiSourceJob
schema = UnpublishVectorMultiSourceJob.parameters_schema
print(f\"dry_run default: {schema['dry_run']['default']}\")
"`

Expected: `dry_run default: True`

- [ ] **Step 3: Commit**

```bash
git add jobs/unpublish_vector_multi_source.py
git commit -m "fix: unpublish_vector_multi_source dry_run defaults to true (safety standard)"
```

---

### Task 5: Update `DEV_BEST_PRACTICES.md` with `dry_run` standard

**Files:**
- Modify: `docs_claude/DEV_BEST_PRACTICES.md`

- [ ] **Step 1: Add `dry_run: true` default standard**

Add a new section to `docs_claude/DEV_BEST_PRACTICES.md` (find the appropriate location among existing patterns):

```markdown
## Destructive Operations: `dry_run: true` Default

**Standard (26 MAR 2026)**: All destructive workflows and handlers MUST default `dry_run` to `true`. The caller must explicitly pass `dry_run: false` to execute mutations.

This is a standard safety practice in integrated applications (Terraform plan/apply, Ansible --check, Kubernetes --dry-run). It prevents misconfigured or accidental submissions from causing data loss.

**Applies to:**
- YAML workflow parameter declarations (`dry_run: {type: bool, default: true}`)
- Platform routing (`translate_for_dag()` must not silently flip to false)
- Handler parameter defaults (`params.get('dry_run', True)`)
- Any endpoint that deletes, drops, or unpublishes data

**Examples of destructive operations:**
- Unpublish (raster, vector, zarr) — deletes blobs, drops tables, removes STAC items
- Schema rebuild (`action=rebuild`) — drops and recreates schemas
- STAC nuke — clears all STAC items/collections
- Job cleanup — deletes old job/task records
```

- [ ] **Step 2: Commit**

```bash
git add docs_claude/DEV_BEST_PRACTICES.md
git commit -m "docs: add dry_run=true default as project standard"
```

---

### Task 6: Update `V10_MIGRATION.md`

**Files:**
- Modify: `V10_MIGRATION.md`

- [ ] **Step 1: Remove `stac_dematerialize_item` from v0.10.9 remaining items**

In `V10_MIGRATION.md`, in the Phase 7 section (around line 2905), the remaining items list currently starts with:

```
1. Build `stac_dematerialize_item` handler — shared prerequisite for all unpublish workflows
2. Build `workflows/unpublish_raster.yaml` — **HIGH PRIORITY**
3. Build `workflows/unpublish_vector.yaml` — **HIGH PRIORITY**
```

Replace with:

```
1. ~~Build `stac_dematerialize_item` handler~~ — NOT NEEDED: `delete_stac_and_audit` already handles STAC deletion + release revocation + audit in a single transaction. See spec: `docs/superpowers/specs/2026-03-26-unpublish-dag-workflows-design.md` decision D2.
2. Build `workflows/unpublish_raster.yaml` — **DONE**: wires existing `unpublish_inventory_raster` → fan-out `unpublish_delete_blob` → `unpublish_delete_stac`
3. Build `workflows/unpublish_vector.yaml` — **DONE**: wires existing `unpublish_inventory_vector` → `unpublish_drop_table` → `unpublish_delete_stac`
```

- [ ] **Step 2: Update the superseded draft YAML reference**

In the Unpublish Vector section (around line 1358), add a note above the existing draft YAML:

```markdown
> **SUPERSEDED (26 MAR 2026)**: This draft assumed handler names (`unpublish_cleanup_postgis`, `unpublish_cleanup_catalog`, `unpublish_finalize`) that were never built. The actual implementation wires the 7 existing Epoch 4 handlers directly. See `workflows/unpublish_vector.yaml` and spec `docs/superpowers/specs/2026-03-26-unpublish-dag-workflows-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add V10_MIGRATION.md
git commit -m "docs: update V10_MIGRATION — unpublish workflows done, stac_dematerialize_item not needed"
```

---

### Task 7: Local Validation (Pre-Deploy Smoke Test)

This task validates the YAML workflows load correctly, handlers resolve, and the parameter wiring is consistent. Not a deployment — just local validation that everything is wired correctly before Azure E2E.

**Files:** None (read-only validation)

- [ ] **Step 1: Validate both workflows load with zero errors**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
for wf_name in ['unpublish_raster', 'unpublish_vector']:
    defn = loader.load_workflow(wf_name)
    errors = loader.validate_workflow(defn)
    node_types = [n.type for n in defn.nodes.values()]
    print(f'{wf_name}: {len(defn.nodes)} nodes, types={node_types}, errors={errors}')
"`

Expected:
```
unpublish_raster: 4 nodes, types=['task', 'fan_out', 'fan_in', 'task'], errors=[]
unpublish_vector: 3 nodes, types=['task', 'task', 'task'], errors=[]
```

- [ ] **Step 2: Verify all referenced handlers exist in ALL_HANDLERS**

Run: `conda activate azgeo && python -c "
from services import ALL_HANDLERS
required = [
    'unpublish_inventory_raster',
    'unpublish_inventory_vector',
    'unpublish_delete_blob',
    'unpublish_drop_table',
    'unpublish_delete_stac',
]
for h in required:
    present = h in ALL_HANDLERS
    print(f'{h}: {\"OK\" if present else \"MISSING\"} — {ALL_HANDLERS[h].__name__ if present else \"N/A\"}')
"`

Expected: All 5 show `OK`.

- [ ] **Step 3: Count total workflows in registry**

Run: `conda activate azgeo && python -c "
from core.workflow_loader import WorkflowLoader
loader = WorkflowLoader()
registry = loader.load_all()
print(f'Total workflows: {len(registry)}')
for name in sorted(registry):
    print(f'  {name}')
"`

Expected: Previous count + 2 (unpublish_raster, unpublish_vector added).

- [ ] **Step 4: Final commit (all tasks complete)**

```bash
git add -A
git commit -m "feat: unpublish DAG workflows complete — raster + vector (v0.10.9)"
```

Only create this commit if there are uncommitted changes from previous tasks. If everything was committed in earlier tasks, skip this step.

---

## E2E Validation (Post-Deploy — Separate Session)

After deployment to Azure, run these tests. This is NOT part of the implementation plan — it's a separate test session after `deploy.sh docker`.

1. **Dry run (raster)**: Submit `unpublish_raster` with `dry_run: true` → all nodes complete, no data mutated
2. **Live run (raster)**: Submit with `dry_run: false` → blobs deleted, STAC item removed, audit recorded
3. **Dry run (vector)**: Submit `unpublish_vector` with `dry_run: true` → all nodes complete, table intact
4. **Live run (vector)**: Submit with `dry_run: false` → table dropped, metadata deleted, audit recorded
5. **Idempotent rerun**: Submit same params again → graceful handling (already deleted)
6. **Approval block**: Submit against approved release without `force_approved` → fails at inventory node
