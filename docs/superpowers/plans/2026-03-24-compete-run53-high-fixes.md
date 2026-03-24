# COMPETE Run 53 HIGH Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 5 HIGH severity findings from COMPETE Run 53 on the DAG orchestration system.

**Architecture:** These are targeted fixes to existing code — no new modules. H1 changes the locking strategy in the orchestrator. H2/H4 change the poll/scan loops in docker_service.py. H3 adds TypeError guards to branch condition evaluation. H5 filters fan-out children from name-based lookups.

**Tech Stack:** Python 3.12, psycopg 3, PostgreSQL advisory locks, threading

---

## File Map

| File | Changes | Tasks |
|------|---------|-------|
| `core/dag_orchestrator.py` | Replace session-level advisory lock with transaction-level lock inside pooled connection | H1 |
| `docker_service.py` | Alternating dual-poll priority; fast-rescan in primary loop | H2, H4 |
| `core/dag_fan_engine.py` | TypeError guards on `in`/`not_in`/`contains`/`not_contains` operators | H3 |
| `core/dag_graph_utils.py` | Filter fan-out children from `build_adjacency` | H5 |
| `core/dag_transition_engine.py` | Filter fan-out children from `task_by_name` | H5 |
| `core/dag_fan_engine.py` | Filter fan-out children from `task_by_name` | H5 |
| `tests/unit/test_dag_orchestrator_lock.py` | New — tests for transaction-level lock | H1 |
| `tests/unit/test_branch_condition.py` | New — tests for operator edge cases | H3 |
| `tests/unit/test_graph_utils_fanout.py` | New — tests for fan-out child filtering | H5 |

---

### Task 1: H3 — TypeError guards on branch condition operators

**Why first:** Smallest, most isolated fix. Pure function with no dependencies.

**Files:**
- Modify: `core/dag_fan_engine.py:188-195`
- Create: `tests/unit/test_branch_condition.py`

- [ ] **Step 1: Write failing tests for operator crashes**

```python
# tests/unit/test_branch_condition.py
"""Tests for _eval_branch_condition edge cases — COMPETE Run 53 H3/L2."""
import pytest
from core.dag_fan_engine import _eval_branch_condition


class TestBranchConditionTypeErrors:
    """H3: in/not_in/contains/not_contains crash on non-iterable values."""

    def test_in_with_int_operand(self):
        """'in' operator with non-iterable operand should return False, not crash."""
        assert _eval_branch_condition(42, "in 99") is False

    def test_not_in_with_int_operand(self):
        assert _eval_branch_condition(42, "not_in 99") is False

    def test_contains_with_int_value(self):
        """'contains' operator with non-iterable value should return False."""
        assert _eval_branch_condition(42, "contains 4") is False

    def test_not_contains_with_int_value(self):
        assert _eval_branch_condition(42, "not_contains 4") is False

    def test_contains_with_none_value(self):
        assert _eval_branch_condition(None, "contains foo") is False

    def test_in_with_none_operand(self):
        assert _eval_branch_condition("foo", "in None") is False

    def test_in_with_list_operand_works(self):
        """Normal case: 'in' with list should still work."""
        assert _eval_branch_condition("a", 'in ["a", "b"]') is True

    def test_contains_with_string_value_works(self):
        """Normal case: 'contains' with string should still work."""
        assert _eval_branch_condition("hello world", "contains hello") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/test_branch_condition.py -v`
Expected: TypeError crashes on the non-iterable tests

- [ ] **Step 3: Add TypeError guards to all four operators**

In `core/dag_fan_engine.py`, replace lines 188-195:

```python
    if operator == "in":
        return value in operand
    if operator == "not_in":
        return value not in operand
    if operator == "contains":
        return operand in value
    if operator == "not_contains":
        return operand not in value
```

With:

