# CoreMachine Adversarial Review — 5 Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 findings from the CoreMachine adversarial code review — 1 critical, 2 high, 2 medium.

**Architecture:** All fixes are surgical. Fix 1 adds orphan task cleanup. Fix 2 is mechanical find-and-replace. Fix 3 adds a re-check before raising. Fix 4 moves raw SQL into the repository. Fix 5 passes existing repos instead of creating new ones.

**Tech Stack:** Python 3.12, psycopg, pytest, unittest.mock

---

## Task 1: Mark orphaned tasks FAILED on Service Bus send failure (CRITICAL)

**Problem:** `_individual_queue_tasks()` creates a DB task record, then sends a Service Bus message. If the send fails, the orphan PENDING task blocks stage completion forever — `complete_task_and_check_stage` counts tasks `NOT IN ('completed', 'failed')`, so the orphan prevents the stage from ever completing.

**Files:**
- Modify: `core/machine.py:1619-1620` (per-task except block)
- Modify: `core/machine.py:~641` (caller checks `tasks_queued == 0`)
- Test: `tests/unit/test_orphan_task_cleanup.py`

**Step 1: Write failing tests**

```python
# tests/unit/test_orphan_task_cleanup.py
"""Tests for orphan task cleanup when Service Bus send fails."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from core.models.enums import TaskStatus


class TestOrphanTaskCleanup:
    """When Service Bus send fails after task DB insert, task must be marked FAILED."""

    @pytest.fixture
    def mock_task_repo(self):
        repo = MagicMock()
        repo.create_task.return_value = MagicMock()
        repo.fail_task.return_value = True
        return repo

    @pytest.fixture
    def mock_service_bus(self):
        sb = MagicMock()
        sb.send_message.side_effect = Exception("Service Bus unavailable")
        return sb

    @pytest.fixture
    def core_machine(self, mock_task_repo, mock_service_bus):
        from core.machine import CoreMachine
        cm = CoreMachine(
            all_jobs={},
            all_handlers={},
        )
        # Inject mocked repos
        cm._repos = {
            'task_repo': mock_task_repo,
            'job_repo': MagicMock(),
        }
        cm._service_bus_repo = mock_service_bus
        cm._event_repo = MagicMock()
        return cm

    def test_send_failure_marks_task_failed(self, core_machine, mock_task_repo):
        """Orphan task is marked FAILED when Service Bus send fails."""
        from core.models.results import TaskDefinition

        task_def = TaskDefinition(
            task_id="test-task-001",
            parent_job_id="a" * 64,
            job_type="test_job",
            task_type="test_handler",
            stage=1,
            task_index="0",
            parameters={}
        )

        result = core_machine._individual_queue_tasks(
            task_defs=[task_def],
            job_id="a" * 64,
            stage=1
        )

        # Task should be marked FAILED
        mock_task_repo.fail_task.assert_called_once()
        call_args = mock_task_repo.fail_task.call_args
        assert call_args[0][0] == "test-task-001"  # task_id
        assert "Service Bus" in call_args[0][1]  # error mentions SB

        # Result should show 0 queued, 1 failed
        assert result['tasks_queued'] == 0
        assert result['tasks_failed'] == 1

    def test_send_failure_all_tasks_returns_zero_queued(self, core_machine):
        """When all tasks fail to queue, tasks_queued is 0."""
        from core.models.results import TaskDefinition

        task_defs = [
            TaskDefinition(
                task_id=f"test-task-{i}",
                parent_job_id="a" * 64,
                job_type="test_job",
                task_type="test_handler",
                stage=1,
                task_index=str(i),
                parameters={}
            )
            for i in range(3)
        ]

        result = core_machine._individual_queue_tasks(
            task_defs=task_defs,
            job_id="a" * 64,
            stage=1
        )

        assert result['tasks_queued'] == 0
        assert result['tasks_failed'] == 3
```

**Step 2: Run tests to verify they fail**

Run: `conda run -n azgeo pytest tests/unit/test_orphan_task_cleanup.py -v`
Expected: Tests FAIL because `fail_task` is never called on the orphan task.

**Step 3: Implement orphan task cleanup**

In `core/machine.py`, modify the per-task except block at line 1619:

```python
    except Exception as e:
        tasks_failed += 1
        self.logger.error(f"❌ Failed to queue task {task_def.task_id}: {e}")
        # Mark orphan task as FAILED to prevent stage deadlock
        try:
            self.repos['task_repo'].fail_task(
                task_def.task_id,
                f"Service Bus send failed: {e}"
            )
            self.logger.warning(
                f"🧹 Marked orphan task {task_def.task_id} as FAILED",
                extra={
                    'checkpoint': 'ORPHAN_TASK_FAILED',
                    'task_id': task_def.task_id,
                    'error': str(e)
                }
            )
        except Exception as cleanup_err:
            self.logger.error(f"❌ Failed to cleanup orphan task {task_def.task_id}: {cleanup_err}")
```

**Step 4: Add zero-queued job failure in caller**

In `core/machine.py`, find the caller of `_individual_queue_tasks` (in `process_job_message`, around line 630-641). After the call returns, add a check:

Find the block that handles the queue result and add after it:

```python
        # If NO tasks were queued, fail the job immediately
        if queue_result.get('tasks_queued', 0) == 0 and queue_result.get('tasks_failed', 0) > 0:
            error_msg = f"All {queue_result['tasks_failed']} tasks failed to queue (Service Bus unavailable)"
            self._mark_job_failed(job_id, error_msg, job_type=job_message.job_type)
            return {
                'success': False,
                'error': error_msg,
                'job_id': job_id
            }
```

**Step 5: Run tests to verify they pass**

Run: `conda run -n azgeo pytest tests/unit/test_orphan_task_cleanup.py -v`
Expected: All tests PASS

**Step 6: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

---

## Task 2: Pass job_type to all 13 _mark_job_failed call sites (HIGH)

**Problem:** All 13 `_mark_job_failed()` calls omit the `job_type` parameter. The platform callback always receives `'unknown'`, so `release.processing_status` stays stuck at `'processing'` on failure.

**Files:**
- Modify: `core/machine.py` (13 call sites)
- Test: `tests/unit/test_mark_job_failed_job_type.py`

**Step 1: Write failing test**

```python
# tests/unit/test_mark_job_failed_job_type.py
"""Tests that _mark_job_failed always receives job_type."""
import pytest
from unittest.mock import MagicMock, patch, call


class TestMarkJobFailedJobType:
    """Every _mark_job_failed call must pass job_type to platform callback."""

    @pytest.fixture
    def callback_spy(self):
        return MagicMock()

    @pytest.fixture
    def core_machine(self, callback_spy):
        from core.machine import CoreMachine
        cm = CoreMachine(
            all_jobs={'test_job': MagicMock()},
            all_handlers={},
            on_job_complete=callback_spy,
        )
        mock_state_mgr = MagicMock()
        cm._state_manager = mock_state_mgr
        cm.state_manager = mock_state_mgr
        cm._repos = {
            'job_repo': MagicMock(),
            'task_repo': MagicMock(),
        }
        cm._event_repo = MagicMock()
        return cm

    def test_mark_job_failed_passes_job_type_to_callback(self, core_machine, callback_spy):
        """_mark_job_failed with job_type passes it to on_job_complete."""
        core_machine._mark_job_failed(
            "a" * 64,
            "test error",
            job_type="vector_docker_etl"
        )

        callback_spy.assert_called_once()
        kwargs = callback_spy.call_args
        # on_job_complete is called with keyword args
        assert kwargs[1]['job_type'] == 'vector_docker_etl'
        assert kwargs[1]['status'] == 'failed'

    def test_mark_job_failed_without_job_type_uses_unknown(self, core_machine, callback_spy):
        """_mark_job_failed without job_type falls back to 'unknown'."""
        core_machine._mark_job_failed(
            "a" * 64,
            "test error"
        )

        callback_spy.assert_called_once()
        kwargs = callback_spy.call_args
        assert kwargs[1]['job_type'] == 'unknown'
```

**Step 2: Run test to confirm it passes (baseline)**

Run: `conda run -n azgeo pytest tests/unit/test_mark_job_failed_job_type.py -v`
Expected: Both PASS (this tests the _mark_job_failed method itself, not the call sites)

