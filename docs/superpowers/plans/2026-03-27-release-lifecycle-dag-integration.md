# Release Lifecycle DAG Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire DAG workflows into the existing Asset/Release management system with a human approval gate node, version ordinal relaxation, and externalization routing.

**Architecture:** Add a `type: gate` node to the DAG engine that suspends workflows at human decision points. The approval API completes the gate, branching to STAC materialization (approve) or workflow termination (reject). The existing AssetRelease entity (44 fields, 3 state machines) is unchanged — this is a wiring problem. Version ordinal ordering guards are relaxed so any ordinal can be approved independently.

**Tech Stack:** Python 3.12, psycopg3, Pydantic v2, YAML workflows, PostgreSQL

**Dependencies:** Requires existing `AssetService`, `AssetApprovalService`, `ReleaseRepository`, DAG transition engine, janitor, Brain poll loop.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| (none) | All changes are modifications to existing files |

### Modified Files
| File | Changes |
|------|---------|
| `core/models/workflow_definition.py` | Add `GateNode` class to discriminated union |
| `infrastructure/workflow_run_repository.py` | Add `WAITING` task status, `AWAITING_APPROVAL` run status, `complete_gate_node()` method |
| `core/dag_graph_utils.py` | Add `WAITING` to terminal statuses |
| `core/dag_transition_engine.py` | Promote gate nodes to `WAITING` instead of `READY` |
| `core/dag_orchestrator.py` | Skip `AWAITING_APPROVAL` runs in poll loop |
| `core/dag_janitor.py` | Skip `AWAITING_APPROVAL` runs in stale scan |
| `services/asset_approval_service.py` | Remove SG5-1 guard, call `complete_gate_node()` on approve/reject |
| `workflows/process_raster.yaml` | Add `approval_gate` node between persist and STAC materialize |
| `workflows/vector_docker_etl.yaml` | Add `approval_gate` node between register_catalog and refresh_tipg |
| `services/__init__.py` | No handler registration needed (gate is orchestrator-managed) |

---

## Task 1: Add GateNode Model and Status Enums

**Files:**
- Modify: `core/models/workflow_definition.py:81-129`
- Modify: `infrastructure/workflow_run_repository.py:41-68`

- [ ] **Step 1: Add GateNode class to workflow_definition.py**

Add after `FanInNode` (line ~122) and before `NodeDefinition` union (line ~125):

```python
class GateNode(BaseModel):
    """
    A node that suspends workflow execution until an external signal.

    Gate nodes block downstream dependencies until completed by an external
    API call (e.g., human approval). The transition engine promotes gate nodes
    to WAITING (not READY), and the janitor/Brain skip workflows in
    AWAITING_APPROVAL status.

    No handler is dispatched — the node transitions:
      PENDING → WAITING (when predecessors complete)
      WAITING → COMPLETED (when external API calls complete_gate_node)
      WAITING → SKIPPED (when external API rejects/cancels)
    """
    type: Literal["gate"] = "gate"
    depends_on: list[str] = []
    gate_type: str = "approval"  # Extensible: "approval", "quality_check", etc.
```

Update the `NodeDefinition` discriminated union:

```python
NodeDefinition = Annotated[
    TaskNode | ConditionalNode | FanOutNode | FanInNode | GateNode,
    Field(discriminator='type')
]
```

- [ ] **Step 2: Add `get_gate_nodes()` helper to WorkflowDefinition**

Add to `WorkflowDefinition` class (after `get_leaf_nodes()`):

```python
def get_gate_nodes(self) -> list[str]:
    """Return names of all gate nodes in this workflow."""
    return [
        name for name, node in self.nodes.items()
        if isinstance(node, GateNode)
    ]
```

- [ ] **Step 3: Add WAITING task status and AWAITING_APPROVAL run status**

In `infrastructure/workflow_run_repository.py`, update the status enums:

