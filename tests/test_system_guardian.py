"""Tests for SystemGuardian service."""
import os
import pytest
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch, call


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_repo():
    """Create a mock GuardianRepository with all detection methods returning empty."""
    repo = MagicMock()
    repo.schema_ready.return_value = True
    repo.log_sweep_start.return_value = "sweep-id"
    repo.log_sweep_end.return_value = True

    # Phase 1: Task recovery - default empty
    repo.get_orphaned_pending_tasks.return_value = []
    repo.get_orphaned_queued_tasks.return_value = []
    repo.get_stale_processing_tasks.return_value = []
    repo.get_stale_docker_tasks.return_value = []

    # Phase 2: Stage recovery
    repo.get_zombie_stages.return_value = []

    # Phase 3: Job recovery
    repo.get_jobs_with_failed_tasks.return_value = []
    repo.get_stuck_queued_jobs.return_value = []
    repo.get_ancient_stale_jobs.return_value = []
    repo.get_completed_task_results.return_value = []

    # Phase 4: Consistency
    repo.get_orphaned_tasks.return_value = []

    # Fix operations
    repo.mark_tasks_failed.return_value = 1
    repo.mark_job_failed.return_value = True
    repo.increment_task_retry.return_value = 1

    return repo


@pytest.fixture
def mock_queue():
    """Create a mock ServiceBusRepository."""
    queue = MagicMock()
    queue.send_message.return_value = "msg-id"
    queue.message_exists_for_task.return_value = False
    return queue


@pytest.fixture
def guardian(mock_repo, mock_queue):
    """Create a SystemGuardian with mocked dependencies."""
    from services.system_guardian import SystemGuardian
    return SystemGuardian(repo=mock_repo, queue_client=mock_queue)


# ============================================================================
# GuardianConfig Tests
# ============================================================================