```python
    if operator in ("in", "not_in", "contains", "not_contains"):
        try:
            if operator == "in":
                return value in operand
            if operator == "not_in":
                return value not in operand
            if operator == "contains":
                return operand in value
            return operand not in value  # not_contains
        except TypeError:
            logger.warning(
                "_eval_branch_condition: type mismatch for '%s': value=%r (%s) operand=%r (%s)",
                operator, value, type(value).__name__, operand, type(operand).__name__,
            )
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/test_branch_condition.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add core/dag_fan_engine.py tests/unit/test_branch_condition.py
git commit -m "fix: TypeError guard on in/not_in/contains/not_contains branch operators (COMPETE H3)"
```

---

### Task 2: H5 — Filter fan-out children from name-based lookups

**Why second:** Pure logic fix, no infrastructure changes.

**Context:** Fan-out children share `task_name` with their template. When `task_by_name` is built as `{t.task_name: t for t in tasks}`, the last child wins, corrupting lookups. Fan-out children always have `fan_out_source is not None`. The orchestrator already filters them from `predecessor_outputs` — the same filter must apply to `task_by_name` and `build_adjacency`.

**Files:**
- Modify: `core/dag_transition_engine.py:345`
- Modify: `core/dag_fan_engine.py:259`
- Modify: `core/dag_graph_utils.py:108-131`
- Create: `tests/unit/test_graph_utils_fanout.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_graph_utils_fanout.py
"""Tests for fan-out child filtering in graph utilities — COMPETE Run 53 H5."""
from core.dag_graph_utils import build_adjacency, TaskSummary
from core.models.workflow_enums import WorkflowTaskStatus


def _ts(iid, name, status=WorkflowTaskStatus.PENDING, fan_out_source=None):
    """Helper to build TaskSummary."""
    return TaskSummary(
        task_instance_id=iid,
        task_name=name,
        status=status,
        handler="test_handler",
        fan_out_source=fan_out_source,
        fan_out_index=None,
        result_data=None,
    )


class TestBuildAdjacencyFanOutFiltering:
    def test_fan_out_children_do_not_corrupt_adjacency(self):
        """Fan-out children share task_name with template.
        build_adjacency must not let children overwrite template in name-based structures."""
        template = _ts("tmpl-1", "process_tiles", WorkflowTaskStatus.EXPANDED)
        child_0 = _ts("child-0", "process_tiles", WorkflowTaskStatus.COMPLETED, fan_out_source="tmpl-1")
        child_1 = _ts("child-1", "process_tiles", WorkflowTaskStatus.COMPLETED, fan_out_source="tmpl-1")
        downstream = _ts("aggregate", "merge_results", WorkflowTaskStatus.PENDING)

        tasks = [template, child_0, child_1, downstream]
        # downstream depends on template (not children directly — fan-in handles children)
        deps = [("aggregate", "tmpl-1")]

        adjacency = build_adjacency(tasks, deps)

        # "merge_results" should depend on "process_tiles" (the template name)
        assert "process_tiles" in adjacency["merge_results"]
        # Template should appear as a key (not overwritten by children)
        assert "process_tiles" in adjacency
```

- [ ] **Step 2: Run test to verify it fails or shows the corruption**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/test_graph_utils_fanout.py -v`

- [ ] **Step 3: Filter fan-out children in build_adjacency**

In `core/dag_graph_utils.py`, modify `build_adjacency` (lines 107-131). Add a filter at the top of the function:

```python
    # Filter out fan-out children — they share task_name with their template
    # and corrupt name-based lookups. Fan-in handles children directly via
    # fan_out_source, not through the adjacency graph.
    template_tasks = [t for t in tasks if t.fan_out_source is None]

    # Build lookup: instance_id -> task_name (need ALL tasks for dep resolution)
    instance_id_to_name: dict[str, str] = {
        t.task_instance_id: t.task_name for t in tasks
    }

    # Seed adjacency with template tasks only
    adjacency: dict[str, set[str]] = {t.task_name: set() for t in template_tasks}
```

The dep loop stays the same but add a guard for children's deps:

```python
    for (task_iid, dep_iid) in deps:
        if task_iid not in instance_id_to_name:
            raise ContractViolationError(...)
        if dep_iid not in instance_id_to_name:
            raise ContractViolationError(...)

        task_name = instance_id_to_name[task_iid]
        upstream_name = instance_id_to_name[dep_iid]
        # Skip deps involving fan-out children — their deps are internal
        if task_name in adjacency:
            adjacency[task_name].add(upstream_name)

    return adjacency