Add to `WorkflowTaskStatus` (after `CANCELLED`):
```python
WAITING = "waiting"  # Gate node — awaiting external signal
```

Add to `WorkflowRunStatus` (after `FAILED`):
```python
AWAITING_APPROVAL = "awaiting_approval"  # Suspended at gate node
```

- [ ] **Step 4: Update DDL for new enum values**

In `infrastructure/deployer.py` (or wherever schema DDL is managed), the enum types need the new values. Search for `workflow_task_status` and `workflow_run_status` enum creation and add the new values.

For PostgreSQL, this requires:
```sql
ALTER TYPE app.workflow_task_status ADD VALUE IF NOT EXISTS 'waiting';
ALTER TYPE app.workflow_run_status ADD VALUE IF NOT EXISTS 'awaiting_approval';
```

Add these to the `ensure` action in `deployer.py` so they run on deploy.

- [ ] **Step 5: Commit**

```bash
git add core/models/workflow_definition.py infrastructure/workflow_run_repository.py infrastructure/deployer.py
git commit -m "feat: add GateNode model + WAITING/AWAITING_APPROVAL status enums"
```

---

## Task 2: Update Graph Utils and Transition Engine

**Files:**
- Modify: `core/dag_graph_utils.py:39-45`
- Modify: `core/dag_transition_engine.py:268-489`

- [ ] **Step 1: Add WAITING to terminal statuses in graph utils**

In `core/dag_graph_utils.py`, update `_TERMINAL_TASK_STATUSES` (line ~39):

```python
_TERMINAL_TASK_STATUSES = frozenset({
    WorkflowTaskStatus.COMPLETED,
    WorkflowTaskStatus.FAILED,
    WorkflowTaskStatus.SKIPPED,
    WorkflowTaskStatus.CANCELLED,
    WorkflowTaskStatus.EXPANDED,
    WorkflowTaskStatus.WAITING,  # Gate node — terminal for predecessor checks
})
```

**Why WAITING is terminal:** Downstream nodes of a gate depend on the gate completing. But the gate's own predecessors need to see the gate as "done blocking" so the transition engine doesn't stall. WAITING means "I'm not going to change state on my own" — same as COMPLETED from the predecessor's perspective.

**IMPORTANT:** Also update `is_run_terminal()` to handle WAITING. A run with any WAITING task is NOT terminal — it's suspended:

In `is_run_terminal()` (line ~279), add before the existing logic:

```python
# A run with any WAITING task is suspended, not terminal
if any(t.status == WorkflowTaskStatus.WAITING for t in tasks):
    return (False, WorkflowRunStatus.AWAITING_APPROVAL)
```

- [ ] **Step 2: Update transition engine to promote gate nodes to WAITING**

In `core/dag_transition_engine.py`, in the `evaluate_transitions()` function, find where nodes are promoted to READY (around line 356-470). After the predecessor check passes, add gate node handling:

```python
# After confirming all_predecessors_terminal() returns True for this node:

from core.models.workflow_definition import GateNode

node_def = workflow_def.nodes.get(task.task_name)

if isinstance(node_def, GateNode):
    # Gate nodes go to WAITING, not READY — they await external signal
    promoted = repo.promote_task(
        task.task_instance_id,
        WorkflowTaskStatus.PENDING,
        WorkflowTaskStatus.WAITING,
    )
    if promoted:
        result.promoted.append(task.task_instance_id)
        logger.info(
            "Gate node %s promoted to WAITING (awaiting external signal)",
            task.task_name,
        )
    continue  # Skip parameter resolution — gate nodes have no handler
```

This must be inserted BEFORE the existing parameter resolution logic for TaskNodes (the `set_params_and_promote` call).

- [ ] **Step 3: Commit**

```bash
git add core/dag_graph_utils.py core/dag_transition_engine.py
git commit -m "feat: transition engine promotes gate nodes to WAITING state"
```

---

## Task 3: Janitor and Brain Exemption