class TestGuardianConfig:
    """Tests for GuardianConfig dataclass."""

    def test_defaults(self):
        """GuardianConfig has correct default values."""
        from services.system_guardian import GuardianConfig
        config = GuardianConfig()
        assert config.sweep_interval_minutes == 5
        assert config.pending_task_timeout_minutes == 2
        assert config.queued_task_timeout_minutes == 5
        assert config.processing_task_timeout_minutes == 30
        assert config.docker_task_timeout_minutes == 180
        assert config.stuck_queued_job_timeout_minutes == 10
        assert config.ancient_job_timeout_minutes == 360
        assert config.max_task_retries == 3
        assert config.enabled is True

    def test_frozen(self):
        """GuardianConfig is immutable (frozen dataclass)."""
        from services.system_guardian import GuardianConfig
        config = GuardianConfig()
        with pytest.raises(FrozenInstanceError):
            config.enabled = False

    def test_from_environment_defaults(self):
        """from_environment returns defaults when no env vars set."""
        from services.system_guardian import GuardianConfig
        with patch.dict(os.environ, {}, clear=False):
            # Remove any GUARDIAN_ vars that might be set
            env_copy = {
                k: v for k, v in os.environ.items()
                if not k.startswith('GUARDIAN_')
            }
            with patch.dict(os.environ, env_copy, clear=True):
                config = GuardianConfig.from_environment()
                assert config.sweep_interval_minutes == 5
                assert config.enabled is True

    def test_from_environment_overrides(self):
        """from_environment reads GUARDIAN_* env vars."""
        from services.system_guardian import GuardianConfig
        env_vars = {
            'GUARDIAN_SWEEP_INTERVAL_MINUTES': '10',
            'GUARDIAN_PENDING_TASK_TIMEOUT_MINUTES': '5',
            'GUARDIAN_MAX_TASK_RETRIES': '5',
            'GUARDIAN_ENABLED': 'false',
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = GuardianConfig.from_environment()
            assert config.sweep_interval_minutes == 10
            assert config.pending_task_timeout_minutes == 5
            assert config.max_task_retries == 5
            assert config.enabled is False


# ============================================================================
# Clean Sweep Tests
# ============================================================================

class TestCleanSweep:
    """Tests for clean sweep with no anomalies."""

    def test_clean_sweep_all_phases_run(self, guardian, mock_repo):
        """Clean sweep runs all 4 phases and returns correct result."""
        result = guardian.sweep()

        assert result.success is True
        assert result.total_scanned == 0
        assert result.total_fixed == 0
        assert result.completed_at is not None
        assert len(result.phases) == 4
        assert 'task_recovery' in result.phases
        assert 'stage_recovery' in result.phases
        assert 'job_recovery' in result.phases
        assert 'consistency' in result.phases

    def test_clean_sweep_all_detection_queries_called(self, guardian, mock_repo):
        """Clean sweep calls all detection queries."""
        guardian.sweep()

        # Phase 1
        mock_repo.get_orphaned_pending_tasks.assert_called_once()
        mock_repo.get_orphaned_queued_tasks.assert_called_once()
        mock_repo.get_stale_processing_tasks.assert_called_once()
        mock_repo.get_stale_docker_tasks.assert_called_once()

        # Phase 2
        mock_repo.get_zombie_stages.assert_called_once()

        # Phase 3
        mock_repo.get_jobs_with_failed_tasks.assert_called_once()
        mock_repo.get_stuck_queued_jobs.assert_called_once()
        mock_repo.get_ancient_stale_jobs.assert_called_once()

        # Phase 4
        mock_repo.get_orphaned_tasks.assert_called_once()

    def test_clean_sweep_two_phase_audit(self, guardian, mock_repo):
        """Clean sweep calls log_sweep_start and log_sweep_end."""
        result = guardian.sweep()

        mock_repo.log_sweep_start.assert_called_once_with(
            result.sweep_id, result.started_at
        )
        mock_repo.log_sweep_end.assert_called_once()

        # Verify log_sweep_end args
        end_call = mock_repo.log_sweep_end.call_args
        assert end_call.kwargs['sweep_id'] == result.sweep_id
        assert end_call.kwargs['items_scanned'] == 0
        assert end_call.kwargs['items_fixed'] == 0
        assert end_call.kwargs['status'] == 'completed'


# ============================================================================
# Skip Conditions Tests
# ============================================================================

class TestSkipConditions:
    """Tests for conditions that skip the sweep."""

    def test_schema_not_ready_skips_sweep(self, mock_repo, mock_queue):
        """Schema not ready returns early without running queries."""
        from services.system_guardian import SystemGuardian
        mock_repo.schema_ready.return_value = False

        guardian = SystemGuardian(repo=mock_repo, queue_client=mock_queue)
        result = guardian.sweep()

        assert result.success is False
        assert result.error == "schema_not_ready"
        assert len(result.phases) == 0

        # No detection queries should be called
        mock_repo.get_orphaned_pending_tasks.assert_not_called()
        mock_repo.get_zombie_stages.assert_not_called()
        mock_repo.get_jobs_with_failed_tasks.assert_not_called()
        mock_repo.get_orphaned_tasks.assert_not_called()

    def test_disabled_config_skips_sweep(self, mock_repo, mock_queue):
        """Disabled config skips sweep entirely."""
        from services.system_guardian import SystemGuardian, GuardianConfig
        config = GuardianConfig(enabled=False)

        guardian = SystemGuardian(
            repo=mock_repo, queue_client=mock_queue, config=config
        )
        result = guardian.sweep()

        assert result.success is False
        assert result.error == "disabled"
        assert len(result.phases) == 0

        # No queries called
        mock_repo.schema_ready.assert_not_called()
        mock_repo.get_orphaned_pending_tasks.assert_not_called()


# ============================================================================
# Fail-Open Tests
# ============================================================================

class TestFailOpen:
    """Tests for fail-open behaviour across phases."""

    def test_phase1_error_does_not_block_phase2(self, mock_repo, mock_queue):
        """Phase 1 exception does not prevent Phase 2+ from running."""
        from services.system_guardian import SystemGuardian

        # Phase 1 blows up
        mock_repo.get_orphaned_pending_tasks.side_effect = RuntimeError("DB timeout")

        guardian = SystemGuardian(repo=mock_repo, queue_client=mock_queue)
        result = guardian.sweep()

        # Phase 1 has error
        assert result.phases['task_recovery'].error == "DB timeout"

        # Phase 2-4 still ran
        mock_repo.get_zombie_stages.assert_called_once()
        mock_repo.get_jobs_with_failed_tasks.assert_called_once()
        mock_repo.get_orphaned_tasks.assert_called_once()

        # Other phases have no error
        assert result.phases['stage_recovery'].error is None
        assert result.phases['job_recovery'].error is None
        assert result.phases['consistency'].error is None

    def test_phase2_error_does_not_block_phase3(self, mock_repo, mock_queue):
        """Phase 2 exception does not prevent Phase 3+ from running."""
        from services.system_guardian import SystemGuardian

        mock_repo.get_zombie_stages.side_effect = RuntimeError("stage query failed")

        guardian = SystemGuardian(repo=mock_repo, queue_client=mock_queue)
        result = guardian.sweep()

        assert result.phases['stage_recovery'].error == "stage query failed"
        mock_repo.get_jobs_with_failed_tasks.assert_called_once()
        mock_repo.get_orphaned_tasks.assert_called_once()

    def test_partial_success_reflected_in_result(self, mock_repo, mock_queue):
        """When one phase fails, success is False but others still reported."""
        from services.system_guardian import SystemGuardian

        mock_repo.get_orphaned_pending_tasks.side_effect = RuntimeError("boom")

        guardian = SystemGuardian(repo=mock_repo, queue_client=mock_queue)
        result = guardian.sweep()

        assert result.success is False
        assert result.completed_at is not None


# ============================================================================
# Phase Behaviour Tests
# ============================================================================

class TestTaskRecovery:
    """Tests for Phase 1: Task Recovery."""

    def test_orphaned_pending_task_resent(self, guardian, mock_repo, mock_queue):
        """Orphaned PENDING task is re-sent to queue."""
        mock_repo.get_orphaned_pending_tasks.return_value = [{
            'task_id': 'task-001',
            'parent_job_id': 'job-001',
            'job_type': 'hello_world',
            'task_type': 'hello_world_greeting',
            'stage': 1,
            'task_index': '0',
            'parameters': {'message': 'test'},
            'retry_count': 0,
        }]

        result = guardian.sweep()

        mock_repo.increment_task_retry.assert_called_with('task-001')
        mock_queue.send_message.assert_called_once()
        assert result.phases['task_recovery'].fixed == 1

    def test_orphaned_pending_max_retries_fails(self, guardian, mock_repo, mock_queue):
        """Orphaned PENDING task at max retries is marked FAILED."""
        mock_repo.get_orphaned_pending_tasks.return_value = [{
            'task_id': 'task-002',
            'parent_job_id': 'job-002',
            'job_type': 'hello_world',
            'task_type': 'hello_world_greeting',
            'stage': 1,
            'task_index': '0',
            'parameters': {},
            'retry_count': 3,
        }]

        result = guardian.sweep()

        mock_repo.mark_tasks_failed.assert_called()
        mock_queue.send_message.assert_not_called()
        assert result.phases['task_recovery'].fixed == 1

    def test_queued_task_skipped_if_message_exists(self, guardian, mock_repo, mock_queue):
        """QUEUED task with existing queue message is skipped."""
        mock_repo.get_orphaned_queued_tasks.return_value = [{
            'task_id': 'task-003',
            'parent_job_id': 'job-003',
            'job_type': 'hello_world',
            'task_type': 'hello_world_greeting',
            'stage': 1,
            'task_index': '0',
            'parameters': {},
            'retry_count': 0,
        }]
        mock_queue.message_exists_for_task.return_value = True

        result = guardian.sweep()

        mock_queue.send_message.assert_not_called()
        mock_repo.mark_tasks_failed.assert_not_called()
        assert result.phases['task_recovery'].fixed == 0

    def test_stale_processing_no_pulse_requeued(self, guardian, mock_repo, mock_queue):
        """Stale PROCESSING task with no pulse is re-queued."""
        mock_repo.get_stale_processing_tasks.return_value = [{
            'task_id': 'task-004',
            'parent_job_id': 'job-004',
            'job_type': 'hello_world',
            'task_type': 'hello_world_greeting',
            'stage': 1,
            'task_index': '0',
            'parameters': {},
            'retry_count': 0,
            'last_pulse': None,
        }]

        result = guardian.sweep()

        mock_repo.increment_task_retry.assert_called_with('task-004')
        mock_queue.send_message.assert_called_once()

    def test_stale_processing_with_pulse_failed(self, guardian, mock_repo, mock_queue):
        """Stale PROCESSING task with pulse is marked FAILED (ran and died)."""
        from datetime import datetime, timezone
        mock_repo.get_stale_processing_tasks.return_value = [{
            'task_id': 'task-005',
            'parent_job_id': 'job-005',
            'job_type': 'hello_world',
            'task_type': 'hello_world_greeting',
            'stage': 1,
            'task_index': '0',
            'parameters': {},
            'retry_count': 0,
            'last_pulse': datetime.now(timezone.utc),
        }]

        result = guardian.sweep()

        mock_repo.mark_tasks_failed.assert_called()
        assert result.phases['task_recovery'].fixed == 1

    def test_docker_task_stale_marked_failed(self, guardian, mock_repo, mock_queue):
        """Stale Docker task is marked FAILED directly (no retry)."""
        mock_repo.get_stale_docker_tasks.return_value = [{
            'task_id': 'task-006',
            'parent_job_id': 'job-006',
            'job_type': 'vector_docker_etl',
            'task_type': 'vector_docker_complete',
            'stage': 1,
            'task_index': '0',
            'parameters': {},
            'retry_count': 0,
        }]

        result = guardian.sweep()

        mock_repo.mark_tasks_failed.assert_called_once()
        assert 'docker_task_failed' in result.phases['task_recovery'].actions[0]


class TestStageRecovery:
    """Tests for Phase 2: Stage Recovery."""

    def test_zombie_stage_with_failures_marks_job_failed(
        self, guardian, mock_repo, mock_queue
    ):
        """Zombie stage with failed tasks marks job FAILED."""
        mock_repo.get_zombie_stages.return_value = [{
            'job_id': 'job-010',
            'job_type': 'hello_world',
            'stage': 1,
            'total_stages': 2,
            'status': 'processing',
            'failed_tasks': 2,
            'completed_tasks': 1,
        }]

        result = guardian.sweep()

        mock_repo.mark_job_failed.assert_called_once()
        assert result.phases['stage_recovery'].fixed == 1

    def test_zombie_stage_all_completed_sends_stage_complete(
        self, guardian, mock_repo, mock_queue
    ):
        """Zombie stage with all completed tasks re-sends StageCompleteMessage."""
        mock_repo.get_zombie_stages.return_value = [{
            'job_id': 'job-011',
            'job_type': 'hello_world',
            'stage': 1,
            'total_stages': 2,
            'status': 'processing',
            'failed_tasks': 0,
            'completed_tasks': 3,
        }]

        result = guardian.sweep()

        mock_queue.send_message.assert_called_once()
        # Verify it sent a StageCompleteMessage, not a TaskQueueMessage
        sent_msg = mock_queue.send_message.call_args[0][1]
        from core.schema.queue import StageCompleteMessage
        assert isinstance(sent_msg, StageCompleteMessage)
        assert sent_msg.completed_by_app == "system_guardian"
        assert result.phases['stage_recovery'].fixed == 1


class TestJobRecovery:
    """Tests for Phase 3: Job Recovery."""

    def test_job_with_failed_tasks_marked_failed(
        self, guardian, mock_repo, mock_queue
    ):
        """Job with failed tasks (no active tasks) is marked FAILED."""
        mock_repo.get_jobs_with_failed_tasks.return_value = [{
            'job_id': 'job-020',
            'job_type': 'hello_world',
            'stage': 1,
            'total_stages': 2,
            'status': 'processing',
            'failed_count': 1,
            'completed_count': 2,
            'processing_count': 0,
            'queued_count': 0,
        }]

        result = guardian.sweep()

        mock_repo.mark_job_failed.assert_called_once()
        assert result.phases['job_recovery'].fixed == 1

    def test_job_with_active_tasks_skipped(self, guardian, mock_repo, mock_queue):
        """Job with failed tasks but still-active tasks is skipped."""
        mock_repo.get_jobs_with_failed_tasks.return_value = [{
            'job_id': 'job-021',
            'job_type': 'hello_world',
            'stage': 1,
            'total_stages': 2,
            'status': 'processing',
            'failed_count': 1,
            'processing_count': 2,
            'queued_count': 0,
        }]

        result = guardian.sweep()

        mock_repo.mark_job_failed.assert_not_called()

    def test_stuck_queued_job_marked_failed(self, guardian, mock_repo, mock_queue):
        """Stuck QUEUED job is marked FAILED."""
        mock_repo.get_stuck_queued_jobs.return_value = [{
            'job_id': 'job-022',
            'job_type': 'hello_world',
            'stage': 1,
            'status': 'queued',
        }]

        result = guardian.sweep()

        mock_repo.mark_job_failed.assert_called_once()
        assert result.phases['job_recovery'].fixed == 1

    def test_ancient_stale_job_marked_failed(self, guardian, mock_repo, mock_queue):
        """Ancient stale job is marked FAILED with partial results."""
        mock_repo.get_ancient_stale_jobs.return_value = [{
            'job_id': 'job-023',
            'job_type': 'hello_world',
            'stage': 2,
            'total_stages': 3,
            'status': 'processing',
        }]

        result = guardian.sweep()

        mock_repo.mark_job_failed.assert_called_once()
        assert result.phases['job_recovery'].fixed == 1


class TestConsistency:
    """Tests for Phase 4: Consistency."""

    def test_orphaned_tasks_marked_failed(self, guardian, mock_repo, mock_queue):
        """Orphaned tasks (no parent job) are marked FAILED."""
        mock_repo.get_orphaned_tasks.return_value = [
            {'task_id': 'orphan-1', 'parent_job_id': 'missing-job'},
            {'task_id': 'orphan-2', 'parent_job_id': 'missing-job'},
        ]

        result = guardian.sweep()

        mock_repo.mark_tasks_failed.assert_called_once_with(
            ['orphan-1', 'orphan-2'],
            "guardian_consistency: parent_job_missing"
        )
        assert result.phases['consistency'].fixed == 2


# ============================================================================
# SweepResult / PhaseResult Tests
# ============================================================================

class TestSweepResult:
    """Tests for SweepResult dataclass."""

    def test_all_actions_aggregates(self):
        """all_actions property returns flat list from all phases."""
        from services.system_guardian import SweepResult, PhaseResult
        result = SweepResult()
        result.phases['p1'] = PhaseResult(phase='p1', actions=['a1', 'a2'])
        result.phases['p2'] = PhaseResult(phase='p2', actions=['a3'])

        assert result.all_actions == ['a1', 'a2', 'a3']

    def test_phases_dict_serializable(self):
        """phases_dict returns a plain dict suitable for JSON."""
        from services.system_guardian import SweepResult, PhaseResult
        result = SweepResult()
        result.phases['p1'] = PhaseResult(
            phase='p1', scanned=5, fixed=2,
            actions=['a1'], error=None
        )

        d = result.phases_dict
        assert d == {
            'p1': {
                'scanned': 5,
                'fixed': 2,
                'actions': ['a1'],
                'error': None,
            }
        }

    def test_complete_calculates_totals(self):
        """complete() sets totals and success flag."""
        from services.system_guardian import SweepResult, PhaseResult
        result = SweepResult()
        result.phases['p1'] = PhaseResult(phase='p1', scanned=10, fixed=3)
        result.phases['p2'] = PhaseResult(phase='p2', scanned=5, fixed=1)

        result.complete()

        assert result.total_scanned == 15
        assert result.total_fixed == 4
        assert result.success is True
        assert result.completed_at is not None

    def test_complete_with_error_phase(self):
        """complete() sets success=False when any phase has error."""
        from services.system_guardian import SweepResult, PhaseResult
        result = SweepResult()
        result.phases['p1'] = PhaseResult(phase='p1', error="boom")
        result.phases['p2'] = PhaseResult(phase='p2')

        result.complete()

        assert result.success is False