```

- [ ] **Step 4: Filter fan-out children in task_by_name (transition engine)**

In `core/dag_transition_engine.py` line 345, change:

```python
    task_by_name: dict[str, TaskSummary] = {t.task_name: t for t in tasks}
```

To:

```python
    task_by_name: dict[str, TaskSummary] = {
        t.task_name: t for t in tasks if t.fan_out_source is None
    }
```

- [ ] **Step 5: Filter fan-out children in task_by_name (fan engine)**

In `core/dag_fan_engine.py` line 259, change:

```python
    task_by_name: dict[str, TaskSummary] = {t.task_name: t for t in tasks}
```

To:

```python
    task_by_name: dict[str, TaskSummary] = {
        t.task_name: t for t in tasks if t.fan_out_source is None
    }
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/test_graph_utils_fanout.py tests/unit/test_dag_initializer.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add core/dag_graph_utils.py core/dag_transition_engine.py core/dag_fan_engine.py tests/unit/test_graph_utils_fanout.py
git commit -m "fix: filter fan-out children from task_by_name and adjacency maps (COMPETE H5)"
```

---

### Task 3: H2 — Alternating dual-poll priority

**Why third:** Simple logic change, no new dependencies.

**Context:** `_run_loop` in `docker_service.py` always tries legacy tasks first (line 686), then DAG tasks (line 701). A steady stream of legacy tasks starves DAG completely. Fix: alternate which is tried first on each poll cycle.

**Files:**
- Modify: `docker_service.py:675-712`

- [ ] **Step 1: Add alternating poll order**

Replace the poll section in `_run_loop` (lines 683-712):

```python
        _poll_dag_first = False  # Alternate poll order to prevent starvation

        while not self._stop_event.is_set():
            try:
                # Alternate poll order each iteration to prevent starvation (COMPETE H2)
                _poll_dag_first = not _poll_dag_first

                if _poll_dag_first:
                    claimed = self._try_claim_and_process_dag() or self._try_claim_and_process_legacy()
                else:
                    claimed = self._try_claim_and_process_legacy() or self._try_claim_and_process_dag()

                self._last_poll_time = datetime.now(timezone.utc)
                self._last_error = None

                if claimed:
                    continue

                # Nothing in either table — wait
                self._stop_event.wait(self.poll_interval_seconds)

            except Exception as e:
                self._last_error = str(e)
                logger.warning(f"[Queue Worker] Poll error: {e}")
                self._stop_event.wait(self.poll_interval_on_error)

        self._is_running = False
        logger.info("[Queue Worker] Stopped")
```

- [ ] **Step 2: Extract claim-and-process helpers**

Add two private methods above `_run_loop`:

```python
    def _try_claim_and_process_legacy(self) -> bool:
        """Claim and process one legacy task. Returns True if work was done."""
        task_record = self._claim_next_task()
        if task_record is None:
            return False

        if self._stop_event.is_set():
            self._release_task(task_record.task_id)
            return False

        task_message = TaskQueueMessage.from_task_record(task_record)
        self._process_task(task_message)
        return True

    def _try_claim_and_process_dag(self) -> bool:
        """Claim and process one DAG workflow task. Returns True if work was done."""
        workflow_task = self._claim_next_workflow_task()
        if workflow_task is None:
            return False

        if self._stop_event.is_set():
            self._release_workflow_task(workflow_task.task_instance_id)
            return False

        self._process_workflow_task(workflow_task)
        return True
```

- [ ] **Step 3: Verify syntax**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -c "import ast; ast.parse(open('docker_service.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add docker_service.py
git commit -m "fix: alternate legacy/DAG poll priority to prevent starvation (COMPETE H2)"
```

---

### Task 4: H4 — Fast rescan when work was done