**Step 3: Update all 13 call sites**

In `core/machine.py`, update each `_mark_job_failed` call to include `job_type`:

**Lines in `process_job_message()` — use `job_message.job_type`:**

Line 433:
```python
# BEFORE
self._mark_job_failed(job_message.job_id, error_msg)
# AFTER
self._mark_job_failed(job_message.job_id, error_msg, job_type=job_message.job_type)
```

Line 573:
```python
# BEFORE
self._mark_job_failed(job_id, error_msg)
# AFTER
self._mark_job_failed(job_id, error_msg, job_type=job_message.job_type)
```

Line 601:
```python
# BEFORE
self._mark_job_failed(job_id, f"Task dict missing required field: {e}")
# AFTER
self._mark_job_failed(job_id, f"Task dict missing required field: {e}", job_type=job_message.job_type)
```

Line 606:
```python
# BEFORE
self._mark_job_failed(job_id, f"Invalid task definition: {e}")
# AFTER
self._mark_job_failed(job_id, f"Invalid task definition: {e}", job_type=job_message.job_type)
```

Line 641:
```python
# BEFORE
self._mark_job_failed(job_id, error_msg)
# AFTER
self._mark_job_failed(job_id, error_msg, job_type=job_message.job_type)
```

**Line 732 in `process_stage_complete()` — use `job_type` local variable (line 679):**

```python
# BEFORE
self._mark_job_failed(
    job_id,
    f"Stage complete processing failed: {e}"
)
# AFTER
self._mark_job_failed(
    job_id,
    f"Stage complete processing failed: {e}",
    job_type=job_type
)
```

**Lines in `process_task_message()` — use `task_message.job_type`:**

Lines 864, 899, 1192, 1252, 1296, 1383, 1527 — all follow the same pattern:

```python
# BEFORE
self._mark_job_failed(
    task_message.parent_job_id,
    error_msg
)
# AFTER
self._mark_job_failed(
    task_message.parent_job_id,
    error_msg,
    job_type=task_message.job_type
)
```

**Step 4: Verify no call sites remain without job_type**

Run: `grep -n '_mark_job_failed(' core/machine.py | grep -v 'job_type='`

Expected: Only the method definition line (no call sites without `job_type=`).

**Step 5: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

---

## Task 3: Fix TOCTOU race in complete_task_with_sql (HIGH)

**Problem:** Two duplicate task messages both pass the Python-level status check (`task.status == PROCESSING`). The first SQL `UPDATE` succeeds. The second returns `task_updated=False`. Line 633 raises `RuntimeError("SQL function failed to update task")`. This propagates to `process_task_message`, which calls `_mark_job_failed` — potentially failing a job that already completed successfully.

**Files:**
- Modify: `core/state_manager.py:627-634` (the `task_updated=False` handling)
- Test: `tests/unit/test_toctou_race.py`

**Step 1: Write failing test**

