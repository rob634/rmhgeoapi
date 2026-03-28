# Gate Node Database Coordination Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace cross-service API calls for gate node completion with database-as-coordination-layer pattern — the Brain polls the release table and drives gate decisions, the approval service only writes to its own table.

**Architecture:** The approval service stops calling complete_gate_node/skip_gate_node. Instead, the Brain's poll loop checks AWAITING_APPROVAL runs against the linked release's approval_state and acts accordingly. The database is the message bus. The Brain is the sole workflow state manager.

**Tech Stack:** Python 3.12, psycopg3, PostgreSQL

---

## File Structure

### Modified Files
| File | Changes |
|------|---------|
| `services/asset_approval_service.py` | Remove gate completion/skip calls, skip inline STAC for DAG releases |
| `core/dag_orchestrator.py` | Add gate reconciliation to poll loop for AWAITING_APPROVAL runs |
| `infrastructure/workflow_run_repository.py` | Add get_release_for_run() lookup method |

---

## Task 1: Remove Gate Calls from Approval Service

**Files:**
- Modify: `services/asset_approval_service.py`

- [ ] **Step 1: Remove gate completion from approve_release()**

In `approve_release()`, find the block that calls `complete_gate_node()` (added in a recent commit). It looks like:

```python
        # Complete the gate node if this release has an active DAG workflow
        if release.workflow_id:
            try:
                from infrastructure.workflow_run_repository import WorkflowRunRepository
                wf_repo = WorkflowRunRepository()
                gate_completed = wf_repo.complete_gate_node(
                    ...
                )
                ...
            except Exception as gate_err:
                ...
```

**Delete the entire block.** Replace with a comment:

```python
        # Gate node completion handled by Brain poll loop (database coordination).
        # The Brain reads approval_state from this release and completes/skips
        # the gate node on its next poll cycle (~5s). No cross-service call needed.
```

- [ ] **Step 2: Remove gate skip from reject_release()**

In `reject_release()`, find the block that calls `skip_gate_node()`. It looks like:

```python
        # Skip the gate node if this release has an active DAG workflow
        if release.workflow_id:
            try:
                from infrastructure.workflow_run_repository import WorkflowRunRepository
                wf_repo = WorkflowRunRepository()
                wf_repo.skip_gate_node(
                    ...
                )
                ...
            except Exception as gate_err:
                ...
```

**Delete the entire block.** Replace with the same comment:

```python
        # Gate node skip handled by Brain poll loop (database coordination).
        # The Brain reads approval_state from this release and skips
        # the gate node on its next poll cycle (~5s). No cross-service call needed.
```

- [ ] **Step 3: Skip inline STAC materialization for DAG releases**

In `approve_release()`, find where `_materialize_stac()` is called (around line 322 in the method, inside the STAC materialization section). There should be an existing guard that skips STAC for vector data. Add a DAG guard before it:

```python
        # Skip inline STAC materialization for DAG-routed releases.
        # The DAG workflow handles STAC materialization post-gate via
        # materialize_single_item and materialize_collection nodes.
        if release.workflow_id:
            logger.info(
                "Skipping inline STAC materialization for DAG release %s "
                "(handled by post-gate workflow nodes)", release_id,
            )
            stac_updated = False
        elif ...:  # existing vector skip guard
```

Make sure the existing STAC rollback logic is also skipped for DAG releases (no STAC to roll back if we didn't materialize inline).

- [ ] **Step 4: Commit**

```bash
git add services/asset_approval_service.py
git commit -m "refactor: remove cross-service gate calls from approval service

Approval service no longer calls complete_gate_node/skip_gate_node.
Brain poll loop handles gate reconciliation via database coordination.
Inline STAC materialization skipped for DAG releases (workflow handles it).
Principle: database is the coordination layer, no cross-service API calls.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add Release Lookup to Repository

**Files:**
- Modify: `infrastructure/workflow_run_repository.py`

- [ ] **Step 1: Add get_release_for_waiting_run() method**

The Brain needs to look up the linked release for an AWAITING_APPROVAL run. The link is: workflow_runs.run_id is stored in asset_releases.workflow_id.

Add a method to WorkflowRunRepository:

```python
def get_release_for_waiting_run(self, run_id: str) -> Optional[dict]:
    """
    Look up the asset_release linked to a workflow run via workflow_id.

    Used by the Brain's gate reconciliation loop to check approval_state
    on releases linked to AWAITING_APPROVAL runs.

    Returns:
        Dict with release_id, approval_state, clearance_state, workflow_id
        or None if no release is linked to this run.
    """
    query = sql.SQL(
        "SELECT release_id, approval_state, clearance_state, "
        "       processing_status, workflow_id, reviewer, version_id "
        "FROM {schema}.{table} "
        "WHERE workflow_id = %s"
    ).format(
        schema=sql.Identifier("app"),
        table=sql.Identifier("asset_releases"),
    )

    try:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (run_id,))
                row = cur.fetchone()

        if row is None:
            return None
        return dict(row)

    except psycopg.Error as exc:
        logger.error(
            "DB error in get_release_for_waiting_run: run_id=%s error=%s",
            run_id, exc,
        )
        raise DatabaseError(
            f"Failed to look up release for run {run_id}: {exc}"
        ) from exc
```

- [ ] **Step 2: Commit**

```bash
git add infrastructure/workflow_run_repository.py
git commit -m "feat: add get_release_for_waiting_run() lookup method

Brain uses this to check approval_state for AWAITING_APPROVAL runs.
Queries asset_releases WHERE workflow_id = run_id.
Returns approval_state, clearance_state, etc. for gate reconciliation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add Gate Reconciliation to Brain Poll Loop