**Context:** With `max_cycles=1` and `scan_interval=5.0`, each sequential node adds 5s of latency. Fix: if any orchestrator cycle promoted/skipped/failed tasks (i.e., made progress), skip the sleep and immediately rescan. Only sleep when no run needed work.

**Files:**
- Modify: `docker_service.py:DAGBrainPrimaryLoop._loop` (around lines 1025-1070)

- [ ] **Step 1: Add progress tracking and fast rescan**

In `DAGBrainPrimaryLoop._loop`, modify the scan loop to track whether any work was done:

```python
        while not self._stop_event.is_set():
            try:
                active_run_ids = self._repo.list_active_runs()
                self._total_scans += 1
                self._last_scan_at = datetime.now(timezone.utc)
                made_progress = False

                if active_run_ids:
                    logger.info(
                        "DAG Brain scan %d: %d active run(s)",
                        self._total_scans, len(active_run_ids),
                    )

                for run_id in active_run_ids:
                    if self._stop_event.is_set():
                        break

                    # Per-run isolation: one run's error must not skip others
                    try:
                        orchestrator = DAGOrchestrator(self._repo)
                        result = orchestrator.run(
                            run_id,
                            max_cycles=1,
                            cycle_interval=0.0,
                            shutdown_event=self._stop_event,
                        )
                        self._total_cycles += 1

                        # Track if this cycle did useful work
                        if result.tasks_promoted > 0 or result.tasks_skipped > 0 or result.tasks_failed > 0:
                            made_progress = True

                        if result.error and result.error != "lock_held":
                            logger.warning(
                                "DAG Brain: run_id=%s cycle result: status=%s error=%s",
                                run_id[:16], result.final_status.value, result.error,
                            )
                    except Exception as run_exc:
                        logger.error(
                            "DAG Brain: run_id=%s orchestration error: %s",
                            run_id[:16], run_exc, exc_info=True,
                        )

            except Exception as exc:
                logger.error("DAG Brain primary loop scan error: %s", exc, exc_info=True)

            # Fast rescan: if any run made progress, skip sleep — there may be
            # more nodes ready to promote immediately (sequential chains).
            if made_progress:
                continue

            self._stop_event.wait(timeout=self._scan_interval)
```

- [ ] **Step 2: Verify syntax**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -c "import ast; ast.parse(open('docker_service.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add docker_service.py
git commit -m "fix: fast rescan when orchestrator makes progress — eliminates 5s latency per sequential node (COMPETE H4)"
```

---

### Task 5: H1 — Replace session-level advisory locks with transaction-level

**Why last:** Most complex change — touches the lock/connection lifecycle in the orchestrator.

**Context:** `DAGOrchestrator.run()` currently opens a dedicated non-pooled TCP connection (`_open_lock_connection()`) for a session-level advisory lock, holds it for one dispatch cycle (`max_cycles=1`), then closes. This churn creates 10+ TCP connections per scan. Since we only need the lock for one cycle, a transaction-level advisory lock (`pg_try_advisory_xact_lock`) within a pooled connection works — the lock auto-releases when the transaction commits.

**Files:**
- Modify: `core/dag_orchestrator.py:206-400` (replace lock lifecycle)
- Create: `tests/unit/test_dag_orchestrator_lock.py`

- [ ] **Step 1: Write test for transaction-level lock behavior**

```python
# tests/unit/test_dag_orchestrator_lock.py
"""Tests for advisory lock lifecycle — COMPETE Run 53 H1."""
from core.dag_orchestrator import _advisory_lock_id


class TestAdvisoryLockId:
    def test_deterministic(self):
        """Same run_id always produces same lock_id."""
        assert _advisory_lock_id("abc") == _advisory_lock_id("abc")

    def test_different_for_different_runs(self):
        assert _advisory_lock_id("run-a") != _advisory_lock_id("run-b")

    def test_non_negative(self):
        """Lock ID must be non-negative (PostgreSQL bigint)."""
        lock_id = _advisory_lock_id("test-run-12345")
        assert lock_id >= 0

    def test_fits_63_bits(self):
        lock_id = _advisory_lock_id("test-run-12345")
        assert lock_id <= 0x7FFFFFFFFFFFFFFF