```python
# tests/unit/test_toctou_race.py
"""Tests for TOCTOU race handling in complete_task_with_sql."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from core.models.enums import TaskStatus
from core.models.results import TaskCompletionResult


class TestTOCTOURaceHandling:
    """When task_updated=False, re-check task status before raising."""

    @pytest.fixture
    def mock_task_repo(self):
        repo = MagicMock()
        return repo

    @pytest.fixture
    def state_manager(self, mock_task_repo):
        from core.state_manager import StateManager
        sm = StateManager.__new__(StateManager)
        sm._repos = {'task_repo': mock_task_repo}
        sm.repos = {'task_repo': mock_task_repo}
        sm.logger = MagicMock()
        return sm

    def test_task_updated_false_completed_task_no_exception(self, state_manager, mock_task_repo):
        """If task_updated=False but task is COMPLETED, return gracefully (duplicate message)."""
        # Simulate: SQL function returns task_updated=False
        mock_completion = TaskCompletionResult(
            task_updated=False,
            stage_complete=False,
            remaining_tasks=0
        )

        # Task is already COMPLETED (another message got there first)
        mock_task = MagicMock()
        mock_task.status = TaskStatus.COMPLETED
        mock_task_repo.get_task.return_value = mock_task

        # Mock the stage completion repo
        with patch('core.state_manager.StageCompletionRepository') as MockSCR:
            mock_scr_instance = MagicMock()
            mock_scr_instance.complete_task_and_check_stage.return_value = mock_completion
            MockSCR.return_value = mock_scr_instance

            # Should NOT raise — task was already completed by duplicate
            result = state_manager.complete_task_with_sql(
                task_id="test-task",
                job_id="a" * 64,
                stage=1,
                task_result=MagicMock(success=True, result_data={}, error_details=None)
            )

            assert result.task_updated is False
            assert result.stage_complete is False

    def test_task_updated_false_unknown_status_raises(self, state_manager, mock_task_repo):
        """If task_updated=False and task is in unexpected state, raise RuntimeError."""
        mock_completion = TaskCompletionResult(
            task_updated=False,
            stage_complete=False,
            remaining_tasks=0
        )

        # Task is PENDING (unexpected — not completed/failed)
        mock_task = MagicMock()
        mock_task.status = TaskStatus.PENDING
        mock_task_repo.get_task.return_value = mock_task

        with patch('core.state_manager.StageCompletionRepository') as MockSCR:
            mock_scr_instance = MagicMock()
            mock_scr_instance.complete_task_and_check_stage.return_value = mock_completion
            MockSCR.return_value = mock_scr_instance

            with pytest.raises(RuntimeError, match="SQL function failed"):
                state_manager.complete_task_with_sql(
                    task_id="test-task",
                    job_id="a" * 64,
                    stage=1,
                    task_result=MagicMock(success=True, result_data={}, error_details=None)
                )
```

**Step 2: Run test to verify it fails**

Run: `conda run -n azgeo pytest tests/unit/test_toctou_race.py -v`
Expected: `test_task_updated_false_completed_task_no_exception` FAILS (currently raises RuntimeError)

**Step 3: Implement re-check before raising**

In `core/state_manager.py`, replace the block at lines 633-634:

```python
        # BEFORE
        if not stage_completion.task_updated:
            raise RuntimeError(f"SQL function failed to update task {task_id}")

        # AFTER
        if not stage_completion.task_updated:
            # Re-check: task may have been completed by a duplicate message (TOCTOU race)
            current = self.repos['task_repo'].get_task(task_id)
            if current and current.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                self.logger.info(
                    f"⚡ Duplicate message detected for task {task_id} "
                    f"(already {current.status.value}). Ignoring.",
                    extra={
                        'checkpoint': 'DUPLICATE_TASK_MESSAGE',
                        'task_id': task_id,
                        'current_status': current.status.value
                    }
                )
                return TaskCompletionResult(
                    task_updated=False,
                    stage_complete=False,
                    remaining_tasks=stage_completion.remaining_tasks
                )
            raise RuntimeError(f"SQL function failed to update task {task_id}")
```

**Step 4: Run test to verify it passes**

Run: `conda run -n azgeo pytest tests/unit/test_toctou_race.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

---

## Task 4: Move fail_all_job_tasks to TaskRepository (MEDIUM)

**Problem:** `StateManager.fail_all_job_tasks()` bypasses the repository pattern with raw SQL and a hardcoded `"app"` schema. If the schema name changes, this function silently targets wrong tables.

**Files:**
- Modify: `infrastructure/jobs_tasks.py` (add `fail_tasks_for_job()` method to `TaskRepository`)
- Modify: `core/state_manager.py:838-898` (delegate to repository)
- Test: `tests/unit/test_fail_all_tasks.py`

**Step 1: Write test for new repository method**

```python
# tests/unit/test_fail_all_tasks.py
"""Tests for TaskRepository.fail_tasks_for_job."""
import pytest
from unittest.mock import MagicMock, patch