**Files:**
- Modify: `core/dag_orchestrator.py`

- [ ] **Step 1: Change AWAITING_APPROVAL handling from skip to reconcile**

In `core/dag_orchestrator.py`, find the early return for AWAITING_APPROVAL runs (added in a prior task). It currently looks like:

```python
            if run.status == WorkflowRunStatus.AWAITING_APPROVAL:
                result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                logger.info(
                    "DAGOrchestrator.run: run_id=%s already AWAITING_APPROVAL — skipping",
                    run_id,
                )
                return result
```

**Replace** this with gate reconciliation logic:

```python
            if run.status == WorkflowRunStatus.AWAITING_APPROVAL:
                # Gate reconciliation: check linked release's approval_state
                release = self._repo.get_release_for_waiting_run(run_id)

                if release is None:
                    # No linked release — cannot reconcile, skip this cycle
                    logger.warning(
                        "DAGOrchestrator.run: run_id=%s AWAITING_APPROVAL but no linked release found",
                        run_id,
                    )
                    result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                    return result

                approval_state = release.get("approval_state")

                if approval_state == "approved":
                    # Human approved — complete the gate node, resume workflow
                    gate_completed = self._repo.complete_gate_node(
                        run_id=run_id,
                        gate_node_name="approval_gate",
                        result_data={
                            "decision": "approved",
                            "clearance_state": release.get("clearance_state"),
                            "reviewer": release.get("reviewer"),
                            "version_id": release.get("version_id"),
                        },
                    )
                    if gate_completed:
                        logger.info(
                            "Gate reconciliation: run_id=%s approved — gate completed, resuming workflow",
                            run_id,
                        )
                        # Don't return — fall through to normal processing
                        # The run is now RUNNING, transition engine will promote downstream nodes
                    else:
                        logger.warning(
                            "Gate reconciliation: run_id=%s approved but gate completion failed "
                            "(gate may already be completed)", run_id,
                        )
                        result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                        return result

                elif approval_state == "rejected":
                    # Human rejected — skip the gate node, workflow completes without post-gate steps
                    self._repo.skip_gate_node(
                        run_id=run_id,
                        gate_node_name="approval_gate",
                        result_data={
                            "decision": "rejected",
                            "reviewer": release.get("reviewer"),
                        },
                    )
                    logger.info(
                        "Gate reconciliation: run_id=%s rejected — gate skipped, downstream will cascade-skip",
                        run_id,
                    )
                    # Don't return — fall through so transition engine propagates skips

                elif approval_state == "revoked":
                    # Human revoked after approval — fail the workflow run
                    self._repo.update_run_status(run_id, WorkflowRunStatus.FAILED)
                    logger.warning(
                        "Gate reconciliation: run_id=%s revoked — workflow run failed",
                        run_id,
                    )
                    result.final_status = WorkflowRunStatus.FAILED
                    return result

                else:
                    # Still pending_review — do nothing, check again next poll
                    logger.debug(
                        "Gate reconciliation: run_id=%s still pending_review — waiting",
                        run_id,
                    )
                    result.final_status = WorkflowRunStatus.AWAITING_APPROVAL
                    return result
```

**IMPORTANT:** After the "approved" and "rejected" branches, the code falls through (no return) so the normal orchestrator processing continues — the transition engine promotes downstream nodes or propagates skips. After "revoked" and "pending_review", it returns early.

- [ ] **Step 2: Update the run status reload after gate reconciliation**

After the gate reconciliation block, the orchestrator needs to reload the run status because complete_gate_node changed it from AWAITING_APPROVAL to RUNNING. The existing code that checks `run.status == WorkflowRunStatus.PENDING` and transitions to RUNNING may need adjustment.

Find where the run status is checked after the AWAITING_APPROVAL block. The run object may be stale. Either:
- Reload the run: `run = self._repo.get_run(run_id)`
- Or proceed knowing the status was just changed to RUNNING by complete_gate_node

The safest approach is to reload the run after gate reconciliation so the existing status checks work correctly.

- [ ] **Step 3: Commit**

```bash
git add core/dag_orchestrator.py
git commit -m "feat: Brain gate reconciliation via database polling

Brain polls asset_releases for AWAITING_APPROVAL runs:
- approved → complete_gate_node → resume workflow
- rejected → skip_gate_node → cascade-skip downstream
- revoked → fail workflow run
- pending_review → do nothing, check next poll
Database is the coordination layer. No cross-service API calls.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Design Notes

### Why Database Coordination

The approval service and DAG engine both have access to the same PostgreSQL database. Rather than the approval service making API calls to the DAG engine (which creates failure modes H2, H3, H4 from COMPETE review), we let:

- **Approval service** write to `app.asset_releases` (its own domain)
- **Brain** read from `app.asset_releases` and act on `app.workflow_tasks`/`app.workflow_runs` (its own domain)

The database is the message bus. Each service owns its writes. The Brain's 5-second poll cycle is the consistency boundary — approval decisions take effect within 5 seconds.

### Revoke During Running Workflow

If a release is approved, the gate completes, and STAC materialization starts running in the DAG — then the release is revoked — the Brain's next poll will see `approval_state=revoked` and fail the run. Any in-flight STAC writes may complete, but the revoke_release() service already handles STAC cleanup (deletes items from pgSTAC). The DAG's STAC writes are idempotent upserts, so a revoke delete + a late DAG upsert creates a race, but the revoke service re-checks and re-deletes as needed.

### complete_gate_node and skip_gate_node Methods

These repository methods are NOT removed — they're still the mechanism the Brain uses to transition gate tasks. They just aren't called by the approval service anymore. The Brain calls them during gate reconciliation.