```

- [ ] **Step 2: Run test to verify passing (lock ID logic unchanged)**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/test_dag_orchestrator_lock.py -v`
Expected: PASS

- [ ] **Step 3: Remove `_open_lock_connection` and `_try_acquire_lock` functions**

Delete the `_open_lock_connection()` function (lines 206-256) and `_try_acquire_lock()` function (lines 259-300) from `core/dag_orchestrator.py`.

- [ ] **Step 4: Rewrite `DAGOrchestrator.run()` lock lifecycle**

Replace the lock acquisition section (Steps 1-2 in `run()`, approximately lines 382-396) and the `finally` block. The new approach:

1. Use the repo's pooled connection to acquire a transaction-level advisory lock
2. Run the dispatch cycle within that transaction
3. Commit (auto-releases the lock)

Replace the entire `run()` method body from the `try:` to the `finally:` with:

```python
        try:
            # ----------------------------------------------------------
            # Step 1: Acquire transaction-level advisory lock via pooled conn
            # ----------------------------------------------------------
            lock_id = _advisory_lock_id(run_id)
            acquired = self._try_acquire_xact_lock(lock_id)

            if not acquired:
                result.error = "lock_held"
                logger.info(
                    "DAGOrchestrator.run: run_id=%s — lock held by another instance, exiting",
                    run_id,
                )
                return result

            # ... steps 2-6 remain identical ...

        finally:
            result.elapsed_seconds = time.monotonic() - t_start
            # Transaction-level lock auto-released on commit/rollback.
            # No dedicated connection to close.
```

Add the new helper method to `DAGOrchestrator`:

```python
    def _try_acquire_xact_lock(self, lock_id: int) -> bool:
        """
        Acquire a transaction-level advisory lock using a pooled connection.

        Uses pg_try_advisory_xact_lock which auto-releases when the
        transaction ends (commit or rollback). No dedicated connection needed.
        """
        try:
            with self._repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_id,))
                    row = cur.fetchone()
                    acquired = row[0]
                conn.commit()

            if acquired:
                logger.info("DAGOrchestrator: advisory xact lock acquired (lock_id=%d)", lock_id)
            else:
                logger.info("DAGOrchestrator: advisory xact lock NOT acquired (lock_id=%d)", lock_id)

            return acquired
        except Exception as exc:
            logger.error("DAGOrchestrator: failed to acquire xact lock: %s", exc)
            return False
```

**Important:** Remove the `lock_conn` variable, the `_open_lock_connection()` call, the lock connection heartbeat check inside the cycle loop (lines 456-464), and the lock connection close in the `finally` block (lines 607-621).

- [ ] **Step 5: Remove lock connection heartbeat check**

Delete the "Verify lock connection is still alive" block from the dispatch cycle (lines 456-464):

```python
                # Verify lock connection is still alive  <-- DELETE THIS BLOCK
                try:
                    with lock_conn.cursor() as hb_cur:
                        hb_cur.execute("SELECT 1")
                except Exception as hb_exc:
                    ...
```

This is no longer needed — there is no dedicated lock connection.

- [ ] **Step 6: Verify syntax**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -c "import ast; ast.parse(open('core/dag_orchestrator.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 7: Run all tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && /Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/test_dag_orchestrator_lock.py tests/unit/test_dag_initializer.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add core/dag_orchestrator.py tests/unit/test_dag_orchestrator_lock.py
git commit -m "fix: replace session-level advisory locks with transaction-level — eliminates connection churn (COMPETE H1)"
```

---

## Verification

After all 5 tasks, run the full unit test suite:

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
/Users/robertharrison/anaconda3/envs/azgeo/bin/python -m pytest tests/unit/ -v
```

Then verify all edited files parse:

```bash
/Users/robertharrison/anaconda3/envs/azgeo/bin/python -c "
import ast
for f in ['core/dag_orchestrator.py', 'core/dag_fan_engine.py', 'core/dag_graph_utils.py', 'core/dag_transition_engine.py', 'docker_service.py']:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```