class TestFailTasksForJob:
    """fail_tasks_for_job marks non-terminal tasks as FAILED."""

    def test_method_exists_on_task_repository(self):
        """TaskRepository must have fail_tasks_for_job method."""
        from infrastructure.jobs_tasks import TaskRepository
        assert hasattr(TaskRepository, 'fail_tasks_for_job')

    def test_fail_tasks_uses_schema_name(self):
        """fail_tasks_for_job must use self.schema_name, not hardcoded 'app'."""
        from infrastructure.jobs_tasks import TaskRepository
        import inspect
        source = inspect.getsource(TaskRepository.fail_tasks_for_job)
        assert 'self.schema_name' in source or 'schema_name' in source
        assert '"app"' not in source  # No hardcoded schema

    def test_state_manager_delegates_to_repo(self):
        """StateManager.fail_all_job_tasks delegates to task_repo."""
        from core.state_manager import StateManager
        import inspect
        source = inspect.getsource(StateManager.fail_all_job_tasks)
        assert 'fail_tasks_for_job' in source
```

**Step 2: Run test to verify it fails**

Run: `conda run -n azgeo pytest tests/unit/test_fail_all_tasks.py -v`
Expected: FAIL — method doesn't exist yet

**Step 3: Add `fail_tasks_for_job` to TaskRepository**

In `infrastructure/jobs_tasks.py`, add after the `fail_task` method (after line 887):

```python
    def fail_tasks_for_job(self, job_id: str, error_msg: str) -> int:
        """
        Mark all non-terminal tasks for a job as FAILED.

        Used when a job is being failed and sibling tasks must be cleaned up
        to prevent orphans blocking stage completion.

        Args:
            job_id: Parent job identifier
            error_msg: Error message to set on failed tasks

        Returns:
            Number of tasks marked as failed
        """
        from psycopg import sql

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {schema}.tasks
                        SET status = 'failed',
                            error_details = %s,
                            updated_at = NOW()
                        WHERE parent_job_id = %s
                          AND status NOT IN ('completed', 'failed')
                        RETURNING task_id
                    """).format(schema=sql.Identifier(self.schema_name)),
                    (error_msg, job_id)
                )
                failed_tasks = cur.fetchall()
                conn.commit()

                return len(failed_tasks)
```

**Step 4: Update StateManager to delegate**

In `core/state_manager.py`, replace the `fail_all_job_tasks` method body (lines 838-898):

```python
    def fail_all_job_tasks(
        self,
        job_id: str,
        error_msg: str
    ) -> int:
        """
        Mark all non-terminal tasks for a job as FAILED.

        GAP-004 FIX (15 DEC 2025): When a job is marked failed, sibling tasks
        in PROCESSING or QUEUED state should also be failed to prevent orphan
        tasks and wasted compute.

        Safe method that won't raise exceptions.

        Args:
            job_id: Job identifier
            error_msg: Error message to set on all failed tasks

        Returns:
            Number of tasks marked as failed
        """
        try:
            failed_count = self.repos['task_repo'].fail_tasks_for_job(job_id, error_msg)

            if failed_count > 0:
                self.logger.warning(
                    f"GAP-004: Marked {failed_count} orphan tasks as FAILED for job {job_id[:16]}...",
                    extra={
                        'checkpoint': 'STATE_ORPHAN_TASKS_FAILED',
                        'job_id': job_id,
                        'failed_count': failed_count,
                    }
                )
            return failed_count

        except Exception as e:
            self.logger.error(
                f"Failed to fail orphan tasks for job {job_id[:16]}...: {e}",
                extra={
                    'checkpoint': 'STATE_FAIL_ORPHAN_TASKS_ERROR',
                    'error_source': 'state',
                    'job_id': job_id,
                }
            )
            return 0
```

**Step 5: Run tests**

Run: `conda run -n azgeo pytest tests/unit/test_fail_all_tasks.py -v`
Expected: All PASS

**Step 6: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

---

## Task 5: Share repos with _confirm_task_queued (MEDIUM)

**Problem:** `_confirm_task_queued()` in `task_handler.py` creates a fresh `RepositoryFactory.create_repositories()` on every task message. Under load, this multiplies DB connections.

**Files:**
- Modify: `triggers/service_bus/task_handler.py:156-199` (accept `task_repo` parameter)
- Modify: `triggers/service_bus/task_handler.py` (the caller, pass `core_machine.repos['task_repo']`)
- Test: `tests/unit/test_confirm_task_queued.py`

**Step 1: Write test**

```python
# tests/unit/test_confirm_task_queued.py
"""Tests for _confirm_task_queued repo sharing."""
import pytest
from unittest.mock import MagicMock, patch
import inspect


class TestConfirmTaskQueuedRepoSharing:
    """_confirm_task_queued should accept a task_repo parameter."""

    def test_accepts_task_repo_parameter(self):
        """Function signature includes task_repo parameter."""
        from triggers.service_bus.task_handler import _confirm_task_queued
        sig = inspect.signature(_confirm_task_queued)
        assert 'task_repo' in sig.parameters

    def test_does_not_create_repositories_when_repo_provided(self):
        """When task_repo is provided, RepositoryFactory is NOT called."""
        from triggers.service_bus.task_handler import _confirm_task_queued

        mock_repo = MagicMock()
        mock_repo.update_task_status_with_validation.return_value = True

        with patch('triggers.service_bus.task_handler.RepositoryFactory') as MockRF:
            _confirm_task_queued(
                task_id="test-task",
                correlation_id="test-corr",
                queue_name="test-queue",
                task_repo=mock_repo
            )

            # RepositoryFactory should NOT be called
            MockRF.create_repositories.assert_not_called()

            # Provided repo should be used
            mock_repo.update_task_status_with_validation.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `conda run -n azgeo pytest tests/unit/test_confirm_task_queued.py -v`
Expected: FAIL — `task_repo` parameter doesn't exist yet

**Step 3: Update `_confirm_task_queued` to accept optional task_repo**

In `triggers/service_bus/task_handler.py`, modify the function signature and body (lines 156-199):

```python
def _confirm_task_queued(
    task_id: str,
    correlation_id: str,
    queue_name: str,
    task_repo=None
) -> None:
    """
    Update task status from PENDING to QUEUED.

    Args:
        task_id: Task ID to update
        correlation_id: Correlation ID for logging
        queue_name: Queue name for logging
        task_repo: Optional TaskRepository instance. If provided, skips
                   RepositoryFactory.create_repositories() to reduce DB connections.
    """
    try:
        if task_repo is None:
            repos = RepositoryFactory.create_repositories()
            task_repo = repos['task_repo']

        success = task_repo.update_task_status_with_validation(
            task_id,
            TaskStatus.QUEUED
        )

        if success:
            logger.info(
                f"[{correlation_id}] PENDING -> QUEUED confirmed for {task_id[:16]}...",
                extra={
                    'checkpoint': 'PENDING_TO_QUEUED',
                    'task_id': task_id,
                    'queue': queue_name
                }
            )
        else:
            current = task_repo.get_task_status(task_id)
            logger.warning(
                f"[{correlation_id}] PENDING -> QUEUED update returned False. "
                f"Current status: {current}. Continuing (janitor will recover if needed)."
            )

    except Exception as status_error:
        logger.error(f"[{correlation_id}] Failed PENDING -> QUEUED update: {status_error}")
```

**Step 4: Update the caller to pass task_repo**

In the same file, find where `_confirm_task_queued` is called (in `process_task_queue_message` or similar). Add `task_repo=core_machine.repos['task_repo']`:

Search for `_confirm_task_queued(` call site and add the parameter:

```python
# BEFORE
_confirm_task_queued(
    task_id=task_message.task_id,
    correlation_id=correlation_id,
    queue_name=queue_name
)

# AFTER
_confirm_task_queued(
    task_id=task_message.task_id,
    correlation_id=correlation_id,
    queue_name=queue_name,
    task_repo=core_machine.repos['task_repo']
)
```

**Step 5: Run tests**

Run: `conda run -n azgeo pytest tests/unit/test_confirm_task_queued.py -v`
Expected: All PASS

**Step 6: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: No regressions

---

## Execution Order

Tasks are independent — can be done in any order or in parallel.

| Task | Finding | Effort | Risk |
|------|---------|--------|------|
| 1 | CRITICAL: Orphan PENDING task cleanup | S-M | Low |
| 2 | HIGH: Pass job_type to _mark_job_failed | S (mechanical) | Near zero |
| 3 | HIGH: TOCTOU race in complete_task_with_sql | S | Low |
| 4 | MEDIUM: Move fail_all_job_tasks to repo | M | Low-Medium |
| 5 | MEDIUM: Share repos with _confirm_task_queued | S | Low |
| **Total** | | **~90 min** | |