**Files:**
- Modify: `core/dag_janitor.py`
- Modify: `core/dag_orchestrator.py`

- [ ] **Step 1: Skip AWAITING_APPROVAL runs in janitor**

In `core/dag_janitor.py`, the janitor scans for stale RUNNING tasks. It queries via `get_stale_workflow_tasks()` which only looks at RUNNING tasks — so WAITING tasks are already excluded from stale detection.

However, add an explicit guard in the janitor's main scan loop. Find where runs are queried (the scan method) and add:

```python
# Skip runs in AWAITING_APPROVAL — these are intentionally suspended at a gate node
if run_status == WorkflowRunStatus.AWAITING_APPROVAL:
    logger.debug("Janitor skipping AWAITING_APPROVAL run %s", run_id)
    continue
```

Also add `WAITING` to the sentinel handler skip list in `get_stale_workflow_tasks()` (in `workflow_run_repository.py` around line 1265). Find where `__conditional__`, `__fan_out__`, `__fan_in__` are excluded and add `__gate__`:

```python
AND handler NOT IN ('__conditional__', '__fan_out__', '__fan_in__', '__gate__')
```

- [ ] **Step 2: Skip AWAITING_APPROVAL runs in Brain poll loop**

In `core/dag_orchestrator.py`, the `run()` method processes runs. Find where run status is checked at the top of the poll cycle (around line 275-287). Add:

```python
if current_status == WorkflowRunStatus.AWAITING_APPROVAL:
    logger.debug("Skipping AWAITING_APPROVAL run %s", run_id)
    continue
```

