"""Tests for GuardianRepository."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestGuardianRepository:
    """Unit tests for GuardianRepository with mocked _execute_query."""

    @pytest.fixture
    def repo(self):
        """Create a GuardianRepository with mocked DB internals."""
        with patch(
            'infrastructure.guardian_repository.PostgreSQLRepository.__init__',
            return_value=None
        ):
            from infrastructure.guardian_repository import GuardianRepository
            r = GuardianRepository()
            r.schema_name = "app"
            r._execute_query = MagicMock()
            r._error_context = MagicMock()
            # Make _error_context work as a context manager
            r._error_context.return_value.__enter__ = MagicMock()
            r._error_context.return_value.__exit__ = MagicMock(return_value=False)
            return r

    # ================================================================
    # schema_ready
    # ================================================================

    def test_schema_ready_true(self, repo):
        """schema_ready returns True when jobs table exists."""
        repo._execute_query.return_value = {'?column?': 1}
        assert repo.schema_ready() is True

    def test_schema_ready_false(self, repo):
        """schema_ready returns False when jobs table missing."""
        repo._execute_query.return_value = None
        assert repo.schema_ready() is False

    def test_schema_ready_handles_exception(self, repo):
        """schema_ready returns False on DB error."""
        repo._error_context.return_value.__enter__.side_effect = RuntimeError("DB down")
        assert repo.schema_ready() is False

    # ================================================================
    # mark_tasks_failed
    # ================================================================

    def test_mark_tasks_failed_empty_list(self, repo):
        """mark_tasks_failed returns 0 for empty task_ids."""
        result = repo.mark_tasks_failed([], "test error")
        assert result == 0
        repo._execute_query.assert_not_called()

    def test_mark_tasks_failed_returns_count(self, repo):
        """mark_tasks_failed returns count of updated rows."""
        repo._execute_query.return_value = [
            {'task_id': 'task-1'},
            {'task_id': 'task-2'},
            {'task_id': 'task-3'},
        ]
        result = repo.mark_tasks_failed(
            ['task-1', 'task-2', 'task-3'],
            "Guardian: stale processing"
        )
        assert result == 3

    def test_mark_tasks_failed_single_task(self, repo):
        """mark_tasks_failed works for a single task."""
        repo._execute_query.return_value = [{'task_id': 'task-1'}]
        result = repo.mark_tasks_failed(['task-1'], "timeout")
        assert result == 1

    def test_mark_tasks_failed_none_result(self, repo):
        """mark_tasks_failed returns 0 when query returns None."""
        repo._execute_query.return_value = None
        result = repo.mark_tasks_failed(['task-1'], "error")
        assert result == 0

    # ================================================================
    # mark_job_failed
    # ================================================================

    def test_mark_job_failed_success(self, repo):
        """mark_job_failed returns True on success."""
        repo._execute_query.return_value = {'job_id': 'job-1'}
        result = repo.mark_job_failed('job-1', "Guardian: ancient stale")
        assert result is True

    def test_mark_job_failed_not_found(self, repo):
        """mark_job_failed returns False when job not found."""
        repo._execute_query.return_value = None
        result = repo.mark_job_failed('nonexistent', "error")
        assert result is False

    def test_mark_job_failed_with_partial_results(self, repo):
        """mark_job_failed accepts partial_results dict."""
        repo._execute_query.return_value = {'job_id': 'job-1'}
        result = repo.mark_job_failed(
            'job-1', "partial failure",
            partial_results={"stage_1": "completed"}
        )
        assert result is True

    # ================================================================
    # increment_task_retry
    # ================================================================

    def test_increment_task_retry_returns_new_count(self, repo):
        """increment_task_retry returns new retry_count."""
        repo._execute_query.return_value = {'retry_count': 3}
        result = repo.increment_task_retry('task-1')
        assert result == 3

    def test_increment_task_retry_not_found(self, repo):
        """increment_task_retry returns -1 when task not found."""
        repo._execute_query.return_value = None
        result = repo.increment_task_retry('nonexistent')
        assert result == -1

    # ================================================================
    # Detection queries return empty lists
    # ================================================================

    def test_get_orphaned_pending_tasks_empty(self, repo):
        """Returns empty list when no orphaned pending tasks."""
        repo._execute_query.return_value = None
        result = repo.get_orphaned_pending_tasks()
        assert result == []

    def test_get_zombie_stages_empty(self, repo):
        """Returns empty list when no zombie stages."""
        repo._execute_query.return_value = None
        result = repo.get_zombie_stages()
        assert result == []

    def test_get_orphaned_tasks_empty(self, repo):
        """Returns empty list when no orphaned tasks."""
        repo._execute_query.return_value = None
        result = repo.get_orphaned_tasks()
        assert result == []

    def test_get_jobs_with_failed_tasks_empty(self, repo):
        """Returns empty list when no jobs with failed tasks."""
        repo._execute_query.return_value = None
        result = repo.get_jobs_with_failed_tasks()
        assert result == []

    # ================================================================
    # Audit logging (non-fatal)
    # ================================================================

    def test_log_sweep_start_success(self, repo):
        """log_sweep_start returns sweep_id on success."""
        from datetime import datetime, timezone
        repo._execute_query.return_value = {'run_id': 'sweep-123'}
        result = repo.log_sweep_start('sweep-123', datetime.now(timezone.utc))
        assert result == 'sweep-123'

    def test_log_sweep_start_failure_returns_none(self, repo):
        """log_sweep_start returns None on DB error."""
        from datetime import datetime, timezone
        repo._error_context.return_value.__enter__.side_effect = RuntimeError("DB error")
        result = repo.log_sweep_start('sweep-123', datetime.now(timezone.utc))
        assert result is None

    def test_log_sweep_end_success(self, repo):
        """log_sweep_end returns True on success."""
        from datetime import datetime, timezone
        repo._execute_query.return_value = {'run_id': 'sweep-123'}
        result = repo.log_sweep_end(
            sweep_id='sweep-123',
            completed_at=datetime.now(timezone.utc),
            items_scanned=50,
            items_fixed=3,
            actions_taken=[{"action": "mark_failed"}],
            phases={"phase_1": {"scanned": 20}},
            status='completed'
        )
        assert result is True

    def test_log_sweep_end_failure_returns_false(self, repo):
        """log_sweep_end returns False on DB error."""
        from datetime import datetime, timezone
        repo._error_context.return_value.__enter__.side_effect = RuntimeError("DB error")
        result = repo.log_sweep_end(
            sweep_id='sweep-123',
            completed_at=datetime.now(timezone.utc),
            items_scanned=0,
            items_fixed=0,
            actions_taken=[],
            phases=None,
            status='failed',
            error_details='boom'
        )
        assert result is False