Also update the run query to exclude AWAITING_APPROVAL from the poll set. Find where the orchestrator queries for active runs and ensure AWAITING_APPROVAL runs are not fetched (they don't need processing).

- [ ] **Step 3: Update run status transition in orchestrator**

In `core/dag_orchestrator.py`, after `is_run_terminal()` is called (around line 402-419), handle the AWAITING_APPROVAL case:

```python
is_terminal, terminal_status = is_run_terminal(tasks)

if terminal_status == WorkflowRunStatus.AWAITING_APPROVAL:
    # Run has hit a gate node — suspend it
    self._repo.update_run_status(run_id, WorkflowRunStatus.AWAITING_APPROVAL)
    logger.info("Run %s suspended at gate node (AWAITING_APPROVAL)", run_id)
    result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
    break
elif is_terminal:
    self._repo.update_run_status(run_id, terminal_status)
    ...
```

- [ ] **Step 4: Allow AWAITING_APPROVAL → RUNNING transition in repository**

In `infrastructure/workflow_run_repository.py`, update `update_run_status()` (around line 1385-1482) to allow:
- `running → awaiting_approval` (suspend at gate)
- `awaiting_approval → running` (resume after approval)

Add to the allowed transitions:

```python
_ALLOWED_RUN_TRANSITIONS = {
    WorkflowRunStatus.PENDING: {WorkflowRunStatus.RUNNING},
    WorkflowRunStatus.RUNNING: {WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED, WorkflowRunStatus.AWAITING_APPROVAL},
    WorkflowRunStatus.AWAITING_APPROVAL: {WorkflowRunStatus.RUNNING},
}
```

- [ ] **Step 5: Commit**

```bash
git add core/dag_janitor.py core/dag_orchestrator.py infrastructure/workflow_run_repository.py
git commit -m "feat: janitor and Brain skip AWAITING_APPROVAL runs"
```

---

## Task 4: complete_gate_node Repository Method

**Files:**
- Modify: `infrastructure/workflow_run_repository.py`

- [ ] **Step 1: Add complete_gate_node method**

Add to `WorkflowRunRepository`:

```python
def complete_gate_node(
    self,
    run_id: str,
    gate_node_name: str,
    result_data: dict,
) -> bool:
    """
    Complete a gate node from external signal (e.g., approval API).

    Transitions the gate task from WAITING → COMPLETED and the
    workflow run from AWAITING_APPROVAL → RUNNING so the Brain
    resumes processing downstream nodes.

    Args:
        run_id: Workflow run ID
        gate_node_name: Name of the gate node (e.g., "approval_gate")
        result_data: Result dict to store on the task (e.g., {"decision": "approved", "clearance_state": "ouo"})

    Returns:
        True if gate was completed, False if not found or wrong state
    """
    query = sql.SQL(
        "UPDATE {schema}.workflow_tasks "
        "SET status = %s, "
        "    result_data = %s, "
        "    completed_at = NOW(), "
        "    updated_at = NOW() "
        "WHERE run_id = %s "
        "  AND task_name = %s "
        "  AND status = %s "
    ).format(schema=sql.Identifier("app"))

    try:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    WorkflowTaskStatus.COMPLETED.value,
                    result_data,
                    run_id,
                    gate_node_name,
                    WorkflowTaskStatus.WAITING.value,
                ))
                task_updated = cur.rowcount == 1

            if task_updated:
                # Resume the workflow run
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            "UPDATE {schema}.workflow_runs "
                            "SET status = %s, updated_at = NOW() "
                            "WHERE run_id = %s AND status = %s"
                        ).format(schema=sql.Identifier("app")),
                        (
                            WorkflowRunStatus.RUNNING.value,
                            run_id,
                            WorkflowRunStatus.AWAITING_APPROVAL.value,
                        ),
                    )
                conn.commit()

            logger.info(
                "complete_gate_node: run=%s gate=%s updated=%s",
                run_id, gate_node_name, task_updated,
            )
            return task_updated

    except psycopg.Error as exc:
        logger.error("DB error in complete_gate_node: run=%s error=%s", run_id, exc)
        raise DatabaseError(f"Failed to complete gate node: {exc}") from exc
```

- [ ] **Step 2: Add skip_gate_node method (for rejection)**

```python
def skip_gate_node(
    self,
    run_id: str,
    gate_node_name: str,
    result_data: dict,
) -> bool:
    """
    Skip a gate node (rejection path). Downstream nodes will be
    skip-propagated by the transition engine on next poll.

    Transitions gate: WAITING → SKIPPED, run: AWAITING_APPROVAL → RUNNING.
    """
    query = sql.SQL(
        "UPDATE {schema}.workflow_tasks "
        "SET status = %s, "
        "    result_data = %s, "
        "    completed_at = NOW(), "
        "    updated_at = NOW() "
        "WHERE run_id = %s "
        "  AND task_name = %s "
        "  AND status = %s "
    ).format(schema=sql.Identifier("app"))

    try:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (
                    WorkflowTaskStatus.SKIPPED.value,
                    result_data,
                    run_id,
                    gate_node_name,
                    WorkflowTaskStatus.WAITING.value,
                ))
                task_updated = cur.rowcount == 1

            if task_updated:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            "UPDATE {schema}.workflow_runs "
                            "SET status = %s, updated_at = NOW() "
                            "WHERE run_id = %s AND status = %s"
                        ).format(schema=sql.Identifier("app")),
                        (
                            WorkflowRunStatus.RUNNING.value,
                            run_id,
                            WorkflowRunStatus.AWAITING_APPROVAL.value,
                        ),
                    )
                conn.commit()

            return task_updated

    except psycopg.Error as exc:
        logger.error("DB error in skip_gate_node: run=%s error=%s", run_id, exc)
        raise DatabaseError(f"Failed to skip gate node: {exc}") from exc
```

- [ ] **Step 3: Commit**

```bash
git add infrastructure/workflow_run_repository.py
git commit -m "feat: complete_gate_node + skip_gate_node repository methods"
```

---

## Task 5: Approval Relaxation — Remove Ordinal Guards

**Files:**
- Modify: `services/asset_approval_service.py:166-188`

- [ ] **Step 1: Remove SG5-1 stale ordinal guard**

In `services/asset_approval_service.py`, find the SG5-1 guard block (lines 166-188). This is the block that calls `release_repo.has_newer_active_ordinal()` and blocks approval if a newer ordinal exists.

**Delete the entire block** (lines 166-188). Replace with a comment:

```python
# SG5-1 stale ordinal guard REMOVED (27 MAR 2026).
# Design decision: any ordinal can be approved independently.
# Ordinal ordering is informational, not a constraint.
# "Latest" = MAX(version_ordinal) WHERE approved (hard rule in get_latest).
```

- [ ] **Step 2: Decouple version_id auto-generation from ordinal**

In `triggers/assets/asset_approvals_bp.py` (the approve endpoint), find where version_id is auto-generated from ordinal (around lines 196-200). The current logic is:

```python
if not version_id and release.version_ordinal:
    version_id = f"v{release.version_ordinal}"
elif not version_id:
    version_id = "v1"
```

Change to make the auto-generation a **suggestion** that can be overridden:

```python
if not version_id:
    # Auto-suggest from ordinal, but client can override
    version_id = f"v{release.version_ordinal}" if release.version_ordinal else "v1"
```

This is functionally identical for now but the comment clarifies intent. The real decoupling happens when the UI sends explicit version_id values.

- [ ] **Step 3: Commit**

```bash
git add services/asset_approval_service.py triggers/assets/asset_approvals_bp.py
git commit -m "feat: remove SG5-1 ordinal guard — any ordinal can be approved independently"
```

---

## Task 6: Wire Approval Service to Gate Node

**Files:**
- Modify: `services/asset_approval_service.py`

- [ ] **Step 1: Add gate node completion to approve_release()**

In `services/asset_approval_service.py`, in the `approve_release()` method, AFTER the atomic approval succeeds (around line 206) and BEFORE STAC materialization (line 262), add:

```python
# Complete the gate node if this release has an active DAG workflow
if release.workflow_id:
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        wf_repo = WorkflowRunRepository()
        gate_completed = wf_repo.complete_gate_node(
            run_id=release.workflow_id,
            gate_node_name="approval_gate",
            result_data={
                "decision": "approved",
                "clearance_state": clearance_state.value,
                "reviewer": reviewer,
                "version_id": version_id,
            },
        )
        if gate_completed:
            logger.info(
                "Gate node completed for workflow %s (release %s approved)",
                release.workflow_id, release_id,
            )
    except Exception as gate_err:
        # Gate completion failure is non-fatal for approval
        # The approval is already committed — DAG will resume on next poll
        logger.warning(
            "Failed to complete gate node for workflow %s: %s (non-fatal)",
            release.workflow_id, gate_err,
        )
```

- [ ] **Step 2: Add gate node skip to reject_release()**

In `reject_release()` method, after the rejection is committed, add:

```python
# Skip the gate node if this release has an active DAG workflow
if release.workflow_id:
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        wf_repo = WorkflowRunRepository()
        wf_repo.skip_gate_node(
            run_id=release.workflow_id,
            gate_node_name="approval_gate",
            result_data={
                "decision": "rejected",
                "reviewer": reviewer,
                "reason": reason,
            },
        )
        logger.info(
            "Gate node skipped for workflow %s (release %s rejected)",
            release.workflow_id, release_id,
        )
    except Exception as gate_err:
        logger.warning(
            "Failed to skip gate node for workflow %s: %s (non-fatal)",
            release.workflow_id, gate_err,
        )
```

- [ ] **Step 3: Commit**

```bash
git add services/asset_approval_service.py
git commit -m "feat: approval service completes/skips gate node on approve/reject"
```

---

## Task 7: Add Gate Nodes to Workflow YAMLs

**Files:**
- Modify: `workflows/process_raster.yaml`
- Modify: `workflows/vector_docker_etl.yaml`

- [ ] **Step 1: Add approval_gate to process_raster.yaml**

Insert after `persist_single` and `persist_tiled` nodes, before `materialize_single_item`:

```yaml
  # -- APPROVAL GATE (workflow suspends here) --
  approval_gate:
    type: gate
    gate_type: approval
    depends_on:
      - "persist_single?"
      - "persist_tiled?"
```

Update `materialize_single_item` to depend on approval_gate instead of persist_single:

```yaml
  materialize_single_item:
    type: task
    handler: stac_materialize_item
    depends_on: [approval_gate]
    params: [collection_id]
    receives:
      cog_id: "upload_single_cog.result.stac_item_id"
      blob_path: "upload_single_cog.result.silver_blob_path"
```

Update `materialize_collection` dependencies:

```yaml
  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on:
      - "materialize_single_item?"
      - "persist_tiled?"
    params: [collection_id]
```

Note: `persist_tiled?` stays as a dependency on materialize_collection because the tiled path also needs to pass through the gate. The gate depends on both `persist_single?` and `persist_tiled?` (optional), so whichever path fires will complete the gate's prerequisites.

- [ ] **Step 2: Add approval_gate to vector_docker_etl.yaml**

Insert after `register_catalog` and before `refresh_tipg`:

```yaml
  # -- APPROVAL GATE (workflow suspends here) --
  approval_gate:
    type: gate
    gate_type: approval
    depends_on:
      - register_catalog

  refresh_tipg:
    type: task
    handler: vector_refresh_tipg
    depends_on: [approval_gate]
    params: [table_name, schema_name]
```

- [ ] **Step 3: Commit**

```bash
git add workflows/process_raster.yaml workflows/vector_docker_etl.yaml
git commit -m "feat: add approval_gate node to raster and vector workflows"
```

---

## Task 8: Wire DAG Handlers to Release Entity

**Files:**
- Modify: `triggers/platform/submit.py` (DAG path)
- Modify: `services/raster/handler_persist_app_tables.py`
- Modify: `services/vector/handler_register_catalog.py`

- [ ] **Step 1: Pass release_id and asset_id through DAG workflow parameters**

In `triggers/platform/submit.py`, the DAG routing path (around line 427-453) calls `translate_for_dag()` and `create_and_submit_dag_run()`. The release_id and asset_id must be injected into the workflow parameters so handlers can update the release:

Find where DAG parameters are assembled and add:

```python
dag_params["_release_id"] = release.release_id
dag_params["_asset_id"] = asset.asset_id
```

These use the underscore prefix convention (like `_run_id`, `_job_id`) for system-injected parameters.

- [ ] **Step 2: Update raster persist handler to write physical outputs to release**

In `services/raster/handler_persist_app_tables.py`, after the cog_metadata upsert succeeds, add release update:

```python
# Update release physical outputs (if release_id present)
release_id = params.get('_release_id')
if release_id:
    try:
        from infrastructure.release_repository import ReleaseRepository
        release_repo = ReleaseRepository()
        release_repo.update_physical_outputs(
            release_id=release_id,
            blob_path=cog_url,
            stac_item_id=cog_id,
            stac_collection_id=params.get('collection_id'),
            output_mode="single",
            content_hash=None,  # Future: compute from COG
        )
        release_repo.update_stac_item_json(release_id, stac_item)
        release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        logger.info("Updated release %s with physical outputs", release_id)
    except Exception as rel_err:
        logger.warning("Failed to update release %s: %s (non-fatal)", release_id, rel_err)
```

- [ ] **Step 3: Update vector register_catalog handler to write physical outputs to release**

In `services/vector/handler_register_catalog.py`, after the catalog registration loop, add release update:

```python
# Update release physical outputs (if release_id present)
release_id = params.get('_release_id')
if release_id:
    try:
        from infrastructure.release_repository import ReleaseRepository
        from infrastructure.release_table_repository import ReleaseTableRepository
        from core.models.asset import ProcessingStatus
        from datetime import datetime, timezone

        release_repo = ReleaseRepository()
        release_table_repo = ReleaseTableRepository()

        # Write release_tables junction entries
        for entry in registered:
            release_table_repo.create(
                release_id=release_id,
                table_name=entry["table_name"],
                geometry_type=entry["geometry_type"],
                feature_count=entry["feature_count"],
                table_role="primary" if len(registered) == 1 else "geometry_split",
            )

        release_repo.update_processing_status(
            release_id,
            ProcessingStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        logger.info("Updated release %s with %d table entries", release_id, len(registered))
    except Exception as rel_err:
        logger.warning("Failed to update release %s: %s (non-fatal)", release_id, rel_err)
```

- [ ] **Step 4: Wire workflow_id on release for gate node lookup**

In `triggers/platform/submit.py`, after `create_and_submit_dag_run()` returns the run_id, update the release with the workflow_id:

```python
# Link DAG run to release (for gate node lookup at approval time)
release_repo = ReleaseRepository()
release_repo.update_workflow_id(release.release_id, dag_run_id)
```

The `update_workflow_id` method sets `workflow_id` on the release so `approve_release()` can find the run_id to call `complete_gate_node()`.

If `update_workflow_id` doesn't exist yet, add it to ReleaseRepository:

```python
def update_workflow_id(self, release_id: str, workflow_id: str) -> bool:
    query = sql.SQL(
        "UPDATE {schema}.{table} SET workflow_id = %s, updated_at = NOW() "
        "WHERE release_id = %s"
    ).format(
        schema=sql.Identifier("app"),
        table=sql.Identifier("asset_releases"),
    )
    try:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (workflow_id, release_id))
                updated = cur.rowcount == 1
            conn.commit()
        return updated
    except psycopg.Error as exc:
        raise DatabaseError(f"Failed to update workflow_id: {exc}") from exc
```

- [ ] **Step 5: Commit**

```bash
git add triggers/platform/submit.py services/raster/handler_persist_app_tables.py services/vector/handler_register_catalog.py infrastructure/release_repository.py
git commit -m "feat: wire DAG handlers to update release entity with physical outputs"
```

---

## Design Notes

### Rejection Path
When a release is rejected, the gate node is SKIPPED. The transition engine's existing skip-propagation logic will cascade SKIPPED to all downstream nodes (materialize_single_item, materialize_collection, refresh_tipg). The workflow run transitions AWAITING_APPROVAL → RUNNING → COMPLETED (all remaining nodes are terminal). Data stays in silver — no deletion.

### Overwrite Path
`platform/submit?overwrite=true` on a REVOKED asset:
1. Creates a new release (revision incremented)
2. Starts a completely new DAG workflow run
3. The old workflow run is already in COMPLETED state (rejected or revoked terminal)
4. New run goes through the same gate → approval cycle

### Externalization (Future Task)
When `clearance_state=PUBLIC` at approval:
1. Gate node completes with `{"clearance_state": "public"}`
2. Post-gate STAC materialization runs
3. A conditional node after STAC checks `approval_gate.result.clearance_state`
4. If "public": routes to an `externalize` handler (ADF pipeline trigger)
5. If "ouo": skips externalization

This is a future YAML change — the gate infrastructure built here supports it. The conditional routing already works (see `route_by_size` in process_raster.yaml).

### Gate Handler Sentinel
Gate nodes use handler `"__gate__"` in the database (set during workflow task creation). This sentinel is:
- Excluded from worker `claim_ready_workflow_task()` queries
- Excluded from janitor stale detection
- Never dispatched to a handler function

The workflow task creation code in `workflow_run_repository.py` (`create_workflow_tasks` or similar) needs to set `handler = '__gate__'` for gate-type nodes, matching the pattern used by `__conditional__`, `__fan_out__`, `__fan_in__`.
